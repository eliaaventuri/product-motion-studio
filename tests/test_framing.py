"""Framing test of Product Motion Studio: how well the product fills the frame (the camera is fitted on its REAL motion):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_framing.py
Matrix A: 5 shots (hero_34, front, low_angle, top_down, macro) x 54 product_motion x 3 formats (16:9, 9:16, 1:1) x 2 products
(cube 0.2 m, post 0.1 x 0.1 x 0.4 m), camera static.   Matrix B: 6 representative camera motions x 54 product_motion x 2 shots
x 2 formats x 2 products.   Every frame is measured with Blender's own projection (world_to_camera_view) on the 8 box corners.
  (a) HERO pose (the last frame; every frame of a loop): the product fills the frame well:
        16:9 -> height >= FILL_H_MIN; 9:16 / 1:1 -> limiting side >= FILL_LIM_MIN[format]; shots that crop on purpose (macro): >= CROP_REL
        of what the same shot gives with a static product. Never bigger than the static fit (+ FILL_UP_TOL), except on moves that
        push in on purpose.
  (b) ACTION: the product leaves the frame by at most OVER_MAX of its own extent and keeps its centre inside, on every frame
        except, for the presets declared 'offscreen' (entrances / exits), the frames within EXIT_S seconds of one where the
        product is out of the frame or MOSTLY_OUT of it.
  (c) camera moves (not the 360 loop: constant distance): the product keeps its size within +-SIZE_VAR (static product).   (d) the camera build takes < FIT_S_MAX s.
When (a) and (b) cannot both hold (a flip is wider than the frame at 0.55 fill) (b) wins: a hero below its floor is accepted only
if (b) is saturated (the worst action overflow >= SATURATED of the extent or a corner >= SAT_CORNER out of the frame: the camera could not have come closer); the cases are listed
in the result line.  Loops: every frame is a hero frame, the check is on the frame where the product is biggest.
Only Workbench / no render."""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view

import product_motion_studio as pkg
from product_motion_studio import api, build_camera, core, presets

# ---- thresholds -------------------------------------------------------------------------------------------------
FILL_H_MIN = 0.55                       # 16:9: product height / frame height at the hero pose
FILL_LIM_MIN = {'16:9': 0.55, '9:16': 0.70, '1:1': 0.60}      # limiting side (the larger of width / height fraction)
CROP_REL = 0.73                         # cropped shots (macro): hero fill >= this x the static fill of the same shot
FILL_UP_TOL = 0.03                      # hero never fills more than the shot's padding says (1 - padding) by more than this
OVER_MAX = 0.20                         # action: fraction of the product's extent outside the frame (same as test_addon 5)
SIZE_VAR = 0.10                         # camera moves, static product: size (limiting side) within +-10 % of its mean
FIT_S_MAX = 0.20                        # whole camera build at 200 frames
DURATION = 96
FORMATS = ('16:9', '9:16', '1:1')
SHOTS = ('hero_34', 'front', 'low_angle', 'top_down', 'macro')
CROPPED = ('macro',)
CAM_MOTIONS = ('orbit_90', 'orbit_rise', 'top_down_spiral', 'crane_up', 'push_in', 'orbit_360_loop')
PUSHING = ('push_in',)                  # the camera comes closer on purpose: the hero may be bigger than the static one
TOL = 0.01                              # rounding slack on the fill floors
SATURATED = 0.12                        # (a) missed is accepted when the action overflows at least this much (b is the limit)
MOSTLY_OUT = 0.22                       # the product is out of the frame, or this much of it is out: it is entering / leaving
EXIT_S = 0.5                            # (offscreen presets) frames within this many seconds of that are the entrance / exit
SAT_CORNER = 0.045                      # ... or a corner is this far out (the camera fit allows 5.5 % of the frame: test_motion_quality flips <= 6 %)
VISIBLE = 0.03                          # frames where the product covers less than this of the frame are not measured (scale ~ 0)

RESULTS = []
DATA = {}


def test(num, name):
    def deco(fn):
        try:
            bad, info = fn()
            if os.environ.get('PMS_DUMP'):
                with open(os.environ['PMS_DUMP'] + '.bad', 'a') as fh:
                    fh.writelines(f"t{num} {b}\n" for b in bad)
            msg = info + (f"  | {len(bad)} violations: " + "; ".join(bad[:5]) if bad else '')
            RESULTS.append((num, name, not bad, msg, len(bad)))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((num, name, False, f"{type(e).__name__}: {e}", 1))
        return fn
    return deco


