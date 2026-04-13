# -*- coding: utf-8 -*-
"""
AI Nodes - Team Tools Package
Internal-only nodes for character/environment department workflows.
Not shipped in commercial builds.
"""

from .nodes_team_char import (
    NeuroCharacterTextureNode,
    NEURO_OT_character_setup_camera,
    NEURO_OT_character_create_duplicate,
    NEURO_OT_character_delete_duplicate,
    NEURO_OT_character_capture,
    NEURO_OT_character_texture_generate,
    NEURO_OT_character_texture_run,
    NEURO_OT_character_texture_cancel,
    NEURO_OT_character_texture_pick,
    NEURO_OT_character_texture_navigate,
    NEURO_OT_character_texture_continue,
)

import bpy

CLASSES = [
    NeuroCharacterTextureNode,
    NEURO_OT_character_setup_camera,
    NEURO_OT_character_create_duplicate,
    NEURO_OT_character_delete_duplicate,
    NEURO_OT_character_capture,
    NEURO_OT_character_texture_generate,
    NEURO_OT_character_texture_run,
    NEURO_OT_character_texture_cancel,
    NEURO_OT_character_texture_pick,
    NEURO_OT_character_texture_navigate,
    NEURO_OT_character_texture_continue,
]


def register():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass