"""N-panel "PMS": a Recipe picker on top and numbered sub-panels 1..10 (Prepare, Camera, Product Motion, Lighting, Background,
Background Light, Floor, Format, Look, Render) with their live controls, and the operators behind the buttons (they call api.py)."""

import textwrap
import traceback
import bpy
from . import api, batch, core, live, presets, previews, props, render_settings, user_presets


def _msg(e):
    """The text of an exception for the info bar (KeyError would show it in quotes)."""
    return str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)


class _PMSOperator(bpy.types.Operator):
    """Base: undoable, never a traceback in the UI (the error goes to the info bar, the traceback to the console),
    and a confirmation before overwriting what the user edited by hand."""
    bl_options = {'REGISTER', 'UNDO'}
    force: bpy.props.BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})      # set by invoke after the user confirms

    def steps(self, context):
        return ()

    def invoke(self, context, event):
        text = api.modified_text(self.steps(context), context.scene) if self.steps(context) else None
        if text is None:
            return self.execute(context)
        self.force = True
        return context.window_manager.invoke_confirm(self, event, title="Edited by hand", message=text,
                                                     confirm_text="Overwrite", icon='ERROR')

    def perform(self, context):
        raise NotImplementedError

    def execute(self, context):
        new_studio = bpy.data.objects.get('PMS_Camera') is None
        try:
            out = self.perform(context)
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            self.report({'ERROR'}, _msg(e))
            return {'CANCELLED'}
        if new_studio and bpy.data.objects.get('PMS_Camera') is not None:
            _look_through_camera(context)
        for w in out['warnings']:
            self.report({'WARNING'}, w)
        return {'FINISHED'}


def _look_through_camera(context):
    """The studio was just created: the 3D views of this window show it through its camera (later builds leave the view alone)."""
    for area in (context.screen.areas if context.screen else ()):
        if area.type == 'VIEW_3D':
            area.spaces.active.region_3d.view_perspective = 'CAMERA'


class PMS_OT_build_all(_PMSOperator):
    bl_idname, bl_label = "pms.build_all", "Build All"
    bl_description = "Build the whole studio with the current choices (selected objects are the product)"

    def steps(self, context):
        return set(api.STEPS)

    def perform(self, context):
        return api.run(api.STEPS, None, context.scene, self.force)


class PMS_OT_build_section(_PMSOperator):
    bl_idname, bl_label = "pms.build_section", "Build"
    bl_description = "Rebuild this section (and what depends on it)"
    section: bpy.props.StringProperty()

    def steps(self, context):
        return api.steps_for(self.section, context.scene)

    def perform(self, context):
        return api.run(api.steps_for(self.section, context.scene), None, context.scene, self.force)


class PMS_OT_add_objects(_PMSOperator):
    bl_idname, bl_label = "pms.add_objects", "Add to Product"
    bl_description = "Add the selected objects to the prepared product and rebuild what follows"

    def steps(self, context):
        return set(api.STEPS[1:-1])

    def perform(self, context):
        return api.add_objects(context.selected_objects, self.force)


class PMS_OT_apply_recipe(_PMSOperator):
    bl_idname, bl_label = "pms.apply_recipe", "Apply Recipe"
    bl_description = "Apply the chosen recipe: motion, shot, lighting, background, look, format and duration in one go"

    def steps(self, context):
        return set(api.STEPS[1:])

    def perform(self, context):
        return api.apply_recipe(context.scene.pms.recipe, force=self.force)


def _set_playback(context, play):
    """Start / stop the viewport playback (needs a window: it crashes Blender in background mode)."""
    scr = context.screen
    if bpy.app.background or scr is None or scr.is_animation_playing == play:
        return
    bpy.ops.screen.animation_play()


def _stop_playback(context):
    _set_playback(context, False)


