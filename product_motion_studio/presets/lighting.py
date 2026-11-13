"""LIGHTING presets: DATA dicts describing a light rig around the product.

SCHEMA   register('lighting', id, name, category, desc, product_types=[...], style='soft|hard|dark|...', data=dict(
             lights=[dict(role=str, type='AREA'|'SPOT'|'POINT'|'SUN', shape='RECTANGLE'|'SQUARE'|'DISK'|'ELLIPSE',
                          az=deg (0 = camera side, +az -> +X, 180 = behind the product), el=deg above the product centre,
                          dist_f=distance as MULTIPLE of the product size,
                          size_f=(x, y) light size as multiple of the product size (area; spot/point use x as radius),
                          power_ref=Watts the light would have on a product of size 1 m (SUN: strength, not scaled),
                          kelvin=K or rgb=(r, g, b), spot_size=deg, blend=0..1,
                          aim=(az, el, dist_f) optional point to aim at (default: the product centre; e.g. the backdrop),
                          only='backdrop' optional: light linking, this light lights only the backdrop and floor, never the product), ...],
             world_strength=0..0.02 (world is black unless you need reflections; same scale as the lights), world_color=(r, g, b)))
RULES    - Everything is relative to size: positions = dist_f * size, sizes = size_f * size, watts = power_ref * size**2
           (same exposure for a 2 cm and a 2 m product). Never use absolute units.
         - az is relative to the camera of the base shot (the rig follows the shot). Roles: key, fill, rim, top, spec, back.
         - Rule of thumb from the references: key strongest, fill larger and weaker, rim harder; one job per light;
           world low. MEASURED (Eevee, glass + metal + plastic test product, AgX, grey cyclorama): a light with
           power_ref ~ 3.5 * dist_f**2 W (size 1 m) gives a normal exposure (mean product luminance 0.35-0.55 after the
           view transform); dark styles ~ 2 * dist_f**2 (luminance 0.15-0.35). The old 120 * dist_f**2 over-exposed ~30x.
           The world is scaled with the lights (same factor), so keep world_strength <= 0.02.
         - product_types: beauty, glass, jewellery, packaging, tech, cosmetics, food, automotive, metal.
OPTIONAL cycles_ev=stops (+ brighter) in data: extra Cycles exposure compensation of the preset, see CYCLES_EV at the end of the file.
"""

from . import REGISTRY, register

register('lighting', 'beauty_soft', 'Beauty Soft', 'beauty', 'Big soft key, wide fill, top softbox, rim and a small spec light.',
         product_types=['beauty', 'cosmetics', 'packaging', 'tech'], style='soft',
         data=dict(world_strength=0.0045, lights=[
             dict(role='key', type='AREA', shape='RECTANGLE', az=-35, el=35, dist_f=2.2, size_f=(1.2, 1.2), power_ref=27, kelvin=5600),
             dict(role='fill', type='AREA', shape='RECTANGLE', az=45, el=12, dist_f=2.6, size_f=(1.8, 1.4), power_ref=10, kelvin=6000),
             dict(role='top', type='AREA', shape='DISK', az=0, el=75, dist_f=2.0, size_f=(1.6, 1.6), power_ref=14, kelvin=5600),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=160, el=25, dist_f=2.4, size_f=(0.5, 1.4), power_ref=17, kelvin=6500),
             dict(role='spec', type='AREA', shape='SQUARE', az=-60, el=20, dist_f=2.5, size_f=(0.25, 0.25), power_ref=6.8, kelvin=5600)]))

register('lighting', 'rim_only', 'Rim Only', 'teaser', 'Two tall strips behind the product: contours only, for teasers and silhouettes.',
         product_types=['glass', 'tech', 'automotive'], style='dark',
         data=dict(world_strength=0.0, lights=[
             dict(role='rim', type='AREA', shape='RECTANGLE', az=140, el=15, dist_f=2.2, size_f=(0.35, 1.8), power_ref=43, kelvin=6500),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=-140, el=15, dist_f=2.2, size_f=(0.35, 1.8), power_ref=43, kelvin=6500)]))

register('lighting', 'three_point_classic', 'Three-Point Classic', 'classic', 'Key, large weak fill, small hard back light.',
         product_types=['packaging', 'tech', 'food'], style='classic',
         data=dict(world_strength=0.0021, lights=[
             dict(role='key', type='AREA', shape='RECTANGLE', az=-45, el=40, dist_f=2.2, size_f=(0.9, 0.9), power_ref=28, kelvin=5500),
             dict(role='fill', type='AREA', shape='RECTANGLE', az=50, el=15, dist_f=2.4, size_f=(1.8, 1.8), power_ref=11, kelvin=5500),
             dict(role='back', type='AREA', shape='SQUARE', az=165, el=35, dist_f=2.2, size_f=(0.4, 0.4), power_ref=21, kelvin=6000)]))

register('lighting', 'hard_strips', 'Hard Strips', 'metal', 'Four narrow vertical strips plus a top strip: long reflections on metal.',
         product_types=['metal', 'automotive', 'jewellery', 'tech'], style='hard',
         data=dict(world_strength=0, lights=[
             dict(role='key', type='AREA', shape='RECTANGLE', az=55, el=8, dist_f=2.2, size_f=(0.22, 1.7), power_ref=19, kelvin=5600),
             dict(role='key', type='AREA', shape='RECTANGLE', az=-55, el=8, dist_f=2.2, size_f=(0.22, 1.7), power_ref=19, kelvin=5600),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=125, el=10, dist_f=2.2, size_f=(0.22, 1.7), power_ref=17, kelvin=6200),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=-125, el=10, dist_f=2.2, size_f=(0.22, 1.7), power_ref=17, kelvin=6200),
             dict(role='top', type='AREA', shape='RECTANGLE', az=0, el=70, dist_f=2.0, size_f=(0.3, 1.5), power_ref=12, kelvin=5600)]))

