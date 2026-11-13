"""Headless test of the second round of Product Motion Studio: live controls, background light, Preview Motion, Render panel,
dispersion lighting, scene recipes (plugin/docs/CONFRONTO_CPS.md):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_live.py
One test per point. Never renders (the dispersion render was checked by hand: see STATO.md)."""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
from bpy_extras.object_utils import world_to_camera_view

import product_motion_studio as pkg
from product_motion_studio import api, core, live, presets, render_settings, ui

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
    api.build(objects=[p], **{**W, **kw})
    return sc, p


def lights(prefix='PMS_Light_'):
    return sorted((o for o in bpy.data.objects if o.type == 'LIGHT' and o.name.startswith(prefix)), key=lambda o: o.name)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def close(a, b, tol=1e-4):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def ramp(obj='PMS_Background'):
    mat = bpy.data.objects[obj].active_material
    return next(n for n in mat.node_tree.nodes if n.type == 'VALTORGB')


def clean():
    assert api.state()['modified'] == [], api.state()['modified']


def cam_dist():
    return abs(bpy.data.objects['PMS_Camera'].location.y)


# ---------------------------------------------------------------------------------------------
@test("1a live camera: lens, padding (also negative), f-stop, DOF on/off, focus offset change the scene at once")
def live_camera():
    sc, p = built(shot='hero_34', camera_motion='static', product_motion='static')
    pms = sc.pms
    cam = sc.camera
    assert (pms.cam_lens, round(pms.cam_padding, 3), pms.cam_dof) == (85, 0.2, True)
    d0 = cam_dist()
    ptr = bpy.data.objects['PMS_Camera'].as_pointer()
    pms.cam_lens = 120
    cam = sc.camera
    assert cam.data.lens == 120 and abs(cam_dist() / d0 - 120 / 85) < 0.2, (cam_dist(), d0)   # re-fitted: the framing is kept
    clean()
    d1 = cam_dist()
    pms.cam_padding = 0.5
    assert cam_dist() > d1                                # more room: farther
    pms.cam_padding = -0.5
    assert cam_dist() < d1 * 0.7, "negative padding crops: closer"
    inf = core.info()
    sc.frame_set(sc.frame_start)
    pts = [world_to_camera_view(sc, sc.camera, inf.root.matrix_world @ c) for c in inf.corners]
    assert max(max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts)) > 1.0, \
        "the product should overfill the frame at padding -0.5"
    clean()
    raises(ValueError, api.set_live, cam_padding=-0.6)
    raises(ValueError, api.set_live, cam_padding=1.0)
    api.set_live(cam_padding=-0.5, cam_lens=100)
    api.apply('camera_shot', 'macro', padding=-0.5)         # the API takes it too
    assert abs(pms.cam_padding + 0.5) < 1e-6 and abs(pms.cam_lens - 150) < 1e-6
    pms.cam_padding = 0.2
    cam = sc.camera
    pms.cam_fstop = 2.0
    assert cam.data.dof.aperture_fstop == 2.0 and cam.data.dof.use_dof
    pms.cam_dof = False
    assert not cam.data.dof.use_dof
    pms.cam_dof = True
    assert cam.data.dof.use_dof and cam.data.dof.focus_object.name == 'PMS_DOF_Empty'
    pms.cam_focus = 0.5
    empty = bpy.data.objects['PMS_DOF_Empty']
    assert abs(empty.delta_location.length - 0.5 * inf.size) < 1e-4, (tuple(empty.delta_location), inf.size)
    assert empty.delta_location.dot(core.cam_basis(sc.pms.base_az * 3.14159265 / 180, 0.3)[2]) != 0
    clean()
    # a camera edited by hand is not rebuilt by the lens slider: the lens is set in place and the edit stays flagged
    sc.camera.data.sensor_width = 24
    ptr = sc.camera.as_pointer()
    pms.cam_lens = 70
    assert sc.camera.as_pointer() == ptr and sc.camera.data.lens == 70 and api.state()['modified'] == ['camera']
    return f"lens/padding/f-stop/DOF/focus live, padding -0.5..0.9, modified={api.state()['modified']}"


