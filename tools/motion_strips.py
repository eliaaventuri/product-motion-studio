"""Visual review of the product_motion presets: Workbench frames (NEVER Eevee / Cycles) + curve csv, for tools/motion_sheet.py.

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python plugin/tools/motion_strips.py -- \
        --out DIR [--only id,id] [--dur 200] [--size 320]
    python3 plugin/tools/motion_sheet.py DIR            (system python with PIL + matplotlib: strips, curves, contact sheets)

Per preset it writes DIR/<id>/ with 8 frames equidistant over the WHOLE shot (a_0..a_7.png), 8 frames equidistant over the
action window (b_0..b_7.png, from just before the first movement to just after the last), a curves csv and a meta json
(frame numbers, measures). The test product is Suzanne (orange) + a cylinder (blue), the camera is the fixed hero_34 shot."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy

import motion_report as mr
from product_motion_studio import api, core, presets


def _args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    opt = dict(out=None, only=None, dur=200, size=320)
    for i, a in enumerate(argv):
        if a == '--out':
            opt['out'] = argv[i + 1]
        elif a == '--only':
            opt['only'] = argv[i + 1].split(',')
        elif a == '--dur':
            opt['dur'] = int(argv[i + 1])
        elif a == '--size':
            opt['size'] = int(argv[i + 1])
    return opt


def setup(size):
    objs = mr.make_product('suzanne')
    for ob, col in zip(objs, ((1.0, 0.45, 0.12, 1), (0.15, 0.4, 0.9, 1))):
        ob.color = col
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = 'STUDIO', 'OBJECT', False, True
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.resolution_percentage = 100
    return objs


def render(path, size):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size, round(size * 9 / 16)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def main():
    opt = _args()
    mr.pkg.register()
    setup(opt['size'])
    sc = bpy.context.scene
    ids = opt['only'] or list(presets.REGISTRY['product_motion'])
    for pid in ids:
        d = os.path.join(opt['out'], pid)
        os.makedirs(d, exist_ok=True)
        s = mr.sample(pid, opt['dur'])
        m = mr.measure(s)
        mr.collect_csv(s, m, os.path.join(d, 'curves'))
        f0, f1, fps = s['f0'], s['f1'], mr.FPS
        n_whole = f1 - f0
        a_frames = [f0 + round(k * n_whole / 7) for k in range(8)]
        t0 = max(0.0, m['action_start_s'] - 0.1)
        t1 = min(n_whole / fps, m['action_start_s'] + m['action_s'] + 0.45)
        if t1 - t0 < 0.5:
            t1 = min(n_whole / fps, t0 + 1.0)
        b_frames = [f0 + round((t0 + k * (t1 - t0) / 7) * fps) for k in range(8)]
        api.apply('product_motion', pid, duration=opt['dur'], fps=mr.FPS)
        for row, frames in (('a', a_frames), ('b', b_frames)):
            for k, f in enumerate(frames):
                sc.frame_set(f)
                render(os.path.join(d, f'{row}_{k}.png'), opt['size'])
        with open(os.path.join(d, 'meta.json'), 'w') as fh:
            json.dump(dict(pid=pid, a=a_frames, b=b_frames, f0=f0, f1=f1, fps=fps, bad=mr.check(m, s),
                           action_s=m['action_s'], hold_s=m['hold_s'], peak_lin=m['peak_lin'], peak_ang=m['peak_ang'],
                           family=s['p'].category), fh)
    print('strips done', len(ids))


if __name__ == '__main__':
    main()
