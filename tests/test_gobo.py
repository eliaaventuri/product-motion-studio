"""Headless test of gobo panels on background lights.
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_gobo.py
"""

import os
import sys
import traceback
import tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
from mathutils import Vector

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


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def luminance(pixels):
    """Pixels: flat array [r,g,b,r,g,b,...] -> luminance array."""
    arr = np.array(pixels, dtype=np.float32)
    if len(arr) == 0:
        return np.array([], dtype=np.float32)
    arr = arr.reshape(-1, 3)
    return 0.2126 * arr[:, 0] + 0.7152 * arr[:, 1] + 0.0722 * arr[:, 2]


# ---------------------------------------------------------------------------------------------
@test("T1 6 new presets build; 4 gobo presets make PMS_Gobo_0 under the rig, in bg_lights, visibility, centre at 'at'")
def test_presets_build():
    new_presets = [
        'venetian_blinds_gobo', 'botanical_leaf_gobo',
        'window_sunbeam_slash', 'water_caustics_wash',
        'horizon_neon_bar', 'split_duotone_cross'
    ]
    gobo_presets = ['venetian_blinds_gobo', 'botanical_leaf_gobo', 'window_sunbeam_slash', 'water_caustics_wash']

    for pid in new_presets:
        sc, p = built(background_light=pid, background='cyclorama_studio_grey')
        # Check rig exists
        rig = bpy.data.objects.get('PMS_BgLight_Rig')
        assert rig is not None, f"{pid}: rig missing"

        if pid in gobo_presets:
            # Check gobo object exists
            gobo = bpy.data.objects.get('PMS_Gobo_0')
            assert gobo is not None, f"{pid}: PMS_Gobo_0 missing"
            assert gobo.parent == rig, f"{pid}: gobo not child of rig"
            # Check collection
            bg_lights_col = bpy.data.collections.get('PMS_BgLights')
            assert bg_lights_col is not None, f"{pid}: bg_lights collection missing"
            assert gobo.name in [o.name for o in bg_lights_col.all_objects], f"{pid}: gobo not in bg_lights collection"
            # Check visibility
            assert gobo.visible_camera is False, f"{pid}: visible_camera should be False"
            assert gobo.visible_shadow is True, f"{pid}: visible_shadow should be True"
            assert gobo.visible_glossy is False, f"{pid}: visible_glossy should be False"
            assert gobo.visible_diffuse is False, f"{pid}: visible_diffuse should be False"
            assert gobo.visible_transmission is False, f"{pid}: visible_transmission should be False"
            assert gobo.visible_volume_scatter is False, f"{pid}: visible_volume_scatter should be False"

            # Check gobo center is on segment light->aim at 'at'
            light = bpy.data.objects.get('PMS_BgLight_0_gobo')
            assert light is not None, f"{pid}: light missing"
            spec = presets.get('background_light', pid).data['lights'][0]
            gobo_spec = spec.get('gobo', {})
            at = gobo_spec.get('at', 0.2)
            S = core.info(sc).size
            from product_motion_studio.build_lighting import _polar
            pos = _polar(spec['az'], spec['el'], spec['dist_f'] * S)
            tgt = _polar(*spec['aim'][:2], spec['aim'][2] * S)
            expected_center_rig = pos + at * (tgt - pos)
            # Convert to world space (rig has rotation base_az)
            rig = bpy.data.objects.get('PMS_BgLight_Rig')
            expected_center = rig.matrix_world @ expected_center_rig
            actual_center = gobo.matrix_world.translation
            diff = (Vector(actual_center) - Vector(expected_center)).length
            tol = 1e-3 * S
            assert diff < tol, f"{pid}: gobo center off by {diff:.6f} (tol {tol:.6f}), at={at}"

        api.remove_all()

    return f"{len(new_presets)} presets built, {len(gobo_presets)} with gobo panels verified"


@test("T2 Switching to 'none' or 'soft_wash' removes all PMS_Gobo_* objects")
def test_gobo_removed_on_switch():
    # Build with a gobo preset
    sc, p = built(background_light='venetian_blinds_gobo', background='cyclorama_studio_grey')
    gobo = bpy.data.objects.get('PMS_Gobo_0')
    assert gobo is not None, "initial gobo missing"

    # Switch to 'none'
    api.apply('background_light', 'none', force=True)
    gobo_none = bpy.data.objects.get('PMS_Gobo_0')
    assert gobo_none is None, "gobo still exists after switching to 'none'"

    # Build again with gobo, then switch to 'soft_wash'
    api.apply('background_light', 'venetian_blinds_gobo', force=True)
    gobo2 = bpy.data.objects.get('PMS_Gobo_0')
    assert gobo2 is not None, "gobo missing after re-apply"

    api.apply('background_light', 'soft_wash', force=True)
    gobo_soft = bpy.data.objects.get('PMS_Gobo_0')
    assert gobo_soft is None, "gobo still exists after switching to 'soft_wash'"

    api.remove_all()
    return "gobo removed on switching to none/soft_wash"


