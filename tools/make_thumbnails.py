"""Makes the preset thumbnails: plugin/product_motion_studio/thumbs/<section>/<id>.jpg (128x128).  Run it again whenever a
preset is added or changed; the thumbnails are generated files, never edit them by hand.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tools/make_thumbnails.py
    ... -- [--only lighting,look] [--ids id1,id2] [--engine CYCLES|EEVEE] [--out DIR] [--sheet contact_sheet.png]

  lighting, background, background_light, look, camera_shot, recipe: a render (128 px) of a test scene (glass bottle, brushed
      metal cylinder, orange plastic cube) built by the add-on itself with the preset chosen (a recipe is shown three quarters
      into its animation).  --engine CYCLES (default): 32 samples, OIDN denoise, Metal GPU when there is one (about a quarter of
      a second each); --engine EEVEE: 16 samples with ray tracing.  The thumbnails show what the final render will look like,
      so Cycles is the default.  (The sections are made backdrop-first and `lighting` last: after the two dispersion lights
      Blender 5.1 renders the light-linked backdrop lights wrongly for the rest of the session, even after reloading a file.)
  product_motion, camera_motion: Workbench "multi-exposure": 4 poses of the movement laid over each other, the older the
      fainter, on the empty studio backdrop.  The shot lasts 200 frames and the poses are spread over the ACTION WINDOW, not
      over the whole shot: where the product (or, for the camera moves, the product in the picture) really moves, at equal
      steps of distance travelled (a loop: one full turn, 4 poses; the rest of the shot, standing still, is skipped).
  --out writes somewhere else (to try the tool without touching the shipped thumbnails)."""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, ADDON)

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

import product_motion_studio as pkg
from product_motion_studio import api, core, presets, previews

SIZE = 128
OUT = previews.DIR
IDS = None                                  # --ids: only these presets (to try the tool)
STILL = ('lighting', 'background', 'background_light', 'look', 'camera_shot', 'recipe')
MULTI = ('product_motion', 'camera_motion')
POSES = 4
SHOT_FRAMES = 200                           # length of the shot the movement thumbnails are taken from
WINDOW = 0.03                               # the action window skips the first and last 3% of the distance travelled
WEIGHTS = (0.35, 0.5, 0.7, 1.0)           # opacity of each pose, oldest first
BACKDROP = 0.80                             # grey of the empty backdrop of the multi-exposures


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    opt = {'only': STILL + MULTI, 'sheet': None, 'engine': 'CYCLES', 'out': None, 'ids': None}
    for i, a in enumerate(argv):
        if a == '--only':
            opt['only'] = tuple(argv[i + 1].split(','))
        elif a == '--sheet':
            opt['sheet'] = argv[i + 1]
        elif a == '--ids':
            opt['ids'] = argv[i + 1].split(',')
        elif a == '--engine':
            opt['engine'] = argv[i + 1].upper()
        elif a == '--out':
            opt['out'] = os.path.abspath(argv[i + 1])
    return opt


# --- the test scene ------------------------------------------------------------------------------------------------

def _mat(name, base, metallic=0.0, rough=0.5, trans=0.0):
    m = bpy.data.materials.new(name)
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1)
    b.inputs['Metallic'].default_value = metallic
    b.inputs['Roughness'].default_value = rough
    b.inputs['Transmission Weight'].default_value = trans
    m.diffuse_color = (*base, 1)                        # what Workbench shows
    return m


def _cyl(name, r, h, loc, bevel):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, vertices=48, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    md = ob.modifiers.new('bevel', 'BEVEL')
    md.width, md.segments = bevel, 3
    bpy.ops.object.shade_smooth()
    return ob


