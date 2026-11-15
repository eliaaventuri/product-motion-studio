"""Headless test of the personal presets and scenes of Product Motion Studio (user_presets.py, capture.py):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tests/test_user_presets.py
Capture of the true state (hand edits + live values) on one scale, apply on another, round trip through the folder and a second
Blender, scenes, rename / update / delete, export / import, id conflicts, corrupt files, the catalogue. Uses a temporary folder
(PMS_USER_DIR) and never renders more than 128 px thumbnails (Workbench)."""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
USER = tempfile.mkdtemp(prefix='pms_user_')
os.environ['PMS_USER_DIR'] = USER

import bpy
from mathutils import Euler, Matrix, Vector

import product_motion_studio as pkg
from product_motion_studio import api, capture, core, live, presets, previews, props, user_presets

pkg.register()
RESULTS = []
W = dict(engine='BLENDER_WORKBENCH', duration=60)
BLENDER = bpy.app.binary_path


ONLY = os.environ.get('PMS_ONLY')                      # e.g. PMS_ONLY=5 runs the tests whose name starts with 5


def test(name):
    def deco(fn):
        if ONLY and not name.startswith(ONLY):
            return fn
        try:
            msg = fn()
            RESULTS.append((name, True, msg or ''))
        except Exception as e:                      # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def clean_user():
    for sub in os.listdir(USER):
        shutil.rmtree(os.path.join(USER, sub), ignore_errors=True)
    user_presets.load_all()


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def cube(size, loc, name='P'):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def natural(name):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', name)]


# --- what the scene looks like, measured from the objects (independent of capture.py) ----------------------------------
def light0():
    return sorted((o for o in bpy.data.collections['PMS_Lights'].all_objects if o.type == 'LIGHT'), key=lambda o: natural(o.name))[0]


def lights_fp(sub='PMS_Lights'):
    inf = core.info(bpy.context.scene)
    col = bpy.data.collections.get(sub)
    out = []
    for ob in sorted((o for o in (col.all_objects if col else ()) if o.type == 'LIGHT'), key=lambda o: natural(o.name)):
        mw, d = ob.matrix_world, ob.data
        loc, rot, sc = mw.decompose()
        out.append(dict(type=d.type, shape=d.shape if d.type == 'AREA' else '', pos=[(a - b) / inf.size for a, b in zip(loc, inf.center)],
                        rot=[x for row in rot.to_matrix() for x in row],
                        size=([d.size * sc.x / inf.size] + ([d.size_y * sc.y / inf.size] if d.shape in ('RECTANGLE', 'ELLIPSE') else [])) if d.type == 'AREA' else [d.shadow_soft_size / inf.size],
                        watts=d.energy / (1 if d.type == 'SUN' else inf.size ** 2), color=list(d.color), temp=d.temperature if d.use_temperature else 0,
                        only=ob.light_linking.receiver_collection is not None))
    return out


def world_fp():
    w = bpy.context.scene.world
    bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
    return [bg.inputs['Strength'].default_value, *bg.inputs['Color'].default_value[:3]]


def bg_fp():
    mat = bpy.data.objects['PMS_Background'].active_material
    nt = mat.node_tree
    ramp = next(n for n in nt.nodes if n.type == 'VALTORGB')
    mp = next(n for n in nt.nodes if n.type == 'MAPPING')
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    return dict(stops=[(e.position, *e.color) for e in ramp.color_ramp.elements], rot=list(mp.inputs['Rotation'].default_value),
                loc=list(mp.inputs['Location'].default_value), rough=bsdf.inputs['Roughness'].default_value,
                glow=nt.nodes['PMS_SelfLight'].inputs[1].default_value,
                grad=next(n for n in nt.nodes if n.type == 'TEX_GRADIENT').gradient_type)


def floor_fp():
    mat = bpy.data.objects['PMS_Floor'].active_material
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    return dict(color=list(bsdf.inputs['Base Color'].default_value), rough=bsdf.inputs['Roughness'].default_value,
                metal=bsdf.inputs['Metallic'].default_value, glow=mat.node_tree.nodes.get('PMS_SelfLight') is not None,
                emit=list(bsdf.inputs['Emission Color'].default_value))


def look_fp():
    sc = bpy.context.scene
    vs, ng = sc.view_settings, sc.compositing_node_group
    vals = []
    for n in sorted(ng.nodes, key=lambda n: (n.bl_idname, n.name)):
        for s in n.inputs:
            if hasattr(s, 'default_value') and not s.is_linked and not isinstance(s.default_value, str):
                v = s.default_value
                vals.append((n.bl_idname, s.name, list(v) if hasattr(v, '__len__') else v))
        if n.bl_idname == 'ShaderNodeValToRGB':
            vals.append(('ramp', [e.position for e in n.color_ramp.elements]))
    return dict(vt=vs.view_transform, look=vs.look, exp=vs.exposure, gamma=vs.gamma, nodes=vals,
                types=sorted(n.bl_idname for n in ng.nodes))


