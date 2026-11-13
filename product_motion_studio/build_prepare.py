"""Prepare: PMS_Product_Root (Empty at the bbox centre) becomes the parent of the product objects."""

from math import ceil, floor
import bpy
from mathutils import Matrix, Vector
from . import core

MESHY = {'CURVE', 'FONT', 'SURFACE', 'META'}     # their real geometry is an evaluated MESH instance in the depsgraph
MAX_SAMPLES = 24


def _is_product(ob):
    """Geometry; an Empty that holds geometry (children) or instances a collection; an Armature with geometric children."""
    if ob.name.startswith('PMS_'):
        return False
    if ob.type in core.GEOMETRY:
        return True
    if ob.type == 'EMPTY' and ob.instance_type == 'COLLECTION' and ob.instance_collection is not None:
        return True
    return ob.type in ('EMPTY', 'ARMATURE') and any(_is_product(c) for c in ob.children)


def _under(ob, root):
    while ob is not None:
        if ob == root:
            return True
        ob = ob.parent
    return False


def _resolve(scene, objects):
    """-> (products, ignored). Raises before anything is touched if an object does not exist / is not in the scene."""
    out, bad = [], []
    for o in objects:
        if isinstance(o, str):
            ob = bpy.data.objects.get(o)
            if ob is None:
                raise RuntimeError(f"PMS prepare: object '{o}' does not exist")
        else:
            ob = o
            try:
                ob.name
            except ReferenceError:
                raise RuntimeError("PMS prepare: an object was deleted") from None
        if ob.name not in scene.objects:
            raise RuntimeError(f"PMS prepare: object '{ob.name}' is not in the scene")
        if ob.name.startswith('PMS_') or ob in out or ob in bad:
            continue
        (out if _is_product(ob) else bad).append(ob)
    return out, bad


def _ignored(bad):
    return "Ignored: " + ", ".join(o.name for o in bad) + " (not geometry)"


def _descendants(obs):
    allobs = list(obs)
    for ob in allobs:
        for c in ob.children:
            if c not in allobs and not c.name.startswith('PMS_'):
                allobs.append(c)
    return allobs


def _hidden(ob):
    try:
        visible = ob.visible_get()                 # viewport flags, hidden/excluded collections
    except RuntimeError:
        visible = False
    cols = ob.users_collection
    return bool(ob.hide_viewport or ob.hide_render or not visible or (cols and all(c.hide_render for c in cols)))


def _anim_range(obs):
    """(first, last) frame of the own animation of the objects or of their parents, or None."""
    chain = list(obs)
    for ob in chain:
        if ob.parent is not None and ob.parent not in chain:
            chain.append(ob.parent)
    spans = []
    for ob in chain:
        ad = ob.animation_data
        if ad is None:
            continue
        if ad.action is not None:
            spans.append(tuple(ad.action.frame_range))
        spans += [(s.frame_start, s.frame_end) for t in ad.nla_tracks for s in t.strips]
    if not spans:
        return None
    return min(s[0] for s in spans), max(s[1] for s in spans)


def _sample_frames(first, last):
    first, last = floor(first), ceil(last)
    n = min(MAX_SAMPLES, last - first + 1)
    if n <= 1:
        return [first]
    return sorted({round(first + (last - first) * i / (n - 1)) for i in range(n)})


def _collect(dg, live):
    """World corners per owner from the depsgraph instances (covers evaluated curves/text, collection instances)."""
    pts = {}
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type not in core.GEOMETRY:
            continue
        mesh_of_curve = False
        if inst.is_instance:
            if inst.parent is None:
                continue
            owner = inst.parent.original
            mesh_of_curve = ob.type == 'MESH' and owner.type in MESHY
        else:
            owner = ob.original
        if owner.name in live:
            pts.setdefault(owner.name, {'mesh': [], 'plain': []})['mesh' if mesh_of_curve else 'plain'] += \
                [inst.matrix_world @ Vector(c) for c in ob.bound_box]
    return [p for d in pts.values() for p in (d['mesh'] or d['plain'])]


def _bounds(scene, obs, warnings):
    """World bbox of the visible geometry (sampled over the objects' own animation); notes go into warnings."""
    carriers = [o for o in obs if o.type in core.GEOMETRY or (o.type == 'EMPTY' and o.instance_type == 'COLLECTION')]
    hidden = {o.name for o in carriers if _hidden(o)}
    if hidden:
        n = len(hidden)
        warnings.append(f"{n} hidden object{'' if n == 1 else 's'} excluded from the framing")
    live = {o.name for o in carriers} - hidden
    span = _anim_range(obs)
    frames = _sample_frames(*span) if span else [None]
    if span:
        warnings.append("The product has its own animation: framing computed over the whole movement")
    cur = (scene.frame_current, scene.frame_subframe)
    pts = []
    try:
        for f in frames:
            if f is not None:
                scene.frame_set(f)
            pts += _collect(bpy.context.evaluated_depsgraph_get(), live)
    finally:
        if span:
            scene.frame_set(cur[0], subframe=cur[1])
    if not pts:
        raise RuntimeError("PMS prepare: " + ("all the product objects are hidden" if hidden
                                              else "the selected objects have no geometry"))
    return (Vector(min(p[i] for p in pts) for i in range(3)),
            Vector(max(p[i] for p in pts) for i in range(3)))


def _adopt(root, ob, inv):
    """Parent ob to root keeping its world transform (basis and keys untouched); remembers how to give it back."""
    parent_part = (ob.parent.matrix_world @ ob.matrix_parent_inverse) if ob.parent else Matrix.Identity(4)
    ob['pms_orig'] = {'parent': ob.parent.name if ob.parent else '',
                      'pinv': [v for row in ob.matrix_parent_inverse for v in row]}
    ob.parent = root
    ob.matrix_parent_inverse = inv @ parent_part


