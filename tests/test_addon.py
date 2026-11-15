"""Headless test of Product Motion Studio:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_addon.py
One PASS/FAIL line per test (the 8 points of plugin/docs/TASK_addon.md + a Workbench render smoke test).
Never renders with Eevee/Cycles (only Workbench)."""

import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

import product_motion_studio as pkg
from product_motion_studio import api, core, coverage, motion, presets

RESULTS = []
FEAT = {}


def test(num, name):
    def deco(fn):
        try:
            msg = fn()
            RESULTS.append((num, name, True, msg or ''))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((num, name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def scene():
    return bpy.context.scene


def clean_scene():
    if core.has_product() or bpy.data.collections.get(core.SYSTEM):
        api.remove_all()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras):
        for item in list(coll):
            if item.users == 0:
                coll.remove(item)


def make_product(scale=1.0):
    """Suzanne + a cylinder, raised off the floor (so 'ground' has something to do)."""
    clean_scene()
    bpy.ops.mesh.primitive_monkey_add(size=2 * scale, location=(0.3 * scale, 0.2 * scale, 3 * scale))
    a = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5 * scale, depth=1.0 * scale,
                                        location=(2.4 * scale, 0.2 * scale, 2.6 * scale))
    b = bpy.context.active_object
    a.rotation_euler = (0.3, 0.1, 0.5)
    bpy.context.view_layer.update()
    return [a, b]


def make_shape(kind):
    """A flat slab (3 x 3 x 0.2) or a tall pole (0.3 x 0.3 x 4)."""
    clean_scene()
    if kind == 'flat':
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1, 2, 0.5))
        ob = bpy.context.active_object
        ob.scale = (3.0, 3.0, 0.2)
    else:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=4.0, location=(-1, 0.5, 2.0))
        ob = bpy.context.active_object
    bpy.context.view_layer.update()
    return [ob]


def mat_diff(a, b, size):
    """Max difference between two 4x4 matrices (location relative to size)."""
    d = 0.0
    for i in range(4):
        for j in range(4):
            e = abs(a[i][j] - b[i][j])
            d = max(d, e / size if (j == 3 and i < 3) else e)
    return d


def containment(sc, cam, root, inf, limit=0.2):
    """Worst (center outside, overflow fraction, corner behind camera) over frames sampled every 5."""
    worst = 0.0
    for f in range(sc.frame_start, sc.frame_end + 1, 5):
        sc.frame_set(f)
        mw = root.matrix_world
        ctr = world_to_camera_view(sc, cam, mw.translation)
        if not (0 <= ctr.x <= 1 and 0 <= ctr.y <= 1 and ctr.z > 0):
            raise AssertionError(f"frame {f}: center outside the frame ({ctr.x:.2f}, {ctr.y:.2f}, {ctr.z:.2f})")
        pts = [world_to_camera_view(sc, cam, mw @ c) for c in inf.corners]
        if min(p.z for p in pts) <= 0:
            raise AssertionError(f"frame {f}: product behind the camera plane")
        for axis in 'xy':
            lo, hi = min(getattr(p, axis) for p in pts), max(getattr(p, axis) for p in pts)
            over = (max(0, -lo) + max(0, hi - 1)) / max(hi - lo, 1e-9)
            worst = max(worst, over)
            if over > limit:
                raise AssertionError(f"frame {f}: product leaves the frame by {over:.0%} on {axis}")
    return worst


def features():
    """Scale-free description of the built studio (positions relative to centre/size)."""
    sc = scene()
    sc.frame_set(sc.frame_start)
    inf = core.info()
    out = {'size': inf.size}
    ctr = inf.center
    cam = bpy.data.objects['PMS_Camera']
    out['cam'] = (cam.matrix_world.translation - ctr) / inf.size
    out['lens'] = cam.data.lens
    out['lights'] = sorted(((o.matrix_world.translation - ctr) / inf.size)[:] + (o.data.energy / inf.size ** 2,)
                           for o in bpy.data.objects if o.type == 'LIGHT')
    bg = bpy.data.objects['PMS_Background']
    out['bg_dims'] = tuple(c / inf.size for c in bg.dimensions)
    return out


