"""LOOK presets (colour management + compositor): DATA dicts.

SCHEMA   register('look', id, name, category, desc, data=dict(
             view_transform='AgX' | 'Khronos PBR Neutral' | 'Standard' ..., look='AgX - Punchy' | 'None' ...
                 (name or fragment: the builder falls back to 'None' if it does not exist), exposure=stops, gamma=1.0,
             glare=None | dict(type='Fog Glow'|'Bloom'|'Streaks'|'Ghosts'|'Simple Star', threshold, strength, size 0..1, quality),
             vignette=None | dict(darken=stops darker at the corners, size=0..1 clear area, feather=0..1),
             lens=None | dict(dispersion=0..0.1, distortion=-0.1..0.1),
             grade=None | dict(saturation=1.0, contrast=0.0, gain=(r, g, b), lift=(r, g, b)),
             grain=None | strength 0..1))
RULES    - Tasteful: glare thresholds are scene-linear and the calibrated lighting puts the median at ~0.15 and only specular
           highlights above 1: use 0.4-1.2 for a subtle glow on highlights, 0.15-0.25 for a real bloom; vignette darken <= 1 stop, dispersion <= 0.03, grain <= 0.3.
         - Order in the node tree is fixed: glare, lens, grade, vignette, grain.
"""

from . import register


def _fog(thr, strength, size=0.4):
    return dict(type='Fog Glow', threshold=thr, strength=strength, size=size, quality='Medium')


def _bloom(thr, strength, size=0.5):
    return dict(type='Bloom', threshold=thr, strength=strength, size=size, quality='Medium')


def _vig(darken, size=0.85, feather=0.6):
    return dict(darken=darken, size=size, feather=feather)


def _grade(sat=1.0, contrast=0.0, gain=(1.0, 1.0, 1.0), lift=(0.0, 0.0, 0.0)):
    return dict(saturation=sat, contrast=contrast, gain=gain, lift=lift)


register('look', 'clean_commercial', 'Clean Commercial', 'commercial', 'Bright neutral AgX, about two thirds of a stop lighter than the base, tiny glow: faithful colour for e-commerce and spots.',
         data=dict(view_transform='AgX', look='None', exposure=0.7, gamma=1.0,
                   glare=_fog(0.8, 0.1, 0.3), vignette=_vig(0.2, 0.95, 0.5), lens=None,
                   grade=None, grain=None))

register('look', 'beauty_soft', 'Beauty Soft', 'beauty', 'Low contrast, peachy warm tint, soft bloom and lifted shadows: skin-care and cosmetics.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=0.4, gamma=1.0,
                   glare=_fog(0.4, 0.3, 0.45), vignette=_vig(0.3, 0.9, 0.6), lens=None,
                   grade=_grade(1.05, 0.0, (1.14, 1.0, 0.9), (0.012, 0.004, 0.0)), grain=None))

register('look', 'dark_editorial', 'Dark Editorial', 'editorial', 'Low-key: high contrast, minus 0.7 stop, desaturated, cold-black corners and a touch of grain.',
         data=dict(view_transform='AgX', look='AgX - High Contrast', exposure=-0.7, gamma=1.0,
                   glare=_fog(0.6, 0.2, 0.4), vignette=_vig(0.9, 0.7, 0.7), lens=None,
                   grade=_grade(0.8, 0.05, (0.88, 1.0, 1.14), (0.0, 0.0, 0.02)), grain=0.15))

register('look', 'metallic_punch', 'Metallic Punch', 'metal', 'Very high contrast with a steel-cold tint, small streaks on the highlights: brushed and polished metals.',
         data=dict(view_transform='AgX', look='AgX - Very High Contrast', exposure=0.15, gamma=1.0,
                   glare=dict(type='Streaks', threshold=1.2, strength=0.25, size=0.3, quality='Medium'), vignette=_vig(0.4, 0.85, 0.6), lens=None,
                   grade=_grade(0.85, 0.0, (0.88, 1.0, 1.12)), grain=None))

