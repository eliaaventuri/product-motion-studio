"""Test for calibrate.py tool.
Run:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_calibrate.py
"""

import os
import sys
import tempfile
import shutil
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core

RESULTS = []


def test(num, name):
    def deco(fn):
        try:
            msg = fn()
            RESULTS.append((num, name, True, msg or ''))
        except Exception as e:
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


@test(1, "calibrate.run returns results for two lighting presets")
def t1():
    clean_scene()

    # Import the calibrate module
    sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
    import calibrate

    tmp = tempfile.mkdtemp(prefix='pms_test_calibrate_')
    try:
        res = calibrate.run(
            section='lighting',
            ids='three_point_classic,dark_luxury_contour',
            engine='EEVEE',
            res=(160, 90),
            samples=4,
            out=tmp
        )

        assert len(res) == 2, f"Expected 2 results, got {len(res)}"
        for r in res:
            assert 0 < r['prod_mean'] < 1, f"prod_mean out of range: {r['prod_mean']}"
            assert r['engine'] == 'EEVEE'
            assert 'prod_clip_pct' in r
            assert 'bg_mean' in r
            assert 'time_s' in r

        # dark_luxury_contour should be darker than three_point_classic
        r1 = next(r for r in res if r['id'] == 'three_point_classic')
        r2 = next(r for r in res if r['id'] == 'dark_luxury_contour')
        assert r2['prod_mean'] < r1['prod_mean'], f"dark_luxury_contour ({r2['prod_mean']:.3f}) not darker than three_point_classic ({r1['prod_mean']:.3f})"

        # PNGs exist
        for r in res:
            png = os.path.join(tmp, f"{r['id']}_{r['engine']}.png")
            assert os.path.exists(png), f"Missing beauty PNG: {png}"

        return f"2 results, means: {r1['prod_mean']:.3f} vs {r2['prod_mean']:.3f}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test(2, "calibrate.run produces JSON and PNG outputs")
def t2():
    clean_scene()

    sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
    import calibrate

    tmp = tempfile.mkdtemp(prefix='pms_test_calibrate_')
    try:
        res = calibrate.run(
            section='lighting',
            ids='three_point_classic',
            engine='EEVEE',
            res=(160, 90),
            samples=4,
            out=tmp
        )

        assert len(res) == 1
        r = res[0]
        assert r['id'] == 'three_point_classic'
        assert r['engine'] == 'EEVEE'
        assert 0 < r['prod_mean'] < 1
        assert 'prod_clip_pct' in r
        assert 'bg_mean' in r
        assert 'time_s' in r

        # Check JSON exists
        json_path = os.path.join(tmp, 'calibrate_lighting.json')
        assert os.path.exists(json_path), f"Missing JSON: {json_path}"

        # Check PNG exists
        png_path = os.path.join(tmp, 'three_point_classic_EEVEE.png')
        assert os.path.exists(png_path), f"Missing PNG: {png_path}"

        return f"JSON and PNG created, prod_mean={r['prod_mean']:.3f}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("\n==== CALIBRATE TEST RESULTS ====")
for num, name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {num}. {name}  {msg}")
fails = [r for r in RESULTS if not r[2]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)