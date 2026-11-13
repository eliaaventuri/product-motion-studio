"""CAMERA MOTION presets: functions (pivot, cam, target, ctx) that animate the camera rig.

SCHEMA   @register('camera_motion', id, name, category, desc, loop=bool)
RIG      target = Empty at the look-at point (child pivot); pivot.rotation_euler = (-el, 0, az) in radians,
         origin on the target; cam = child of pivot at local (0, -D, 0), looking at the pivot origin.
         So: az -> pivot.rotation_euler[2], elevation -> pivot.rotation_euler[0] (= -el),
         distance -> cam.location[1] (= -D). There is NO Track To (handheld/whip need free rotation).
RULES    - Animate only those channels (or `target`/`cam.data.lens`/`PMS_DOF_Empty`/noise on cam rotation).
         - ctx.az/ctx.el/ctx.dist are the base shot (radians / fitted distance). For any move that changes
           az, el or distance, set the distance with ctx.fit(az=(a0, a1), el=(e0, e1)) (degrees, number or
           sweep) so the product stays framed in EVERY frame (the tests check it).
         - A loop (loop=True) must come back to the identical pose at ctx.f1 (full turns, LINEAR keys).
         - Moves are relative to the base shot, so they work with every camera_shot and every format.

TIME LAW (what makes the moves feel shot, not generated). A move is NOT stretched over the clip: it has a speed in
         seconds (`_Law`): the main movement lasts amount/peak seconds; the rest of a long clip is a very slow drift
         that decelerates to rest (`tail`, ~10 % of the travel), and on a SHORT clip the travel is scaled down so the
         peak speed never exceeds `peak_max` (no jerk-and-flick at 2 s, no imperceptible crawl at 20 s).
         Speed profiles are C2 (velocity ramps with smootherstep): acceleration and jerk are continuous, there is
         no stop-and-go. Keys are written as Hermite curves (free handles = exact slopes), 5-15 per channel.
FAMILIES (exceptions declared, checked by tests/test_camera_quality.py)
         dolly/orbit/crane/slide ... smooth ramps, peak angular speed <= ~30 deg/s (orbits <= 29), push-in relative
                                      rate 0.4-12 %/s, no abrupt start/stop;
         orbit_360_loop .............. LINEAR, constant speed fixed by the clip length (a loop must close), clockwise
                                      so that it does not cancel a (counter-clockwise) Spin Loop of the product;
         whip_orbit_finale ........... declared whip: up to ~170 deg/s for ~1 s;
         dolly_zoom / rack_focus ..... the only ones that change the lens / the focus (declared);
         handheld .................... small mixed-frequency noise (< 0.9 deg p-p, no digital jitter).
"""

from math import asin, cos, degrees, log, pi, radians, sin
import bpy
import numpy as np
from . import register
from .. import core, motion as m


@register('camera_motion', 'static', 'Static', 'hold', 'Locked-off camera.', loop=True)
def static(pivot, cam, target, ctx):
    pass


# === time laws ==============================================================

def _clip_s(ctx):
    """Length of the animation in seconds (first to last frame)."""
    return max(1, ctx.f1 - ctx.f0) / ctx.fps


def _secs(ctx, s):
    """Fraction (0..1) of the clip taken by s seconds, clamped: laws are written in seconds, the clip length
    only decides how much of them fits (use with ctx.t)."""
    return min(1.0, max(0.0, s / _clip_s(ctx)))


def _clamp01(x):
    return min(1.0, max(0.0, x))


def _smoother(x):
    """Smootherstep 0..1 (zero velocity AND acceleration at both ends)."""
    x = _clamp01(x)
    return x * x * x * (x * (6 * x - 15) + 10)


def _smoother_int(y):
    """Integral of _smoother from 0 to y (0..0.5)."""
    y = _clamp01(y)
    return y ** 4 * (y * y - 3 * y + 2.5)


def _shape(x, ra, rb):
    """Progress 0..1 of a move whose speed ramps up over the first `ra` and down over the last `rb` of it
    (smootherstep ramps, constant speed between: ra = rb = 0.5 is a bell, 0.2 a near-trapezoid)."""
    x = _clamp01(x)
    tot = 1 - (ra + rb) / 2
    if ra > 0 and x < ra:
        s = ra * _smoother_int(x / ra)
    elif x <= 1 - rb:
        s = ra / 2 + (x - ra)
    else:
        s = tot - rb * _smoother_int((1 - x) / rb)
    return s / tot


