"""Coverage check: does the backdrop fill the frame? The cyclorama is open (floor + curved wall), so orbits, top-down or
low shots can show the void behind it.

Geometric test, not an angle rule: at ~10 frames sampled over the range, rays go from the camera through a 7x7 grid of
frame points (edges and corners included) against the PMS backdrop and floor meshes (BVH). The product is ignored: it
stands in front of the backdrop. Result: warning text in scene.pms.coverage ('' = fine), also returned as a list.
Run by api.run after any step that changes camera, backdrop, floor, format or animation (never from a draw())."""

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from . import core

GRID = 7
SAMPLES = 10
NAMES = ('PMS_Background', 'PMS_Floor')
TIPS = {'cyclorama': "Use a 360 background or shorten the orbit.",
        'studio360': "Lower the camera height or tilt.",
        'image': "Use a larger image or reduce the camera movement."}


def _frames_text(frames):
    """[1, 2, 3, 7] with consecutive samples merged: '1-3, 7'."""
    return ', '.join(str(a) if a == b else f"{a}-{b}" for a, b in frames)


def check(scene):
    """Update scene.pms.coverage and return the list of warnings (empty when the frame is always covered)."""
    pms = core.settings(scene)
    pms.coverage = ''
    cam = bpy.data.objects.get('PMS_Camera')
    obs = [o for o in (bpy.data.objects.get(n) for n in NAMES) if o is not None]
    if cam is None or not obs or scene.render.film_transparent:       # no camera/backdrop, or alpha film on purpose
        return []
    f0, f1, current = scene.frame_start, scene.frame_end, scene.frame_current
    samples = sorted({round(f0 + (f1 - f0) * i / (SAMPLES - 1)) for i in range(SAMPLES)})
    grid = [(-1 + 2 * i / (GRID - 1), -1 + 2 * j / (GRID - 1)) for i in range(GRID) for j in range(GRID)]
    miss_at = {}
    for f in samples:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        cam_eval = cam.evaluated_get(dg)
        tx, ty = core.frame_tans(scene, cam_eval.data.lens)
        mw = cam_eval.matrix_world
        trees = [(BVHTree.FromObject(o, dg), o.evaluated_get(dg).matrix_world.inverted()) for o in obs]
        miss = 0
        for x, y in grid:
            d = mw.to_3x3() @ Vector((x * tx, y * ty, -1.0))
            if not any(t.ray_cast(inv @ mw.translation, (inv.to_3x3() @ d).normalized())[0] is not None
                       for t, inv in trees):
                miss += 1
        if miss:
            miss_at[f] = miss / len(grid)
    scene.frame_set(current)
    if not miss_at:
        return []
    runs, start, prev = [], None, None                                  # merge consecutive failing samples
    for f in samples:
        if f in miss_at:
            start = f if start is None else start
            prev = f
        elif start is not None:
            runs.append((start, prev))
            start = None
    if start is not None:
        runs.append((start, prev))
    kind = core.preset(scene, 'background')[1].get('kind')
    text = (f"The backdrop does not fill the frame ({'frame' if len(runs) == 1 and runs[0][0] == runs[0][1] else 'frames'} "
            f"{_frames_text(runs)}: the void shows, up to {max(miss_at.values()):.0%}). "
            f"{TIPS.get(kind, TIPS['image'])}")
    pms.coverage = text
    return [text]
