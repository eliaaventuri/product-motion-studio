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

from . import core, motion, presets


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
        self.pid = ''                                    # id of the running preset (build() sets it)
        self._init_range()

    def _init_range(self):
        self.span = self.f1 - self.f0
        self.dur_s = self.span / self.fps
        self.hold_s = min(max(0.5, min(0.12 * self.dur_s, 2.0)), 0.4 * self.dur_s)
        self.t_end = self.dur_s - self.hold_s
        self.k = 1.0

    def set_range(self, f0, f1):
        """Run the preset on f0..f1 instead of the whole shot (intro + loop): span, durations and hold follow."""
        self.f0 = f0
        self.f1 = f1
        self._init_range()

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


KEY_ATTRS = ('interpolation', 'easing', 'handle_left_type', 'handle_right_type', 'handle_left', 'handle_right')


def _snapshot_keys(root):
    """{(data_path, index): [(frame, value, {key attribute: value})]} of every F-Curve of the root."""
    def attrs(kp):
        return {a: (tuple(getattr(kp, a)) if a in ('handle_left', 'handle_right') else getattr(kp, a)) for a in KEY_ATTRS}
    return {(fc.data_path, fc.array_index): [(kp.co.x, kp.co.y, attrs(kp)) for kp in fc.keyframe_points]
            for fc in motion.iter_fcurves(root)}


def _bake_modifiers(root, f0, f1):
    """F-Curves with modifiers (Cycles of the loops, Noise of the wobble) -> one key per frame on f0..f1, so that
    the intro before f0 stays clean and the action stays plain keys (camera fit and hand-edit checks read them)."""
    for fc in motion.iter_fcurves(root):
        if not fc.modifiers:
            continue
        vals = [fc.evaluate(f) for f in range(f0, f1 + 1)]
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)
        fc.keyframe_points.clear()
        for f, v in enumerate(vals, f0):
            kp = fc.keyframe_points.insert(f, v, options={'FAST'})
            kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
        fc.update()


def _merge_intro(root, snap, split):
    """Put the intro keys (frames before split) back in front of the loop; the key at split too when the loop does
    not key that channel there."""
    for (path, index), keys in snap.items():
        fc = motion._fcurve(root, path, index)
        if fc is None:
            root.keyframe_insert(path, index=index, frame=split)        # a channel only the intro moves
            fc = motion._fcurve(root, path, index)
            fc.keyframe_points.clear()
        at_split = any(abs(kp.co.x - split) < 1e-6 for kp in fc.keyframe_points)
        for x, y, attrs in keys:
            if x > split + 1e-6 or (abs(x - split) < 1e-6 and at_split):
                continue
            kp = fc.keyframe_points.insert(x, y, options={'FAST'})
            for a, v in attrs.items():                                    # types before handles: positions stick
                setattr(kp, a, v)
        fc.update()


def _shift_loop(root, end, split):
    """Shift the loop F-Curves so they start from the intro's end pose at split."""
    for fc in motion.iter_fcurves(root):
        key = (fc.data_path, fc.array_index)
        if key not in end:
            continue
        start = fc.evaluate(split)
        target = end[key]
        if fc.data_path.endswith('scale'):
            if abs(start) < 1e-9:
                continue
            k = target / start
            for kp in fc.keyframe_points:
                kp.co.y *= k
                kp.handle_left.y *= k
                kp.handle_right.y *= k
        else:
            d = target - start
            for kp in fc.keyframe_points:
                kp.co.y += d
                kp.handle_left.y += d
                kp.handle_right.y += d
        fc.update()


def build(scene):
    core.begin(scene)
    inf = core.info(scene)
    core.reset_root(inf.root)
    pms = core.settings(scene)
    p, data = core.preset(scene, 'product_motion')
    ctx = AnimCtx(scene, inf, core.overrides(scene, 'product_motion'))
    ctx.pid = p.meta.get('fn_id', p.id)                # a personal preset runs the function of its base preset

    loop_id = pms.motion_loop
    is_loop_preset = p.meta.get('loop', False)
    combined = loop_id not in ('', 'NONE') and not is_loop_preset

    if not combined:
        p.fn(inf.root, ctx)
        last = _fit_range(inf.root, ctx.f0, ctx.f1)
        core.restore_rest_values(inf.root)       # presets leave channels at their first-key value
        scene.frame_set(ctx.f0)
        out = {'product_motion': p.id, 'frames': (ctx.f0, ctx.f1), 'loop': p.meta.get('loop', False),
               'ends_at_rest': p.meta.get('ends_at_rest', False), 'opts_used': sorted(ctx.opt.used)}
        if last is not None:
            out['note'] = f"Short duration: keys reached frame {last:g}, compressed to fit within {ctx.f1}"
        if is_loop_preset and loop_id not in ('', 'NONE'):
            out['note'] = "The motion is already a loop: 'Then Loop' ignored"
        # Preserve and combine preset notes
        note = getattr(ctx, 'note', '')
        if note:
            if 'note' in out:
                out['note'] = out['note'] + '; ' + note
            else:
                out['note'] = note
        return out

    # Intro on f0..split, then the loop on split..f1, merged in one plain action
    f0, f1 = ctx.f0, ctx.f1
    split = f0 + max(12, min(round(pms.motion_intro_s * ctx.fps), f1 - f0 - 12))
    ctx.set_range(f0, split)
    p.fn(inf.root, ctx)
    _fit_range(inf.root, f0, split)
    # Save the intro's end pose at split frame for each channel
    end = {(fc.data_path, fc.array_index): fc.evaluate(split) for fc in motion.iter_fcurves(inf.root)}
    snap = _snapshot_keys(inf.root)
    # Snapshot parts' animation and pms_explode flag (for presets like exploded_z_reveal that animate parts)
    parts_snap = {}
    parts_explode = set()
    for ch in inf.root.children:
        if ch.get('pms_explode'):
            parts_snap[ch.name] = _snapshot_keys(ch)
            parts_explode.add(ch.name)
    core.reset_root(inf.root)
    lp = presets.get('product_motion', loop_id)
    ctx2 = AnimCtx(scene, inf, {})                       # the loop with its default options
    ctx2.set_range(split, f1)
    ctx2.pid = lp.meta.get('fn_id', lp.id)
    lp.fn(inf.root, ctx2)
    _fit_range(inf.root, split, f1)
    _bake_modifiers(inf.root, split, f1)
    _shift_loop(inf.root, end, split)
    _merge_intro(inf.root, snap, split)
    # Restore parts' animation
    for ch in inf.root.children:
        if ch.name in parts_snap:
            for (path, index), keys in parts_snap[ch.name].items():
                fc = motion._fcurve(ch, path, index)
                if fc is None:
                    ch.keyframe_insert(path, index=index, frame=split)
                    fc = motion._fcurve(ch, path, index)
                    fc.keyframe_points.clear()
                for x, y, attrs in keys:
                    if x > split + 1e-6:
                        continue
                    kp = fc.keyframe_points.insert(x, y, options={'FAST'})
                    for a, v in attrs.items():
                        setattr(kp, a, v)
                fc.update()
            # Restore pms_explode flag if it was set
            if ch.name in parts_explode:
                ch['pms_explode'] = True
    core.restore_rest_values(inf.root)
    scene.frame_set(f0)
    out = {'product_motion': p.id, 'frames': (f0, f1), 'loop': False, 'loop_after': loop_id, 'split': split,
            'ends_at_rest': False, 'opts_used': sorted(ctx.opt.used)}
    # Preserve and combine preset notes from intro preset
    note = getattr(ctx, 'note', '')
    if note:
        out['note'] = note
    return out