class _Law:
    """Progress p(frame) 0..1 of one move, in seconds (see the module docstring).
    amount, peak: size of the travel and target PEAK speed of the main part (same unit, per second); ramp = (ra, rb)
    speed ramps; peak_max caps the peak on short clips by scaling the travel (self.k <= 1 is that factor);
    tail = share of the travel done by the slow drift over the whole clip; start_s/end_s = leading/trailing
    hold; min_s = minimum duration of the main part; fill = the move takes the whole clip (moving hold);
    timed = (start_s, duration_s) fixes the timing (focus pulls, whips): k = 1, no tail."""

    def __init__(self, ctx, amount=1.0, peak=1.0, peak_max=None, ramp=(0.35, 0.35), tail=0.10, start_s=0.0,
                 end_s=0.0, min_s=0.0, fill=False, timed=None):
        self.ctx, self.ramp = ctx, ramp
        d = _clip_s(ctx)
        ra, rb = ramp
        ratio = 1 / (1 - (ra + rb) / 2)
        self.k, self.tau = 1.0, 0.0
        if timed is not None:
            self.t0_s, self.T_s = timed
            return
        self.t0_s = min(start_s, 0.35 * d)
        avail = d - self.t0_s - min(end_s, 0.25 * d)
        amount = abs(amount)
        if fill:
            self.T_s = avail
            return
        pm = peak_max or 1.7 * peak
        t_nom = max(amount * ratio / peak, min(min_s, avail))
        if t_nom * (1 - tail) + 1.0 <= avail and tail > 0:        # room for the slow drift after the main move
            self.tau = tail
            self.T_s = max((1 - tail) * amount * ratio / peak, min(min_s, avail))
        else:
            self.T_s = min(t_nom, avail)
            if amount > 1e-12:
                self.k = min(1.0, pm * self.T_s / (amount * ratio))

    def _main(self, f, ramp=None):
        ra, rb = ramp or self.ramp
        t0 = self.ctx.f0 + self.t0_s * self.ctx.fps
        return _shape((f - t0) / max(1e-9, self.T_s * self.ctx.fps), ra, rb)

    def p(self, f, ramp=None):
        """Progress at frame f (float)."""
        v = self._main(f, ramp)
        if self.tau:
            v = (1 - self.tau) * v + self.tau * _smoother((f - self.ctx.f0) / max(1, self.ctx.f1 - self.ctx.f0))
        return v

    def keys(self):
        """Key frames (ints) good enough to carry the curve as Hermite segments."""
        ctx = self.ctx
        ra, rb = self.ramp
        xs = [ra * i / 4 for i in range(5)] if ra > 0 else [0.0]
        mid = 1 - ra - rb
        xs += [ra + mid * i / 4 for i in range(1, 4)] if mid > 0.12 else []
        xs += [1 - rb + rb * i / 4 for i in range(5)] if rb > 0 else [1.0]
        t0, tf = ctx.f0 + self.t0_s * ctx.fps, self.T_s * ctx.fps
        fr = [ctx.f0, ctx.f1] + [t0 + x * tf for x in xs]
        if self.tau:
            fr += [ctx.f0 + (ctx.f1 - ctx.f0) * u for u in (0.25, 0.5, 0.75)]
        return _thin(ctx, fr)


def _thin(ctx, frames, gap=2):
    """Sorted integer frames inside the clip, at least `gap` apart (the clip ends are always kept)."""
    out = []
    for f in sorted({min(ctx.f1, max(ctx.f0, int(round(f)))) for f in frames}):
        if out and f - out[-1] < gap:
            if f == ctx.f1:
                out.pop()
            else:
                continue
        out.append(f)
    return out


def _grid(ctx, per_s=3.0):
    """Evenly spaced key frames (for oscillations), about per_s keys per second."""
    n = max(4, int((ctx.f1 - ctx.f0) / ctx.fps * per_s))
    return _thin(ctx, [ctx.f0 + (ctx.f1 - ctx.f0) * i / n for i in range(n + 1)])


def _union(*lists):
    return sorted({f for lst in lists for f in lst})


