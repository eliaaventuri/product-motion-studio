"""Background light: rig Empty PMS_BgLight_Rig at the product centre with lights that light only the backdrop and the floor
(light linking, see build_lighting.backdrop_receivers). Power and colour are live controls (live.apply_bg_lights).
A light may carry a GOBO (a panel with a cut-out pattern between the light and the backdrop: real shadows in Eevee and Cycles,
invisible to the camera and to reflections) and/or a glowing STRIP (an emissive bar at the light, seen by the camera)."""

from math import radians, tan
import bmesh
import bpy
from mathutils import Vector
from . import build_compositing, core, live
from .build_lighting import _aim, _light, _polar, backdrop_receivers


# === gobo patterns ===============================================================================================

def _math(nt, op, a, b=None):
    """Math node; a / b are sockets or numbers. Returns the output socket."""
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def _band(nt, x, lo, hi):
    """1 where lo < x < hi, else 0."""
    return _math(nt, 'MULTIPLY', _math(nt, 'GREATER_THAN', x, lo), _math(nt, 'LESS_THAN', x, hi))


def _ramp(nt, fac, lo, hi):
    """0 below lo, 1 above hi, linear in between (the soft edge of the pattern)."""
    n = nt.nodes.new('ShaderNodeMath')
    n.operation, n.use_clamp = 'DIVIDE', True
    nt.links.new(_math(nt, 'SUBTRACT', fac, lo), n.inputs[0])
    n.inputs[1].default_value = hi - lo
    return n.outputs[0]


def _mask(nt, pattern, vec):
    """Opacity of the gobo at the panel coordinates vec (0..1 across the panel after angle/scale): 1 blocks the light."""
    if pattern == 'blinds':                                 # horizontal slats, ~55 % solid
        w = nt.nodes.new('ShaderNodeTexWave')
        w.wave_type, w.bands_direction, w.wave_profile = 'BANDS', 'Y', 'SIN'
        w.inputs['Scale'].default_value = 9.0
        nt.links.new(vec, w.inputs['Vector'])
        return _ramp(nt, w.outputs['Fac'], 0.40, 0.44)
    if pattern == 'leaves':                                 # dappled foliage: organic blobs, about half solid
        n = nt.nodes.new('ShaderNodeTexNoise')
        n.inputs['Scale'].default_value = 6.0
        n.inputs['Detail'].default_value = 4.0
        n.inputs['Roughness'].default_value = 0.55
        n.inputs['Distortion'].default_value = 0.8
        nt.links.new(vec, n.inputs['Vector'])
        return _ramp(nt, n.outputs['Fac'], 0.47, 0.53)
    if pattern == 'window':                                 # a four-pane window: light only through the panes
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(vec, sep.inputs['Vector'])
        u, v = sep.outputs['X'], sep.outputs['Y']
        inside = _math(nt, 'MULTIPLY', _band(nt, u, 0.2, 0.8), _band(nt, v, 0.15, 0.85))
        frame = _math(nt, 'MAXIMUM', _band(nt, u, 0.48, 0.52), _band(nt, v, 0.48, 0.52))     # the mullion cross
        return _math(nt, 'SUBTRACT', 1.0, _math(nt, 'MULTIPLY', inside, _math(nt, 'SUBTRACT', 1.0, frame)))
    if pattern == 'caustics':                               # thin bright web (the cell edges), 25 % of the light everywhere
        n = nt.nodes.new('ShaderNodeTexNoise')
        n.inputs['Scale'].default_value = 2.0
        n.inputs['Detail'].default_value = 2.0
        nt.links.new(vec, n.inputs['Vector'])
        warp = nt.nodes.new('ShaderNodeVectorMath')
        warp.operation = 'MULTIPLY_ADD'                     # vec + noise * 0.25
        nt.links.new(n.outputs['Color'], warp.inputs[0])
        warp.inputs[1].default_value = (0.25, 0.25, 0.25)
        nt.links.new(vec, warp.inputs[2])
        vor = nt.nodes.new('ShaderNodeTexVoronoi')
        vor.feature = 'DISTANCE_TO_EDGE'
        vor.inputs['Scale'].default_value = 12.0
        nt.links.new(warp.outputs['Vector'], vor.inputs['Vector'])
        return _math(nt, 'MULTIPLY', _ramp(nt, vor.outputs['Distance'], 0.015, 0.05), 0.75)
    raise ValueError(f"unknown gobo pattern '{pattern}'")


def _gobo_material(pattern, angle, scale):
    """Mix of Transparent (holes) and black Diffuse (solid) by the pattern; one material per pattern / angle / scale."""
    name = f'PMS_Gobo_{pattern}_{angle:g}_{scale:g}'
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    if hasattr(mat, 'use_transparent_shadow'):
        mat.use_transparent_shadow = True                   # Eevee: the holes let the light through
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = 'DITHERED'
    nt = mat.node_tree
    nt.nodes.clear()
    uv = nt.nodes.new('ShaderNodeUVMap')
    centre = nt.nodes.new('ShaderNodeVectorMath')
    centre.operation = 'SUBTRACT'
    centre.inputs[1].default_value = (0.5, 0.5, 0.0)
    nt.links.new(uv.outputs['UV'], centre.inputs[0])
    mp = nt.nodes.new('ShaderNodeMapping')                  # rotate / scale about the panel centre, back to 0..1
    mp.inputs['Location'].default_value = (0.5, 0.5, 0.0)
    mp.inputs['Rotation'].default_value = (0.0, 0.0, radians(angle))
    mp.inputs['Scale'].default_value = (scale, scale, 1.0)
    nt.links.new(centre.outputs['Vector'], mp.inputs['Vector'])
    mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(_mask(nt, pattern, mp.outputs['Vector']), mix.inputs['Fac'])
    clear, solid = nt.nodes.new('ShaderNodeBsdfTransparent'), nt.nodes.new('ShaderNodeBsdfDiffuse')
    solid.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(solid.outputs[0], mix.inputs[2])
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return mat


