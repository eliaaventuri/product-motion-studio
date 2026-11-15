"""Headless test of Product Motion Studio render packs:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_batch.py
One test per point. Real tiny render only in B6."""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, batch, core

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=60)


def test(name):
    def deco(fn):
        try:
            msg = fn()
            RESULTS.append((name, True, msg or ''))
        except Exception as e:
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


def built(scale=1.0, **kw):
    sc = fresh()
    p = cube(size=2 * scale, loc=(0, 0, scale))
    api.build(objects=[p], **{**W, **kw})
    return sc, p


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def close(a, b, tol=1e-4):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def cam_pos():
    cam = bpy.data.objects.get('PMS_Camera')
    if cam:
        return tuple(cam.matrix_world.translation)
    return None


# ---------------------------------------------------------------------------------------------
@test("B1 angles: 5 shots, camera back, lens/frame/filepath restored")
def test_angles():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    pms = sc.pms
    api.set_live(cam_lens=80)

    # record state before
    shot_before = pms.camera_shot
    motion_before = pms.camera_motion
    cam_mat_before = [tuple(row) for row in sc.camera.matrix_world]
    lens_before = sc.camera.data.lens
    frame_before = sc.frame_current
    filepath_before = sc.render.filepath

    res = api.render_pack('angles', render=False)
    assert len(res['jobs']) == 5, f"expected 5 jobs, got {len(res['jobs'])}"
    assert [j['name'] for j in res['jobs']] == list(batch.ANGLES)

    # camera positions pairwise farther than 1e-3
    positions = [j['camera'] for j in res['jobs']]
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            dx = positions[i][0] - positions[j][0]
            dy = positions[i][1] - positions[j][1]
            dz = positions[i][2] - positions[j][2]
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            assert dist > 1e-3, f"positions {i} and {j} too close: {dist}"

    # after: restored
    assert pms.camera_shot == shot_before
    assert pms.camera_motion == motion_before
    assert close([tuple(row) for row in sc.camera.matrix_world], cam_mat_before, 1e-4)
    assert abs(sc.camera.data.lens - lens_before) < 1e-3
    assert sc.frame_current == frame_before
    assert sc.render.filepath == filepath_before
    return "ok"


@test("B2 formats: 3 formats, resolutions correct, format/restored")
def test_formats():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    pms = sc.pms

    res_before = (sc.render.resolution_x, sc.render.resolution_y)
    fmt_before = pms.format

    res = api.render_pack('formats', render=False)
    assert len(res['jobs']) == 3
    assert [j['resolution'] for j in res['jobs']] == [(1920, 1080), (1080, 1080), (1080, 1920)]

    # after: restored
    assert (sc.render.resolution_x, sc.render.resolution_y) == res_before
    assert pms.format == fmt_before
    return "ok"


@test("B3 variants: collection with V1, V2; visibility correct; products restored")
def test_variants():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    pms = sc.pms

    # create variant collection
    bpy.ops.mesh.primitive_cube_add(size=2, location=(5, 0, 1))
    v1 = bpy.context.active_object
    v1.name = 'V1'
    bpy.ops.mesh.primitive_cube_add(size=2, location=(10, 0, 1))
    v2 = bpy.context.active_object
    v2.name = 'V2'

    coll = bpy.data.collections.new('Variants')
    sc.collection.children.link(coll)
    coll.objects.link(v1)
    coll.objects.link(v2)

    res = api.render_pack('variants', variants='Variants', render=False)
    assert [j['name'] for j in res['jobs']] == ['V1', 'V2']
    assert res['jobs'][0]['visible'] == ['V1']
    assert res['jobs'][1]['visible'] == ['V2']

    # after: products restored, all three objects visible
    state = api.state()
    assert state['products'] == ['P']
    for name in ('P', 'V1', 'V2'):
        ob = bpy.data.objects.get(name)
        assert ob is not None
        assert ob.hide_render is False
    return "ok"


@test("B4 hand edit: moving camera by hand raises; force=True works")
def test_hand_edit():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')

    # move camera by hand
    cam = bpy.data.objects['PMS_Camera']
    cam.location.x += 1
    bpy.context.view_layer.update()

    # should raise RuntimeError
    try:
        api.render_pack('angles', render=False)
        raise AssertionError("expected RuntimeError for hand edit")
    except RuntimeError as e:
        assert 'edited by hand' in str(e).lower()

    # with force=True should work
    res = api.render_pack('angles', render=False, force=True)
    assert len(res['jobs']) == 5
    return "ok"