register('look', 'glow', 'Glow', 'stylised', 'Low-contrast, bright and saturated with a big soft bloom on everything bright, cool-white cast and slight lens dispersion.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=0.8, gamma=1.0,
                   glare=_bloom(0.1, 0.8, 0.7), vignette=_vig(0.4, 0.85, 0.6), lens=dict(dispersion=0.02, distortion=0.0),
                   grade=_grade(1.3, 0.0, (0.94, 1.0, 1.1)), grain=None))

register('look', 'premium_clean', 'Premium Clean', 'commercial', 'Crisp medium-high contrast, a quarter stop lighter, warm-white tint: polished brand film.',
         data=dict(view_transform='AgX', look='AgX - Medium High Contrast', exposure=0.25, gamma=1.0,
                   glare=_fog(0.8, 0.15, 0.35), vignette=_vig(0.35, 0.9, 0.6), lens=None,
                   grade=_grade(1.0, 0.02, (1.14, 1.02, 0.88)), grain=None))

register('look', 'high_contrast_punchy', 'High Contrast Punchy', 'commercial', 'Filmic very high contrast with strongly boosted saturation: bold, saturated spots.',
         data=dict(view_transform='Filmic', look='Very High Contrast', exposure=0.2, gamma=1.0,
                   glare=_fog(0.72, 0.15, 0.35), vignette=_vig(0.4, 0.85, 0.6), lens=None,
                   grade=_grade(1.35, 0.06), grain=None))

register('look', 'film_warm', 'Film Warm', 'film', 'Amber highlights, a third of a stop darker, lifted faded blacks, gentle bloom and a little grain.',
         data=dict(view_transform='AgX', look='AgX - Medium Low Contrast', exposure=-0.3, gamma=1.0,
                   glare=_fog(0.48, 0.22, 0.45), vignette=_vig(0.5, 0.8, 0.7), lens=None,
                   grade=_grade(0.95, 0.03, (1.18, 1.0, 0.8), (0.02, 0.01, 0.0)), grain=0.1))

register('look', 'cool_tech', 'Cool Tech', 'tech', 'Cold cyan-blue cast, crisp contrast and a faint blue lift: devices and gadgets.',
         data=dict(view_transform='AgX', look='AgX - Medium High Contrast', exposure=0.2, gamma=1.0,
                   glare=_fog(0.64, 0.18, 0.35), vignette=_vig(0.45, 0.85, 0.6), lens=None,
                   grade=_grade(0.95, 0.04, (0.82, 1.02, 1.2), (0.0, 0.01, 0.03)), grain=None))

register('look', 'bleach_bypass', 'Bleach Bypass', 'film', 'Desaturated, hard contrast, slightly dark with grain: gritty cinematic look.',
         data=dict(view_transform='AgX', look='AgX - Very High Contrast', exposure=-0.2, gamma=1.0,
                   glare=_fog(0.8, 0.1, 0.3), vignette=_vig(0.6, 0.8, 0.7), lens=None,
                   grade=_grade(0.45, 0.08), grain=0.15))

register('look', 'pastel_airy', 'Pastel Airy', 'beauty', 'Very bright, very low contrast, soft saturation and a pink-lavender lift: light, airy, pastel.',
         data=dict(view_transform='AgX', look='AgX - Very Low Contrast', exposure=0.9, gamma=1.0,
                   glare=_fog(0.4, 0.3, 0.5), vignette=None, lens=None,
                   grade=_grade(0.75, 0.0, (1.05, 0.96, 1.1), (0.03, 0.015, 0.04)), grain=None))

register('look', 'noir', 'Noir', 'stylised', 'Black and white, very hard contrast, dark with a strong vignette and fine grain.',
         data=dict(view_transform='AgX', look='AgX - Very High Contrast', exposure=-0.3, gamma=1.0,
                   glare=_fog(0.6, 0.15, 0.35), vignette=_vig(1.0, 0.6, 0.7), lens=None,
                   grade=_grade(0.0, 0.1), grain=0.2))