def make_product(kind):
    if core.has_product() or bpy.data.collections.get(core.SYSTEM):
        api.remove_all()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    if kind == 'cube':
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0.3, 0.2, 0.1))
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.3, 0.2, 0.2))
        bpy.context.active_object.scale = (0.1, 0.1, 0.4)
    bpy.context.view_layer.update()
    return [bpy.context.active_object]


def project(sc, cam, root, inf):
    """(over, fill_x, fill_y, centre inside, corner farthest out of the frame as a fraction of it) of the box at the current frame."""
    mw = root.matrix_world
    pts = [world_to_camera_view(sc, cam, mw @ c) for c in inf.corners]
    ctr = world_to_camera_view(sc, cam, mw.translation)
    front = min(p.z for p in pts) > 0
    over, fills, corner = 0.0, [], 0.0
    for axis in 'xy':
        lo, hi = min(getattr(p, axis) for p in pts), max(getattr(p, axis) for p in pts)
        over = max(over, (max(0, -lo) + max(0, hi - 1)) / max(hi - lo, 1e-9))
        fills.append(hi - lo)
        corner = max(corner, -lo, hi - 1)
    inside = front and 0 <= ctr.x <= 1 and 0 <= ctr.y <= 1
    return over if front else 9.0, fills[0], fills[1], inside, corner


def measure(pid, loop):
    """Per-frame framing of the built scene: hero fills, worst action overflow, centre-out count, size variation."""
    sc = bpy.context.scene
    cam, root, inf = sc.camera, bpy.data.objects[core.ROOT_NAME], core.info()
    f0, f1 = core.frame_range(core.settings(sc))
    frames = list(range(f0, f1 + 1))
    rows, rest = [], []
    for f in frames:
        sc.frame_set(f)
        rows.append(project(sc, cam, root, inf))
        rest.append(root.matrix_world.translation.copy())
    over = np.array([r[0] for r in rows])
    fx, fy = np.array([r[1] for r in rows]), np.array([r[2] for r in rows])
    inside = np.array([r[3] for r in rows])
    corner = np.array([r[4] for r in rows])
    offscreen = presets.REGISTRY['product_motion'][pid].meta.get('offscreen', False)
    exempt = np.zeros(len(rows), bool)
    if offscreen:                                    # entrances / exits: within EXIT_S of a frame where the product is out of the frame
        out = (~inside) | (over > MOSTLY_OUT)
        near = np.convolve(out.astype(float), np.ones(2 * int(EXIT_S * core.settings(sc).fps) + 1), mode='same') > 0
        exempt = near & (over > 0.0)
    lim = np.maximum(fx, fy)
    live = ~exempt & (lim > VISIBLE)
    # a loop turns freely on its rest position (the first frame's centre); a bounce / hover away from it is action
    on_rest = np.array([(r - rest[0]).length < 0.03 * inf.size for r in rest]) if loop else np.zeros(len(rows), bool)
    return dict(h=float(fy[-1]), lim=float(lim[-1]), over=float(over[live].max()) if live.any() else 0.0, corner=float(corner[live].max()) if live.any() else 0.0, out=int((~inside & live).sum()),
                n_exempt=int(exempt.sum()), lim_min=float(lim[live].min() if live.any() else lim[-1]), lim_max=float(lim[live].max() if live.any() else lim[-1]),
                loop_h=(float(fy[on_rest].min()), float(fy[on_rest].max())) if loop else (0.0, 0.0),
                lim_rest=float(lim[on_rest].max()) if loop else 0.0, h_max=float(fy[live].max()) if live.any() else 0.0, loop=loop)


def run_matrix():
    for kind in ('cube', 'post'):
        objs = make_product(kind)
        api.build(objects=objs, product_motion='static', camera_motion='static', shot='hero_34', duration=DURATION,
                  engine='BLENDER_WORKBENCH')
        for fmt in FORMATS:
            api.apply('format', fmt)
            for shot in SHOTS:
                api.apply('camera_shot', shot)
                for pid, p in presets.REGISTRY['product_motion'].items():
                    api.apply('product_motion', pid)
                    DATA[('A', kind, fmt, shot, pid)] = measure(pid, bool(p.meta.get('loop')))
        api.apply('format', '16:9')
        for cm in CAM_MOTIONS:
            api.apply('camera_motion', cm)
            for fmt in ('16:9', '9:16'):
                api.apply('format', fmt)
                for shot in ('hero_34', 'front'):
                    api.apply('camera_shot', shot)
                    for pid, p in presets.REGISTRY['product_motion'].items():
                        api.apply('product_motion', pid)
                        DATA[('B', kind, fmt, shot, cm, pid)] = measure(pid, bool(p.meta.get('loop')))
        api.apply('camera_motion', 'static')
        api.apply('format', '16:9')