class PMS_OT_preview_motion(_PMSOperator):
    bl_idname, bl_label = "pms.preview_motion", "Preview Motion"
    bl_description = ("Try the preset chosen in the list on the studio and play it. Click again (or press Esc) to go back to what "
                      "was built; press Apply to keep it")
    section: bpy.props.StringProperty()

    def steps(self, context):
        return set() if api._PREVIEW else api.steps_for(self.section, context.scene)

    def perform(self, context):
        if api._PREVIEW:                                                # second click: stop and put everything back
            _stop_playback(context)
            return api.preview_stop() or {'warnings': []}
        out = api.preview_start(self.section, None, self.force)
        if out.get('preview'):
            context.scene.frame_set(context.scene.frame_start)
            _set_playback(context, True)
            if not bpy.app.background:                                  # (no window in background mode: applied, not playing)
                bpy.ops.pms.preview_watch('INVOKE_DEFAULT')            # Esc stops it too
        return out


class PMS_OT_preview_apply(bpy.types.Operator):
    bl_idname, bl_label = "pms.preview_apply", "Apply"
    bl_description = "Keep the previewed preset and stop playing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(api._PREVIEW)

    def execute(self, context):
        _stop_playback(context)
        api.preview_stop(keep=True)
        return {'FINISHED'}


class PMS_OT_preview_watch(bpy.types.Operator):
    """Modal helper of Preview Motion: Esc ends the preview (and puts the studio back)."""
    bl_idname, bl_label = "pms.preview_watch", "Preview Motion Watch"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not api._PREVIEW:                                            # ended by the button
            return {'FINISHED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            _stop_playback(context)
            try:
                api.preview_stop()
            except Exception:                                           # noqa: BLE001
                traceback.print_exc()
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class PMS_OT_render(bpy.types.Operator):
    bl_idname, bl_label = "pms.render", "Render"
    bl_description = "Put the Render panel's settings in the scene and start Blender's render"
    bl_options = {'REGISTER', 'UNDO'}
    mode: bpy.props.EnumProperty(items=[('still', "Still", ""), ('animation', "Animation", "")], default='still')

    def execute(self, context):
        try:
            out = render_settings.apply(context.scene, self.mode)
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            self.report({'ERROR'}, _msg(e))
            return {'CANCELLED'}
        for w in out['warnings']:
            self.report({'WARNING'}, w)
        if self.mode == 'still':
            bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
        else:
            bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        return {'FINISHED'}


class PMS_OT_remove_all(bpy.types.Operator):
    bl_idname, bl_label = "pms.remove_all", "Remove All"
    bl_description = "Delete everything PMS created and restore the product and scene settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            api.remove_all(context.scene)
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            self.report({'ERROR'}, _msg(e))
            return {'CANCELLED'}
        return {'FINISHED'}


_PACK = {'rendering': False, 'cancelled': False}


def _pack_done(*args):
    _PACK['rendering'] = False


def _pack_cancel(*args):
    _PACK['rendering'] = False
    _PACK['cancelled'] = True


class PMS_OT_render_pack(bpy.types.Operator):
    bl_idname, bl_label = "pms.render_pack", "Render Pack"
    bl_description = ("Render the same studio several times in one go; everything is put back at the end. "
                      "Esc stops after the current render")
    bl_options = {'REGISTER', 'UNDO'}
    force: bpy.props.BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})      # set by invoke after the user confirms

    def _make(self, context):
        pms = context.scene.pms
        return batch.Pack(context.scene, pms.pack_kind.lower(),
                          'still' if pms.pack_mode == 'STILL' else 'animation',
                          variants=pms.pack_variants, force=self.force)

    def invoke(self, context, event):
        kind = context.scene.pms.pack_kind.lower()
        mods = api.modified_steps(batch.GUARD[kind], context.scene)
        if mods:
            self.force = True
            return context.window_manager.invoke_confirm(
                self, event, title="Edited by hand",
                message=api.modified_text(batch.GUARD[kind], context.scene),
                confirm_text="Overwrite", icon='ERROR')
        return self.execute(context)

    def execute(self, context):
        self.pack = None
        try:
            self.pack = self._make(context)
            self.pack.begin()
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            if self.pack is not None:
                self.pack.end()                                         # what begin() already changed goes back
            self.report({'ERROR'}, _msg(e))
            return {'CANCELLED'}
        self.i = 0
        self.stop = False
        _PACK.update(rendering=False, cancelled=False)
        bpy.app.handlers.render_complete.append(_pack_done)
        bpy.app.handlers.render_cancel.append(_pack_cancel)
        self.timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            self.stop = True
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if _PACK['rendering'] or bpy.app.is_job_running('RENDER'):     # (the handlers alone can say "done" too early)
            return {'PASS_THROUGH'}
        if _PACK['cancelled'] or self.stop or self.i >= len(self.pack.items):
            return self._finish(context)
        try:
            self.pack.setup(self.i)
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            self.report({'ERROR'}, _msg(e))
            self.stop = True
            return {'PASS_THROUGH'}
        self.i += 1
        _PACK['rendering'] = True
        if self.pack.mode == 'still':                                   # (not the panel: it may change meanwhile)
            res = bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
        else:
            res = bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        if 'CANCELLED' in res:
            _PACK['rendering'] = False
            self.stop = True
        return {'PASS_THROUGH'}

    def _finish(self, context):
        try:
            if self.timer in context.window_manager.event_timers:
                context.window_manager.event_timer_remove(self.timer)
        except Exception:
            pass
        try:
            if _pack_done in bpy.app.handlers.render_complete:
                bpy.app.handlers.render_complete.remove(_pack_done)
        except Exception:
            pass
        try:
            if _pack_cancel in bpy.app.handlers.render_cancel:
                bpy.app.handlers.render_cancel.remove(_pack_cancel)
        except Exception:
            pass
        warns = self.pack.end()
        for w in warns:
            self.report({'WARNING'}, w)
        done = self.i - (1 if _PACK['cancelled'] else 0)
        self.report({'INFO'}, f"Render pack: {done} of {len(self.pack.items)} rendered in "
                              f"{bpy.path.abspath(self.pack.base)}")
        return {'FINISHED'}


