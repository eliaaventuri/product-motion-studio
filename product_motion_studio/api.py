"""PMS API for Claude / scripts. Same functions the UI operators call (no duplicated logic).

    import product_motion_studio.api as pms      # or bl_ext.user_default.product_motion_studio.api
    pms.list_presets()                           # {section: [(id, name, category), ...]}
    pms.build(objects=None, shot='hero_34', product_motion='luxury_drift', camera_motion='push_in',
              lighting='beauty_soft', background='cyclorama_studio_grey', floor='seamless', format='16:9',
              look='clean_commercial', duration=200, fps=24, engine='CYCLES')
    pms.apply('lighting', 'rim_only')            # rebuild one section (and what depends on it)
    pms.apply('product_motion', 'spin_360_loop', turns=2, duration=240)   # overrides: preset options / global settings
    pms.add_objects([bpy.data.objects['Strap']])   # more objects into the prepared product
    pms.apply_recipe('luxury_perfume', shot='macro')   # a complete style (motion, shot, lights, background, look, format, duration)
    pms.set_live(cam_lens=100, cam_padding=-0.3, light_power=1.5, look_intensity=0.7)   # live controls (see live.py)
    pms.set_render('FINAL', fmt='MP4', mode='animation')   # Render panel settings (nothing is rendered)
    pms.render_pack('angles', shots=['front', 'side'])   # Render pack: same studio, multiple times (then restored)
    pms.preview_start('product_motion', 'flip'); pms.preview_stop()   # Preview Motion logic (the panel plays it)
    pms.save_preset('lighting', 'My Key Light'); pms.save_scene('Hero look')   # personal presets / scenes (user_presets.py)
    pms.apply_scene('user_scene_hero_look'); pms.list_user(); pms.export_user(path); pms.import_user(path)
    pms.remove_all();  pms.state()

Sections the user edited by hand (moved light, lens, keys, nodes) are never overwritten silently: build/apply/run skip them
and return a warning; force=True overwrites. Everything is validated before the scene is touched and a failing step puts
props, overrides and scene back (transaction).
"""

import difflib
import json
import math
import os
import traceback

import bpy
from . import (build_animation, build_background, build_bglight, build_camera, build_compositing, build_floor,
               build_format, build_lighting, build_prepare, capture, core, coverage, live, presets, props, render_settings,
               user_presets)


STEPS = ('prepare', 'format', 'animation', 'camera', 'lighting', 'background', 'floor', 'bglight', 'compositing')
_RUN = {'format': build_format.build, 'animation': build_animation.build, 'camera': build_camera.build,
        'lighting': build_lighting.build, 'background': build_background.build,
        'floor': build_floor.build, 'bglight': build_bglight.build, 'compositing': build_compositing.build}
# the step a preset section builds itself, and what else must be rebuilt after it (format sets frame_end: loops stop one
# frame early; the frame fit of an image background follows the camera: see _expand)
OWN = {'product_motion': 'animation', 'camera_shot': 'camera', 'camera_motion': 'camera', 'lighting': 'lighting',
       'background': 'background', 'background_light': 'bglight', 'floor': 'floor', 'format': 'format', 'look': 'compositing'}
# the presets each step builds from (recorded in pms.built: what Preview Motion puts back)
BUILT = {'format': ('format',), 'animation': ('product_motion',), 'camera': ('camera_shot', 'camera_motion'),
         'lighting': ('lighting',), 'background': ('background',), 'floor': ('floor',), 'bglight': ('background_light',),
         'compositing': ('look',)}
PREVIEWABLE = ('product_motion', 'camera_motion')
DEPENDENTS = {
    'product_motion': ('format', 'animation', 'camera'),
    'camera_shot': ('camera',),
    'camera_motion': ('format', 'camera'),
    'lighting': ('lighting',),
    'background': ('background', 'floor', 'bglight'),
    'background_light': ('bglight',),
    'floor': ('background', 'floor', 'bglight'),
    'format': ('format', 'camera'),
    'look': ('compositing',),
}
CHECK_AFTER = {'prepare', 'format', 'animation', 'camera', 'background', 'floor'}   # steps that can leave the frame uncovered
GLOBALS = ('duration', 'fps', 'frame_start', 'engine', 'ground', 'animate_lighting', 'bg_image', 'isolate_lights',
           'motion_loop', 'motion_intro_s')
TIME = ('duration', 'fps', 'frame_start')
# global setting -> steps to rebuild (the time settings add 'lighting' when the highlight sweep is on: see _global_steps)
GLOBAL_STEPS = {'duration': ('format', 'animation', 'camera'), 'fps': ('format', 'animation', 'camera'),
                'frame_start': ('format', 'animation', 'camera'), 'engine': ('format',), 'ground': STEPS,
                'animate_lighting': ('lighting',), 'bg_image': ('background', 'floor'), 'isolate_lights': ('lighting',),
                'motion_loop': ('format', 'animation', 'camera'), 'motion_intro_s': ('format', 'animation', 'camera')}
