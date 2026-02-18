# -*- coding: utf-8 -*-
"""
UI Panels and Preferences  addon.
"""

import bpy
import os

from .dependencies import VERIFIED_PACKAGES
from .utils import (
    get_model_name_display,
    get_status_icon,
    get_preview_collection,
    get_conversation_turn_count,
    license_key_update,
)
from bpy.types import Operator


def update_api_status(self, context):
    """Force refresh status bar when keys change"""
    try:
        from .dependencies import check_all_api_keys
        # We use a timer to avoid freezing while typing (debounce)
        bpy.app.timers.register(lambda: check_all_api_keys(context) or None, first_interval=0.5)
    except Exception:
        pass


# =============================================================================
# ADDON PREFERENCES
# =============================================================================

class NEURO_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    gemini_api_key: bpy.props.StringProperty(
        name="Google API Key",
        description="Your Google Gemini API key",
        subtype='PASSWORD',
        update=update_api_status
    )

    fal_api_key: bpy.props.StringProperty(
        name="Fal API Key",
        description="Your Fal.AI API key (Best Image models provider)",
        subtype='PASSWORD',
        update=update_api_status
    )

    replicate_api_key: bpy.props.StringProperty(
        name="Replicate API Key",
        description="Your Replicate API key (backup provider)",
        subtype='PASSWORD',
        update=update_api_status
    )

    tripo_api_key: bpy.props.StringProperty(
        name="Tripo API Key",
        description="Your Tripo 3D API key (starts with 'tsk_')",
        subtype='PASSWORD',
        update=update_api_status
    )

    openai_api_key: bpy.props.StringProperty(
        name="OpenAI API Key",
        description="Your OpenAI API key (only needed for GPT Image 1 on Replicate)",
        subtype='PASSWORD',
    )

    aiml_api_key: bpy.props.StringProperty(
        name="AIML API Key",
        description="Your AIML API Key",
        subtype='PASSWORD',
        update=update_api_status
    )

    # Provider availability toggles (set in addon prefs)
    provider_google_enabled: bpy.props.BoolProperty(
        name="Google",
        description="Enable Google Gemini API models",
        default=True,
    )

    provider_replicate_enabled: bpy.props.BoolProperty(
        name="Replicate",
        description="Enable Replicate API models (backup provider)",
        default=False,
    )

    provider_fal_enabled: bpy.props.BoolProperty(
        name="Fal",
        description="Enable Fal.AI models (Best Image models provider)",
        default=True,
    )

    provider_aiml_enabled: bpy.props.BoolProperty(
        name="AIML",
        description="Enable AIML API models (unified provider)",
        default=True,
    )

    # Active provider selection (for switching)
    active_provider: bpy.props.EnumProperty(
        name="Active Provider",
        description="Currently active provider for generation",
        items=[
            ('replicate', "Replicate", "Use Replicate API"),
            ('google', "Google", "Use Google API"),
            ('fal', "Fal", "Use Fal.AI API"),
            ('aiml', "AIML", "Use AIML API (unified)"),
        ],
    )

    # Per-provider model storage
    selected_image_model_replicate: bpy.props.StringProperty(
        name="Replicate Image Model",
        default="nano-banana-pro",
    )
    selected_image_model_google: bpy.props.StringProperty(
        name="Google Image Model",
        default="nano-banana-pro-google",
    )
    selected_image_model_fal: bpy.props.StringProperty(
        name="Fal Image Model",
        default="nano-banana-pro-fal",
    )
    selected_image_model_aiml: bpy.props.StringProperty(
        name="AIML Image Model",
        default="gpt-image-1-aiml",
    )

    selected_text_model_replicate: bpy.props.StringProperty(
        name="Replicate Text Model",
        default="gpt-5.1",
    )
    selected_text_model_google: bpy.props.StringProperty(
        name="Google Text Model",
        default="gemini-3-pro-google",
    )
    selected_text_model_fal: bpy.props.StringProperty(
        name="Fal Text Model",
        default="",
    )

    # === FAL OPTIONS ===
    # Text/LLM source (Fal has no native LLM)
    fal_text_from_aiml: bpy.props.BoolProperty(
        name="AIML Text Models",
        description="Use AIML text models when Fal is active (conflicts with Replicate text)",
        default=True,
    )
    fal_text_from_google: bpy.props.BoolProperty(
        name="Google (Gemini)",
        description="Use Google Gemini for text/LLM operations when Fal is active (Free tier, region restricted)",
        default=False,
    )
    fal_text_from_replicate: bpy.props.BoolProperty(
        name="Replicate",
        description="Use Replicate for text/LLM operations when Fal is active (conflicts with AIML text)",
        default=False,
    )
    # Image models addon
    fal_include_google_models: bpy.props.BoolProperty(
        name="Add Google Models",
        description="Include Google image and LLM models in model list when Fal is active",
        default=False,
    )

    # === AIML OPTIONS ===
    aiml_include_google_models: bpy.props.BoolProperty(
        name="Add Google Models",
        description="Include Google image and LLM models in model list when AIML is active",
        default=False,
    )

    # === GOOGLE OPTIONS ===
    # Google + Fal image models option
    google_include_fal_models: bpy.props.BoolProperty(
        name="Include Fal.AI Models",
        description="When Google is active, also show Fal.AI image generation models in the model list",
        default=False,
    )

    # === REPLICATE OPTIONS ===
    replicate_include_google_models: bpy.props.BoolProperty(
        name="Add Google Models",
        description="Include Google image and LLM models in model list when Replicate is active",
        default=False,
    )

    # === MODEL VISIBILITY ===
    disabled_models: bpy.props.StringProperty(
        name="Disabled Models",
        description="JSON list of disabled model IDs",
        default="[]",
    )

    active_tab: bpy.props.EnumProperty(
        name="Active Tab",
        items=[
            ('CORE', "Core", "General settings and license"),
            ('PROVIDERS', "Providers", "API keys and connections"),
            ('TOOLS', "Tools", "Local AI tools"),
            ('TOKEN', "NeuroToken", "Unified token system"),
            ('DEV', "Dev", "Developer options"),
        ],
        default='CORE'
    )

    # CHANGED: Added SKIP_SAVE to prevent stuck restart messages
    needs_restart: bpy.props.BoolProperty(
        default=False,
        options={'SKIP_SAVE'}
    )
    rembg_needs_restart: bpy.props.BoolProperty(
        default=False,
        options={'SKIP_SAVE'}
    )

    verbose_logging: bpy.props.BoolProperty(
        name="Verbose Logging",
        description="Enable detailed API and registry logging in console",
        default=False,
    )

    manual_language: bpy.props.EnumProperty(
        name="Manual Language",
        description="Language for help popups and manuals",
        items=[
            ('EN', "English", "English manuals"),
            ('RU', "Ru", "Slavic language manuals"),
        ],
        default='EN',
    )

    show_primary_keys: bpy.props.BoolProperty(name="Show Primary Keys", default=True)
    show_3d_keys: bpy.props.BoolProperty(name="Show 3D Keys", default=True)
    show_backup_keys: bpy.props.BoolProperty(name="Show Backup Keys", default=False)
    show_dev_tools: bpy.props.BoolProperty(name="Show Developer Tools", default=False)

    # LICENSE PARAMETERS (for Master builds)
    license_key: bpy.props.StringProperty(
        name="License Key",
        description="Enter your license key",
        default="",
        subtype='PASSWORD',
        update=license_key_update
    )

    license_status: bpy.props.EnumProperty(
        name="License Status",
        items=[
            ('NONE', "None", "Not validated"),
            ('VALID', "Valid", "License is valid"),
            ('INVALID', "Invalid", "License is invalid"),
            ('PENDING', "Pending", "Validation in progress"),
        ],
        default='NONE'
    )

    license_message: bpy.props.StringProperty(
        name="License Message",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # Import here to avoid circular imports
        from .dependencies import DEPENDENCIES_INSTALLED

        # --- TAB BAR ---
        row = layout.row(align=True)
        row.prop_enum(self, "active_tab", "CORE", icon='PREFERENCES')
        row.prop_enum(self, "active_tab", "PROVIDERS", icon='WORLD')
        row.prop_enum(self, "active_tab", "TOOLS", icon='MODIFIER')

        # NeuroToken tab (hide for internal builds)
        # is_internal() returns True for BOTH hardcoded key AND config file builds
        is_internal_build = False
        try:
            from .config import is_internal
            is_internal_build = is_internal()
        except Exception:
            pass

        if not is_internal_build:
            row.prop_enum(self, "active_tab", "TOKEN", icon='FILE_VOLUME')

        if self.show_dev_tools:  # Only show Dev tab if enabled, or hidden toggle?
            # Let's keep Dev tab always visible but maybe icon only if space is tight
            # For now, just standard tab
            pass
        row.prop_enum(self, "active_tab", "DEV", icon='CONSOLE')

        layout.separator()

        # =================================================================
        # TAB: CORE
        # =================================================================
        if self.active_tab == 'CORE':
            # --- DEPENDENCY STATUS ---
            box = layout.box()
            if not DEPENDENCIES_INSTALLED:
                box.label(text="⚠️ Libraries Missing or Corrupted", icon='ERROR')
                box.label(text="Click below to download required AI libraries (50 MB).")
                box.operator("neuro.install_dependencies", icon='IMPORT')
            elif self.needs_restart:
                box.alert = True
                box.label(text="⚠️ RESTART REQUIRED", icon='ERROR')
                box.label(text="Libraries installed successfully!")
                box.label(text="Please close and reopen Blender to activate.", icon='FILE_REFRESH')
                box.separator()
                box.label(text="File → Quit Blender, then reopen")
            else:
                box.label(text="✓ Libraries Installed", icon='CHECKMARK')
                row = box.row()
                row.label(text="If you have issues, force update:")
                row.operator("neuro.install_dependencies", text="Force Update Libs", icon='FILE_REFRESH')

            # --- LICENSE SECTION ---
            # Show License Block ONLY if NOT internal build
            # is_internal_build already computed in tab bar section above
            try:
                if not is_internal_build:
                    box = layout.box()

                    # Safe token import
                    try:
                        from .config import get_token
                        token = get_token()
                        is_token_valid = token and token.is_valid()
                    except Exception:
                        token = None
                        is_token_valid = False

                    # Determine Status
                    status = 'VALID' if is_token_valid else self.license_status

                    # Icons
                    if status == 'VALID':
                        header_icon = 'CHECKMARK'
                        btn_icon = 'CHECKMARK'
                    elif status == 'INVALID':
                        header_icon = 'ERROR'
                        btn_icon = 'PLAY'
                    else:
                        header_icon = 'KEYINGSET'
                        btn_icon = 'PLAY'

                    box.label(text="License", icon=header_icon)

                    # License key input
                    row = box.row()
                    if status == 'INVALID':
                        row.alert = True
                    row.prop(self, "license_key", text="Key")

                    # Validate Button
                    row.operator("neuro.validate_license", text="", icon=btn_icon)

                    # Status Message
                    display_msg = self.license_message
                    if status == 'VALID' and self.license_status != 'VALID':
                        display_msg = "Session Active (Verified)"

                    if display_msg:
                        msg_row = box.row()
                        if status == 'VALID':
                            msg_row.label(text=display_msg, icon='CHECKMARK')
                        elif status == 'INVALID':
                            msg_row.alert = True
                            msg_row.label(text=display_msg, icon='ERROR')
                        else:
                            msg_row.label(text=display_msg, icon='INFO')

            except Exception as e:
                layout.label(text=f"UI Error: {e}", icon='ERROR')
                import traceback
                traceback.print_exc()

            # Language
            lang_box = layout.box()
            row = lang_box.row()
            row.label(text="Manual Language:")
            row.prop(self, "manual_language", expand=True)

            layout.separator()
            # --- UPDATE CHECK ---
            try:
                from .update import updater
                updater.draw_update_ui(layout)
            except Exception:
                pass

            layout.separator()

            # Feedback
            box = layout.box()
            box.label(text="Feedback & Support", icon='HELP')
            box.label(text="For bug reports and feature requests:")
            if is_internal_build:
                op = box.operator("neuro.copy_text", text="vladislav.stolyarenko@vizor-games.com", icon='COPYDOWN')
                op.text = "vladislav.stolyarenko@vizor-games.com"
            else:
                op = box.operator("neuro.copy_text", text="contact@neuronodes.io", icon='COPYDOWN')
                op.text = "contact@neuronodes.io"



        # =================================================================
        # TAB: PROVIDERS
        # =================================================================
        elif self.active_tab == 'PROVIDERS':
            row = layout.row()
            row.operator("neuro.test_all_connections", text="Test All Connections", icon='CHECKMARK')
            layout.separator()

            # PRIMARY KEYS
            box = layout.box()
            box.label(text="Primary Keys", icon='KEY_HLT')
            col = box.column(align=True)

            # AIML
            row = col.row(align=True)
            row.operator("neuro.aiml_key_info", text="", icon='QUESTION')
            row.prop(self, "provider_aiml_enabled", text="",
                     icon='CHECKMARK' if self.provider_aiml_enabled else 'CHECKBOX_DEHLT')
            sub = row.row(align=True)
            sub.enabled = self.provider_aiml_enabled
            sub.prop(self, "aiml_api_key", text="AIML API")
            status = getattr(scn, 'neuro_aiml_status', False)
            row.label(text="", icon='CHECKMARK' if status else 'BLANK1')
            op = row.operator("neuro.test_api_key", text="", icon='URL')
            op.provider = 'aiml'
            col.separator()

            # Fal
            row = col.row(align=True)
            row.operator("neuro.fal_key_info", text="", icon='QUESTION')
            row.prop(self, "provider_fal_enabled", text="",
                     icon='CHECKMARK' if self.provider_fal_enabled else 'CHECKBOX_DEHLT')
            sub = row.row(align=True)
            sub.enabled = self.provider_fal_enabled
            sub.prop(self, "fal_api_key", text="Fal.AI")
            status = getattr(scn, 'neuro_fal_status', False)
            row.label(text="", icon='CHECKMARK' if status else 'BLANK1')
            op = row.operator("neuro.test_api_key", text="", icon='URL')
            op.provider = 'fal'
            col.separator()

            # Google
            row = col.row(align=True)
            row.operator("neuro.google_key_info", text="", icon='QUESTION')
            row.prop(self, "provider_google_enabled", text="",
                     icon='CHECKMARK' if self.provider_google_enabled else 'CHECKBOX_DEHLT')
            sub = row.row(align=True)
            sub.enabled = self.provider_google_enabled
            sub.prop(self, "gemini_api_key", text="Google API")
            status = getattr(scn, 'neuro_google_status', False)
            row.label(text="", icon='CHECKMARK' if status else 'BLANK1')
            op = row.operator("neuro.test_api_key", text="", icon='URL')
            op.provider = 'google'

            layout.separator()

            # 3D GENERATION
            box = layout.box()
            box.label(text="3D Generation", icon='MESH_MONKEY')
            col = box.column(align=True)

            # Tripo
            row = col.row(align=True)
            row.operator("neuro.tripo_key_info", text="", icon='QUESTION')
            row.label(text="", icon='CHECKMARK')
            row.prop(self, "tripo_api_key", text="Tripo 3D")
            # [CHANGED] Now uses the persistent status from the actual API check
            status = getattr(scn, 'neuro_tripo_status', False)
            row.label(text="", icon='CHECKMARK' if status else 'BLANK1')
            op = row.operator("neuro.test_api_key", text="", icon='URL')
            op.provider = 'tripo'
            if self.tripo_api_key and not self.tripo_api_key.startswith("tsk_"):
                col.label(text="Key should start with 'tsk_'", icon='ERROR')

            # Hunyuan placeholder
            row = col.row(align=True)
            row.enabled = False
            row.label(text="", icon='CHECKBOX_DEHLT')
            row.label(text="Hunyuan 3D (Alpha)")
            row.label(text="", icon='TIME')

            layout.separator()

            # BACKUP PROVIDERS
            box = layout.box()
            box.label(text="Backup Providers", icon='RECOVER_LAST')
            col = box.column(align=True)

            # Replicate
            row = col.row(align=True)
            row.operator("neuro.replicate_key_info", text="", icon='QUESTION')
            row.prop(self, "provider_replicate_enabled", text="",
                     icon='CHECKMARK' if self.provider_replicate_enabled else 'CHECKBOX_DEHLT')
            sub = row.row(align=True)
            sub.enabled = self.provider_replicate_enabled
            sub.prop(self, "replicate_api_key", text="Replicate")
            status = getattr(scn, 'neuro_replicate_status', False)
            row.label(text="", icon='CHECKMARK' if status else 'BLANK1')
            op = row.operator("neuro.test_api_key", text="", icon='URL')
            op.provider = 'replicate'

            # OpenAI
            row = col.row(align=True)
            row.label(text="", icon='BLANK1')
            sub = row.row(align=True)
            sub.enabled = self.provider_replicate_enabled
            sub.prop(self, "openai_api_key", text="OpenAI (for GPT)")
            row.label(text="", icon='BLANK1')
            row.label(text="", icon='BLANK1')
            col.separator()



        # =================================================================
        # TAB: TOOLS
        # =================================================================
        elif self.active_tab == 'TOOLS':
            box = layout.box()
            box.label(text="Local Tools (PC)", icon='PLUGIN')

            # Check rembg status
            from .dependencies import check_rembg, REMBG_AVAILABLE
            rembg_installed = check_rembg()

            col = box.column(align=True)
            row = col.row(align=True)

            if self.rembg_needs_restart:
                row.alert = True
                row.label(text="Restart Blender to activate", icon='FILE_REFRESH')
            elif rembg_installed:
                # CHECK IF MODEL EXISTS
                import os
                home = os.path.expanduser("~")
                model_path = os.path.join(home, ".u2net", "birefnet-general.onnx")

                if os.path.exists(model_path):
                    row.label(text="Background Removal", icon='CHECKMARK')
                    row.label(text="Ready (Local)")
                else:
                    row.label(text="Background Removal", icon='CHECKMARK')
                    # Show Download button if model missing
                    row.operator("neuro.download_rembg_model", text="Download Model (~170MB)", icon='IMPORT')
            else:
                row.label(text="Background Removal", icon='CHECKBOX_DEHLT')
                row.operator("neuro.install_rembg", text="Install (~600MB)", icon='IMPORT')

            col.scale_y = 0.8
            col.separator(factor=0.6)
            col.label(text="Free local tool, auto-fallback when cloud unavailable")


        # =================================================================
        # TAB: NEURO TOKEN
        # =================================================================
        elif self.active_tab == 'TOKEN':
            box = layout.box()

            box.label(text="NeuroToken", icon='FILE_VOLUME')

            col = box.column()
            col.scale_y = 1.2
            col.label(text="Unified AI Credit System", icon='INFO')
            col.separator()

            col.label(text="• One token for all AI providers")
            col.label(text="• No API key juggling")
            col.label(text="• Stable model availability")
            col.label(text="• Priority support")

            col.separator()

            # Activate button - opens URL
            row = box.row()
            row.scale_y = 1
            row.operator("wm.url_open", text="Activate NeuroToken",
                         icon='URL').url = "https://neuronodes.io/token"

            box.separator()
            box.label(text="Coming Soon", icon='TIME')
        # =================================================================
        # TAB: DEV
        # =================================================================
        elif self.active_tab == 'DEV':
            dev_box = layout.box()
            dev_box.label(text="Developer Tools", icon='CONSOLE')
            dev_box.operator("neuro.dev_manual", text="Show Dev Manual", icon='QUESTION')

            # Verbose logging toggle
            dev_box.prop(self, "verbose_logging", icon='TEXT')
            row = dev_box.row()
            row.operator("neuro.check_package_updates", text="Check for Package Updates", icon='FILE_REFRESH')

            # Node Editor Settings
            dev_box.separator()
            dev_box.label(text="Node Editor Settings:", icon='NODE')
            try:
                # Find active AINodes node tree
                ntree = None
                for tree in bpy.data.node_groups:
                    if tree.bl_idname == 'NeuroGenNodeTree':
                        ntree = tree
                        break
                if ntree:
                    dev_box.prop(ntree, "preview_scale", text="Preview Size")
                else:
                    dev_box.label(text="  No AINodes node tree found")
            except Exception:
                dev_box.label(text="  (Open Node Editor first)")

            dev_box.label(text="Pinned Versions (Safe):", icon='LOCKVIEW_ON')
            try:
                from .dependencies import VERIFIED_PACKAGES
                for pkg_name, pkg_info in VERIFIED_PACKAGES.items():
                    dev_box.label(text=f"  {pkg_name}: {pkg_info['version']}")
            except Exception:
                pass

            # Show registered models from registry with enable/disable toggles
            dev_box.separator()
            dev_box.label(text="Registered Models:", icon='PRESET')
            dev_box.label(text="  (Click to disable/enable models)", icon='INFO')
            try:
                import json
                from .model_registry import get_registry, ModelCategory
                registry = get_registry()

                # Parse disabled models
                try:
                    disabled = set(json.loads(self.disabled_models))
                except Exception:
                    disabled = set()

                # Group by category
                categories = {
                    ModelCategory.IMAGE_GENERATION: "Image Generation",
                    ModelCategory.TEXT_GENERATION: "Text/LLM",
                }

                for cat, cat_name in categories.items():
                    models = [m for m in registry.get_all() if m.category == cat]
                    if not models:
                        continue

                    cat_box = dev_box.box()
                    cat_box.label(text=cat_name, icon='IMAGE_DATA' if cat == ModelCategory.IMAGE_GENERATION else 'TEXT')

                    for model in models:
                        row = cat_box.row(align=True)
                        is_disabled = model.id in disabled

                        # Toggle button
                        icon = 'CHECKBOX_DEHLT' if is_disabled else 'CHECKBOX_HLT'
                        op = row.operator("neuro.toggle_model", text="", icon=icon, emboss=False)
                        op.model_id = model.id

                        # Model info
                        provider_tag = model.provider.value.upper()[:3]
                        label = f"[{provider_tag}] {model.name}"
                        sub = row.row()
                        sub.enabled = not is_disabled
                        sub.label(text=label)

            except Exception as e:
                dev_box.label(text=f"  Registry error: {e}", icon='ERROR')


# =================================================================
# TEST OPERATORS UI / MINOR UTIL
# =================================================================

class NEURO_OT_copy_text(bpy.types.Operator):
    """Copy text to clipboard"""
    bl_idname = "neuro.copy_text"
    bl_label = "Copy Text"

    text: bpy.props.StringProperty()

    def execute(self, context):
        context.window_manager.clipboard = self.text
        self.report({'INFO'}, f"Copied to clipboard")
        return {'FINISHED'}


class NEURO_OT_toggle_model(bpy.types.Operator):
    """Toggle model enabled/disabled state"""
    bl_idname = "neuro.toggle_model"
    bl_label = "Toggle Model"

    model_id: bpy.props.StringProperty()

    def execute(self, context):
        import json

        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs:
            return {'CANCELLED'}

        # Parse current disabled list
        try:
            disabled = json.loads(prefs.disabled_models)
        except Exception:
            disabled = []

        # Toggle
        if self.model_id in disabled:
            disabled.remove(self.model_id)
            action = "enabled"
        else:
            disabled.append(self.model_id)
            action = "disabled"

        # Save back
        prefs.disabled_models = json.dumps(disabled)

        # Update registry model state
        try:
            from .model_registry import get_registry
            registry = get_registry()
            model = registry.get(self.model_id)
            if model:
                model.enabled = (self.model_id not in disabled)
        except Exception:
            pass

        self.report({'INFO'}, f"Model {self.model_id} {action}")
        return {'FINISHED'}


class NEURO_OT_validate_license(Operator):
    bl_idname = "neuro.validate_license"
    bl_label = "Validate License"
    bl_description = "Validate license key"

    def execute(self, context):
        from .config import init_session, get_token

        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs:
            self.report({'ERROR'}, "Could not find addon preferences")
            return {'CANCELLED'}

        license_key = prefs.license_key

        if not license_key:
            prefs.license_status = 'NONE'
            prefs.license_message = "Enter a license key first"
            self.report({'WARNING'}, prefs.license_message)
            return {'CANCELLED'}

        token = init_session(license_key, force=True)

        if token and token.is_valid():
            prefs.license_status = 'VALID'
            prefs.license_message = "License validated! Machine activated."
            self.report({'INFO'}, prefs.license_message)
            return {'FINISHED'}
        else:
            prefs.license_status = 'INVALID'
            prefs.license_message = "License validation failed. Check your key."
            self.report({'ERROR'}, prefs.license_message)
            return {'CANCELLED'}


class NEURO_OT_test_api_key(bpy.types.Operator):
    """Test single API key connection"""
    bl_idname = "neuro.test_api_key"
    bl_label = "Test Connection"

    provider: bpy.props.StringProperty()

    def execute(self, context):
        import threading
        scn = context.scene
        prefs = context.preferences.addons[__package__].preferences
        provider = self.provider

        self.report({'INFO'}, f"Testing {provider}...")

        # --- AIML: Delegate (Special Case) ---
        if provider == 'aiml':
            if prefs.aiml_api_key:
                if hasattr(bpy.ops.aiml, "refresh_balance"):
                    try:
                        def trigger_aiml():
                            bpy.ops.aiml.refresh_balance()
                            return None

                        bpy.app.timers.register(trigger_aiml)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] AIML Launch Failed: {e}")
                        scn.neuro_aiml_status = False
                else:
                    self.report({'WARNING'}, "AIML operator missing")
            else:
                self.report({'ERROR'}, "No AIML Key provided")
                scn.neuro_aiml_status = False

            return {'FINISHED'}

        # --- OTHERS: Threaded Logic ---
        def test_connection():
            success = False
            try:
                # GOOGLE
                if provider == 'google':
                    key = prefs.gemini_api_key
                    if key:
                        from google import genai
                        client = genai.Client(api_key=key)
                        next(iter(client.models.list(config={'page_size': 1})))
                        success = True
                    else:
                        print(f"[{LOG_PREFIX}] Google Key Empty")

                # REPLICATE
                elif provider == 'replicate':
                    import requests
                    key = prefs.replicate_api_key
                    if key:
                        r = requests.get(
                            "https://api.replicate.com/v1/account",
                            headers={"Authorization": f"Bearer {key}"},
                            timeout=10
                        )
                        success = r.status_code == 200
                    else:
                        print(f"[{LOG_PREFIX}] Replicate Key Empty")

                # FAL
                elif provider == 'fal':
                    import requests
                    key = prefs.fal_api_key
                    if key:
                        r = requests.get(
                            "https://api.fal.ai/v1/models",
                            headers={"Authorization": f"Key {key}"},
                            params={"limit": 1},
                            timeout=10
                        )
                        success = r.status_code == 200
                    else:
                        print(f"[{LOG_PREFIX}] Fal Key Empty")


                elif provider == 'tripo':
                    context.scene.tripo_balance = "Checking..."
                    scn.neuro_tripo_status = False
                    try:
                        def trigger_tripo():
                            if hasattr(bpy.ops.tripo, "refresh_balance"):
                                bpy.ops.tripo.refresh_balance()
                            return None
                        bpy.app.timers.register(trigger_tripo)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Tripo Launch Failed: {e}")
                        return {'CANCELLED'}

                    attempts = 0
                    def poll_tripo():
                        nonlocal attempts
                        attempts += 1
                        bal = getattr(scn, "tripo_balance", "")
                        if bal == "Checking...":
                            if attempts > 20:  # 10 seconds timeout
                                print(f"[{LOG_PREFIX}] Tripo check timed out")
                                return None
                            return 0.5  # Retry

                        if "Error" in bal or "No" in bal or "Fail" in bal:
                            scn.neuro_tripo_status = False
                            return None

                        if any(c.isdigit() for c in bal):
                            scn.neuro_tripo_status = True
                            return None

                        return 0.5

                    bpy.app.timers.register(poll_tripo)
                    return {'FINISHED'}

            except Exception as e:
                print(f"[Test {provider}] Error: {e}")
                success = False

            # Update status on main thread
            def update_status():
                if provider == 'google':
                    scn.neuro_google_status = success
                elif provider == 'replicate':
                    scn.neuro_replicate_status = success
                elif provider == 'fal':
                    scn.neuro_fal_status = success
                # (AIML handles its own status)
                return None

            bpy.app.timers.register(update_status, first_interval=0.1)

        threading.Thread(target=test_connection, daemon=True).start()

        return {'FINISHED'}


