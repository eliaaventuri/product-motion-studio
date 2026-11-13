"""BACKGROUND presets: DATA dicts for the backdrop behind the product.

SCHEMA   register('background', id, name, category, desc, data=dict(
             kind='cyclorama' (wall + cove behind the product) | 'studio360' (closed round room, for orbits) |
                  'image' (plate parented to the camera pivot, shows the file in the add-on's Background Image field),
             stops=[(pos 0..1, (r, g, b)), ...]   colour ramp (linear colours) along the profile: 0 = start, 1 = top of the wall
                                                  (radial gradients: 0 = centre),
             gradient=dict(type='linear'|'radial', rotation=deg, center=(u, v)),
             roughness=0..1, self_light=emission strength (0 = lit only by the lights),
             world_fill=(strength, (r, g, b)) optional: ambient the product reflects, for backdrops with nothing around it (image plates)))
RULES    - Sizes come from the product size (see build_background.layout); never put absolute lengths here.
         - Keep colours dark/mid (albedo 0.1-0.45): the lights lift them. Higher albedo clips on AgX.
         - The 'floor' section decides if the floor is part of this mesh (floor 'seamless') or a separate plane.
OPTIONAL cycles_ev=stops (+ brighter) in data: extra Cycles exposure compensation of the preset, see CYCLES_EV at the end of the file.
"""

from . import REGISTRY, register

register('background', 'cyclorama_studio_grey', 'Cyclorama Studio Grey', 'studio',
         'Seamless grey cyclorama, slightly darker towards the top.',
         data=dict(kind='cyclorama', roughness=0.9, self_light=0.0,
                   gradient=dict(type='linear', rotation=0),
                   stops=[(0.0, (0.34, 0.34, 0.35)), (0.55, (0.30, 0.30, 0.31)), (1.0, (0.12, 0.12, 0.13))]))

register('background', 'cyclorama_gradient_blue', 'Cyclorama Gradient Blue', 'colour',
         'Seamless cyclorama, mid blue on the floor fading to deep navy.',
         data=dict(kind='cyclorama', roughness=0.85, self_light=0.0,
                   gradient=dict(type='linear', rotation=0),
                   stops=[(0.0, (0.04, 0.12, 0.40)), (0.5, (0.02, 0.07, 0.28)), (1.0, (0.005, 0.015, 0.08))]))

register('background', 'studio_360', '360 Studio', 'studio',
         'Closed round white-grey room: use with orbits, nothing but background in every direction.',
         data=dict(kind='studio360', roughness=0.9, self_light=0.5,
                   gradient=dict(type='linear', rotation=0),
                   stops=[(0.0, (0.38, 0.38, 0.40)), (1.0, (0.20, 0.20, 0.22))]))

register('background', 'image', 'Image Backplate', 'image',
         'Picture (set Background Image) on a plate that follows the camera pivot; grey gradient if no file.',
         data=dict(kind='image', roughness=1.0, self_light=1.0, world_fill=(0.5, (0.6, 0.6, 0.62)),
                   gradient=dict(type='radial', rotation=0, center=(0.5, 0.5)),
                   stops=[(0.0, (0.45, 0.45, 0.47)), (1.0, (0.12, 0.12, 0.13))]))


# === extra backdrops ========================================================
# Colours are written as sRGB hex (what you would pick in a colour picker) and converted to linear.
# What the camera sees of a cyclorama is mostly the floor and the foot of the wall (profile 0.28..0.6 with a
# seamless floor, 0..0.25 when the floor is a separate plane): so the gradients live in that range.