def _put(idb, path, index, fn, frames):
    """Keys of a channel as Hermite segments: value fn(frame) and its exact slope at each frame (free handles)."""
    pts = [(f, fn(f)) for f in frames]
    fc, kps = m._keys(idb, path, index, pts)
    eps = 0.05
    n = len(kps)
    for i, (kp, (f, _)) in enumerate(zip(kps, pts)):
        sl = (fn(f + eps) - fn(f - eps)) / (2 * eps)
        hl = (kp.co.x - kps[i - 1].co.x) / 3 if i else (kps[1].co.x - kp.co.x) / 3
        hr = (kps[i + 1].co.x - kp.co.x) / 3 if i < n - 1 else hl
        kp.handle_left_type = kp.handle_right_type = 'FREE'
        kp.handle_left = (kp.co.x - hl, kp.co.y - sl * hl)
        kp.handle_right = (kp.co.x + hr, kp.co.y + sl * hr)
    fc.update()
    return fc


def _drive(ctx, pivot, cam, az=None, el=None, dist=None, frames=None, dist_frames=None):
    """Key azimuth/elevation (degrees) and distance as functions of the frame (None = untouched); the distance has its own
    key frames when it follows a fitted curve (dist_frames)."""
    frames = frames or _grid(ctx)
    if az is not None:
        _put(pivot, 'rotation_euler', 2, lambda f: radians(az(f)), frames)
    if el is not None:
        _put(pivot, 'rotation_euler', 0, lambda f: -radians(el(f)), frames)
    if dist is not None:
        _put(cam, 'location', 1, lambda f: -dist(f), dist_frames or frames)


EL_MAX = 88.0                       # highest elevation (degrees) any move may reach


# === geometry helpers =======================================================

def _closer(ctx, wanted, d=None, **fit):
    """Largest fraction <= wanted by which the camera may come closer than d (default: the shot distance)
    before the product overfills the frame by more than ~8% (real perspective, via ctx.fit). A shot that is
    already cropped on purpose (macro) may be pushed by 5% of the frame more."""
    d = ctx.dist if d is None else d
    pad = ctx.padding
    d_min = ctx.fit(padding=min(pad, -0.08) if pad >= -0.08 else pad - 0.05, strict=True, **fit)
    return max(0.0, min(wanted, 1 - d_min / d))


def _el_floor(ctx, d, floor_gap=0.02):
    """Lowest elevation (degrees) at which a camera at distance d stays above the floor."""
    min_z = ctx.info.base_z + floor_gap * ctx.size
    return degrees(asin(max(-1.0, min(1.0, (min_z - ctx.target.z) / d))))


def _span(a, b, k, anchor):
    """(start, end) of a travel a -> b scaled by k, keeping the start (anchor='start') or the end fixed."""
    return (a, a + k * (b - a)) if anchor == 'start' else (b - k * (b - a), b)


def _rng(a, b):
    return (a, b) if abs(b - a) > 1e-9 else a


def _curve_fn(frames, values):
    """Function of the frame that interpolates the per-frame samples; mirrored past the ends (zero slope at the first and
    last frame, so the key handles there are flat: the camera starts and stops from rest)."""
    f0, f1 = frames[0], frames[-1]
    return lambda f: float(np.interp(2 * f0 - f if f < f0 else 2 * f1 - f if f > f1 else f, frames, values))


def _dist_frames(ctx, frames, values):
    """Key frames of a fitted distance curve: the law's own plus one every ~0.4 s (none when the curve is flat)."""
    if float(np.ptp(values)) < 1e-4 * float(values.max()):
        return [ctx.f0, ctx.f1]
    return _thin(ctx, list(frames) + [ctx.f0 + i * ctx.fps * 0.4 for i in range(int((ctx.f1 - ctx.f0) / (ctx.fps * 0.4)) + 1)], gap=3)