# value checks for overrides (same names in presets' data and in the global settings)
CHECKS = {'lens': (lambda v: v > 0, "lens must be > 0 (mm)"),
          'padding': (lambda v: -0.5 <= v <= 0.9, "padding must be between -0.5 and 0.9 (negative = deliberate crop)"),
          'dof': (lambda v: v >= 0, "dof (f-stop) must be >= 0 (0 = off)"),
          'fstop': (lambda v: v > 0, "fstop must be > 0"),
          'el': (lambda v: -89 <= v <= 89, "el (elevation, degrees) must be between -89 and 89"),
          'duration': (lambda v: v >= 12 and v == int(v), "duration must be an integer >= 12"),
          'fps': (lambda v: 1 <= v <= 120 and v == int(v), "fps must be an integer between 1 and 120"),
          'frame_start': (lambda v: v >= 0 and v == int(v), "frame_start must be an integer >= 0"),
          'motion_intro_s': (lambda v: v >= 0.5, "motion_intro_s must be >= 0.5 (seconds)")}
_PREVIEW = {}                                                # the Preview Motion in progress (see preview_start)
RECIPE_FIELDS = ('product_motion', 'camera_shot', 'camera_motion', 'lighting', 'background', 'background_light', 'floor',
                 'look', 'format', 'duration')
_TRUE, _FALSE = ('true', 'yes', 'on', '1'), ('false', 'no', 'off', '0')


def _scene():
    return bpy.context.scene


# === validation (before anything is touched) =================================

def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_bool(key, v):
    if isinstance(v, str):
        if v.strip().lower() in _TRUE:
            return True
        if v.strip().lower() in _FALSE:
            return False
        raise ValueError(f"{key} must be true/false, not {v!r}")
    return bool(v)


def _loose(v):
    """Strings from a command line or a form: 'False' -> False, '2' -> 2, '0.5' -> 0.5; anything else unchanged."""
    if not isinstance(v, str):
        return v
    low = v.strip().lower()
    if low in ('true', 'yes', 'on'):
        return True
    if low in ('false', 'no', 'off'):
        return False
    for conv in (int, float):
        try:
            return conv(v)
        except ValueError:
            pass
    return v


def _check(key, v):
    if _isnum(v) and not math.isfinite(v):
        raise ValueError(f"{key}: invalid value ({v})")
    if key in CHECKS and (not _isnum(v) or not CHECKS[key][0](v)):
        raise ValueError(f"{CHECKS[key][1]} (got {v!r})")


def _globals(pms, glob):
    """Coerce the global settings to the type of their property and check them. Returns a new dict."""
    out = {}
    for k, v in glob.items():
        prop = pms.bl_rna.properties[k]
        if prop.type == 'BOOLEAN':
            v = _to_bool(k, v)
        elif prop.type == 'INT':
            v = _loose(v)
            if not _isnum(v) or v != int(v):
                raise ValueError(f"{k} must be an integer, not {v!r}")
            v = int(v)
        elif prop.type == 'FLOAT':
            v = _loose(v)
            if not _isnum(v):
                raise ValueError(f"{k} must be a number, not {v!r}")
            v = float(v)
        elif prop.type == 'ENUM':
            ids = [i.identifier for i in prop.enum_items]
            if v not in ids:
                raise ValueError(f"{k}: {v!r} is not valid; choose from {ids}")
        else:
            v = '' if v is None else str(v)
        _check(k, v)
        out[k] = v
    if out.get('bg_image'):
        path = bpy.path.abspath(out['bg_image'])
        if os.path.isfile(path):
            core.check_image(path)
    return out


def _data_keys(section):
    """Names a data preset section understands: the keys of its presets' data."""
    return {k for p in presets.REGISTRY[section].values() for k in (p.data or {})}


def _options(section, preset_id, override):
    """Coerce and check the preset overrides (data keys of a data preset, free options of a function preset)."""
    p = presets.get(section, preset_id)
    out = {}
    for k, v in override.items():
        ref = None
        if p.fn is None:
            ref = (p.data or {}).get(k)
            if ref is None:
                ref = next((q.data[k] for q in presets.REGISTRY[section].values() if q.data and k in q.data), None)
        if isinstance(ref, str):
            pass
        elif isinstance(ref, bool):
            v = _to_bool(k, v)
        else:
            v = _loose(v)
            if _isnum(ref) and not _isnum(v):
                raise ValueError(f"{k} must be a number, not {v!r}")
        _check(k, v)
        out[k] = v
    return out


