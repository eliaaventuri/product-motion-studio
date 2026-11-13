"""FLOOR presets: DATA dicts for the ground under the product.

SCHEMA   register('floor', id, name, category, desc, data=dict(
             kind='none' | 'seamless' (the backdrop's own floor, same material) | 'plane' (separate plane PMS_Floor),
             color=(r, g, b) or None (None = colour of the backdrop), roughness=0..1, metallic=0..1,
             shadow_catcher=True (Cycles shadow catcher + transparent film; the backdrop is hidden from the camera)))
RULES    - The plane is sized from the backdrop layout (build_background.layout), never in absolute units.
         - It sits exactly on the product base (z of the lowest point), the backdrop 0.1% of size below it.
"""

from . import REGISTRY, register

register('floor', 'none', 'None', 'none', 'No floor (the product floats over the backdrop).', data=dict(kind='none'))
register('floor', 'matte', 'Matte', 'plane', 'Matte plane, backdrop colour.', data=dict(kind='plane', roughness=0.85, metallic=0.0))
register('floor', 'glossy', 'Glossy', 'plane', 'Glossy plane with soft reflections.', data=dict(kind='plane', roughness=0.15, metallic=0.0))
register('floor', 'mirror', 'Mirror', 'plane', 'Mirror floor: sharp reflection of the product.',
         data=dict(kind='plane', roughness=0.03, metallic=1.0, color=(0.55, 0.55, 0.58)))
register('floor', 'shadow_catcher', 'Shadow Catcher', 'plane',
         'Only the shadow stays on a transparent background (Cycles).',
         data=dict(kind='plane', roughness=0.85, metallic=0.0, shadow_catcher=True))
register('floor', 'seamless', 'Seamless', 'seamless', 'Floor and wall are one continuous surface (cyclorama).', data=dict(kind='seamless'))

register('floor', 'dark_glossy', 'Dark Glossy', 'plane',
         'Near-black glossy plane: soft reflections of the product and of the lights, the backdrop keeps its own colour behind.',
         data=dict(kind='plane', roughness=0.15, metallic=0.0, color=(0.03, 0.035, 0.045)))

register('floor', 'satin', 'Satin', 'plane',
         'Satin plane, backdrop colour: soft blurred reflections, no mirror-like hot spots from the lights.',
         data=dict(kind='plane', roughness=0.3, metallic=0.0))

# Cycles exposure compensation of the preset (stops, see build_compositing.CYCLES_EV): a mirror floor throws back the bright studio
# in Cycles much more than Eevee does.
REGISTRY['floor']['mirror'].data['cycles_ev'] = -0.5