def _arc(ctx, pivot, cam, az=None, el=None, closer=0.0, amount=None, peak=14.0, peak_max=None, ramp=(0.38, 0.42),
         el_ramp=None, anchor='start', tail=0.10, start_s=0.0, min_s=0.0):
    """Orbit / crane / arc with a time law. az, el = (start, end) degrees (absolute); closer = fraction by which the
    camera comes closer over the move (the distance is fitted for the whole travel); amount = size of the main
    quantity that sets the duration (default: the larger of the az and el travels, degrees); peak = its peak
    speed (deg/s); anchor = which end of the travel keeps its value when a short clip scales the travel down."""
    az = (ctx.az_deg, ctx.az_deg) if az is None else az
    el = (ctx.el_deg, ctx.el_deg) if el is None else el
    el = (min(el[0], EL_MAX), min(el[1], EL_MAX))          # never over the top (the view would flip)
    d = ctx.fit(az=_rng(*az), el=_rng(*el))
    for _ in range(2):                                    # never below the floor: raise the lowest elevation, refit
        lo = _el_floor(ctx, d)
        if min(el) >= lo:
            break
        el = (max(el[0], lo), max(el[1], lo))
        d = ctx.fit(az=_rng(*az), el=_rng(*el))
    travel = max(abs(az[1] - az[0]), abs(el[1] - el[0]))   # what is left of the move after the limits above
    amount = travel if amount is None else min(amount, travel)
    law = _Law(ctx, amount, peak, peak_max, ramp, tail, start_s, 0.0, min_s)
    az = _span(az[0], az[1], law.k, anchor)                # short clip: the travel shrinks towards the fixed end
    el = _span(el[0], el[1], law.k, anchor)
    fr = ctx.track.frames
    p_el = (lambda x: law.p(x, el_ramp)) if el_ramp else law.p
    frames = _union(law.keys(), _Law(ctx, 1, 1, ramp=el_ramp, timed=(law.t0_s, law.T_s)).keys()) if el_ramp \
        else law.keys()
    az_f = lambda x: az[0] + (az[1] - az[0]) * law.p(x)       # noqa: E731
    el_f = lambda x: el[0] + (el[1] - el[0]) * p_el(x)        # noqa: E731
    az_a, el_a, p_a = (np.array([fn(x) for x in fr]) for fn in (az_f, el_f, law.p))
    # the distance follows the product along the REAL path of the camera: smooth curve, never below what the frame needs
    # at that frame (so the product keeps about the same size from start to end instead of shrinking at the end of the move)
    dist_a = ctx.envelope(ctx.curve(az_a, el_a))
    if closer:                                            # comes closer by `closer` * p(frame), as far as the frame allows
        loose = ctx.curve(az_a, el_a, padding=min(ctx.padding, -0.08) if ctx.padding >= -0.08 else ctx.padding - 0.05, strict=True)
        room = np.where(p_a > 0.05, (1 - loose / dist_a) / np.maximum(p_a, 1e-9), 1.0)
        dist_a = dist_a * (1 - max(0.0, min(closer * law.k, float(room.min()))) * p_a)
    _drive(ctx, pivot, cam,
           az=az_f if az[0] != az[1] else None,
           el=el_f if el[0] != el[1] else None,
           dist=_curve_fn(fr, dist_a), frames=frames, dist_frames=_dist_frames(ctx, frames, dist_a))
    cam.location[1] = -dist_a[0]
    pivot.rotation_euler[2] = radians(az_f(ctx.f0) if az[0] != az[1] else az[0])
    pivot.rotation_euler[0] = -radians(el_f(ctx.f0) if el[0] != el[1] else el[0])
    return law


# === dolly ==================================================================

def _dolly(ctx, cam, f, peak, ramp, pull=False, peak_max=None, min_s=4.0, tail=0.10, start_s=0.0, fill=False):
    """Distance d0 -> d0*(1-f) (pull: the other way round) with a time law; f = fraction closer."""
    if f <= 1e-6:
        return None
    law = _Law(ctx, f, peak, peak_max, ramp, tail, start_s, 0.0, min_s, fill=fill)
    d0, fe = ctx.dist, f * law.k
    if pull:
        fn = lambda x: d0 * (1 - fe * (1 - law.p(x)))      # noqa: E731
    else:
        fn = lambda x: d0 * (1 - fe * law.p(x))            # noqa: E731
    _put(cam, 'location', 1, lambda x: -fn(x), law.keys())
    cam.location[1] = -fn(ctx.f0)
    return law


@register('camera_motion', 'push_in', 'Push-in', 'dolly',
          'Classic steady push-in (up to 16% closer, slower on long clips): eases out of a standstill, glides, settles.',
          loop=False)
def push_in(pivot, cam, target, ctx):
    f = _closer(ctx, ctx.opt.get('amount', 0.16))
    _dolly(ctx, cam, f, peak=0.040, peak_max=0.10, ramp=(0.45, 0.40))


@register('camera_motion', 'pull_back', 'Pull-back', 'dolly',
          'Starts tight and eases back to the full shot, with a long gentle landing.', loop=False)
def pull_back(pivot, cam, target, ctx):
    f = _closer(ctx, ctx.opt.get('amount', 0.16))
    _dolly(ctx, cam, f, peak=0.040, peak_max=0.10, ramp=(0.30, 0.55), pull=True)


@register('camera_motion', 'orbit_90', 'Orbit 90', 'orbit',
          'Quarter orbit with a slight rise (4 degrees): the camera glides, never exceeds a credible speed '
          '(less than 90 degrees on very short clips).', loop=False)