register('lighting', 'dark_luxury_contour', 'Dark Luxury Contour', 'luxury', 'Black scene, cool and warm contour strips, one tight top spot.',
         product_types=['jewellery', 'cosmetics', 'beauty', 'metal'], style='dark',
         data=dict(world_strength=0.0, lights=[
             dict(role='rim', type='AREA', shape='RECTANGLE', az=115, el=12, dist_f=2.2, size_f=(0.25, 1.6), power_ref=23, kelvin=7500),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=-115, el=12, dist_f=2.2, size_f=(0.25, 1.6), power_ref=23, kelvin=3800),
             dict(role='top', type='SPOT', az=0, el=75, dist_f=2.4, size_f=(0.3, 0.3), power_ref=18, kelvin=4500, spot_size=28, blend=0.6),
             dict(role='fill', type='AREA', shape='RECTANGLE', az=-30, el=10, dist_f=2.6, size_f=(2.0, 1.4), power_ref=1.8, kelvin=5600)]))

register('lighting', 'glass_edges', 'Glass Edges', 'glass', 'Big back panel and two side strips so glass reads by its bright edges.',
         product_types=['glass', 'cosmetics', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             dict(role='back', type='AREA', shape='RECTANGLE', az=180, el=8, dist_f=2.4, size_f=(2.6, 1.8), power_ref=15, kelvin=6000),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=80, el=10, dist_f=2.2, size_f=(0.3, 1.6), power_ref=11, kelvin=6500),
             dict(role='rim', type='AREA', shape='RECTANGLE', az=-80, el=10, dist_f=2.2, size_f=(0.3, 1.6), power_ref=11, kelvin=6500),
             dict(role='fill', type='AREA', shape='RECTANGLE', az=0, el=5, dist_f=3.0, size_f=(2.0, 1.2), power_ref=1.5, kelvin=5600)]))


# ---------------------------------------------------------------------------------------------------
# Compact builders for the presets below (same dict schema as above, just shorter to write).
# Categories: beauty, glass, jewellery, metal, packaging, tech, food, automotive, luxury, highkey,
# lowkey, color, halo, silhouette, dramatic.

def _a(role, az, el, d, size, power, kelvin=5600, shape='RECTANGLE', rgb=None):
    """AREA light; size = (x, y) as multiple of the product size (SQUARE/DISK use x only)."""
    spec = dict(role=role, type='AREA', shape=shape, az=az, el=el, dist_f=d, size_f=size, power_ref=power)
    spec.update(rgb=rgb) if rgb else spec.update(kelvin=kelvin)
    return spec


def _s(role, az, el, d, radius, power, kelvin=5600, cone=28, blend=0.5, rgb=None):
    """SPOT light (radius = soft size as multiple of the product size)."""
    spec = dict(role=role, type='SPOT', az=az, el=el, dist_f=d, size_f=(radius, radius), power_ref=power,
                spot_size=cone, blend=blend)
    spec.update(rgb=rgb) if rgb else spec.update(kelvin=kelvin)
    return spec


# --- beauty / cosmetics -----------------------------------------------------------------------------
register('lighting', 'beauty_clamshell', 'Beauty Clamshell', 'beauty', 'Big top softbox plus a low front reflector (clamshell) and two thin rims.',
         product_types=['beauty', 'cosmetics', 'packaging'], style='soft',
         data=dict(world_strength=0.0037, lights=[
             _a('key', 0, 55, 2.2, (1.6, 1.0), 29), _a('fill', 0, 4, 2.4, (1.8, 0.6), 12),
             _a('rim', 150, 20, 2.4, (0.35, 1.5), 16, 6500), _a('rim', -150, 20, 2.4, (0.35, 1.5), 16, 6500)]))

register('lighting', 'beauty_butterfly', 'Beauty Butterfly', 'beauty', 'High frontal key, low fill, back hair light and a thin kicker.',
         product_types=['beauty', 'cosmetics'], style='soft',
         data=dict(world_strength=0.0029, lights=[
             _a('key', 0, 60, 2.2, (1.0, 1.0), 28, 5500), _a('fill', 0, 8, 2.6, (2.0, 1.2), 9.8),
             _a('back', 180, 50, 2.4, (0.8, 0.8), 21, 6000), _a('rim', -120, 20, 2.4, (0.3, 1.4), 14, 6500)]))

register('lighting', 'cosmetics_window_wrap', 'Cosmetics Window Wrap', 'beauty', 'Large side window, wrap-around fill, soft top and a cool back rim.',
         product_types=['cosmetics', 'beauty', 'packaging'], style='soft',
         data=dict(world_strength=0.006, lights=[
             _a('key', -65, 30, 2.4, (1.8, 1.4), 39, 5200), _a('fill', 65, 20, 2.6, (1.2, 1.2), 12),
             _a('top', 0, 80, 2.0, (1.2, 1.2), 11, 5600, 'DISK'), _a('rim', 170, 25, 2.4, (0.4, 1.4), 18, 6500)]))

register('lighting', 'matte_cream_sun', 'Matte Cream Sun', 'beauty', 'One soft sun (angle 4 deg) and a huge weak fill: flat colours, creams, sun-care.',
         product_types=['cosmetics', 'packaging', 'beauty'], style='hard',
         data=dict(world_strength=0.021, lights=[
             dict(role='key', type='SUN', az=-40, el=45, dist_f=3.0, power_ref=0.73, kelvin=5400, angle=4.0),
             _a('fill', 50, 15, 2.8, (2.4, 1.8), 33), _a('rim', 160, 30, 2.4, (0.5, 1.2), 52, 6500)]))

register('lighting', 'beauty_pastel_glow', 'Beauty Pastel Glow', 'beauty', 'Two big symmetric softboxes, soft dome and a low back fill: airy and pale.',
         product_types=['beauty', 'cosmetics'], style='soft',
         data=dict(world_strength=0.0054, lights=[
             _a('key', -40, 25, 2.5, (1.8, 1.8), 23, 5200), _a('fill', 40, 25, 2.5, (1.8, 1.8), 23, 5400),
             _a('top', 0, 78, 2.0, (1.8, 1.8), 14, 5600, 'DISK'), _a('back', 180, 10, 2.6, (2.4, 1.2), 9.9, 6500)]))

register('lighting', 'lipstick_strips', 'Lipstick Strips', 'beauty', 'Two tall front strips for clean highlights on tubes, soft top-front, one rim.',
         product_types=['cosmetics', 'beauty', 'metal'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('key', 30, 8, 2.2, (0.3, 1.8), 20), _a('key', -30, 8, 2.2, (0.3, 1.8), 20),
             _a('fill', 0, 40, 2.8, (1.6, 1.2), 14), _a('rim', 160, 30, 2.2, (0.25, 1.6), 18, 6500)]))

