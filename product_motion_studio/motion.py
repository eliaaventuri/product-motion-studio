"""Motion helpers for Product Motion Studio (PMS): autonomous copy of
skill/animazione-prodotto/scripts/product_anim_helpers.py plus the few functions it needs from
~/.claude/skills/blender/scripts/blender_helpers.py (iter_fcurves, ease_keys, ease_in_out).
Only bpy / math / mathutils, no exec. DO NOT edit the skill files: edit here.

Conventions: frames are integers; angles in the API are DEGREES (keys are radians);
"current value" = property value at call time (set the object up BEFORE calling).
Helpers LEAVE the animated property at its first-key value (e.g. pop_in leaves scale 0):
the builder (build_animation) restores the rest pose after the preset has run.

INDEX: set_timing | pop_in, slide_in, drop_in, hide_until, ease_to_rest | settle, anticipate,
stagger, wobble, color_flash | spin_loop | explode | orbit_rig, path_orbit, handheld, whip_pan,
pendulum, dolly_zoom | slam_in, impact | make_shot, curve_report.
PMS additions at the bottom ("choreography"): e_beta, e_over, trk, hops, impact_wave (curves in absolute time),
bake (samples a pose function frame by frame, with floor clamp), life_yaw (slow decorative yaw for the tail of a shot).
Private key helpers used by presets: _keys (insert keys), _seg (free handles), _flat.
"""

import bpy
from math import comb, cos, pi, radians, sin, sqrt, tau
from mathutils import Matrix, Vector


# === from blender_helpers.py ================================================

def iter_fcurves(obj):
    """Yield every f-curve of obj's action, version-safely. <4.4 uses the flat
    `action.fcurves`; >=4.4 uses slotted channelbags. Guards the None-slot case:
    `strip.channelbag(None)` RAISES (not empty), so iterate `strip.channelbags`
    (the collection) when no slot is assigned (appended/legacy/NLA actions)."""
    adt = obj.animation_data
    if not (adt and adt.action):
        return
    act = adt.action
    if bpy.app.version < (4, 4):
        for fc in act.fcurves:                      # flat list on old Blender
            yield fc
        return
    slot = adt.action_slot
    for layer in act.layers:
        for strip in layer.strips:
            bags = [strip.channelbag(slot)] if slot is not None else list(strip.channelbags)
            for cb in bags:
                if cb:
                    for fc in cb.fcurves:
                        yield fc



def ease_keys(obj, interpolation='SINE', easing='EASE_IN_OUT', handle='AUTO_CLAMPED'):
    """The biggest 'reads-as-pro' lever: replace robotic linear motion with eased
    acceleration. Sets interpolation + easing on every keyframe of obj's action and
    calls fc.update() (mandatory — stale handles otherwise). interpolation: 'SINE'/
    'CUBIC' (smooth), 'BACK' (overshoot+settle), 'BOUNCE', 'ELASTIC', or 'BEZIER'.
    Returns the count touched. (Pair: ease_in_out/anticipate_settle/bounce/elastic.)"""
    n = 0
    for fc in iter_fcurves(obj):
        for kp in fc.keyframe_points:
            kp.interpolation = interpolation
            if interpolation not in ('CONSTANT', 'LINEAR', 'BEZIER'):
                try:
                    kp.easing = easing
                except Exception:
                    pass
            if interpolation == 'BEZIER':
                kp.handle_left_type = kp.handle_right_type = handle
            n += 1
        fc.update()
    return n


def ease_in_out(obj):
    """Smooth slow-in/slow-out — the default pro feel for a reveal or move."""
    return ease_keys(obj, 'SINE', 'EASE_IN_OUT')



# === internal key helpers ===================================================

def _is_scalar(idb, path):
    return isinstance(getattr(idb, path), (int, float))


def _getval(idb, path, index):
    v = getattr(idb, path)
    return v if _is_scalar(idb, path) else v[index]


def _setval(idb, path, index, value):
    if _is_scalar(idb, path):
        setattr(idb, path, value)
    else:
        getattr(idb, path)[index] = value


def _fcurve(idb, path, index=0):
    """The F-Curve for (path, index) of an ID's action (object, camera data, node tree), or None."""
    ai = 0 if _is_scalar(idb, path) else index
    for fc in iter_fcurves(idb):
        if fc.data_path == path and fc.array_index == ai:
            return fc
    return None


def _keys(idb, path, index, pts, interp='BEZIER'):
    """Insert (frame, value) keys on a channel (creating it if needed), all inserts
    BEFORE grabbing keyframe pointers (inserting can invalidate them). Touched keys get
    AUTO_CLAMPED handles and `interp`. Returns (fcurve, [keyframe_point per pt])."""
    fc = _fcurve(idb, path, index)
    if fc is None:
        f0, v0 = pts[0]
        _setval(idb, path, index, v0)
        idb.keyframe_insert(path, index=-1 if _is_scalar(idb, path) else index, frame=f0)
        fc = _fcurve(idb, path, index)
    for f, v in pts:
        fc.keyframe_points.insert(f, v)
    by = {int(round(kp.co.x)): kp for kp in fc.keyframe_points}
    kps = [by[f] for f, _ in pts]
    for kp in kps:
        kp.interpolation = interp
        kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
    return fc, kps


def _seg(ka, kb, a=(1 / 3, 0.0), b=(1 / 3, 0.0)):
    """Shape the Bezier segment ka->kb with FREE handles. a = (x, y) fractions of the
    segment (dx, dy) for ka's right handle, measured from ka; b = same for kb's left
    handle, measured back from kb. Presets: ease-in quad a=(1/3,0) b=(1/3,2/3);
    ease-out quad a=(1/3,2/3) b=(1/3,0); in-out a=b=(1/3,0)."""
    ka.handle_right_type = 'FREE'
    kb.handle_left_type = 'FREE'
    dx = kb.co.x - ka.co.x
    dy = kb.co.y - ka.co.y
    ka.handle_right = (ka.co.x + a[0] * dx, ka.co.y + a[1] * dy)
    kb.handle_left = (kb.co.x - b[0] * dx, kb.co.y - b[1] * dy)


