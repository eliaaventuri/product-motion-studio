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
from math import radians

import bpy

from . import core

# section -> (signature step, live props)
GROUPS = {
    'camera_shot': ('camera', ('cam_lens', 'cam_padding', 'cam_dof', 'cam_fstop', 'cam_focus')),
    'lighting': ('lighting', ('light_power', 'light_tint', 'light_rot')),
    'background': ('background', ('bg_color_a', 'bg_color_mid', 'bg_color_b', 'bg_type', 'bg_rotation', 'bg_roughness',
                                  'bg_selflight')),
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
                    cam_fstop=f if f > 0 else FSTOP, cam_focus=float(data.get('focus_offset', 0.0)))
    if section == 'lighting':
        return dict(light_power=1.0, light_tint=(1.0, 1.0, 1.0), light_rot=0.0)
    if section == 'background_light':
        return dict(bgl_power=1.0, bgl_color=(1.0, 1.0, 1.0))
    if section == 'background':
        stops, g = _stops(data), data.get('gradient', {})
        m = _mid_index(stops)
        a, b = stops[0][1], stops[-1][1]
        return dict(bg_color_a=a, bg_color_b=b, bg_color_mid=stops[m][1] if m else tuple((x + y) / 2 for x, y in zip(a, b)),
                    bg_type='RADIAL' if g.get('type') == 'radial' else 'LINEAR', bg_rotation=float(g.get('rotation', 0)),
                    bg_roughness=float(data.get('roughness', 0.9)), bg_selflight=float(data.get('self_light', 0.0)))
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
                 fstop=pms.cam_fstop, focus_offset=pms.cam_focus)
    elif section == 'background':
        stops = _stops(data)
        m = _mid_index(stops)
        stops[0] = (stops[0][0], tuple(pms.bg_color_a))
        stops[-1] = (stops[-1][0], tuple(pms.bg_color_b))
        if m:
            stops[m] = (stops[m][0], tuple(pms.bg_color_mid))
        g = dict(data.get('gradient', {}))
        g['type'], g['rotation'] = pms.bg_type.lower(), pms.bg_rotation
        d.update(stops=stops, gradient=g, roughness=pms.bg_roughness, self_light=pms.bg_selflight)
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

def scale_lights(scene, key, power, tint):
    """energy = base * power, colour = base * tint, for every light of a section (the bases are stored by the builders)."""
    col = bpy.data.collections.get(core.SUB[key])
    for ob in (col.all_objects if col else ()):
        base = ob.data.get('pms_base') if ob.type == 'LIGHT' else None
        if base:
            ob.data.energy = base[0] * power
            ob.data.color = [base[1 + i] * tint[i] for i in range(3)]


def apply_lights(scene):
    """Lighting live values: power and tint on the lights and on the world, rig rotation."""
    pms = core.settings(scene)
    scale_lights(scene, 'lights', pms.light_power, pms.light_tint)
    w = scene.world
    if w is not None and w.name == 'PMS_World' and w.get('pms_base'):
        bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
        if bg is not None:
            b = w['pms_base']
            bg.inputs['Strength'].default_value = b[0] * pms.light_power
            bg.inputs['Color'].default_value = (*(b[1 + i] * pms.light_tint[i] for i in range(3)), 1.0)
    rig = bpy.data.objects.get('PMS_Light_Rig')
    if rig is not None:
        rig.delta_rotation_euler[2] = radians(pms.light_rot)


def apply_bg_lights(scene):
    pms = core.settings(scene)
    scale_lights(scene, 'bg_lights', pms.bgl_power, pms.bgl_color)


def apply_focus(scene, cam_data=None):
    """DOF on/off, f-stop and the focus point (the DOF empty, moved along the base view direction by delta_location so
    that the focus pull of a camera motion keeps working)."""
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
    'light_power': updater('lighting', lambda s, p: apply_lights(s)), 'light_tint': updater('lighting', lambda s, p: apply_lights(s)),
    'light_rot': updater('lighting', lambda s, p: apply_lights(s)),
    'bgl_power': updater('bglight', lambda s, p: apply_bg_lights(s)), 'bgl_color': updater('bglight', lambda s, p: apply_bg_lights(s)),
    'floor_color': updater('floor', apply_floor), 'floor_roughness': updater('floor', apply_floor),
    'look_intensity': updater('compositing', apply_look), 'look_exposure': updater('compositing', apply_look),
}
for _k in GROUPS['background'][1]:
    CALLBACKS[_k] = updater('background', apply_background)