# --- glass / liquid ---------------------------------------------------------------------------------
register('lighting', 'glass_backlit_warm', 'Glass Backlit Warm', 'glass', 'Warm panel behind, cool side strips: amber liquids glow, glass edges read.',
         product_types=['glass', 'food', 'cosmetics'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('back', 180, 6, 2.4, (2.6, 1.8), 15, 3600), _a('rim', 85, 10, 2.2, (0.3, 1.7), 11, 7000),
             _a('rim', -85, 10, 2.2, (0.3, 1.7), 11, 7000), _a('fill', 0, 5, 3.0, (2.0, 1.2), 1.8)]))

register('lighting', 'glass_dark_field', 'Glass Dark Field', 'glass', 'Side and top strips only, no back light: bright edges on black.',
         product_types=['glass', 'jewellery', 'cosmetics'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('rim', 75, 10, 2.2, (0.28, 1.8), 12, 6500), _a('rim', -75, 10, 2.2, (0.28, 1.8), 12, 6500),
             _a('top', 0, 72, 2.0, (0.3, 1.6), 9.1), _a('fill', 0, 5, 3.0, (1.5, 1.0), 1)]))

register('lighting', 'liquid_top_glow', 'Liquid Top Glow', 'glass', 'Top disk plus back panel and side strips: colour glows through liquids.',
         product_types=['glass', 'food', 'beauty'], style='soft',
         data=dict(world_strength=0, lights=[
             _a('top', 0, 82, 2.0, (1.6, 1.6), 26, 5600, 'DISK'), _a('back', 180, 10, 2.4, (2.2, 1.6), 29, 6000),
             _a('rim', 100, 15, 2.2, (0.3, 1.4), 15, 6500), _a('rim', -100, 15, 2.2, (0.3, 1.4), 15, 6500)]))

register('lighting', 'bottle_four_strips', 'Bottle Four Strips', 'glass', 'Four tall strips, two in front-side and two behind: classic bottle outline.',
         product_types=['glass', 'cosmetics', 'metal', 'beauty'], style='hard',
         data=dict(world_strength=0.0, lights=[
             _a('key', 35, 8, 2.2, (0.2, 1.8), 25), _a('key', -35, 8, 2.2, (0.2, 1.8), 25),
             _a('rim', 145, 8, 2.2, (0.2, 1.8), 26, 6200), _a('rim', -145, 8, 2.2, (0.2, 1.8), 26, 6200)]))

register('lighting', 'glass_bright_field', 'Glass Bright Field', 'glass', 'Huge bright panel behind and weak side cards: glass shows as dark outlines.',
         product_types=['glass', 'packaging'], style='high-key',
         data=dict(world_strength=0.0075, lights=[
             _a('back', 180, 12, 2.6, (3.4, 2.2), 135), _a('fill', 70, 20, 2.6, (1.2, 1.6), 22),
             _a('fill', -70, 20, 2.6, (1.2, 1.6), 22), _a('top', 0, 80, 2.0, (1.4, 1.4), 18)]))

register('lighting', 'perfume_sparkle', 'Perfume Sparkle', 'glass', 'Warm back panel, side strip and three tiny sources for facet sparkle.',
         product_types=['glass', 'cosmetics', 'jewellery', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('back', 180, 10, 2.4, (2.2, 1.6), 17, 4500), _a('rim', -90, 10, 2.2, (0.25, 1.5), 13, 6500),
             _a('spec', -55, 25, 2.4, (0.18, 0.18), 8.2, 5600, 'SQUARE'), _a('spec', 50, 35, 2.4, (0.15, 0.15), 7.5, 5600, 'SQUARE'),
             _a('spec', 130, 50, 2.3, (0.15, 0.15), 4.5, 7000, 'SQUARE')]))

# --- jewellery / metal ------------------------------------------------------------------------------
register('lighting', 'jewel_sparkle_cluster', 'Jewel Sparkle Cluster', 'jewellery', 'Eight small sources around the stone for scintillation, soft front fill.',
         product_types=['jewellery', 'glass'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('spec', az, el, 2.2, (0.12, 0.12), 12, k, 'SQUARE') for az, el, k in (
                 (-60, 30, 5600), (-20, 55, 6500), (25, 40, 5600), (65, 25, 6500),
                 (110, 45, 5600), (-110, 40, 6500), (150, 30, 5600), (-150, 55, 6500))
         ] + [_a('fill', 0, 20, 3.0, (2.4, 1.6), 13)]))

register('lighting', 'jewel_dome_sparkle', 'Jewel Dome Sparkle', 'jewellery', 'Soft top dome for body colour plus five tiny ring sources for fire.',
         product_types=['jewellery', 'glass'], style='soft',
         data=dict(world_strength=0.0022, lights=[
             _a('top', 0, 85, 1.9, (2.4, 2.4), 29, 5600, 'DISK'), _a('fill', 0, 15, 2.8, (2.0, 1.2), 11)] + [
             _a('spec', az, 35, 2.3, (0.14, 0.14), 12, 6500, 'SQUARE') for az in (-90, -30, 30, 90, 180)]))

register('lighting', 'ring_top_spots', 'Ring Top Spots', 'jewellery', 'Three tight spots from above, a soft front fill and a back strip.',
         product_types=['jewellery', 'metal'], style='hard',
         data=dict(world_strength=0.0045, lights=[
             _s('spec', -40, 62, 2.3, 0.15, 85, 5600, 22), _s('spec', 40, 62, 2.3, 0.15, 85, 6500, 22),
             _s('spec', 180, 62, 2.3, 0.15, 85, 5600, 22), _a('fill', 0, 10, 3.0, (2.2, 1.4), 31),
             _a('rim', 120, 15, 2.2, (0.25, 1.4), 54, 6500)]))

register('lighting', 'metal_long_strips', 'Metal Long Strips', 'metal', 'Long thin strips front, top and back: continuous reflections on polished metal.',
         product_types=['metal', 'automotive', 'tech', 'jewellery'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('key', 45, 15, 2.4, (0.18, 2.2), 20), _a('key', -45, 15, 2.4, (0.18, 2.2), 20),
             _a('top', 0, 72, 2.2, (0.3, 2.0), 15), _a('rim', 135, 15, 2.4, (0.2, 2.0), 16, 6200),
             _a('rim', -135, 15, 2.4, (0.2, 2.0), 16, 6200)]))

