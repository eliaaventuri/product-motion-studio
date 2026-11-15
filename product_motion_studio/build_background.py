"""Background: cyclorama / 360 studio mesh or camera plate, with a gradient (or image) material."""

import os
from math import cos, pi, radians, sin, sqrt
import bmesh
import bpy
from mathutils import Vector
from . import build_compositing, core, live

ARC = 14          # segments of the cove


def _surface(nt, bsdf, kind, color, S):
    """Insert procedural surface nodes between the ramp output and the BSDF.
    kind: 'travertine' | 'concrete' | 'fluted' | 'silk'
    Returns the final color output to connect to Base Color and Emission Color."""
    new = nt.nodes.new
    coord = new('ShaderNodeTexCoord')
    coord.name = coord.label = 'PMS_Surface_Coord'
    mapping = new('ShaderNodeMapping')
    mapping.name = mapping.label = 'PMS_Surface_Mapping'
    mapping.vector_type = 'POINT'
    mapping.inputs['Scale'].default_value = (1.0 / S, 1.0 / S, 1.0 / S)
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])

    if kind == 'travertine':
        # Bands for horizontal veins
        wave = new('ShaderNodeTexWave')
        wave.name = wave.label = 'PMS_Surface_Wave_Bands'
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'Z'
        wave.inputs['Scale'].default_value = 1.6
        wave.inputs['Distortion'].default_value = 6.0
        wave.inputs['Detail'].default_value = 4.0
        wave.inputs['Detail Scale'].default_value = 2.0
        nt.links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        # Voronoi for pores
        voronoi = new('ShaderNodeTexVoronoi')
        voronoi.name = voronoi.label = 'PMS_Surface_Voronoi'
        voronoi.feature = 'F1'
        voronoi.inputs['Scale'].default_value = 14.0
        nt.links.new(mapping.outputs['Vector'], voronoi.inputs['Vector'])

        # Pores mask: F1 < 0.08
        math_pores = new('ShaderNodeMath')
        math_pores.name = math_pores.label = 'PMS_Surface_Pores_Mask'
        math_pores.operation = 'LESS_THAN'
        math_pores.inputs[1].default_value = 0.08
        nt.links.new(voronoi.outputs['Distance'], math_pores.inputs[0])

        # Color: ramp * (0.80 + 0.20 * bands) * (1 - 0.3 * pores)
        # First multiply by bands factor
        math_bands = new('ShaderNodeMath')
        math_bands.name = math_bands.label = 'PMS_Surface_Bands_Factor'
        math_bands.operation = 'MULTIPLY'
        math_bands.inputs[0].default_value = 0.20
        nt.links.new(wave.outputs['Fac'], math_bands.inputs[1])

        add_bands = new('ShaderNodeMath')
        add_bands.name = add_bands.label = 'PMS_Surface_Bands_Add'
        add_bands.operation = 'ADD'
        add_bands.inputs[0].default_value = 0.80
        nt.links.new(math_bands.outputs[0], add_bands.inputs[1])

        # Multiply by (1 - 0.3 * pores)
        math_pores_mult = new('ShaderNodeMath')
        math_pores_mult.name = math_pores_mult.label = 'PMS_Surface_Pores_Mult'
        math_pores_mult.operation = 'MULTIPLY'
        math_pores_mult.inputs[0].default_value = 0.30
        nt.links.new(math_pores.outputs[0], math_pores_mult.inputs[1])

        sub_pores = new('ShaderNodeMath')
        sub_pores.name = sub_pores.label = 'PMS_Surface_Pores_Sub'
        sub_pores.operation = 'SUBTRACT'
        sub_pores.inputs[0].default_value = 1.0
        nt.links.new(math_pores_mult.outputs[0], sub_pores.inputs[1])

        # Final color multiplier
        math_color = new('ShaderNodeMath')
        math_color.name = math_color.label = 'PMS_Surface_Color_Mult'
        math_color.operation = 'MULTIPLY'
        nt.links.new(add_bands.outputs[0], math_color.inputs[0])
        nt.links.new(sub_pores.outputs[0], math_color.inputs[1])

        mix_color = new('ShaderNodeMix')
        mix_color.name = mix_color.label = 'PMS_Surface_Color'
        mix_color.data_type = 'RGBA'
        mix_color.blend_type = 'MULTIPLY'
        nt.links.new(color, mix_color.inputs[6])                  # A color
        mix_color.inputs[0].default_value = 1.0                   # Multiply: A * B
        nt.links.new(math_color.outputs[0], mix_color.inputs[7])  # B = scalar factor
        final_color = mix_color.outputs[2]

        # Roughness: 0.62 + 0.15 * bands
        math_rough = new('ShaderNodeMath')
        math_rough.name = math_rough.label = 'PMS_Surface_Roughness'
        math_rough.operation = 'MULTIPLY'
        math_rough.inputs[0].default_value = 0.15
        nt.links.new(wave.outputs['Fac'], math_rough.inputs[1])

        add_rough = new('ShaderNodeMath')
        add_rough.name = add_rough.label = 'PMS_Surface_Roughness_Add'
        add_rough.operation = 'ADD'
        add_rough.inputs[0].default_value = 0.62
        nt.links.new(math_rough.outputs[0], add_rough.inputs[1])
        nt.links.new(add_rough.outputs[0], bsdf.inputs['Roughness'])

        # Bump from pores
        bump = new('ShaderNodeBump')
        bump.name = bump.label = 'PMS_Surface_Bump'
        bump.inputs['Strength'].default_value = 0.35
        bump.inputs['Distance'].default_value = 0.004 * S
        nt.links.new(math_pores.outputs[0], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    elif kind == 'concrete':
        # Noise for stains
        noise1 = new('ShaderNodeTexNoise')
        noise1.name = noise1.label = 'PMS_Surface_Noise_Stains'
        noise1.inputs['Scale'].default_value = 3.0
        noise1.inputs['Detail'].default_value = 8.0
        noise1.inputs['Roughness'].default_value = 0.6
        nt.links.new(mapping.outputs['Vector'], noise1.inputs['Vector'])

        # Noise for brushed lines: stretch coordinates (0.3, 30, 30) -> horizontal lines along X
        mapping2 = new('ShaderNodeMapping')
        mapping2.name = mapping2.label = 'PMS_Surface_Mapping_Brushed'
        mapping2.vector_type = 'POINT'
        mapping2.inputs['Scale'].default_value = (0.3, 30.0, 30.0)
        nt.links.new(mapping.outputs['Vector'], mapping2.inputs['Vector'])

        noise2 = new('ShaderNodeTexNoise')
        noise2.name = noise2.label = 'PMS_Surface_Noise_Brushed'
        noise2.inputs['Scale'].default_value = 3.0
        noise2.inputs['Detail'].default_value = 8.0
        noise2.inputs['Roughness'].default_value = 0.6
        nt.links.new(mapping2.outputs['Vector'], noise2.inputs['Vector'])

        # Color: ramp * (0.75 + 0.25 * stains) * (0.92 + 0.08 * lines)
        math_stains = new('ShaderNodeMath')
        math_stains.name = math_stains.label = 'PMS_Surface_Stains_Factor'
        math_stains.operation = 'MULTIPLY'
        math_stains.inputs[0].default_value = 0.25
        nt.links.new(noise1.outputs['Fac'], math_stains.inputs[1])

        add_stains = new('ShaderNodeMath')
        add_stains.name = add_stains.label = 'PMS_Surface_Stains_Add'
        add_stains.operation = 'ADD'
        add_stains.inputs[0].default_value = 0.75
        nt.links.new(math_stains.outputs[0], add_stains.inputs[1])

        math_lines = new('ShaderNodeMath')
        math_lines.name = math_lines.label = 'PMS_Surface_Lines_Factor'
        math_lines.operation = 'MULTIPLY'
        math_lines.inputs[0].default_value = 0.08
        nt.links.new(noise2.outputs['Fac'], math_lines.inputs[1])

        add_lines = new('ShaderNodeMath')
        add_lines.name = add_lines.label = 'PMS_Surface_Lines_Add'
        add_lines.operation = 'ADD'
        add_lines.inputs[0].default_value = 0.92
        nt.links.new(math_lines.outputs[0], add_lines.inputs[1])

        math_color1 = new('ShaderNodeMath')
        math_color1.name = math_color1.label = 'PMS_Surface_Color_Mult1'
        math_color1.operation = 'MULTIPLY'
        nt.links.new(add_stains.outputs[0], math_color1.inputs[0])
        nt.links.new(add_lines.outputs[0], math_color1.inputs[1])

        mix_color = new('ShaderNodeMix')
        mix_color.name = mix_color.label = 'PMS_Surface_Color'
        mix_color.data_type = 'RGBA'
        mix_color.blend_type = 'MULTIPLY'
        nt.links.new(color, mix_color.inputs[6])                  # A color
        mix_color.inputs[0].default_value = 1.0                   # Multiply: A * B
        nt.links.new(math_color1.outputs[0], mix_color.inputs[7])  # B = scalar factor
        final_color = mix_color.outputs[2]

        # Roughness fixed 0.85
        bsdf.inputs['Roughness'].default_value = 0.85

        # Bump from stains + lines
        math_bump = new('ShaderNodeMath')
        math_bump.name = math_bump.label = 'PMS_Surface_Bump_Add'
        math_bump.operation = 'ADD'
        nt.links.new(noise1.outputs['Fac'], math_bump.inputs[0])
        nt.links.new(noise2.outputs['Fac'], math_bump.inputs[1])

        bump = new('ShaderNodeBump')
        bump.name = bump.label = 'PMS_Surface_Bump'
        bump.inputs['Strength'].default_value = 0.15
        bump.inputs['Distance'].default_value = 0.003 * S
        nt.links.new(math_bump.outputs[0], bump.inputs['Height'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    elif kind == 'fluted':
        # Wave BANDS direction X, SIN profile, scale for 0.12*S wide ribs
        # With Mapping scale 1/S, Wave scale = 1/0.12
        wave = new('ShaderNodeTexWave')
        wave.name = wave.label = 'PMS_Surface_Wave_Fluted'
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'X'
        wave.wave_profile = 'SIN'
        wave.inputs['Scale'].default_value = 1.0 / 0.12
        nt.links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        # Color unchanged
        final_color = color

        # Bump only where Z > 0.05*S in Object coords
        separate = new('ShaderNodeSeparateXYZ')
        separate.name = separate.label = 'PMS_Surface_SeparateXYZ'
        nt.links.new(coord.outputs['Object'], separate.inputs['Vector'])

        math_z = new('ShaderNodeMath')
        math_z.name = math_z.label = 'PMS_Surface_Z_Compare'
        math_z.operation = 'GREATER_THAN'
        math_z.inputs[1].default_value = 0.05 * S
        nt.links.new(separate.outputs['Z'], math_z.inputs[0])

        # Multiply bump strength by Z mask
        math_bump_strength = new('ShaderNodeMath')
        math_bump_strength.name = math_bump_strength.label = 'PMS_Surface_Bump_Strength'
        math_bump_strength.operation = 'MULTIPLY'
        math_bump_strength.inputs[0].default_value = 0.9
        nt.links.new(math_z.outputs[0], math_bump_strength.inputs[1])

        bump = new('ShaderNodeBump')
        bump.name = bump.label = 'PMS_Surface_Bump'
        bump.inputs['Distance'].default_value = 0.03 * S
        nt.links.new(wave.outputs['Fac'], bump.inputs['Height'])
        nt.links.new(math_bump_strength.outputs[0], bump.inputs['Strength'])
        nt.links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    elif kind == 'silk':
        # Satin material: no texture, just BSDF params
        final_color = color
        bsdf.inputs['Roughness'].default_value = 0.28
        bsdf.inputs['Sheen Weight'].default_value = 0.6
        bsdf.inputs['Sheen Roughness'].default_value = 0.3
        bsdf.inputs['Specular IOR Level'].default_value = 0.5

    return final_color


def stage_height(data, S):
    """Return stage height in world units, or 0.0 if no stage."""
    stage = data.get('stage')
    if stage:
        return float(stage.get('height_f', 0.35)) * S
    return 0.0


def layout(kind, S, with_floor=True, distance=1.0, cove=1.0):
    """Backdrop dimensions from the product size S. Shared with build_floor (plane size)."""
    if kind == 'cyclorama':
        return dict(half_w=14 * S, y_front=-9 * S, y_back=5 * S * distance, R=1.5 * S * cove, H=12 * S)
    if kind == 'studio360':
        return dict(R_floor=7 * S * distance, R=1.5 * S * cove, H=12 * S)
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


def _mesh(kind, L, with_floor, silk=False, S=1.0):
    prof = _profile(kind, L, with_floor)
    length = [0.0]
    for a, b in zip(prof, prof[1:]):
        length.append(length[-1] + ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
    v_of = [s / length[-1] for s in length]
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    if kind == 'cyclorama':
        if silk:
            # columns every ~0.07 S on [-half_w, half_w]: the shortest fold (0.45 S) gets 6+ vertices
            nc = int(2 * L['half_w'] / (0.07 * S)) + 1
            cols = [(-L['half_w'] + 2 * L['half_w'] * i / (nc - 1), i / (nc - 1)) for i in range(nc)]
            # densify profile: each segment split into pieces max 0.25 * S long
            prof_dense = []
            for a, b in zip(prof, prof[1:]):
                seg_len = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                n_seg = max(1, int(seg_len / (0.25 * S)) + 1)
                for k in range(n_seg):
                    t = k / n_seg
                    prof_dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            prof_dense.append(prof[-1])
            # update v_of for dense profile
            length_dense = [0.0]
            for a, b in zip(prof_dense, prof_dense[1:]):
                length_dense.append(length_dense[-1] + ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5)
            v_of = [s / length_dense[-1] for s in length_dense]
            grid = [[bm.verts.new((x, y, z)) for (y, z) in prof_dense] for x, _ in cols]
            uvs = lambda c, i: (cols[c][1], v_of[i])
            ncol = len(cols)
        else:
            cols = [(-L['half_w'], 0.0), (L['half_w'], 1.0)]
            grid = [[bm.verts.new((x, y, z)) for (y, z) in prof] for x, _ in cols]
            uvs = lambda c, i: (cols[c][1], v_of[i])
            ncol = 2
        wrap = False
    else:
        n = 96
        grid = [[bm.verts.new((r * cos(2 * pi * j / n), r * sin(2 * pi * j / n), z)) for (r, z) in prof]
                for j in range(n)]
        uvs = lambda c, i: (c / n, v_of[i])
        ncol, wrap = n + 1, True
    for c in range(ncol - 1):
        c2 = (c + 1) % len(grid)
        for i in range(len(grid[c]) - 1):
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
    # Silk displacement on cyclorama
    if kind == 'cyclorama' and silk:
        for v in mesh.vertices:
            x, y, z = v.co
            # A(z) = 0.22 * S * smoothstep(z / (3 * S))
            u = z / (3.0 * S)
            if u < 0.0:
                u = 0.0
            elif u > 1.0:
                u = 1.0
            A = 0.22 * S * (3 * u * u - 2 * u * u * u)
            # dy = A * (sin(2π x/(1.1 S) + 0.4) + 0.5 sin(2π x/(0.7 S) + 1.3) + 0.25 sin(2π x/(0.45 S) + 2.1))
            dy = A * (sin(2 * pi * x / (1.1 * S) + 0.4)
                      + 0.5 * sin(2 * pi * x / (0.7 * S) + 1.3)
                      + 0.25 * sin(2 * pi * x / (0.45 * S) + 2.1))
            v.co.y += dy
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


def _ramp_material(name, data, image_path=None, size=1.0):
    """Principled material: colour from a gradient ramp (or an image file), optional self light.
    If data has 'surface' and no image, insert procedural surface nodes."""
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
        # Procedural surface
        surface_kind = data.get('surface')
        if surface_kind:
            color = _surface(nt, bsdf, surface_kind, color, size)
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
    L = layout(kind, S, with_floor, distance=float(data.get('distance', 1.0)), cove=float(data.get('cove', 1.0)))

    # Stage height
    h = stage_height(data, S)

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
        silk = (data.get('surface') == 'silk')
        mesh = _mesh(kind, L, with_floor, silk=silk, S=S)
        ob = core.link(scene, 'background', bpy.data.objects.new('PMS_Background', mesh))
        # Background drops by stage height h
        ob.location = (inf.center.x, inf.center.y, inf.base_z - 0.001 * S - h)
        ob['pms_orient'] = True

    ob.data.materials.append(_ramp_material('PMS_Background', data, path if kind == 'image' and path else None, size=S))
    ob.visible_camera = not floor.get('shadow_catcher', False)

    # Stage (plinth / steps) for cyclorama and studio360: the backdrop drops by h, the stage fills the gap
    if kind in ('cyclorama', 'studio360') and h > 0:
        stage_data = data.get('stage')
        stage_type = stage_data.get('type', 'plinth_round')
        stage_color = stage_data.get('color')
        stage_roughness = stage_data.get('roughness', 0.5)
        wf = max(inf.dims.x, inf.dims.y)
        # The backdrop origin is on the product centre: local x/y = 0 is the centre, local z = 0.001 * S
        # puts the top face of the stage on inf.base_z in world
        local_z = 0.001 * S
        pieces = []
        if stage_type == 'plinth_round':
            # Cylinder 64 sides, radius 0.8 * wf + 0.1 * S, height h (create_cone is centred on z = 0)
            r = 0.8 * wf + 0.1 * S
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=64, radius1=r, radius2=r, depth=h)
            bmesh.ops.translate(bm, vec=(0, 0, h / 2.0), verts=bm.verts)
            pieces.append(('PMS_Stage', bm, (0.0, 0.0, local_z)))
        elif stage_type == 'plinth_box':
            # Square box, side 1.6 * wf + 0.2 * S, height h
            bm = bmesh.new()
            side = 1.6 * wf + 0.2 * S
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(side, side, h), verts=bm.verts)
            bmesh.ops.translate(bm, vec=(0, 0, h / 2.0), verts=bm.verts)
            pieces.append(('PMS_Stage', bm, (0.0, 0.0, local_z)))
        elif stage_type == 'steps':
            # 3 boxes of height h / 3 stacked; all share the back edge (max y) of the top step
            t = 1.4 * wf + 0.1 * S
            widths = [t + 1.8 * S, t + 0.9 * S, t]          # bottom to top
            depths = [t + 1.2 * S, t + 0.6 * S, t]
            step_h = h / 3.0
            for i in range(3):
                bm = bmesh.new()
                bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=(widths[i], depths[i], step_h), verts=bm.verts)
                bmesh.ops.translate(bm, vec=(0, 0, step_h / 2.0), verts=bm.verts)
                y_local = t / 2.0 - depths[i] / 2.0
                pieces.append((f'PMS_Stage_{i + 1}', bm, (0.0, y_local, local_z + i * step_h)))
        stage_obs = []
        for name, bm, loc in pieces:
            mesh = bpy.data.meshes.new(name)
            bm.to_mesh(mesh)
            bm.free()
            stage_ob = core.link(scene, 'background', bpy.data.objects.new(name, mesh))
            stage_ob.location = loc
            stage_ob.parent = ob
            bevel = stage_ob.modifiers.new('PMS_Bevel', 'BEVEL')
            bevel.width = 0.01 * S
            bevel.segments = 3
            bevel.limit_method = 'ANGLE'
            stage_obs.append(stage_ob)
        # Material: the backdrop's own, or a plain Principled when the stage has its own colour
        if stage_color is not None:
            mat = bpy.data.materials.new('PMS_Stage')
            nt = mat.node_tree
            nt.nodes.clear()
            new = nt.nodes.new
            out, bsdf = new('ShaderNodeOutputMaterial'), new('ShaderNodeBsdfPrincipled')
            nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            bsdf.inputs['Base Color'].default_value = (*stage_color, 1.0)
            bsdf.inputs['Roughness'].default_value = stage_roughness
            mat.diffuse_color = (*stage_color, 1.0)
        else:
            mat = ob.active_material
        for stage_ob in stage_obs:
            stage_ob.data.materials.append(mat)
    core.orient_rigs(scene)
    if scene.world is not None and scene.world.name == 'PMS_World':
        from . import build_lighting
        build_lighting.refresh_world(scene)                  # the backdrop may add (or take away) the world fill
    return {'background': p.id, 'object': ob.name, 'kind': kind, 'warnings': warnings}
