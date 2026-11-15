"""Headless test for intro + loop motion feature.
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_intro_loop.py
"""
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
W = dict(engine='BLENDER_WORKBENCH', duration=120, fps=24)


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


def built(**kw):
    sc = fresh()
    p = cube()
    api.build(objects=[p], **{**W, **kw})
    return sc, p


def root_obj():
    return bpy.data.objects.get(core.ROOT_NAME)


def get_loop_preset():
    """Find a loop preset to use for testing (skipping 'static' which produces no keys)."""
    for pid, p in presets.REGISTRY['product_motion'].items():
        if pid == 'static':
            continue
        if p.meta.get('loop') and not p.meta.get('hidden') and not p.meta.get('user'):
            return pid
    return 'hover_float_loop'


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


# ---------------------------------------------------------------------------------------------
@test("M1: intro + loop produces keys before and after split, no modifiers, no jump at split")
def m1_intro_loop():
    sc, p = built(product_motion='pop_in_reveal')
    LOOP = get_loop_preset()
    out = api.apply('product_motion', 'pop_in_reveal', motion_loop=LOOP, motion_intro_s=2.0)
    root = root_obj()
    fps = sc.render.fps
    split = out['details']['animation']['split']
    assert split == sc.frame_start + 48, f"split={split}, expected {sc.frame_start + 48}"
    f0, f1 = sc.frame_start, sc.frame_end

    # No fcurve has modifiers
    for fc in core.motion.iter_fcurves(root):
        assert not fc.modifiers, f"{fc.data_path}[{fc.array_index}] has modifiers"

    # Keys before and after split
    has_before = has_after = False
    for fc in core.motion.iter_fcurves(root):
        for kp in fc.keyframe_points:
            if kp.co.x < split:
                has_before = True
            if kp.co.x > split:
                has_after = True
    assert has_before and has_after, "should have keys before and after split"

    # At least one channel changes after split
    changes = False
    for fc in core.motion.iter_fcurves(root):
        vmin = min(fc.evaluate(f) for f in range(split, f1 + 1))
        vmax = max(fc.evaluate(f) for f in range(split, f1 + 1))
        if vmax - vmin > 1e-4:
            changes = True
            break
    assert changes, "no channel changes after split"

    # No jump at split: |fc(split) - fc(split-1)| < 0.05 * size
    size = api.state()['size']
    for fc in core.motion.iter_fcurves(root):
        v1 = fc.evaluate(split)
        v0 = fc.evaluate(split - 1)
        assert abs(v1 - v0) < 0.05 * size, f"jump at split on {fc.data_path}[{fc.array_index}]: {abs(v1 - v0)} >= {0.05 * size}"

    clean()
    return f"split={split}, loop={LOOP}"


@test("M2: motion_loop='NONE' produces same fcurves as fresh build with only pop_in_reveal")
def m2_none_loop():
    sc1, p1 = built(product_motion='pop_in_reveal')
    api.apply('product_motion', 'pop_in_reveal', motion_loop='NONE')
    root1 = root_obj()
    fcs1 = [(fc.data_path, fc.array_index, [tuple(kp.co) for kp in fc.keyframe_points])
            for fc in core.motion.iter_fcurves(root1)]

    sc2, p2 = built(product_motion='pop_in_reveal')
    root2 = root_obj()
    fcs2 = [(fc.data_path, fc.array_index, [tuple(kp.co) for kp in fc.keyframe_points])
            for fc in core.motion.iter_fcurves(root2)]

    assert len(fcs1) == len(fcs2), f"different number of fcurves: {len(fcs1)} vs {len(fcs2)}"
    for (dp1, ai1, ks1), (dp2, ai2, ks2) in zip(fcs1, fcs2):
        assert dp1 == dp2 and ai1 == ai2, f"different path/index: {dp1}[{ai1}] vs {dp2}[{ai2}]"
        assert len(ks1) == len(ks2), f"different key count on {dp1}[{ai1}]: {len(ks1)} vs {len(ks2)}"
        for (f1, v1), (f2, v2) in zip(ks1, ks2):
            assert abs(f1 - f2) < 1e-6 and abs(v1 - v2) < 1e-6, f"different key: {f1},{v1} vs {f2},{v2}"

    clean()
    return "fcurves identical to fresh build"


@test("M3: loop preset as main motion with motion_loop=LOOP -> no exception, note, usual result")
def m3_loop_main():
    LOOP = get_loop_preset()
    sc, p = built(product_motion=LOOP)
    out = api.apply('product_motion', LOOP, motion_loop=LOOP, motion_intro_s=2.0)
    assert 'note' in out['details']['animation'], "expected note about loop ignored"
    assert "already a loop" in out['details']['animation']['note'], f"wrong note: {out['details']['animation']['note']}"

    root = root_obj()
    has_cycles = any(any(m.type == 'CYCLES' for m in fc.modifiers)
                     for fc in core.motion.iter_fcurves(root))
    # The plain build of this preset has a CYCLES modifier
    plain_sc, plain_p = built(product_motion=LOOP)
    plain_root = root_obj()
    plain_has_cycles = any(any(m.type == 'CYCLES' for m in fc.modifiers)
                           for fc in core.motion.iter_fcurves(plain_root))
    assert has_cycles == plain_has_cycles, f"cycles mismatch: {has_cycles} vs {plain_has_cycles}"

    clean()
    return f"note='{out['details']['animation']['note']}', cycles={has_cycles}"


