# -*- coding: utf-8 -*-

import os
import json
import bpy
import textwrap
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty
from bpy.types import Node

from ..utils import get_model_name_display
from ..nodes_core import NeuroNodeBase, HistoryMixin
from .. import nodes_core


# =============================================================================
# DESIGN VARIATIONS NODE
# =============================================================================

class NeuroDesignVariationsNode(HistoryMixin, NeuroNodeBase, Node):
    """Generate design variations with simple or guided workflow"""
    bl_idname = 'NeuroDesignVariationsNode'
    bl_label = 'Design Variations'
    bl_icon = 'MOD_ARRAY'
    bl_width_default = 272
    bl_width_min = 220

    # Mode selection
    variation_mode: EnumProperty(
        name="Mode",
        items=[
            ('SIMPLE', "1 step: Simple", "Direct generation - describe what you want"),
            ('GUIDED', "2 step: Text->Img", "Get Text variation and then generate"),
        ],
        default='SIMPLE',
        description="Select variation workflow"
    )

    # Simple mode - description
    simple_description: StringProperty(
        name="Description",
        default="",
        description="Describe the design variations you want"
    )

    # Guided mode - user changes input
    guided_changes: StringProperty(
        name="Changes",
        default="",
        description="Step 1. Describe what elements to change/add"
    )

    # Guided mode - AI generated prompts (stored as JSON for multi-line)
    generated_prompts: StringProperty(
        name="Generated Prompts",
        default="",
        description="Step 2. AI-generated variation prompts"
    )

    # Workflow state for guided mode
    prompts_ready: BoolProperty(
        name="Prompts Ready",
        default=False,
        description="Whether prompts have been generated and are ready for image generation"
    )

    # Generation state
    is_processing: BoolProperty(name="Is Processing", default=False)
    status_message: StringProperty(name="Status", default="")
    result_path: StringProperty(name="Result Path", default="")
    model_used: StringProperty(name="Model Used", default="")

    # Image history
    image_history: StringProperty(name="Image History", default="[]")
    history_index: IntProperty(name="History Index", default=0, min=0)

    def init(self, context):
        # Reset all instance properties to defaults
        self.is_processing = False
        self.status_message = ""
        self.result_path = ""
        self.model_used = ""
        self.generated_prompts = ""
        self.prompts_ready = False
        self.image_history = "[]"
        self.history_index = 0

        self.inputs.new('NeuroImageSocket', "Image")
        self.outputs.new('NeuroImageSocket', "Image Out")

    def copy(self, node):
        self.result_path = ""
        self.is_processing = False
        self.status_message = ""
        self.generated_prompts = ""
        self.prompts_ready = False
        self.image_history = "[]"
        self.history_index = 0

    def free(self):
        # Clean up text datablock if exists
        text_name = f"DesignVar_{self.name}"
        if text_name in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts[text_name])

    def get_input_image(self):
        """Get connected input image path"""
        if "Image" in self.inputs and self.inputs["Image"].is_linked:
            for link in self.inputs["Image"].links:
                if hasattr(link.from_node, 'get_image_path'):
                    # Pass socket name for multi-output nodes like ImageSplitter
                    try:
                        path = link.from_node.get_image_path(link.from_socket.name)
                    except TypeError:
                        path = link.from_node.get_image_path()
                    if path and os.path.exists(path):
                        return path
                if hasattr(link.from_node, 'result_path') and link.from_node.result_path:
                    if os.path.exists(link.from_node.result_path):
                        return link.from_node.result_path
        return None

    def get_image_path(self):
        """Return result path for downstream nodes"""
        return self.result_path if self.result_path and os.path.exists(self.result_path) else None

    def draw_buttons(self, context, layout):
        # Mode selector
        layout.prop(self, "variation_mode", expand=True)

        layout.separator()

        if self.variation_mode == 'SIMPLE':
            self._draw_simple_mode(layout)
        else:
            self._draw_guided_mode(layout)

    def _draw_simple_mode(self, layout):
        """Draw Simple mode UI"""
        # Description input
        layout.label(text="What variations do you want?", icon='INFO')
        layout.prop(self, "simple_description", text="")

        # Show premade prompt preview
        box = layout.box()
        box.scale_y = 0.7
        full_prompt = self.get_simple_prompt()
        preview = full_prompt[:60] + "..." if len(full_prompt) > 60 else full_prompt
        row = box.row(align=True)
        row.label(text=preview, icon='TEXT')
        op = row.operator("neuro.node_show_prompt", text="", icon='FULLSCREEN_ENTER')
        op.prompt_text = full_prompt
        op.title = "Variation Prompt"

        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Generate button
        self.draw_action_row(layout, "neuro.node_design_var_simple", "Generate Variations", 'MOD_ARRAY',
                             cancel_operator="neuro.node_design_var_cancel")

    def _draw_guided_mode(self, layout):
        """Draw Guided mode UI"""
        if not self.prompts_ready:
            # Step 1: User describes changes
            layout.label(text="Describe changes:", icon='GREASEPENCIL')
            layout.prop(self, "guided_changes", text="")

            # Generate prompts button
            row = layout.row(align=True)
            row.scale_y = 1.2
            if self.is_processing:
                row.operator("neuro.node_design_var_cancel", text="Cancel", icon='CANCEL').node_name = self.name
            else:
                row.operator("neuro.node_design_var_prompts", text="Generate Prompts",
                             icon='TEXT').node_name = self.name
        else:
            # Step 2: Show generated prompts, allow edit, generate image
            layout.label(text="Generated prompts:", icon='CHECKMARK')

            # Preview box with prompts
            box = layout.box()
            box.scale_y = 0.8
            prompts = self.generated_prompts
            if prompts:
                # Show wrapped preview - use textwrap for proper display
                lines = prompts.split('\n')
                for i, line in enumerate(lines[:12]):
                    if line.strip():
                        # Wrap long lines
                        wrapped = textwrap.wrap(line, width=40)
                        for wrap_line in wrapped[:2]:  # Max 2 wrapped lines per option
                            box.label(text=wrap_line)
                if len(lines) > 12:
                    box.label(text=f"... (+{len(lines) - 12} more lines)")

            # Edit / Save / Reset buttons
            row = layout.row(align=True)
            row.operator("neuro.node_design_var_edit", text="Edit", icon='GREASEPENCIL').node_name = self.name
            row.operator("neuro.node_design_var_save", text="Save", icon='FILE_TICK').node_name = self.name
            row.operator("neuro.node_design_var_reset", text="Reset", icon='LOOP_BACK').node_name = self.name

            # Show preview if we have result
            if self.result_path and os.path.exists(self.result_path):
                self._draw_preview_with_nav(layout)

            # Generate Image button
            self.draw_action_row(layout, "neuro.node_design_var_image", "Generate Image", 'IMAGE_DATA',
                                 cancel_operator="neuro.node_design_var_cancel")

    def _draw_preview_with_nav(self, layout):
        """Draw preview with history navigation"""
        row = layout.row(align=True)
        self.draw_preview(row, self.result_path)
        col = row.column(align=True)

        # Navigation if history exists
        history = self.get_history_list()
        if len(history) > 1:
            col.ui_units_x = 1
            sub = col.row(align=True)
            sub.enabled = self.history_index > 0
            op = sub.operator("neuro.node_design_var_history_nav", text="", icon='TRIA_UP')
            op.node_name = self.name
            op.direction = -1

            sub = col.row(align=True)
            sub.enabled = self.history_index < len(history) - 1
            op = sub.operator("neuro.node_design_var_history_nav", text="", icon='TRIA_DOWN')
            op.node_name = self.name
            op.direction = 1

            col.label(text=f"{self.history_index + 1}/{len(history)}")

        # --- ADDED: COPY BUTTON ---
        if len(history) > 0:
            col.separator()
            op = col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

    def get_simple_prompt(self):
        """Build prompt for simple mode"""
        desc = self.simple_description.strip()
        if not desc:
            desc = "different style variations"
        return f"make the {desc}, keep art style. Split canvas in 4 parts, Present 4 design variations in one image."

    def get_guided_system_prompt(self):
        """System prompt for guided mode text generation"""
        return """Create 4 variations of prompts for described above task, analyzing image in process.
Just base structure would be: "add/replace [elements/details] (optionally) in place of [position/area on image]"
You can adjust number of changes for each prompt and tell position on image if needed.
If there are many elements on image described in prompt - replace them all but if user asked for new design for EACH element then provide changes for each element.
Basically you creating 4 design changes/enhancements to get a finished composition.

Rules:
- Keep changes exactly in described zones
- Keep style consistent
- Elements should be appropriate and logical to composition
- Changes should respect design rules

Structure FINAL output in this form:
"Split canvas in 4 parts and Present 4 changes for each part, keep camera angle:
-option 1
-option 2
-option 3
-option 4"
"""

    def get_guided_user_prompt(self):
        """Build user prompt for guided mode"""
        changes = self.guided_changes.strip()
        if not changes:
            changes = "create interesting variations"
        return changes

    def draw_label(self):
        if self.is_processing:
            return "Processing..."
        if self.status_message:
            return self.status_message
        if self.result_path and self.model_used:
            return f"Variations: {get_model_name_display(self.model_used)}"
        return "Design Variations"