@test("T3 Render Eevee + Cycles: gobo casts shadows (the backdrop changes by >= 10 % Eevee, 5 % Cycles)")
def test_render_shadows():
    import shutil

    tmpdir = tempfile.mkdtemp(prefix='pms_gobo_render_')
    try:
        sc, p = built(background_light='venetian_blinds_gobo', background='cyclorama_studio_grey')
        cam = bpy.data.objects.get('PMS_Camera')
        assert cam is not None
        r = sc.render
        old = (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath, sc.eevee.taa_render_samples,
               sc.cycles.samples)

        # --- WITH GOBO ---
        sc.render.engine = 'BLENDER_EEVEE'
        sc.render.resolution_x = 192
        sc.render.resolution_y = 108
        sc.render.resolution_percentage = 100
        sc.eevee.taa_render_samples = 4
        sc.render.filepath = os.path.join(tmpdir, 'with_gobo_eevee.png')
        sc.render.image_settings.file_format = 'PNG'
        sc.render.image_settings.color_mode = 'RGB'
        bpy.ops.render.render(write_still=True)

        # Load pixels
        img_with = bpy.data.images.load(sc.render.filepath)
        pix_with = np.array(img_with.pixels[:], dtype=np.float32)
        bpy.data.images.remove(img_with)

        # Hide gobo
        gobo = bpy.data.objects.get('PMS_Gobo_0')
        assert gobo is not None
        gobo.hide_render = True
        bpy.context.view_layer.update()

        # --- WITHOUT GOBO ---
        sc.render.filepath = os.path.join(tmpdir, 'without_gobo_eevee.png')
        bpy.ops.render.render(write_still=True)

        img_without = bpy.data.images.load(sc.render.filepath)
        pix_without = np.array(img_without.pixels[:], dtype=np.float32)
        bpy.data.images.remove(img_without)

        # Restore
        gobo.hide_render = False

        # Analyze: the upper half of the image (backdrop behind the product), with vs without the panel
        w, h = 192, 108

        def shadow(pa, pb):
            """Mean |with - without| / mean(without) on the upper half: how much the pattern changes the backdrop."""
            lum = [(p.reshape(h, w, 4)[h // 2:, :, :3] * (0.2126, 0.7152, 0.0722)).sum(axis=2) for p in (pa, pb)]
            return float(np.abs(lum[0] - lum[1]).mean() / max(lum[1].mean(), 1e-6))

        ratio = shadow(pix_with, pix_without)
        print(f"  Eevee: change={ratio:.3f}")

        # --- CYCLES ---
        sc.render.engine = 'CYCLES'
        sc.cycles.samples = 32
        sc.render.filepath = os.path.join(tmpdir, 'with_gobo_cycles.png')
        bpy.ops.render.render(write_still=True)

        img_with_c = bpy.data.images.load(sc.render.filepath)
        pix_with_c = np.array(img_with_c.pixels[:], dtype=np.float32)
        bpy.data.images.remove(img_with_c)

        gobo.hide_render = True
        bpy.context.view_layer.update()

        sc.render.filepath = os.path.join(tmpdir, 'without_gobo_cycles.png')
        bpy.ops.render.render(write_still=True)

        img_without_c = bpy.data.images.load(sc.render.filepath)
        pix_without_c = np.array(img_without_c.pixels[:], dtype=np.float32)
        bpy.data.images.remove(img_without_c)

        gobo.hide_render = False

        ratio_c = shadow(pix_with_c, pix_without_c)
        print(f"  Cycles: change={ratio_c:.3f}")

        # Restore what the render changed
        r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath = old[:5]
        sc.eevee.taa_render_samples, sc.cycles.samples = old[5:]
        api.remove_all()

        # Both should pass
        assert ratio >= 0.1, f"Eevee: the gobo changes the backdrop by {ratio:.3f} only (< 0.1)"
        assert ratio_c >= 0.05, f"Cycles: the gobo changes the backdrop by {ratio_c:.3f} only (< 0.05)"   # bounces fill the stripes
        return f"backdrop change with the gobo: Eevee {ratio:.3f}, Cycles {ratio_c:.3f}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@test("T4 Capture preserves gobo dict in saved preset")
def test_capture_preserves_gobo():
    import shutil

    tmpdir = tempfile.mkdtemp(prefix='pms_user_gobo_')
    os.environ['PMS_USER_DIR'] = tmpdir

    try:
        from product_motion_studio import user_presets
        user_presets.load_all()

        sc, p = built(background_light='water_caustics_wash', background='cyclorama_studio_grey')

        # Save preset
        res = api.save_preset('background_light', 'Test Gobo Capture', thumbnail=False)
        pid = res['id']
        assert pid.startswith('user_'), f"unexpected id: {pid}"

        # Read the saved preset file
        import json
        with open(res['file'], 'r') as f:
            saved = json.load(f)

        # Check light 0 has gobo with pattern 'caustics'
        lights = saved['data']['lights']
        assert len(lights) == 1, f"expected 1 light, got {len(lights)}"
        gobo = lights[0].get('gobo')
        assert gobo is not None, "gobo missing in saved preset"
        assert gobo.get('pattern') == 'caustics', f"pattern is {gobo.get('pattern')}, expected 'caustics'"

        # Delete the user preset
        api.delete_user('preset', f'background_light/{pid}')

        api.remove_all()
        return f"captured gobo pattern={gobo.get('pattern')}, at={gobo.get('at')}, scale={gobo.get('scale')}, angle={gobo.get('angle')}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        del os.environ['PMS_USER_DIR']
        user_presets.load_all()


print("\n==== PMS GOBO TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)