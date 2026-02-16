# -*- coding: utf-8 -*-

import os
import bpy
import textwrap
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Node

from ..utils import get_model_name_display
from ..nodes_core import NeuroNodeBase
# This is the "Better" part: Dynamic model loading from the base module
from .base import get_node_text_models


# =============================================================================
# TEXT NODE
# =============================================================================

class NeuroTextNode(NeuroNodeBase, Node):
    """Simple text input node"""
    bl_idname = 'NeuroTextNode'
    bl_label = 'Text'
    bl_icon = 'TEXT'
    bl_width_default = 240
    bl_width_min = 160

    text_content: StringProperty(
        name="Text",
        default="",
        description="Input text"
    )

    def init(self, context):
        self.outputs.new('NeuroTextSocket', "Text")

    def copy(self, node):
        pass

    def draw_buttons(self, context, layout):
        layout.prop(self, "text_content", text="")
        op = layout.operator("neuro.open_text_editor", text="Open Editor", icon='GREASEPENCIL')
        op.node_name = self.name
        op.prop_name = "text_content"

        # Show current length
        if self.text_content:
            layout.label(text=f"{len(self.text_content)} chars", icon='WORDWRAP_ON')

    def draw_label(self):
        return self.text_content[:20] + "..." if self.text_content else "Text"

    def get_output_prompt(self):
        """Return text for downstream nodes"""
        return self.text_content


# =============================================================================
# MERGE TEXT NODE
# =============================================================================

class NeuroMergeTextNode(NeuroNodeBase, Node):
    """Merge multiple text inputs into one string"""
    bl_idname = 'NeuroMergeTextNode'
    bl_label = 'Merge Text'
    bl_icon = 'SORTALPHA'
    bl_width_default = 200

    separator: EnumProperty(
        name="Separator",
        items=[
            ('SPACE', 'Space', 'Join with space'),
            ('NEWLINE', 'New Line', 'Join with new line'),
            ('COMMA', 'Comma', 'Join with comma'),
            ('NONE', 'None', 'Join without separator'),
        ],
        default='SPACE',
        description="Separator between text inputs"
    )

    def init(self, context):
        socket = self.inputs.new('NeuroTextSocket', "Texts")
        socket.link_limit = 4096  # Allow multiple connections
        self.outputs.new('NeuroTextSocket', "Merged")

    def copy(self, node):
        pass

    def draw_buttons(self, context, layout):
        layout.prop(self, "separator", text="Separator")

    def get_output_prompt(self):
        """Collect all connected texts and join them"""
        texts = []
        if "Texts" in self.inputs and self.inputs["Texts"].is_linked:
            # Iterate over all links connected to this socket
            for link in self.inputs["Texts"].links:
                if hasattr(link.from_node, 'get_output_prompt'):
                    text = link.from_node.get_output_prompt()
                    if text:
                        texts.append(text)

        sep_map = {
            'SPACE': " ",
            'NEWLINE': "\n",
            'COMMA': ", ",
            'NONE': ""
        }
        return sep_map[self.separator].join(texts)


# =============================================================================
# UPGRADE PROMPT NODE
# =============================================================================

