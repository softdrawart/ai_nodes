# -*- coding: utf-8 -*-
import os
import json
import bpy
import tempfile
from bpy.types import Menu, Panel, Operator, FileHandler
from bpy.props import StringProperty, CollectionProperty
from nodeitems_utils import NodeCategory, NodeItem


def get_unified_models(self, context):
    """Get unified model list - same model name shared across providers"""
    try:
        from .model_registry import get_registry, ModelCategory
        registry = get_registry()
        models = registry.get_by_category(ModelCategory.IMAGE_GENERATION)
        return [(m.id, m.name, m.description) for m in models]
    except Exception:
        return [("gemini-2.5-flash-image", "Gemini 2.5 Flash", "")]


class NEURO_PT_node_prompt_builder(Panel):
    """Side Panel for Node Prompt Building modifiers"""
    bl_label = "Prompt Builder"
    bl_idname = "NEURO_PT_node_prompt_builder"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = PANELS_NAME
    bl_options = {'INSTANCED'}  # Allows per-node context

    @classmethod
    def poll(cls, context):
        """Safely check if panel should be drawn to prevent crashes"""
        return (context.space_data and
                context.space_data.type == 'NODE_EDITOR' and
                getattr(context.space_data, 'tree_type', '') == 'NeuroGenNodeTree')

    def draw(self, context):
        layout = self.layout

        # Safe access to node tree and active node
        ntree = getattr(context.space_data, 'node_tree', None)
        node = context.active_node

        # If no relevant node is selected, show info message
        if not node or getattr(node, 'bl_idname', '') != 'NeuroGenerateNode':
            layout.label(text="Select a Generate Node", icon='INFO')
            return

        layout.label(text="Style Modifiers", icon='MODIFIER')

        # Verify properties exist before drawing to prevent UI freeze
        if hasattr(node, "mod_isometric"):
            grid = layout.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(node, "mod_isometric", text="Isometric")
            grid.prop(node, "mod_detailed", text="Detailed")
            grid.prop(node, "mod_soft", text="Soft Light")
            grid.prop(node, "mod_clean", text="Clean BG")
            grid.prop(node, "mod_vibrant", text="Vibrant")
            grid.prop(node, "mod_casual", text="Casual")


