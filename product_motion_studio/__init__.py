"""Product Motion Studio (PMS): registers properties, operators and the N panel."""

from . import props, previews, ui, user_presets


def register():
    previews.register()
    props.register()
    ui.register()
    user_presets.load_all()                  # personal presets and scenes from the user folder


def unregister():
    user_presets.unload()
    ui.unregister()
    props.unregister()
    previews.unregister()