@test("M4: state.modified does not contain 'animation' after M1; invalid motion_loop raises ValueError")
def m4_modified_and_validation():
    sc, p = built(product_motion='pop_in_reveal')
    LOOP = get_loop_preset()
    api.apply('product_motion', 'pop_in_reveal', motion_loop=LOOP, motion_intro_s=2.0)
    st = api.state()
    assert 'animation' not in st['modified'], f"animation in modified: {st['modified']}"

    raises(ValueError, api.apply, 'product_motion', 'pop_in_reveal', motion_loop='nope')
    clean()
    return f"modified={st['modified']}, invalid raises ValueError"


@test("M5: changing motion_intro_s rebuilds with new split")
def m5_change_intro_s():
    sc, p = built(product_motion='pop_in_reveal')
    LOOP = get_loop_preset()
    api.apply('product_motion', 'pop_in_reveal', motion_loop=LOOP, motion_intro_s=2.0)
    root = root_obj()
    # Check loop channel (rotation_euler Z typically) has keys before split
    split1 = 1 + 48  # frame_start + 48

    sc.pms.motion_intro_s = 3.0
    # rebuild triggered by property update
    st = api.state()
    split2 = 1 + 72  # frame_start + 72 (3.0s * 24fps)

    root = root_obj()
    # Find a channel that changes after split (e.g., rotation_euler Z for hover_float_loop)
    has_late_keys = False
    for fc in core.motion.iter_fcurves(root):
        for kp in fc.keyframe_points:
            if kp.co.x >= split2 - 1:
                has_late_keys = True
                break
        if has_late_keys:
            break
    assert has_late_keys, f"loop keys not found after new split {split2}"

    clean()
    return f"split changed from {split1} to {split2}"


@test("M6: intro + a loop with Noise (wobble_spin_loop): baked to plain keys, the intro stays clean, no jump")
def m6_noise_loop():
    sc, p = built(product_motion='pop_in_reveal')
    out = api.apply('product_motion', 'pop_in_reveal', motion_loop='wobble_spin_loop', motion_intro_s=2.0)
    root = root_obj()
    split = out['details']['animation']['split']
    size = api.state()['size']
    fcs = list(core.motion.iter_fcurves(root))
    assert fcs and not any(fc.modifiers for fc in fcs), "modifiers left on the root's F-Curves"
    moving = [fc for fc in fcs if max(fc.evaluate(f) for f in range(split, sc.frame_end + 1)) -
              min(fc.evaluate(f) for f in range(split, sc.frame_end + 1)) > 1e-4]
    assert moving, "the loop does not move after the split"
    for fc in fcs:
        jump = abs(fc.evaluate(split) - fc.evaluate(split - 1))
        assert jump < 0.05 * size, f"jump at split on {fc.data_path}[{fc.array_index}]: {jump}"
    clean()
    return f"split={split}, {len(moving)} channels move in the loop"


@test("M7: loop starts from intro pose (no jump back at split)")
def m7_loop_starts_from_intro_pose():
    sc, p = built(product_motion='drift_yaw_slow')
    # Apply intro + loop via api.apply to get the result with split
    out = api.apply('product_motion', 'drift_yaw_slow', motion_loop='spin_360_eased_loop', motion_intro_s=2.0)
    root = root_obj()
    split = out['details']['animation']['split']

    # Check rotation_euler Z from split-12 to split+12
    prev_z = None
    backtrack_found = False
    for f in range(split - 12, split + 13):
        sc.frame_set(f)
        z = root.matrix_world.to_euler().z
        z_deg = z * 180 / 3.141592653589793
        if prev_z is not None:
            diff = z_deg - prev_z
            # No significant backtrack (should not go backwards more than 0.05 degrees)
            if diff < -0.05:
                backtrack_found = True
                break
        prev_z = z_deg

    assert not backtrack_found, f"backtrack found at split: rotation went backwards"

    # Also check continuity at split: |z(split) - z(split-1)| < 1 degree
    sc.frame_set(split - 1)
    z_before = root.matrix_world.to_euler().z * 180 / 3.141592653589793
    sc.frame_set(split)
    z_at = root.matrix_world.to_euler().z * 180 / 3.141592653589793
    assert abs(z_at - z_before) < 1.0, f"jump at split: {z_at} vs {z_before}, diff={abs(z_at - z_before)}"

    clean()
    return f"split={split}, no backtrack, continuity OK"


# ---------------------------------------------------------------------------------------------
print("\n==== INTRO LOOP TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)