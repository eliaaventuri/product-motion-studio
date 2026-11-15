"""FLOOR presets: DATA dicts for the ground under the product.

SCHEMA   register('floor', id, name, category, desc, data=dict(
             kind='none' | 'seamless' (the backdrop's own floor, same material) | 'plane' (separate plane PMS_Floor),
             color=(r, g, b) or None (None = colour of the backdrop), roughness=0..1, metallic=0..1,
             shadow_catcher=True (Cycles shadow catcher + transparent film; the backdrop is hidden from the camera),
             surface='asphalt'|'obsidian'|'acrylic'|'water' optional: procedural surface on the floor plane,
             no_light_reflections=True optional: exclude product lights from lighting this floor (for dark glossy floors)))
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

# === New floors with surface ================================================================

register('floor', 'wet_asphalt_micro', 'Wet Asphalt Micro', 'material',
         'Micro-textured wet asphalt with puddle reflections.',
         data=dict(kind='plane', color=(0.035, 0.035, 0.038), roughness=0.4, metallic=0.0, surface='asphalt'))

register('floor', 'obsidian_black_glass', 'Obsidian Black Glass', 'material',
         'Obsidian black glass: roughness grows with distance from product.',
         data=dict(kind='plane', color=(0.012, 0.012, 0.014), roughness=0.02, metallic=0.0, surface='obsidian',
                   no_light_reflections=True))

register('floor', 'frosted_acrylic_matte', 'Frosted Acrylic Matte', 'material',
         'Frosted acrylic with subsurface scattering and clear coat.',
         data=dict(kind='plane', color=(0.80, 0.81, 0.83), roughness=0.42, metallic=0.0, surface='acrylic'))

register('floor', 'rippled_water_pool', 'Rippled Water Pool', 'material',
         'Water pool with concentric ripples fading from center.',
         data=dict(kind='plane', color=(0.02, 0.045, 0.06), roughness=0.04, metallic=0.0, surface='water',
                   no_light_reflections=True))