register('lighting', 'metal_wide_gradient', 'Metal Wide Gradient', 'metal', 'One huge softbox and a weaker opposite one: smooth gradients on brushed metal.',
         product_types=['metal', 'tech', 'automotive'], style='soft',
         data=dict(world_strength=0.0022, lights=[
             _a('key', -60, 25, 2.6, (2.6, 2.2), 46), _a('fill', 70, 15, 2.6, (1.8, 2.0), 17, 6500),
             _a('top', 0, 75, 2.2, (0.5, 1.8), 15), _a('rim', 160, 20, 2.4, (0.2, 1.8), 18, 6500)]))

# --- packaging / label ------------------------------------------------------------------------------
register('lighting', 'packaging_flat_even', 'Packaging Flat Even', 'packaging', 'Two equal front softboxes plus top and low fill: even, readable labels.',
         product_types=['packaging', 'food', 'cosmetics'], style='soft',
         data=dict(world_strength=0.007, lights=[
             _a('key', 42, 22, 2.4, (1.6, 1.6), 30), _a('key', -42, 22, 2.4, (1.6, 1.6), 30),
             _a('top', 0, 70, 2.2, (1.8, 1.4), 18), _a('fill', 0, 5, 3.0, (2.2, 1.0), 7)]))

register('lighting', 'packaging_dome', 'Packaging Dome', 'packaging', 'Big overhead dome and wide soft fills: almost no glare on glossy print.',
         product_types=['packaging', 'food'], style='soft',
         data=dict(world_strength=0.012, lights=[
             _a('top', 0, 80, 2.0, (2.6, 2.6), 52, 5600, 'DISK'), _a('fill', 0, 15, 2.8, (2.4, 1.8), 21),
             _a('fill', 80, 20, 2.4, (1.2, 1.4), 12), _a('fill', -80, 20, 2.4, (1.2, 1.4), 12)]))

register('lighting', 'packaging_side_gradient', 'Packaging Side Gradient', 'packaging', 'Large side key with front fill: shows box volume without losing the label.',
         product_types=['packaging', 'tech', 'cosmetics'], style='soft',
         data=dict(world_strength=0.0082, lights=[
             _a('key', -55, 28, 2.4, (1.8, 1.6), 51), _a('fill', 30, 12, 2.8, (2.4, 1.8), 21),
             _a('rim', 150, 30, 2.4, (0.4, 1.4), 23, 6500), _a('top', 0, 75, 2.2, (1.2, 1.2), 15)]))

register('lighting', 'carton_edge_rims', 'Carton Edge Rims', 'packaging', 'Large flat front light and two thin back strips that draw the box edges.',
         product_types=['packaging', 'tech', 'beauty'], style='soft',
         data=dict(world_strength=0.0068, lights=[
             _a('key', 0, 25, 2.8, (2.4, 1.8), 44), _a('rim', 125, 15, 2.2, (0.25, 1.6), 34, 6500),
             _a('rim', -125, 15, 2.2, (0.25, 1.6), 34, 6500), _a('top', 0, 70, 2.2, (1.4, 1.0), 19)]))

# --- tech / devices ---------------------------------------------------------------------------------
register('lighting', 'tech_screen_gradient', 'Tech Screen Gradient', 'tech', 'One huge panel for a gradient reflection on black glass, cool rim and side strip.',
         product_types=['tech', 'glass'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('key', 25, 38, 2.4, (2.4, 1.8), 15, 6200), _a('rim', -150, 15, 2.2, (0.25, 1.6), 9.6, 7500),
             _a('rim', -70, 10, 2.2, (0.3, 1.5), 7.2, 6500), _a('fill', 0, 5, 3.0, (2.0, 1.2), 1.4)]))

register('lighting', 'tech_cool_rim', 'Tech Cool Rim', 'tech', 'Two blue-white rim strips, a small neutral key and a thin top strip.',
         product_types=['tech', 'metal', 'automotive'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('rim', 135, 18, 2.2, (0.3, 1.6), 15, 8000), _a('rim', -135, 18, 2.2, (0.3, 1.6), 15, 8000),
             _a('key', -20, 35, 2.6, (1.6, 1.2), 11, 5500), _a('fill', 0, 3, 3.0, (2.0, 0.8), 2.7),
             _a('top', 0, 70, 2.0, (0.3, 1.4), 7.7, 7000)]))

register('lighting', 'tech_edge_glint', 'Tech Edge Glint', 'tech', 'Grazing side strips, top and back strip: bright chamfers on aluminium.',
         product_types=['tech', 'metal', 'jewellery'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('rim', 88, 5, 2.2, (0.15, 1.8), 28), _a('rim', -88, 5, 2.2, (0.15, 1.8), 28),
             _a('top', 0, 75, 2.0, (0.25, 1.6), 18, 6000), _a('back', 180, 8, 2.4, (0.3, 1.8), 23),
             _a('fill', 0, 20, 3.0, (2.2, 1.4), 5.5)]))

register('lighting', 'tech_matte_black', 'Tech Matte Black', 'tech', 'Side contours, a back kicker and a large soft top for matte black devices.',
         product_types=['tech', 'automotive'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('rim', 105, 35, 2.2, (0.4, 1.6), 11, 6500), _a('rim', -105, 35, 2.2, (0.4, 1.6), 11, 6500),
             _a('back', 180, 20, 2.4, (0.5, 1.2), 8.6), _a('top', 0, 60, 2.6, (1.8, 1.2), 6.2),
             _a('fill', 0, 10, 3.0, (2.0, 1.2), 1.2)]))

register('lighting', 'tech_desk_neutral', 'Tech Desk Neutral', 'tech', 'Neutral key, soft fill, cool back light and top: everyday product look.',
         product_types=['tech', 'packaging', 'beauty'], style='classic',
         data=dict(world_strength=0.0046, lights=[
             _a('key', -35, 45, 2.4, (1.4, 1.2), 30, 5000), _a('fill', 40, 15, 2.8, (2.0, 1.6), 13),
             _a('back', 170, 30, 2.4, (1.0, 0.6), 20, 7000), _a('top', 0, 80, 2.0, (1.4, 1.4), 12)]))

