"""Headless test for deeper bounces on glass and Post-Production Passes toggle.
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_render_extras.py
Never renders."""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy

import product_motion_studio as pkg
from product_motion_studio import api, core, render_settings

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=60)


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


def built(scale=1.0, **kw):
    sc = fresh()
    p = cube(size=2 * scale, loc=(0, 0, scale))
    api.build(objects=[p], **{**W, **kw})
    return sc, p


# ---------------------------------------------------------------------------------------------
@test("T1 glass: transmission 1.0 -> deeper bounces set, reason mentions material")
def t1_glass():
    sc, p = built()
    mat = bpy.data.materials.new('GlassMat')
    mat.use_nodes = True
    p.data.materials.append(mat)
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    api.set_render('FINAL')
    c = sc.cycles
    assert c.transmission_bounces == 16, f"transmission_bounces={c.transmission_bounces}"
    assert c.glossy_bounces == 8, f"glossy_bounces={c.glossy_bounces}"
    assert c.max_bounces == 16, f"max_bounces={c.max_bounces}"
    out = api.set_render('FINAL')
    assert 'deep_bounces' in out and out['deep_bounces'] and 'GlassMat' in out['deep_bounces'], out
    return f"deep bounces active: max={c.max_bounces}, glossy={c.glossy_bounces}, transmission={c.transmission_bounces}, reason={out['deep_bounces']}"


# ---------------------------------------------------------------------------------------------
@test("T2 back: transmission 0.0 + non-glass preset -> bounces restored, saved dict removed")
def t2_back():
    sc, p = built()
    mat = bpy.data.materials.new('GlassMat')
    mat.use_nodes = True
    p.data.materials.append(mat)
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    api.set_render('FINAL')
    c = sc.cycles
    assert c.transmission_bounces == 16
    bsdf.inputs['Transmission Weight'].default_value = 0.0
    api.apply('lighting', 'beauty_soft')
    # Debug: check what needs_deep_bounces returns
    from product_motion_studio import render_settings
    print(f"DEBUG T2: scene.pms.lighting={sc.pms.lighting!r}, recipe={sc.pms.recipe!r}")
    reason = render_settings.needs_deep_bounces(sc)
    print(f"DEBUG T2: needs_deep_bounces returned: {reason!r}")
    api.set_render('FINAL')
    c = sc.cycles
    assert c.max_bounces == 12, f"max_bounces={c.max_bounces}"
    assert c.glossy_bounces == 4, f"glossy_bounces={c.glossy_bounces}"
    assert c.transmission_bounces == 12, f"transmission_bounces={c.transmission_bounces}"
    assert c.transparent_max_bounces == 8, f"transparent_max_bounces={c.transparent_max_bounces}"
    assert 'pms_saved_bounces' not in sc, f"pms_saved_bounces still present: {sc.get('pms_saved_bounces')}"
    out = api.set_render('FINAL')
    assert out['deep_bounces'] is None, out
    return f"bounces restored: max={c.max_bounces}, glossy={c.glossy_bounces}, transmission={c.transmission_bounces}, transparent_max={c.transparent_max_bounces}, saved removed"


# ---------------------------------------------------------------------------------------------
@test("T3 preset word: opaque cube + lighting preset containing 'glass' -> transmission 16")
def t3_preset_word():
    sc, p = built()
    lighting_ids = [lid for lid, _, _ in api.list_presets('lighting')['lighting']]
    glass_id = next((lid for lid in lighting_ids if 'glass' in lid.lower()), None)
    assert glass_id, f"no lighting preset with 'glass' found in {lighting_ids}"
    api.apply('lighting', glass_id)
    api.set_render('FINAL')
    c = sc.cycles
    assert c.transmission_bounces == 16, f"transmission_bounces={c.transmission_bounces}"
    out = api.set_render('FINAL')
    assert 'deep_bounces' in out and out['deep_bounces'] and glass_id in out['deep_bounces'], out
    return f"glass preset '{glass_id}' triggered deep bounces, transmission={c.transmission_bounces}, reason={out['deep_bounces']}"


# ---------------------------------------------------------------------------------------------
@test("T4 passes on: built studio + render_passes=True -> all PASSES True, media_type MULTI_LAYER_IMAGE, color_depth 32, mist depth > 0")
def t4_passes_on():
    sc, p = built()
    pms = sc.pms
    with core.quiet():
        pms.render_passes = True
    api.set_render(mode='still')
    vl = sc.view_layers[0]
    for p in render_settings.PASSES:
        assert getattr(vl, p), f"{p} not True on view layer"
    assert vl.cycles.use_pass_shadow_catcher, "shadow catcher not enabled"
    im = sc.render.image_settings
    assert im.media_type == 'MULTI_LAYER_IMAGE', f"media_type={im.media_type}"
    assert im.color_depth == '32', f"color_depth={im.color_depth}"
    assert sc.world and sc.world.mist_settings.depth > 0, f"mist depth={sc.world.mist_settings.depth if sc.world else 'no world'}"
    return f"passes on: all PASSES True, media_type={im.media_type}, color_depth={im.color_depth}, mist_depth={sc.world.mist_settings.depth if sc.world else 'N/A'}"


# ---------------------------------------------------------------------------------------------
@test("T5 passes off: render_passes=False -> all PASSES False, saved dict removed, media_type IMAGE, file_format PNG")
def t5_passes_off():
    sc, p = built()
    pms = sc.pms
    with core.quiet():
        pms.render_passes = True
    api.set_render(mode='still')
    vl = sc.view_layers[0]
    with core.quiet():
        pms.render_passes = False
    api.set_render(mode='still')
    for p in render_settings.PASSES:
        assert not getattr(vl, p), f"{p} not False on view layer"
    assert 'pms_saved_passes' not in sc, f"pms_saved_passes still present: {sc.get('pms_saved_passes')}"
    im = sc.render.image_settings
    assert im.media_type == 'IMAGE', f"media_type={im.media_type}"
    assert im.file_format == 'PNG', f"file_format={im.file_format}"
    return f"passes off: all PASSES False, media_type={im.media_type}, file_format={im.file_format}, saved removed"


# ---------------------------------------------------------------------------------------------
if __name__ == '__main__':
    print("\n==== PMS RENDER EXTRAS TEST RESULTS ====")
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
    fails = [r for r in RESULTS if not r[1]]
    print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
    sys.exit(1 if fails else 0)