class NeuroUpgradePromptNode(NeuroNodeBase, Node):
    """Upgrade prompt using LLM (Creative or Editing modes)"""
    bl_idname = 'NeuroUpgradePromptNode'
    bl_label = 'Upgrade Prompt'
    bl_icon = 'MODIFIER'
    bl_width_default = 280
    bl_width_min = 220

    input_prompt: StringProperty(name="Input", default="")
    output_prompt: StringProperty(name="Output", default="")

    upgrade_mode: EnumProperty(
        name="Mode",
        items=[
            ('CREATIVE', 'Creative', 'Enhance creativity and details'),
            ('EDITING', 'Editing (Strict)', 'Format for precise editing tasks'),
            ('EDITING_LOOSE', 'Editing (Loose)', 'More flexible editing instructions'),
        ],
        default='CREATIVE'
    )

    # Use dynamic model getter from base.py
    model: EnumProperty(
        name="Model",
        items=get_node_text_models,
        description="LLM Model to use for upgrade"
    )

    is_processing: BoolProperty(name="Processing", default=False)
    status_message: StringProperty(name="Status", default="")

    def init(self, context):
        self.inputs.new('NeuroImageSocket', "Reference")
        self.inputs.new('NeuroTextSocket', "Prompt In")
        self.outputs.new('NeuroTextSocket', "Prompt Out")

    def copy(self, node):
        self.is_processing = False
        self.status_message = ""

    def draw_buttons(self, context, layout):
        # --- INPUT SECTION ---
        has_input = False
        if "Prompt In" in self.inputs and self.inputs["Prompt In"].is_linked:
            layout.label(text="Input: Linked", icon='LINKED')
            has_input = True
        else:
            row = layout.row(align=True)
            row.prop(self, "input_prompt", text="")
            op = row.operator("neuro.open_text_editor", text="", icon='GREASEPENCIL')
            op.node_name = self.name
            op.prop_name = "input_prompt"
            has_input = bool(self.input_prompt.strip())

        # --- MAIN ACTION ROW ---
        # [View] [Model] --sep-- [Upgrade]
        row = layout.row(align=True)
        row.scale_y = 1.15

        # --- MODE SELECTOR ---
        upg_mod = row.row(align=True)
        upg_mod.prop(self, "upgrade_mode", text="")
        # 2. Model Selector
        row.prop(self, "model", text="")

        # --- SEPARATOR ---
        row.separator(factor=0.6)

        # 3. Action Button (Wide, Far Right)
        sub_gen = row.row(align=True)
        sub_gen.scale_x = 2

        if self.is_processing:
            sub_gen.operator("neuro.node_cancel_text", text="", icon='CANCEL').node_name = self.name
        else:
            sub = sub_gen.row(align=True)
            sub.enabled = has_input
            sub.operator("neuro.node_upgrade_prompt", text="", icon='PLAY').node_name = self.name

        # --- RESULT PREVIEW ---
        if self.output_prompt:
            box = layout.box()
            col = box.column(align=True)  # align=True removes vertical spacing

            # Calculate wrap width based on node width (approx 7px per char)
            # self.width is the current width of the node instance
            wrap_width = max(30, int(self.width / 5.8))

            lines = textwrap.wrap(self.output_prompt, width=wrap_width)
            for i, line in enumerate(lines):
                if i > 3:
                    col.label(text="...")
                    break
                col.label(text=line)

            # Copy button
            row = box.row(align=True)
            row.alignment = 'RIGHT'
            op_view = row.operator("neuro.node_show_prompt", text="Show", icon='FILE_TEXT')
            op_view.prompt_text = self.output_prompt
            op_view.title = "Upgraded Prompt"
            op = row.operator("neuro.copy_prompt", text="Copy", icon='COPYDOWN')
            op.prompt_text = self.output_prompt

        if self.status_message:
            layout.label(text=self.status_message, icon='INFO')

    def get_input_prompt(self):
        if "Prompt In" in self.inputs and self.inputs["Prompt In"].is_linked:
            for link in self.inputs["Prompt In"].links:
                if hasattr(link.from_node, 'get_output_prompt'):
                    return link.from_node.get_output_prompt()
        return self.input_prompt

    def get_output_prompt(self):
        return self.output_prompt if self.output_prompt else self.get_input_prompt()

    def get_reference_image(self):
        if "Reference" in self.inputs and self.inputs["Reference"].is_linked:
            for link in self.inputs["Reference"].links:
                from_node = link.from_node
                if hasattr(from_node, 'get_image_path'): return from_node.get_image_path()
        return ""


# =============================================================================
# TEXT GENERATION NODE
# =============================================================================

class NeuroTextGenNode(NeuroNodeBase, Node):
    """General purpose LLM text generation node"""
    bl_idname = 'NeuroTextGenNode'
    bl_label = 'Text Generation'
    bl_icon = 'TEXT'
    bl_width_default = 240
    bl_width_min = 200

    input_prompt: StringProperty(name="Prompt", default="", description="Instructions for LLM")
    output_text: StringProperty(name="Output", default="")

    # Use dynamic model getter
    model: EnumProperty(
        name="Model",
        items=get_node_text_models,
        description="LLM Model"
    )

    is_generating: BoolProperty(name="Generating", default=False)
    status_message: StringProperty(name="Status", default="")

    def init(self, context):
        # Context input (e.g. from other text nodes)
        self.inputs.new('NeuroTextSocket', "Context").link_limit = 4096
        # Image input (for multimodal models)
        self.inputs.new('NeuroImageSocket', "Images").link_limit = 4096

        self.outputs.new('NeuroTextSocket', "Text Out")

    def copy(self, node):
        self.is_generating = False
        self.status_message = ""

