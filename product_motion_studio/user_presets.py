"""Personal presets and scenes ("My Presets", "My Scenes"): captured from the studio as it is now (capture.py), saved as JSON
in the user's folder (never inside the add-on), loaded into presets.REGISTRY when the add-on is registered.

FOLDER   $PMS_USER_DIR if set (tests, scripts); else the user folder of the extension
             bpy.utils.extension_path_user(__package__, path="user_presets")
             macOS    ~/Library/Application Support/Blender/<ver>/extensions/.user/<repo>/product_motion_studio/user_presets
             Windows  %APPDATA%\\Blender Foundation\\Blender\\<ver>\\extensions\\.user\\<repo>\\product_motion_studio\\user_presets
             Linux    ~/.config/blender/<ver>/extensions/.user/<repo>/product_motion_studio/user_presets
         else (add-on imported from source, not installed as an extension) bpy.utils.user_resource('SCRIPTS', path='pms_user_presets').
             presets/<section>/<id>.json (+ .jpg)      scenes/<id>.json (+ .jpg)

FORMAT   {"pms_format": 1, "kind": "preset", "section": "lighting", "id": "user_my_key", "name": "My Key", "category": "My Presets",
          "desc": "...", "created": "...", "base": "beauty_soft", "data": {...schema of the section...}, "meta": {...}}
         function sections (product_motion, camera_motion): no "data" but "base" (a built-in preset id) and "opts" (its overrides).
         {"pms_format": 1, "kind": "scene", "id": "user_scene_hero", "name": ..., "settings": {duration, fps, ...},
          "sections": {"lighting": {"data": {...}, "base": ...}, "product_motion": {"base": ..., "opts": {...}}, ...}}
         An applied scene registers its sections as hidden presets "<scene id>__<section>" (not in the lists, only as the
         current choice). Export = one JSON bundle {"kind": "bundle", "presets": [...], "scenes": [...], "thumbs": {key: base64}}."""

import base64
import json
import math
import os
import re
import time

import bpy

from . import capture, core, presets, previews

FORMAT = 1
CATEGORY = 'My Presets'
SCENE_PREFIX = 'user_scene_'
SCENE_SECTIONS = capture.SECTIONS                       # every section a scene stores
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINES = ('CYCLES', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH')
SETTINGS = ('duration', 'fps', 'frame_start', 'engine', 'animate_lighting', 'isolate_lights', 'render_quality',
            'render_motion_blur', 'render_format', 'bg_image', 'render_custom_engine', 'render_samples', 'render_percent',
            'render_passes', 'pack_kind', 'pack_mode', 'motion_loop', 'motion_intro_s')
WARNINGS = []                                           # problems found while loading (corrupt file, missing base...)
REV = [0]                                               # grows with every change of the lists: caches key on it
_SCENES = {}                                            # scene id -> entry
_ITEMS = {}                                             # enum items lists, kept alive for good (Blender keeps their strings)


# === folder ======================================================================

def user_dir(create=False):
    """The folder of the personal presets (see the module docstring); never inside the add-on's own folder."""
    env = os.environ.get('PMS_USER_DIR')
    if env:
        path = os.path.abspath(os.path.expanduser(env))
    else:
        try:
            path = bpy.utils.extension_path_user(__package__, path='user_presets', create=create)
        except (ValueError, RuntimeError, AttributeError, TypeError):      # not installed as an extension
            path = bpy.utils.user_resource('SCRIPTS', path='pms_user_presets', create=create)
    if not path:
        raise RuntimeError("PMS: no user folder to keep personal presets in")
    path = os.path.abspath(path)
    if os.path.commonpath([path, PKG_DIR]) == PKG_DIR:
        raise RuntimeError(f"PMS: personal presets must not live inside the add-on folder ({path})")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _path(kind, ident, section=None, ext='.json', create=False):
    folder = os.path.join(user_dir(create), 'scenes' if kind == 'scene' else os.path.join('presets', section))
    if create:
        os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, ident + ext)


def _write(path, entry):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(entry, fh, indent=1)
    os.replace(tmp, path)


# === validation ==================================================================

def _need(cond, msg):
    if not cond:
        raise ValueError(msg)


def _num(v, lo=None, hi=None):
    return (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            and (lo is None or v >= lo) and (hi is None or v <= hi))


def _vec(v, n):
    return isinstance(v, (list, tuple)) and len(v) == n and all(_num(x) for x in v)


