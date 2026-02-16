# -*- coding: utf-8 -*-
import os
import bpy
from bpy.props import StringProperty, IntProperty, EnumProperty
from bpy.types import Operator

from .utils import (
    get_all_api_keys, cancel_event, get_generations_folder,
    get_unique_filename, check_is_saved
)
from .nodes_ops_common import (
    get_node_tree, get_artist_tool_model, run_node_worker,
    save_generation_result, log_node_generation
)


# =============================================================================
# ARTIST TOOLS OPERATORS
# =============================================================================

class NEURO_OT_node_artist_describe(Operator):
    """Analyze image and generate numbered list of objects"""
    bl_idname = "neuro.node_artist_describe"
    bl_label = "Analyze Image"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_text

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        input_image = node.get_input_image()
        if not input_image or not os.path.exists(input_image):
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Get appropriate text model based on provider (Fal doesn't have text, will fallback)
        model_id = get_artist_tool_model(context, 'text')

        # Check we have the required API key
        if not api_keys.get("google") and not api_keys.get("replicate"):
            # Simple check - more robust check is done inside generate_text
            pass

        node.is_processing = True
        node.status_message = "Analyzing..."
        node.description_result = ""
        node.selected_line = ""
        node.selected_index = -1

        node_name = node.name
        ntree_name = ntree.name

        # Improved prompt that requests direct list format without preamble
        prompt = """List all distinct objects, elements, or subjects visible in this image.

Output ONLY a numbered list with NO introduction or explanation:
1. [item]
2. [item]
3. [item]

Rules:
- One item per line
- Be specific and concise
- Include colors/features only if needed for identification
- Order from most to least prominent
- Start directly with "1." - no intro text"""

        # Log generation details
        log_node_generation("Artist Tools: Describe", model_id, prompt, [input_image], {"thinking_level": "high"})

        def do_work():
            result = generate_text(
                prompt=prompt,
                image_paths=[input_image],
                model_id=model_id,
                api_keys=api_keys,
                model_params={"thinking_level": "high"},
                timeout=60
            )
            # Clean up any unwanted prefix if model still adds one
            if result:
                lines = result.strip().split('\n')
                # Find first line that starts with a number
                start_idx = 0
                for i, line in enumerate(lines):
                    if line.strip() and line.strip()[0].isdigit():
                        start_idx = i
                        break
                if start_idx > 0:
                    result = '\n'.join(lines[start_idx:])
            return result

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.description_result = result
                n.status_message = ""
            else:
                n.status_message = "Analysis failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Describe")
        return {'FINISHED'}


class NEURO_OT_node_artist_pick_line(Operator):
    """Show popup to pick a line - click to copy to clipboard"""
    bl_idname = "neuro.node_artist_pick_line"
    bl_label = "Pick Line"
    node_name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=400)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        ntree = get_node_tree(context, None)
        if not ntree:
            layout.label(text="No node tree", icon='ERROR')
            return

        node = ntree.nodes.get(self.node_name)
        if not node or not node.description_result:
            layout.label(text="No description available", icon='ERROR')
            return

        layout.label(text="Click to copy to clipboard:", icon='COPYDOWN')
        layout.separator()

        lines = node.description_result.strip().split('\n')
        for i, line in enumerate(lines):
            if line.strip():
                row = layout.row()
                op = row.operator("neuro.node_artist_copy_line", text=line[:60])
                op.line_text = line


class NEURO_OT_node_artist_copy_line(Operator):
    """Copy this line to clipboard (without number prefix)"""
    bl_idname = "neuro.node_artist_copy_line"
    bl_label = "Copy Line"
    line_text: StringProperty()

    def execute(self, context):
        import re
        # Strip "N. " or "N) " prefix from the line
        clean_text = re.sub(r'^\d+[\.\)]\s*', '', self.line_text.strip())
        context.window_manager.clipboard = clean_text
        self.report({'INFO'}, f"Copied: {clean_text[:40]}...")
        return {'FINISHED'}


class NEURO_OT_node_artist_toggle_element(Operator):
    """Toggle element selection"""
    bl_idname = "neuro.node_artist_toggle_element"
    bl_label = "Toggle Element"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()
    element_index: IntProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        node.toggle_element_selection(self.element_index)

        # Force UI redraw
        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


