"""Preset registry: one module per section in this folder, one entry per preset.

REGISTRY = {section: {id: Preset}}.  A preset is either
  - DATA   (camera_shot, lighting, background, background_light, floor, format, look, recipe): a dict passed to
           register(..., data={...})
  - FUNCTION (product_motion, camera_motion): a function decorated with @register(...)

    register('camera_shot', 'front', 'Front', 'hero', 'Straight on', data=dict(az=0, el=4, ...))

    @register('product_motion', 'my_motion', 'My Motion', 'reveal', 'what it does',
              loop=False, ends_at_rest=True)
    def my_motion(root, ctx): ...

Adding a preset = adding one entry to the right module here. Nothing else (UI lists, api, tests
and the catalog read the registry). Extra keyword args become `meta` (loop, ends_at_rest, style...).
"""

import difflib
import zlib

SECTIONS = ('product_motion', 'camera_shot', 'camera_motion', 'lighting',
            'background', 'background_light', 'floor', 'format', 'look', 'recipe')

REGISTRY = {s: {} for s in SECTIONS}


def enum_num(preset_id):
    """Enum number of a preset: a 24-bit hash of its id, so a saved file keeps its choice when presets are added. 24 bits on
    purpose: the icon-view popup keeps the value in a float32 (exact only up to 2**24)."""
    return zlib.crc32(preset_id.encode()) & 0xFFFFFF


class Preset:
    def __init__(self, section, id, name, category, desc, data=None, fn=None, meta=None):
        self.section, self.id, self.name = section, id, name
        self.category, self.desc = category, desc
        self.data, self.fn, self.meta = data, fn, meta or {}


def register(section, id, name, category, desc='', data=None, **meta):
    """Register a preset. With data= it registers immediately; without, it returns a decorator."""
    if section not in REGISTRY:
        raise ValueError(f"unknown section {section!r}")

    def add(fn=None):
        if id in REGISTRY[section]:
            raise ValueError(f"duplicate preset {section}/{id}")
        REGISTRY[section][id] = Preset(section, id, name, category, desc, data, fn, meta)
        return fn

    if data is not None:
        add()
        return None
    return add


def get(section, id):
    if section not in REGISTRY:
        raise ValueError(f"unknown section {section!r}; available: {list(SECTIONS)}")
    try:
        return REGISTRY[section][id]
    except KeyError:
        ids = sorted(REGISTRY[section])
        near = [i for i in ids if str(id) in i] or difflib.get_close_matches(str(id), ids, n=3, cutoff=0.6)
        hint = f"did you mean {', '.join(repr(i) for i in near[:3])}? " if near else ''
        raise KeyError(f"{section}: unknown preset {id!r}; {hint}available: {ids}") from None


# Importing the modules runs their register() calls.
from . import (product_motion, camera_shot, camera_motion, lighting, background, background_light,  # noqa: E402,F401
               floor, format, look, recipe)