def validate_data(section, data):
    """ValueError (clear message) unless `data` fits the schema of the section's presets."""
    _need(isinstance(data, dict), "'data' must be an object")
    if section in ('lighting', 'background_light'):
        lights = data.get('lights')
        _need(isinstance(lights, list), "'lights' must be a list")
        for i, lt in enumerate(lights):
            _need(isinstance(lt, dict), f"light {i}: must be an object")
            _need(lt.get('type', 'AREA') in ('AREA', 'SPOT', 'POINT', 'SUN'), f"light {i}: unknown type {lt.get('type')!r}")
            _need(lt.get('shape', 'RECTANGLE') in ('RECTANGLE', 'SQUARE', 'DISK', 'ELLIPSE'), f"light {i}: unknown shape {lt.get('shape')!r}")
            for k in ('az', 'el', 'dist_f', 'power_ref'):
                _need(_num(lt.get(k)), f"light {i}: '{k}' must be a number")
            _need(_vec(lt.get('size_f', (1, 1)), 2), f"light {i}: 'size_f' must be two numbers")
            for k in ('rgb', 'aim', 'rot'):
                _need(k not in lt or _vec(lt[k], 3), f"light {i}: '{k}' must be three numbers")
        _need(section != 'lighting' or _num(data.get('world_strength', 0.0), 0.0), "'world_strength' must be a number >= 0")
    elif section == 'background':
        _need(data.get('kind') in ('cyclorama', 'studio360', 'image'), f"background: unknown kind {data.get('kind')!r}")
        stops = data.get('stops')
        _need(isinstance(stops, list) and len(stops) >= 2, "background: 'stops' needs at least two [position, [r, g, b]]")
        for s in stops:
            _need(isinstance(s, (list, tuple)) and len(s) == 2 and _num(s[0]) and _vec(s[1], 3), f"background: bad stop {s!r}")
        _need(isinstance(data.get('gradient', {}), dict), "background: 'gradient' must be an object")
        _need(data.get('gradient', {}).get('type', 'linear') in ('linear', 'radial'), "background: gradient type must be linear or radial")
        _need(_num(data.get('roughness', 0.9), 0, 1) and _num(data.get('self_light', 0.0), 0), "background: roughness / self_light out of range")
    elif section == 'floor':
        _need(data.get('kind') in ('none', 'seamless', 'plane'), f"floor: unknown kind {data.get('kind')!r}")
        _need(data.get('color') is None or _vec(data['color'], 3), "floor: 'color' must be three numbers")
    elif section == 'look':
        for k in ('glare', 'lens', 'grade', 'vignette'):
            _need(isinstance(data.get(k, {}), dict), f"look: '{k}' must be an object")
        _need(isinstance(data.get('view_transform', 'AgX'), str) and isinstance(data.get('look', 'None'), str), "look: view_transform / look must be text")
    elif section == 'camera_shot':
        _need(_num(data.get('az')) and _num(data.get('el'), -89, 89), "camera_shot: az / el must be numbers (el between -89 and 89)")
        _need(_num(data.get('lens'), 1e-6) and _num(data.get('padding'), -0.5, 0.9) and _num(data.get('dof', 0), 0),
              "camera_shot: lens > 0, padding between -0.5 and 0.9, dof >= 0")
    elif section == 'format':
        res = data.get('res')
        _need(isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(x, int) and 1 <= x <= 16384 for x in res),
              "format: 'res' must be two whole numbers (width, height)")


def _builtin(section, base):
    p = presets.REGISTRY.get(section, {}).get(base)
    _need(p is not None and not p.meta.get('user'),
          f"{section}: base preset {base!r} does not exist in this version of PMS")
    return p


def validate_body(section, body):
    """Check the part of an entry that describes one section (also what a scene embeds)."""
    _need(section in capture.SECTIONS, f"unknown section {section!r}")
    if section in capture.FUNCTION_SECTIONS:
        _builtin(section, body.get('base'))
        _need(isinstance(body.get('opts', {}), dict), f"{section}: 'opts' must be an object")
    else:
        validate_data(section, body.get('data'))


def _valid_id(v, prefix='user_'):
    return isinstance(v, str) and re.fullmatch(prefix + r'[A-Za-z0-9_]+', v) is not None


