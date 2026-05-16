# face_features — derive expression metrics from 68-point landmarks
# Output: face{i}/{valid,smile,mouth_open,blink_left,blink_right,brow_raise}
# Reads facetrack ops. When facetrack invalid, channels are 0.
import math

SOURCES = [
    ('face1', '/project1/facetrack1'),
    ('face2', '/project1/facetrack2'),
]

# Tuning constants — adjust if features feel too sensitive/insensitive
EAR_OPEN_REF = 0.30        # EAR for a fully open eye (closed -> ~0.10)
MOUTH_OPEN_GAIN = 2.0      # multiplier into 0-1
SMILE_GAIN = 2.0           # smaller gain so frowns aren't crushed by smile saturation
BROW_BIAS = 0.20
BROW_GAIN = 3.0


def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def onCook(scriptOp):
    scriptOp.clear()
    for name, path in SOURCES:
        ft = op(path)
        if ft is None:
            continue
        valid_ch = ft['face1:valid']
        valid = valid_ch.eval() if valid_ch is not None else 0.0
        valid = 1.0 if valid >= 0.5 else 0.0

        def pt(i, axis):
            ch = ft['face1/pt{}:{}'.format(i, axis)]
            return ch.eval() if ch is not None else 0.0

        def d(i, j):
            return math.hypot(pt(i, 'u') - pt(j, 'u'), pt(i, 'v') - pt(j, 'v'))

        smile = mouth_open = blink_left = blink_right = brow_raise = 0.0
        eye_left_x = eye_left_y = eye_right_x = eye_right_y = 0.0
        if valid:
            # Eye Aspect Ratio per eye (ibug: 37-42 right eye, 43-48 left eye, from subject POV)
            ear_r = (d(38, 42) + d(39, 41)) / (2 * d(37, 40) + 1e-6)
            ear_l = (d(44, 48) + d(45, 47)) / (2 * d(43, 46) + 1e-6)
            # blink_left from viewer = subject's right eye = pts 37-42
            blink_left = clamp01(1.0 - ear_r / EAR_OPEN_REF)
            blink_right = clamp01(1.0 - ear_l / EAR_OPEN_REF)

            mouth_w = d(49, 55) + 1e-6
            inner_h = (d(63, 67) + d(62, 68) + d(64, 66)) / 3.0
            mouth_open = clamp01(inner_h / mouth_w * MOUTH_OPEN_GAIN)

            # Smile vs frown: mouth corners (49, 55) relative to upper-lip mid (52) and lower-lip mid (58)
            corner_v = 0.5 * (pt(49, 'v') + pt(55, 'v'))
            center_v = 0.5 * (pt(52, 'v') + pt(58, 'v'))
            smile_raw = (corner_v - center_v) / mouth_w * SMILE_GAIN
            # Map -1..+1 to 0..1 so consumers can threshold easily
            smile = clamp01((smile_raw + 1.0) * 0.5)

            # Inter-pupillary-ish distance for normalization (inner-eye-corner of each eye)
            ipd = d(40, 43) + 1e-6
            brow_mid_v = 0.5 * (pt(22, 'v') + pt(23, 'v'))   # inner brow points
            eye_mid_v = 0.5 * (pt(40, 'v') + pt(43, 'v'))
            brow_raise = clamp01(((brow_mid_v - eye_mid_v) / ipd - BROW_BIAS) * BROW_GAIN)

            # Eye centroids — track to measure eye-region movement (not blinking).
            # Subject's right eye = pts 37-42 (viewer left), left eye = pts 43-48 (viewer right).
            eye_right_x = sum(pt(i, 'u') for i in range(37, 43)) / 6.0
            eye_right_y = sum(pt(i, 'v') for i in range(37, 43)) / 6.0
            eye_left_x  = sum(pt(i, 'u') for i in range(43, 49)) / 6.0
            eye_left_y  = sum(pt(i, 'v') for i in range(43, 49)) / 6.0

        for ch_name, val in (
            ('valid', valid),
            ('smile', smile),
            ('mouth_open', mouth_open),
            ('blink_left', blink_left),
            ('blink_right', blink_right),
            ('brow_raise', brow_raise),
            ('eye_left_x', eye_left_x),
            ('eye_left_y', eye_left_y),
            ('eye_right_x', eye_right_x),
            ('eye_right_y', eye_right_y),
        ):
            c = scriptOp.appendChan('{}/{}'.format(name, ch_name))
            c[0] = val
    return