# --- food -------------------------------------------------------------------------------------------
register('lighting', 'food_backlit_window', 'Food Backlit Window', 'food', 'Warm window from behind-side with a weak front fill: glossy, appetising edges.',
         product_types=['food', 'glass'], style='soft',
         data=dict(world_strength=0.0084, lights=[
             _a('back', 150, 38, 2.4, (2.0, 1.6), 75, 4800), _a('fill', 0, 20, 2.8, (2.2, 1.6), 21, 5200),
             _a('fill', -70, 15, 2.4, (1.2, 1.4), 16, 5200)]))

register('lighting', 'food_top_down', 'Food Top Down', 'food', 'Big overhead disk, two side fills and a small spec for flat-lay shots.',
         product_types=['food', 'packaging'], style='soft',
         data=dict(world_strength=0.0089, lights=[
             _a('top', 0, 85, 2.0, (2.4, 2.4), 53, 5200, 'DISK'), _a('fill', 80, 15, 2.4, (1.4, 1.4), 14, 5000),
             _a('fill', -80, 15, 2.4, (1.4, 1.4), 14, 5000), _a('spec', -30, 40, 2.5, (0.3, 0.3), 11, 5600, 'SQUARE')]))

register('lighting', 'food_warm_side', 'Food Warm Side', 'food', 'Low warm side key, white reflector opposite and a soft back rim.',
         product_types=['food', 'packaging'], style='soft',
         data=dict(world_strength=0.0054, lights=[
             _a('key', -80, 25, 2.4, (1.4, 1.4), 54, 3800), _a('fill', 70, 10, 2.6, (1.8, 1.8), 18, 4500),
             _a('rim', 160, 40, 2.4, (0.6, 1.0), 25, 4200), _a('top', 0, 75, 2.0, (1.2, 1.2), 11, 5000, 'DISK')]))

# --- automotive / large products --------------------------------------------------------------------
register('lighting', 'auto_overhead_stripes', 'Auto Overhead Stripes', 'automotive', 'Long overhead and side stripes plus back rims: the car-reveal reflection pattern.',
         product_types=['automotive', 'metal', 'tech'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('top', 0, 80, 2.4, (0.5, 3.2), 32), _a('key', 80, 25, 2.8, (0.3, 3.0), 29),
             _a('key', -80, 25, 2.8, (0.3, 3.0), 29), _a('rim', 150, 12, 2.6, (0.25, 2.8), 21, 6200),
             _a('rim', -150, 12, 2.6, (0.25, 2.8), 21, 6200)]))

register('lighting', 'auto_showroom', 'Auto Showroom', 'automotive', 'Huge overhead softbox, big side panel, weaker fill and two back strips.',
         product_types=['automotive', 'tech', 'metal'], style='soft',
         data=dict(world_strength=0.0042, lights=[
             _a('top', 0, 75, 2.6, (3.0, 2.4), 42), _a('key', -70, 25, 3.0, (2.0, 2.0), 34),
             _a('fill', 60, 10, 3.2, (2.4, 1.6), 16, 6000), _a('rim', 155, 15, 2.8, (0.3, 2.4), 22, 6500),
             _a('rim', -155, 15, 2.8, (0.3, 2.4), 22, 6500)]))

register('lighting', 'auto_low_rake', 'Auto Low Rake', 'automotive', 'Very low long strips, thin top bar and back panel: sculpts flanks and shoulders.',
         product_types=['automotive', 'tech', 'metal'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('key', 60, 4, 3.0, (0.3, 3.0), 18), _a('key', -60, 4, 3.0, (0.3, 3.0), 18),
             _a('top', 0, 70, 2.6, (2.6, 0.6), 15), _a('back', 180, 6, 2.8, (2.4, 0.8), 13, 6200)]))

# --- dark luxury ------------------------------------------------------------------------------------
register('lighting', 'luxury_gold_contour', 'Luxury Gold Contour', 'luxury', 'Warm gold contour strips, a tight warm top spot and a cold back kicker.',
         product_types=['jewellery', 'cosmetics', 'metal', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('rim', 120, 12, 2.2, (0.25, 1.6), 21, 2700), _a('rim', -120, 12, 2.2, (0.25, 1.6), 21, 3400),
             _s('top', 0, 70, 2.4, 0.3, 15, 3200, 26, 0.6), _a('back', 180, 5, 2.4, (0.2, 1.2), 8.7, 8000),
             _a('fill', -30, 10, 2.6, (2.0, 1.4), 1.6, 4500)]))

register('lighting', 'luxury_single_snoot', 'Luxury Single Snoot', 'luxury', 'One snooted warm spot from the front-side and a thin cool rim: pure drama.',
         product_types=['jewellery', 'cosmetics', 'glass', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _s('key', -25, 55, 2.4, 0.2, 84, 4200, 18, 0.7), _a('rim', 160, 15, 2.2, (0.2, 1.5), 48, 6500),
             _a('fill', 0, 10, 3.0, (2.0, 1.2), 4.5)]))

register('lighting', 'luxury_black_mirror', 'Luxury Black Mirror', 'luxury', 'Thin long strips at the sides, top and back: gloss black reads as pure lines.',
         product_types=['automotive', 'tech', 'beauty', 'metal'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('key', 60, 5, 2.4, (0.14, 2.0), 12, 6000), _a('key', -60, 5, 2.4, (0.14, 2.0), 12, 6000),
             _a('top', 0, 78, 2.2, (0.2, 1.8), 9.7, 6000), _a('rim', 150, 10, 2.4, (0.14, 2.0), 11, 6000),
             _a('rim', -150, 10, 2.4, (0.14, 2.0), 11, 6000)]))

# --- high-key / low-key -----------------------------------------------------------------------------
register('lighting', 'highkey_white_cyc', 'High-Key White Cyc', 'highkey', 'Wide soft light from every side over a bright world: white, shadowless, airy.',
         product_types=['beauty', 'packaging', 'cosmetics', 'food', 'tech'], style='high-key',
         data=dict(world_strength=0.012, world_color=(0.9, 0.9, 0.9), lights=[
             _a('key', -55, 25, 2.6, (2.2, 2.0), 29), _a('key', 55, 25, 2.6, (2.2, 2.0), 29),
             _a('top', 0, 75, 2.4, (2.4, 2.0), 24), _a('fill', 0, 12, 3.0, (2.4, 1.6), 18),
             _a('back', 160, 25, 2.4, (1.2, 1.8), 20), _a('back', -160, 25, 2.4, (1.2, 1.8), 20)]))

