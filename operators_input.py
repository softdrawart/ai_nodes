# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Input Operators
Reference images, prompts, presets, and input management.
"""

import os
import re
import json
import threading
from datetime import datetime

import bpy
from bpy.types import Operator

from .constants import (
    STYLE_OPTIONS, LIGHTING_ITEMS, MODIFIERS_MAP,
    CREATIVE_UPGRADE_PROMPT, EDITING_UPGRADE_PROMPT, EDITING_UPGRADE_PROMPT_LOOSE,
    DEFAULT_TEXTURE_PROMPT, DEFAULT_TEXTURE_REF_PROMPT,
    get_presets_file
)
from .utils import (
    get_api_keys, get_all_api_keys, get_generations_folder,
    refresh_previews_and_collections,
    get_conversation_turn_count, clear_conversation_history,
    get_fal_text_provider, get_text_api_key_for_fal
)


# =============================================================================
# THOUGHT HISTORY
# =============================================================================

class NEURO_OT_clear_thought_history(Operator):
    """Clear thought signature conversation history"""
    bl_idname = "neuro.clear_thought_history"
    bl_label = "Clear Session"
    bl_description = "Clear multi-turn conversation history (start fresh)"

    def execute(self, context):
        turns = get_conversation_turn_count()
        clear_conversation_history()
        self.report({'INFO'}, f"Cleared {turns} conversation turn(s)")
        return {'FINISHED'}


# =============================================================================
# REFERENCE IMAGE OPERATORS
# =============================================================================

class NEURO_OT_add_reference_image(Operator):
    """Add selected image in Image Editor as reference"""
    bl_idname = "neuro.add_reference_image"
    bl_label = "Add Active Image"

    def execute(self, context):
        scn = context.scene
        img = getattr(context.space_data, "image", None)
        if not img:
            self.report({'ERROR'}, "No active image found")
            return {'CANCELLED'}

        path = bpy.path.abspath(img.filepath) if img.filepath else ""

        if not path or img.source == 'VIEWER' or not os.path.exists(path):
            blend_dir = bpy.path.abspath("//")
            if not blend_dir or blend_dir == "//":
                import tempfile
                ref_dir = os.path.join(tempfile.gettempdir(), "Blender_AI_Generations", "references")
            else:
                ref_dir = os.path.join(blend_dir, "generations", "references")

            os.makedirs(ref_dir, exist_ok=True)

            img_name = img.name if img.name else "untitled"
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', img_name)
            safe_name = os.path.splitext(safe_name)[0]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_name}_{timestamp}.png"
            save_path = os.path.join(ref_dir, filename)

            try:
                img.save_render(save_path)
                path = save_path
                self.report({'INFO'}, f"Saved '{img.name}' as reference")
            except Exception as e:
                self.report({'ERROR'}, f"Failed to save image: {e}")
                return {'CANCELLED'}

        ref = scn.neuro_reference_images.add()
        ref.path = path
        refresh_previews_and_collections(scn)

        if len(scn.neuro_reference_images) == 1:
            scn.neuro_use_ref_influence = True

        return {'FINISHED'}


class NEURO_OT_add_reference_from_disk(Operator):
    """Add reference image(s) from disk - supports multiple selection"""
    bl_idname = "neuro.add_reference_from_disk"
    bl_label = "Add from Disk"

    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_glob: bpy.props.StringProperty(default="*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tiff;*.tga", options={'HIDDEN'})

    def execute(self, context):
        scn = context.scene
        added = 0

        if self.files:
            for file_elem in self.files:
                if file_elem.name:
                    filepath = os.path.join(self.directory, file_elem.name)
                    if os.path.isfile(filepath):
                        ref = scn.neuro_reference_images.add()
                        ref.path = bpy.path.abspath(filepath)
                        added += 1

        if added > 0:
            refresh_previews_and_collections(scn)
            self.report({'INFO'}, f"Added {added} reference image(s)")
            scn.neuro_use_ref_influence = True
        else:
            self.report({'WARNING'}, "No valid images selected")

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class NEURO_OT_add_reference_from_clipboard(Operator):
    """Grab an image from the system clipboard and add it as a reference"""
    bl_idname = "neuro.add_reference_from_clipboard"
    bl_label = "Add from Clipboard"

    def execute(self, context):
        try:
            from PIL import ImageGrab
        except ImportError:
            self.report({'ERROR'}, "PIL not available")
            return {'CANCELLED'}

        scn = context.scene
        try:
            img = ImageGrab.grabclipboard()
            if not img:
                self.report({'ERROR'}, "No image found in clipboard")
                return {'CANCELLED'}

            blend_dir = bpy.path.abspath("//")
            if not blend_dir or blend_dir == "//":
                self.report({'ERROR'}, "Save .blend file first")
                return {'CANCELLED'}

            ref_dir = os.path.join(blend_dir, "generations", "references")
            os.makedirs(ref_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"clipboard_ref_{timestamp}.png"
            path = os.path.join(ref_dir, filename)

            img.save(path, format="PNG")
            ref = scn.neuro_reference_images.add()
            ref.path = path
            refresh_previews_and_collections(scn)
            scn.neuro_use_ref_influence = True
            self.report({'INFO'}, "Added image from clipboard")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Clipboard read failed: {e}")
            return {'CANCELLED'}


class NEURO_OT_remove_reference(Operator):
    """Remove reference image from list"""
    bl_idname = "neuro.remove_reference"
    bl_label = "Remove Reference"
    index: bpy.props.IntProperty()

    def execute(self, context):
        scn = context.scene
        if 0 <= self.index < len(scn.neuro_reference_images):
            scn.neuro_reference_images.remove(self.index)
            refresh_previews_and_collections(scn)
        return {'FINISHED'}


class NEURO_OT_clear_all_references(Operator):
    """Clear all reference images"""
    bl_idname = "neuro.clear_all_references"
    bl_label = "Clear All"

    def execute(self, context):
        context.scene.neuro_reference_images.clear()
        refresh_previews_and_collections(context.scene)
        return {'FINISHED'}


class NEURO_OT_replace_reference(Operator):
    """Replace first reference image with this generated image"""
    bl_idname = "neuro.replace_reference"
    bl_label = "Replace Input"
    bl_description = "Replace the first reference image with this generated image"

    path: bpy.props.StringProperty()

    def execute(self, context):
        scn = context.scene
        p = self.path

        if not os.path.exists(p):
            self.report({'ERROR'}, "File not found")
            return {'CANCELLED'}

        if len(scn.neuro_reference_images) > 0:
            scn.neuro_reference_images.remove(0)

        ref = scn.neuro_reference_images.add()
        ref.path = p

        scn.neuro_reference_images.move(len(scn.neuro_reference_images) - 1, 0)

        refresh_previews_and_collections(scn)
        self.report({'INFO'}, "Replaced first reference image")
        return {'FINISHED'}


# =============================================================================
# PROMPT TEMPLATE OPERATORS
# =============================================================================

class NEURO_OT_load_texture_pattern(Operator):
    """Load texture generation prompt pattern"""
    bl_idname = "neuro.load_texture_pattern"
    bl_label = "Load Pattern"
    bl_description = "Fill prompt with texture generation pattern"

    def execute(self, context):
        context.scene.neuro_prompt = DEFAULT_TEXTURE_PROMPT
        self.report({'INFO'}, "Loaded texture pattern - replace [object_name] with your description")
        return {'FINISHED'}


class NEURO_OT_load_texture_ref_pattern(Operator):
    """Load texture generation prompt pattern with reference"""
    bl_idname = "neuro.load_texture_ref_pattern"
    bl_label = "Ref Template"
    bl_description = "Fill prompt with texture pattern that uses reference images for inspiration"

    def execute(self, context):
        context.scene.neuro_prompt = DEFAULT_TEXTURE_REF_PROMPT
        self.report({'INFO'}, "Loaded reference texture pattern - replace [object_name]")
        return {'FINISHED'}


# =============================================================================
# PRESET OPERATORS
# =============================================================================

class NEURO_OT_save_builder_presets(Operator):
    """Save current builder options to a JSON file for editing"""
    bl_idname = "neuro.save_builder_presets"
    bl_label = "Save Presets"

    def execute(self, context):
        data = {
            "_instructions": "Edit prompt text for styles/lighting/modifiers_map. JSON Format required.",
            "styles": STYLE_OPTIONS,
            "lighting": LIGHTING_ITEMS,
            "modifiers_map": MODIFIERS_MAP
        }
        try:
            presets_file = get_presets_file()
            with open(presets_file, 'w') as f:
                json.dump(data, f, indent=4)
            self.report({'INFO'}, f"Saved to {presets_file}")
            bpy.ops.wm.path_open(filepath=os.path.dirname(presets_file))
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e}")
        return {'FINISHED'}


class NEURO_OT_load_builder_presets(Operator):
    """Load builder options from JSON file"""
    bl_idname = "neuro.load_builder_presets"
    bl_label = "Load Presets"

    def execute(self, context):
        from . import constants

        presets_file = get_presets_file()
        if not os.path.exists(presets_file):
            self.report({'ERROR'}, "No presets file found")
            return {'CANCELLED'}

        try:
            with open(presets_file, 'r') as f:
                data = json.load(f)
                if "styles" in data:
                    constants.STYLE_OPTIONS = data["styles"]
                if "lighting" in data:
                    constants.LIGHTING_ITEMS = [tuple(x) for x in data["lighting"]]
                if "modifiers_map" in data:
                    loaded_map = data["modifiers_map"]
                    for k in constants.MODIFIERS_MAP.keys():
                        if k in loaded_map:
                            constants.MODIFIERS_MAP[k] = loaded_map[k]

            context.scene.neuro_texture_style = context.scene.neuro_texture_style
            self.report({'INFO'}, "Presets loaded successfully")

        except Exception as e:
            self.report({'ERROR'}, f"Load failed: {e}")

        return {'FINISHED'}


# =============================================================================
# PROMPT OPERATORS
# =============================================================================

class NEURO_OT_upgrade_prompt(Operator):
    """Analyze reference images or text and upgrade the prompt using LLM"""
    bl_idname = "neuro.upgrade_prompt"
    bl_label = "Upgrade Prompt"
    bl_description = "Use AI to enhance and detail your prompt (Context aware)"

    def execute(self, context):
        from .api import generate_text

        scn = context.scene
        original_prompt = scn.neuro_prompt_image.strip()

        if not original_prompt:
            self.report({'ERROR'}, "Please enter a prompt first")
            return {'CANCELLED'}

        # Get the active provider
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        active_provider = prefs.active_provider if prefs else 'google'
        api_keys = get_all_api_keys(context)

        # Determine which provider to use for text operations
        if active_provider == 'fal':
            # Fal has no LLM - need fallback
            text_provider, _ = get_text_api_key_for_fal(context)
            if not text_provider:
                self.report({'ERROR'}, "Fal has no LLM. Enable Google or Replicate in Settings > Text/LLM Source")
                return {'CANCELLED'}
            active_provider = text_provider
            provider_display = f"via {text_provider.title()}"
        else:
            provider_display = active_provider.title()

        # Map selected upgrade model to provider-specific model ID
        selected_model = scn.neuro_upgrade_model.lower() if scn.neuro_upgrade_model else ""

        # Detect base model type
        if "gemini-3-flash" in selected_model:
            base = "gemini-3-flash"
        elif "gemini-3-pro" in selected_model:
            base = "gemini-3-pro"
        elif "gpt-5-nano" in selected_model:
            base = "gpt-5-nano"
        elif "gpt-5.1" in selected_model:
            base = "gpt-5.1"
        elif "gpt-5.2" in selected_model:
            base = "gpt-5.2"
        else:
            base = "gemini-3-pro"  # Default

        # Build provider-specific model ID
        if active_provider == 'google' and base.startswith('gemini'):
            model_id = f"{base}-preview"
        elif active_provider == 'google' and base.startswith('gpt'):
            # Google doesn't have GPT models, use gemini instead
            model_id = "gemini-3-pro-preview"
        elif active_provider == 'replicate':
            model_id = f"{base}-repl"
        else:  # aiml
            model_id = f"{base}-aiml"

        refs = [r.path for r in scn.neuro_reference_images if os.path.exists(r.path)]

        has_history = scn.neuro_use_thought_signatures and get_conversation_turn_count() > 0
        is_editing_mode = bool(refs) or has_history
        use_strict = scn.neuro_upgrade_strict

        if is_editing_mode:
            if use_strict:
                upgrade_template = EDITING_UPGRADE_PROMPT
                mode_text = "Editing (Strict)"
            else:
                upgrade_template = EDITING_UPGRADE_PROMPT_LOOSE
                mode_text = "Editing (Loose)"
        else:
            upgrade_template = CREATIVE_UPGRADE_PROMPT
            mode_text = "Creative"

        scn.neuro_prompt_backup = original_prompt
        scn.neuro_status = f"Upgrading ({mode_text}) via {provider_display}..."
        scn.neuro_is_generating = True
        scn.neuro_progress = 0.0

        # Build full prompt with template
        full_prompt = f"{upgrade_template}\n\nOriginal prompt to upgrade:\n{original_prompt}"

        # Get model config defaults for required params
        from .model_registry import get_model
        config = get_model(model_id)
        model_params = {}
        if config and config.params:
            for param in config.params:
                model_params[param.name] = param.default

        def worker_job(prompt_text, refs_local, model, keys, params, timeout):
            error_msg = None
            upgraded = None
            try:
                upgraded = generate_text(
                    prompt=prompt_text,
                    image_paths=refs_local,
                    model_id=model,
                    api_keys=keys,
                    model_params=params,
                    timeout=timeout
                )
            except TimeoutError:
                error_msg = "timeout"
            except Exception as e:
                error_msg = str(e)
                print(f"[{LOG_PREFIX}] Upgrade prompt exception:", e)

            def main_thread_update():
                scn_inner = bpy.context.scene
                scn_inner.neuro_is_generating = False
                scn_inner.neuro_progress = 0.0

                if upgraded:
                    scn_inner.neuro_prompt_image = upgraded
                    scn_inner.neuro_status = "Prompt upgraded successfully!"
                else:
                    if error_msg == "timeout":
                        scn_inner.neuro_status = "Prompt upgrade timed out"
                    elif error_msg and "503" in error_msg:
                        scn_inner.neuro_status = "Server Overloaded (503). Try again."
                    elif error_msg and "429" in error_msg:
                        scn_inner.neuro_status = "Quota Exceeded (429)."
                    else:
                        scn_inner.neuro_status = "Upgrade failed (Check Console)"

                return None

            bpy.app.timers.register(main_thread_update, first_interval=0.2)

        threading.Thread(target=worker_job,
                         args=(full_prompt, refs, model_id, api_keys, model_params, scn.neuro_timeout),
                         daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_revert_prompt(Operator):
    """Revert to original prompt before upgrade"""
    bl_idname = "neuro.revert_prompt"
    bl_label = "Revert Prompt"
    bl_description = "Restore the original prompt before upgrade"

    def execute(self, context):
        scn = context.scene
        if scn.neuro_prompt_backup:
            if scn.neuro_input_mode == 'IMAGE':
                scn.neuro_prompt_image = scn.neuro_prompt_backup
            else:
                scn.neuro_prompt_texture = scn.neuro_prompt_backup

            scn.neuro_status = "Prompt reverted to original"
            self.report({'INFO'}, "Reverted to original prompt")
        else:
            self.report({'WARNING'}, "No backup prompt available")
        return {'FINISHED'}


class NEURO_OT_copy_prompt(Operator):
    """Copy prompt to clipboard"""
    bl_idname = "neuro.copy_prompt"
    bl_label = "Copy Prompt"

    prompt_text: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        if properties.prompt_text:
            return f"Click to copy:\n{properties.prompt_text}"
        return "Copy this prompt to clipboard"

    def execute(self, context):
        context.window_manager.clipboard = self.prompt_text
        self.report({'INFO'}, "Prompt copied to clipboard")
        return {'FINISHED'}


class NEURO_OT_show_full_prompt(Operator):
    """Show full prompt text in a popup"""
    bl_idname = "neuro.show_full_prompt"
    bl_label = "Full Prompt"
    bl_description = "View full prompt text"

    prompt_text: bpy.props.StringProperty()
    prompt_title: bpy.props.StringProperty(default="Prompt")

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.label(text=self.prompt_title, icon='TEXT')
        layout.separator()

        box = layout.box()
        words = self.prompt_text.split()
        line = ""
        max_chars = 60
        for word in words:
            if len(line) + len(word) + 1 <= max_chars:
                line += (" " if line else "") + word
            else:
                if line:
                    box.label(text=line)
                line = word
        if line:
            box.label(text=line)

        layout.separator()
        row = layout.row()
        row.operator("neuro.copy_prompt", text="Copy to Clipboard", icon='COPYDOWN').prompt_text = self.prompt_text


# =============================================================================
# REGISTRATION
# =============================================================================

INPUT_OPERATOR_CLASSES = (
    NEURO_OT_clear_thought_history,
    NEURO_OT_add_reference_image,
    NEURO_OT_add_reference_from_disk,
    NEURO_OT_add_reference_from_clipboard,
    NEURO_OT_remove_reference,
    NEURO_OT_clear_all_references,
    NEURO_OT_replace_reference,
    NEURO_OT_load_texture_pattern,
    NEURO_OT_load_texture_ref_pattern,
    NEURO_OT_save_builder_presets,
    NEURO_OT_load_builder_presets,
    NEURO_OT_upgrade_prompt,
    NEURO_OT_revert_prompt,
    NEURO_OT_copy_prompt,
    NEURO_OT_show_full_prompt,
)


def register():
    for cls in INPUT_OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(INPUT_OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)