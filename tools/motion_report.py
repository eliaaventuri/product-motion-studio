"""Motion quality report for the product_motion presets of Product Motion Studio (regenerable, nothing is written in the repo).

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tools/motion_report.py -- \
        [--only id,id] [--durations 48,96,200,480] [--out report.txt] [--curves DIR] [--kind suzanne|flat|tall]

For every preset and duration (24 fps) it samples the root of the prepared test product frame by frame and measures
  speed (linear size/s, angular deg/s, scale 1/s), acceleration, jerk, velocity jumps from one frame to the next, overshoot
  (% of travel, per channel), settle decay (successive peaks), final hold (frames at ~0 speed), floor penetration (% size),
  loop seam (C0 and C1) and the length in SECONDS of the main action (first to last frame above a small absolute speed (the slow 'life' of the tail stays below)).
Output: a compact table (one row per preset at the middle duration) + the list of violations of LIMITS.
tests/test_motion_quality.py runs the same measures and fails on any violation (`collect` and `check` are its API).
Never renders anything (no Workbench, no Eevee, no Cycles)."""

import os
import sys
from math import atan2, degrees, pi, radians

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..')))

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Quaternion, Vector

import product_motion_studio as pkg
from product_motion_studio import api, core, motion, presets

FPS = 24
DURATIONS = (48, 96, 200, 480)

# === LIMITS: every threshold of the quality criteria lives here ============================================================
LIMITS = dict(
    hold_s=0.5,             # final hold on the hero pose (non-loop): >= 0.5 s at every duration
    hold_eps=(0.02, 1.0, 0.004),   # "still": linear size/s, angular deg/s, scale 1/s
    floor_pct=0.5,          # max floor penetration, % of size (rise_from_below: declared exception)
    ovs_max=0.15,           # overshoot, fraction of the travel of a channel (impact family: see OVS_FAMILY)
    settle_ratio=0.60,      # every oscillation <= 60% of the previous one
    settle_peaks=4,         # at most this many peaks after the arrival ("no endless spring")
    settle_min=4.0,         # a channel is judged when its main excursion is at least this many times the noise floor
    settle_floor=(0.003, 0.4, 0.004),   # noise floor of the peak finder (size, deg, scale)
    vjump=0.55,             # |v[f+1]-v[f]| / peak speed, in the interior of a non-impact motion
    seam=0.08,              # loop: velocity step at the seam / peak speed
    loop_turn_s=(5.0, 14.0),    # turntable loops: seconds per turn when the duration allows it (>= 200 frames)
    loop_ang_short=300.0,   # max deg/s of a spin loop at short durations (a 2 s loop needs a fast turn)
    action_speed=0.06,      # a step belongs to the main action above this combined speed (1 size/s = 90 deg/s = 1 scale/s = 1.0)
    action_short=0.4,       # at <= 96 frames the lower bound of the action time is min(lo, action_short * T)
    short_gain=1.6,         # at 48 frames (2 s) the peak-speed limits are this much looser (everything has to fit in 1.5 s)
    settle_beats={},        # id -> number of leading intentional excursions skipped by the settle test
)
# peak speeds by family: (linear size/s, angular deg/s)
PEAK = {'loop': (3.0, 330.0), 'spin': (1.5, 480.0), 'drift': (0.6, 40.0), 'reveal': (12.0, 650.0),
        'impact': (13.0, 150.0), 'flip': (6.0, 900.0), 'flyby': (16.0, 300.0), 'stylized': (12.0, 900.0),
        'return': (14.0, 600.0), 'hold': (1.0, 10.0)}
PEAK_ID = {'exit_and_return': (16.0, 600.0), 'spin_360_settle': (1.5, 560.0), 'coin_flip': (6.0, 1250.0), 'spin_down_to_hero': (1.0, 900.0), 'snap_turns_90': (1.0, 1100.0),
           'slam_from_above': (18.0, 200.0), 'bounce_loop': (3.0, 100.0), 'glitch_step': (12.0, 2500.0)}
