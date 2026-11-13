"""Headless test of the product preparation of Product Motion Studio (build_prepare.py, pop_in_reveal):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_prepare.py
One PASS/FAIL line per test, one test per audit bug (B1, B2, B15, B4, B5, B6, B7) + pop_in_reveal.
Never renders with Eevee/Cycles."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
from mathutils import Matrix, Vector

import product_motion_studio as pkg
from product_motion_studio import api, build_prepare, core, presets

pkg.register()
RESULTS = []


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
    for coll in (bpy.data.collections, bpy.data.meshes, bpy.data.curves, bpy.data.lights, bpy.data.cameras,
                 bpy.data.armatures, bpy.data.actions):
        for item in list(coll):
            coll.remove(item)
    scene().frame_set(1)
    return scene()


def cube(name, loc=(0, 0, 0), size=2.0):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def select(*obs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in obs:
        o.select_set(True)


def prepare(objects=None, **kw):
    return build_prepare.build(scene(), objects, **kw)


def root():
    return bpy.data.objects[core.ROOT_NAME]


def snapshot():
    """Everything a failed re-prepare must leave untouched."""
    r = bpy.data.objects.get(core.ROOT_NAME)
    if r is None:
        return None
    kids = {c.name: (c.parent.name, round_m(c.matrix_world), c['pms_orig']['parent'],
                     tuple(round(v, 6) for v in c['pms_orig']['pinv']), round_m(c.matrix_parent_inverse))
            for c in r.children}
    return (round_m(r.matrix_world), [round(v, 6) for v in r['pms_dims']], round(r['pms_size'], 6),
            [round(v, 6) for v in r['pms_center']], kids)


def round_m(m):
    return tuple(round(v, 5) for row in m for v in row)


def world_bounds(obs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = [o.evaluated_get(dg).matrix_world @ Vector(c) for o in obs for c in o.evaluated_get(dg).bound_box]
    return (Vector(min(p[i] for p in pts) for i in range(3)), Vector(max(p[i] for p in pts) for i in range(3)))


def close(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------------------------------------

@test(1, "B1: only geometry becomes product; camera/light/etc. are ignored and reported")
def t1():
    sc = clean_scene()
    a = cube('A', (0, 0, 0))
    bpy.ops.object.camera_add(location=(10, -10, 5))
    cam = bpy.context.active_object
    bpy.ops.object.light_add(type='POINT', location=(3, 3, 3))
    light = bpy.context.active_object
    bpy.ops.object.empty_add(location=(-5, 0, 0))
    lone = bpy.context.active_object
    lone.name = 'LoneEmpty'
    grp = bpy.data.objects.new('Group', None)                       # empty with a geometric child: accepted
    grp.location = (0, 6, 0)
    sc.collection.objects.link(grp)
    child = cube('Child', (0, 6, 0))
    child.parent = grp
    child.matrix_parent_inverse = grp.matrix_world.inverted()
    arm_ob = bpy.data.objects.new('BareArm', bpy.data.armatures.new('BareArm'))   # armature without geometry: ignored
    sc.collection.objects.link(arm_ob)
    arm2 = bpy.data.objects.new('RigArm', bpy.data.armatures.new('RigArm'))       # armature with a mesh child: accepted
    arm2.location = (0, -6, 0)
    sc.collection.objects.link(arm2)
    body = cube('Body', (0, -6, 0))
    body.parent = arm2
    body.matrix_parent_inverse = arm2.matrix_world.inverted()
    bpy.ops.object.text_add(location=(6, 0, 0))
    txt = bpy.context.active_object
    bpy.ops.object.grease_pencil_add(type='STROKE', location=(0, 0, 6))
    gp = bpy.context.active_object
    for o in bpy.data.objects:
        o.select_set(True)                                          # "Select All"
    res = prepare()
    kids = {c.name for c in root().children}
    assert kids == {'A', 'Group', 'RigArm', txt.name, gp.name}, kids
    assert cam.parent is None and light.parent is None and lone.parent is None and arm_ob.parent is None
    w = ' '.join(res['warnings'])
    for n in (cam.name, light.name, 'LoneEmpty', 'BareArm'):
        assert n in w, (n, w)
    assert 'Ignored' in w and 'not geometry' in w, w
    for bad in ([cam], ['LoneEmpty'], [light, arm_ob]):             # nothing valid: error, scene untouched
        before = snapshot()
        try:
            prepare(bad)
        except RuntimeError as e:
            assert 'no product' in str(e), e
        else:
            raise AssertionError("camera/empty/light accepted as product")
        assert snapshot() == before
    return f"products {sorted(kids)}; warning: {res['warnings'][0]}"


@test(2, "B2: the selection re-prepares, empty/equal selection keeps; add_objects adds a piece")
def t2():
    clean_scene()
    a, b = cube('A', (0, 0, 0)), cube('B', (6, 0, 0))
    select(a)
    prepare()
    assert [c.name for c in root().children] == ['A']
    select(b)                                                       # different selection -> new product
    res = prepare()
    assert res['products'] == ['B'] and a.parent is None, res
    assert close(a.matrix_world.translation, (0, 0, 0))             # A released where it was
    select()                                                        # empty selection: keep
    assert prepare()['products'] == ['B']
    select(b)                                                       # same selection: keep (new root, same product)
    assert prepare()['products'] == ['B']
    bc = cube('Bc', (6, 0, 1))                                      # only a deeper part of the product selected: keep
    bc.parent = b
    bc.matrix_parent_inverse = b.matrix_world.inverted()
    select(bc)
    assert prepare()['products'] == ['B']
    # add_objects
    c = cube('C', (0, 0, 9))
    r0 = root()
    size0 = r0['pms_size']
    before = {o.name: round_m(o.matrix_world) for o in (b,)}
    notes = []
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
    scene().collection.objects.link(cam)
    r = build_prepare.add_objects(scene(), [c, cam], warnings=notes)
    assert r.name == core.ROOT_NAME and r['pms_size'] > size0, (r['pms_size'], size0)
    assert c.parent == r and b.parent == r and cam.parent is None
    assert round_m(b.matrix_world) == before['B'], "existing piece moved"
    assert round_m(c.matrix_world) == round_m(Matrix.Translation((0, 0, 9))), "added piece moved"
    mn, mx = world_bounds([b, c])
    assert close(r.location, (mn + mx) / 2) and close(r['pms_center'], (mn + mx) / 2), (r.location, (mn + mx) / 2)
    assert close(r['pms_dims'], mx - mn) and abs(r['pms_size'] - (mx - mn).length) < 1e-3
    assert any('Cam' in n for n in notes), notes
    core.info()                                                     # still a valid product
    size1 = r['pms_size']
    api.remove_all()
    assert c.parent is None and close(c.matrix_world.translation, (0, 0, 9))     # given back untouched
    try:
        build_prepare.add_objects(scene(), [c])
    except RuntimeError:
        pass
    else:
        raise AssertionError("add_objects without product")
    return f"size {size0:.3f} -> {size1:.3f}"


@test(3, "B15: a failed re-prepare leaves the prepared product and the scene as they were")
def t3():
    sc = clean_scene()
    a, b = cube('A', (0, 0, 2)), cube('B', (4, 0, 2))
    prepare([a, b], ground=True)
    snap = snapshot()
    saved_keys = set(sc.keys())
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    dot = bpy.data.objects.new('Dot', bpy.data.meshes.new('Dot'))   # a single vertex: zero size, found AFTER the bounds
    dot.data.from_pydata([(5, 5, 5)], [], [])
    sc.collection.objects.link(dot)
    hidden = cube('Hid', (9, 9, 9))
    hidden.hide_viewport = True
    for bad in (['NoSuchObject'], [a, 'NoSuchObject'], [cam], [dot], [hidden]):
        try:
            prepare(bad)
        except RuntimeError as e:
            msg = str(e)
        else:
            raise AssertionError(f"{bad} accepted")
        assert snapshot() == snap, f"scene changed after the failed prepare of {bad}: {msg}"
        assert all(c.parent == root() for c in root().children)
    # first prepare that fails does not leave the scene snapshot behind
    api.remove_all()
    assert 'pms_saved' not in sc
    try:
        prepare([dot])
    except RuntimeError:
        pass
    assert 'pms_saved' not in sc and core.ROOT_NAME not in bpy.data.objects and 'pms_orig' not in a
    return "scene identical after 5 failures"


@test(4, "B4: hidden objects are not in the bounds (warning) but still follow the product")
def t4():
    notes = []
    for kind in ('hide_viewport', 'hide_set', 'hide_render', 'col_exclude', 'col_hidden'):
        sc = clean_scene()
        a = cube('A', (0, 0, 0))
        b = cube('B', (50, 0, 0))
        if kind == 'hide_viewport':
            b.hide_viewport = True
        elif kind == 'hide_set':
            b.hide_set(True)
        elif kind == 'hide_render':
            b.hide_render = True
        else:
            col = bpy.data.collections.new('Hid')
            sc.collection.children.link(col)
            for k in list(b.users_collection):
                k.objects.unlink(b)
            col.objects.link(b)
            lc = bpy.context.view_layer.layer_collection.children['Hid']
            if kind == 'col_exclude':
                lc.exclude = True
            else:
                lc.hide_viewport = True
        bpy.context.view_layer.update()
        res = prepare([a, b])
        assert close(res['dims'], (2, 2, 2)), (kind, res['dims'])
        assert any('hidden object' in w for w in res['warnings']), (kind, res['warnings'])
        assert b.parent == root() and a.parent == root(), kind                # both move with the product
        notes.append(kind)
    sc = clean_scene()                                                         # nothing hidden: no warning
    res = prepare([cube('A'), cube('B', (4, 0, 0))])
    assert not any('hidden object' in w for w in res['warnings'])
    return ', '.join(notes)


@test(5, "B5: an already animated product is framed over its whole motion; frame restored")
def t5():
    sc = clean_scene()
    a = cube('A', (0, 0, 0))
    a.location.x = 0
    a.keyframe_insert('location', frame=1)
    a.location.x = 10
    a.keyframe_insert('location', frame=40)
    sc.frame_set(7)
    res = prepare([a], ground=False)
    assert close(res['dims'], (12, 2, 2)), res['dims']
    assert close(res['center'], (5, 0, 0)), res['center']
    assert any('its own animation' in w for w in res['warnings']), res['warnings']
    assert sc.frame_current == 7, sc.frame_current
    # animated parent (the child is the product)
    sc = clean_scene()
    par = bpy.data.objects.new('Par', None)
    sc.collection.objects.link(par)
    par.location.z = 0
    par.keyframe_insert('location', frame=1)
    par.location.z = 20
    par.keyframe_insert('location', frame=200)                  # long range: sampled, at most 24 evaluations
    ch = cube('Ch', (0, 0, 0))
    ch.parent = par
    sc.frame_set(1)
    res = prepare([ch], ground=False)
    assert close(res['dims'], (2, 2, 22), 1e-2), res['dims']
    assert any('its own animation' in w for w in res['warnings'])
    assert len(build_prepare._sample_frames(1, 200)) <= 24
    # static product: no warning
    sc = clean_scene()
    res = prepare([cube('A')])
    assert not any('animazione' in w for w in res['warnings'])
    return "dims 12x2x2 and 2x2x22"


def evaluated_points(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        pts = [ev.matrix_world @ v.co for v in me.vertices]
    finally:
        ev.to_mesh_clear()
    return Vector(min(p[i] for p in pts) for i in range(3)), Vector(max(p[i] for p in pts) for i in range(3))


@test(6, "B6: text/curves use their evaluated geometry (extrude, bevel)")
def t6():
    sc = clean_scene()
    bpy.ops.object.text_add(location=(0, 0, 0))
    txt = bpy.context.active_object
    txt.data.body = "Hi"
    txt.data.extrude = 0.4
    bpy.ops.curve.primitive_bezier_curve_add(location=(10, 0, 0))
    cv = bpy.context.active_object
    cv.data.bevel_depth = 0.3
    cv.data.extrude = 0.2
    bpy.context.view_layer.update()
    for ob in (txt, cv):
        mn, mx = evaluated_points(ob)
        res = prepare([ob], ground=False)
        got_mn = Vector(res['center']) - Vector(res['dims']) / 2
        got_mx = Vector(res['center']) + Vector(res['dims']) / 2
        assert close(got_mn, mn, 1e-3) and close(got_mx, mx, 1e-3), (ob.type, tuple(got_mn), tuple(mn), tuple(got_mx), tuple(mx))
    res = prepare([txt], ground=False)
    assert abs(res['dims'][2] - 0.8) < 1e-3, res['dims']           # extrude 0.4 both ways (the plain bbox gave 0)
    return f"text dims {tuple(round(v, 3) for v in res['dims'])}"


@test(7, "B7: a collection instance (Empty) counts with the geometry of its collection, nested too")
def t7():
    sc = clean_scene()
    part = bpy.data.collections.new('Part')                         # not linked to the scene: only instanced
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    pc = bpy.context.active_object
    for k in list(pc.users_collection):
        k.objects.unlink(pc)
    part.objects.link(pc)
    inst = bpy.data.objects.new('Inst', None)
    inst.instance_type, inst.instance_collection = 'COLLECTION', part
    inst.location, inst.scale = (20, 0, 0), (2, 2, 2)
    sc.collection.objects.link(inst)
    res = prepare([inst], ground=False)
    assert close(res['dims'], (4, 4, 4)) and close(res['center'], (20, 0, 0)), (res['dims'], res['center'])
    # nested: collection Outer holds an instance of Part moved by (0, 5, 0)
    clean_scene()
    part = bpy.data.collections.new('Part')
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    pc = bpy.context.active_object
    for k in list(pc.users_collection):
        k.objects.unlink(pc)
    part.objects.link(pc)
    outer = bpy.data.collections.new('Outer')
    e2 = bpy.data.objects.new('E2', None)
    e2.instance_type, e2.instance_collection, e2.location = 'COLLECTION', part, (0, 5, 0)
    outer.objects.link(e2)
    e3 = bpy.data.objects.new('E3', None)
    e3.instance_type, e3.instance_collection, e3.location = 'COLLECTION', outer, (50, 0, 0)
    sc = scene()
    sc.collection.objects.link(e3)
    res = prepare([e3], ground=False)
    assert close(res['dims'], (2, 2, 2)) and close(res['center'], (50, 5, 0)), (res['dims'], res['center'])
    # selecting such an Empty is accepted as a product; an Empty without children/instance is not
    plain = bpy.data.objects.new('Plain', None)
    sc.collection.objects.link(plain)
    assert build_prepare._resolve(sc, [e3, plain])[0] == [e3]
    return "dims 4x4x4 and nested centre (50, 5, 0)"


@test(8, "pop_in_reveal: the base stays on the floor while scaling, ends at rest")
def t8():
    sc = clean_scene()
    a = cube('A', (0.3, 0.2, 3), 2.0)
    b = cube('B', (2.4, 0.2, 2.6), 1.0)
    api.build(objects=[a, b], product_motion='pop_in_reveal', camera_motion='static')
    inf = core.info()
    r = inf.root
    low = 1e9
    for f in range(sc.frame_start, sc.frame_end + 1):
        sc.frame_set(f)
        low = min(low, min((r.matrix_world @ c).z for c in inf.corners))
    assert low > -1e-4 * inf.size, f"sinks to z={low:.4f} (base is at 0)"
    sc.frame_set(sc.frame_end)
    d = max(abs(r.matrix_world[i][j] - Matrix.Translation(inf.center)[i][j]) for i in range(4) for j in range(4))
    assert d < 1e-4, d
    sc.frame_set(sc.frame_start)
    assert max(r.scale) < 1e-6
    return f"lowest base z {low:.2e}"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS PREPARE TEST RESULTS ====")
for num, name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)
