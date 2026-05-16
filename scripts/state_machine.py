# Game state machine.
# States: attract -> ready -> playing -> scoring -> attract
#
# attract:  library clips rotating; waits for face to enter frame.
# ready:    face detected long enough; live preview + "hold mouth open" prompt.
# playing:  capture running, expression scoring over ROUND_LENGTH_SEC.
# scoring:  show final score for SCORING_HOLD_SEC, then loop back to attract.
# Captures are kept automatically when a round completes; save_capture's
# face-loss watchdog still deletes partial clips if the player walks away mid-round.

import time
import os
import json
import random

HIGH_SCORE_FILE = 'high_score.json'

ROUND_LENGTH_SEC = 30
SCORING_HOLD_SEC = 5
DETECT_DEBOUNCE_SEC = 1.0        # need face for this long before promoting attract -> ready
READY_TIMEOUT_SEC = 30           # if no one starts, fall back to attract
FACE_LOST_GRACE_SEC = 2.0        # tolerate brief face loss during ready / playing
ATTRACT_ROTATE_SEC = 4.0
FEATURE_CHANS = ('smile', 'mouth_open', 'blink_left', 'blink_right', 'brow_raise')

# Edge thresholds for counting discrete blinks (debounced)
BLINK_HI = 0.30
BLINK_LO = 0.15

# Edge thresholds for counting discrete mouth-open events
MOUTH_OPEN_HI = 0.45
MOUTH_OPEN_LO = 0.20

# Start-the-round gesture — hold mouth open
READY_MOUTH_THRESH   = 0.45
READY_MOUTH_HOLD_SEC = 3.0


# --- helpers --------------------------------------------------------------

def current_state():
    return op('current').text.strip()


def state_age():
    return time.time() - parent().fetch('state_entered_at', time.time())


def _round_total():
    """Sum of the three slot counts — what the player accumulated this round."""
    comp = parent()
    return (comp.fetch('blink_left_count', 0) +
            comp.fetch('blink_right_count', 0) +
            comp.fetch('mouth_open_count', 0))


def _display_points(raw):
    return int(round(raw))


# --- high score persistence ----------------------------------------------

def _high_score_path():
    return project.folder + '/scripts/' + HIGH_SCORE_FILE


def _load_high_score():
    try:
        with open(_high_score_path(), 'r') as f:
            return float(json.load(f).get('high_score', 0.0))
    except Exception:
        return 0.0


def _save_high_score(v):
    try:
        with open(_high_score_path(), 'w') as f:
            json.dump({'high_score': float(v)}, f)
    except Exception as e:
        print('[state] save high score failed: ' + str(e))


def reset_high_score():
    _save_high_score(0.0)
    parent().store('high_score', 0.0)
    parent().store('new_high', False)
    print('[state] high score reset to 0')


def _library_dir():
    return project.folder + '/library'


def _list_clips(part):
    d = _library_dir() + '/' + part
    if not os.path.isdir(d):
        return []
    return sorted([f for f in os.listdir(d) if f.endswith('.mp4')])


def rotate_attract_clips():
    """Pick a matched left/right eye pair + a different mouth, write to library_pool/pick_*."""
    base = _library_dir()
    eyes = _list_clips('left_eye')
    if not eyes:
        return
    eye_choice = random.choice(eyes)
    mouths = _list_clips('mouth')
    pool = [m for m in mouths if m != eye_choice] or mouths
    if not pool:
        return
    mouth_choice = random.choice(pool)
    le = op('/project1/library_pool/pick_left_eye')
    re = op('/project1/library_pool/pick_right_eye')
    mo = op('/project1/library_pool/pick_mouth')
    if le: le.par.file = base + '/left_eye/' + eye_choice
    if re: re.par.file = base + '/right_eye/' + eye_choice
    if mo: mo.par.file = base + '/mouth/' + mouth_choice


def overlay_text():
    """Top-of-screen banner text per state."""
    if _collab_on():
        return ''
    s = current_state()
    comp = parent()
    high = _display_points(comp.fetch('high_score', _load_high_score()))
    if s == 'attract':
        return 'High score: ' + str(high)
    if s == 'ready':
        held = comp.fetch('ready_mouth_started', 0.0)
        if held > 0:
            remaining = max(0.0, READY_MOUTH_HOLD_SEC - (time.time() - held))
            return 'Hold mouth open... ' + str(round(remaining, 1))
        return 'Hold mouth open to play\nHigh: ' + str(high)
    if s == 'playing':
        remaining = max(0, int(ROUND_LENGTH_SEC - state_age()))
        return str(remaining) + '   running: ' + str(_display_points(_round_total()))
    if s == 'scoring':
        total = comp.fetch('score_total', 0.0)
        line1 = 'You got ' + str(_display_points(total)) + ' points!'
        if comp.fetch('new_high', False):
            line2 = 'NEW HIGH SCORE!'
        else:
            line2 = 'High: ' + str(high)
        return line1 + '\n' + line2
    return ''