_TITLES = {'camera_shot': "Camera", 'product_motion': "Product Motion", 'lighting': "Lighting", 'background': "Background",
           'background_light': "Background Light", 'floor': "Floor", 'format': "Format", 'look': "Look"}


# === personal presets and scenes (user_presets.py) ============================

class _UserOperator(bpy.types.Operator):
    """Base of the personal-preset buttons: errors go to the info bar (never a traceback in the UI)."""
    bl_options = {'REGISTER', 'UNDO'}

    def run(self, context):
        raise NotImplementedError

    def execute(self, context):
        try:
            msg = self.run(context)
        except Exception as e:                                          # noqa: BLE001
            traceback.print_exc()
            self.report({'ERROR'}, _msg(e))
            return {'CANCELLED'}
        if msg:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


def _name_dialog(op, context, event, title, confirm):
    return context.window_manager.invoke_props_dialog(op, width=320, title=title, confirm_text=confirm)


class PMS_OT_save_preset(_UserOperator):
    bl_idname, bl_label = "pms.save_preset", "Save as My Preset"
    bl_description = "Save this section as it is now (your edits and live values included) as a personal preset"
    section: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    name: bpy.props.StringProperty(name="Name", default="My Preset", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.section in ('product_motion', 'camera_motion'):
            return ("Save the chosen preset and its options as a personal preset. Curves you edited by hand are NOT saved: "
                    "only the preset and its options")
        return ("Save this section as it is now (objects moved by hand, colours, power, lens, live values) as a personal "
                "preset relative to the product size: it works on products of any size")

    def invoke(self, context, event):
        self.name = f"My {_TITLES.get(self.section, 'Preset')}"
        return _name_dialog(self, context, event, "Save as My Preset", "Save")

    def draw(self, context):
        self.layout.prop(self, "name")
        if self.section in ('product_motion', 'camera_motion'):
            self.layout.label(text="Saves the preset and its options (curves edited by hand are not kept)", icon='INFO')

    def run(self, context):
        out = api.save_preset(self.section, self.name)
        return f"Saved '{out['name']}' in My Presets"


class _OnPreset(_UserOperator):
    """A button about the personal preset chosen in a section (or the scene chosen in My Scenes)."""
    section: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def target(self, context):
        pms = context.scene.pms
        if self.section == 'scene':
            if pms.user_scene in ('', 'NONE'):
                raise ValueError("Choose a personal scene first")
            return 'scene', pms.user_scene, None
        return 'preset', getattr(pms, self.section), self.section


class PMS_OT_update_user(_OnPreset):
    bl_idname, bl_label = "pms.update_user", "Update"
    bl_description = "Overwrite this personal preset (or scene) with the studio as it is now"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Update", message="Overwrite it with the current state?",
                                                     confirm_text="Update", icon='QUESTION')

    def run(self, context):
        kind, ident, section = self.target(context)
        api.update_user(kind, ident, section)
        return "Updated"