register('lighting', 'highkey_ecom_spec', 'High-Key E-commerce', 'highkey', 'Big top light, small spec light and back lights for a clean white background.',
         product_types=['packaging', 'tech', 'beauty', 'cosmetics', 'food'], style='high-key',
         data=dict(world_strength=0.012, world_color=(0.9, 0.9, 0.9), lights=[
             _a('top', 0, 70, 2.0, (2.4, 2.0), 30), _a('spec', -40, 30, 2.6, (0.25, 0.25), 11, 5600, 'SQUARE'),
             _a('fill', 0, 15, 3.0, (2.4, 1.6), 20), _a('back', 170, 30, 2.4, (1.8, 1.4), 25)]))

register('lighting', 'lowkey_softbox_slit', 'Low-Key Slit', 'lowkey', 'One narrow soft slit from the side, a thin back rim, almost no fill.',
         product_types=['beauty', 'cosmetics', 'tech', 'glass', 'food'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('key', -80, 20, 2.2, (0.4, 1.8), 24, 5000), _a('rim', 150, 20, 2.2, (0.25, 1.6), 12, 6500),
             _a('fill', 30, 5, 3.0, (2.0, 1.2), 0.98)]))

register('lighting', 'lowkey_moody_fill', 'Low-Key Moody', 'lowkey', 'Small warm key, cold dim fill and a cold back rim: moody and cinematic.',
         product_types=['beauty', 'tech', 'food', 'metal', 'automotive'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('key', -50, 35, 2.4, (0.8, 0.8), 18, 4500), _a('fill', 50, 8, 3.0, (2.4, 1.6), 1.6, 6500),
             _a('rim', 165, 25, 2.4, (0.4, 1.2), 12, 6500)]))

# --- colored / neon / gels --------------------------------------------------------------------------
register('lighting', 'neon_duotone', 'Neon Duotone', 'color', 'Pink strip on one side, cyan on the other, a touch of white fill.',
         product_types=['tech', 'beauty', 'glass', 'metal', 'automotive'], style='neon',
         data=dict(world_strength=0.0, lights=[
             _a('rim', -110, 15, 2.2, (0.4, 1.8), 150, rgb=(1.0, 0.15, 0.55)),
             _a('rim', 110, 15, 2.2, (0.4, 1.8), 150, rgb=(0.1, 0.7, 1.0)), _a('fill', 0, 20, 3.0, (2.0, 1.2), 14)]))

register('lighting', 'gel_teal_orange', 'Gel Teal-Orange', 'color', 'Warm orange key against a teal back and fill: cinematic complementary colours.',
         product_types=['tech', 'beauty', 'automotive', 'food', 'metal'], style='neon',
         data=dict(world_strength=0.0023, lights=[
             _a('key', -45, 30, 2.3, (1.2, 1.2), 70, 2800),
             _a('back', 140, 20, 2.4, (0.6, 1.6), 60, rgb=(0.1, 0.65, 0.7)),
             _a('fill', 60, 10, 2.8, (1.8, 1.4), 17, rgb=(0.15, 0.6, 0.65))]))

register('lighting', 'neon_magenta_rim', 'Neon Magenta Rim', 'color', 'Magenta rim strips, a blue top spot and a small warm key.',
         product_types=['tech', 'glass', 'beauty', 'automotive', 'metal'], style='neon',
         data=dict(world_strength=0.0, lights=[
             _a('rim', 140, 15, 2.2, (0.3, 1.7), 78, rgb=(0.9, 0.1, 0.9)),
             _a('rim', -140, 15, 2.2, (0.3, 1.7), 78, rgb=(0.9, 0.1, 0.9)),
             _s('top', 0, 70, 2.4, 0.3, 63, rgb=(0.1, 0.3, 1.0), cone=30),
             _a('key', -30, 25, 2.6, (0.4, 0.4), 38, 3500)]))

# --- halo / back-glow, silhouette, dramatic ---------------------------------------------------------
register('lighting', 'halo_back_disk', 'Halo Back Disk', 'halo', 'A big disk behind the product makes a halo; small front key keeps detail.',
         product_types=['tech', 'beauty', 'glass', 'metal', 'automotive'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('back', 180, 10, 2.0, (1.8, 1.8), 22, 6000, 'DISK'), _a('key', -30, 30, 2.6, (1.0, 1.0), 11),
             _a('fill', 20, 10, 3.0, (2.0, 1.2), 1.9)]))

register('lighting', 'halo_arc_glow', 'Halo Arc Glow', 'halo', 'Five tall strips in an arc behind the product: a soft wrap of rim light.',
         product_types=['glass', 'tech', 'cosmetics', 'automotive', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('rim', az, el, 2.2, (0.4, 1.2), 9.2, 6500) for az, el in ((140, 12), (160, 16), (180, 20), (-160, 16), (-140, 12))
         ] + [_a('key', -20, 30, 2.6, (1.4, 1.2), 7)]))

register('lighting', 'silhouette_bright_back', 'Silhouette Bright Back', 'silhouette',
         'Bright backdrop, dark product: wall and top panels light only the backdrop and floor (light linking), two thin rim strips, nothing '
         'in front. Use cyclorama_studio_grey: pure_white glows by itself and bounces ~0.2 onto the product. Glass and metal still show the backdrop.',
         product_types=['glass', 'tech', 'automotive', 'beauty'], style='high-key',
         data=dict(world_strength=0.0, lights=[
             dict(_a('back', -125, 20, 3.5, (3.0, 2.0), 900, 6000), aim=(180, 10, 6.5), only='backdrop'),
             dict(_a('back', 125, 20, 3.5, (3.0, 2.0), 900, 6000), aim=(180, 10, 6.5), only='backdrop'),
             dict(_a('top', 0, 70, 4.0, (10.0, 10.0), 600, 6000), only='backdrop'),
             _a('rim', 150, 15, 2.2, (0.25, 1.6), 10, 6500), _a('rim', -150, 15, 2.2, (0.25, 1.6), 10, 6500)]))