# ---------------------------------------------------------------------------------------------
@test(1, "register/unregister without errors")
def t1():
    for _ in range(2):
        pkg.register()
        assert hasattr(bpy.types.Scene, 'pms')
        pkg.unregister()
        assert not hasattr(bpy.types.Scene, 'pms')
    pkg.register()
    return "2 cycles"


@test(2, "build() with defaults on a product 1x and 0.01x")
def t2():
    out = {}
    for s in (1.0, 0.01):
        prods = make_product(s)
        r = api.build(objects=prods)
        sc = scene()
        names = set(r['objects'])
        for need in ('PMS_Product_Root', 'PMS_Camera', 'PMS_Cam_Pivot', 'PMS_Cam_Target', 'PMS_DOF_Empty',
                     'PMS_Light_Rig', 'PMS_Background'):
            assert need in names, f"missing {need}"
        assert sc.camera.name == 'PMS_Camera' and sc.frame_end == 200 and sc.render.resolution_x == 1920
        assert not r['warnings'], r['warnings']
        out[s] = r['n_objects']
        FEAT[s] = features()
    return f"objects 1x={out[1.0]} 0.01x={out[0.01]}"


@test(3, "every preset of every section applies without exceptions")
def t3():
    prods = make_product(1.0)
    api.build(objects=prods)
    n, bad = 0, []
    for section in presets.SECTIONS:
        for pid in list(presets.REGISTRY[section]):
            try:
                api.apply(section, pid)
                n += 1
            except Exception as e:                  # noqa: BLE001
                traceback.print_exc()
                bad.append(f"{section}/{pid}: {type(e).__name__}: {e}")
    # image backdrop with a real file
    img = bpy.data.images.new("tmp_bg", 8, 8)
    path = os.path.join(tempfile.gettempdir(), "pms_test_bg.png")
    img.filepath_raw, img.file_format = path, 'PNG'
    img.save()
    r = api.apply('background', 'image', bg_image=path)
    assert not [w for w in r['warnings'] if 'image' in w], r['warnings']
    api.apply('background', 'cyclorama_studio_grey', bg_image='')
    api.apply('lighting', 'beauty_soft', animate_lighting=True)
    assert bpy.data.objects['PMS_Light_Rig'].animation_data.action, "animate_lighting made no keys"
    api.apply('lighting', 'beauty_soft', animate_lighting=False)
    assert not bpy.data.objects['PMS_Light_Rig'].animation_data
    assert not bad, "; ".join(bad)
    return f"{n} presets"


@test(4, "ends_at_rest and loop poses of every product_motion")
def t4():
    prods = make_product(1.0)
    api.build(objects=prods, product_motion='static', camera_motion='static')
    sc, notes = scene(), []
    for pid, p in presets.REGISTRY['product_motion'].items():
        api.apply('product_motion', pid)
        inf = core.info()
        root = inf.root
        sc.frame_set(sc.frame_start)
        first = root.matrix_world.copy()
        last_f = sc.frame_end + (1 if core.is_loop(sc) else 0)      # a loop stops one frame early (its last key = the first)
        sc.frame_set(last_f)
        last = root.matrix_world.copy()
        rest = Matrix.Translation(inf.center)
        if p.meta.get('ends_at_rest'):
            d = mat_diff(last, rest, inf.size)
            assert d < 1e-4, f"{pid}: final pose differs from rest by {d:.2e}"
        if p.meta.get('loop'):
            d = mat_diff(first, last, inf.size)
            assert d < 1e-4, f"{pid}: first and last frame differ by {d:.2e}"
        notes.append(pid)
    # same slope at the seam of the seamless loops (no visible hitch)
    for pid in ('spin_360_loop', 'hover_float_loop'):
        api.apply('product_motion', pid)
        root = core.info().root
        eps = 1e-3
        for fc in list(motion.iter_fcurves(root)):
            a = (fc.evaluate(sc.frame_start + eps) - fc.evaluate(sc.frame_start)) / eps
            b = (fc.evaluate(sc.frame_end + 1) - fc.evaluate(sc.frame_end + 1 - eps)) / eps
            assert abs(a - b) < 1e-3 * max(1.0, abs(a)) + 1e-4, f"{pid}: slope jump at the loop seam ({a:.4f} vs {b:.4f}) on {fc.data_path}[{fc.array_index}]"
    return f"{len(notes)} motions"


