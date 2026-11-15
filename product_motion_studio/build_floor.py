"""Floor: separate plane PMS_Floor (matte / glossy / mirror / shadow catcher). 'seamless' is part of the backdrop."""

import bmesh
import bpy
from . import core, live
from . import build_background, build_compositing, build_lighting
from .build_background import layout, stage_height


def _plane(kind, L):
    bm = bmesh.new()
    if kind == 'cyclorama':
        for x, y in ((-L['half_w'], L['y_front']), (L['half_w'], L['y_front']),
                     (L['half_w'], L['y_back']), (-L['half_w'], L['y_back'])):
            bm.verts.new((x, y, 0))
        bm.faces.new(bm.verts[:])
    elif kind == 'studio360':
        bmesh.ops.create_circle(bm, cap_ends=True, radius=L['R_floor'], segments=96)
    else:
        h = L['half']
        for x, y in ((-h, -h), (h, -h), (h, h), (-h, h)):
            bm.verts.new((x, y, 0))
        bm.faces.new(bm.verts[:])
    bm.faces.ensure_lookup_table()
    bm.faces[0].normal_update()
    if bm.faces[0].normal.z < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new('PMS_Floor')
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _floor_surface(nt, bsdf, kind, color, S):
    """Insert procedural surface nodes for floor materials.
    kind: 'asphalt' | 'obsidian' | 'acrylic' | 'water'
    Returns the colour socket to connect to Base Color, or None when Base Color stays as it is."""
    new = nt.nodes.new
    coord = new('ShaderNodeTexCoord')
    coord.name = coord.label = 'PMS_FloorSurface_Coord'
    mapping = new('ShaderNodeMapping')
    mapping.name = mapping.label = 'PMS_FloorSurface_Mapping'
    mapping.vector_type = 'POINT'
    mapping.inputs['Scale'].default_value = (1.0 / S, 1.0 / S, 1.0 / S)
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])

    if kind == 'asphalt':
        # Noise for grain (scale 30, detail 10)
        noise_grain = new('ShaderNodeTexNoise')
        noise_grain.name = noise_grain.label = 'PMS_FloorSurface_Noise_Grain'
        noise_grain.inputs['Scale'].default_value = 30.0
        noise_grain.inputs['Detail'].default_value = 10.0
        noise_grain.inputs['Roughness'].default_value = 0.5
        nt.links.new(mapping.outputs['Vector'], noise_grain.inputs['Vector'])

        # Bump from grain
        bump = new('ShaderNodeBump')
        bump.name = bump.label = 'PMS_FloorSurface_Bump_Grain'
        bump.inputs['Strength'].default_value = 0.4
        bump.inputs['Distance'].default_value = 0.004 * S
        nt.links.new(noise_grain.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

        # Puddles: Noise (scale 1.5) -> ColorRamp (0.45 black, 0.55 white) = mask
        noise_puddle = new('ShaderNodeTexNoise')
        noise_puddle.name = noise_puddle.label = 'PMS_FloorSurface_Noise_Puddle'
        noise_puddle.inputs['Scale'].default_value = 1.5
        noise_puddle.inputs['Detail'].default_value = 4.0
        nt.links.new(mapping.outputs['Vector'], noise_puddle.inputs['Vector'])

        ramp = new('ShaderNodeValToRGB')
        ramp.name = ramp.label = 'PMS_FloorSurface_Puddle_Mask'
        ramp.color_ramp.elements[0].position = 0.45
        ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        ramp.color_ramp.elements[1].position = 0.55
        ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(noise_puddle.outputs['Fac'], ramp.inputs['Fac'])

        # Roughness = mix(0.55, 0.06, mask)
        mix_rough = new('ShaderNodeMix')
        mix_rough.name = mix_rough.label = 'PMS_FloorSurface_Roughness'
        mix_rough.data_type = 'FLOAT'
        mix_rough.blend_type = 'MIX'
        # For FLOAT data_type: index 0=Factor, 2=A, 3=B (VALUE sockets)
        mix_rough.inputs[2].default_value = 0.55
        mix_rough.inputs[3].default_value = 0.06
        nt.links.new(ramp.outputs['Color'], mix_rough.inputs[0])
        nt.links.new(mix_rough.outputs[0], bsdf.inputs['Roughness'])

        # Base Color = color * (1 - 0.4 * mask)
        math_mult = new('ShaderNodeMath')
        math_mult.name = math_mult.label = 'PMS_FloorSurface_Color_Mult'
        math_mult.operation = 'MULTIPLY'
        math_mult.inputs[0].default_value = 0.4
        nt.links.new(ramp.outputs['Color'], math_mult.inputs[1])

        math_sub = new('ShaderNodeMath')
        math_sub.name = math_sub.label = 'PMS_FloorSurface_Color_Sub'
        math_sub.operation = 'SUBTRACT'
        math_sub.inputs[0].default_value = 1.0
        nt.links.new(math_mult.outputs['Value'], math_sub.inputs[1])

        mix_color = new('ShaderNodeMix')
        mix_color.name = mix_color.label = 'PMS_FloorSurface_Color'
        mix_color.data_type = 'RGBA'
        mix_color.blend_type = 'MULTIPLY'
        # RGBA sockets: 0=Factor, 6=A, 7=B; output 2. Multiply: A * B with B = grey (1 - 0.4 * mask)
        mix_color.inputs[0].default_value = 1.0
        mix_color.inputs[6].default_value = (*color, 1.0)
        nt.links.new(math_sub.outputs['Value'], mix_color.inputs[7])
        return mix_color.outputs[2]

    elif kind == 'obsidian':
        # Roughness grows with distance from product: Object vector length after Mapping 1/S
        # Map Range (0.6 -> 4.0) to (0.02 -> 0.35)
        vector = new('ShaderNodeVectorMath')
        vector.name = vector.label = 'PMS_FloorSurface_Length'
        vector.operation = 'LENGTH'
        nt.links.new(mapping.outputs['Vector'], vector.inputs[0])

        map_range = new('ShaderNodeMapRange')
        map_range.name = map_range.label = 'PMS_FloorSurface_Roughness_Map'
        map_range.inputs['From Min'].default_value = 0.6
        map_range.inputs['From Max'].default_value = 4.0
        map_range.inputs['To Min'].default_value = 0.02
        map_range.inputs['To Max'].default_value = 0.35
        nt.links.new(vector.outputs['Value'], map_range.inputs['Value'])
        nt.links.new(map_range.outputs['Result'], bsdf.inputs['Roughness'])

        bsdf.inputs['Specular IOR Level'].default_value = 0.5
        return None

    elif kind == 'acrylic':
        # Subsurface + Coat
        bsdf.inputs['Subsurface Weight'].default_value = 0.35
        bsdf.inputs['Subsurface Radius'].default_value = (1.0, 1.0, 1.0)
        bsdf.inputs['Subsurface Scale'].default_value = 0.03 * S
        bsdf.inputs['Coat Weight'].default_value = 0.3
        bsdf.inputs['Coat Roughness'].default_value = 0.25
        return None

    elif kind == 'water':
        # Wave Texture RINGS
        wave = new('ShaderNodeTexWave')
        wave.name = wave.label = 'PMS_FloorSurface_Wave_Rings'
        wave.wave_type = 'RINGS'
        wave.rings_direction = 'SPHERICAL'
        wave.wave_profile = 'SIN'
        # Scale: 1/0.18 after Mapping 1/S
        wave.inputs['Scale'].default_value = 1.0 / 0.18
        wave.inputs['Distortion'].default_value = 0.5
        wave.inputs['Detail'].default_value = 2.0
        wave.inputs['Detail Scale'].default_value = 2.0
        nt.links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        # Bump distance 0.01 * S with strength from Map Range of distance from center (0.5 -> 5.0) to (1.0 -> 0.15)
        vector2 = new('ShaderNodeVectorMath')
        vector2.name = vector2.label = 'PMS_FloorSurface_Dist_Center'
        vector2.operation = 'LENGTH'
        nt.links.new(mapping.outputs['Vector'], vector2.inputs[0])

        map_range2 = new('ShaderNodeMapRange')
        map_range2.name = map_range2.label = 'PMS_FloorSurface_Bump_Strength'
        map_range2.inputs['From Min'].default_value = 0.5
        map_range2.inputs['From Max'].default_value = 5.0
        map_range2.inputs['To Min'].default_value = 1.0
        map_range2.inputs['To Max'].default_value = 0.15
        nt.links.new(vector2.outputs['Value'], map_range2.inputs['Value'])

        bump = new('ShaderNodeBump')
        bump.name = bump.label = 'PMS_FloorSurface_Bump_Water'
        bump.inputs['Distance'].default_value = 0.01 * S
        nt.links.new(wave.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(map_range2.outputs['Result'], bump.inputs['Strength'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

        bsdf.inputs['IOR'].default_value = 1.33
        bsdf.inputs['Specular IOR Level'].default_value = 0.5
        return None

    return None


def build(scene):
    core.begin(scene)
    build_compositing.sync_ev(scene)                        # Cycles exposure compensation follows the presets in use
    inf = core.info(scene)
    core.clear_section(scene, 'floor')
    p, data = live.preset(scene, 'floor')
    _, bg = core.preset(scene, 'background')
    catcher = bool(data.get('shadow_catcher', False))
    scene.render.film_transparent = catcher or bool(scene['pms_saved']['film'])
    obj_name = None
    if data['kind'] == 'plane':
        pms = core.settings(scene)
        # Floor drops with the stage
        stage_h = stage_height(bg, inf.size)
        ob = core.link(scene, 'floor', bpy.data.objects.new('PMS_Floor', _plane(bg['kind'], layout(bg['kind'], inf.size,
                                                                      distance=pms.bg_distance, cove=pms.bg_cove))))
        ob.location = (inf.center.x, inf.center.y, inf.base_z - stage_h)
        ob['pms_orient'] = True
        mat = bpy.data.materials.new('PMS_Floor')
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bg_ob = bpy.data.objects.get('PMS_Background')
        color = data.get('color') or (tuple(bg_ob.active_material.diffuse_color[:3]) if bg_ob and bg_ob.active_material
                                      else (0.3, 0.3, 0.3))
        bsdf.inputs['Base Color'].default_value = (*color, 1.0)
        bsdf.inputs['Roughness'].default_value = data.get('roughness', 0.85)
        bsdf.inputs['Metallic'].default_value = data.get('metallic', 0.0)
        mat.diffuse_color = (*color, 1.0)

        # Floor surface
        surface_kind = data.get('surface')
        if surface_kind:
            final_color = _floor_surface(mat.node_tree, bsdf, surface_kind, color, inf.size)
            if final_color is not None:
                mat.node_tree.links.new(final_color, bsdf.inputs['Base Color'])

        bg_mat = bg_ob.active_material if bg_ob is not None else None
        if (p.data.get('color') is None or p.data.get('glow')) and data.get('metallic', 0.0) < 0.5 and bg['kind'] != 'image' and bg_mat is not None:
            # a floor in the backdrop's colour glows like the backdrop (else a dark band shows where the floor meets the wall)
            bsdf.inputs['Emission Color'].default_value = (*color, 1.0)
            build_background.add_self_light(mat.node_tree, bsdf)
            glow = bg_mat.node_tree.nodes.get('PMS_SelfLight')
            build_background.set_self_light(mat, glow.inputs[1].default_value if glow is not None else 0.0)
        ob.data.materials.append(mat)
        ob.is_shadow_catcher = catcher
        core.orient_rigs(scene)
        obj_name = ob.name
    bg_ob = bpy.data.objects.get('PMS_Background')
    if bg_ob is not None:
        bg_ob.visible_camera = not catcher
    build_lighting.link_mirror_floor(scene)
    return {'floor': p.id, 'object': obj_name, 'shadow_catcher': catcher}
