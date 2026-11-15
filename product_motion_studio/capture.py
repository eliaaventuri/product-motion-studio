"""Capture: the TRUE state of a section (built objects, nodes, live values, hand edits) as a preset entry of its schema.

    entry(scene, section) -> {'data': {...}, 'base': <preset id it started from>}        data sections
                             {'base': <built-in function preset id>, 'opts': {...}}      product_motion, camera_motion

Data sections are converted back to the SCHEMA of their presets, relative to the size of the product (positions in multiples of
its size, sizes in multiples of its size, watts / size**2), so the preset works on a product of any scale. What is read:
  lighting, background_light  every light object (hand-moved, rotated, scaled, power, colour, shape; hidden lights are left out),
                              the live Power / Tint / Rig Rotation are folded in; lighting also the world strength and colour
  camera_shot                 lens, padding, depth of field and focus (live values); az / el / target height from the camera
                              pose at the current frame when the camera was moved by hand
  background, floor           colour ramp, gradient, roughness, self light / floor colour, roughness, metallic, shadow catcher
  look                        the compositor nodes (glare, lens, grade, vignette, grain), exposure, intensity, view transform
  format                      the render resolution
Function sections keep the base preset id and its options (overrides): curves edited by hand are NOT captured.
A section that is not built yet is captured from its preset and live values."""

import json
import re
from math import asin, atan2, degrees, radians

import bpy
from mathutils import Matrix, Vector

from . import build_compositing, core, live, motion, presets

DATA_SECTIONS = ('lighting', 'background_light', 'background', 'floor', 'look', 'camera_shot', 'format')
FUNCTION_SECTIONS = ('product_motion', 'camera_motion')
SECTIONS = FUNCTION_SECTIONS + DATA_SECTIONS
KEEP_META = ('product_types', 'style', 'needs_cycles')       # what a personal data preset keeps of the meta of its source
_RIG = {'lights': ('PMS_Light_Rig', 'PMS_Light'), 'bg_lights': ('PMS_BgLight_Rig', 'PMS_BgLight')}


def _r(v, n=6):
    return round(float(v), n) + 0.0               # (+ 0.0: no -0.0)


def _rgb(c):
    return [_r(x) for x in list(c)[:3]]


def _animated(idb, path, index):
    return any(fc.data_path == path and fc.array_index == index for fc in motion.iter_fcurves(idb))


def _source(scene, section):
    """The preset the section is built from: its data (a copy, overrides applied) and the id of the stock preset it started from."""
    p, data = core.preset(scene, section)
    return p, data, p.meta.get('base', p.id)


# === function sections ===========================================================

def _function(scene, section):
    p = presets.get(section, getattr(core.settings(scene), section))
    return {'base': p.meta.get('fn_id', p.id), 'opts': dict(core.overrides(scene, section)), 'meta': {}}


# === lights ======================================================================

def _rig_matrix(rig, az0):
    """The rig as PMS left it plus the hand edits and the live rotation (the highlight sweep of Animate Lighting is not one)."""
    m = rig.matrix_basis.copy()
    if _animated(rig, 'rotation_euler', 2):
        loc = m.translation.copy()
        corr = Matrix.Rotation(radians(az0) - rig.rotation_euler[2], 4, 'Z')
        m = Matrix.Translation(loc) @ corr @ Matrix.Translation(-loc) @ m
    return m


def _aim_of(pos, q_rot, size):
    """(aim, rot): the `aim` point that reproduces the orientation (None = aims at the product centre), or an exact `rot`
    (degrees) when no aim point does (a rolled light)."""
    from .build_lighting import _aim
    axis = -(q_rot @ Vector((0, 0, 1)))                             # the light emits along its local -Z
    if pos.cross(axis).length < 0.01 * size:                        # the axis passes by the product centre
        tgt = Vector()
    else:
        tgt = pos + axis * pos.length
    want = _aim(pos - tgt).to_matrix()
    if (want @ Vector((1, 0, 0)) - q_rot @ Vector((1, 0, 0))).length < 0.01 and (want @ Vector((0, 0, 1)) - q_rot @ Vector((0, 0, 1))).length < 0.01:
        if tgt.length < 1e-9:
            return None, None
        d = tgt.length
        return [_r(degrees(atan2(tgt.x, -tgt.y)), 4), _r(degrees(asin(max(-1, min(1, tgt.z / d)))), 4), _r(d / size)], None
    return None, [_r(degrees(a), 4) for a in q_rot.to_euler()]


