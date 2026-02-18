# -*- coding: utf-8 -*-

import os
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from bpy.types import Node

from ..nodes_core import NeuroNodeBase, HistoryMixin


# =============================================================================
# REMOVE BACKGROUND NODE
# =============================================================================

class NeuroRemoveBackgroundNode(HistoryMixin, NeuroNodeBase, Node):
    """Remove background from image using BiRefNet or cloud API"""
    bl_idname = 'NeuroRemoveBackgroundNode'
    bl_label = 'Remove Background'
    bl_icon = 'BRUSH_DATA'
    bl_width_default = 220
    bl_width_min = 180

    # Generation state
    is_processing: BoolProperty(name="Is Processing", default=False)
    status_message: StringProperty(name="Status", default="")
    result_path: StringProperty(name="Result Path", default="")

    # Image history
    image_history: StringProperty(name="Image History", default="[]")
    history_index: IntProperty(name="History Index", default=0, min=0)

    def init(self, context):
        self.is_processing = False
        self.status_message = ""
        self.result_path = ""
        self.image_history = "[]"
        self.history_index = 0

        self.inputs.new('NeuroImageSocket', "Image")
        self.outputs.new('NeuroImageSocket', "Image Out")

    def copy(self, node):
        self.result_path = ""
        self.is_processing = False
        self.status_message = ""
        self.image_history = "[]"
        self.history_index = 0

    def get_input_image(self):
        """Get connected input image path"""
        if "Image" in self.inputs and self.inputs["Image"].is_linked:
            for link in self.inputs["Image"].links:
                if hasattr(link.from_node, 'get_image_path'):
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
        # Show preview with history navigation if we have result
        if self.result_path and os.path.exists(self.result_path):
            self._draw_preview_with_nav(layout)

        # Main action button
        row = layout.row(align=True)
        row.scale_y = 1.2

        if self.is_processing:
            row.operator("neuro.node_rembg_cancel", text="Cancel", icon='CANCEL').node_name = self.name
        else:
            # View full image button
            if self.result_path and os.path.exists(self.result_path):
                op = row.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
                op.image_path = self.result_path

            row.operator("neuro.node_rembg_execute", text="Remove Background", icon='IMAGE_RGB_ALPHA').node_name = self.name

        # Status message
        if self.status_message:
            layout.label(text=self.status_message)

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
            op = sub.operator("neuro.node_rembg_history_nav", text="", icon='TRIA_UP')
            op.node_name = self.name
            op.direction = -1

            sub = col.row(align=True)
            sub.enabled = self.history_index < len(history) - 1
            op = sub.operator("neuro.node_rembg_history_nav", text="", icon='TRIA_DOWN')
            op.node_name = self.name
            op.direction = 1

            col.label(text=f"{self.history_index + 1}/{len(history)}")

        # --- ADDED: COPY BUTTON ---
        if len(history) > 0:
            col.separator()
            op = col.operator("neuro.node_copy_image_file", text="", icon='COPYDOWN')
            op.image_path = self.result_path

    def draw_label(self):
        if self.is_processing:
            return "Removing BG..."
        if self.status_message:
            return self.status_message
        if self.result_path:
            return "BG Removed!"
        return "Remove Background"


# =============================================================================
# IMAGE SPLITTER NODE
# =============================================================================