class NEURO_MT_node_add(Menu):
    bl_idname = "NEURO_MT_node_add"
    bl_label = "Add"

    @classmethod
    def poll(cls, context):
        return (context.space_data and hasattr(context.space_data,
                                               'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree')

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.label(text="Generation")
        layout.operator("node.add_node", text="Generate / Edit", icon='IMAGE_DATA').type = 'NeuroGenerateNode'
        layout.operator("node.add_node", text="Reference Image", icon='IMAGE_REFERENCE').type = 'NeuroReferenceNode'
        layout.separator()
        layout.label(text="Artist Tools")
        layout.operator("node.add_node", text="Artist Tools", icon='TOOL_SETTINGS').type = 'NeuroArtistToolsNode'
        layout.operator("node.add_node", text="Relight", icon='LIGHT_SUN').type = 'NeuroRelightNode'
        layout.operator("node.add_node", text="Design Variations", icon='MOD_ARRAY').type = 'NeuroDesignVariationsNode'
        layout.operator("node.add_node", text="Image Splitter", icon='MOD_EXPLODE').type = 'NeuroImageSplitterNode'
        layout.operator("node.add_node", text="Remove Background", icon='IMAGE_RGB_ALPHA').type = 'NeuroRemoveBackgroundNode'
        layout.separator()
        layout.label(text="Text")
        layout.operator("node.add_node", text="Text Generation", icon='EVENT_T').type = 'NeuroTextGenNode'
        layout.operator("node.add_node", text="Upgrade Prompt", icon='MODIFIER').type = 'NeuroUpgradePromptNode'
        layout.operator("node.add_node", text="Text", icon='TEXT').type = 'NeuroTextNode'
        layout.operator("node.add_node", text="Merge Text", icon='SORTALPHA').type = 'NeuroMergeTextNode'
        layout.separator()
        layout.label(text="3D Generation")
        layout.operator("node.add_node", text="3D Generate (Tripo)", icon='MESH_MONKEY').type = 'TripoGenerateNode'
        layout.operator("node.add_node", text="Smart LowPoly (Tripo)", icon='MOD_DECIM').type = 'TripoSmartLowPolyNode'
        layout.operator("node.add_node", text="AI Geometry Nodes (Beta)",
                        icon='GEOMETRY_NODES').type = 'NeuroGeoNodesNode'
        layout.separator()
        layout.label(text="Layout")
        layout.operator("node.add_node", text="Frame", icon='NONE').type = 'NodeFrame'


class NEURO_PT_node_defaults(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "Providers"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # Get addon preferences
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs:
            layout.label(text="Preferences not found", icon='ERROR')
            return

        # === PROVIDER SWITCH ===
        box = layout.box()
        box.label(text="Active Provider:", icon='WORLD')
        row = box.row(align=True)

        # Provider buttons - order: Fal, AIML, Google, Replicate
        if prefs.provider_fal_enabled:
            op = row.operator("neuro.switch_provider",
                              text="Fal",
                              depress=(prefs.active_provider == 'fal'))
            op.provider = 'fal'
        if prefs.provider_aiml_enabled:
            op = row.operator("neuro.switch_provider",
                              text="AIML",
                              depress=(prefs.active_provider == 'aiml'))
            op.provider = 'aiml'
        if prefs.provider_google_enabled:
            op = row.operator("neuro.switch_provider",
                              text="Google",
                              depress=(prefs.active_provider == 'google'))
            op.provider = 'google'
        if prefs.provider_replicate_enabled:
            op = row.operator("neuro.switch_provider",
                              text="Replicate",
                              depress=(prefs.active_provider == 'replicate'))
            op.provider = 'replicate'

        # Get status indicators
        aiml_status = getattr(scn, 'neuro_aiml_status', False)
        google_status = getattr(scn, 'neuro_google_status', False)
        fal_status = getattr(scn, 'neuro_fal_status', False)
        rep_status = getattr(scn, 'neuro_replicate_status', False)

        # === FAL OPTIONS ===
        if prefs.active_provider == 'fal':
            fal_box = box.box()

            # Text/LLM Source (Fal has no native LLM)
            fal_box.label(text="Text/LLM Source:", icon='TEXT')

            # AIML text option
            row = fal_box.row(align=True)
            row.prop(prefs, "fal_text_from_aiml", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.fal_text_from_aiml
            sub.label(text="AIML Text", icon='CHECKMARK' if aiml_status else 'ERROR')
            if prefs.fal_text_from_aiml and prefs.fal_text_from_replicate:
                sub.label(text="[conflicts]")
                sub.alert = True

            # Replicate text option
            row = fal_box.row(align=True)
            row.prop(prefs, "fal_text_from_replicate", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.fal_text_from_replicate
            sub.label(text="Replicate Text", icon='CHECKMARK' if rep_status else 'ERROR')
            if prefs.fal_text_from_aiml and prefs.fal_text_from_replicate:
                sub.label(text="[conflicts]")
                sub.alert = True

            # Warning if nothing selected
            if not prefs.fal_text_from_aiml and not prefs.fal_text_from_replicate:
                warn_row = fal_box.row()
                warn_row.alert = True
                warn_row.label(text="No text source!", icon='ERROR')

            # Add Models section
            fal_box.separator()
            fal_box.label(text="Add Models:", icon='PLUS')

            # Google models (doesn't conflict)
            row = fal_box.row(align=True)
            row.prop(prefs, "fal_include_google_models", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.fal_include_google_models
            sub.label(text="Google Image/LLMs", icon='CHECKMARK' if google_status else 'ERROR')

        # === AIML OPTIONS ===
        elif prefs.active_provider == 'aiml':
            aiml_box = box.box()
            aiml_box.label(text="Add Models:", icon='PLUS')

            row = aiml_box.row(align=True)
            row.prop(prefs, "aiml_include_google_models", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.aiml_include_google_models
            sub.label(text="Google Image/LLMs", icon='CHECKMARK' if google_status else 'ERROR')

        # === GOOGLE OPTIONS ===
        elif prefs.active_provider == 'google':
            google_box = box.box()
            google_box.label(text="Add Models:", icon='PLUS')

            row = google_box.row(align=True)
            row.prop(prefs, "google_include_fal_models", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.google_include_fal_models
            sub.label(text="Fal.AI Image Models", icon='CHECKMARK' if fal_status else 'ERROR')

        # === REPLICATE OPTIONS ===
        elif prefs.active_provider == 'replicate':
            rep_box = box.box()
            rep_box.label(text="Add Models:", icon='PLUS')

            row = rep_box.row(align=True)
            row.prop(prefs, "replicate_include_google_models", text="")
            sub = row.row(align=True)
            sub.enabled = prefs.replicate_include_google_models
            sub.label(text="Google Image/LLMs", icon='CHECKMARK' if google_status else 'ERROR')


def draw_neuro_header(self, context):
    if (context.space_data and hasattr(context.space_data,
                                       'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree'):
        layout = self.layout
        ntree = context.space_data.node_tree
        scn = context.scene

        layout.popover(panel="NEURO_PT_node_defaults", text="Providers", icon='WORLD')
        layout.separator()

        # AIML balance display
        row = layout.row(align=True)
        if scn.aiml_balance:
            row.label(text=f"AIML: {scn.aiml_balance}", icon='FUND')
        row.operator("aiml.refresh_balance", text="", icon='FILE_REFRESH')

        # Tripo balance display
        row = layout.row(align=True)
        if scn.tripo_balance:
            row.label(text=f"Tripo: {scn.tripo_balance}", icon='MESH_MONKEY')
        row.operator("tripo.refresh_balance", text="", icon='FILE_REFRESH')
        layout.separator()

        layout.operator("neuro.run_selection", text="Selection", icon='PLAY')
        layout.separator()

        # Mini Translator
        row = layout.row(align=True)
        row.prop(scn, "neuro_translate_input", text="")
        row.operator("neuro.translate_text", text="", icon='FILE_TEXT')
        row.operator("neuro.copy_translation", text="", icon='COPYDOWN')

        layout.separator()
        row = layout.row(align=True)
        row.operator("neuro.node_export", text="", icon='EXPORT')
        row.operator("neuro.node_import", text="", icon='IMPORT')
        row.operator("neuro.relocate_missing_images", text="", icon='FILEBROWSER')
        layout.separator()
        layout.operator("neuro.node_manual", text="", icon='QUESTION')


def draw_node_add_menu(self, context):
    if (context.space_data and hasattr(context.space_data,
                                       'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree'):
        layout = self.layout
        layout.separator()
        layout.label(text="AINodes")
        layout.operator("node.add_node", text="Generate / Edit", icon='IMAGE_DATA').type = 'NeuroGenerateNode'


class NeuroNodeCategory(NodeCategory):
    @classmethod
    def poll(cls, context):
        return (context.space_data and hasattr(context.space_data,
                                               'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree')


neuro_node_CATEGORIES = [
    NeuroNodeCategory('NEURO_GENERATION', "Generation", items=[
        NodeItem('NeuroGenerateNode'), NodeItem('NeuroReferenceNode'),
    ]),
    NeuroNodeCategory('NEURO_ARTIST', "Artist Tools", items=[
        NodeItem('NeuroArtistToolsNode'),
        NodeItem('NeuroRelightNode'),
        NodeItem('NeuroDesignVariationsNode'),
        NodeItem('NeuroImageSplitterNode'),
        NodeItem('NeuroRemoveBackgroundNode'),
    ]),
    NeuroNodeCategory('NEURO_TEXT', "Text", items=[
        NodeItem('NeuroTextGenNode'), NodeItem('NeuroUpgradePromptNode'), NodeItem('NeuroTextNode'),
        NodeItem('NeuroMergeTextNode'),
    ]),
    NeuroNodeCategory('NEURO_3D', "3D Generation", items=[
        NodeItem('TripoGenerateNode'),
        NodeItem('TripoSmartLowPolyNode'),
    ]),
    NeuroNodeCategory('NEURO_LAYOUT', "Layout", items=[
        NodeItem('NodeFrame'), NodeItem('NodeReroute'),
    ]),
    NeuroNodeCategory('NEURO_GEO', "Geometry Nodes", items=[NodeItem('NeuroGeoNodesNode'), ]),
]


class NEURO_OT_show_add_menu(Operator):
    bl_idname = "neuro.show_add_menu"
    bl_label = "Add Node"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context): return (context.space_data and hasattr(context.space_data,
                                                                   'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree')

    def execute(self, context):
        bpy.ops.wm.call_menu(name='NEURO_MT_node_add')
        return {'FINISHED'}


class NEURO_OT_paste_reference_node(Operator):
    """Paste image from clipboard as a new Reference Node at cursor"""
    bl_idname = "neuro.paste_reference_node"
    bl_label = "Paste Reference Node"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'NODE_EDITOR' and
                context.space_data and hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree')

    def invoke(self, context, event):
        ntree = context.space_data.node_tree
        if not ntree:
            self.report({'WARNING'}, "No node tree active")
            return {'CANCELLED'}

        # --- Calculate Node Position from Mouse ---
        node_x, node_y = 0, 0

        # When shortcut is pressed with mouse in the node editor WINDOW region,
        # context.region is WINDOW and mouse_region_x/y are already region-local
        if context.region.type == 'WINDOW' and hasattr(context.region, 'view2d'):
            node_x, node_y = context.region.view2d.region_to_view(
                event.mouse_region_x,
                event.mouse_region_y
            )
        else:
            # Fallback: mouse might be in header/sidebar when shortcut pressed
            # Use 2D cursor or view center
            if hasattr(context.space_data, 'cursor_location'):
                node_x, node_y = context.space_data.cursor_location
            else:
                for r in context.area.regions:
                    if r.type == 'WINDOW' and hasattr(r, 'view2d'):
                        node_x, node_y = r.view2d.region_to_view(r.width // 2, r.height // 2)
                        break

        # --- Get Image from Clipboard ---
        try:
            from PIL import ImageGrab
            from .utils import get_generations_folder
            from datetime import datetime

            clipboard_content = ImageGrab.grabclipboard()

            if clipboard_content is None:
                self.report({'WARNING'}, "Clipboard is empty")
                return {'CANCELLED'}

            filepath = None

            # Case A: File path(s) copied from file manager
            if isinstance(clipboard_content, list):
                # Filter for image files
                for item in clipboard_content:
                    if isinstance(item, str) and os.path.isfile(item):
                        ext = os.path.splitext(item)[1].lower()
                        if ext in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tiff', '.tif'}:
                            filepath = item
                            break

            # Case B: PIL Image object (screenshot, browser image, etc.)
            elif hasattr(clipboard_content, 'save'):
                ref_dir = get_generations_folder("references")
                filename = f"clipboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = os.path.join(ref_dir, filename)
                clipboard_content.save(filepath, format='PNG')

            if not filepath or not os.path.exists(filepath):
                self.report({'WARNING'}, "No valid image in clipboard")
                return {'CANCELLED'}

            # --- Create Reference Node ---
            node = ntree.nodes.new('NeuroReferenceNode')
            node.location = (node_x, node_y)
            node.source_type = 'FILE'

            # Set image path
            node.file_path = filepath
            node.image_path = filepath
            if hasattr(node, 'set_image_paths_list'):
                node.set_image_paths_list([filepath])
            node.status_message = "Pasted"

            # Select only this node
            for n in ntree.nodes:
                n.select = False
            node.select = True
            ntree.nodes.active = node

            # Force UI refresh
            context.area.tag_redraw()

            self.report({'INFO'}, f"Pasted reference node")
            return {'FINISHED'}

        except ImportError:
            self.report({'ERROR'}, "Pillow (PIL) library required for clipboard paste")
            return {'CANCELLED'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Paste failed: {str(e)[:50]}")
            return {'CANCELLED'}


# =============================================================================
# DRAG AND DROP SUPPORT
# =============================================================================

# Supported image extensions for drag and drop
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif'}
MAX_DROP_IMAGES = 10


class NEURO_OT_drop_images(Operator):
    """Create Reference node from dropped images"""
    bl_idname = "neuro.drop_images"
    bl_label = "Drop Images"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    # Directory containing the files
    directory: StringProperty(subtype='DIR_PATH')
    # Collection of dropped files
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'NODE_EDITOR' and
                context.space_data and hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree')

    def execute(self, context):
        ntree = context.space_data.node_tree
        if not ntree:
            self.report({'ERROR'}, "No node tree active")
            return {'CANCELLED'}

        # Collect valid image files
        image_paths = []
        for f in self.files:
            filepath = os.path.join(self.directory, f.name)
            ext = os.path.splitext(f.name)[1].lower()
            if ext in IMAGE_EXTENSIONS and os.path.exists(filepath):
                image_paths.append(filepath)
                if len(image_paths) >= MAX_DROP_IMAGES:
                    break

        if not image_paths:
            self.report({'WARNING'}, "No valid image files dropped")
            return {'CANCELLED'}

        # Get drop location using view2d
        region = context.region
        space = context.space_data

        # Default to center if no cursor info
        view_x, view_y = 0, 0

        # Try to use view2d to convert coordinates
        try:
            # Use cursor location from space data if available
            if hasattr(space, 'cursor_location'):
                view_x = space.cursor_location[0]
                view_y = space.cursor_location[1]
            # Alternatively use view2d region_to_view conversion
            elif region and hasattr(region, 'view2d'):
                # Use center of view
                view_x, view_y = region.view2d.region_to_view(
                    region.width // 2, region.height // 2
                )
        except Exception:
            # Fallback to origin
            view_x, view_y = 0, 0

        # Create Reference node
        node = ntree.nodes.new('NeuroReferenceNode')
        node.location = (view_x, view_y)
        node.source_type = 'FILE'

        # Store all paths in the node
        node.set_image_paths_list(image_paths)

        num_images = len(image_paths)
        if num_images > MAX_DROP_IMAGES:
            node.status_message = f"Loaded {MAX_DROP_IMAGES} (limit)"
            self.report({'INFO'}, f"Loaded {MAX_DROP_IMAGES} images (limit reached)")
        else:
            node.status_message = f"Loaded {num_images} image{'s' if num_images > 1 else ''}"
            self.report({'INFO'}, f"Created Reference node with {num_images} image{'s' if num_images > 1 else ''}")

        # Select the new node
        for n in ntree.nodes:
            n.select = False
        node.select = True
        ntree.nodes.active = node

        return {'FINISHED'}


class NEURO_OT_relocate_missing_images(Operator):
    """Relocate missing images for nodes in the current tree"""
    bl_idname = "neuro.relocate_missing_images"
    bl_label = "Relocate Missing Images"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(
        name="Directory",
        description="Search directory for missing images",
        subtype='DIR_PATH'
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        ntree = context.space_data.node_tree if context.space_data else None
        if not ntree:
            self.report({'ERROR'}, "No active node tree")
            return {'CANCELLED'}

        search_dir = self.directory
        if not search_dir or not os.path.isdir(search_dir):
            self.report({'ERROR'}, "Invalid directory")
            return {'CANCELLED'}

        # Build a map of filenames to full paths in the search directory
        file_map = {}
        for root, dirs, files in os.walk(search_dir):
            for filename in files:
                lower_name = filename.lower()
                if lower_name.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif')):
                    if filename not in file_map:
                        file_map[filename] = os.path.join(root, filename)

        relocated_count = 0
        missing_count = 0

        # Check all nodes for missing paths
        for node in ntree.nodes:
            # Check result_path
            if hasattr(node, 'result_path') and node.result_path:
                if not os.path.exists(node.result_path):
                    filename = os.path.basename(node.result_path)
                    if filename in file_map:
                        node.result_path = file_map[filename]
                        relocated_count += 1
                    else:
                        missing_count += 1

            # Check image_path (for Reference nodes)
            if hasattr(node, 'image_path') and node.image_path:
                if not os.path.exists(node.image_path):
                    filename = os.path.basename(node.image_path)
                    if filename in file_map:
                        node.image_path = file_map[filename]
                        relocated_count += 1
                    else:
                        missing_count += 1

            # Check file_path
            if hasattr(node, 'file_path') and node.file_path:
                if not os.path.exists(node.file_path):
                    filename = os.path.basename(node.file_path)
                    if filename in file_map:
                        node.file_path = file_map[filename]
                        relocated_count += 1
                    else:
                        missing_count += 1

            # Check image history entries
            if hasattr(node, 'image_history') and node.image_history:
                try:
                    history = json.loads(node.image_history)
                    updated = False
                    for entry in history:
                        path = entry.get('path', '') if isinstance(entry, dict) else entry
                        if path and not os.path.exists(path):
                            filename = os.path.basename(path)
                            if filename in file_map:
                                if isinstance(entry, dict):
                                    entry['path'] = file_map[filename]
                                else:
                                    # Old format - need to update entire entry
                                    idx = history.index(entry)
                                    history[idx] = file_map[filename]
                                updated = True
                                relocated_count += 1
                            else:
                                missing_count += 1
                    if updated:
                        import json
                        node.image_history = json.dumps(history)
                except Exception:
                    pass

        if relocated_count > 0:
            self.report({'INFO'}, f"Relocated {relocated_count} image path(s)")
        if missing_count > 0:
            self.report({'WARNING'}, f"{missing_count} image(s) still missing")
        if relocated_count == 0 and missing_count == 0:
            self.report({'INFO'}, "No missing images found")

        return {'FINISHED'}


class NEURO_OT_translate_text(Operator):
    """Translate input text to English"""
    bl_idname = "neuro.translate_text"
    bl_label = "Translate to English"

    def execute(self, context):
        import threading
        from .api import generate_text
        from .utils import get_all_api_keys

        scn = context.scene
        input_text = scn.neuro_translate_input.strip()

        if not input_text:
            self.report({'WARNING'}, "Enter text to translate")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Get active provider
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        active_provider = prefs.active_provider if prefs else 'google'

        # Select fast/cheap model per provider
        provider_models = {
            'google': 'gemini-3-flash-preview',
            'aiml': 'gpt-5-nano-aiml',
            'replicate': 'gpt-5-nano-repl',
        }

        # Fal fallback - check text source settings (priority: AIML > Replicate > Google)
        if active_provider == 'fal':
            if prefs and getattr(prefs, 'fal_text_from_aiml', False) and api_keys.get("aiml", ""):
                model_id = 'gpt-5-nano-aiml'
            elif prefs and getattr(prefs, 'fal_text_from_replicate', False) and api_keys.get("replicate", ""):
                model_id = 'gpt-5-nano-repl'
            elif prefs and getattr(prefs, 'fal_text_from_google', False) and api_keys.get("google", ""):
                model_id = 'gemini-3-flash-preview'
            else:
                self.report({'ERROR'}, "Fal has no text models. Enable AIML or Replicate in Providers.")
                return {'CANCELLED'}
        else:
            model_id = provider_models.get(active_provider, 'gemini-3-flash-preview')

        prompt = f"Translate the following text to English. Output ONLY the translated text, nothing else:\n\n{input_text}"

        def translate_worker():
            try:
                result = generate_text(
                    prompt=prompt,
                    model_id=model_id,
                    api_keys=api_keys,
                    timeout=30,
                )

                def update_result():
                    if result:
                        context.scene.neuro_translate_result = result.strip()
                        context.scene.neuro_translate_input = result.strip()
                    return None

                bpy.app.timers.register(update_result, first_interval=0.1)

            except Exception as e:
                print(f"[{LOG_PREFIX}] Translation error: {e}")

                def show_error():
                    return None

                bpy.app.timers.register(show_error, first_interval=0.1)

        threading.Thread(target=translate_worker, daemon=True).start()

        # Show which model is being used
        model_display = model_id.replace('-aiml', '').replace('-repl', '').replace('-preview', '')
        self.report({'INFO'}, f"Translating via {model_display}...")
        return {'FINISHED'}


class NEURO_OT_copy_translation(Operator):
    """Copy translated text to clipboard"""
    bl_idname = "neuro.copy_translation"
    bl_label = "Copy Translation"

    def execute(self, context):
        scn = context.scene
        text = scn.neuro_translate_input.strip() or scn.neuro_translate_result.strip()

        if not text:
            self.report({'WARNING'}, "No text to copy")
            return {'CANCELLED'}

        context.window_manager.clipboard = text
        self.report({'INFO'}, "Copied to clipboard")
        return {'FINISHED'}


class NEURO_FH_drop_images(FileHandler):
    """File handler for dropping images into AINodes node editor"""
    bl_idname = "NEURO_FH_drop_images"
    bl_label = "Drop Images to Nodes"
    bl_import_operator = "neuro.drop_images"
    bl_file_extensions = ".png;.jpg;.jpeg;.webp;.bmp;.tiff;.tif;.gif"

    @classmethod
    def poll_drop(cls, context):
        """Check if we're in a AINodes node editor"""
        return (context.area and context.area.type == 'NODE_EDITOR' and
                context.space_data and hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree' and
                context.space_data.node_tree is not None)


addon_keymaps = []


def register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
        kmi = km.keymap_items.new('neuro.show_add_menu', 'A', 'PRESS', shift=True)
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new('neuro.duplicate_nodes', 'D', 'PRESS', shift=True)
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new('neuro.auto_connect_nodes', 'F', 'PRESS')
        addon_keymaps.append((km, kmi))

        # New: Ctrl+B to paste reference node at mouse position
        kmi = km.keymap_items.new('neuro.paste_reference_node', 'B', 'PRESS', ctrl=True)
        addon_keymaps.append((km, kmi))


def unregister_keymaps():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()