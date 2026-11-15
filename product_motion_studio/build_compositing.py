"""Look: colour management + compositor node group (Blender 5.x: scene.compositing_node_group).

Chain: Render Layers > Glare > Lens Distortion > Colour balance / Saturation / Contrast > Vignette > Grain > Group Output.
"""

import json
import bpy
from . import core, live

GROUP = 'PMS_Compositing'
CYCLES_EV = -0.5          # stops taken off every Cycles render: Cycles has the studio's bounces, Eevee has not, so for the same
                          # lights a Cycles product is ~0.5 stop brighter (measured on 130 preset combinations, STATO.md)


def cycles_ev(scene):
    """Total exposure compensation (stops, negative) of a Cycles render of this scene: the global CYCLES_EV plus the optional
    'cycles_ev' of the lighting, background, background_light and floor presets in use (the few that deviate from the average)."""
    total = CYCLES_EV
    for section in ('lighting', 'background', 'background_light', 'floor'):
        try:
            total += float(core.preset(scene, section)[1].get('cycles_ev', 0.0))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    return total + recipe_ev(scene)


def recipe_ev(scene):
    """Optional 'cycles_ev' of the applied recipe (stops, + brighter), added to the section ones. It counts only while the
    lighting, background, background light and floor are still the ones of the recipe (a hand-picked preset cancels it)."""
    from . import presets
    try:
        pms = core.settings(scene)
        recipe = presets.get('recipe', pms.recipe)
        if all(getattr(pms, s) == recipe.data[s] for s in ('lighting', 'background', 'background_light', 'floor')):
            return float(recipe.meta.get('cycles_ev', 0.0))
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    return 0.0


def sync_ev(scene):
    """Put the compensation in Cycles' own Film > Exposure (scene.cycles.film_exposure, a linear multiplier that only Cycles uses):
    no engine hook is needed, Eevee ignores it. Called by the builders of lighting, background, background_light and floor and by this one."""
    try:
        scene.cycles.film_exposure = 2.0 ** cycles_ev(scene)
    except AttributeError:                                  # Cycles add-on disabled
        pass


def _socket(node, name, kind='RGBA'):
    return next(s for s in node.inputs if s.name == name and s.type == kind)


def _mix(nt, blend, a, b, factor):
    n = nt.nodes.new('ShaderNodeMix')
    n.data_type, n.blend_type = 'RGBA', blend
    n.inputs[0].default_value = factor if isinstance(factor, float) else 1.0
    if not isinstance(factor, float):
        nt.links.new(factor, n.inputs[0])
    nt.links.new(a, n.inputs[6])
    nt.links.new(b, n.inputs[7])
    return n.outputs[2]


def _set_look(vs, name, warnings):
    for cand in (name, 'None'):
        try:
            vs.look = cand
            return
        except TypeError:
            pass
    warnings.append(f"look {name!r} not available")


