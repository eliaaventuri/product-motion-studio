"""Animation: runs the product_motion preset on PMS_Product_Root (the only object animated).

Presets receive an AnimCtx = core.Ctx + helpers in ABSOLUTE time, so that an action lasts what it really takes (a pop-in
0.8 s, a drop 0.6 s, a flip 0.8 s of air) whatever the total duration (a 480-frame pop-in is NOT a 10 s slow motion):
the rest of the shot is the product "living" (motion.life_yaw) and, at the end, a still hold on the hero pose.

    ctx.sec(s)                       seconds -> whole frames
    ctx.u(s)                         seconds -> normalized time 0..1 of this shot
    ctx.snap(t)                      t seconds moved to the nearest whole frame (contacts must land on a frame)
    ctx.dur_s                        length of the shot in seconds (frames f0..f1)
    ctx.hold_s / ctx.t_end           final hold in seconds (max(0.5 s, 12% of the shot, at most 2 s)) / time it starts
    ctx.action(start_u, seconds, min_u=0, max_u=1)
                                     normalized end of an action that starts at start_u and lasts `seconds`, clamped to
                                     min_u..max_u of the shot and never into the final hold
    ctx.plan(*seconds, lead=0)       consecutive phases in seconds -> [t0, t1, ...] boundaries (seconds, on whole frames);
                                     if they do not fit before the final hold ALL of them (lead included) shrink by the same
                                     factor ctx.k (< 1), so short shots keep the order and the proportions
"""

from . import core, motion


def _fit_range(root, f0, f1):
    """Presets put every key on its own whole frame: at a short duration the last ones run past f1. Squeeze all the
    channels by the same factor so the keys end inside f0..f1 (their timing relative to each other is kept).
    Returns the old last frame if it had to squeeze, else None."""
    fcs = list(motion.iter_fcurves(root))
    last = max((k.co.x for fc in fcs for k in fc.keyframe_points), default=f1)
    if last <= f1 + 1e-6:
        return None
    k = (f1 - f0) / (last - f0)
    for fc in fcs:
        for kp in fc.keyframe_points:
            for pt in (kp.co, kp.handle_left, kp.handle_right):
                pt.x = f0 + (pt.x - f0) * k
        fc.update()
    return last


class AnimCtx(core.Ctx):
    """core.Ctx for the product_motion presets, with the absolute-time helpers documented in the module docstring."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.span = self.f1 - self.f0
        self.dur_s = self.span / self.fps
        self.hold_s = min(max(0.5, min(0.12 * self.dur_s, 2.0)), 0.4 * self.dur_s)
        self.t_end = self.dur_s - self.hold_s
        self.k = 1.0
        self.pid = ''                                    # id of the running preset (build() sets it)

    def sec(self, s):
        return int(round(s * self.fps))

    def u(self, s):
        return s / self.dur_s if self.dur_s > 0 else 0.0

    def snap(self, t):
        return round(t * self.fps) / self.fps

    def action(self, start_u, seconds, min_u=0.0, max_u=1.0):
        end = start_u + min(max(self.u(seconds), min_u), max_u)
        return min(end, max(start_u, 1.0 - self.u(self.hold_s)))

    def plan(self, *seconds, lead=0.0):
        need = lead + sum(seconds)
        self.k = k = min(1.0, self.t_end / need) if need > 0 else 1.0
        times = [self.snap(lead * k)]
        for d in seconds:
            times.append(self.snap(times[-1] + d * k))
        return times


def build(scene):
    core.begin(scene)
    inf = core.info(scene)
    core.reset_root(inf.root)
    p, data = core.preset(scene, 'product_motion')
    ctx = AnimCtx(scene, inf, core.overrides(scene, 'product_motion'))
    ctx.pid = p.meta.get('fn_id', p.id)                # a personal preset runs the function of its base preset
    p.fn(inf.root, ctx)
    last = _fit_range(inf.root, ctx.f0, ctx.f1)
    core.restore_rest_values(inf.root)       # presets leave channels at their first-key value
    scene.frame_set(ctx.f0)
    out = {'product_motion': p.id, 'frames': (ctx.f0, ctx.f1), 'loop': p.meta.get('loop', False),
           'ends_at_rest': p.meta.get('ends_at_rest', False), 'opts_used': sorted(ctx.opt.used)}
    if last is not None:
        out['note'] = f"Short duration: keys reached frame {last:g}, compressed to fit within {ctx.f1}"
    return out