class PMS_OT_rename_user(_OnPreset):
    bl_idname, bl_label = "pms.rename_user", "Rename"
    bl_description = "Rename this personal preset (or scene)"
    name: bpy.props.StringProperty(name="Name", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        kind, ident, section = self.target(context)
        self.name = user_presets.get_scene(ident)['name'] if kind == 'scene' else presets.get(section, ident).name
        return _name_dialog(self, context, event, "Rename", "Rename")

    def run(self, context):
        kind, ident, section = self.target(context)
        return f"Renamed to '{api.rename_user(kind, ident, self.name, section)['name']}'"


class PMS_OT_delete_user(_OnPreset):
    bl_idname, bl_label = "pms.delete_user", "Delete"
    bl_description = "Delete this personal preset (or scene) from your folder"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Delete", message="Delete it for good?",
                                                     confirm_text="Delete", icon='ERROR')

    def run(self, context):
        kind, ident, section = self.target(context)
        api.delete_user(kind, ident, section)
        return "Deleted"


class PMS_OT_save_scene(_UserOperator):
    bl_idname, bl_label = "pms.save_scene", "Save Scene"
    bl_description = ("Save the whole studio as it is now (every section with your edits, format, frames, fps, engine, render "
                      "settings) as a personal scene you can apply in one click")
    name: bpy.props.StringProperty(name="Name", default="My Scene", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return _name_dialog(self, context, event, "Save Scene", "Save")

    def run(self, context):
        return f"Saved scene '{api.save_scene(self.name)['name']}'"


class PMS_OT_apply_scene(_PMSOperator):
    bl_idname, bl_label = "pms.apply_scene", "Apply Scene"
    bl_description = "Rebuild the whole studio on the current product from the chosen personal scene"

    def steps(self, context):
        return set(api.STEPS[1:])

    def perform(self, context):
        sid = context.scene.pms.user_scene
        if sid in ('', 'NONE'):
            raise ValueError("Choose a personal scene first")
        return api.apply_scene(sid, force=self.force)


class PMS_OT_reload_user(_UserOperator):
    bl_idname, bl_label = "pms.reload_user", "Reload"
    bl_description = "Read your personal presets and scenes from the folder again"

    def run(self, context):
        out = api.reload_user()
        for w in out['warnings']:
            self.report({'WARNING'}, w)
        return f"{len(out['presets'])} presets, {len(out['scenes'])} scenes"


class PMS_OT_export_user(_UserOperator):
    bl_idname, bl_label = "pms.export_user", "Export..."
    bl_description = "Save your personal presets and scenes (with their thumbnails) in one file to share"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})
    ids: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})      # empty = everything; else "section/id" or "scene/id"

    @classmethod
    def description(cls, context, properties):
        return ("Export this personal preset to a file to share" if properties.ids else
                "Export all your personal presets and scenes (with thumbnails) to one file to share")

    def invoke(self, context, event):
        self.filepath = "pms_presets.json"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def run(self, context):
        out = api.export_user(bpy.path.abspath(self.filepath), [i for i in self.ids.split(',') if i] or None)
        return f"Exported {out['presets']} presets and {out['scenes']} scenes"


