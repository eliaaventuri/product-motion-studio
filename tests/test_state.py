"""Headless test of the state/safety/API/UI fixes of Product Motion Studio (audit 2026-10-03):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_state.py
One test per bug (B3, B8..B14, B16, loop, short durations, more scenes, add_objects); each one fails with the old code.
Never renders."""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, motion, presets, ui

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


def lights():
    return sorted((o for o in bpy.data.objects if o.type == 'LIGHT' and o.name.startswith('PMS_')), key=lambda o: o.name)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def ptrs(names):
    return {n: bpy.data.objects[n].as_pointer() for n in names}


# ---------------------------------------------------------------------------------------------
@test("B3 world and compositor of the user survive build + save + reopen + remove_all")
def b3():
    sc = fresh()
    p = cube()
    world = bpy.data.worlds.new('MyHDRI')
    sc.world = world
    comp = bpy.data.node_groups.new('MyComp', 'CompositorNodeTree')
    sc.compositing_node_group = comp
    api.build(objects=[p], **W)
    assert sc.world.name == 'PMS_World' and sc.compositing_node_group.name == 'PMS_Compositing'
    assert world.use_fake_user and comp.use_fake_user, "no fake user while PMS is active"
    path = os.path.join(tempfile.gettempdir(), 'pms_state_b3.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    assert 'MyHDRI' in bpy.data.worlds and 'MyComp' in bpy.data.node_groups, "lost on save"
    api.remove_all()
    assert sc.world and sc.world.name == 'MyHDRI' and sc.compositing_node_group.name == 'MyComp'
    assert not sc.world.use_fake_user and not sc.compositing_node_group.use_fake_user, "fake user left behind"
    return "world + compositor back, fake user removed"


@test("B3b fake user not touched when the user had one already")
def b3b():
    sc = fresh()
    p = cube()
    world = bpy.data.worlds.new('Keep')
    world.use_fake_user = True
    sc.world = world
    api.build(objects=[p], **W)
    api.remove_all()
    assert sc.world.name == 'Keep' and sc.world.use_fake_user
    return "kept"


@test("B8 operators are undoable and report errors instead of tracebacks")
def b8():
    sc = fresh()
    for cls in ui._classes:
        if hasattr(cls, 'bl_idname') and cls.bl_idname.startswith('pms.'):
            assert 'UNDO' in cls.bl_options and 'REGISTER' in cls.bl_options, cls.bl_idname
    msg = raises(RuntimeError, bpy.ops.pms.build_section, section='camera_shot')
    assert 'no product' in msg and 'Traceback' not in msg, msg
    msg = raises(RuntimeError, bpy.ops.pms.build_section, section='foo')
    assert msg.startswith("Error: unknown section 'foo'") and "KeyError" not in msg, msg
    sc, p = built()
    orig = api._RUN['lighting']
    api._RUN['lighting'] = lambda scene: 1 / 0
    try:
        msg = raises(RuntimeError, bpy.ops.pms.build_section, section='lighting')
    finally:
        api._RUN['lighting'] = orig
    assert 'division by zero' in msg, msg
    return "all 4 operators undoable; errors: " + msg.strip()[:40]


@test("B9 user lights are hidden at build, given back by remove_all")
def b9():
    sc = fresh()
    p = cube()
    bpy.ops.object.light_add(type='POINT', location=(3, 3, 3))
    a = bpy.context.active_object
    bpy.ops.object.light_add(type='SUN')
    b = bpy.context.active_object
    b.hide_viewport = b.hide_render = True                   # one the user had hidden already
    out = api.build(objects=[p], **W)
    assert a.hide_render and a.hide_viewport, "user light still on"
    assert "Hid 1 scene light" in out['warnings'], out['warnings']
    api.build(**W)                                           # second build: no new warning, nothing changes
    api.remove_all()
    assert not a.hide_render and not a.hide_viewport and 'pms_hidden' not in a
    assert b.hide_viewport and b.hide_render, "state of the already hidden light changed"
    api.build(objects=[p], isolate_lights=False, **W)
    assert not a.hide_render
    return "hidden, warned, restored; isolate_lights=False leaves them"


@test("B10 first build starts from the scene (fps, start frame, engine); remove_all restores frame_current")
def b10():
    sc = fresh()
    sc.render.fps, sc.frame_start, sc.frame_end, sc.frame_current = 30, 10, 90, 40
    sc.render.engine = 'BLENDER_WORKBENCH'
    p = cube()
    assert sc.pms.engine == 'KEEP'
    api.build(objects=[p], duration=100)
    assert sc.pms.fps == 30 and sc.pms.frame_start == 10, (sc.pms.fps, sc.pms.frame_start)
    assert sc.render.engine == 'BLENDER_WORKBENCH' and sc.render.fps == 30
    assert (sc.frame_start, sc.frame_end) == (10, 109), (sc.frame_start, sc.frame_end)
    assert core.info().root.animation_data.action, "no animation"
    api.remove_all()
    assert (sc.frame_start, sc.frame_end, sc.frame_current, sc.render.fps) == (10, 90, 40, 30)
    sc.render.fps = 25                                       # a new build starts from the scene again
    api.build(objects=[p], duration=30)
    assert sc.pms.fps == 25
    return "fps 30, start 10, engine kept, frame_current 40"


@test("B11 hand edits are not overwritten by dependents (lights, lens, DOF empty, keys, nodes)")
def b11a():
    sc, p = built()
    ls = lights()
    ls[0].location.x += 3
    sc.camera.data.lens = 120
    before = ptrs([o.name for o in ls] + ['PMS_Camera'])
    out = api.apply('product_motion', 'spin_360_loop')                # camera is a dependent: kept
    assert sc.camera.data.lens == 120 and ptrs(list(before)) == before, "camera rebuilt"
    assert any('Camera edited by hand' in w for w in out['warnings']), out['warnings']
    assert not any('Luci' in w for w in out['warnings'])             # lights are not a dependent of product_motion any more
    assert abs(ls[0].location.x - ls[0].location.x) == 0 and bpy.data.objects[ls[0].name].as_pointer() == before[ls[0].name]
    out = api.apply('look', 'dark_editorial', duration=100)           # duration used to rebuild the lights too
    assert ptrs(list(before)) == before and sc.frame_end in (99, 100)
    assert any('Camera edited by hand' in w for w in out['warnings']), out['warnings']
    return out['warnings'][0][:60]


@test("B11b explicit rebuild: apply() refuses without force and says why, force=True overwrites")
def b11b():
    sc, p = built()
    ls = lights()
    x0 = ls[0].location.x
    ls[0].location.x += 3
    out = api.apply('lighting', 'rim_only')
    assert out['warnings'] == ["Lights edited by hand: not rebuilt (use Build Lighting to overwrite)"], out['warnings']
    assert api.state()['lighting'] == 'beauty_soft' and abs(bpy.data.objects[ls[0].name].location.x - (x0 + 3)) < 1e-6
    assert api.state()['modified'] == ['lighting']
    out = api.apply('lighting', 'rim_only', force=True)
    assert not out['warnings'] and api.state()['lighting'] == 'rim_only' and api.state()['modified'] == []
    # camera: lens / f-stop / DOF empty / keys
    sc.camera.data.dof.aperture_fstop = 1.2
    out = api.apply('camera_shot', 'front')
    assert any('Camera edited' in w for w in out['warnings']) and api.state()['camera_shot'] == 'hero_34'
    api.apply('camera_shot', 'front', force=True)
    bpy.data.objects['PMS_DOF_Empty'].location.z += 1
    assert api.state()['modified'] == ['camera']
    api.apply('camera_shot', 'hero_34', force=True)
    root = core.info().root
    root.keyframe_insert('scale', frame=5)                           # extra key by hand
    assert api.state()['modified'] == ['animation']
    out = api.apply('product_motion', 'spin_90')
    assert any('Product motion edited' in w for w in out['warnings']) and api.state()['product_motion'] != 'spin_90'
    api.apply('product_motion', 'spin_90', force=True)
    ng = sc.compositing_node_group
    ng.nodes.new('CompositorNodeBlur')                               # a node by hand
    assert api.state()['modified'] == ['compositing']
    out = api.apply('look', 'dark_editorial')
    assert any('Look edited' in w for w in out['warnings'])
    api.apply('look', 'dark_editorial', force=True)
    return "lights, lens/f-stop, DOF empty, keys, nodes"


@test("B11c no false positives: lots of applies leave nothing marked as edited; rigs follow the shot only if untouched")
def b11c():
    sc, p = built()
    for sec in ('camera_shot', 'camera_motion', 'background', 'floor', 'format', 'look', 'lighting', 'product_motion'):
        for pid in list(presets.REGISTRY[sec])[:6]:
            api.apply(sec, pid)
            assert api.state()['modified'] == [], (sec, pid, api.state()['modified'])
    api.apply('lighting', 'beauty_soft')
    api.apply('camera_shot', 'front')
    ls = lights()
    ls[0].location.y += 2
    rot = tuple(bpy.data.objects['PMS_Light_Rig'].rotation_euler)
    api.apply('camera_shot', 'side')
    assert tuple(bpy.data.objects['PMS_Light_Rig'].rotation_euler) == rot, "hand-edited rig was re-oriented"
    api.apply('lighting', 'beauty_soft', force=True)
    assert api.state()['modified'] == []
    return "clean after 48 applies"


@test("B11d propagation: camera_shot / duration leave lights, background and floor alone")
def b11d():
    sc, p = built()
    names = [o.name for o in core.system_collection(sc).all_objects if o.name != 'PMS_Product_Root']
    before = ptrs(names)
    api.apply('camera_shot', 'front')
    api.apply('look', 'dark_editorial', duration=80)
    after = ptrs(names)
    same = {n for n in names if before[n] == after[n]}
    for n in names:
        if n.startswith('PMS_Light') or n in ('PMS_Background', 'PMS_Floor'):
            assert n in same, f"{n} rebuilt"
    api.apply('lighting', 'beauty_soft', animate_lighting=True)
    lp = ptrs([o.name for o in lights()])
    api.apply('look', 'dark_editorial', duration=90)               # sweep follows the duration: lights rebuilt
    assert ptrs(list(lp)) != lp
    return "only what depends on the change is rebuilt"


@test("B11e UI operators: Build without confirmation never overwrites, invoke asks first")
def b11e():
    sc, p = built()
    for ob in bpy.data.objects:
        ob.select_set(ob is p)
    ls = lights()
    ls[0].location.x += 3
    x = ls[0].location.x
    assert hasattr(ui.PMS_OT_build_section, 'invoke') and hasattr(ui.PMS_OT_build_all, 'invoke')
    text = api.modified_text(api.steps_for('lighting'))
    assert text == "You edited by hand: lights. Overwrite your edits?", text
    assert bpy.ops.pms.build_section(section='lighting') == {'FINISHED'}     # exec: like the api, kept (warning)
    assert abs(bpy.data.objects[ls[0].name].location.x - x) < 1e-6
    assert api.modified_text(api.steps_for('camera_shot')) is None
    # headless Blender never calls invoke(): drive it with a stand-in for the operator and the window manager
    asked = []

    class WM:
        def invoke_confirm(self, op, event, title=None, message=None, confirm_text=None, icon='NONE'):
            asked.append(message)
            return {'RUNNING_MODAL'}

    class Ctx:
        scene, window_manager = sc, WM()

    class Op:
        force = False
        steps = ui.PMS_OT_build_section.steps
        execute = lambda self, context: {'FINISHED'}                   # noqa: E731

    op = Op()
    op.section = 'lighting'
    assert ui.PMS_OT_build_section.invoke(op, Ctx, None) == {'RUNNING_MODAL'} and op.force and asked == [text], asked
    op = Op()
    op.section = 'camera_shot'                                              # nothing edited there: runs at once
    assert ui.PMS_OT_build_section.invoke(op, Ctx, None) == {'FINISHED'} and not op.force and len(asked) == 1
    op = Op()
    op.section, op.force = 'lighting', True                                 # what execute does after the user said yes
    assert api.run(api.steps_for('lighting'), None, sc, force=True)['warnings'] == []
    assert api.state()['modified'] == [] and abs(lights()[0].location.x - x) > 1
    return text


@test("B12 duration / fps / engine apply at once, without recursion; before the first build they only set the value")
def b12():
    sc = fresh()
    p = cube()
    sc.pms.duration = 90
    assert not core.has_product() and not bpy.data.collections.get(core.SYSTEM)
    api.build(objects=[p], engine='BLENDER_WORKBENCH')
    calls = []
    orig = api._RUN['format']
    api._RUN['format'] = lambda scene: (calls.append(1), orig(scene))[1]
    try:
        sc.pms.duration = 120
        assert sc.frame_end == 120 and len(calls) == 1, (sc.frame_end, calls)
        keys = [k.co.x for fc in motion.iter_fcurves(core.info().root) for k in fc.keyframe_points]
        assert max(keys) <= 120 and max(keys) > 100, max(keys)
        sc.pms.fps = 30
        assert sc.render.fps == 30
        sc.pms.engine = 'BLENDER_EEVEE'
        assert sc.render.engine == 'BLENDER_EEVEE'
        calls.clear()
        api.apply('camera_shot', 'front', duration=64, fps=25)       # api: one run, no callback storm
        assert sc.frame_end == 64 and sc.render.fps == 25 and len(calls) == 1, calls
    finally:
        api._RUN['format'] = orig
    return "frame_end follows the panel"


@test("B13 unknown section, unknown overrides, boolean strings, bg_image that is not an image")
def b13():
    sc, p = built()
    assert 'foo' in raises(ValueError, api.apply, 'foo', 'x')
    assert 'foo' in raises(ValueError, presets.get, 'foo', 'x')
    assert 'foo' in raises(ValueError, api.list_presets, 'foo')
    out = api.apply('product_motion', 'spin_360_loop', turn=2)
    assert "Unknown override 'turn' (did you mean 'turns'?)" in out['warnings'], out['warnings']
    assert 'turn' not in api.state()['overrides'].get('product_motion', {})
    out = api.apply('product_motion', 'spin_360_loop', turns=2)
    assert not [w for w in out['warnings'] if 'Override' in w] and api.state()['overrides']['product_motion'] == {'turns': 2}
    out = api.apply('camera_shot', 'hero_34', lenss=50)
    assert "Unknown override 'lenss' (did you mean 'lens'?)" in out['warnings'], out['warnings']
    api.apply('product_motion', 'spin_360_loop', ease='False')
    assert api.state()['overrides']['product_motion']['ease'] is False
    api.apply('lighting', 'beauty_soft', animate_lighting='False')
    assert api.state()['animate_lighting'] is False
    api.apply('lighting', 'beauty_soft', animate_lighting='true')
    assert api.state()['animate_lighting'] is True
    raises(ValueError, api.apply, 'lighting', 'beauty_soft', animate_lighting='maybe')
    txt = os.path.join(tempfile.gettempdir(), 'pms_not_an_image.png')
    with open(txt, 'w') as f:
        f.write('this is not a picture')
    before = api.state()
    msg = raises(ValueError, api.apply, 'background', 'image', bg_image=txt)
    assert 'bg_image' in msg and 'readable image' in msg, msg
    assert api.state() == before, "state changed by a refused override"
    return msg[:60]


@test("B14 overrides are validated first; a failing step puts everything back")
def b14():
    sc, p = built()
    before = api.state()
    cam = bpy.data.objects['PMS_Camera'].as_pointer()
    for sec, pid, kw in (('camera_shot', 'hero_34', dict(lens=0)), ('camera_shot', 'hero_34', dict(lens=-5)),
                         ('camera_shot', 'hero_34', dict(padding=1.5)), ('camera_shot', 'hero_34', dict(dof=-1)),
                         ('camera_shot', 'hero_34', dict(lens='abc')),
                         ('product_motion', 'static', dict(duration=5)), ('product_motion', 'static', dict(duration=20.5)),
                         ('product_motion', 'static', dict(fps=0)), ('product_motion', 'static', dict(engine='NOPE')),
                         ('look', 'dark_editorial', dict(duration=float('nan')))):
        raises(ValueError, api.apply, sec, pid, **kw)
        assert api.state() == before, (sec, kw)
    assert bpy.data.objects['PMS_Camera'].as_pointer() == cam, "camera rebuilt by a refused override"
    raises(ValueError, api.build, objects=[p], duration=5)
    raises(ValueError, api.build, objects=[p], fps=0)
    assert api.state() == before
    # a step that crashes half way: props, overrides and scene come back
    orig = api._RUN['camera']

    def crash(scene):
        if core.settings(scene).camera_shot == 'front':               # only with the new settings: the rollback works
            core.clear_section(scene, 'camera')                       # what the real step does first
            raise RuntimeError("boom")
        return orig(scene)
    api._RUN['camera'] = crash
    try:
        raises(RuntimeError, api.apply, 'camera_shot', 'front', padding=0.3)
    finally:
        api._RUN['camera'] = orig
    after = api.state()
    assert after['camera_shot'] == 'hero_34' and after['overrides'] == before['overrides'], after
    assert 'PMS_Camera' in bpy.data.objects and sc.camera is bpy.data.objects['PMS_Camera'], "camera lost"
    assert after['modified'] == [] and after['frame_range'] == before['frame_range']
    # first build that fails: nothing is left
    sc = fresh()
    q = cube()
    api._RUN['lighting'] = lambda scene: 1 / 0
    try:
        raises(ZeroDivisionError, api.build, objects=[q], **W)
    finally:
        api._RUN['lighting'] = api.build_lighting.build
    assert not core.has_product() and not bpy.data.collections.get(core.SYSTEM) and 'pms_saved' not in sc
    assert q.parent is None and sc.pms.overrides == '{}'
    return "10 refused overrides, crash rolled back, failed first build removed"


@test("B16 core.settings() never registers the add-on as a side effect")
def b16():
    pkg.unregister()
    try:
        msg = raises(RuntimeError, core.settings, bpy.context.scene)
        assert msg == "Product Motion Studio is not enabled: enable it in Preferences > Add-ons", msg
        assert not hasattr(bpy.types.Scene, 'pms')
        raises(RuntimeError, api.build)
        assert not hasattr(bpy.types.Scene, 'pms'), "api call registered the classes"
    finally:
        pkg.register()
    return msg[:40]


@test("loop: frame_end = f1 - 1 when the result loops, documented in the result")
def loop():
    sc = fresh()
    p = cube()
    out = api.build(objects=[p], product_motion='spin_360_loop', camera_motion='static', **{**W, 'duration': 100})
    assert sc.frame_end == 99 and any('Loop' in n for n in out['notes']), (sc.frame_end, out['notes'])
    last = max(k.co.x for fc in motion.iter_fcurves(core.info().root) for k in fc.keyframe_points)
    assert last == 100, last
    out = api.apply('camera_motion', 'orbit_360_loop')
    assert sc.frame_end == 99
    out = api.apply('camera_motion', 'push_in')                       # camera does not loop: whole range
    assert sc.frame_end == 100 and not out['notes']
    out = api.apply('camera_motion', 'static')
    api.apply('product_motion', 'luxury_drift')
    assert sc.frame_end == 100
    api.apply('product_motion', 'static')
    assert sc.frame_end == 99
    return "99 (loop) / 100"


@test("short durations: no keys past the end of the range for any product / camera motion")
def short():
    sc, p = built(camera_motion='static', product_motion='static')
    bad, squeezed = [], 0
    for dur in (12, 20):
        for sec in ('product_motion', 'camera_motion'):
            for pid in presets.REGISTRY[sec]:
                out = api.apply(sec, pid, duration=dur)
                squeezed += bool(out['notes'] and any('Short duration' in n for n in out['notes']))
                f0, f1 = core.frame_range(sc.pms)
                for ob in core.system_collection(sc).all_objects:
                    for idb in (ob, ob.data):
                        for fc in (motion.iter_fcurves(idb) if idb is not None and hasattr(idb, 'animation_data') else ()):
                            if any(k.co.x > f1 + 1e-6 or k.co.x < f0 - 1e-6 for k in fc.keyframe_points):
                                bad.append((dur, pid, fc.data_path))
    assert not bad, bad[:3]
    assert not squeezed, f"{squeezed} presets still need the squeeze safety net (_fit_range)"
    return "no preset needs the squeeze safety net at 12 / 20 frames"


@test("image backplate edited by hand: the camera rebuild keeps it in place and parented to the new pivot")
def plate():
    sc = fresh()
    path = os.path.join(tempfile.gettempdir(), 'pms_plate_test.png')
    img = bpy.data.images.new('pms_plate_test', 8, 8)
    img.filepath_raw, img.file_format = path, 'PNG'
    img.save()
    bpy.data.images.remove(img)
    api.build(objects=[cube()], **W, background='image', bg_image=path, floor='none')
    plate = bpy.data.objects['PMS_Background']
    assert plate.parent and plate.parent.name == 'PMS_Cam_Pivot'
    plate.location.z += 0.2                                          # edited by hand: protected, not rebuilt
    f0 = core.frame_range(sc.pms)[0]
    sc.frame_set(f0)
    world = plate.matrix_world.copy()
    out = api.apply('camera_shot', 'front')
    plate = bpy.data.objects['PMS_Background']
    assert any('Backdrop edited by hand' in w for w in out['warnings']), out['warnings']
    assert plate.parent is not None and plate.parent.name == 'PMS_Cam_Pivot', plate.parent
    sc.frame_set(f0)
    err = max(abs(a - b) for ra, rb in zip(plate.matrix_world, world) for a, b in zip(ra, rb))
    assert err < 1e-4, f"plate moved in the world by {err}"
    return f"parent kept, world error {err:.1e}"


@test("more scenes: a second scene cannot build while the first holds PMS")
def scenes():
    sc, p = built()
    b = bpy.data.scenes.new('B')
    q = cube('Q')
    b.collection.objects.link(q)
    bpy.context.window.scene = b
    try:
        msg = raises(RuntimeError, api.build, objects=[q], **W)
        assert msg == "PMS is already used in scene 'Scene': remove it there or work in that scene", msg
        raises(RuntimeError, api.remove_all)
        assert 'PMS_Camera' in sc.objects and sc.camera.name == 'PMS_Camera'
    finally:
        bpy.context.window.scene = sc
    api.remove_all()
    bpy.context.window.scene = b
    api.build(objects=[q], **W)
    assert 'PMS_Camera' in b.objects and 'PMS_Camera' not in sc.objects
    bpy.context.window.scene = sc
    return msg[:50]


@test("add_objects: API and operator exist and add to the prepared product")
def add():
    sc, p = built()
    extra = cube('Extra', (4, 0, 1))
    assert hasattr(ui, 'PMS_OT_add_objects') and hasattr(api, 'add_objects')
    api.add_objects([extra])
    assert extra.parent is core.info().root and 'Extra' in api.state()['products']
    e2 = cube('Extra2', (-4, 0, 1))
    for ob in bpy.data.objects:
        ob.select_set(ob is e2)
    assert bpy.ops.pms.add_objects() == {'FINISHED'}
    assert e2.parent is core.info().root
    assert api.state()['modified'] == []
    return "2 objects added"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS STATE TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)
