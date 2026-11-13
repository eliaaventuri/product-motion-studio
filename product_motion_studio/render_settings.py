"""Render panel: quality presets, output folder and format. Settings only: nothing is rendered here (the operators of the
panel call Blender's own render operators after `apply`)."""

import bpy

from . import core

QUALITY = {
    'DRAFT': dict(engine='BLENDER_EEVEE', samples=16, percent=50),
    'PREVIEW': dict(engine='BLENDER_EEVEE', samples=64, percent=100),
    'FINAL': dict(engine='CYCLES', samples=256, percent=100),
}
ADAPTIVE = 0.01


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


def apply(scene, mode=None):
    """Put the chosen quality (and motion blur) in the scene. mode 'still' / 'animation' also sets the output file
    (a still is always a PNG; an animation is an H.264 MP4 or a PNG sequence, as chosen). Returns what was set."""
    pms = scene.pms
    q = quality(pms)
    r = scene.render
    warnings = []
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
               motion_blur=r.use_motion_blur, warnings=warnings)
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
        if mode == 'still' or pms.render_format == 'PNG':
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
