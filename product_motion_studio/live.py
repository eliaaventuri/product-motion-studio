"""Live controls: panel properties that change the built studio at once, without a Build.

Each section with live controls has a few props in scene.pms (see props.py). Two jobs:
  - the builders read them (`preset()` = core.preset + live values), so a rebuild keeps what the user set;
  - the update callbacks (`updater()`) edit the existing PMS objects in place (cheap), then stamp the section again,
    so a live change is never reported as "edited by hand" (a section that WAS edited by hand stays so: the stamp is kept).
The live values go back to the preset's defaults when the section's preset (or its overrides) changes: `sync()` compares a
marker "preset id|overrides" stored in pms.live_marks with the current one. api.apply()/build() forget the marker of the
sections they set, so choosing a preset explicitly always starts from its defaults.
"""

import json
import traceback
from math import log, radians

import bpy

from . import core, motion

# section -> (signature step, live props)
GROUPS = {
    'camera_shot': ('camera', ('cam_lens', 'cam_padding', 'cam_dof', 'cam_fstop', 'cam_focus', 'cam_autofocus')),
    'lighting': ('lighting', ('light_power', 'light_tint', 'light_rot', 'light_fill', 'light_rim', 'light_temp')),
    'background': ('background', ('bg_color_a', 'bg_color_mid', 'bg_color_b', 'bg_type', 'bg_rotation', 'bg_roughness',
                                  'bg_selflight', 'bg_distance', 'bg_cove')),
    'background_light': ('bglight', ('bgl_color', 'bgl_power')),
    'floor': ('floor', ('floor_color', 'floor_roughness')),
    'look': ('compositing', ('look_intensity', 'look_exposure')),
}
PROPS = tuple(p for _, ps in GROUPS.values() for p in ps)
FSTOP = 5.6          # f-stop shown (DOF off) when the preset has no depth of field


# === defaults, marker, sync ===================================================

def _stops(data):
    return sorted(((float(p), tuple(c)) for p, c in data['stops']), key=lambda s: s[0])


def _mid_index(stops):
    """Index of the interior stop nearest to 0.5 (None when the gradient has only two stops)."""
    if len(stops) < 3:
        return None
    return min(range(1, len(stops) - 1), key=lambda i: abs(stops[i][0] - 0.5))


def defaults(scene, section, data):
    """Live prop values a preset's data stands for."""
    pms = core.settings(scene)
    if section == 'camera_shot':
        f = float(data.get('dof', 0) or 0)
        return dict(cam_lens=float(data['lens']), cam_padding=float(data['padding']), cam_dof=f > 0,
                    cam_fstop=f if f > 0 else FSTOP, cam_focus=float(data.get('focus_offset', 0.0)),
                    cam_autofocus=bool(data.get('autofocus', False)))
    if section == 'lighting':
        return dict(light_power=1.0, light_tint=(1.0, 1.0, 1.0), light_rot=0.0,
                    light_fill=1.0, light_rim=1.0, light_temp=0.0)
    if section == 'background_light':
        return dict(bgl_power=1.0, bgl_color=(1.0, 1.0, 1.0))
    if section == 'background':
        stops, g = _stops(data), data.get('gradient', {})
        m = _mid_index(stops)
        a, b = stops[0][1], stops[-1][1]
        return dict(bg_color_a=a, bg_color_b=b, bg_color_mid=stops[m][1] if m else tuple((x + y) / 2 for x, y in zip(a, b)),
                    bg_type='RADIAL' if g.get('type') == 'radial' else 'LINEAR', bg_rotation=float(g.get('rotation', 0)),
                    bg_roughness=float(data.get('roughness', 0.9)), bg_selflight=float(data.get('self_light', 0.0)),
                    bg_distance=float(data.get('distance', 1.0)), bg_cove=float(data.get('cove', 1.0)))
    if section == 'floor':
        return dict(floor_color=tuple(data.get('color') or pms.bg_color_a),
                    floor_roughness=float(data.get('roughness', 0.85)))
    if section == 'look':
        return dict(look_intensity=float(data.get('intensity', 1.0)), look_exposure=float(data.get('exposure', 0.0)))
    raise KeyError(section)


