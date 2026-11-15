"""Headless test for exploded_z_reveal preset.
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_explode.py
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
from mathutils import Matrix, Vector

import product_motion_studio as pkg
from product_motion_studio import api, core, presets
from product_motion_studio import motion as m_motion

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=96, fps=24)


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


def box(name, loc=(0, 0, 1), size=(2, 2, 2)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = size
    bpy.context.view_layer.update()
    return ob


def built(objects=None, **kw):
    sc = fresh()
    if objects is None:
        body = box('Body', (0, 0, 0.1), (0.1, 0.1, 0.2))
        cap = box('Cap', (0, 0, 0.2 + 0.025), (0.06, 0.06, 0.05))
        objects = [body, cap]
    api.build(objects=objects, **{**W, **kw})
    return sc, objects


def root_obj():
    return bpy.data.objects.get(core.ROOT_NAME)


def close(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


# ---------------------------------------------------------------------------------------------
@test("E1: exploded_z_reveal - Cap has pms_explode and delta_location[2] curve, max ~ 0.22 * size")
def e1_exploded_basic():
    sc, objs = built()
    out = api.apply('product_motion', 'exploded_z_reveal')
    root = root_obj()
    cap = None
    body = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap = ch
        elif 'Body' in ch.name:
            body = ch
    assert cap is not None and body is not None

    assert cap.get('pms_explode'), "Cap should have pms_explode"
    assert not body.get('pms_explode'), "Body should NOT have pms_explode"

    # Cap has delta_location[2] animation
    fc_cap = None
    for fc in m_motion.iter_fcurves(cap):
        if fc.data_path == 'delta_location' and fc.array_index == 2:
            fc_cap = fc
            break
    assert fc_cap is not None, "Cap should have delta_location[2] fcurve"

    # Max value ~ 0.22 * size
    size = api.state()['size']
    max_z = max(fc_cap.evaluate(f) for f in range(sc.frame_start, sc.frame_end + 1))
    expected = 0.22 * size
    assert abs(max_z - expected) / expected <= 0.05, f"Cap max_z={max_z:.4f}, expected ~{expected:.4f} (5% tol)"

    # Body has no animation
    fc_body = None
    for fc in m_motion.iter_fcurves(body):
        if fc.data_path == 'delta_location' and fc.array_index == 2:
            fc_body = fc
            break
    assert fc_body is None, "Body should NOT have delta_location[2] fcurve"

    # At f1, cap curve is 0
    assert abs(fc_cap.evaluate(sc.frame_end)) < 1e-4, f"Cap delta_location[2] at f1 should be 0, got {fc_cap.evaluate(sc.frame_end)}"

    clean()
    return f"max_z={max_z:.4f} (expected ~{expected:.4f})"


@test("E2: Camera frames the exploded Cap at max separation")
def e2_camera_framing():
    sc = fresh()
    body = box('Body', (0, 0, 0.1), (0.1, 0.1, 0.2))
    cap = box('Cap', (0, 0, 0.2 + 0.025), (0.06, 0.06, 0.05))
    api.build(objects=[body, cap], product_motion='exploded_z_reveal', camera_motion='static', **W)
    root = root_obj()
    cap = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap = ch
            break
    assert cap is not None

    # Find frame of max separation
    fc_cap = None
    for fc in m_motion.iter_fcurves(cap):
        if fc.data_path == 'delta_location' and fc.array_index == 2:
            fc_cap = fc
            break
    max_f = sc.frame_start
    max_z = -1.0
    for f in range(sc.frame_start, sc.frame_end + 1):
        z = fc_cap.evaluate(f)
        if z > max_z:
            max_z = z
            max_f = f

    sc.frame_set(max_f)
    from bpy_extras.object_utils import world_to_camera_view
    dg = bpy.context.evaluated_depsgraph_get()
    ev = cap.evaluated_get(dg)
    for c in ev.bound_box:
        v = world_to_camera_view(sc, sc.camera, ev.matrix_world @ Vector(c))
        assert v.z > 0 and v.x >= 0 and v.x <= 1 and v.y >= 0 and v.y <= 1, \
            f"Cap corner {c} out of frame: {v}"

    clean()
    return f"max separation at frame {max_f}, all Cap corners in frame"


@test("E3: Back to static - Cap has no pms_explode, no animation_data, delta_location.z == 0")
def e3_back_to_static():
    sc, objs = built()
    api.apply('product_motion', 'exploded_z_reveal')
    api.apply('product_motion', 'static')
    root = root_obj()
    cap = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap = ch
            break
    assert cap is not None

    assert not cap.get('pms_explode'), "Cap should not have pms_explode after static"
    assert cap.animation_data is None or cap.animation_data.action is None, \
        "Cap should have no animation_data after static"
    assert abs(cap.delta_location.z) < 1e-6, f"Cap delta_location.z should be 0, got {cap.delta_location.z}"

    clean()
    return "Cap clean after static"


@test("E4: api.remove_all - Cap and Body have no PMS actions, delta_location.z == 0, original parents")
def e4_remove_all():
    sc = fresh()
    body = box('Body', (0, 0, 0.1), (0.1, 0.1, 0.2))
    cap = box('Cap', (0, 0, 0.2 + 0.025), (0.06, 0.06, 0.05))
    # Capture original parents BEFORE build
    original_parents = {body.name: body.parent, cap.name: cap.parent}
    api.build(objects=[body, cap], product_motion='exploded_z_reveal', camera_motion='static', **W)
    objs = [body, cap]
    api.apply('product_motion', 'exploded_z_reveal')
    api.remove_all()

    for ob in objs:
        assert ob.parent == original_parents[ob.name], f"{ob.name} parent not restored"
        assert abs(ob.delta_location.z) < 1e-6, f"{ob.name} delta_location.z not 0"
        # Check no PMS actions remain
        for fc in m_motion.iter_fcurves(ob):
            if fc.data_path == 'delta_location' and fc.array_index == 2:
                raise AssertionError(f"{ob.name} still has delta_location[2] fcurve after remove_all")

    clean()
    return "All objects restored after remove_all"


@test("E5: Single object product - fallback, root moves, note present")
def e5_single_object():
    sc = fresh()
    single = box('Single', (0, 0, 1), (1, 1, 1))
    api.build(objects=[single], **W)
    out = api.apply('product_motion', 'exploded_z_reveal')
    root = root_obj()

    # Root should have animation (fallback)
    has_fc = any(fc.keyframe_points for fc in m_motion.iter_fcurves(root))
    assert has_fc, "Root should have animation in fallback"

    # Note should be in output (under details/animation)
    anim = out['details']['animation']
    assert 'note' in anim, f"Output should have note about fallback, got {anim}"
    assert 'needs 2+ parts' in anim['note'], f"Wrong note: {anim['note']}"

    clean()
    return f"fallback note: {anim['note']}"


@test("E6: Cap with user animation before prepare - fallback used, user animation preserved")
def e6_user_animation_preserved():
    sc = fresh()
    body = box('Body', (0, 0, 0.1), (0.1, 0.1, 0.2))
    cap = box('Cap', (0, 0, 0.2 + 0.025), (0.06, 0.06, 0.05))

    # Add user animation to Cap BEFORE prepare (only on Z)
    sc.frame_set(1)
    cap.location = (0, 0, 0.3)
    cap.keyframe_insert('location', index=2, frame=1)
    sc.frame_set(10)
    cap.location = (0, 0, 0.5)
    cap.keyframe_insert('location', index=2, frame=10)
    # Capture user keys on the ORIGINAL cap object (only Z)
    user_keys = [(kp.co.x, kp.co.y) for fc in m_motion.iter_fcurves(cap)
                 if fc.data_path == 'location' and fc.array_index == 2 for kp in fc.keyframe_points]

    api.build(objects=[body, cap], **W)
    out = api.apply('product_motion', 'exploded_z_reveal')

    # Should use fallback (note present)
    anim = out['details']['animation']
    assert 'note' in anim and 'needs 2+ parts' in anim['note'], f"Expected fallback note, got {anim.get('note')}"

    # User animation on Cap should be preserved
    root = root_obj()
    cap_obj = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap_obj = ch
            break
    assert cap_obj is not None

    # Check user keys still there (on location, not delta_location)
    user_fc = None
    for fc in m_motion.iter_fcurves(cap_obj):
        if fc.data_path == 'location' and fc.array_index == 2:
            user_fc = fc
            break
    assert user_fc is not None, "User location animation should remain"
    after_keys = [(kp.co.x, kp.co.y) for kp in user_fc.keyframe_points]
    assert len(after_keys) == len(user_keys), f"Key count changed: {len(user_keys)} -> {len(after_keys)}"
    for (f1, v1), (f2, v2) in zip(user_keys, after_keys):
        assert abs(f1 - f2) < 1e-6 and abs(v1 - v2) < 1e-6, f"Key mismatch: {f1},{v1} vs {f2},{v2}"

    # After static, user animation still there
    api.apply('product_motion', 'static')
    cap_obj = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap_obj = ch
            break
    user_fc = None
    for fc in m_motion.iter_fcurves(cap_obj):
        if fc.data_path == 'location' and fc.array_index == 2:
            user_fc = fc
            break
    assert user_fc is not None, "User animation should remain after static"
    after_keys2 = [(kp.co.x, kp.co.y) for kp in user_fc.keyframe_points]
    assert len(after_keys2) == len(user_keys)

    # After remove_all, user animation still there
    api.remove_all()
    cap_obj = bpy.data.objects.get('Cap')
    user_fc = None
    for fc in m_motion.iter_fcurves(cap_obj):
        if fc.data_path == 'location' and fc.array_index == 2:
            user_fc = fc
            break
    assert user_fc is not None, "User animation should remain after remove_all"
    after_keys3 = [(kp.co.x, kp.co.y) for kp in user_fc.keyframe_points]
    assert len(after_keys3) == len(user_keys)

    clean()
    return f"user keys preserved: {len(user_keys)} before/after static/remove_all"


@test("E7: Intro + loop with exploded_z_reveal - no error")
def e7_intro_loop():
    sc, objs = built()
    LOOP = 'hover_float_loop'  # a known loop preset
    out = api.build(product_motion='exploded_z_reveal', camera_motion='static',
                    motion_loop=LOOP, motion_intro_s=2.0, **W)
    root = root_obj()

    # Should have keys before and after split
    split = out['details']['animation']['split']
    has_before = has_after = False
    for fc in m_motion.iter_fcurves(root):
        for kp in fc.keyframe_points:
            if kp.co.x < split:
                has_before = True
            if kp.co.x > split:
                has_after = True
    assert has_before and has_after, "Should have keys before and after split"

    # Cap should have pms_explode and animation
    cap = None
    for ch in root.children:
        if 'Cap' in ch.name:
            cap = ch
            break
    assert cap.get('pms_explode'), "Cap should have pms_explode in intro+loop"

    clean()
    return f"intro+loop works, split={split}"


# ---------------------------------------------------------------------------------------------
print("\n==== EXPLODE TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)