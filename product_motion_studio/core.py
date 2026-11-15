"""PMS core: product info/bounds, collections, scene snapshot, cleanup, camera fitting, ctx.

Everything PMS creates lives in collection PMS_SYSTEM (one sub-collection per section) and its
datablocks are named PMS_*: cleanup = remove the section's objects, then purge zero-user PMS_ data.
"""

import contextlib
import hashlib
import json
from math import pi, radians, sin, cos
import bpy
import numpy as np
from mathutils import Vector, Matrix
from . import motion

SYSTEM = 'PMS_SYSTEM'
SUB = {'product': 'PMS_Product', 'camera': 'PMS_Camera', 'lights': 'PMS_Lights',
       'background': 'PMS_Background', 'floor': 'PMS_Floor', 'bg_lights': 'PMS_BgLights'}
ROOT_NAME = 'PMS_Product_Root'
OV_ACT = 0.17           # share of the product's own extent that may leave the frame while it is in action (not on its hero pose)
EXIT_S = 0.5            # offscreen presets: frames this close (seconds) to an exit / entrance are part of it
MOSTLY_OUT = 0.3        # offscreen presets: a product with this share of its extent out of the frame (at the hero distance) is entering / leaving
ACT_PAD = -0.11         # ... and no corner may be farther out than 5.5 % of the frame (test_motion_quality: a flip sticks out by <= 6 %)
HERO_TOL = 0.03         # (size) a frame of a loop is on its rest position when the box centre is not farther than this from the first frame's
RECEIVERS = 'PMS_Backdrop_Receivers'      # light-linking receivers of backdrop-only lights (children: background, floor)
NO_FLOOR = 'PMS_Mirror_Floor_Excluded'   # light-linking receivers of the product lights over a mirror floor (floor excluded)
GEOMETRY = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'CURVES', 'POINTCLOUD', 'VOLUME',
            'GREASEPENCIL'}


# === collections and cleanup ================================================

def system_collection(scene):
    col = bpy.data.collections.get(SYSTEM)
    if col is None:
        col = bpy.data.collections.new(SYSTEM)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def section_collection(scene, key):
    """Sub-collection of PMS_SYSTEM for a section key of SUB (created on demand)."""
    name = SUB[key]
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    system = system_collection(scene)
    if col.name not in system.children:
        system.children.link(col)
    return col


def purge_orphans():
    """Remove PMS_* datablocks nobody uses any more."""
    d = bpy.data
    for coll in (d.meshes, d.lights, d.cameras, d.materials, d.worlds, d.actions,
                 d.node_groups, d.images, d.curves):
        for item in list(coll):
            if item.name.startswith('PMS_') and item.users == 0:
                coll.remove(item)


