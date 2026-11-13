"""Background: cyclorama / 360 studio mesh or camera plate, with a gradient (or image) material."""

import os
from math import cos, pi, radians, sin
import bmesh
import bpy
from mathutils import Vector
from . import build_compositing, core, live

ARC = 14          # segments of the cove


def layout(kind, S, with_floor=True):
    """Backdrop dimensions from the product size S. Shared with build_floor (plane size)."""
    if kind == 'cyclorama':
        return dict(half_w=14 * S, y_front=-9 * S, y_back=5 * S, R=1.5 * S, H=12 * S)
    if kind == 'studio360':
        return dict(R_floor=7 * S, R=1.5 * S, H=12 * S)
    return dict(half=30 * S)


def _profile(kind, L, with_floor):
    """(lateral, z) points from the start of the floor to the top of the wall."""
    if kind == 'cyclorama':
        edge, pts = L['y_back'], ([(L['y_front'], 0.0)] if with_floor else [])
    else:
        edge, pts = L['R_floor'], ([(0.0, 0.0)] if with_floor else [])
    R = L['R']
    pts.append((edge, 0.0))
    pts += [(edge + R * sin(pi / 2 * i / ARC), R * (1 - cos(pi / 2 * i / ARC))) for i in range(1, ARC + 1)]
    pts.append((edge + R, L['H']))
    return pts


def _mesh(kind, L, with_floor):
    prof = _profile(kind, L, with_floor)
    length = [0.0]
    for a, b in zip(prof, prof[1:]):
        length.append(length[-1] + ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
    v_of = [s / length[-1] for s in length]
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    if kind == 'cyclorama':
        cols = [(-L['half_w'], 0.0), (L['half_w'], 1.0)]
        grid = [[bm.verts.new((x, y, z)) for (y, z) in prof] for x, _ in cols]
        uvs = lambda c, i: (cols[c][1], v_of[i])
        ncol, wrap = 2, False
    else:
        n = 96
        grid = [[bm.verts.new((r * cos(2 * pi * j / n), r * sin(2 * pi * j / n), z)) for (r, z) in prof]
                for j in range(n)]
        uvs = lambda c, i: (c / n, v_of[i])
        ncol, wrap = n + 1, True
    for c in range(ncol - 1):
        c2 = (c + 1) % len(grid)
        for i in range(len(prof) - 1):
            f = bm.faces.new((grid[c][i], grid[c][i + 1], grid[c2][i + 1], grid[c2][i]))
            for loop, (cc, ii) in zip(f.loops, ((c, i), (c, i + 1), (c + 1, i + 1), (c + 1, i))):
                loop[uv].uv = uvs(cc, ii)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6 * L.get('H', 1))
    bm.faces.ensure_lookup_table()
    bm.faces[0].normal_update()
    if bm.faces[0].normal.z < 0:                              # floor/cove must face up and the wall faces the product
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new('PMS_Background')
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    return mesh


def configure_gradient(nt, data):
    """(Re)set the gradient nodes of a ramp material from data: stops, gradient type / rotation / centre."""
    g = data.get('gradient', {})
    radial = g.get('type') == 'radial'
    mp = next(n for n in nt.nodes if n.type == 'MAPPING')
    grad = next(n for n in nt.nodes if n.type == 'TEX_GRADIENT')
    ramp = next(n for n in nt.nodes if n.type == 'VALTORGB')
    mp.vector_type = 'POINT'
    grad.gradient_type = 'SPHERICAL' if radial else 'LINEAR'
    if radial:                                                # 1 at the centre: reverse the stop positions
        cu, cv = g.get('center', (0.5, 0.5))
        mp.inputs['Location'].default_value = (-cu * 1.4, -cv * 1.4, 0)  # POINT: S*uv + L = 0 at uv = c
        mp.inputs['Rotation'].default_value = (0, 0, 0)
        mp.inputs['Scale'].default_value = (1.4, 1.4, 1.4)
        stops = [(1 - p, c) for p, c in data['stops']]
    else:                                                     # x' = v: the ramp runs along the profile
        mp.inputs['Location'].default_value = (0, 0, 0)
        mp.inputs['Rotation'].default_value = (0, 0, radians(-90 + g.get('rotation', 0)))
        mp.inputs['Scale'].default_value = (1, 1, 1)
        stops = data['stops']
    stops = sorted(stops, key=lambda s: s[0])
    els = ramp.color_ramp.elements
    while len(els) > 2:
        els.remove(els[len(els) - 1])
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = (*col, 1)


