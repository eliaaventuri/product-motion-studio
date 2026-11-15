"""Scene properties (scene.pms): every choice of the studio lives here; UI and api read/write the same state."""

import zlib

import bpy
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from . import capture, core, live, presets, previews, render_settings, user_presets

DEFAULTS = dict(product_motion='luxury_drift', camera_shot='hero_34', camera_motion='push_in',
                lighting='beauty_soft', background='cyclorama_studio_grey', background_light='none', floor='seamless',
                format='16:9', look='clean_commercial', recipe='luxury_perfume')


PLAIN = ('floor', 'format')           # dynamic items too (personal presets come and go), but a plain dropdown without a filter
FILTERED = tuple(s for s in previews.SECTIONS if s not in PLAIN)  # sections with a Category filter, a thumbnail per preset and dynamic items
ALL = 'ALL'
LOCKABLE = ('product_motion', 'camera_shot', 'camera_motion', 'lighting', 'background', 'background_light', 'floor', 'look',
            'format')                 # sections a recipe can be told to keep (the panel's locks)
_CACHE = {}                         # items lists, kept alive for good (Blender keeps pointers to their strings)


def _num(preset_id):
    """Enum number of a preset: a 24-bit hash of its id (presets.enum_num). 24 bits on purpose: the icon-view popup keeps the
    value in a float32 (exact only up to 2**24); bigger numbers came back rounded to a multiple of 64 and the click chose 'nothing'."""
    return presets.enum_num(preset_id)


def _ordered(section):
    """The presets of a section sorted by category, then name."""
    return sorted(presets.REGISTRY[section].values(), key=lambda p: (p.category, p.name.lower()))


def categories(section):
    """Categories of the stock presets (+ "My Presets" for the sections that can have personal ones)."""
    cats = {p.category for p in presets.REGISTRY[section].values() if not p.meta.get('user')}
    return sorted(cats | ({user_presets.CATEGORY} if section in capture.SECTIONS else set()))


def product_types():
    return sorted({t for p in presets.REGISTRY['lighting'].values() for t in p.meta.get('product_types', ())})


def matches(p, text):
    """True if all words in text appear in the preset's searchable text (name, id, desc, category, product_types)."""
    if not text:
        return True
    words = text.lower().replace('-', '').split()
    hay = ' '.join([p.id, p.name, p.desc or '', p.category, *p.meta.get('product_types', ())])
    hay = hay.lower().replace('-', '').replace('_', ' ')          # 'e-commerce' = 'ecommerce', ids split into words
    return all(w in hay or w in hay.replace(' ', '') for w in words)


def visible_ids(section, category=ALL, product_type=ALL, text=''):
    """Ids of the presets the filters let through, in list order."""
    return [p.id for p in _ordered(section)
            if not p.meta.get('hidden') and category in (ALL, p.category)
            and product_type in (ALL, *p.meta.get('product_types', ())) and matches(p, text)]


def _items(section, category, product_type, current, text=''):
    key = (section, category, product_type, text, current, user_presets.REV[0])
    if key not in _CACHE:
        show = set(visible_ids(section, category, product_type, text)) | {current}      # the chosen preset is always listed
        _CACHE[key] = [(p.id, p.name, p.desc, previews.icon(section, p.id), _num(p.id))
                       for p in _ordered(section) if p.id in show]
    return _CACHE[key]


def _filters(pms, section):
    if section in PLAIN:
        return ALL, ALL, ''
    text = getattr(pms, section + '_find', '')
    return getattr(pms, section + '_cat'), (pms.lighting_ptype if section == 'lighting' else ALL), text


def _dynamic(section):
    """Enum of a filtered section: its items depend on the filters, the stored value is the preset's own number."""
    default = _num(DEFAULTS[section])

    def items(self, context):
        by_num = {_num(i): i for i in presets.REGISTRY[section]}          # (personal presets come and go)
        if self is None:
            return _items(section, ALL, ALL, None)
        cur = by_num.get(self.get(section, default))
        cat, ptype, text = _filters(self, section)
        return _items(section, cat, ptype, cur, text)
    return EnumProperty(name=section.replace('_', ' ').title(), items=items, default=default)