def _lin(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def _mix(a, b, t=0.5):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _cyc(id, name, category, desc, floor, wall, top=None, rough=0.9, kind='cyclorama', mid=None, self_light=0.0, **extra):
    """Linear gradient: `floor` colour to `wall` colour around the cove, `top` at the top of the wall."""
    f, w = _lin(floor), _lin(wall)
    t = _lin(top) if top else w
    stops = [(0.0, f), (0.3, f), (0.62, _lin(mid) if mid else w), (1.0, t)]
    if kind == 'studio360':
        stops = [(0.0, f), (0.3, _mix(f, w, 0.35)), (0.5, w), (1.0, t)]
    register('background', id, name, category, desc,
             data=dict(kind=kind, roughness=rough, self_light=self_light, gradient=dict(type='linear', rotation=0),
                       stops=stops, **extra))


def _radial(id, name, category, desc, colors, center, rough=0.9, kind='cyclorama', self_light=0.0, **extra):
    """Radial gradient: colors = [(pos, hex)], 0 = centre. On a cyclorama the camera sees only a small part
    of the UV square, so the stops sit in 0..0.15 (the visible pool is about 3 x product size wide)."""
    register('background', id, name, category, desc,
             data=dict(kind=kind, roughness=rough, self_light=self_light,
                       gradient=dict(type='radial', rotation=0, center=center),
                       stops=[(p, _lin(h)) for p, h in colors], **extra))


_cyc('cyclorama_pure_white', 'Cyclorama Pure White', 'studio',
     'Clean high-key white sweep for e-commerce and tech: pair with bright lights.',
     '#B8B8B7', '#AEAEAE', '#8A8A8C', self_light=5.5)
_cyc('cyclorama_gloss_black', 'Cyclorama Gloss Black', 'studio',
     'Glossy black sweep: the product reflects softly on the floor, jewellery/premium look.',
     '#1F1F22', '#131316', '#070709', rough=0.22, self_light=0.5)
_cyc('cyclorama_warm_cream', 'Cyclorama Warm Cream', 'studio',
     'Warm cream paper sweep: cosmetics, food, lifestyle.',
     '#B8A585', '#AA9770', '#7A6A52', self_light=0.75)
_cyc('cyclorama_graphite', 'Cyclorama Graphite', 'studio',
     'Mid-dark graphite sweep: technical, serious, makes metals pop.',
     '#5A5C61', '#43454A', '#1C1D20', rough=0.6, self_light=0.62)
_cyc('cyclorama_pastel_pink', 'Cyclorama Pastel Pink', 'colour',
     'Soft powder pink sweep.', '#B8949A', '#AF8A90', '#8C666D', self_light=0.75)
_cyc('cyclorama_pastel_mint', 'Cyclorama Pastel Mint', 'colour',
     'Soft mint green sweep.', '#8FB8A3', '#82AB97', '#5E8271', self_light=1.0)
_cyc('cyclorama_pastel_sky', 'Cyclorama Pastel Sky', 'colour',
     'Soft sky blue sweep.', '#92B0C9', '#84A3BE', '#60809B', self_light=0.75)
_cyc('cyclorama_brand_red', 'Cyclorama Brand Red', 'colour',
     'Saturated brand red floor falling to deep burgundy.', '#B9282D', '#9C1E24', '#3E0A0E', mid='#7A161B', self_light=0.5)
_cyc('cyclorama_deep_green', 'Cyclorama Deep Green', 'colour',
     'Premium forest green, rich and quiet.', '#2F7258', '#1D5240', '#081C14', mid='#17402F', self_light=0.75)
_cyc('cyclorama_sunset', 'Cyclorama Sunset Gradient', 'colour',
     'Warm orange floor fading through rose to plum: lifestyle and beauty.',
     '#B8734C', '#A9577D', '#3A2260', mid='#8A4B78', self_light=0.62)
_cyc('cyclorama_duotone_teal_orange', 'Cyclorama Duotone Teal-Orange', 'colour',
     'Teal floor rising to warm orange: complementary duotone, very "ad".',
     '#2B8F92', '#B96A2B', '#B96A2B', mid='#D9792B', self_light=0.5)
_radial('cyclorama_radial_spotlight', 'Cyclorama Radial Spotlight', 'studio',
        'Neutral grey pool of light behind the product falling off to near black.',
        [(0.0, '#B0B0B3'), (0.04, '#68686C'), (0.10, '#242427'), (1.0, '#0E0E10')], (0.5, 0.38), self_light=1.0)
_radial('cyclorama_radial_brand_blue', 'Cyclorama Radial Brand Blue', 'colour',
        'Bright brand blue glow around the product fading to deep navy.',
        [(0.0, '#3C66B8'), (0.05, '#2F56AC'), (0.12, '#12255E'), (1.0, '#071230')], (0.5, 0.38), self_light=1.0)
_cyc('studio_360_dark', '360 Studio Charcoal', 'studio',
     'Closed round room in charcoal: moody orbits with nothing but dark background.',
     '#3B3C41', '#26272B', '#101113', kind='studio360', self_light=0.5)
_cyc('studio_360_warm', '360 Studio Warm', 'studio',
     'Closed round room in warm sand: soft, friendly orbits.',
     '#BBAD95', '#8E8068', '#5C5243', kind='studio360', self_light=1.0)
_radial('image_dark', 'Image Backplate Dark', 'image',
        'Picture (set Background Image) on a camera-following plate; dark vignette gradient if no file.',
        [(0.0, '#3E3E45'), (0.6, '#17171B'), (1.0, '#09090B')], (0.5, 0.5), rough=1.0, kind='image', self_light=1.0,
        world_fill=(0.2, (0.5, 0.5, 0.55)))


# --- dedicated to recipes (presets/recipe.py) ---------------------------------------------------------------------------
_cyc('cyclorama_noir_graphite', 'Cyclorama Noir Graphite', 'studio',
     'Very dark graphite sweep with a soft sheen: the product separates from it without the black hole of a pure black.',
     '#3D3E42', '#2E2F33', '#111113', rough=0.6, self_light=0.62)


_radial('cyclorama_radial_cobalt', 'Cyclorama Radial Cobalt', 'colour',
        'Rich cobalt blue glow behind the product fading to deep navy: full colour that stays below the gamut limit.',
        [(0.0, '#2A5AD8'), (0.06, '#2249BE'), (0.14, '#132872'), (1.0, '#050A24')], (0.5, 0.38), self_light=1.0)


_cyc('cyclorama_ecom_white', 'Cyclorama E-commerce White', 'studio',
     'Bright white sweep that is lit as well as glowing a little: soft contact shadows and glass that does not vanish (e-commerce).',
     '#E6E6E4', '#DADAD8', '#BDBDBC', self_light=1.6)


_cyc('cyclorama_dusty_rose', 'Cyclorama Dusty Rose', 'colour',
     'Pale powder-pink floor rising to a dusty rose wall and a deep rose top: soft but with depth, white products stand out.',
     '#E3C2C6', '#B88690', '#6A4350', self_light=0.9)


_cyc('cyclorama_warm_clay', 'Cyclorama Warm Clay', 'studio',
     'Darker warm clay-brown paper that is lit rather than glowing: food and objects lit from the side stand out against it.',
     '#9C7D55', '#7E6343', '#3E2F20', self_light=0.12)


# CYCLES COMPENSATION: Cycles has the studio's bounces and Eevee has not, so build_compositing.CYCLES_EV takes half a stop off every
# Cycles render; these are the presets that need more or less than that (stops, + = brighter), measured with the test scene against
# Eevee (STATO.md, "Cycles"). They add up with the ones of the other sections.  Re-measure after changing the lights.
CYCLES_EV = {
    'studio_360': +0.10,
    'image': +0.50,
    'cyclorama_pure_white': +0.10,
    'cyclorama_ecom_white': +0.20,
    'cyclorama_warm_cream': +0.15,
    'cyclorama_warm_clay': +0.15,
    'cyclorama_graphite': +0.15,
    'cyclorama_pastel_pink': +0.15,
    'cyclorama_dusty_rose': +0.15,
    'cyclorama_pastel_mint': +0.15,
    'cyclorama_pastel_sky': +0.15,
    'cyclorama_brand_red': +0.15,
    'cyclorama_deep_green': +0.20,
    'cyclorama_sunset': +0.20,
    'cyclorama_duotone_teal_orange': +0.15,
    'cyclorama_radial_spotlight': +0.35,
    'cyclorama_radial_brand_blue': +0.30,
    'cyclorama_radial_cobalt': +0.30,
    'cyclorama_noir_graphite': +0.15,
    'studio_360_dark': +0.15,
    'studio_360_warm': +0.15,
    'image_dark': +0.30,
}
for _id, _ev in CYCLES_EV.items():
    REGISTRY['background'][_id].data['cycles_ev'] = _ev
