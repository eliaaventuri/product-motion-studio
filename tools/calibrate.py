"""Calibration tool: render test scene with each preset, measure luminance and clipping.
Usage:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tools/calibrate.py --
    --section SECTION --ids id1,id2,... [--engine EEVEE|CYCLES|BOTH] [--res 320x180] [--samples 16] [--out DIR]

Outputs a table on stdout and writes JSON + beauty PNGs to --out (default: temp dir).
"""

import os
import sys
import json
import time
import tempfile
import argparse
import shutil
from pathlib import Path

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, ADDON)

import product_motion_studio as pkg
from product_motion_studio import api, core, presets


def _parse_res(res_str):
    try:
        w, h = map(int, res_str.lower().split('x'))
        return w, h
    except Exception:
        raise ValueError(f"Invalid --res '{res_str}', use WxH (e.g. 320x180)")


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--section', required=True,
                   choices=list(presets.SECTIONS))
    p.add_argument('--ids', required=True)
    p.add_argument('--engine', default='EEVEE', choices=['EEVEE', 'CYCLES', 'BOTH'])
    p.add_argument('--res', default='320x180')
    p.add_argument('--samples', type=int, default=None)
    p.add_argument('--out', default=None)
    return p.parse_args(argv)


def _make_test_product():
    """Create the deterministic test product: Glass, Metal, Plastic ~20cm total."""
    def _mat(name, base, metallic=0.0, rough=0.5, trans=0.0, ior=1.5):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        bsdf = nt.nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (*base, 1)
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Transmission Weight'].default_value = trans
        if trans > 0:
            bsdf.inputs['IOR'].default_value = ior
        m.diffuse_color = (*base, 1)
        return m

    # Glass cylinder
    bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.16, vertices=48, location=(-0.1, 0, 0.08))
    glass_ob = bpy.context.active_object
    glass_ob.name = 'Glass'
    bpy.ops.object.shade_smooth()
    glass_mat = _mat('Glass', (0.75, 0.88, 1.0), 0.0, 0.05, 1.0, 1.45)
    glass_ob.data.materials.append(glass_mat)

    # Metal sphere
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04, segments=32, ring_count=16, location=(0, 0, 0.04))
    metal_ob = bpy.context.active_object
    metal_ob.name = 'Metal'
    bpy.ops.object.shade_smooth()
    metal_mat = _mat('Metal', (0.9, 0.9, 0.9), 1.0, 0.25)
    metal_ob.data.materials.append(metal_mat)

    # Plastic box
    bpy.ops.mesh.primitive_cube_add(size=0.07, location=(0.1, 0, 0.035))
    plastic_ob = bpy.context.active_object
    plastic_ob.name = 'Plastic'
    md = plastic_ob.modifiers.new('bevel', 'BEVEL')
    md.width, md.segments = 0.006, 3
    bpy.ops.object.shade_smooth()
    plastic_mat = _mat('Plastic', (0.5, 0.5, 0.5), 0.0, 0.4)
    plastic_ob.data.materials.append(plastic_mat)

    bpy.context.view_layer.update()
    return [glass_ob, metal_ob, plastic_ob]


