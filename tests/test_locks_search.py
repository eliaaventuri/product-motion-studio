"""Headless test for section locks + text search of presets (Product Motion Studio):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_locks_search.py
One test per point. Never renders."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, live, presets, props

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


def built(scale=1.0, **kw):
    sc = fresh()
    p = cube(size=2 * scale, loc=(0, 0, scale))
    # Map camera_shot -> shot for api.build
    build_kw = dict(W)
    build_kw.update(kw)
    if 'camera_shot' in build_kw:
        build_kw['shot'] = build_kw.pop('camera_shot')
    api.build(objects=[p], **build_kw)
    return sc, p


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
@test("L1: lock camera_shot, apply recipe keeps it (preset, overrides, live values)")
def L1_lock_camera_shot():
    sc, p = built(camera_shot='macro', product_motion='static')
    pms = sc.pms
    # Apply a different shot, with an override
    api.apply('camera_shot', 'macro', padding=0.3)
    # Set a live value
    api.set_live(cam_lens=70)
    # Lock camera_shot
    pms.locks = {'camera_shot'}
    # Find a recipe with a different camera_shot
    recipes = presets.REGISTRY['recipe']
    R = None
    for rid, r in recipes.items():
        if r.data['camera_shot'] != 'macro':
            R = rid
            break
    assert R is not None, "no recipe with camera_shot != macro"
    # Apply recipe
    out = api.apply_recipe(R)
    # Check: camera_shot stays 'macro'
    assert pms.camera_shot == 'macro', f"camera_shot changed to {pms.camera_shot}"
    # Override kept
    ov = core.overrides(sc, 'camera_shot')
    assert abs(ov.get('padding', 0) - 0.3) < 1e-4, f"override lost: {ov}"
    # Live value kept
    assert abs(pms.cam_lens - 70) < 1e-4, f"cam_lens changed to {pms.cam_lens}"
    # Lighting follows recipe
    r_data = recipes[R].data
    assert pms.lighting == r_data['lighting'], f"lighting not from recipe: {pms.lighting} vs {r_data['lighting']}"
    # Result has kept
    assert out['kept'] == ['camera_shot'], f"kept wrong: {out['kept']}"
    return f"kept camera_shot, override, live; lighting from recipe"


@test("L2: explicit keep=[] overrides locks, recipe changes camera_shot")
def L2_keep_empty_overrides_locks():
    sc, p = built(camera_shot='macro', product_motion='static')
    pms = sc.pms
    api.apply('camera_shot', 'macro', padding=0.3)
    api.set_live(cam_lens=70)
    pms.locks = {'camera_shot'}
    recipes = presets.REGISTRY['recipe']
    R = None
    for rid, r in recipes.items():
        if r.data['camera_shot'] != 'macro':
            R = rid
            break
    assert R is not None
    out = api.apply_recipe(R, keep=[])
    assert pms.camera_shot == recipes[R].data['camera_shot'], f"camera_shot not changed: {pms.camera_shot}"
    return "keep=[] overrides locks"


@test("L3: apply_recipe with unknown keep raises ValueError, state unchanged")
def L3_unknown_keep_raises():
    sc, p = built(camera_shot='macro', product_motion='static')
    pms = sc.pms
    api.apply('camera_shot', 'macro', padding=0.3)
    pms.locks = {'camera_shot'}
    recipes = presets.REGISTRY['recipe']
    R = next(iter(recipes))
    msg = raises(ValueError, api.apply_recipe, R, keep=['nope'])
    assert 'nope' in msg and 'camera_shot' in msg
    assert pms.camera_shot == 'macro', "state changed despite error"
    return "ValueError raised, state unchanged"


@test("L4: lock format after apply format 1:1, recipe with different format keeps 1080x1080")
def L4_lock_format():
    sc, p = built(format='16:9')
    pms = sc.pms
    api.apply('format', '1:1')
    pms.locks = {'format'}
    recipes = presets.REGISTRY['recipe']
    R = None
    for rid, r in recipes.items():
        if r.data['format'] != '1:1':
            R = rid
            break
    assert R is not None, "no recipe with format != 1:1"
    out = api.apply_recipe(R)
    # Resolution should stay 1080x1080 (1:1 at 1080p)
    assert sc.render.resolution_x == 1080 and sc.render.resolution_y == 1080, f"resolution changed: {sc.render.resolution_x}x{sc.render.resolution_y}"
    assert out['kept'] == ['format'], f"kept wrong: {out['kept']}"
    return f"format kept at 1080x1080"


# ---------------------------------------------------------------------------------------------
@test("S1: props.visible_ids with text filter")
def S1_visible_ids_text():
    # glass in lighting
    ids = props.visible_ids('lighting', text='glass')
    assert len(ids) > 0, "no presets match 'glass'"
    for pid in ids:
        p = presets.REGISTRY['lighting'][pid]
        assert props.matches(p, 'glass'), f"{pid} does not match 'glass'"
    # nonsense returns empty
    ids = props.visible_ids('lighting', text='zzqqxx')
    assert ids == [], f"expected empty, got {ids}"
    return f"glass matches: {ids[:5]}...; zzqqxx empty"


@test("S2: api.list_presets search matches props.visible_ids")
def S2_list_presets_search():
    props_ids = set(props.visible_ids('lighting', text='glass'))
    api_ids = set(api.list_presets('lighting', search='glass')['lighting'])
    # api.list_presets returns tuples (id, name, category)
    api_ids_only = {t[0] for t in api_ids}
    assert props_ids == api_ids_only, f"mismatch: props={props_ids}, api={api_ids_only}"
    return f"both return {len(props_ids)} ids"


@test("S3: words are ANDed in search")
def S3_words_anded():
    # Find a recipe section preset with 'loop' and 'spin' in its searchable text
    ids_loop = props.visible_ids('product_motion', text='loop')
    ids_loop_spin = props.visible_ids('product_motion', text='loop spin')
    assert len(ids_loop_spin) > 0, "no preset matches 'loop spin'"
    assert len(ids_loop_spin) <= len(ids_loop), f"'loop spin' longer than 'loop': {len(ids_loop_spin)} vs {len(ids_loop)}"
    for pid in ids_loop_spin:
        p = presets.REGISTRY['product_motion'][pid]
        assert props.matches(p, 'loop'), f"{pid} missing 'loop'"
        assert props.matches(p, 'spin'), f"{pid} missing 'spin'"
    return f"'loop': {len(ids_loop)}, 'loop spin': {len(ids_loop_spin)}"


@test("S4: _items always includes current preset even if it doesn't match search")
def S4_current_preset_always_visible():
    sc, p = built()
    pms = sc.pms
    # Set a lighting preset
    pms.lighting = 'beauty_soft'
    # Set search that doesn't match beauty_soft
    pms.lighting_find = 'glass'
    cat, ptype, text = props._filters(pms, 'lighting')
    items = props._items('lighting', cat, ptype, pms.lighting, text)
    # beauty_soft should be in the items
    found = any(item[0] == 'beauty_soft' for item in items)
    assert found, "current preset 'beauty_soft' not in filtered items"
    return "current preset included despite search mismatch"


# ---------------------------------------------------------------------------------------------
@test("S5: search does not block recipe; search cleared after apply")
def S5_search_does_not_block_recipe():
    sc, p = built()
    pms = sc.pms
    # Find a search term that excludes 'tech_desk_neutral'
    search_term = 'strip'
    assert 'tech_desk_neutral' not in props.visible_ids('lighting', text=search_term), \
        f"'{search_term}' unexpectedly includes 'tech_desk_neutral'"
    # Set the search term
    pms.lighting_find = search_term
    # Apply a recipe that sets lighting to 'tech_desk_neutral'
    out = api.apply_recipe('headphones_studio')
    # Check that lighting was set correctly
    assert pms.lighting == 'tech_desk_neutral', f"lighting not set to tech_desk_neutral: {pms.lighting}"
    # Check that search was cleared
    assert pms.lighting_find == '', f"search not cleared: {pms.lighting_find}"
    return f"search cleared, lighting={pms.lighting}"


@test("S6: failed build restores previous choices (product_motion, camera_motion)")
def S6_failed_build_restores_choices():
    sc, p = built()
    pms = sc.pms
    # Save original values
    orig_product_motion = pms.product_motion
    orig_camera_motion = pms.camera_motion

    # Replace props.assign with a function that raises on 'lighting'
    import product_motion_studio.props as props_module
    original_assign = props_module.assign

    def failing_assign(pms_obj, key, value):
        if key == 'lighting':
            raise RuntimeError("Simulated failure on lighting")
        return original_assign(pms_obj, key, value)

    try:
        props_module.assign = failing_assign
        # Also patch the module that api.py uses
        import product_motion_studio.api as api_module
        api_module.props.assign = failing_assign

        # This should raise RuntimeError
        raises(RuntimeError, api.apply_recipe, 'headphones_studio')
    finally:
        props_module.assign = original_assign
        import product_motion_studio.api as api_module
        api_module.props.assign = original_assign

    # Check that choices were restored
    assert pms.product_motion == orig_product_motion, \
        f"product_motion not restored: {pms.product_motion} vs {orig_product_motion}"
    assert pms.camera_motion == orig_camera_motion, \
        f"camera_motion not restored: {pms.camera_motion} vs {orig_camera_motion}"
    return f"choices restored: product_motion={pms.product_motion}, camera_motion={pms.camera_motion}"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS LOCKS + SEARCH TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)