def _flat(kp):
    """Make both handles of kp FREE and horizontal (extremum: zero slope)."""
    kp.handle_left_type = kp.handle_right_type = 'FREE'
    kp.handle_left = (kp.handle_left.x, kp.co.y)
    kp.handle_right = (kp.handle_right.x, kp.co.y)


def _axis(axis):
    """'X' / 'Y' / 'Z' with optional '-' prefix -> (index, sign)."""
    s = -1.0 if axis.startswith('-') else 1.0
    return {'X': 0, 'Y': 1, 'Z': 2}[axis.lstrip('+-').upper()], s


def _world(target):
    """World position of an Object, or of a (x, y, z) tuple."""
    if hasattr(target, "matrix_world"):
        bpy.context.view_layer.update()
        return target.matrix_world.translation.copy()
    return Vector(target)


def _link(ob, collection=None):
    (collection or bpy.context.scene.collection).objects.link(ob)
    return ob


# === Timing =================================================================

def set_timing(fps=30, start=0, end=None, seconds=None):
    """Set fps and the frame range. end = start + seconds*fps when seconds is given;
    otherwise `end` (kept as-is if None). Returns dict(fps, start, end, seconds)."""
    sc = bpy.context.scene
    sc.render.fps = int(fps)
    sc.render.fps_base = 1.0
    sc.frame_start = int(start)
    if seconds is not None:
        end = int(start) + int(round(seconds * fps))
    if end is not None:
        sc.frame_end = int(end)
    return {"fps": sc.render.fps, "start": sc.frame_start, "end": sc.frame_end,
            "seconds": (sc.frame_end - sc.frame_start) / sc.render.fps}


# === Object entries =========================================================

def pop_in(obj, f_start, f_end, overshoot=0.12, settle_frames=None):
    """Scale 0 at f_start -> (1+overshoot)*S at ~65% of the duration -> S at f_end
    (S = the object's current scale). Fast aggressive launch (FREE handles pulling
    toward the peak), soft arrival (flat handles). settle_frames (optional): adds a
    small damped second oscillation (4% of S) over about that many frames after f_end.
    Returns the three scale F-Curves."""
    dur = f_end - f_start
    if dur < 2:
        raise ValueError("pop_in needs at least 2 frames")
    f_peak = f_start + max(1, round(dur * 0.65))
    s = list(obj.scale)
    fcs = []
    for i in range(3):
        fc, (k0, kp, k1) = _keys(obj, "scale", i, [(f_start, 0.0),
                                                    (f_peak, (1 + overshoot) * s[i]),
                                                    (f_end, s[i])])
        _seg(k0, kp, a=(0.25, 0.85), b=(0.4, 0.0))
        _seg(kp, k1, a=(1 / 3, 0.0), b=(0.4, 0.0))
        fc.update()
        fcs.append(fc)
    if settle_frames:
        for i in range(3):
            settle(obj, "scale", i, f_end, 0.04 * s[i], cycles=2,
                   period=max(3, round(settle_frames / 2)))
    return fcs


def slide_in(obj, offset, f_start, f_end, overshoot=0.0):
    """Enter from location+offset to the current location: fast start, long strong
    ease-out (friction; ~70% of the distance in the first 40% of the time). overshoot
    (distance units, >0) passes the rest position by that much along the slide
    direction at ~70% of the time, then settles back. Returns the 3 location F-Curves."""
    dur = f_end - f_start
    if dur < 2:
        raise ValueError("slide_in needs at least 2 frames")
    off = Vector(offset)
    d = (-off).normalized() if off.length > 1e-9 else Vector((0, 0, 0))   # direction of travel
    p = obj.location.copy()
    fcs = []
    for i in range(3):
        pts = [(f_start, p[i] + off[i])]
        if overshoot:
            pts.append((f_start + max(1, round(dur * 0.7)), p[i] + d[i] * overshoot))
        pts.append((f_end, p[i]))
        fc, ks = _keys(obj, "location", i, pts)
        if overshoot:
            _seg(ks[0], ks[1], a=(0.25, 0.8), b=(0.4, 0.0))
            _seg(ks[1], ks[2], a=(1 / 3, 0.0), b=(0.4, 0.0))
        else:
            _seg(ks[0], ks[1], a=(0.25, 0.8), b=(0.4, 0.0))
        fc.update()
        fcs.append(fc)
    return fcs


