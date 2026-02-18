# -*- coding: utf-8 -*-
import threading
import textwrap
import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .utils import get_all_api_keys, get_api_keys, cancel_event, get_fal_text_provider, get_text_api_key_for_fal
from .constants import CREATIVE_UPGRADE_PROMPT, EDITING_UPGRADE_PROMPT, EDITING_UPGRADE_PROMPT_LOOSE
from .nodes_ops_common import get_node_tree


class NEURO_OT_node_generate_text(Operator):
    bl_idname = "neuro.node_generate_text"
    bl_label = "Generate Text"
    node_name: StringProperty()
    tree_name: StringProperty()

    def execute(self, context):
        from .api import generate_text
        from .model_registry import get_model

        ntree = get_node_tree(context, self.tree_name)
        if not ntree:
            self.report({'ERROR'}, "No node tree found")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}

        prompt = node.get_complete_prompt()
        if not prompt.strip():
            self.report({'WARNING'}, "Empty prompt")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)
        model = node.model
        config = get_model(model)

        if config and (rk := config.requires_api_key) and not api_keys.get(rk):
            self.report({'ERROR'}, f"Missing {rk} API key")
            print(f"[{ADDON_NAME_CONFIG}] Text generation cancelled: Missing {rk} API key for model {model}")
            node.status_message = f"Missing {rk} API key"
            return {'CANCELLED'}

        print(f"[{ADDON_NAME_CONFIG}] Starting text generation: model={model}")

        node.is_generating = True
        node.status_message = "Generating..."
        node_name, ntree_name, model_save = node.name, ntree.name, model

        model_params = {}
        try:
            if config:
                for param in config.params:
                    prop = f"param_{param.name}"
                    if hasattr(node, prop): model_params[param.name] = getattr(node, prop)
        except Exception:
            pass

        def worker():
            res = None
            error_msg = None
            try:
                res = generate_text(prompt=prompt, image_paths=node.get_input_images(),
                                    model_id=model, api_keys=api_keys, model_params=model_params, timeout=120)
            except Exception as e:
                error_msg = str(e)[:100]
                print(f"[{LOG_PREFIX}] Text gen error: {e}")

            def update():
                tree = bpy.data.node_groups.get(ntree_name)
                if tree and (n := tree.nodes.get(node_name)):
                    n.is_generating = False
                    if res:
                        n.output_text = res
                        n.status_message = ""
                        n.model_used = model_save
                        n.has_generated = True
                    else:
                        n.status_message = f"Error: {error_msg}" if error_msg else "Failed"
                return None

            bpy.app.timers.register(update, first_interval=0.1)

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_node_cancel_text(Operator):
    bl_idname = "neuro.node_cancel_text"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and (node := ntree.nodes.get(self.node_name)):
            node.is_generating = False
            node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_upgrade_prompt(Operator):
    bl_idname = "neuro.node_upgrade_prompt"
    bl_label = "Upgrade Prompt"
    node_name: StringProperty()
    tree_name: StringProperty()

    def execute(self, context):
        from .api import generate_text
        ntree = get_node_tree(context, self.tree_name)
        node = ntree.nodes.get(self.node_name)
        prompt = node.get_input_prompt()
        if not prompt.strip(): return {'CANCELLED'}

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
            text_provider, api_key = get_text_api_key_for_fal(context)
            if not text_provider or not api_key:
                self.report({'ERROR'}, "Fal has no LLM. Enable Google or Replicate in Settings")
                return {'CANCELLED'}
            active_provider = text_provider  # Use the fallback provider

        # Map node.model base to provider-specific model ID
        # Model IDs follow pattern: {base}-{provider_suffix}
        model_base = node.model.lower() if node.model else ""

        # Detect base model type from the selected model
        if "gemini-3-flash" in model_base:
            base = "gemini-3-flash"
        elif "gemini-3-pro" in model_base:
            base = "gemini-3-pro"
        elif "gpt-5-nano" in model_base:
            base = "gpt-5-nano"
        elif "gpt-5.1" in model_base:
            base = "gpt-5.1"
        elif "gpt-5.2" in model_base:
            base = "gpt-5.2"
        else:
            base = "gemini-3-pro"  # Default

        # Build provider-specific model ID
        provider_suffix = {
            'aiml': '-aiml',
            'replicate': '-repl',
            'google': '-preview' if base.startswith('gemini') else '-repl',
        }

        if active_provider == 'google' and base.startswith('gemini'):
            model_id = f"{base}-preview"
        elif active_provider == 'google' and base.startswith('gpt'):
            # Google doesn't have GPT models, use gemini instead
            model_id = "gemini-3-pro-preview"
        else:
            model_id = f"{base}{provider_suffix.get(active_provider, '-aiml')}"

        templates = {'CREATIVE': CREATIVE_UPGRADE_PROMPT, 'EDITING': EDITING_UPGRADE_PROMPT,
                     'EDITING_LOOSE': EDITING_UPGRADE_PROMPT_LOOSE}
        template = templates.get(node.upgrade_mode, CREATIVE_UPGRADE_PROMPT)
        ref_images = [path] if (path := node.get_reference_image()) else []

        # Build full prompt with template
        full_prompt = f"{template}\n\nOriginal prompt to upgrade:\n{prompt}"

        # Get model config defaults for required params
        from .model_registry import get_model
        config = get_model(model_id)
        model_params = {}
        if config and config.params:
            for param in config.params:
                model_params[param.name] = param.default

        node.is_processing = True
        node.is_upgrading = True
        node.status_message = f"Upgrading via {active_provider}..."
        node_name, ntree_name = node.name, ntree.name

        def worker():
            res = None
            try:
                res = generate_text(
                    prompt=full_prompt,
                    image_paths=ref_images,
                    model_id=model_id,
                    api_keys=api_keys,
                    model_params=model_params,
                    timeout=60
                )
            except Exception as e:
                print(f"[{LOG_PREFIX}] Prompt upgrade error: {e}")

            def update():
                tree = bpy.data.node_groups.get(ntree_name)
                if tree and (n := tree.nodes.get(node_name)):
                    n.is_processing = False
                    n.is_upgrading = False
                    if res:
                        n.output_prompt = res
                        n.status_message = "Upgraded!"
                    else:
                        n.status_message = "Failed"
                return None

            bpy.app.timers.register(update, first_interval=0.1)

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_node_copy_prompt(Operator):
    bl_idname = "neuro.node_copy_prompt"
    bl_label = "Copy"
    prompt_text: StringProperty()

    def execute(self, context):
        context.window_manager.clipboard = self.prompt_text
        self.report({'INFO'}, "Copied")
        return {'FINISHED'}