class PMS_OT_import_user(_UserOperator):
    bl_idname, bl_label = "pms.import_user", "Import..."
    bl_description = "Add the personal presets and scenes of a file somebody shared with you (ids already in use are renamed)"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def run(self, context):
        out = api.import_user(bpy.path.abspath(self.filepath))
        for text in out['errors']:
            self.report({'ERROR'}, text)
        return f"Imported {len(out['presets'])} presets and {len(out['scenes'])} scenes" + (
            f" ({len(out['renamed'])} renamed)" if out['renamed'] else "")


def _user_row(lay, pms, section):
    """"Save as My Preset" under the picker of a section; when the chosen preset is a personal one also Rename / Update / Delete."""
    lay.operator("pms.save_preset", icon='ADD').section = section
    p = presets.REGISTRY[section].get(getattr(pms, section))
    if p is not None and p.meta.get('user') and not p.meta.get('hidden'):
        row = lay.row(align=True)
        for idname, text in (("pms.rename_user", "Rename"), ("pms.update_user", "Update"), ("pms.delete_user", "Delete")):
            row.operator(idname, text=text).section = section
        row.operator("pms.export_user", text="", icon='EXPORT').ids = f"{section}/{p.id}"


def _draw_scenes(lay, context):
    pms = context.scene.pms
    box = lay.box()
    box.label(text="My Scenes")
    box.operator("pms.save_scene", icon='ADD')
    if user_presets.scenes():
        box.template_icon_view(pms, "user_scene", show_labels=True, scale=6, scale_popup=5)
        box.prop(pms, "user_scene", text="")
        box.operator("pms.apply_scene", icon='CHECKMARK')
        row = box.row(align=True)
        for idname, text in (("pms.rename_user", "Rename"), ("pms.update_user", "Update"), ("pms.delete_user", "Delete")):
            row.operator(idname, text=text).section = 'scene'
        row.operator("pms.export_user", text="", icon='EXPORT').ids = f"scene/{pms.user_scene}"
    else:
        box.label(text="Nothing saved yet")
    row = box.row(align=True)
    row.operator("pms.reload_user", icon='FILE_REFRESH')
    row.operator("pms.export_user", text="Export...", icon='EXPORT')
    row.operator("pms.import_user", icon='IMPORT')


def _wrap_chars(context):
    """Characters per line that fit in the sidebar (the yellow warning is a plain label: Blender does not wrap them)."""
    region = context.region
    prefs = context.preferences
    unit = max(prefs.system.pixel_size * prefs.view.ui_scale, 0.1)
    return max(20, int((region.width / unit - 60) / 6.2)) if region is not None and region.width > 1 else 34


class PMS_PT_main(bpy.types.Panel):
    bl_idname, bl_label = "PMS_PT_main", "Product Motion Studio"
    bl_space_type, bl_region_type, bl_category = 'VIEW_3D', 'UI', "PMS"

    def draw(self, context):
        pms = context.scene.pms
        box = self.layout.box()
        box.label(text="Recipe")
        _presets(box, pms, 'recipe')
        box.operator("pms.apply_recipe", text="Apply Recipe", icon='CHECKMARK')
        if pms.locks:
            kept_titles = [s.replace('_', ' ').title() for s in sorted(pms.locks)]
            box.label(text="Kept: " + ", ".join(kept_titles), icon='LOCKED')
        _draw_scenes(self.layout, context)
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.operator("pms.build_all", icon='PLAY')
        row.operator("pms.remove_all", icon='TRASH')
        for i, line in enumerate(textwrap.wrap(pms.coverage, _wrap_chars(context))):          # yellow triangle: the backdrop shows the void
            col.label(text=line, icon='ERROR' if i == 0 else 'BLANK1')
        col.prop(pms, "engine")
        row = col.row(align=True)
        row.prop(pms, "duration", text="Frames")
        row.prop(pms, "fps")