def validate_entry(entry):
    """ValueError unless `entry` is a personal preset or scene this version can read."""
    _need(isinstance(entry, dict), "not a PMS preset (expected a JSON object)")
    fmt = entry.get('pms_format')
    _need(isinstance(fmt, int) and not isinstance(fmt, bool), "not a PMS preset file (no 'pms_format')")
    _need(fmt <= FORMAT, f"made by a newer version of PMS (format {fmt}, this one reads up to {FORMAT})")
    _need(isinstance(entry.get('name'), str) and entry['name'].strip(), "missing 'name'")
    if entry.get('kind') == 'preset':
        _need(_valid_id(entry.get('id')), f"bad id {entry.get('id')!r} (expected user_...)")
        validate_body(entry.get('section'), entry)
    elif entry.get('kind') == 'scene':
        _need(_valid_id(entry.get('id'), SCENE_PREFIX), f"bad scene id {entry.get('id')!r} (expected {SCENE_PREFIX}...)")
        secs = entry.get('sections')
        _need(isinstance(secs, dict) and secs, "scene without sections")
        for sec, body in secs.items():
            try:
                validate_body(sec, body)
            except ValueError as e:
                raise ValueError(f"scene '{entry['name']}': {e}") from None
        _need(isinstance(entry.get('settings', {}), dict), "scene: 'settings' must be an object")
    else:
        raise ValueError(f"unknown kind {entry.get('kind')!r}")
    return entry


# === registry ====================================================================

def _slug(name):
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:40] or 'preset'


def _taken(section, pid):
    reg = presets.REGISTRY[section]
    return pid in reg or presets.enum_num(pid) in {presets.enum_num(i) for i in reg}


def _new_id(section, name):
    base = 'user_' + _slug(name)
    pid, n = base, 1
    while _taken(section, pid):
        n += 1
        pid = f"{base}_{n}"
    return pid


def _new_scene_id(name):
    base = SCENE_PREFIX + _slug(name)
    sid, n = base, 1
    while sid in _SCENES or any(_taken(s, f"{sid}__{s}") for s in SCENE_SECTIONS):
        n += 1
        sid = f"{base}_{n}"
    return sid


def _names(section=None):
    if section is None:
        return {e['name'] for e in _SCENES.values()}
    return {p.name for p in presets.REGISTRY[section].values() if p.meta.get('user') and not p.meta.get('hidden')}


def _unique_name(name, taken, template="{} ({})"):
    name = ' '.join(str(name).split())[:60] or "My Preset"
    out, n = name, 1
    while out in taken:
        n += 1
        out = template.format(name, n)
    return out


def _register(section, pid, name, body, desc='', hidden=False, scene=None, file=None):
    """Put one personal preset into the registry (replacing the one with the same id)."""
    reg = presets.REGISTRY[section]
    old = reg.get(pid)
    _need(old is None or old.meta.get('user'), f"{section}: {pid!r} is a built-in preset")
    _need(old is not None or not _taken(section, pid), f"{section}: the id {pid!r} clashes with another preset")
    meta = dict(body.get('meta') or {})
    meta.update(user=True, base=body.get('base'), file=file)
    if hidden:
        meta.update(hidden=True, scene=scene)
    if section in capture.FUNCTION_SECTIONS:
        base = _builtin(section, body['base'])
        reg[pid] = presets.Preset(section, pid, name, CATEGORY, desc, None, base.fn,
                                  dict(base.meta, **meta, fn_id=base.id, user_opts=dict(body.get('opts') or {})))
    else:
        reg[pid] = presets.Preset(section, pid, name, CATEGORY, desc, json.loads(json.dumps(body['data'])), None, meta)
    return reg[pid]


def _register_scene(entry, file=None):
    sid = entry['id']
    for sec, body in entry['sections'].items():
        _register(sec, f"{sid}__{sec}", entry['name'], body, desc=f"Part of the scene '{entry['name']}'", hidden=True, scene=sid)
    _SCENES[sid] = entry
    if file:
        entry['_file'] = file


def _drop_scene(sid):
    _SCENES.pop(sid, None)
    for sec in presets.SECTIONS:
        presets.REGISTRY[sec].pop(f"{sid}__{sec}", None)


def unload():
    """Take every personal preset out of the registry."""
    for sec in presets.SECTIONS:
        for pid in [i for i, p in presets.REGISTRY[sec].items() if p.meta.get('user')]:
            del presets.REGISTRY[sec][pid]
    _SCENES.clear()