def _build_base_scene(engine, duration=24):
    """Build base scene with default PMS settings, then we'll swap presets per section."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = _make_test_product()
    pms_engine = _engine_to_pms(engine)
    api.build(
        objects=objs,
        shot='hero_34',
        product_motion='static',
        camera_motion='static',
        lighting='three_point_classic',
        background='cyclorama_studio_grey',
        background_light='none',
        floor='matte',
        look='neutral_delivery',
        format='16:9',
        duration=duration,
        engine=pms_engine,
    )
    sc = bpy.context.scene
    sc.frame_set(sc.frame_end)  # last frame
    return sc, objs


def _setup_engine(sc, engine, samples):
    if engine == 'CYCLES':
        sc.render.engine = 'CYCLES'
        c = sc.cycles
        c.samples = samples or 64
        c.use_adaptive_sampling = True
        c.adaptive_threshold = 0.03
        c.use_denoising = True
        c.denoiser = 'OPENIMAGEDENOISE'
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
                    sc.cycles.device = 'GPU'
                    break
        except (KeyError, AttributeError):
            sc.cycles.device = 'CPU'
    else:
        sc.render.engine = 'BLENDER_EEVEE'
        sc.eevee.taa_render_samples = samples or 16
        sc.eevee.use_raytracing = True


def _engine_to_pms(engine):
    """Map user-facing engine names to PMS engine enum values."""
    return {'EEVEE': 'BLENDER_EEVEE', 'CYCLES': 'CYCLES'}.get(engine, engine)


def _render_beauty(sc, path, engine, samples):
    """Render beauty with compositor active (look applied). Returns render time."""
    _setup_engine(sc, engine, samples)
    sc.render.use_compositing = True
    sc.render.filepath = path
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    return time.perf_counter() - t0


def _render_mask(sc, product_obs, path):
    """Render object-ID mask with Workbench. Returns mask array (H,W) bool."""
    # Save current state
    old_engine = sc.render.engine
    old_compositing = sc.render.use_compositing
    old_shading_light = sc.display.shading.light
    old_shading_color = sc.display.shading.color_type
    old_film_transparent = sc.render.film_transparent
    old_world = sc.world

    # Set up Workbench for mask
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.use_compositing = False
    sc.render.film_transparent = False
    sh = sc.display.shading
    sh.light = 'FLAT'
    sh.color_type = 'OBJECT'

    # Product objects white, everything else black
    for ob in product_obs:
        ob.color = (1.0, 1.0, 1.0, 1.0)
    for ob in bpy.data.objects:
        if ob not in product_obs and ob.type == 'MESH':
            ob.color = (0.0, 0.0, 0.0, 1.0)

    # Black world
    bw = bpy.data.worlds.new('MaskWorld')
    bw.use_nodes = True
    bw.node_tree.nodes['Background'].inputs['Color'].default_value = (0, 0, 0, 1)
    sc.world = bw

    sc.render.filepath = path
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '8'
    bpy.ops.render.render(write_still=True)

    # Load mask
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    rgba = buf.reshape(h, w, 4)
    mask = rgba[..., 0] > 0.5  # white = product

    # Restore everything
    sc.render.engine = old_engine
    sc.render.use_compositing = old_compositing
    sc.render.film_transparent = old_film_transparent
    sh.light = old_shading_light
    sh.color_type = old_shading_color
    sc.world = old_world
    for ob in product_obs:
        ob.color = (0.8, 0.8, 0.8, 1.0)  # default-ish
    bpy.data.worlds.remove(bw)

    return mask


def _luminance_from_png(path):
    """Load PNG, return luminance array (H,W) 0..1 and RGB array (H,W,3)."""
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    # Buffer is always 4 channels from foreach_get
    rgba = buf.reshape(h, w, 4)
    rgb = rgba[..., :3]
    # sRGB to linear is NOT done here; the PNG is 8-bit sRGB from render
    # Rec.709 luminance from sRGB values
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    return lum, rgb


def _saturation_from_rgb(rgb):
    """HSV saturation from RGB 0..1, returns (H,W) array."""
    if rgb.ndim == 2:
        # Grayscale - saturation is 0
        return np.zeros_like(rgb)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    delta = mx - mn
    sat = np.where(mx > 0, delta / mx, 0)
    return sat


def _clip_fraction(arr, threshold=254/255):
    """Fraction of pixels where max(R,G,B) >= threshold."""
    if arr.ndim == 2:
        # Grayscale - use single channel
        return float((arr >= threshold).mean())
    return float((arr.max(axis=2) >= threshold).mean())


def _apply_section(sc, section, pid, product_obs):
    """Apply a single section preset, rebuild scene. Returns api result."""
    if section == 'recipe':
        return api.apply_recipe(pid)
    return api.apply(section, pid, force=True)


def _run_calibration(section, ids, engine, res, samples, out_dir):
    """Main calibration loop. Returns list of result dicts."""
    w, h = res
    all_results = []

    # Get preset IDs to test
    if ids.upper() == 'ALL':
        test_ids = sorted(presets.REGISTRY[section].keys())
    else:
        test_ids = [i.strip() for i in ids.split(',')]

    # For look section: we need to render existing looks for comparison
    look_pixels = {}
    if section == 'look':
        existing_ids = sorted(k for k in presets.REGISTRY['look'] if k not in test_ids)     # measured looks are not references
        # We'll render these as needed

    engines = ['EEVEE', 'CYCLES'] if engine == 'BOTH' else [engine]

    for pid in test_ids:
        for eng in engines:
            # Fresh base scene for each preset/engine combo
            sc, product_obs = _build_base_scene(eng, duration=24)
            sc.render.resolution_x = w
            sc.render.resolution_y = h
            sc.render.resolution_percentage = 100

            # Apply the test preset
            res_apply = _apply_section(sc, section, pid, product_obs)
            sc.frame_set(sc.frame_end)

            # Beauty render
            beauty_path = os.path.join(out_dir, f"{pid}_{eng}.png")
            render_time = _render_beauty(sc, beauty_path, eng, samples)

            # Mask render
            mask_path = os.path.join(out_dir, f"{pid}_{eng}_mask.png")
            mask = _render_mask(sc, product_obs, mask_path)

            # Analyze beauty
            lum, rgb = _luminance_from_png(beauty_path)

            prod_mask = mask
            bg_mask = ~mask

            prod_lum = lum[prod_mask]
            bg_lum = lum[bg_mask]
            prod_rgb = rgb[prod_mask]
            bg_rgb = rgb[bg_mask]

            prod_mean = float(prod_lum.mean()) if prod_lum.size > 0 else 0.0
            prod_clip = _clip_fraction(prod_rgb)
            bg_mean = float(bg_lum.mean()) if bg_lum.size > 0 else 0.0
            bg_clip = _clip_fraction(bg_rgb)
            all_clip = _clip_fraction(rgb)

            result = {
                'id': pid,
                'engine': eng,
                'prod_mean': prod_mean,
                'prod_clip_pct': round(prod_clip * 100, 2),
                'bg_mean': bg_mean,
                'bg_clip_pct': round(bg_clip * 100, 2),
                'all_clip_pct': round(all_clip * 100, 2),
                'time_s': round(render_time, 2),
            }

            if section == 'look':
                sat = _saturation_from_rgb(rgb)
                prod_sat = sat[prod_mask]
                result['sat_mean'] = float(prod_sat.mean()) if prod_sat.size > 0 else 0.0
                # Store beauty pixels for comparison
                look_pixels[(pid, eng)] = rgb.copy()

            all_results.append(result)

    # For BOTH engine: compute Eevee - Cycles diff
    if engine == 'BOTH':
        for r in all_results:
            if r['engine'] == 'EEVEE':
                pid = r['id']
                cyc = next((x for x in all_results if x['id'] == pid and x['engine'] == 'CYCLES'), None)
                if cyc and cyc['prod_mean'] > 0:
                    diff = r['prod_mean'] - cyc['prod_mean']
                    stops = np.log2(r['prod_mean'] / cyc['prod_mean']) if cyc['prod_mean'] > 0 else 0.0
                    r['ec_diff'] = round(diff, 4)
                    r['ec_stops'] = round(stops, 3)
                else:
                    r['ec_diff'] = 0.0
                    r['ec_stops'] = 0.0

    # For look: compare new looks to nearest existing
    if section == 'look' and look_pixels:
        existing_ids = sorted(k for k in presets.REGISTRY['look'] if k not in test_ids)     # measured looks are not references
        # Render existing looks if not already done
        for eid in existing_ids:
            for eng in engines:
                if (eid, eng) not in look_pixels:
                    # Need to render this existing look
                    sc, product_obs = _build_base_scene(eng, duration=24)
                    sc.render.resolution_x = w
                    sc.render.resolution_y = h
                    sc.render.resolution_percentage = 100
                    _apply_section(sc, 'look', eid, product_obs)
                    sc.frame_set(sc.frame_end)
                    beauty_path = os.path.join(out_dir, f"{eid}_{eng}.png")
                    _render_beauty(sc, beauty_path, eng, samples)
                    lum, rgb = _luminance_from_png(beauty_path)
                    look_pixels[(eid, eng)] = rgb

        # Compare each new look to nearest existing
        for r in all_results:
            if r['engine'] in engines:
                pid = r['id']
                eng = r['engine']
                rgb_new = look_pixels[(pid, eng)]
                best_id, best_diff = None, float('inf')
                for eid in existing_ids:
                    if eid == pid:
                        continue
                    rgb_exist = look_pixels[(eid, eng)]
                    diff = np.mean(np.abs(rgb_new.astype(np.float32) - rgb_exist.astype(np.float32)))
                    if diff < best_diff:
                        best_diff = diff
                        best_id = eid
                r['nearest'] = f"{best_id} ({best_diff:.4f})"

    return all_results


def _print_table(results):
    """Print results table to stdout."""
    # Header
    cols = ['id', 'engine', 'prod_mean', 'prod_clip%', 'bg_mean', 'bg_clip%', 'ec_stops', 'time']
    print(' | '.join(f"{c:>12}" for c in cols))
    print('-' * (13 * len(cols) - 1))
    for r in results:
        ec = r.get('ec_stops', '')
        ec_str = f"{ec:>12}" if ec != '' else f"{'':>12}"
        print(f"{r['id']:>12} | {r['engine']:>12} | {r['prod_mean']:>12.4f} | {r['prod_clip_pct']:>11.2f} | {r['bg_mean']:>12.4f} | {r['bg_clip_pct']:>11.2f} | {ec_str} | {r['time_s']:>12.2f}")


def _write_json(results, section, out_dir):
    """Write JSON output."""
    path = os.path.join(out_dir, f"calibrate_{section}.json")
    data = {
        'section': section,
        'results': results,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    return path


def run(section, ids, engine='EEVEE', res=(320, 180), samples=None, out=None):
    """Main entry point for programmatic use. Returns list of result dicts."""
    if out is None:
        out = tempfile.mkdtemp(prefix='pms_calibrate_')
    else:
        out = os.path.abspath(out)
        os.makedirs(out, exist_ok=True)

    pkg.register()

    try:
        results = _run_calibration(section, ids, engine, res, samples, out)
        _print_table(results)
        json_path = _write_json(results, section, out)
        print(f"CALIBRATE DONE {json_path}")
        return results
    finally:
        pkg.unregister()


def main():
    opt = _args()
    res = _parse_res(opt.res)
    samples = opt.samples
    out = opt.out

    run(opt.section, opt.ids, opt.engine, res, samples, out)


if __name__ == '__main__':
    main()