@test("1b live lighting: Power, Tint, Rig rotation")
def live_lighting():
    sc, p = built(lighting='beauty_soft')
    pms = sc.pms
    base = {o.name: o.data.energy for o in lights()}
    w0 = sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value
    pms.light_power = 2.0
    assert all(abs(o.data.energy - 2 * base[o.name]) < 1e-4 for o in lights())
    assert abs(sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value - 2 * w0) < 1e-6
    clean()
    pms.light_power = 0.0
    assert all(o.data.energy == 0 for o in lights())
    pms.light_power = 1.0
    pms.light_tint = (1.0, 0.5, 0.25)
    assert all(close(o.data.color, (1.0, 0.5, 0.25)) for o in lights() if not o.data.use_temperature or True)
    pms.light_tint = (1, 1, 1)
    rig = bpy.data.objects['PMS_Light_Rig']
    rz = rig.rotation_euler[2]
    pms.light_rot = 40
    assert abs(rig.delta_rotation_euler[2] - 0.6981317) < 1e-5 and rig.rotation_euler[2] == rz
    clean()
    # a light moved by hand: still reported, and the live value reaches it
    ls = lights()
    ls[0].location.x += 1
    assert api.state()['modified'] == ['lighting']
    pms.light_power = 1.5
    assert api.state()['modified'] == ['lighting'], "a live change must not hide the hand edit"
    assert abs(ls[0].data.energy - 1.5 * base[ls[0].name]) < 1e-4
    # animated sweep: the rotation is a delta, the keys stay
    api.apply('lighting', 'beauty_soft', force=True, animate_lighting=True)
    rig = bpy.data.objects['PMS_Light_Rig']
    assert pms.light_power == 1.0 and rig.animation_data.action
    pms.light_rot = -20
    assert abs(rig.delta_rotation_euler[2] + 0.34906585) < 1e-5 and rig.animation_data.action
    clean()
    return "power, tint, rotation live; hand edit still flagged"


