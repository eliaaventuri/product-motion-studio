"""Lighting: rig Empty PMS_Light_Rig at the product centre, lights as its children, PMS_World."""

from math import cos, radians, sin
import bpy
from mathutils import Matrix, Vector
from . import core, live
from . import build_compositing, motion


def _white(rgb):
    return all(abs(c - 1.0) < 1e-4 for c in rgb)


def _polar(az_deg, el_deg, d):
    az, el = radians(az_deg), radians(el_deg)
    return Vector((d * sin(az) * cos(el), -d * cos(az) * cos(el), d * sin(el)))


def _aim(pos):
    """Rotation (euler, rig space) so a light emits (-Z) along -pos (pos = light position minus aim point), +X horizontal."""
    z = pos.normalized()                                    # light local +Z points away from the target
    x = Vector((0, 0, 1)).cross(z)
    x = x.normalized() if x.length > 1e-6 else Vector((1, 0, 0))
    y = z.cross(x)
    return Matrix((x, y, z)).transposed().to_euler()


def _light(scene, rig, spec, index, size, receivers=None, key='lights', prefix='PMS_Light'):
    ltype = spec.get('type', 'AREA')
    data = bpy.data.lights.new(f"{prefix}_{index}_{spec.get('role', 'light')}", ltype)
    power = float(spec['power_ref'])
    data.energy = power if ltype == 'SUN' else power * size ** 2
    if spec.get('kelvin'):
        data.use_temperature, data.temperature = True, float(spec['kelvin'])
    if spec.get('rgb') and not (spec.get('kelvin') and _white(spec['rgb'])):    # (personal presets: kelvin AND a tint)
        data.color = spec['rgb']
    sx, sy = spec.get('size_f', (1.0, 1.0))
    if ltype == 'AREA':
        data.shape = spec.get('shape', 'RECTANGLE')
        data.size = sx * size
        if data.shape in ('RECTANGLE', 'ELLIPSE'):
            data.size_y = sy * size
    elif ltype in ('SPOT', 'POINT'):
        data.shadow_soft_size = sx * size
        if ltype == 'SPOT':
            data.spot_size = radians(spec.get('spot_size', 40))
            data.spot_blend = spec.get('blend', 0.5)
    elif ltype == 'SUN':
        data.angle = radians(spec.get('angle', 3.0))
    pos = _polar(spec['az'], spec['el'], spec['dist_f'] * size)
    tgt = _polar(*spec['aim'][:2], spec['aim'][2] * size) if spec.get('aim') else Vector()   # default: the product centre
    data['pms_base'] = [data.energy, *data.color]            # live Power / Tint multiply these (live.scale_lights)
    data['pms_role'] = spec.get('role', 'light')
    ob = core.link(scene, key, bpy.data.objects.new(data.name, data))
    ob.parent = rig
    ob.location = pos
    ob.rotation_euler = [radians(a) for a in spec['rot']] if spec.get('rot') else _aim(pos - tgt)   # rot: personal presets (exact)
    ob.visible_camera = False                                # lights stay out of the frame (can be switched on)
    if spec.get('only') == 'backdrop':                       # light linking: lights the backdrop/floor, never the product
        ob.light_linking.receiver_collection = receivers
    return ob


def _world(scene, strength, color):
    old = bpy.data.worlds.get('PMS_World')
    if old is not None and old is not scene.world:
        bpy.data.worlds.remove(old)
    w = scene.world if (scene.world and scene.world.name == 'PMS_World') else bpy.data.worlds.new('PMS_World')
    nt = w.node_tree
    bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None) or nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (*color, 1.0)
    bg.inputs['Strength'].default_value = strength
    w['pms_base'] = [strength, *color]                        # live Power / Tint multiply these (live.apply_lights)
    scene.world = w


def refresh_world(scene):
    """PMS_World from the lighting preset, lifted by the backdrop's 'world_fill' (strength, colour): a backdrop with nothing around
    the product (the image plates) leaves glass and metal nothing to reflect, so they would render black. Called by this builder and
    by the background builder (a background change does not rebuild the lights). Lights edited by hand are not touched: nor is the world."""
    if 'lighting' in core._PROTECTED:
        return
    _, data = core.preset(scene, 'lighting')
    strength, color = data.get('world_strength', 0.0), tuple(data.get('world_color', (0.05, 0.05, 0.05)))
    fill = core.preset(scene, 'background')[1].get('world_fill')
    if fill and fill[0] > strength:
        strength, color = fill[0], tuple(fill[1])
    _world(scene, strength, color)
    live.apply_lights(scene)