def _unknown(section, override, res):
    """Warnings for override names the section does not know (with a suggestion), and those names."""
    if section not in ('product_motion', 'camera_motion'):      # the function sections read ctx.opt
        valid = _data_keys(section)
    else:
        step = OWN[section]
        if step not in res:                                  # the section was not built: cannot tell
            return [], set()
        valid = set(res[step].get('opts_used', ()))
    bad = [k for k in override if k not in valid]
    warns = []
    for k in bad:
        near = difflib.get_close_matches(k, valid, n=1)
        warns.append(f"Unknown override '{k}'" + (f" (did you mean '{near[0]}'?)" if near else ""))
    return warns, set(bad)


# === running the pipeline ====================================================

def _snapshot(pms):
    """Every property of scene.pms (choices, settings, overrides, coverage, live values). Arrays are copied: the live
    colours would otherwise read back their current value. A dynamic enum whose stored number matches none of its items
    (My Scenes in a new file, with personal scenes saved) reads '' and cannot be set back: it is left out."""
    rna = pms.bl_rna.properties
    snap = {k: getattr(pms, k) for k in rna.keys() if k != 'rna_type'}
    snap = {k: v for k, v in snap.items() if not (v == '' and rna[k].type == 'ENUM')}
    return {k: tuple(v) if hasattr(v, '__len__') and not isinstance(v, (str, set)) else v for k, v in snap.items()}


def _global_steps(pms, key):
    steps = set(GLOBAL_STEPS[key])
    if key in TIME and pms.animate_lighting:
        steps.add('lighting')
    return steps


def _expand(scene, steps):
    """An image backdrop is a plane hung on the camera rig and sized from its frame: it follows the camera."""
    if 'camera' in steps and core.preset(scene, 'background')[1].get('kind') == 'image':
        steps = set(steps) | {'background', 'floor'}
    return set(steps)


def steps_for(section, scene=None):
    """Steps a section's Build button runs ('prepare' = everything from the product on)."""
    scene = scene or _scene()
    if section == 'prepare':
        return set(STEPS[:-1])
    if section not in DEPENDENTS:
        raise ValueError(f"unknown section {section!r}; valid: {['prepare'] + list(DEPENDENTS)}")
    return _expand(scene, DEPENDENTS[section])


def modified_steps(steps, scene=None):
    """Which of the steps would overwrite something edited by hand (names in core.HAND)."""
    scene = scene or _scene()
    return [s for s in core.SIGNED if s in steps and core.modified(scene, s)]


def modified_text(steps, scene=None):
    """'You edited by hand: lights, camera. Overwrite your edits?' (None when nothing was edited)."""
    mods = modified_steps(steps, scene)
    return f"You edited by hand: {', '.join(core.HAND[s][2] for s in mods)}. Overwrite your edits?" if mods else None


def _execute(scene, steps, objects, force, done):
    steps = set(steps)
    mods = {s for s in core.SIGNED if core.modified(scene, s)}
    blocked = set() if force else mods & steps
    if 'prepare' in steps:
        blocked.discard('animation')                         # a new root replaces the old one: its keys are gone anyway
    core.set_protected(mods - (steps - blocked))             # nothing else (orient_rigs) may move what we skip
    out, warnings = {}, []
    try:
        for step in STEPS:
            if step not in steps:
                continue
            if step in blocked:
                kept = [presets.REGISTRY[sec].get(b) for sec in BUILT.get(step, ()) for b in [_loads(core.settings(scene).built).get(sec)]
                        if b and b != getattr(core.settings(scene), sec)]
                warnings.append(core.hand_text(step) + (f"; the scene still has {', '.join(p.name for p in kept if p)}"
                                                        if any(kept) else ''))
                continue
            done.append(step)
            out[step] = build_prepare.build(scene, objects) if step == 'prepare' else _RUN[step](scene)
            warnings += out[step].get('warnings', [])
        if set(done) & CHECK_AFTER:
            warnings += coverage.check(scene)
    finally:
        core.set_protected(())
    pms = core.settings(scene)
    built = _loads(pms.built)
    for step in done:
        built.update({sec: getattr(pms, sec) for sec in BUILT.get(step, ())})
    pms.built = json.dumps(built)
    for s in core.SIGNED:                                    # PMS's own result is the new reference; edits kept are not
        if s not in mods - set(done):
            core.stamp(scene, s)
    out['warnings'] = warnings
    out['notes'] = [out[s]['note'] for s in STEPS if s in out and 'note' in out[s]]
    return out


def _loads(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}


def _rollback(scene, snap, before, done):
    """A step failed: props and overrides go back, and what had already run is rebuilt (or, on a first build, removed)."""
    try:
        core.set_protected(())
        pms = core.settings(scene)
        with core.quiet():
            for k, v in snap.items():
                props.assign(pms, k, v)
        if before is None:
            remove_all(scene)
            return
        if 'prepare' in done:
            build_prepare.build(scene, before)
        redo = [s for s in STEPS if s in done and s != 'prepare']
        _execute(scene, redo, None, True, [])
    except Exception:                                        # noqa: BLE001
        traceback.print_exc()