def user_presets(section=None):
    """Personal presets that show in the lists (the scenes' hidden ones are not)."""
    secs = [section] if section else presets.SECTIONS
    return [p for s in secs for p in presets.REGISTRY[s].values() if p.meta.get('user') and not p.meta.get('hidden')]


def scenes():
    return sorted(_SCENES.values(), key=lambda e: e['name'].lower())


def get_scene(sid):
    try:
        return _SCENES[sid]
    except KeyError:
        raise KeyError(f"unknown personal scene {sid!r}; available: {sorted(_SCENES)}") from None


def embedded_id(sid, section):
    return f"{sid}__{section}"


def load_all():
    """Read the user folder (nothing is created): what is not valid is skipped with a warning (WARNINGS, api.list_user())."""
    unload()
    WARNINGS.clear()
    try:
        root = user_dir()
    except RuntimeError as e:
        WARNINGS.append(str(e))
        return refresh()
    todo = [(os.path.join(root, 'presets', s, f), s) for s in capture.SECTIONS
            for f in _json_files(os.path.join(root, 'presets', s))] + \
           [(os.path.join(root, 'scenes', f), None) for f in _json_files(os.path.join(root, 'scenes'))]
    for path, section in todo:
        rel = os.path.relpath(path, root)
        try:
            with open(path, encoding='utf-8') as fh:
                entry = json.load(fh)
            validate_entry(entry)
            if entry['kind'] == 'preset':
                _need(entry['section'] == section, f"it is in the folder of {section} but says {entry['section']}")
                _register(section, entry['id'], entry['name'], entry, entry.get('desc', ''), file=path)
            else:
                _need(section is None, "a scene in a preset folder")
                _register_scene(entry, path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            WARNINGS.append(f"{rel}: {e.args[0] if isinstance(e, KeyError) and e.args else e}")
    for w in WARNINGS:
        print(f"PMS warning: personal preset skipped: {w}")
    return refresh()


def _json_files(folder):
    return sorted(f for f in os.listdir(folder) if f.endswith('.json')) if os.path.isdir(folder) else []


def refresh():
    """After any change: thumbnails reloaded, the lists of the panel rebuilt."""
    files = {}
    for p in user_presets():
        files[f"{p.section}/{p.id}"] = _path('preset', p.id, p.section, '.jpg') if p.meta.get('file') else ''
    for sid in _SCENES:
        files[f"scene/{sid}"] = _path('scene', sid, ext='.jpg') if _SCENES[sid].get('_file') else ''
    try:
        previews.load_user({k: v for k, v in files.items() if v})
    except (RuntimeError, ValueError):
        pass
    REV[0] += 1


# === lists for the panel =========================================================

def scene_items():
    """Items of the My Scenes grid (enum with thumbnails)."""
    key = (REV[0], tuple(_SCENES))
    if key not in _ITEMS:
        items = [(e['id'], e['name'], f"Saved {str(e.get('created', ''))[:10]}", previews.icon('scene', e['id']), presets.enum_num(e['id']))
                 for e in scenes()]
        _ITEMS[key] = items or [('NONE', "No saved scenes yet", "", 0, 0)]
    return _ITEMS[key]


# === thumbnail ===================================================================

def render_thumb(scene, path, size=128):
    """A quick render (128 px, JPEG) of what the scene camera sees now: Eevee in a window, Workbench in background mode (there
    is no viewport render there). Never raises: False when it could not be made (no camera, ...)."""
    cam = scene.camera
    if cam is None:
        return False
    r, im = scene.render, scene.render.image_settings
    ee = scene.eevee
    prefs = bpy.context.preferences.view
    keep = {k: getattr(r, k) for k in ('engine', 'resolution_x', 'resolution_y', 'resolution_percentage', 'filepath',
                                       'use_file_extension', 'film_transparent', 'use_border', 'use_motion_blur')}
    keep_im = {k: getattr(im, k) for k in ('file_format', 'color_mode', 'quality', 'color_depth')}   # (depth after the format)
    keep_media = getattr(im, 'media_type', None)
    keep_ee = (ee.taa_render_samples, getattr(ee, 'use_raytracing', None))
    keep_disp = prefs.render_display_type
    try:
        r.engine = 'BLENDER_WORKBENCH' if bpy.app.background else 'BLENDER_EEVEE'
        r.resolution_x = r.resolution_y = size
        r.resolution_percentage = 100
        r.use_file_extension, r.film_transparent, r.use_border, r.use_motion_blur = False, False, False, False
        if keep_media is not None:
            im.media_type = 'IMAGE'
        im.file_format, im.color_mode, im.quality = 'JPEG', 'RGB', 85
        ee.taa_render_samples = 16
        if keep_ee[1] is not None:
            ee.use_raytracing = True                                           # (glass and metal render black without it)
        r.filepath = path
        prefs.render_display_type = 'NONE'
        bpy.ops.render.render(write_still=True)
        return os.path.isfile(path)
    except Exception as e:                                                      # noqa: BLE001 (a thumbnail is never worth an error)
        print(f"PMS warning: thumbnail not made: {e}")
        return False
    finally:
        for k, v in keep.items():
            setattr(r, k, v)
        if keep_media is not None:
            im.media_type = keep_media
        for k, v in keep_im.items():
            setattr(im, k, v)
        ee.taa_render_samples = keep_ee[0]
        if keep_ee[1] is not None:
            ee.use_raytracing = keep_ee[1]
        prefs.render_display_type = keep_disp


# === save / update / rename / delete ============================================

def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _desc(section, body, name):
    base = presets.REGISTRY[section].get(body.get('base'))
    what = f" from {base.name}" if base is not None else ""
    if section in capture.FUNCTION_SECTIONS:
        return f"{base.name if base else body.get('base')} with your options (curves edited by hand are not kept)"
    return f"Saved{what} on {_now()[:10]}"


def _thumb(scene, path, make):
    if make and not render_thumb(scene, path) and os.path.isfile(path):
        os.remove(path)


def save_preset(scene, section, name, update=None, thumbnail=True):
    """Capture a section as a personal preset. update=<id>: overwrite that preset (name and id stay). Returns its Preset."""
    _need(section in capture.SECTIONS, f"cannot save {section!r} as a personal preset; valid: {list(capture.SECTIONS)}")
    old = None
    if update:
        old = presets.REGISTRY[section].get(update)
        _need(old is not None and old.meta.get('user') and not old.meta.get('hidden'), f"{section}: {update!r} is not a personal preset")
    elif not str(name).strip():
        raise ValueError("give the preset a name")
    body = capture.entry(scene, section)
    name = old.name if old else _unique_name(name, _names(section))
    pid = update or _new_id(section, name)
    entry = dict(pms_format=FORMAT, kind='preset', section=section, id=pid, name=name, category=CATEGORY,
                 desc=_desc(section, body, name), created=_now(), **body)
    if old is not None:
        try:
            with open(old.meta['file'], encoding='utf-8') as fh:
                entry['created'] = json.load(fh).get('created', entry['created'])
        except (OSError, ValueError, KeyError):
            pass
        entry['updated'] = _now()
    validate_entry(entry)
    file = _path('preset', pid, section, create=True)
    _write(file, entry)
    _thumb(scene, _path('preset', pid, section, '.jpg'), thumbnail)
    p = _register(section, pid, name, entry, entry['desc'], file=file)
    refresh()
    return p


def scene_settings(scene):
    pms = core.settings(scene)
    s = {k: getattr(pms, k) for k in SETTINGS}
    s['engine'] = scene.render.engine if scene.render.engine in ENGINES else 'KEEP'
    return s


def save_scene(scene, name, update=None, thumbnail=True):
    """Capture every section plus the global and render settings as a personal scene. Returns the scene entry."""
    if update:
        get_scene(update)
    elif not str(name).strip():
        raise ValueError("give the scene a name")
    if not core.has_product():
        raise RuntimeError("PMS: prepare a product first (nothing to save)")
    sections = {sec: capture.entry(scene, sec) for sec in SCENE_SECTIONS}
    old = _SCENES.get(update) if update else None
    sid = update or _new_scene_id(name)
    entry = dict(pms_format=FORMAT, kind='scene', id=sid, name=old['name'] if old else _unique_name(name, _names()), created=_now(),
                 settings=scene_settings(scene), sections=sections)
    if old is not None:
        entry['created'], entry['updated'] = old.get('created', entry['created']), _now()
    validate_entry(entry)
    file = _path('scene', sid, create=True)
    _write(file, entry)
    _thumb(scene, _path('scene', sid, ext='.jpg'), thumbnail)
    _drop_scene(sid)
    _register_scene(entry, file)
    refresh()
    return entry


def rename(kind, ident, name, section=None):
    name = ' '.join(str(name).split())[:60]
    _need(name, "give it a name")
    if kind == 'scene':
        entry = get_scene(ident)
        if name == entry['name']:
            return entry
        entry['name'] = _unique_name(name, _names() - {entry['name']})
        _write(entry['_file'], {k: v for k, v in entry.items() if k != '_file'})
        for sec in entry['sections']:
            presets.REGISTRY[sec][embedded_id(ident, sec)].name = entry['name']
    else:
        p = _find(section, ident)
        new = _unique_name(name, _names(p.section) - {p.name})
        with open(p.meta['file'], encoding='utf-8') as fh:
            entry = json.load(fh)
        entry['name'] = new
        _write(p.meta['file'], entry)
        p.name = new
    refresh()
    return entry if kind == 'scene' else p


def _find(section, ident):
    """A personal preset by section (None: the only section that has the id)."""
    hits = [p for p in user_presets(section) if p.id == ident]
    _need(hits, f"unknown personal preset {ident!r}" + (f" in {section}" if section else ""))
    _need(len(hits) == 1, f"the id {ident!r} is in several sections ({[p.section for p in hits]}): say which")
    return hits[0]


def find(ident, section=None):
    """(section, id) of a personal preset given as 'id', 'section/id' or with `section`."""
    if section is None and '/' in ident:
        section, ident = ident.split('/', 1)
    p = _find(section, ident)
    return p.section, p.id


def delete(kind, ident, section=None):
    """Delete a personal preset or scene (files included). The sections of every scene that used it go back to the default
    preset (what is built stays as it is). Returns the removed ids."""
    if kind == 'scene':
        get_scene(ident)
        removed = {sec: [embedded_id(ident, sec)] for sec in SCENE_SECTIONS}
        files = [_path('scene', ident), _path('scene', ident, ext='.jpg')]
    else:
        p = _find(section, ident)
        removed = {p.section: [p.id]}
        files = [p.meta['file'], p.meta['file'][:-5] + '.jpg']
    _forget_choice(removed)
    if kind == 'scene':
        _drop_scene(ident)
    else:
        del presets.REGISTRY[p.section][p.id]
    for f in files:
        if os.path.isfile(f):
            os.remove(f)
    refresh()
    return removed


def _forget_choice(removed):
    """Sections of any scene that point to a preset about to disappear go back to the built-in preset it was saved from (the
    default if that is gone too): a later Build of another section then rebuilds something close to what is in the scene,
    not a different format or look."""
    from . import props
    for sc in bpy.data.scenes:
        pms = getattr(sc, 'pms', None)
        if pms is None:
            continue
        with core.quiet():
            for sec, ids in removed.items():
                cur = getattr(pms, sec, None)
                if cur in ids:
                    base = presets.REGISTRY[sec][cur].meta.get('base') if cur in presets.REGISTRY[sec] else None
                    props.assign(pms, sec, base if base in presets.REGISTRY[sec] and base not in ids else props.DEFAULTS[sec])
        if pms.user_scene in [i.rsplit('__', 1)[0] for ids in removed.values() for i in ids]:
            pms.property_unset('user_scene')


# === export / import =============================================================

def _thumb_b64(path):
    if os.path.isfile(path):
        with open(path, 'rb') as fh:
            return base64.b64encode(fh.read()).decode('ascii')
    return None


def export_bundle(path, ids=None):
    """Write personal presets and scenes (all, or the ids / 'section/id' / 'scene/id' listed) and their thumbnails in one JSON file."""
    want = set(ids) if ids else None
    out_p, out_s, thumbs, hit = [], [], {}, set()
    for p in user_presets():
        keys = {p.id, f"{p.section}/{p.id}"}
        if want is None or keys & want:
            hit |= keys & (want or set())
            with open(p.meta['file'], encoding='utf-8') as fh:
                out_p.append(json.load(fh))
            b = _thumb_b64(p.meta['file'][:-5] + '.jpg')
            if b:
                thumbs[f"{p.section}/{p.id}"] = b
    for e in scenes():
        keys = {e['id'], f"scene/{e['id']}"}
        if want is None or keys & want:
            hit |= keys & (want or set())
            out_s.append({k: v for k, v in e.items() if k != '_file'})
            b = _thumb_b64(_path('scene', e['id'], ext='.jpg'))
            if b:
                thumbs[f"scene/{e['id']}"] = b
    if want and want - hit:
        raise ValueError(f"nothing to export for {sorted(want - hit)}")
    _need(out_p or out_s, "nothing to export: no personal presets or scenes yet")
    _write(path, dict(pms_format=FORMAT, kind='bundle', presets=out_p, scenes=out_s, thumbs=thumbs))
    return {'path': path, 'presets': len(out_p), 'scenes': len(out_s)}


def import_bundle(path):
    """Read a bundle (or a single preset / scene file). Ids already in use are renamed; what cannot be read (unknown base preset,
    wrong schema, newer format) is skipped with a clear message. Returns {presets, scenes, renamed, errors}."""
    with open(path, encoding='utf-8') as fh:
        try:
            data = json.load(fh)
        except ValueError as e:
            raise ValueError(f"{os.path.basename(path)} is not a PMS file (invalid JSON: {e})") from None
    _need(isinstance(data, dict) and isinstance(data.get('pms_format'), int), f"{os.path.basename(path)} is not a PMS file (no 'pms_format')")
    _need(data['pms_format'] <= FORMAT, f"made by a newer version of PMS (format {data['pms_format']}, this one reads up to {FORMAT})")
    if data.get('kind') == 'bundle':
        entries = list(data.get('presets') or []) + list(data.get('scenes') or [])
    else:
        entries = [data]
    thumbs = data.get('thumbs') or {}
    out = {'presets': [], 'scenes': [], 'renamed': {}, 'errors': []}
    for entry in entries:
        label = entry.get('name', '?') if isinstance(entry, dict) else '?'
        try:
            validate_entry(entry)
            if entry['kind'] == 'preset':
                _import_preset(dict(entry), thumbs, out)
            else:
                _import_scene(dict(entry), thumbs, out)
        except (ValueError, TypeError, KeyError, OSError) as e:
            out['errors'].append(f"'{label}' skipped: {e.args[0] if isinstance(e, KeyError) and e.args else e}")
    refresh()
    return out


def _save_thumb(b64, path):
    if isinstance(b64, str):
        try:
            with open(path, 'wb') as fh:
                fh.write(base64.b64decode(b64))
        except (ValueError, OSError):
            pass


def _import_preset(entry, thumbs, out):
    section = entry['section']
    old_id = entry['id']
    if _taken(section, old_id):
        entry['id'] = _new_id(section, old_id[len('user_'):])
        out['renamed'][f"{section}/{old_id}"] = entry['id']
    entry['name'] = _unique_name(entry['name'], _names(section))
    file = _path('preset', entry['id'], section, create=True)
    _write(file, entry)
    _save_thumb(thumbs.get(f"{section}/{old_id}"), file[:-5] + '.jpg')
    _register(section, entry['id'], entry['name'], entry, entry.get('desc', ''), file=file)
    out['presets'].append(f"{section}/{entry['id']}")


def _import_scene(entry, thumbs, out):
    old_id = entry['id']
    if old_id in _SCENES or any(_taken(s, f"{old_id}__{s}") for s in SCENE_SECTIONS):
        entry['id'] = _new_scene_id(old_id[len(SCENE_PREFIX):])
        out['renamed'][f"scene/{old_id}"] = entry['id']
    entry['name'] = _unique_name(entry['name'], _names())
    file = _path('scene', entry['id'], create=True)
    _write(file, entry)
    _save_thumb(thumbs.get(f"scene/{old_id}"), file[:-5] + '.jpg')
    _register_scene(entry, file)
    out['scenes'].append(entry['id'])


# === listing =====================================================================

def listing():
    """What api.list_user() returns."""
    try:
        folder = user_dir()
    except RuntimeError as e:
        folder = str(e)
    return {'dir': folder,
            'presets': [{'section': p.section, 'id': p.id, 'name': p.name, 'desc': p.desc, 'base': p.meta.get('base')}
                        for p in user_presets()],
            'scenes': [{'id': e['id'], 'name': e['name'], 'created': e.get('created'), 'sections': sorted(e['sections'])}
                       for e in scenes()],
            'warnings': list(WARNINGS)}


def applied_scene(scene):
    """Id of the personal scene whose sections are all the current choices of the scene (None when none)."""
    pms = getattr(scene, 'pms', None)
    if pms is None:
        return None
    for sid, e in _SCENES.items():
        if all(getattr(pms, sec, None) == embedded_id(sid, sec) for sec in e['sections'] if sec in presets.SECTIONS):
            return sid
    return None