def hero_floor(fmt, shot, static):
    """Lowest accepted hero fill (height in 16:9, limiting side otherwise)."""
    if shot in CROPPED:
        return CROP_REL * hero_value(fmt, static)
    return FILL_H_MIN if fmt == '16:9' else FILL_LIM_MIN[fmt]


def ceiling(shot):
    """Most the hero may fill: the shot's own padding (fraction of the frame) + FILL_UP_TOL."""
    return 1.0 - presets.REGISTRY['camera_shot'][shot].data['padding'] + FILL_UP_TOL


def hero_value(fmt, d):
    return d['h'] if fmt == '16:9' else d['lim']


def hero_of(fmt, d):
    """The hero fill of a case: the last frame; a loop: the frame where the product is biggest."""
    if d['loop']:
        return d['loop_h'][1] if fmt == '16:9' else d['lim_rest']
    return hero_value(fmt, d)


def judge(fmt, shot, d, static, slack=0.0, whole_loop=False):
    """(problem text or '', is a (b)-limited miss): (a) of one case. whole_loop: a camera that turns 360 degrees on a constant
    distance (the size at the hero frame depends on the silhouette seen from the start angle): the biggest frame counts."""
    v, lo = hero_of(fmt, d), hero_floor(fmt, shot, static) - slack
    if whole_loop:
        v = d['h_max'] if fmt == '16:9' else d['lim_max']
    if v < lo - TOL:
        if d['over'] >= SATURATED or d['corner'] >= SAT_CORNER:
            return '', True
        return f"fill {v:.2f} < {lo:.2f} with room left (overflow {d['over']:.2f}, corner {d['corner']:.3f})", False
    return '', False


t0 = time.perf_counter()
pkg.register()
run_matrix()
MATRIX_S = time.perf_counter() - t0


@test(1, "(a) hero pose fills the frame: 5 shots x 54 product motions x 3 formats x 2 products, camera static")
def t1():
    bad, limited, n, worst = [], {}, 0, 9.0
    for key, d in DATA.items():
        if key[0] != 'A':
            continue
        _, kind, fmt, shot, pid = key
        n += 1
        static = DATA[('A', kind, fmt, shot, 'static')]
        msg, lim = judge(fmt, shot, d, static)
        if msg:
            bad.append(f"{pid}/{shot}/{fmt}/{kind} {msg}")
        if lim:
            limited[pid] = limited.get(pid, 0) + 1
        if hero_of(fmt, d) > ceiling(shot):
            bad.append(f"{pid}/{shot}/{fmt}/{kind} fills more than its padding ({hero_of(fmt, d):.2f} > {ceiling(shot):.2f})")
        if not lim:
            worst = min(worst, hero_of(fmt, d) / max(hero_of(fmt, static), 1e-9))
    return bad, (f"{n} cases, worst hero/static ratio {worst:.2f} on the unlimited ones; limited by (b) in {sum(limited.values())}: " +
                 ", ".join(f"{k} {v}" for k, v in sorted(limited.items(), key=lambda kv: -kv[1])[:12]))


@test(2, "(b) action: overflow <= 20 %, centre inside, except the declared offscreen runs (matrix A)")
def t2():
    bad, worst, n_ex = [], 0.0, 0
    for key, d in DATA.items():
        if key[0] != 'A':
            continue
        _, kind, fmt, shot, pid = key
        worst = max(worst, d['over'])
        n_ex += d['n_exempt']
        if d['over'] > OVER_MAX or d['out']:
            bad.append(f"{pid}/{shot}/{fmt}/{kind} over {d['over']:.2f} centre-out {d['out']}")
    return bad, f"worst overflow {worst:.1%}, {n_ex} offscreen frames exempt"