def orbit_90(pivot, cam, target, ctx):
    deg, rise = ctx.opt.get('degrees', 90), ctx.opt.get('rise', 4)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + deg), el=(ctx.el_deg, ctx.el_deg + rise),
         amount=abs(deg), peak=14, peak_max=26, ramp=(0.38, 0.42))


@register('camera_motion', 'orbit_360_loop', 'Orbit 360 Loop', 'orbit',
          'Constant-speed full orbit (clockwise, with a gentle breathing of the height), seamless loop. '
          'Clockwise on purpose: it does not cancel a counter-clockwise product spin (with Spin Loop the product '
          'appears to turn twice per loop).', loop=True)
def orbit_360_loop(pivot, cam, target, ctx):
    sgn = -1 if ctx.opt.get('direction', -1) < 0 else 1
    breath = 3.5                                            # degrees: the height rises and comes back once per turn
    fr = ctx.track.frames
    x = (fr - ctx.f0) / max(1, ctx.f1 - ctx.f0)
    # constant distance (a camera on a circular track): the largest the frame ever needs along the whole turn
    cam.location[1] = -float(ctx.curve(ctx.az_deg + sgn * 360 * x, ctx.el_deg + breath * (1 - np.cos(2 * np.pi * x)) / 2).max())
    fc, (k0, k1) = m._keys(pivot, 'rotation_euler', 2,
                           [(ctx.f0, ctx.az), (ctx.f1, ctx.az + sgn * radians(360))], interp='LINEAR')
    fc.update()
    pivot.rotation_euler[2] = ctx.az

    def el(f):
        x = (f - ctx.f0) / max(1, ctx.f1 - ctx.f0)
        return ctx.el_deg + breath * (1 - cos(2 * pi * x)) / 2
    _put(pivot, 'rotation_euler', 0, lambda f: -radians(el(f)), _grid(ctx, 2.0))
    pivot.rotation_euler[0] = -ctx.el


@register('camera_motion', 'crane_up', 'Crane Up', 'crane',
          'Camera rises 28 degrees on a boom with a touch of side drift (5 degrees) so it reads as 3D, '
          'product always framed.', loop=False)
def crane_up(pivot, cam, target, ctx):
    rise = ctx.opt.get('degrees', 28)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + 5), el=(ctx.el_deg, ctx.el_deg + rise), amount=rise,
         peak=8, peak_max=14, ramp=(0.40, 0.40))


# === more dolly moves =======================================================

@register('camera_motion', 'push_in_slow', 'Push-in Slow', 'dolly',
          'Moving hold: the camera creeps in over the whole clip (3% on a 2 s clip, up to 10% on a long one), '
          'the premium pack-shot drift.', loop=False)
def push_in_slow(pivot, cam, target, ctx):
    wanted = ctx.opt.get('amount', min(0.10, max(0.03, 0.006 * _clip_s(ctx))))
    _dolly(ctx, cam, _closer(ctx, wanted), peak=0.01, ramp=(0.5, 0.5), fill=True)


@register('camera_motion', 'push_in_fast', 'Push-in Fast', 'dolly',
          'Punchy push-in (up to 30% closer in about 2.5 s) that lands on the product and keeps creeping in.',
          loop=False)
def push_in_fast(pivot, cam, target, ctx):
    f = _closer(ctx, ctx.opt.get('amount', 0.30))
    _dolly(ctx, cam, f, peak=0.16, peak_max=0.30, ramp=(0.30, 0.60), min_s=1.5, tail=0.08)


@register('camera_motion', 'pull_back_reveal', 'Pull-back Reveal', 'dolly',
          'Holds tight on the product for a beat, then pulls back to the full shot with a long ease: reveal.',
          loop=False)
def pull_back_reveal(pivot, cam, target, ctx):
    f = _closer(ctx, ctx.opt.get('amount', 0.30))
    hold = min(0.7, 0.2 * _clip_s(ctx))
    _dolly(ctx, cam, f, peak=0.12, peak_max=0.20, ramp=(0.45, 0.45), pull=True, start_s=hold, min_s=3.0)


# === orbits =================================================================

@register('camera_motion', 'orbit_45_left', 'Orbit 45 Left', 'orbit',
          'Slow precision orbit, camera drifts 45 degrees to the left (bell-shaped speed).', loop=False)
def orbit_45_left(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 45)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg - deg), amount=deg, peak=7, ramp=(0.5, 0.5))