def _build_button(layout, section, text=None):
    layout.operator("pms.build_section", text=text or f"Build {_TITLES.get(section, 'Section')}").section = section


def _draw_1(self, context):
    pms, lay = context.scene.pms, self.layout
    root = bpy.data.objects.get(core.ROOT_NAME)
    lay.prop(pms, "ground")
    if root is not None:
        size = root.get('pms_size')
        lay.label(text=f"Product: {len(root.children)} object(s)" + (f", size {size:.3g}" if size is not None else ""))
    else:
        lay.label(text=f"Selected: {len(context.selected_objects)} object(s)")
    _build_button(lay, 'prepare', "Prepare")
    if root is not None:
        lay.operator("pms.add_objects", icon='ADD')


def _presets(lay, pms, section, text="", ptype=False):
    """Category filter (+ product type for lighting), the thumbnail picker and the list of one section."""
    if section in props.PLAIN:
        lay.template_icon_view(pms, section, show_labels=True, scale=6, scale_popup=5)
        row = lay.row(align=True)
        row.prop(pms, section, text=text)
        if section in props.LOCKABLE:
            row.prop_enum(pms, 'locks', section, text="", icon='LOCKED' if section in pms.locks else 'UNLOCKED')
        _hand_note(lay, pms, section)
        return
    col = lay.column(align=True)
    row = col.row(align=True)
    row.prop(pms, section + '_cat', text="Category")
    if section in props.LOCKABLE:
        row.prop_enum(pms, 'locks', section, text="", icon='LOCKED' if section in pms.locks else 'UNLOCKED')
    if ptype:
        col.prop(pms, 'lighting_ptype', text="Type")
    if section in props.FILTERED:
        col.prop(pms, section + '_find', text="", icon='VIEWZOOM')
    lay.template_icon_view(pms, section, show_labels=True, scale=6, scale_popup=5)
    lay.prop(pms, section, text=text)
    _hand_note(lay, pms, section)


def _hand_note(lay, pms, section):
    """The list shows a preset the scene does not have: the section was edited by hand and the last build kept it."""
    built = api._loads(pms.built).get(section)
    step = next((s for s, secs in api.BUILT.items() if section in secs), None)
    if built and built != getattr(pms, section) and step in core.SIGNED and core.modified(pms.id_data, step):
        p = presets.REGISTRY[section].get(built)
        lay.label(text=f"In the scene: {p.name if p else built} (edited by hand)", icon='ERROR')


def _live_box(lay, scene, section):
    """Box for the live controls of a section: greyed out until the section is built."""
    box = lay.box()
    built = live.is_built(scene, section)
    box.label(text="Live controls" if built else "Live controls (build this section first)")
    col = box.column(align=True)
    col.use_property_split, col.use_property_decorate = True, False
    col.enabled = built
    return col


def _preview_row(lay, pms, section):
    """Preview Motion for the preset chosen in the list: the button turns into Stop while it plays; Apply keeps it."""
    mine = api._PREVIEW.get('section') == section
    row = lay.row(align=True)
    row.enabled = core.has_product()
    op = row.operator("pms.preview_motion", text="Stop Preview" if mine else "Preview Motion", icon='PAUSE' if mine else 'PLAY')
    op.section = section
    if mine:
        row.operator("pms.preview_apply", text="Apply", icon='CHECKMARK')