def make_product():
    """Bottle (tinted glass) + metal cylinder + orange cube, about 20 cm wide, standing on z=0."""
    body = _cyl('Bottle', 0.032, 0.09, (-0.075, 0, 0.045), 0.006)
    neck = _cyl('Neck', 0.012, 0.03, (-0.075, 0, 0.105), 0.002)
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    neck.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.join()
    glass = _mat('Glass', (0.75, 0.88, 1.0), 0, 0.05, 1.0)
    glass.diffuse_color = (0.45, 0.65, 0.85, 1)
    glass.use_raytrace_refraction, glass.thickness_mode = True, 'SLAB'
    body.data.materials.append(glass)
    metal = _cyl('Metal', 0.03, 0.1, (0.0, 0, 0.05), 0.003)
    metal.data.materials.append(_mat('Metal', (0.8, 0.8, 0.8), 1.0, 0.3))
    bpy.ops.mesh.primitive_cube_add(size=0.07, location=(0.075, 0, 0.035))
    cube = bpy.context.active_object
    cube.name = 'Cube'
    md = cube.modifiers.new('bevel', 'BEVEL')
    md.width, md.segments = 0.006, 3
    bpy.ops.object.shade_smooth()
    cube.data.materials.append(_mat('Plastic', (0.9, 0.33, 0.07), 0.0, 0.45))
    bpy.context.view_layer.update()
    return [body, metal, cube]


def make_image(path):
    """A small gradient picture for the 'image' backdrops (teal to warm, like a blurred location)."""
    img = bpy.data.images.new('pms_thumb_plate', 64, 64)
    y, x = np.mgrid[0:64, 0:64] / 63.0
    px = np.ones((64, 64, 4), dtype=np.float32)
    px[..., 0], px[..., 1], px[..., 2] = 0.15 + 0.7 * x, 0.35 + 0.15 * y, 0.5 - 0.35 * x + 0.1 * y
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw, img.file_format = path, 'PNG'
    img.save()
    bpy.data.images.remove(img)


def new_scene(engine, duration=48):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = make_product()
    api.build(objects=objs, shot='hero_34', product_motion='static', camera_motion='static', lighting='beauty_soft',
              background='cyclorama_studio_grey', floor='seamless', format='1:1', look='neutral_delivery',
              engine=engine, duration=duration)
    return bpy.context.scene, objs


def square(scene):
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100


# --- stills (Cycles or Eevee) --------------------------------------------------------------------------------------------