def clear_section(scene, key):
    """Delete every object a section created (idempotent builds start with this)."""
    col = bpy.data.collections.get(SUB[key])
    if col is not None:
        for ob in list(col.all_objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    purge_orphans()


def link(scene, key, ob):
    section_collection(scene, key).objects.link(ob)
    return ob


def new_empty(scene, key, name, location=(0, 0, 0), display='PLAIN_AXES', size=1.0, parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = display
    ob.empty_display_size = size
    ob.location = location
    link(scene, key, ob)
    if parent is not None:
        ob.parent = parent        # no parent inverse: location is in the parent's space
    return ob


# === scene snapshot (restored by remove_all) =================================

_QUIET = [0]


@contextlib.contextmanager
def quiet():
    """While active, the update callbacks of scene.pms do nothing (the api sets many props at once)."""
    _QUIET[0] += 1
    try:
        yield
    finally:
        _QUIET[0] -= 1


def is_quiet():
    return _QUIET[0] > 0


def owners():
    """Scenes where the studio (PMS_SYSTEM) is linked: its collections are global, so only one scene can use it."""
    col = bpy.data.collections.get(SYSTEM)
    return [s for s in bpy.data.scenes if col is not None and col.name in s.collection.children]


def claim_scene(scene):
    """Raise if another scene already holds the studio."""
    own = owners()
    if own and scene not in own:
        raise RuntimeError(f"PMS is already used in scene '{own[0].name}': remove it there or work in that scene")


def _hold(idb, saved, key):
    """Keep a reference to a user's datablock that PMS takes out of the scene. A fake user stops Blender from
    purging it (0 users) when the file is saved; we only remove it again if we were the ones to set it."""
    if idb is None:
        return
    saved[key] = idb
    if not idb.use_fake_user:
        idb.use_fake_user = True
        saved[key + '_fake'] = True


def begin(scene):
    """Call at the start of every build: remembers the user's scene settings once."""
    if 'pms_saved' in scene:
        return
    pms = settings(scene)
    r, vs = scene.render, scene.view_settings
    saved = {
        'res': [r.resolution_x, r.resolution_y, r.resolution_percentage],
        'fps': {'fps': r.fps, 'base': r.fps_base}, 'range': [scene.frame_start, scene.frame_end],
        'cur': scene.frame_current,
        'engine': r.engine, 'film': bool(r.film_transparent),
        'vs': {'vt': vs.view_transform, 'look': vs.look, 'exposure': vs.exposure, 'gamma': vs.gamma},
        'use_comp': bool(r.use_compositing), 'rt': bool(getattr(scene.eevee, 'use_raytracing', False))}
    saved['camera'] = scene.camera
    _hold(scene.world, saved, 'world')
    _hold(scene.compositing_node_group, saved, 'comp')
    scene['pms_saved'] = saved
    with quiet():                                            # first build: start from the scene, not from fixed defaults
        if not pms.is_property_set('fps'):
            pms.fps = max(1, min(120, int(r.fps)))
        if not pms.is_property_set('frame_start'):
            pms.frame_start = max(0, scene.frame_start)


def _saved_id(val, coll):
    """A saved reference: the datablock itself (or its name, in files saved by older versions)."""
    if isinstance(val, str):
        return coll.get(val) if val else None
    return val


def restore_scene(scene):
    s = scene.get('pms_saved')
    if s is None:
        return
    r, vs = scene.render, scene.view_settings
    world = _saved_id(s.get('world'), bpy.data.worlds)
    comp = _saved_id(s.get('comp'), bpy.data.node_groups)
    scene.world = world
    scene.camera = _saved_id(s.get('camera'), bpy.data.objects)
    r.resolution_x, r.resolution_y, r.resolution_percentage = s['res']
    r.fps, r.fps_base = s['fps']['fps'], s['fps']['base']
    scene.frame_start, scene.frame_end = s['range']
    r.film_transparent = s['film']
    r.use_compositing = s['use_comp']
    scene.compositing_node_group = comp
    for idb, key in ((world, 'world'), (comp, 'comp')):      # reassigned: the fake user we added is no longer needed
        if idb is not None and s.get(key + '_fake'):
            idb.use_fake_user = False
    try:
        r.engine = s['engine']
    except TypeError:
        pass
    if 'rt' in s and hasattr(scene.eevee, 'use_raytracing'):
        scene.eevee.use_raytracing = bool(s['rt'])
    try:
        v = s['vs']
        vs.view_transform, vs.look, vs.exposure, vs.gamma = v['vt'], v['look'], v['exposure'], v['gamma']
    except TypeError:
        pass
    if 'cur' in s:
        scene.frame_set(int(s['cur']))
    isolate_lights(scene, False)
    for key in [k for k in scene.keys() if k.startswith('pms_sig_')] + [k for k in ('pms_pct',) if k in scene]:
        del scene[key]
    del scene['pms_saved']


def isolate_lights(scene, on):
    """The user's own lights (not PMS_*) would add to the studio lighting: on = hide them (render + viewport),
    remembering their state on the object; off = put them back. Returns how many were hidden now."""
    n = 0
    if on:
        for ob in scene.objects:
            if (ob.type == 'LIGHT' and not ob.name.startswith('PMS_') and 'pms_hidden' not in ob
                    and not (ob.hide_render and ob.hide_viewport)):
                ob['pms_hidden'] = [int(ob.hide_render), int(ob.hide_viewport)]
                ob.hide_render = ob.hide_viewport = True
                n += 1
    else:
        for ob in bpy.data.objects:
            if 'pms_hidden' in ob:
                ob.hide_render, ob.hide_viewport = (bool(x) for x in ob['pms_hidden'])
                del ob['pms_hidden']
    return n


# === hand edits: what the user changed after PMS built a section =============

SIGNED = ('animation', 'camera', 'lighting', 'background', 'floor', 'bglight', 'compositing')   # steps whose result can be edited by hand
_SIG_SUB = {'camera': 'camera', 'lighting': 'lights', 'background': 'background', 'floor': 'floor', 'bglight': 'bg_lights'}
HAND = {'animation': ("Product motion edited by hand: not rebuilt", "Build Product Motion", 'product motion'),
        'camera': ("Camera edited by hand: not rebuilt", "Build Camera", 'camera'),
        'lighting': ("Lights edited by hand: not rebuilt", "Build Lighting", 'lights'),
        'background': ("Backdrop edited by hand: not rebuilt", "Build Background", 'backdrop'),
        'floor': ("Floor edited by hand: not rebuilt", "Build Floor", 'floor'),
        'bglight': ("Background lights edited by hand: not rebuilt", "Build Background Light", 'background lights'),
        'compositing': ("Look edited by hand: not rebuilt", "Build Look", 'look')}
_PROTECTED = set()                                           # steps being skipped now: nothing may move their objects


def hand_text(step):
    return f"{HAND[step][0]} (use {HAND[step][1]} to overwrite)"


def set_protected(steps):
    _PROTECTED.clear()
    _PROTECTED.update(steps)


def _n(v):
    return '%.5g' % (float(v) + 0.0)


def _val(v):
    if isinstance(v, str):
        return v
    try:
        return [_n(x) for x in v]
    except TypeError:
        pass
    try:
        return _n(v)
    except (TypeError, ValueError):
        return getattr(v, 'name', str(v))


def _getp(idb, path):
    for a in path.split('.'):
        idb = getattr(idb, a)
    return idb


def _anim(idb):
    """(animated channels, keyframes) of an ID's action: animated channels are compared through their keys."""
    animated, keys = set(), []
    for fc in motion.iter_fcurves(idb):
        animated.add((fc.data_path, fc.array_index))
        keys.append((fc.data_path, fc.array_index, [(_n(k.co.x), _n(k.co.y)) for k in fc.keyframe_points]))
    return animated, keys


def _props(idb, paths, animated):
    out = []
    for p in paths:
        try:
            v = _val(_getp(idb, p))
        except AttributeError:
            continue
        for i, x in enumerate(v if isinstance(v, list) else [v]):
            if (p, i) not in animated:
                out.append(x)
    return out


_OB_PROPS = ('location', 'rotation_euler', 'scale', 'hide_render', 'hide_viewport')
_DATA_PROPS = {'CAMERA': ('lens', 'sensor_width', 'clip_start', 'clip_end', 'dof.use_dof', 'dof.aperture_fstop',
                          'dof.focus_distance', 'dof.focus_object'),
               'LIGHT': ('type', 'energy', 'color', 'size', 'size_y', 'shadow_soft_size', 'spot_size', 'spot_blend',
                         'angle', 'use_temperature', 'temperature')}


def _ob_sig(ob):
    animated, keys = _anim(ob)
    parts = [ob.name, ob.parent.name if ob.parent else '', keys] + _props(ob, _OB_PROPS, animated)
    if ob.type in _DATA_PROPS:
        a2, k2 = _anim(ob.data)
        parts += [k2] + _props(ob.data, _DATA_PROPS[ob.type], a2)
    elif ob.type == 'MESH':
        parts.append([len(m.node_tree.nodes) for m in ob.data.materials if m and m.node_tree])
    return parts


def signature(scene, step):
    """Fingerprint of what can be edited by hand in a section ('' when it does not exist): object transforms (animated
    channels: their keyframes), camera lens/f-stop/focus, light energy/colour/size, number of keys and nodes."""
    if step == 'compositing':
        ng, vs = scene.compositing_node_group, scene.view_settings
        if ng is None or ng.name != 'PMS_Compositing':
            return ''
        parts = [len(ng.nodes), len(ng.links), vs.view_transform, vs.look, _n(vs.exposure), _n(vs.gamma)]
        for node in sorted(ng.nodes, key=lambda n: n.name):
            parts += [_val(s.default_value) for s in node.inputs if hasattr(s, 'default_value') and not s.is_linked]
    else:
        if step == 'animation':
            root = bpy.data.objects.get(ROOT_NAME)
            obs = [root] if root else []
        else:
            col = bpy.data.collections.get(SUB[_SIG_SUB[step]])
            obs = sorted(col.all_objects, key=lambda o: o.name) if col else []
        if not obs:
            return ''
        parts = [_ob_sig(o) for o in obs]
        w = scene.world
        if step == 'lighting' and w and w.name == 'PMS_World':
            bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
            parts.append([_val(bg.inputs['Color'].default_value), _val(bg.inputs['Strength'].default_value)] if bg else [])
    return hashlib.md5(repr(parts).encode()).hexdigest()[:16]


def stamp(scene, step):
    """Remember the section as PMS just left it (called at the end of every run)."""
    sig = signature(scene, step)
    if sig:
        scene['pms_sig_' + step] = sig
    elif 'pms_sig_' + step in scene:
        del scene['pms_sig_' + step]


def modified(scene, step):
    """True if the section was edited by hand since PMS built it."""
    old = scene.get('pms_sig_' + step)
    if not old:
        return False
    cur = signature(scene, step)
    return bool(cur) and cur != old


# === settings, overrides, presets ============================================

def settings(scene):
    """scene.pms (the add-on must be enabled: it never registers itself as a side effect)."""
    if not hasattr(bpy.types.Scene, 'pms'):
        raise RuntimeError("Product Motion Studio is not enabled: enable it in Preferences > Add-ons")
    return scene.pms


def overrides(scene, section):
    """Overrides of a section: the options saved in a personal function preset (user_presets.py) under the ones set now."""
    from . import presets
    pms = settings(scene)
    try:
        own = json.loads(pms.overrides).get(section, {})
    except ValueError:
        own = {}
    p = presets.REGISTRY.get(section, {}).get(getattr(pms, section, None))
    opts = p.meta.get('user_opts') if p is not None else None
    return {**opts, **own} if opts else own


def set_overrides(scene, section, values):
    pms = settings(scene)
    try:
        allv = json.loads(pms.overrides)
    except ValueError:
        allv = {}
    if values:
        allv[section] = values
    else:
        allv.pop(section, None)
    pms.overrides = json.dumps(allv)


def preset(scene, section):
    """(Preset, data dict with overrides applied) for the preset currently selected in a section."""
    from . import presets
    p = presets.get(section, getattr(settings(scene), section))
    data = dict(p.data) if p.data else {}
    data.update(overrides(scene, section))
    return p, data


def check_image(path):
    """ValueError unless `path` is an image Blender can read."""
    img = bpy.data.images.load(path, check_existing=True)
    ok = img.size[0] > 0 and img.size[1] > 0
    if img.users == 0:
        bpy.data.images.remove(img)
    if not ok:
        raise ValueError(f"bg_image: '{path}' is not a readable image")


# === product info ============================================================

class Info:
    """The prepared product: root, dims (world bbox extents), size (diagonal), center (rest pose)."""

    def __init__(self, root):
        self.root = root
        self.dims = Vector(root['pms_dims'])
        self.size = float(root['pms_size'])
        self.center = Vector(root['pms_center'])
        self.base_z = self.center.z - self.dims.z / 2
        h = self.dims / 2
        self.corners = [Vector((sx * h.x, sy * h.y, sz * h.z))
                        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]   # root-local


def info(scene=None):
    root = bpy.data.objects.get(ROOT_NAME)
    if root is None:
        raise RuntimeError("PMS: no product prepared (select objects and run Prepare / pms.build(objects=...))")
    return Info(root)


def has_product():
    return bpy.data.objects.get(ROOT_NAME) is not None


def clear_parts_motion(root):
    """Remove explode animation from all direct children of root that have pms_explode."""
    for ch in root.children:
        if ch.get('pms_explode'):
            action = ch.animation_data.action if ch.animation_data else None
            ch.animation_data_clear()
            if action and action.users == 0:
                bpy.data.actions.remove(action)
            ch.delta_location[2] = 0.0
            if 'pms_explode' in ch:
                del ch['pms_explode']


def reset_root(root):
    """Remove all animation from the root and put it back on its rest pose."""
    clear_parts_motion(root)
    root.animation_data_clear()
    restore_rest_values(root)
    purge_orphans()


def restore_rest_values(root):
    root.location = root['pms_center']
    root.rotation_mode = 'XYZ'
    root.rotation_euler = (0, 0, 0)
    root.scale = (1, 1, 1)
    root.delta_location = (0, 0, 0)
    root.delta_rotation_euler = (0, 0, 0)


def unprepare(root):
    """Give every product object its original parent/parent-inverse; delete the root. Returns the products."""
    clear_parts_motion(root)
    products = []
    for ob in list(root.children):
        orig = ob.get('pms_orig')
        if orig is not None:
            ob.parent = bpy.data.objects.get(orig['parent']) if orig['parent'] else None
            ob.matrix_parent_inverse = Matrix([orig['pinv'][i * 4:i * 4 + 4] for i in range(4)])
            del ob['pms_orig']
        products.append(ob)
    bpy.data.objects.remove(root, do_unlink=True)
    purge_orphans()
    return products


# === camera geometry =========================================================

def frame_tans(scene, lens, sensor=36.0):
    """Half-extent of the frame at distance 1: (tan_x, tan_y) for sensor_fit AUTO."""
    r = scene.render
    aspect = (r.resolution_x * r.pixel_aspect_x) / (r.resolution_y * r.pixel_aspect_y)
    t = (sensor / 2) / lens
    return (t, t / aspect) if aspect >= 1 else (t * aspect, t)


def cam_basis(az, el):
    """Camera at azimuth az / elevation el (radians) around the target: (right, up, back) where
    back points from the target to the camera. az 0 = in front (-Y), positive az goes to +X."""
    back = Vector((sin(az) * cos(el), -cos(az) * cos(el), sin(el)))
    right = Vector((cos(az), sin(az), 0.0))
    return right, back.cross(right), back


def basis(az, el):
    """cam_basis for arrays of az / el (radians): (right, up, back), each (..., 3)."""
    az, el = np.asarray(az, float), np.asarray(el, float)
    back = np.stack([np.sin(az) * np.cos(el), -np.cos(az) * np.cos(el), np.sin(el) + 0 * az], axis=-1)
    right = np.stack([np.cos(az) + 0 * el, np.sin(az) + 0 * el, 0 * az + 0 * el], axis=-1)
    return right, np.cross(back, right), back


def _euler_xyz(e):
    """(n, 3, 3) rotation matrices of Blender XYZ euler angles (n, 3) in radians."""
    cx, cy, cz = np.cos(e).T
    sx, sy, sz = np.sin(e).T
    R = np.empty((len(e), 3, 3))
    R[:, 0] = np.stack([cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz], axis=1)
    R[:, 1] = np.stack([cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz], axis=1)
    R[:, 2] = np.stack([-sy, sx * cy, cx * cy], axis=1)
    return R


def smooth_max(r, k):
    """Smooth upper envelope of the samples r: >= r everywhere, flat at both ends (the samples are mirrored there) and as close
    to r as smoothness allows: the double box blur of r (+-k samples) plus a margin that covers where r pokes above it (the
    margin itself is a max over +-2k samples, blurred twice: a smooth bump only at the peaks of r, nothing on smooth stretches,
    so a move that starts from rest keeps its start from rest)."""
    r = np.asarray(r, float)
    n = len(r)
    k = int(min(k, (n - 1) // 4))
    if k < 1:
        return r.copy()
    box = np.ones(2 * k + 1) / (2 * k + 1)

    def blur(a):
        return np.convolve(np.convolve(np.pad(a, 2 * k, mode='symmetric'), box, mode='valid'), box, mode='valid')
    b = blur(r)
    d = np.max(np.lib.stride_tricks.sliding_window_view(np.pad(np.maximum(r - b, 0.0), 4 * k, mode='symmetric'), 4 * k + 1), axis=1)
    return b + blur(d[2 * k:-2 * k])


def _closed(x, y, t, tans, pad):
    """Distance at which points with camera coordinates x (right), y (up), t (towards the camera), shape (..., K), fit the
    frame leaving `pad` (fraction of the half frame; negative = overfill; may be an array broadcast on (...)): (...,)."""
    pad = np.asarray(pad, float)[..., None] if np.ndim(pad) else pad
    return np.max(np.maximum(t + np.abs(x) / (tans[0] * (1 - pad)), t + np.abs(y) / (tans[1] * (1 - pad))), axis=-1)


def _halves(q, t, d, tan):
    """Position of points in half frames (frame = -1..1) along one camera axis, seen from distance d (...,): (..., K)."""
    return q / (np.maximum(d[..., None] - t, 1e-9) * tan)


def _over(x, y, t, d, tans):
    """Fraction of the points' extent outside the frame (worst axis) and whether their centre is outside, at distance d
    (same definition as the framing tests): ((...,), (...,) bool). A point at or behind the camera counts as out."""
    behind = (t >= d[..., None] - 1e-9).any(axis=-1)
    over = np.zeros(d.shape)
    for q, tn in ((x, tans[0]), (y, tans[1])):
        u = _halves(q, t, d, tn)
        lo, hi = u.min(axis=-1), u.max(axis=-1)
        over = np.maximum(over, (np.maximum(0, -1 - lo) + np.maximum(0, hi - 1)) / np.maximum(hi - lo, 1e-9))
    centre = [np.abs(_halves(q.mean(axis=-1, keepdims=True), t.mean(axis=-1, keepdims=True), d, tn))[..., 0]
              for q, tn in ((x, tans[0]), (y, tans[1]))]
    return np.where(behind, 9.0, over), behind | (np.maximum(*centre) > 1.0)


def _open_dist(x, y, t, tans, ov, d0):
    """Smallest distance at which at most `ov` of the points' extent (worst axis) is outside the frame, shape (...,).
    Exact for a flat product, refined 4 times for the perspective: on each axis the overflow limit gives c = (d_ref - t) / (d - t) <=
    min(1 / (hi - ov E), 1 / (-lo - ov E), 2 / (E (1 - ov))) (E = extent, hi / lo = its ends, in half frames)."""
    d = np.asarray(d0, float)
    cmin = np.full(d.shape, np.inf)
    for _ in range(4):
        cmin = np.full(d.shape, np.inf)
        for q, tn in ((x, tans[0]), (y, tans[1])):
            u = _halves(q, t, d, tn)
            hi, lo = u.max(axis=-1), u.min(axis=-1)
            e = hi - lo
            with np.errstate(divide='ignore', invalid='ignore'):
                c = np.minimum(np.where(hi - ov * e > 0, 1 / (hi - ov * e), np.inf),
                               np.where(-lo - ov * e > 0, 1 / (-lo - ov * e), np.inf))
                c = np.minimum(c, np.where(e > 0, 2 / (e * (1 - ov)), np.inf))
            cmin = np.minimum(cmin, c)
        tm = t.mean(axis=-1)                                  # image size goes with 1 / (d - t): scale the depth, not d
        d = np.where(np.isfinite(cmin), np.maximum(tm + (d - tm) / np.where(np.isfinite(cmin), cmin, 1.0), t.max(axis=-1) + 1e-6), d)
    return np.where(np.isfinite(cmin), d, 0.0)


class Track:
    """The REAL motion of the product: its box corners in the world at every frame f0..f1, read from the root's f-curves
    (no frame_set: under 1 ms for 100 frames). The camera is fitted on these, not on a theoretical envelope.
      hero      the poses that must fill the frame with the full padding: the last pose; for a loop the frames on its rest
                position (a loop turns freely there, only a bounce / hover is action) -> `H`;
      exempt[f] frames where the product is out of the frame on purpose (see mark_offscreen): ignored;
      action    the other frames: the product may leave the frame by up to OV_ACT of its own extent (a flip, a bounce), with
                no corner more than ACT_PAD out.
    At every instant the camera must fit the HERO pose seen from its angle at that instant (so an orbit keeps the product at
    the same size) and the product as it is at that frame within the action allowance (so a flip is never cut)."""

    MAX_HERO = 48            # hero poses kept (a spin loop has one per frame: every few frames is enough)

    def __init__(self, inf, f0, f1, loop=False, fps=24):
        root = inf.root
        fcs = {(fc.data_path, fc.array_index): fc for fc in motion.iter_fcurves(root)}
        self.frames = np.arange(f0, f1 + 1)
        n = len(self.frames)

        def vec(path):
            base = getattr(root, path)
            return np.stack([np.array([fcs[(path, i)].evaluate(f) for f in self.frames]) if (path, i) in fcs
                             else np.full(n, float(base[i])) for i in range(3)], axis=1)
        R = _euler_xyz(vec('delta_rotation_euler')) @ _euler_xyz(vec('rotation_euler'))
        corners = np.array([tuple(c) for c in inf.corners]) * (vec('scale') * np.array(root.delta_scale))[:, None, :]
        self.pts = (vec('location') + vec('delta_location'))[:, None, :] + np.einsum('nij,nkj->nki', R, corners)
        self.size, self.loop, self.near = inf.size, loop, max(1, round(EXIT_S * fps))
        self.roll = 0.0
        ctr = self.pts.mean(axis=1)
        if loop:
            self.hero = np.linalg.norm(ctr - ctr[0], axis=1) < HERO_TOL * self.size
            self.H = self.pts[self.hero]
            self.H = self.H[np.linspace(0, len(self.H) - 1, min(len(self.H), self.MAX_HERO)).round().astype(int)]
        else:
            self.hero = np.abs(self.pts - self.pts[-1]).max(axis=(1, 2)) < 1e-4 * self.size       # the final pose
            self.H = self.pts[-1:]
        self.exempt, self.offscreen = np.zeros(n, bool), False

        # Account for parts with pms_explode: they lift along Z, expand the camera bounds
        if any(ch.get('pms_explode') for ch in inf.root.children):
            extra = np.zeros(n)
            for ch in inf.root.children:
                if ch.get('pms_explode'):
                    for fc in motion.iter_fcurves(ch):
                        if fc.data_path == 'delta_location' and fc.array_index == 2:
                            vals = np.array([fc.evaluate(f) for f in self.frames])
                            extra = np.maximum(extra, np.maximum(vals, 0.0))
            # Find the 4 highest corners (max local z in inf.corners)
            corners_local = np.array([tuple(c) for c in inf.corners])
            top_indices = np.argsort(corners_local[:, 2])[-4:]
            self.pts[:, top_indices, 2] += extra[:, None]

    def _roll(self, x, y):
        """Rotate x, y by self.roll (radians). If roll is 0 returns (x, y) unchanged."""
        if self.roll == 0.0:
            return x, y
        c, s = np.cos(self.roll), np.sin(self.roll)
        return x * c - y * s, x * s + y * c

    def action(self):
        """Frames that only have to respect the action allowance."""
        return ~self.exempt & (~self.hero if self.loop else True)

    def hero_center(self):
        """Centre of the product's box on its hero pose (the camera looks at it)."""
        return self.H.mean(axis=(0, 1)) if self.loop else self.pts[-1].mean(axis=0)

    def _coords(self, pts, target, az, el):
        """Camera coordinates (x right, y up, t towards the camera) of pts (F, K, 3) for the camera angles az, el (radians,
        arrays of C values): three arrays (C, F, K). Roll is applied to x, y."""
        rel = pts - np.asarray(target)
        x, y, t = (np.einsum('fkc,qc->qfk', rel, v) for v in basis(az, el))
        xr, yr = self._roll(x, y)
        return xr, yr, t

    def _ov(self, pad):
        """Overflow allowed in action: OV_ACT, or what the hero padding itself overfills (+ 4 %) when that is more."""
        return max(OV_ACT, (-pad / (1 - pad) + 0.04) if pad < 0 else 0.0)

    def _action_dist(self, x, y, t, tans, pad):
        """Distance an action frame needs: at most OV_ACT of the product's extent out of the frame, and no corner farther out
        than ACT_PAD allows (whichever is stricter)."""
        ov = self._ov(pad)
        return np.maximum(_open_dist(x, y, t, tans, ov, _closed(x, y, t, tans, -ov)),
                          _closed(x, y, t, tans, min(pad, ACT_PAD)))

    def fit(self, target, azs, els, tans, pad, only_hero=False, strict=False):
        """Constant distance at which the hero pose fits the frame leaving `pad` (fraction of the half frame, negative =
        overfill) and the action frames overflow by at most OV_ACT of the product's extent (ACT_PAD at the corners), for every camera az / el
        (radians) of the given sequences. only_hero: just the hero pose; strict: the action frames get `pad` too."""
        a, e = np.meshgrid(np.atleast_1d(azs), np.atleast_1d(els))
        a, e = a.ravel(), e.ravel()
        x, y, t = self._coords(self.H, target, a, e)
        d = float(_closed(x, y, t, tans, pad).max())
        act = self.pts[self.action()]
        if only_hero or not len(act):
            return d
        _, k = np.unique(np.round(act.reshape(len(act), -1) / (1e-4 * self.size)), axis=0, return_index=True)
        x, y, t = self._coords(act[np.sort(k)], target, a, e)
        if strict:
            return max(d, float(_closed(x, y, t, tans, pad).max()))
        return max(d, float(self._action_dist(x, y, t, tans, pad).max()))

    def curve(self, target, az, el, tans, pad, strict=False):
        """Distance needed at each frame f0..f1 for a camera at az[f] / el[f] (radians, one per frame): (n,) array."""
        right, up, back = basis(az, el)
        rel = self.H - np.asarray(target)                                      # the hero pose(s), seen from each frame's angle
        xh, yh, th = (np.einsum('hkc,nc->nhk', rel, v).reshape(len(az), -1) for v in (right, up, back))
        xh, yh = self._roll(xh, yh)
        r = _closed(xh, yh, th, tans, pad)
        rel = self.pts - np.asarray(target)
        x, y, t = (np.einsum('nkc,nc->nk', rel, v) for v in (right, up, back))
        x, y = self._roll(x, y)
        ex = self._offscreen(x, y, t, r, tans, pad) if self.offscreen else self.exempt   # along the path of THIS camera
        act = ~ex & (~self.hero if self.loop else True)
        if not act.any():
            return r
        if strict:
            ra = _closed(x, y, t, tans, pad)
        else:
            ra = self._action_dist(x, y, t, tans, pad)
        return np.where(act, np.maximum(r, ra), r)

    def _offscreen(self, x, y, t, d, tans, pad):
        """Mask of the frames out of the frame on purpose, for the camera coordinates x, y, t (n, K) and the hero distance d
        (n,) of each frame: the frames that need more distance than the hero pose (they stick out by more than the action may)
        within EXIT_S seconds of a moment when the product is out of the frame, or mostly out of it, are exempt."""
        over, centre_out = _over(x, y, t, d, tans)
        partial = self._action_dist(x, y, t, tans, pad) > d * 1.005       # frames that would push the camera farther than the hero needs
        centre_out = centre_out | (over > MOSTLY_OUT)
        near = np.zeros(len(partial), bool)
        for i in np.flatnonzero(centre_out):
            near[max(0, i - self.near):i + self.near + 1] = True
        return partial & near & ~self.hero

    def mark_offscreen(self, target, az, el, tans, pad):
        """Presets that enter or leave the frame on purpose (meta offscreen: slide-ins, drops from above or from the camera,
        fly-bys, exits): seen from the shot's camera, fitted on the hero pose, the runs of frames in which the product is out
        of the frame are exempt (see _offscreen). A flip that only spills over the border is not. curve() redoes it along the
        path of a moving camera."""
        self.offscreen = True
        d = self.fit(target, [az], [el], tans, pad, only_hero=True)
        x, y, t = (np.einsum('nkc,c->nk', self.pts - np.asarray(target), v[0]) for v in basis([az], [el]))
        x, y = self._roll(x, y)
        self.exempt = self._offscreen(x, y, t, np.full(len(self.pts), d), tans, pad)

    def ortho_scale(self, target, az, el, tans, pad):
        """Orthographic scale for the given az, el (radians, scalars) covering ALL frames of self.pts with padding `pad`.
        Returns the ortho_scale (width of the longer side of the image in world units)."""
        x, y, _ = self._coords(self.pts, target, np.atleast_1d(az), np.atleast_1d(el))
        tx, ty = tans
        t = max(tx, ty)
        return float(2 * t * max(np.abs(x).max() / tx, np.abs(y).max() / ty) / (1 - pad))


def _samples(v, step):
    if isinstance(v, (tuple, list)):
        n = max(2, int(abs(v[1] - v[0]) / step) + 1)
        return [radians(v[0] + (v[1] - v[0]) * i / (n - 1)) for i in range(n)]
    return [radians(v)]


def frame_range(pms):
    """(f0, f1) of the animation: `duration` frames from the start frame."""
    f0 = int(pms.frame_start)
    return f0, f0 + int(pms.duration) - 1


def is_loop(scene):
    """The result loops when both the product motion and the camera motion do (camera 'static' counts as loop)."""
    return bool(preset(scene, 'product_motion')[0].meta.get('loop') and preset(scene, 'camera_motion')[0].meta.get('loop'))


class OptDict(dict):
    """User overrides as the presets see them (ctx.opt); remembers which names were read, so the api can flag unknown ones."""

    def __init__(self, *a):
        super().__init__(*a)
        self.used = set()

    def get(self, key, default=None):
        self.used.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.used.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.used.add(key)
        return super().__contains__(key)


class Ctx:
    """What preset functions receive. Time helpers + product scale + free overrides (opt)."""

    def __init__(self, scene, inf, opt=None):
        pms = settings(scene)
        self.scene, self.info = scene, inf
        self.f0, self.f1 = frame_range(pms)
        self.fps = int(pms.fps)
        self.size, self.center, self.dims = inf.size, inf.center.copy(), inf.dims.copy()
        self.axis_up = Vector((0, 0, 1))
        self.opt = OptDict(opt or {})
        _, shot = preset(scene, 'camera_shot')
        a = radians(shot.get('az', 0))
        self.right = Vector((cos(a), sin(a), 0.0))     # screen-right of the base shot (world XY)

    def t(self, u):
        """Normalized time 0..1 -> integer frame in f0..f1."""
        return int(round(self.f0 + u * (self.f1 - self.f0)))


class CamCtx(Ctx):
    """Ctx for camera_motion: base az/el (radians), dist (fitted distance), lens, fit(), curve(), track (the product's
    real motion)."""

    def __init__(self, scene, inf, opt, az, el, dist, lens, padding, track, target):
        super().__init__(scene, inf, opt)
        self.az, self.el, self.dist, self.lens, self.padding = az, el, dist, lens, padding
        self.az_deg, self.el_deg = az * 180 / pi, el * 180 / pi
        self.track, self.target = track, target
        self.tans = frame_tans(scene, lens)

    def fit(self, az=None, el=None, padding=None, lens=None, strict=False):
        """Constant distance that keeps the product (its real motion) framed for every az/el in the given degrees; each may
        be a number or a (start, end) sweep. Defaults: the base az/el of the shot and its lens."""
        azs = _samples(az, 10) if az is not None else [self.az]
        els = _samples(el, 5) if el is not None else [self.el]
        tans = self.tans if lens is None else frame_tans(self.scene, lens)
        return self.track.fit(self.target, azs, els, tans, self.padding if padding is None else padding, strict=strict)

    def curve(self, az, el, padding=None, strict=False):
        """Distance needed at every frame f0..f1 by a camera at az[f] / el[f] (arrays, DEGREES): shape (f1 - f0 + 1,)."""
        return self.track.curve(self.target, np.radians(az), np.radians(el), self.tans,
                                self.padding if padding is None else padding, strict)

    def envelope(self, need):
        """Smooth distance curve (array per frame) that is never below `need` (see curve) and is flat at the ends."""
        return smooth_max(need, max(2, min(round(0.25 * self.fps), len(need) // 16)))     # (short clips: a narrower window)


def orient_rigs(scene):
    """Light rig and backdrop follow the azimuth of the base shot (lit relative to the camera)."""
    az = radians(settings(scene).base_az)
    for name, step in (('PMS_Light_Rig', 'lighting'), ('PMS_Background', 'background'), ('PMS_Floor', 'floor'),
                       ('PMS_BgLight_Rig', 'bglight')):
        ob = bpy.data.objects.get(name)
        if ob is not None and ob.get('pms_orient', True) and step not in _PROTECTED:     # hand-edited: stays as it is
            ob.rotation_euler = (0, 0, az)