def _live_camera(lay, context):
    pms = context.scene.pms
    col = _live_box(lay, context.scene, 'camera_shot')
    col.prop(pms, "cam_lens")
    col.prop(pms, "cam_padding")
    col.prop(pms, "cam_dof", toggle=True)
    sub = col.column(align=True)
    sub.active = pms.cam_dof
    sub.prop(pms, "cam_fstop")
    sub.prop(pms, "cam_focus")
    sub.prop(pms, "cam_autofocus")


def _draw_2(self, context):
    pms, lay = context.scene.pms, self.layout
    lay.label(text="Shot")
    _presets(lay, pms, 'camera_shot')
    _user_row(lay, pms, 'camera_shot')
    _live_camera(lay, context)
    lay.label(text="Motion")
    _presets(lay, pms, 'camera_motion')
    _user_row(lay, pms, 'camera_motion')
    _preview_row(lay, pms, 'camera_motion')
    _build_button(lay, 'camera_shot')


def _live_lighting(lay, context):
    pms = context.scene.pms
    col = _live_box(lay, context.scene, 'lighting')
    col.prop(pms, "light_power")
    col.prop(pms, "light_tint")
    col.prop(pms, "light_rot")
    col.prop(pms, "light_fill")
    col.prop(pms, "light_rim")
    col.prop(pms, "light_temp")


def _live_background(lay, context):
    pms, scene = context.scene.pms, context.scene
    col = _live_box(lay, scene, 'background')
    data = core.preset(scene, 'background')[1]
    if data.get('kind') != 'image' or not pms.bg_image:                  # a picture has no gradient colours
        col.prop(pms, "bg_type")
        col.prop(pms, "bg_color_a")
        if live._mid_index(live._stops(data)):
            col.prop(pms, "bg_color_mid")
        col.prop(pms, "bg_color_b")
        if pms.bg_type == 'LINEAR':
            col.prop(pms, "bg_rotation")
    col.prop(pms, "bg_roughness")
    col.prop(pms, "bg_selflight")
    col.prop(pms, "bg_distance")
    col.prop(pms, "bg_cove")


def _live_bg_light(lay, context):
    pms = context.scene.pms
    col = _live_box(lay, context.scene, 'background_light')
    col.prop(pms, "bgl_color")
    col.prop(pms, "bgl_power")


def _live_floor(lay, context):
    pms, scene = context.scene.pms, context.scene
    col = _live_box(lay, scene, 'floor')
    if core.preset(scene, 'floor')[1].get('kind') == 'plane':
        col.prop(pms, "floor_color")
        col.prop(pms, "floor_roughness")
    else:
        col.label(text="Uses the background colours")


def _live_look(lay, context):
    pms = context.scene.pms
    col = _live_box(lay, context.scene, 'look')
    col.prop(pms, "look_intensity")
    col.prop(pms, "look_exposure")


def _draw_simple(prop, section, extra=(), live_fn=None, preview=False):
    def draw(self, context):
        pms = context.scene.pms
        if prop in previews.SECTIONS:
            _presets(self.layout, pms, prop, ptype=prop == 'lighting')
        else:
            row = self.layout.row(align=True)
            row.prop(pms, prop, text="")
            if prop in props.LOCKABLE:
                row.prop_enum(pms, 'locks', prop, text="", icon='LOCKED' if prop in pms.locks else 'UNLOCKED')
        _user_row(self.layout, pms, section)
        for e in extra:
            if e == 'motion_intro_s' and pms.motion_loop == 'NONE':
                continue
            if e == 'bg_image':
                col = self.layout.column()
                col.use_property_split, col.use_property_decorate = True, False
                col.prop(pms, e, text="Image File")
            else:
                self.layout.prop(pms, e)
        if live_fn is not None:
            live_fn(self.layout, context)
        if preview:
            _preview_row(self.layout, pms, section)
        _build_button(self.layout, section)
    return draw


