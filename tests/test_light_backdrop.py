"""Headless test of the new live controls: light_fill, light_rim, light_temp, bg_distance, bg_cove.
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_light_backdrop.py
Never renders."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, live, presets

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


def lights(prefix='PMS_Light_'):
    return sorted((o for o in bpy.data.objects if o.type == 'LIGHT' and o.name.startswith(prefix)), key=lambda o: o.name)


def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


# ---------------------------------------------------------------------------------------------
@test("T1 fill: light_fill=0.5 halves fill lights, key lights unchanged")
def test_fill():
    # find a lighting preset with key, fill, and rim roles
    reg = presets.REGISTRY['lighting']
    target = None
    for pid, p in reg.items():
        roles = {s.get('role') for s in p.data.get('lights', [])}
        if 'key' in roles and 'fill' in roles and 'rim' in roles:
            target = pid
            break
    assert target is not None, "no lighting preset with key/fill/rim roles found"

    sc, p = built(lighting=target)
    pms = sc.pms
    base = {o.name: o.data.energy for o in lights()}
    roles_map = {o.name: o.data.get('pms_role', 'light') for o in lights()}

    api.set_live(light_fill=0.5)
    for o in lights():
        role = roles_map[o.name]
        expected = base[o.name] * (0.5 if role == 'fill' else 1.0)
        assert abs(o.data.energy - expected) < 1e-4, f"{o.name} ({role}): {o.data.energy} vs {expected}"
    clean()
    return f"fill lights halved, others unchanged"


@test("T2 rim: light_rim=2.0 doubles rim and back lights")
def test_rim():
    reg = presets.REGISTRY['lighting']
    target = None
    for pid, p in reg.items():
        roles = {s.get('role') for s in p.data.get('lights', [])}
        if 'key' in roles and 'fill' in roles and 'rim' in roles:
            target = pid
            break
    assert target is not None

    sc, p = built(lighting=target)
    pms = sc.pms
    base = {o.name: o.data.energy for o in lights()}
    roles_map = {o.name: o.data.get('pms_role', 'light') for o in lights()}

    api.set_live(light_rim=2.0)
    for o in lights():
        role = roles_map[o.name]
        expected = base[o.name] * (2.0 if role in ('rim', 'back') else 1.0)
        assert abs(o.data.energy - expected) < 1e-4, f"{o.name} ({role}): {o.data.energy} vs {expected}"
    clean()
    return "rim and back lights doubled"


@test("T3 temperature: light_temp shifts colour temperature correctly")
def test_temp():
    reg = presets.REGISTRY['lighting']
    target = None
    for pid, p in reg.items():
        roles = {s.get('role') for s in p.data.get('lights', [])}
        if 'key' in roles:
            target = pid
            break
    assert target is not None

    sc, p = built(lighting=target)
    pms = sc.pms

    # test temp_factor(0) == (1, 1, 1)
    tf0 = live.temp_factor(0)
    assert close(tf0, (1.0, 1.0, 1.0), 1e-6), f"temp_factor(0) = {tf0}"

    # test luminance preservation
    tf_m2000 = live.temp_factor(-2000)
    lum = 0.2126 * tf_m2000[0] + 0.7152 * tf_m2000[1] + 0.0722 * tf_m2000[2]
    assert abs(lum - 1.0) < 1e-6, f"luminance of temp_factor(-2000) = {lum}"

    # test colour ratio changes for a key light
    key_light = next(o for o in lights() if o.data.get('pms_role') == 'key')
    base_color = key_light.data.color[:]
    base_r, base_b = base_color[0], base_color[2]

    api.set_live(light_temp=-2000)  # warmer -> R/B larger
    c_warm = key_light.data.color[:]
    ratio_warm = c_warm[0] / c_warm[2] if c_warm[2] > 0 else float('inf')

    api.set_live(light_temp=2000)  # cooler -> R/B smaller
    c_cool = key_light.data.color[:]
    ratio_cool = c_cool[0] / c_cool[2] if c_cool[2] > 0 else float('inf')

    assert ratio_warm > ratio_cool, f"warmer R/B {ratio_warm} not > cooler R/B {ratio_cool}"
    clean()
    return f"temp_factor(0)={tf0}, warm R/B={ratio_warm:.3f} > cool R/B={ratio_cool:.3f}, luminance preserved"


@test("T4 fill kept by rebuild: light_fill=0.5 then rebuild keeps half energy")
def test_fill_rebuild():
    reg = presets.REGISTRY['lighting']
    target = None
    for pid, p in reg.items():
        roles = {s.get('role') for s in p.data.get('lights', [])}
        if 'key' in roles and 'fill' in roles and 'rim' in roles:
            target = pid
            break
    assert target is not None

    sc, p = built(lighting=target)
    pms = sc.pms
    fill_lights = [o for o in lights() if o.data.get('pms_role') == 'fill']
    base_energies = {o.name: o.data['pms_base'][0] for o in fill_lights}

    api.set_live(light_fill=0.5)
    for o in fill_lights:
        assert abs(o.data.energy - base_energies[o.name] * 0.5) < 1e-4

    api.rebuild('lighting')
    for o in lights():
        if o.data.get('pms_role') == 'fill':
            assert abs(o.data.energy - base_energies[o.name] * 0.5) < 1e-4, f"rebuild lost fill factor on {o.name}"
    clean()
    return "fill factor preserved after rebuild"


@test("T5 distance: bg_distance=2.0 moves wall farther by ~5*size")
def test_distance():
    sc, p = built(background='cyclorama_studio_grey')
    pms = sc.pms
    bg = bpy.data.objects.get('PMS_Background')
    assert bg is not None
    verts = [bg.matrix_world @ v.co for v in bg.data.vertices]
    max_y0 = max(v.y for v in verts)
    size = api.state()['size']

    api.set_live(bg_distance=2.0)
    bpy.context.view_layer.update()
    # refit_backdrop rebuilds the background, need to re-fetch
    bg = bpy.data.objects.get('PMS_Background')
    assert bg is not None
    verts2 = [bg.matrix_world @ v.co for v in bg.data.vertices]
    max_y1 = max(v.y for v in verts2)

    # wall should move by about 5 * size (from 5*S*distance to 5*S*2*distance = +5*S)
    expected_delta = 5 * size
    actual_delta = max_y1 - max_y0
    assert abs(actual_delta - expected_delta) < 0.25 * expected_delta, \
        f"wall moved {actual_delta:.3f} vs expected ~{expected_delta:.3f} (25% tol)"

    # background should not be marked as modified (it was rebuilt cleanly)
    assert 'background' not in api.state()['modified'], f"background modified: {api.state()['modified']}"
    clean()
    return f"wall moved {actual_delta:.3f} (expected ~{expected_delta:.3f}), modified={api.state()['modified']}"


@test("T6 cove: bg_cove=2.0 changes mesh, back to 1.0 restores Y")
def test_cove():
    sc, p = built(background='cyclorama_studio_grey')
    pms = sc.pms
    bg = bpy.data.objects.get('PMS_Background')
    assert bg is not None
    verts0 = [bg.matrix_world @ v.co for v in bg.data.vertices]

    api.set_live(bg_cove=2.0)
    bpy.context.view_layer.update()
    bg = bpy.data.objects.get('PMS_Background')  # rebuilt
    assert bg is not None
    verts1 = [bg.matrix_world @ v.co for v in bg.data.vertices]

    # some vertex should differ
    changed = any(abs(v1.y - v0.y) > 1e-4 or abs(v1.z - v0.z) > 1e-4
                  for v0, v1 in zip(verts0, verts1))
    assert changed, "mesh did not change with cove=2.0"

    # back to 1.0
    api.set_live(bg_cove=1.0)
    bpy.context.view_layer.update()
    bg = bpy.data.objects.get('PMS_Background')  # rebuilt again
    assert bg is not None
    verts2 = [bg.matrix_world @ v.co for v in bg.data.vertices]

    # Y should be back to original (tolerance 1e-4)
    max_y0 = max(v.y for v in verts0)
    max_y2 = max(v.y for v in verts2)
    assert abs(max_y2 - max_y0) < 1e-4, f"Y not restored: {max_y2} vs {max_y0}"
    clean()
    return "cove changes mesh, Y restored at 1.0"


@test("T7 hand edit: moved PMS_Background kept when bg_distance changes")
def test_hand_edit():
    sc, p = built(background='cyclorama_studio_grey')
    pms = sc.pms
    bg = bpy.data.objects.get('PMS_Background')
    assert bg is not None

    # move by hand
    bg.location.x += 1.0
    bpy.context.view_layer.update()
    moved_x = bg.location.x

    # change bg_distance should not raise and should keep the hand edit
    try:
        api.set_live(bg_distance=1.5)
    except Exception as e:
        raise AssertionError(f"set_live(bg_distance=1.5) raised {type(e).__name__}: {e}")

    bpy.context.view_layer.update()
    assert abs(bg.location.x - moved_x) < 1e-4, f"hand edit lost: x={bg.location.x} vs {moved_x}"

    # background should still be marked as modified (hand edit preserved)
    assert 'background' in api.state()['modified'], f"hand edit not flagged: {api.state()['modified']}"
    # but no exception, and hand edit kept
    return "hand edit preserved, still flagged as modified"


print("\n==== PMS LIGHT/BACKDROP TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)