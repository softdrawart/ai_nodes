# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Node-Based Generation System (Entry Point)
"""
import bpy
import nodeitems_utils

from . import nodes_core
from .nodes_items import text
from .nodes_items import gen_ref
from .nodes_items import tools_artist
from .nodes_items import tools_special
from .nodes_items import tools_util
from . import nodes_ops
from . import nodes_utils_ops
from . import nodes_text_ops
from . import nodes_tools_ops
from . import nodes_ui
from . import nodes_3d
from . import nodes_geo
from .nodes_core import stop_background_timer, start_image_sync_timer, stop_image_sync_timer

# Status manager (optional - graceful fallback if missing)
try:
    from . import status_manager

    HAS_STATUS_MANAGER = True
except ImportError:
    HAS_STATUS_MANAGER = False

# List of classes to register from submodules
CLASSES = [
    nodes_core.NeuroGenNodeTree,
    nodes_core.NeuroImageSocket,
    nodes_core.NeuroTextSocket,
    nodes_core.NeuroHistorySocket,

    # Generation & Reference
    gen_ref.NeuroGenerateNode,
    gen_ref.NeuroReferenceNode,
    gen_ref.NeuroInpaintNode,
    # Text Nodes
    text.NeuroTextNode,
    text.NeuroMergeTextNode,
    text.NeuroUpgradePromptNode,
    text.NeuroTextGenNode,
    # Tools
    tools_artist.NeuroArtistToolsNode,
    tools_special.NeuroRelightNode,
    tools_special.NeuroDesignVariationsNode,
    # Utils
    tools_util.NeuroImageSplitterNode,
    tools_util.NeuroRemoveBackgroundNode,

    # Base Generation Ops (from nodes_ops)
    nodes_ops.NEURO_OT_node_generate,
    nodes_ops.NEURO_OT_node_cancel,
    nodes_ops.NEURO_OT_node_remove_bg,
    # Inpaint operators
    nodes_ops.NEURO_OT_node_create_inpaint,
    nodes_ops.NEURO_OT_node_inpaint_generate,
    nodes_ops.NEURO_OT_node_inpaint_cancel,
    # RemoveBackground node operators
    nodes_ops.NEURO_OT_node_rembg_execute,
    nodes_ops.NEURO_OT_node_rembg_cancel,
    nodes_ops.NEURO_OT_node_rembg_history_nav,

    # Text Ops (from nodes_text_ops)
    nodes_text_ops.NEURO_OT_node_generate_text,
    nodes_text_ops.NEURO_OT_node_cancel_text,
    nodes_text_ops.NEURO_OT_node_upgrade_prompt,
    nodes_text_ops.NEURO_OT_node_copy_prompt,
    nodes_text_ops.NEURO_OT_node_show_prompt,
    nodes_text_ops.NEURO_OT_open_text_editor,
    nodes_text_ops.NEURO_OT_sync_text_to_node,

    # Utility Ops (from nodes_utils_ops)
    nodes_utils_ops.NEURO_OT_refresh_node_preview,
    nodes_utils_ops.NEURO_OT_node_history_nav,
    nodes_utils_ops.NEURO_OT_node_view_full_image,
    nodes_utils_ops.NEURO_OT_node_open_paint,
    nodes_utils_ops.NEURO_OT_node_revert_paint,
    nodes_utils_ops.NEURO_OT_node_toggle_inpaint,
    nodes_utils_ops.NEURO_OT_node_copy_image_file,
    nodes_utils_ops.NEURO_OT_node_load_file,
    nodes_utils_ops.NEURO_OT_node_load_files_multi,
    nodes_utils_ops.NEURO_OT_node_ref_clear,
    nodes_utils_ops.NEURO_OT_node_from_editor,
    nodes_utils_ops.NEURO_OT_node_load_blender_image,
    nodes_utils_ops.NEURO_OT_node_from_render,
    nodes_utils_ops.NEURO_OT_node_from_clipboard,
    nodes_utils_ops.NEURO_OT_duplicate_nodes,
    nodes_utils_ops.NEURO_OT_auto_connect_nodes,
    nodes_utils_ops.NEURO_OT_run_selection,
    nodes_utils_ops.NEURO_OT_node_export,
    nodes_utils_ops.NEURO_OT_node_import,
    nodes_utils_ops.NEURO_OT_node_manual,

    # Artist Tools Ops (from nodes_tools_ops)
    nodes_tools_ops.NEURO_OT_node_artist_describe,
    nodes_tools_ops.NEURO_OT_node_artist_pick_line,
    nodes_tools_ops.NEURO_OT_node_artist_copy_line,
    nodes_tools_ops.NEURO_OT_node_artist_toggle_element,
    nodes_tools_ops.NEURO_OT_node_artist_clear_selection,
    nodes_tools_ops.NEURO_OT_node_artist_copy_selected,
    nodes_tools_ops.NEURO_OT_node_artist_elements_action,
    nodes_tools_ops.NEURO_OT_node_artist_upscale,
    nodes_tools_ops.NEURO_OT_node_artist_angle,
    nodes_tools_ops.NEURO_OT_node_artist_separation,
    nodes_tools_ops.NEURO_OT_node_artist_decompose,
    nodes_tools_ops.NEURO_OT_node_artist_flip,
    nodes_tools_ops.NEURO_OT_node_artist_cancel,
    nodes_tools_ops.NEURO_OT_node_artist_multiview,
    nodes_tools_ops.NEURO_OT_node_artist_history_nav,
    # Image Splitter operators
    nodes_tools_ops.NEURO_OT_node_split_image,
    # Design Variations operators
    nodes_tools_ops.NEURO_OT_node_design_var_simple,
    nodes_tools_ops.NEURO_OT_node_design_var_prompts,
    nodes_tools_ops.NEURO_OT_node_design_var_edit,
    nodes_tools_ops.NEURO_OT_node_design_var_save,
    nodes_tools_ops.NEURO_OT_node_design_var_reset,
    nodes_tools_ops.NEURO_OT_node_design_var_image,
    nodes_tools_ops.NEURO_OT_node_design_var_cancel,
    nodes_tools_ops.NEURO_OT_node_design_var_history_nav,
    # Relight operators
    nodes_tools_ops.NEURO_OT_node_relight_direction,
    nodes_tools_ops.NEURO_OT_node_relight_flip,
    nodes_tools_ops.NEURO_OT_node_relight_generate,
    nodes_tools_ops.NEURO_OT_node_relight_cancel,
    nodes_tools_ops.NEURO_OT_node_relight_history,
    nodes_tools_ops.NEURO_OT_node_relight_load_ref,
    nodes_tools_ops.NEURO_OT_node_relight_select_ref,
    nodes_tools_ops.NEURO_OT_node_relight_clear_refs,

    # Nodes editor UI
    nodes_ui.NEURO_MT_node_add,
    nodes_ui.NEURO_PT_node_defaults,
    nodes_ui.NEURO_PT_node_prompt_builder,
    nodes_ui.NEURO_OT_show_add_menu,
    nodes_ui.NEURO_OT_drop_images,
    nodes_ui.NEURO_OT_relocate_missing_images,
    nodes_ui.NEURO_OT_translate_text,
    nodes_ui.NEURO_OT_copy_translation,
    nodes_ui.NEURO_FH_drop_images,
    nodes_ui.NEURO_OT_paste_reference_node,
    # Geo Node
    nodes_geo.NeuroGeoNodesNode,
    nodes_geo.NEURO_OT_geonodes_generate,
    nodes_geo.NEURO_OT_geonodes_execute,
    nodes_geo.NEURO_OT_geonodes_cancel,
    nodes_geo.NEURO_OT_geonodes_copy_code,

]


def register():
    # 1. Initialize preview collection in core
    try:
        import bpy.utils.previews
        if nodes_core.node_preview_collection is None:
            nodes_core.node_preview_collection = bpy.utils.previews.new()
    except Exception as e:
        print(f"[{LOG_PREFIX}] Node previews init warning: {e}")

    # 2. Register classes
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # Already registered

    # 3. Register 3D nodes
    nodes_3d.register()

    # 4. UI and Keymaps
    bpy.types.NODE_HT_header.append(nodes_ui.draw_neuro_header)
    bpy.types.NODE_MT_add.append(nodes_ui.draw_node_add_menu)

    try:
        nodeitems_utils.register_node_categories('neuro_nodes', nodes_ui.neuro_node_CATEGORIES)
    except Exception:
        pass

    nodes_ui.register_keymaps()

    # 5. Status Manager
    if HAS_STATUS_MANAGER:
        status_manager.register()

    # 6. Start image sync timer for auto-pack support
    start_image_sync_timer()


def unregister():
    stop_background_timer()
    stop_image_sync_timer()

    # Unregister status manager first
    if HAS_STATUS_MANAGER:
        try:
            status_manager.unregister()
        except Exception:
            pass

    nodes_ui.unregister_keymaps()

    try:
        nodeitems_utils.unregister_node_categories('neuro_nodes')
    except Exception:
        pass

    bpy.types.NODE_MT_add.remove(nodes_ui.draw_node_add_menu)
    bpy.types.NODE_HT_header.remove(nodes_ui.draw_neuro_header)

    # Unregister 3D nodes
    nodes_3d.unregister()

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # Clean up preview collection
    if nodes_core.node_preview_collection is not None:
        try:
            bpy.utils.previews.remove(nodes_core.node_preview_collection)
        except Exception:
            pass
        nodes_core.node_preview_collection = None

    # Clean up timer
    stop_background_timer()
    stop_image_sync_timer()