def _draw_render(self, context):
    pms, lay = context.scene.pms, self.layout
    lay.row(align=True).prop(pms, "render_quality", expand=True)
    if pms.render_quality == 'CUSTOM':
        col = lay.column(align=True)
        col.use_property_split, col.use_property_decorate = True, False
        col.prop(pms, "render_custom_engine")
        col.prop(pms, "render_samples")
        col.prop(pms, "render_percent")
        r = context.scene.render
        col.label(text=f"{r.resolution_x * pms.render_percent // 100} x {r.resolution_y * pms.render_percent // 100} px")
    col = lay.column(align=True)
    col.use_property_split, col.use_property_decorate = True, False
    col.prop(pms, "render_motion_blur")
    sub = col.row()
    sub.active = not pms.render_passes                       # the passes always go to a multilayer EXR
    sub.prop(pms, "render_format")
    col.prop(pms, "render_passes")
    if pms.render_passes:
        col.label(text="Output: multilayer EXR (passes + graded image)", icon='INFO')
    col.prop(pms, "render_path")
    col = lay.column(align=True)
    col.operator("pms.render", text="Render Still", icon='RENDER_STILL').mode = 'still'
    col.operator("pms.render", text="Render Animation", icon='RENDER_ANIMATION').mode = 'animation'

    # Render Pack
    box = lay.box()
    box.label(text="Render Pack", icon='RENDER_RESULT')
    box.row(align=True).prop(pms, "pack_kind", expand=True)
    if pms.pack_kind == 'VARIANTS':
        box.prop(pms, "pack_variants")
    box.row(align=True).prop(pms, "pack_mode", expand=True)
    if pms.pack_kind == 'ANGLES':
        box.label(text="Front, Hero 3/4, Side, Rear 3/4, Top Down")
    elif pms.pack_kind == 'FORMATS':
        box.label(text="16:9, 1:1, 9:16")
    else:
        n = len(batch.variant_roots(pms.pack_variants)) if pms.pack_variants else 0
        box.label(text=f"{n} objects")
    box.operator("pms.render_pack", icon='RENDER_STILL')


_SUBS = [("1. Prepare", _draw_1),
         ("2. Camera", _draw_2),
         ("3. Product Motion", _draw_simple('product_motion', 'product_motion', ('motion_loop', 'motion_intro_s'),
                                            preview=True)),
         ("4. Lighting", _draw_simple('lighting', 'lighting', ('animate_lighting', 'isolate_lights'), _live_lighting)),
         ("5. Background", _draw_simple('background', 'background', ('bg_image',), _live_background)),
         ("6. Background Light", _draw_simple('background_light', 'background_light', (), _live_bg_light)),
         ("7. Floor", _draw_simple('floor', 'floor', (), _live_floor)),
         ("8. Format", _draw_simple('format', 'format')),
         ("9. Look", _draw_simple('look', 'look', (), _live_look)),
         ("10. Render", _draw_render)]

_classes = [PMS_OT_build_all, PMS_OT_build_section, PMS_OT_add_objects, PMS_OT_apply_recipe, PMS_OT_preview_motion,
            PMS_OT_preview_apply, PMS_OT_preview_watch, PMS_OT_render, PMS_OT_remove_all,
            PMS_OT_render_pack, PMS_OT_save_preset, PMS_OT_update_user, PMS_OT_rename_user, PMS_OT_delete_user,
            PMS_OT_save_scene, PMS_OT_apply_scene, PMS_OT_reload_user, PMS_OT_export_user, PMS_OT_import_user, PMS_PT_main]
for _i, (_label, _draw) in enumerate(_SUBS, start=1):
    _classes.append(type(f"PMS_PT_sub{_i}", (bpy.types.Panel,), {
        'bl_idname': f"PMS_PT_sub{_i}", 'bl_label': _label, 'bl_space_type': 'VIEW_3D', 'bl_region_type': 'UI',
        'bl_category': "PMS", 'bl_parent_id': "PMS_PT_main", 'bl_options': {'DEFAULT_CLOSED'} if _i > 2 else set(),
        'draw': _draw}))


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