def enable_gpu(scene):
    """Cycles on the GPU when the preferences can offer one (Metal / OptiX / CUDA / HIP); else the CPU."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('METAL', 'OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
            try:
                prefs.compute_device_type = kind
                prefs.refresh_devices()
            except (TypeError, ValueError):
                continue
            gpus = [d for d in prefs.devices if d.type != 'CPU']
            if gpus:
                for d in gpus:
                    d.use = True
                scene.cycles.device = 'GPU'
                return kind
    except (KeyError, AttributeError):
        pass
    scene.cycles.device = 'CPU'
    return 'CPU'


def still_setup(scene, engine):
    scene.render.use_motion_blur = False
    if engine == 'CYCLES':
        c = scene.cycles
        scene.render.engine = 'CYCLES'
        c.samples, c.use_adaptive_sampling, c.adaptive_threshold = 32, True, 0.03
        c.use_denoising, c.denoiser = True, 'OPENIMAGEDENOISE'
        enable_gpu(scene)
    else:
        scene.render.engine = 'BLENDER_EEVEE'
        scene.eevee.taa_render_samples = 16
        scene.eevee.use_raytracing = True                   # glass refraction and reflections
    im = scene.render.image_settings
    im.file_format, im.color_mode, im.quality = 'JPEG', 'RGB', 85


def render_to(scene, path):
    square(scene)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def make_still(section, tmp, report, engine='CYCLES'):
    scene, _ = new_scene('CYCLES' if engine == 'CYCLES' else 'BLENDER_EEVEE')
    still_setup(scene, engine)
    plate = os.path.join(tmp, 'plate.png')
    make_image(plate)
    for pid in presets.REGISTRY[section]:
        if IDS and pid not in IDS:
            continue
        extra = {'bg_image': plate} if section == 'background' else {}
        out = api.apply(section, pid, force=True, **extra)
        scene.frame_set(scene.frame_start + (round(0.75 * (scene.frame_end - scene.frame_start)) if section == 'recipe' else 0))
        render_to(scene, os.path.join(OUT, section, pid + '.jpg'))
        report.append((section, pid, out['warnings']))


# --- Workbench multi-exposure ------------------------------------------------------------------------------------------

def workbench_setup(scene):
    r, sh = scene.render, scene.display.shading
    r.film_transparent, r.use_compositing, r.use_sequencer = True, False, False
    scene.display.render_aa = '8'
    scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
    sh.light, sh.color_type = 'STUDIO', 'MATERIAL'
    sh.show_object_outline, sh.object_outline_color = True, (0.1, 0.1, 0.12)
    sh.show_cavity = False
    im = r.image_settings
    im.file_format, im.color_mode, im.color_depth = 'PNG', 'RGBA', '8'


def read_rgba(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = 'Non-Color'
    buf = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(SIZE, SIZE, 4)


def write_jpg(arr, path):
    img = bpy.data.images.new('pms_thumb', SIZE, SIZE, alpha=False)
    img.colorspace_settings.name = 'Non-Color'
    rgba = np.ones((SIZE, SIZE, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(arr, 0, 1)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw, img.file_format = path, 'JPEG'
    img.save(quality=85)
    bpy.data.images.remove(img)


def _track(scene, points, step=2):
    """points() is called at frames f0, f0+step, ... of the shot; returns (frames, cumulative distance travelled)."""
    f0, f1 = scene.frame_start, scene.frame_end
    frames = list(range(f0, f1 + 1, step))
    if frames[-1] != f1:
        frames.append(f1)
    pts = []
    for f in frames:
        scene.frame_set(f)
        pts.append(points())
    pts = np.array(pts)
    d = np.linalg.norm(pts[1:] - pts[:-1], axis=2).max(axis=1)         # the corner that moves most, per step
    return np.array(frames), np.concatenate([[0.0], np.cumsum(d)])


def pose_frames(scene, points, loop):
    """The POSES frames of the ACTION WINDOW, at equal steps of distance travelled. points() gives the K points that follow the
    movement (box corners of the product in the world, or in the camera picture for the camera moves). A loop: one full turn
    in POSES steps (its last pose would repeat the first); a shot that does not move at all: spread over the whole shot."""
    frames, s = _track(scene, points)
    total = s[-1]
    if total < 1e-9:
        return [round(scene.frame_start + (scene.frame_end - scene.frame_start) * k / (POSES - 1)) for k in range(POSES)]
    lo, hi = WINDOW * total, (1 - WINDOW) * total
    if loop:
        targets = [lo + (hi - lo) * k / POSES for k in range(POSES)]
    else:
        targets = [lo + (hi - lo) * k / (POSES - 1) for k in range(POSES)]
    return [int(frames[min(int(np.searchsorted(s, t)), len(frames) - 1)]) for t in targets]


def product_points(scene):
    """Box corners of the product, in the world, at the current frame."""
    inf = core.info(scene)
    return lambda: np.array([tuple(inf.root.matrix_world @ Vector(c)) for c in inf.corners])


def picture_points(scene):
    """Box corners of the product as the camera sees them (x, y in the picture, 0..1 over the frame), at the current frame."""
    inf = core.info(scene)
    cam = bpy.data.objects['PMS_Camera']

    def points():
        mw = inf.root.matrix_world
        return np.array([tuple(world_to_camera_view(scene, cam, mw @ Vector(c)))[:2] for c in inf.corners])
    return points


def make_multi(section, tmp, report):
    scene, objs = new_scene('BLENDER_WORKBENCH', SHOT_FRAMES)
    workbench_setup(scene)
    square(scene)
    # the empty backdrop (no product) of the first pose, then only the product on a transparent film
    shot = os.path.join(tmp, 'pose.png')

    def render_png():
        square(scene)
        scene.render.filepath = shot
        bpy.ops.render.render(write_still=True)
        return read_rgba(shot)

    for pid, p in presets.REGISTRY[section].items():
        if IDS and pid not in IDS:
            continue
        out = api.apply(section, pid, force=True)
        if section == 'product_motion':
            frames = pose_frames(scene, product_points(scene), bool(p.meta.get('loop', False)))
        else:
            frames = pose_frames(scene, picture_points(scene), False)
        scene.frame_set(frames[0])
        for ob in objs:
            ob.hide_render = True
        scene.render.film_transparent = False
        back = render_png()[..., :3]
        for ob in objs:
            ob.hide_render = False
        scene.render.film_transparent = True
        backdrop = [c for c in (bpy.data.collections.get(core.SUB[k]) for k in ('background', 'floor')) if c]
        for c in backdrop:
            c.hide_render = True
        img = back
        for f, w in zip(frames, WEIGHTS):
            scene.frame_set(f)
            px = render_png()
            a = px[..., 3:4] * w
            img = img * (1 - a) + px[..., :3] * a
        for c in backdrop:
            c.hide_render = False
        write_jpg(img, os.path.join(OUT, section, pid + '.jpg'))
        report.append((section, pid, out['warnings']))
    return None


# --- contact sheet --------------------------------------------------------------------------------------------------------

def contact_sheet(path, sections, per_row=int(os.environ.get("PMS_SHEET_COLS", 18)), gap=4):
    rows = []
    for section in sections:
        ids = list(presets.REGISTRY[section])
        for i in range(0, len(ids), per_row):
            row = [read_jpg(os.path.join(OUT, section, pid + '.jpg')) for pid in ids[i:i + per_row]]
            row += [np.full((SIZE, SIZE, 3), 0.1, np.float32)] * (per_row - len(row))
            rows.append(np.concatenate([np.pad(t, ((0, 0), (0, gap), (0, 0)), constant_values=0.1) for t in row], axis=1))
        rows.append(np.full((gap * 2, rows[-1].shape[1], 3), 0.1, np.float32))
    sheet = np.concatenate(rows[::-1], axis=0)             # image rows count from the bottom
    h, w = sheet.shape[:2]
    img = bpy.data.images.new('pms_sheet', w, h, alpha=False)
    img.colorspace_settings.name = 'Non-Color'
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., :3] = sheet
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw, img.file_format = path, 'PNG'
    img.save()
    bpy.data.images.remove(img)
    return w, h


def read_jpg(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = 'Non-Color'
    buf = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(SIZE, SIZE, 4)[..., :3]


# --- main -----------------------------------------------------------------------------------------------------------------

def main():
    global OUT, IDS
    opt = _args()
    IDS = opt['ids']
    if opt['out']:
        OUT = opt['out']
    t0 = time.time()
    pkg.register()
    tmp = tempfile.mkdtemp(prefix='pms_thumbs_')
    report = []
    sections = sorted(opt['only'], key=lambda x: x == 'lighting')       # lighting last (see the module docstring)
    try:
        for section in sections:
            os.makedirs(os.path.join(OUT, section), exist_ok=True)
            for f in os.listdir(os.path.join(OUT, section)):             # thumbnails of presets that no longer exist
                if f[:-4] not in presets.REGISTRY[section]:
                    os.remove(os.path.join(OUT, section, f))
            if section in STILL:
                make_still(section, tmp, report, opt['engine'])
            else:
                make_multi(section, tmp, report)
            print(f"{section}: {len(presets.REGISTRY[section])} thumbnails, {time.time() - t0:.0f} s")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
    print(f"THUMBS: {len(report)} made ({opt['engine']}), {total / 1e6:.2f} MB in folder, {time.time() - t0:.0f} s")
    if opt['sheet']:
        print("SHEET:", opt['sheet'], contact_sheet(opt['sheet'], [x for x in previews.SECTIONS if x in opt['only']]))


main()