OVS_FAMILY = {'impact': 0.25}              # bounce / recoil of a landing: up to 25% of the fall
# main action in seconds: first-to-last frame above LIMITS['action_speed'] (settle tails included). Families with no
# entry (loop, drift, hold) are exempt: their "action" is the whole shot.
ACTION_S = {
    'spin_90': (0.9, 2.2), 'spin_180': (1.1, 2.8), 'spin_360_settle': (1.4, 3.4),
    'pop_in_reveal': (0.5, 1.4), 'scale_up_reveal': (0.5, 1.5), 'spin_in_reveal': (0.8, 2.0),
    'rise_from_below': (0.45, 1.8), 'slide_in': (0.7, 1.8), 'slide_in_right': (0.7, 1.8),
    'slide_in_top': (0.7, 1.9), 'unfold_tilt_reveal': (0.8, 2.0), 'soft_scale_reveal': (0.9, 2.4),
    'tilt_reveal': (0.8, 2.0), 'exploded_z_reveal': (0.05, 0.5),
    'drop_impact': (0.5, 1.5), 'drop_straight': (0.5, 1.4), 'drop_bounce': (0.7, 1.8), 'slam_from_above': (0.4, 1.4),
    'drop_tilted': (0.5, 1.5), 'heavy_land': (0.9, 2.2),
    'flip': (0.8, 2.2), 'flip_back': (0.8, 2.2), 'flip_side': (0.8, 2.2), 'flip_180_reveal': (0.8, 2.2),
    'coin_flip': (1.0, 2.4),
    'fly_by_swoop': (1.0, 2.6), 'fly_through_front': (1.0, 2.6), 'zoom_past_return': (1.6, 4.0),
    'glitch_step': (0.5, 1.8), 'magnetic_snap': (1.0, 2.6), 'tumble_settle': (1.0, 2.6),
    'showcase_3_pose': (2.0, 12.0),
    'exit_and_return': (2.0, 5.0), 'exit_up_and_return': (2.0, 5.0), 'tilt_to_hero': (0.7, 2.2),
    'spin_down_to_hero': (1.2, 3.0),
    'slide_in_left': (0.7, 1.8), 'slide_in_bottom': (0.7, 1.8), 'spring_overshoot_settle': (1.0, 2.0),
    'pendulum_damped_settle': (2.0, 3.0),
}
# declared contacts / hard stops: the velocity may jump at the contact frame (arrival WITHOUT ease, then recoil)
IMPACTS = {'drop_impact', 'drop_straight', 'drop_bounce', 'slam_from_above', 'drop_tilted', 'heavy_land', 'flip',
           'flip_back', 'flip_side', 'flip_180_reveal', 'coin_flip', 'glitch_step', 'bounce_loop', 'magnetic_snap',
           'tumble_settle', 'exit_up_and_return', 'snap_turns_90', 'slide_in_top', 'beat_pulse_120bpm',
           'exploded_z_reveal'}
# declared exceptions of single checks: check -> ids
EXEMPT = {'floor': {'rise_from_below'}, 'hold': {'static'}, 'settle': {'glitch_step', 'showcase_3_pose'}}
# declared cuts: the product leaves the frame and re-enters from the other side (the jump happens out of frame); the steps
# farther than OFFSCREEN * size from the rest pose are ignored by every speed measure
OFFSCREEN_CUT = {'exit_and_return', 'exit_up_and_return', 'zoom_past_return'}
OFFSCREEN = 2.5
SPIN_LOOPS = {'spin_360_loop', 'spin_360_eased_loop', 'spin_720_loop', 'wobble_spin_loop', 'turntable_tilted_loop',
              'levitate_spin_loop'}


# === the test product =======================================================================================================