@register('camera_motion', 'orbit_45_right', 'Orbit 45 Right', 'orbit',
          'Slow orbit 45 degrees to the right that settles into the pose (long deceleration). '
          'Counter-rotates with Luxury Drift: pair it with the left version for a yawing product.', loop=False)
def orbit_45_right(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 45)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + deg), amount=deg, peak=7, ramp=(0.30, 0.55))


@register('camera_motion', 'orbit_90_left', 'Orbit 90 Left', 'orbit',
          'Quarter orbit to the left that arrives softly on the final pose.', loop=False)
def orbit_90_left(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 90)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg - deg), amount=deg, peak=12, peak_max=24, ramp=(0.25, 0.55))


@register('camera_motion', 'orbit_180_right', 'Orbit 180 Right', 'orbit',
          'Half orbit to the right, from the front to the back of the product, near-constant speed '
          '(a little less than 180 degrees when the clip is short).', loop=False)
def orbit_180_right(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 180)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + deg), amount=deg, peak=26, peak_max=29, ramp=(0.25, 0.30))


@register('camera_motion', 'orbit_rise', 'Orbit + Rise', 'orbit',
          'Quarter orbit to the right while the camera climbs 20 degrees (the rise comes in a little later): '
          'classic hero reveal.', loop=False)
def orbit_rise(pivot, cam, target, ctx):
    deg, rise = ctx.opt.get('degrees', 90), ctx.opt.get('rise', 20)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + deg), el=(ctx.el_deg, ctx.el_deg + rise), amount=abs(deg),
         peak=14, peak_max=24, ramp=(0.38, 0.42), el_ramp=(0.60, 0.30))


@register('camera_motion', 'top_down_spiral', 'Top-down Spiral', 'orbit',
          'Camera spirals up and over the product (up to 150 degrees) to end almost top-down.', loop=False)
def top_down_spiral(pivot, cam, target, ctx):
    deg, e1 = ctx.opt.get('degrees', 150), ctx.opt.get('end_el', 78)
    e1 = max(e1, ctx.el_deg)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg + deg), el=(ctx.el_deg, e1), amount=abs(deg),
         peak=20, peak_max=26, ramp=(0.40, 0.40), el_ramp=(0.60, 0.30))


@register('camera_motion', 'pendulum', 'Pendulum', 'orbit',
          'Camera sways like a pendulum set in motion: grows to 22 degrees each side, fastest in the centre, '
          'then loses energy and comes to rest on the shot.', loop=False)
def pendulum(pivot, cam, target, ctx):
    a = ctx.opt.get('degrees', 22)
    d = _clip_s(ctx)
    cycles = max(1.25, round(d / 6.4 * 4) / 4)                # one swing = 3.2 s, quarter-cycle resolution
    a = min(a, 22 * (d / cycles) / 6.4)                       # short clip: smaller swings, same peak speed
    a = max(a, 4.0)
    sag = ctx.opt.get('sag', 2.5)                             # the camera hangs lower in the centre: higher at the apex

    def env(x):
        return _smoother(x / 0.26) * (1 - _smoother((x - 0.40) / 0.60))

    def off(f):
        x = (f - ctx.f0) / max(1, ctx.f1 - ctx.f0)
        return -a * env(x) * sin(2 * pi * cycles * x)
    cam.location[1] = -ctx.fit(az=(ctx.az_deg - a, ctx.az_deg + a), el=(ctx.el_deg, ctx.el_deg + sag))
    frames = _thin(ctx, [ctx.f0 + (ctx.f1 - ctx.f0) * i / max(8, int(cycles * 12)) for i in range(max(8, int(cycles * 12)) + 1)])
    _drive(ctx, pivot, cam, az=lambda f: ctx.az_deg + off(f),
           el=lambda f: ctx.el_deg + sag * (off(f) / a) ** 2, frames=frames)
    pivot.rotation_euler[2] = ctx.az
    pivot.rotation_euler[0] = -ctx.el


@register('camera_motion', 'arc_push', 'Arc + Push', 'orbit',
          'A 40 degree arc to the left while pushing in 12%: the camera "lands" on the product. '
          'Left on purpose: it adds to a counter-clockwise product yaw instead of cancelling it.', loop=False)
def arc_push(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 40)
    _arc(ctx, pivot, cam, az=(ctx.az_deg, ctx.az_deg - deg), amount=deg, peak=9, peak_max=16, ramp=(0.30, 0.55),
         closer=ctx.opt.get('amount', 0.12))