@test("1c live background: gradient colours (linear + radial), type, rotation, roughness, self light")
def live_background():
    sc, p = built(background='cyclorama_studio_grey', floor='matte')
    pms = sc.pms
    mat = bpy.data.objects['PMS_Background'].active_material
    r = ramp()
    assert len(r.color_ramp.elements) == 3 and close(pms.bg_color_a, r.color_ramp.elements[0].color[:3])
    pms.bg_color_a = (1.0, 0.0, 0.0)
    pms.bg_color_mid = (0.0, 1.0, 0.0)
    pms.bg_color_b = (0.0, 0.0, 1.0)
    els = r.color_ramp.elements
    assert close(els[0].color[:3], (1, 0, 0)) and close(els[1].color[:3], (0, 1, 0)) and close(els[2].color[:3], (0, 0, 1))
    clean()
    gnode = next(n for n in mat.node_tree.nodes if n.type == 'TEX_GRADIENT')
    pms.bg_type = 'RADIAL'
    assert gnode.gradient_type == 'SPHERICAL'
    els = r.color_ramp.elements                          # radial: the first colour is the centre = ramp end
    assert close(els[-1].color[:3], (1, 0, 0)) and close(els[0].color[:3], (0, 0, 1))
    pms.bg_type = 'LINEAR'
    pms.bg_rotation = 90
    mp = next(n for n in mat.node_tree.nodes if n.type == 'MAPPING')
    assert abs(mp.inputs['Rotation'].default_value[2]) < 1e-6        # -90 + 90
    pms.bg_roughness = 0.2
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    assert abs(bsdf.inputs['Roughness'].default_value - 0.2) < 1e-6
    glow = mat.node_tree.nodes['PMS_SelfLight']                      # strength x (1 - Is Diffuse Ray): the glow is for the eye only
    assert glow.inputs[1].default_value == 0 and bsdf.inputs['Emission Strength'].is_linked
    pms.bg_selflight = 2.5
    assert abs(glow.inputs[1].default_value - 2.5) < 1e-6 and bsdf.inputs['Emission Color'].is_linked
    clean()
    # floor plane colour / roughness
    fmat = bpy.data.objects['PMS_Floor'].active_material
    fb = next(n for n in fmat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    pms.floor_color = (0.8, 0.1, 0.1)
    pms.floor_roughness = 0.1
    assert close(fb.inputs['Base Color'].default_value[:3], (0.8, 0.1, 0.1)) and abs(fb.inputs['Roughness'].default_value - 0.1) < 1e-6
    clean()
    # a rebuild keeps the live values (same preset)
    api.apply('camera_shot', 'front')
    api.run(api.steps_for('background'), None, sc)
    assert close(pms.bg_color_a, (1, 0, 0)) and close(ramp().color_ramp.elements[0].color[:3], (1, 0, 0)), "lost on rebuild"
    assert close(pms.floor_color, (0.8, 0.1, 0.1))
    clean()
    return "gradient colours, type, rotation, roughness, self light, floor colour live; kept on rebuild"


@test("1d live look: Intensity (final mix node) and exposure")
def live_look():
    sc, p = built(look='dark_editorial')
    pms = sc.pms
    ng = sc.compositing_node_group
    mix = ng.nodes['PMS_Intensity']
    assert mix.inputs[0].default_value == 1.0 and mix.inputs[6].is_linked and mix.inputs[7].is_linked
    out = next(n for n in ng.nodes if n.type == 'GROUP_OUTPUT')
    assert out.inputs[0].links[0].from_node.name == mix.name
    assert mix.inputs[6].links[0].from_node.type == 'R_LAYERS', "A must be the neutral render"
    e0 = sc.view_settings.exposure
    assert abs(e0 - pms.look_exposure) < 1e-6
    pms.look_intensity = 0.3
    assert abs(mix.inputs[0].default_value - 0.3) < 1e-6
    pms.look_exposure = e0 + 1
    assert abs(sc.view_settings.exposure - (e0 + 1)) < 1e-6
    clean()
    api.run(api.steps_for('look'), None, sc)               # the Build button: same preset, the live values stay
    assert abs(sc.compositing_node_group.nodes['PMS_Intensity'].inputs[0].default_value - 0.3) < 1e-6
    clean()
    return "intensity 0.3 and exposure +1 live, kept on rebuild"


@test("1e live values: reset to the preset's defaults with a new preset, kept by other rebuilds, survive save + reopen, no false 'modified'")
def live_state():
    sc, p = built()
    pms = sc.pms
    pms.light_power, pms.cam_lens, pms.look_intensity, pms.bg_selflight, pms.bgl_power = 2.0, 120.0, 0.5, 1.5, 1.7
    pms.bg_color_b = (0.9, 0.1, 0.2)
    api.apply('camera_motion', 'pull_back')                # other section: the camera lens (a camera_shot value) stays
    assert pms.cam_lens == 120 and sc.camera.data.lens == 120
    api.apply('product_motion', 'spin_90', duration=90)
    assert pms.cam_lens == 120 and pms.light_power == 2.0
    clean()
    path = os.path.join(tempfile.gettempdir(), 'pms_live_save.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    sc = bpy.context.scene
    pms = sc.pms
    assert (pms.light_power, pms.cam_lens, pms.look_intensity, pms.bg_selflight) == (2.0, 120.0, 0.5, 1.5), "lost on reopen"
    assert close(pms.bg_color_b, (0.9, 0.1, 0.2))
    assert sc.camera.data.lens == 120 and abs(lights()[0].data.energy - 2 * lights()[0].data['pms_base'][0]) < 1e-4
    assert abs(sc.compositing_node_group.nodes['PMS_Intensity'].inputs[0].default_value - 0.5) < 1e-6
    clean()                                                # (a saved file is not a hand edit)
    pms.light_power = 3.0                                  # and the live controls still work after the reopen
    assert abs(lights()[0].data.energy - 3 * lights()[0].data['pms_base'][0]) < 1e-4
    api.run(api.steps_for('lighting'), None, sc)           # Build button, same preset: the values stay
    assert pms.light_power == 3.0 and abs(lights()[0].data.energy - 3 * lights()[0].data['pms_base'][0]) < 1e-4
    clean()
    # a new preset (chosen in the panel, then Build) starts from the defaults; so does an explicit apply of the same one
    pms.lighting = 'rim_only'
    api.run(api.steps_for('lighting'), None, sc)
    assert pms.light_power == 1.0 and close(pms.light_tint, (1, 1, 1))
    pms.light_power = 2.0
    api.apply('lighting', 'rim_only')
    assert pms.light_power == 1.0
    pms.cam_lens = 130
    pms.camera_shot = 'front'
    api.run(api.steps_for('camera_shot'), None, sc)
    assert pms.cam_lens == 85 and sc.camera.data.lens == 85 and abs(pms.cam_padding - 0.2) < 1e-6
    pms.bg_color_b = (0, 0, 0)
    api.apply('background', 'cyclorama_gradient_blue')
    assert close(pms.bg_color_b, presets.REGISTRY['background']['cyclorama_gradient_blue'].data['stops'][-1][1])
    api.apply('look', 'noir')
    assert pms.look_intensity == 1.0
    clean()
    # override of a preset value is the new default
    api.apply('camera_shot', 'hero_34', lens=100)
    assert pms.cam_lens == 100
    # remove_all puts every live control back
    api.remove_all()
    assert pms.light_power == 1.0 and pms.cam_lens == 85 and pms.live_marks == '{}' and pms.built == '{}'
    return "reset / keep / save+reopen / explicit apply behave; modified always []"


# ---------------------------------------------------------------------------------------------
@test("2 background light: 6 presets, only the backdrop and floor, scaled with the product, rebuilt with background, live colour/power")
def background_light():
    reg = presets.REGISTRY['background_light']
    assert sorted(reg) == sorted(['none', 'soft_wash', 'spot_pool', 'top_gradient', 'side_sweep', 'rim_glow']), sorted(reg)
    assert not reg['none'].data['lights'] and all(reg[i].data['lights'] for i in reg if i != 'none')
    feats = {}
    for scale in (1.0, 0.01):
        sc, p = built(scale=scale)
        assert not lights('PMS_BgLight'), "'none' makes no lights"
        for pid in reg:
            if pid == 'none':
                continue
            out = api.apply('background_light', pid)
            assert not out['warnings'], out['warnings']
            ls = lights('PMS_BgLight_')
            assert len(ls) == len(reg[pid].data['lights'])
            rc = bpy.data.collections[core.RECEIVERS]
            for o in ls:
                assert o.light_linking.receiver_collection is rc, f"{o.name} not linked to the backdrop"
                assert not o.visible_camera
            assert {o.name for o in rc.all_objects} <= {'PMS_Background', 'PMS_Floor'}, "the product must not receive these lights"
            inf = core.info()
            bpy.context.view_layer.update()
            feats.setdefault(pid, []).append(sorted((tuple(round(c / inf.size, 3) for c in (o.matrix_world.translation - inf.center)),
                                                     round(o.data.energy / inf.size ** 2, 3)) for o in ls))
        api.apply('background_light', 'none')
        assert not lights('PMS_BgLight') and 'PMS_BgLight_Rig' not in bpy.data.objects
    assert all(a == b for a, b in feats.values()), "not scale free"
    sc, p = built()
    api.apply('background_light', 'soft_wash')
    pms = sc.pms
    clean()
    base = {o.name: o.data['pms_base'][0] for o in lights('PMS_BgLight_')}
    pms.bgl_power = 2.5
    assert all(abs(o.data.energy - 2.5 * base[o.name]) < 1e-4 for o in lights('PMS_BgLight_'))
    pms.bgl_color = (1.0, 0.2, 0.2)
    assert all(close(o.data.color, (1.0, 0.2, 0.2)) for o in lights('PMS_BgLight_'))
    assert all(o.name.startswith('PMS_Light_') is False for o in lights('PMS_BgLight_'))
    clean()
    before = {o.name: o.as_pointer() for o in lights('PMS_BgLight_')}
    api.apply('camera_shot', 'front')
    api.apply('look', 'noir')
    assert {o.name: o.as_pointer() for o in lights('PMS_BgLight_')} == before, "camera / look must not rebuild them"
    api.apply('background', 'cyclorama_pure_white')        # rebuilt with the background
    assert {o.name: o.as_pointer() for o in lights('PMS_BgLight_')} != before
    assert pms.background_light == 'soft_wash'
    api.apply('lighting', 'rim_only')                      # studio lights separate
    assert len(lights('PMS_BgLight_')) == 2
    # hand edit protected like the other sections
    lights('PMS_BgLight_')[0].location.x += 1
    assert api.state()['modified'] == ['bglight']
    pms.bgl_power = 1.2
    assert api.state()['modified'] == ['bglight']
    out = api.apply('background_light', 'rim_glow')
    assert out['warnings'] and 'Background lights' in out['warnings'][0] and pms.background_light == 'soft_wash'
    api.apply('background_light', 'rim_glow', force=True)
    clean()
    api.remove_all()
    assert not [o for o in bpy.data.objects if o.name.startswith('PMS_')] and 'PMS_BgLights' not in bpy.data.collections
    return "6 presets, backdrop-only, scale free, rebuilt with background, live colour/power, hand edit flagged"


# ---------------------------------------------------------------------------------------------
@test("3 Preview Motion: applies the chosen preset, restores the previous state (animation, options, frame); Apply keeps it")
def preview_motion():
    sc, p = built(product_motion='spin_360_loop', camera_motion='push_in')
    api.apply('product_motion', 'spin_360_loop', turns=2)
    sc.frame_set(17)
    sig0, ov0, fr0 = core.signature(sc, 'animation'), api.state()['overrides'], sc.frame_current
    out = api.preview_start('product_motion', 'drop_impact')
    assert out['preview'] and api.state()['product_motion'] == 'drop_impact' and api.state()['preview']['preset'] == 'spin_360_loop'
    assert core.signature(sc, 'animation') != sig0
    clean()
    out = api.preview_stop()
    assert out['restored'] == 'spin_360_loop' and api.state()['product_motion'] == 'spin_360_loop'
    assert core.signature(sc, 'animation') == sig0 and api.state()['overrides'] == ov0 and sc.frame_current == fr0
    assert api.state()['preview'] is None and api.preview_stop() is None
    clean()
    # camera motion, then Apply keeps it
    api.preview_start('camera_motion', 'orbit_90')
    assert api.state()['camera_motion'] == 'orbit_90'
    api.preview_stop(keep=True)
    assert api.state()['camera_motion'] == 'orbit_90' and api.state()['preview'] is None and api.state()['built']['camera_motion'] == 'orbit_90'
    # the panel's choice (not built yet) is what a preview shows; stop goes back to what was BUILT
    sc.pms.camera_motion = 'pull_back'
    api.preview_start('camera_motion')
    assert api.state()['preview']['preset'] == 'orbit_90' and sc.camera.data
    api.preview_start('product_motion', 'flip')            # another preview: the first one is put back first
    assert api.state()['camera_motion'] == 'orbit_90' and api.state()['preview']['section'] == 'product_motion'
    api.preview_stop()
    assert api.state()['product_motion'] == 'spin_360_loop' and core.signature(sc, 'animation') == sig0
    # a section edited by hand is not touched without force
    core.info().root.keyframe_insert('scale', frame=5)
    out = api.preview_start('product_motion', 'flip')
    assert out['preview'] is False and out['warnings'] and api.state()['product_motion'] == 'spin_360_loop' and not api._PREVIEW
    raises(ValueError, api.preview_start, 'lighting')
    api.preview_start('product_motion', 'flip', force=True)
    assert api.state()['preview']
    api.remove_all()
    assert api.state()['preview'] is None
    # the operator (no viewport here: it applies, and the second call stops)
    sc, p = built(product_motion='spin_360_loop')
    sig0 = core.signature(sc, 'animation')
    sc.pms.product_motion = 'drop_impact'
    bpy.ops.pms.preview_motion('EXEC_DEFAULT', section='product_motion')
    assert api._PREVIEW and api.state()['product_motion'] == 'drop_impact'
    bpy.ops.pms.preview_motion('EXEC_DEFAULT', section='product_motion')
    assert not api._PREVIEW and api.state()['product_motion'] == 'spin_360_loop' and core.signature(sc, 'animation') == sig0
    sc.pms.product_motion = 'flip'
    bpy.ops.pms.preview_motion('EXEC_DEFAULT', section='product_motion')
    bpy.ops.pms.preview_apply('EXEC_DEFAULT')
    assert not api._PREVIEW and api.state()['product_motion'] == 'flip'
    return "start / stop / keep / hand-edit guard / operator toggle"


# ---------------------------------------------------------------------------------------------
@test("4 Render panel: Draft / Preview / Final settings, output path and format, still / animation setup (nothing rendered)")
def render_panel():
    sc, p = built()
    pms = sc.pms
    out = api.set_render('DRAFT')
    assert (sc.render.engine, sc.eevee.taa_render_samples, sc.render.resolution_percentage) == ('BLENDER_EEVEE', 16, 50), out
    assert pms.engine == 'BLENDER_EEVEE' and not sc.render.use_motion_blur
    api.apply('format', '1:1')                              # a rebuild keeps the percentage and the engine
    assert sc.render.resolution_percentage == 50 and sc.render.engine == 'BLENDER_EEVEE'
    api.set_render('PREVIEW')
    assert (sc.render.engine, sc.eevee.taa_render_samples, sc.render.resolution_percentage) == ('BLENDER_EEVEE', 64, 100)
    out = api.set_render('FINAL')
    c = sc.cycles
    assert sc.render.engine == 'CYCLES' and c.samples == 256 and c.use_adaptive_sampling and abs(c.adaptive_threshold - 0.01) < 1e-9
    assert c.use_denoising and c.denoiser == 'OPENIMAGEDENOISE' and not sc.render.use_motion_blur
    assert c.device == ('GPU' if render_settings.gpu_available() else 'CPU') and out['device'] == c.device
    out = api.set_render('FINAL', motion_blur=True)
    assert sc.render.use_motion_blur and (c.device != 'GPU' or out['warnings'])
    # the panel's own properties work as well (update callbacks)
    pms.render_motion_blur = False
    assert not sc.render.use_motion_blur
    pms.render_quality = 'DRAFT'
    assert sc.render.engine == 'BLENDER_EEVEE' and sc.render.resolution_percentage == 50
    # output
    out = api.set_render('FINAL', path='//out/', fmt='MP4', mode='animation')
    im, ff = sc.render.image_settings, sc.render.ffmpeg
    assert im.file_format == 'FFMPEG' and ff.format == 'MPEG4' and ff.codec == 'H264' and sc.render.filepath == '//out/animation_', out
    api.set_render(fmt='PNG', mode='animation')
    assert im.file_format == 'PNG' and sc.render.filepath == '//out/frame_' and im.color_depth == '16'   # final: 16 bit
    api.set_render('PREVIEW', mode='animation')
    assert im.color_depth == '8'
    # Custom: your own engine, samples and resolution
    out = api.set_render(engine='CYCLES', samples=500, percent=150, mode='animation')
    assert pms.render_quality == 'CUSTOM' and (sc.render.engine, c.samples, sc.render.resolution_percentage) == ('CYCLES', 500, 150), out
    assert c.use_denoising and im.color_depth == '16'
    api.apply('format', '16:9')                             # a rebuild keeps the custom percentage
    assert sc.render.resolution_percentage == 150
    pms.render_custom_engine = 'BLENDER_EEVEE'              # the panel's fields
    pms.render_samples = 40
    assert sc.render.engine == 'BLENDER_EEVEE' and sc.eevee.taa_render_samples == 40
    api.set_render('FINAL', mode='animation')
    api.set_render(mode='still')
    assert im.file_format == 'PNG' and sc.render.filepath == '//out/still'
    api.set_render(path='/tmp/x', fmt='MP4', mode='animation')
    assert sc.render.filepath == '/tmp/x/animation_'
    # remove_all gives the scene's percentage back
    api.remove_all()
    assert sc.render.resolution_percentage == 100 and 'pms_pct' not in sc
    # the panel exists with its buttons
    assert hasattr(bpy.types, 'PMS_PT_sub10') and bpy.types.PMS_PT_sub10.bl_label == "10. Render"
    assert hasattr(bpy.ops.pms, 'render')
    return "draft/preview/final, adaptive 0.01, OIDN, device " + c.device + ", MP4 H.264 / PNG, still"


# ---------------------------------------------------------------------------------------------
@test("5 dispersion lighting: 2 small-hard-source presets, warning outside Cycles, the product materials are never touched")
def dispersion():
    ids = ['dispersion_crystal_points', 'dispersion_backlit_prism']
    reg = presets.REGISTRY['lighting']
    sc = fresh()
    p = cube()
    mat = bpy.data.materials.new('Glass')
    mat.use_nodes = True
    p.data.materials.append(mat)
    snap = (mat.as_pointer(), len(mat.node_tree.nodes), [tuple(i.default_value) if hasattr(i.default_value, '__len__') else i.default_value
                                                       for i in mat.node_tree.nodes['Principled BSDF'].inputs if hasattr(i, 'default_value')])
    api.build(objects=[p], **W)
    for pid in ids:
        pr = reg[pid]
        assert pr.meta.get('needs_cycles') and 'Cycles' in pr.desc and 'ispersion' in pr.desc and pr.category == 'glass'
        small = [s for s in pr.data['lights'] if s['role'] != 'fill']
        assert len(small) >= 3 and all(max(s['size_f']) <= 0.1 for s in small), "sources must be small and hard"
        out = api.apply('lighting', pid)
        assert any('Cycles' in w and 'dispersion' in w for w in out['warnings']), out['warnings']
        out = api.apply('lighting', pid, engine='CYCLES')
        assert not [w for w in out['warnings'] if 'dispersion' in w], out['warnings']
        api.apply('lighting', pid, engine='BLENDER_WORKBENCH')
    api.apply('lighting', 'beauty_soft')
    assert not [w for w in api.apply('lighting', 'beauty_soft')['warnings'] if 'dispersion' in w]
    mat2 = bpy.data.materials['Glass']
    snap2 = (mat2.as_pointer(), len(mat2.node_tree.nodes), [tuple(i.default_value) if hasattr(i.default_value, '__len__') else i.default_value
                                                           for i in mat2.node_tree.nodes['Principled BSDF'].inputs if hasattr(i, 'default_value')])
    assert snap == snap2, "the product's material changed"
    return "2 presets, warning outside Cycles, materials untouched"


# ---------------------------------------------------------------------------------------------
@test("6 scene recipes: 16, only existing ids, apply_recipe / apply('recipe') / operator, overrides, nothing marked as edited")
def recipes():
    reg = presets.REGISTRY['recipe']
    assert len(reg) >= 16, len(reg)
    for rid, r in reg.items():
        d = r.data
        assert set(d) == set(api.RECIPE_FIELDS), (rid, set(d) ^ set(api.RECIPE_FIELDS))
        for sec in api.RECIPE_FIELDS:
            if sec != 'duration':
                assert d[sec] in presets.REGISTRY[sec], f"recipe {rid}: {sec}={d[sec]!r} does not exist"
        assert isinstance(d['duration'], int) and d['duration'] >= 12 and r.desc and r.category
    sc, p = built()
    for rid, r in reg.items():
        out = api.apply_recipe(rid)
        st = api.state()
        assert out['recipe'] == rid and st['recipe'] == rid
        for sec in api.RECIPE_FIELDS[:-1]:
            assert st[sec] == r.data[sec], (rid, sec)
        assert st['duration'] == r.data['duration'] and (sc.frame_end - sc.frame_start + 1) in (st['duration'], st['duration'] - 1)
        assert tuple(sc.render.resolution_x * 1 for _ in (0,))[0] == presets.REGISTRY['format'][r.data['format']].data['res'][0]
        assert st['engine'] == 'BLENDER_WORKBENCH' and st['modified'] == [], (rid, st['modified'])
    # overrides, the generic apply(), the operator
    api.apply_recipe('luxury_perfume', shot='macro', duration=100, look='noir')
    st = api.state()
    assert (st['camera_shot'], st['duration'], st['look'], st['lighting']) == ('macro', 100, 'noir', 'perfume_glow_key')
    raises(ValueError, api.apply_recipe, 'luxury_perfume', colour='red')
    raises(KeyError, api.apply_recipe, 'nope')
    assert api.state()['camera_shot'] == 'macro'
    out = api.apply('recipe', 'turntable_catalogue')
    assert out['recipe'] == 'turntable_catalogue' and api.state()['product_motion'] == 'spin_360_loop'
    sc.pms.recipe = 'food_warm'
    bpy.ops.pms.apply_recipe('EXEC_DEFAULT')
    assert api.state()['lighting'] == 'food_warm_side_deep' and api.state()['modified'] == []
    # live values start from the recipe's presets
    sc.pms.cam_lens = 200
    api.apply_recipe('food_warm')
    assert sc.pms.cam_lens == 85
    # a recipe on a hand edit: nothing overwritten without force
    ls = lights()
    ls[0].location.x += 1
    x = ls[0].location.x
    ptr = ls[0].as_pointer()
    out = api.apply_recipe('luxury_perfume')
    assert any('Lights edited' in w for w in out['warnings']) and bpy.data.objects[ls[0].name].as_pointer() == ptr
    assert bpy.data.objects[ls[0].name].location.x == x, "hand-edited light was overwritten"
    api.apply_recipe('luxury_perfume', force=True)
    assert api.state()['modified'] == [] and api.state()['lighting'] == 'perfume_glow_key'
    return f"{len(reg)} recipes applied, all ids exist"


# ---------------------------------------------------------------------------------------------
print("\n==== PMS LIVE TEST RESULTS ====")
for name, ok, msg in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}  {msg}")
fails = [r for r in RESULTS if not r[1]]
print(f"==== {len(RESULTS) - len(fails)}/{len(RESULTS)} passed ====")
sys.exit(1 if fails else 0)
