import time
import os

PARTS = ('left_eye', 'right_eye', 'mouth')
LENGTH_SEC = 10
SAFETY_BUFFER_SEC = 1
STOP_DELAY_MS = (LENGTH_SEC + SAFETY_BUFFER_SEC) * 1000
WATCH_INTERVAL_MS = 100
FILE_RELEASE_DELAY_MS = 1500
FACE_VALID_OP = '/project1/face_count'
FACE_VALID_CHAN = 'n_faces'


def _stop_recorders():
    for part in PARTS:
        rec = parent().op('record_' + part)
        if rec:
            rec.par.record = 0


def _clear_state():
    parent().store('capture_state', {'token': None, 'paths': []})


def capture(length_sec=None):
    state = parent().fetch('capture_state', {'token': None, 'paths': []})
    if state.get('token') is not None:
        print('[library_capture] Capture already in progress, ignoring')
        return []
    if length_sec is None:
        length_sec = LENGTH_SEC
    stop_delay_ms = int((length_sec + SAFETY_BUFFER_SEC) * 1000)
    ts = int(time.time() * 1000)
    library_dir = project.folder + '/library'
    started = []
    for part in PARTS:
        rec = parent().op('record_' + part)
        if rec is None:
            continue
        target_dir = library_dir + '/' + part
        os.makedirs(target_dir, exist_ok=True)
        path = target_dir + '/' + str(ts) + '.mp4'
        # Force off->on transition every press so a stuck toggle re-triggers
        rec.par.record = 0
        rec.par.file = path
        rec.par.record = 1
        started.append(path)
    counter = parent().op('count')
    if counter:
        counter.par.value0 = counter.par.value0.eval() + 1
    parent().store('capture_state', {'token': ts, 'paths': started})
    # Auto-stop fires regardless of face state
    run("op('/project1/library_capture/save_capture').module.stop_recording(" + str(ts) + ")",
        delayMilliSeconds=stop_delay_ms)
    # Face watchdog — re-arms itself until capture ends
    run("op('/project1/library_capture/save_capture').module.watch_face(" + str(ts) + ")",
        delayMilliSeconds=WATCH_INTERVAL_MS)
    print('[library_capture] Started capture ts=' + str(ts) + ', auto-stop in ' + str(stop_delay_ms/1000) + 's')
    return started


def stop_recording(token=None):
    state = parent().fetch('capture_state', {'token': None, 'paths': []})
    if token is not None and state.get('token') != token:
        # A newer capture (or an abort) already took over — leave it alone
        return
    _stop_recorders()
    _clear_state()
    print('[library_capture] Auto-reset record=0')


def abort_recording(token):
    state = parent().fetch('capture_state', {'token': None, 'paths': []})
    if state.get('token') != token:
        return
    _stop_recorders()
    paths = list(state.get('paths', []))
    _clear_state()
    print('[library_capture] Face lost — aborting capture, will delete ' + str(len(paths)) + ' file(s)')
    # Defer deletion so the moviefileout encoder can close the files
    run("op('/project1/library_capture/save_capture').module._delete_files(" + repr(paths) + ")",
        delayMilliSeconds=FILE_RELEASE_DELAY_MS)


def _delete_files(paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
                print('[library_capture] Deleted incomplete file: ' + p)
        except Exception as e:
            print('[library_capture] Failed to delete ' + p + ': ' + str(e))


def watch_face(token):
    state = parent().fetch('capture_state', {'token': None, 'paths': []})
    if state.get('token') != token:
        return  # capture already ended (auto-stop, abort, or superseded)
    try:
        valid = op(FACE_VALID_OP)[FACE_VALID_CHAN].eval()
    except Exception as e:
        print('[library_capture] watch_face read failed: ' + str(e))
        valid = 1.0
    if valid < 0.5:
        abort_recording(token)
        return
    run("op('/project1/library_capture/save_capture').module.watch_face(" + str(token) + ")",
        delayMilliSeconds=WATCH_INTERVAL_MS)