def clean():
    if core.has_product() or bpy.data.collections.get(core.SYSTEM):
        api.remove_all()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def make_product(kind='suzanne'):
    clean()
    if kind == 'flat':
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1, 2, 0.5))
        bpy.context.active_object.scale = (3.0, 3.0, 0.2)
        objs = [bpy.context.active_object]
    elif kind == 'tall':
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=4.0, location=(-1, 0.5, 2.0))
        objs = [bpy.context.active_object]
    else:
        bpy.ops.mesh.primitive_monkey_add(size=2, location=(0.3, 0.2, 3))
        a = bpy.context.active_object
        bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1.0, location=(2.4, 0.2, 2.6))
        a.rotation_euler = (0.3, 0.1, 0.5)
        objs = [a, bpy.context.active_object]
    bpy.context.view_layer.update()
    api.build(objects=objs, product_motion='static', camera_motion='static', duration=48, fps=FPS)
    return objs


# === sampling ===============================================================================================================

def _omega(dq):
    """Rotation vector (rad, world axes) of a quaternion; accurate for tiny angles (Quaternion.to_axis_angle is not)."""
    v = Vector((dq.x, dq.y, dq.z))
    ln = v.length
    if ln < 1e-14:
        return Vector((0.0, 0.0, 0.0))
    return v * (2.0 * atan2(ln, abs(dq.w)) / ln * (1.0 if dq.w >= 0 else -1.0))


def _overflow(sc, mw, corners):
    """How far the box of the product sticks out of the camera frame (fraction of the frame, 0 = fully inside)."""
    out = 0.0
    for c in corners:
        v = world_to_camera_view(sc, sc.camera, mw @ c)
        out = max(out, -v.x, v.x - 1.0, -v.y, v.y - 1.0)
    return max(0.0, out)


def _rotation(root):
    """Orientation of the root from its rotation properties (delta applied after the euler), immune to scale 0."""
    return (root.delta_rotation_euler.to_matrix() @ root.rotation_euler.to_matrix()).to_quaternion()


def sample(pid, dur, extra=None):
    """Applies the preset at `dur` frames and samples the root frame by frame. Returns a dict of raw series + meta."""
    sc = bpy.context.scene
    api.apply('product_motion', pid, duration=dur, fps=FPS, **(extra or {}))
    inf = core.info()
    root = inf.root
    f0, f1 = core.frame_range(sc.pms)
    last = f1                                              # loops: the last key (= the first pose) is on f1
    P, Q, S, Z, O = [], [], [], [], []
    base = inf.base_z
    for f in range(f0, last + 1):
        sc.frame_set(f)
        mw = root.matrix_world
        P.append(mw.translation.copy())
        S.append(mw.to_scale())
        Q.append(_rotation(root))
        Z.append(min((mw @ c).z for c in inf.corners) - base)
        O.append(_overflow(sc, mw, inf.corners))
    p = presets.get('product_motion', pid)
    return dict(pid=pid, dur=dur, p=p, size=inf.size, center=inf.center.copy(), P=P, Q=Q, S=S, Z=Z, O=O, f0=f0, f1=f1,
                life=_life(root, f0, last), root=root, loop=bool(p.meta.get('loop')),
                seam=_seam(root, f0, last) if p.meta.get('loop') else None)


def _seam(root, f0, f1):
    """Worst relative slope step over every curve of a loop at the seam (as test_addon test 4)."""
    eps, worst = 1e-3, 0.0
    for fc in motion.iter_fcurves(root):
        a = (fc.evaluate(f0 + eps) - fc.evaluate(f0)) / eps
        b = (fc.evaluate(f1) - fc.evaluate(f1 - eps)) / eps
        worst = max(worst, abs(a - b) / max(1.0, abs(a), abs(b)))
    return worst


# === measures ===============================================================================================================

def _peaks(d, floor):
    """Local maxima of |d| (boundary samples count) whose prominence over both neighbouring valleys exceeds `floor`."""
    a = [abs(x) for x in d]
    n = len(a)
    cand = [i for i in range(n) if (i == 0 or a[i] > a[i - 1]) and (i == n - 1 or a[i] >= a[i + 1]) and a[i] > floor]
    out = []
    for i in cand:
        l = i
        while l > 0 and a[l - 1] <= a[l]:
            l -= 1
        r = i
        while r < n - 1 and a[r + 1] <= a[r]:
            r += 1
        vl = min(a[l:i + 1]) if l < i else a[i]
        vr = min(a[i:r + 1])
        if a[i] - max(vl if i > 0 else 0.0, vr) > floor or (i == 0 and a[i] - vr > floor):
            out.append((i, a[i]))
    return out