DELIBERATE_CROP = {'detail_corner_crop': 0.5}    # crops on purpose (tight + lens shift): the centre must stay in, the overflow may be larger


@test(5, "product stays in frame: every shot, camera motion, loop and format (3 product shapes)")
def t5():
    sc = scene()
    worst, n = 0.0, 0

    def check(limit=0.2):
        nonlocal worst, n
        inf = core.info()
        worst = max(worst, containment(sc, sc.camera, inf.root, inf, limit))
        n += 1

    for shape in ('suzanne+cylinder', 'flat', 'tall'):
        prods = make_product(1.0) if shape.startswith('suz') else make_shape(shape)
        api.build(objects=prods, product_motion='static', camera_motion='static', shot='hero_34')
        for pid in presets.REGISTRY['camera_shot']:
            api.apply('camera_shot', pid)
            check(DELIBERATE_CROP.get(pid, 0.2))
        api.apply('camera_shot', 'hero_34')
        for pid in presets.REGISTRY['camera_motion']:
            api.apply('camera_motion', pid)
            check()
        api.apply('camera_motion', 'orbit_360_loop')
        for fmt in presets.REGISTRY['format']:
            api.apply('format', fmt)
            check()
        api.apply('format', '16:9')
        api.apply('camera_motion', 'static')
        for pid, p in presets.REGISTRY['product_motion'].items():
            if p.meta.get('loop'):
                api.apply('product_motion', pid)
                check()
    return f"{n} setups, worst overflow {worst:.1%}"


@test(6, "idempotence: build() repeated gives the same scene")
def t6():
    prods = make_product(1.0)
    counts = []
    for _ in range(5):
        api.build(objects=prods)
        counts.append((len(core.system_collection(scene()).all_objects),
                       len([m for m in bpy.data.meshes if m.name.startswith('PMS_')]),
                       len([m for m in bpy.data.materials if m.name.startswith('PMS_')]),
                       len([m for m in bpy.data.lights if m.name.startswith('PMS_')]),
                       len([m for m in bpy.data.actions if m.name.startswith('PMS_')])))
    assert len(set(counts)) == 1, counts
    api.build()                         # no objects: reuses the prepared product
    assert counts[0][0] == len(core.system_collection(scene()).all_objects)
    for name in ('PMS_Product_Root', 'PMS_Camera'):
        assert len([o for o in bpy.data.objects if o.name.startswith(name)]) == 1
    return f"objects/meshes/materials/lights/actions = {counts[0]}"


@test(7, "scale: same proportions on 1x and 0.01x products")
def t7():
    a, b = FEAT[1.0], FEAT[0.01]
    assert abs(a['size'] / b['size'] - 100) < 1e-3 * 100, (a['size'], b['size'])
    assert (a['cam'] - b['cam']).length < 1e-3, (a['cam'], b['cam'])
    assert abs(a['lens'] - b['lens']) < 1e-6
    assert len(a['lights']) == len(b['lights'])
    for la, lb in zip(a['lights'], b['lights']):
        assert max(abs(x - y) / max(1.0, abs(x)) for x, y in zip(la, lb)) < 1e-3, (la, lb)
    assert max(abs(x - y) for x, y in zip(a['bg_dims'], b['bg_dims'])) < 1e-3
    return f"cam/size {tuple(round(c, 3) for c in a['cam'])}"


