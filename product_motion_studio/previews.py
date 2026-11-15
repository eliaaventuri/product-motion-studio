"""Preset thumbnails: thumbs/<section>/<id>.jpg (128x128, made by plugin/tools/make_thumbnails.py, never by hand),
loaded in one bpy.utils.previews collection while the add-on is registered. props.py puts the icon ids in the enum items."""

import os
import bpy
import bpy.utils.previews
from . import presets

SECTIONS = ('product_motion', 'camera_shot', 'camera_motion', 'lighting', 'background', 'background_light', 'look', 'recipe',
            'floor', 'format')
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thumbs')
_pcoll = None
_user = None                                    # personal presets and scenes (user_presets.py): thumbnails in the user folder


def filename(preset_id):
    """Filename for a preset thumbnail (colons replaced for Windows compatibility)."""
    return preset_id.replace(':', 'x') + '.jpg'


def path(section, preset_id):
    return os.path.join(DIR, section, filename(preset_id))


def icon(section, preset_id):
    """Icon id of a preset thumbnail (0 = no icon: the file is missing or the add-on is not registered)."""
    key = f"{section}/{preset_id}"
    item = _pcoll.get(key) if _pcoll is not None else None
    if item is None and _user is not None:
        item = _user.get(key)
    return item.icon_id if item is not None else 0


def count():
    return len(_pcoll) if _pcoll is not None else 0


def register():
    global _pcoll
    unregister()
    _pcoll = bpy.utils.previews.new()
    for section in SECTIONS:
        for pid in presets.REGISTRY[section]:
            if os.path.isfile(path(section, pid)):
                _pcoll.load(f"{section}/{pid}", path(section, pid), 'IMAGE')


def load_user(files):
    """Replace the thumbnails of the personal presets: files = {"<section>/<id>" or "scene/<id>": path of a jpg}."""
    global _user
    if _user is not None:
        bpy.utils.previews.remove(_user)
    _user = bpy.utils.previews.new()
    for key, file in files.items():
        if os.path.isfile(file):
            _user.load(key, file, 'IMAGE')


def unregister():
    global _pcoll, _user
    if _user is not None:
        bpy.utils.previews.remove(_user)
        _user = None
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