register('look', 'teal_orange_light', 'Teal-Orange Light', 'film', 'Bright, complementary split: orange highlights and teal shadows.',
         data=dict(view_transform='AgX', look='AgX - Punchy', exposure=0.85, gamma=1.0,
                   glare=_fog(0.6, 0.15, 0.35), vignette=_vig(0.4, 0.85, 0.6), lens=None,
                   grade=_grade(1.1, 0.03, (1.3, 1.0, 0.75), (-0.015, 0.025, 0.045)), grain=None))

register('look', 'dreamy_bloom', 'Dreamy Bloom', 'stylised', 'Wide soft bloom, pink-lavender haze and lifted blacks: soft-focus dream glow.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=0.5, gamma=1.0,
                   glare=_bloom(0.15, 0.45, 0.7), vignette=_vig(0.35, 0.85, 0.7), lens=None,
                   grade=_grade(1.05, 0.0, (1.06, 0.95, 1.1), (0.03, 0.01, 0.04)), grain=None))

register('look', 'anamorphic_streaks', 'Anamorphic Streaks', 'stylised', 'Streaks on bright highlights, hint of dispersion and a steel-blue cast: cinema-lens flare.',
         data=dict(view_transform='AgX', look='AgX - Medium High Contrast', exposure=-0.1, gamma=1.0,
                   glare=dict(type='Streaks', threshold=1.0, strength=0.3, size=0.5, quality='Medium'), vignette=_vig(0.6, 0.8, 0.7), lens=dict(dispersion=0.008, distortion=0.0),
                   grade=_grade(1.0, 0.03, (0.75, 0.95, 1.25)), grain=None))

register('look', 'vintage_lens', 'Vintage Lens', 'film', 'Barrel distortion, visible dispersion, yellow-sepia fade, strong vignette and grain: old glass.',
         data=dict(view_transform='AgX', look='AgX - Medium Low Contrast', exposure=0.15, gamma=1.0,
                   glare=_fog(0.48, 0.25, 0.5), vignette=_vig(0.9, 0.7, 0.8), lens=dict(dispersion=0.025, distortion=0.04),
                   grade=_grade(0.7, 0.02, (1.1, 1.1, 0.7), (0.03, 0.02, 0.0)), grain=0.2))

register('look', 'grain_16mm', 'Grain 16mm', 'film', 'Soft 16mm feel: heavy grain, muted green-olive colour, soft bloom.',
         data=dict(view_transform='AgX', look='AgX - Medium Low Contrast', exposure=-0.2, gamma=1.0,
                   glare=_fog(0.48, 0.2, 0.45), vignette=_vig(0.6, 0.8, 0.7), lens=None,
                   grade=_grade(0.7, 0.02, (1.0, 1.1, 0.85), (0.015, 0.02, 0.0)), grain=0.3))

register('look', 'strong_vignette', 'Strong Vignette', 'stylised', 'Neutral grade, slightly darker, with a deep wide vignette that pulls the eye to the centre.',
         data=dict(view_transform='AgX', look='AgX - Base Contrast', exposure=-0.2, gamma=1.0,
                   glare=_fog(0.8, 0.12, 0.3), vignette=_vig(1.0, 0.45, 0.8), lens=None,
                   grade=None, grain=None))

register('look', 'neutral_delivery', 'Neutral Delivery', 'commercial', 'Plain AgX, no effects: for grading elsewhere or colour-critical delivery.',
         data=dict(view_transform='AgX', look='None', exposure=0.0, gamma=1.0,
                   glare=None, vignette=None, lens=None,
                   grade=None, grain=None))

register('look', 'ecommerce_neutral', 'E-commerce Neutral', 'commercial', 'Khronos PBR Neutral, 0.6 stop down: brand colours stay true, no glow, white products on white backdrops keep their detail.',
         data=dict(view_transform='Khronos PBR Neutral', look='None', exposure=-0.6, gamma=1.0,
                   glare=None, vignette=None, lens=None,
                   grade=None, grain=None))