class NEURO_OT_test_all_connections(bpy.types.Operator):
    """Test all enabled API connections"""
    bl_idname = "neuro.test_all_connections"
    bl_label = "Test All Connections"

    def execute(self, context):
        try:
            bpy.ops.neuro.validate_keys()
            self.report({'INFO'}, "Testing all connections...")
        except Exception as e:
            self.report({'ERROR'}, f"Test failed: {e}")
        return {'FINISHED'}


# =============================================================================
# IMAGE EDITOR PANEL
# =============================================================================

class NEURO_PT_panel(bpy.types.Panel):
    bl_label = "Blender AI Generations"
    bl_idname = "IMAGE_PT_neuro"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = PANELS_NAME

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # ============ INPUT BLOCK ============
        input_box = layout.box()

        # Header + Mode Switch
        row = input_box.row(align=True)
        row.label(text="Input", icon='CURRENT_FILE')
        row.prop(scn, "neuro_input_mode", expand=True)

        if scn.neuro_input_mode == 'IMAGE':
            self.draw_image_mode(input_box, scn)
        else:
            self.draw_texture_mode(input_box, scn)

        # Reference Images (Always visible)
        self.draw_reference_images(input_box, scn)

        layout.separator()

        # ============ GENERATION BLOCK ============
        self.draw_generation_block(layout, scn)

        layout.separator()

        # ============ SETTINGS BLOCK ============
        self.draw_settings_block(layout, scn, context)

        layout.separator()

        # ============ GENERATED GALLERIES ============
        self.draw_image_gallery(layout, scn)
        layout.separator()
        self.draw_texture_gallery(layout, scn)

    def draw_image_mode(self, input_box, scn):
        """Draw Image mode UI elements."""
        prompt_row = input_box.row(align=True)
        prompt_row.prop(scn, "neuro_prompt_image", text="")

        if scn.neuro_prompt_image:
            op = prompt_row.operator("neuro.show_full_prompt", text="", icon='TEXT')
            op.prompt_text = scn.neuro_prompt_image
            op.prompt_title = "Image Prompt"

        # Gemini History (Beta) - Only for Gemini 3 models
        model = scn.neuro_generation_model
        if model.startswith("gemini-3"):
            hist_row = input_box.row(align=True)
            hist_row.prop(scn, "neuro_use_thought_signatures", text="Gemini History (Beta)")

            if scn.neuro_use_thought_signatures:
                turns = get_conversation_turn_count()
                if turns > 0:
                    hist_row.operator("neuro.clear_thought_history", text="", icon='X')
                    hist_row.label(text=f"{turns} turn(s)")

        # Image Mode Tools
        input_box.separator(factor=0.1)
        row = input_box.row(align=True)
        row.operator("neuro.upgrade_prompt", text="Upgrade Prompt", icon='KEY_SHIFT_FILLED')
        row.prop(scn, "neuro_upgrade_strict", text="Strict", toggle=True)
        if scn.neuro_prompt_backup:
            row.operator("neuro.revert_prompt", text="", icon='LOOP_BACK')

        # Modifiers
        grid = input_box.grid_flow(row_major=True, columns=3, align=True)
        grid.prop(scn, "neuro_mod_isometric")
        grid.prop(scn, "neuro_mod_detailed")
        grid.prop(scn, "neuro_mod_soft")
        grid.prop(scn, "neuro_mod_clean")
        grid.prop(scn, "neuro_mod_vibrant")
        grid.prop(scn, "neuro_mod_casual")

        row = input_box.row(align=True)
        batch_col = row.column(align=True)
        # Only disable batch for direct Google Gemini 3 with history enabled
        if scn.neuro_use_thought_signatures and model.startswith("gemini-3"):
            batch_col.enabled = False
        batch_col.prop(scn, "neuro_num_outputs", text="Batch")
        row.prop(scn, "neuro_aspect_ratio", text="")

    def draw_texture_mode(self, input_box, scn):
        """Draw Texture mode UI elements."""
        builder_box = input_box.box()
        builder_box.label(text="Texture Builder", icon='MODIFIER')
        builder_box.prop(scn, "neuro_texture_obj_desc")

        row = builder_box.row(align=True)
        row.prop(scn, "neuro_texture_style", text="")
        row.prop(scn, "neuro_texture_lighting", text="")

        builder_box.separator(factor=0.5)
        grid = builder_box.grid_flow(row_major=True, columns=2, align=True)
        grid.prop(scn, "neuro_mod_isometric")
        grid.prop(scn, "neuro_mod_detailed")
        grid.prop(scn, "neuro_mod_soft")
        grid.prop(scn, "neuro_mod_clean")
        grid.prop(scn, "neuro_mod_vibrant")
        grid.prop(scn, "neuro_mod_casual")

        builder_box.separator(factor=0.5)
        row = builder_box.row()
        has_refs = len(scn.neuro_reference_images) > 0
        ref_text = "Use Ref Image Influence" if has_refs else "Use Ref Image Influence (no refs)"
        row.prop(scn, "neuro_use_ref_influence", text=ref_text)

        input_box.prop(scn, "neuro_prompt_texture", text="")

        # Texture Mode Tools
        row = input_box.row(align=True)
        row.prop(scn, "neuro_num_outputs", text="Batch")
        row.operator("neuro.setup_matcap_normal", text="", icon='SHADING_TEXTURE')
        row.operator("neuro.revert_matcap", text="", icon='SHADING_SOLID')

    def draw_reference_images(self, input_box, scn):
        """Draw reference images section."""
        input_box.separator(factor=0.1)
        ref_box = input_box.box()
        row = ref_box.row()
        row.prop(scn, "neuro_show_references",
                 icon='TRIA_DOWN' if scn.neuro_show_references else 'TRIA_RIGHT',
                 emboss=False, text="Input Images")
        row.label(text=f"({len(scn.neuro_reference_images)})", icon='RENDERLAYERS')
        if len(scn.neuro_reference_images) > 0:
            row.operator("neuro.clear_all_references", text="", icon='X')

        if scn.neuro_show_references:
            row = ref_box.row(align=True)
            row.operator("neuro.add_reference_image", text="Active", icon='IMAGE_DATA')
            row.operator("neuro.add_reference_from_disk", text="Disk", icon='FILE_FOLDER')
            row.operator("neuro.add_reference_from_clipboard", text="Clip", icon='PASTEDOWN')

            if len(scn.neuro_reference_images) > 0:
                grid = ref_box.grid_flow(columns=2, even_columns=True, even_rows=True)
                for i, ref in enumerate(scn.neuro_reference_images):
                    col = grid.column()
                    subbox = col.box()

                    key = os.path.normpath(os.path.abspath(ref.path))
                    pcoll = get_preview_collection()
                    if pcoll and key in pcoll:
                        icon = pcoll[key].icon_id
                        subbox.template_icon(icon_value=icon, scale=6)
                    else:
                        subbox.label(text="(no preview)", icon='ERROR')

                    subbox.label(text=os.path.basename(ref.path)[:20])
                    op = subbox.operator("neuro.remove_reference", text="Remove", icon='X')
                    op.index = i

    def draw_generation_block(self, layout, scn):
        """Draw generation buttons and status."""
        from .dependencies import FAL_AVAILABLE

        gen_box = layout.box()
        row = gen_box.row()
        row.label(text="Generate", icon='RENDER_STILL')

        if scn.neuro_input_mode == 'IMAGE':
            row.operator("neuro.image_manual", text="", icon='QUESTION')
        else:
            row.operator("neuro.texture_manual", text="", icon='QUESTION')

        row = gen_box.row(align=True)

        if scn.neuro_is_generating:
            row.scale_y = 1.4
            row.operator("neuro.cancel_generation", text="Cancel", icon='CANCEL')
        else:
            if scn.neuro_input_mode == 'IMAGE':
                col = row.column(align=True)
                col.scale_y = 1.4
                col.operator("neuro.generate_image", text="Generate Image", icon='IMAGE_DATA')

                col = row.column(align=True)
                col.scale_y = 1.4
                if len(scn.neuro_reference_images) == 0 or not FAL_AVAILABLE:
                    col.enabled = False
                col.operator("neuro.remove_background", text="", icon='BRUSH_DATA')
            else:
                col = row.column(align=True)
                col.scale_y = 1.4
                col.operator("neuro.generate_texture", text="Generate Texture", icon='TEXTURE')

                col = row.column(align=True)
                col.scale_y = 1.4
                if len(scn.neuro_reference_images) == 0 or not FAL_AVAILABLE:
                    col.enabled = False
                col.operator("neuro.remove_background", text="", icon='BRUSH_DATA')

        if scn.neuro_is_generating:
            gen_box.prop(scn, "neuro_progress", text="Progress", slider=True)

        if scn.neuro_status:
            status_icon = get_status_icon(scn.neuro_status)
            gen_box.label(text=scn.neuro_status, icon=status_icon)

    def draw_settings_block(self, layout, scn, context):
        """Draw settings panel."""
        box = layout.box()
        row = box.row()
        row.prop(scn, "neuro_show_settings",
                 icon='TRIA_DOWN' if scn.neuro_show_settings else 'TRIA_RIGHT',
                 emboss=False, text="Settings")

        if scn.neuro_show_settings:
            # Get addon preferences
            prefs = None
            for name in [__package__, __name__, "ai_nodes"]:
                if name and name in context.preferences.addons:
                    prefs = context.preferences.addons[name].preferences
                    break

            # Provider switch (same as node editor)
            if prefs:
                prov_box = box.box()
                prov_box.label(text="Active Provider:", icon='WORLD')
                row = prov_box.row(align=True)

                # Use operator buttons for proper model persistence
                if prefs.provider_replicate_enabled:
                    op = row.operator("neuro.switch_provider",
                                      text="Replicate",
                                      depress=(prefs.active_provider == 'replicate'))
                    op.provider = 'replicate'
                if prefs.provider_google_enabled:
                    op = row.operator("neuro.switch_provider",
                                      text="Google",
                                      depress=(prefs.active_provider == 'google'))
                    op.provider = 'google'
                if prefs.provider_fal_enabled:
                    op = row.operator("neuro.switch_provider",
                                      text="Fal",
                                      depress=(prefs.active_provider == 'fal'))
                    op.provider = 'fal'
                if prefs.provider_aiml_enabled:
                    op = row.operator("neuro.switch_provider",
                                      text="AIML",
                                      depress=(prefs.active_provider == 'aiml'))
                    op.provider = 'aiml'

                # Fal Text Source Options (shown when Fal is active)
                if prefs.active_provider == 'fal':
                    fal_box = prov_box.box()
                    fal_box.label(text="Text/LLM Source:", icon='TEXT')

                    # AIML option with connection status
                    row = fal_box.row(align=True)
                    row.prop(prefs, "fal_text_from_aiml", text="")
                    sub = row.row(align=True)
                    sub.enabled = prefs.fal_text_from_aiml
                    aiml_status = scn.neuro_aiml_status if hasattr(scn, 'neuro_aiml_status') else False
                    status_icon = 'CHECKMARK' if aiml_status else 'ERROR'
                    sub.label(text="AIML Text", icon=status_icon)
                    if prefs.fal_text_from_aiml and prefs.fal_text_from_replicate:
                        sub.label(text="[conflicts]")
                        sub.alert = True

                    # Replicate option with connection status
                    row = fal_box.row(align=True)
                    row.prop(prefs, "fal_text_from_replicate", text="")
                    sub = row.row(align=True)
                    sub.enabled = prefs.fal_text_from_replicate
                    rep_status = scn.neuro_replicate_status if hasattr(scn, 'neuro_replicate_status') else False
                    status_icon = 'CHECKMARK' if rep_status else 'ERROR'
                    sub.label(text="Replicate Text", icon=status_icon)
                    if prefs.fal_text_from_aiml and prefs.fal_text_from_replicate:
                        sub.label(text="[conflicts]")
                        sub.alert = True

                    # Warning if nothing selected
                    if not prefs.fal_text_from_aiml and not prefs.fal_text_from_replicate:
                        warn_row = fal_box.row()
                        warn_row.alert = True
                        warn_row.label(text="No text source! Prompt upgrade disabled", icon='ERROR')

                    # Add Models section
                    fal_box.separator()
                    fal_box.label(text="Add Models:", icon='PLUS')
                    row = fal_box.row(align=True)
                    row.prop(prefs, "fal_include_google_models", text="")
                    sub = row.row(align=True)
                    sub.enabled = prefs.fal_include_google_models
                    google_status = scn.neuro_google_status if hasattr(scn, 'neuro_google_status') else False
                    sub.label(text="Google Image/LLMs", icon='CHECKMARK' if google_status else 'ERROR')

            box.separator(factor=0.3)

            row = box.row()
            row.scale_y = 1.2
            col = row.column(align=True)
            col.label(text="Generation Model:", icon='RENDER_STILL')
            col = row.column(align=True)
            col.scale_x = 1.2
            col.prop(scn, "neuro_generation_model", text="")

            row = box.row()
            row.scale_y = 1.2
            col = row.column(align=True)
            col.label(text="Prompt Model:", icon='CURRENT_FILE')
            col = row.column(align=True)
            col.scale_x = 1.2
            col.prop(scn, "neuro_upgrade_model", text="")

            box.separator(factor=0.5)
            if scn.neuro_input_mode == 'TEXTURE':
                row = box.row(align=True)
                row.operator("neuro.save_builder_presets", text="Save Builder", icon='EXPORT')
                row.operator("neuro.load_builder_presets", text="Load Builder", icon='IMPORT')
                box.separator(factor=0.5)

            row = box.row()
            col = row.column(align=True)
            col.prop(scn, "neuro_timeout", text="Timeout (s)")
            col = row.column(align=True)
            col.prop(scn, "neuro_texture_resolution", text="Resolution")

            if scn.neuro_input_mode == 'TEXTURE':
                row2 = box.row()
                row2.prop(scn, "neuro_texture_frame_percent", text="Frame %")

    def draw_image_gallery(self, layout, scn):
        """Draw generated images gallery."""
        box = layout.box()
        row = box.row()
        row.prop(scn, "neuro_show_generated",
                 icon='TRIA_DOWN' if scn.neuro_show_generated else 'TRIA_RIGHT',
                 emboss=False, text="Generated Images")

        fav_count = sum(1 for g in scn.neuro_generated_images if g.favorite)
        count_text = f"({len(scn.neuro_generated_images)})"
        if fav_count > 0:
            count_text += f" ★{fav_count}"
        row.label(text=count_text)

        if len(scn.neuro_generated_images) > 0:
            row.prop(scn, "neuro_filter_favorites", text="",
                     icon='SOLO_ON' if scn.neuro_filter_favorites else 'SOLO_OFF')

        if scn.neuro_show_generated:
            if len(scn.neuro_generated_images) > 0:
                row = box.row(align=True)
                row.operator("neuro.clear_generated", text="Clear All", icon='X')
                row.operator("neuro.relocate_gallery_images", text="", icon='FILEBROWSER')

                display_images = []
                if scn.neuro_filter_favorites:
                    display_images = [(i, g) for i, g in enumerate(scn.neuro_generated_images) if g.favorite]
                else:
                    display_images = list(enumerate(scn.neuro_generated_images))

                self.draw_gallery_items(box, display_images, scn, is_texture=False)
            else:
                box.label(text="No images generated yet")

    def draw_texture_gallery(self, layout, scn):
        """Draw generated textures gallery."""
        box = layout.box()
        row = box.row()
        row.prop(scn, "neuro_show_textures",
                 icon='TRIA_DOWN' if scn.neuro_show_textures else 'TRIA_RIGHT',
                 emboss=False, text="Generated Textures")

        fav_count_tex = sum(1 for t in scn.neuro_generated_textures if t.favorite)
        count_text_tex = f"({len(scn.neuro_generated_textures)})"
        if fav_count_tex > 0:
            count_text_tex += f" ★{fav_count_tex}"
        row.label(text=count_text_tex)

        if len(scn.neuro_generated_textures) > 0:
            row.prop(scn, "neuro_filter_favorites_tex", text="",
                     icon='SOLO_ON' if scn.neuro_filter_favorites_tex else 'SOLO_OFF')

        if scn.neuro_show_textures:
            if len(scn.neuro_generated_textures) > 0:
                row = box.row(align=True)
                row.operator("neuro.clear_textures", text="Clear All", icon='X')
                row.operator("neuro.relocate_gallery_images", text="", icon='FILEBROWSER')

                display_textures = []
                if scn.neuro_filter_favorites_tex:
                    display_textures = [(i, t) for i, t in enumerate(scn.neuro_generated_textures) if t.favorite]
                else:
                    display_textures = list(enumerate(scn.neuro_generated_textures))

                self.draw_gallery_items(box, display_textures, scn, is_texture=True)
            else:
                box.label(text="No textures generated yet")

    def draw_gallery_items(self, box, display_items, scn, is_texture):
        """Draw gallery items (shared between images and textures)."""
        if not display_items and (
                (is_texture and scn.neuro_filter_favorites_tex) or (not is_texture and scn.neuro_filter_favorites)):
            box.label(text="No favorites yet", icon='INFO')
            return

        # Group by batch
        batches = {}
        for i, item in display_items:
            if item.batch_id not in batches:
                batches[item.batch_id] = []
            batches[item.batch_id].append((i, item))

        sorted_batches = sorted(batches.items(), key=lambda x: x[0], reverse=True)

        for batch_id, items in sorted_batches:
            batch_box = box.box()
            row = batch_box.row()
            first_item = items[0][1]
            model_name = get_model_name_display(
                first_item.model_used if hasattr(first_item, 'model_used') else "Unknown")
            icon_type = 'TEXTURE' if is_texture else 'RENDERLAYERS'

            if is_texture:
                row.label(text=f"{first_item.timestamp} ({len(items)})", icon=icon_type)
            else:
                row.label(text=f"Batch: {first_item.timestamp} ({len(items)}): {model_name}", icon=icon_type)

            # Determine which item is currently displayed
            if len(items) > 1:
                batch_entry = None
                for entry in scn.neuro_batch_view_index:
                    if entry.batch_id == batch_id:
                        batch_entry = entry
                        break

                current_idx = batch_entry.current_index if batch_entry else 0
                current_idx = max(0, min(current_idx, len(items) - 1))
            else:
                current_idx = 0

            display_idx, display_item = items[current_idx]

            # PBR buttons for textures
            if is_texture:
                if not hasattr(display_item, 'map_type') or display_item.map_type == 'COLOR':
                    pbr_row = row.row(align=False)
                    pbr_row.scale_x = 0.7

                    op = pbr_row.operator("neuro.generate_pbr_map", text="", icon='SHADING_RENDERED')
                    op.texture_index = display_idx
                    op.map_type = 'ROUGHNESS'

                    op = pbr_row.operator("neuro.generate_pbr_map", text="", icon='MATSPHERE')
                    op.texture_index = display_idx
                    op.map_type = 'METALLIC'

                    op = pbr_row.operator("neuro.generate_pbr_map", text="", icon='MOD_DISPLACE')
                    op.texture_index = display_idx
                    op.map_type = 'HEIGHT'

            # Star button
            star_icon = 'SOLO_ON' if display_item.favorite else 'SOLO_OFF'
            op = row.operator("neuro.toggle_favorite", text="", icon=star_icon)
            op.index = display_idx
            op.is_texture = is_texture

            # Batch navigation
            if len(items) > 1:
                nav_row = batch_box.row(align=True)
                nav_col = nav_row.column(align=True)
                prev_op = nav_col.operator("neuro.batch_navigate", text="", icon='TRIA_LEFT')
                prev_op.batch_id = batch_id
                prev_op.direction = -1
                prev_op.is_texture = is_texture

                nav_col = nav_row.column(align=True)
                nav_col.scale_x = 3.0
                item_type_text = "Texture" if is_texture else "Image"
                nav_col.label(text=f"{item_type_text} {current_idx + 1} of {len(items)}")

                nav_col = nav_row.column(align=True)
                next_op = nav_col.operator("neuro.batch_navigate", text="", icon='TRIA_RIGHT')
                next_op.batch_id = batch_id
                next_op.direction = 1
                next_op.is_texture = is_texture

            idx, item = display_idx, display_item

            subbox = batch_box.box()
            key = os.path.normpath(os.path.abspath(item.path))
            pcoll = get_preview_collection()
            if pcoll and key in pcoll:
                icon = pcoll[key].icon_id
                subbox.template_icon(icon_value=icon, scale=8)
            else:
                subbox.label(text="(no preview)", icon='ERROR')

            # Map type badge for textures
            if is_texture and hasattr(item, "map_type") and item.map_type != 'COLOR':
                badge_row = subbox.row()
                badge_row.alignment = 'CENTER'
                map_icons = {'ROUGHNESS': 'SHADING_RENDERED', 'METALLIC': 'MATSPHERE', 'HEIGHT': 'MOD_DISPLACE'}
                source_idx = getattr(item, 'source_texture_idx', 0)
                if source_idx > 0:
                    badge_text = f"Texture {source_idx}: {item.map_type.capitalize()}"
                else:
                    badge_text = item.map_type.capitalize()
                badge_row.label(text=badge_text, icon=map_icons.get(item.map_type, 'NODE_MATERIAL'))

            if item.prompt:
                prompt_display = item.prompt[:60] + "..." if len(item.prompt) > 60 else item.prompt
                row = subbox.row(align=True)
                op = row.operator("neuro.copy_prompt", text=prompt_display, icon='TEXT')
                op.prompt_text = item.prompt

            row = subbox.row(align=True)
            op = row.operator("neuro.load_generated", text="Show in Editor", icon='FILE_IMAGE')
            op.path = item.path

            if is_texture:
                op = row.operator("neuro.apply_texture", text="Apply Texture", icon='MATERIAL')
                op.path = item.path
                op.target_object = item.target_object

                op = row.operator("neuro.regenerate_texture", text="Regenerate", icon='FILE_REFRESH')
                op.index = idx

                op = row.operator("neuro.delete_texture", text="", icon='TRASH')
                op.index = idx
            else:
                op = row.operator("neuro.replace_reference", text="Use as Input", icon='IMPORT')
                op.path = item.path

                op = row.operator("neuro.regenerate_image", text="Regenerate", icon='FILE_REFRESH')
                op.index = idx

                op = row.operator("neuro.delete_generated", text="", icon='TRASH')
                op.index = idx


# =============================================================================
# REGISTRATION
# =============================================================================

classes = (
    NEURO_AddonPreferences,
    NEURO_OT_copy_text,
    NEURO_OT_toggle_model,
    NEURO_OT_validate_license,
    NEURO_OT_test_api_key,
    NEURO_OT_test_all_connections,
    NEURO_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.neuro_tripo_status = bpy.props.BoolProperty(default=False)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.neuro_tripo_status