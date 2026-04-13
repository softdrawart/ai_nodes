# -*- coding: utf-8 -*-
"""
Pure Python UI and Operator definitions.
Passes all actual logic to the compiled updater_core.
"""
import bpy
from . import updater_core

check_for_update = updater_core.check_for_update

# Re-export for __init__.py and UI
get_state = updater_core.get_state
_get_addon_version = updater_core._get_addon_version
draw_update_ui = updater_core.draw_update_ui


# =============================================================================
# OPERATORS (Wrappers)
# =============================================================================

class NEURO_OT_check_update(bpy.types.Operator):
    """Check server for new version"""
    bl_idname = "neuro.check_update"
    bl_label = "Check for Updates"

    def execute(self, context):
        return updater_core.op_check_update(self, context)


class NEURO_OT_install_update(bpy.types.Operator):
    """Download and install the update"""
    bl_idname = "neuro.install_update"
    bl_label = "Install Update"

    def execute(self, context):
        return updater_core.op_install_update(self, context)


class NEURO_OT_restore_backup(bpy.types.Operator):
    """Restore the previous version if an update fails"""
    bl_idname = "neuro.restore_backup"
    bl_label = "Restore Backup"

    def execute(self, context):
        return updater_core.op_restore_backup(self, context)


class NEURO_OT_restart_blender(bpy.types.Operator):
    """Save file and restart Blender to apply update"""
    bl_idname = "neuro.restart_blender"
    bl_label = "Restart Blender"

    def execute(self, context):
        return updater_core.op_restart_blender(self, context)


# =============================================================================
# REGISTRATION
# =============================================================================

_classes = [
    NEURO_OT_check_update,
    NEURO_OT_install_update,
    NEURO_OT_restore_backup,
    NEURO_OT_restart_blender,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    # Start the background timer from the core
    updater_core.register_timer()


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

    # Stop the background timer
    updater_core.unregister_timer()