def run(steps, objects=None, scene=None, force=False, snap=None):
    """Run pipeline steps in canonical order. Returns {step: summary}; 'warnings' and 'notes' are listed apart.
    Sections edited by hand are skipped (warning) unless force=True. If a step raises, props and overrides (snap: taken by
    the caller before it changed them, default: now) are restored, what ran is rebuilt, and the error is raised."""
    scene = scene or _scene()
    pms = core.settings(scene)
    core.claim_scene(scene)
    snap = snap or _snapshot(pms)
    root = bpy.data.objects.get(core.ROOT_NAME)
    before = [o.name for o in root.children] if root else None
    done = []
    try:
        return _execute(scene, steps, objects, force, done)
    except Exception:
        _rollback(scene, snap, before, done)
        raise


def rebuild(section, force=False):
    """What a section's Build button does: its step and what depends on it."""
    scene = _scene()
    return _summary(scene, run(steps_for(section, scene), None, scene, force))


def _same_seconds(scene, pms, fps):
    """Duration in frames that keeps the length in seconds when the fps changes (the render fps is still the old one)."""
    old = scene.render.fps / (scene.render.fps_base or 1.0)
    return max(12, round(pms.duration * fps / old)) if old > 0 else pms.duration


def on_setting_changed(scene, key):
    """Update callback of duration / fps / frame_start / engine: apply at once (hand edits are kept). A new fps keeps the
    length in seconds (the duration in frames follows)."""
    if core.is_quiet() or scene not in core.owners() or not core.has_product():
        return
    pms = core.settings(scene)
    if key == 'fps':
        with core.quiet():
            pms.duration = _same_seconds(scene, pms, pms.fps)
    try:
        run(_global_steps(core.settings(scene), key), None, scene)
    except Exception:                                        # noqa: BLE001 (a callback cannot raise usefully)
        traceback.print_exc()


def list_presets(section=None, search=None):
    """{section: [(id, name, category), ...]} (or just one section).
    search: if given, only presets where props.matches(p, search) is True."""
    from . import props
    if section is not None and section not in presets.REGISTRY:
        raise ValueError(f"unknown section {section!r}; available: {list(presets.SECTIONS)}")
    secs = [section] if section else presets.SECTIONS
    return {s: [(p.id, p.name, p.category) for p in presets.REGISTRY[s].values()
                if not p.meta.get('hidden') and props.matches(p, search)] for s in secs}


def _summary(scene, out):
    objs = [o.name for o in (core.system_collection(scene).all_objects)]
    root = bpy.data.objects.get(core.ROOT_NAME)
    return {'steps': [s for s in STEPS if s in out], 'objects': objs, 'n_objects': len(objs),
            'frame_range': (scene.frame_start, scene.frame_end), 'fps': scene.render.fps,
            'size': float(root['pms_size']) if root else None,
            'details': {k: v for k, v in out.items() if k not in ('warnings', 'notes')}, 'warnings': out['warnings'],
            'notes': out.get('notes', [])}


def build(objects=None, shot='hero_34', product_motion='luxury_drift', camera_motion='push_in',
          lighting='beauty_soft', animate_lighting=False, background='cyclorama_studio_grey',
          floor='seamless', format='16:9', look='clean_commercial', duration=200, fps=None,
          engine='KEEP', ground=True, bg_image='', isolate_lights=True, force=False, background_light='none',
          keep=(), motion_loop=None, motion_intro_s=None):
    """Build the whole studio. objects=None: selected objects, or the already prepared product.
    fps=None: the scene's fps (first build) / the current setting; engine='KEEP': the scene's render engine.
    A section edited by hand is not rebuilt (warning) unless force=True.
    keep: iterable of section names to keep as they are (their overrides and live values are preserved).
    motion_loop: 'NONE' or a loop preset id (None = keep current setting).
    motion_intro_s: intro length in seconds (None = keep current setting)."""
    scene = _scene()
    pms = core.settings(scene)
    core.claim_scene(scene)
    choice = dict(camera_shot=shot, product_motion=product_motion, camera_motion=camera_motion,
                  lighting=lighting, background=background, background_light=background_light, floor=floor,
                  format=format, look=look)
    for section, pid in choice.items():
        presets.get(section, pid)                                  # validate before touching the scene
    keep = set(keep)
    kept = {s: core.overrides(scene, s) for s in keep}
    glob = dict(duration=duration, engine=engine, ground=ground, animate_lighting=animate_lighting,
                bg_image=bg_image, isolate_lights=isolate_lights)
    if fps is not None:
        glob['fps'] = fps
    if motion_loop is not None:
        glob['motion_loop'] = motion_loop
    if motion_intro_s is not None:
        glob['motion_intro_s'] = motion_intro_s
    glob = _globals(pms, glob)
    core.begin(scene)                                              # first build: fps / frame_start come from the scene
    snap = _snapshot(pms)
    try:
        with core.quiet():
            for section, pid in choice.items():
                props.assign(pms, section, pid)
            for k, v in glob.items():
                setattr(pms, k, v)
            pms.overrides = '{}'
            for s, v in kept.items():
                core.set_overrides(scene, s, v)
            forget = [s for s in live.GROUPS if s not in keep]
            if forget:
                live.forget(scene, forget)
    except Exception:
        with core.quiet():
            for k, v in snap.items():
                props.assign(pms, k, v)
        raise
    root = bpy.data.objects.get(core.ROOT_NAME)
    full = objects is not None or root is None or bool(root.get('pms_ground', True)) != bool(ground)
    return _summary(scene, run(STEPS if full else STEPS[1:], objects, scene, force, snap))