@register('camera_motion', 'whip_orbit_finale', 'Whip Orbit Finale', 'orbit',
          'Slow drift, then a fast whip around the product (80 degrees in about a second, declared exception to '
          'the speed limit), then a hold.', loop=False)
def whip_orbit_finale(pivot, cam, target, ctx):
    deg = ctx.opt.get('degrees', 80)
    d = _clip_s(ctx)
    hold = max(0.25, min(0.6, 0.15 * d))
    whip = min(1.1, 0.45 * d)
    drift = 0.07 * deg
    cam.location[1] = -ctx.fit(az=(ctx.az_deg, ctx.az_deg + deg))
    slow = _Law(ctx, timed=(0.0, d - hold), ramp=(0.5, 0.5))
    fast = _Law(ctx, timed=(d - hold - whip, whip), ramp=(0.5, 0.5))
    _drive(ctx, pivot, cam,
           az=lambda f: ctx.az_deg + drift * slow.p(f) + (deg - drift) * fast.p(f),
           frames=_union(slow.keys(), fast.keys()))
    pivot.rotation_euler[2] = ctx.az


# === crane / pedestal / truck ===============================================

@register('camera_motion', 'crane_down', 'Crane Down', 'crane',
          'Camera starts 28 degrees higher and settles down onto the shot (long soft landing), with a touch of '
          'side drift; the product stays framed.', loop=False)
def crane_down(pivot, cam, target, ctx):
    drop = ctx.opt.get('degrees', 28)
    _arc(ctx, pivot, cam, az=(ctx.az_deg + 5, ctx.az_deg), el=(ctx.el_deg + drop, ctx.el_deg), amount=drop,
         peak=8, peak_max=14, ramp=(0.25, 0.55), anchor='end')


@register('camera_motion', 'low_angle_hero_rise', 'Low-angle Hero Rise', 'crane',
          'Starts near the floor looking up (power shot) and rises to the shot while pushing in slightly.',
          loop=False)
def low_angle_hero_rise(pivot, cam, target, ctx):
    e0, e1 = ctx.el_deg - ctx.opt.get('drop', 12), ctx.el_deg + ctx.opt.get('rise', 8)
    _arc(ctx, pivot, cam, el=(e0, e1), amount=e1 - e0, peak=7.5, peak_max=13, ramp=(0.40, 0.40),
         closer=0.06, anchor='end')


def _slide(ctx, cam, target, vec_dir, tan, s, peak):
    """Translate the look-at target (world) by s half-frames along vec_dir with a time law: the rig follows."""
    law = _Law(ctx, s, peak, 0.20, (0.35, 0.35))
    s_eff = s * law.k
    d = ctx.fit(padding=max(ctx.padding, s_eff + 0.03))
    cam.location[1] = -d
    vec = vec_dir * (s_eff * tan * d)
    frames = law.keys()
    for i in range(3):
        if abs(vec[i]) < 1e-12:
            continue
        _put(target, 'location', i, lambda f, i=i: ctx.target[i] + vec[i] * law.p(f), frames)
    target.location = ctx.target


@register('camera_motion', 'pedestal_rise', 'Pedestal Rise', 'crane',
          'Camera rises straight up without tilting: the product slides down the frame.', loop=False)
def pedestal_rise(pivot, cam, target, ctx):
    _slide(ctx, cam, target, ctx.axis_up, ctx.tans[1], ctx.opt.get('amount', 0.22), 0.06)


@register('camera_motion', 'truck_right', 'Truck Right', 'crane',
          'Camera slides sideways to the right without turning: parallax against the backdrop.', loop=False)
def truck_right(pivot, cam, target, ctx):
    _slide(ctx, cam, target, ctx.right, ctx.tans[0], ctx.opt.get('amount', 0.28), 0.07)


# === lens / focus / handheld ================================================

@register('camera_motion', 'dolly_zoom', 'Dolly Zoom', 'lens',
          'Vertigo: after a beat the camera pushes in while the lens widens, the product keeps its size and the '
          'room stretches.', loop=False)
def dolly_zoom(pivot, cam, target, ctx):
    l0 = ctx.lens
    l1 = max(24.0, l0 * ctx.opt.get('ratio', 0.55))
    amount = log(l0 / l1)
    law = _Law(ctx, amount, 0.30, 0.50, (0.45, 0.45), tail=0.08, start_s=min(0.4, 0.2 * _clip_s(ctx)))
    l1 = l0 * (l1 / l0) ** law.k
    d1 = ctx.fit(lens=l1)
    frames = law.keys()
    _put(cam.data, 'lens', 0, lambda f: l0 * (l1 / l0) ** law.p(f), frames)       # lens and distance in lockstep
    _put(cam, 'location', 1, lambda f: -ctx.dist * (d1 / ctx.dist) ** law.p(f), frames)
    cam.location[1] = -ctx.dist


