"""Headless test of the new backdrops and floors with surface/stage.
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_backdrops_extra.py
One PASS/FAIL line per test. Never renders."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, presets

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=60)


def test(name):
    def deco(fn):
        try:
            msg = fn()
            RESULTS.append((name, True, msg or ''))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def cube(name='P', loc=(0, 0, 1), size=2):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def built(**kw):
    sc = fresh()
    p = cube()
    api.build(objects=[p], **{**W, **kw})
    return sc, p


def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


# ---------------------------------------------------------------------------------------------
@test("1 New backgrounds build without errors (with floor 'matte' and 'seamless')")
def test_new_backgrounds_build():
    new_bgs = [
        'arch_plinth_pedestal',
        'fluted_ribbed_wall',
        'stepped_gallery_stage',
        'travertine_stone_studio',
        'brushed_concrete_brutalist',
        'satin_silk_drape',
    ]
    for bg_id in new_bgs:
        for floor_kind in ('matte', 'seamless'):
            sc, p = built(background=bg_id, floor=floor_kind)
            bg_ob = bpy.data.objects.get('PMS_Background')
            assert bg_ob is not None, f"{bg_id} + {floor_kind}: no PMS_Background"
            assert bg_ob.active_material is not None, f"{bg_id} + {floor_kind}: no material"
            if floor_kind == 'seamless':
                assert bg_ob.data.vertices, f"{bg_id} + seamless: no mesh"
            api.remove_all()
    return f"{len(new_bgs)} backgrounds x 2 floors built"


@test("2 arch_plinth_pedestal + matte: PMS_Stage child of PMS_Background, top at base_z")
def test_arch_plinth_pedestal():
    sc, p = built(background='arch_plinth_pedestal', floor='matte')
    bg_ob = bpy.data.objects.get('PMS_Background')
    assert bg_ob is not None
    stage_ob = bpy.data.objects.get('PMS_Stage')
    assert stage_ob is not None, "PMS_Stage not found"
    assert stage_ob.parent == bg_ob, "PMS_Stage not parented to PMS_Background"

    # Max Z of stage vertices in world == inf.base_z
    inf = core.info()
    max_z = max((stage_ob.matrix_world @ v.co).z for v in stage_ob.data.vertices)
    expected_z = inf.base_z
    assert abs(max_z - expected_z) < 1e-4 * inf.size, f"stage top Z {max_z:.6f} != base_z {expected_z:.6f}"

    # Floor at base_z - 0.35*S
    floor_ob = bpy.data.objects.get('PMS_Floor')
    assert floor_ob is not None
    floor_z = floor_ob.location.z
    expected_floor_z = inf.base_z - 0.35 * inf.size
    assert abs(floor_z - expected_floor_z) < 1e-4 * inf.size, f"floor Z {floor_z:.6f} != {expected_floor_z:.6f}"

    # Product hasn't moved
    root = bpy.data.objects.get('PMS_Product_Root')
    assert abs(root.location.z - inf.center.z) < 1e-4, "product moved"
    api.remove_all()
    return f"stage top {max_z:.6f} == base_z {expected_z:.6f}, floor {floor_z:.6f}"


@test("3 stepped_gallery_stage: PMS_Stage_1..3 exist, 3 is highest and smallest")
def test_stepped_gallery_stage():
    sc, p = built(background='stepped_gallery_stage', floor='matte')
    stages = [bpy.data.objects.get(f'PMS_Stage_{i}') for i in range(1, 4)]
    assert all(s is not None for s in stages), "not all PMS_Stage_1..3 found"
    assert stages[0].parent == bpy.data.objects.get('PMS_Background')
    assert stages[1].parent == bpy.data.objects.get('PMS_Background')
    assert stages[2].parent == bpy.data.objects.get('PMS_Background')

    # Stage 3 (index 2) is highest and smallest (by volume/bbox)
    zs = [max((s.matrix_world @ v.co).z for v in s.data.vertices) for s in stages]
    assert zs[2] > zs[1] > zs[0], f"Z order wrong: {zs}"

    # Volume proxy: bbox volume
    vols = [s.dimensions.x * s.dimensions.y * s.dimensions.z for s in stages]
    assert vols[2] < vols[1] < vols[0], f"Volume order wrong (top should be smallest): {vols}"
    api.remove_all()
    return f"Z: {[round(z,3) for z in zs]}, vols: {[round(v,3) for v in vols]}"


@test("4 Return to cyclorama_studio_grey: PMS_Stage* gone, floor back at base_z")
def test_return_to_cyclorama():
    sc, p = built(background='arch_plinth_pedestal', floor='matte')
    assert bpy.data.objects.get('PMS_Stage') is not None
    inf = core.info()
    floor_z_with_stage = bpy.data.objects['PMS_Floor'].location.z

    # Switch back
    api.apply('background', 'cyclorama_studio_grey')

    # PMS_Stage* should not exist
    for name in ('PMS_Stage', 'PMS_Stage_1', 'PMS_Stage_2', 'PMS_Stage_3'):
        assert bpy.data.objects.get(name) is None, f"{name} still exists"

    # Floor back at base_z
    floor_ob = bpy.data.objects.get('PMS_Floor')
    assert floor_ob is not None
    floor_z = floor_ob.location.z
    assert abs(floor_z - inf.base_z) < 1e-4 * inf.size, f"floor Z {floor_z:.6f} != base_z {inf.base_z:.6f}"
    api.remove_all()
    return f"stages removed, floor at base_z {inf.base_z:.6f}"


@test("5 satin_silk_drape: mesh >= 2000 verts, y stddev > 0.02*S for z > S")
def test_satin_silk_drape():
    sc, p = built(background='satin_silk_drape', floor='matte')
    bg_ob = bpy.data.objects.get('PMS_Background')
    assert bg_ob is not None
    verts = [v.co for v in bg_ob.data.vertices]
    assert len(verts) >= 2000, f"only {len(verts)} vertices, expected >= 2000"

    inf = core.info()
    S = inf.size
    # Vertices with z > S in local coords
    high_verts = [v for v in verts if v.z > S]
    assert len(high_verts) > 10, f"only {len(high_verts)} vertices with z > S"
    ys = [v.y for v in high_verts]
    mean_y = sum(ys) / len(ys)
    var_y = sum((y - mean_y) ** 2 for y in ys) / len(ys)
    std_y = var_y ** 0.5
    assert std_y > 0.02 * S, f"y stddev {std_y:.6f} <= 0.02*S ({0.02*S:.6f})"
    api.remove_all()
    return f"verts={len(verts)}, high_verts={len(high_verts)}, y_stddev={std_y:.6f}"


@test("6 travertine/concrete/fluted: materials have expected nodes")
def test_surface_nodes():
    surface_tests = [
        ('travertine_stone_studio', 'PMS_Surface_Voronoi', 'PMS_Surface_Wave_Bands'),
        ('brushed_concrete_brutalist', 'PMS_Surface_Noise_Stains', 'PMS_Surface_Noise_Brushed'),
        ('fluted_ribbed_wall', 'PMS_Surface_Wave_Fluted', 'PMS_Surface_SeparateXYZ'),
    ]
    for bg_id, *expected_nodes in surface_tests:
        sc, p = built(background=bg_id, floor='matte')
        bg_ob = bpy.data.objects.get('PMS_Background')
        mat = bg_ob.active_material
        nt = mat.node_tree
        for node_name in expected_nodes:
            node = nt.nodes.get(node_name)
            assert node is not None, f"{bg_id}: missing node {node_name}"
        api.remove_all()
    return "all surface nodes present"


@test("7 New floors build on cyclorama and studio360")
def test_new_floors_build():
    new_floors = [
        'wet_asphalt_micro',
        'obsidian_black_glass',
        'frosted_acrylic_matte',
        'rippled_water_pool',
    ]
    backdrops = ['cyclorama_studio_grey', 'studio_360']
    for bg_id in backdrops:
        for floor_id in new_floors:
            sc, p = built(background=bg_id, floor=floor_id)
            floor_ob = bpy.data.objects.get('PMS_Floor')
            assert floor_ob is not None, f"{bg_id} + {floor_id}: no PMS_Floor"
            assert floor_ob.active_material is not None, f"{bg_id} + {floor_id}: no material"
            # Check surface nodes exist
            mat = floor_ob.active_material
            nt = mat.node_tree
            if floor_id == 'wet_asphalt_micro':
                assert nt.nodes.get('PMS_FloorSurface_Noise_Grain')
                assert nt.nodes.get('PMS_FloorSurface_Puddle_Mask')
            elif floor_id == 'obsidian_black_glass':
                assert nt.nodes.get('PMS_FloorSurface_Length')
                assert nt.nodes.get('PMS_FloorSurface_Roughness_Map')
            elif floor_id == 'frosted_acrylic_matte':
                bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
                assert abs(bsdf.inputs['Subsurface Weight'].default_value - 0.35) < 1e-4
                assert abs(bsdf.inputs['Coat Weight'].default_value - 0.3) < 1e-4
            elif floor_id == 'rippled_water_pool':
                assert nt.nodes.get('PMS_FloorSurface_Wave_Rings')
                assert nt.nodes.get('PMS_FloorSurface_Bump_Water')
            api.remove_all()
    return f"{len(new_floors)} floors x {len(backdrops)} backdrops built"


@test("8 obsidian_black_glass & rippled_water_pool: product lights exclude floor (like mirror)")
def test_no_light_reflections():
    for floor_id in ('obsidian_black_glass', 'rippled_water_pool'):
        sc, p = built(background='cyclorama_studio_grey', floor=floor_id)
        coll = bpy.data.collections.get('PMS_Mirror_Floor_Excluded')
        assert coll is not None, f"{floor_id}: NO_FLOOR collection not created"
        # Floor should be in the collection
        floor_coll = core.section_collection(sc, 'floor')
        assert floor_coll.name in [c.name for c in coll.children], f"{floor_id}: floor not in NO_FLOOR"
        # Product lights should exclude the floor
        lights = [o for o in core.section_collection(sc, 'lights').objects if o.type == 'LIGHT']
        for l in lights:
            assert l.light_linking.receiver_collection == coll, f"{floor_id}: light {l.name} not linked to NO_FLOOR"
        api.remove_all()

    # wet_asphalt_micro should NOT exclude
    sc, p = built(background='cyclorama_studio_grey', floor='wet_asphalt_micro')
    coll = bpy.data.collections.get('PMS_Mirror_Floor_Excluded')
    assert coll is None, "wet_asphalt_micro created NO_FLOOR collection"
    api.remove_all()
    return "obsidian/rippled exclude floor, asphalt does not"


@test("9 Rebuild twice: no 'edited by hand' warnings")
def test_rebuild_idempotent():
    for bg_id in ('travertine_stone_studio', 'arch_plinth_pedestal', 'satin_silk_drape'):
        sc, p = built(background=bg_id, floor='matte')
        for _ in range(2):                          # two rebuilds in a row
            res = api.apply('background', bg_id)
            assert not any('edited by hand' in w for w in res.get('warnings', [])), f"{bg_id}: {res.get('warnings')}"
            assert 'background' not in api.state()['modified'], f"{bg_id}: rebuild flagged modified"
        api.remove_all()
    return "rebuild twice clean for all"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS BACKDROPS EXTRA TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)