class NeuroImageSplitterNode(NeuroNodeBase, Node):
    """Split 2x2 grid image into 4 separate images"""
    bl_idname = 'NeuroImageSplitterNode'
    bl_label = 'Image Splitter'
    bl_icon = 'MOD_EXPLODE'
    bl_width_default = 220
    bl_width_min = 180

    splitter_mode: EnumProperty(
        name="Output Mode",
        items=[
            ('UNIVERSAL', 'Universal', 'Generic quadrant labels (A B C D)'),
            ('MULTIGEN', 'Multi-View', 'Labeled for 3D multi-view generation (Front/Left/Right/Back)'),
        ],
        default='MULTIGEN',
        update=lambda self, ctx: self.update_output_names()
    )

    def update_output_names(self):
        """Rename output sockets based on mode"""
        if self.splitter_mode == 'UNIVERSAL':
            names = ["A", "B", "C", "D"]
        else:
            names = ["Front", "Left", "Right", "Back"]

        # Output sockets are at indices 0-3
        for i, name in enumerate(names):
            if i < len(self.outputs):
                self.outputs[i].name = name

    # Result paths for each quadrant
    front_path: StringProperty(name="Front Path", default="")
    left_path: StringProperty(name="Left Path", default="")
    right_path: StringProperty(name="Right Path", default="")
    back_path: StringProperty(name="Back Path", default="")

    # Processing state
    is_processing: BoolProperty(name="Is Processing", default=False)
    has_split: BoolProperty(name="Has Split", default=False)

    def init(self, context):
        # Reset all instance properties to defaults
        self.front_path = ""
        self.left_path = ""
        self.right_path = ""
        self.back_path = ""
        self.is_processing = False
        self.has_split = False

        self.inputs.new('NeuroImageSocket', "Image")
        # Socket order matches Tripo 3D inputs for easy connection
        self.outputs.new('NeuroImageSocket', "Front")
        self.outputs.new('NeuroImageSocket', "Left")
        self.outputs.new('NeuroImageSocket', "Right")
        self.outputs.new('NeuroImageSocket', "Back")

    def copy(self, node):
        self.front_path = ""
        self.left_path = ""
        self.right_path = ""
        self.back_path = ""
        self.has_split = False

    def free(self):
        pass

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

    def get_image_path(self, output_name=None):
        """Return image path for specified output socket"""
        paths = {
            "Front": self.front_path,
            "Left": self.left_path,
            "Right": self.right_path,
            "Back": self.back_path,
        }
        if output_name and output_name in paths:
            path = paths[output_name]
            return path if path and os.path.exists(path) else None
        # Default to front if no specific output
        return self.front_path if self.front_path and os.path.exists(self.front_path) else None

    def get_output_image_path(self, output_socket):
        """Get image path for a specific output socket"""
        return self.get_image_path(output_socket.name)

    def draw_buttons(self, context, layout):
        if self.has_split and self._all_paths_exist():
            # 2x2 Preview grid
            self._draw_preview_grid(layout)

            # 2x2 View buttons matching grid layout
            row = layout.row(align=True)
            row.scale_y = 1.1
            op = row.operator("neuro.node_view_full_image", text="Front", icon='NONE')
            op.image_path = self.front_path
            op = row.operator("neuro.node_view_full_image", text="Right", icon='NONE')
            op.image_path = self.right_path

            row = layout.row(align=True)
            row.scale_y = 1.1
            op = row.operator("neuro.node_view_full_image", text="Left", icon='NONE')
            op.image_path = self.left_path
            op = row.operator("neuro.node_view_full_image", text="Back", icon='NONE')
            op.image_path = self.back_path
        else:
            # Main split button
            layout.prop(self, "splitter_mode", expand=True)
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("neuro.node_split_image", text="Split Image", icon='MOD_EXPLODE').node_name = self.name

    def _draw_preview_grid(self, layout):
        """Draw 2x2 preview grid"""
        box = layout.box()
        col = box.column(align=True)

        # Top row: Front | Right
        row = col.row(align=True)
        self._draw_small_preview(row, self.front_path)
        self._draw_small_preview(row, self.right_path)

        # Bottom row: Left | Back
        row = col.row(align=True)
        self._draw_small_preview(row, self.left_path)
        self._draw_small_preview(row, self.back_path)

    def _draw_small_preview(self, layout, image_path):
        """Draw small preview icon"""
        # Fix imports for subdirectory structure
        from ..nodes_core import node_preview_collection

        if not image_path or not os.path.exists(image_path):
            layout.label(text="", icon='IMAGE_DATA')
            return

        try:
            key = os.path.normpath(os.path.abspath(image_path))
            if node_preview_collection is None:
                import bpy.utils.previews
                from .. import nodes_core
                nodes_core.node_preview_collection = bpy.utils.previews.new()

            if key not in node_preview_collection:
                node_preview_collection.load(key, image_path, 'IMAGE')

            if key in node_preview_collection:
                layout.template_icon(icon_value=node_preview_collection[key].icon_id, scale=5.0)
            else:
                layout.label(text="", icon='IMAGE_DATA')
        except:
            layout.label(text="", icon='IMAGE_DATA')

    def _all_paths_exist(self):
        """Check if all split images exist"""
        return (self.front_path and os.path.exists(self.front_path) and
                self.left_path and os.path.exists(self.left_path) and
                self.right_path and os.path.exists(self.right_path) and
                self.back_path and os.path.exists(self.back_path))

    def draw_label(self):
        return "Image Splitter"