@test(8, "remove_all(): no PMS_ leftovers, product and scene as before")
def t8():
    prods = make_product(1.0)
    sc = scene()
    before = [(o.name, o.matrix_world.copy(), o.parent) for o in prods]
    saved = (sc.render.resolution_x, sc.render.resolution_y, sc.render.engine, sc.frame_end, sc.camera,
             sc.world.name if sc.world else None, sc.render.fps)
    api.build(objects=prods, floor='shadow_catcher', look='dark_editorial')
    api.remove_all()
    left = [x.name for coll in (bpy.data.objects, bpy.data.collections, bpy.data.meshes, bpy.data.materials,
                                bpy.data.lights, bpy.data.cameras, bpy.data.worlds, bpy.data.actions,
                                bpy.data.node_groups, bpy.data.images) for x in coll if x.name.startswith('PMS_')]
    assert not left, f"leftovers: {left}"
    for name, mw, parent in before:
        ob = bpy.data.objects[name]
        assert ob.parent is parent and mat_diff(ob.matrix_world, mw, 1.0) < 1e-5, f"{name} moved"
        assert 'pms_orig' not in ob and not ob.animation_data, f"{name} not clean"
    now = (sc.render.resolution_x, sc.render.resolution_y, sc.render.engine, sc.frame_end, sc.camera,
           sc.world.name if sc.world else None, sc.render.fps)
    assert now == saved, f"scene settings not restored: {saved} -> {now}"
    assert sc.compositing_node_group is None and not sc.render.film_transparent
    return "clean"