register('look', 'luxury_gold', 'Luxury Gold', 'editorial', 'Dark, warm and rich: deep vignette, golden gain, restrained bloom.',
         data=dict(view_transform='AgX', look='AgX - High Contrast', exposure=-0.45, gamma=1.0,
                   glare=_fog(0.6, 0.2, 0.4), vignette=_vig(0.8, 0.7, 0.7), lens=None,
                   grade=_grade(1.0, 0.04, (1.25, 1.05, 0.7), (0.01, 0.0, 0.0)), grain=0.08))

register('look', 'cinematic_soft', 'Cinematic Soft', 'film', 'Soft contrast with a rosy-magenta cast and cool lifted shadows, gentle bloom and vignette: dreamy film stock.',
         data=dict(view_transform='AgX', look='AgX - Medium Low Contrast', exposure=-0.15, gamma=1.0,
                   glare=_fog(0.48, 0.22, 0.45), vignette=_vig(0.55, 0.8, 0.7), lens=None,
                   grade=_grade(1.0, 0.03, (1.1, 0.9, 1.1), (0.02, 0.0, 0.03)), grain=0.06))

register('look', 'glass_crystal', 'Glass Crystal', 'glass', 'Bright with an aqua-green cast, crisp high-threshold bloom on the brightest edges and mild dispersion: glass and gems.',
         data=dict(view_transform='AgX', look='AgX - Medium High Contrast', exposure=0.9, gamma=1.0,
                   glare=_bloom(1.0, 0.3, 0.4), vignette=_vig(0.4, 0.85, 0.6), lens=dict(dispersion=0.012, distortion=0.0),
                   grade=_grade(1.0, 0.03, (0.75, 1.15, 1.0)), grain=None))

register('look', 'neon_night', 'Neon Night', 'stylised', 'Dark, saturated, magenta shadows and blue-violet highlights with strong bloom and light dispersion.',
         data=dict(view_transform='AgX', look='AgX - Punchy', exposure=-0.15, gamma=1.0,
                   glare=_bloom(0.25, 0.5, 0.6), vignette=_vig(0.7, 0.75, 0.7), lens=dict(dispersion=0.015, distortion=0.0),
                   grade=_grade(1.3, 0.04, (1.05, 0.85, 1.25), (0.03, 0.0, 0.04)), grain=0.05))

register('look', 'matte_flat', 'Matte Flat', 'editorial', 'Heavily lifted blacks, low contrast, desaturated: modern matte editorial.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=0.1, gamma=1.0,
                   glare=None, vignette=_vig(0.2, 0.9, 0.6), lens=None,
                   grade=_grade(0.6, 0.0, (1.0, 1.0, 1.0), (0.07, 0.07, 0.07)), grain=0.05))

register('look', 'silk_highkey', 'Silk High-Key', 'beauty', 'Very bright and soft, warm peach tint with a gentle bloom: high-key beauty.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=1.2, gamma=1.0,
                   glare=_fog(0.4, 0.28, 0.5), vignette=None, lens=None,
                   grade=_grade(1.0, 0.0, (1.1, 1.0, 0.88), (0.01, 0.01, 0.01)), grain=None))

register('look', 'moody_blue', 'Moody Blue', 'editorial', 'Dark, cold and quiet: navy shadows, deep vignette, soft glow.',
         data=dict(view_transform='AgX', look='AgX - High Contrast', exposure=-0.5, gamma=1.0,
                   glare=_fog(0.6, 0.2, 0.4), vignette=_vig(0.9, 0.7, 0.7), lens=None,
                   grade=_grade(0.9, 0.04, (0.7, 0.9, 1.3), (0.0, 0.01, 0.04)), grain=0.1))

register('look', 'sunset_warm', 'Sunset Warm', 'film', 'Golden hour: strong orange-red gain, rich saturation, soft bloom.',
         data=dict(view_transform='AgX', look='AgX - Punchy', exposure=0.7, gamma=1.0,
                   glare=_fog(0.48, 0.3, 0.5), vignette=_vig(0.5, 0.8, 0.7), lens=None,
                   grade=_grade(1.2, 0.02, (1.3, 0.92, 0.62), (0.02, 0.0, -0.005)), grain=None))

