# -*- coding: utf-8 -*-
import os
import shutil
import time
import threading

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .utils import (
    get_api_keys, get_generations_folder, get_unique_filename,
    sanitize_filename, cancel_event, get_all_api_keys,
)
from .nodes_ops_common import (
    get_node_tree, log_node_generation, log_node_result, get_artist_tool_model
)

# Status tracking
try:
    from . import status_manager

    HAS_STATUS = True
except ImportError:
    HAS_STATUS = False


# =============================================================================
# GENERATION OPERATORS
# =============================================================================

class NEURO_OT_node_generate(Operator):
    bl_idname = "neuro.node_generate"
    bl_label = "Generate"
    node_name: StringProperty()
    tree_name: StringProperty()

    def _ensure_provider_selected(self, context):
        """Auto-select first valid provider if current selection is invalid"""
        from .utils import get_addon_name
        try:
            addon_name = get_addon_name()
            if not addon_name or addon_name not in context.preferences.addons:
                return

            prefs = context.preferences.addons[addon_name].preferences
            scn = context.scene

            # Check if current provider is valid (enabled AND has working key)
            current = prefs.active_provider
            current_valid = False

            if current == 'aiml' and prefs.provider_aiml_enabled:
                if getattr(scn, 'neuro_aiml_status', False) or prefs.aiml_api_key:
                    current_valid = True
            elif current == 'google' and prefs.provider_google_enabled:
                if getattr(scn, 'neuro_google_status', False) or prefs.google_api_key:
                    current_valid = True
            elif current == 'fal' and prefs.provider_fal_enabled:
                if getattr(scn, 'neuro_fal_status', False) or prefs.fal_api_key:
                    current_valid = True
            elif current == 'replicate' and prefs.provider_replicate_enabled:
                if getattr(scn, 'neuro_replicate_status', False) or prefs.replicate_api_key:
                    current_valid = True

            if current_valid:
                return

            # Auto-select first valid provider (priority: AIML > Google > Fal > Replicate)
            if prefs.provider_aiml_enabled and prefs.aiml_api_key:
                prefs.active_provider = 'aiml'
                print(f"[{LOG_PREFIX}] Auto-selected AIML provider")
            elif prefs.provider_google_enabled and prefs.google_api_key:
                prefs.active_provider = 'google'
                print(f"[{LOG_PREFIX}] Auto-selected Google provider")
            elif prefs.provider_fal_enabled and prefs.fal_api_key:
                prefs.active_provider = 'fal'
                print(f"[{LOG_PREFIX}] Auto-selected Fal provider")
            elif prefs.provider_replicate_enabled and prefs.replicate_api_key:
                prefs.active_provider = 'replicate'
                print(f"[{LOG_PREFIX}] Auto-selected Replicate provider")
        except Exception as e:
            print(f"[{LOG_PREFIX}] Auto-select provider error: {e}")

    def execute(self, context):
        from .utils import get_all_api_keys, get_addon_name
        from .model_registry import get_model, Provider

        # Auto-select first valid provider if none selected
        self._ensure_provider_selected(context)

        ntree = get_node_tree(context, self.tree_name)
        if not ntree:
            self.report({'ERROR'}, "No node tree found")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}

        prompt = node.get_input_prompt() if hasattr(node, 'get_input_prompt') else node.prompt
        if not prompt.strip():
            self.report({'WARNING'}, "Empty prompt")
            return {'CANCELLED'}

        # Inpaint: wrap prompt so model only edits the painted area
        if getattr(node, 'use_inpaint', False):
            prompt = (
                f"Edit ONLY the area marked with bright purple paint in this image. "
                f"Do not modify, regenerate, or alter anything outside the painted zone — "
                f"preserve all unpainted pixels exactly as they are. "
                f"Inside the painted purple area: {prompt}"
            )

        api_keys = get_all_api_keys(context)
        model = node.model

        # Check if we have the required API key for this model
        config = get_model(model)
        if config:
            required_key = config.requires_api_key
            if not api_keys.get(required_key, "").strip():
                self.report({'ERROR'}, f"Missing API key: {required_key}")
                print(f"[{ADDON_NAME_CONFIG}] Generation cancelled: Missing {required_key} API key for model {model}")
                node.status_message = f"Missing {required_key} key"
                return {'CANCELLED'}
        else:
            # Fallback check
            google_key, fal_key, replicate_key, aiml_key = get_api_keys(context)
            if (model.startswith("gpt") or model.startswith("fal")) and not fal_key:
                self.report({'ERROR'}, "Missing Fal.AI API key")
                return {'CANCELLED'}
            if model.startswith("replicate/") and not replicate_key:
                self.report({'ERROR'}, "Missing Replicate API key")
                return {'CANCELLED'}
            if not model.startswith("gpt") and not model.startswith("fal") and not model.startswith(
                    "replicate/") and not google_key:
                self.report({'ERROR'}, "Missing Google API key")
                return {'CANCELLED'}

        print(f"[{ADDON_NAME_CONFIG}] Starting generation: model={model}, prompt={prompt[:50]}...")

        node.is_generating = True
        node.status_message = "Generating..."
        input_images = node.get_input_images()
        node_name, ntree_name = node.name, ntree.name
        aspect_ratio = node.aspect_ratio
        model_save = model

        # Capture history settings BEFORE starting thread
        use_history = False
        input_history = []
        if hasattr(node, 'should_use_history') and node.should_use_history():
            use_history = True
            if hasattr(node, 'get_input_history'):
                input_history = node.get_input_history()
            print(f"[{ADDON_NAME_CONFIG}] History enabled, input entries: {len(input_history)}")

        # Get model params from registry
        model_params = {}
        is_aiml_model = False
        try:
            from .model_registry import get_model, Provider
            config = get_model(model)
            if config:
                is_aiml_model = (config.provider == Provider.AIML)
                for param in config.params:
                    # Check if node has this param as property
                    prop_name = f"param_{param.name}"
                    if hasattr(node, prop_name):
                        model_params[param.name] = getattr(node, prop_name)
                    else:
                        model_params[param.name] = param.default
        except Exception as e:
            print(f"[{ADDON_NAME_CONFIG}] Error reading model params: {e}")

        # Get resolution from model_params if present (only for models that define it)
        resolution = model_params.get("resolution")  # None if not defined

        # Clean up model_params - remove default/placeholder values that shouldn't be sent to API
        # These cause "Invalid payload" errors on providers that don't support them
        keys_to_remove = []
        for key, value in model_params.items():
            if value == "match_input_image":  # Aspect ratio default
                keys_to_remove.append(key)
            elif value == "1K":  # Resolution default
                keys_to_remove.append(key)
            elif value == "auto":  # Generic "use API default" - not supported by all providers
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del model_params[key]

        # Log generation details - shows what will actually be sent
        all_params = {**model_params}
        # Add node's aspect_ratio only if user selected something non-default
        if aspect_ratio and aspect_ratio != "match_input_image":
            all_params["aspect_ratio"] = aspect_ratio
        # Add resolution only if 2K or 4K
        if resolution and resolution in ("2K", "4K"):
            all_params["resolution"] = resolution
        log_node_generation("Generate/Edit", model, prompt, input_images, all_params)

        # Add job to status queue
        job_id = None
        if HAS_STATUS:
            job_id = status_manager.add_job(prompt[:30], model, "Generate")
            status_manager.start_job(job_id)

        def worker_job():
            from .api import generate_images
            from .dependencies import FAL_AVAILABLE
            result_path, error_msg = None, None
            new_history = None
            start_time = time.time()
            try:
                cancel_event.clear()

                # Dynamic timeout based on model (Pro models need more time)
                timeout = 180 if "pro" in model.lower() else 90

                # use_history and input_history are captured from main thread above

                if use_history:
                    print(f"[{ADDON_NAME_CONFIG}] Calling generate_images with history={len(input_history)} entries")
                    call_kwargs = {
                        "model_id": model,
                        "prompt": prompt,
                        "image_paths": input_images,
                        "num_outputs": 1,
                        "api_keys": api_keys,
                        "timeout": timeout,
                        "aspect_ratio": aspect_ratio,
                        "model_params": model_params,
                        "use_thought_signatures": True,
                        "conversation_history": input_history,
                        "cancel_event": cancel_event,
                    }
                    # Only pass resolution if model defines it
                    if resolution:
                        call_kwargs["resolution"] = resolution
                    result = generate_images(**call_kwargs)
                    imgs, new_history = result
                    print(
                        f"[{ADDON_NAME_CONFIG}] Generation done, new history entries: {len(new_history) if new_history else 0}")
                else:
                    call_kwargs = {
                        "model_id": model,
                        "prompt": prompt,
                        "image_paths": input_images,
                        "num_outputs": 1,
                        "api_keys": api_keys,
                        "timeout": timeout,
                        "aspect_ratio": aspect_ratio,
                        "model_params": model_params,
                        "cancel_event": cancel_event,
                    }
                    # Only pass resolution if model defines it
                    if resolution:
                        call_kwargs["resolution"] = resolution
                    imgs = generate_images(**call_kwargs)

                if imgs and not cancel_event.is_set():
                    gen_dir = get_generations_folder("nodes")
                    filename = get_unique_filename(gen_dir, sanitize_filename(prompt[:25]) or "generated")
                    result_path = os.path.join(gen_dir, filename)
                    imgs[0].save(result_path, format="PNG")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if not cancel_event.is_set(): error_msg = str(e)[:100]

            duration = time.time() - start_time
            log_node_result("Generate/Edit", result_path is not None, result_path, error_msg, duration)

            # Update job status
            if HAS_STATUS and job_id:
                if cancel_event.is_set():
                    status_manager.cancel_job(job_id)
                elif result_path:
                    status_manager.complete_job(job_id, success=True)
                else:
                    status_manager.complete_job(job_id, success=False, error=error_msg)

            # These values will be used in the update closure
            final_history = new_history
            final_result_path = result_path
            final_error = error_msg

            def update():
                tree = bpy.data.node_groups.get(ntree_name)
                if tree:
                    n = tree.nodes.get(node_name)
                    if n:
                        n.is_generating = False
                        if final_result_path:
                            n.result_path = final_result_path
                            n.model_used = model_save
                            n.has_generated = True
                            n.status_message = ""
                            # Add to image history with model
                            if hasattr(n, 'add_to_history'):
                                n.add_to_history(final_result_path, model_save)
                            # Store conversation history for downstream nodes
                            if final_history and hasattr(n, 'set_output_history'):
                                n.set_output_history(final_history)
                                print(
                                    f"[{ADDON_NAME_CONFIG}] Saved {len(final_history)} history entries to node {n.name}")
                            # Refresh AIML balance after successful generation
                            if is_aiml_model:
                                try:
                                    from .operators_providers import refresh_aiml_balance
                                    refresh_aiml_balance()
                                except Exception:
                                    pass
                        elif cancel_event.is_set():
                            n.status_message = "Cancelled"
                        elif final_error:
                            n.status_message = f"Error: {final_error}"
                        else:
                            n.status_message = "Failed"
                return None

            bpy.app.timers.register(update, first_interval=0.1)

        threading.Thread(target=worker_job, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_node_cancel(Operator):
    bl_idname = "neuro.node_cancel"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_generating = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_remove_bg(Operator):
    """Create RemoveBackground node and auto-execute"""
    bl_idname = "neuro.node_remove_bg"
    bl_label = "Remove Background"
    node_name: StringProperty()

    def execute(self, context):
        from .dependencies import FAL_AVAILABLE, REPLICATE_AVAILABLE, REMBG_AVAILABLE
        from .utils import get_all_api_keys

        api_keys = get_all_api_keys(context)

        # Check if any BG removal provider is available
        has_replicate = REPLICATE_AVAILABLE and api_keys.get("replicate", "").strip()
        has_fal = FAL_AVAILABLE and api_keys.get("fal", "").strip()
        has_local = REMBG_AVAILABLE

        if not has_replicate and not has_fal and not has_local:
            self.report({'WARNING'}, "No Background Removal tool available. Check Preferences > Local Tools.")
            return {'CANCELLED'}

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        source_node = ntree.nodes.get(self.node_name)
        if not source_node:
            return {'CANCELLED'}

        # Get image path from source node
        image_path = None
        if hasattr(source_node, 'result_path') and source_node.result_path:
            image_path = source_node.result_path
        elif hasattr(source_node, 'get_image_path'):
            image_path = source_node.get_image_path()

        if not image_path or not os.path.exists(image_path):
            self.report({'WARNING'}, "No image to process")
            return {'CANCELLED'}

        # Create new RemoveBackground node
        rembg_node = ntree.nodes.new('NeuroRemoveBackgroundNode')
        rembg_node.location = (source_node.location.x + source_node.width + 50, source_node.location.y)
        rembg_node.label = "Remove BG"

        # Connect source node to rembg node
        if "Image Out" in source_node.outputs:
            ntree.links.new(source_node.outputs["Image Out"], rembg_node.inputs["Image"])
        elif "Image" in source_node.outputs:
            ntree.links.new(source_node.outputs["Image"], rembg_node.inputs["Image"])

        # Auto-execute the remove background operation
        bpy.ops.neuro.node_rembg_execute(node_name=rembg_node.name)

        self.report({'INFO'}, "Created RemoveBackground node")
        return {'FINISHED'}

# =============================================================================
# INPAINT OPERATORS
# =============================================================================

class NEURO_OT_node_create_inpaint(Operator):
    """Create Inpaint node from current image and open Paint Mode"""
    bl_idname = "neuro.node_create_inpaint"
    bl_label = "Inpaint"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        source_node = ntree.nodes.get(self.node_name)
        if not source_node:
            return {'CANCELLED'}

        # Get image from source node
        image_path = None
        if hasattr(source_node, 'result_path') and source_node.result_path:
            image_path = source_node.result_path
        elif hasattr(source_node, 'get_image_path'):
            image_path = source_node.get_image_path()

        if not image_path or not os.path.exists(image_path):
            self.report({'WARNING'}, "No image to inpaint")
            return {'CANCELLED'}

        # Copy image so painting doesn't modify original
        import shutil
        gen_dir = get_generations_folder("nodes")
        base = os.path.splitext(os.path.basename(image_path))[0]
        copy_name = get_unique_filename(gen_dir, f"{base}_inpaint")
        copy_path = os.path.join(gen_dir, copy_name)
        shutil.copy2(image_path, copy_path)

        # Create Inpaint node
        inpaint_node = ntree.nodes.new('NeuroInpaintNode')
        inpaint_node.location = (
            source_node.location.x + source_node.width + 50,
            source_node.location.y
        )
        inpaint_node.label = "Inpaint"

        # Load image into preview (no socket connection!)
        inpaint_node.result_path = copy_path
        if hasattr(inpaint_node, 'add_to_history'):
            inpaint_node.add_to_history(copy_path, "source")

        # Auto-open Paint Mode on the new node
        try:
            bpy.ops.neuro.node_open_paint(node_name=inpaint_node.name)
        except Exception as e:
            print(f"[{LOG_PREFIX} Inpaint] Could not auto-open paint: {e}")
            self.report({'INFO'}, "Inpaint node created — click Paint to mark zone")

        self.report({'INFO'}, "Paint the zone, then type prompt and click Inpaint")
        return {'FINISHED'}


class NEURO_OT_node_inpaint_generate(Operator):
    """Generate inpainted image — edits only the purple-painted zone"""
    bl_idname = "neuro.node_inpaint_generate"
    bl_label = "Inpaint Generate"
    node_name: StringProperty()
    tree_name: StringProperty(default="")

    def execute(self, context):
        from .utils import get_all_api_keys
        from .api import generate_images
        from .nodes_ops_common import get_artist_tool_model, log_node_generation, log_node_result
        from .nodes_core import start_background_timer

        ntree = get_node_tree(context, self.tree_name)
        if not ntree:
            self.report({'ERROR'}, "No node tree found")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}

        if not node.prompt.strip():
            self.report({'WARNING'}, "Empty prompt — describe what to generate in the zone")
            return {'CANCELLED'}

        if not node.result_path or not os.path.exists(node.result_path):
            self.report({'WARNING'}, "No image — load an image first")
            return {'CANCELLED'}

        api_keys = get_all_api_keys(context)

        # Select model: PRO or Flash
        tool_type = 'pro' if node.use_pro_model else 'nano'
        model = get_artist_tool_model(context, tool_type)

        # Wrap prompt with inpaint instruction
        user_prompt = node.prompt.strip()
        user_prompt = node.prompt.strip()

        if node.use_pro_model:
            # Banana Pro /edit endpoint understands editing natively
            # Keep prompt clean and direct
            prompt = (
                f"In this image there is an area marked with bright purple/magenta paint. "
                f"Replace that painted area with: {user_prompt}. "
                f"Keep everything outside the purple area unchanged."
            )
        else:
            # Nano Banana needs explicit detailed instructions
            prompt = (
                f"Edit ONLY the area marked with bright purple/magenta paint in this image. "
                f"Do not modify, regenerate, or alter anything outside the painted zone — "
                f"preserve all unpainted pixels exactly as they are. "
                f"Adjust changes to fit composition. Remove painted purple area after editing."
                f"Inside the painted purple area: {user_prompt} "
            )

        # Collect images: main (painted) + references from sockets
        input_images = node.get_input_images()

        # Build model params for pro model (resolution)
        model_params = {}
        resolution = "1K"
        if node.use_pro_model:
            resolution = node.param_resolution
            if resolution in ("2K", "4K"):
                model_params["resolution"] = resolution

        node.is_generating = True
        node.status_message = "Generating..."
        start_background_timer()

        node_name = node.name
        ntree_name = ntree.name
        model_save = model

        log_node_generation("Inpaint", model, prompt, input_images)

        # Status tracking
        job_id = None
        try:
            from . import status_manager
            job_id = status_manager.add_job(prompt[:30], model, "Inpaint")
            status_manager.start_job(job_id)
        except ImportError:
            pass

        def worker():
            result_path, error_msg = None, None
            start_time = time.time()
            try:
                cancel_event.clear()
                timeout = 180 if "pro" in model.lower() else 90

                imgs = generate_images(
                    model_id=model,
                    prompt=prompt,
                    image_paths=input_images,
                    num_outputs=1,
                    api_keys=api_keys,
                    timeout=timeout,
                    resolution=resolution,
                    model_params=model_params,
                    cancel_event=cancel_event,
                )

                if imgs and not cancel_event.is_set():
                    gen_dir = get_generations_folder("nodes")
                    filename = get_unique_filename(
                        gen_dir, sanitize_filename(user_prompt[:25]) or "inpaint"
                    )
                    result_path = os.path.join(gen_dir, filename)
                    imgs[0].save(result_path, format="PNG")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if not cancel_event.is_set():
                    error_msg = str(e)[:100]

            duration = time.time() - start_time
            log_node_result("Inpaint", result_path is not None, result_path, error_msg, duration)

            # Update status
            if job_id:
                try:
                    from . import status_manager
                    if cancel_event.is_set():
                        status_manager.cancel_job(job_id)
                    elif result_path:
                        status_manager.complete_job(job_id, success=True)
                    else:
                        status_manager.complete_job(job_id, success=False, error=error_msg)
                except Exception:
                    pass

            final_path = result_path
            final_error = error_msg

            def update():
                tree = bpy.data.node_groups.get(ntree_name)
                if tree:
                    n = tree.nodes.get(node_name)
                    if n:
                        n.is_generating = False
                        if final_path:
                            n.result_path = final_path
                            n.model_used = model_save
                            n.has_generated = True
                            n.status_message = ""
                            if hasattr(n, 'add_to_history'):
                                n.add_to_history(final_path, model_save)
                        elif cancel_event.is_set():
                            n.status_message = "Cancelled"
                        elif final_error:
                            n.status_message = f"Error: {final_error}"
                        else:
                            n.status_message = "Failed"
                return None

            bpy.app.timers.register(update, first_interval=0.1)

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_node_inpaint_cancel(Operator):
    """Cancel inpaint generation"""
    bl_idname = "neuro.node_inpaint_cancel"
    bl_label = "Cancel Inpaint"
    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_generating = False
                node.status_message = "Cancelled"
        return {'FINISHED'}

