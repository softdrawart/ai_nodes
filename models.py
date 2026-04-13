# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Model Definitions
All AI model configurations in one place for easy maintenance.

To add a new model:
1. Add ModelConfig to appropriate section (IMAGE/TEXT/UTILITY)
2. Follow naming convention:
    - Google: Name (Google) - Priority provider if Available
    - OpenAI: Name (-oai) - Direct OpenAI API (NeuroToken only)
    - Replicate: Name (Repl) - fallback provider
    - Fal: Name (Fal) - fallback provider

3. Set priority (lower = higher in list)
First goes vendor provider (Google),(OpenAI) etc.)
0 - Nano Banana Mini
5 - Nano Banana
10 - Nano Banana Pro
50 - Imagen
55 - Gemini 3 Pro
120 - Gpt Image (1.0)
125 - Gpt Image Mini (1.0 mini)
130 - Gpt Image Pro (1.5)
170 - Gpt Nano
180 - Gpt (5.2)
190 - Gpt Latest (5.4)
300 - Grok 4.1
350 - Grok Imagine
400 - Flux
450 - Flux 2 PRO
900 - BirefNet
"""

from .model_registry import (
    ModelConfig, ModelParam, ParamType,
    Provider, ModelCategory, ModelRegistry
)


def register_all_models(registry: ModelRegistry):
    """Register all built-in models. Called by model_registry on init."""

    _register_image_models_replicate(registry)
    _register_image_models_google(registry)
    _register_image_models_fal(registry)
    _register_text_models(registry)
    _register_openai_models(registry)
    _register_utility_models(registry)


# =============================================================================
# IMAGE GENERATION - GOOGLE (suffix: Google)
# =============================================================================

def _register_image_models_google(registry: ModelRegistry):
    """Google direct API image models"""

    registry.register(ModelConfig(
        id="nano-banana-mini-google",
        name="Nano Banana Mini (Google)",
        description="Fast Image Editing tool via Google",
        provider=Provider.GOOGLE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gemini-2.5-flash-image",
        requires_api_key="google",
        priority=0,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
        ]
    ))

    registry.register(ModelConfig(
        id="nano-banana-google",
        name="Nano Banana (Google)",
        description="Best Image Editing tool via Google",
        provider=Provider.GOOGLE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gemini-3.1-flash-image-preview",
        requires_api_key="google",
        priority=5,
        params=[
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="2K",
                options=["1K", "2K", "4K"],
                api_name="image_size",
                description="Output image resolution",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="google_search",
                label="Web Search",
                param_type=ParamType.BOOL,
                default=False,
                description="Enable Google Search for real-time information",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="nano-banana-pro-google",
        name="Nano Banana Pro (Google)",
        description="Complex Image Editing tool via Google",
        provider=Provider.GOOGLE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gemini-3-pro-image-preview",
        requires_api_key="google",
        priority=10,
        params=[
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="2K",
                options=["1K", "2K", "4K"],
                api_name="image_size",
                description="Output image resolution",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="google_search",
                label="Web Search",
                param_type=ParamType.BOOL,
                default=False,
                description="Enable Google Search for real-time information",
            ),
        ],
    ))

# =============================================================================
# IMAGE GENERATION - REPLICATE (Repl)
# =============================================================================

def _register_image_models_replicate(registry: ModelRegistry):
    """Replicate image models - base names, no suffix"""

    registry.register(ModelConfig(
        id="nano-banana-mini-repl",
        name="Nano Banana Mini (Repl)",
        description="Fast Image Editing tool via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/nano-banana",
        requires_api_key="replicate",
        image_param_name="image_input",
        image_as_array=True,
        priority=2,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="nano-banana-pro-repl",
        name="Nano Banana Pro (Repl)",
        description="Complex Image Editing tool via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/nano-banana-pro",
        requires_api_key="replicate",
        image_param_name="image_input",
        image_as_array=True,
        priority=12,
        params=[
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="2K",
                options=["1K", "2K", "4K"],
                description="Output resolution",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="nano-banana-repl",
        name="Nano Banana (Repl)",
        description="Best Image Editing tool via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/nano-banana-2",
        requires_api_key="replicate",
        image_param_name="image_input",
        image_as_array=True,
        priority=7,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "match_input_image"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="grok-imagen-repl",
        name="Grok Imagen (Repl)",
        description="Latest Grok Imagen via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="xai/grok-imagine-image",
        requires_api_key="replicate",
        image_param_name="image",
        image_as_array=False,
        priority=352,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2",
                         "19.5:9", "9:19.5", "20:9", "9:20", "auto"],
                description="Output aspect ratio (ignored when editing an image)",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="flux2-pro-repl",
        name="Flux 2 Pro (Repl)",
        description="Flux 2 Pro via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="black-forest-labs/flux-2-pro",
        requires_api_key="replicate",
        image_param_name="input_images",
        image_as_array=True,
        priority=452,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "match_input_image"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="1 MP",
                options=["match_input_image", "0.5 MP", "1 MP", "2 MP", "4 MP"],
                description="Resolution in megapixels. 2 MP or below is recommended.",
            )
        ],
    ))


# =============================================================================
# IMAGE GENERATION - FAL (suffix: Fal)
# =============================================================================

def _register_image_models_fal(registry: ModelRegistry):
    """Fal.AI image models"""

    registry.register(ModelConfig(
        id="nano-banana-mini-fal",
        name="Nano Banana Mini (Fal)",
        description="Fast Image Editing tool via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="fal-ai/nano-banana",
        edit_endpoint="fal-ai/nano-banana/edit",
        requires_api_key="fal",
        priority=3,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="nano-banana-pro-fal",
        name="Nano Banana Pro (Fal)",
        description="Complex Image Editing tool via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="fal-ai/nano-banana-pro",
        edit_endpoint="fal-ai/nano-banana-pro/edit",
        requires_api_key="fal",
        priority=13,
        params=[
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="2K",
                options=["1K", "2K", "4K"],
                description="Output resolution",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="enable_web_search",
                label="Web Search",
                param_type=ParamType.BOOL,
                default=False,
                description="Enable web search for real-time information",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="nano-banana-fal",
        name="Nano Banana (Fal)",
        description="Best Image Editing tool via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="fal-ai/nano-banana-2",
        edit_endpoint="fal-ai/nano-banana-2/edit",
        requires_api_key="fal",
        priority=8,
        params=[
            ModelParam(
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="2K",
                options=["1K", "2K", "4K"],
                description="Output resolution",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="grok-imagen-fal",
        name="Grok Imagen (Fal)",
        description="Latest Grok Imagen via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="xai/grok-imagine-image",
        edit_endpoint="xai/grok-imagine-image/edit",
        requires_api_key="fal",
        priority=353,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:1", "20:9", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "9:20", "1:2"],
                description="Output aspect ratio",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="flux2-pro-fal",
        name="Flux 2 Pro (Fal)",
        description="Flux 2 Pro via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="black-forest-labs/flux-2-pro",
        requires_api_key="fal",
        image_param_name="input_images",
        image_as_array=True,
        priority=453,
        params=[
        ],
    ))


# =============================================================================
# TEXT GENERATION MODELS
# =============================================================================

def _register_text_models(registry: ModelRegistry):
    """Text generation models for all providers"""

    # --- REPLICATE (Repl) ---

    registry.register(ModelConfig(
        id="gemini-3-flash-repl",
        name="Gemini 3 Flash (Repl)",
        description="Fast Google reasoning with thinking via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="google/gemini-3-flash",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=52,
        params=[
            ModelParam(
                name="thinking_level",
                label="Thinking",
                param_type=ParamType.ENUM,
                default="low",
                options=["low", "high"],
                description="Depth of reasoning",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gemini-3-pro-repl",
        name="Gemini 3.1 Pro (Repl)",
        description="Latest Google reasoning with thinking via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="google/gemini-3.1-pro",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=57,
        params=[
            ModelParam(
                name="thinking_level",
                label="Thinking",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "high"],
                description="Depth of reasoning",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="claude-sonnet-4-5-repl",
        name="Claude Sonnet 4.5 (Repl)",
        description="Claude Sonnet 4.5 is the best coding model to date",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="anthropic/claude-4.5-sonnet",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=102,
        params=[
            ModelParam(
                name="max_tokens",
                label="Max Tokens",
                param_type=ParamType.INT,
                default=8192,
                min_val=1024,
                max_val=64000,
                description="Maximum length of response",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="claude-opus-4-6-repl",
        name="Claude Opus 4.6 (Repl)",
        description="Claude Opus 4.6",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="anthropic/claude-opus-4.6",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=107,
        params=[
            ModelParam(
                name="max_tokens",
                label="Max Tokens",
                param_type=ParamType.INT,
                default=8192,
                min_val=1024,
                max_val=64000,
                description="Maximum length of response",
            ),
        ],
    ))

    # --- GOOGLE (suffix: Google) ---

    registry.register(ModelConfig(
        id="gemini-3-flash-google",
        name="Gemini 3 Flash (Google)",
        description="Fast Google reasoning with thinking",
        provider=Provider.GOOGLE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gemini-3-flash-preview",
        requires_api_key="google",
        supports_images=True,
        supports_batch=False,
        priority=50,
        params=[
            ModelParam(
                name="thinking_level",
                label="Thinking",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "high"],
                description="Depth of reasoning",
            ),
            ModelParam(
                name="use_google_search",
                label="Google Search",
                param_type=ParamType.BOOL,
                default=False,
                description="Enable Google Search grounding",
                advanced=True,
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gemini-3-pro-google",
        name="Gemini 3.1 Pro (Google)",
        description="Latest Google reasoning with thinking",
        provider=Provider.GOOGLE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gemini-3.1-pro-preview",
        requires_api_key="google",
        supports_images=True,
        supports_batch=False,
        priority=55,
        params=[
            ModelParam(
                name="thinking_level",
                label="Thinking",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "high"],
                description="Depth of reasoning",
            ),
            ModelParam(
                name="use_google_search",
                label="Google Search",
                param_type=ParamType.BOOL,
                default=False,
                description="Enable Google Search grounding",
                advanced=True,
            ),
        ],
    ))


# =============================================================================
# OPENAI DIRECT MODELS (-oai suffix, NeuroToken only)
# =============================================================================

def _register_openai_models(registry: ModelRegistry):
    """OpenAI direct API models — NeuroToken only, no provider key required."""

    # --- TEXT ---

    registry.register(ModelConfig(
        id="text-gpt-nano-oai",
        name="GPT Nano",
        description="Fast GPT model via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gpt-5-nano",
        supports_images=True,
        supports_batch=False,
        priority=171,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Reasoning effort level",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="text-gpt-oai",
        name="GPT",
        description="Advanced GPT model via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gpt-5.2",
        supports_images=True,
        supports_batch=False,
        priority=173,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Reasoning effort level",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="text-gpt-latest-oai",
        name="GPT Latest",
        description="Best GPT model via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gpt-5.4",
        supports_images=True,
        supports_batch=False,
        priority=174,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "medium", "high"],
                description="Reasoning effort level",
            ),
        ],
    ))

    # --- IMAGE ---

    registry.register(ModelConfig(
        id="gpt-image-oai",
        name="GPT Image",
        description="OpenAI image generation via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gpt-image-1",
        supports_images=True,
        supports_batch=False,
        priority=175,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "9:16", "16:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "low", "medium", "high"],
                description="Image quality level",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background style",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-image-mini-oai",
        name="GPT Image Mini",
        description="Fast OpenAI image generation via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gpt-image-1-mini",
        supports_images=True,
        supports_batch=False,
        priority=176,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "9:16", "16:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "low", "medium", "high"],
                description="Image quality level",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background style",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-image-pro-oai",
        name="GPT Image Pro",
        description="Latest OpenAI image model via OpenAI API",
        provider=Provider.OPENAI,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gpt-image-1.5",
        supports_images=True,
        supports_batch=False,
        priority=177,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2", "9:16", "16:9"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "low", "medium", "high"],
                description="Image quality level",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background style",
            ),
        ],
    ))


# =============================================================================
# UTILITY MODELS
# =============================================================================

def _register_utility_models(registry: ModelRegistry):
    """Utility models (background removal, upscaling, etc.)"""

    registry.register(ModelConfig(
        id="birefnet-repl",
        name="Background Removal (Repl)",
        description="BiRefNet via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.UTILITY,
        endpoint="men1scus/birefnet:f74986db0355b58403ed20963af156525e2891ea3c2d499bfbfb2a28cd87c5d7",
        requires_api_key="replicate",
        supports_batch=False,
        priority=902,
    ))

    registry.register(ModelConfig(
        id="birefnet-fal",
        name="Background Removal (Fal)",
        description="BiRefNet via Fal.AI",
        provider=Provider.FAL,
        category=ModelCategory.UTILITY,
        endpoint="fal-ai/birefnet",
        requires_api_key="fal",
        supports_batch=False,
        priority=903,
    ))