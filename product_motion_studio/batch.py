"""Render packs: the same studio rendered several times in one go (e-commerce angles, social formats, product variants),
then everything put back as it was (choices, options, camera live values, frame, visibility, output). Used by
api.render_pack (blocking: scripts, headless) and by the panel's modal operator (one render at a time)."""

import re
import traceback

import bpy

from . import api, core, live, presets, render_settings


ANGLES = ('front', 'hero_34', 'side', 'rear_34', 'top_down')
FORMATS = ('16:9', '1:1', '9:16')
KINDS = ('angles', 'formats', 'variants')
GUARD = {'angles': {'camera'}, 'formats': {'camera'}, 'variants': {'animation'}}
CAM_LIVE = live.GROUPS['camera_shot'][1]


def safe(name):
    """Sanitize a name for use in a file path: '16:9' -> '16x9'."""
    return re.sub(r'[^A-Za-z0-9_-]+', '_', name.replace(':', 'x')).strip('_') or 'item'


def layer_entries(scene, coll):
    """The view layers' entries of a collection (excluded there = its objects do not render)."""
    out = []

    def walk(lc):
        if lc.collection == coll:
            out.append(lc)
        for c in lc.children:
            walk(c)
    for vl in scene.view_layers:
        walk(vl.layer_collection)
    return out


def variant_roots(coll):
    """Top-level objects of a collection whose parent is None or not in the collection, sorted by name."""
    objs = coll.objects
    roots = [ob for ob in objs if ob.parent is None or ob.parent.name not in objs]   # (the collection looks up names)
    return sorted(roots, key=lambda o: o.name)