def backdrop_receivers(scene):
    """Collection light-linked by the backdrop-only lights: the background and floor sub-collections."""
    receivers = bpy.data.collections.get(core.RECEIVERS) or bpy.data.collections.new(core.RECEIVERS)
    for key in ('background', 'floor'):
        sub = core.section_collection(scene, key)
        if sub.name not in receivers.children:
            receivers.children.link(sub)
    return receivers


def link_mirror_floor(scene):
    """Over a mirror floor the product lights do not light the floor: a mirror has no diffuse, so the only thing they would add is
    the sharp reflection of their own shape (white boxes on the horizon, with a low camera). The floor still mirrors the product
    and the backdrop. Called by this builder and by the floor builder (a floor change does not rebuild the lights).
    Also applies when floor has no_light_reflections=True (dark glossy floors where light reflections make white rectangles)."""
    if 'lighting' in core._PROTECTED:
        return
    _, data = core.preset(scene, 'floor')
    mirror = data.get('kind') == 'plane' and (data.get('metallic', 0.0) >= 0.5 or data.get('no_light_reflections', False))
    coll = bpy.data.collections.get(core.NO_FLOOR)
    if mirror:
        coll = coll or bpy.data.collections.new(core.NO_FLOOR)
        sub = core.section_collection(scene, 'floor')
        if sub.name not in coll.children:
            coll.children.link(sub)
        for col, child in zip(coll.children, coll.collection_children):    # (same order; no lookup by name in 5.1)
            if col == sub:
                child.light_linking.link_state = 'EXCLUDE'
    for ob in core.section_collection(scene, 'lights').objects:
        if ob.type == 'LIGHT' and ob.light_linking.receiver_collection in (None, coll):
            ob.light_linking.receiver_collection = coll if mirror else None


def build(scene):
    core.begin(scene)
    build_compositing.sync_ev(scene)                        # Cycles exposure compensation follows the presets in use
    pms = core.settings(scene)
    inf = core.info(scene)
    core.clear_section(scene, 'lights')
    hidden = core.isolate_lights(scene, bool(pms.isolate_lights))     # the user's lights would add to the studio's
    warnings = [f"Hid {hidden} scene light{'s' if hidden != 1 else ''}"] if hidden else []
    p, data = live.preset(scene, 'lighting')
    rig = core.new_empty(scene, 'lights', 'PMS_Light_Rig', inf.center, 'PLAIN_AXES', inf.size * 0.1)
    receivers = backdrop_receivers(scene) if any(spec.get('only') == 'backdrop' for spec in data['lights']) else None
    lights = [_light(scene, rig, spec, i, inf.size, receivers) for i, spec in enumerate(data['lights'])]
    refresh_world(scene)
    rig.rotation_euler = (0, 0, radians(pms.base_az))
    if pms.animate_lighting:                                # slow highlight sweep, linear-free ease
        f0, f1 = core.frame_range(pms)
        az = rig.rotation_euler[2]
        motion._keys(rig, 'rotation_euler', 2, [(f0, az - radians(15)), (f1, az + radians(15))])
        motion._fcurve(rig, 'rotation_euler', 2).update()
        rig.rotation_euler[2] = az
    live.apply_lights(scene)                                # live Power / Tint / Rig rotation
    link_mirror_floor(scene)
    if p.meta.get('needs_cycles') and scene.render.engine != 'CYCLES':
        warnings.append(f"{p.name}: dispersion shows only in Cycles (engine is {scene.render.engine}) and with a glass that disperses "
                        "(Blender 5.1 has no Dispersion socket: mix three Glass BSDF with IOR 1.50/1.52/1.54 filtered R/G/B)")
    return {'lighting': p.id, 'lights': [o.name for o in lights], 'rig': rig.name,
            'total_watts': sum(o.data.energy for o in lights if o.data.type != 'SUN'), 'warnings': warnings}