def cam_fp(distance=True):
    sc = bpy.context.scene
    inf = core.info(sc)
    cam, tgt = bpy.data.objects['PMS_Camera'], bpy.data.objects['PMS_Cam_Target']
    v = cam.matrix_world.translation - tgt.matrix_world.translation
    d = dict(lens=cam.data.lens, dof=cam.data.dof.use_dof, fstop=cam.data.dof.aperture_fstop,
             dir=list(v.normalized()), tz=(tgt.matrix_world.translation.z - inf.base_z) / inf.dims.z)
    if distance:
        d['dist'] = v.length / inf.size
    return d


def same(a, b, tol=2e-3, path=''):
    """Recursive comparison of dicts / lists / numbers (relative tolerance); raises with the path of the first difference."""
    if isinstance(a, dict):
        assert set(a) == set(b), f"{path}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            same(a[k], b[k], tol, f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, tol, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert math.isclose(a, b, rel_tol=tol, abs_tol=tol), f"{path}: {a} != {b}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


def rich_look():
    return next(i for i, p in presets.REGISTRY['look'].items()
                if all(p.data.get(k) for k in ('glare', 'lens', 'grade', 'vignette', 'grain')))


def make_rich(size=0.2, loc=(0, 0, 0.1), **build):
    """A studio with a bit of everything, then edited the way Elia would: live values, then by hand."""
    sc = fresh()
    p = cube(size, loc)
    api.build(objects=[p], shot='hero_34', lighting='beauty_soft', background='cyclorama_gradient_blue', background_light='soft_wash',
              floor='glossy', look=rich_look(), product_motion='spin_360_loop', camera_motion='push_in', **{**W, **build})
    s = size / 0.2
    api.set_live(cam_lens=120, cam_padding=0.1, cam_dof=True, cam_fstop=4.0, cam_focus=0.1, light_power=1.3, light_tint=(1.0, 0.9, 0.8),
                 light_rot=20, bg_color_a=(0.4, 0.2, 0.1), bg_roughness=0.4, bg_selflight=0.8, bg_rotation=15, bgl_power=1.5,
                 bgl_color=(0.9, 1.0, 1.0), floor_color=(0.5, 0.45, 0.4), floor_roughness=0.3, look_intensity=0.7, look_exposure=0.3)
    L = sorted((o for o in bpy.data.collections['PMS_Lights'].all_objects if o.type == 'LIGHT'), key=lambda o: natural(o.name))
    L[0].location = L[0].location + Vector((0.12 * s, -0.05 * s, 0.1 * s))               # moved
    L[1].rotation_euler.x += 0.35                                                       # rotated (rolled)
    L[2].scale = (1.4, 1.4, 1.4)                                                        # scaled
    L[3].data.energy *= 2.0                                                             # power
    L[3].data.color = (1.0, 0.5, 0.5)                                                   # colour
    L[3].data.use_temperature = False
    L[4].data.shape = 'DISK'                                                            # shape
    bg = next(n for n in bpy.data.objects['PMS_Background'].active_material.node_tree.nodes if n.type == 'VALTORGB')
    bg.color_ramp.elements[-1].color = (0.2, 0.9, 0.3, 1.0)                              # backdrop edited in the node tree
    fl = next(n for n in bpy.data.objects['PMS_Floor'].active_material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    fl.inputs['Metallic'].default_value = 0.3
    ng = sc.compositing_node_group
    glare = next(n for n in ng.nodes if n.bl_idname == 'CompositorNodeGlare')
    glare.inputs['Strength'].default_value = 0.77                                       # compositor values
    next(n for n in ng.nodes if n.bl_idname == 'ShaderNodeValToRGB').color_ramp.elements[0].position = 0.45   # vignette size
    bpy.data.objects['PMS_Cam_Pivot'].rotation_euler.z += math.radians(12)               # camera moved by hand
    bpy.context.view_layer.update()
    return sc


def snapshot_all():
    return dict(lights=lights_fp(), world=world_fp(), bgl=lights_fp('PMS_BgLights'), bg=bg_fp(), floor=floor_fp(), look=look_fp(),
                cam=cam_fp(distance=False))


SECTIONS_DATA = ('camera_shot', 'lighting', 'background_light', 'background', 'floor', 'look')


# =============================================================================================
@test("1 capture of hand edits + live values, saved on one scale, applied on another: the scene is equivalent")
def t_capture():
    clean_user()
    make_rich(0.2, (0, 0, 0.1))
    a = snapshot_all()
    assert len(a['lights']) == 5 and len(a['bgl']) == 2
    ids = {s: api.save_preset(s, f"Mine {s}", thumbnail=False)['id'] for s in SECTIONS_DATA + ('format',)}
    api.remove_all()
    cube(1.0, (1.5, -2.0, 0.5))                                      # another scale and place
    api.build(objects=[bpy.data.objects['P']], product_motion='spin_360_loop', **W)
    for s in ('camera_shot', 'lighting', 'background_light', 'background', 'floor', 'look'):
        api.apply(s, ids[s])
    b = snapshot_all()
    same(a, b)
    # live controls went back to their defaults: what was captured is the preset's own value now
    lv = api.state()['live']
    assert lv['light_power'] == 1.0 and tuple(lv['light_tint']) == (1.0, 1.0, 1.0) and lv['light_rot'] == 0.0, lv
    assert abs(lv['cam_lens'] - 120) < 1e-3 and lv['cam_dof'] and abs(lv['cam_fstop'] - 4) < 1e-3, lv
    return f"{len(a['lights'])} lights + {len(a['bgl'])} bg lights, look nodes {len(a['look']['nodes'])}"


@test("1b a camera that was not touched by hand keeps the fitted distance at another scale")
def t_cam_distance():
    clean_user()
    sc = fresh()
    cube(0.2, (0, 0, 0.1))
    api.build(objects=[bpy.data.objects['P']], shot='low_angle', **W)
    api.set_live(cam_lens=135, cam_padding=0.05)
    a = cam_fp()
    pid = api.save_preset('camera_shot', 'Low tele', thumbnail=False)['id']
    api.remove_all()
    cube(1.0, (3, 0, 0.5))
    api.build(objects=[bpy.data.objects['P']], **W)
    api.apply('camera_shot', pid)
    same(a, cam_fp())


@test("1c fidelity: every stock preset, saved untouched as a personal preset and applied, builds the same studio")
def t_stock_identity():
    clean_user()
    fresh()
    cube(0.3, (0, 0, 0.15))
    api.build(objects=[bpy.data.objects['P']], **W)
    fps = {'camera_shot': lambda: cam_fp(), 'lighting': lambda: dict(l=lights_fp(), w=world_fp()),
           'background_light': lambda: lights_fp('PMS_BgLights'), 'look': look_fp,
           'background': lambda: bg_fp() if bpy.data.objects['PMS_Background'].active_material.node_tree.nodes.get('PMS_SelfLight') and
           any(n.type == 'VALTORGB' for n in bpy.data.objects['PMS_Background'].active_material.node_tree.nodes) else None,
           'floor': lambda: floor_fp() if bpy.data.objects.get('PMS_Floor') else None}
    n = 0
    for section, fp in fps.items():
        for pid in [i for i, p in presets.REGISTRY[section].items() if not p.meta.get('user')]:
            if section == 'background' and presets.get(section, pid).data.get('kind') == 'image':
                continue
            api.apply(section, pid, force=True)
            a = fp()
            uid = api.save_preset(section, f"id {pid}", thumbnail=False)['id']
            api.apply(section, uid, force=True)
            try:
                same(a, fp(), 3e-3, f"{section}/{pid}")
            finally:
                api.delete_user('preset', f"{section}/{uid}")
            n += 1
    return f"{n} stock presets round-trip"


@test("2 function sections keep the base id + options; applying a personal preset runs the same animation")
def t_function():
    clean_user()
    sc = fresh()
    cube(0.2, (0, 0, 0.1))
    api.build(objects=[bpy.data.objects['P']], **W)
    api.apply('product_motion', 'spin_360_loop', turns=2)
    root = bpy.data.objects[core.ROOT_NAME]
    keys = lambda: [(k.co.x, round(k.co.y, 4)) for fc in sorted(root.animation_data.action.layers[0].strips[0].channelbag(root.animation_data.action_slot).fcurves, key=lambda f: (f.data_path, f.array_index)) for k in fc.keyframe_points]  # noqa: E731
    ref = keys()
    api.apply('camera_motion', 'orbit_90')
    r = api.save_preset('product_motion', 'Two turns', thumbnail=False)
    r2 = api.save_preset('camera_motion', 'My orbit', thumbnail=False)
    e = json.load(open(r['file']))
    assert e['base'] == 'spin_360_loop' and e['opts'] == {'turns': 2} and 'data' not in e, e
    api.apply('product_motion', 'luxury_drift')
    assert keys() != ref
    api.apply('product_motion', r['id'])
    same(keys(), ref)
    p = presets.get('product_motion', r['id'])
    assert p.category == 'My Presets' and p.meta.get('loop') is True and p.fn is presets.get('product_motion', 'spin_360_loop').fn
    api.apply('camera_motion', 'static')
    api.apply('camera_motion', r2['id'])
    assert api.state()['camera_motion'] == r2['id'] and api.state()['built']['camera_motion'] == r2['id']
    # a personal preset saved from a personal preset still points at the stock base
    r3 = api.save_preset('product_motion', 'Two turns again', thumbnail=False)
    assert json.load(open(r3['file']))['base'] == 'spin_360_loop'
    # an override on top of the personal options wins
    api.apply('product_motion', r['id'], turns=3)
    assert api.state()['overrides']['product_motion'] == {'turns': 3}


@test("3 they are in the registry, the lists, the Category filter and have a thumbnail; ids user_...; files in the user folder")
def t_registry():
    clean_user()
    make_rich()
    r = api.save_preset('lighting', 'Studio One')
    assert r['id'] == 'user_studio_one' and r['file'].startswith(USER) and os.path.isfile(r['file']), r
    jpg = r['file'][:-5] + '.jpg'
    assert os.path.isfile(jpg)
    img = bpy.data.images.load(jpg)
    assert tuple(img.size) == (128, 128), tuple(img.size)
    bpy.data.images.remove(img)
    assert not any(user_presets.PKG_DIR in f for f in (r['file'], jpg))
    assert ('user_studio_one', 'Studio One', 'My Presets') in api.list_presets('lighting')['lighting']
    pms = bpy.context.scene.pms
    pms.lighting = 'user_studio_one'                                  # the enum accepts it (its items come from the registry)
    assert pms.lighting == 'user_studio_one'
    pms.lighting_cat = 'My Presets'                                   # the Category filter lists only the personal ones
    assert props.visible_ids('lighting', 'My Presets') == ['user_studio_one']
    assert raises(TypeError, setattr, pms, 'lighting', 'beauty_soft')
    pms.lighting = 'user_studio_one'
    pms.lighting_cat = 'ALL'
    pms.lighting = 'beauty_soft'
    assert previews._user.get('lighting/user_studio_one') is not None     # (icon ids are 0 in background mode)
    assert 'My Presets' in props.categories('lighting') and 'My Presets' in props.categories('floor') and 'My Presets' not in props.categories('recipe')
    # floor and format are lists too
    api.save_preset('floor', 'My Floor', thumbnail=False)
    api.save_preset('format', 'My Format', thumbnail=False)
    for sec, pid in (('floor', 'user_my_floor'), ('format', 'user_my_format')):
        api.apply(sec, pid)
        assert getattr(pms, sec) == pid
    # every section accepts a personal id (the enum numbers are the crc of the id: no clash)
    assert len({props._num(i) for i in presets.REGISTRY['lighting']}) == len(presets.REGISTRY['lighting'])
    # the dir is not the add-on's
    old = os.environ['PMS_USER_DIR']
    os.environ['PMS_USER_DIR'] = os.path.join(user_presets.PKG_DIR, 'inside')
    try:
        assert 'add-on folder' in raises(RuntimeError, user_presets.user_dir)
    finally:
        os.environ['PMS_USER_DIR'] = old
    del os.environ['PMS_USER_DIR']
    try:
        fallback = user_presets.user_dir()
    finally:
        os.environ['PMS_USER_DIR'] = old
    assert fallback.endswith('pms_user_presets') or 'user_presets' in fallback, fallback
    return os.path.relpath(r['file'], USER)


@test("4 round trip: folder -> reload -> a second Blender; corrupt, wrong-format and wrong-base files are skipped with a warning")
def t_roundtrip():
    clean_user()
    make_rich()
    ids = {s: api.save_preset(s, f"RT {s}")['id'] for s in SECTIONS_DATA + ('format', 'product_motion', 'camera_motion')}
    sc = api.save_scene('RT scene')
    before = api.list_user()
    assert len(before['presets']) == 9 and len(before['scenes']) == 1 and not before['warnings'], before
    # garbage next to the good files
    open(os.path.join(USER, 'presets', 'lighting', 'broken.json'), 'w').write('{ not json')
    json.dump(dict(pms_format=99, kind='preset', section='lighting', id='user_future', name='Future', data={'lights': []}),
              open(os.path.join(USER, 'presets', 'lighting', 'user_future.json'), 'w'))
    json.dump(dict(pms_format=1, kind='preset', section='product_motion', id='user_ghost', name='Ghost', base='no_such_motion', opts={}),
              open(os.path.join(USER, 'presets', 'product_motion', 'user_ghost.json'), 'w'))
    after = api.reload_user()
    assert len(after['presets']) == 9 and len(after['scenes']) == 1, after
    w = ' | '.join(after['warnings'])
    assert 'broken.json' in w and 'newer version' in w and 'no_such_motion' in w and len(after['warnings']) == 3, after['warnings']
    assert 'user_ghost' not in presets.REGISTRY['product_motion'] and 'user_future' not in presets.REGISTRY['lighting']
    # a fresh Blender process reads the same folder
    code = ("import sys, json; sys.path.insert(0, %r); import bpy; import product_motion_studio as pkg; pkg.register(); "
            "from product_motion_studio import api; u = api.list_user(); "
            "print('ROUNDTRIP', json.dumps([sorted(p['id'] for p in u['presets']), [s['id'] for s in u['scenes']], len(u['warnings'])]))" % os.path.join(HERE, '..'))
    out = subprocess.run([BLENDER, '-b', '--factory-startup', '--python-expr', code], capture_output=True, text=True,
                         env=dict(os.environ, PMS_USER_DIR=USER)).stdout
    got = json.loads(re.search(r'ROUNDTRIP (.*)', out).group(1))
    assert got[0] == sorted(p['id'] for p in after['presets']) and got[1] == [sc['id']] and got[2] == 3, got
    return "second Blender sees 9 presets + 1 scene, 3 files skipped"


@test("5 a whole scene: save, change everything, apply -> equivalent (format, frames, fps, engine, render settings, flags)")
def t_scene():
    clean_user()
    sc = make_rich(animate_lighting=True, isolate_lights=False)          # (the highlight sweep is keyed on the light rig)
    pms = sc.pms
    api.set_render('PREVIEW', motion_blur=True)
    pms.render_format = 'PNG'
    api.apply('format', '9:16', duration=90, fps=30)
    api.apply('look', rich_look())
    expected = dict(snap=snapshot_all(), res=(sc.render.resolution_x, sc.render.resolution_y), fps=sc.render.fps,
                    rng=(sc.frame_start, sc.frame_end), engine=sc.render.engine, flags=(pms.animate_lighting, pms.isolate_lights),
                    blur=sc.render.use_motion_blur, fmt=pms.render_format, quality=pms.render_quality)
    res = api.save_scene('Hero Look')
    sid = res['id']
    assert sid == 'user_scene_hero_look' and os.path.isfile(res['file']) and os.path.isfile(res['file'][:-5] + '.jpg')
    e = json.load(open(res['file']))
    assert e['pms_format'] == 1 and set(e['sections']) == set(user_presets.SCENE_SECTIONS) and e['settings']['fps'] == 30, e['settings']
    # change everything
    api.apply_recipe('turntable_catalogue')
    api.apply('format', '1:1', duration=50, fps=24, animate_lighting=False, isolate_lights=True, force=True)
    api.set_render('DRAFT', motion_blur=False)
    api.set_live(light_power=0.5)
    out = api.apply_scene(sid, force=True)
    assert not [w for w in out['warnings'] if 'edited by hand' in w], out['warnings']
    now = dict(snap=snapshot_all(), res=(sc.render.resolution_x, sc.render.resolution_y), fps=sc.render.fps,
               rng=(sc.frame_start, sc.frame_end), engine=sc.render.engine, flags=(pms.animate_lighting, pms.isolate_lights),
               blur=sc.render.use_motion_blur, fmt=pms.render_format, quality=pms.render_quality)
    same(expected, now)
    st = api.state()
    assert st['user']['applied_scene'] == sid and st['user']['scenes'] == 1 and st['product_motion'] == f"{sid}__product_motion"
    assert presets.get('lighting', st['lighting']).meta.get('hidden')
    assert st['lighting'] not in [i for i, _, _ in api.list_presets('lighting')['lighting']]
    # the same scene on a product of another scale
    api.remove_all()
    cube(1.0, (2, 2, 0.5))
    api.build(objects=[bpy.data.objects['P']], **W)
    api.apply_scene(sid)
    same(expected['snap'], snapshot_all())
    return f"{len(e['sections'])} sections, 30 fps 9:16"


@test("5b a section edited by hand is not overwritten by Apply Scene unless forced")
def t_scene_hand():
    clean_user()
    sc = make_rich()
    sid = api.save_scene('Hand', thumbnail=False)['id']
    api.apply_recipe('turntable_catalogue', force=True)
    light = light0()
    light.data.energy *= 3
    keep = light.data.energy
    out = api.apply_scene(sid)
    assert any('Lights edited by hand' in w for w in out['warnings']), (out['warnings'], core.modified(sc, 'lighting'))
    assert light0().data.energy == keep
    api.apply_scene(sid, force=True)
    assert abs(light0().data.energy - keep) > 1e-6
    light0().data.energy *= 2                                  # edited again: the panel asks before overwriting (modified_text)
    assert 'lights' in api.modified_text(set(api.STEPS[1:]), sc), api.modified_text(set(api.STEPS[1:]), sc)


@test("6 rename / update / delete, for presets and scenes; delete puts the default back where it was chosen")
def t_manage():
    clean_user()
    sc = make_rich()
    pms = sc.pms
    r = api.save_preset('lighting', 'Old Name', thumbnail=False)
    pid = r['id']
    assert api.rename_user('preset', pid, 'New Name')['name'] == 'New Name'
    assert presets.get('lighting', pid).name == 'New Name' and json.load(open(r['file']))['name'] == 'New Name'
    assert pid == 'user_old_name'                                   # the id does not change
    # update: overwrite with the state now
    first = json.load(open(r['file']))['data']['lights'][0]['power_ref']
    light0().data.energy *= 2
    api.update_user('preset', pid, thumbnail=False)
    e = json.load(open(r['file']))
    assert abs(e['data']['lights'][0]['power_ref'] / first - 2.0) < 1e-3 and e['name'] == 'New Name' and 'updated' in e
    assert api.list_user()['presets'][0]['id'] == pid and len(api.list_user()['presets']) == 1
    # delete: the section that had it selected is back to its default
    api.apply('lighting', pid, force=True)
    assert pms.lighting == pid
    out = api.delete_user('preset', f'lighting/{pid}')
    assert out['deleted'] == {'lighting': [pid]} and not os.path.exists(r['file']) and not os.path.exists(r['file'][:-5] + '.jpg')
    assert pms.lighting == props.DEFAULTS['lighting'] and pid not in presets.REGISTRY['lighting']
    assert 'unknown personal preset' in raises(ValueError, api.delete_user, 'preset', pid)
    assert 'kind must be' in raises(ValueError, api.delete_user, 'thing', pid)
    # scenes
    s = api.save_scene('Scene One', thumbnail=False)
    sid = s['id']
    api.rename_user('scene', sid, 'Scene Uno')
    assert user_presets.get_scene(sid)['name'] == 'Scene Uno' and presets.get('lighting', f'{sid}__lighting').name == 'Scene Uno'
    api.apply_scene(sid, force=True)
    n_lights = len(bpy.data.collections['PMS_Lights'].all_objects)
    light0().data.energy *= 4
    api.update_user('scene', sid, thumbnail=False)
    assert json.load(open(s['file']))['sections']['lighting']['data']['lights'][0]['power_ref'] > 0 and len(api.list_user()['scenes']) == 1
    assert pms.user_scene == sid
    api.delete_user('scene', sid)
    assert not os.path.exists(s['file']) and not api.list_user()['scenes'] and pms.lighting == props.DEFAULTS['lighting']
    assert not any(p for sec in presets.SECTIONS for pid2, p in presets.REGISTRY[sec].items() if pid2.startswith(sid))
    # names stay unique inside a section, ids too
    a = api.save_preset('look', 'Same', thumbnail=False)
    b = api.save_preset('look', 'Same', thumbnail=False)
    assert a['id'] != b['id'] and a['name'] != b['name'], (a, b)
    assert 'give the preset a name' in raises(ValueError, api.save_preset, 'look', '  ', thumbnail=False)
    assert 'cannot save' in raises(ValueError, api.save_preset, 'recipe', 'x')
    return n_lights


@test("7 export -> import into a clean folder (thumbnails travel); conflicts get renamed; bad entries are skipped with a message")
def t_export_import():
    clean_user()
    make_rich()
    for s in ('lighting', 'background', 'product_motion'):
        api.save_preset(s, f"Share {s}")
    api.save_scene('Share scene')
    bundle = os.path.join(tempfile.mkdtemp(), 'share.json')
    out = api.export_user(bundle)
    assert out == dict(path=bundle, presets=3, scenes=1), out
    data = json.load(open(bundle))
    assert data['kind'] == 'bundle' and data['pms_format'] == 1 and len(data['thumbs']) == 4, list(data['thumbs'])
    part = api.export_user(bundle + '.one', ['lighting/user_share_lighting'])
    assert part['presets'] == 1 and part['scenes'] == 0
    assert 'nothing to export' in raises(ValueError, api.export_user, bundle + '.x', ['nope'])
    listed = api.list_user()
    # a clean folder (another "friend")
    other = tempfile.mkdtemp(prefix='pms_friend_')
    os.environ['PMS_USER_DIR'] = other
    try:
        api.reload_user()
        assert not api.list_user()['presets']
        res = api.import_user(bundle)
        assert len(res['presets']) == 3 and len(res['scenes']) == 1 and not res['renamed'] and not res['errors'], res
        again = api.list_user()
        assert sorted(p['id'] for p in again['presets']) == sorted(p['id'] for p in listed['presets']) and not again['warnings']
        assert os.path.isfile(os.path.join(other, 'presets', 'lighting', 'user_share_lighting.jpg')) and previews._user.get('lighting/user_share_lighting') is not None
        assert os.path.isfile(os.path.join(other, 'scenes', 'user_scene_share_scene.jpg'))
        # importing it again: ids in conflict are renamed (and names made unique), nothing is overwritten
        res2 = api.import_user(bundle)
        assert len(res2['presets']) == 3 and len(res2['scenes']) == 1 and len(res2['renamed']) == 4, res2
        assert res2['renamed']['lighting/user_share_lighting'] == 'user_share_lighting_2'
        names = [p['name'] for p in api.list_user()['presets'] if p['section'] == 'lighting']
        assert len(set(names)) == 2, names
        assert presets.get('lighting', 'user_share_lighting_2').category == 'My Presets'
        assert user_presets.get_scene('user_scene_share_scene_2')['name'] != user_presets.get_scene('user_scene_share_scene')['name']
        # bad content: a base that does not exist, a wrong schema, a newer format, plain garbage
        bad = dict(data)
        bad['presets'] = data['presets'] + [
            dict(pms_format=1, kind='preset', section='camera_motion', id='user_gone', name='Gone', base='removed_in_v9', opts={}),
            dict(pms_format=1, kind='preset', section='lighting', id='user_wrong', name='Wrong', data={'lights': [{'az': 'x'}]}),
            dict(pms_format=7, kind='preset', section='look', id='user_new', name='New', data={})]
        bad['scenes'] = [dict(data['scenes'][0], id='user_scene_bad', name='Bad scene',
                              sections=dict(data['scenes'][0]['sections'], camera_motion=dict(base='removed_in_v9', opts={})))]
        json.dump(bad, open(bundle + '.bad', 'w'))
        res3 = api.import_user(bundle + '.bad')
        msgs = ' | '.join(res3['errors'])
        assert len(res3['errors']) == 4 and 'removed_in_v9' in msgs and "'az' must be a number" in msgs and 'newer version' in msgs, res3['errors']
        assert 'Bad scene' in msgs and len(res3['presets']) == 3 and not res3['scenes']
        open(bundle + '.junk', 'w').write('[1, 2')
        assert 'not a PMS file' in raises(ValueError, api.import_user, bundle + '.junk')
        json.dump(dict(pms_format=3, kind='bundle'), open(bundle + '.fut', 'w'))
        assert 'newer version' in raises(ValueError, api.import_user, bundle + '.fut')
        # a single preset file is accepted too
        single = os.path.join(other, 'presets', 'lighting', 'user_share_lighting.json')
        assert len(api.import_user(single)['presets']) == 1
    finally:
        os.environ['PMS_USER_DIR'] = USER
        api.reload_user()
    return f"{len(again['presets'])} presets + 1 scene across folders; 4 bad entries skipped"


@test("8 the panel's operators (save, rename, update, delete, scene, reload, export, import) work and report errors")
def t_operators():
    clean_user()
    sc = make_rich()
    pms = sc.pms
    assert bpy.ops.pms.save_preset('EXEC_DEFAULT', section='lighting', name='Op Light') == {'FINISHED'}
    assert 'user_op_light' in presets.REGISTRY['lighting']
    api.apply('lighting', 'user_op_light', force=True)
    assert bpy.ops.pms.rename_user('EXEC_DEFAULT', section='lighting', name='Op Light 2') == {'FINISHED'}
    assert presets.get('lighting', 'user_op_light').name == 'Op Light 2'
    assert bpy.ops.pms.update_user('EXEC_DEFAULT', section='lighting') == {'FINISHED'}
    assert bpy.ops.pms.save_scene('EXEC_DEFAULT', name='Op Scene') == {'FINISHED'} and pms.user_scene == 'user_scene_op_scene'
    assert bpy.ops.pms.apply_scene('EXEC_DEFAULT', force=True) == {'FINISHED'} and api.state()['user']['applied_scene'] == 'user_scene_op_scene'
    path = os.path.join(tempfile.mkdtemp(), 'op.json')
    assert bpy.ops.pms.export_user('EXEC_DEFAULT', filepath=path) == {'FINISHED'} and os.path.isfile(path)
    assert bpy.ops.pms.export_user('EXEC_DEFAULT', filepath=path + '1', ids='scene/user_scene_op_scene') == {'FINISHED'}
    assert json.load(open(path + '1'))['presets'] == [] and len(json.load(open(path + '1'))['scenes']) == 1
    assert bpy.ops.pms.import_user('EXEC_DEFAULT', filepath=path) == {'FINISHED'}
    assert 'user_op_light_2' in presets.REGISTRY['lighting']
    assert bpy.ops.pms.reload_user('EXEC_DEFAULT') == {'FINISHED'}
    assert bpy.ops.pms.delete_user('EXEC_DEFAULT', section='scene') == {'FINISHED'}
    assert 'user_scene_op_scene' not in [e['id'] for e in api.list_user()['scenes']] and pms.lighting == props.DEFAULTS['lighting']
    api.apply('lighting', 'user_op_light', force=True)
    assert bpy.ops.pms.delete_user('EXEC_DEFAULT', section='lighting') == {'FINISHED'}       # the chosen one (user_op_light)
    assert 'user_op_light' not in presets.REGISTRY['lighting'] and pms.lighting == props.DEFAULTS['lighting']
    # errors: reported, not raised
    pms.property_unset('user_scene')
    for text, op, kw in (("Choose a personal scene first", bpy.ops.pms.apply_scene, {}),
                         ("cannot save", bpy.ops.pms.save_preset, dict(section='recipe', name='x')),
                         ("No such file", bpy.ops.pms.import_user, dict(filepath=path + '.missing')),
                         ("unknown personal preset", bpy.ops.pms.delete_user, dict(section='lighting'))):   # a stock preset: not deletable
        assert text in raises(RuntimeError, op, 'EXEC_DEFAULT', **kw), text
    undoable = all('UNDO' in getattr(bpy.types, f"PMS_OT_{n}").bl_options and 'REGISTER' in getattr(bpy.types, f"PMS_OT_{n}").bl_options
                   for n in ('save_preset', 'update_user', 'rename_user', 'delete_user', 'save_scene', 'apply_scene', 'reload_user',
                             'export_user', 'import_user'))
    assert undoable
    # the descriptions say what is (not) captured
    d = bpy.types.PMS_OT_save_preset.description(bpy.context, type('P', (), {'section': 'product_motion'})())
    assert 'NOT saved' in d


@test("9 nothing personal in the catalogue; stock registry and thumbnails untouched; state() reports them")
def t_catalog():
    clean_user()
    make_rich()
    api.save_preset('lighting', 'Catalogue Test', thumbnail=False)
    api.save_preset('product_motion', 'Catalogue Motion', thumbnail=False)
    api.save_scene('Catalogue Scene', thumbnail=False)
    out = os.path.join(tempfile.mkdtemp(), 'cat.md')
    os.environ['PMS_CATALOG_OUT'] = out
    import runpy
    runpy.run_path(os.path.join(HERE, '..', 'tools', 'export_catalog.py'), run_name='cat')
    text = open(out).read()
    assert 'user_catalogue' not in text and 'Catalogue Test' not in text and 'My Presets' not in text and 'user_scene' not in text
    n_stock = sum(1 for sec in presets.SECTIONS for pid in presets.REGISTRY[sec] if not pid.startswith('user_'))
    assert f'Total presets: {n_stock}.' in text, (n_stock, re.search(r'Total presets: \d+', text).group(0))
    st = api.state()['user']
    assert st['presets'] == {'product_motion': 1, 'lighting': 1} and st['scenes'] == 1, st
    assert not any(f.startswith(user_presets.PKG_DIR) for f in (m.meta.get('file') or '' for m in user_presets.user_presets()))
    assert previews.count() == 193 + 0 or previews.count() > 150           # the stock thumbnails are the pack's own pcoll
    assert not [f for f in os.listdir(os.path.join(user_presets.PKG_DIR, 'thumbs', 'lighting')) if 'user_' in f]


@test("10 errors are clear: no product, unknown section / scene")
def t_errors():
    clean_user()
    fresh()
    assert 'prepare a product' in raises(RuntimeError, api.save_scene, 'x')
    assert 'unknown personal scene' in raises(KeyError, api.apply_scene, 'user_scene_nope')
    assert 'unknown personal scene' in raises(KeyError, api.delete_user, 'scene', 'user_scene_nope')
    r = api.save_preset('format', 'Fmt only', thumbnail=False)              # needs no product
    assert json.load(open(r['file']))['data']['res'] == [1920, 1080]
    assert api.save_preset('lighting', 'No product', thumbnail=False)['id'] == 'user_no_product'     # not built: the chosen preset is copied


@test("11 enum numbers of the plain sections (floor, format): files saved with the old position numbers are migrated")
def t_migrate():
    clean_user()
    sc = fresh()
    pms = sc.pms
    ids = [i for i in presets.REGISTRY['floor']]
    pms['floor'] = 2                                                         # what a file saved by the old static enum holds
    pms['format'] = 1
    props.migrate()
    assert pms.floor == ids[2] and pms.format == list(presets.REGISTRY['format'])[1], (pms.floor, pms.format)
    pms['floor'] = 7777777
    props.migrate()
    assert pms.floor == props.DEFAULTS['floor']



@test("12 deleting the personal scene in use: the sections go back to the presets it was saved from, a later build keeps the format")
def t_delete_in_use():
    sc = fresh()
    p = cube(0.2, (0, 0, 0.1))
    api.apply_recipe('beverage_can_cool', objects=[p])
    res0 = (sc.render.resolution_x, sc.render.resolution_y)
    sid = api.save_scene('In Use')['id']
    api.apply_scene(sid)
    api.delete_user('scene', sid)
    pms = sc.pms
    assert (pms.format, pms.lighting, pms.look) == ('1:1', 'metal_long_strips', 'clean_commercial'), (pms.format, pms.lighting, pms.look)
    api.apply('camera_motion', 'push_in_slow')
    assert (sc.render.resolution_x, sc.render.resolution_y) == res0, (sc.render.resolution_x, sc.render.resolution_y)
    return f"format kept {res0}"


@test("13 a recipe over lights edited by hand: the warning names the preset the scene still has")
def t_hand_kept_name():
    sc = fresh()
    p = cube(0.2, (0, 0, 0.1))
    api.apply_recipe('beverage_can_cool', objects=[p])
    L = next(o for o in bpy.data.collections['PMS_Lights'].all_objects if o.type == 'LIGHT')
    L.location.z += 0.1
    w = api.apply_recipe('minimal_scandinavian')['warnings']
    assert any('Lights edited by hand' in x and 'Metal Long Strips' in x for x in w), w
    return w[0]


@test("14 a new fps keeps the length in seconds (panel and API); an unknown preset suggests the right id")
def t_fps_seconds():
    sc = fresh()
    p = cube(0.2, (0, 0, 0.1))
    api.build(objects=[p], **{**W, 'duration': 96})
    sc.pms.fps = 30                                         # the panel field
    assert sc.pms.duration == 120 and sc.frame_end - sc.frame_start + 1 == 120, (sc.pms.duration, sc.frame_start, sc.frame_end)
    api.apply('camera_motion', 'push_in', fps=24)
    assert sc.pms.duration == 96 and sc.render.fps == 24, (sc.pms.duration, sc.render.fps)
    api.apply('camera_motion', 'push_in', fps=60, duration=100)  # explicit duration wins
    assert sc.pms.duration == 100
    try:
        api.apply('camera_motion', 'orbit_360')
    except KeyError as e:
        assert "did you mean 'orbit_360_loop'" in str(e), e
    else:
        raise AssertionError("no error")
    return "96 f @24 -> 120 f @30 -> 96 f @24"


@test("15 a build that fails with personal scenes saved but none chosen: every setting goes back, no second error")
def t_rollback_no_scene():
    import contextlib
    import io
    sc = fresh()
    p = cube(0.2, (0, 0, 0.1))
    api.build(objects=[p], **W)
    api.save_scene('Rollback Test', thumbnail=False)
    sc.pms.property_unset('user_scene')                     # as in a new file: personal scenes exist, none is chosen
    assert sc.pms.user_scene == '', sc.pms.user_scene
    before = api._snapshot(sc.pms)
    other = next(k for k in presets.REGISTRY['lighting'] if k != sc.pms.lighting)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        msg = raises(RuntimeError, api.build, objects=[], lighting=other, **W)
    after = api._snapshot(sc.pms)
    clean_user()
    assert 'no product' in msg, msg
    assert 'Traceback' not in err.getvalue(), err.getvalue()[-400:]
    diff = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not diff, [(k, before.get(k), after.get(k)) for k in diff]
    assert bpy.data.objects.get(core.ROOT_NAME), "the previous build was removed"
    return f"lighting back to {sc.pms.lighting}, no error while restoring"

print("RESULTS")
bad = 0
for name, ok, msg in RESULTS:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{msg}]" if msg else ''))
    bad += not ok
print(f"{len(RESULTS) - bad}/{len(RESULTS)} passed")
shutil.rmtree(USER, ignore_errors=True)
sys.exit(1 if bad else 0)
