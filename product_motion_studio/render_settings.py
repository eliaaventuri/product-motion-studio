"""Render panel: quality presets, output folder and format. Settings only: nothing is rendered here (the operators of the
panel call Blender's own render operators after `apply`).
Also: deeper Cycles bounces for glass-like products, and the Post-Production Passes toggle."""

import bpy

from . import core

QUALITY = {
    'DRAFT': dict(engine='BLENDER_EEVEE', samples=16, percent=50),
    'PREVIEW': dict(engine='BLENDER_EEVEE', samples=64, percent=100),
    'FINAL': dict(engine='CYCLES', samples=256, percent=100),
}
ADAPTIVE = 0.01

GLASS_WORDS = ('glass', 'jewel', 'liquid', 'perfume', 'bottle', 'dispersion', 'crystal', 'diamond', 'gem')
DEEP = {'max_bounces': 16, 'glossy_bounces': 8, 'transmission_bounces': 16, 'transparent_max_bounces': 16}
PASSES = ('use_pass_z', 'use_pass_mist', 'use_pass_cryptomatte_object', 'use_pass_cryptomatte_material',
          'use_pass_cryptomatte_asset')


def gpu_available():
    """True when Cycles has a GPU device enabled in the preferences."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        if prefs.compute_device_type == 'NONE':
            return False
        return any(d.type != 'CPU' and d.use for d in prefs.get_devices_for_type(prefs.compute_device_type))
    except (KeyError, AttributeError, TypeError):
        return False


def _path(folder, name):
    folder = folder or '//render/'
    return folder + name if folder.endswith(('/', '\\')) else folder + '/' + name


def quality(pms):
    """Engine, samples and resolution % of the chosen quality ('CUSTOM': the panel's own values)."""
    if pms.render_quality == 'CUSTOM':
        return dict(engine=pms.render_custom_engine, samples=pms.render_samples, percent=pms.render_percent)
    return QUALITY[pms.render_quality]


def needs_deep_bounces(scene):
    """Why the product needs deeper Cycles light bounces (glass-like material, or a glass / jewel / liquid lighting
    preset), or None. Glass seen through glass turns black when the transmission bounces run out."""
    root = bpy.data.objects.get(core.ROOT_NAME)
    if root:
        for ob in root.children_recursive:
            for slot in ob.material_slots:
                mat = slot.material
                if not mat or not mat.node_tree:
                    continue
                for node in mat.node_tree.nodes:
                    if node.type in ('BSDF_GLASS', 'BSDF_REFRACTION'):
                        return f"glass material '{mat.name}'"
                    if node.type == 'BSDF_PRINCIPLED':
                        inp = node.inputs.get('Transmission Weight')
                        if inp and (inp.is_linked or inp.default_value > 0.3):
                            return f"glass material '{mat.name}'"
    lighting = getattr(scene.pms, 'lighting', '')       # (not the recipe field: it keeps the last recipe chosen,
    for w in GLASS_WORDS:                                # even after the sections were changed one by one)
        if w in lighting.lower():
            return f"preset '{lighting}'"
    return None


def _bounces(scene):
    """Apply or restore deeper light bounces for glass-like products. Returns the reason or None."""
    c = scene.cycles
    reason = needs_deep_bounces(scene)
    if reason and 'pms_saved_bounces' not in scene:
        scene['pms_saved_bounces'] = {k: getattr(c, k) for k in DEEP}
    if reason:
        for k, v in DEEP.items():
            setattr(c, k, max(v, getattr(c, k)))
    elif 'pms_saved_bounces' in scene:
        saved = scene['pms_saved_bounces'].to_dict()
        for k, v in saved.items():
            setattr(c, k, v)
        del scene['pms_saved_bounces']
    return reason


def _passes(scene, on):
    """Enable or disable depth / mist / Cryptomatte passes and mist settings."""
    if on:
        if 'pms_saved_passes' not in scene:
            layers = {}
            for vl in scene.view_layers:
                layers[vl.name] = {p: getattr(vl, p) for p in PASSES}
                layers[vl.name]['use_pass_shadow_catcher'] = getattr(vl.cycles, 'use_pass_shadow_catcher', False)
            mist = []
            if scene.world and scene.camera and bpy.data.objects.get(core.ROOT_NAME):
                mist = [scene.world.mist_settings.start, scene.world.mist_settings.depth]
            scene['pms_saved_passes'] = {'layers': layers, 'mist': mist}
        root = bpy.data.objects.get(core.ROOT_NAME)
        for vl in scene.view_layers:
            for p in PASSES:
                setattr(vl, p, True)
            vl.cycles.use_pass_shadow_catcher = any(o.is_shadow_catcher for o in scene.objects)
        if scene.world and scene.camera and root:
            d = (scene.camera.matrix_world.translation - root.matrix_world.translation).length
            size = float(root['pms_size'])
            scene.world.mist_settings.start = max(0.0, d - 0.6 * size)
            scene.world.mist_settings.depth = max(0.01, 3.0 * size)
    elif 'pms_saved_passes' in scene:
        saved = scene['pms_saved_passes']
        for vl in scene.view_layers:
            if vl.name in saved.get('layers', {}):
                layer_data = saved['layers'][vl.name]
                for p, val in layer_data.items():
                    if p == 'use_pass_shadow_catcher':
                        setattr(vl.cycles, p, val)
                    else:
                        setattr(vl, p, val)
        if scene.world and saved.get('mist'):
            scene.world.mist_settings.start, scene.world.mist_settings.depth = saved['mist']
        del scene['pms_saved_passes']


def apply(scene, mode=None):
    """Put the chosen quality (and motion blur) in the scene. mode 'still' / 'animation' also sets the output file
    (a still is always a PNG; an animation is an H.264 MP4 or a PNG sequence, as chosen; with Post-Production Passes
    both are multilayer EXR). Also deepens the Cycles bounces for glass and sets / puts back the passes.
    Returns what was set."""
    pms = scene.pms
    q = quality(pms)
    r = scene.render
    warnings, notes = [], []
    try:
        r.engine = q['engine']
    except TypeError:
        warnings.append(f"engine {q['engine']} not available")
    if r.engine == q['engine']:
        with core.quiet():                                    # the Engine field of the panel follows (a rebuild keeps it)
            pms.engine = q['engine']
    r.resolution_percentage = q['percent']
    scene['pms_pct'] = q['percent']                           # build_format keeps it
    r.use_motion_blur = bool(pms.render_motion_blur)
    out = dict(quality=pms.render_quality, engine=r.engine, samples=q['samples'], percent=q['percent'],
               motion_blur=r.use_motion_blur, warnings=warnings, notes=notes)
    reason = _bounces(scene)
    out['deep_bounces'] = reason
    if reason and r.engine == 'CYCLES':
        notes.append(f"Deeper light bounces for {reason}")
    _passes(scene, bool(pms.render_passes))
    out['passes'] = bool(pms.render_passes)
    if q['engine'] == 'CYCLES':
        c = scene.cycles
        c.samples = q['samples']
        c.use_adaptive_sampling, c.adaptive_threshold = True, ADAPTIVE
        c.use_denoising, c.denoiser = True, 'OPENIMAGEDENOISE'
        c.device = 'GPU' if gpu_available() else 'CPU'
        out.update(device=c.device, adaptive_threshold=ADAPTIVE, denoiser=c.denoiser)
        if r.use_motion_blur and c.device == 'GPU':
            warnings.append("Motion blur in Cycles on the GPU can leave black lines: render on the CPU if you see them")
    else:
        scene.eevee.taa_render_samples = q['samples']
        try:
            scene.eevee.use_raytracing = True                 # glass refraction and metal reflections of the studio (off: they render black)
        except AttributeError:
            pass
    if mode:
        im = r.image_settings
        if pms.render_passes:
            im.media_type = 'MULTI_LAYER_IMAGE'               # passes + graded image ('Composite' layer)
            im.file_format = 'OPEN_EXR_MULTILAYER'
            im.color_depth = '32'
            im.exr_codec = 'ZIP'
            im.color_mode = 'RGBA' if r.film_transparent else 'RGB'
            r.filepath = _path(pms.render_path, 'still' if mode == 'still' else 'frame_')
        elif mode == 'still' or pms.render_format == 'PNG':
            im.media_type = 'IMAGE'                           # (Blender 5: the media type comes before the file format)
            im.file_format = 'PNG'
            im.color_mode = 'RGBA' if r.film_transparent else 'RGB'
            im.color_depth = '16' if pms.render_quality in ('FINAL', 'CUSTOM') else '8'   # 16 bit: room for grading the final
            r.filepath = _path(pms.render_path, 'still' if mode == 'still' else 'frame_')
        else:
            im.media_type = 'VIDEO'
            im.file_format = 'FFMPEG'
            r.ffmpeg.format, r.ffmpeg.codec = 'MPEG4', 'H264'
            r.ffmpeg.constant_rate_factor, r.ffmpeg.ffmpeg_preset = 'HIGH', 'GOOD'
            r.ffmpeg.audio_codec = 'NONE'
            im.color_mode = 'RGB'
            r.filepath = _path(pms.render_path, 'animation_')
        out.update(file_format=im.file_format, filepath=r.filepath)
    return out