def _rack_fstop(ctx, reach, cur):
    """f-stop that makes the far/near side of the product (+-reach*size) visibly out of focus when the other is sharp:
    circle of confusion ~1.2% of the sensor width, clamped to f/0.1..f/4 (the shot's own f-stop when it is thinner)."""
    f = ctx.lens
    dn, sf = (ctx.dist - reach * ctx.size) * 1000.0, (ctx.dist + reach * ctx.size) * 1000.0   # mm; 1 BU = 1 m (Blender's DOF)
    if dn <= 1.5 * f:
        return min(cur, 4.0)
    n = f * f * (sf - dn) / (36.0 * 0.012 * sf * (dn - f))
    return min(cur, max(0.1, min(4.0, n)))


@register('camera_motion', 'rack_focus', 'Rack Focus', 'lens',
          'Locked camera with a moving-hold push; the focus is pulled in about a second from the near side of the '
          'product to the far side, with an aperture wide enough to read it.', loop=False)
def rack_focus(pivot, cam, target, ctx):
    dof = cam.data.dof
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    if focus is None:
        return
    if not dof.use_dof:
        dof.use_dof, dof.aperture_fstop = True, 2.8
    dof.focus_object = focus
    reach = ctx.opt.get('reach', 0.4)
    dof.aperture_fstop = _rack_fstop(ctx, reach, dof.aperture_fstop if dof.aperture_fstop > 0 else 4.0)
    back = core.cam_basis(ctx.az, ctx.el)[2]              # target -> camera
    near, far = ctx.center + back * reach * ctx.size, ctx.center - back * reach * ctx.size
    d = _clip_s(ctx)
    pull = min(1.2, max(0.5, 0.2 * d))
    start = min(6.0, max(0.4, 0.3 * d))
    law = _Law(ctx, timed=(min(start, d - pull - 0.2), pull), ramp=(0.5, 0.5))
    for i in range(3):
        _put(focus, 'location', i, lambda f, i=i: near[i] + (far[i] - near[i]) * law.p(f), law.keys())
    focus.location = near
    _dolly(ctx, cam, _closer(ctx, 0.05), peak=0.01, ramp=(0.5, 0.5), fill=True)


def _noise(ctx, idb, path, index, strength, scale_s, phase, depth=2):
    """Noise F-Modifier (scale in seconds) on a channel, restricted to the clip with a short fade in/out."""
    fc = m._fcurve(idb, path, index)
    if fc is None:
        idb.keyframe_insert(path, index=index, frame=ctx.f0)
        fc = m._fcurve(idb, path, index)
    md = fc.modifiers.new('NOISE')
    md.scale, md.strength, md.phase, md.depth = scale_s * ctx.fps, strength, phase, depth
    md.use_restricted_range = True
    md.frame_start, md.frame_end = ctx.f0, ctx.f1
    md.blend_in = md.blend_out = min(ctx.fps * 0.6, (ctx.f1 - ctx.f0) / 3)


@register('camera_motion', 'handheld', 'Handheld', 'lens',
          'Documentary feel: a slow breathing sway plus a fine tremor (under one degree), on top of a 5% drift '
          'towards the product.', loop=False)
def handheld(pivot, cam, target, ctx):
    _dolly(ctx, cam, _closer(ctx, 0.05), peak=0.01, ramp=(0.5, 0.5), fill=True)
    s = ctx.opt.get('strength', 0.012)                    # radians of noise strength (see wobble); ~0.7 deg p-p at 0.012
    sc = ctx.opt.get('scale', 1.0)                        # slow-sway period in seconds
    for i, w in ((0, 1.0), (2, 1.0), (1, 0.4)):           # pitch, yaw, roll (roll is the smallest)
        _noise(ctx, cam, 'rotation_euler', i, s * w, sc, 7.0 + 31.0 * i, depth=2)
        _noise(ctx, cam, 'rotation_euler', i, s * w * 0.35, sc * 0.3, 53.0 + 17.0 * i, depth=1)
    for i in (0, 2):                                      # shoulder sway: a hair of position (fraction of the size)
        _noise(ctx, cam, 'location', i, ctx.size * 0.006, sc * 1.4, 91.0 + 13.0 * i, depth=1)
