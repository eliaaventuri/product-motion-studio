"""Camera-motion analysis for Product Motion Studio (regenerable).

    Blender -b --factory-startup --python plugin/tools/camera_report.py -- [options]
      --presets a,b     camera_motion ids (default: all)      --shots hero_34,front,low_angle,macro (default)
      --durs 48,96,200,480 (default)                          --json FILE   full metrics per case
      --curves DIR      PNG graphs (azimuth / elevation / distance / lens / speed) of every preset, shot hero_34, 200 f
      --strips DIR      Workbench strips of 8 frames of every preset (shot hero_34, 200 f) + contact sheets
No Cycles/Eevee, only Workbench.  Also imported by tests/test_camera_quality.py (measure()).

Metrics per (preset, shot, duration), time in seconds, lengths in product sizes (size = bbox diagonal):
  peak_omega   peak angular speed of the view direction (deg/s), omega = sqrt((daz*cos el)^2 + del^2)
  peak_az, peak_el   peak azimuth / elevation rate (deg/s)
  peak_speed   peak speed of the camera in the world (size/s); peak_rel = peak_speed / distance (1/s)
  jerk_index   peak jerk * peak speed / peak acceleration^2 (dimensionless, independent of size and duration):
               ~3.4 for a quintic (smootherstep) ease, ~0.25*fps*T (48 at 8 s) for a cubic ease whose acceleration
               jumps at the start
  ease_in/out  speed at the first / last frames over the peak speed (0 = starts/stops from rest)
  stop_go      True if the speed climbs above 50 % of the peak, falls below 8 % and climbs again above 25 %
  main_s       time for the camera to cover from 5 % to 95 % of its path; hold_in/hold_out: leading/trailing rest (s)
  lens_range, focus_shift (size)   change of the focal length / of the DOF focus empty during the clip
  rack_a/rack_b   defocus (% of the sensor width) of the far/near side of the product at the start and the end
  noise_deg (p-p of the camera rotation noise), noise_bands (energy fractions 0-0.5/0.5-2/2-6/6-12 Hz)
  pct_out, max_over, center_out, fill_min/max, cx0/cy0/cx1/cy1: product framing (same definition as test_addon test 5)
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

import product_motion_studio as pkg
from product_motion_studio import api, core, presets

SHOTS = ('hero_34', 'front', 'low_angle', 'macro')
DURS = (48, 96, 200, 480)


def make_product(scale=1.0):
    """Same product as tests/test_addon.py: Suzanne + a cylinder, raised off the floor."""
    if core.has_product() or bpy.data.collections.get(core.SYSTEM):
        api.remove_all()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    bpy.ops.mesh.primitive_monkey_add(size=2 * scale, location=(0.3 * scale, 0.2 * scale, 3 * scale))
    a = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5 * scale, depth=1.0 * scale,
                                        location=(2.4 * scale, 0.2 * scale, 2.6 * scale))
    b = bpy.context.active_object
    a.rotation_euler = (0.3, 0.1, 0.5)
    bpy.context.view_layer.update()
    return [a, b]


def setup(product_motion='static', shot='hero_34', camera_motion='static', engine='BLENDER_WORKBENCH', **kw):
    try:
        pkg.register()
    except Exception:                                            # noqa: BLE001  (already registered)
        pass
    objs = make_product()
    api.build(objects=objs, product_motion=product_motion, camera_motion=camera_motion, shot=shot,
              engine=engine, **kw)
    return objs


def _framing(sc, cam, root, inf):
    mw = root.matrix_world
    ctr = world_to_camera_view(sc, cam, mw.translation)
    pts = [world_to_camera_view(sc, cam, mw @ c) for c in inf.corners]
    behind = min(p.z for p in pts) <= 0
    over, fill = 0.0, 0.0
    for axis in 'xy':
        lo, hi = min(getattr(p, axis) for p in pts), max(getattr(p, axis) for p in pts)
        over = max(over, (max(0, -lo) + max(0, hi - 1)) / max(hi - lo, 1e-9))
        fill = max(fill, hi - lo)
    out = behind or not (0 <= ctr.x <= 1 and 0 <= ctr.y <= 1)
    return over, fill, out, ctr.x, ctr.y


def _coc(f_mm, n, d, s, sensor):
    """Circle of confusion (fraction of the sensor width) for focus at d and a point at s (same unit as f)."""
    return abs(f_mm * f_mm / n * (s - d) / (s * (d - f_mm))) / sensor


def sample(sc, f0, f1, probes=True):
    """Per-frame raw channels of the current camera rig, frames f0..f1."""
    cam, pivot = bpy.data.objects['PMS_Camera'], bpy.data.objects['PMS_Cam_Pivot']
    focus = bpy.data.objects.get('PMS_DOF_Empty')
    root = bpy.data.objects[core.ROOT_NAME]
    inf = core.info()
    rows = {k: [] for k in ('az', 'el', 'dist', 'lens', 'pos', 'rot', 'focus', 'over', 'fill', 'out', 'cx', 'cy',
                            'prod_yaw')}
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        rows['az'].append(pivot.rotation_euler[2])
        rows['el'].append(-pivot.rotation_euler[0])
        rows['dist'].append(-cam.location[1])
        rows['lens'].append(cam.data.lens)
        rows['pos'].append(tuple(cam.matrix_world.translation))
        rows['rot'].append(tuple(cam.rotation_euler))
        rows['focus'].append(tuple(focus.matrix_world.translation) if focus else (0, 0, 0))
        o, fl, out, cx, cy = _framing(sc, cam, root, inf)
        rows['over'].append(o)
        rows['fill'].append(fl)
        rows['out'].append(out)
        rows['cx'].append(cx)
        rows['cy'].append(cy)
        ax = root.matrix_world.to_3x3() @ Vector((1, 0, 0))
        rows['prod_yaw'].append(math.atan2(ax.y, ax.x))
    return {k: np.array(v, dtype=float) for k, v in rows.items()}, inf, cam


def analyse(s, inf, cam, fps):
    """Metrics from the raw channels (see the module docstring)."""
    n = len(s['az'])
    size = inf.size
    pos = s['pos'] / size
    d = lambda x: np.gradient(x, axis=0) * fps                  # noqa: E731
    vel = d(pos)
    v = np.linalg.norm(vel, axis=1)
    acc = np.linalg.norm(d(vel), axis=1)
    jerk = np.linalg.norm(d(d(vel)), axis=1)
    peak = float(v.max()) if n else 0.0
    out = dict(frames=n, seconds=(n - 1) / fps, peak_speed=peak)
    el = s['el']
    daz, dele = np.gradient(np.unwrap(s['az'])) * fps, np.gradient(el) * fps
    om = np.degrees(np.sqrt((daz * np.cos(el)) ** 2 + dele ** 2))
    out.update(peak_omega=float(om.max()), peak_az=float(np.degrees(np.abs(daz)).max()),
               peak_el=float(np.degrees(np.abs(dele)).max()),
               az_total=float(np.degrees(s['az'][-1] - s['az'][0])), el_total=float(np.degrees(s['el'][-1] - s['el'][0])),
               dist_total=float((s['dist'][-1] - s['dist'][0]) / s['dist'][0]))
    out['peak_rel'] = float((np.abs(np.gradient(s['dist'])) * fps / s['dist']).max())
    if peak > 1e-9 and n > 8:
        s_arc = np.cumsum(v) / fps
        tot = s_arc[-1]
        i5, i95 = int(np.searchsorted(s_arc, 0.05 * tot)), int(np.searchsorted(s_arc, 0.95 * tot))
        out['main_s'] = float((i95 - i5) / fps)
        a_pk = float(acc[3:-3].max()) if n > 8 else 0.0
        out['jerk_index'] = float(jerk[3:-3].max() * peak / a_pk ** 2) if a_pk > 1e-12 else 0.0
        out['ease_in'] = float(v[:2].mean() / peak)
        out['ease_out'] = float(v[-2:].mean() / peak)
        vn = v / peak
        flag = False
        hi = np.where(vn > 0.5)[0]
        if len(hi):
            low = np.where((vn < 0.08) & (np.arange(n) > hi[0]))[0]
            if len(low):
                flag = bool((vn[low[0]:] > 0.25).any())
        out['stop_go'] = flag
        rest = vn < 0.015
        k = 0
        while k < n and rest[k]:
            k += 1
        j = 0
        while j < n and rest[n - 1 - j]:
            j += 1
        out['hold_in'], out['hold_out'] = k / fps, j / fps
        out['accel_peak'] = float(acc.max())
    else:
        out.update(main_s=0.0, jerk_index=0.0, ease_in=0.0, ease_out=0.0, stop_go=False,
                   hold_in=(n - 1) / fps, hold_out=(n - 1) / fps, accel_peak=0.0)
    out['lens_range'] = float(s['lens'].max() - s['lens'].min())
    out['focus_shift'] = float(np.linalg.norm(s['focus'] - s['focus'][0], axis=1).max() / size)
    # framing
    out['pct_out'] = float((s['over'] > 0.005).mean() * 100)
    out['max_over'] = float(s['over'].max())
    out['center_out'] = int(s['out'].sum())
    out['fill_min'], out['fill_max'] = float(s['fill'].min()), float(s['fill'].max())
    out.update(cx0=float(s['cx'][0]), cy0=float(s['cy'][0]), cx1=float(s['cx'][-1]), cy1=float(s['cy'][-1]),
               cx_dev=float(np.abs(s['cx'] - 0.5).max()), cy_dev=float(np.abs(s['cy'] - 0.5).max()))
    # handheld-type noise: rotation of the camera object around its rest rotation, and its spectrum
    rot = np.degrees(s['rot'] - np.array([math.pi / 2, 0, 0]))
    nz = rot
    out['noise_deg'] = float(np.ptp(nz, axis=0).max())
    if n >= 32 and out['noise_deg'] > 1e-6:
        sp = np.abs(np.fft.rfft(nz - nz.mean(axis=0), axis=0)) ** 2
        fr = np.fft.rfftfreq(n, 1 / fps)
        e = sp.sum(axis=1)
        tot = e.sum() + 1e-30
        out['noise_bands'] = [float(e[(fr >= a) & (fr < b)].sum() / tot) for a, b in
                              ((0, 0.5), (0.5, 2), (2, 6), (6, 13))]
    else:
        out['noise_bands'] = [0.0, 0.0, 0.0, 0.0]
    # rack focus legibility: defocus of the far / near side of the product at start and end
    out['rack_a'] = out['rack_b'] = 0.0
    dof = cam.data.dof
    if dof.use_dof and out['focus_shift'] > 1e-6:
        sensor = cam.data.sensor_width
        ctr = np.array(inf.center, dtype=float)
        back = s['pos'][0] - ctr
        back = back / np.linalg.norm(back)
        res = []
        for i in (0, n - 1):
            cp = s['pos'][i]
            near, far = ctr + back * 0.4 * size, ctr - back * 0.4 * size
            dfoc = np.linalg.norm(s['focus'][i] - cp)
            c_near = _coc(s['lens'][i], dof.aperture_fstop, dfoc * 1000, np.linalg.norm(near - cp) * 1000, sensor)
            c_far = _coc(s['lens'][i], dof.aperture_fstop, dfoc * 1000, np.linalg.norm(far - cp) * 1000, sensor)
            res.append((c_far - c_near) * 100)
        out['rack_a'], out['rack_b'] = float(res[0]), float(res[1])
    out['fstop'] = float(dof.aperture_fstop) if dof.use_dof else 0.0
    return out


def measure(sc, f0, f1, fps):
    s, inf, cam = sample(sc, f0, f1)
    m = analyse(s, inf, cam, fps)
    return m, s


def run_cases(pids, shots, durs, keep_series=False):
    sc = bpy.context.scene
    res, series = {}, {}
    for shot in shots:
        api.apply('camera_shot', shot)
        for pid in pids:
            for dur in durs:
                api.apply('camera_motion', pid, duration=dur)
                f0, f1 = core.frame_range(core.settings(sc))
                m, s = measure(sc, f0, f1, int(sc.render.fps))
                res[f"{pid}|{shot}|{dur}"] = m
                if keep_series:
                    series[f"{pid}|{shot}|{dur}"] = s
    return res, series


def dump_curves(outdir, pids):
    """JSON of azimuth / elevation / distance / lens / speed for every preset (hero_34, 200 f) for the plot script."""
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    api.apply('camera_shot', 'hero_34')
    data = {}
    for pid in pids:
        api.apply('camera_motion', pid, duration=200)
        f0, f1 = core.frame_range(core.settings(sc))
        m, s = measure(sc, f0, f1, int(sc.render.fps))
        pos = s['pos'] / core.info().size
        v = np.linalg.norm(np.gradient(pos, axis=0), axis=1) * int(sc.render.fps)
        data[pid] = dict(fps=int(sc.render.fps), az=np.degrees(s['az']).tolist(), el=np.degrees(s['el']).tolist(),
                         dist=(s['dist'] / core.info().size).tolist(), lens=s['lens'].tolist(), speed=v.tolist(),
                         over=s['over'].tolist(), cx=s['cx'].tolist(), cy=s['cy'].tolist(), metrics=m)
    with open(os.path.join(outdir, 'curves.json'), 'w') as fh:
        json.dump(data, fh)


def render_strips(outdir, pids, nframes=8, size=(384, 216)):
    """Workbench renders of nframes frames of every preset (shot hero_34, 200 f): outdir/strip_<id>_<k>.png."""
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    api.apply('camera_shot', 'hero_34')
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = size[0], size[1], 100
    sc.render.image_settings.file_format = 'PNG'
    try:
        sc.display.shading.light = 'STUDIO'
        sc.display.shading.color_type = 'OBJECT'
    except Exception:                                            # noqa: BLE001
        pass
    for pid in pids:
        api.apply('camera_motion', pid, duration=200)
        f0, f1 = core.frame_range(core.settings(sc))
        for k in range(nframes):
            fr = int(round(f0 + (f1 - f0) * k / (nframes - 1)))
            sc.frame_set(fr)
            sc.render.filepath = os.path.join(outdir, f"strip_{pid}_{k}.png")
            bpy.ops.render.render(write_still=True)


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    opt = {}
    for i, a in enumerate(argv):
        if a.startswith('--'):
            opt[a[2:]] = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith('--') else True
    return opt


def main():
    opt = _args()
    pids = opt['presets'].split(',') if 'presets' in opt else list(presets.REGISTRY['camera_motion'])
    shots = opt['shots'].split(',') if 'shots' in opt else list(SHOTS)
    durs = [int(x) for x in opt['durs'].split(',')] if 'durs' in opt else list(DURS)
    setup()
    if 'curves' in opt:
        dump_curves(opt['curves'], pids)
        print('curves written to', opt['curves'])
    if 'strips' in opt:
        render_strips(opt['strips'], pids)
        print('strips written to', opt['strips'])
    if 'json' in opt or ('curves' not in opt and 'strips' not in opt):
        res, _ = run_cases(pids, shots, durs)
        if 'json' in opt:
            with open(opt['json'], 'w') as fh:
                json.dump(res, fh)
        print(f"{len(res)} cases measured" + (f" -> {opt['json']}" if 'json' in opt else ''))
        for pid in pids:
            rows = [v for k, v in res.items() if k.startswith(pid + '|')]
            print(f"{pid:20s} omega<= {max(r['peak_omega'] for r in rows):5.1f}  speed<= {max(r['peak_speed'] for r in rows):5.2f}"
                  f"  J<= {max(r['jerk_index'] for r in rows):6.0f}  out<= {max(r['pct_out'] for r in rows):5.1f}%"
                  f"  over<= {max(r['max_over'] for r in rows):.2f}")


if __name__ == '__main__':
    main()
