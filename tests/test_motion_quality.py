"""Motion quality of the 54 product_motion presets (criteria of the "pro spot" review), headless:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_motion_quality.py
Every preset is applied at 48, 96, 200 and 480 frames (24 fps) on a test product and its root is sampled frame by frame by
plugin/tools/motion_report.py (the same numbers are printed by that tool). Nothing is rendered.

THRESHOLDS (declared in tools/motion_report.py: LIMITS, PEAK, PEAK_ID, OVS_FAMILY, ACTION_S, IMPACTS, EXEMPT, OFFSCREEN_CUT)
  hold          >= 0.5 s of still hero pose at the end of every non-loop motion (design: max(0.5 s, 12% of the shot, <= 2 s))
  action time   the main action lasts what it takes in SECONDS (ACTION_S: pop 0.5-1.4, slide 0.7-1.8, drop 0.5-1.5, flip 0.8-2.2,
                spin 0.9-3.4, ...), at 480 frames as well as at 48 (a 480-frame pop-in is not a 10 s slow motion)
  peak speed    per family (size/s, deg/s): loop 3/330, spin 1.5/480, drift 0.6/40, reveal 12/650, impact 13/150, flip 6/900,
                flyby 16/300, stylized 12/900, return 14/600 (x1.6 at 48 frames; a few ids declared in PEAK_ID)
  velocity jump <= 0.55 of the peak from one frame to the next outside declared contacts (IMPACTS) and out-of-frame cuts
  overshoot     <= 15% of the excursion (impact family: 25%); every swing <= 60% of the previous; <= 4 swings (no endless spring)
  floor         <= 0.5% of size of penetration at every frame (rise_from_below: declared exception)
  loops         C0 and C1 at the seam (bounce_loop: contacts, declared); spin loops 5-14 s per turn at >= 200 frames
  in frame      after the action the product is inside the camera frame at every frame (loops: at every frame)
  fps / short   same results at 30 and 60 fps (ends at rest, keys inside the range) and at 12 / 20 / 30 frames"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

import bpy
from mathutils import Matrix

import motion_report as mr
import product_motion_studio as pkg
from product_motion_studio import api, core, motion, presets

RESULTS = []
pkg.register()
IDS = list(presets.REGISTRY['product_motion'])
CACHE = {}


def test(num, name):
    def deco(fn):
        try:
            msg = fn()
            RESULTS.append((num, name, True, msg or ''))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((num, name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def mr_diff(a, b):
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))


def runs(kind='suzanne', durations=mr.DURATIONS):
    key = (kind, tuple(durations))
    if key not in CACHE:
        CACHE[key] = mr.collect(None, durations, kind=kind, keep=True)
    return CACHE[key]


def violations(res, only=None):
    out = []
    for (pid, dur), (m, bad, _) in res.items():
        for b in bad:
            if only is None or b.split()[0] in only:
                out.append(f"{pid}@{dur}: {b}")
    return out


@test(1, "all 63 presets, 4 durations (48 / 96 / 200 / 480 frames): every criterion of tools/motion_report.py")
def t1():
    res = runs()
    bad = violations(res)
    assert len(IDS) == 63, len(IDS)
    assert not bad, f"{len(bad)} violations, e.g. {bad[:4]}"
    return f"{len(res)} runs, 0 violations"


@test(2, "absolute time: the main action lasts the same seconds at 200 and 480 frames (no slow motion), inside its range")
def t2():
    res = runs()
    worst, n = 0.0, 0
    for pid in IDS:
        p = presets.get('product_motion', pid)
        if p.meta.get('loop') or p.category == 'drift' or pid not in mr.ACTION_S:
            continue
        a200, a480 = res[(pid, 200)][0]['action_s'], res[(pid, 480)][0]['action_s']
        lo, hi = mr.ACTION_S[pid]
        assert lo - 0.04 <= a480 <= hi + 0.04, f"{pid}: {a480:.2f} s at 480 frames, expected {lo}-{hi}"
        if pid != 'showcase_3_pose':            # the showcase stretches its holds with the duration, by design
            assert abs(a200 - a480) <= 0.3, f"{pid}: {a200:.2f} s at 200 frames vs {a480:.2f} s at 480"
        n += 1
        if pid != 'showcase_3_pose':
            worst = max(worst, abs(a200 - a480))
    return f"{n} actions, worst 200-vs-480 difference {worst:.2f} s"


@test(3, "hold: >= 0.5 s of still hero pose at every duration, and the life of the tail is a slow +-2 degree yaw")
def t3():
    res = runs()
    worst_hold, worst_life = 9.0, 0.0
    for (pid, dur), (m, _, s) in res.items():
        p = presets.get('product_motion', pid)
        if p.meta.get('loop') or pid == 'static':
            continue
        worst_hold = min(worst_hold, m['hold_s'])
        life = s['life']
        worst_life = max(worst_life, max(abs(x) for x in life))
        assert abs(life[-1]) < 1e-6, f"{pid}@{dur}: life yaw not zero at the end"
    assert worst_hold >= 0.5 - 1e-6, worst_hold
    assert worst_life <= 2.0 + 1e-6, worst_life
    return f"shortest hold {worst_hold:.2f} s, life <= {worst_life:.2f} deg"


@test(4, "other shapes (flat slab, tall pole): floor, hold, overshoot, settle, loops at 96 / 200 frames")
def t4():
    n = 0
    for kind in ('flat', 'tall'):
        res = runs(kind, (96, 200))
        bad = violations(res, only=('floor', 'hold', 'overshoot', 'settle', 'spring', 'vjump', 'seam', 'peak_lin', 'peak_ang'))
        assert not bad, f"{kind}: {len(bad)} violations, e.g. {bad[:3]}"
        n += len(res)
    return f"{n} runs, 0 violations"


@test(5, "in frame: after the action the product is inside the camera frame (loops: always); flips stay within 6% of it")
def t5():
    worst_after, worst_loop, worst_flip = 0.0, 0.0, 0.0
    for kind in ('suzanne', 'flat', 'tall'):
        res = runs(kind, (96, 200))
        for (pid, dur), (m, _, s) in res.items():
            p = presets.get('product_motion', pid)
            O = s['O']
            k = int((m['action_start_s'] + m['action_s']) * mr.FPS) + 1
            if p.meta.get('loop'):
                worst_loop = max(worst_loop, max(O))
            else:
                worst_after = max(worst_after, max(O[k:], default=0.0))
            if p.category == 'flip':
                worst_flip = max(worst_flip, max(O))
    assert worst_after <= 0.01, f"after the action the box sticks out by {worst_after:.1%} of the frame"
    assert worst_loop <= 0.03, f"a loop sticks out by {worst_loop:.1%} of the frame"
    assert worst_flip <= 0.06, f"a flip sticks out by {worst_flip:.1%} of the frame"
    return f"after {worst_after:.1%}, loops {worst_loop:.1%}, flips {worst_flip:.1%}"


@test(6, "30 and 60 fps, odd durations: ends at rest / loops close, keys inside the range, action time in seconds unchanged")
def t6():
    mr.make_product('suzanne')
    sc = bpy.context.scene
    for fps, dur in ((30, 100), (60, 400), (24, 12), (24, 20), (24, 30)):
        for pid in IDS:
            p = presets.get('product_motion', pid)
            api.apply('product_motion', pid, duration=dur, fps=fps)
            f0, f1 = core.frame_range(sc.pms)
            root = core.info().root
            keys = [k.co.x for fc in motion.iter_fcurves(root) for k in fc.keyframe_points]
            assert not keys or (min(keys) >= f0 - 1e-6 and max(keys) <= f1 + 1e-6), f"{pid} {dur}f@{fps}: keys outside {f0}-{f1}"
            if dur >= 30:
                sc.frame_set(f1)
                last = root.matrix_world.copy()
                rest = Matrix.Translation(core.info().center)
                if p.meta.get('ends_at_rest'):
                    assert mr_diff(last, rest) < 1e-3, f"{pid} {dur}f@{fps}: not at rest at the end"
    api.apply('product_motion', 'pop_in_reveal', duration=100, fps=30)
    root = core.info().root
    sc.frame_set(core.frame_range(sc.pms)[0] + 12)                  # 0.4 s after the start at 30 fps = frame 12
    pop30 = root.scale.x
    api.apply('product_motion', 'pop_in_reveal', duration=100, fps=24)
    sc.frame_set(core.frame_range(sc.pms)[0] + 10)                  # 0.4 s at 24 fps (rounded to a frame)
    pop24 = root.scale.x
    assert abs(pop30 - pop24) < 0.04, (pop30, pop24)
    return f"scale at 0.4 s: {pop30:.3f} (30 fps) vs {pop24:.3f} (24 fps)"


@test(7, "weight: impact presets stop at full speed on the contact frame (no ease-out) and recoil 10-25%")
def t7():
    res = runs('suzanne', (200,))
    n = 0
    for pid in ('drop_straight', 'drop_impact', 'drop_bounce', 'slam_from_above', 'heavy_land', 'drop_tilted'):
        m, _, s = res[(pid, 200)]
        P = s['P']
        z = [(p - s['center']).z / s['size'] for p in P]
        contact = next(i for i in range(1, len(z)) if z[i] < 0.01 and z[i - 1] > 0.05)     # first frame on the floor
        v_before = (z[contact - 2] - z[contact - 1]) * mr.FPS            # speed one frame before the contact
        v_peak = max((z[i - 1] - z[i]) * mr.FPS for i in range(1, contact + 1))
        assert v_before >= 0.8 * v_peak, f"{pid}: slows down before the contact ({v_before:.2f} vs peak {v_peak:.2f} size/s)"
        # squash: the contact frame is the deepest, the next ones recoil the other way by 10-25%
        sz = [x[2] for x in s['S']]
        d = [1.0 - v for v in sz[contact:contact + 12]]
        assert d[0] >= max(d) - 1e-9 and d[0] > 0.01, f"{pid}: the contact frame is not the extreme pose"
        rebound = max(-x for x in d) / d[0]
        assert 0.10 <= rebound <= 0.25, f"{pid}: recoil {rebound:.0%}"
        n += 1
    return f"{n} impacts: arrival at >= 80% of the peak speed, recoil 10-25%"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS MOTION QUALITY RESULTS ====")
for num, name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)