_SCORE_VISIBLE_STATES = ('playing', 'scoring')


def slot_text_left_eye():
    """Left-eye slot: blink count this round."""
    if current_state() not in _SCORE_VISIBLE_STATES:
        return ''
    return str(int(parent().fetch('blink_left_count', 0)))


def slot_text_right_eye():
    if current_state() not in _SCORE_VISIBLE_STATES:
        return ''
    return str(int(parent().fetch('blink_right_count', 0)))


def slot_text_mouth():
    """Mouth slot: count of times the mouth opened past MOUTH_OPEN_HI this round."""
    if current_state() not in _SCORE_VISIBLE_STATES:
        return ''
    return str(int(parent().fetch('mouth_open_count', 0)))


def _collab_on():
    p = parent().par.Collabmode if hasattr(parent().par, 'Collabmode') else None
    return bool(p.eval()) if p is not None else False


def output_mode():
    """Switch index for live eye/mouth slots: 0=attract clip, 1=live face1."""
    if _collab_on():
        fc = op('/project1/face_count')
        n = fc['n_faces'].eval() if fc else 0
        return 1 if n >= 1 else 0
    if current_state() in ('ready', 'playing'):
        return 1
    return 0


def mouth_mode():
    """0=attract, 1=face1 mouth, 2=face2 mouth (collab swap when 2 faces detected)."""
    om = output_mode()
    if om == 0:
        return 0
    fc = op('/project1/face_count')
    n = fc['n_faces'].eval() if fc else 0
    if _collab_on() and n >= 2:
        return 2
    return 1


def _push_all_text():
    """Write every state-driven text TOP. Called every tick."""
    pairs = (
        ('/project1/state_text',               overlay_text()),
        ('/project1/attract_face/score_left',  slot_text_left_eye()),
        ('/project1/attract_face/score_right', slot_text_right_eye()),
        ('/project1/attract_face/score_mouth', slot_text_mouth()),
    )
    for path, txt in pairs:
        t = op(path)
        if t is not None:
            t.par.text = txt


# --- entry hooks ----------------------------------------------------------

def enter(new_state):
    comp = parent()
    op('current').text = new_state
    comp.store('state_entered_at', time.time())
    print('[state] -> ' + new_state)
    if new_state == 'attract':
        comp.store('peaks', {})
        comp.store('round_paths', [])
        comp.store('detect_seen_at', 0.0)
        comp.store('last_rotate', 0.0)
        comp.store('face_lost_at', 0.0)
        comp.store('new_high', False)
        if comp.fetch('high_score', None) is None:
            comp.store('high_score', _load_high_score())
        rotate_attract_clips()
    elif new_state == 'ready':
        comp.store('face_lost_at', 0.0)
        comp.store('ready_mouth_started', 0.0)
    elif new_state == 'playing':
        comp.store('peaks', {ch: 0.0 for ch in FEATURE_CHANS})
        comp.store('face_lost_at', 0.0)
        comp.store('blink_left_count', 0)
        comp.store('blink_right_count', 0)
        comp.store('mouth_open_count', 0)
        comp.store('blink_left_high', False)
        comp.store('blink_right_high', False)
        comp.store('mouth_open_high', False)
        try:
            paths = op('/project1/library_capture/save_capture').module.capture(length_sec=ROUND_LENGTH_SEC)
            comp.store('round_paths', paths or [])
        except Exception as e:
            print('[state] capture start failed: ' + str(e))
    elif new_state == 'scoring':
        total = _round_total()
        comp.store('score_total', total)
        prev_high = comp.fetch('high_score', _load_high_score())
        new_high = total > prev_high
        if new_high:
            _save_high_score(total)
            comp.store('high_score', total)
        comp.store('new_high', new_high)
        paths = comp.fetch('round_paths', [])
        print('[state] score = ' + str(_display_points(total)) +
              ' (high ' + str(_display_points(comp.fetch('high_score', 0.0))) + ')' +
              ', kept ' + str(len(paths)) + ' clip(s)' +
              ('  NEW HIGH!' if new_high else ''))


# --- per-tick handlers ----------------------------------------------------

def tick_attract():
    comp = parent()
    now = time.time()
    last_rot = comp.fetch('last_rotate', 0.0)
    if now - last_rot >= ATTRACT_ROTATE_SEC:
        rotate_attract_clips()
        comp.store('last_rotate', now)
    fc_op = op('/project1/face_count')
    n = fc_op['n_faces'].eval() if fc_op else 0
    if n >= 1:
        seen_at = comp.fetch('detect_seen_at', 0.0)
        if seen_at == 0:
            comp.store('detect_seen_at', now)
        elif now - seen_at >= DETECT_DEBOUNCE_SEC:
            enter('ready')
    else:
        comp.store('detect_seen_at', 0.0)