def measure(s):
    """All the numbers of one sample. Speeds: lin size/s, ang deg/s, scl 1/s; times in seconds."""
    P, Q, S, size, fps = s['P'], s['Q'], s['S'], s['size'], FPS
    n = len(P)
    v = [(P[i + 1] - P[i]) * fps / size for i in range(n - 1)]
    sv = [(S[i + 1] - S[i]) * fps for i in range(n - 1)]
    w = []
    for i in range(n - 1):
        w.append(_omega(Q[i + 1] @ Q[i].conjugated()) * fps)       # rad/s, world frame
    masked = [False] * (n - 1)
    if s['pid'] in OFFSCREEN_CUT:                          # steps that happen far outside the frame (declared cut)
        c = s['center']
        masked = [(P[i] - c).length > OFFSCREEN * size and (P[i + 1] - c).length > OFFSCREEN * size for i in range(n - 1)]
        for i, mk in enumerate(masked):
            if mk:
                v[i] = Vector((0.0, 0.0, 0.0))
                w[i] = Vector((0.0, 0.0, 0.0))
                sv[i] = Vector((0.0, 0.0, 0.0))
    ls = [x.length for x in v]
    asp = [degrees(x.length) for x in w]
    ss = [x.length for x in sv]
    ns = [max(a / 1.0, b / 90.0, c / 1.0) for a, b, c in zip(ls, asp, ss)]
    pk = max(ns) if ns else 0.0
    m = dict(peak_lin=max(ls, default=0.0), peak_ang=max(asp, default=0.0), peak_scl=max(ss, default=0.0), npk=pk)
    # acceleration / jerk (linear, size/s^2, size/s^3)
    a_ = [(v[i + 1] - v[i]) * fps for i in range(len(v) - 1)]
    j_ = [(a_[i + 1] - a_[i]) * fps for i in range(len(a_) - 1)]
    m['peak_acc'] = max((x.length for x in a_), default=0.0)
    m['peak_jerk'] = max((x.length for x in j_), default=0.0)
    # velocity jumps in the interior (the first step out of rest is not counted: entrances start fast on purpose)
    pl, pa, ps = max(m['peak_lin'], 1e-9), max(m['peak_ang'], 1e-9), max(m['peak_scl'], 1e-9)
    ok = [not (masked[i] or masked[i + 1]) for i in range(len(v) - 1)]
    jls = [(v[i + 1] - v[i]).length / pl if ok[i] else 0.0 for i in range(len(v) - 1)]
    jas = [degrees((w[i + 1] - w[i]).length) / pa if ok[i] else 0.0 for i in range(len(w) - 1)]
    jss = [(sv[i + 1] - sv[i]).length / ps if ok[i] else 0.0 for i in range(len(sv) - 1)]
    # a jump only counts when that quantity is a real part of the motion (peak above the noise)
    cand = []
    for kind, js_, pk_, noise in (('lin', jls, pl, 0.25), ('ang', jas, pa, 12.0), ('scl', jss, ps, 0.2)):
        if pk_ > noise and js_:                       # relative jump and, as well, an absolute one (a kink of a tiny motion is invisible)
            x = max(js_)
            if x * pk_ > noise:
                cand.append((x, kind, js_.index(x)))
    m['vjump_at'] = max(cand) if cand else (0.0, '', 0)
    m['vjump'] = m['vjump_at'][0]
    # final hold
    el, ea, es = LIMITS['hold_eps']
    k = 0
    while k < len(ls) and ls[-1 - k] < el and asp[-1 - k] < ea and ss[-1 - k] < es:
        k += 1
    m['hold_s'] = (k + 1) / fps if k < len(ls) else n / fps
    # main action in seconds: first to last step above 10% of the peak
    act = [i for i, x in enumerate(ns) if x >= LIMITS['action_speed']] if pk > 0 else []
    m['action_s'] = (act[-1] - act[0] + 1) / fps if act else 0.0
    m['action_start_s'] = act[0] / fps if act else 0.0
    # floor
    m['floor_pct'] = max(0.0, -min(s['Z'])) / size * 100
    # overshoot and settle on WORLD channels (rotation-invariant): location per axis (size), accumulated rotation vector
    # per world axis (deg; the 'life' yaw is subtracted), scale per axis. Euler angles would split a rotation about a
    # tilted axis into misleading peaks.
    fl = LIMITS['settle_floor']
    ch = {}
    for i in range(3):
        ch['loc' + 'xyz'[i]] = [p[i] / size for p in P]
        ch['scl' + 'xyz'[i]] = [x[i] for x in S]
    life = s['life']
    acc = [Vector((0.0, 0.0, 0.0))]
    for i in range(n - 1):
        step = w[i] * (180.0 / pi) / fps
        step.z -= life[i + 1] - life[i]
        acc.append(acc[-1] + step)
    for i in range(3):
        ch['rot' + 'xyz'[i]] = [a[i] for a in acc]
    # overshoot / settle are judged on three scalar distances to the FINAL pose (so arcs and multi-axis turns do not split
    # into misleading per-axis lobes): location (size), orientation (deg, life yaw removed), scale (max difference)
    qf = Quaternion((0.0, 0.0, 1.0), -radians(life[-1])) @ Q[-1]
    judged = {
        'dloc': [(p - P[-1]).length / size for p in P],
        'drot': [degrees((Quaternion((0.0, 0.0, 1.0), -radians(life[i])) @ Q[i]).rotation_difference(qf).angle)
                 for i in range(n)],
        'dscl': [max(abs(x[j] - S[-1][j]) for j in range(3)) for x in S]}
    judged = {k: [x if x < 180.0 or k != 'drot' else 360.0 - x for x in v] for k, v in judged.items()}
    ovs, ovs_ch, worst_ratio, worst_np, worst_ch = 0.0, '', 0.0, 0, ''
    for name, d in judged.items():
        kind = {'l': 0, 'r': 1, 's': 2}[name[1]]
        top = max(abs(x) for x in d)                      # the main excursion of the channel
        if top < LIMITS['settle_min'] * fl[kind]:
            continue
        arrive = max(i for i, x in enumerate(d) if abs(x) >= 0.25 * top)      # end of the main excursion
        pks = [(i, a) for i, a in _peaks(d, fl[kind]) if i > arrive]
        pks = pks[LIMITS['settle_beats'].get(s['pid'], 0):]
        if not pks:
            continue
        o = pks[0][1] / top                              # first swing after the arrival, fraction of the excursion
        if o > ovs:
            ovs, ovs_ch = o, name
        for (_, a0), (_, a1) in zip(pks, pks[1:]):
            r = a1 / a0
            if r > worst_ratio:
                worst_ratio, worst_ch = r, name
        if len(pks) > worst_np:
            worst_np, worst_ch = len(pks), name
    m['first_rebound'] = ovs
    m.update(ovs=ovs, ovs_ch=ovs_ch, settle_ratio=worst_ratio, settle_peaks=worst_np, settle_ch=worst_ch, ch=ch)
    # loops: seam C0 (pose) and C1 (3-point slopes at both ends of every world channel, relative to its steepest slope)
    if s['loop']:
        m['seam_c0'] = (P[-1] - P[0]).length / size + abs(degrees(Q[0].rotation_difference(Q[-1]).angle)) / 100.0
        m['seam_c1'] = s['seam']
        worst = 0.0
        for name, ser in ch.items():
            a = (-3 * ser[0] + 4 * ser[1] - ser[2]) / 2.0 * fps
            b = (3 * ser[-1] - 4 * ser[-2] + ser[-3]) / 2.0 * fps
            top = max(abs(ser[i + 1] - ser[i]) for i in range(n - 1)) * fps
            if top > {'l': 0.15, 'r': 6.0, 's': 0.1}[name[0]]:
                worst = max(worst, abs(a - b) / top)
        m['seam_v'] = worst
        m['seam_w'] = 0.0
        ang_total = sum(asp) / fps
        m['loop_turn_s'] = (n - 1) / fps / (ang_total / 360.0) if ang_total > 90 else 0.0
    return m