def apply(section, preset_id, *, force=False, **override):
    """Select a preset in one section and rebuild it (plus its dependents). Extra keywords are overrides:
    global settings (duration, fps, frame_start, engine, ground, animate_lighting, bg_image, isolate_lights) or preset options
    (data keys such as lens=100 / padding=0.3 for data presets, ctx.opt names such as turns=2 for functions).
    Overrides are validated first. If the section was edited by hand nothing changes and a warning comes back, unless
    force=True; edited dependents are left as they are (warning)."""
    if section == 'recipe':
        return apply_recipe(preset_id, force=force, **override)
    scene = _scene()
    pms = core.settings(scene)
    core.claim_scene(scene)
    if section not in presets.SECTIONS:
        raise ValueError(f"unknown section {section!r}; valid: {list(presets.SECTIONS)}")
    presets.get(section, preset_id)
    glob = {k: override.pop(k) for k in GLOBALS if k in override}
    if not core.has_product():
        raise RuntimeError("PMS: build() with objects first")
    glob = _globals(pms, glob)
    if 'fps' in glob and 'duration' not in glob:
        glob['duration'] = _same_seconds(scene, pms, glob['fps'])
    override = _options(section, preset_id, override)
    steps = set(DEPENDENTS[section])
    snap = _snapshot(pms)
    with core.quiet():
        for k, v in glob.items():
            setattr(pms, k, v)                                     # (put back below if the section is blocked)
        for k in glob:
            steps |= _global_steps(pms, k)
    steps = _expand(scene, steps)
    own = OWN[section]
    if not force and own in modified_steps(steps, scene):
        with core.quiet():
            for k in glob:
                setattr(pms, k, snap[k])
        return _summary(scene, {'warnings': [core.hand_text(own)]})
    with core.quiet():
        props.assign(pms, section, preset_id)
        core.set_overrides(scene, section, override)
        if section in live.GROUPS:
            live.forget(scene, [section])                          # a preset chosen explicitly starts from its defaults
    res = run(steps, None, scene, force, snap)
    warns, bad = _unknown(section, override, res)
    if bad:
        core.set_overrides(scene, section, {k: v for k, v in override.items() if k not in bad})
        res['warnings'] = warns + res['warnings']
    return _summary(scene, res)


def add_objects(objects, force=False):
    """Put more objects into the prepared product and rebuild what follows from it (see build_prepare.add_objects)."""
    scene = _scene()
    core.settings(scene)
    core.claim_scene(scene)
    if not core.has_product():
        raise RuntimeError("PMS: build() with objects first")
    notes = []
    build_prepare.add_objects(scene, objects, notes)           # keeps the product where it is, clears the root animation
    core.stamp(scene, 'animation')                             # (so it is rebuilt: its keys are gone, not edited)
    res = run(set(STEPS[1:-1]), None, scene, force)
    res['warnings'] = notes + res['warnings']
    return _summary(scene, res)


def remove_all(scene=None):
    """Delete everything PMS created and put the product and the scene settings back as they were."""
    scene = scene or _scene()
    core.claim_scene(scene)
    root = bpy.data.objects.get(core.ROOT_NAME)
    products = core.unprepare(root) if root else []          # first: gives the products their parents back
    for key in core.SUB:
        core.clear_section(scene, key)
    for name in list(core.SUB.values()) + [core.SYSTEM, core.RECEIVERS, core.NO_FLOOR]:
        col = bpy.data.collections.get(name)
        if col is not None:
            bpy.data.collections.remove(col)
    core.restore_scene(scene)                                # also: user lights back, hand-edit stamps forgotten
    _PREVIEW.clear()
    if hasattr(scene, 'pms'):
        live.clear(scene)
        with core.quiet():
            scene.pms.overrides, scene.pms.coverage, scene.pms.built = '{}', '', '{}'
            for k in ('fps', 'frame_start'):                 # the next build starts from the scene again
                scene.pms.property_unset(k)
    core.purge_orphans()
    bpy.context.view_layer.update()
    return {'restored': [o.name for o in products]}


