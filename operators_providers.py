# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Provider & Validation Operators
Provider switching, API key validation, background removal, generation control.
"""

import os
import shutil
import threading

import bpy
from bpy.types import Operator

from .utils import (
    get_api_keys, get_generations_folder,
    refresh_previews_and_collections,
    progress_timer, cancel_event, temp_files_registry,
    cleanup_temp_files
)

# =============================================================================
# GENERATION ID TRACKING
# =============================================================================

current_generation_id = 0


def get_current_gen_id():
    global current_generation_id
    return current_generation_id


def increment_gen_id():
    global current_generation_id
    current_generation_id += 1
    return current_generation_id


# =============================================================================
# PROVIDER SWITCH OPERATOR
# =============================================================================

class NEURO_OT_switch_provider(Operator):
    """Switch active provider and preserve model selections"""
    bl_idname = "neuro.switch_provider"
    bl_label = "Switch Provider"
    bl_description = "Switch to this provider (preserves model selections)"

    provider: bpy.props.StringProperty()

    def execute(self, context):
        from .model_registry import (
            get_stored_model_for_provider, set_stored_model_for_provider,
            get_active_provider, get_registry, Provider, ModelCategory
        )

        prefs = context.preferences.addons[__package__].preferences

        # Get current provider before switching
        current_provider = get_active_provider(context)

        # Save current model selections for current provider
        if current_provider:
            current_image_model = getattr(context.scene, 'neuro_node_default_model', '')
            current_text_model = getattr(context.scene, 'neuro_node_default_text_model', '')

            if current_image_model:
                set_stored_model_for_provider(context, ModelCategory.IMAGE_GENERATION, current_provider,
                                              current_image_model)
            if current_text_model:
                set_stored_model_for_provider(context, ModelCategory.TEXT_GENERATION, current_provider,
                                              current_text_model)

        # Switch to new provider
        prefs.active_provider = self.provider

        # Get registry and new provider enum
        registry = get_registry()
        provider_map = {
            'aiml': Provider.AIML,
            'replicate': Provider.REPLICATE,
            'google': Provider.GOOGLE,
            'fal': Provider.FAL,
        }
        new_provider_enum = provider_map.get(self.provider, Provider.AIML)

        # Get valid models for new provider
        valid_image_models = [m.id for m in registry.get_all()
                              if m.category == ModelCategory.IMAGE_GENERATION
                              and m.provider == new_provider_enum and m.enabled]
        valid_text_models = [m.id for m in registry.get_all()
                             if m.category == ModelCategory.TEXT_GENERATION
                             and m.provider == new_provider_enum and m.enabled]

        # Restore stored model selections for new provider (with validation)
        new_provider = self.provider
        stored_image = get_stored_model_for_provider(context, ModelCategory.IMAGE_GENERATION, new_provider)
        stored_text = get_stored_model_for_provider(context, ModelCategory.TEXT_GENERATION, new_provider)

        # Only set if model exists in provider's list, else use first available
        if stored_image and stored_image in valid_image_models:
            try:
                context.scene.neuro_node_default_model = stored_image
                default_image_model = stored_image
            except Exception:
                default_image_model = valid_image_models[0] if valid_image_models else ""
        elif valid_image_models:
            try:
                context.scene.neuro_node_default_model = valid_image_models[0]
                default_image_model = valid_image_models[0]
            except Exception:
                default_image_model = ""
        else:
            default_image_model = ""

        if stored_text and stored_text in valid_text_models:
            try:
                context.scene.neuro_node_default_text_model = stored_text
                default_text_model = stored_text
            except Exception:
                default_text_model = valid_text_models[0] if valid_text_models else ""
        elif valid_text_models:
            try:
                context.scene.neuro_node_default_text_model = valid_text_models[0]
                default_text_model = valid_text_models[0]
            except Exception:
                default_text_model = ""
        else:
            default_text_model = ""

        # CRITICAL: Update all existing nodes to use valid models for the new provider
        # This prevents RNA enum warnings when the provider has fewer models
        self._update_node_models(valid_image_models, valid_text_models, default_image_model, default_text_model)

        # Force UI redraw
        for area in context.screen.areas:
            area.tag_redraw()

        self.report({'INFO'}, f"Switched to {self.provider.title()} provider")
        return {'FINISHED'}

    def _update_node_models(self, valid_image_models, valid_text_models, default_image, default_text):
        """Update all node model properties to valid values for the new provider.
        This prevents RNA enum warnings when switching between providers with different model counts."""

        # Node types that have model enum properties
        image_gen_node_types = {'NeuroGenerateNode', 'NeuroDesignVariationsNode'}
        text_gen_node_types = {'NeuroTextGenNode', 'NeuroUpgradePromptNode', 'NeuroArtistToolsNode'}

        for node_group in bpy.data.node_groups:
            if node_group.bl_idname != 'NeuroGenNodeTree':
                continue

            for node in node_group.nodes:
                try:
                    # Handle image generation nodes
                    if node.bl_idname in image_gen_node_types and hasattr(node, 'model'):
                        current_model = node.model
                        if current_model not in valid_image_models:
                            # Reset to default for new provider
                            if default_image:
                                node.model = default_image

                    # Handle text generation nodes
                    if node.bl_idname in text_gen_node_types and hasattr(node, 'model'):
                        current_model = node.model
                        if current_model not in valid_text_models:
                            # Reset to default for new provider
                            if default_text:
                                node.model = default_text
                except Exception as e:
                    # Silently skip nodes that fail - don't break the entire switch
                    print(f"[{LOG_PREFIX}] Warning: Could not update model for node {node.name}: {e}")


# =============================================================================
# API VALIDATION OPERATOR
# =============================================================================

class NEURO_OT_validate_keys(Operator):
    """Check if API keys are valid by making dummy requests"""
    bl_idname = "neuro.validate_keys"
    bl_label = "Check Connections"
    bl_description = "Test API connections for all providers"

    def execute(self, context):
        scn = context.scene
        google_key, fal_key, replicate_key, aiml_key = get_api_keys(context)

        # Get Tripo key
        tripo_key = ""
        try:
            prefs = context.preferences.addons[__package__].preferences
            tripo_key = getattr(prefs, 'tripo_api_key', '')
        except Exception:
            pass

        # Reset statuses
        scn.neuro_aiml_status = False
        scn.neuro_google_status = False
        scn.neuro_fal_status = False
        scn.neuro_replicate_status = False
        scn.neuro_keys_checked = False

        def check_worker():
            # Import locally to ensure threading safety
            import requests

            a_status = False
            g_status = False
            f_status = False
            r_status = False
            aiml_balance = ""
            tripo_balance = ""

            # --- 1. AIML (Billing Check) ---
            if aiml_key:
                try:
                    r = requests.get(
                        "https://api.aimlapi.com/v1/billing/balance",
                        headers={"Authorization": f"Bearer {aiml_key}"},
                        timeout=10
                    )
                    if r.status_code == 200:
                        a_status = True
                        data = r.json()
                        raw_bal = data if isinstance(data, (int, float)) else data.get("balance", 0)

                        # Format balance
                        if raw_bal >= 1_000_000:
                            aiml_balance = f"{raw_bal / 1_000_000:.1f}M cr"
                        elif raw_bal >= 1_000:
                            aiml_balance = f"{raw_bal / 1_000:.0f}K cr"
                        else:
                            aiml_balance = f"{int(raw_bal)} cr"
                except Exception as e:
                    print(f"[{LOG_PREFIX}] AIML Validation Failed: {e}")

            # --- 2. GOOGLE (Client Check) ---
            if google_key:
                try:
                    from .dependencies import check_dependencies
                    deps_ok, _, modules = check_dependencies()
                    if deps_ok and modules.get('Client'):
                        Client = modules['Client']
                        client = Client(api_key=google_key)
                        # Minimal call
                        next(iter(client.models.list(config={'page_size': 1})))
                        g_status = True
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Google Validation Failed: {e}")

            # --- 3. FAL (Models List Check) ---
            if fal_key:
                try:
                    # Robust check: List 1 model
                    r = requests.get(
                        "https://api.fal.ai/v1/models",
                        headers={"Authorization": f"Key {fal_key}"},
                        params={"limit": 1},
                        timeout=10
                    )
                    if r.status_code == 200:
                        f_status = True
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Fal Validation Failed: {e}")
                    # Fallback: simple format check if offline/error
                    if ":" in fal_key:
                        f_status = True

            # --- 4. REPLICATE (Account Check) ---
            if replicate_key:
                try:
                    # Robust check: Get Account
                    r = requests.get(
                        "https://api.replicate.com/v1/account",
                        headers={"Authorization": f"Bearer {replicate_key}"},
                        timeout=10
                    )
                    if r.status_code == 200:
                        r_status = True
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Replicate Validation Failed: {e}")

            # --- 5. TRIPO (Balance Check) ---
            if tripo_key and tripo_key.startswith("tsk_"):
                try:
                    # We trigger the async operator, but we can't wait for it easily in this thread.
                    # We assume valid if format is correct, and let the operator update balance later.
                    # This prevents "False" status on startup if the async check is slow.
                    from .nodes_3d import refresh_tripo_balance

                    # Schedule the refresh on main thread
                    bpy.app.timers.register(lambda: refresh_tripo_balance() or None)

                    # Assume true for now based on key format
                    # The refresh operator will flip it to False if it fails
                    context.scene.neuro_tripo_status = True
                except Exception:
                    pass

            # --- UPDATE UI ---
            def update_ui():
                context.scene.neuro_aiml_status = a_status
                context.scene.neuro_google_status = g_status
                context.scene.neuro_fal_status = f_status
                context.scene.neuro_replicate_status = r_status
                context.scene.neuro_keys_checked = True

                if aiml_balance:
                    context.scene.aiml_balance = aiml_balance

                # Auto-select provider logic (Preserved from your code)
                try:
                    prefs = context.preferences.addons[__package__].preferences
                    current = prefs.active_provider
                    current_valid = False

                    if current == 'aiml' and prefs.provider_aiml_enabled and a_status:
                        current_valid = True
                    elif current == 'google' and prefs.provider_google_enabled and g_status:
                        current_valid = True
                    elif current == 'fal' and prefs.provider_fal_enabled and f_status:
                        current_valid = True
                    elif current == 'replicate' and prefs.provider_replicate_enabled and r_status:
                        current_valid = True

                    if not current_valid:
                        if prefs.provider_aiml_enabled and a_status:
                            prefs.active_provider = 'aiml'
                        elif prefs.provider_google_enabled and g_status:
                            prefs.active_provider = 'google'
                        elif prefs.provider_replicate_enabled and r_status:
                            prefs.active_provider = 'replicate'
                        elif prefs.provider_fal_enabled and f_status:
                            prefs.active_provider = 'fal'
                except Exception:
                    pass

                return None

            bpy.app.timers.register(update_ui)

        threading.Thread(target=check_worker, daemon=True).start()
        return {'FINISHED'}


# =============================================================================
# BACKGROUND REMOVAL OPERATOR
# =============================================================================

class NEURO_OT_remove_background(Operator):
    """Remove background from first reference image"""
    bl_idname = "neuro.remove_background"
    bl_label = "Remove Background"
    bl_description = "Remove background from first reference image"

    def execute(self, context):
        from .dependencies import FAL_AVAILABLE, REPLICATE_AVAILABLE
        from .api import remove_background
        from .utils import get_all_api_keys

        scn = context.scene
        api_keys = get_all_api_keys(context)

        # Check if any BG removal provider is available
        has_replicate = REPLICATE_AVAILABLE and api_keys.get("replicate", "").strip()
        has_fal = FAL_AVAILABLE and api_keys.get("fal", "").strip()

        if not has_replicate and not has_fal:
            self.report({'ERROR'}, "No background removal provider available. Need Replicate or Fal API key.")
            return {'CANCELLED'}

        if len(scn.neuro_reference_images) == 0:
            self.report({'ERROR'}, "No reference images to process")
            return {'CANCELLED'}

        first_ref = scn.neuro_reference_images[0]
        if not os.path.exists(first_ref.path):
            self.report({'ERROR'}, "Reference image file not found")
            return {'CANCELLED'}

        # Get active provider
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break
        active_provider = prefs.active_provider if prefs else 'replicate'

        scn.neuro_status = "Removing background..."
        scn.neuro_is_generating = True
        scn.neuro_progress = 0.0

        def worker_job(img_path, keys, provider):
            try:
                result_path = remove_background(img_path, keys, provider)
                success = result_path is not None
            except Exception as e:
                result_path = None
                success = False
                print(f"[BG Removal] Error: {e}")

            def main_thread_update():
                scn_inner = bpy.context.scene
                scn_inner.neuro_is_generating = False

                if success and result_path:
                    try:
                        ref_dir = get_generations_folder("references")
                        perm_path = os.path.join(ref_dir, os.path.basename(result_path))
                        shutil.move(result_path, perm_path)
                        if result_path in temp_files_registry:
                            temp_files_registry.discard(result_path)
                        final_path = perm_path
                        print(f"[{LOG_PREFIX}] Saved background removal to: {final_path}")
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed to save persistent copy: {e}")
                        final_path = result_path

                    scn_inner.neuro_reference_images[0].path = final_path
                    refresh_previews_and_collections(scn_inner)

                    # Use safe_show_in_editor to prevent .001 duplicates
                    from .utils import safe_show_in_editor
                    try:
                        safe_show_in_editor(final_path, reload_existing=True)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed to load in editor: {e}")

                    scn_inner.neuro_status = "Background removed successfully"
                else:
                    scn_inner.neuro_status = "Background removal failed"

                return None

            bpy.app.timers.register(main_thread_update, first_interval=0.2)

        threading.Thread(target=worker_job, args=(first_ref.path, api_keys, active_provider), daemon=True).start()
        return {'FINISHED'}


# =============================================================================
# AIML BALANCE REFRESH OPERATOR
# =============================================================================

class AIML_OT_refresh_balance(Operator):
    """Refresh AIML credit balance"""
    bl_idname = "aiml.refresh_balance"
    bl_label = "Refresh AIML Balance"
    bl_description = "Refresh AIML credit balance"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import requests

        # Get API key
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs or not prefs.aiml_api_key:
            context.scene.aiml_balance = "No Key"
            return {'CANCELLED'}

        api_key = prefs.aiml_api_key

        def fetch_balance():
            try:
                response = requests.get(
                    "https://api.aimlapi.com/v1/billing/balance",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    balance = data.get("balance", 0)
                    # Display balance in credits with K/M suffixes for readability
                    if balance >= 1_000_000:
                        balance_str = f"{balance / 1_000_000:.1f}M cr"
                    elif balance >= 1_000:
                        balance_str = f"{balance / 1_000:.0f}K cr"
                    else:
                        balance_str = f"{balance} cr"

                    def update_ui():
                        bpy.context.scene.aiml_balance = balance_str
                        bpy.context.scene.neuro_aiml_status = True
                        return None

                    bpy.app.timers.register(update_ui, first_interval=0.1)
                else:
                    def update_err():
                        bpy.context.scene.aiml_balance = "Error"
                        bpy.context.scene.neuro_aiml_status = False
                        return None

                    bpy.app.timers.register(update_err, first_interval=0.1)

            except Exception as e:
                print(f"[AIML] Balance check failed: {e}")

                def update_err():
                    bpy.context.scene.aiml_balance = "Error"
                    return None

                bpy.app.timers.register(update_err, first_interval=0.1)

        threading.Thread(target=fetch_balance, daemon=True).start()
        return {'FINISHED'}


def refresh_aiml_balance():
    """Helper function to refresh AIML balance - call after generation"""
    try:
        bpy.ops.aiml.refresh_balance()
    except Exception:
        pass


# =============================================================================
# CANCEL GENERATION OPERATOR
# =============================================================================

class NEURO_OT_cancel_generation(Operator):
    """Cancel the current generation process"""
    bl_idname = "neuro.cancel_generation"
    bl_label = "Cancel"

    def execute(self, context):
        cancel_event.set()
        progress_timer.stop()
        increment_gen_id()

        context.scene.neuro_is_generating = False
        context.scene.neuro_status = "Generation cancelled"
        context.scene.neuro_progress = 0.0

        cleanup_temp_files()

        return {'FINISHED'}


# =============================================================================
# REGISTRATION
# =============================================================================

PROVIDER_OPERATOR_CLASSES = (
    NEURO_OT_switch_provider,
    NEURO_OT_validate_keys,
    NEURO_OT_remove_background,
    NEURO_OT_cancel_generation,
    AIML_OT_refresh_balance,
)


def register():
    for cls in PROVIDER_OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(PROVIDER_OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)