def check(m, s):
    """List of violation strings for one measured sample (see LIMITS)."""
    L, pid, p, dur = LIMITS, s['pid'], s['p'], s['dur']
    fam, loop = p.category, s['loop']
    T = (s['f1'] - s['f0']) / FPS
    bad = []
    lin_max, ang_max = PEAK_ID.get(pid, PEAK.get(fam, PEAK['reveal']))
    if dur <= 48:
        lin_max, ang_max = lin_max * L['short_gain'], ang_max * L['short_gain']
    if m['peak_lin'] > lin_max:
        bad.append(f"peak_lin {m['peak_lin']:.1f}>{lin_max}")
    if m['peak_ang'] > ang_max:
        bad.append(f"peak_ang {m['peak_ang']:.0f}>{ang_max:.0f}")
    if m['floor_pct'] > L['floor_pct'] and pid not in EXEMPT['floor']:
        bad.append(f"floor {m['floor_pct']:.2f}%")
    if not loop:
        if m['hold_s'] < L['hold_s'] - 1e-6 and pid not in EXEMPT['hold']:
            bad.append(f"hold {m['hold_s']:.2f}s<{L['hold_s']}")
        if m['vjump'] > L['vjump'] and pid not in IMPACTS:
            bad.append(f"vjump {m['vjump']:.2f} ({m['vjump_at'][1]} at step {m['vjump_at'][2]})")
        rng = ACTION_S.get(pid)
        if rng and m['npk'] > 0:
            lo, hi = rng
            lo_eff = min(lo, L['action_short'] * T) if dur <= 96 else lo
            if not lo_eff - 0.04 <= m['action_s'] <= hi + 0.04:
                bad.append(f"action {m['action_s']:.2f}s not in [{lo_eff:.2f},{hi}]")
        om = OVS_FAMILY.get(fam, L['ovs_max'])
        if pid not in EXEMPT['settle']:
            if m['ovs'] > om:
                bad.append(f"overshoot {m['ovs']:.0%}>{om:.0%} ({m['ovs_ch']})")
            if m['settle_ratio'] > L['settle_ratio']:
                bad.append(f"settle ratio {m['settle_ratio']:.2f}>{L['settle_ratio']} ({m['settle_ch']})")
            if m['settle_peaks'] > L['settle_peaks']:
                bad.append(f"spring {m['settle_peaks']} peaks ({m['settle_ch']})")
    else:
        if m['seam_c0'] > 1e-3:
            bad.append(f"seam C0 {m['seam_c0']:.1e}")
        if m['seam_c1'] > 2e-3:
            bad.append(f"seam C1 {m['seam_c1']:.1e}")
        if m['seam_v'] > L['seam'] and pid not in IMPACTS:
            bad.append(f"seam slope step {m['seam_v']:.2f}")
        if pid in SPIN_LOOPS:
            lo, hi = L['loop_turn_s']
            if dur >= 200 and not (lo * (0.5 if 'spin_720' in pid else 1.0) <= m['loop_turn_s'] <= hi):
                bad.append(f"turn {m['loop_turn_s']:.1f} s/turn")
            if dur < 200 and m['peak_ang'] > L['loop_ang_short'] * (2 if 'spin_720' in pid else 1):
                bad.append(f"spin {m['peak_ang']:.0f} deg/s at {dur}f")
    return bad