def _light_spec(ob, q, size, backdrop):
    d = ob.data
    pos, rot, scale = q.decompose()
    scale = [abs(x) for x in scale]
    dist = pos.length
    spec = {'role': (re.match(r'PMS_(?:Bg)?Light_\d+_(.+?)(?:\.\d+)?$', ob.name) or [0, 'light'])[1], 'type': d.type}
    if d.type == 'AREA':
        spec['shape'] = d.shape
        sx, sy = d.size * scale[0], (d.size_y * scale[1] if d.shape in ('RECTANGLE', 'ELLIPSE') else d.size * scale[0])
        spec['size_f'] = [_r(sx / size), _r(sy / size)]
    elif d.type in ('SPOT', 'POINT'):
        spec['size_f'] = [_r(d.shadow_soft_size / size)] * 2
        if d.type == 'SPOT':
            spec.update(spot_size=_r(degrees(d.spot_size), 3), blend=_r(d.spot_blend))
    elif d.type == 'SUN':
        spec['angle'] = _r(degrees(d.angle), 4)
    spec['power_ref'] = _r(d.energy if d.type == 'SUN' else d.energy / size ** 2, 5)
    if d.use_temperature:
        spec['kelvin'] = _r(d.temperature, 1)
    if not (d.use_temperature and all(abs(c - 1.0) < 1e-4 for c in d.color)):
        spec['rgb'] = _rgb(d.color)
    spec['az'] = _r(degrees(atan2(pos.x, -pos.y)) if dist > 1e-9 else 0.0, 4)
    spec['el'] = _r(degrees(asin(max(-1.0, min(1.0, pos.z / dist)))) if dist > 1e-9 else 0.0, 4)
    spec['dist_f'] = _r(dist / size)
    aim, euler = _aim_of(pos, rot.to_matrix(), size)
    if aim:
        spec['aim'] = aim
    if euler:
        spec['rot'] = euler
    if backdrop or ob.light_linking.receiver_collection is not None:
        spec['only'] = 'backdrop'
    return spec