def _enum(section):
    return _dynamic(section)


def _filter_enum(plural, singular, values):
    items = [(ALL, f"All {plural}", "")] + [(v, v.replace('_', ' ').title(), "") for v in values]
    return EnumProperty(name=singular, items=items, default=ALL,
                        description="Filters the list of presets; the chosen preset stays chosen")


def assign(pms, key, value):
    """setattr(pms, key, value); a preset hidden by the filters of its section widens them first (a scene's own presets are in no
    list: their enum number is stored)."""
    p = presets.REGISTRY.get(key, {}).get(value) if isinstance(value, str) else None   # ('locks' is a set)
    if p is not None and p.meta.get('hidden'):
        pms[key] = _num(value)
        return
    try:
        setattr(pms, key, value)
    except TypeError:
        if key not in FILTERED:
            raise
        setattr(pms, key + '_cat', ALL)
        if key == 'lighting':
            pms.lighting_ptype = ALL
        setattr(pms, key + '_find', '')
        setattr(pms, key, value)


def _applier(key):
    """Update callback: duration, fps and engine apply at once when the studio is built (hand edits are kept)."""
    def update(self, context):
        from . import api
        api.on_setting_changed(self.id_data, key)
    return update


_ann = {s: _enum(s) for s in presets.SECTIONS}
for _s in presets.SECTIONS:                                    # (stock presets only: personal ones are added by user_presets)
    if len({_num(i) for i in presets.REGISTRY[_s]}) != len(presets.REGISTRY[_s]):
        raise ValueError(f"{_s}: two preset ids with the same enum number")
_ann.update({s + '_cat': _filter_enum("Categories", "Category", categories(s)) for s in FILTERED})
_ann['lighting_ptype'] = _filter_enum("Product types", "Product type", product_types())
_ann['locks'] = EnumProperty(name="Locks", options={'ENUM_FLAG'}, default=set(),
                             items=[(s, s.replace('_', ' ').title(), "Locked: applying a recipe keeps this section as it is")
                                    for s in LOCKABLE])
for s in FILTERED:
    _ann[s + '_find'] = StringProperty(name="Search", default="", options={'TEXTEDIT_UPDATE'},
                                       description="Show only the presets whose name, description or category contain all "
                                                   "these words (e.g. glass, loop, dark, ecommerce); the chosen preset stays")
def _loop_items():
    from . import presets
    items = [('NONE', "No Loop", "Only the motion above")]
    for p in sorted(presets.REGISTRY['product_motion'].values(), key=lambda p: p.name):
        if p.meta.get('loop') and not p.meta.get('hidden') and not p.meta.get('user'):
            items.append((p.id, p.name, p.desc or ''))
    return items