def state():
    """Current choices and product data."""
    scene = _scene()
    pms = core.settings(scene)
    root = bpy.data.objects.get(core.ROOT_NAME)
    cam = bpy.data.objects.get('PMS_Camera')
    d = {s: getattr(pms, s) for s in presets.SECTIONS}
    d.update(duration=pms.duration, fps=pms.fps, frame_start=pms.frame_start, engine=pms.engine, ground=pms.ground,
             animate_lighting=pms.animate_lighting, bg_image=pms.bg_image, isolate_lights=pms.isolate_lights,
             motion_loop=pms.motion_loop, motion_intro_s=pms.motion_intro_s,
             overrides=json.loads(pms.overrides), coverage=pms.coverage, prepared=root is not None,
             camera=cam.name if cam else None, frame_range=(scene.frame_start, scene.frame_end),
             modified=modified_steps(set(STEPS), scene), live=live.values(scene), built=_loads(pms.built),
             preview=dict(_PREVIEW) or None,
             user=dict(presets={sec: n for sec in capture.SECTIONS if (n := len(user_presets.user_presets(sec)))},
                       scenes=len(user_presets.scenes()), applied_scene=user_presets.applied_scene(scene)))
    if root is not None:
        d.update(size=float(root['pms_size']), dims=tuple(root['pms_dims']), center=tuple(root['pms_center']),
                 products=[o.name for o in root.children])
    return d


# === recipes, live controls, preview, render =================================

def apply_recipe(recipe_id, *, force=False, objects=None, keep=None, **override):
    """Apply a scene recipe: a complete style (product motion, shot, camera motion, lighting, background, background light,
    floor, look, format, duration) in one go. Overrides replace single fields of the recipe (shot='macro', look='noir',
    duration=120, animate_lighting=True ...). The product must be prepared (or selected / passed as objects). The engine,
    ground, fps, background image and isolate-lights settings are kept as they are.
    keep: iterable of section names to keep as they are (the panel's locks are used by default).
    For kept sections, the current choice wins over the recipe and over an override of that field."""
    from . import props
    scene = _scene()
    pms = core.settings(scene)
    r = dict(presets.get('recipe', recipe_id).data)
    r.update(animate_lighting=pms.animate_lighting)
    for k in list(override):
        key = 'camera_shot' if k == 'shot' else k
        if key in r:
            r[key] = override.pop(k)
    if override:
        raise ValueError(f"unknown overrides for the recipe: {sorted(override)}; valid: {list(RECIPE_FIELDS) + ['shot', 'animate_lighting']}")
    keep = set(pms.locks) if keep is None else set(keep)
    bad = [s for s in keep if s not in props.LOCKABLE]
    if bad:
        raise ValueError(f"keep: unknown sections {sorted(bad)}; valid: {list(props.LOCKABLE)}")
    for s in keep:
        r[s] = getattr(pms, s)
    out = build(objects=objects, shot=r['camera_shot'], product_motion=r['product_motion'], camera_motion=r['camera_motion'],
                lighting=r['lighting'], background=r['background'], background_light=r['background_light'], floor=r['floor'],
                format=r['format'], look=r['look'], duration=r['duration'], animate_lighting=r['animate_lighting'],
                engine=pms.engine, ground=pms.ground, bg_image=pms.bg_image, isolate_lights=pms.isolate_lights, force=force,
                keep=keep)
    with core.quiet():
        props.assign(pms, 'recipe', recipe_id)
    build_compositing.sync_ev(scene)                    # the recipe's own cycles_ev (if any) counts from now on
    out['recipe'] = recipe_id
    out['kept'] = sorted(keep)
    return out


def set_live(**values):
    """Set live controls (the same properties as the panel: cam_lens, cam_padding, cam_dof, cam_fstop, cam_focus, light_power,
    light_tint, light_rot, bg_color_a / _mid / _b, bg_type, bg_rotation, bg_roughness, bg_selflight, bgl_color, bgl_power,
    floor_color, floor_roughness, look_intensity, look_exposure): the built studio changes at once, hand edits are kept.
    Returns the live values after the change."""
    scene = _scene()
    pms = core.settings(scene)
    for k, v in values.items():
        if k not in live.PROPS:
            raise ValueError(f"unknown live control {k!r}; valid: {list(live.PROPS)}")
        if k == 'cam_padding':
            _check('padding', v)
        setattr(pms, k, v)
    return live.values(scene)


def set_render(quality=None, motion_blur=None, path=None, fmt=None, mode=None, engine=None, samples=None, percent=None):
    """Render panel settings: quality 'DRAFT' (Eevee 16 samples, 50 %) / 'PREVIEW' (Eevee 64) / 'FINAL' (Cycles 256, adaptive
    0.01, OIDN, GPU when available) / 'CUSTOM' (engine 'CYCLES' or 'BLENDER_EEVEE', samples, percent = resolution in % of the
    format; giving any of them selects CUSTOM), motion blur, output folder, fmt 'MP4' (H.264) or 'PNG' (sequence; 16 bit for
    FINAL and CUSTOM). mode 'still' / 'animation' also sets the output file. Only settings: nothing is rendered."""
    scene = _scene()
    pms = core.settings(scene)
    with core.quiet():
        if engine is not None:
            pms.render_custom_engine = engine
        if samples is not None:
            pms.render_samples = int(samples)
        if percent is not None:
            pms.render_percent = int(percent)
        if quality is None and (engine, samples, percent) != (None, None, None):
            quality = 'CUSTOM'
        if quality is not None:
            pms.render_quality = quality
        if motion_blur is not None:
            pms.render_motion_blur = bool(motion_blur)
        if path is not None:
            pms.render_path = path
        if fmt is not None:
            pms.render_format = fmt
    return render_settings.apply(scene, mode)


