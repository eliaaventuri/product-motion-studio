"""Builds the review images of the product_motion presets from the folder written by tools/motion_strips.py.
Run it with the SYSTEM python (needs PIL and matplotlib; Blender's python has neither):

    python3 plugin/tools/motion_sheet.py DIR [--only id,id] [--thumb 160]

DIR/sheet_<id>.png   title + measures, row A (8 frames over the whole shot), row B (8 frames over the action window)
DIR/curves_<id>.png  location (size units), rotation (degrees, world axes), scale, floor gap and life yaw vs time
DIR/family_<family>.png  all the sheets of a family stacked;  DIR/provino.png  every preset, both rows, small"""

import csv
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

COLORS = ('#d1495b', '#2e7d32', '#1d4ed8')


def _font(sz):
    for p in ('/System/Library/Fonts/Menlo.ttc', '/System/Library/Fonts/Helvetica.ttc'):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def sheet(d, pid, thumb):
    meta = json.load(open(os.path.join(d, pid, 'meta.json')))
    fps = meta['fps']
    w, h = thumb, round(thumb * 9 / 16)
    img = Image.new('RGB', (8 * w, 2 * h + 36), (24, 24, 28))
    dr = ImageDraw.Draw(img)
    f = _font(11)
    flag = '  !! ' + '; '.join(meta['bad']) if meta['bad'] else ''
    dr.text((6, 4), f"{pid} [{meta['family']}]  action {meta['action_s']:.2f}s  hold {meta['hold_s']:.2f}s  "
                    f"v {meta['peak_lin']:.1f} size/s  w {meta['peak_ang']:.0f} deg/s{flag}", font=f, fill=(255, 120, 120) if meta['bad'] else (235, 235, 235))
    for r, row in enumerate('ab'):
        for k in range(8):
            im = Image.open(os.path.join(d, pid, f'{row}_{k}.png')).convert('RGB').resize((w, h))
            img.paste(im, (k * w, 36 + r * h))
            fr = meta[row][k]
            dr.text((k * w + 3, 36 + r * h + 2), f"{row}{k} f{fr} {(fr - meta['f0']) / fps:.2f}s", font=_font(9), fill=(255, 255, 0))
    img.save(os.path.join(d, f'sheet_{pid}.png'))
    return img


def curves(d, pid):
    meta = json.load(open(os.path.join(d, pid, 'meta.json')))
    rows = list(csv.DictReader(open(os.path.join(d, pid, 'curves.csv'))))
    fps = meta['fps']
    t = [(int(r['frame']) - meta['f0']) / fps for r in rows]
    fig, ax = plt.subplots(5, 1, figsize=(10, 9), sharex=True)
    groups = (('loc', 'location (size)', 1.0), ('rot', 'rotation (deg, world, accumulated)', 1.0), ('scl', 'scale', 1.0))
    for a, (pre, title, _) in zip(ax, groups):
        for i, c in enumerate('xyz'):
            v = [float(r[pre + c]) for r in rows]
            v = [x - v[0] for x in v] if pre != 'scl' else v
            a.plot(t, v, color=COLORS[i], lw=1.2, label=c)
        a.set_ylabel(title, fontsize=7)
        a.grid(alpha=0.25)
    ax[3].plot(t, [float(r['floor_gap']) * 100 for r in rows], color='#555', lw=1.2)
    ax[3].set_ylabel('lowest corner above floor (% size)', fontsize=7)
    ax[3].grid(alpha=0.25)
    ax[4].plot(t, [float(r['life']) for r in rows], color='#999', lw=1.2)
    ax[4].set_ylabel('life yaw (deg)', fontsize=7)
    ax[4].set_xlabel('seconds')
    ax[4].grid(alpha=0.25)
    for a in ax:
        a.axvspan(meta['action_s'] and (meta['b'][0] - meta['f0']) / fps, (meta['b'][7] - meta['f0']) / fps, color='#fc0', alpha=0.08)
        a.tick_params(labelsize=7)
    ax[0].legend(fontsize=7, ncol=3, loc='upper right')
    fig.suptitle(f"{pid}  action {meta['action_s']:.2f}s  hold {meta['hold_s']:.2f}s", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(d, f'curves_{pid}.png'), dpi=70)
    plt.close(fig)


def main():
    argv = sys.argv[1:]
    d = argv[0]
    only = argv[argv.index('--only') + 1].split(',') if '--only' in argv else None
    thumb = int(argv[argv.index('--thumb') + 1]) if '--thumb' in argv else 160
    ids = [x for x in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, x, 'meta.json')) and (not only or x in only)]
    fams = {}
    imgs = {}
    for pid in ids:
        imgs[pid] = sheet(d, pid, thumb)
        curves(d, pid)
        fams.setdefault(json.load(open(os.path.join(d, pid, 'meta.json')))['family'], []).append(pid)
    for fam, pids in fams.items():
        for n in range(0, len(pids), 6):
            chunk = pids[n:n + 6]
            big = Image.new('RGB', (imgs[chunk[0]].width, sum(imgs[p].height for p in chunk)))
            y = 0
            for p in chunk:
                big.paste(imgs[p], (0, y))
                y += imgs[p].height
            big.save(os.path.join(d, f'family_{fam}_{n // 6}.png'))
    if not only:
        small = [Image.open(os.path.join(d, f'sheet_{p}.png')) for p in ids]
        sw = max(i.width for i in small)
        prov = Image.new('RGB', (sw * 2, ((len(small) + 1) // 2) * small[0].height))
        for k, im in enumerate(small):
            prov.paste(im, ((k % 2) * sw, (k // 2) * im.height))
        prov.save(os.path.join(d, 'provino.png'))
    print('sheets', len(ids))


if __name__ == '__main__':
    main()