_ann.update(
    duration=IntProperty(name="Duration", description="Number of frames, counted from the start frame",
                         default=200, min=12, soft_max=2000, update=_applier('duration')),
    frame_start=IntProperty(name="Start Frame", description="First frame of the animation (at the first build: the scene's)",
                            default=1, min=0, update=_applier('frame_start')),
    fps=IntProperty(name="FPS", description="At the first build: the scene's. Changing it keeps the length in seconds "
                    "(the frames follow)", default=24, min=1, max=120,
                    update=_applier('fps')),
    engine=EnumProperty(name="Engine", default='KEEP', update=_applier('engine'), items=[
        ('KEEP', "Keep scene engine", "Leave the render engine of the scene as it is"),
        ('CYCLES', "Cycles", ""), ('BLENDER_EEVEE', "Eevee", ""), ('BLENDER_WORKBENCH', "Workbench", "")]),
    isolate_lights=BoolProperty(name="Isolate Lights", default=True,
                                description="Hide your own lights while the studio lighting is built (Remove All gives them back)"),
    ground=BoolProperty(name="Ground", description="Rest the product base on z=0", default=True),
    animate_lighting=BoolProperty(name="Animate Lighting", description="Slow highlight sweep (rotates the light rig)",
                                  default=False),
    bg_image=StringProperty(name="Background Image", subtype='FILE_PATH',
                            description="Picture used by the Image backgrounds (pick one of those in the list, then Build)"),
    base_az=FloatProperty(name="Base Azimuth", description="Azimuth (deg) of the base shot; internal", options={'HIDDEN'}),
    coverage=StringProperty(name="Coverage", description="Backdrop coverage warning (empty = fine); internal, set by every build",
                            default="", options={'HIDDEN'}),
    overrides=StringProperty(name="Overrides", description="JSON of per-section overrides; internal",
                             default="{}", options={'HIDDEN'}),
    motion_loop=EnumProperty(name="Then Loop", default='NONE', update=_applier('motion_loop'),
                             description="After the intro, the product goes on with this loop until the end of the shot",
                             items=_loop_items()),
    motion_intro_s=FloatProperty(name="Intro", default=2.0, min=0.5, soft_max=10.0, max=60.0, unit='TIME_ABSOLUTE',
                                 update=_applier('motion_intro_s'),
                                 description="Length of the intro before the loop starts (seconds)"),
)


def _lf(key, name, description, **kw):
    """Float live control with its update callback (live.py)."""
    return FloatProperty(name=name, description=description, update=live.CALLBACKS[key], **kw)


def _lc(key, name, description, default):
    """Colour live control."""
    return FloatVectorProperty(name=name, description=description, subtype='COLOR', size=3, default=default, min=0.0, max=1.0,
                               update=live.CALLBACKS[key])


def _render_updater(self, context):
    if not core.is_quiet():
        render_settings.apply(self.id_data)


