# -*- coding: utf-8 -*-
"""
Constants Module
All static strings, model definitions, prompts, and configuration data.

Note: Model definitions are also in model_registry.py for the new system.
These lists are kept for backward compatibility with existing code.
"""

import os

# =============================================================================
# VERSION INFO
# =============================================================================

ADDON_VERSION = (1, 8, 5)
BLENDER_MIN_VERSION = (4, 5, 0)
LOG_PREFIX = "AINODES"
ADDON_NAME_CONFIG = "Blender AI Nodes"
PANELS_NAME = "AINodes"

SYMBOLS = """utf-8 symbols: ✓ (check), ⚠️ (warning/error), ★ (favorites)"""


# =============================================================================
# ASPECT RATIOS
# =============================================================================

ASPECT_RATIOS = [
    ("match_input_image", "Match Input", "Match the aspect ratio of input image"),
    ("1:1", "1:1 (Square)", "1024x1024"),
    ("3:4", "3:4 (Portrait)", "768x1024"),
    ("4:3", "4:3 (Landscape)", "1024x768"),
    ("16:9", "16:9 (Wide)", "1920x1080"),
    ("9:16", "9:16 (Tall)", "1080x1920"),
    ("21:9", "21:9 (Ultrawide)", "2560x1080"),
]

# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

CREATIVE_UPGRADE_PROMPT = """You are an expert visual prompt engineer. The user has provided a basic concept: "{original_prompt}".
Write a detailed, creative, and high-quality image generation prompt based on this concept.
Focus on:
1. Artistic Style: Try to pick up users intention , but mainly focus on concept art style, slight stylized style. (Avoid photorealism).
2. Visual details: Materials, textures, vibrant colors.
3. Lighting: Best would be Neutral ambient occlusion lighting, but focus on original prompt preference.
4. Composition.

Do NOT write instructions like "Create an image of...". Just describe the visual scene directly.
Output ONLY the final prompt text. Keep it concise (approx 2-5 sentences).
"""

EDITING_UPGRADE_PROMPT = """Make initial text instruction {original_prompt} a little bit more creative based on input image. Provide ONLY the improved prompt, no explanations or quotes, no description of the original image, only ToDo instruction. 
If changing something use this template: Using the provided image, change only the [specific element] to [new element/description]. Keep everything else in the image exactly the same, preserving the original style, lighting, and composition.
If adding or removing use this template: Using the provided image of [subject], please [add/remove/modify] [element] to/from the scene. Ensure the change is [description of how the change should integrate].
"""

# Non-strict version - more creative freedom for editing
EDITING_UPGRADE_PROMPT_LOOSE = """Make initial text instruction {original_prompt} a more creative based on input image. Provide ONLY the improved prompt, no explanations or quotes, no description of the original image, only ToDo instruction."""

DEFAULT_TEXTURE_PROMPT = """Use the attached normal map to define exact generation edges and boundaries and understand the model's geometry, preserve pixel to pixel accuracy to existing normal map. Keep the same object size. Create an entirely new colored texture for this [object_description] based on the prompt."""

DEFAULT_TEXTURE_REF_PROMPT = """Use the attached normal map to define exact generation edges and boundaries and understand the model's geometry, preserve pixel to pixel accuracy to existing normal map. Keep the same object size. Use the reference image only as style and color influence. Create an entirely new colored texture for this [object_description] based on the prompt."""

# PBR Map Generation Prompts
MAP_PROMPTS = {
    'ROUGHNESS': "Create roughness map for this image. Pixel to pixel accuracy.",
    'METALLIC': "Create metallic map for this image. Pixel to pixel accuracy.",
    'HEIGHT': "Create bump height map for this image. Pixel to pixel accuracy."
}

# =============================================================================
# STYLE & MODIFIER OPTIONS
# =============================================================================

# Format: ID: (Prompt Suffix, UI Name)
STYLE_OPTIONS = {
    "NONE": ("", "<no style>"),
    "DIGITAL": (" in digital painting style", "Digital Painting"),
    "SIMS": (" in the style of The Sims (clean, plastic shading, simplified realism)", "Sims Game Style"),
    "CARTOON": (" in stylized cartoon style", "Stylized / Cartoon"),
    "HAND": (" in hand painted texture style", "Hand Painted"),
    "GAME": (" in unreal engine asset style", "Game Asset"),
}

# Format: (ID, UI Name, Prompt Suffix)
LIGHTING_ITEMS = [
    ("NONE", "<no instruction>", ""),
    ("FLAT", "Flat / Neutral", " with neutral ambient occlusion lighting"),
    ("STUDIO", "Studio Soft", " with soft studio lighting"),
    ("NATURAL", "Naturally Lit", " with natural lighting"),
    ("DAY_R", "Daylight (Right)", " with daylight coming from the right"),
    ("DAY_L", "Daylight (Left)", " with daylight coming from the left"),
    ("EVE_R", "Evening (Right)", " with warm evening light from the right"),
    ("EVE_L", "Evening (Left)", " with warm evening light from the left"),
]

MODIFIERS_MAP = {
    "neuro_mod_isometric": " isometric view, 2.5D",
    "neuro_mod_detailed": " sharp details, high readability",
    "neuro_mod_clean": " clean background, isolated",
    "neuro_mod_vibrant": " vibrant colors, joyful palette",
    "neuro_mod_soft": " soft shading, ambient occlusion, cozy atmosphere",
    "neuro_mod_casual": " casual game asset, mobile game style, unity 3d render",
}

# =============================================================================
# FILE PATHS
# =============================================================================

def get_addon_dir():
    """Get the addon directory path"""
    return os.path.dirname(os.path.realpath(__file__))

def get_presets_file():
    """Get the path to the builder presets JSON file"""
    return os.path.join(get_addon_dir(), "neuro_builder_presets.json")

def get_assets_path():
    """Get the path to the assets folder"""
    return os.path.join(get_addon_dir(), "assets")

# =============================================================================
# BUILD METADATA
# =============================================================================

_BUILD_ID = "VS_INTERNAL_2026_02_11_BUILD_1851"
_LICENSED_TO = "Vlad Stoliarenko - Company Use"
PRODUCT_NAME = "Blender AI Nodes"
IS_MRKTV = False