# TODO: UI same rework as gen node ??
    def draw_buttons(self, context, layout):
        # --- INPUT SECTION ---
        # Show linked context indicator if connected
        if "Context" in self.inputs and self.inputs["Context"].is_linked:
            layout.label(text="Context: Linked", icon='LINKED')

        row = layout.row(align=True)
        row.prop(self, "input_prompt", text="")
        op = row.operator("neuro.open_text_editor", text="", icon='GREASEPENCIL')
        op.node_name = self.name
        op.prop_name = "input_prompt"

        # --- MAIN ACTION ROW ---
        # [View] [Model] --sep-- [Generate]
        row = layout.row(align=True)
        row.scale_y = 1.15

        # 2. Model Selector
        row.prop(self, "model", text="")

        # --- SEPARATOR ---
        row.separator(factor=0.6)

        # 3. Action Button (Wide, Far Right)
        sub_gen = row.row(align=True)
        sub_gen.scale_x = 1.4

        if self.is_generating:
            sub_gen.operator("neuro.node_cancel_text", text="", icon='CANCEL').node_name = self.name
        else:
            # Preserved ICON: PLAY
            sub_gen.operator("neuro.node_generate_text", text="", icon='PLAY').node_name = self.name

        # --- RESULT PREVIEW ---
        if self.output_text:
            box = layout.box()
            col = box.column(align=True)  # align=True removes vertical spacing

            # Dynamic wrapping
            wrap_width = max(30, int(self.width / 5.8))

            lines = textwrap.wrap(self.output_text, width=wrap_width)
            for i, line in enumerate(lines):
                if i > 4:
                    col.label(text="...")
                    break
                col.label(text=line)

            # Copy button
            row = box.row(align=True)
            row.alignment = 'RIGHT'
            op_view = row.operator("neuro.node_show_prompt", text="Show", icon='FILE_TEXT')
            op_view.prompt_text = self.output_text
            op_view.title = "Generated output"
            op = row.operator("neuro.copy_prompt", text="Copy", icon='COPYDOWN')
            op.prompt_text = self.output_text

        if self.status_message:
            layout.label(text=self.status_message, icon='INFO')

    def get_context_text(self):
        """Collect text from Context input"""
        texts = []
        if "Context" in self.inputs and self.inputs["Context"].is_linked:
            for link in self.inputs["Context"].links:
                if hasattr(link.from_node, 'get_output_prompt'):
                    text = link.from_node.get_output_prompt()
                    if text:
                        texts.append(text)
        return "\n\n".join(texts)

    def get_complete_prompt(self):
        """Combine user prompt and context"""
        parts = []
        if self.input_prompt:
            parts.append(self.input_prompt)

        context = self.get_context_text()
        if context:
            parts.append(f"\nContext:\n{context}")

        return "\n\n".join(parts)

    def get_input_images(self):
        """Collect images for multimodal input"""
        images = []
        if "Images" in self.inputs and self.inputs["Images"].is_linked:
            for link in self.inputs["Images"].links:
                from_node = link.from_node
                if hasattr(from_node, 'get_all_image_paths'):
                    paths = from_node.get_all_image_paths()
                    for p in paths:
                        if p and os.path.exists(p) and p not in images:
                            images.append(p)
                elif hasattr(from_node, 'get_image_path'):
                    # Pass socket name if supported (though Image socket usually generic here)
                    try:
                        p = from_node.get_image_path(link.from_socket.name)
                    except TypeError:
                        p = from_node.get_image_path()

                    if p and os.path.exists(p) and p not in images:
                        images.append(p)
        return images

    def get_output_prompt(self):
        return self.output_text if self.output_text else ""