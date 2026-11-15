"""Headless test for autofocus feature in Product Motion Studio.
Run with: /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_autofocus.py"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, motion

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=48)


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
    p = cube(size=2, loc=(0, 0, 1))
    api.build(objects=[p], **{**W, **kw})
    return sc, p


# ---------------------------------------------------------------------------------------------
@test("A1 autofocus: DOF on, keys on every frame, focus_object=None, distance in range")
def test_a1():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    pms = sc.pms
    api.set_live(cam_dof=True, cam_autofocus=True)
    cam = sc.camera
    cd = cam.data
    # Check fcurve exists with keys on every frame
    fc = motion._fcurve(cd, 'dof.focus_distance')
    assert fc is not None, "dof.focus_distance fcurve missing"
    frames = [int(round(kp.co.x)) for kp in fc.keyframe_points]
    expected = list(range(sc.frame_start, sc.frame_end + 1))
    assert frames == expected, f"frames {frames} != expected {expected}"
    # focus_object should be None
    assert cd.dof.focus_object is None, "focus_object should be None when autofocus is on"
    # At middle frame, focus distance should be between (cam->cube_center - cube_size) and cam->cube_center
    sc.frame_set(sc.frame_start + (sc.frame_end - sc.frame_start) // 2)
    bpy.context.view_layer.update()
    cam_loc = cam.matrix_world.translation
    cube_center = core.info(sc).center
    dist_to_center = (cube_center - cam_loc).length
    cube_size = float(core.info(sc).size)
    fd = cd.dof.focus_distance
    assert fd < dist_to_center, f"focus_distance {fd} should be < dist_to_center {dist_to_center}"
    assert fd > dist_to_center - cube_size, f"focus_distance {fd} should be > dist_to_center - cube_size {dist_to_center - cube_size}"
    # pms_autofocus tag
    assert cd.get('pms_autofocus') is True
    return f"fcurve with {len(frames)} keys, focus_object=None, distance in range"


@test("A2 autofocus push_in: focus distance decreases as camera gets closer")
def test_a2():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    api.set_live(cam_dof=True, cam_autofocus=True)
    cam = sc.camera
    cd = cam.data
    fc = motion._fcurve(cd, 'dof.focus_distance')
    # First frame
    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    fd_start = fc.evaluate(sc.frame_start)
    # Last frame
    sc.frame_set(sc.frame_end)
    bpy.context.view_layer.update()
    fd_end = fc.evaluate(sc.frame_end)
    assert fd_start > fd_end, f"focus distance at start {fd_start} should be > at end {fd_end} (camera gets closer)"
    return f"start={fd_start:.3f} end={fd_end:.3f}"


@test("A3 autofocus off: no fcurve, focus_object restored, no pms_autofocus tag")
def test_a3():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    api.set_live(cam_dof=True, cam_autofocus=True)
    # Now turn off
    api.set_live(cam_autofocus=False)
    cam = sc.camera
    cd = cam.data
    fc = motion._fcurve(cd, 'dof.focus_distance')
    assert fc is None, "dof.focus_distance fcurve should be removed when autofocus is off"
    # focus_object should be PMS_DOF_Empty
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    assert cd.dof.focus_object == focus, "focus_object should be PMS_DOF_Empty when autofocus is off"
    # pms_autofocus tag should be gone
    assert 'pms_autofocus' not in cd, "pms_autofocus tag should be deleted"
    return "no fcurve, focus_object restored, tag removed"


@test("A4 autofocus + apply preset: modified empty, apply works, autofocus off after explicit apply")
def test_a4():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    api.set_live(cam_dof=True, cam_autofocus=True)
    # modified should not contain 'camera' (live changes don't mark as modified)
    mod = api.state()['modified']
    assert 'camera' not in mod, f"modified should not contain 'camera', got {mod}"
    # apply a preset explicitly - starts from defaults, so autofocus should be off
    api.apply('camera_shot', 'macro')
    cam = sc.camera
    cd = cam.data
    fc = motion._fcurve(cd, 'dof.focus_distance')
    assert fc is None, "after explicit apply, autofocus should be off (no fcurve)"
    # apply should not raise
    return f"modified={mod}, apply works, autofocus off after apply"


@test("A5 autofocus + camera rebuild (lens change): fcurve recreated with keys on every frame")
def test_a5():
    sc, p = built(shot='hero_34', camera_motion='push_in', product_motion='static')
    api.set_live(cam_dof=True, cam_autofocus=True)
    # Change lens - triggers camera rebuild
    api.set_live(cam_lens=70)
    cam = sc.camera
    cd = cam.data
    fc = motion._fcurve(cd, 'dof.focus_distance')
    assert fc is not None, "dof.focus_distance fcurve should exist after rebuild"
    frames = [int(round(kp.co.x)) for kp in fc.keyframe_points]
    expected = list(range(sc.frame_start, sc.frame_end + 1))
    assert frames == expected, f"frames {frames} != expected {expected}"
    return f"fcurve recreated with {len(frames)} keys after lens change"


@test("A6 autofocus kept through a camera_motion change: baked after the new motion (push_in, rack_focus)")
def test_a6():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    api.set_live(cam_dof=True, cam_autofocus=True)
    api.apply('camera_motion', 'push_in')
    cd = sc.camera.data
    assert sc.pms.cam_autofocus, "autofocus switched off by the camera_motion change"
    fc = motion._fcurve(cd, 'dof.focus_distance')
    assert fc is not None and cd.dof.focus_object is None, "push_in: autofocus keys missing"
    first, last = fc.evaluate(sc.frame_start), fc.evaluate(sc.frame_end)
    assert first > last * 1.02, f"push_in: focus should follow the camera in ({first:.3f} -> {last:.3f})"
    api.apply('camera_motion', 'rack_focus')
    cd = sc.camera.data
    assert cd.dof.focus_object is None, "rack_focus put the focus object back over the autofocus keys"
    assert motion._fcurve(cd, 'dof.focus_distance') is not None, "rack_focus: autofocus keys missing"
    return f"push_in focus {first:.3f} -> {last:.3f}; rack_focus keeps the autofocus"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS AUTOFOCUS TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)