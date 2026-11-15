"""PRODUCT MOTION presets: functions (root, ctx) that put keyframes on the product root.

SCHEMA   @register('product_motion', id, name, category, desc, loop=, ends_at_rest=, offscreen=)
RULES    - Animate ONLY `root` (PMS_Product_Root). It sits on its rest pose (location = ctx.center, rotation 0, scale 1).
         - Scale everything by ctx.size (product diagonal): offsets/heights as fractions of ctx.size, never absolute units.
         - ABSOLUTE TIME. A preset is a function pose(t) of the time in SECONDS (ctx.fps aware); motion.bake samples it on every
           frame. An action lasts what it really takes (pop 0.8 s, drop 0.6 s, flip 0.75 s of air, quarter turn 1 s...) at ANY
           duration: ctx.plan(*seconds) lays the phases one after the other and shrinks them all together only when the shot
           is too short; the rest of the shot is "life" (motion.life_yaw: a slow +-2 degree yaw, opt 'life'=0 turns it off)
           and a still hold on the hero pose of ctx.hold_s = max(0.5 s, 12% of the shot, at most 2 s). Helpers of the ctx are
           documented in build_animation.py (sec, u, snap, action, plan, dur_s, t_end).
         - Loops (loop=True) are normalized to the duration but their speed is kept elegant: the number of turns / cycles
           follows ctx.dur_s (a turntable turn takes about 9 s, a float cycle about 5 s); pose at f0 == pose at f1, C1 at the seam.
         - ends_at_rest=True -> at ctx.f1 the root is back on its rest pose. loop=True -> pose at f0 == pose at f1.
         - offscreen=True: the product enters / leaves the frame on purpose (slide-ins, drops from above, fly-bys, exits): the camera
           fit ignores the runs of frames in which it is out of the frame (core.Track.mark_offscreen). The camera is fitted on the
           REAL motion (the box corners sampled from the root's f-curves, build_camera): hero pose = full padding, action = may
           overfill by 12 %. (sweep= / margin= / lift= in the registrations below are the old theoretical envelope, no longer read.)
         - ctx.opt holds user overrides (apply(..., turns=2)): read them with ctx.opt.get(name, default).
         - Categories = families: loop, spin, drift, reveal, impact, flip, flyby, stylized, return (+ hold).
WEIGHT   (from the weight/impact notes of the skill) a body that hits the floor / its seat does NOT ease out before the contact
         (gravity: x^2), the CONTACT frame is the extreme pose (1 frame), then the WHOLE body takes the blow (squash about its
         base, rocking tilt, push), recoils 22% the other way, 7%, 2% and is still ~11 frames later (_Hit, motion.impact_wave).
         Light bodies recover fast, heavy ones slowly (weight). Nothing sinks into the floor: motion.bake raises the product
         so that no corner of its box goes below the floor (rise_from_below is the declared exception).
EXCEPTIONS (declared; tests/test_motion_quality.py and tools/motion_report.py know them)
         - rise_from_below: starts under the floor on purpose (floor penetration exempt).
         - exit_and_return, exit_up_and_return, zoom_past_return: the product leaves the frame and re-enters from the other
           side, the jump happens out of frame (speed measures ignore the steps farther than 2.5 size from the rest pose).
         - impact / flip / stylized contacts (drops, landings, bounce_loop, magnetic_snap, glitch_step, snap_turns_90): the
           velocity jumps at the contact frame ON PURPOSE (arrival without ease, then recoil).
         - drift presets are the whole shot (their "action" is the drift); bounce_loop has contacts at its seam (no C1 there).
         - peak speeds: coin_flip (3 turns in 1.3 s), spin_down_to_hero (starts spinning fast), snap_turns_90, glitch_step.
         - beat_pulse_120bpm: the kick on the beat is a declared contact (velocity jump at the attack, IMPACTS in motion_report).
"""

from math import cos, exp, pi, radians, sin, sqrt, tau
from random import Random
from mathutils import Matrix, Vector
from . import register
from .. import motion as m
from ..motion import bake, e_beta, e_over, e_smooth, hops, impact_wave, trk


@register('product_motion', 'static', 'Static', 'hold', 'No product motion (camera only).',
          loop=True, ends_at_rest=True)
def static(root, ctx):
    pass


# === helpers =================================================================
# Values are given in FRACTIONS OF ctx.size (location), DEGREES (rotation) or factors (scale); times in SECONDS.

UP = Vector((0.0, 0.0, 1.0))


def _axes(ctx):
    """(screen-right, depth-away-from-camera) unit vectors in world XY."""
    r = Vector((ctx.right.x, ctx.right.y, 0.0)).normalized()
    return r, Vector((-r.y, r.x, 0.0))


def _rot(axis, deg):
    return Matrix.Rotation(radians(deg), 3, Vector(axis))


