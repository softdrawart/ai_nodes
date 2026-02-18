# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Manual/Help Operators
Info popups and workflow documentation.
"""

import bpy
from bpy.types import Operator


# =============================================================================
# DEVELOPER MANUAL
# =============================================================================

class NEURO_OT_dev_manual(Operator):
    """Developer workflow manual"""
    bl_idname = "neuro.dev_manual"
    bl_label = "Developer Manual"
    bl_description = "How to update packages securely"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=500)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Developer: Package Update Workflow", icon='CONSOLE')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="When Google/Fal release new API versions:")
        col.separator()
        col.label(text="1. Click 'Check for Package Updates' button")
        col.label(text="2. Review available updates in popup")
        col.label(text="3. Check console for new config (copy-pasteable)")
        col.separator()
        col.label(text="4. Verify changes are safe:")
        col.label(text="   • Check package GitHub/changelog")
        col.label(text="   • Look for security advisories")
        col.label(text="   • Test in dev environment first")
        col.separator()
        col.label(text="5. Update VERIFIED_PACKAGES in dependencies.py:")
        col.label(text="   • Set new version string")
        col.label(text="   • Set new SHA256 hash")
        col.separator()
        col.label(text="6. Test installation on clean Blender")
        col.label(text="7. Push new addon version to users")

        layout.separator()
        box = layout.box()
        box.label(text="Security: Packages are hash-verified before install.", icon='LOCKED')
        box.label(text="If PyPI is compromised, mismatched hashes block install.")


# =============================================================================
# TEXTURE GENERATION MANUAL
# =============================================================================

class NEURO_OT_texture_manual(Operator):
    """Texture generation workflow manual"""
    bl_idname = "neuro.texture_manual"
    bl_label = "Texture Generation Manual"
    bl_description = "How to use texture generation"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=480)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Texture Generation Workflow", icon='TEXTURE')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="How It Works:", icon='INFO')
        col.label(text="• Captures normal map from current camera view")
        col.label(text="• AI generates texture matching the geometry")
        col.label(text="• Projects texture back onto object via UV")
        col.separator()

        col.label(text="Requirements:", icon='CHECKMARK')
        col.label(text="• Single mesh object selected")
        col.label(text="• Camera view active (Numpad 0)")
        col.label(text="• Object should be regular mesh (not curved)")
        col.label(text="• Works best with flat/low-poly surfaces")
        col.separator()

        col.label(text="Best Practices:", icon='SOLO_ON')
        col.label(text="• Frame object to fill 80-99% of view")
        col.label(text="• Use orthographic camera for tileable textures")
        col.label(text="• Front/side views work better than oblique angles")
        col.label(text="• Add reference images for style consistency")
        col.separator()

        col.label(text="Limitations:", icon='ERROR')
        col.label(text="• Single object only (no multi-object)")
        col.label(text="• Projection from one angle (not 360°)")
        col.label(text="• Curved surfaces may have stretching")
        col.label(text="• Complex topology needs manual UV tweaks")

        layout.separator()
        box = layout.box()
        box.label(text="Tip: Use 'Frame %' slider to control object coverage", icon='LIGHT')


# =============================================================================
# IMAGE GENERATION MANUAL
# =============================================================================

class NEURO_OT_image_manual(Operator):
    """Image generation workflow manual"""
    bl_idname = "neuro.image_manual"
    bl_label = "Image Generation Manual"
    bl_description = "How to use image generation for 3D workflows"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Image Generation for 3D Workflows", icon='IMAGE_DATA')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="Sketch-to-Concept:", icon='GREASEPENCIL')
        col.label(text="Turn rough sketches into polished concepts:")
        col.separator()
        box = layout.box()
        box.scale_y = 0.8
        box.label(text="Prompt template:")
        box.label(text='"Turn this rough [medium] sketch of a [subject]')
        box.label(text='into a [style]. Keep [features] but add [details]."')
        col.separator()

        col.label(text="Reference Image Limits:", icon='RENDERLAYERS')
        col.label(text="• Up to 6 object images (high fidelity preservation)")
        col.label(text="• Up to 5 human images (character consistency)")
        col.label(text="• Mix references for style + subject control")
        col.separator()

        col.label(text="Resolution Options:", icon='FULLSCREEN_ENTER')
        col.label(text="• 1K (1024px) - Fast iteration, drafts")
        col.label(text="• 2K (2048px) - Production quality")
        col.separator()

        col.label(text="3D Workflow Tips:", icon='VIEW3D')
        col.label(text="• Render clay/matcap as sketch input")
        col.label(text="• Use orthographic renders for clean refs")
        col.label(text="• Generate multiple angles for consistency")
        col.label(text="• Combine with texture mode for full pipeline")
        col.separator()

        col.label(text="Aspect Ratios:", icon='ARROW_LEFTRIGHT')
        col.label(text="• 1:1 - Icons, textures, UI elements")
        col.label(text="• 3:4 / 4:3 - Character art, props")
        col.label(text="• 16:9 - Environment concepts, scenes")

        layout.separator()
        box = layout.box()
        box.label(text="Modifiers add style keywords to your prompt", icon='MODIFIER')


# =============================================================================
# API KEY INFO POPUPS
# =============================================================================

class NEURO_OT_google_key_info(Operator):
    """How to get Google Gemini API Key"""
    bl_idname = "neuro.google_key_info"
    bl_label = "Google Gemini API Key"
    bl_description = "Instructions for getting Google API key"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Google Gemini API Key", icon='INFO')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="This key allows the addon to communicate ONLY with Gemini models.")
        col.separator()
        col.label(text="1. Go to Google AI Studio: aistudio.google.com")
        col.label(text="2. Sign in with your Google account.")
        col.label(text="3. Click 'Get API key' in the left menu.")
        col.label(text="4. Click 'Create API key'.")
        col.separator()
        col.label(text="   • Option A: 'Create API key in new project' (Quick)")
        col.label(text="   • Option B: Select existing Google Cloud project")
        col.separator()
        col.label(text="5. Copy the generated key string.")
        col.separator()

        box = layout.box()
        box.label(text="Note: Usage is free (90 days) within standard limits.", icon='CHECKMARK')
        box.alert = True
        box.label(text="Important: Check your location! Use good VPN if unavailable", icon='ERROR')


class NEURO_OT_fal_key_info(Operator):
    """How to get Fal.AI API Key"""
    bl_idname = "neuro.fal_key_info"
    bl_label = "Fal.AI API Key"
    bl_description = "Instructions for getting Fal.AI API key"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Fal.AI API Key", icon='INFO')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="API for Image models.")
        col.separator()
        col.label(text="1. Go to dashboard: fal.ai/dashboard/keys")
        col.label(text="2. Sign in via GitHub, GitLab, or Google.")
        col.label(text="3. Create a key:")
        col.label(text="   • Find 'API Keys' in left menu or main screen.")
        col.label(text="   • Click 'Create Key' (or 'Add Key').")
        col.separator()
        col.label(text="4. Select scope (permissions):")
        col.label(text="   • 'API' — sufficient for generation")
        col.label(text="   • 'ADMIN' — full access")
        col.separator()
        col.label(text="5. Copy the generated key.")
        col.separator()

        box = layout.box()
        box.alert = True
        box.label(text="Important: fal.ai is a paid service!", icon='ERROR')
        box.label(text="Fal.ai has only IMAGE MODELS, use in combination with other provider!!!")
        box.label(text="Add credits before using.")


class NEURO_OT_replicate_key_info(Operator):
    """How to get Replicate API Key"""
    bl_idname = "neuro.replicate_key_info"
    bl_label = "Replicate API Key"
    bl_description = "Instructions for getting Replicate API key"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Replicate API Key", icon='INFO')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="Unified API for LLMs+Image models.")
        col.separator()
        col.label(text="1. Go to: replicate.com/account/api-tokens")
        col.label(text="2. Sign in with GitHub or Google.")
        col.label(text="3. Click 'Create token'.")
        col.label(text="4. Give it a name (e.g., 'Blender API KEY').")
        col.label(text="5. Copy the generated token here.")
        col.separator()

        box = layout.box()
        box.alert = True
        box.label(text="Important: Replicate is a paid service!", icon='ERROR')
        box.label(text="Replicate uses OpenAI key for GPT-IMAGE-1 !!!")
        box.label(text="Add credits before using.")


class NEURO_OT_aiml_key_info(Operator):
    """How to get AIML API Key"""
    bl_idname = "neuro.aiml_key_info"
    bl_label = "AIML API Key"
    bl_description = "Instructions for getting AIML API key"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def draw(self, context):
        layout = self.layout
        layout.label(text="AIML API Key", icon='INFO')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="Unified API for LLMs+Image models.")
        col.separator()
        col.label(text="1. Go to: aimlapi.com")
        col.label(text="2. Login to the dashboard.")
        col.label(text="3. Add Plan/Credits to your account.")
        col.label(text="4. Navigate to 'API Keys' in the sidebar.")
        col.label(text="5. Create a new key(s) and copy it here.")
        col.separator()

        box = layout.box()
        box.alert = True
        box.label(text="Important: AIML is a paid service!", icon='ERROR')
        box.label(text="AIML has NO INPUT for GPT-IMAGE-1.5 !!!")
        box.label(text="Add credits before using.")


class NEURO_OT_tripo_key_info(Operator):
    """How to get Tripo 3D API Key"""
    bl_idname = "neuro.tripo_key_info"
    bl_label = "Tripo 3D API Key"
    bl_description = "Instructions for getting Tripo 3D API key"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=450)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Tripo 3D API Key", icon='INFO')
        layout.separator()

        col = layout.column(align=True)
        col.label(text="3D model generation provider.")
        col.separator()
        col.label(text="1. Go to: platform.tripo3d.ai/billing")
        col.label(text="2. Sign in or Create Account.")
        col.label(text="3. Add credits to your wallet.")
        col.label(text="4. Copy your API Key.")
        col.separator()

        box = layout.box()
        box.alert = True
        box.label(text="Billing: You must set up billing to use the API.", icon='ERROR')


# =============================================================================
# REGISTRATION
# =============================================================================

MANUAL_OPERATOR_CLASSES = (
    NEURO_OT_dev_manual,
    NEURO_OT_texture_manual,
    NEURO_OT_image_manual,
    NEURO_OT_google_key_info,
    NEURO_OT_fal_key_info,
    NEURO_OT_replicate_key_info,
    NEURO_OT_aiml_key_info,
    NEURO_OT_tripo_key_info,
)


def register():
    for cls in MANUAL_OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(MANUAL_OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)