@test(3, "(a)+(b) with 6 camera moves x 54 product motions x 2 shots x 2 formats x 2 products")
def t3():
    bad, worst, n, limited = [], 0.0, 0, 0
    for key, d in DATA.items():
        if key[0] != 'B':
            continue
        _, kind, fmt, shot, cm, pid = key
        n += 1
        static = DATA[('A', kind, fmt, shot, 'static')]
        msg, lim = judge(fmt, shot, d, static, slack=0.03, whole_loop=cm == 'orbit_360_loop')   # the move ends at its own angle
        limited += lim
        if msg:
            bad.append(f"{cm}+{pid}/{shot}/{fmt}/{kind} {msg}")
        if cm not in PUSHING and hero_of(fmt, d) > ceiling(shot) + 0.03:
            bad.append(f"{cm}+{pid}/{shot}/{fmt}/{kind} fills more than its padding")
        worst = max(worst, d['over'])
        if d['over'] > OVER_MAX or d['out']:
            bad.append(f"{cm}+{pid}/{shot}/{fmt}/{kind} over {d['over']:.2f} out {d['out']}")
    return bad, f"{n} cases, worst overflow {worst:.1%}, {limited} limited by (b)"


@test(4, "(c) camera moves with a static product: the product keeps its size within +-10 % (not the 360 loop, a constant-distance track)")
def t4():
    bad, worst = [], 0.0
    for key, d in DATA.items():
        if key[0] != 'B' or key[5] != 'static' or key[4] in PUSHING + ('orbit_360_loop',):
            continue
        _, kind, fmt, shot, cm, pid = key
        mean = 0.5 * (d['lim_min'] + d['lim_max'])
        var = (d['lim_max'] - d['lim_min']) / 2 / mean
        worst = max(worst, var)
        if var > SIZE_VAR:
            bad.append(f"{cm}/{shot}/{fmt}/{kind} size varies +-{var:.0%} ({d['lim_min']:.2f}..{d['lim_max']:.2f})")
    return bad, f"worst +-{worst:.1%}"


@test(5, "(d) the camera build (fit on the real motion) takes < 0.2 s at 200 frames, worst of 6 moves x 5 heavy product motions")
def t5():
    sc = bpy.context.scene
    make_product('cube')
    api.build(objects=[o for o in bpy.data.objects if o.type == 'MESH'][:1] or make_product('cube'),
              product_motion='static', camera_motion='static', shot='hero_34', duration=200, engine='BLENDER_WORKBENCH')
    worst, where, tfit = 0.0, '', 0.0
    for pid in ('flip', 'coin_flip', 'spin_360_loop', 'exit_and_return', 'drop_bounce'):
        api.apply('product_motion', pid)
        inf = core.info()
        f0, f1 = core.frame_range(core.settings(sc))
        t = time.perf_counter()
        for _ in range(5):
            core.Track(inf, f0, f1)
        tfit = max(tfit, (time.perf_counter() - t) / 5)
        for cm in CAM_MOTIONS:
            api.apply('camera_motion', cm)
            t = time.perf_counter()
            for _ in range(5):
                build_camera.build(sc)
            dt = (time.perf_counter() - t) / 5
            if dt > worst:
                worst, where = dt, f"{cm}+{pid}"
    bad = [f"{where} {worst:.3f} s"] if worst > FIT_S_MAX else []
    return bad, f"worst camera build {worst * 1000:.0f} ms ({where}), sampling the track {tfit * 1000:.1f} ms; matrix took {MATRIX_S:.0f} s"


@test(6, "the sampled corners are the real ones: Track vs matrix_world (6 product motions, 4 frames each)")
def t6():
    sc = bpy.context.scene
    bad, worst = [], 0.0
    objs = make_product('post')
    api.build(objects=objs, product_motion='static', camera_motion='static', shot='hero_34', duration=96,
              engine='BLENDER_WORKBENCH')
    for pid in ('flip', 'coin_flip', 'spin_360_loop', 'drop_bounce', 'tumble_settle', 'wobble_spin_loop'):
        api.apply('product_motion', pid)
        inf = core.info()
        f0, f1 = core.frame_range(core.settings(sc))
        tr = core.Track(inf, f0, f1)
        for f in (f0, f0 + 20, f0 + 47, f1):
            sc.frame_set(f)
            mw = inf.root.matrix_world
            ref = np.array([tuple(mw @ c) for c in inf.corners])
            err = float(np.abs(ref - tr.pts[f - f0]).max()) / inf.size
            worst = max(worst, err)
            if err > 1e-4:
                bad.append(f"{pid}@{f} err {err:.2e}")
    return bad, f"worst error {worst:.1e} x size"


if os.environ.get('PMS_DUMP'):
    import json
    json.dump({'|'.join(k): v for k, v in DATA.items()}, open(os.environ['PMS_DUMP'], 'w'))

print("\n==== PMS FRAMING RESULTS ====")
for num, name, ok, msg, n in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed, {sum(r[4] for r in RESULTS if not r[2])} violations ====")
sys.exit(1 if fails else 0)