class NEURO_OT_node_show_prompt(Operator):
    bl_idname = "neuro.node_show_prompt"
    bl_label = "View Prompt"
    prompt_text: StringProperty()
    title: StringProperty(default="Prompt")

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=500)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        l = self.layout
        l.label(text=self.title, icon='TEXT')
        l.separator()
        box = l.box()
        wrapper = textwrap.TextWrapper(width=70)
        for line in self.prompt_text.split('\n'):
            for w in wrapper.wrap(line) if line else [""]: box.label(text=w)
        l.separator()
        l.operator("neuro.node_copy_prompt", text="Copy", icon='COPYDOWN').prompt_text = self.prompt_text


class NEURO_OT_open_text_editor(Operator):
    """Open an internal text editor for a node property"""
    bl_idname = "neuro.open_text_editor"
    bl_label = "Edit Text"
    node_name: StringProperty()
    prop_name: StringProperty(default="prompt")

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node: return {'CANCELLED'}

        # Get current text
        current_text = getattr(node, self.prop_name, "")

        # Create unique text block name
        text_name = f"Node_{node.name}_{self.prop_name}"

        # Create or Get Text Block
        if text_name in bpy.data.texts:
            text_block = bpy.data.texts[text_name]
            # Optional: Overwrite only if empty to prevent data loss?
            # For now, we sync Node -> Text when opening
            text_block.clear()
            text_block.write(current_text)
        else:
            text_block = bpy.data.texts.new(text_name)
            text_block.write(current_text)

        # Try to find an existing text editor area to switch
        for area in context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.spaces[0].text = text_block
                self.report({'INFO'}, f"Opened '{text_name}'")
                return {'FINISHED'}

        # If no editor found, tell user
        self.report({'INFO'}, f"Created '{text_name}'. Open Text Editor view to edit.")
        return {'FINISHED'}


class NEURO_OT_sync_text_to_node(Operator):
    """Sync content from text editor back to node property"""
    bl_idname = "neuro.sync_text_to_node"
    bl_label = "Sync Text"
    bl_description = "Save text from Editor back to Node"
    node_name: StringProperty()
    prop_name: StringProperty(default="prompt")

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node: return {'CANCELLED'}

        text_name = f"Node_{node.name}_{self.prop_name}"
        if text_name in bpy.data.texts:
            content = bpy.data.texts[text_name].as_string()
            setattr(node, self.prop_name, content)
            self.report({'INFO'}, "Text synced to node")
        else:
            self.report({'WARNING'}, "Text block not found")

        return {'FINISHED'}