def collect(ids=None, durations=DURATIONS, kind='suzanne', keep=False):
    """{(pid, dur): (measures, violations)} for the given preset ids (None = all) on the test product."""
    make_product(kind)
    out = {}
    for pid in (ids or list(presets.REGISTRY['product_motion'])):
        for dur in durations:
            s = sample(pid, dur)
            m = measure(s)
            out[(pid, dur)] = (m, check(m, s), s if keep else None)
    return out


def collect_csv(s, m, path):
    """Dumps the world channels of a sample (size units / degrees / scale) as csv, `path`.csv; tools/motion_sheet.py
    (system python, matplotlib) draws them."""
    ch = m['ch']
    with open(path + '.csv', 'w') as fh:
        keys = list(ch)
        fh.write('frame,' + ','.join(keys) + ',floor_gap,life\n')
        for i in range(len(s['P'])):
            fh.write(f"{s['f0'] + i}," + ','.join(f"{ch[k][i]:.6f}" for k in keys) + f",{s['Z'][i] / s['size']:.6f},{s['life'][i]:.4f}\n")


def _life(root, f0, f1):
    fc = {(c.data_path, c.array_index): c for c in motion.iter_fcurves(root)}.get(('delta_rotation_euler', 2))
    return [degrees(fc.evaluate(f)) if fc else 0.0 for f in range(f0, f1 + 1)]