class NEURO_OT_node_artist_clear_selection(Operator):
    """Clear all element selections"""
    bl_idname = "neuro.node_artist_clear_selection"
    bl_label = "Clear Selection"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        node.clear_element_selection()

        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


class NEURO_OT_node_artist_copy_selected(Operator):
    """Copy selected elements to clipboard"""
    bl_idname = "neuro.node_artist_copy_selected"
    bl_label = "Copy Selected"

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        text = node.get_selected_elements_text()
        if text:
            context.window_manager.clipboard = text
            self.report({'INFO'}, f"Copied: {text[:50]}...")
        else:
            self.report({'WARNING'}, "No elements selected")

        return {'FINISHED'}


class NEURO_OT_node_artist_elements_action(Operator):
    """Keep or delete selected elements from image"""
    bl_idname = "neuro.node_artist_elements_action"
    bl_label = "Elements Action"

    node_name: StringProperty()
    action: EnumProperty(
        items=[
            ('KEEP', 'Keep', 'Keep only selected elements, delete everything else'),
            ('DELETE', 'Delete', 'Delete selected elements from image'),
        ],
        default='KEEP'
    )

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        input_image = node.get_input_image()
        if not input_image:
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        elements_text = node.get_selected_elements_text()
        if not elements_text:
            self.report({'ERROR'}, "No elements selected")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Check node's use_pro_model toggle
        use_pro = getattr(node, 'use_pro_model', False)
        model_id = get_artist_tool_model(context, 'pro' if use_pro else 'nano')
        model_save = model_id
        action = self.action

        # Build prompt based on action
        if action == 'KEEP':
            prompt = f"Delete everything except Exception: {elements_text}."
            status_text = "Keeping selected..."
            prefix = "kept"
        else:
            prompt = f"Delete: {elements_text}."
            status_text = "Deleting selected..."
            prefix = "deleted"

        node.is_processing = True
        node.status_message = status_text

        log_node_generation(f"Artist Tools: {action.title()} Elements", model_id, prompt, [input_image],
                            {"elements": elements_text, "pro": use_pro})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=90,
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", prefix)
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, f"Artist Tools: {action.title()} Elements")
        return {'FINISHED'}


# =============================================================================
# STANDARD ARTIST TOOLS (Upscale, Angle, Separation, Multiview)
# =============================================================================