register('lighting', 'dramatic_top_spot', 'Dramatic Top Spot', 'dramatic', 'One hard spot from straight above, low back rims, a hint of fill.',
         product_types=['jewellery', 'beauty', 'tech', 'glass', 'metal'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _s('top', 0, 80, 2.6, 0.25, 60, 4800, 25, 0.5), _a('rim', 130, 8, 2.2, (0.3, 1.4), 26, 6500),
             _a('rim', -130, 8, 2.2, (0.3, 1.4), 26, 6500), _a('fill', 0, 10, 3.0, (2.0, 1.2), 2.6)]))

# --- dispersion (glass / crystal, Cycles) ---------------------------------------------------------------
_DISP = ("Render in Cycles; the glass needs dispersion (Principled/Glass Dispersion > 0 where Blender has it; Blender 5.1 has none: "
         "mix three Glass BSDF with IOR 1.50/1.52/1.54 filtered red/green/blue).")
register('lighting', 'dispersion_crystal_points', 'Dispersion Crystal Points', 'glass',
         'Four tiny hard sources around the glass and a dim soft fill: every facet and edge splits into rainbow fringes. ' + _DISP,
         product_types=['glass', 'jewellery'], style='hard', needs_cycles=True,
         data=dict(world_strength=0.0, lights=[
             _a('spec', az, el, 2.6, (0.05, 0.05), 11, 6500, 'SQUARE') for az, el in ((-62, 32), (58, 38), (150, 42), (-140, 28))] + [
             _a('fill', 0, 12, 3.0, (2.2, 1.4), 1.6, 5600)]))

register('lighting', 'dispersion_backlit_prism', 'Dispersion Backlit Prism', 'glass',
         'A tiny hard source behind and two at the sides: light crosses the glass and spreads into a spectrum at its edges. ' + _DISP,
         product_types=['glass', 'jewellery'], style='dark', needs_cycles=True,
         data=dict(world_strength=0.0, lights=[
             _a('back', 180, 6, 2.6, (0.06, 0.06), 28, 6500, 'SQUARE'), _a('back', 155, 38, 2.5, (0.05, 0.05), 14, 6500, 'SQUARE'),
             _a('spec', -80, 14, 2.4, (0.05, 0.05), 9, 6500, 'SQUARE'), _a('spec', 80, 14, 2.4, (0.05, 0.05), 9, 6500, 'SQUARE'),
             _a('fill', 0, 10, 3.0, (2.0, 1.2), 1.4, 5600)]))


# --- dedicated to recipes (presets/recipe.py) ---------------------------------------------------------------------------
register('lighting', 'noir_edge_key', 'Noir Edge Key', 'luxury',
         'Moody but readable: thin side and back strips draw the contours, one soft key from the front-left shapes the volumes.',
         product_types=['beauty', 'tech', 'glass'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('key', -42, 28, 2.6, (1.2, 1.4), 36, 5000), _a('fill', 40, 8, 3.0, (2.0, 1.0), 3, 5600),
             _a('rim', 90, 6, 2.6, (0.14, 2.0), 12, 6000), _a('rim', -90, 6, 2.6, (0.14, 2.0), 12, 6000),
             _a('top', 0, 78, 2.2, (0.2, 1.8), 15.6, 6000),
             _a('rim', 150, 20, 2.4, (0.14, 2.0), 17, 6000), _a('rim', -150, 20, 2.4, (0.14, 2.0), 17, 6000)]))


register('lighting', 'tech_launch_rim', 'Tech Launch Rim', 'tech',
         'Two wide blue-white rim panels (a soft vertical gradient on glass and metal, no blown streak), a small key and a thin top strip.',
         product_types=['tech', 'glass', 'metal'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('rim', 135, 18, 2.2, (1.2, 1.6), 10.8, 8000), _a('rim', -135, 18, 2.2, (1.2, 1.6), 10.8, 8000),
             _a('key', -20, 35, 2.6, (1.6, 1.2), 12.6, 5500), _a('fill', 0, 3, 3.0, (2.0, 0.8), 4),
             _a('top', 0, 70, 2.0, (0.3, 1.4), 10.8, 7000)]))


register('lighting', 'ecom_soft_shadow', 'E-commerce Soft Shadow', 'highkey',
         'Big soft top light, weaker fill and back lights: a clean white scene that still gives a soft contact shadow and readable glass edges.',
         product_types=['packaging', 'tech', 'beauty', 'cosmetics', 'glass'], style='high-key',
         data=dict(world_strength=0.012, world_color=(0.9, 0.9, 0.9), lights=[
             _a('top', 0, 70, 2.0, (2.4, 2.0), 34.5), _a('spec', -40, 30, 2.6, (0.25, 0.25), 11, 5600, 'SQUARE'),
             _a('fill', 0, 15, 3.0, (2.4, 1.6), 14), _a('back', 170, 30, 2.4, (1.8, 1.4), 20)]))


register('lighting', 'jewel_dome_soft', 'Jewel Dome Soft', 'jewellery',
         'Wide soft top dome, two broad rim strips for the edges of glass and metal, and five tiny sources (low ones for glints on the sides, high ones for fire): sparkle without burnt caps.',
         product_types=['jewellery', 'glass', 'metal'], style='soft',
         data=dict(world_strength=0.0022, lights=[
             _a('top', 0, 85, 1.9, (3.2, 3.2), 9, 5600, 'DISK'), _a('fill', 0, 15, 2.8, (2.0, 1.2), 8.8),
             _a('rim', 130, 25, 2.4, (0.3, 2.0), 12, 6000), _a('rim', -130, 25, 2.4, (0.3, 2.0), 12, 6000),
             _a('spec', -90, 65, 2.3, (0.05, 0.05), 7.8, 6500, 'SQUARE'), _a('spec', -30, 14, 2.3, (0.05, 0.05), 19, 6500, 'SQUARE'),
             _a('spec', 30, 65, 2.3, (0.05, 0.05), 7.8, 6500, 'SQUARE'), _a('spec', 90, 14, 2.3, (0.05, 0.05), 19, 6500, 'SQUARE'),
             _a('spec', 180, 65, 2.3, (0.05, 0.05), 7.8, 6500, 'SQUARE')]))