# =============================================================================
# RELIGHT NODE - AI-powered relighting
# =============================================================================

class NeuroRelightNode(HistoryMixin, NeuroNodeBase, Node):
    """AI-powered relighting: Change lighting direction using reference cube images"""
    bl_idname = 'NeuroRelightNode'
    bl_label = 'Relight'
    bl_icon = 'LIGHT_SUN'
    bl_width_default = 272
    bl_width_min = 200

    # Light direction (controls prompt and reference image)
    light_direction: EnumProperty(
        name="Direction",
        items=[
            ('LEFT', "Light from Left", "Light source on the left side"),
            ('RIGHT', "Light from Right", "Light source on the right side"),
        ],
        default='LEFT',
        description="Lighting direction"
    )

    # Editable prompt
    relight_prompt: StringProperty(
        name="Prompt",
        default="change lighting to the left side. Use cube image as reference of lighting. Keep the temperature, contrast and saturation level.",
        description="Relighting prompt (editable)"
    )

    # Reference image paths
    ref_left_path: StringProperty(
        name="Left Reference",
        default="",
        subtype='FILE_PATH',
        description="Reference image for light from left (Sun_Left.jpg)"
    )
    ref_right_path: StringProperty(
        name="Right Reference",
        default="",
        subtype='FILE_PATH',
        description="Reference image for light from right (Sun_Right.jpg)"
    )

    # Use Pro model
    use_pro_model: BoolProperty(
        name="Banana Pro",
        default=True,
        description="Use Banana Pro models for higher quality (recommended)"
    )

    # Reference image saturation adjustment
    ref_saturation: FloatProperty(
        name="Ref Saturation",
        default=1.0,
        min=0.0,
        max=3.0,
        step=10,
        description="Adjust saturation of reference image (1.0 = original)"
    )

    # Settings panel expanded
    show_settings: BoolProperty(
        name="Settings",
        default=False,
        description="Show advanced settings"
    )

    # References panel expanded
    show_references: BoolProperty(
        name="References",
        default=False,
        description="Show reference image settings"
    )

    # Generation state
    is_processing: BoolProperty(name="Is Processing", default=False)
    status_message: StringProperty(name="Status", default="")
    result_path: StringProperty(name="Result Path", default="")
    model_used: StringProperty(name="Model Used", default="")

    # History
    image_history: StringProperty(name="Image History", default="[]")
    history_index: IntProperty(name="History Index", default=0, min=0)

    def init(self, context):
        # Reset all instance properties to defaults
        self.is_processing = False
        self.status_message = ""
        self.result_path = ""
        self.model_used = ""
        self.image_history = "[]"
        self.history_index = 0

        self.inputs.new('NeuroImageSocket', "Image")
        self.outputs.new('NeuroImageSocket', "Image Out")
        self._init_default_refs()

    def _init_default_refs(self):
        """Set default reference images from assets folder"""
        # Only set if empty
        if self.ref_left_path and self.ref_right_path:
            return

        # Try multiple methods to find addon directory
        addon_dir = None

        # Method 1: __file__ based
        try:
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            # Adjust for 'nodes' or 'nodes_items' subdirectory if needed
            dir_name = os.path.basename(addon_dir)
            if dir_name in ("nodes", "nodes_items"):
                addon_dir = os.path.dirname(addon_dir)
        except:
            pass

        # Method 2: If __file__ failed, try bpy.utils.user_resource
        if not addon_dir or not os.path.exists(addon_dir):
            try:
                import bpy
                for mod_name in ["blender_ai_nodes", "ai_nodes"]:
                    addon_path = bpy.utils.user_resource('SCRIPTS', path=f"addons/{mod_name}")
                    if os.path.exists(addon_path):
                        addon_dir = addon_path
                        break
            except:
                pass

        if not addon_dir:
            print("[Relight] Could not find addon directory for default refs")
            return

        # Try both "assets" and ".assets" folders
        assets_dir = os.path.join(addon_dir, "assets")
        if not os.path.exists(assets_dir):
            assets_dir = os.path.join(addon_dir, ".assets")

        if not os.path.exists(assets_dir):
            print(f"[Relight] Assets folder not found in {addon_dir}")
            return

        if not self.ref_left_path:
            left_path = os.path.join(assets_dir, "Sun_Left.jpg")
            if os.path.exists(left_path):
                self.ref_left_path = left_path
                print(f"[Relight] Set default left ref: {left_path}")
            else:
                print(f"[Relight] Sun_Left.jpg not found in {assets_dir}")

        if not self.ref_right_path:
            right_path = os.path.join(assets_dir, "Sun_Right.jpg")
            if os.path.exists(right_path):
                self.ref_right_path = right_path
                print(f"[Relight] Set default right ref: {right_path}")
            else:
                print(f"[Relight] Sun_Right.jpg not found in {assets_dir}")

    def copy(self, node):
        self.is_processing = False
        self.status_message = ""
        self.result_path = ""
        self.model_used = ""
        self.image_history = "[]"
        self.history_index = 0

    def draw_label(self):
        if self.is_processing:
            return "Relighting..."
        if self.result_path and self.model_used:
            return f"Relight: {get_model_name_display(self.model_used)}"
        return "Relight"

    def draw_buttons(self, context, layout):
        self._init_default_refs()

        # Preview - show result if exists, otherwise input
        input_img = self.get_input_image()
        preview_path = self.result_path if self.result_path and os.path.exists(self.result_path) else input_img

        if preview_path and os.path.exists(preview_path):
            self._draw_preview_with_nav(layout)

        # Direction row: [-> (from right)] [Flip H] [<- (from left)]
        dir_row = layout.row(align=True)
        dir_row.scale_y = 1.1

        # Right arrow  = light FROM LEFT (goes to right)
        op = dir_row.operator("neuro.node_relight_direction", text="", icon='FORWARD',
                              depress=(self.light_direction == 'LEFT'))
        op.node_name = self.name
        op.direction = 'LEFT'

        # Flip horizontal button
        flip_op = dir_row.operator("neuro.node_relight_flip", text="Flip H", icon='MOD_MIRROR')
        flip_op.node_name = self.name

        # Left arrow = light FROM RIGHT (goes to left)
        op = dir_row.operator("neuro.node_relight_direction", text="", icon='BACK',
                              depress=(self.light_direction == 'RIGHT'))
        op.node_name = self.name
        op.direction = 'RIGHT'

        # Main action row: [View] [Relight] [RemoveBG] [Settings]
        action_row = layout.row(align=True)
        action_row.scale_y = 1.15

        if self.is_processing:
            action_row.operator("neuro.node_relight_cancel", text="Cancel", icon='CANCEL').node_name = self.name
        else:
            # View full image
            if self.result_path and os.path.exists(self.result_path):
                op = action_row.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
                op.image_path = self.result_path

            # Main Relight button
            action_row.operator("neuro.node_relight_generate", text="Relight", icon='LIGHT_SUN').node_name = self.name

            # Remove BG (if have result)
            if self.result_path and os.path.exists(self.result_path):
                action_row.operator("neuro.node_remove_bg", text="", icon='IMAGE_RGB_ALPHA' ).node_name = self.name

            # Settings toggle
            action_row.prop(self, "show_settings", text="", icon='PREFERENCES')

        # Settings panel
        if self.show_settings:
            self._draw_settings(context, layout)

        # Status
        if self.status_message:
            layout.label(text=self.status_message, icon='INFO')

    def _draw_settings(self, context, layout):
        """Draw settings panel"""
        box = layout.box()

        row = box.row(align=True)
        sub = row.split(factor=0.2, align=True)
        sub.prop(self, "use_pro_model", text="PRO", toggle=True, icon='EXPERIMENTAL')
        sub.prop(self, "relight_prompt", text="")

        # Row 2: Saturation slider
        box.prop(self, "ref_saturation", text="Ref Saturation")

        # Row 3: Expandable References header with Clear button
        ref_header = box.row(align=True)
        ref_header.prop(self, "show_references",
                        icon='TRIA_DOWN' if self.show_references else 'TRIA_RIGHT',
                        icon_only=True, emboss=False)
        ref_header.label(text="References")

        # Clear refs button
        clear_op = ref_header.operator("neuro.node_relight_clear_refs", text="", icon='X')
        clear_op.node_name = self.name

        # Expandable references content
        if self.show_references:
            ref_box = box.box()
            ref_row = ref_box.row(align=False)

            # From Left column
            left_col = ref_row.column(align=True)
            left_col.label(text="from Left")
            if self.ref_left_path and os.path.exists(self.ref_left_path):
                self._draw_mini_preview(left_col, self.ref_left_path)
            else:
                left_col.label(text="(none)", icon='IMAGE_DATA')
            # Buttons on separate rows for better spacing
            op = left_col.operator("neuro.node_relight_load_ref", text="Load", icon='FILEBROWSER')
            op.node_name = self.name
            op.ref_side = 'LEFT'
            op = left_col.operator("neuro.node_relight_select_ref", text="Select", icon='IMAGE_DATA')
            op.node_name = self.name
            op.ref_side = 'LEFT'

            # Separator between columns
            ref_row.separator()

            # From Right column
            right_col = ref_row.column(align=True)
            right_col.label(text="from Right")
            if self.ref_right_path and os.path.exists(self.ref_right_path):
                self._draw_mini_preview(right_col, self.ref_right_path)
            else:
                right_col.label(text="(none)", icon='IMAGE_DATA')
            # Buttons on separate rows
            op = right_col.operator("neuro.node_relight_load_ref", text="Load", icon='FILEBROWSER')
            op.node_name = self.name
            op.ref_side = 'RIGHT'
            op = right_col.operator("neuro.node_relight_select_ref", text="Select", icon='IMAGE_DATA')
            op.node_name = self.name
            op.ref_side = 'RIGHT'

    def _draw_preview_with_nav(self, layout):
        """Draw preview with history navigation on the side"""
        row = layout.row(align=True)

        # Main preview
        preview_path = self.result_path if self.result_path and os.path.exists(
            self.result_path) else self.get_input_image()
        self.draw_preview(row, preview_path)
        col = row.column(align=True)

        # History navigation column
        history = self.get_history_list()
        if len(history) > 1:
            col.ui_units_x = 1

            # Previous
            sub = col.row(align=True)
            sub.enabled = self.history_index > 0
            op = sub.operator("neuro.node_relight_history", text="", icon='TRIA_UP')
            op.node_name = self.name
            op.direction = -1

            # Next
            sub = col.row(align=True)
            sub.enabled = self.history_index < len(history) - 1
            op = sub.operator("neuro.node_relight_history", text="", icon='TRIA_DOWN')
            op.node_name = self.name
            op.direction = 1

            # Count
            col.label(text=f"{self.history_index + 1}/{len(history)}")

        # --- ADDED: COPY BUTTON ---
        if len(history) > 0:
            col.separator()
            op = col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

    def _draw_mini_preview(self, layout, path):
        """Draw small reference preview"""
        from .. import nodes_core
        if not path or not os.path.exists(path):
            return

        abs_path = os.path.normpath(os.path.abspath(path))
        try:
            mtime = os.path.getmtime(path)
            key = f"{abs_path}:{mtime}"
        except:
            key = abs_path

        if nodes_core.node_preview_collection is None:
            return

        if key not in nodes_core.node_preview_collection:
            try:
                nodes_core.node_preview_collection.load(key, path, 'IMAGE')
            except:
                return

        if key in nodes_core.node_preview_collection:
            layout.template_icon(icon_value=nodes_core.node_preview_collection[key].icon_id, scale=3.5)

    def get_input_image(self):
        """Get connected input image path"""
        if "Image" in self.inputs and self.inputs["Image"].is_linked:
            for link in self.inputs["Image"].links:
                if hasattr(link.from_node, 'get_image_path'):
                    # Pass socket name for multi-output nodes like ImageSplitter
                    try:
                        return link.from_node.get_image_path(link.from_socket.name)
                    except TypeError:
                        return link.from_node.get_image_path()
                elif hasattr(link.from_node, 'result_path'):
                    return link.from_node.result_path
        return ""

    def get_image_path(self):
        """For output socket - returns result"""
        return self.result_path if self.result_path and os.path.exists(self.result_path) else ""

    def get_reference_image(self):
        """Get current reference based on direction"""
        if self.light_direction == 'LEFT':
            return self.ref_left_path if self.ref_left_path and os.path.exists(self.ref_left_path) else ""
        return self.ref_right_path if self.ref_right_path and os.path.exists(self.ref_right_path) else ""

    def get_saturated_reference(self):
        """Get reference image with saturation adjustment applied.
        Returns path to modified temp file, or original if saturation is 1.0"""
        ref_path = self.get_reference_image()
        if not ref_path:
            return ""

        # If saturation is 1.0 (or very close), use original
        if abs(self.ref_saturation - 1.0) < 0.01:
            return ref_path

        try:
            from PIL import Image, ImageEnhance
            import tempfile

            img = Image.open(ref_path)
            enhancer = ImageEnhance.Color(img)
            saturated = enhancer.enhance(self.ref_saturation)

            # Save to temp file
            temp_dir = tempfile.gettempdir()
            base_name = os.path.splitext(os.path.basename(ref_path))[0]
            temp_path = os.path.join(temp_dir, f"{base_name}_sat{self.ref_saturation:.1f}.jpg")
            saturated.save(temp_path, "JPEG", quality=95)
            print(f"[Relight] Applied saturation {self.ref_saturation:.1f} to reference: {temp_path}")
            return temp_path
        except Exception as e:
            print(f"[Relight] Saturation adjustment failed: {e}")
            return ref_path  # Fallback to original

    def update_prompt_for_direction(self):
        """Update prompt when direction changes"""
        if self.light_direction == 'LEFT':
            self.relight_prompt = "change lighting to the left side. Use cube image as reference of lighting. Keep the temperature, contrast and saturation level."
        else:
            self.relight_prompt = "change lighting to the right side. Use cube image as reference of lighting. Keep the temperature, contrast and saturation level."