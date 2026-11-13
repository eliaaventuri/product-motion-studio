"""Background light: rig Empty PMS_BgLight_Rig at the product centre with lights that light only the backdrop and the floor
(light linking, see build_lighting.backdrop_receivers). Power and colour are live controls (live.apply_bg_lights)."""

from math import radians
from . import build_compositing, core, live
from .build_lighting import _light, backdrop_receivers


def build(scene):
    core.begin(scene)
    build_compositing.sync_ev(scene)                        # Cycles exposure compensation follows the presets in use
    pms = core.settings(scene)
    inf = core.info(scene)
    core.clear_section(scene, 'bg_lights')
    p, data = live.preset(scene, 'background_light')
    if not data['lights']:
        return {'background_light': p.id, 'lights': [], 'rig': None, 'warnings': []}
    rig = core.new_empty(scene, 'bg_lights', 'PMS_BgLight_Rig', inf.center, 'PLAIN_AXES', inf.size * 0.1)
    rig.rotation_euler = (0, 0, radians(pms.base_az))
    receivers = backdrop_receivers(scene)
    lights = [_light(scene, rig, dict(spec, only='backdrop'), i, inf.size, receivers, 'bg_lights', 'PMS_BgLight')
              for i, spec in enumerate(data['lights'])]
    live.apply_bg_lights(scene)
    return {'background_light': p.id, 'lights': [o.name for o in lights], 'rig': rig.name, 'warnings': []}