def tick_ready():
    comp = parent()
    now = time.time()
    fc_op = op('/project1/face_count')
    n = fc_op['n_faces'].eval() if fc_op else 0
    if n < 1:
        lost_at = comp.fetch('face_lost_at', 0.0)
        if lost_at == 0:
            comp.store('face_lost_at', now)
        elif now - lost_at >= FACE_LOST_GRACE_SEC:
            print('[state] face left during ready, back to attract')
            enter('attract')
            return
    else:
        comp.store('face_lost_at', 0.0)

    # Hold mouth open to start the round
    feat = op('/project1/face_features')
    mouth_open = feat['face1/mouth_open'].eval() if feat and feat['face1/mouth_open'] else 0.0
    valid = feat['face1/valid'].eval() if feat and feat['face1/valid'] else 0
    mouth_started = comp.fetch('ready_mouth_started', 0.0)
    if valid and mouth_open >= READY_MOUTH_THRESH:
        if mouth_started == 0:
            comp.store('ready_mouth_started', now)
        elif now - mouth_started >= READY_MOUTH_HOLD_SEC:
            enter('playing')
            return
    else:
        if mouth_started != 0:
            comp.store('ready_mouth_started', 0.0)

    if state_age() >= READY_TIMEOUT_SEC:
        print('[state] ready timed out, back to attract')
        enter('attract')


def tick_playing():
    comp = parent()
    feat = op('/project1/face_features')
    peaks = comp.fetch('peaks', {})
    bl_count = comp.fetch('blink_left_count', 0)
    br_count = comp.fetch('blink_right_count', 0)
    mo_count = comp.fetch('mouth_open_count', 0)
    bl_high  = comp.fetch('blink_left_high', False)
    br_high  = comp.fetch('blink_right_high', False)
    mo_high  = comp.fetch('mouth_open_high', False)

    if feat:
        valid_c = feat['face1/valid']
        if valid_c is not None and valid_c.eval() >= 0.5:
            for ch in FEATURE_CHANS:
                v = feat['face1/' + ch]
                if v is None:
                    continue
                cur = v.eval()
                if cur > peaks.get(ch, 0.0):
                    peaks[ch] = cur

            bl_v = feat['face1/blink_left'].eval()  if feat['face1/blink_left']  else 0.0
            br_v = feat['face1/blink_right'].eval() if feat['face1/blink_right'] else 0.0
            mo_v = feat['face1/mouth_open'].eval()  if feat['face1/mouth_open']  else 0.0

            # Debounced edge counters
            if bl_v >= BLINK_HI and not bl_high:
                bl_count += 1; bl_high = True
            elif bl_v <= BLINK_LO:
                bl_high = False
            if br_v >= BLINK_HI and not br_high:
                br_count += 1; br_high = True
            elif br_v <= BLINK_LO:
                br_high = False
            if mo_v >= MOUTH_OPEN_HI and not mo_high:
                mo_count += 1; mo_high = True
            elif mo_v <= MOUTH_OPEN_LO:
                mo_high = False

    comp.store('peaks', peaks)
    comp.store('blink_left_count', bl_count)
    comp.store('blink_right_count', br_count)
    comp.store('mouth_open_count', mo_count)
    comp.store('blink_left_high', bl_high)
    comp.store('blink_right_high', br_high)
    comp.store('mouth_open_high', mo_high)

    now = time.time()
    fc_op = op('/project1/face_count')
    n = fc_op['n_faces'].eval() if fc_op else 0
    if n < 1:
        lost_at = comp.fetch('face_lost_at', 0.0)
        if lost_at == 0:
            comp.store('face_lost_at', now)
        elif now - lost_at >= FACE_LOST_GRACE_SEC:
            print('[state] face lost during playing, aborting round')
            enter('attract')
            return
    else:
        comp.store('face_lost_at', 0.0)

    if state_age() >= ROUND_LENGTH_SEC:
        enter('scoring')


def tick_scoring():
    # Captures are kept automatically (no contribute prompt). Loop back to attract.
    if state_age() >= SCORING_HOLD_SEC:
        enter('attract')


# --- master tick + key handler -------------------------------------------

def tick():
    # Collab mode bypasses the whole state machine — no scoring, no transitions,
    # just rotate attract clips so the no-face case still has something on screen.
    if _collab_on():
        comp = parent()
        now = time.time()
        last_rot = comp.fetch('last_rotate', 0.0)
        if now - last_rot >= ATTRACT_ROTATE_SEC:
            rotate_attract_clips()
            comp.store('last_rotate', now)
        _push_all_text()
        return

    s = current_state()
    if s == 'attract':   tick_attract()
    elif s == 'ready':   tick_ready()
    elif s == 'playing': tick_playing()
    elif s == 'scoring': tick_scoring()
    else:
        print('[state] unknown state: ' + s + ' - resetting to attract')
        enter('attract')
    _push_all_text()


def on_key():
    """Legacy keyboard start trigger — still works as a debug shortcut."""
    if current_state() == 'ready':
        enter('playing')


def force(new_state):
    enter(new_state)