class Pack:
    """A render pack: iterate over items, set up each, render, then put everything back."""

    def __init__(self, scene, kind, mode='still', shots=None, formats=None, variants=None, path=None, force=False):
        if kind not in KINDS:
            raise ValueError(f"unknown pack {kind!r}; valid: {list(KINDS)}")
        if mode not in ('still', 'animation'):
            raise ValueError(f"mode must be 'still' or 'animation', got {mode!r}")
        if not core.has_product():
            raise RuntimeError("PMS: build() with objects first")

        pms = core.settings(scene)

        if kind == 'angles':
            self.items = [(s, s) for s in (shots or ANGLES)]
            for _, s in self.items:
                if presets.get('camera_shot', s) is None:
                    raise ValueError(f"camera_shot preset {s!r} not found")
        elif kind == 'formats':
            self.items = [(safe(f), f) for f in (formats or FORMATS)]
            for _, f in self.items:
                if presets.get('format', f) is None:
                    raise ValueError(f"format preset {f!r} not found")
        else:  # variants
            if variants is None:
                raise ValueError("Render pack: choose the collection of variants")
            coll = variants if isinstance(variants, bpy.types.Collection) else bpy.data.collections.get(variants)
            if coll is None:
                raise ValueError(f"Render pack: collection {variants!r} not found")
            roots = variant_roots(coll)
            if not roots:
                raise ValueError(f"Render pack: the collection {coll.name!r} has no objects")
            if not layer_entries(scene, coll):
                raise ValueError(f"Render pack: the collection {coll.name!r} is not in the scene")
            self.items = [(safe(o.name), o.name) for o in roots]
            self.coll = coll

        mods = api.modified_steps(GUARD[kind], scene)
        if mods and not force:
            raise RuntimeError(
                f"Render pack: you edited by hand: {', '.join(core.HAND[s][2] for s in mods)}. "
                f"The pack would overwrite it (force=True / confirm in the panel)"
            )

        self.scene = scene
        self.kind = kind
        self.mode = mode
        self.force = force
        self.base = render_settings._path(path or pms.render_path, f'pack_{kind}/')
        self.saved = None
        self.warnings = []
        self.hidden = {}
        self.coll_state = None                       # variants: (hide_render, [(layer entry, exclude)]) of the collection

    def begin(self):
        api.preview_stop()

        pms = core.settings(self.scene)
        r = self.scene.render

        # Frame
        self.saved = {
            'frame': self.scene.frame_current,
            'choices': {s: getattr(pms, s) for s in ('camera_shot', 'camera_motion', 'format')},
            'overrides': {s: dict(core.overrides(self.scene, s)) for s in ('camera_shot', 'camera_motion', 'format')},
            'camera_live': {
                k: (tuple(v) if hasattr(v, '__len__') and not isinstance(v, str) else v)
                for k in CAM_LIVE
                for v in [getattr(pms, k)]
            },
            'render': {
                'filepath': r.filepath,
                'media_type': r.image_settings.media_type,
                'file_format': r.image_settings.file_format,
                'color_depth': r.image_settings.color_depth,
                'color_mode': r.image_settings.color_mode,
            }
        }

        if self.kind == 'variants':
            root = bpy.data.objects.get(core.ROOT_NAME)
            self.products = [o.name for o in root.children] if root else []
            candidate_names = set(self.products)
            for v in self.items:
                ob = bpy.data.objects.get(v[1])
                if ob:
                    candidate_names.add(ob.name)
                    candidate_names.update(o.name for o in ob.children_recursive)
            self.hidden = {n: bpy.data.objects[n].hide_render for n in candidate_names if n in bpy.data.objects}
            lcs = layer_entries(self.scene, self.coll)      # the collection may be hidden from renders (so the variants
            self.coll_state = (self.coll.hide_render, [(lc, lc.exclude) for lc in lcs])   # stay out of other shots)
            self.coll.hide_render = False
            for lc in lcs:
                lc.exclude = False

        if self.kind == 'angles':
            self._note(api.apply('camera_motion', 'static', force=self.force))

    def _note(self, res):
        if res and 'warnings' in res:
            for w in res['warnings']:
                if w not in self.warnings:
                    self.warnings.append(w)
        return res

    def setup(self, i):
        name, value = self.items[i]
        pms = core.settings(self.scene)

        if self.kind == 'angles':
            self._note(api.apply('camera_shot', value, force=self.force))
        elif self.kind == 'formats':
            self._note(api.apply('format', value, force=self.force))
        else:  # variants
            for n in self.hidden:
                ob = bpy.data.objects.get(n)
                if ob:
                    ob.hide_render = True
            ob = bpy.data.objects.get(value)
            if ob:
                ob.hide_render = self.hidden.get(value, False)
                for child in ob.children_recursive:
                    child.hide_render = self.hidden.get(child.name, False)
            res = api.run(set(api.STEPS), [bpy.data.objects[value]], self.scene, self.force)
            self._note(res)

        self.scene.frame_set(self.saved['frame'])
        render_settings.apply(self.scene, self.mode)

        r = self.scene.render
        if self.mode == 'still':
            r.filepath = self.base + name
        elif r.image_settings.media_type == 'VIDEO':
            r.filepath = self.base + name + '_'
        else:
            r.filepath = self.base + name + '/frame_'

        cam = self.scene.camera
        return {
            'name': name,
            'value': value,
            'filepath': r.filepath,
            'resolution': (r.resolution_x, r.resolution_y),
            'camera': tuple(cam.matrix_world.translation) if cam else None,
            'visible': (sorted(n for n in self.hidden if not bpy.data.objects[n].hide_render)
                        if self.kind == 'variants' else None),
        }

    def end(self):
        if not self.saved:
            return self.warnings

        # Variants: restore hide_render, then re-run prepare on original products
        if self.kind == 'variants':
            try:
                for n, v in self.hidden.items():
                    ob = bpy.data.objects.get(n)
                    if ob:
                        ob.hide_render = v
                if self.products:
                    api.run(set(api.STEPS), [bpy.data.objects[n] for n in self.products if n in bpy.data.objects],
                            self.scene, self.force)
                if self.coll_state is not None:
                    self.coll.hide_render = self.coll_state[0]
                    for lc, exclude in self.coll_state[1]:
                        lc.exclude = exclude
            except Exception:
                traceback.print_exc()
                self.warnings.append("Render pack: could not put back variants")

        # Angles: restore camera_motion then camera_shot
        if self.kind == 'angles':
            try:
                ov = self.saved['overrides']['camera_motion']
                api.apply('camera_motion', self.saved['choices']['camera_motion'], force=True, **ov)
            except Exception:
                traceback.print_exc()
                self.warnings.append("Render pack: could not put back camera_motion")
            try:
                ov = self.saved['overrides']['camera_shot']
                api.apply('camera_shot', self.saved['choices']['camera_shot'], force=True, **ov)
            except Exception:
                traceback.print_exc()
                self.warnings.append("Render pack: could not put back camera_shot")

        # Formats: restore format
        if self.kind == 'formats':
            try:
                ov = self.saved['overrides']['format']
                api.apply('format', self.saved['choices']['format'], force=True, **ov)
            except Exception:
                traceback.print_exc()
                self.warnings.append("Render pack: could not put back format")

        # All kinds: restore camera live values, frame, render output
        try:
            live_vals = {k: v for k, v in self.saved['camera_live'].items()}
            api.set_live(**live_vals)
        except Exception:
            traceback.print_exc()
            self.warnings.append("Render pack: could not put back camera live values")

        try:
            self.scene.frame_set(self.saved['frame'])
        except Exception:
            traceback.print_exc()
            self.warnings.append("Render pack: could not put back frame")

        try:
            r = self.scene.render
            im = r.image_settings
            # media_type first
            im.media_type = self.saved['render']['media_type']
            im.file_format = self.saved['render']['file_format']
            im.color_depth = self.saved['render']['color_depth']
            im.color_mode = self.saved['render']['color_mode']
            r.filepath = self.saved['render']['filepath']
        except Exception:
            traceback.print_exc()
            self.warnings.append("Render pack: could not put back render output")

        self.saved = None
        return self.warnings