def _vignette(nt, img, v):
    new, link = nt.nodes.new, nt.links.new
    coords = new('CompositorNodeImageCoordinates')
    link(img, coords.inputs['Image'])                 # the input defines the pixel grid
    sub, ln = new('ShaderNodeVectorMath'), new('ShaderNodeVectorMath')
    sub.operation, ln.operation = 'SUBTRACT', 'LENGTH'
    sub.inputs[1].default_value = (0.5, 0.5, 0)
    ramp = new('ShaderNodeValToRGB')
    ramp.color_ramp.interpolation = 'EASE'
    outer = 0.7071
    inner = outer * v.get('size', 0.9) * (1 - 0.7 * v.get('feather', 0.5))
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = inner, (1, 1, 1, 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = outer, (0, 0, 0, 1)
    link(coords.outputs['Normalized'], sub.inputs[0])
    link(sub.outputs['Vector'], ln.inputs[0])
    link(ln.outputs['Value'], ramp.inputs['Fac'])
    dark = new('CompositorNodeExposure')
    dark.inputs['Exposure'].default_value = -float(v.get('darken', 0.5))
    link(img, dark.inputs['Image'])
    return _mix(nt, 'MIX', dark.outputs['Image'], img, ramp.outputs['Color'])


def _grain(nt, img, strength):
    new, link = nt.nodes.new, nt.links.new
    coords, noise = new('CompositorNodeImageCoordinates'), new('ShaderNodeTexWhiteNoise')
    link(img, coords.inputs['Image'])
    noise.noise_dimensions = '4D'
    link(coords.outputs['Pixel'], noise.inputs['Vector'])
    seed = new('ShaderNodeValue')                           # the frame as a node OUTPUT: a driven input would change by itself
    link(seed.outputs[0], noise.inputs['W'])                # and look like a hand edit to core.signature
    fcurve = seed.outputs[0].driver_add('default_value')
    fcurve.driver.type = 'SCRIPTED'
    fcurve.driver.expression = 'frame'
    return _mix(nt, 'OVERLAY', img, noise.outputs['Value'], float(strength) * 0.5)    # Value = grey grain (Color would tint it)


def build(scene):
    core.begin(scene)
    p, data = live.preset(scene, 'look')
    warnings = []
    vs = scene.view_settings
    vs.view_transform = data.get('view_transform', 'AgX')
    _set_look(vs, data.get('look', 'None'), warnings)
    vs.exposure, vs.gamma = data.get('exposure', 0.0), data.get('gamma', 1.0)

    scene.compositing_node_group = None
    old = bpy.data.node_groups.get(GROUP)
    if old is not None:
        bpy.data.node_groups.remove(old)
    ng = bpy.data.node_groups.new(GROUP, 'CompositorNodeTree')
    ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    new, link = ng.nodes.new, ng.links.new
    sync_ev(scene)
    img = neutral = new('CompositorNodeRLayers').outputs['Image']

    g = data.get('glare')
    if g:
        n = new('CompositorNodeGlare')
        n.inputs['Type'].default_value = g.get('type', 'Fog Glow')
        n.inputs['Quality'].default_value = g.get('quality', 'Medium')
        for key, name in (('threshold', 'Threshold'), ('strength', 'Strength'), ('size', 'Size')):
            if key in g:
                n.inputs[name].default_value = g[key]
        if 'tint' in g:                                     # coloured glow (halation): RGB, alpha 1
            n.inputs['Tint'].default_value = (*g['tint'][:3], 1.0)
        link(img, n.inputs['Image'])
        img = n.outputs['Image']
    lens = data.get('lens')
    if lens:
        n = new('CompositorNodeLensdist')
        n.inputs['Dispersion'].default_value = lens.get('dispersion', 0.0)
        n.inputs['Distortion'].default_value = lens.get('distortion', 0.0)
        n.inputs['Fit'].default_value = lens.get('distortion', 0.0) > 0      # scale up so no black edges show
        link(img, n.inputs['Image'])
        img = n.outputs['Image']
    grade = data.get('grade')
    if grade:
        cb = new('CompositorNodeColorBalance')
        _socket(cb, 'Gain').default_value = (*grade.get('gain', (1, 1, 1)), 1.0)
        _socket(cb, 'Lift').default_value = (*(1 + c for c in grade.get('lift', (0, 0, 0))), 1.0)
        link(img, cb.inputs['Image'])
        hs = new('CompositorNodeHueSat')
        hs.inputs['Saturation'].default_value = grade.get('saturation', 1.0)
        link(cb.outputs['Image'], hs.inputs['Image'])
        img = hs.outputs['Image']
        if grade.get('contrast'):
            bc = new('CompositorNodeBrightContrast')
            bc.inputs['Contrast'].default_value = grade['contrast'] * 100
            link(img, bc.inputs['Image'])
            img = bc.outputs['Image']
    if data.get('vignette'):
        img = _vignette(ng, img, data['vignette'])
    if data.get('grain'):
        try:
            img = _grain(ng, img, data['grain'])
        except Exception as e:                                  # driver/noise API differences: skip, report
            warnings.append(f"grain skipped: {e}")
    mix = new('ShaderNodeMix')                                  # Intensity (live): 0 = the neutral render, 1 = the whole look
    mix.name, mix.label = 'PMS_Intensity', 'Look Intensity'
    mix.data_type, mix.blend_type = 'RGBA', 'MIX'
    mix.inputs[0].default_value = data.get('intensity', 1.0)
    link(neutral, mix.inputs[6])
    link(img, mix.inputs[7])
    img = mix.outputs[2]
    out = new('NodeGroupOutput')
    link(img, out.inputs['Image'])
    ng['pms_vignette'] = json.dumps(data.get('vignette') or {})        # (user_presets: the size / feather the ramp was made from)
    scene.compositing_node_group = ng
    scene.render.use_compositing = True
    return {'look': p.id, 'view_transform': vs.view_transform, 'look_applied': vs.look,
            'nodes': len(ng.nodes), 'warnings': warnings}