_ann.update(
    # live controls (live.py): they change the built studio at once; the preset's defaults come back with a new preset
    cam_lens=_lf('cam_lens', "Lens", "Focal length in mm (the camera distance is fitted again)", default=85.0, min=1.0, max=1000.0,
                 soft_min=14.0, soft_max=300.0, precision=0, unit='CAMERA'),
    cam_padding=_lf('cam_padding', "Padding", "Empty border around the product, as a fraction of the half frame; negative = deliberate crop",
                    default=0.2, min=-0.5, max=0.9, precision=2),
    cam_dof=BoolProperty(name="Depth of Field", description="Blur what is out of focus", default=False,
                         update=live.CALLBACKS['cam_dof']),
    cam_fstop=_lf('cam_fstop', "F-Stop", "Aperture: lower = shallower depth of field", default=live.FSTOP,
                  min=0.1, max=128.0, soft_min=0.8, soft_max=22.0, precision=1),
    cam_focus=_lf('cam_focus', "Focus Offset", "Focus point moved along the view direction, in product sizes (+ = towards the camera)",
                  default=0.0, min=-1.0, max=1.0, precision=2),
    cam_autofocus=BoolProperty(name="Auto Focus", default=False, update=live.CALLBACKS['cam_autofocus'],
                              description="Keep the focus on the product's surface in every frame (keys on the focus distance): macros, rack focus and dolly zoom follow the product. Needs Depth of Field"),
    light_power=_lf('light_power', "Power", "Multiplier of every studio light (and of the world)", default=1.0, min=0.0, max=4.0,
                    precision=2),
    light_tint=_lc('light_tint', "Tint", "Colour multiplied on every studio light", (1.0, 1.0, 1.0)),
    light_rot=_lf('light_rot', "Rig Rotation", "Rotation of the light rig around the product, in degrees", default=0.0,
                  min=-360.0, max=360.0, soft_min=-180.0, soft_max=180.0, precision=0),
    light_fill=_lf('light_fill', "Fill", "Power of the fill lights, relative to the preset (key/fill ratio)", default=1.0,
                   min=0.0, max=10.0, soft_max=3.0, precision=2),
    light_rim=_lf('light_rim', "Rim", "Power of the rim and back lights, relative to the preset", default=1.0,
                  min=0.0, max=10.0, soft_max=3.0, precision=2),
    light_temp=_lf('light_temp', "Temperature", "Colour temperature shift of all the studio lights, in kelvin: "
                   "negative warmer, positive cooler", default=0.0, min=-5000.0, max=5000.0, soft_min=-3000.0, soft_max=3000.0, step=100, precision=0),
    bg_color_a=_lc('bg_color_a', "Start", "First colour of the gradient (the floor, or the centre of a radial one)", (0.3, 0.3, 0.3)),
    bg_color_mid=_lc('bg_color_mid', "Middle", "Middle colour of the gradient (if it has one)", (0.2, 0.2, 0.2)),
    bg_color_b=_lc('bg_color_b', "End", "Last colour of the gradient (the top of the wall, or the edge of a radial one)", (0.1, 0.1, 0.1)),
    bg_type=EnumProperty(name="Type", default='LINEAR', update=live.CALLBACKS['bg_type'], items=[
        ('LINEAR', "Linear", "Colour changes along the backdrop"), ('RADIAL', "Radial", "Colour changes away from a centre")]),
    bg_rotation=_lf('bg_rotation', "Rotation", "Direction of a linear gradient, in degrees", default=0.0, min=-180.0, max=180.0,
                    precision=0),
    bg_roughness=_lf('bg_roughness', "Roughness", "Roughness of the backdrop", default=0.9, min=0.0, max=1.0, precision=2),
    bg_selflight=_lf('bg_selflight', "Self Light", "Emission of the backdrop: it glows by itself on top of what the lights give",
                     default=0.0, min=0.0, max=10.0, soft_max=6.0, precision=2),
    bg_distance=_lf('bg_distance', "Distance", "How far the wall is behind the product (x the preset)", default=1.0,
                    min=0.3, max=6.0, soft_max=3.0, precision=2),
    bg_cove=_lf('bg_cove', "Cove", "Radius of the curve between floor and wall (x the preset)", default=1.0,
                min=0.1, max=5.0, soft_max=3.0, precision=2),
    bgl_color=_lc('bgl_color', "Colour", "Colour multiplied on the background lights", (1.0, 1.0, 1.0)),
    bgl_power=_lf('bgl_power', "Power", "Multiplier of the background lights", default=1.0, min=0.0, max=4.0, precision=2),
    floor_color=_lc('floor_color', "Colour", "Colour of the floor plane", (0.3, 0.3, 0.3)),
    floor_roughness=_lf('floor_roughness', "Roughness", "Roughness of the floor plane", default=0.85, min=0.0, max=1.0, precision=2),
    look_intensity=_lf('look_intensity', "Intensity", "How much of the look is applied: 0 = neutral render, 1 = full look",
                       default=1.0, min=0.0, max=1.0, subtype='FACTOR', precision=2),
    look_exposure=_lf('look_exposure', "Exposure", "Exposure of the view transform (stops)", default=0.0, min=-5.0, max=5.0,
                      precision=2),
    user_scene=EnumProperty(name="My Scenes", description="Personal scene to apply, rename, update or delete",
                            items=lambda self, context: user_presets.scene_items()),
    live_marks=StringProperty(name="Live Marks", description="JSON: preset each section's live values belong to; internal",
                              default="{}", options={'HIDDEN'}),
    built=StringProperty(name="Built", description="JSON: preset each section was last built with; internal",
                         default="{}", options={'HIDDEN'}),
    # render panel (render_settings.py)
    render_quality=EnumProperty(name="Quality", default='PREVIEW', update=_render_updater, items=[
        ('DRAFT', "Draft", "Eevee, 16 samples, half resolution"), ('PREVIEW', "Preview", "Eevee, 64 samples, full resolution"),
        ('FINAL', "Final", "Cycles, 256 samples, adaptive sampling, OpenImageDenoise, GPU when available"),
        ('CUSTOM', "Custom", "Your own engine, samples and resolution")]),
    render_custom_engine=EnumProperty(name="Engine", default='CYCLES', update=_render_updater, description="Engine of the Custom quality",
                                      items=[('BLENDER_EEVEE', "Eevee", ""), ('CYCLES', "Cycles", "Adaptive sampling, OpenImageDenoise, GPU when available")]),
    render_samples=IntProperty(name="Samples", description="Samples of the Custom quality", default=128, min=1, soft_max=4096,
                               max=65536, update=_render_updater),
    render_percent=IntProperty(name="Resolution", description="Resolution of the Custom quality, in % of the format's size",
                               default=100, min=1, max=400, subtype='PERCENTAGE', update=_render_updater),
    render_motion_blur=BoolProperty(name="Motion Blur", description="Render with motion blur (off by default: it slows Cycles down)",
                                    default=False, update=_render_updater),
    render_path=StringProperty(name="Output", description="Folder the render is written to", subtype='DIR_PATH',
                               default="//render/", options={'PATH_SUPPORTS_BLEND_RELATIVE'}),
    render_format=EnumProperty(name="Format", default='MP4', items=[
        ('MP4', "H.264 MP4", "One video file"), ('PNG', "PNG Sequence", "One image per frame")]),
    pack_kind=EnumProperty(name="Pack", default='ANGLES', items=[
        ('ANGLES', "Angles", "E-commerce angles: front, hero 3/4, side, rear 3/4, top down (camera motion held still)"),
        ('FORMATS', "Formats", "The same shot in 16:9, 1:1 and 9:16, re-framed for each"),
        ('VARIANTS', "Variants", "Every object of a collection, one at a time, in the same studio")]),
    pack_mode=EnumProperty(name="Render", default='STILL', items=[
        ('STILL', "Stills", "One image per item"), ('ANIMATION', "Animations", "One animation per item")]),
    pack_variants=PointerProperty(name="Variants", type=bpy.types.Collection,
                                  description="Collection whose objects are the versions of the product (colours, "
                                              "models), placed where you like. It can stay hidden from renders "
                                              "(camera icon off): the pack shows each variant by itself"),
    render_passes=BoolProperty(name="Post-Production Passes", default=False, update=_render_updater,
                               description="Also save depth, mist and Cryptomatte masks (object, material, asset; shadow "
                                           "catcher in Cycles) for compositing in other programs: the output becomes a 32-bit "
                                           "multilayer OpenEXR, the graded image is its 'Composite' layer"),
)
PMSSettings = type('PMSSettings', (bpy.types.PropertyGroup,), {'__annotations__': _ann})


