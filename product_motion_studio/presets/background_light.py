"""BACKGROUND LIGHT presets: DATA dicts, lights that light ONLY the backdrop and the floor (light linking, like the
silhouette presets of 'lighting'), never the product. Use them to shape the background (pools, washes, gradients, halos)
independently from the product lighting.

SCHEMA   register('background_light', id, name, category, desc, data=dict(lights=[dict(...), ...]))
         Same light dicts as the 'lighting' section (role, type, shape, az, el, dist_f, size_f, power_ref, kelvin/rgb,
         spot_size, blend) with two differences: every light carries only='backdrop' and aim=(az, el, dist_f) is the point of
         the backdrop it lights (az 180 = the wall behind the product). 'none' has an empty list: no lights, no rig.
RULES    - Sizes, distances and watts scale with the product size exactly like the 'lighting' presets (never absolute).
         - Colour and power are live controls in the panel (Colour = tint, Power = multiplier); the preset values are the
           defaults. The backdrop colours (albedo 0.1-0.45) are lifted by these lights: keep power_ref moderate.
OPTIONAL cycles_ev=stops (+ brighter) in data: extra Cycles exposure compensation of the preset, see CYCLES_EV at the end of the file.
"""

from . import REGISTRY, register

register('background_light', 'none', 'None', 'none', 'No dedicated background light: the backdrop is lit by the studio lights and its own self light.',
         data=dict(lights=[]))

register('background_light', 'soft_wash', 'Soft Wash', 'wash',
         'Two big soft panels from the sides wash the whole wall evenly: lifts a dark backdrop without a visible source.',
         data=dict(lights=[
             dict(role='wash', type='AREA', shape='RECTANGLE', az=-75, el=22, dist_f=3.6, size_f=(3.0, 3.0), power_ref=95,
                  kelvin=6000, aim=(180, 16, 5.4), only='backdrop'),
             dict(role='wash', type='AREA', shape='RECTANGLE', az=75, el=22, dist_f=3.6, size_f=(3.0, 3.0), power_ref=95,
                  kelvin=6000, aim=(180, 16, 5.4), only='backdrop')]))

register('background_light', 'spot_pool', 'Spot Pool', 'spot',
         'One soft spot makes a pool of light on the wall right behind the product and lets the edges fall into shade.',
         data=dict(lights=[
             dict(role='pool', type='SPOT', az=0, el=48, dist_f=4.0, size_f=(0.25, 0.25), power_ref=1100, kelvin=5600,
                  spot_size=42, blend=0.9, aim=(180, 7, 5.0), only='backdrop')]))

register('background_light', 'top_gradient', 'Top Gradient', 'gradient',
         'A wide strip above and behind the product lights the wall from the top: a smooth bright-to-dark gradient downwards.',
         data=dict(lights=[
             dict(role='gradient', type='AREA', shape='RECTANGLE', az=170, el=62, dist_f=3.8, size_f=(5.0, 1.2), power_ref=95,
                  kelvin=5600, aim=(180, 26, 5.6), only='backdrop')]))

register('background_light', 'side_sweep', 'Side Sweep', 'gradient',
         'A long panel from one side grazes the wall: a diagonal sweep of light from one edge of the frame to the other.',
         data=dict(lights=[
             dict(role='sweep', type='AREA', shape='RECTANGLE', az=95, el=18, dist_f=5.2, size_f=(0.8, 4.5), power_ref=160,
                  kelvin=5200, aim=(180, 20, 5.6), only='backdrop')]))

register('background_light', 'rim_glow', 'Rim Glow', 'glow',
         'A low warm panel between product and wall: a glowing halo behind the product that separates it from the backdrop.',
         data=dict(lights=[
             dict(role='glow', type='AREA', shape='DISK', az=180, el=16, dist_f=3.2, size_f=(3.4, 3.4), power_ref=75,
                  kelvin=3800, aim=(180, 8, 5.2), only='backdrop')]))


# CYCLES COMPENSATION: Cycles has the studio's bounces and Eevee has not, so build_compositing.CYCLES_EV takes half a stop off every
# Cycles render; these are the presets that need more or less than that (stops, + = brighter), measured with the test scene against
# Eevee (STATO.md, "Cycles"). They add up with the ones of the other sections.  Re-measure after changing the lights.
CYCLES_EV = {
    'soft_wash': -0.15,
    'spot_pool': -0.25,
    'side_sweep': -0.45,
}
for _id, _ev in CYCLES_EV.items():
    REGISTRY['background_light'][_id].data['cycles_ev'] = _ev
