"""Camera: rig PMS_Cam_Target > PMS_Cam_Pivot > PMS_Camera (+ PMS_DOF_Empty), distance fitted to the product."""

from math import asin, pi, radians, sin
import bpy
from mathutils import Vector
from . import core, live


def _kept_children(scene, pms):
    """Objects of other sections hanging on the old pivot (the 'image' backplate, when it was edited by hand and so
    is not rebuilt) with their world matrix at the start frame: the pivot is about to be deleted."""
    old = bpy.data.objects.get('PMS_Cam_Pivot')
    cam_col = bpy.data.collections.get(core.SUB['camera'])
    if old is None or cam_col is None:
        return []
    mine = {o.name for o in cam_col.all_objects}
    kids = [c for c in old.children_recursive if c.name not in mine]
    if not kids:
        return []
    cur = scene.frame_current
    scene.frame_set(core.frame_range(pms)[0])
    kept = [(c, c.matrix_world.copy()) for c in kids]
    scene.frame_set(cur)
    return kept


def _readopt(scene, pms, pivot, kept):
    """Parent the kept objects to the new pivot without moving them (world matrix at the start frame)."""
    if not kept:
        return
    cur = scene.frame_current
    scene.frame_set(core.frame_range(pms)[0])
    for ob, mw in kept:
        ob.parent = pivot
        ob.matrix_parent_inverse.identity()
        ob.matrix_world = mw
    scene.frame_set(cur)


def _camera_views(scene):
    """3D views looking through the scene camera: deleting the old camera would throw them out of camera view."""
    views = []
    wm = bpy.context.window_manager
    for win in (wm.windows if wm else []):
        if win.scene != scene:
            continue
        for area in win.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            sp = area.spaces.active
            if sp.region_3d and sp.region_3d.view_perspective == 'CAMERA':
                views.append(sp)
    return views


def _restore_views(views, cam):
    for sp in views:
        if sp.use_local_camera:
            sp.camera = cam
        sp.region_3d.view_perspective = 'CAMERA'


def build(scene):
    core.begin(scene)
    views = _camera_views(scene)
    pms = core.settings(scene)
    inf = core.info(scene)
    kept = _kept_children(scene, pms)
    core.clear_section(scene, 'camera')
    shot_p, shot = live.preset(scene, 'camera_shot')       # lens / padding / f-stop / focus: the live values
    mot_p, _ = core.preset(scene, 'camera_motion')
    prod_p, _ = core.preset(scene, 'product_motion')
    meta = prod_p.meta
    f0, f1 = core.frame_range(pms)
    track = core.Track(inf, f0, f1, loop=bool(meta.get('loop')), fps=int(pms.fps))                     # the product's real motion

    lens, pad = float(shot['lens']), float(shot['padding'])
    az, el = radians(shot['az']), radians(shot['el'])
    tz = shot.get('target_z', 0.5)
    target_pos = Vector((inf.center.x, inf.center.y, inf.base_z + tz * inf.dims.z))
    target_pos += Vector(track.hero_center()) - inf.center    # looks at the hero pose (a drift that ends off-centre stays centred)
    tans = core.frame_tans(scene, lens)
    if meta.get('offscreen'):
        track.mark_offscreen(target_pos, az, el, tans, pad)
    dist = track.fit(target_pos, [az], [el], tans, pad)
    warnings = []
    min_z = inf.base_z + 0.02 * inf.size                    # camera never goes under the floor
    if target_pos.z + dist * sin(el) < min_z:
        el = asin(max(-1.0, min(1.0, (min_z - target_pos.z) / dist)))
        dist = track.fit(target_pos, [az], [el], tans, pad)
        warnings.append("camera raised to stay above the floor")
    pms.base_az = shot['az']

    target = core.new_empty(scene, 'camera', 'PMS_Cam_Target', target_pos, 'SPHERE', inf.size * 0.03)
    pivot = core.new_empty(scene, 'camera', 'PMS_Cam_Pivot', (0, 0, 0), 'PLAIN_AXES', inf.size * 0.1, parent=target)
    pivot.rotation_euler = (-el, 0, az)
    cdata = bpy.data.cameras.new('PMS_Camera')
    cdata.lens, cdata.sensor_fit = lens, 'AUTO'
    cdata.clip_start, cdata.clip_end = inf.size * 0.01, inf.size * 300
    cam = core.link(scene, 'camera', bpy.data.objects.new('PMS_Camera', cdata))
    cam.parent = pivot
    cam.location = (0, -dist, 0)
    cam.rotation_euler = (pi / 2, 0, 0)                      # looks along the pivot's +Y, at its origin
    dof = core.new_empty(scene, 'camera', 'PMS_DOF_Empty', inf.center, 'SPHERE', inf.size * 0.02)
    dof['pms_back'] = tuple(core.cam_basis(az, el)[2])      # target -> camera: the live Focus Offset moves the empty along it
    live.apply_focus(scene, cdata)

    ctx = core.CamCtx(scene, inf, core.overrides(scene, 'camera_motion'), az, el, dist, lens, pad,
                      track, target_pos)
    if mot_p.fn is not None:
        mot_p.fn(pivot, cam, target, ctx)
    scene.camera = cam
    _restore_views(views, cam)
    core.orient_rigs(scene)
    _readopt(scene, pms, pivot, kept)
    bpy.context.view_layer.update()
    return {'camera': cam.name, 'shot': shot_p.id, 'camera_motion': mot_p.id, 'distance': dist,
            'lens': lens, 'opts_used': sorted(ctx.opt.used), 'warnings': warnings}
