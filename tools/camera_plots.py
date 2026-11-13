"""Contact sheets for the camera_motion review (system python3 with matplotlib + Pillow, NOT Blender).

    python3 plugin/tools/camera_plots.py OUTDIR [--per-sheet 5]
OUTDIR is the folder written by
    Blender -b --factory-startup --python plugin/tools/camera_report.py -- --curves OUTDIR --strips OUTDIR
It writes OUTDIR/strips_N.png (8 Workbench frames per preset), OUTDIR/curves_N.png (azimuth, elevation, distance,
lens, speed over time) and OUTDIR/provino_camera_motion.png (all strips in one image)."""

import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

THUMB = (240, 135)


def strip(outdir, pid, n=8, size=THUMB):
    im = Image.new('RGB', (size[0] * n, size[1] + 16), (24, 24, 24))
    ImageDraw.Draw(im).text((4, 2), pid, fill=(255, 255, 255))
    for k in range(n):
        p = os.path.join(outdir, f"strip_{pid}_{k}.png")
        if os.path.exists(p):
            im.paste(Image.open(p).convert('RGB').resize(size), (k * size[0], 16))
    return im


def main():
    outdir = sys.argv[1]
    per = int(sys.argv[sys.argv.index('--per-sheet') + 1]) if '--per-sheet' in sys.argv else 5
    data = json.load(open(os.path.join(outdir, 'curves.json')))
    ids = list(data)
    for i in range(0, len(ids), per):
        part = ids[i:i + per]
        sheet = Image.new('RGB', (THUMB[0] * 8, (THUMB[1] + 16) * len(part)))
        for j, pid in enumerate(part):
            sheet.paste(strip(outdir, pid), (0, j * (THUMB[1] + 16)))
        sheet.save(os.path.join(outdir, f"strips_{i // per + 1}.png"))
        fig, axs = plt.subplots(len(part), 5, figsize=(15, 2.1 * len(part)), squeeze=False)
        for j, pid in enumerate(part):
            d = data[pid]
            t = [k / d['fps'] for k in range(len(d['az']))]
            for ax, key, lab in zip(axs[j], ('az', 'el', 'dist', 'lens', 'speed'),
                                    ('azimuth deg', 'elevation deg', 'distance (size)', 'lens mm', 'speed size/s')):
                ax.plot(t, d[key], lw=1.2)
                ax.set_title(f"{pid}: {lab}" if key == 'az' else lab, fontsize=8)
                ax.tick_params(labelsize=6)
                ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, f"curves_{i // per + 1}.png"), dpi=70)
        plt.close(fig)
    small = (160, 90)
    big = Image.new('RGB', (small[0] * 8, (small[1] + 16) * len(ids)))
    for j, pid in enumerate(ids):
        big.paste(strip(outdir, pid, size=small), (0, j * (small[1] + 16)))
    big.save(os.path.join(outdir, 'provino_camera_motion.png'))
    print('written', outdir)


if __name__ == '__main__':
    main()
