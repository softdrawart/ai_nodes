# -*- coding: utf-8 -*-
"""
Main initialization and registration module.
"""

bl_info = {
    "name": "Blender AI Nodes",
    "author": "Vlad Stoliarenko",
    "version": (1, 9, 3),
    "blender": (4, 5, 0),
    "location": "Image Editor > Sidebar > AI | Node Editor: AI Nodes",
    "description": "AI Nodes (Text/2D/GeoNodes/3D) and Texture projections",
    "warning": "Requires Blender 4.5+ | Internal use only",
    "category": "Image",
}

# =============================================================================
# APPLY PENDING .PYD UPDATES (must run BEFORE any .pyd imports)
# =============================================================================

import os as _os

def _apply_pending_updates():
    """Replace .pyd/.so files that couldn't be overwritten during last update."""
    addon_dir = _os.path.dirname(_os.path.abspath(__file__))
    applied = 0
    for root, dirs, files in _os.walk(addon_dir):
        for f in files:
            if f.endswith('.pending'):
                pending = _os.path.join(root, f)
                target = pending[:-8]  # strip ".pending"
                try:
                    if _os.path.exists(target):
                        _os.remove(target)
                    _os.rename(pending, target)
                    applied += 1
                except Exception as e:
                    print(f"[AINODES] Failed to apply pending update for {f}: {e}")
    if applied:
        print(f"[AINODES] Applied {applied} pending file update(s)")
    # Also clean up leftover .pyd.old files from previous updates
    for root, dirs, files in _os.walk(addon_dir):
        for f in files:
            if f.endswith(('.pyd.old', '.so.old')):
                try:
                    _os.remove(_os.path.join(root, f))
                except Exception:
                    pass

_apply_pending_updates()

# =============================================================================
# IMPORTS
# =============================================================================

import time as _time

import bpy
from bpy.app.handlers import persistent
from .constants import LOG_PREFIX, ADDON_NAME_CONFIG

if bpy.app.version < (4, 5, 0):
    raise Exception(
        f"{ADDON_NAME_CONFIG} requires Blender 4.5 or newer. "
        f"You have {bpy.app.version_string}. Please update Blender."
    )

from . import dependencies
from . import utils
from . import api
from . import properties
from . import operators
from . import operators_gen
from . import ui
from . import nodes
from . import update


@persistent
def _load_handler(dummy):
    """Handle file load — refresh previews, re-check API keys, restore token."""
    bpy.app.timers.register(utils.trigger_preview_refresh, first_interval=0.5)
    bpy.app.timers.register(_restore_neurotoken_on_load, first_interval=2.0)


def _restore_neurotoken_on_load():
    """Restore token state after scene load (runs in background thread)."""
    import threading

    def _worker():
        try:
            from .token_utils import restore_neurotoken_state
            restored = restore_neurotoken_state()
            if restored:
                print(f"[{LOG_PREFIX}] Token state restored")
        except Exception as e:
            print(f"[{LOG_PREFIX}] Token restore error: {e}")

    threading.Thread(target=_worker, daemon=True).start()
    return None  # Don't repeat timer


# =============================================================================
# REGISTRATION
# =============================================================================

def register():
    """Register all addon components."""

    # 1. Dependencies
    dependencies.ensure_libs_path()
    deps_installed, fal_available, modules = dependencies.check_dependencies()

    dependencies.DEPENDENCIES_INSTALLED = deps_installed
    dependencies.FAL_AVAILABLE = fal_available
    dependencies.REPLICATE_AVAILABLE = modules.get('replicate') is not None

    # 2. API modules
    if deps_installed:
        api.init_api_modules(
            modules.get('Image'),
            modules.get('Client'),
            modules.get('types'),
            modules.get('fal_client'),
            modules.get('replicate'),
        )

    # 3. Preview collection
    utils.init_preview_collection()

    # 4. Register all classes (order matters)
    dependencies.register()
    properties.register()
    operators.register()
    operators_gen.register()
    ui.register()
    nodes.register()
    update.register()
    # texture_scan.register()

    # 5. Delayed session init (background thread, no UI freeze)
    def _delayed_init():
        import threading

        license_key = ""
        try:
            prefs = bpy.context.preferences.addons.get(__package__)
            if prefs:
                license_key = getattr(prefs.preferences, 'license_key', '')
        except Exception:
            pass

        def _worker():
            try:
                from .config import init_session, is_internal
                if is_internal():
                    init_session()
                elif license_key:
                    init_session(license_key)
            except Exception as e:
                print(f"[{LOG_PREFIX}] Session init error: {e}")

        threading.Thread(target=_worker, daemon=True).start()
        return None

    bpy.app.timers.register(_delayed_init, first_interval=1.0)

    # 6. Model registry log
    try:
        from . import model_registry
        from .utils import log_verbose
        registry = model_registry.get_registry()
        models = registry.get_all()
        print(f"[{LOG_PREFIX}] Model Registry: {len(models)} models registered")
    except Exception as e:
        print(f"[{LOG_PREFIX}] Model Registry load warning: {e}")

    # 7. Handlers and timers
    if _load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_handler)

    bpy.app.timers.register(utils.trigger_preview_refresh, first_interval=1.0)
    bpy.app.timers.register(utils.cleanup_orphaned_temps, first_interval=1.0)
    bpy.app.timers.register(utils.reset_ui_states, first_interval=0.5)
    bpy.app.timers.register(utils.load_bundled_node_groups, first_interval=6.0)

    # 8. Cleanup handler
    utils.register_cleanup()

    ver = ".".join(map(str, bl_info["version"]))
    replicate_ok = dependencies.REPLICATE_AVAILABLE
    print(f"[{LOG_PREFIX}] {ADDON_NAME_CONFIG} v{ver} registered")
    print(
        f"[{LOG_PREFIX}] Dependencies: {'OK' if deps_installed else 'MISSING'}, "
        f"Google: {'OK' if deps_installed else 'N/A'}, "
        f"Fal: {'OK' if fal_available else 'N/A'}, "
        f"Replicate: {'OK' if replicate_ok else 'N/A'}"
    )


def unregister():
    """Unregister all addon components."""

    utils.cleanup_temp_files()

    if _load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_handler)

    # Reverse order
    update.unregister()
    nodes.unregister()
    ui.unregister()
    operators_gen.unregister()
    operators.unregister()
    properties.unregister()
    dependencies.unregister()
    # texture_scan.unregister()

    utils.cleanup_preview_collection()
    utils.unregister_cleanup()

    try:
        from .config import shutdown
        shutdown()
    except Exception:
        pass

    print(f"[{LOG_PREFIX}] {ADDON_NAME_CONFIG} unregistered")


if __name__ == "__main__":
    register()