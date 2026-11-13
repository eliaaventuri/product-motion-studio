"""RECIPE presets: a complete style (every section) for a professional use case, applied in one go by api.apply_recipe.

SCHEMA   register('recipe', id, name, category, desc, data=dict(
             product_motion=id, camera_shot=id, camera_motion=id, lighting=id, background=id, background_light=id,
             floor=id, look=id, format=id, duration=frames))        every id is an existing preset of that section
RULES    - A recipe only names presets (no numbers of its own): to tune it, change the preset or use the live controls.
         - duration is the recommended length in frames at the scene's fps (24 fps: 240 = 10 s).
         - Loops pair a looping product motion with a static camera (the result loops).
         - tests/test_live.py checks that every id exists.
OPTIONAL cycles_ev=stops (+ brighter) as a keyword of _r (kept in the preset's meta, not in data): extra Cycles exposure compensation of the whole recipe, added to the
         ones of its lighting/background/background light/floor presets (see build_compositing.recipe_ev).
"""

from . import register


def _r(id, name, category, desc, product_motion, camera_shot, camera_motion, lighting, background, background_light, floor,
       look, format, duration, **meta):
    register('recipe', id, name, category, desc, data=dict(
        product_motion=product_motion, camera_shot=camera_shot, camera_motion=camera_motion, lighting=lighting,
        background=background, background_light=background_light, floor=floor, look=look, format=format, duration=duration),
        **meta)


_r('luxury_perfume', 'Luxury Perfume', 'luxury', 'Black glossy sweep with a warm glow behind the glass, glints on the edges, a slow drift and a gentle push-in: fragrance and spirits.',
   'luxury_drift', 'hero_34', 'push_in_slow', 'perfume_glow_key', 'cyclorama_gloss_black', 'rim_glow', 'glossy', 'luxury_gold',
   '16:9', 240, product_types=['glass', 'cosmetics'], cycles_ev=0.25)
_r('skincare_pastel', 'Skincare Pastel', 'beauty', 'Powder-pink floor rising to a dusty rose wall, soft key and a warm glow behind, a product that blooms in and a slow push: clean skincare and wellness.',
   'soft_scale_reveal', 'front', 'push_in_slow', 'three_point_classic', 'cyclorama_dusty_rose', 'rim_glow', 'matte', 'pastel_depth',
   '4:5', 180, product_types=['cosmetics', 'beauty'], cycles_ev=-0.5)
_r('tech_launch_dark', 'Tech Launch Dark', 'tech', 'Dark room, cool rim light and a pool of light behind: the product rises and the camera circles it.',
   'rise_from_below', 'low_angle', 'orbit_45_right', 'tech_launch_rim', 'cyclorama_radial_spotlight', 'top_gradient', 'dark_glossy', 'cool_tech',
   '16:9', 200, product_types=['tech'], cycles_ev=-0.4)
_r('smartphone_hero', 'Smartphone Hero', 'tech', 'Graphite sweep, a big gradient reflection on the glass and a tilt into the hero pose with an arcing push-in.',
   'tilt_to_hero', 'hero_34', 'arc_push', 'tech_screen_gradient_lift', 'cyclorama_noir_graphite', 'spot_pool', 'glossy', 'metallic_punch',
   '16:9', 216, product_types=['tech'], cycles_ev=0.2)
_r('sneaker_drop', 'Sneaker Drop', 'lifestyle', 'Teal and orange sweep, low camera, the product drops in with a bounce and the camera pushes fast: streetwear drops.',
   'drop_bounce', 'low_angle', 'push_in_fast', 'three_point_classic', 'cyclorama_duotone_teal_orange', 'spot_pool', 'matte',
   'high_contrast_punchy', '4:5', 150, product_types=['packaging', 'tech'], cycles_ev=0.12)
_r('watch_jewellery_sparkle', 'Watch and Jewellery Sparkle', 'luxury', 'Black mirror floor, tiny sources for fire and glints, a smooth turn: watches, rings, gems.',
   'spin_360_eased_loop', 'hero_34', 'static', 'jewel_dome_soft', 'cyclorama_gloss_black', 'rim_glow', 'mirror', 'jewel_sparkle',
   '1:1', 240, product_types=['jewellery', 'metal'], cycles_ev=-0.3)