class NEURO_OT_node_artist_upscale(Operator):
    """Upscale/improve image quality"""
    bl_idname = "neuro.node_artist_upscale"
    bl_label = "Upscale"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image:
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model_id = get_artist_tool_model(context, 'pro')
        prompt = node.get_upscale_prompt()
        model_save = model_id

        node.is_processing = True
        node.status_message = "Upscaling..."

        # Log generation details
        log_node_generation("Artist Tools: Upscale", model_id, prompt, [input_image],
                            {"mode": node.upscale_preset, "resolution": "2K"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=90,
                resolution="2K",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "upscaled")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Upscale failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Upscale")
        return {'FINISHED'}


class NEURO_OT_node_artist_angle(Operator):
    """Change image angle/perspective"""
    bl_idname = "neuro.node_artist_angle"
    bl_label = "Change Angle"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image: return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model_id = get_artist_tool_model(context, 'nano')
        prompt = node.get_angle_prompt()
        model_save = model_id

        node.is_processing = True
        node.status_message = "Processing..."

        log_node_generation("Artist Tools: Change Angle", model_id, prompt, [input_image],
                            {"preset": node.angle_preset, "aspect_ratio": "1:1"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=90,
                aspect_ratio="1:1",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "angle_changed")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Change Angle")
        return {'FINISHED'}


class NEURO_OT_node_artist_decompose(Operator):
    """Decompose object into separate elements on a 2x2 grid"""
    bl_idname = "neuro.node_artist_decompose"
    bl_label = "Decompose"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image: return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        # Decompose always uses banana-pro models
        model_id = get_artist_tool_model(context, 'pro')
        prompt = node.get_decompose_prompt()
        model_save = model_id

        node.is_processing = True
        node.status_message = "Decomposing..."

        log_node_generation("Artist Tools: Decompose", model_id, prompt, [input_image],
                            {"aspect_ratio": "1:1", "resolution": "2K"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=120,
                aspect_ratio="1:1",
                resolution="2K",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "decompose")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Decompose failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Decompose")
        return {'FINISHED'}


class NEURO_OT_node_artist_separation(Operator):
    """Separate or delete elements from image"""
    bl_idname = "neuro.node_artist_separation"
    bl_label = "Separation"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image or not node.element_text.strip(): return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Check node's use_pro_model toggle
        use_pro = getattr(node, 'use_pro_model', False)
        model_id = get_artist_tool_model(context, 'pro' if use_pro else 'nano')
        prompt = node.get_separation_prompt()
        model_save = model_id
        mode = node.separation_mode

        node.is_processing = True
        node.status_message = "Keeping..." if mode == 'SEPARATE' else "Deleting..."

        log_node_generation("Artist Tools: Separation", model_id, prompt, [input_image],
                            {"mode": mode, "preserve_form": node.preserve_form})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=90,
                aspect_ratio="1:1",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                prefix = "kept" if mode == 'SEPARATE' else "deleted"
                return save_generation_result(imgs[0], "nodes", prefix)
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Separation")
        return {'FINISHED'}


class NEURO_OT_node_artist_flip(Operator):
    """Flip/Mirror image horizontally or vertically"""
    bl_idname = "neuro.node_artist_flip"
    bl_label = "Flip Image"
    node_name: StringProperty()

    def execute(self, context):
        from PIL import Image

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        input_image = node.get_input_image()
        if not input_image or not os.path.exists(input_image):
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        node.is_processing = True
        node.status_message = "Flipping..."

        direction = node.flip_direction
        ntree_name = ntree.name
        node_name = node.name

        def do_work():
            try:
                img = Image.open(input_image)

                if direction == 'HORIZONTAL':
                    flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
                elif direction == 'VERTICAL':
                    flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
                else:  # BOTH
                    flipped = img.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.FLIP_TOP_BOTTOM)

                # Save result
                gen_dir = get_generations_folder("nodes")
                prefix = f"flipped_{direction.lower()}"
                filename = get_unique_filename(gen_dir, prefix)
                result_path = os.path.join(gen_dir, filename)
                flipped.save(result_path, format="PNG")
                return result_path
            except Exception as e:
                print(f"[{ADDON_NAME_CONFIG}] Flip error: {e}")
                return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = "Pillow (local)"
                n.status_message = ""
                n.add_to_history(result, "Pillow")
            else:
                n.status_message = f"Failed: {error}" if error else "Failed"

        run_node_worker(ntree_name, node_name, do_work, on_complete, "Artist Tools: Flip")
        return {'FINISHED'}


class NEURO_OT_node_artist_cancel(Operator):
    """Cancel artist tool operation"""
    bl_idname = "neuro.node_artist_cancel"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_processing = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_artist_multiview(Operator):
    """Generate multiview (front/left/right/rear)"""
    bl_idname = "neuro.node_artist_multiview"
    bl_label = "Create Multiview"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image: return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model_id = get_artist_tool_model(context, 'pro')
        prompt = node.get_multiview_prompt()
        model_save = model_id

        node.is_processing = True
        node.status_message = "Creating multiview..."

        log_node_generation("Artist Tools: Multiview", model_id, prompt, [input_image],
                            {"aspect_ratio": "1:1", "resolution": "2K"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=120,
                aspect_ratio="1:1",
                resolution="2K",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "multiview")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Generation failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Artist Tools: Multiview")
        return {'FINISHED'}


class NEURO_OT_node_artist_history_nav(Operator):
    """Navigate artist tools history"""
    bl_idname = "neuro.node_artist_history_nav"
    bl_label = "Navigate"
    node_name: StringProperty()
    direction: IntProperty(default=1)

    def execute(self, context):
        bpy.ops.neuro.node_history_nav(node_name=self.node_name, direction=self.direction)
        return {'FINISHED'}


# =============================================================================
# IMAGE SPLITTER OPERATORS
# =============================================================================

class NEURO_OT_node_split_image(Operator):
    """Split 2x2 grid image into 4 separate images"""
    bl_idname = "neuro.node_split_image"
    bl_label = "Split Image"
    node_name: StringProperty()

    def execute(self, context):
        from PIL import Image
        from .nodes_core import node_preview_collection

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image:
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        try:
            # Open and split image
            img = Image.open(input_image)
            w, h = img.size

            half_w = w // 2
            half_h = h // 2

            # Crop quadrants (left, top, right, bottom)
            # Grid layout:  Front | Right
            #               Left  | Back
            front = img.crop((0, 0, half_w, half_h))  # Top-left
            right = img.crop((half_w, 0, w, half_h))  # Top-right
            left = img.crop((0, half_h, half_w, h))  # Bottom-left
            back = img.crop((half_w, half_h, w, h))  # Bottom-right

            # Save to generations/nodes/split subfolder
            gen_dir = get_generations_folder("nodes/split")

            # Generate unique base name - check actual output files
            counter = 1
            while True:
                base = f"split_{counter:03d}"
                if not os.path.exists(os.path.join(gen_dir, f"{base}_front.png")):
                    break
                counter += 1

            front_path = os.path.join(gen_dir, f"{base}_front.png")
            left_path = os.path.join(gen_dir, f"{base}_left.png")
            right_path = os.path.join(gen_dir, f"{base}_right.png")
            back_path = os.path.join(gen_dir, f"{base}_back.png")

            front.save(front_path, format="PNG")
            left.save(left_path, format="PNG")
            right.save(right_path, format="PNG")
            back.save(back_path, format="PNG")

            node.output_paths = {}
            if node.splitter_mode == 'UNIVERSAL':
                node.output_paths = {"A": front_path, "B": left_path, "C": right_path, "D": back_path}
            else:
                node.output_paths = {"Front": front_path, "Left": left_path, "Right": right_path, "Back": back_path}
            # Keep the named attrs for backward compat
            node.front_path = front_path
            node.left_path = left_path
            node.right_path = right_path
            node.back_path = back_path
            node.has_split = True

            # Auto-refresh previews for the new images
            if node_preview_collection is not None:
                for path in [front_path, left_path, right_path, back_path]:
                    try:
                        key = os.path.normpath(os.path.abspath(path))
                        if key in node_preview_collection:
                            del node_preview_collection[key]
                        node_preview_collection.load(key, path, 'IMAGE')
                    except Exception:
                        pass

            self.report({'INFO'}, "Image split into 4 parts")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to split image: {str(e)}")
            return {'CANCELLED'}

        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


# =============================================================================
# DESIGN VARIATIONS NODE OPERATORS
# =============================================================================

class NEURO_OT_node_design_var_simple(Operator):
    """Generate design variations (simple mode)"""
    bl_idname = "neuro.node_design_var_simple"
    bl_label = "Generate Variations"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image:
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model_id = get_artist_tool_model(context, 'pro')
        prompt = node.get_simple_prompt()
        model_save = model_id

        node.is_processing = True
        node.status_message = "Generating variations..."

        log_node_generation("Design Variations: Simple", model_id, prompt, [input_image], {"resolution": "2K"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=120,
                resolution="2K",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "design_var")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Generation failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Design Variations: Simple")
        return {'FINISHED'}


class NEURO_OT_node_design_var_prompts(Operator):
    """Generate prompts using text model (guided mode step 1)"""
    bl_idname = "neuro.node_design_var_prompts"
    bl_label = "Generate Prompts"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_text

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()
        if not input_image:
            self.report({'ERROR'}, "No input image connected")
            return {'CANCELLED'}

        if not node.guided_changes.strip():
            self.report({'ERROR'}, "Please describe the changes you want")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Get active provider and select appropriate Gemini 3 Pro text model
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        active_provider = prefs.active_provider if prefs else 'google'

        # Map provider to Gemini 3 Pro text model
        provider_text_models = {
            'google': 'gemini-3-pro-preview',
            'aiml': 'gemini-3-pro-aiml',
            'replicate': 'gemini-3-pro-repl',
            'fal': 'gemini-3-pro-preview',  # Fal has no text models, fallback to Google
        }
        model_id = provider_text_models.get(active_provider, 'gemini-3-pro-preview')

        # For Fal provider, check if Google key available for text fallback
        if active_provider == 'fal':
            if not api_keys.get("google", ""):
                self.report({'ERROR'}, "Fal has no text models. Enable Google API for text generation.")
                return {'CANCELLED'}

        system_prompt = node.get_guided_system_prompt()
        user_prompt = node.get_guided_user_prompt()
        # User changes come first ("described above task")
        full_prompt = f"{user_prompt}\n\n{system_prompt}"

        node.is_processing = True
        node.status_message = "Generating prompts..."

        log_node_generation("Design Variations: Prompts", model_id, user_prompt, [input_image],
                            {"system_prompt_length": len(system_prompt)})

        def do_work():
            result = generate_text(
                prompt=full_prompt,
                image_paths=[input_image],
                model_id=model_id,
                api_keys=api_keys,
                timeout=90,
            )
            return result

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.generated_prompts = result
                n.prompts_ready = True
                n.status_message = ""
            else:
                n.status_message = "Failed to generate prompts"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Design Variations: Prompts")
        return {'FINISHED'}


class NEURO_OT_node_design_var_edit(Operator):
    """Open prompts in text editor for editing"""
    bl_idname = "neuro.node_design_var_edit"
    bl_label = "Edit Prompts"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)

        # Create/update text datablock
        text_name = f"DesignVar_{node.name}"
        if text_name in bpy.data.texts:
            text = bpy.data.texts[text_name]
            text.clear()
        else:
            text = bpy.data.texts.new(text_name)

        text.write(node.generated_prompts)

        # Try to find existing text editor and set the text
        for area in context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.spaces[0].text = text
                self.report({'INFO'}, f"Editing '{text_name}' - click Save when done")
                return {'FINISHED'}

        self.report({'INFO'}, f"Created '{text_name}' - open Text Editor and select it to edit, then click Save")
        return {'FINISHED'}


class NEURO_OT_node_design_var_save(Operator):
    """Save edited prompts from text editor back to node"""
    bl_idname = "neuro.node_design_var_save"
    bl_label = "Save Prompts"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        text_name = f"DesignVar_{node.name}"
        if text_name in bpy.data.texts:
            node.generated_prompts = bpy.data.texts[text_name].as_string()
            self.report({'INFO'}, "Prompts saved")
        else:
            self.report({'WARNING'}, "No text to save")

        return {'FINISHED'}


class NEURO_OT_node_design_var_reset(Operator):
    """Reset guided mode to start over"""
    bl_idname = "neuro.node_design_var_reset"
    bl_label = "Reset Prompts"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        node.generated_prompts = ""
        node.prompts_ready = False
        node.status_message = ""

        # Clean up text datablock
        text_name = f"DesignVar_{node.name}"
        if text_name in bpy.data.texts:
            bpy.data.texts.remove(bpy.data.texts[text_name])

        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


class NEURO_OT_node_design_var_image(Operator):
    """Generate image from prompts (guided mode step 2)"""
    bl_idname = "neuro.node_design_var_image"
    bl_label = "Generate Image"
    node_name: StringProperty()

    def execute(self, context):
        # Re-use simple var operator logic but with GUIDED mode inputs
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        input_image = node.get_input_image()

        # Check for updated text from editor
        text_name = f"DesignVar_{node.name}"
        if text_name in bpy.data.texts:
            node.generated_prompts = bpy.data.texts[text_name].as_string()

        if not node.generated_prompts.strip():
            self.report({'ERROR'}, "No prompts to generate from")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model_id = get_artist_tool_model(context, 'pro')
        prompt = node.generated_prompts
        model_save = model_id

        node.is_processing = True
        node.status_message = "Generating image..."

        log_node_generation("Design Variations: Guided", model_id, prompt, [input_image], {"resolution": "2K"})

        def do_work():
            imgs = generate_images(
                model_id=model_save,
                prompt=prompt,
                image_paths=[input_image],
                num_outputs=1,
                api_keys=api_keys,
                timeout=120,
                resolution="2K",
                cancel_event=cancel_event,
            )
            if imgs and not cancel_event.is_set():
                return save_generation_result(imgs[0], "nodes", "design_var")
            return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = model_save
                n.status_message = ""
                n.add_to_history(result, model_save)
            else:
                n.status_message = "Generation failed"

        run_node_worker(ntree.name, node.name, do_work, on_complete, "Design Variations: Guided")
        return {'FINISHED'}


class NEURO_OT_node_design_var_cancel(Operator):
    """Cancel design variations operation"""
    bl_idname = "neuro.node_design_var_cancel"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_processing = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_design_var_history_nav(Operator):
    """Navigate design variations history"""
    bl_idname = "neuro.node_design_var_history_nav"
    bl_label = "Navigate"
    node_name: StringProperty()
    direction: IntProperty(default=1)

    def execute(self, context):
        bpy.ops.neuro.node_history_nav(node_name=self.node_name, direction=self.direction)
        return {'FINISHED'}


# =============================================================================
# RELIGHT NODE OPERATORS
# =============================================================================

class NEURO_OT_node_relight_direction(Operator):
    """Set light direction and update prompt"""
    bl_idname = "neuro.node_relight_direction"
    bl_label = "Set Direction"
    node_name: StringProperty()
    direction: StringProperty(default='RIGHT')

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        node.light_direction = self.direction
        node.update_prompt_for_direction()
        return {'FINISHED'}


class NEURO_OT_node_relight_flip(Operator):
    """Flip image horizontally using Pillow"""
    bl_idname = "neuro.node_relight_flip"
    bl_label = "Flip Horizontal"
    node_name: StringProperty()

    def execute(self, context):
        from PIL import Image

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get image - prefer result if exists, else input
        if node.result_path and os.path.exists(node.result_path):
            input_image = node.result_path
        else:
            input_image = node.get_input_image()

        if not input_image or not os.path.exists(input_image):
            self.report({'ERROR'}, "No image to flip")
            return {'CANCELLED'}

        node.is_processing = True
        node.status_message = "Flipping..."

        ntree_name = ntree.name
        node_name = node.name

        def do_work():
            try:
                img = Image.open(input_image)
                flipped = img.transpose(Image.FLIP_LEFT_RIGHT)

                gen_dir = get_generations_folder("nodes")
                filename = get_unique_filename(gen_dir, "relight_flip")
                result_path = os.path.join(gen_dir, filename)
                flipped.save(result_path, format="PNG")
                return result_path
            except Exception as e:
                print(f"[{LOG_PREFIX} Relight] Flip error: {e}")
                return None

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if result:
                n.result_path = result
                n.model_used = "Pillow"
                n.status_message = ""
                n.add_to_history(result, "Pillow")
            else:
                n.status_message = f"Failed: {error}" if error else "Flip failed"

        run_node_worker(ntree_name, node_name, do_work, on_complete, "Relight: Flip")
        return {'FINISHED'}


class NEURO_OT_node_relight_generate(Operator):
    """Generate relighted image using AI"""
    bl_idname = "neuro.node_relight_generate"
    bl_label = "Relight"
    node_name: StringProperty()

    def execute(self, context):
        from .api import generate_images

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get working image: use result (e.g. from flip) if exists, otherwise input socket
        if node.result_path and os.path.exists(node.result_path):
            working_image = node.result_path
        else:
            working_image = node.get_input_image()

        if not working_image or not os.path.exists(working_image):
            self.report({'ERROR'}, "No image to relight")
            return {'CANCELLED'}

        # Get cube reference image based on direction (with saturation applied)
        cube_ref = node.get_saturated_reference()
        prompt = node.relight_prompt

        # DEBUG LOGGING
        print(f"[Relight] Direction: {node.light_direction}")
        print(f"[Relight] ref_left_path: {node.ref_left_path}")
        print(f"[Relight] ref_right_path: {node.ref_right_path}")
        print(f"[Relight] Saturation: {node.ref_saturation}")
        print(f"[Relight] Selected cube_ref: {cube_ref}")
        print(f"[Relight] Working image: {working_image}")
        print(f"[Relight] Prompt: {prompt}")

        if not cube_ref or not os.path.exists(cube_ref):
            self.report({'WARNING'}, "No cube reference image set")

        if not prompt:
            self.report({'ERROR'}, "No prompt")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Get active provider
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        active_provider = prefs.active_provider if prefs else 'aiml'

        # Select model based on provider and pro setting
        # Use actual model IDs from models.py
        if node.use_pro_model:
            model_map = {
                'aiml': 'nano-banana-pro-aiml',
                'google': 'gemini-3-pro-image-preview',
                'replicate': 'nano-banana-pro-repl',
                'fal': 'nano-banana-pro-fal',
            }
        else:
            model_map = {
                'aiml': 'nano-banana-aiml',
                'google': 'gemini-2.5-flash-image',
                'replicate': 'nano-banana-repl',
                'fal': 'nano-banana-fal',
            }

        model_id = model_map.get(active_provider, 'nano-banana-pro-aiml')

        node.is_processing = True
        node.status_message = "Relighting..."

        ntree_name = ntree.name
        node_name_str = node.name

        def do_work():
            try:
                cancel_event.clear()

                # Build image list: working image + cube reference
                image_paths = [working_image]
                if cube_ref and os.path.exists(cube_ref):
                    image_paths.append(cube_ref)

                print(f"[Relight] Sending to API:")
                print(f"[Relight]   Model: {model_id}")
                print(f"[Relight]   Images: {image_paths}")
                print(f"[Relight]   Prompt: {prompt}")

                results = generate_images(
                    model_id=model_id,
                    prompt=prompt,
                    image_paths=image_paths,
                    num_outputs=1,
                    api_keys=api_keys,
                    timeout=120,
                    cancel_event=cancel_event,
                )

                if results and len(results) > 0:
                    gen_dir = get_generations_folder("nodes")
                    filename = get_unique_filename(gen_dir, "relight")
                    result_path = os.path.join(gen_dir, filename)
                    results[0].save(result_path, format="PNG")
                    return result_path, model_id
                return None, None
            except Exception as e:
                print(f"[{LOG_PREFIX} Relight] Error: {e}")
                import traceback
                traceback.print_exc()
                return None, str(e)

        def on_complete(n, result, error, duration):
            n.is_processing = False
            if isinstance(result, tuple) and result[0]:
                path, model = result
                n.result_path = path
                n.model_used = model
                n.status_message = ""
                n.add_to_history(path, model)
            else:
                n.status_message = f"Failed: {error}" if error else "Generation failed"

        run_node_worker(ntree_name, node_name_str, do_work, on_complete, "Relight: Generate")
        return {'FINISHED'}


class NEURO_OT_node_relight_cancel(Operator):
    """Cancel relight operation"""
    bl_idname = "neuro.node_relight_cancel"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_processing = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_relight_history(Operator):
    """Navigate relight history"""
    bl_idname = "neuro.node_relight_history"
    bl_label = "Navigate"
    node_name: StringProperty()
    direction: IntProperty(default=1)

    def execute(self, context):
        bpy.ops.neuro.node_history_nav(node_name=self.node_name, direction=self.direction)
        return {'FINISHED'}


class NEURO_OT_node_relight_load_ref(Operator):
    """Load reference image for relighting"""
    bl_idname = "neuro.node_relight_load_ref"
    bl_label = "Load Reference"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()
    ref_side: StringProperty(default='RIGHT')

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.webp", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath or not os.path.exists(self.filepath):
            self.report({'ERROR'}, "Invalid file")
            return {'CANCELLED'}

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        if self.ref_side == 'LEFT':
            node.ref_left_path = self.filepath
        else:
            node.ref_right_path = self.filepath

        self.report({'INFO'}, f"Loaded {self.ref_side.lower()} reference")
        return {'FINISHED'}


class NEURO_OT_node_relight_select_ref(Operator):
    """Select reference image from Blender's loaded images"""
    bl_idname = "neuro.node_relight_select_ref"
    bl_label = "Select Reference"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "image_name"

    node_name: StringProperty()
    ref_side: StringProperty(default='RIGHT')

    def get_image_items(self, context):
        items = []
        for img in bpy.data.images:
            if img.filepath and not img.filepath.startswith('<'):
                items.append((img.name, img.name, img.filepath))
        if not items:
            items.append(('NONE', "No images loaded", ""))
        return items

    image_name: EnumProperty(
        name="Image",
        items=get_image_items,
        description="Select from loaded Blender images"
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.image_name == 'NONE':
            self.report({'WARNING'}, "No images available")
            return {'CANCELLED'}

        img = bpy.data.images.get(self.image_name)
        if not img or not img.filepath:
            self.report({'ERROR'}, "Image has no filepath")
            return {'CANCELLED'}

        filepath = bpy.path.abspath(img.filepath)
        if not os.path.exists(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        if self.ref_side == 'LEFT':
            node.ref_left_path = filepath
        else:
            node.ref_right_path = filepath

        self.report({'INFO'}, f"Selected {self.image_name}")
        return {'FINISHED'}


class NEURO_OT_node_relight_clear_refs(Operator):
    """Clear reference images to use relighting without references"""
    bl_idname = "neuro.node_relight_clear_refs"
    bl_label = "Clear References"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        node.ref_left_path = ""
        node.ref_right_path = ""

        self.report({'INFO'}, "References cleared")
        return {'FINISHED'}