def _lights(scene, key):
    """The light specs of a section (None when it is not built)."""
    rig = bpy.data.objects.get(_RIG[key][0])
    col = bpy.data.collections.get(core.SUB[key])
    if rig is None or col is None or not core.has_product():
        return None
    inf, pms = core.info(scene), core.settings(scene)
    az0 = pms.base_az
    pose = _pose(scene)
    rest = Matrix.Translation(inf.center) @ Matrix.Rotation(radians(pose['az'] if pose else az0), 4, 'Z')   # lights are relative to the camera
    rig_m = _rig_matrix(rig, az0)
    lights = sorted((o for o in col.all_objects if o.type == 'LIGHT' and not o.hide_render),
                    key=lambda o: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', o.name)])
    out = []
    for ob in lights:
        q = rest.inverted() @ ((rig_m @ ob.matrix_basis) if ob.parent is rig else ob.matrix_world)
        out.append(_light_spec(ob, q, inf.size, key == 'bg_lights'))
    return out


def _lighting(scene):
    p, src, base = _source(scene, 'lighting')
    data = {k: v for k, v in src.items() if k not in ('lights', 'world_strength', 'world_color')}
    lights = _lights(scene, 'lights')
    if lights is None:
        data.update(lights=[dict(s) for s in src['lights']], world_strength=src.get('world_strength', 0.0),
                    world_color=list(src.get('world_color', (0.05, 0.05, 0.05))))
    else:
        data['lights'] = lights
        w, bg = scene.world, None
        if w is not None and w.name == 'PMS_World':
            bg = next((n for n in w.node_tree.nodes if n.type == 'BACKGROUND'), None)
        data['world_strength'] = _r(bg.inputs['Strength'].default_value, 6) if bg else 0.0
        data['world_color'] = _rgb(bg.inputs['Color'].default_value) if bg else [0.05, 0.05, 0.05]
    return {'data': data, 'base': base, 'meta': _meta(p)}


def _bg_lighting(scene):
    p, src, base = _source(scene, 'background_light')
    data = {k: v for k, v in src.items() if k != 'lights'}
    lights = _lights(scene, 'bg_lights')
    if lights is None:
        data['lights'] = [dict(s) for s in src['lights']]
    else:
        for spec, ref in zip(lights, src['lights']):                   # gobo panels and glow strips are meshes, not lights:
            for key in ('gobo', 'strip'):                                # they come from the preset (same index)
                if key in ref:
                    spec[key] = dict(ref[key]) if isinstance(ref[key], dict) else ref[key]
        data['lights'] = lights
    return {'data': data, 'base': base, 'meta': _meta(p)}


def _meta(p):
    return {k: p.meta[k] for k in KEEP_META if k in p.meta}


# === camera ======================================================================

def _pose(scene):
    """{az, el, target_z} of the camera as it is now, when it was moved by hand (None: it is as PMS built it)."""
    cam, target = bpy.data.objects.get('PMS_Camera'), bpy.data.objects.get('PMS_Cam_Target')
    if cam is None or target is None or not core.has_product() or not core.modified(scene, 'camera'):
        return None
    bpy.context.view_layer.update()
    inf = core.info(scene)
    v = cam.matrix_world.translation - target.matrix_world.translation
    if v.length < 1e-9:
        return None
    return dict(az=degrees(atan2(v.x, -v.y)), el=max(-89.0, min(89.0, degrees(asin(max(-1.0, min(1.0, v.z / v.length)))))),
                target_z=max(-0.5, min(1.5, (target.matrix_world.translation.z - inf.base_z) / inf.dims.z)))


def _camera(scene):
    p, src, base = _source(scene, 'camera_shot')
    _, merged = live.preset(scene, 'camera_shot')                  # lens / padding / f-stop / focus: the live values
    data = {k: v for k, v in src.items() if k not in ('lens', 'padding', 'dof', 'focus_offset', 'autofocus')}
    data.update(lens=_r(merged['lens'], 3), padding=_r(merged['padding'], 4), dof=_r(merged['dof'], 3),
                focus_offset=_r(merged.get('focus_offset', 0.0), 4), autofocus=merged.get('autofocus', False))
    cam = bpy.data.objects.get('PMS_Camera')
    if cam is not None and core.has_product():
        pms = core.settings(scene)
        data['lens'] = _r(cam.data.lens, 3)
        data['dof'] = _r(cam.data.dof.aperture_fstop, 3) if cam.data.dof.use_dof else 0.0
        data['autofocus'] = pms.cam_autofocus
        pose = _pose(scene)
        if pose:                                                     # moved by hand: az / el / height from where the camera is now
            data.update(az=_r(pose['az'], 3), el=_r(pose['el'], 3), target_z=_r(pose['target_z'], 4))
        else:
            data['az'], data['el'] = src.get('az', pms.base_az), src.get('el', 0.0)
    return {'data': data, 'base': base, 'meta': {}}


# === background, floor ===========================================================

def _material(name):
    ob = bpy.data.objects.get(name)
    return ob.active_material if ob is not None else None


def _background(scene):
    p, src, base = _source(scene, 'background')
    _, merged = live.preset(scene, 'background')
    data = {k: v for k, v in src.items() if k not in ('stops', 'gradient', 'roughness', 'self_light', 'distance', 'cove')}
    data.update(stops=[[_r(a), _rgb(c)] for a, c in sorted(((float(a), c) for a, c in merged['stops']), key=lambda s: s[0])],
                gradient=dict(merged.get('gradient', {})), roughness=_r(merged['roughness']), self_light=_r(merged['self_light']),
                distance=_r(merged.get('distance', 1.0)), cove=_r(merged.get('cove', 1.0)))
    mat = _material('PMS_Background')
    if mat is not None:
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        data['roughness'] = _r(bsdf.inputs['Roughness'].default_value)
        glow = nt.nodes.get('PMS_SelfLight')
        data['self_light'] = _r(glow.inputs[1].default_value if glow is not None else bsdf.inputs['Emission Strength'].default_value)
        ramp = next((n for n in nt.nodes if n.type == 'VALTORGB'), None)
        if ramp is not None:
            mp = next(n for n in nt.nodes if n.type == 'MAPPING')
            radial = next(n for n in nt.nodes if n.type == 'TEX_GRADIENT').gradient_type == 'SPHERICAL'
            stops = [(1 - e.position if radial else e.position, _rgb(e.color)) for e in ramp.color_ramp.elements]
            data['stops'] = [[_r(a), c] for a, c in sorted(stops, key=lambda s: s[0])]
            g = dict(data['gradient'])
            g['type'] = 'radial' if radial else 'linear'
            if radial:
                loc = mp.inputs['Location'].default_value
                g['center'] = [_r(-loc[0] / 1.4, 4), _r(-loc[1] / 1.4, 4)]
            else:
                g['rotation'] = _r(degrees(mp.inputs['Rotation'].default_value[2]) + 90, 3)
            data['gradient'] = g
    return {'data': data, 'base': base, 'meta': {}}


def _floor(scene):
    p, src, base = _source(scene, 'floor')
    _, merged = live.preset(scene, 'floor')
    data = dict(src)
    mat, ob = _material('PMS_Floor'), bpy.data.objects.get('PMS_Floor')
    if src.get('kind') == 'plane':
        color, rough, metal, catcher = merged.get('color'), merged.get('roughness', 0.85), src.get('metallic', 0.0), src.get('shadow_catcher', False)
        if mat is not None:
            bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            color, rough = list(bsdf.inputs['Base Color'].default_value)[:3], bsdf.inputs['Roughness'].default_value
            metal = bsdf.inputs['Metallic'].default_value
            catcher = bool(ob.is_shadow_catcher)
        follows = src.get('color') is None or bool(src.get('glow'))      # a floor in the backdrop's colour glows like the backdrop
        bg = _material('PMS_Background')
        if src.get('color') is None and bg is not None and color is not None \
                and max(abs(a - b) for a, b in zip(color, bg.diffuse_color[:3])) < 1e-4:
            data.pop('color', None)                                       # still the backdrop's colour
        else:
            data['color'] = _rgb(color) if color is not None else None
            if follows:
                data['glow'] = True
        data.update(roughness=_r(rough), metallic=_r(metal))
        if catcher:
            data['shadow_catcher'] = True
        if data.get('color') is None:
            data.pop('color', None)
    return {'data': data, 'base': base, 'meta': {}}


# === look ========================================================================

def _node(ng, idname):
    return next((n for n in ng.nodes if n.bl_idname == idname), None)


def _look(scene):
    p, src, base = _source(scene, 'look')
    _, merged = live.preset(scene, 'look')
    vs = scene.view_settings
    data = {k: v for k, v in src.items() if k not in ('exposure', 'intensity')}
    data.update(view_transform=vs.view_transform, look=vs.look, exposure=_r(vs.exposure, 4), gamma=_r(vs.gamma, 4),
                intensity=_r(merged.get('intensity', 1.0)))
    ng = scene.compositing_node_group
    if ng is None or ng.name != build_compositing.GROUP:
        return {'data': data, 'base': base, 'meta': {}}
    for key in ('glare', 'lens', 'grade', 'vignette', 'grain'):
        data.pop(key, None)
    mix = ng.nodes.get('PMS_Intensity')
    if mix is not None:
        data['intensity'] = _r(mix.inputs[0].default_value)
    n = _node(ng, 'CompositorNodeGlare')
    if n is not None:
        g = {'type': n.inputs['Type'].default_value, 'quality': n.inputs['Quality'].default_value}
        for key, name in (('threshold', 'Threshold'), ('strength', 'Strength'), ('size', 'Size')):
            if name in n.inputs:
                g[key] = _r(n.inputs[name].default_value, 5)
        tint = tuple(_r(c, 4) for c in n.inputs['Tint'].default_value[:3])
        if tint != (1.0, 1.0, 1.0):
            g['tint'] = tint
        data['glare'] = g
    n = _node(ng, 'CompositorNodeLensdist')
    if n is not None:
        data['lens'] = dict(dispersion=_r(n.inputs['Dispersion'].default_value, 5), distortion=_r(n.inputs['Distortion'].default_value, 5))
    cb = _node(ng, 'CompositorNodeColorBalance')
    if cb is not None:
        sock = lambda node, name: next(s for s in node.inputs if s.name == name and s.type == 'RGBA')   # noqa: E731
        grade = dict(gain=_rgb(sock(cb, 'Gain').default_value), lift=[_r(c - 1.0) for c in list(sock(cb, 'Lift').default_value)[:3]])
        hs, bc = _node(ng, 'CompositorNodeHueSat'), _node(ng, 'CompositorNodeBrightContrast')
        grade['saturation'] = _r(hs.inputs['Saturation'].default_value, 5) if hs is not None else 1.0
        if bc is not None:
            grade['contrast'] = _r(bc.inputs['Contrast'].default_value / 100, 5)
        data['grade'] = grade
    ramp = next((x for x in ng.nodes if x.bl_idname == 'ShaderNodeValToRGB'), None)
    if ramp is not None:
        v = _vignette(ng, ramp)
        if v:
            data['vignette'] = v
    for x in ng.nodes:
        if x.bl_idname == 'ShaderNodeMix' and x.name != 'PMS_Intensity' and x.blend_type == 'OVERLAY':
            data['grain'] = _r(x.inputs[0].default_value * 2, 5)
    return {'data': data, 'base': base, 'meta': {}}


def _vignette(ng, ramp):
    """size / feather / darken of the vignette: the ramp holds one number (the inner radius), the size / feather it was built
    from are kept on the node group (build_compositing)."""
    try:
        old = json.loads(ng.get('pms_vignette', '{}'))
    except ValueError:
        old = {}
    dark = _node(ng, 'CompositorNodeExposure')
    outer, inner = 0.7071, ramp.color_ramp.elements[0].position
    feather = float(old.get('feather', 0.5))
    size = float(old.get('size', 0.9))
    if abs(inner - outer * size * (1 - 0.7 * feather)) > 1e-5:
        size = inner / (outer * (1 - 0.7 * feather))
    v = dict(size=_r(size, 5), feather=_r(feather, 5))
    if dark is not None:
        v['darken'] = _r(-dark.inputs['Exposure'].default_value, 5)
    return v


def _format(scene):
    r = scene.render
    return {'data': {'res': [int(r.resolution_x), int(r.resolution_y)]}, 'base': core.settings(scene).format, 'meta': {}}


_CAPTURE = {'lighting': _lighting, 'background_light': _bg_lighting, 'camera_shot': _camera, 'background': _background,
            'floor': _floor, 'look': _look, 'format': _format}


def entry(scene, section):
    """The preset entry of a section as it is now (see the module docstring)."""
    if section not in SECTIONS:
        raise ValueError(f"cannot save {section!r} as a personal preset; valid: {list(SECTIONS)}")
    core.settings(scene)
    if section in FUNCTION_SECTIONS:
        return _function(scene, section)
    return _CAPTURE[section](scene)