def merge(scene, section, data):
    """The preset's data with the live values folded in (what the builders use)."""
    pms = core.settings(scene)
    d = dict(data)
    if section == 'camera_shot':
        d.update(lens=pms.cam_lens, padding=pms.cam_padding, dof=pms.cam_fstop if pms.cam_dof else 0.0,
                 fstop=pms.cam_fstop, focus_offset=pms.cam_focus, autofocus=pms.cam_autofocus)
    elif section == 'background':
        stops = _stops(data)
        m = _mid_index(stops)
        stops[0] = (stops[0][0], tuple(pms.bg_color_a))
        stops[-1] = (stops[-1][0], tuple(pms.bg_color_b))
        if m:
            stops[m] = (stops[m][0], tuple(pms.bg_color_mid))
        g = dict(data.get('gradient', {}))
        g['type'], g['rotation'] = pms.bg_type.lower(), pms.bg_rotation
        d.update(stops=stops, gradient=g, roughness=pms.bg_roughness, self_light=pms.bg_selflight,
                 distance=pms.bg_distance, cove=pms.bg_cove)
    elif section == 'floor':
        d.update(color=tuple(pms.floor_color), roughness=pms.floor_roughness)
    elif section == 'look':
        d.update(exposure=pms.look_exposure, intensity=pms.look_intensity)
    return d


def marks(pms):
    try:
        return json.loads(pms.live_marks)
    except ValueError:
        return {}


def marker(scene, section, p):
    """'preset id|overrides' (the floor also follows the backdrop it was made for)."""
    m = p.id + '|' + json.dumps(core.overrides(scene, section), sort_keys=True)
    return m + '|' + core.settings(scene).background if section == 'floor' else m


def preset(scene, section):
    """(Preset, data with overrides and live values) of a section with live controls. When its preset or overrides changed
    since the live values were last set, the live values go back to the new preset's defaults first."""
    p, data = core.preset(scene, section)
    pms = core.settings(scene)
    cur, m = marks(pms), marker(scene, section, p)
    if cur.get(section) != m:
        with core.quiet():
            for k, v in defaults(scene, section, data).items():
                setattr(pms, k, v)
            cur[section] = m
            pms.live_marks = json.dumps(cur)
    return p, merge(scene, section, data)


def forget(scene, sections=None):
    """The next build of these sections (default: all) starts from the preset's defaults."""
    pms = core.settings(scene)
    cur = marks(pms)
    for s in (sections or GROUPS):
        cur.pop(s, None)
    with core.quiet():
        pms.live_marks = json.dumps(cur)


def clear(scene):
    """remove_all: every live prop back to its RNA default, no markers."""
    pms = core.settings(scene)
    with core.quiet():
        for k in PROPS:
            pms.property_unset(k)
        pms.live_marks = '{}'


def is_built(scene, section):
    return section in marks(core.settings(scene))


def values(scene):
    """{prop: value} of every live control (for api.state())."""
    pms = core.settings(scene)
    out = {}
    for k in PROPS:
        v = getattr(pms, k)
        out[k] = v if isinstance(v, (str, bool)) else (tuple(round(x, 5) for x in v) if hasattr(v, '__len__') else round(v, 5))
    return out


# === applying values to the objects ============================================

ROLE_PROPS = {'fill': 'light_fill', 'rim': 'light_rim', 'back': 'light_rim'}   # light role -> its live power factor


def kelvin_rgb(k):
    """Tanner Helland blackbody approximation (k clamped 1000..40000, t = k/100). Returns tuple of 3 floats (linear 0..1)."""
    k = max(1000, min(40000, k))
    t = k / 100.0
    if t <= 66:
        r = 255
        g = 99.4708025861 * log(t) - 161.1195681661
        b = 138.5177312231 * log(t - 10) - 305.0447927307 if t > 10 else 0
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255
    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    return ((r / 255.0) ** 2.2, (g / 255.0) ** 2.2, (b / 255.0) ** 2.2)


def temp_factor(shift):
    """Factor to multiply colour by for a temperature shift in kelvin (shift 0 -> (1,1,1), luminance preserved)."""
    a = kelvin_rgb(6500 + shift)
    b = kelvin_rgb(6500)
    f = [x / y if y > 0 else 1.0 for x, y in zip(a, b)]
    # normalize to keep luminance (ITU-R BT.709 weights)
    lum = 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
    if lum > 0:
        f = [x / lum for x in f]
    return tuple(f)


def scale_lights(scene, key, power, tint, roles=None, warm=(1.0, 1.0, 1.0)):
    """energy = base * power * role_factor, colour = base * tint * warm, for every light of a section."""
    pms = core.settings(scene)
    col = bpy.data.collections.get(core.SUB[key])
    for ob in (col.all_objects if col else ()):
        base = ob.data.get('pms_base') if ob.type == 'LIGHT' else None
        if base:
            role = ob.data.get('pms_role', 'light')
            role_factor = getattr(pms, roles[role]) if roles and role in roles else 1.0
            ob.data.energy = base[0] * power * role_factor
            ob.data.color = [base[1 + i] * tint[i] * warm[i] for i in range(3)]