def _x(t, a, b):
    """Progress 0..1 of t between a and b."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a)


def _pin(ctx, sz):
    """Z offset (fraction of size) that keeps the BASE on the floor when the body is scaled by sz in Z."""
    return (sz - 1.0) * 0.5 * ctx.dims.z / ctx.size


def _scale(ctx, sz, loc=None):
    """(loc, scl) of a body squashed / stretched to sz in Z about its base (x, y keep the volume roughly)."""
    loc = Vector(loc) if loc is not None else Vector((0.0, 0.0, 0.0))
    loc.z += _pin(ctx, sz)
    sxy = 1.0 + 0.5 * (1.0 - sz)
    return loc, Vector((sxy, sxy, sz))


def _about(ctx, p, R):
    """Location offset (fraction of size) of the body when it is rotated by R about the point p (world offset from its centre)."""
    return (p - R @ p) / ctx.size


def _hover(ctx, rot_at, n=360):
    """Constant lift (fraction of size) that keeps the lowest corner of the box above the floor over a whole loop whose
    orientation is rot_at(u), u in 0..1: the product floats instead of rocking on its edge (no kinks at the seam)."""
    base = -0.5 * ctx.dims.z
    dip = 0.0
    for k in range(n):
        R = rot_at(k / n)
        dip = max(dip, base - min((R @ c).z for c in ctx.info.corners))
    return dip / ctx.size + 0.004 if dip > 0.0 else 0.0


def _turns(ctx, per_turn=9.0, minimum=1):
    """Turns of a spin loop: about one turn per `per_turn` seconds."""
    return max(minimum, round(ctx.dur_s / per_turn))


def _cycles(ctx, per=5.0):
    """Cycles of a float / sway loop: about one per `per` seconds."""
    return max(1, round(ctx.dur_s / per))


def _life(root, ctx, t_done):
    """The slow life of the tail: from 0.35 s after the action until the final hold."""
    h = sum(map(ord, ctx.pid))                             # a different swing for every preset, always the same one
    m.life_yaw(root, ctx, t_done + 0.35, ctx.t_end, (1.5 + 0.1 * (h % 6)) * ctx.opt.get('life', 1.0),
               period=5.5 + 0.5 * (h % 7), sign=1.0 if h % 2 else -1.0)


class _Hit:
    """Whole-body reaction to contacts [(time, gain), ...]: squash about the base, rocking tilt toward `direction`, push.
    pose(t, loc, rot, sz) adds it to a body pose; the extreme is the contact frame."""

    def __init__(self, ctx, hits, squash=0.03, tilt=1.0, direction=(0.25, 0.1, -1.0), push=0.0, weight=1.0):
        self.ctx, self.hits, self.squash, self.tilt, self.push = ctx, hits, squash, tilt, push
        d = Vector((direction[0], direction[1], 0.0))
        self.dh = d.normalized() if d.length > 1e-6 else Vector((1.0, 0.0, 0.0))
        self.axis = UP.cross(self.dh)
        room = (ctx.t_end - max(t for t, _ in hits)) * 24.0          # the wave is defined in frames at 24 fps
        self.weight = max(0.15, min(weight, room / 11.0))

    def wave(self, t):
        return sum(g * impact_wave((t - tc) * 24.0, self.weight) for tc, g in self.hits)

    def pose(self, t, loc=None, rot=None, sz=1.0):
        w = self.wave(t)
        loc = Vector(loc) if loc is not None else Vector((0.0, 0.0, 0.0))
        loc = loc + self.dh * (self.push * w)
        loc, scl = _scale(self.ctx, sz * (1.0 - self.squash * w), loc)
        R = _rot(self.axis, self.tilt * w)
        if rot is not None:
            R = R @ rot
        return loc, R, scl


# === loop / spin =============================================================

@register('product_motion', 'spin_360_loop', '360 Spin Loop', 'loop',
          'Constant-speed turntable (one turn per ~9 s), seamless loop.',
          loop=True, ends_at_rest=True, sweep='spin')
def spin_360_loop(root, ctx):
    m.spin_loop(root, 'Z', ctx.f0, ctx.f1, turns=ctx.opt.get('turns', _turns(ctx)), ease=ctx.opt.get('ease', False))


@register('product_motion', 'spin_360_eased_loop', '360 Spin Eased Loop', 'loop',
          'Turn that slows toward the loop point and speeds up mid-turn (one turn per ~9 s), seamless.',
          loop=True, ends_at_rest=True, sweep='spin')
def spin_360_eased_loop(root, ctx):
    m.spin_loop(root, 'Z', ctx.f0, ctx.f1, turns=ctx.opt.get('turns', _turns(ctx)), ease=True)


@register('product_motion', 'spin_720_loop', '720 Spin Loop', 'loop',
          'Energetic turntable: a turn every ~4.5 s (two per short loop), constant speed, seamless.',
          loop=True, ends_at_rest=True, sweep='spin')
def spin_720_loop(root, ctx):
    m.spin_loop(root, 'Z', ctx.f0, ctx.f1, turns=ctx.opt.get('turns', _turns(ctx, 4.5, 2)), ease=ctx.opt.get('ease', False))


@register('product_motion', 'spin_90', 'Quarter Turn', 'spin',
          'Small wind-up, then a quarter turn that glides to a stop with a tiny overshoot, ending rotated 90 degrees.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def spin_90(root, ctx):
    a = ctx.opt.get('angle', 90)
    t = ctx.plan(0.28, 1.0)
    over = 0.035

    def pose(tt):
        yaw = trk(tt, [(0, 0), (t[1], -0.045 * a), (t[2], a, lambda x: e_over(x, over, 2, 3, 0.6))])
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2] + 0.2)


@register('product_motion', 'spin_180', 'Half Turn', 'spin',
          'Wind-up, then a half turn that glides to a stop and shows the back of the product.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def spin_180(root, ctx):
    a = ctx.opt.get('angle', 180)
    t = ctx.plan(0.32, 1.3)

    def pose(tt):
        yaw = trk(tt, [(0, 0), (t[1], -0.04 * a), (t[2], a, lambda x: e_over(x, 0.03, 2, 3, 0.6))])
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2] + 0.2)


@register('product_motion', 'spin_360_settle', 'Full Turn + Settle', 'spin',
          'Wind-up, one full turn in 2.3 s that overshoots a few degrees and settles back on its pose.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.02)
def spin_360_settle(root, ctx):
    t = ctx.plan(0.36, 2.3)

    def pose(tt):
        yaw = trk(tt, [(0, 0), (t[1], -15.0), (t[2], 360.0, lambda x: e_over(x, 0.022, 2, 3, 0.65))])
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2] + 0.2)


@register('product_motion', 'spring_overshoot_settle', 'Spring Overshoot Settle', 'spin',
          'Fast turn that overshoots about 25 percent and settles like a damped spring in about 1.2 s, ending rotated.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def spring_overshoot_settle(root, ctx):
    a, zeta, w = ctx.opt.get('angle', 90), 0.4, 8.3
    wd = w * sqrt(1.0 - zeta * zeta)
    t = ctx.plan(2.0)

    def pose(tt):
        s = tt / ctx.k                                  # the spring runs in shot time (compressed when the shot is short)
        x = 1.0 - exp(-zeta * w * s) * (cos(wd * s) + zeta * w / wd * sin(wd * s))
        return None, _rot(UP, a * x), None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[1] + 0.2)


@register('product_motion', 'pendulum_damped_settle', 'Pendulum Damped Settle', 'spin',
          'Swings 35 degrees left and right, the swing dies out in about 3 s (period 1.8 s) and the product comes to rest.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.02)
def pendulum_damped_settle(root, ctx):
    a, per, dec = 35.0, 1.8, 0.9
    ctx.plan(5.0 * dec)

    def pose(tt):
        s = tt / ctx.k
        yaw = a * exp(-s / dec) * cos(tau * s / per) * (1.0 - e_smooth((s - 4.0 * dec) / dec))
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'wobble_spin_loop', 'Wobble Spin Loop', 'loop',
          'Turntable with a gentle nodding wobble (about 6 degrees), floating just above the floor, seamless.',
          loop=True, ends_at_rest=False, sweep='spin', margin=1.1, lift=0.07)
def wobble_spin_loop(root, ctx):
    turns, c, a = ctx.opt.get('turns', _turns(ctx)), _cycles(ctx, 4.0), ctx.opt.get('tilt', 6.0)
    m.spin_loop(root, 'Z', ctx.f0, ctx.f1, turns=turns)

    def rot_at(u):
        return _rot(UP, 360.0 * turns * u) @ _rot((0, 1, 0), 0.5 * a * sin(tau * 2 * c * u)) @ _rot((1, 0, 0), a * sin(tau * c * u))
    lift = Vector((0, 0, _hover(ctx, rot_at)))
    bake(root, ctx, lambda t: (lift, rot_at(t / ctx.dur_s), None), cyc=True, ground=False, skip=(('rotation_euler', 2),))


@register('product_motion', 'turntable_tilted_loop', 'Tilted Turntable Loop', 'loop',
          'Spins about its own axis, leaned 14 degrees toward the camera so the top shows, floating just above the floor; seamless.',
          loop=True, ends_at_rest=False, sweep='spin', margin=1.1, lift=0.1)
def turntable_tilted_loop(root, ctx):
    right, _ = _axes(ctx)
    tilt, turns = ctx.opt.get('tilt', 14.0), _turns(ctx)

    def rot_at(u):
        return _rot(right, tilt) @ _rot(UP, 360.0 * turns * u)
    lift = Vector((0, 0, _hover(ctx, rot_at)))
    bake(root, ctx, lambda t: (lift, rot_at(t / ctx.dur_s), None), cyc=True, ground=False)


@register('product_motion', 'pendulum_sway_loop', 'Pendulum Sway Loop', 'loop',
          'Slow yaw swing left and right (30 degrees each way, a swing every ~9 s) like a pendulum, seamless.',
          loop=True, ends_at_rest=True, sweep='spin', margin=1.0)
def pendulum_sway_loop(root, ctx):
    a, c = ctx.opt.get('angle', 30.0), _cycles(ctx, 9.0)
    bake(root, ctx, lambda t: (None, _rot(UP, a * sin(tau * c * t / ctx.dur_s)), None), cyc=True, ground=False)


@register('product_motion', 'breathing_scale_loop', 'Breathing Scale Loop', 'loop',
          'Barely visible scale pulse (2.5%, a breath every ~5 s) that keeps the base on the floor, seamless.',
          loop=True, ends_at_rest=True, margin=1.03, lift=0.01)
def breathing_scale_loop(root, ctx):
    amt, c = ctx.opt.get('amount', 0.025), _cycles(ctx, 5.0)

    def pose(t):
        s = 1.0 + amt * 0.5 * (1.0 - cos(tau * c * t / ctx.dur_s))
        return Vector((0, 0, _pin(ctx, s))), None, s
    bake(root, ctx, pose, cyc=True, ground=False)


@register('product_motion', 'levitate_spin_loop', 'Levitate Spin Loop', 'loop',
          'Rises and sinks gently (a cycle every ~5 s) while turning at constant speed, seamless.',
          loop=True, ends_at_rest=True, sweep='spin', margin=1.0, lift=0.085)
def levitate_spin_loop(root, ctx):
    a, c = ctx.opt.get('height', 0.04), _cycles(ctx, 5.0)
    m.spin_loop(root, 'Z', ctx.f0, ctx.f1, turns=_turns(ctx))
    bake(root, ctx, lambda t: (Vector((0, 0, a * (1.0 - cos(tau * c * t / ctx.dur_s)))), None, None), cyc=True, ground=False)


@register('product_motion', 'hover_float_loop', 'Hover Float Loop', 'loop',
          'Gentle rise and fall (never below the floor, a cycle every ~5 s) with a slight yaw sway, seamless.',
          loop=True, ends_at_rest=True, sweep='spin', margin=1.0, lift=0.07)
def hover_float_loop(root, ctx):
    a, sway, c = ctx.opt.get('height', 0.035), ctx.opt.get('sway', 4.0), _cycles(ctx, 5.0)

    def pose(t):
        ph = tau * c * t / ctx.dur_s
        return Vector((0, 0, a * (1.0 - cos(ph)))), _rot(UP, sway * sin(ph)), None
    bake(root, ctx, pose, cyc=True, ground=False)


@register('product_motion', 'snap_turns_90', 'Snap Turns 90', 'stylized',
          'Four hard 90-degree snaps with holds between them (6% overshoot), back on its pose, seamless.',
          loop=True, ends_at_rest=True, sweep='spin', margin=1.02)
def snap_turns_90(root, ctx):
    per = ctx.dur_s / 4.0
    sd = min(0.28, 0.6 * per)
    starts = [k * per + 0.5 * (per - sd) for k in range(4)]

    def pose(t):
        yaw = sum(90.0 * e_over(_x(t, s0, s0 + sd), 0.065, 2, 3, 0.55) for s0 in starts)
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'gyro_precession_loop', 'Gyro Precession Loop', 'loop',
          'Spinning-top loop: the leaned product precesses around the vertical (about every 6 s) while it spins on its own axis, seamless.',
          loop=True, ends_at_rest=False, sweep='spin', margin=1.1)
def gyro_precession_loop(root, ctx):
    right, _ = _axes(ctx)
    tilt = ctx.opt.get('tilt', 10.0)
    prec, spins = max(1, round(ctx.dur_s / 6.0)), max(2, round(ctx.dur_s / 3.0))

    def rot_at(u):
        p = 360.0 * prec * u
        return _rot(UP, p) @ _rot(right, tilt) @ _rot(UP, 360.0 * spins * u - p)
    lift = Vector((0, 0, _hover(ctx, rot_at)))
    bake(root, ctx, lambda t: (lift, rot_at(t / ctx.dur_s), None), cyc=True, ground=False)


@register('product_motion', 'beat_pulse_120bpm', 'Beat Pulse 120 BPM', 'loop',
          'Scale pulse on the beat (120 BPM, option bpm): a 4.5% kick in 0.06 s that decays, synced to Reels and TikTok, seamless.',
          loop=True, ends_at_rest=True, margin=1.03)
def beat_pulse_120bpm(root, ctx):
    bpm = ctx.opt.get('bpm', 120)
    n = max(1, round(ctx.dur_s * bpm / 60.0))
    per = ctx.dur_s / n

    def pose(t):
        x = t - per * int(t / per)
        kick = e_smooth(x / 0.06) if x < 0.06 else exp(-(x - 0.06) / 0.12)
        s = 1.0 + 0.045 * kick * (1.0 - e_smooth((x - 0.6 * per) / (0.4 * per)))
        return Vector((0, 0, _pin(ctx, s))), None, s
    bake(root, ctx, pose, cyc=True, ground=False)


@register('product_motion', 'showcase_4_angles_snap', 'Showcase 4 Angles', 'loop',
          'Four stops at 90-degree angles: each holds with a slow drift, then turns to the next angle in under 1 s, seamless.',
          loop=True, ends_at_rest=True, sweep='spin', margin=1.02)
def showcase_4_angles_snap(root, ctx):
    per = ctx.dur_s / 4.0
    mv = min(0.9, 0.9 * per)
    hold = per - mv
    drift = 3.0 * min(1.0, hold / 1.5)                    # short clips: the hold is brief, so is its drift (no kick at the seam)

    def pose(t):
        k = min(3, int(t / per))
        x = t - k * per
        if x < hold:
            yaw = 90.0 * k + drift * e_smooth(x / hold)
        else:
            yaw = 90.0 * k + drift + (90.0 - drift) * e_over(_x(x, hold, per), 0.04, 2, 3, 0.8)
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, cyc=True, ground=False)


@register('product_motion', 'zero_gravity_tumble_loop', 'Zero Gravity Tumble Loop', 'loop',
          'Floats above the floor and tumbles slowly in every direction (a full turn about every 14 s, a gentle bob), seamless.',
          loop=True, ends_at_rest=False, sweep='spin', margin=1.1)
def zero_gravity_tumble_loop(root, ctx):
    n, c = _turns(ctx, 14.0), _cycles(ctx, 5.0)

    def rot_at(u):
        ph = tau * u
        return _rot(UP, 360.0 * n * u) @ _rot((0, 1, 0), 12.0 * sin(2 * ph + 1.1)) @ _rot((1, 0, 0), 18.0 * sin(ph + 0.3))
    lift = _hover(ctx, rot_at)                         # the lowest corner clears the floor whatever the shape

    def pose(t):
        return Vector((0, 0, lift + 0.03 * (1.0 + sin(tau * c * t / ctx.dur_s)))), rot_at(t / ctx.dur_s), None
    bake(root, ctx, pose, cyc=True, ground=False)


# === luxury drift ============================================================
# The drift presets ARE the shot: they move over the whole of it, smoothly, and rest in the hold at its end. At short durations
# the amount of motion is capped (rate per second) so a "slow" drift never becomes fast.

@register('product_motion', 'luxury_drift', 'Luxury Drift', 'drift',
          'Slow premium yaw of 40 degrees with a barely-there float (1.2% of its size), ending rotated.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def luxury_drift(root, ctx):
    td = ctx.t_end
    ang = min(ctx.opt.get('angle', 40), 12.0 * td)

    def pose(t):
        x = _x(t, 0.0, td)
        return Vector((0, 0, 0.012 * sin(pi * x) ** 2)), _rot(UP, ang * e_beta(x, 2, 2)), None
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'drift_yaw_slow', 'Drift Yaw Slow', 'drift',
          'Very slow premium yaw of 25 degrees with a long smooth acceleration, ending rotated.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def drift_yaw_slow(root, ctx):
    td = ctx.t_end
    ang = min(ctx.opt.get('angle', 25.0), 8.0 * td)
    bake(root, ctx, lambda t: (None, _rot(UP, ang * e_beta(_x(t, 0.0, td), 3, 3)), None), ground=False)


@register('product_motion', 'drift_yaw_reverse', 'Drift Yaw Reverse', 'drift',
          'Starts with a 3 degree wind-up the other way, then drifts 25 degrees the opposite direction, ending rotated.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02)
def drift_yaw_reverse(root, ctx):
    td = ctx.t_end
    ang = min(ctx.opt.get('angle', 25.0), 8.0 * td)
    w = 0.14 * td

    def pose(t):
        yaw = trk(t, [(0, 0), (w, 0.12 * ang), (td, -ang, lambda x: e_beta(x, 2, 3))])
        return None, _rot(UP, yaw), None
    bake(root, ctx, pose, ground=False)


def _drift_lateral(root, ctx, sign):
    td = ctx.t_end
    d = sign * ctx.opt.get('distance', 0.09)
    r, _ = _axes(ctx)

    def pose(t):
        e = e_beta(_x(t, 0.0, td), 2, 2)
        return r * (d * e), _rot(UP, -sign * 8.0 * e), None
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'drift_lateral_right', 'Drift Lateral Right', 'drift',
          'Slow slide to the right of frame (9% of size) with a slight counter-yaw, ending offset.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.12)
def drift_lateral_right(root, ctx):
    _drift_lateral(root, ctx, 1.0)


@register('product_motion', 'drift_lateral_left', 'Drift Lateral Left', 'drift',
          'Slow slide to the left of frame (9% of size) with a slight counter-yaw, ending offset.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.12)
def drift_lateral_left(root, ctx):
    _drift_lateral(root, ctx, -1.0)


@register('product_motion', 'drift_rise', 'Drift Rise', 'drift',
          'Lifts off the floor by 7% of its size while yawing 14 degrees, ending floating.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02, lift=0.07)
def drift_rise(root, ctx):
    td = ctx.t_end

    def pose(t):
        e = e_beta(_x(t, 0.0, td), 2, 2)
        return Vector((0, 0, ctx.opt.get('height', 0.07) * e)), _rot(UP, 14.0 * e), None
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'drift_tilt_slow', 'Drift Tilt Slow', 'drift',
          'Slow lean of 8 degrees toward the camera with a slight yaw, ending tilted; stays above the floor.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.08, lift=0.04)
def drift_tilt_slow(root, ctx):
    td = ctx.t_end
    right, _ = _axes(ctx)
    tilt = ctx.opt.get('tilt', 8.0)

    def pose(t):
        e = e_beta(_x(t, 0.0, td), 2, 2)
        return None, _rot(right, tilt * e) @ _rot(UP, 12.0 * e), None
    bake(root, ctx, pose)


# === reveal / entrances ======================================================

@register('product_motion', 'pop_in_reveal', 'Pop-in Reveal', 'reveal',
          'Scale 0 to final in 0.8 s with an 8% overshoot and a small yaw, then rests.',
          loop=False, ends_at_rest=True, margin=1.08)
def pop_in_reveal(root, ctx):
    os = ctx.opt.get('overshoot', 0.08)
    t = ctx.plan(0.8, 0.35)

    def pose(tt):
        s = e_over(_x(tt, 0.0, t[1]), os, 1, 3, 0.5)
        yaw = -18.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 3))
        return Vector((0, 0, _pin(ctx, s))), _rot(UP, yaw), s
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2])


@register('product_motion', 'scale_up_reveal', 'Scale-up Reveal', 'reveal',
          'Grows from nothing to full size on the floor in 1.3 s with a long soft ease-out, no overshoot.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.0)
def scale_up_reveal(root, ctx):
    t = ctx.plan(1.3, 0.3)

    def pose(tt):
        s = e_beta(_x(tt, 0.0, t[1]), 2, 4)
        yaw = -10.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 3))
        return Vector((0, 0, _pin(ctx, s))), _rot(UP, yaw), s
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2])


@register('product_motion', 'spin_in_reveal', 'Spin-in Reveal', 'reveal',
          'Pops in from nothing while spinning 270 degrees, overshoots a few degrees and settles.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.08)
def spin_in_reveal(root, ctx):
    t = ctx.plan(0.95, 0.35)

    def pose(tt):
        s = e_over(_x(tt, 0.0, t[1]), 0.07, 1, 3, 0.5)
        yaw = -270.0 + 270.0 * e_over(_x(tt, 0.0, t[2]), 0.0222, 2, 3, 0.6)
        return Vector((0, 0, _pin(ctx, s))), _rot(UP, yaw), s
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2])


@register('product_motion', 'rise_from_below', 'Rise From Below', 'reveal',
          'Emerges from beneath the floor, rises in 1 s with a small overshoot and settles on its base.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def rise_from_below(root, ctx):
    s0 = max(ctx.dims.z / ctx.size + 0.1, 0.35)            # a flat product still travels far enough to read
    t = ctx.plan(1.0)

    def pose(tt):
        z = -s0 + s0 * e_over(_x(tt, 0.0, t[1]), 0.04, 1, 3, 0.6)
        return Vector((0, 0, z)), None, None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[1])


def _lean(tt, ts, te, amp):
    """Forward lean of a sliding body: tips toward its travel while it brakes, tips back a hair, rights itself."""
    return trk(tt, [(0.0, 0.0), (ts + 0.28 * (te - ts), amp), (ts + 0.8 * (te - ts), -0.12 * amp),
                    (te + 0.2, 0.0)])


@register('product_motion', 'slide_in', 'Slide-in', 'reveal',
          'Enters from the left of the frame in 1.1 s with friction, tips forward as it brakes, yaw settles a beat later.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def slide_in(root, ctx):
    r, f = _axes(ctx)
    d = 2.6
    t = ctx.plan(1.1, 0.3)

    def pose(tt):
        e = e_over(_x(tt, 0.0, t[1]), 0.04 / d, 1, 3, 0.72)
        yaw = -20.0 * (1.0 - e_beta(_x(tt, 0.12, t[2]), 2, 3))
        return -r * (d * (1.0 - e)), _rot(f, _lean(tt, 0.0, t[1], 5.0)) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'slide_in_right', 'Slide-in Right', 'reveal',
          'Sweeps in from the back right in an arc (1.2 s), brakes with friction, yaw 30 degrees arrives later.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def slide_in_right(root, ctx):
    r, f = _axes(ctx)
    d = 2.6
    t = ctx.plan(1.2, 0.35)

    def pose(tt):
        e = e_over(_x(tt, 0.0, t[1]), 0.04 / d, 1, 3, 0.72)
        q = e_beta(_x(tt, 0.0, t[1]), 2, 3)
        yaw = 30.0 * (1.0 - e_beta(_x(tt, 0.15, t[2]), 2, 3))
        return r * (d * (1.0 - e)) + f * (1.1 * (1.0 - q)), _rot(f, -_lean(tt, 0.0, t[1], 5.0)) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'slide_in_left', 'Slide-in Left', 'reveal',
          'Sweeps in from the back left in an arc (1.2 s), brakes with friction, yaw -30 degrees arrives later.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def slide_in_left(root, ctx):
    r, f = _axes(ctx)
    d = 2.6
    t = ctx.plan(1.2, 0.35)

    def pose(tt):
        e = e_over(_x(tt, 0.0, t[1]), 0.04 / d, 1, 3, 0.72)
        q = e_beta(_x(tt, 0.0, t[1]), 2, 3)
        yaw = -30.0 * (1.0 - e_beta(_x(tt, 0.15, t[2]), 2, 3))
        return -r * (d * (1.0 - e)) + f * (1.1 * (1.0 - q)), _rot(f, _lean(tt, 0.0, t[1], 5.0)) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'slide_in_bottom', 'Slide-in Bottom', 'reveal',
          'Slides in from the bottom edge, from the foreground along the floor (1.1 s), brakes with friction, tips back as it stops.',
          loop=False, offscreen=True, ends_at_rest=True)
def slide_in_bottom(root, ctx):
    r, f = _axes(ctx)
    d = 1.6
    t = ctx.plan(1.1, 0.3)

    def pose(tt):
        e = e_over(_x(tt, 0.0, t[1]), 0.04 / d, 1, 3, 0.72)
        yaw = -12.0 * (1.0 - e_beta(_x(tt, 0.12, t[2]), 2, 3))
        return -f * (d * (1.0 - e)), _rot(r, -_lean(tt, 0.0, t[1], 5.0)) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'slide_in_top', 'Slide-in Top', 'reveal',
          'Glides down from above the frame in 1 s (no gravity), brakes softly and floats a hair off the floor once.',
          loop=False, offscreen=True, ends_at_rest=True, sweep='spin', margin=1.0)
def slide_in_top(root, ctx):
    t = ctx.plan(1.0, 0.45)

    def pose(tt):
        z = 1.7 * (1.0 - e_beta(_x(tt, 0.0, t[1]), 1, 3)) + hops(tt, t[1], [(0.015, 0.34)])
        yaw = -14.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 3))
        return Vector((0, 0, z)), _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'tilt_reveal', 'Tilt Reveal', 'reveal',
          'Starts pitched and yawed above the floor, rotates and lowers to rest in 1.3 s with a 10% overshoot.',
          loop=False, ends_at_rest=True, sweep='spin', lift=0.25)
def tilt_reveal(root, ctx):
    right, _ = _axes(ctx)
    t = ctx.plan(1.3, 0.2)

    def pose(tt):
        x = _x(tt, 0.0, t[1])
        pitch = 32.0 * (1.0 - e_over(x, 0.1, 2, 3, 0.6))
        yaw = -28.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 3))
        return Vector((0, 0, 0.25 * (1.0 - e_beta(x, 2, 3)))), _rot(right, pitch) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'unfold_tilt_reveal', 'Unfold Tilt Reveal', 'reveal',
          'Lies on its front face and pivots up over the front edge in 1.5 s (78 degrees), yaw unwinds, tiny overshoot.',
          loop=False, ends_at_rest=True, sweep='spin', lift=0.3)
def unfold_tilt_reveal(root, ctx):
    right, f = _axes(ctx)
    half_f = 0.5 * (abs(f.x) * ctx.dims.x + abs(f.y) * ctx.dims.y)
    pivot = -f * half_f - UP * (0.5 * ctx.dims.z)             # front bottom edge (the camera side)
    t = ctx.plan(1.5, 0.2)

    def pose(tt):
        k = 1.0 - e_over(_x(tt, 0.0, t[1]), 0.035, 2, 3, 0.6)
        R = _rot(right, 78.0 * k) @ _rot(UP, -22.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 3)))
        return _about(ctx, pivot, R), R, None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'soft_scale_reveal', 'Soft Scale Reveal', 'reveal',
          'Fade-like entrance: scales from 90% to full size in 1.6 s with a slow in-out ease and a tiny yaw.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.0)
def soft_scale_reveal(root, ctx):
    t = ctx.plan(1.6, 0.2)

    def pose(tt):
        s = 0.9 + 0.1 * e_beta(_x(tt, 0.0, t[1]), 2, 2)
        yaw = -6.0 * (1.0 - e_beta(_x(tt, 0.0, t[2]), 2, 2))
        return Vector((0, 0, _pin(ctx, s))), _rot(UP, yaw), s
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[2])


@register('product_motion', 'exploded_z_reveal', 'Exploded Z Reveal', 'reveal',
          'The parts lift apart along Z (a cap off its bottle, a lid off its case), float for a beat and drop back '
          'into place with a small knock. Needs a product made of 2+ objects; a single object just lifts and settles.',
          loop=False, ends_at_rest=True)
def exploded_z_reveal(root, ctx):
    parts = list(root.children)
    # Check if any part has user animation (without pms_explode)
    user_animated = False
    for ch in parts:
        ad = ch.animation_data
        if ad and ad.action:
            has_fcurves = any(fc.keyframe_points for fc in m.iter_fcurves(ch))
            if has_fcurves and not ch.get('pms_explode'):
                user_animated = True
                break
    if user_animated or len(parts) < 2:
        # FALLBACK: root lifts and settles (bake offsets are fractions of the size)
        ctx.note = ("exploded_z_reveal: needs 2+ parts without their own animation, "
                    "the whole product lifts instead")
        t = ctx.plan(0.3, 0.7, 0.9, 0.45)
        t0, t_up, t_float, t_down = t[1], t[2], t[3], t[4]       # t[0] is the start: t0 ends the wait
        hit = _Hit(ctx, [(t_down, 1.0)], squash=0.015, tilt=0.3, weight=0.7)

        def pose(tt):
            if tt < t_up:
                z = 0.25 * e_beta(_x(tt, t0, t_up), 2, 3)
            elif tt < t_float:
                z = 0.25 * (1.0 + 0.03 * sin(pi * _x(tt, t_up, t_float)) ** 2)     # one soft bob, still at both ends
            else:
                z = 0.25 * (1.0 - _x(tt, t_float, t_down) ** 2)
            return hit.pose(tt, Vector((0, 0, z)))
        bake(root, ctx, pose)
        _life(root, ctx, t_down + 0.2)
        return

    # Sort parts by min world Z of their bounding box
    def min_z_world(ob):
        if ob.type == 'EMPTY':
            return ob.matrix_world.translation.z
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        return min(p.z for p in pts)

    parts.sort(key=min_z_world)
    n = len(parts)
    gap = min(ctx.opt.get('gap', 0.22) * ctx.size, 0.6 * ctx.size / (n - 1))

    # Timing: 0.3 wait, 0.7 rise, 0.9 float, 0.45 fall
    t = ctx.plan(0.3, 0.7, 0.9, 0.45)
    t0, t_up, t_float, t_down = t[1], t[2], t[3], t[4]       # t[0] is the start: t0 ends the wait

    # Root impact on reassembly
    hit = _Hit(ctx, [(t_down, 1.0)], squash=0.015, tilt=0.3, weight=0.7)

    def pose(tt):
        # Root hit on reassembly
        root_loc, root_rot, root_scl = hit.pose(tt, None, None, 1.0)

        for i, ch in enumerate(parts):
            if i == 0:
                # Lowest part stays put - no pms_explode, no animation
                ch.delta_location = (0.0, 0.0, 0.0)
                if 'pms_explode' in ch:
                    del ch['pms_explode']
            else:
                lift = i * gap
                if tt < t_up:
                    z = lift * e_beta(_x(tt, t0, t_up), 2, 3)
                elif tt < t_float:
                    z = lift * (1.0 + 0.03 * sin(pi * _x(tt, t_up, t_float)) ** 2)     # one soft bob, still at both ends
                else:
                    z = lift * (1.0 - _x(tt, t_float, t_down) ** 2)
                ch.delta_location = (0.0, 0.0, z)
                ch['pms_explode'] = True
                ch.keyframe_insert('delta_location', index=2, frame=ctx.f0 + int(round(tt * ctx.fps)))
        # At the end, all back to 0 (but keep pms_explode as marker)
        if tt >= t_down:
            for i, ch in enumerate(parts):
                if i > 0:
                    ch.delta_location = (0.0, 0.0, 0.0)
                    ch.keyframe_insert('delta_location', index=2, frame=ctx.f0 + int(round(tt * ctx.fps)))

        return root_loc, root_rot, root_scl

    bake(root, ctx, pose)
    _life(root, ctx, t_down + 0.2)


# === drop / impact ===========================================================
# Falls are real gravity in cinema time: z = H (1 - x^2) from rest, so the arrival is at full speed and NOT eased; bounces
# are parabolas of the same gravity (a rebound of r*H lasts 2 sqrt(r) times the fall). Every contact is a _Hit.

@register('product_motion', 'drop_impact', 'Drop + Impact', 'impact',
          'Falls 1.4 sizes in 0.64 s, lands with a small hop, the whole body rocks and settles.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def drop_impact(root, ctx):
    H = 1.4
    t = ctx.plan(0.64, 0.7, lead=0.14)
    t0, tc = t[0], t[1]
    seq = [(0.06 * H, 2.0 * (tc - t0) * sqrt(0.06))]
    hit = _Hit(ctx, [(tc, 1.0), (tc + seq[0][1], 0.3)], squash=0.03, tilt=1.2)

    def pose(tt):
        z = H * (1.0 - _x(tt, t0, tc) ** 2) + hops(tt, tc, seq)
        return hit.pose(tt, Vector((0, 0, z)))
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'drop_straight', 'Drop Straight', 'impact',
          'Falls straight down from above in 0.56 s, dead stop on the floor, the whole body squashes and rocks slightly.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def drop_straight(root, ctx):
    H = 1.2
    t = ctx.plan(0.56, 0.6, lead=0.1)
    t0, tc = t[0], t[1]
    hit = _Hit(ctx, [(tc, 1.0)], squash=0.03, tilt=0.8, direction=(0.1, 0.04, -1.0))
    bake(root, ctx, lambda tt: hit.pose(tt, Vector((0, 0, H * (1.0 - _x(tt, t0, tc) ** 2)))))
    _life(root, ctx, t[2])


@register('product_motion', 'drop_bounce', 'Drop + Bounce', 'impact',
          'Falls in 0.6 s and bounces twice (22% then 7% of the height) before it rests; every landing squashes the body.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def drop_bounce(root, ctx):
    H = 1.2
    t = ctx.plan(0.6, 0.9, lead=0.1)
    t0, tc = t[0], t[1]
    fall = tc - t0
    seq = [(r * H, 2.0 * fall * sqrt(r)) for r in (0.22, 0.07)]
    hit = _Hit(ctx, [(tc, 1.0), (tc + seq[0][1], 0.45), (tc + seq[0][1] + seq[1][1], 0.18)], squash=0.025, tilt=0.7)

    def pose(tt):
        return hit.pose(tt, Vector((0, 0, H * (1.0 - _x(tt, t0, tc) ** 2) + hops(tt, tc, seq))))
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'slam_from_above', 'Slam From Above', 'impact',
          'Winds up (rises a little), then smashes down in 0.34 s with no ease-out; the body squashes 5%, rocks and rings out.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def slam_from_above(root, ctx):
    z0, rise = 1.8, 0.12
    t = ctx.plan(0.3, 0.34, 0.7)
    tw, tc = t[1], t[2]
    hit = _Hit(ctx, [(tc, 1.0)], squash=0.05, tilt=2.0, direction=(0.3, 0.12, -1.0), weight=1.3)

    def pose(tt):
        z = z0 + rise * e_smooth(_x(tt, 0.0, tw)) if tt < tw else (z0 + rise) * (1.0 - _x(tt, tw, tc) ** 2)
        return hit.pose(tt, Vector((0, 0, z)))
    bake(root, ctx, pose)
    _life(root, ctx, t[3])


@register('product_motion', 'drop_tilted', 'Drop Tilted', 'impact',
          'Falls tilted and yawed in 0.55 s, straightens just before touching down, lands with a small whole-body rock.',
          loop=False, offscreen=True, ends_at_rest=True, sweep='spin', margin=1.05, lift=0.1)
def drop_tilted(root, ctx):
    right, fwd = _axes(ctx)
    H = 1.0
    t = ctx.plan(0.55, 0.65, lead=0.1)
    t0, tc = t[0], t[1]
    hit = _Hit(ctx, [(tc, 1.0)], squash=0.02, tilt=1.0)

    def pose(tt):
        k = 1.0 - e_beta(_x(tt, t0, tc - 0.12), 2, 2)
        R = _rot(right, 22.0 * k) @ _rot(fwd, -12.0 * k) @ _rot(UP, 25.0 * k)
        return hit.pose(tt, Vector((0, 0, H * (1.0 - _x(tt, t0, tc) ** 2))), R)
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'heavy_land', 'Heavy Land', 'impact',
          'Hangs for a beat, is yanked down 0.55 sizes in 0.38 s and lands like a heavy object: deep squash, slow settle.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def heavy_land(root, ctx):
    t = ctx.plan(0.34, 0.38, 1.0)
    th, tc = t[1], t[2]
    hit = _Hit(ctx, [(tc, 1.0)], squash=0.06, tilt=2.5, direction=(0.35, 0.1, -1.0), weight=1.7)

    def pose(tt):
        z = 0.55 + 0.025 * e_smooth(_x(tt, 0.0, th)) if tt < th else 0.575 * (1.0 - _x(tt, th, tc) ** 2)
        return hit.pose(tt, Vector((0, 0, z)))
    bake(root, ctx, pose)
    _life(root, ctx, t[3])


# === flip ====================================================================

def _flip(root, ctx, axis, turns, h, air, crouch=0.3, squash=0.04, profile=None, tilt=0.8):
    """Crouch (squat 7%), launch (stretch 4%), a hop of height h (raised if the product needs more clearance to turn over)
    that lasts `air` seconds with `turns` turns about `axis`
    (starts just before take-off, passes the final angle by 1.5% at touch-down and settles during the squash), landing as
    a _Hit. profile(x) -> 0..1 replaces that rotation curve (it must end at 1 at touch-down)."""
    t = ctx.plan(crouch, air, 0.7)
    tl, tL = t[1], t[2]
    tr0, tr1 = tl - 0.04, tL + 0.2
    xp = (tL - tr0) / (tr1 - tr0)
    hit = _Hit(ctx, [(tL, 1.0)], squash=squash, tilt=tilt)

    def prog(tt):
        return profile(_x(tt, tl, tL)) if profile else e_over(_x(tt, tr0, tr1), 0.015, 2, 3, xp)
    # a long / flat / tall product needs more air to turn over: raise the hop until the box clears the floor all the way
    # (otherwise the floor clamp would lift it abruptly at the start of the turn)
    need = 0.0
    for k in range(1, 40):
        y = k / 40.0
        R = _rot(axis, 360.0 * turns * prog(tl + y * (tL - tl)))
        req = max(0.0, -min((R @ c).z for c in ctx.info.corners) - 0.5 * ctx.dims.z) / ctx.size
        if 0.06 < y < 0.94:
            need = max(need, req / (4.0 * y * (1.0 - y)))
    h = min(0.6, max(h, 1.05 * need))

    def pose(tt):
        y = (tt - tl) / (tL - tl)
        z = h * 4.0 * y * (1.0 - y) if 0.0 <= y <= 1.0 else 0.0
        sz = trk(tt, [(0.0, 1.0), (tl, 0.93), (tl + 0.14, 1.04, lambda x: e_beta(x, 1, 3)), (tl + 0.45 * (tL - tl), 1.0)])
        return hit.pose(tt, Vector((0, 0, z)), _rot(axis, 360.0 * turns * prog(tt)), sz)
    bake(root, ctx, pose)
    _life(root, ctx, t[3])


@register('product_motion', 'flip', 'Flip', 'flip',
          'Crouches, hops 30% of its size and turns a full forward flip in 0.75 s, lands with a squash and a rock.',
          loop=False, ends_at_rest=True, sweep='sphere', lift=0.3, margin=1.06)
def flip(root, ctx):
    _flip(root, ctx, _axes(ctx)[0], 1.0, 0.30, 0.75)


@register('product_motion', 'flip_back', 'Back Flip', 'flip',
          'Deeper crouch, a higher hop (40%) and a full backward flip in 0.9 s about the screen-horizontal axis.',
          loop=False, ends_at_rest=True, sweep='sphere', lift=0.4, margin=1.02)
def flip_back(root, ctx):
    _flip(root, ctx, _axes(ctx)[0], -1.0, 0.40, 0.9, crouch=0.34, squash=0.05)


@register('product_motion', 'flip_side', 'Side Flip', 'flip',
          'Hops 25% of its size and rolls a full sideways flip in 0.7 s about the depth axis, lands with a squash.',
          loop=False, ends_at_rest=True, sweep='sphere', lift=0.3, margin=1.06)
def flip_side(root, ctx):
    _flip(root, ctx, _axes(ctx)[1], 1.0, 0.25, 0.7, crouch=0.26)


@register('product_motion', 'flip_180_reveal', 'Flip 180 Reveal', 'flip',
          'Wind-up crouch, a small hop and a half turn about the vertical axis that lands showing the back of the product.',
          loop=False, ends_at_rest=False, sweep='spin', margin=1.02, lift=0.15)
def flip_180_reveal(root, ctx):
    _flip(root, ctx, UP, 0.5, 0.12, 0.6, crouch=0.28, squash=0.03)


@register('product_motion', 'coin_flip', 'Coin Flip', 'flip',
          'Tossed high (50% of its size) for 1.3 s and spinning three fast turns about the horizontal axis, caught on its base.',
          loop=False, ends_at_rest=True, sweep='sphere', lift=0.5, margin=1.02)
def coin_flip(root, ctx):
    _flip(root, ctx, _axes(ctx)[0], 3.0, 0.5, 1.3, crouch=0.3, squash=0.035,
          profile=lambda x: 0.35 * x + 0.65 * e_smooth(x))


# === fly-by / passes =========================================================

def _bez(p0, p1, p2, s):
    return p0 * (1 - s) ** 2 + p1 * (2 * (1 - s) * s) + p2 * (s * s)


def _bank(path, tt, dt, gain):
    """Roll about the heading of a path (Vector fn of t): leans into the turn, from the lateral acceleration."""
    p_a, p_0, p_b = path(tt - dt), path(tt), path(tt + dt)
    v = (p_b - p_a) / (2 * dt)
    a = (p_b - 2 * p_0 + p_a) / (dt * dt)
    vh = Vector((v.x, v.y, 0.0))
    if vh.length < 1e-4:
        return Matrix.Identity(3)
    lat = vh.cross(Vector((a.x, a.y, 0.0))).z / vh.length
    return _rot(vh.normalized(), -22.0 * max(-1.0, min(1.0, lat * gain)) * e_smooth(tt / 0.3))


@register('product_motion', 'fly_by_swoop', 'Fly-by Swoop', 'flyby',
          'Swoops in from high behind the left in a banking arc (1.4 s, fast then a long brake) and settles on its pose.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def fly_by_swoop(root, ctx):
    r, f = _axes(ctx)
    p0, p1 = -2.2 * r + 1.8 * f + 0.9 * UP, -0.6 * r - 1.0 * f + 0.1 * UP
    t = ctx.plan(1.4, 0.3)
    dt = 0.5 / ctx.fps
    hit = _Hit(ctx, [(t[1], 1.0)], squash=0.0, tilt=0.6, direction=(r.x, r.y, 0.0))

    def path(tt):
        return _bez(p0, p1, Vector(), e_beta(_x(tt, 0.0, t[1]), 1, 3))

    def pose(tt):
        x = _x(tt, 0.0, t[1])
        yaw = -70.0 * (1.0 - e_beta(_x(tt, 0.0, t[1] + 0.2), 2, 3))
        R = _bank(path, tt, dt, 0.02) @ _rot(f, -24.0 * (1.0 - e_beta(x, 2, 3))) @ _rot(UP, yaw)
        return hit.pose(tt, path(tt), R)
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'fly_through_front', 'Fly-through Front', 'flyby',
          'Comes in low from the left right in front of the camera (1.5 s), S-curves back and settles on its pose.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def fly_through_front(root, ctx):
    r, f = _axes(ctx)
    p0, p1 = -2.0 * r - 1.6 * f + 0.3 * UP, 1.2 * r - 1.2 * f + 0.1 * UP
    t = ctx.plan(1.5, 0.3)
    dt = 0.5 / ctx.fps
    hit = _Hit(ctx, [(t[1], 1.0)], squash=0.0, tilt=0.6, direction=(r.x, r.y, 0.0))

    def path(tt):
        return _bez(p0, p1, Vector(), e_beta(_x(tt, 0.0, t[1]), 2, 3))

    def pose(tt):
        k = 1.0 - e_beta(_x(tt, 0.0, t[1]), 2, 3)
        R = _bank(path, tt, dt, 0.03) @ _rot(f, 16.0 * k) @ _rot(UP, -50.0 * k)
        return hit.pose(tt, path(tt), R)
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'zoom_past_return', 'Zoom-past + Return', 'flyby',
          'Pulls back, rushes toward the camera and past it, then glides back in from far behind (1.5 s) into its pose.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def zoom_past_return(root, ctx):
    r, f = _axes(ctx)
    a, b = -5.0 * f + 1.0 * r + 0.2 * UP, 6.0 * f - 1.5 * r + 0.7 * UP
    t = ctx.plan(0.25, 0.55, 0.35, 1.5, 0.3)             # pull back, rush past the camera, (out of frame), glide back, settle
    tw, te, tr0, tr1 = t[1], t[2], t[3], t[4]

    def pose(tt):
        if tt < tr0:
            x = _x(tt, tw, te)
            back = 0.14 * e_smooth(_x(tt, 0.0, tw)) * (1.0 - x)           # a small pull away from the camera first
            return a * (x * x) + f * back, _rot(UP, 40.0 * x * x), None
        e = 1.0 - e_beta(_x(tt, tr0, tr1), 1, 3)
        return b * e, _rot(UP, 100.0 * e), None
    bake(root, ctx, pose)
    _life(root, ctx, t[5])


# === stylised ================================================================

@register('product_motion', 'glitch_step', 'Glitch Step', 'stylized',
          'A 0.55 s burst of stepped jitter (position, yaw, width) that builds, fades and snaps clean onto the pose.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.06)
def glitch_step(root, ctx):
    rng = Random(11)
    r, _ = _axes(ctx)
    t = ctx.plan(0.55, lead=0.15)
    n = max(1, round((t[1] - t[0]) * ctx.fps))
    steps, k = [], 0
    while k < n:
        a = 0.35 + 0.65 * sin(pi * k / n)
        steps.append((k, a, [rng.uniform(-1, 1) for _ in range(4)]))
        k += rng.choice((1, 2, 2, 3))

    def pose(tt):
        i = int((tt - t[0]) * ctx.fps + 1e-6)
        if i < 0 or i >= n:
            return None, None, None
        s = [st for st in steps if st[0] <= i][-1]
        a, d = s[1], s[2]
        return (r * (0.05 * a * d[0]) + Vector((0, 0, 0.02 * a * abs(d[1]))), _rot(UP, 10.0 * a * d[2]),
                Vector((1.0 + 0.06 * a * d[3], 1.0, 1.0)))
    bake(root, ctx, pose, interp='CONSTANT', ground=False)
    _life(root, ctx, t[1])


@register('product_motion', 'bounce_loop', 'Bounce Loop', 'stylized',
          'Hops (about every 1.25 s) with a tiny squash after every landing and a stretch in the air, seamless.',
          loop=True, ends_at_rest=True, margin=1.03, lift=0.18)
def bounce_loop(root, ctx):
    n = ctx.opt.get('hops', max(2, min(20, round(ctx.dur_s / 1.25))))
    hgt = ctx.opt.get('height', 0.16)
    per = ctx.dur_s / n

    def pose(t):
        y = (t % per) / per if t < ctx.dur_s - 1e-9 else 0.0
        z = hgt * 4.0 * y * (1.0 - y)
        sz = 1.0 - (0.05 * sin(pi * y / 0.14) ** 2 if y < 0.14 else 0.0) + 0.03 * sin(pi * y)
        loc, scl = _scale(ctx, sz, Vector((0, 0, z)))
        return loc, None, scl
    bake(root, ctx, pose, ground=False)


@register('product_motion', 'magnetic_snap', 'Magnetic Snap', 'stylized',
          'Shivers to the side, is pulled in at full acceleration and snaps onto its pose with a bounce back.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.1)
def magnetic_snap(root, ctx):
    r, _ = _axes(ctx)
    off = 0.55 * r + 0.40 * UP
    t = ctx.plan(0.55, 0.36, 0.8, lead=0.1)
    ts, tp, tc = t[0], t[1], t[2]
    hit = _Hit(ctx, [(tc, 1.0)], squash=0.0, tilt=1.2, direction=-off, push=0.008, weight=1.0)

    def pose(tt):
        if tt < tp:
            a = e_smooth(_x(tt, ts, tp))
            sh = 0.02 * a * (sin(tau * 6.0 * tt) + 0.5 * sin(tau * 9.3 * tt + 1.0))
            yaw = 28.0 + 12.0 * a * (sin(tau * 5.0 * tt) + 0.4 * sin(tau * 8.1 * tt))
            return off + Vector((0, 0, sh)), _rot(UP, yaw), None
        s = _x(tt, tp, tc) ** 2.2
        return hit.pose(tt, off * (1.0 - s), _rot(UP, 28.0 * (1.0 - s)))
    bake(root, ctx, pose)
    _life(root, ctx, t[3])


@register('product_motion', 'tumble_settle', 'Tumble + Settle', 'stylized',
          'Tossed in from the right, tumbles on all axes for 0.85 s, bounces once and settles upright on its base.',
          loop=False, offscreen=True, ends_at_rest=True, sweep='spin', margin=1.05, lift=0.1)
def tumble_settle(root, ctx):
    r, _ = _axes(ctx)
    H = 0.9
    t = ctx.plan(0.85, 0.9, lead=0.05)
    t0, tc = t[0], t[1]
    seq = [(0.12 * H, 2.0 * (tc - t0) * sqrt(0.12))]
    hit = _Hit(ctx, [(tc, 1.0), (tc + seq[0][1], 0.2)], squash=0.02, tilt=1.0)

    def pose(tt):
        x = _x(tt, t0, tc)
        k = 1.0 - e_beta(x, 2, 2)
        R = _rot(UP, 120.0 * k) @ _rot((0, 1, 0), 180.0 * k) @ _rot((1, 0, 0), 300.0 * k)
        loc = r * (H * k) + Vector((0, 0, H * (1.0 - x * x) + hops(tt, tc, seq)))
        return hit.pose(tt, loc, R)
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'showcase_3_pose', 'Showcase 3-Pose', 'stylized',
          'Three hero poses (left, right, leaning forward) reached in 0.95 s each and held while they creep to a stop, then back to the base pose.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.08, lift=0.06)
def showcase_3_pose(root, ctx):
    right, _ = _axes(ctx)
    trans = 0.95
    allp = [(-32.0, 5.0), (30.0, -3.0), (0.0, 12.0)]
    n = 3 if ctx.t_end >= 5.2 else 2 if ctx.t_end >= 3.4 else 1        # short shots show fewer poses, never a rushed one
    hold = max(0.35, min(2.0, (ctx.t_end - 0.25 - (n + 1) * trans) / n))
    seq = []
    for k in range(n):
        seq += [trans, hold]
    t = ctx.plan(*seq, trans, lead=0.25)
    poses = [(0.0, 0.0)] + allp[:n] + [(0.0, 0.0)]
    starts = t[0:-1:2]
    ends = t[1::2]
    ease = lambda x: e_beta(x, 2, 3)

    def pose(tt):
        yaw, pitch = 0.0, 0.0
        for (ya, pa), (yb, pb), s0, s1 in zip(poses, poses[1:], starts, ends):
            e = ease(_x(tt, s0, s1))
            yaw += (yb - ya) * e
            pitch += (pb - pa) * e
        return None, _rot(right, pitch) @ _rot(UP, yaw), None
    bake(root, ctx, pose)
    _life(root, ctx, t[-1])


# === exits and returns =======================================================

@register('product_motion', 'exit_and_return', 'Exit + Return', 'return',
          'Leans back, accelerates out of the frame to the right (0.5 s), then re-enters from the left in 1.15 s and settles on its pose.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def exit_and_return(root, ctx):
    r, _ = _axes(ctx)
    t = ctx.plan(0.28, 0.5, 0.45, 1.15, 0.2)             # wind-up, rush out, (out of frame), glide back in, settle
    tw, te, tr0, tr1 = t[1], t[2], t[3], t[4]

    def pose(tt):
        if tt < tr0:
            s = _x(tt, tw, te) ** 2.2
            back = -0.12 * e_smooth(_x(tt, 0.0, tw)) * (1.0 - s)          # leans back / away from where it is going first
            return r * (3.4 * s + back), _rot(UP, 25.0 * s - 5.0 * e_smooth(_x(tt, 0.0, tw)) * (1.0 - s)), None
        e = e_over(_x(tt, tr0, tr1), 0.03, 1, 3, 0.7)
        return -r * (3.4 * (1.0 - e)), _rot(UP, -25.0 * (1.0 - e)), None
    bake(root, ctx, pose)
    _life(root, ctx, t[5])


@register('product_motion', 'exit_up_and_return', 'Exit Up + Return', 'return',
          'Crouches, shoots up out of the frame (0.5 s), then drops back from above in 0.75 s, bounces once and rests on its pose.',
          loop=False, offscreen=True, ends_at_rest=True, margin=1.04)
def exit_up_and_return(root, ctx):
    H = 2.8
    t = ctx.plan(0.28, 0.5, 0.4, 0.75, 0.7)              # crouch, shoot up, (out of frame), drop back, settle
    tw, te, tf, tc = t[1], t[2], t[3], t[4]
    seq = [(0.08 * H, 2.0 * (tc - tf) * sqrt(0.08))]
    hit = _Hit(ctx, [(tc, 1.0), (tc + seq[0][1], 0.3)], squash=0.02, tilt=0.8)

    def pose(tt):
        if tt < tf:
            s = _x(tt, tw, te) ** 2.0
            sz = trk(tt, [(0.0, 1.0), (tw, 0.93), (tw + 0.15, 1.05, lambda x: e_beta(x, 1, 3)), (tw + 0.45, 1.0)])
            loc, scl = _scale(ctx, sz, Vector((0, 0, H * s)))
            return loc, _rot(UP, 25.0 * s), scl
        x = _x(tt, tf, tc)
        z = H * (1.0 - x * x) + hops(tt, tc, seq)
        return hit.pose(tt, Vector((0, 0, z)), _rot(UP, -90.0 * (1.0 - e_beta(x, 1, 3))))
    bake(root, ctx, pose)
    _life(root, ctx, t[5])


@register('product_motion', 'tilt_to_hero', 'Tilt to Hero', 'return',
          'Eases from an off-angle (leaning, pitched and yawed) into the straight hero pose in 1.5 s with a micro-overshoot.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.05, lift=0.1)
def tilt_to_hero(root, ctx):
    right, f = _axes(ctx)
    t = ctx.plan(1.5, 0.2)

    def pose(tt):
        k = 1.0 - e_over(_x(tt, 0.0, t[1]), 0.04, 2, 3, 0.6)
        return None, _rot(right, 10.0 * k) @ _rot(f, 12.0 * k) @ _rot(UP, -35.0 * k), None
    bake(root, ctx, pose)
    _life(root, ctx, t[2])


@register('product_motion', 'spin_down_to_hero', 'Spin Down to Hero', 'return',
          'Starts spinning fast, brakes over 1.5 turns in 1.9 s and stops on its pose with a small overshoot.',
          loop=False, ends_at_rest=True, sweep='spin', margin=1.02)
def spin_down_to_hero(root, ctx):
    t = ctx.plan(1.9)

    def pose(tt):
        return None, _rot(UP, 540.0 * (1.0 - e_over(_x(tt, 0.0, t[1]), 0.0075, 1, 2, 0.85))), None
    bake(root, ctx, pose, ground=False)
    _life(root, ctx, t[1])
