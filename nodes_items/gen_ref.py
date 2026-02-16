# -*- coding: utf-8 -*-

import os
import json
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Node

# Import dependencies from parent modules
from ..constants import ASPECT_RATIOS, MODIFIERS_MAP
from ..utils import get_model_name_display
from ..nodes_core import NeuroNodeBase, HistoryMixin
from .. import nodes_core  # Needed for node_preview_collection in Reference Node

# Import dynamic getters from base.py (since you created it)
from .base import get_node_generation_models


class NeuroGenerateNode(NeuroNodeBase, Node):
    bl_idname = 'NeuroGenerateNode'
    bl_label = 'Generate / Edit'
    bl_icon = 'IMAGE_DATA'
    bl_width_default = 272
    bl_width_min = 220

    def update_history_sockets(self, context):
        """Show/hide history sockets based on model and checkbox"""
        show_history = (self.model == "gemini-3-pro-image-preview" and self.use_thought_signatures)

        if "History In" in self.inputs:
            self.inputs["History In"].hide = not show_history
        if "History Out" in self.outputs:
            self.outputs["History Out"].hide = not show_history

    # Core Props
    prompt: StringProperty(name="Prompt", default="")
    show_settings: BoolProperty(name="Show Settings", default=False)
    show_modifiers: BoolProperty(name="Show Modifiers", default=False)
    model: EnumProperty(name="Model", items=get_node_generation_models, update=update_history_sockets)
    aspect_ratio: EnumProperty(name="Aspect Ratio", items=ASPECT_RATIOS, default='match_input_image')
    result_path: StringProperty(name="Result Path", default="")
    model_used: StringProperty(name="Model Used", default="")
    is_generating: BoolProperty(name="Is Generating", default=False)
    has_generated: BoolProperty(name="Has Generated", default=False)
    status_message: StringProperty(name="Status", default="")

    # Image History (for navigation)
    image_history: StringProperty(name="Image History", default="[]")
    history_index: IntProperty(name="History Index", default=0, min=0)

    use_inpaint: bpy.props.BoolProperty(
        name="Inpaint",
        description="When enabled, generation only affects the purple-painted area. "
                    "Paint the zone first using Open Paint, then enable this toggle",
        default=False,
    )

    # PrePaint backup path
    prepaint_backup: StringProperty(name="PrePaint Backup", default="")

    # Conversation History (Gemini 3 Pro thought signatures)
    use_thought_signatures: BoolProperty(name="Use History", default=False, update=update_history_sockets)
    conversation_history: StringProperty(name="Conversation History", default="[]",
                                         description="JSON-encoded conversation history for Gemini 3 Pro")

    # Modifiers (Prompt Builder) - Local to node
    mod_isometric: BoolProperty(name="Isometric", default=False)
    mod_detailed: BoolProperty(name="Detailed", default=False)
    mod_soft: BoolProperty(name="Soft Shading", default=False)
    mod_clean: BoolProperty(name="Clean BG", default=False)
    mod_vibrant: BoolProperty(name="Vibrant", default=False)
    mod_casual: BoolProperty(name="Casual", default=False)

    # Model Params
    param_resolution: EnumProperty(name="Resolution", items=[('1K', '1K', ''), ('2K', '2K', ''), ('4K', '4K', '')],
                                   default='1K')
    param_aspect_ratio: EnumProperty(name="Aspect Ratio",
                                     items=[('1:1', '1:1', ''), ('3:4', '3:4', ''), ('4:3', '4:3', ''),
                                            ('16:9', '16:9', ''), ('9:16', '9:16', ''),
                                            ('match_input_image', 'Match Input', '')], default='match_input_image')
    param_google_search: BoolProperty(name="Web Search", default=False)
    param_enable_web_search: BoolProperty(name="Web Search", default=False)
    param_enhance_prompt: BoolProperty(name="Enhance Promt", default=True)
    param_background: EnumProperty(name="Background", items=[('auto', 'Auto', ''), ('transparent', 'Transparent', ''),
                                                             ('opaque', 'Opaque', '')], default='auto')
    param_quality: EnumProperty(name="Quality",
                                items=[('low', 'Low', ''), ('medium', 'Medium', ''), ('high', 'High', ''),
                                       ('auto', 'Auto', '')], default='auto')
    param_input_fidelity: EnumProperty(name="Input Fidelity", items=[('low', 'Low', ''), ('high', 'High', '')],
                                       default='low')

    def init(self, context):
        # Reset all instance properties to defaults
        self.result_path = ""
        self.model_used = ""
        self.is_generating = False
        self.has_generated = False
        self.status_message = ""
        self.image_history = "[]"
        self.history_index = 0
        self.conversation_history = "[]"

        inp = self.inputs.new('NeuroImageSocket', "References")
        inp.link_limit = 4096
        self.outputs.new('NeuroImageSocket', "Image")
        self.inputs.new('NeuroTextSocket', "Prompt In")
        self.outputs.new('NeuroTextSocket', "Prompt Out")
        # History sockets - hidden by default, shown only when history enabled
        hist_in = self.inputs.new('NeuroHistorySocket', "History In")
        hist_in.hide = True
        hist_out = self.outputs.new('NeuroHistorySocket', "History Out")
        hist_out.hide = True
        if context and hasattr(context.scene, "neuro_node_default_model"):
            self.model = context.scene.neuro_node_default_model

    def has_history_input(self):
        """Check if history input socket is connected"""
        if "History In" in self.inputs:
            return self.inputs["History In"].is_linked
        return False

    def get_input_history(self):
        """Get conversation history from connected input node"""
        import base64

        def decode_history(history_list):
            """Convert base64 strings back to bytes for API"""
            decoded = []
            for turn in history_list:
                new_turn = {"role": turn.get("role", "user"), "parts": []}
                for part in turn.get("parts", []):
                    if isinstance(part, dict):
                        new_part = dict(part)
                        # Decode thoughtSignature if present
                        if "_b64_sig" in new_part:
                            new_part["thoughtSignature"] = base64.b64decode(new_part["_b64_sig"])
                            del new_part["_b64_sig"]
                        # Decode inline_data bytes
                        if "inline_data" in new_part and "_base64_data" in new_part.get("inline_data", {}):
                            new_part["inline_data"] = dict(new_part["inline_data"])
                            new_part["inline_data"]["data"] = base64.b64decode(new_part["inline_data"]["_base64_data"])
                            del new_part["inline_data"]["_base64_data"]
                        new_turn["parts"].append(new_part)
                    else:
                        new_turn["parts"].append(part)
                decoded.append(new_turn)
            return decoded

        if "History In" in self.inputs and self.inputs["History In"].is_linked:
            for link in self.inputs["History In"].links:
                from_node = link.from_node
                if hasattr(from_node,
                           'conversation_history') and from_node.conversation_history and from_node.conversation_history != "[]":
                    try:
                        history = json.loads(from_node.conversation_history)
                        decoded = decode_history(history)
                        print(f"[{ADDON_NAME_CONFIG}] Decoded {len(decoded)} history turns from upstream")
                        return decoded
                    except Exception as e:
                        print(f"[{ADDON_NAME_CONFIG}] Failed to decode history: {e}")
        return []

    def set_output_history(self, history_list):
        """Store conversation history for output to downstream nodes.
        Binary data (bytes) is encoded to base64 for JSON serialization."""
        import base64

        def encode_history(history_list):
            """Convert bytes to base64 strings for JSON storage"""
            encoded = []
            for turn in history_list:
                new_turn = {"role": turn.get("role", "user"), "parts": []}
                for part in turn.get("parts", []):
                    if isinstance(part, bytes):
                        # Encode raw bytes to base64 string
                        new_turn["parts"].append({"_b64_bytes": base64.b64encode(part).decode("utf-8")})
                    elif isinstance(part, dict):
                        new_part = dict(part)
                        # Encode thoughtSignature bytes
                        if "thoughtSignature" in new_part and isinstance(new_part["thoughtSignature"], bytes):
                            new_part["_b64_sig"] = base64.b64encode(new_part["thoughtSignature"]).decode("utf-8")
                            del new_part["thoughtSignature"]
                        # Encode inline_data bytes (shouldn't be bytes since api.py already base64 encodes it)
                        if "inline_data" in new_part:
                            if isinstance(new_part["inline_data"].get("data"), bytes):
                                new_part["inline_data"] = dict(new_part["inline_data"])
                                new_part["inline_data"]["_base64_data"] = base64.b64encode(
                                    new_part["inline_data"]["data"]).decode("utf-8")
                                del new_part["inline_data"]["data"]
                        new_turn["parts"].append(new_part)
                    else:
                        new_turn["parts"].append(part)
                encoded.append(new_turn)
            return encoded

        try:
            encoded = encode_history(history_list)
            self.conversation_history = json.dumps(encoded)
            print(
                f"[{ADDON_NAME_CONFIG}] History serialized: {len(encoded)} turns, {len(self.conversation_history)} chars")
        except Exception as e:
            print(f"[{ADDON_NAME_CONFIG}] Failed to serialize history: {e}")
            import traceback
            traceback.print_exc()
            self.conversation_history = "[]"

    def should_use_history(self):
        """Determine if history should be used based on model and connections"""
        # Only for Gemini 3 Pro
        if self.model != "gemini-3-pro-image-preview":
            return False
        # Use if checkbox is checked OR if history input is connected
        return self.use_thought_signatures or self.has_history_input()

    def copy(self, node):
        self.is_generating = False
        self.has_generated = False
        self.status_message = ""
        self.image_history = "[]"
        self.history_index = 0
        self.conversation_history = "[]"  # Clear conversation history on copy

    def get_history_list(self):
        import json
        try:
            return json.loads(self.image_history)
        except:
            return []

    def add_to_history(self, path, model):
        import json
        history = self.get_history_list()
        entry = {"path": path, "model": model}
        existing = [h.get("path") if isinstance(h, dict) else h for h in history]
        if path not in existing: history.append(entry)
        self.image_history = json.dumps(history)
        self.history_index = len(history) - 1

    def get_history_entry(self, index):
        history = self.get_history_list()
        if 0 <= index < len(history):
            entry = history[index]
            return entry if isinstance(entry, dict) else {"path": entry, "model": ""}
        return None

    def draw_label(self):
        if self.is_generating: return "Generating..."
        if self.status_message: return self.status_message
        hist = self.get_history_list()
        if hist and 0 <= self.history_index < len(hist):
            entry = self.get_history_entry(self.history_index)
            if entry and entry.get("model"): return get_model_name_display(entry["model"])
        if self.model_used: return get_model_name_display(self.model_used)
        return "Generate / Edit"

    def draw_buttons(self, context, layout):
        has_result = bool(self.result_path and os.path.exists(self.result_path))

        # --- PREVIEW & ACTION COLUMN ---
        if has_result:
            row = layout.row(align=True)
            self.draw_preview(row, self.result_path)

            col = row.column(align=True)
            col.ui_units_x = 1.0

            history = self.get_history_list()
            if len(history) > 1:
                col.separator(factor=1)
                op_prev = col.operator("neuro.node_history_nav", text="", icon='TRIA_UP')
                op_prev.node_name = self.name
                op_prev.direction = -1
                op_next = col.operator("neuro.node_history_nav", text="", icon='TRIA_DOWN')
                op_next.node_name = self.name
                op_next.direction = 1
                col.label(text=f"{self.history_index + 1}/{len(history)}")

            col.separator(factor=1.5)
            op = col.operator("neuro.node_open_paint", text="", icon='BRUSH_DATA')
            op.node_name = self.name

            if self.prepaint_backup and os.path.exists(self.prepaint_backup):
                col.separator(factor=0.5)
                op = col.operator("neuro.node_revert_paint", text="", icon='LOOP_BACK')
                op.node_name = self.name

            col.separator(factor=0.5)
            op = col.operator("neuro.node_create_inpaint", text="", icon='CLIPUV_HLT')
            op.node_name = self.name

            # --- ADDED: COPY BUTTON ---
            col.separator(factor=2)
            op = col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

            if not self.is_generating:
                col.separator(factor=2)
                bg_op = col.operator("neuro.node_remove_bg", text="", icon='IMAGE_RGB_ALPHA' )
                bg_op.node_name = self.name

        else:
            box = layout.box()
            box.scale_y = 2.0
            box.label(text="No Image", icon='IMAGE_DATA')

        # --- PROMPT INPUT ---
        prompt_connected = self.inputs["Prompt In"].is_linked if "Prompt In" in self.inputs else False

        if prompt_connected:
            row = layout.row(align=True)
            row.label(text="Linked Prompt", icon='LINKED')
            connected = self.get_input_prompt()
            op = row.operator("neuro.node_show_prompt", text="", icon='TEXT')
            op.prompt_text = connected
        else:
            row = layout.row(align=True)
            row.prop(self, "prompt", text="")
            edit_op = row.operator("neuro.open_text_editor", text="", icon='GREASEPENCIL')
            edit_op.node_name = self.name
            edit_op.prop_name = "prompt"

            text_name = f"Node_{self.name}_prompt"
            if text_name in bpy.data.texts:
                sync_op = row.operator("neuro.sync_text_to_node", text="", icon='FILE_REFRESH')
                sync_op.node_name = self.name
                sync_op.prop_name = "prompt"

        # --- MAIN ACTION ROW ---
        row = layout.row(align=True)
        row.scale_y = 1.15

        # 1. Fullscreen
        sub = row.row(align=True)
        sub.enabled = has_result
        op_view = sub.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
        op_view.image_path = self.result_path

        # 2. Model Selector
        row.prop(self, "model", text="")

        # --- SEPARATOR ---
        row.separator(factor=0.5)

        # 3. Modifiers & Settings (Now in the middle)
        row.prop(self, "show_modifiers", text="", icon='WORDWRAP_ON')
        row.prop(self, "show_settings", text="", icon='PREFERENCES')

        # --- SEPARATOR (Safety padding) ---
        row.separator(factor=0.6)

        # 4. Generate / Cancel (Far Right, Wide)
        sub_gen = row.row(align=True)
        sub_gen.scale_x = 1.4
        if self.is_generating:
            sub_gen.operator("neuro.node_cancel", text="", icon='CANCEL').node_name = self.name
        else:
            op = sub_gen.operator("neuro.node_generate", text="", icon='PLAY')
            op.node_name = self.name

        # --- MODIFIERS BOX ---
        if self.show_modifiers:
            box = layout.box()
            box.label(text="Style Modifiers:", icon='MODIFIER')
            grid = box.grid_flow(row_major=True, columns=2, align=True)
            grid.prop(self, "mod_isometric", text="Isometric")
            grid.prop(self, "mod_detailed", text="Detailed")
            grid.prop(self, "mod_soft", text="Soft Light")
            grid.prop(self, "mod_clean", text="Clean BG")
            grid.prop(self, "mod_vibrant", text="Vibrant")
            grid.prop(self, "mod_casual", text="Casual")

        # --- SETTINGS BOX ---
        if self.show_settings:
            box = layout.box()

            try:
                from ..model_registry import get_model
                config = get_model(self.model)
                if config and config.params:
                    param_names = [p.name for p in config.params]
                    drawn_params = set()

                    if "resolution" in param_names and "aspect_ratio" in param_names:
                        r = box.row(align=True)
                        r.prop(self, "param_resolution", text="Res")
                        r.prop(self, "param_aspect_ratio", text="")
                        drawn_params.update(["resolution", "aspect_ratio"])

                    if "background" in param_names and "quality" in param_names:
                        r = box.row(align=True)
                        r.prop(self, "param_background", text="BG")
                        r.prop(self, "param_quality", text="Quality")
                        drawn_params.update(["background", "quality"])

                    if "google_search" in param_names and self.model == "gemini-3-pro-image-preview":
                        hist_box = box.box()
                        r = hist_box.row(align=True)
                        r.prop(self, "param_google_search", text="Web Search")
                        has_input = self.has_history_input()
                        if has_input:
                            r.prop(self, "use_thought_signatures", text="Used History")
                            r.label(text="", icon='LINKED')
                        else:
                            r.prop(self, "use_thought_signatures", text="Enable History")
                        drawn_params.add("google_search")

                    for param in config.params:
                        box.scale_y = 0.9
                        if param.name in drawn_params:
                            continue
                        prop_name = f"param_{param.name}"
                        if hasattr(self, prop_name):
                            if param.name == "input_fidelity":
                                if not ("References" in self.inputs and self.inputs["References"].is_linked):
                                    continue
                            box.prop(self, prop_name, text=param.label)
                else:
                    r = box.row(align=True)
                    r.prop(self, "param_resolution", text="Res")
                    r.prop(self, "param_aspect_ratio", text="")
            except:
                box.prop(self, "param_resolution")

    def get_input_prompt(self):
        # Base prompt
        base = self.prompt

        # If linked, use that instead
        if "Prompt In" in self.inputs and self.inputs["Prompt In"].is_linked:
            for link in self.inputs["Prompt In"].links:
                if hasattr(link.from_node, 'get_output_prompt'):
                    base = link.from_node.get_output_prompt()
                    break

        # Append Modifiers (The "Prompt Builder" logic)
        # MODIFIERS_MAP is imported at module level from .constants
        modifiers = []

        if self.mod_isometric:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_isometric", ""))
        if self.mod_detailed:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_detailed", ""))
        if self.mod_soft:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_soft", ""))
        if self.mod_clean:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_clean", ""))
        if self.mod_vibrant:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_vibrant", ""))
        if self.mod_casual:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_casual", ""))

        if modifiers:
            mod_text = " ".join(m for m in modifiers if m)
            base = base.strip() + " " + mod_text
            print(f"[MODS APPLIED] Final prompt: {base}")

        return base

    def get_image_path(self):
        return self.result_path if self.result_path and os.path.exists(self.result_path) else ""

    def get_input_images(self):
        images = []
        if "References" in self.inputs and self.inputs["References"].is_linked:
            for link in self.inputs["References"].links:
                from_node = link.from_node
                # Check for multi-image support first
                if hasattr(from_node, 'get_all_image_paths'):
                    paths = from_node.get_all_image_paths()
                    for path in paths:
                        if path and os.path.exists(path) and path not in images:
                            images.append(path)
                elif hasattr(from_node, 'get_image_path'):
                    path = from_node.get_image_path()
                    if path and os.path.exists(path) and path not in images:
                        images.append(path)
        return images

    def get_output_prompt(self):
        return self.get_input_prompt()