def render_pack(kind, *, mode='still', shots=None, formats=None, variants=None, path=None, render=True, force=False):
    """Render a pack: the same studio rendered several times and put back exactly as it was.

    Kinds:
      - 'angles': e-commerce shots front, hero_34, side, rear_34, top_down (camera motion held still).
      - 'formats': the same shot in 16:9, 1:1, 9:16, re-framed for each.
      - 'variants': every top-level object of a collection, one at a time, in place of the product.

    Files (render=True):
      Still:   <output folder>/pack_<kind>/<name>.png
      Animation (VIDEO): <output folder>/pack_<kind>/<name>_####-####.mp4
      Animation (PNG/EXR sequence): <output folder>/pack_<kind>/<name>/frame_####
    render=False sets up every job without rendering (checks). Everything is put back at the end.

    Returns {'kind': kind, 'folder': absolute path, 'jobs': [job dicts], 'warnings': []}.
    """
    from . import batch
    scene = _scene()
    core.settings(scene)
    core.claim_scene(scene)
    pack = batch.Pack(scene, kind, mode, shots, formats, variants, path, force)
    jobs = []
    try:
        pack.begin()
        for i in range(len(pack.items)):
            job = pack.setup(i)
            if render:
                if mode == 'still':
                    bpy.ops.render.render(write_still=True)
                else:
                    bpy.ops.render.render(animation=True)
            jobs.append(job)
    finally:
        warnings = pack.end()
    return {'kind': kind, 'folder': bpy.path.abspath(pack.base), 'jobs': jobs, 'warnings': warnings}


def preview_start(section, preset_id=None, force=False):
    """Preview Motion: apply a product_motion / camera_motion preset (default: the one chosen in the panel) and remember what
    was built, so preview_stop() puts it back. Playing it is the UI operator's job (a viewport is needed). Starting another
    preview first stops the one in progress. A section edited by hand is not touched unless force=True ('preview': False)."""
    if section not in PREVIEWABLE:
        raise ValueError(f"preview only for {list(PREVIEWABLE)}, not {section!r}")
    scene = _scene()
    pms = core.settings(scene)
    core.claim_scene(scene)
    if not core.has_product():
        raise RuntimeError("PMS: build() with objects first")
    preset_id = preset_id or getattr(pms, section)
    presets.get(section, preset_id)
    preview_stop()
    if not force and OWN[section] in modified_steps(steps_for(section, scene), scene):
        return dict(_summary(scene, {'warnings': [core.hand_text(OWN[section])]}), preview=False)
    before = dict(scene=scene.name, section=section, preset=_loads(pms.built).get(section) or getattr(pms, section),
                  overrides=core.overrides(scene, section), frame=scene.frame_current, previewing=preset_id)
    out = apply(section, preset_id, force=force)
    _PREVIEW.update(before)
    out['preview'] = True
    return out


def preview_stop(keep=False):
    """End the Preview Motion in progress: put the previous preset (and its options) back and the frame where it was; with
    keep=True the previewed preset stays (the panel's Apply). None when no preview is in progress."""
    if not _PREVIEW:
        return None
    st = dict(_PREVIEW)
    _PREVIEW.clear()
    scene = bpy.data.scenes.get(st['scene'])
    if scene is None or not core.has_product() or scene not in core.owners():
        return None
    if keep:
        return {'kept': st['previewing'], 'warnings': []}
    out = apply(st['section'], st['preset'], force=True, **st['overrides'])
    scene.frame_set(st['frame'])
    out['restored'] = st['preset']
    return out


# === personal presets and scenes (user_presets.py) ===========================

def save_preset(section, name, thumbnail=True):
    """Save a section as it is now (hand edits and live values included) as a personal preset of category "My Presets", id
    "user_<name>". Data sections (lighting, background_light, background, floor, look, camera_shot, format) are converted to the
    schema of their presets, relative to the product size (they work on any product); product_motion and camera_motion keep
    the base preset id and its overrides (curves edited by hand are NOT kept). thumbnail=False skips the 128 px render.
    Returns {section, id, name, file}; choose it later with apply(section, id)."""
    scene = _scene()
    core.settings(scene)
    p = user_presets.save_preset(scene, section, name, thumbnail=thumbnail)
    return {'section': section, 'id': p.id, 'name': p.name, 'file': p.meta['file']}


