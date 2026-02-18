# -*- coding: utf-8 -*-
"""Update system package."""
from . import updater

# Re-export for convenience
get_state = updater.get_state
get_addon_version = updater._get_addon_version
draw_update_ui = updater.draw_update_ui


def register():
    updater.register()


def unregister():
    updater.unregister()