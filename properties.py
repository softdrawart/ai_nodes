# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Properties Module
Property groups and scene property registration.
"""

import bpy

from .constants import (
    ASPECT_RATIOS, STYLE_OPTIONS, LIGHTING_ITEMS, MODIFIERS_MAP
)


# =============================================================================
# PROPERTY GROUPS
# =============================================================================

class NeuroReferenceImage(bpy.types.PropertyGroup):
    """Property group for reference images"""
    path: bpy.props.StringProperty(name="Path")


class NeuroGeneratedImage(bpy.types.PropertyGroup):
    """Property group for generated images"""
    path: bpy.props.StringProperty(name="Path")
    prompt: bpy.props.StringProperty(name="Original Prompt")
    timestamp: bpy.props.StringProperty(name="Timestamp")
    batch_id: bpy.props.StringProperty(name="Batch ID")
    batch_index: bpy.props.IntProperty(name="Batch Index", default=0)
    batch_total: bpy.props.IntProperty(name="Batch Total", default=1)
    favorite: bpy.props.BoolProperty(name="Favorite", default=False)
    model_used: bpy.props.StringProperty(name="Model Used", default="gemini-2.5-flash-image")


class NeuroGeneratedTexture(bpy.types.PropertyGroup):
    """Property group for generated textures"""
    path: bpy.props.StringProperty(name="Path")
    prompt: bpy.props.StringProperty(name="Original Prompt")
    timestamp: bpy.props.StringProperty(name="Timestamp")
    batch_id: bpy.props.StringProperty(name="Batch ID")
    batch_index: bpy.props.IntProperty(name="Batch Index", default=0)
    batch_total: bpy.props.IntProperty(name="Batch Total", default=1)
    target_object: bpy.props.StringProperty(name="Target Object")
    favorite: bpy.props.BoolProperty(name="Favorite", default=False)
    model_used: bpy.props.StringProperty(name="Model Used", default="gemini-2.5-flash-image")
    map_type: bpy.props.StringProperty(name="Map Type", default="COLOR")
    source_texture_idx: bpy.props.IntProperty(name="Source Texture Index", default=0)


class NeuroBatchViewIndex(bpy.types.PropertyGroup):
    """Property group for batch view navigation"""
    batch_id: bpy.props.StringProperty(name="Batch ID")
    current_index: bpy.props.IntProperty(name="Current Index", default=0)


# =============================================================================
# DYNAMIC ENUM GETTERS
# =============================================================================

def _get_disabled_models(context):
    """Get set of disabled model IDs from preferences"""
    import json
    prefs = None
    for name in ["blender_ai_nodes", "ai_nodes", __package__]:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break
    if prefs and hasattr(prefs, 'disabled_models'):
        try:
            return set(json.loads(prefs.disabled_models))
        except Exception:
            pass
    return set()


def _filter_disabled(items, disabled_set):
    """Filter out disabled models from enum items list.
    Keeps separators (items starting with _) and non-disabled models.
    """
    filtered = [item for item in items
                if item[0].startswith('_') or item[0] not in disabled_set]
    return filtered if filtered else None  # Return None to signal fallback needed


def get_style_items(self, context):
    """Dynamic getter for Styles"""
    items = []
    for key, val in STYLE_OPTIONS.items():
        items.append((key, val[1], ""))
    return items


def get_lighting_items(self, context):
    """Dynamic getter for Lighting"""
    return [(x[0], x[1], "") for x in LIGHTING_ITEMS]


def get_generation_models(self, context):
    """Dynamic getter for generation models from registry - uses active provider.

    Supports adding models from secondary providers based on preferences:
    - Fal + fal_include_google_models → add Google models
    - AIML + aiml_include_google_models → add Google models
    - Google + google_include_fal_models → add Fal models
    - Replicate + replicate_include_google_models → add Google models
    """
    try:
        from .model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()

        # Get active provider from preferences
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if prefs and hasattr(prefs, 'active_provider'):
            active = prefs.active_provider
            provider_map = {
                'aiml': Provider.AIML,
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
            }
            provider = provider_map.get(active, Provider.AIML)

            items = registry.get_models_for_active_provider(
                category=ModelCategory.IMAGE_GENERATION,
                active_provider=provider
            )
            items = list(items) if items else []

            # Fal + Google models option
            if active == 'fal' and getattr(prefs, 'fal_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_separator", "-- Google Models --", ""))
                    items.extend(google_items)

            # AIML + Google models option
            elif active == 'aiml' and getattr(prefs, 'aiml_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_separator", "-- Google Models --", ""))
                    items.extend(google_items)

            # Google + Fal models option
            elif active == 'google' and getattr(prefs, 'google_include_fal_models', False):
                fal_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.FAL
                )
                if fal_items:
                    items.append(("_fal_separator", "-- Fal.AI Models --", ""))
                    items.extend(fal_items)

            # Replicate + Google models option
            elif active == 'replicate' and getattr(prefs, 'replicate_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_separator", "-- Google Models --", ""))
                    items.extend(google_items)

            if items:
                # Filter out disabled models
                disabled = _get_disabled_models(context)
                filtered = _filter_disabled(items, disabled)
                if filtered:
                    return filtered

        # Fallback - show all models from all enabled providers
        items = registry.get_blender_enum_items(ModelCategory.IMAGE_GENERATION)
        disabled = _get_disabled_models(context)
        filtered = _filter_disabled(items, disabled)
        if filtered:
            return filtered
        # Ultimate fallback
        return [
            ("nano-banana", "Nano Banana", ""),
            ("nano-banana-pro", "Nano Banana Pro", ""),
        ]
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Model enum error: {e}")
        return [
            ("nano-banana", "Nano Banana", ""),
            ("nano-banana-pro", "Nano Banana Pro", ""),
        ]


def get_text_models(self, context):
    """Dynamic getter for text models from registry - uses active provider.

    Special handling for Fal provider: Since Fal has no LLM capabilities,
    uses the configured text source (AIML or Replicate, mutually exclusive).
    Google models can be added alongside any text source.
    """
    try:
        from .model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()

        # Get active provider from preferences
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if prefs and hasattr(prefs, 'active_provider'):
            active = prefs.active_provider

            # Special handling for Fal - use text source provider
            if active == 'fal':
                # Get the text source provider for Fal
                text_provider = None
                items = []

                # Priority 1: AIML if enabled (conflicts with Replicate)
                if getattr(prefs, 'fal_text_from_aiml', False):
                    aiml_key = getattr(prefs, 'aiml_api_key', '')
                    if aiml_key:
                        text_provider = Provider.AIML

                # Priority 2: Replicate if enabled and AIML not selected
                if not text_provider and getattr(prefs, 'fal_text_from_replicate', False):
                    replicate_key = getattr(prefs, 'replicate_api_key', '')
                    if replicate_key:
                        text_provider = Provider.REPLICATE

                # Legacy fallback: fal_text_from_google for backward compatibility
                if not text_provider and getattr(prefs, 'fal_text_from_google', False):
                    google_key = getattr(prefs, 'gemini_api_key', '')
                    if google_key:
                        text_provider = Provider.GOOGLE

                if text_provider:
                    items = registry.get_models_for_active_provider(
                        category=ModelCategory.TEXT_GENERATION,
                        active_provider=text_provider
                    )
                    items = list(items) if items else []

                # Add Google models if include option enabled (doesn't conflict)
                # Skip if Google is already the main text provider
                if text_provider != Provider.GOOGLE and getattr(prefs, 'fal_include_google_models', False):
                    google_key = getattr(prefs, 'gemini_api_key', '')
                    if google_key:
                        google_items = registry.get_models_for_active_provider(
                            category=ModelCategory.TEXT_GENERATION,
                            active_provider=Provider.GOOGLE
                        )
                        if google_items:
                            if items:
                                items.append(("_google_text_separator", "-- Google LLMs --", ""))
                            items.extend(google_items)

                if items:
                    return items

                # No text source configured - return empty with warning
                return [("none", "No LLM Source (Configure in Settings)",
                         "Fal has no LLM. Enable AIML or Replicate in Settings.")]

            # Normal provider handling
            provider_map = {
                'aiml': Provider.AIML,
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
            }
            provider = provider_map.get(active, Provider.AIML)

            items = registry.get_models_for_active_provider(
                category=ModelCategory.TEXT_GENERATION,
                active_provider=provider
            )
            items = list(items) if items else []

            # AIML + Google text models option
            if active == 'aiml' and getattr(prefs, 'aiml_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.TEXT_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_text_separator", "-- Google LLMs --", ""))
                    items.extend(google_items)

            # Replicate + Google text models option
            elif active == 'replicate' and getattr(prefs, 'replicate_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.TEXT_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_text_separator", "-- Google LLMs --", ""))
                    items.extend(google_items)

            if items:
                # Filter out disabled models
                disabled = _get_disabled_models(context)
                filtered = _filter_disabled(items, disabled)
                if filtered:
                    return filtered

        # Fallback - show all models
        items = registry.get_blender_enum_items(ModelCategory.TEXT_GENERATION)
        disabled = _get_disabled_models(context)
        filtered = _filter_disabled(items, disabled)
        if filtered:
            return filtered
        # Ultimate fallback
        return [
            ("gpt-5.1", "GPT-5.1", ""),
            ("gemini-3-pro-google", "Gemini 3.0 Pro (Google)", ""),
        ]
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Text model enum error: {e}")
        return [
            ("gpt-5.1", "GPT-5.1", ""),
            ("gemini-3-pro-google", "Gemini 3.0 Pro (Google)", ""),
        ]


# =============================================================================
# PROMPT BUILDER UPDATE CALLBACK
# =============================================================================

def update_prompt_from_builder(self, context):
    """Rebuilds the prompt string whenever a builder setting changes"""
    scn = context.scene

    # 1. Object
    obj = scn.neuro_texture_obj_desc.strip()
    if not obj:
        obj = "[object]"

    prompt = f"Generate a full texture for this {obj}"

    # Style
    style_id = scn.neuro_texture_style
    if style_id in STYLE_OPTIONS:
        prompt += STYLE_OPTIONS[style_id][0]

    # Lighting
    light_id = scn.neuro_texture_lighting
    light_suffix = ""
    for item in LIGHTING_ITEMS:
        if item[0] == light_id:
            light_suffix = item[2]
            break
    prompt += light_suffix

    # Modifiers
    active_mods = []
    for prop_name, mod_text in MODIFIERS_MAP.items():
        if getattr(scn, prop_name):
            active_mods.append(mod_text.strip())

    if active_mods:
        prompt += ", " + ", ".join(active_mods)

    prompt += "."

    # 3. ESSENTIAL TECHNICAL INSTRUCTION
    prompt += " Use the attached normal map to define exact generation edges and boundaries and understand the model's geometry, preserve pixel to pixel accuracy to existing normal map. Keep the same object size."

    # 4. Reference Influence (Optional)
    if scn.neuro_use_ref_influence:
        prompt += " Use the provided reference image as concept, style and color influence."

    prompt += " Create an entirely new colored texture based on the prompt."

    # 5. Update Main Prompt
    scn.neuro_prompt_texture = prompt


# =============================================================================
# PROPERTY REGISTRATION
# =============================================================================

PROPERTY_CLASSES = (
    NeuroReferenceImage,
    NeuroGeneratedImage,
    NeuroGeneratedTexture,
    NeuroBatchViewIndex,
)


def register_properties():
    """Register all scene properties"""

    bpy.types.Scene.neuro_node_default_model = bpy.props.EnumProperty(
        name="Default Node Model",
        items=get_generation_models,
        description="Default model for new Generate nodes"
    )

    bpy.types.Scene.neuro_node_default_text_model = bpy.props.EnumProperty(
        name="Default Text Model",
        items=get_text_models,
        description="Default model for new Text Generation nodes"
    )

    bpy.types.Scene.neuro_node_default_upgrade_model = bpy.props.EnumProperty(
        name="Default Upgrade Model",
        items=get_text_models,
        description="Default model for new Upgrade Prompt nodes"
    )

    # === INPUT MODE ===
    bpy.types.Scene.neuro_input_mode = bpy.props.EnumProperty(
        name="Input Mode",
        items=[
            ('IMAGE', "Image/Edit", "Generate or Edit 2D Images"),
            ('TEXTURE', "Texture", "Generate Textures for 3D Objects")
        ],
        default='IMAGE',
        description="Switch between Image Generation and Texture Creation workflows"
    )

    # === PROMPTS ===
    bpy.types.Scene.neuro_prompt_image = bpy.props.StringProperty(
        name="Image Prompt",
        default="",
        description="Prompt for Image Generation"
    )
    bpy.types.Scene.neuro_prompt_texture = bpy.props.StringProperty(
        name="Texture Prompt",
        default="",
        description="Prompt for Texture Generation"
    )
    bpy.types.Scene.neuro_prompt_backup = bpy.props.StringProperty(
        name="Prompt Backup",
        default=""
    )

    # === TEXTURE BUILDER ===
    bpy.types.Scene.neuro_texture_gen_type = bpy.props.EnumProperty(
        name="Texture Type",
        items=[
            ('COLOR', "Base Color", "Generate standard color texture"),
            ('ROUGHNESS', "Roughness", "Generate Roughness map from input"),
            ('METALLIC', "Metallic", "Generate Metallic map from input"),
            ('HEIGHT', "Height", "Generate Height/Bump map from input"),
        ],
        default='COLOR',
        description="Type of texture to generate"
    )

    bpy.types.Scene.neuro_texture_obj_desc = bpy.props.StringProperty(
        name="Object",
        default="",
        description="What is this object?",
        update=update_prompt_from_builder
    )

    bpy.types.Scene.neuro_texture_style = bpy.props.EnumProperty(
        name="Style",
        items=get_style_items,
        default=None,
        update=update_prompt_from_builder
    )

    bpy.types.Scene.neuro_texture_lighting = bpy.props.EnumProperty(
        name="Lighting",
        items=get_lighting_items,
        default=None,
        update=update_prompt_from_builder
    )

    bpy.types.Scene.neuro_use_ref_influence = bpy.props.BoolProperty(
        name="Use Reference Influence",
        description="Instruct AI to use reference image for concept/style",
        default=False,
        update=update_prompt_from_builder
    )

    # === MODIFIERS ===
    bpy.types.Scene.neuro_mod_isometric = bpy.props.BoolProperty(
        name="Isometric View", default=False, update=update_prompt_from_builder)
    bpy.types.Scene.neuro_mod_detailed = bpy.props.BoolProperty(
        name="Sharp Details", default=False, update=update_prompt_from_builder)
    bpy.types.Scene.neuro_mod_soft = bpy.props.BoolProperty(
        name="Soft Shading", default=False, update=update_prompt_from_builder)
    bpy.types.Scene.neuro_mod_clean = bpy.props.BoolProperty(
        name="Clean BG", default=False, update=update_prompt_from_builder)
    bpy.types.Scene.neuro_mod_vibrant = bpy.props.BoolProperty(
        name="Vibrant Colors", default=False, update=update_prompt_from_builder)
    bpy.types.Scene.neuro_mod_casual = bpy.props.BoolProperty(
        name="Casual Asset", default=False, update=update_prompt_from_builder)

    # === COLLECTIONS ===
    bpy.types.Scene.neuro_reference_images = bpy.props.CollectionProperty(type=NeuroReferenceImage)
    bpy.types.Scene.neuro_generated_images = bpy.props.CollectionProperty(type=NeuroGeneratedImage)
    bpy.types.Scene.neuro_generated_textures = bpy.props.CollectionProperty(type=NeuroGeneratedTexture)
    bpy.types.Scene.neuro_batch_view_index = bpy.props.CollectionProperty(type=NeuroBatchViewIndex)

    # === GENERATION STATE ===
    bpy.types.Scene.neuro_status = bpy.props.StringProperty(name="Status", default="")
    bpy.types.Scene.neuro_num_outputs = bpy.props.IntProperty(name="Batch count", default=1, min=1, max=4)
    bpy.types.Scene.neuro_is_generating = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_progress = bpy.props.FloatProperty(
        name="Progress", default=0.0, min=0.0, max=100.0, subtype='PERCENTAGE')
    bpy.types.Scene.neuro_aspect_ratio = bpy.props.EnumProperty(
        name="Aspect Ratio", items=ASPECT_RATIOS, default="1:1")

    # === FAVORITES ===
    bpy.types.Scene.neuro_filter_favorites = bpy.props.BoolProperty(
        name="Show Favorites Only", default=False)
    bpy.types.Scene.neuro_filter_favorites_tex = bpy.props.BoolProperty(
        name="Show Favorites Only", default=False)

    # === MODELS ===
    bpy.types.Scene.neuro_generation_model = bpy.props.EnumProperty(
        name="Generation Model",
        items=get_generation_models,
        description="AI model for image generation"
    )
    bpy.types.Scene.neuro_upgrade_model = bpy.props.EnumProperty(
        name="Upgrade Model",
        items=get_text_models,
        description="AI model for prompt upgrade"
    )

    # === SETTINGS ===
    bpy.types.Scene.neuro_timeout = bpy.props.IntProperty(name="Timeout", default=60, min=15, max=300)
    bpy.types.Scene.neuro_texture_frame_percent = bpy.props.IntProperty(
        name="Texture Frame %", default=99, min=80, max=100)
    bpy.types.Scene.neuro_texture_resolution = bpy.props.EnumProperty(
        name="Output Resolution",
        items=[
            ('1024', "1K", "1024x1024 - Standard"),
            ('2048', "2K", "2048x2048 - High quality"),
        ],
        default='1024',
        description="Output resolution for textures. Images use aspect ratio setting."
    )

    # === API STATUS ===
    bpy.types.Scene.neuro_google_status = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_fal_status = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_replicate_status = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_aiml_status = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_keys_checked = bpy.props.BoolProperty(default=False)

    # === TRIPO 3D ===
    bpy.types.Scene.tripo_balance = bpy.props.StringProperty(
        name="Tripo Balance",
        description="Current Tripo token balance",
        default=""
    )

    # === AIML BALANCE ===
    bpy.types.Scene.aiml_balance = bpy.props.StringProperty(
        name="AIML Balance",
        description="Current AIML credit balance",
        default=""
    )

    # === TRANSLATOR (Node Editor Header) ===
    bpy.types.Scene.neuro_translate_input = bpy.props.StringProperty(
        name="Translate",
        description="Enter text to translate to English",
        default=""
    )
    bpy.types.Scene.neuro_translate_result = bpy.props.StringProperty(
        name="Translation Result",
        description="Translated text (English)",
        default=""
    )

    # === THOUGHT SIGNATURES ===
    bpy.types.Scene.neuro_use_thought_signatures = bpy.props.BoolProperty(
        name="Gemini History (Beta)",
        description="Keep conversation history between generations. AI remembers previous images and can build upon or edit them in follow-up requests",
        default=False
    )

    # === STRICT MODE ===
    bpy.types.Scene.neuro_upgrade_strict = bpy.props.BoolProperty(
        name="Strict",
        description="Use strict templates for editing prompts. Enforces structured output format (recommended for consistent results)",
        default=True
    )

    # === VPN STATUS ===
    bpy.types.Scene.neuro_vpn_status = bpy.props.StringProperty(name="VPN Status", default="")

    # === UI TOGGLES ===
    bpy.types.Scene.neuro_show_references = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.neuro_show_settings = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.neuro_show_generated = bpy.props.BoolProperty(default=True)
    bpy.types.Scene.neuro_show_textures = bpy.props.BoolProperty(default=True)

    # === STORED SHADING ===
    bpy.types.Scene.neuro_stored_shading_type = bpy.props.StringProperty(default="")
    bpy.types.Scene.neuro_stored_shading_light = bpy.props.StringProperty(default="")
    bpy.types.Scene.neuro_stored_studio_light = bpy.props.StringProperty(default="")


def unregister_properties():
    """Unregister all scene properties"""
    props_to_delete = [
        'neuro_node_default_model',
        'neuro_node_default_text_model',
        'neuro_node_default_upgrade_model',
        'neuro_input_mode',
        'neuro_texture_obj_desc',
        'neuro_texture_style',
        'neuro_texture_lighting',
        'neuro_mod_isometric',
        'neuro_mod_detailed',
        'neuro_mod_soft',
        'neuro_mod_clean',
        'neuro_mod_vibrant',
        'neuro_mod_casual',
        'neuro_use_ref_influence',
        'neuro_prompt_image',
        'neuro_prompt_texture',
        'neuro_prompt_backup',
        'neuro_reference_images',
        'neuro_generated_images',
        'neuro_generated_textures',
        'neuro_status',
        'neuro_num_outputs',
        'neuro_is_generating',
        'neuro_generation_model',
        'neuro_upgrade_model',
        'neuro_timeout',
        'neuro_texture_frame_percent',
        'neuro_vpn_status',
        'neuro_batch_view_index',
        'neuro_show_references',
        'neuro_show_settings',
        'neuro_show_generated',
        'neuro_show_textures',
        'neuro_stored_shading_type',
        'neuro_stored_shading_light',
        'neuro_stored_studio_light',
        'neuro_progress',
        'neuro_aspect_ratio',
        'neuro_filter_favorites',
        'neuro_filter_favorites_tex',
        'neuro_google_status',
        'neuro_fal_status',
        'neuro_replicate_status',
        'neuro_aiml_status',
        'neuro_keys_checked',
        'neuro_use_thought_signatures',
        'tripo_balance',
        'aiml_balance',
        'neuro_translate_input',
        'neuro_translate_result',
        'neuro_upgrade_strict',
        'neuro_texture_gen_type',
        'neuro_texture_resolution',
    ]

    for prop in props_to_delete:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass


# =============================================================================
# REGISTRATION
# =============================================================================

def register():
    """Register property classes and scene properties"""
    for cls in PROPERTY_CLASSES:
        bpy.utils.register_class(cls)
    register_properties()


def unregister():
    """Unregister property classes and scene properties"""
    unregister_properties()
    for cls in reversed(PROPERTY_CLASSES):
        bpy.utils.unregister_class(cls)