def save_scene(name, thumbnail=True):
    """Save the whole studio (every section as a personal preset embedded in the scene, plus format, frames, fps, engine, render
    settings, animate_lighting, isolate_lights) as a personal scene "user_scene_<name>". Returns {id, name, file}."""
    scene = _scene()
    core.settings(scene)
    e = user_presets.save_scene(scene, name, thumbnail=thumbnail)
    with core.quiet():
        scene.pms.user_scene = e['id']
    return {'id': e['id'], 'name': e['name'], 'file': e['_file']}


def apply_scene(scene_id, *, force=False, objects=None):
    """Rebuild everything on the current product from a personal scene (like apply_recipe: sections edited by hand are kept
    with a warning unless force=True). The product must be prepared (or selected / passed as objects)."""
    scene = _scene()
    pms = core.settings(scene)
    sc = user_presets.get_scene(scene_id)
    s = sc.get('settings') or {}
    choice = {sec: user_presets.embedded_id(scene_id, sec) if sec in sc['sections'] else getattr(pms, sec)
              for sec in ('camera_shot', 'product_motion', 'camera_motion', 'lighting', 'background', 'background_light', 'floor',
                          'format', 'look')}
    glob = {k: s[k] for k in ('duration', 'fps', 'engine', 'animate_lighting', 'isolate_lights', 'bg_image') if k in s}
    glob = _globals(pms, glob)
    snap = _snapshot(pms)
    try:
        with core.quiet():
            for k in ('render_quality', 'render_motion_blur', 'render_format', 'render_custom_engine', 'render_samples', 'render_percent'):
                if k in s:
                    setattr(pms, k, s[k])
            if 'frame_start' in s:
                pms.frame_start = max(0, int(s['frame_start']))
        render_settings.apply(scene)                               # quality -> samples, percentage (the engine follows `glob`)
        out = build(objects=objects, shot=choice['camera_shot'], product_motion=choice['product_motion'],
                    camera_motion=choice['camera_motion'], lighting=choice['lighting'], background=choice['background'],
                    background_light=choice['background_light'], floor=choice['floor'], format=choice['format'],
                    look=choice['look'], ground=pms.ground, force=force,
                    **{**dict(duration=pms.duration, engine=pms.engine, animate_lighting=pms.animate_lighting,
                              isolate_lights=pms.isolate_lights, bg_image=pms.bg_image), **glob})
    except Exception:
        with core.quiet():
            for k, v in snap.items():
                props.assign(pms, k, v)
        raise
    with core.quiet():
        pms.user_scene = scene_id
    out['scene'] = scene_id
    return out


def list_user():
    """{dir, presets: [{section, id, name, desc, base}], scenes: [{id, name, created, sections}], warnings} of the personal
    presets and scenes (warnings: files skipped while loading)."""
    return user_presets.listing()


def _kind(kind):
    if kind not in ('preset', 'scene'):
        raise ValueError(f"kind must be 'preset' or 'scene', not {kind!r}")
    return kind


def delete_user(kind, ident, section=None):
    """Delete a personal 'preset' (id, or 'section/id') or 'scene' (files included). A section of the studio that has it selected
    goes back to the default preset (what is built stays as it is). Returns the removed ids."""
    _kind(kind)
    if kind == 'preset':
        section, ident = user_presets.find(ident, section)
    return {'deleted': user_presets.delete(kind, ident, section)}


def rename_user(kind, ident, name, section=None):
    _kind(kind)
    if kind == 'preset':
        section, ident = user_presets.find(ident, section)
    user_presets.rename(kind, ident, name, section)
    return {'kind': kind, 'id': ident, 'name': (user_presets.get_scene(ident)['name'] if kind == 'scene'
                                                else presets.get(section, ident).name)}


def update_user(kind, ident, section=None, thumbnail=True):
    """Overwrite a personal preset (or scene) with the studio as it is now: id and name stay."""
    scene = _scene()
    core.settings(scene)
    _kind(kind)
    if kind == 'scene':
        user_presets.save_scene(scene, '', update=ident, thumbnail=thumbnail)
    else:
        section, ident = user_presets.find(ident, section)
        user_presets.save_preset(scene, section, '', update=ident, thumbnail=thumbnail)
    return {'kind': kind, 'id': ident, 'updated': True}


def export_user(path, ids=None):
    """Write personal presets and scenes (ids: list of 'id', 'section/id' or 'scene/id'; None = all) with their thumbnails in one
    JSON file to share. Returns {path, presets, scenes}."""
    return user_presets.export_bundle(path, ids)


def import_user(path):
    """Read a file made by export_user. Ids already in use are renamed; what cannot be read (unknown base preset, bad schema, newer
    format) is skipped. Returns {presets, scenes, renamed, errors}."""
    return user_presets.import_bundle(path)


def reload_user():
    """Read the personal presets from the user folder again."""
    user_presets.load_all()
    return user_presets.listing()
