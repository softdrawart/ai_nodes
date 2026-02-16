# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Operators Module (Entry Point)
Thin shell that imports from split operator modules.

Split modules:
- operators_manual.py    : Help/manual popups
- operators_input.py     : Reference images, prompts, presets
- operators_gallery.py   : Gallery management, viewport
- operators_providers.py : Provider switch, API validation, generation control
- operators_gen.py       : Generation operators (image, texture, PBR)
"""

import bpy

# Import split modules
from . import operators_manual
from . import operators_input
from . import operators_gallery
from . import operators_providers

# Re-export generation ID functions (used by operators_gen.py)
from .operators_providers import get_current_gen_id, increment_gen_id


# =============================================================================
# REGISTRATION
# =============================================================================

def register():
    """Register all operator modules"""
    operators_manual.register()
    operators_input.register()
    operators_gallery.register()
    operators_providers.register()


def unregister():
    """Unregister all operator modules in reverse order"""
    operators_providers.unregister()
    operators_gallery.unregister()
    operators_input.unregister()
    operators_manual.unregister()