@test("B5 errors: unknown kind, missing variants collection, empty collection")
def test_errors():
    # unknown kind
    sc, p = built()
    try:
        api.render_pack('foo')
        raise AssertionError("expected ValueError for unknown kind")
    except ValueError as e:
        assert 'unknown pack' in str(e)

    # missing variants
    try:
        api.render_pack('variants', variants=None)
        raise AssertionError("expected ValueError for missing variants")
    except ValueError as e:
        assert 'choose the collection' in str(e)

    # empty collection
    coll = bpy.data.collections.new('EmptyVariants')
    sc.collection.children.link(coll)
    try:
        api.render_pack('variants', variants='EmptyVariants')
        raise AssertionError("expected ValueError for empty collection")
    except ValueError as e:
        assert 'has no objects' in str(e)

    return "ok"


@test("B6 real tiny render: Eevee 1 sample, 5%, front and side files exist")
def test_real_render():
    tmp = tempfile.mkdtemp()
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    api.set_render(engine='BLENDER_EEVEE', samples=1, percent=5)

    res = api.render_pack('angles', shots=['front', 'side'], path=tmp)

    pack_dir = os.path.join(tmp, 'pack_angles')
    front_path = os.path.join(pack_dir, 'front.png')
    side_path = os.path.join(pack_dir, 'side.png')
    assert os.path.isfile(front_path), f"missing {front_path}"
    assert os.path.isfile(side_path), f"missing {side_path}"
    return f"ok ({front_path}, {side_path})"



@test("B7 passes: multilayer EXR with graded image and Cryptomatte, output put back")
def test_passes_exr():
    tmp = tempfile.mkdtemp()
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    api.set_render(engine='BLENDER_EEVEE', samples=1, percent=5, mode='still')
    before = (sc.render.image_settings.media_type, sc.render.image_settings.file_format, sc.render.filepath)
    with core.quiet():
        sc.pms.render_passes = True
    api.render_pack('formats', formats=['1:1'], path=tmp)
    exr = os.path.join(tmp, 'pack_formats', '1x1.exr')
    assert os.path.isfile(exr), f"missing {exr}"
    head = open(exr, 'rb').read(20000)
    for layer in (b'Composite.Combined', b'CryptoObject', b'Depth', b'Mist'):
        assert layer in head, f"{layer!r} not in the EXR"
    after = (sc.render.image_settings.media_type, sc.render.image_settings.file_format, sc.render.filepath)
    assert after == before, f"output not put back: {after} != {before}"
    return f"ok ({exr})"



@test("B8 variant_roots: a variant parented outside the collection (e.g. to the PMS root during a pack) is still a root")
def test_variant_roots_parent():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    coll = bpy.data.collections.new('VR'); sc.collection.children.link(coll)
    a = cube('A', loc=(4, 0, 1)); b = cube('B', loc=(4, 0, 3))
    for ob in (a, b):
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        coll.objects.link(ob)
    b.parent = a                                    # child inside the collection: not a root
    a.parent = p                                    # parent outside the collection: still a root
    names = [o.name for o in batch.variant_roots(coll)]
    assert names == ['A'], names
    return f"ok {names}"



@test("B9 variants from a collection hidden from renders / excluded: rendered during the pack, hidden again after")
def test_variants_hidden_collection():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    coll = bpy.data.collections.new('HV'); sc.collection.children.link(coll)
    v = cube('HV1', loc=(5, 0, 1))
    for c in list(v.users_collection):
        c.objects.unlink(v)
    coll.objects.link(v)
    coll.hide_render = True
    lc = batch.layer_entries(sc, coll)[0]
    lc.exclude = True
    seen = []
    orig_setup = batch.Pack.setup

    def spy(self, i):
        job = orig_setup(self, i)
        seen.append((coll.hide_render, lc.exclude, api.state()['products']))
        return job
    batch.Pack.setup = spy
    try:
        res = api.render_pack('variants', variants='HV', render=False)
    finally:
        batch.Pack.setup = orig_setup
    assert seen == [(False, False, ['HV1'])], seen
    assert coll.hide_render is True and batch.layer_entries(sc, coll)[0].exclude is True, "collection not hidden again"
    assert api.state()['products'] == ['P'], api.state()['products']
    orphan = bpy.data.collections.new('NotInScene')
    try:
        api.render_pack('variants', variants=orphan, render=False)
        raise AssertionError("a collection outside the scene was accepted")
    except ValueError:
        pass
    return "ok"


# ---------------------------------------------------------------------------------------------
if __name__ == '__main__':
    print("Running render pack tests...")
    print("")

    for name, ok, msg in RESULTS:
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name} {msg}")

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print("")
    print(f"Total: {len(RESULTS)}  PASS: {len(RESULTS) - fails}  FAIL: {fails}")
    sys.exit(1 if fails else 0)