def apply_lights(scene):
    """Lighting live values: power and tint on the lights and on the world, rig rotation, temperature shift."""
    pms = core.settings(scene)
    warm = temp_factor(pms.light_temp)
    scale_lights(scene, 'lights', pms.light_power, pms.light_tint, ROLE_PROPS, warm)
    w = scene.world
    if w is not None and w.name == 'PMS_World' and w.get('pms_base'):
        bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
        if bg is not None:
            b = w['pms_base']
            bg.inputs['Strength'].default_value = b[0] * pms.light_power
            bg.inputs['Color'].default_value = (*(b[1 + i] * pms.light_tint[i] * warm[i] for i in range(3)), 1.0)
    rig = bpy.data.objects.get('PMS_Light_Rig')
    if rig is not None:
        rig.delta_rotation_euler[2] = radians(pms.light_rot)


def apply_bg_lights(scene):
    pms = core.settings(scene)
    scale_lights(scene, 'bg_lights', pms.bgl_power, pms.bgl_color)


def apply_focus(scene, cam_data=None, auto=True):
    """DOF on/off, f-stop and the focus point (the DOF empty, moved along the base view direction by delta_location so
    that the focus pull of a camera motion keeps working), then Auto Focus (auto=False: the camera build bakes it after
    the camera motion, so that the focus follows the moving camera)."""
    pms = core.settings(scene)
    cam = bpy.data.objects.get('PMS_Camera')
    cd = cam_data or (cam.data if cam else None)
    if cd is None:
        return
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    cd.dof.aperture_fstop = pms.cam_fstop
    cd.dof.use_dof = bool(pms.cam_dof)
    if focus is not None:
        cd.dof.focus_object = focus
        back = focus.get('pms_back')
        if back is not None:
            size = float(core.info(scene).size)
            focus.delta_location = [b * pms.cam_focus * size for b in back]
    if auto:
        autofocus(scene, cam)


def autofocus(scene, cam):
    """Auto Focus on (with DOF): bake the focus on the product surface; off: put the DOF empty back in charge."""
    pms = core.settings(scene)
    if cam is not None and pms.cam_autofocus and pms.cam_dof:
        bake_autofocus(scene, cam)
    else:
        clear_autofocus(cam)


def _surface(scene, dg, origin, target, prods, size):
    """Distance from origin to the first product surface on the way to target (scene objects in front are skipped);
    the distance to target when nothing of the product is hit."""
    d = target - origin
    far = d.length
    if far < 1e-9:
        return far
    ray = d / far
    start = origin
    for _ in range(8):                                   # at most 8 non-product hits (floor, backdrop, props)
        hit, loc, _n, _i, ob, _m = scene.ray_cast(dg, start, ray, distance=2 * far)
        if not hit:
            break
        if ob.original in prods:
            return (loc - origin).length
        start = loc + ray * 1e-4 * size
    return far


def bake_autofocus(scene, cam):
    """Key dof.focus_distance on every frame at the product surface seen from the camera towards the DOF empty
    (+ Focus Offset), linear keys; the camera then focuses by distance (no focus object)."""
    pms = core.settings(scene)
    root = bpy.data.objects.get(core.ROOT_NAME)
    if root is None:
        return
    prods = set(root.children_recursive)
    size = float(core.info(scene).size)
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    saved = scene.frame_current
    keys = []
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        target = (focus or root).matrix_world.translation
        dist = _surface(scene, dg, cam.matrix_world.translation.copy(), target, prods, size)
        keys.append((f, max(1e-3, dist + pms.cam_focus * size)))
    scene.frame_set(saved)
    cd = cam.data
    cd.dof.focus_object = None
    motion.remove_fcurves(cd, 'dof.focus_distance')
    for f, dist in keys:
        cd.dof.focus_distance = dist
        cd.keyframe_insert('dof.focus_distance', frame=f)
    fc = motion._fcurve(cd, 'dof.focus_distance')
    for kp in fc.keyframe_points:
        kp.interpolation = 'LINEAR'
    cd['pms_autofocus'] = True