class NeuroReferenceNode(NeuroNodeBase, Node):
    bl_idname = 'NeuroReferenceNode'
    bl_label = 'Reference Image'
    bl_icon = 'IMAGE_REFERENCE'
    bl_width_default = 260
    bl_width_min = 200

    source_type: EnumProperty(name="Source",
                              items=[
                                  ('FILE', 'File', 'Load from disk'),
                                  ('EDITOR', 'Current Editor Image', 'From Image Editor'),
                                  ('BLENDER', 'Editor List', 'Pick from Blender images'),
                                  ('CLIPBOARD', 'Clipboard', 'Paste from clipboard'),
                                  ('RENDER', 'Render', 'Use Render Result'),
                              ],
                              default='FILE')
    file_path: StringProperty(name="File", default="", subtype='FILE_PATH')
    image_path: StringProperty(name="Loaded Image", default="")
    blender_image: StringProperty(name="Blender Image", default="")
    status_message: StringProperty(name="Status", default="")

    # Multi-image support
    image_paths_json: StringProperty(name="Image Paths", default="[]",
                                     description="JSON array of image paths")
    current_index: IntProperty(name="Current Index", default=0, min=0,
                               description="Currently selected image index")
    grid_columns: IntProperty(name="Grid Columns", default=3, min=2, max=6,
                              description="Number of columns in grid preview")

    # PrePaint backup path
    prepaint_backup: StringProperty(name="PrePaint Backup", default="")

    def init(self, context):
        self.outputs.new('NeuroImageSocket', "Image")

    def get_image_paths_list(self):
        """Get all image paths as list"""
        try:
            paths = json.loads(self.image_paths_json) if self.image_paths_json else []
            # Filter to only existing files
            return [p for p in paths if p and os.path.exists(p)]
        except:
            return []

    def set_image_paths_list(self, paths):
        """Set image paths from list"""
        self.image_paths_json = json.dumps(paths)
        if paths:
            self.current_index = min(self.current_index, len(paths) - 1)
        else:
            self.current_index = 0

    def add_image_path(self, path):
        """Add a single image path"""
        paths = self.get_image_paths_list()
        if path and os.path.exists(path) and path not in paths:
            paths.append(path)
            self.set_image_paths_list(paths)
            self.current_index = len(paths) - 1

    def clear_images(self):
        """Clear all stored images"""
        self.image_paths_json = "[]"
        self.current_index = 0
        self.image_path = ""

    def draw_buttons(self, context, layout):
        paths = self.get_image_paths_list()
        num_images = len(paths)

        if num_images > 1:
            # Multi-image grid preview
            self._draw_grid_preview(layout, paths)
        elif num_images == 1:
            # Single image preview
            self.draw_preview(layout, paths[0])
        else:
            # Fallback to legacy single-image path
            preview_path = self.get_image_path()
            if not self.draw_preview(layout, preview_path):
                box = layout.box()
                box.scale_y = 1.5
                box.label(text="No image", icon='IMAGE_DATA')

        # Image count indicator
        if num_images > 0:
            row = layout.row()
            row.alignment = 'CENTER'
            row.label(text=f"{num_images} image{'s' if num_images > 1 else ''}")
            if num_images > 1:
                row.operator("neuro.node_ref_clear", text="", icon='X').node_name = self.name

        # Get the specific image path (handles current grid selection index)
        current_path = self.get_image_path()

        row = layout.row(align=True)
        row.prop(self, "source_type", text="")

        # Paint Button + Revert (Only show if valid path exists)
        if current_path and os.path.exists(current_path):
            row.separator()
            op = row.operator("neuro.node_open_paint", text="", icon='BRUSH_DATA' )
            op.node_name = self.name
            # Revert to backup (only show if backup exists)
            if self.prepaint_backup and os.path.exists(self.prepaint_backup):
                op = row.operator("neuro.node_revert_paint", text="", icon='LOOP_BACK')
                op.node_name = self.name
            inp = row.operator("neuro.node_create_inpaint", text="", icon='CLIPUV_HLT')
            inp.node_name = self.name

        if self.source_type == 'FILE':
            layout.prop(self, "file_path", text="")
            row = layout.row(align=True)
            if self.file_path:
                row.operator("neuro.node_load_file", text="Load", icon='IMPORT').node_name = self.name
            op = row.operator("neuro.node_load_files_multi", text="Load Multiple", icon='FILE_FOLDER')
            op.node_name = self.name
        elif self.source_type == 'EDITOR':
            layout.operator("neuro.node_from_editor", text="From Editor", icon='IMAGE_DATA').node_name = self.name
        elif self.source_type == 'CLIPBOARD':
            layout.operator("neuro.node_from_clipboard", text="Paste", icon='PASTEDOWN').node_name = self.name
        elif self.source_type == 'BLENDER':
            layout.prop_search(self, "blender_image", bpy.data, "images", text="")
            if self.blender_image:
                layout.operator("neuro.node_load_blender_image", text="Load", icon='IMPORT').node_name = self.name
        elif self.source_type == 'RENDER':
            layout.operator("neuro.node_from_render", text="Grab Render", icon='RENDER_STILL').node_name = self.name

        """ 
        if self.status_message:
            layout.label(text=self.status_message, icon='INFO')
        """

    def _draw_grid_preview(self, layout, paths):
        """Draw auto-arranged grid of image previews"""
        preview_collection = nodes_core.node_preview_collection

        if preview_collection is None:
            try:
                import bpy.utils.previews
                nodes_core.node_preview_collection = bpy.utils.previews.new()
                preview_collection = nodes_core.node_preview_collection
            except:
                return

        num_images = len(paths)
        cols = min(self.grid_columns, num_images)

        # Calculate preview scale based on grid size
        base_scale = self.get_preview_scale()
        grid_scale = max(4, base_scale // cols)

        box = layout.box()
        grid = box.grid_flow(row_major=True, columns=cols, even_columns=True, even_rows=True, align=True)

        for i, path in enumerate(paths):
            if not os.path.exists(path):
                continue

            abs_path = os.path.normpath(os.path.abspath(path))

            # Generate preview key with mtime
            try:
                mtime = os.path.getmtime(path)
                key = f"{abs_path}:{mtime}"
            except OSError:
                key = abs_path

            # Load preview if needed
            if key not in preview_collection:
                try:
                    preview_collection.load(key, path, 'IMAGE')
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Failed to load grid preview {key}: {e}")
                    continue

            if key in preview_collection:
                col = grid.column(align=True)
                col.template_icon(icon_value=preview_collection[key].icon_id, scale=grid_scale)

    def get_image_path(self):
        """Get single image path (current/first) - backward compatible"""
        paths = self.get_image_paths_list()
        if paths:
            idx = min(self.current_index, len(paths) - 1)
            return paths[idx]

        # Fallback to legacy single-image properties
        if self.source_type == 'FILE' and self.file_path:
            path = bpy.path.abspath(self.file_path)
            if os.path.exists(path):
                return path
        elif self.source_type == 'BLENDER' and self.blender_image:
            img = bpy.data.images.get(self.blender_image)
            if img and self.image_path and os.path.exists(self.image_path):
                return self.image_path
        return self.image_path if self.image_path and os.path.exists(self.image_path) else ""

    def get_all_image_paths(self):
        """Get all stored image paths for multi-reference support"""
        paths = self.get_image_paths_list()
        if paths:
            return paths

        # Fallback to single image
        single = self.get_image_path()
        return [single] if single else []


class NeuroInpaintNode(NeuroNodeBase, HistoryMixin, Node):
    """Inpaint — Paint area on image, generate changes only in painted zone"""
    bl_idname = 'NeuroInpaintNode'
    bl_label = 'Inpaint'
    bl_icon = 'CLIPUV_HLT'
    bl_width_default = 272
    bl_width_min = 220

    # --- Prompt ---
    prompt: StringProperty(
        name="Prompt",
        description="Describe what to generate in the painted zone",
        default="",
    )

    # --- Model toggle ---
    use_pro_model: BoolProperty(
        name="PRO",
        description="Use Nano Banana Pro (slower, higher quality) instead of Flash",
        default=False,
    )

    param_resolution: EnumProperty(
        name="Resolution",
        items=[('1K', '1K', ''), ('2K', '2K', ''), ('4K', '4K', '')],
        default='1K',
        description="Output resolution (Banana Pro only)",
    )

    # --- State (standard pattern) ---
    result_path: StringProperty(default="")
    image_history: StringProperty(default="[]")
    history_index: IntProperty(default=0, min=0)
    model_used: StringProperty(default="")
    is_generating: BoolProperty(default=False)
    has_generated: BoolProperty(default=False)
    status_message: StringProperty(default="")
    prepaint_backup: StringProperty(default="")

    def init(self, context):
        # Reference inputs only — main image lives in result_path (preview)
        self.inputs.new('NeuroImageSocket', "Reference")
        self.outputs.new('NeuroImageSocket', "Image Out")

    def copy(self, node):
        self.is_generating = False
        self.status_message = ""
        self.has_generated = False

    def get_image_path(self):
        """For open_paint, revert_paint, remove_bg, view_full operators"""
        if self.result_path and os.path.exists(self.result_path):
            return self.result_path
        return None

    def get_input_images(self):
        """Main image (result_path) + any connected references.
        First image = the painted base image.
        Additional images = style/content references from sockets."""
        images = []

        # 1. Main image — the painted preview
        if self.result_path and os.path.exists(self.result_path):
            images.append(self.result_path)

        # 2. Connected reference images from sockets
        for inp in self.inputs:
            if inp.is_linked and inp.bl_idname == 'NeuroImageSocket':
                linked_node = inp.links[0].from_node
                path = None
                if hasattr(linked_node, 'result_path') and linked_node.result_path:
                    path = linked_node.result_path
                elif hasattr(linked_node, 'get_image_path'):
                    path = linked_node.get_image_path()
                if path and os.path.exists(path):
                    images.append(path)

        return images

    def draw_buttons(self, context, layout):
        has_result = bool(self.result_path and os.path.exists(self.result_path))

        # --- PREVIEW & ACTION COLUMN ---
        if has_result:
            main_row = layout.row(align=True)

            # Preview image (left, expands)
            preview_col = main_row.column()
            self.draw_preview(preview_col, self.result_path)

            # Sidebar buttons (right, narrow icon column)
            side_col = main_row.column(align=True)
            side_col.ui_units_x = 1

            # History navigation
            history = self.get_history_list()
            if len(history) > 1:
                op = side_col.operator("neuro.node_history_nav", text="", icon='TRIA_UP')
                op.node_name = self.name
                op.direction = -1
                op = side_col.operator("neuro.node_history_nav", text="", icon='TRIA_DOWN')
                op.node_name = self.name
                op.direction = 1
                side_col.label(text=f"{self.history_index + 1}/{len(history)}")

            # Open Paint
            side_col.separator(factor=1.5)
            op = side_col.operator("neuro.node_open_paint", text="", icon='BRUSH_DATA')
            op.node_name = self.name

            # Revert Paint
            if self.prepaint_backup and os.path.exists(self.prepaint_backup):
                side_col.separator(factor=0.5)
                op = side_col.operator("neuro.node_revert_paint", text="", icon='LOOP_BACK')
                op.node_name = self.name

            # Inpaint (recursive — create another inpaint node from this result)
            side_col.separator(factor=0.5)
            op = side_col.operator("neuro.node_create_inpaint", text="", icon='CLIPUV_HLT')
            op.node_name = self.name

            # --- ADDED: COPY BUTTON ---
            side_col.separator(factor=2)
            op = side_col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

            # Remove BG
            if not self.is_generating:
                side_col.separator(factor=2)
                op = side_col.operator("neuro.node_remove_bg", text="", icon='IMAGE_RGB_ALPHA')
                op.node_name = self.name

        # ─── Status / Model info ───
        if self.model_used:
            row = layout.row()
            row.scale_y = 0.6
            row.alignment = 'RIGHT'
            row.label(text=self.model_used, icon='INFO')

        # ─── Prompt ───
        prompt_row = layout.row(align=True)
        prompt_row.prop(self, "prompt", text="")
        op = prompt_row.operator("neuro.open_text_editor", text="", icon='GREASEPENCIL')
        op.node_name = self.name
        op.prop_name = "prompt"

        # ─── Generate row: [Fullscreen] [PRO toggle] [Inpaint button] ───
        if self.is_generating:
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("neuro.node_inpaint_cancel", text="Cancel", icon='CANCEL').node_name = self.name
            if self.status_message:
                layout.label(text=self.status_message)
        else:
            row = layout.row(align=True)
            row.scale_y = 1.2

            # View Full Image (left)
            if has_result:
                op = row.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
                op.image_path = self.result_path

            # PRO toggle + resolution
            row.prop(self, "use_pro_model", text="Banana Pro", toggle=True)
            if self.use_pro_model:
                row.prop(self, "param_resolution", text="")

            # Inpaint generate button
            row.operator(
                "neuro.node_inpaint_generate",
                text="Inpaint",
                icon='CLIPUV_HLT'
            ).node_name = self.name