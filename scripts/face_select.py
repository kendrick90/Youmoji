# face_select — pick primary/secondary YOLO detections with hysteresis.
#
# Reads /project1/faces (id, x, y, width, height per sample).
# Outputs: primary_idx, secondary_idx, primary_id, secondary_id, n_active
#
# Scoring: SIZE_WEIGHT * area + CENTER_WEIGHT * (1 - distance_from_center).
# Stickiness: if a previously-selected id is still in view and scores at least
# STICKY_THRESHOLD * top_score, keep it. Prevents an active player from being
# bumped by a small/distant face passing through.

SIZE_WEIGHT = 0.7
CENTER_WEIGHT = 0.3
STICKY_THRESHOLD = 0.70
MIN_WIDTH = 0.04          # discard YOLO detections smaller than this fraction


def onCook(scriptOp):
    scriptOp.clear()

    faces = op('/project1/faces')
    n_in = faces.numSamples if faces else 0

    # Live threshold from face_thresh (fallback to MIN_WIDTH default)
    th = op('/project1/face_thresh')
    min_w = th['min_width'].eval() if th else MIN_WIDTH
    viable = []  # list of (idx, id, x, y, w, h)
    for i in range(n_in):
        w = faces['width'][i]
        if w < min_w:
            continue
        viable.append((i, faces['id'][i], faces['x'][i], faces['y'][i], w, faces['height'][i]))

    def score(rec):
        _, _, x, y, w, h = rec
        area = w * h
        dx = x - 0.5
        dy = y - 0.5
        dist = (dx * dx + dy * dy) ** 0.5
        center_score = max(0.0, 1.0 - dist / 0.7)
        return SIZE_WEIGHT * area * 4.0 + CENTER_WEIGHT * center_score

    primary_idx = 0
    secondary_idx = 0
    primary_id = -1.0
    secondary_id = -1.0

    if viable:
        scored = sorted([(score(rec), rec) for rec in viable], reverse=True, key=lambda t: t[0])
        top_score, top_rec = scored[0]
        primary_rec = top_rec

        # Stickiness for primary (state lives on parent COMP to avoid a
        # self-cook-loop on scriptOp's own storage)
        store = parent()
        prev_primary_id = store.fetch('face_select_prev_primary_id', -1.0)
        if prev_primary_id != -1.0:
            for s, rec in scored:
                if rec[1] == prev_primary_id and s >= top_score * STICKY_THRESHOLD:
                    primary_rec = rec
                    break

        # Pick secondary from remaining
        rest = [t for t in scored if t[1][0] != primary_rec[0]]
        if rest:
            sec_top_score, sec_top_rec = rest[0]
            secondary_rec = sec_top_rec
            prev_secondary_id = store.fetch('face_select_prev_secondary_id', -1.0)
            if prev_secondary_id != -1.0 and prev_secondary_id != primary_rec[1]:
                for s, rec in rest:
                    if rec[1] == prev_secondary_id and s >= sec_top_score * STICKY_THRESHOLD:
                        secondary_rec = rec
                        break
            secondary_idx = secondary_rec[0]
            secondary_id = secondary_rec[1]
        else:
            secondary_idx = primary_rec[0]
            secondary_id = -1.0

        primary_idx = primary_rec[0]
        primary_id = primary_rec[1]

    store = parent()
    store.store('face_select_prev_primary_id', primary_id)
    store.store('face_select_prev_secondary_id', secondary_id)

    out = (
        ('primary_idx', primary_idx),
        ('secondary_idx', secondary_idx),
        ('primary_id', primary_id),
        ('secondary_id', secondary_id),
        ('n_active', len(viable)),
    )
    for name, val in out:
        c = scriptOp.appendChan(name)
        c[0] = float(val)
    return
