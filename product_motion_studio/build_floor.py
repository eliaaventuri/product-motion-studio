"""Floor: separate plane PMS_Floor (matte / glossy / mirror / shadow catcher). 'seamless' is part of the backdrop."""

import bmesh
import bpy
from . import core, live
from . import build_background, build_compositing, build_lighting
from .build_background import layout


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
        ob = core.link(scene, 'floor', bpy.data.objects.new('PMS_Floor', _plane(bg['kind'], layout(bg['kind'], inf.size))))
        ob.location = (inf.center.x, inf.center.y, inf.base_z)
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
