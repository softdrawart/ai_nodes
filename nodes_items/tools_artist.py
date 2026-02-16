# -*- coding: utf-8 -*-

import os
import json
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Node

from ..utils import get_model_name_display
from ..nodes_core import NeuroNodeBase, HistoryMixin
from .. import nodes_core  # Needed for node_preview_collection


# =============================================================================
# ARTIST TOOLS NODE
# =============================================================================

class NeuroArtistToolsNode(HistoryMixin, NeuroNodeBase, Node):
    """Artist workflow tools: Describe to Delete, Upscale, Change Angle, Variations, Multiview"""
    bl_idname = 'NeuroArtistToolsNode'
    bl_label = 'Artist Tools'
    bl_icon = 'TOOL_SETTINGS'
    bl_width_default = 272
    bl_width_min = 200

    # Tool mode
    tool_mode: EnumProperty(
        name="Tool",
        items=[
            ('DESCRIBE', "Get Objects List", "Generate numbered list of objects in image"),
            ('DECOMPOSE', "Decompose", "Decompose image by objects via best logic"),
            ('SEPARATION', "Separation", "Separate or delete elements from image"),
            ('UPSCALE', "Upscale / Quality", "Improve image quality"),
            ('FLIP', "Flip / Mirror", "Flip image horizontally or vertically"),
            ('ANGLE', "Change Angle", "Convert to isometric or other angle"),
            ('MULTIVIEW', "Create Multiview", "Generate front/left/right/rear views"),
        ],
        default='DESCRIBE',
        description="Select artist tool"
    )

    # For Flip mode
    flip_direction: EnumProperty(
        name="Direction",
        items=[
            ('HORIZONTAL', "Horizontal", "Flip left-right (mirror)"),
            ('VERTICAL', "Vertical", "Flip top-bottom"),
            ('BOTH', "Both", "Flip both directions (180° rotation)"),
        ],
        default='HORIZONTAL',
        description="Flip direction"
    )

    # For Separation mode
    separation_mode: EnumProperty(
        name="Mode",
        items=[
            ('SEPARATE', "Keep Element(s)", "Keep only specified elements, delete everything else"),
            ('DELETE', "Delete Element(s)", "Delete specified elements from image"),
        ],
        default='DELETE',
        description="Select separation mode"
    )
    element_text: StringProperty(
        name="Elements",
        default="",
        description="Specify element(s) to separate or delete"
    )
    preserve_form: BoolProperty(
        name="Preserve Form",
        default=False,
        description="Keep same angle, position and geometry"
    )

    # For Describe mode - stores the generated list
    description_result: StringProperty(name="Description Result", default="")
    selected_line: StringProperty(name="Selected Line", default="")
    selected_index: IntProperty(name="Selected Index", default=-1)
    # Multi-select: JSON array of selected line indices
    selected_elements_json: StringProperty(name="Selected Elements", default="[]",
                                           description="JSON array of selected element indices")
    # UI state for collapsible list
    show_elements_list: BoolProperty(name="Show Elements", default=True,
                                     description="Show/hide detected elements list")
    # Use Pro model for Keep/Delete operations
    use_pro_model: BoolProperty(name="Use Pro Model", default=False,
                                description="Use Nano Banana Pro for higher quality results")

    def get_selected_elements(self):
        """Get selected element indices as list"""
        try:
            return json.loads(self.selected_elements_json) if self.selected_elements_json else []
        except:
            return []

    def set_selected_elements(self, indices):
        """Set selected element indices from list"""
        self.selected_elements_json = json.dumps(sorted(set(indices)))

    def toggle_element_selection(self, index):
        """Toggle selection of an element by index"""
        selected = self.get_selected_elements()
        if index in selected:
            selected.remove(index)
        else:
            selected.append(index)
        self.set_selected_elements(selected)

    def clear_element_selection(self):
        """Clear all selections"""
        self.selected_elements_json = "[]"

    def get_selected_elements_text(self):
        """Get text of selected elements as comma-separated string"""
        import re
        selected = self.get_selected_elements()
        if not selected or not self.description_result:
            return ""

        lines = self.description_result.strip().split('\n')
        elements = []
        for idx in selected:
            if 0 <= idx < len(lines):
                line = lines[idx].strip()
                # Strip "N. " or "N) " prefix
                clean = re.sub(r'^\d+[\.\)]\s*', '', line)
                if clean:
                    elements.append(clean)
        return ", ".join(elements)

    # For Upscale mode
    upscale_preset: EnumProperty(
        name="Upscale Mode",
        items=[
            ('UPSCALE', "Upscale", "Simple upscale"),
            ('UPSCALE_ENHANCE', "Upscale + minor Enhance", "Upscale and improve quality"),
            ('IMPROVE', "Polish", "Tries to produce polished image"),
            ('CREATIVE', "Creative FINISH", "Creatively tries to produce final image"),
        ],
        default='UPSCALE_ENHANCE',
        description="Select upscale/enhancement mode"
    )

    # For Angle mode
    angle_preset: EnumProperty(
        name="Angle",
        items=[
            ('ISOMETRIC', "Isometric", "Convert to isometric 60-degree angle"),
            ('ISOMETRIC2', "Isometric V2", "Convert to typical isometric 2.5D game view"),
            ('FRONT', "Front View", "Convert to front view"),
            ('SIDE', "Side View", "Convert to side view"),
            ('TOP', "Top Down", "Convert to top-down view"),
            ('CUSTOM', "Custom", "Use custom prompt"),
        ],
        default='ISOMETRIC',
    )
    custom_angle_prompt: StringProperty(name="Custom Prompt", default="")

    # For Variations mode - prompt input
    variations_prompt: StringProperty(
        name="Variation Prompt",
        default="",
        description="Describe the variations you want"
    )

    # For Multiview mode - editable prompt
    multiview_prompt: StringProperty(
        name="Multiview Prompt",
        default="Scan the image from four angles: front, left, right, and rear. Create a single image showing all 4 views. Save geometry and proportions",
        description="Prompt for multiview generation"
    )

    # For Decompose mode - editable prompt
    decompose_prompt: StringProperty(
        name="Decompose Prompt",
        default="decompose object. Split canvas in 4 parts and present each element separately. Solid white background",
        description="Prompt for decomposition"
    )

    # Generation state
    is_processing: BoolProperty(name="Is Processing", default=False)
    status_message: StringProperty(name="Status", default="")
    result_path: StringProperty(name="Result Path", default="")
    model_used: StringProperty(name="Model Used", default="")

    # Image history for Upscale/Angle/Variations/Multiview modes
    image_history: StringProperty(name="Image History", default="[]")
    history_index: IntProperty(name="History Index", default=0, min=0)

    def init(self, context):
        # Reset all instance properties to defaults
        self.is_processing = False
        self.status_message = ""
        self.description_result = ""
        self.selected_line = ""
        self.selected_index = -1
        self.result_path = ""
        self.model_used = ""
        self.image_history = "[]"
        self.history_index = 0
        self.selected_elements_json = "[]"

        inp = self.inputs.new('NeuroImageSocket', "Image")
        inp.link_limit = 4096  # Allow multiple image connections
        self.outputs.new('NeuroImageSocket', "Image Out")  # For Upscale/Angle/Variations/Multiview

    def copy(self, node):
        self.is_processing = False
        self.status_message = ""
        self.description_result = ""
        self.selected_line = ""
        self.selected_index = -1
        self.result_path = ""
        self.model_used = ""
        self.image_history = "[]"
        self.history_index = 0

    def draw_label(self):
        if self.is_processing:
            return "Processing..."
        mode_labels = {
            'DESCRIBE': "Get Objects List",
            'DECOMPOSE': "Decompose",
            'SEPARATION': "Separation",
            'FLIP': "Flip / Mirror",
            'UPSCALE': "Upscale / Quality",
            'ANGLE': "Change Angle",
            'MULTIVIEW': "Create Multiview",
        }
        # Show model used if we have results
        if self.result_path and self.model_used and self.tool_mode in ('DECOMPOSE', 'SEPARATION', 'UPSCALE', 'ANGLE', 'MULTIVIEW'):
            return f"{mode_labels.get(self.tool_mode, 'Artist Tools')}: {get_model_name_display(self.model_used)}"
        return mode_labels.get(self.tool_mode, "Artist Tools")

    def draw_buttons(self, context, layout):
        # Handle invalid tool_mode
        current_mode = None
        try:
            current_mode = self.tool_mode
        except:
            pass

        # Tool mode selector
        layout.prop(self, "tool_mode", text="")

        # Mode-specific UI
        if current_mode == 'DECOMPOSE':
            self._draw_decompose_mode(layout)
        elif current_mode == 'SEPARATION':
            self._draw_separation_mode(layout)
        elif current_mode == 'FLIP':
            self._draw_flip_mode(layout)
        elif current_mode == 'UPSCALE':
            self._draw_upscale_mode(layout)
        elif current_mode == 'ANGLE':
            self._draw_angle_mode(layout)
        elif current_mode == 'MULTIVIEW':
            self._draw_multiview_mode(layout)
        else:
            # DESCRIBE or any invalid/missing mode
            self._draw_describe_mode(layout)

    def _draw_describe_mode(self, layout):
        """Draw UI for Describe to Delete mode"""
        row = layout.row()
        row.scale_y = 1.2
        if self.is_processing:
            row.operator("neuro.node_artist_cancel", text="Cancel", icon='CANCEL').node_name = self.name
        else:
            row.operator("neuro.node_artist_describe", text="Analyze Image", icon='VIEWZOOM').node_name = self.name

        if self.description_result:
            # Show preview if we have result from delete/keep action
            if self.result_path and os.path.exists(self.result_path):
                self._draw_preview_with_nav(layout)

            lines = [l for l in self.description_result.strip().split('\n') if l.strip()]
            selected = self.get_selected_elements()

            # Collapsible header with element count
            box = layout.box()
            header = box.row(align=True)
            header.prop(self, "show_elements_list",
                        icon='TRIA_DOWN' if self.show_elements_list else 'TRIA_RIGHT',
                        icon_only=True, emboss=False)
            header.label(text=f"Elements ({len(lines)})")
            if selected:
                header.label(text=f"[{len(selected)} selected]")
            # Full view button
            op = header.operator("neuro.node_show_prompt", text="", icon='FULLSCREEN_ENTER')
            op.prompt_text = self.description_result
            op.title = "Detected Elements"

            if self.show_elements_list:
                col = box.column(align=True)
                for i, line in enumerate(lines):
                    row = col.row(align=True)

                    # Checkbox toggle
                    is_selected = i in selected
                    icon = 'CHECKBOX_HLT' if is_selected else 'CHECKBOX_DEHLT'
                    op = row.operator("neuro.node_artist_toggle_element", text="", icon=icon, emboss=False)
                    op.node_name = self.name
                    op.element_index = i

                    # Text label (truncated) - just label, no click action
                    display_text = line[:35] + "..." if len(line) > 35 else line
                    row.label(text=display_text)

            # Action buttons row
            row = layout.row(align=True)
            row.scale_y = 1.3

            # Selected count
            row.label(text=f"{len(selected)} sel")

            # PRO toggle
            row.prop(self, "use_pro_model", text="PRO", toggle=True, icon='EXPERIMENTAL')

            row.separator()

            # Fullscreen view button (opens current result in image editor)
            sub = row.row(align=True)
            sub.enabled = bool(self.result_path and os.path.exists(self.result_path))
            op = sub.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
            op.image_path = self.result_path if self.result_path else ""

            # Keep/Delete buttons
            sub = row.row(align=True)
            sub.enabled = len(selected) > 0 and not self.is_processing

            op = sub.operator("neuro.node_artist_elements_action", text="Keep", icon='CHECKMARK')
            op.node_name = self.name
            op.action = 'KEEP'

            op = sub.operator("neuro.node_artist_elements_action", text="Delete", icon='TRASH')
            op.node_name = self.name
            op.action = 'DELETE'

            # Clear selection
            if selected:
                op = row.operator("neuro.node_artist_clear_selection", text="", icon='X')
                op.node_name = self.name

            # Copy to clipboard
            if selected:
                row = layout.row()
                row.scale_y = 0.8
                row.operator("neuro.node_artist_copy_selected", text="Copy to Clipboard",
                             icon='COPYDOWN').node_name = self.name

    def _draw_flip_mode(self, layout):
        """Draw UI for Flip/Mirror mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Direction selector
        layout.prop(self, "flip_direction", text="")

        # Main button row
        self.draw_action_row(layout, "neuro.node_artist_flip", "Flip", 'MOD_MIRROR',
                             cancel_operator="neuro.node_artist_cancel")

    def _draw_decompose_mode(self, layout):
        """Draw UI for Decompose mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Editable prompt field
        layout.prop(self, "decompose_prompt", text="")

        # Main button row
        self.draw_action_row(layout, "neuro.node_artist_decompose", "Decompose", 'IMGDISPLAY',
                             cancel_operator="neuro.node_artist_cancel")

    def _draw_separation_mode(self, layout):
        """Draw UI for Separation mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Mode selector (Separate/Delete)
        layout.prop(self, "separation_mode", text="")

        # Element text input
        layout.prop(self, "element_text", text="")

        # Preserve form checkbox + PRO toggle row
        row = layout.row(align=True)
        row.prop(self, "preserve_form")
        row.separator()
        row.prop(self, "use_pro_model", text="PRO", toggle=True, icon='EXPERIMENTAL')

        # Main button row - mode-dependent text/icon
        if self.separation_mode == 'SEPARATE':
            self.draw_action_row(layout, "neuro.node_artist_separation", "Keep", 'CHECKMARK',
                                 cancel_operator="neuro.node_artist_cancel")
        else:
            self.draw_action_row(layout, "neuro.node_artist_separation", "Delete", 'TRASH',
                                 cancel_operator="neuro.node_artist_cancel")

    def _draw_upscale_mode(self, layout):
        """Draw UI for Upscale mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Upscale preset selector
        layout.prop(self, "upscale_preset", text="")

        # Main button row
        self.draw_action_row(layout, "neuro.node_artist_upscale", "Upscale", 'SEQ_PREVIEW',
                             cancel_operator="neuro.node_artist_cancel")

    def _draw_angle_mode(self, layout):
        """Draw UI for Change Angle mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        layout.prop(self, "angle_preset", text="")

        if self.angle_preset == 'CUSTOM':
            layout.prop(self, "custom_angle_prompt", text="")

        # Main button row
        self.draw_action_row(layout, "neuro.node_artist_angle", "Change Angle", 'ORIENTATION_VIEW',
                             cancel_operator="neuro.node_artist_cancel")

    def _draw_multiview_mode(self, layout):
        """Draw UI for Multiview mode"""
        # Show preview if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Editable prompt field
        layout.prop(self, "multiview_prompt", text="")

        # Main button row
        self.draw_action_row(layout, "neuro.node_artist_multiview", "Create Multiview", 'VIEW_CAMERA',
                             cancel_operator="neuro.node_artist_cancel")

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
            op = sub.operator("neuro.node_artist_history_nav", text="", icon='TRIA_UP')
            op.node_name = self.name
            op.direction = -1

            sub = col.row(align=True)
            sub.enabled = self.history_index < len(history) - 1
            op = sub.operator("neuro.node_artist_history_nav", text="", icon='TRIA_DOWN')
            op.node_name = self.name
            op.direction = 1

            col.label(text=f"{self.history_index + 1}/{len(history)}")

        # --- ADDED: COPY BUTTON ---
        if len(history) > 0:
            col.separator()
            op = col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

    def get_input_image(self):
        """Get the connected input image path"""
        if "Image" in self.inputs and self.inputs["Image"].is_linked:
            for link in self.inputs["Image"].links:
                if hasattr(link.from_node, 'get_image_path'):
                    # Pass socket name for multi-output nodes like ImageSplitter
                    try:
                        return link.from_node.get_image_path(link.from_socket.name)
                    except TypeError:
                        return link.from_node.get_image_path()
        return ""

    def get_image_path(self):
        """For chaining - returns result image"""
        return self.result_path if self.result_path and os.path.exists(self.result_path) else ""

    def get_output_prompt(self):
        """For text output - returns selected line or full description"""
        if self.selected_line:
            return self.selected_line
        return self.description_result

    def get_decompose_prompt(self):
        """Get decompose prompt (editable by user)"""
        return self.decompose_prompt

    def get_upscale_prompt(self):
        """Build prompt for upscale/enhancement"""
        presets = {
            'UPSCALE': "upscale image",
            'UPSCALE_ENHANCE': "Enhance and upscale this image. Improve quality while maintaining the original composition and style.",
            'IMPROVE': "improve quality",
            'CREATIVE': "upgrade image",
        }
        return presets.get(self.upscale_preset, presets['UPSCALE_ENHANCE'])

    def get_angle_prompt(self):
        """Build prompt for angle change"""
        presets = {
            'ISOMETRIC': "isometric view of this object, orthographic camera, 60 degree angle view",
            'ISOMETRIC2': "Convert to isometric 2.5D view",
            'FRONT': "Convert this image to a front view, maintaining the same subject and style",
            'SIDE': "Convert this image to a side view, maintaining the same subject and style",
            'TOP': "Convert this image to a top-down view, maintaining the same subject and style",
        }
        if self.angle_preset == 'CUSTOM':
            return self.custom_angle_prompt
        return presets.get(self.angle_preset, presets['ISOMETRIC'])

    def get_separation_prompt(self):
        """Build prompt for separation/deletion"""
        element = self.element_text.strip()
        if not element:
            element = "main subject"

        if self.separation_mode == 'SEPARATE':
            prompt = f"Remove everything except {element}"
        else:
            prompt = f"Delete {element} "

        if self.preserve_form:
            prompt += ". Preserve the exact angle, position, scale and proportions"

        return prompt

    def get_multiview_prompt(self):
        """Build prompt for multiview generation"""
        return self.multiview_prompt if self.multiview_prompt else "Scan the image from four angles: front, left, right, and rear. Create a single image showing all 4 views. Save geometry and proportions"