@persistent
def migrate(*_):
    """load_post: a preset enum saved with the old 30-bit numbers (files saved before the 24-bit change) is converted to its
    new number; a value that matches nothing goes back to the default."""
    for scene in bpy.data.scenes:
        pms = getattr(scene, 'pms', None)
        if pms is None:
            continue
        for section in FILTERED:
            stored = pms.get(section)
            if stored is None:
                continue
            ids = presets.REGISTRY[section]
            if stored in {_num(i) for i in ids}:
                continue
            old = {zlib.crc32(i.encode()) & 0x3FFFFFFF: i for i in ids}
            if stored in old:
                pms[section] = _num(old[stored])
            else:
                del pms[section]
        for section in PLAIN:                                   # files saved when these were plain enums stored the list position
            stored = pms.get(section)
            ids = [i for i, p in presets.REGISTRY[section].items() if not p.meta.get('user')]
            if stored is not None and stored not in {_num(i) for i in presets.REGISTRY[section]}:
                if stored < len(ids):
                    pms[section] = _num(ids[stored])
                else:
                    del pms[section]


def register():
    _CACHE.clear()
    bpy.utils.register_class(PMSSettings)
    bpy.types.Scene.pms = PointerProperty(type=PMSSettings)
    bpy.app.handlers.load_post.append(migrate)


def unregister():
    if migrate in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(migrate)
    del bpy.types.Scene.pms
    bpy.utils.unregister_class(PMSSettings)