def clear_autofocus(cam):
    """Remove the Auto Focus keys and give the focus back to the DOF empty."""
    if cam is None or not cam.data.get('pms_autofocus'):
        return
    cd = cam.data
    motion.remove_fcurves(cd, 'dof.focus_distance')
    if not any(True for _ in motion.iter_fcurves(cd)):
        cd.animation_data_clear()
    del cd['pms_autofocus']
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    if focus:
        cd.dof.focus_object = focus


# === update callbacks =============================================================

def _run_live(scene, step, fn):
    pms = scene.pms
    if core.is_quiet() or scene not in core.owners() or not core.has_product():
        return
    was_edited = core.modified(scene, step)                  # an edit by hand stays one: only a clean section is stamped again
    try:
        fn(scene, pms)
    except Exception:                                        # noqa: BLE001 (a callback cannot raise usefully)
        traceback.print_exc()
        return
    if not was_edited:
        core.stamp(scene, step)


def updater(step, fn):
    """Update callback for a live prop: runs fn(scene, pms) on the built objects (nothing before the first build)."""
    def update(self, context):
        _run_live(self.id_data, step, fn)
    return update


def refit(scene, pms):
    """Lens / padding: the distance is fitted again for the whole motion, so the camera section runs again (what depends on it
    follows). A camera edited by hand is not rebuilt: the lens is set in place."""
    cam = bpy.data.objects.get('PMS_Camera')
    if cam is None:
        return
    if core.modified(scene, 'camera'):
        cam.data.lens = pms.cam_lens
        return
    from . import api
    api.run(api.steps_for('camera_shot', scene), None, scene)


def _material(name):
    ob = bpy.data.objects.get(name)
    return ob.active_material if ob is not None else None


def apply_background(scene, pms):
    from . import build_background
    mat = _material('PMS_Background')
    if mat is not None:
        data = merge(scene, 'background', core.preset(scene, 'background')[1])
        build_background.update_material(mat, data)
        floor = _material('PMS_Floor')                          # a floor in the backdrop's colour glows like the backdrop
        if floor is not None and floor.node_tree.nodes.get('PMS_SelfLight') is not None:
            build_background.set_self_light(floor, data.get('self_light', 0.0))


def refit_backdrop(scene, pms):
    """Rebuild the backdrop if it was not edited by hand; otherwise keep the hand edit."""
    if core.modified(scene, 'background'):
        return
    from . import api
    api.run(api.steps_for('background', scene), None, scene)


def apply_floor(scene, pms):
    mat = _material('PMS_Floor')
    if mat is None:
        return
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*pms.floor_color, 1.0)
    bsdf.inputs['Roughness'].default_value = pms.floor_roughness
    if mat.node_tree.nodes.get('PMS_SelfLight') is not None:
        bsdf.inputs['Emission Color'].default_value = (*pms.floor_color, 1.0)
    mat.diffuse_color = (*pms.floor_color, 1.0)


def apply_look(scene, pms):
    ng = scene.compositing_node_group
    node = ng.nodes.get('PMS_Intensity') if ng is not None else None
    if node is not None:
        node.inputs[0].default_value = pms.look_intensity
    scene.view_settings.exposure = pms.look_exposure


CALLBACKS = {
    'cam_lens': updater('camera', refit), 'cam_padding': updater('camera', refit),
    'cam_dof': updater('camera', lambda s, p: apply_focus(s)), 'cam_fstop': updater('camera', lambda s, p: apply_focus(s)),
    'cam_focus': updater('camera', lambda s, p: apply_focus(s)),
    'cam_autofocus': updater('camera', lambda s, p: apply_focus(s)),
    'light_power': updater('lighting', lambda s, p: apply_lights(s)),
    'light_tint': updater('lighting', lambda s, p: apply_lights(s)),
    'light_rot': updater('lighting', lambda s, p: apply_lights(s)),
    'light_fill': updater('lighting', lambda s, p: apply_lights(s)),
    'light_rim': updater('lighting', lambda s, p: apply_lights(s)),
    'light_temp': updater('lighting', lambda s, p: apply_lights(s)),
    'bgl_power': updater('bglight', lambda s, p: apply_bg_lights(s)), 'bgl_color': updater('bglight', lambda s, p: apply_bg_lights(s)),
    'floor_color': updater('floor', apply_floor), 'floor_roughness': updater('floor', apply_floor),
    'look_intensity': updater('compositing', apply_look), 'look_exposure': updater('compositing', apply_look),
}
for _k in GROUPS['background'][1]:
    CALLBACKS[_k] = updater('background', apply_background)
CALLBACKS['bg_distance'] = CALLBACKS['bg_cove'] = updater('background', refit_backdrop)