def _quad(name, sx, sy):
    """Rectangle sx x sy centred on the origin in its XY plane (normal +Z), UV 0..1."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    f = bm.faces.new([bm.verts.new((x * sx / 2, y * sy / 2, 0)) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    for loop, c in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = c
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _gobo(scene, rig, spec, index, S):
    """Panel with the cut-out pattern at the fraction `at` of the way from the light to its aim point, perpendicular to the
    beam, big enough to cover the cone. Only shadow rays see it."""
    g = spec['gobo']
    pos = _polar(spec['az'], spec['el'], spec['dist_f'] * S)
    tgt = _polar(*spec['aim'][:2], spec['aim'][2] * S) if spec.get('aim') else Vector()
    at, reach = g.get('at', 0.2), (tgt - pos).length
    if spec.get('type') == 'SPOT':
        side = 2 * at * reach * tan(radians(spec.get('spot_size', 40)) / 2) * 1.3
    else:
        side = 1.5 * max(spec.get('size_f', (1.0, 1.0))) * S + 2 * at * reach * 0.6
    ob = core.link(scene, 'bg_lights', bpy.data.objects.new(f'PMS_Gobo_{index}', _quad(f'PMS_Gobo_{index}', side, side)))
    ob.parent = rig
    ob.location = pos + at * (tgt - pos)
    ob.rotation_euler = _aim(pos - tgt)                     # like the light: perpendicular to the beam
    ob.visible_camera = ob.visible_diffuse = ob.visible_glossy = False
    ob.visible_transmission = ob.visible_volume_scatter = False
    ob.visible_shadow = True
    ob['pms_orient'] = False
    ob.data.materials.append(_gobo_material(g.get('pattern', 'blinds'), float(g.get('angle', 0.0)), float(g.get('scale', 1.0))))
    return ob


def _strip(scene, rig, spec, index, S):
    """Emissive bar of the light's size at the light, facing the camera of the base shot: the source itself is in the frame
    (a neon line on the horizon). It glows for the camera and in reflections, it does not light the product (no diffuse rays)."""
    sx, sy = spec.get('size_f', (1.0, 0.05))
    ob = core.link(scene, 'bg_lights', bpy.data.objects.new(f'PMS_Glow_{index}', _quad(f'PMS_Glow_{index}', sx * S, sy * S)))
    ob.parent = rig
    ob.location = _polar(spec['az'], spec['el'], spec['dist_f'] * S)
    ob.rotation_euler = (radians(90), 0, 0)                 # normal -Y: towards the camera (az 0 of the rig)
    ob.visible_diffuse = ob.visible_shadow = False
    ob['pms_orient'] = False
    mat = bpy.data.materials.new(f'PMS_Glow_{index}')
    nt = mat.node_tree
    nt.nodes.clear()
    em, out = nt.nodes.new('ShaderNodeEmission'), nt.nodes.new('ShaderNodeOutputMaterial')
    em.inputs['Color'].default_value = (*spec.get('rgb', (1.0, 1.0, 1.0)), 1.0)
    em.inputs['Strength'].default_value = float(spec.get('strip', 6.0))
    nt.links.new(em.outputs[0], out.inputs['Surface'])
    ob.data.materials.append(mat)
    return ob


def build(scene):
    core.begin(scene)
    build_compositing.sync_ev(scene)                        # Cycles exposure compensation follows the presets in use
    pms = core.settings(scene)
    inf = core.info(scene)
    core.clear_section(scene, 'bg_lights')
    p, data = live.preset(scene, 'background_light')
    if not data['lights']:
        return {'background_light': p.id, 'lights': [], 'rig': None, 'warnings': []}
    rig = core.new_empty(scene, 'bg_lights', 'PMS_BgLight_Rig', inf.center, 'PLAIN_AXES', inf.size * 0.1)
    rig.rotation_euler = (0, 0, radians(pms.base_az))
    receivers = backdrop_receivers(scene)
    lights = []
    for i, spec in enumerate(data['lights']):
        lights.append(_light(scene, rig, dict(spec, only='backdrop'), i, inf.size, receivers, 'bg_lights', 'PMS_BgLight'))
        if spec.get('gobo'):
            _gobo(scene, rig, spec, i, inf.size)
        if spec.get('strip'):
            _strip(scene, rig, spec, i, inf.size)
    live.apply_bg_lights(scene)
    return {'background_light': p.id, 'lights': [o.name for o in lights], 'rig': rig.name, 'warnings': []}
