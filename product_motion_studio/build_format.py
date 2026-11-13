"""Format: resolution, fps, frame range, render engine (no objects)."""

from . import core


def build(scene):
    core.begin(scene)
    pms = core.settings(scene)
    _, data = core.preset(scene, 'format')
    r = scene.render
    r.resolution_x, r.resolution_y = data['res']
    r.resolution_percentage = scene.get('pms_pct', 100)       # the Render panel's quality sets it
    r.fps, r.fps_base = int(pms.fps), 1.0
    f0, f1 = core.frame_range(pms)
    loop = core.is_loop(scene)
    scene.frame_start, scene.frame_end = f0, f1 - 1 if loop else f1      # a loop's last key repeats the first: not rendered
    if hasattr(scene.eevee, 'use_raytracing'):
        scene.eevee.use_raytracing = True      # Eevee (and Material Preview) without it: metal and glass reflect nothing and look black
    warnings = []
    if pms.engine != 'KEEP':
        try:
            r.engine = pms.engine
        except TypeError:
            warnings.append(f"engine {pms.engine} not available")
    out = {'resolution': tuple(data['res']), 'frames': (scene.frame_start, scene.frame_end), 'fps': int(pms.fps),
           'loop': loop, 'warnings': warnings}
    if loop:
        out['note'] = f"Loop: frame_end = {f1 - 1} (keys reach {f1}, same as {f0}: the duplicate frame is not rendered)"
    return out