def update_material(mat, data):
    """Apply roughness, self light and (when the material has a ramp) the gradient of data to an existing material: what the
    builder does at build time and the live controls do afterwards."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Roughness'].default_value = data.get('roughness', 0.9)
    if any(n.type == 'VALTORGB' for n in nt.nodes):
        configure_gradient(nt, data)
        mat.diffuse_color = (*sorted(data['stops'], key=lambda s: s[0])[0][1], 1)
    set_self_light(mat, data.get('self_light', 0.0))


def add_self_light(nt, bsdf):
    """Wire the Emission Strength of a Principled node as strength x (1 - Is Diffuse Ray). Self light is for the eye (camera,
    reflections, refractions), not for the product: diffuse rays do not see it, so in Cycles a glowing backdrop does not bounce
    extra light onto the product (Eevee does not either). The strength is the PMS_SelfLight node (see set_self_light)."""
    path, inv, glow = nt.nodes.new('ShaderNodeLightPath'), nt.nodes.new('ShaderNodeMath'), nt.nodes.new('ShaderNodeMath')
    inv.operation, glow.operation = 'SUBTRACT', 'MULTIPLY'
    inv.inputs[0].default_value = 1.0
    glow.name = glow.label = 'PMS_SelfLight'
    nt.links.new(path.outputs['Is Diffuse Ray'], inv.inputs[1])
    nt.links.new(inv.outputs[0], glow.inputs[0])
    nt.links.new(glow.outputs[0], bsdf.inputs['Emission Strength'])


def set_self_light(mat, value):
    nt = mat.node_tree
    glow = nt.nodes.get('PMS_SelfLight')                      # (materials made before the node existed: the socket itself)
    if glow is not None:
        glow.inputs[1].default_value = value
    else:
        next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Emission Strength'].default_value = value


def _ramp_material(name, data, image_path=None):
    """Principled material: colour from a gradient ramp (or an image file), optional self light."""
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    nt.nodes.clear()
    new = nt.nodes.new
    out, bsdf = new('ShaderNodeOutputMaterial'), new('ShaderNodeBsdfPrincipled')
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Specular IOR Level'].default_value = 0.15
    uv = new('ShaderNodeUVMap')
    if image_path:
        tex = new('ShaderNodeTexImage')
        try:
            core.check_image(image_path)
        except ValueError as e:
            raise RuntimeError(f"PMS {e}") from None
        tex.image = bpy.data.images.load(image_path, check_existing=False)
        tex.image.name = 'PMS_Background_Image'
        nt.links.new(uv.outputs['UV'], tex.inputs['Vector'])
        color = tex.outputs['Color']
        bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
    else:
        mp, grad, ramp = new('ShaderNodeMapping'), new('ShaderNodeTexGradient'), new('ShaderNodeValToRGB')
        nt.links.new(uv.outputs['UV'], mp.inputs['Vector'])
        nt.links.new(mp.outputs['Vector'], grad.inputs['Vector'])
        nt.links.new(grad.outputs['Fac'], ramp.inputs['Fac'])
        color = ramp.outputs['Color']
        nt.links.new(color, bsdf.inputs['Base Color'])
    nt.links.new(color, bsdf.inputs['Emission Color'])        # strength 0 = no glow; self light is a live control
    add_self_light(nt, bsdf)
    update_material(mat, data)
    return mat


def build(scene):
    core.begin(scene)
    build_compositing.sync_ev(scene)                        # Cycles exposure compensation follows the presets in use
    pms = core.settings(scene)
    inf = core.info(scene)
    core.clear_section(scene, 'background')
    p, data = live.preset(scene, 'background')
    _, floor = core.preset(scene, 'floor')
    kind, S = data['kind'], inf.size
    with_floor = floor.get('kind') == 'seamless'
    warnings = []
    L = layout(kind, S, with_floor)
    if kind == 'image':
        path = bpy.path.abspath(pms.bg_image) if pms.bg_image else ''
        if path and not os.path.isfile(path):
            warnings.append(f"background image not found: {path}")
            path = ''
        if not path:
            warnings.append("no background image set: grey gradient used")
        if with_floor:
            warnings.append("floor 'seamless' needs a cyclorama/360 backdrop: no floor created")
        cam = bpy.data.objects.get('PMS_Camera')
        pivot = bpy.data.objects.get('PMS_Cam_Pivot')
        if cam is None or pivot is None:
            raise RuntimeError("PMS background 'image' needs the camera built first")
        plate_d = 4 * S                                       # behind the product, in pivot space
        reach = 1.6 * abs(cam.location.y)                     # generous: covers push/pull moves
        tx, ty = core.frame_tans(scene, cam.data.lens)
        mesh = bpy.data.meshes.new('PMS_Background')
        w, h = tx * (reach + plate_d) * 1.3, ty * (reach + plate_d) * 1.3
        bm = bmesh.new()
        uv = bm.loops.layers.uv.new('UVMap')
        vs = [bm.verts.new(c) for c in ((-w, -h, 0), (w, -h, 0), (w, h, 0), (-w, h, 0))]
        f = bm.faces.new(vs)
        for loop, c in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = c
        bm.to_mesh(mesh)
        bm.free()
        ob = core.link(scene, 'background', bpy.data.objects.new('PMS_Background', mesh))
        ob.parent = pivot
        ob.location = (0, plate_d, 0)
        ob.rotation_euler = (pi / 2, 0, 0)                    # plane normal towards the camera
        ob['pms_orient'] = False
        ob.visible_shadow = False
    else:
        mesh = _mesh(kind, L, with_floor)
        ob = core.link(scene, 'background', bpy.data.objects.new('PMS_Background', mesh))
        ob.location = (inf.center.x, inf.center.y, inf.base_z - 0.001 * S)
        ob['pms_orient'] = True
    ob.data.materials.append(_ramp_material('PMS_Background', data, path if kind == 'image' and path else None))
    ob.visible_camera = not floor.get('shadow_catcher', False)
    core.orient_rigs(scene)
    if scene.world is not None and scene.world.name == 'PMS_World':
        from . import build_lighting
        build_lighting.refresh_world(scene)                  # the backdrop may add (or take away) the world fill
    return {'background': p.id, 'object': ob.name, 'kind': kind, 'warnings': warnings}