# === main ===================================================================================================================

def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    opt = dict(only=None, durations=DURATIONS, out=None, curves=None, kind='suzanne')
    for i, a in enumerate(argv):
        if a == '--only':
            opt['only'] = argv[i + 1].split(',')
        elif a == '--durations':
            opt['durations'] = tuple(int(x) for x in argv[i + 1].split(','))
        elif a == '--out':
            opt['out'] = argv[i + 1]
        elif a == '--curves':
            opt['curves'] = argv[i + 1]
        elif a == '--kind':
            opt['kind'] = argv[i + 1]
    return opt


def main():
    opt = _args()
    pkg.register()
    res = collect(opt['only'], opt['durations'], kind=opt['kind'], keep=bool(opt['curves']))
    lines = []
    mid = 200 if 200 in opt['durations'] else opt['durations'][-1]
    lines.append(f"== table at {mid} frames @{FPS} fps (peak lin size/s, ang deg/s; ovs % of travel; hold/action s) ==")
    lines.append(f"{'preset':<22}{'fam':<9}{'act':>5}{'hold':>5}{'vlin':>6}{'wang':>6}{'ovs':>5}{'rbn':>5}{'flr%':>6}{'vjmp':>5}{'jerk':>7}")
    for pid in (opt['only'] or list(presets.REGISTRY['product_motion'])):
        m, bad, _ = res[(pid, mid)]
        fam = presets.get('product_motion', pid).category
        lines.append(f"{pid:<22}{fam:<9}{m['action_s']:>5.2f}{m['hold_s']:>5.2f}{m['peak_lin']:>6.1f}{m['peak_ang']:>6.0f}"
                     f"{m['ovs']*100:>5.0f}{m['first_rebound']*100:>5.0f}{m['floor_pct']:>6.2f}{m['vjump']:>5.2f}{m['peak_jerk']:>7.0f}")
    nviol = 0
    lines.append("== violations ==")
    for (pid, dur), (m, bad, _) in res.items():
        for b in bad:
            nviol += 1
            lines.append(f"{pid} @{dur}: {b}")
    kinds = {}
    for (pid, dur), (m, bad, _) in res.items():
        for b in bad:
            kinds[b.split()[0]] = kinds.get(b.split()[0], 0) + 1
    lines.append(f"== TOTAL {nviol} violations in {len(res)} runs; by kind: {kinds} ==")
    if opt['curves']:
        os.makedirs(opt['curves'], exist_ok=True)
        for pid in (opt['only'] or list(presets.REGISTRY['product_motion'])):
            if (pid, 200) in res:
                collect_csv(res[(pid, 200)][2], res[(pid, 200)][0], os.path.join(opt['curves'], pid))
    text = '\n'.join(lines)
    if opt['out']:
        with open(opt['out'], 'w') as fh:
            fh.write(text + '\n')
    print(text if len(lines) < 12 else '\n'.join(lines[-1:]))


if __name__ == '__main__':
    main()