def _detach(old):
    """Like core.unprepare but keeps the root alive; returns [(object, parent inverse it had under the root)]."""
    saved = []
    for ob in list(old.children):
        orig = ob.get('pms_orig')
        if orig is None:
            continue
        saved.append((ob, ob.matrix_parent_inverse.copy()))
        ob.parent = bpy.data.objects.get(orig['parent']) if orig['parent'] else None
        ob.matrix_parent_inverse = Matrix([orig['pinv'][i * 4:i * 4 + 4] for i in range(4)])
    return saved


def _normalise(sel, current):
    """Selected objects that sit inside a current product count as that product (top)."""
    cur = {o.name for o in current}
    out = []
    for s in sel:
        p = s
        while p is not None and p.name not in cur:
            p = p.parent
        t = p if p is not None else s
        if t not in out:
            out.append(t)
    return out


def build(scene, objects=None, ground=None):
    """objects: objects / names. None = the selection if it is a (valid) different product than the current one,
    else the current product. Everything is validated before the prepared product is touched; a failure leaves the
    scene as it was. Returns a dict with 'warnings'."""
    pms = core.settings(scene)
    warnings = []
    old = bpy.data.objects.get(core.ROOT_NAME)
    current = [c for c in old.children if 'pms_orig' in c] if old else []
    if objects is None:
        sel, bad = _resolve(scene, bpy.context.selected_objects)
        norm = _normalise(sel, current)
        obs = norm if norm and (old is None or {o.name for o in norm} != {o.name for o in current}) else current
    else:
        obs, bad = _resolve(scene, objects)
    if not obs:
        raise RuntimeError("PMS prepare: no product (select objects or pass objects=[...])"
                           + (f" - {_ignored(bad)}" if bad else ""))
    if bad:
        warnings.append(_ignored(bad))
    saved = _detach(old) if old else []
    try:
        bpy.context.view_layer.update()
        desc = _descendants(obs)
        mn, mx = _bounds(scene, desc, warnings)
        dims, center = mx - mn, (mn + mx) / 2
        if dims.length < 1e-9:
            raise RuntimeError("PMS prepare: the product has zero size")
    except BaseException:
        for ob, pinv in saved:                       # roll back: the prepared product stays as it was
            ob.parent = old
            ob.matrix_parent_inverse = pinv
        bpy.context.view_layer.update()
        raise
    if old:
        for ob, _ in saved:
            if 'pms_orig' in ob:
                del ob['pms_orig']
        bpy.data.objects.remove(old, do_unlink=True)
        core.purge_orphans()
    core.begin(scene)
    if ground is not None:
        pms.ground = bool(ground)
    names = {o.name for o in desc}
    tops = [o for o in obs if not (o.parent and o.parent.name in names)]

    root = bpy.data.objects.new(core.ROOT_NAME, None)
    root.empty_display_type, root.empty_display_size = 'PLAIN_AXES', dims.length * 0.15
    root.location = center
    core.link(scene, 'product', root)
    bpy.context.view_layer.update()
    inv = root.matrix_world.inverted()
    for ob in tops:
        _adopt(root, ob, inv)
    if pms.ground:
        center.z += -mn.z
    root['pms_dims'], root['pms_size'], root['pms_ground'] = list(dims), dims.length, bool(pms.ground)
    root['pms_center'] = list(center)
    core.restore_rest_values(root)
    bpy.context.view_layer.update()
    return {'root': root.name, 'size': dims.length, 'dims': tuple(dims), 'center': tuple(center),
            'products': [o.name for o in tops], 'ground': pms.ground, 'warnings': warnings}


def add_objects(scene, objects, warnings=None):
    """Add pieces to the prepared product: parent them to the root keeping their world transform, recompute
    pms_size/dims/center from the new box. The product does not move in the world (no re-grounding): the root
    empty slides to the new box centre and the children's parent inverses compensate. The root animation is
    cleared (it was keyed on the old centre): re-run the animation..floor steps afterwards.
    Notes (ignored / hidden objects ...) are appended to `warnings` if a list is given. Returns the root."""
    root = bpy.data.objects.get(core.ROOT_NAME)
    if root is None:
        raise RuntimeError("PMS add_objects: no product prepared (use prepare first)")
    notes = warnings if warnings is not None else []
    new, bad = _resolve(scene, objects)
    new = [o for o in new if not _under(o, root)]
    if bad:
        notes.append(_ignored(bad))
    if not new:
        raise RuntimeError("PMS add_objects: no new object with geometry to add"
                           + (f" - {_ignored(bad)}" if bad else ""))
    core.reset_root(root)                            # rest pose: world transforms are the prepared ones
    bpy.context.view_layer.update()
    existing = list(root.children)
    mn, mx = _bounds(scene, _descendants(existing + new), notes)
    dims, center = mx - mn, (mn + mx) / 2
    names = {o.name for o in _descendants(new)}
    inv = root.matrix_world.inverted()
    for ob in [o for o in new if not (o.parent and o.parent.name in names)]:
        _adopt(root, ob, inv)
    shift = Matrix.Translation(root.location - center)
    for ob in root.children:
        ob.matrix_parent_inverse = shift @ ob.matrix_parent_inverse
    root.location = center
    root.empty_display_size = dims.length * 0.15
    root['pms_dims'], root['pms_size'], root['pms_center'] = list(dims), dims.length, list(center)
    bpy.context.view_layer.update()
    return root
