"""Test for new camera shot presets with roll, ortho, shift fields.

/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_shots_extra.py
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
import numpy as np
from math import pi, radians
from bpy_extras.object_utils import world_to_camera_view

import product_motion_studio as pkg
from product_motion_studio import api, core, presets

RESULTS = []

pkg.register()


def test(num, name):
    def deco(fn):
        try:
            bad, info = fn()
            msg = info + (f"  | {len(bad)} violations: " + "; ".join(bad[:5]) if bad else '')
            RESULTS.append((num, name, not bad, msg, len(bad)))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((num, name, False, f"{type(e).__name__}: {e}", 1))
        return fn
    return deco


def make_box():
    """Create a 0.3 x 0.15 x 0.6 m box."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    if core.has_product() or bpy.data.collections.get(core.SYSTEM):
        api.remove_all()
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.scale = (0.3, 0.15, 0.6)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    return [ob]


def project_vertices(sc, cam, root, inf):
    """Project all 8 box corners to camera view (u, v, z). Returns arrays of u, v."""
    mw = root.matrix_world
    pts = [world_to_camera_view(sc, cam, mw @ c) for c in inf.corners]
    u = np.array([p.x for p in pts])
    v = np.array([p.y for p in pts])
    z = np.array([p.z for p in pts])
    return u, v, z


def tightness(u, v, pad):
    """m = max(|2u-1|, |2v-1|) over vertices. Expected m = 1 - pad."""
    m = np.maximum(np.abs(2 * u - 1), np.abs(2 * v - 1)).max()
    return m


@test(1, "All 5 new presets build without errors")
def t1():
    bad = []
    make_box()
    for shot_id in ('packshot_tele_85mm', 'isometric_catalogue', 'dutch_tilt_dynamic', 'detail_corner_crop', 'flatlay_angled_45'):
        try:
            api.build(objects=make_box(), product_motion='static', camera_motion='static',
                      shot=shot_id, duration=96, engine='BLENDER_WORKBENCH')
        except Exception as e:
            bad.append(f"{shot_id}: {type(e).__name__}: {e}")
    return bad, f"Built {5 - len(bad)}/5 presets"


@test(2, "dutch_tilt_dynamic: roll=18 deg, tightness check")
def t2():
    bad = []
    make_box()
    api.build(objects=make_box(), product_motion='static', camera_motion='static',
              shot='dutch_tilt_dynamic', duration=96, engine='BLENDER_WORKBENCH')
    sc = bpy.context.scene
    cam = bpy.data.objects['PMS_Camera']
    root = bpy.data.objects[core.ROOT_NAME]
    inf = core.info()
    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    u, v, z = project_vertices(sc, cam, root, inf)
    # Check roll
    roll_y = cam.delta_rotation_euler.y
    if abs(roll_y - radians(18)) > 1e-6:
        bad.append(f"delta_rotation_euler.y = {roll_y:.6f}, expected {radians(18):.6f}")
    # Check tightness: m = max(|2u-1|, |2v-1|) should be ~ 1 - 0.18 = 0.82
    m = tightness(u, v, 0.18)
    if abs(m - 0.82) >= 0.03:
        bad.append(f"tightness m = {m:.3f}, expected ~0.82 (tol 0.03)")
    return bad, f"roll={roll_y:.6f}, m={m:.3f}"


@test(3, "isometric_catalogue: ortho camera, tightness with padding 0.15")
def t3():
    bad = []
    make_box()
    api.build(objects=make_box(), product_motion='static', camera_motion='static',
              shot='isometric_catalogue', duration=96, engine='BLENDER_WORKBENCH')
    sc = bpy.context.scene
    cam = bpy.data.objects['PMS_Camera']
    root = bpy.data.objects[core.ROOT_NAME]
    inf = core.info()
    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    # Check ortho type
    if cam.data.type != 'ORTHO':
        bad.append(f"camera type = {cam.data.type}, expected ORTHO")
    u, v, z = project_vertices(sc, cam, root, inf)
    m = tightness(u, v, 0.15)
    if abs(m - 0.85) >= 0.03:
        bad.append(f"tightness m = {m:.3f}, expected ~0.85 (tol 0.03)")
    return bad, f"type={cam.data.type}, m={m:.3f}"