register('lighting', 'beauty_clamshell_soft', 'Beauty Clamshell Soft', 'beauty',
         'Clamshell with a wider top softbox, a larger low reflector and two broad high rims: no hot reflection on a glossy floor.',
         product_types=['beauty', 'cosmetics', 'packaging'], style='soft',
         data=dict(world_strength=0.0037, lights=[
             _a('key', 0, 55, 2.2, (1.6, 1.0), 29), _a('fill', 0, 4, 2.4, (2.6, 0.9), 6.4),
             _a('rim', 135, 35, 2.4, (1.0, 1.5), 20, 6500), _a('rim', -135, 35, 2.4, (1.0, 1.5), 20, 6500)]))


register('lighting', 'auto_overhead_soft', 'Auto Overhead Soft', 'automotive',
         'The overhead-stripes rig with wider, weaker side and back strips: the same long reflections without blown streaks.',
         product_types=['automotive', 'metal', 'tech'], style='hard',
         data=dict(world_strength=0, lights=[
             _a('top', 0, 80, 2.4, (0.5, 3.2), 25.6), _a('key', 80, 25, 2.8, (0.5, 3.0), 20.3),
             _a('key', -80, 25, 2.8, (0.5, 3.0), 20.3), _a('rim', 150, 12, 2.6, (0.45, 2.8), 14.7, 6200),
             _a('rim', -150, 12, 2.6, (0.45, 2.8), 14.7, 6200)]))


register('lighting', 'perfume_glow_key', 'Perfume Glow Key', 'glass',
         'A big warm ellipse behind the bottle (a glow reflected in a glossy black sweep), a soft warm key, a side strip and three tiny sources for facet sparkle.',
         product_types=['glass', 'cosmetics', 'beauty'], style='dark',
         data=dict(world_strength=0.0, lights=[
             _a('back', 180, 14, 2.4, (6.8, 4.1), 118, 4500, 'ELLIPSE'), _a('rim', -90, 10, 2.2, (0.25, 1.5), 16.9, 6500),
             _a('key', -50, 28, 2.6, (1.2, 1.4), 12, 4200), _a('fill', 40, 6, 3.0, (2.0, 0.9), 1.5, 4500),
             _a('spec', -55, 25, 2.4, (0.18, 0.18), 12.3, 5600, 'SQUARE'), _a('spec', 50, 35, 2.4, (0.15, 0.15), 11.25, 5600, 'SQUARE'),
             _a('spec', 130, 50, 2.3, (0.15, 0.15), 6.75, 7000, 'SQUARE')]))


register('lighting', 'tech_screen_gradient_lift', 'Tech Screen Gradient Lift', 'tech',
         'The big gradient panel with stronger key and cool rims: glass and metal read clearly against a dark graphite sweep.',
         product_types=['tech', 'glass', 'metal'], style='dark',
         data=dict(world_strength=0, lights=[
             _a('key', 25, 38, 2.4, (2.4, 1.8), 24, 6200), _a('rim', -150, 15, 2.2, (0.25, 1.6), 13.44, 7500),
             _a('rim', -70, 10, 2.2, (0.3, 1.5), 10.08, 6500), _a('fill', 0, 5, 3.0, (2.0, 1.2), 1.96)]))


register('lighting', 'matte_cream_sun_deep', 'Matte Cream Sun Deep', 'beauty',
         'The soft sun with a stronger key and a weaker fill: longer, clearer shadows and more volume on matte objects.',
         product_types=['cosmetics', 'packaging', 'beauty'], style='hard',
         data=dict(world_strength=0.021, lights=[
             dict(role='key', type='SUN', az=-40, el=45, dist_f=3.0, power_ref=0.95, kelvin=5400, angle=4.0),
             _a('fill', 50, 15, 2.8, (2.4, 1.8), 23.1), _a('rim', 160, 30, 2.4, (0.5, 1.2), 36.4, 6500)]))


register('lighting', 'food_warm_side_deep', 'Food Warm Side Deep', 'food',
         'Low warm side key (stronger), white reflector opposite and a brighter back rim: the food lights up against a darker table.',
         product_types=['food', 'packaging'], style='soft',
         data=dict(world_strength=0.0054, lights=[
             _a('key', -80, 25, 2.4, (1.4, 1.4), 86.4, 3800), _a('fill', 70, 10, 2.6, (1.8, 1.8), 18, 4500),
             _a('rim', 160, 40, 2.4, (0.6, 1.0), 35, 4200), _a('top', 0, 75, 2.0, (1.2, 1.2), 11, 5000, 'DISK')]))


# CYCLES COMPENSATION: Cycles has the studio's bounces and Eevee has not, so build_compositing.CYCLES_EV takes half a stop off every
# Cycles render; these are the presets that need more or less than that (stops, + = brighter), measured with the test scene against
# Eevee (STATO.md, "Cycles"). They add up with the ones of the other sections.  Re-measure after changing the lights.
CYCLES_EV = {
    'beauty_soft': -0.15,
    'rim_only': +0.20,
    'glass_edges': -0.15,
    'matte_cream_sun': +0.25,
    'matte_cream_sun_deep': +0.25,
    'glass_dark_field': -0.55,
    'perfume_sparkle': -0.45,
    'perfume_glow_key': 0.05,
    'jewel_sparkle_cluster': -0.35,
    'jewel_dome_sparkle': -0.15,
    'ring_top_spots': +0.20,
    'tech_screen_gradient': -0.35,
    'tech_screen_gradient_lift': -0.35,
    'tech_desk_neutral': -0.10,
    'tech_cool_rim': -0.55,
    'tech_matte_black': -0.70,
    'food_backlit_window': +0.20,
    'auto_low_rake': -0.35,
    'luxury_black_mirror': -0.50,
    'neon_duotone': +0.20,
    'neon_magenta_rim': +0.20,
    'halo_back_disk': -0.25,
    'halo_arc_glow': -0.70,
    'silhouette_bright_back': -0.25,
    'dispersion_crystal_points': -0.85,
    'dispersion_backlit_prism': -0.30,
}
for _id, _ev in CYCLES_EV.items():
    REGISTRY['lighting'][_id].data['cycles_ev'] = _ev