register('look', 'monochrome', 'Monochrome', 'stylised', 'Soft black and white, lighter and gentler than Noir, with fine grain.',
         data=dict(view_transform='AgX', look='AgX - Greyscale', exposure=0.4, gamma=1.0,
                   glare=_fog(0.6, 0.15, 0.35), vignette=_vig(0.5, 0.8, 0.7), lens=None,
                   grade=_grade(0.0, 0.03), grain=0.12))

register('look', 'vivid_pop', 'Vivid Pop', 'stylised', 'Khronos PBR Neutral with a contrast push and very high saturation (no highlight clipping): toys, drinks and colourful packaging.',
         data=dict(view_transform='Khronos PBR Neutral', look='None', exposure=-0.3, gamma=1.0,
                   glare=_fog(0.6, 0.2, 0.4), vignette=_vig(0.25, 0.9, 0.6), lens=None,
                   grade=_grade(1.5, 0.12), grain=None))


register('look', 'noir_editorial', 'Noir Editorial', 'stylised', 'Black and white with deep blacks but readable midtones, hard contrast, soft vignette and fine grain: moody editorial.',
         data=dict(view_transform='AgX', look='AgX - Medium High Contrast', exposure=0.2, gamma=1.0,
                   glare=_fog(0.6, 0.15, 0.35), vignette=dict(darken=0.8, size=0.6, feather=0.8), lens=None,
                   grade=_grade(0.0, 0.1), grain=0.2))

register('look', 'punchy_agx', 'Punchy AgX', 'commercial', 'AgX Punchy with a little extra saturation and contrast: full, vivid colour that never reaches the gamut limit.',
         data=dict(view_transform='AgX', look='AgX - Punchy', exposure=0.5, gamma=1.0,
                   glare=_fog(0.72, 0.15, 0.35), vignette=_vig(0.4, 0.85, 0.6), lens=None,
                   grade=_grade(1.1, 0.05), grain=None))

register('look', 'jewel_sparkle', 'Jewel Sparkle', 'metal', 'Very high contrast steel-cold grade with small star flares on the brightest glints only: jewellery and watches.',
         data=dict(view_transform='AgX', look='AgX - Very High Contrast', exposure=0.15, gamma=1.0,
                   glare=dict(type='Simple Star', threshold=0.4, strength=0.45, size=0.3, quality='Medium'), vignette=_vig(0.4, 0.85, 0.6), lens=None,
                   grade=_grade(0.85, 0.0, (0.88, 1.0, 1.12)), grain=None))

register('look', 'pastel_depth', 'Pastel Depth', 'beauty', 'Soft pastel with a little more contrast, a pink-lavender lift and a gentle vignette: airy but not flat.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=0.0, gamma=1.0,
                   glare=_fog(0.4, 0.3, 0.5), vignette=_vig(0.6, 0.85, 0.6), lens=None,
                   grade=_grade(1.0, 0.1, (1.05, 0.96, 1.1), (0.03, 0.015, 0.04)), grain=None))

register('look', 'matte_soft_contrast', 'Matte Soft Contrast', 'editorial', 'Matte and calm like Matte Flat, but with deeper blacks and a little more contrast: soft shadows keep their shape.',
         data=dict(view_transform='AgX', look='AgX - Low Contrast', exposure=-0.2, gamma=1.0,
                   glare=None, vignette=_vig(0.2, 0.9, 0.6), lens=None,
                   grade=_grade(0.8, 0.08, (1.0, 1.0, 1.0), (0.03, 0.03, 0.03)), grain=0.05))

register('look', 'film_warm_lift', 'Film Warm Lift', 'film', 'Film Warm with the exposure back up (+0.4): amber highlights, faded blacks, gentle bloom and a little grain on a brighter picture.',
         data=dict(view_transform='AgX', look='AgX - Medium Low Contrast', exposure=0.4, gamma=1.0,
                   glare=_fog(0.48, 0.22, 0.45), vignette=_vig(0.5, 0.8, 0.7), lens=None,
                   grade=_grade(0.95, 0.03, (1.18, 1.0, 0.8), (0.02, 0.01, 0.0)), grain=0.1))