_r('beverage_can_cool', 'Beverage Can Cool', 'lifestyle', 'Cold blue sweep, long strip reflections on the metal and a floating spin: cans, bottles, energy drinks.',
   'levitate_spin_loop', 'front', 'static', 'metal_long_strips', 'cyclorama_gradient_blue', 'top_gradient', 'glossy', 'clean_commercial',
   '1:1', 240, product_types=['metal', 'glass', 'packaging'])
_r('food_warm', 'Food Warm', 'lifestyle', 'Warm clay-brown paper, low side light that lifts the food off the table and a slide-in: appetising food and drink.',
   'slide_in', 'high_34', 'pull_back_reveal', 'food_warm_side_deep', 'cyclorama_warm_clay', 'spot_pool', 'matte', 'film_warm_lift',
   '4:5', 200, product_types=['food', 'packaging'], cycles_ev=-0.1)
_r('packaging_ecommerce_white', 'Packaging E-commerce White', 'catalogue', 'White sweep, big soft top light and neutral colour: a clean looping turn with a soft contact shadow for shop pages.',
   'spin_360_eased_loop', 'hero_34', 'static', 'ecom_soft_shadow', 'cyclorama_ecom_white', 'none', 'seamless', 'ecommerce_neutral',
   '1:1', 180, product_types=['packaging', 'cosmetics', 'tech'])
_r('automotive_part_metal', 'Automotive Part Metal', 'automotive', 'Graphite sweep, long overhead stripes and a mirror floor: the part slides in while the camera trucks along.',
   'slide_in_right', 'low_angle', 'truck_right', 'auto_overhead_soft', 'cyclorama_graphite', 'side_sweep', 'mirror', 'metallic_punch',
   '16:9', 220, product_types=['automotive', 'metal'])
_r('headphones_studio', 'Headphones Studio', 'tech', 'Cool grey-blue studio, soft key and a cool back light: a tilt into the hero pose and a slow orbit.',
   'tilt_to_hero', 'hero_34', 'orbit_45_left', 'tech_desk_neutral', 'cyclorama_graphite', 'none', 'glossy', 'cool_tech',
   '16:9', 200, product_types=['tech'])
_r('cosmetics_pop_color', 'Cosmetics Pop Color', 'beauty', 'Mint sweep, clamshell light and saturated colour: a bouncing loop for lipsticks, jars and tubes.',
   'bounce_loop', 'front', 'static', 'beauty_clamshell_soft', 'cyclorama_pastel_mint', 'top_gradient', 'satin', 'vivid_pop',
   '1:1', 120, product_types=['cosmetics', 'beauty'])
_r('minimal_scandinavian', 'Minimal Scandinavian', 'lifestyle', 'Cream paper, soft sun from a window, matte colour and a barely-there drift: calm home and design objects.',
   'drift_yaw_slow', 'hero_34', 'push_in_slow', 'matte_cream_sun_deep', 'cyclorama_warm_cream', 'spot_pool', 'matte', 'matte_soft_contrast',
   '4:5', 240, product_types=['packaging', 'cosmetics'])
_r('editorial_noir', 'Editorial Noir', 'luxury', 'Black and white, thin strips of light that draw the edges, a soft key for the volumes and a crane up in cinemascope: moody editorial.',
   'drift_yaw_slow', 'low_angle', 'crane_up', 'noir_edge_key', 'cyclorama_noir_graphite', 'spot_pool', 'matte', 'noir_editorial',
   '2.39:1', 240, product_types=['beauty', 'tech', 'glass'])
_r('social_9x16_punchy', 'Social 9:16 Punchy', 'social', 'Vertical, a rich cobalt glow and punchy colour: the product pops in and the camera pushes fast.',
   'pop_in_reveal', 'hero_34', 'push_in_fast', 'beauty_soft', 'cyclorama_radial_cobalt', 'rim_glow', 'glossy', 'punchy_agx',
   '9:16', 120, product_types=['beauty', 'tech', 'packaging'])
_r('turntable_catalogue', 'Turntable Catalogue', 'catalogue', 'Neutral graphite-grey sweep, even light, a seamless looping 360 turn from a slightly high angle: the standard product turntable.',
   'spin_360_loop', 'high_34', 'static', 'packaging_flat_even', 'cyclorama_graphite', 'none', 'seamless', 'neutral_delivery',
   '16:9', 240, product_types=['packaging', 'tech', 'cosmetics', 'food'])