@test(4, "packshot_tele_85mm and flatlay_angled_45: tightness with their padding")
def t4():
    bad = []
    shots = [('packshot_tele_85mm', 0.15), ('flatlay_angled_45', 0.2)]
    for shot_id, pad in shots:
        make_box()
        api.build(objects=make_box(), product_motion='static', camera_motion='static',
                  shot=shot_id, duration=96, engine='BLENDER_WORKBENCH')
        sc = bpy.context.scene
        cam = bpy.data.objects['PMS_Camera']
        root = bpy.data.objects[core.ROOT_NAME]
        inf = core.info()
        sc.frame_set(sc.frame_start)
        bpy.context.view_layer.update()
        u, v, z = project_vertices(sc, cam, root, inf)
        m = tightness(u, v, pad)
        expected = 1 - pad
        if abs(m - expected) >= 0.03:
            bad.append(f"{shot_id}: m = {m:.3f}, expected ~{expected:.2f} (tol 0.03)")
    return bad, f"Checked {len(shots)} shots"


@test(5, "detail_corner_crop: shift_x=0.16, target projects to u=0.34, v=0.5")
def t5():
    bad = []
    make_box()
    api.build(objects=make_box(), product_motion='static', camera_motion='static',
              shot='detail_corner_crop', duration=96, engine='BLENDER_WORKBENCH')
    sc = bpy.context.scene
    cam = bpy.data.objects['PMS_Camera']
    root = bpy.data.objects[core.ROOT_NAME]
    target = bpy.data.objects['PMS_Cam_Target']
    inf = core.info()
    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    # Check shift_x
    if abs(cam.data.shift_x - 0.16) > 1e-6:
        bad.append(f"shift_x = {cam.data.shift_x:.6f}, expected 0.16")
    # Project target (the point the camera looks at)
    mw = target.matrix_world
    tu, tv, tz = world_to_camera_view(sc, cam, mw.translation)
    expected_u = 0.5 - 0.16
    if abs(tu - expected_u) >= 0.02:
        bad.append(f"target u = {tu:.3f}, expected {expected_u:.2f} (tol 0.02)")
    if abs(tv - 0.5) >= 0.02:
        bad.append(f"target v = {tv:.3f}, expected 0.50 (tol 0.02)")
    return bad, f"shift_x={cam.data.shift_x:.3f}, target=({tu:.3f}, {tv:.3f})"


@test(6, "hero_34 reverts: PERSP, zero delta_rotation_euler, zero shift")
def t6():
    bad = []
    make_box()
    api.build(objects=make_box(), product_motion='static', camera_motion='static',
              shot='hero_34', duration=96, engine='BLENDER_WORKBENCH')
    sc = bpy.context.scene
    cam = bpy.data.objects['PMS_Camera']
    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    if cam.data.type != 'PERSP':
        bad.append(f"camera type = {cam.data.type}, expected PERSP")
    if abs(cam.delta_rotation_euler.x) > 1e-6 or abs(cam.delta_rotation_euler.y) > 1e-6 or abs(cam.delta_rotation_euler.z) > 1e-6:
        bad.append(f"delta_rotation_euler = ({cam.delta_rotation_euler.x:.6f}, {cam.delta_rotation_euler.y:.6f}, {cam.delta_rotation_euler.z:.6f}), expected (0,0,0)")
    if abs(cam.data.shift_x) > 1e-6 or abs(cam.data.shift_y) > 1e-6:
        bad.append(f"shift = ({cam.data.shift_x:.6f}, {cam.data.shift_y:.6f}), expected (0,0)")
    return bad, f"type={cam.data.type}, delta_rot=({cam.delta_rotation_euler.x:.3f},{cam.delta_rotation_euler.y:.3f},{cam.delta_rotation_euler.z:.3f}), shift=({cam.data.shift_x:.3f},{cam.data.shift_y:.3f})"


@test(7, "coverage check runs without exceptions for isometric_catalogue and detail_corner_crop")
def t7():
    bad = []
    from product_motion_studio import coverage
    for shot_id in ('isometric_catalogue', 'detail_corner_crop'):
        make_box()
        api.build(objects=make_box(), product_motion='static', camera_motion='static',
                  shot=shot_id, duration=96, engine='BLENDER_WORKBENCH')
        try:
            result = coverage.check(bpy.context.scene)
            if not isinstance(result, list):
                bad.append(f"{shot_id}: coverage.check returned {type(result)}, expected list")
        except Exception as e:
            bad.append(f"{shot_id}: {type(e).__name__}: {e}")
    return bad, f"Coverage check on 2 shots"


if __name__ == '__main__':
    # Set format to 16:9 for all tests
    sc = bpy.context.scene
    sc.render.resolution_x = 1920
    sc.render.resolution_y = 1080
    sc.render.resolution_percentage = 100
    # Run tests
    t1()
    t2()
    t3()
    t4()
    t5()
    t6()
    t7()
    # Print results
    print("\n==== PMS SHOTS EXTRA RESULTS ====")
    for num, name, ok, msg, n in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
    fails = [r for r in RESULTS if not r[2]]
    print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed, {sum(r[4] for r in RESULTS if not r[2])} violations ====")
    sys.exit(1 if fails else 0)