def drop_in(obj, height, f_start, f_end, bounce=0.04):
    """Fall from Z+height at f_start (parabolic acceleration), hit the floor, one
    damped rebound of bounce*height, and rest EXACTLY at the current Z on f_end.
    The rebound lasts ~2*sqrt(bounce) of the fall time (real physics). Returns the Z F-Curve."""
    dur = f_end - f_start
    z = obj.location.z
    s = sqrt(bounce) if bounce > 0 else 0.0
    rebound = max(2, round(dur * 2 * s / (1 + 2 * s))) if bounce > 0 else 0
    f_hit = f_end - rebound
    if f_hit <= f_start + 1:
        raise ValueError("drop_in: duration too short for this bounce")
    pts = [(f_start, z + height), (f_hit, z)]
    if rebound:
        pts += [(f_hit + rebound // 2, z + bounce * height), (f_end, z)]
    fc, ks = _keys(obj, "location", 2, pts)
    _seg(ks[0], ks[1], a=(1 / 3, 0.0), b=(1 / 3, 2 / 3))          # ease-in quad (gravity)
    if rebound:
        _seg(ks[1], ks[2], a=(1 / 3, 2 / 3), b=(1 / 3, 0.0))      # up: decelerate
        _seg(ks[2], ks[3], a=(1 / 3, 0.0), b=(1 / 3, 2 / 3))      # down: accelerate
        _flat(ks[2])
    fc.update()
    return fc


def hide_until(obj, frame, method='scale'):
    """Object is absent before `frame` and pops into existence on it (CONSTANT key).
    method 'scale': scale 0 -> current; 'below': Z - 10 -> current Z. Call it BEFORE
    animating that same channel. Returns dict(method, frame, hidden, shown)."""
    if method == 'scale':
        shown = tuple(obj.scale)
        for i in range(3):
            fc, (k0, k1) = _keys(obj, "scale", i, [(frame - 1, 0.0), (frame, shown[i])])
            k0.interpolation = 'CONSTANT'
            fc.update()
        return {"method": method, "frame": frame, "hidden": (0.0, 0.0, 0.0), "shown": shown}
    if method == 'below':
        z = obj.location.z
        fc, (k0, k1) = _keys(obj, "location", 2, [(frame - 1, z - 10.0), (frame, z)])
        k0.interpolation = 'CONSTANT'
        fc.update()
        return {"method": method, "frame": frame, "hidden": z - 10.0, "shown": z}
    raise ValueError("method must be 'scale' or 'below'")


# === Polish =================================================================

def settle(obj, data_path, index, f_land, amplitude, cycles=2, period=4, one_sided=False):
    """Micro-damping: after f_land the channel oscillates around its value at f_land
    (+A, -A, back to rest) with amplitude halved every cycle, ending still on that value
    at f_land + cycles*period. Assumes the channel has no keys after f_land (those would
    be overwritten/mixed). one_sided=True: every bounce goes only towards the sign of
    `amplitude` and comes back to rest (a part snapping into its seat bounces BACK,
    it never sinks into the housing - use it for assemblies). Returns dict(rest, frames, values)."""
    fc = _fcurve(obj, data_path, index)
    if fc is None:
        raise ValueError(f"settle: no F-Curve for {data_path}[{index}]")
    if period < 3:
        raise ValueError("settle: period must be >= 3 frames")
    v0 = fc.evaluate(f_land)
    q1, q2 = max(1, round(period / 4)), max(2, round(period * 3 / 4))
    pts = []
    if not any(int(round(kp.co.x)) == f_land for kp in fc.keyframe_points):
        pts.append((f_land, v0))
    for c in range(cycles):
        a = amplitude * 0.5 ** c
        base = f_land + c * period
        if one_sided:
            pts += [(base + period // 2, v0 + a), (base + period, v0)]
        else:
            pts += [(base + q1, v0 + a), (base + q2, v0 - a), (base + period, v0)]
    _, kps = _keys(obj, data_path, index, pts)
    fc = _fcurve(obj, data_path, index)
    fc.update()
    return {"rest": v0, "frames": [f for f, _ in pts], "values": [v for _, v in pts]}


def anticipate(obj, data_path, index, f_start, amount, frames=4):
    """Wind-up before an action: the channel (must have a key at f_start) first goes
    `amount` the OPPOSITE way of its next move, at the middle of the `frames` before
    f_start, then runs through its rest value at f_start into the action. Adds a rest
    key at f_start-frames and the dip key; returns dict(rest, dip, frames)."""
    fc = _fcurve(obj, data_path, index)
    if fc is None:
        raise ValueError(f"anticipate: no F-Curve for {data_path}[{index}]")
    ks = sorted(fc.keyframe_points, key=lambda k: k.co.x)
    pos = [int(round(k.co.x)) for k in ks]
    if f_start not in pos:
        raise ValueError("anticipate: the channel needs a key at f_start")
    i = pos.index(f_start)
    v = ks[i].co.y
    sign = 1.0
    if i + 1 < len(ks) and abs(ks[i + 1].co.y - v) > 1e-9:
        sign = 1.0 if ks[i + 1].co.y > v else -1.0
    f_dip = f_start - max(1, frames // 2)
    dip = v - sign * amount
    _keys(obj, data_path, index, [(f_start - frames, v), (f_dip, dip)])
    _fcurve(obj, data_path, index).update()
    return {"rest": v, "dip": dip, "frames": (f_start - frames, f_dip, f_start)}


def stagger(objs, delay=3):
    """Shift ALL keys (and handles) of the i-th object by i*delay frames. Returns
    dict name -> offset in frames."""
    out = {}
    for i, ob in enumerate(objs):
        shift = i * delay
        out[ob.name] = shift
        for fc in iter_fcurves(ob):
            for kp in fc.keyframe_points:
                kp.co.x += shift
                kp.handle_left.x += shift
                kp.handle_right.x += shift
            fc.update()
    return out


def wobble(obj, data_path='rotation_euler', index=0, strength=0.03, scale=12.0, phase=None,
           frames=None):
    """Organic jitter: F-Modifier Noise on a channel (a key is created at the current
    frame if the channel has none). strength in the channel's units (radians for
    rotation); scale = frames per noise cycle (peak deviation is about 0.3*strength); phase None -> derived from the name so
    different objects differ. frames=(start, end) limits the jitter to that range (a
    seated part must NOT keep jittering). Returns the modifier."""
    fc = _fcurve(obj, data_path, index)
    if fc is None:
        obj.keyframe_insert(data_path, index=-1 if _is_scalar(obj, data_path) else index,
                            frame=bpy.context.scene.frame_current)
        fc = _fcurve(obj, data_path, index)
    m = fc.modifiers.new('NOISE')
    m.scale = scale
    m.strength = strength
    m.phase = float(sum(map(ord, obj.name)) % 97) if phase is None else phase
    if frames:                       # (start, end): jitter only there, 6-frame fade in/out
        m.use_restricted_range = True
        m.frame_start, m.frame_end = frames
        m.blend_in = m.blend_out = min(6, (frames[1] - frames[0]) / 2)
    return m


def color_flash(material, frames, colors, socket='Base Color', node_name=None):
    """Stepped (CONSTANT) colour keys on the Principled BSDF `socket`: colors[i]
    (RGB or RGBA) switches on at frames[i]. node_name None -> first Principled.
    Returns the list of F-Curves touched."""
    if material.node_tree is None:
        material.use_nodes = True
    nt = material.node_tree
    node = nt.nodes[node_name] if node_name else next(
        n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    sock = node.inputs[socket]
    for f, c in zip(frames, colors):
        c = tuple(c) + (1.0,) * (4 - len(c))
        sock.default_value = c
        sock.keyframe_insert("default_value", frame=f)
    first = tuple(colors[0]) + (1.0,) * (4 - len(colors[0]))
    sock.default_value = first            # static value = first flash colour
    fcs = [fc for fc in iter_fcurves(nt) if fc.data_path == sock.path_from_id("default_value")]
    for fc in fcs:
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'
        fc.update()
    return fcs


# === Rotation ===============================================================

def spin_loop(obj, axis='Z', f_start=0, f_end=60, turns=1, ease=False):
    """Seamless spin: rotation goes r0 -> r0 + 360*turns degrees over f_start..f_end
    (axis 'X'/'Y'/'Z', '-Z' reverses). ease=False: LINEAR, constant speed, identical
    in/out slope. ease=True: Bezier with FREE handles that give the SAME slope at both
    ends = 35% of the mean speed (handles length 1/3 of the span, value 1/3 * 0.35 *
    total), so the curve slows symmetrically toward the loop point and the exit slope at
    f_end equals the entry slope at f_start (no stop, no jump when it repeats). Returns the F-Curve."""
    i, sign = _axis(axis)
    if obj.rotation_mode in ('QUATERNION', 'AXIS_ANGLE'):
        obj.rotation_mode = 'XYZ'
    r0 = obj.rotation_euler[i]
    total = sign * turns * tau
    fc, (k0, k1) = _keys(obj, "rotation_euler", i, [(f_start, r0), (f_end, r0 + total)])
    if not ease:
        k0.interpolation = k1.interpolation = 'LINEAR'
    else:
        k = 0.35
        dx = (f_end - f_start) / 3.0
        dy = k * total / 3.0
        k0.handle_left_type = k0.handle_right_type = 'FREE'
        k1.handle_left_type = k1.handle_right_type = 'FREE'
        k0.handle_right = (k0.co.x + dx, k0.co.y + dy)
        k0.handle_left = (k0.co.x - dx, k0.co.y - dy)
        k1.handle_left = (k1.co.x - dx, k1.co.y - dy)
        k1.handle_right = (k1.co.x + dx, k1.co.y + dy)
    fc.update()
    return fc


# === Assemblies =============================================================

def explode(parts, f_assembled, f_exploded, distance=1.0, direction='radial',
            stagger_frames=2, center=None):
    """Exploded view from the CURRENT (assembled) positions. direction:
      'radial'  each part moves `distance` away from `center` (default = centroid of
                the parts) along centre->part;
      'X','-Z'..  parts are sorted along that axis and part i (0 = first) moves
                `distance`*i along it, i.e. distance is the SPACING between neighbours;
      list of vectors  part i moves Vector(v_i)*distance.
    Keys: assembled at f_assembled, exploded at f_exploded, in-out ease; part i is
    delayed by i*stagger_frames (both keys). f_exploded < f_assembled makes an assembly.
    Positions use obj.location (parts should share a parent). Returns
    dict name -> (assembled_pos, exploded_pos) as tuples."""
    parts = list(parts)
    home = [ob.location.copy() for ob in parts]
    n = len(parts)
    if isinstance(direction, str) and direction.lower() == 'radial':
        c = Vector(center) if center is not None else sum(home, Vector()) / n
        disp = []
        for h in home:
            d = h - c
            disp.append((d.normalized() if d.length > 1e-6 else Vector((0, 0, 1))) * distance)
    elif isinstance(direction, str):
        i, sign = _axis(direction)
        order = sorted(range(n), key=lambda k: sign * home[k][i])
        disp = [Vector()] * n
        for rank, k in enumerate(order):
            v = Vector((0, 0, 0))
            v[i] = sign * distance * rank
            disp[k] = v
    else:
        disp = [Vector(v) * distance for v in direction]
    out = {}
    for k, ob in enumerate(parts):
        end = home[k] + disp[k]
        d = k * stagger_frames
        for ax in range(3):
            fc, (ka, kb) = _keys(ob, "location", ax, [(f_assembled + d, home[k][ax]),
                                                      (f_exploded + d, end[ax])])
            ka, kb = sorted((ka, kb), key=lambda q: q.co.x)
            _seg(ka, kb)
            fc.update()
        out[ob.name] = (tuple(home[k]), tuple(end))
    return out


# === Camera rigs ============================================================

def orbit_rig(target, radius, height, focal_mm=85, start_deg=0, end_deg=90,
              f_start=0, f_end=60, ease=True):
    """Hero orbit: an Empty at the target (Object or xyz tuple), a camera child of it at
    `radius` / `height`, Track To the target, Z rotation of the empty animated
    start_deg -> end_deg (SINE in-out when ease, else linear). Sets scene.camera.
    Returns (empty, cam). The camera aims at the target's origin."""
    sc = bpy.context.scene
    pos = _world(target)
    rig = _link(bpy.data.objects.new("OrbitRig", None))
    rig.empty_display_type = 'PLAIN_AXES'
    rig.location = pos
    cd = bpy.data.cameras.new("OrbitCam")
    cd.lens = focal_mm
    cam = _link(bpy.data.objects.new("OrbitCam", cd))
    cam.parent = rig
    cam.location = (radius, 0, height)
    aim = target if hasattr(target, "matrix_world") else rig
    con = cam.constraints.new('TRACK_TO')
    con.target = aim
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    rig.rotation_euler = (0, 0, radians(start_deg))
    rig.keyframe_insert("rotation_euler", index=2, frame=f_start)
    rig.rotation_euler[2] = radians(end_deg)
    rig.keyframe_insert("rotation_euler", index=2, frame=f_end)
    if ease:
        ease_in_out(rig)
    else:
        for fc in iter_fcurves(rig):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
    sc.camera = cam
    return rig, cam


def path_orbit(target, radius, f_start, f_end, turns=1.0, height=0.0):
    """Orbit on a Bezier Circle: camera with Follow Path + Track To the target, at
    target.z+height. Blender 5 semantics (verified): constraint.offset is in FRAMES of
    the path (curve.path_duration, default 100 = one lap) and WRAPS on a cyclic curve;
    offset_factor only spans 0..1 (no multi-turn). So `offset` is animated LINEARLY from
    0 to path_duration*turns (positive = counter-clockwise seen from above; negative
    turns reverse). Returns (circle_object, camera); sets scene.camera."""
    sc = bpy.context.scene
    pos = _world(target) + Vector((0, 0, height))
    bpy.ops.curve.primitive_bezier_circle_add(radius=radius, location=pos)
    circle = bpy.context.active_object
    circle.name = "OrbitPath"
    cd = bpy.data.cameras.new("PathCam")
    cam = _link(bpy.data.objects.new("PathCam", cd))
    fp = cam.constraints.new('FOLLOW_PATH')
    fp.target = circle
    fp.use_curve_follow = False
    fp.use_fixed_location = False
    tt = cam.constraints.new('TRACK_TO')
    if hasattr(target, "matrix_world"):
        tt.target = target
    else:
        aim = _link(bpy.data.objects.new("OrbitAim", None))
        aim.location = Vector(target)
        tt.target = aim
    tt.track_axis = 'TRACK_NEGATIVE_Z'
    tt.up_axis = 'UP_Y'
    lap = circle.data.path_duration
    fp.offset = 0.0
    fp.keyframe_insert("offset", frame=f_start)
    fp.offset = lap * turns
    fp.keyframe_insert("offset", frame=f_end)
    for fc in iter_fcurves(cam):
        if fc.data_path.endswith("offset"):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
            fc.update()
    sc.camera = cam
    return circle, cam


def handheld(cam, strength=0.01, scale=25.0):
    """Handheld feel: Noise F-Modifier on the 3 rotation channels (radians; 0.01 ~ 0.6
    deg), different phase per axis. Needs a camera WITHOUT Track To (the constraint
    overrides rotation) — use on a child/parent or a free camera. Returns the 3 modifiers."""
    mods = []
    for i in range(3):
        mods.append(wobble(cam, 'rotation_euler', i, strength, scale, phase=7.0 + 31.0 * i))
    return mods


def _rot_keys(cam, axis, f0, f1, delta):
    i, sign = _axis(axis)
    r0 = cam.rotation_euler[i]
    return i, r0, _keys(cam, "rotation_euler", i, [(f0, r0), (f1, r0 + sign * radians(delta))])


def whip_pan(cam, f_start, frames=7, angle_deg=70, axis='Z'):
    """Transition whip pan: rotation r0 -> r0 + angle over `frames`, ease-in AND ease-out
    with long flat handles (speed peaks mid-move). Free camera only (no Track To).
    Returns the F-Curve."""
    _, _, (fc, (k0, k1)) = _rot_keys(cam, axis, f_start, f_start + frames, angle_deg)
    _seg(k0, k1, a=(0.5, 0.0), b=(0.5, 0.0))
    fc.update()
    return fc


def pendulum(cam, angle_deg, f_start, f_mid, f_end, axis='Z'):
    """Side-to-side swing: rest value r0 is the CENTRE. r0-angle at f_start (apex, at
    rest), r0 at f_mid (fastest), r0+angle at f_end (apex). FREE handles make each half a
    parabola arc (ease-in then ease-out) with equal slope across the centre key. Free
    camera only. Returns the F-Curve."""
    i, sign = _axis(axis)
    r0 = cam.rotation_euler[i]
    a = radians(angle_deg) * sign
    fc, (k0, km, k1) = _keys(cam, "rotation_euler", i,
                             [(f_start, r0 - a), (f_mid, r0), (f_end, r0 + a)])
    t1, t2 = f_mid - f_start, f_end - f_mid
    m = abs(a) * (1 / t1 + 1 / t2) * (1 if a > 0 else -1)   # slope at centre
    for k in (k0, km, k1):
        k.handle_left_type = k.handle_right_type = 'FREE'
    k0.handle_left = (k0.co.x - t1 / 3, k0.co.y)
    k0.handle_right = (k0.co.x + t1 / 3, k0.co.y)
    km.handle_left = (km.co.x - t1 / 3, km.co.y - m * t1 / 3)
    km.handle_right = (km.co.x + t2 / 3, km.co.y + m * t2 / 3)
    k1.handle_left = (k1.co.x - t2 / 3, k1.co.y)
    k1.handle_right = (k1.co.x + t2 / 3, k1.co.y)
    fc.update()
    return fc


def dolly_zoom(cam, target, f_start, f_end, focal_start=35, focal_end=85):
    """Vertigo effect: the camera slides along the line target->camera while the lens
    changes so that distance/focal stays constant (the target keeps its apparent size,
    the background stretches). Distance at f_start = current distance; at f_end =
    that * focal_end/focal_start. Location and lens use the SAME in-out ease so the
    ratio holds at every frame. Unparented camera assumed (and already aimed). Returns
    dict(d_start, d_end, ratio)."""
    tp = _world(target)
    cp = cam.matrix_world.translation.copy()
    u = (cp - tp)
    d0 = u.length
    u.normalize()
    d1 = d0 * focal_end / focal_start
    p0, p1 = tp + u * d0, tp + u * d1
    cam.data.lens = focal_start
    for ax in range(3):
        fc, (ka, kb) = _keys(cam, "location", ax, [(f_start, p0[ax]), (f_end, p1[ax])])
        _seg(ka, kb)
        fc.update()
    fc, (ka, kb) = _keys(cam.data, "lens", 0, [(f_start, focal_start), (f_end, focal_end)])
    _seg(ka, kb)
    fc.update()
    return {"d_start": d0, "d_end": d1, "ratio": d0 / focal_start}


# === Shots / review =========================================================

def make_shot(name, camera, f_start, f_end):
    """Shot = collection "SHOT_<name>" holding the camera + a timeline marker at f_start
    bound to that camera (camera switching in the render). f_start/f_end are stored on
    the collection as custom props. Returns the marker."""
    sc = bpy.context.scene
    col = bpy.data.collections.new(f"SHOT_{name}")
    sc.collection.children.link(col)
    for c in list(camera.users_collection):
        c.objects.unlink(camera)
    col.objects.link(camera)
    col["f_start"], col["f_end"] = int(f_start), int(f_end)
    mk = sc.timeline_markers.new(name, frame=int(f_start))
    mk.camera = camera
    return mk


def curve_report(obj):
    """Print + return one dict per F-Curve of obj (and of obj.data, e.g. camera lens):
    id, data_path, index, n_keys, interp (set), handles (set of types), min/max sampled
    every frame between first and last key (overshoot!), first/last key value, modifiers."""
    rows = []
    ids = [("obj", obj)]
    d = getattr(obj, "data", None)
    if d is not None and getattr(d, "animation_data", None):
        ids.append(("data", d))
    for label, idb in ids:
        for fc in iter_fcurves(idb):
            kps = sorted(fc.keyframe_points, key=lambda k: k.co.x)
            if not kps:
                continue
            f0, f1 = int(round(kps[0].co.x)), int(round(kps[-1].co.x))
            vals = [fc.evaluate(f) for f in range(f0, f1 + 1)]
            rows.append({
                "id": label, "data_path": fc.data_path, "index": fc.array_index,
                "n_keys": len(kps),
                "interp": sorted({k.interpolation for k in kps}),
                "handles": sorted({k.handle_left_type for k in kps} |
                                  {k.handle_right_type for k in kps}),
                "min": min(vals), "max": max(vals),
                "first": kps[0].co.y, "last": kps[-1].co.y, "frames": (f0, f1),
                "modifiers": [m.type for m in fc.modifiers]})
    for r in rows:
        print(f"{r['id']}:{r['data_path']}[{r['index']}] keys={r['n_keys']} "
              f"{r['frames'][0]}-{r['frames'][1]} interp={','.join(r['interp'])} "
              f"handles={','.join(r['handles'])} min={r['min']:.3f} max={r['max']:.3f} "
              f"first={r['first']:.3f} last={r['last']:.3f} mods={r['modifiers']}")
    return rows



# === Weight & impact =========================================================

def slam_in(obj, offset, f_start, f_contact):
    """A part flies in from location+offset and HITS its seat at f_contact: it accelerates
    all the way (ease-in, top speed at contact, no ease-out before touching) and stops
    dead on the contact frame. The bounce belongs to the body it hits: follow with
    impact(). Returns the 3 location F-Curves."""
    if f_contact - f_start < 2:
        raise ValueError("slam_in needs at least 2 frames")
    off = Vector(offset)
    p = obj.location.copy()
    fcs = []
    for i in range(3):
        fc, ks = _keys(obj, "location", i, [(f_start, p[i] + off[i]), (f_contact, p[i])])
        _seg(ks[0], ks[1], a=(1 / 3, 0.0), b=(1 / 3, 2 / 3))
        ks[1].handle_right_type = 'FREE'
        ks[1].handle_right = (ks[1].co.x + 2, ks[1].co.y)           # dead stop, no drift
        fc.update()
        fcs.append(fc)
    obj.location = p          # leave the property at the seat: later keyframe_insert calls read it
    return fcs


def _pulse(idb, path, vec, f0, frames_vals):
    """Add a pulse (frame offset from f0, factor) * vec on top of whatever the 3 channels
    of `path` already hold (so several impacts accumulate)."""
    for i in range(3):
        if abs(vec[i]) < 1e-12:
            continue
        fc = _fcurve(idb, path, i)
        base = (lambda f: fc.evaluate(f)) if fc else (lambda f: getattr(idb, path)[i])
        pts = [(f0 + df, base(f0 + df) + k * vec[i]) for df, k in frames_vals]
        fc, ks = _keys(idb, path, i, pts)
        _seg(ks[0], ks[1], a=(0.2, 0.8), b=(0.35, 0.0))            # impulsive attack
        fc.update()


def impact(body, f_contact, direction, distance=0.004, tilt_deg=1.0, delay=1, recover=10,
           followers=(), follower_delay=1, follower_scale=0.6, camera=None, shake=0.003):
    """WEIGHT on collision: when a part hits `body` at f_contact, the WHOLE body takes the
    blow. Body: after `delay` frames it is pushed `distance` along `direction` (world/parent
    axes, the travel direction of the incoming part) in 2 frames and tilts `tilt_deg`
    (top leans the same way), swings back ~35%, then settles by f_contact+delay+2+recover.
    Heavier body = smaller distance/tilt (rule: 10-25% of the part's speed-per-frame).
    followers = loose/elastic appendages ONLY (cable, strap, antenna): rigid parts already
    seated in the body are its children and move with it - giving them their own pulse
    makes them sink 1-3 mm into the seat (seen on a real assembly). Same pulse, each
    `follower_delay` frames later and x follower_scale (overlap). camera: decaying
    positional shake of `shake` units. Everything goes on delta_location /
    delta_rotation_euler, so it ADDS to the existing animation and impacts accumulate.
    Returns the list of frames used for the body."""
    d = Vector(direction).normalized()
    shape = [(0, 0.0), (2, 1.0), (2 + round(recover * 0.4), -0.35),
             (2 + round(recover * 0.7), 0.1), (2 + recover, 0.0)]
    tilt_axis = Vector((0, 0, 1)).cross(d)
    tilt = tilt_axis.normalized() * radians(tilt_deg) if tilt_axis.length > 1e-6 else Vector()
    f0 = f_contact + delay - 1
    _pulse(body, "delta_location", d * distance, f0, shape)
    if tilt.length:
        _pulse(body, "delta_rotation_euler", tilt, f0, shape)
    for k, ob in enumerate(followers, start=1):
        s = follower_scale ** k
        fk = f0 + k * follower_delay
        _pulse(ob, "delta_location", d * distance * s, fk, shape)
        if tilt.length:
            _pulse(ob, "delta_rotation_euler", tilt * s, fk, shape)
    if camera is not None and shake:
        side = d.cross(Vector((0, 0, 1)))
        side = side.normalized() if side.length > 1e-6 else Vector((1, 0, 0))
        jolt = (d * 0.5 + side + Vector((0, 0, 0.6))).normalized() * shake
        _pulse(camera, "delta_location", jolt, f0,
               [(0, 0.0), (1, 1.0), (3, -0.6), (5, 0.35), (7, -0.15), (9, 0.0)])
    return [f0 + df for df, _ in shape]


def ease_to_rest(obj, data_path, index, start_value, f_start, f_end, overshoot=0.0):
    """PMS addition. Channel goes from start_value at f_start to its CURRENT value (the rest
    value) at f_end with the pop_in shape: fast launch, soft arrival. overshoot (fraction of
    the travel, e.g. 0.06) passes the rest by that much at ~70% of the time and comes back.
    Leaves the property at the rest value. Returns the F-Curve."""
    if f_end - f_start < 2:
        raise ValueError("ease_to_rest needs at least 2 frames")
    rest = _getval(obj, data_path, index)
    travel = rest - start_value
    pts = [(f_start, start_value)]
    if overshoot:
        pts.append((f_start + max(1, round((f_end - f_start) * 0.7)), rest + overshoot * travel))
    pts.append((f_end, rest))
    fc, ks = _keys(obj, data_path, index, pts)
    _seg(ks[0], ks[1], a=(0.25, 0.8), b=(0.4, 0.0))
    if overshoot:
        _seg(ks[1], ks[2], a=(1 / 3, 0.0), b=(0.4, 0.0))
    fc.update()
    _setval(obj, data_path, index, rest)
    return fc


def pin_base_to_scale(obj, half_height, index=2):
    """PMS addition. Keeps the BASE of a body still while its scale animates. The origin sits
    `half_height` above the base, so z-location mirrors scale[index]:
    loc_z = rest_z + half_height * (scale - 1), same keys/handles (the map is affine, so the
    Bezier shape is identical). Call after the scale keys exist (uniform scale, no rotation
    about X/Y); location z must not be keyed yet. Returns the location z F-Curve."""
    src = _fcurve(obj, "scale", index)
    if src is None:
        raise ValueError("pin_base_to_scale: no scale F-Curve")
    z0 = obj.location.z

    def f(y):
        return z0 + half_height * (y - 1.0)

    pts = sorted(src.keyframe_points, key=lambda k: k.co.x)
    fc, kps = _keys(obj, "location", 2, [(int(round(k.co.x)), f(k.co.y)) for k in pts])
    for s, d in zip(pts, kps):
        d.interpolation = s.interpolation
        d.handle_left_type, d.handle_right_type = s.handle_left_type, s.handle_right_type
        if s.handle_left_type in ('FREE', 'ALIGNED', 'VECTOR'):
            d.handle_left = (s.handle_left.x, f(s.handle_left.y))
        if s.handle_right_type in ('FREE', 'ALIGNED', 'VECTOR'):
            d.handle_right = (s.handle_right.x, f(s.handle_right.y))
    fc.update()
    _setval(obj, "location", 2, z0)
    return fc


# === PMS choreography: curves in absolute time, baking, life ================================================
# Presets of presets/product_motion.py describe the root as a function pose(t) of the time t in SECONDS from the first
# frame (not of a normalized 0..1), `bake` samples it on every frame (renders only ever see whole frames, so the keys
# ARE the motion; the Bezier handles in between are auto-clamped) and `life_yaw` adds the slow decorative yaw of the tail.

def e_smooth(x):
    """Smoothstep 0..1 (zero slope at both ends)."""
    x = 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
    return x * x * (3.0 - 2.0 * x)


def e_beta(x, a=2, b=2):
    """0..1 ease = integral of x^(a-1) (1-x)^(b-1) (regularized incomplete beta, integer a, b >= 1).
    a = how soft the start is (1: full speed at once, 2: smooth start), b = how soft the arrival is (1: stops at full speed,
    2: smooth, 3-4: long friction-like tail). Speed peaks at x = (a-1)/(a+b-2). e_beta(x,2,2) = smoothstep,
    e_beta(x,1,3) = 1-(1-x)^3 (ease-out), e_beta(x,3,1) = x^3 (gravity-like ease-in, arrives at full speed)."""
    x = 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
    n = a + b - 1
    return sum(comb(n, j) * x ** j * (1.0 - x) ** (n - j) for j in range(a, n + 1))


def e_over(x, os=0.06, a=2, b=3, xp=0.6):
    """0..1 ease that passes 1 by `os` (fraction of the travel, 0.03-0.15) at x = xp and comes back to 1 smoothly:
    one overshoot, no spring. b >= 2 (the peak is reached with zero speed)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if x < xp:
        return (1.0 + os) * e_beta(x / xp, a, b)
    return 1.0 + os * (1.0 - e_smooth((x - xp) / (1.0 - xp)))


def trk(t, keys):
    """Piecewise track of floats in time: keys = [(t0, v0), (t1, v1, ease), ...]; ease(x) maps 0..1 to 0..1 (may overshoot),
    default smoothstep. Holds v0 before t0 and the last value after the last key."""
    if t <= keys[0][0]:
        return keys[0][1]
    for ka, kb in zip(keys, keys[1:]):
        if t <= kb[0]:
            x = (t - ka[0]) / (kb[0] - ka[0]) if kb[0] > ka[0] else 1.0
            f = kb[2] if len(kb) > 2 else e_smooth
            return ka[1] + (kb[1] - ka[1]) * f(x)
    return keys[-1][1]


def hops(t, t0, seq):
    """Height at time t of consecutive parabolic hops after a contact at t0 (one-sided bounces that never go below the
    floor): seq = [(apex_height, duration_s), ...]. 0 before t0 and after the last hop."""
    for h, d in seq:
        if t < t0:
            return 0.0
        if t < t0 + d:
            y = (t - t0) / d
            return h * 4.0 * y * (1.0 - y)
        t0 += d
    return 0.0


IMPACT_SHAPE = ((0, 1.0), (1, 0.55), (3, -0.22), (6, 0.07), (9, -0.02), (11, 0.0))


def impact_wave(k, weight=1.0):
    """Whole-body reaction after a contact, k = frames AT 24 FPS since the contact (float, = seconds * 24 at any fps):
    the extreme pose is the CONTACT frame itself (1 frame), 55% on the next, then a recoil of 22% the other way, 7%, 2%, back to rest in 11 frames; smooth
    between the extremes, each peak <= 60% of the previous. weight > 1 stretches it (heavier body, slower recovery).
    Multiply it by the squash / tilt / push of the body."""
    k = k / weight
    if k < 0.0 or k >= IMPACT_SHAPE[-1][0]:
        return 0.0
    for (ka, va), (kb, vb) in zip(IMPACT_SHAPE, IMPACT_SHAPE[1:]):
        if k <= kb:
            return va + (vb - va) * e_smooth((k - ka) / (kb - ka))
    return 0.0


def bake(root, ctx, pose, interp='BEZIER', cyc=False, ground=True, skip=()):
    """Samples pose(t) -> (loc, rot, scl) on EVERY frame f0..f1 (t = seconds since f0) and keys the root.
    loc: Vector offset from the rest centre in units of ctx.size (world axes); rot: 3x3 Matrix or None; scl: float / Vector
    / None. ground=True raises the product (never lowers it) so that no corner of its box goes below the floor.
    cyc=True: seamless loop (auto handles + Cycles modifier; pose at f1 must equal pose at f0). skip: channels not written,
    e.g. (('rotation_euler', 2),) when the caller keys them. Channels that never leave their rest value are not created;
    runs of identical values keep only their two ends. Returns the number of keys."""
    f0, f1, fps = ctx.f0, ctx.f1, ctx.fps
    size, center = ctx.size, ctx.center
    base_z = center.z - ctx.dims.z / 2.0
    w_soft = 0.005 * size                              # at most ~0.1% of size of play at the floor
    corners = ctx.info.corners
    rows, prev = [], None
    for f in range(f0, f1 + 1):
        loc, rot, scl = pose((f - f0) / fps)
        loc = Vector(loc) if loc is not None else Vector((0.0, 0.0, 0.0))
        rot = rot if rot is not None else Matrix.Identity(3)
        sc = Vector((scl, scl, scl)) if isinstance(scl, (int, float)) else (Vector(scl) if scl is not None else Vector((1.0, 1.0, 1.0)))
        pos = center + loc * size
        if ground:
            low = min((pos + rot @ Vector((c.x * sc.x, c.y * sc.y, c.z * sc.z))).z for c in corners)
            d = base_z - low
            if d > 0.0:                                  # lift by d, eased over its first w (C1: 2d^2/w - d^3/w^2), so rocking
                pos.z += (2.0 * d * d / w_soft - d ** 3 / (w_soft * w_soft)) if d < w_soft else d   # on an edge has no kink
        eul = rot.to_euler('XYZ', prev) if prev is not None else rot.to_euler('XYZ')
        prev = eul
        rows.append((f, pos, eul, sc))
    chans = []
    for i in range(3):
        chans.append(('location', i, [r[1][i] for r in rows], center[i]))
        chans.append(('rotation_euler', i, [r[2][i] for r in rows], 0.0))
        chans.append(('scale', i, [r[3][i] for r in rows], 1.0))
    frames = [r[0] for r in rows]
    n = 0
    for path, i, vals, rest in chans:
        if (path, i) in skip or max(abs(v - rest) for v in vals) < 1e-9:
            continue
        keep = [j for j in range(len(vals))
                if j in (0, len(vals) - 1) or abs(vals[j] - vals[j - 1]) > 1e-9 or abs(vals[j] - vals[j + 1]) > 1e-9]
        fc, kps = _keys(root, path, i, [(frames[j], vals[j]) for j in keep], interp)
        if cyc:
            for kp in kps:
                kp.handle_left_type = kp.handle_right_type = 'AUTO'
            fc.modifiers.new('CYCLES')
        fc.update()
        n += len(kps)
    return n


def life_yaw(root, ctx, t_from, t_to, amp_deg=2.0, period=None, sign=1.0):
    """The slow 'life' of a product that has finished its action: a decorative yaw of +-amp_deg on delta_rotation_euler Z
    (world Z, added on top of everything else) between t_from and t_to (seconds), smooth in and out (value and speed are
    zero at both ends); sign / period vary the swing from preset to preset. Needs >= 1.6 s; does nothing otherwise. Returns the keyed frames."""
    span = t_to - t_from
    if span < 1.6 or amp_deg <= 0.0:
        return []
    per = period or min(9.0, max(4.0, span / 2.2))
    ramp = min(1.4, 0.3 * span)
    step = per / 8.0
    ts = [t_from + step * k for k in range(int(span / step) + 1)]
    if t_to - ts[-1] > 1e-6:
        ts.append(t_to)
    pts = []
    for t in ts:
        env = e_smooth((t - t_from) / ramp) * e_smooth((t_to - t) / ramp)
        pts.append((ctx.f0 + int(round(t * ctx.fps)), sign * radians(amp_deg) * env * sin(tau * (t - t_from) / per)))
    pts[-1] = (pts[-1][0], 0.0)
    seen, uniq = set(), []
    for f, v in pts:
        if f not in seen:
            seen.add(f)
            uniq.append((f, v))
    fc, _ = _keys(root, 'delta_rotation_euler', 2, uniq)
    fc.update()
    return [f for f, _ in uniq]