# =============================================================================
# REMOVE BACKGROUND NODE OPERATORS
# =============================================================================

class NEURO_OT_node_rembg_execute(Operator):
    """Execute background removal on RemoveBackground node"""
    bl_idname = "neuro.node_rembg_execute"
    bl_label = "Remove Background"
    node_name: StringProperty()

    def execute(self, context):
        from .api import remove_background
        from .utils import get_all_api_keys
        from .dependencies import FAL_AVAILABLE, REPLICATE_AVAILABLE, REMBG_AVAILABLE

        api_keys = get_all_api_keys(context)

        # Check if any BG removal provider is available
        has_replicate = REPLICATE_AVAILABLE and api_keys.get("replicate", "").strip()
        has_fal = FAL_AVAILABLE and api_keys.get("fal", "").strip()
        has_local = REMBG_AVAILABLE

        if not has_replicate and not has_fal and not has_local:
            self.report({'WARNING'}, "No Background Removal tool available. Check Preferences > Local Tools.")
            return {'CANCELLED'}

        # Get active provider
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break
        active_provider = prefs.active_provider if prefs else 'replicate'

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get input image
        image_path = node.get_input_image()
        if not image_path:
            self.report({'WARNING'}, "No input image connected")
            return {'CANCELLED'}

        node.status_message = "Removing BG..."
        node.is_processing = True
        node_name, ntree_name = node.name, ntree.name

        def worker():
            result = None
            try:
                result = remove_background(image_path, api_keys, active_provider)
            except Exception as e:
                print(f"[{LOG_PREFIX}] RemBG error: {e}")

            def update():
                tree = bpy.data.node_groups.get(ntree_name)
                if tree and (n := tree.nodes.get(node_name)):
                    n.is_processing = False
                    if result and os.path.exists(result):
                        gen_dir = get_generations_folder("nodes/rembg")
                        new_path = os.path.join(gen_dir, os.path.basename(result))
                        shutil.move(result, new_path)
                        n.result_path = new_path
                        n.status_message = "Done!"
                        # Add to history
                        n.add_to_history(new_path)
                    else:
                        n.status_message = "Failed"
                return None

            bpy.app.timers.register(update, first_interval=0.1)

        threading.Thread(target=worker, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_node_rembg_cancel(Operator):
    """Cancel background removal"""
    bl_idname = "neuro.node_rembg_cancel"
    bl_label = "Cancel"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                node.is_processing = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_node_rembg_history_nav(Operator):
    """Navigate through image history"""
    bl_idname = "neuro.node_rembg_history_nav"
    bl_label = "Navigate History"
    node_name: StringProperty()
    direction: bpy.props.IntProperty(default=1)

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        history = node.get_history_list()
        if not history:
            return {'CANCELLED'}

        new_index = node.history_index + self.direction
        new_index = max(0, min(new_index, len(history) - 1))

        if new_index != node.history_index:
            node.history_index = new_index
            node.result_path = history[new_index]

        return {'FINISHED'}