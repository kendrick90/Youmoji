# face_count — how many usable players are in frame.
#
# Reads /project1/face_select (which has already scored + filtered YOLO
# detections by center+size+stickiness). Reports:
#   n_faces   — capped at 2 for the current 2-pipeline setup (mouth swap)
#   n_active  — raw count of viable detections from face_select
#   primary_tracked   — 1 if facetrack1 has locked landmarks on primary face
#   secondary_tracked — 1 if facetrack2 has locked landmarks on secondary
#
# Routing / state transitions use n_faces. Scoring / face_features use the
# tracked flags to know if landmark-based features are reliable.

def onCook(scriptOp):
    scriptOp.clear()
    fs = op('/project1/face_select')
    n_active = int(fs['n_active'].eval()) if fs else 0
    p_id = fs['primary_id'].eval() if fs else -1.0
    s_id = fs['secondary_id'].eval() if fs else -1.0
    has_distinct_secondary = 1 if (s_id != -1.0 and s_id != p_id) else 0

    def _ft_valid(path):
        ft = op(path)
        if ft is None:
            return 0
        v = ft['face1:valid']
        return 1 if (v is not None and v.eval() > 0.5) else 0

    p_tracked = _ft_valid('/project1/facetrack1')
    s_tracked = _ft_valid('/project1/facetrack2')

    # n_faces counts only tracked players — landmarks must be locked.
    # YOLO false-positives (posters, background) won't promote past attract mode.
    n_faces = p_tracked + (s_tracked if has_distinct_secondary else 0)

    for name, val in (
        ('n_faces',           n_faces),
        ('n_active',          n_active),   # raw YOLO count
        ('primary_tracked',   p_tracked),
        ('secondary_tracked', s_tracked),
    ):
        c = scriptOp.appendChan(name)
        c[0] = val