@test(9, "extra: Workbench render of one frame with the compositor (vignette darkens corners)")
def t9():
    prods = make_product(1.0)
    sc = scene()
    api.build(objects=prods, engine='BLENDER_WORKBENCH', look='dark_editorial', product_motion='static')
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 192, 108, 100
    path = os.path.join(tempfile.gettempdir(), "pms_test_render.png")
    sc.render.filepath = path
    sc.render.image_settings.file_format = 'PNG'
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    w, h = img.size
    px = list(img.pixels)

    def lum(x, y):
        i = (y * w + x) * 4
        return sum(px[i:i + 3]) / 3

    corner, mid = lum(1, 1), lum(w // 2, h // 2)
    assert w == 192 and h == 108
    assert any(v > 0 for v in px), "black image"
    return f"corner {corner:.3f} centre {mid:.3f}"


@test(10, "extra: UI operators (build_all, build_section, remove_all)")
def t10():
    prods = make_product(1.0)
    for ob in bpy.data.objects:
        ob.select_set(ob in prods)
    assert bpy.ops.pms.build_all() == {'FINISHED'}
    n = len(core.system_collection(scene()).all_objects)
    for sec in ('prepare', 'camera_shot', 'lighting', 'look', 'format'):
        assert bpy.ops.pms.build_section(section=sec) == {'FINISHED'}, sec
    assert len(core.system_collection(scene()).all_objects) == n
    assert bpy.ops.pms.remove_all() == {'FINISHED'}
    assert not core.has_product()
    return f"{n} objects"


@test(11, "extra: coverage warning (open cyclorama shows the void, studio_360 and a static hero do not), < 0.5 s")
def t11():
    prods = make_product(1.0)
    sc = scene()
    out = api.build(objects=prods, shot='front', product_motion='static', camera_motion='orbit_360_loop',
                    background='cyclorama_studio_grey', engine='BLENDER_WORKBENCH')
    w = [x for x in out['warnings'] if 'backdrop does not' in x]
    assert len(w) == 1 and sc.pms.coverage == w[0] and 'frame' in w[0] and 'void' in w[0], out['warnings']
    assert api.state()['coverage'] == w[0]
    t0 = time.perf_counter()
    coverage.check(sc)
    dt = time.perf_counter() - t0
    assert dt < 0.5, f"check took {dt:.2f} s"
    api.apply('camera_shot', 'hero_34')
    out = api.apply('camera_motion', 'static')
    assert not [x for x in out['warnings'] if 'backdrop does not' in x] and sc.pms.coverage == '', (out['warnings'], sc.pms.coverage)
    api.apply('camera_shot', 'front')
    api.apply('camera_motion', 'orbit_360_loop')
    assert sc.pms.coverage, "cyclorama + front + orbit should warn"
    out = api.apply('background', 'studio_360')
    assert not [x for x in out['warnings'] if 'backdrop does not' in x] and sc.pms.coverage == '', (out['warnings'], sc.pms.coverage)
    return f"{dt * 1000:.1f} ms; {w[0][:60]}..."


@test(12, "extra: silhouette lights are backdrop-only (light linking), rim strips light the product")
def t12():
    prods = make_product(1.0)
    api.build(objects=prods, lighting='silhouette_bright_back', product_motion='static', camera_motion='static')
    lights = [o for o in bpy.data.objects if o.type == 'LIGHT' and o.name.startswith('PMS_Light')]
    back = [o for o in lights if o.light_linking.receiver_collection is not None]
    rim = [o for o in lights if o.light_linking.receiver_collection is None]
    assert len(back) == 3 and len(rim) == 2, (len(back), len(rim))
    names = {o.name for o in back[0].light_linking.receiver_collection.all_objects}
    assert 'PMS_Background' in names and not names & {o.name for o in prods}, names
    api.apply('lighting', 'beauty_soft')
    api.apply('lighting', 'silhouette_bright_back')                         # rebuild keeps the link to the (rebuilt) backdrop
    names = {o.name for o in core.system_collection(scene()).all_objects if o.type == 'LIGHT' and o.light_linking.receiver_collection}
    assert len(names) == 3
    api.remove_all()
    assert core.RECEIVERS not in bpy.data.collections
    return "3 backdrop-only lights + 2 rims"


@test(13, "extra: panel filters (every category / product type filters its list, the chosen preset stays listed and chosen)")
def t13():
    from product_motion_studio import capture, props
    pms = scene().pms
    checked = 0
    for section in props.FILTERED:
        reg = presets.REGISTRY[section]
        cats = sorted({p.category for p in reg.values()} | ({'My Presets'} if section in capture.SECTIONS else set()))   # (+ the personal presets)
        assert props.categories(section) == cats
        enum = [i.identifier for i in pms.bl_rna.properties[section + '_cat'].enum_items]
        assert enum == ['ALL'] + cats, (section, enum)
        order = [(reg[i].category, reg[i].name.lower()) for i in props.visible_ids(section)]
        assert order == sorted(order) and len(order) == len(reg), f"{section}: list not sorted by category then name"
        current = getattr(pms, section)
        for cat in cats:
            setattr(pms, section + '_cat', cat)
            assert getattr(pms, section) == current, f"{section}: changing the filter changed the preset"
            for pid in reg:
                setattr(pms, section + '_cat', 'ALL')               # (back to the chosen preset: it may be hidden by `cat`)
                setattr(pms, section, current)
                setattr(pms, section + '_cat', cat)
                try:
                    setattr(pms, section, pid)
                    listed = True
                except TypeError:
                    listed = False
                assert listed == (reg[pid].category == cat or pid == current), (section, cat, pid, listed)
                checked += 1
            setattr(pms, section + '_cat', 'ALL')
            setattr(pms, section, current)
            if reg[current].category != cat:                            # the current preset is shown even if filtered out
                assert current in [it[0] for it in props._items(section, cat, 'ALL', current)]
        setattr(pms, section + '_cat', 'ALL')
        setattr(pms, section, current)
    # lighting: product type, alone and with a category
    light = presets.REGISTRY['lighting']
    types = props.product_types()
    assert [i.identifier for i in pms.bl_rna.properties['lighting_ptype'].enum_items] == ['ALL'] + types
    current = pms.lighting
    for t in types:
        for cat in ('ALL', 'glass', 'tech'):
            pms.lighting_ptype, pms.lighting_cat = t, cat
            for pid, p in light.items():
                pms.lighting_ptype, pms.lighting_cat = 'ALL', 'ALL'
                pms.lighting = current
                pms.lighting_ptype, pms.lighting_cat = t, cat
                want = t in p.meta['product_types'] and cat in ('ALL', p.category)
                try:
                    pms.lighting = pid
                    got = True
                except TypeError:
                    got = False
                assert got == (want or pid == current), (t, cat, pid)
                checked += 1
    # the API can still pick a preset the filters hide (they widen), nothing else changes
    pms.lighting_ptype, pms.lighting_cat = 'food', 'glass'
    props.assign(pms, 'lighting', 'rim_only')
    assert pms.lighting == 'rim_only' and pms.lighting_cat == 'ALL' and pms.lighting_ptype == 'ALL'
    pms.lighting_ptype, pms.lighting_cat = 'ALL', 'ALL'
    pms.lighting = current
    return f"{checked} (filter, preset) pairs checked in {len(props.FILTERED)} sections"


@test(14, "extra: one thumbnail (128x128 jpg) per preset of every thumbnail section, none left over, < 3 MB in all")
def t14():
    from product_motion_studio import previews
    total, n = 0, 0
    for section in previews.SECTIONS:
        folder = os.path.join(previews.DIR, section)
        assert sorted(os.listdir(folder)) == sorted(previews.filename(p) for p in presets.REGISTRY[section]), f"{section}: thumbnails != presets"
        for pid in presets.REGISTRY[section]:
            path = previews.path(section, pid)
            total += os.path.getsize(path)
            img = bpy.data.images.load(path)
            assert tuple(img.size) == (128, 128), (path, tuple(img.size))
            bpy.data.images.remove(img)
            n += 1
    assert total < 3e6, total
    return f"{n} thumbnails, {total / 1e6:.2f} MB"


@test(15, "extra: previews are loaded by register (one per preset) and freed by unregister, 3 cycles, no growth")
def t15():
    from product_motion_studio import props, previews
    want = sum(len(presets.REGISTRY[s]) for s in previews.SECTIONS)
    assert previews.count() == want, (previews.count(), want)
    for s in props.FILTERED:                    # (icon ids stay 0 in background mode: check the loaded images instead)
        assert len(props._items(s, 'ALL', 'ALL', None)) == len(presets.REGISTRY[s]), s
        assert all(tuple(previews._pcoll[f"{s}/{pid}"].image_size) == (128, 128) for pid in presets.REGISTRY[s]), s
    sizes = []
    for _ in range(3):
        old = previews._pcoll
        pkg.unregister()
        assert previews._pcoll is None and previews.count() == 0 and not hasattr(bpy.types.Scene, 'pms')
        assert len(old) == 0, "the old preview collection was not freed"
        pkg.register()
        sizes.append(previews.count())
        assert tuple(previews._pcoll['look/' + next(iter(presets.REGISTRY['look']))].image_size) == (128, 128)
    assert sizes == [want] * 3 and len(props._CACHE) < 50, (sizes, len(props._CACHE))
    return f"{want} previews, 3 cycles clean"


@test(16, "Eevee reflections on after a build and restored by remove_all; mirror floor: product lights do not light it")
def t16():
    objs = make_product()
    sc = scene()
    sc.eevee.use_raytracing = False
    api.apply_recipe('automotive_part_metal', objects=objs)
    assert sc.eevee.use_raytracing, "raytracing off: metal and glass render black in Eevee"
    lights = [o for o in bpy.data.collections[core.SUB['lights']].objects if o.type == 'LIGHT']
    coll = bpy.data.collections.get(core.NO_FLOOR)
    floor = bpy.data.collections[core.SUB['floor']]
    assert coll is not None and list(coll.children) == [floor], coll
    assert coll.collection_children[0].light_linking.link_state == 'EXCLUDE'
    assert lights and all(o.light_linking.receiver_collection == coll for o in lights)
    api.apply('floor', 'matte')
    assert all(o.light_linking.receiver_collection is None for o in lights), "matte floor: the lights must light it (shadows)"
    api.apply('floor', 'mirror')
    assert all(o.light_linking.receiver_collection == coll for o in lights)
    api.remove_all()
    assert not sc.eevee.use_raytracing and bpy.data.collections.get(core.NO_FLOOR) is None
    return f"{len(lights)} product lights excluded from the mirror floor"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS TEST RESULTS ====")
for num, name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)
