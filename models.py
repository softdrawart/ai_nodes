# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Model Definitions
All AI model configurations in one place for easy maintenance.

To add a new model:
1. Add ModelConfig to appropriate section (IMAGE/TEXT/UTILITY)
2. Follow naming convention:
    - AIML: Base name (no suffix) - primary provider
    - Google: Name (Google) - Priority provider if Available
    - Replicate: Name (Repl) - fallback provider
    - Fal: Name (Fal) - fallback provider

3. Set priority (lower = higher in list)
First goes vendor provider (Google),(OpenAI) etc.)
0 - Nano Banano
5 - Nano Banano Pro
10 - Imagen
120 - Gpt-Image-1
125 - Gpt-Image-1.5
55 - Gemini 3 Pro
170 - Gpt Nano
175 - Gpt 5.1
180 - Gpt 5.2
300 - Grok 4.1
350 - Grok Imagine
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
    _register_image_models_aiml(registry)
    _register_text_models(registry)
    _register_utility_models(registry)


# =============================================================================
# IMAGE GENERATION - AIML API (All-In-One Provider)
# =============================================================================

def _register_image_models_aiml(registry: ModelRegistry):
    """AIML API image models - unified access to multiple AI providers

    AIML API provides access to various models through a single API.
    Model names should match AIML's naming convention (e.g., "openai/gpt-image-1")

    To add more AIML models, copy this template and modify:
    - id: Unique identifier (add -aiml suffix for clarity)
    - name: Display name with (AIML) suffix
    - endpoint: AIML model identifier (e.g., "openai/gpt-image-1", "stability/sdxl")
    - params: Model-specific parameters
    """

    # Nano Banana via AIML
    registry.register(ModelConfig(
        id="nano-banana-aiml",
        name="Nano Banana",
        description="Nano Banana via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/gemini-2.5-flash-image",
        edit_endpoint="google/gemini-2.5-flash-image-edit",
        requires_api_key="aiml",
        priority=1,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.ENUM,
                default="google/gemini-2.5-flash-image",
                options=["google/gemini-2.5-flash-image", "gemini-2.5-flash-image-edit"],
                description="AIML model identifier",
                api_name="model",
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

    # Nano Banana Pro via AIML
    registry.register(ModelConfig(
        id="nano-banana-pro-aiml",
        name="Nano Banana Pro",
        description="Nano Banana Pro via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/nano-banana-pro",
        edit_endpoint="google/nano-banana-pro-edit",
        requires_api_key="aiml",
        priority=6,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.ENUM,
                default="google/nano-banana-pro",
                options=["google/nano-banana-pro", "google/nano-banana-pro-edit"],
                description="AIML model identifier",
                api_name="model",
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
                name="resolution",
                label="Resolution",
                param_type=ParamType.ENUM,
                default="1K",
                options=["1K", "2K", "4K"],
                description="Output resolution",
            ),
        ],
    ))

    # Imagen 4 Ultra via AIML
    registry.register(ModelConfig(
        id="imagen-4-ultra-aiml",
        name="Imagen 4 Ultra",
        description="Google Imagen 4 Ultra via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/imagen-4.0-ultra-generate-001",
        requires_api_key="aiml",
        priority=11,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="google/imagen-4.0-ultra-generate-001",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "9:16", "16:9", "3:4", "4:3"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="enhance_prompt",
                label="Enhance Prompt",
                param_type=ParamType.BOOL,
                default=True,
                description="Use LLM-based prompt rewriting",
            ),
        ],
    ))

    # GPT Image 1 via AIML
    registry.register(ModelConfig(
        id="gpt-image-1-aiml",
        name="GPT Image 1",
        description="OpenAI GPT Image 1 via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="openai/gpt-image-1",
        requires_api_key="aiml",
        priority=121,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-image-1",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Output quality",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background type",
            ),
        ],
    ))

    # GPT Image 1 Mini via AIML
    registry.register(ModelConfig(
        id="gpt-image-1-mini-aiml",
        name="GPT Image 1 Mini",
        description="OpenAI GPT Image 1 Mini - cost-effective variant via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="openai/gpt-image-1-mini",
        requires_api_key="aiml",
        priority=122,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-image-1-mini",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "medium", "high"],
                description="Output quality",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background type",
            ),
        ],
    ))

    # GPT Image 1.5 via AIML
    registry.register(ModelConfig(
        id="gpt-image-1.5-aiml",
        name="GPT Image 1.5 (No input)",
        description="OpenAI GPT Image 1.5 via AIML API",
        provider=Provider.AIML,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="openai/gpt-image-1-5",
        requires_api_key="aiml",
        priority=126,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-image-1-5",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "2:3", "3:2"],
                description="Output aspect ratio (maps to size)",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Output quality",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background type",
            ),
        ],
    ))


# =============================================================================
# IMAGE GENERATION - GOOGLE (suffix: Google)
# =============================================================================

def _register_image_models_google(registry: ModelRegistry):
    """Google direct API image models"""

    registry.register(ModelConfig(
        id="gemini-2.5-flash-image",
        name="Nano Banana (Google)",
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
        id="gemini-3-pro-image-preview",
        name="Nano Banana Pro (Google)",
        description="Complex Image Editing tool via Google",
        provider=Provider.GOOGLE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="gemini-3-pro-image-preview",
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

# =============================================================================
# IMAGE GENERATION - REPLICATE (Repl)
# =============================================================================

def _register_image_models_replicate(registry: ModelRegistry):
    """Replicate image models - base names, no suffix"""

    registry.register(ModelConfig(
        id="nano-banana-repl",
        name="Nano Banana (Repl)",
        description="Fast Image Editing tool via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="google/nano-banana",
        requires_api_key="replicate",
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
        priority=7,
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
        id="gpt-image-1-repl",
        name="GPT Image 1 (Repl)",
        description="GPT Image via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="openai/gpt-image-1",
        requires_api_key="replicate",
        priority=122,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "3:2", "2:3"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="auto",
                options=["low", "medium", "high", "auto"],
                description="Quality level for generation",
            ),
            ModelParam(
                name="input_fidelity",
                label="Input Fidelity",
                param_type=ParamType.ENUM,
                default="low",
                options=["low", "high"],
                description="Fidelity to input image",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background handling",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-image-1.5-repl",
        name="GPT Image 1.5 (Repl)",
        description="Latest GPT Image via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="openai/gpt-image-1.5",
        requires_api_key="replicate",
        priority=127,
        params=[
            ModelParam(
                name="aspect_ratio",
                label="Aspect Ratio",
                param_type=ParamType.ENUM,
                default="1:1",
                options=["1:1", "3:2", "2:3"],
                description="Output aspect ratio",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="auto",
                options=["low", "medium", "high", "auto"],
                description="Quality level for generation",
            ),
            ModelParam(
                name="input_fidelity",
                label="Input Fidelity",
                param_type=ParamType.ENUM,
                default="low",
                options=["low", "high"],
                description="Fidelity to input image",
            ),
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background handling",
            ),
        ],
    ))


# =============================================================================
# IMAGE GENERATION - FAL (suffix: Fal)
# =============================================================================

def _register_image_models_fal(registry: ModelRegistry):
    """Fal.AI image models"""

    registry.register(ModelConfig(
        id="nano-banana-fal",
        name="Nano Banana (Fal)",
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
        id="gpt-image-1-fal",
        name="GPT Image 1 (Fal)",
        description="GPT Image via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="fal-ai/gpt-image-1/text-to-image",
        edit_endpoint="fal-ai/gpt-image-1/edit-image",
        requires_api_key="fal",
        size_options=["1024x1024", "1536x1024", "1024x1536"],
        default_size="1024x1024",
        priority=123,
    ))

    registry.register(ModelConfig(
        id="gpt-image-1.5-fal",
        name="GPT Image 1.5 (Fal)",
        description="Latest GPT Image via Fal",
        provider=Provider.FAL,
        category=ModelCategory.IMAGE_GENERATION,
        endpoint="fal-ai/gpt-image-1.5",
        edit_endpoint="fal-ai/gpt-image-1.5/edit",
        requires_api_key="fal",
        size_options=["1024x1024", "1536x1024", "1024x1536"],
        default_size="1024x1024",
        priority=128,
        params=[
            ModelParam(
                name="background",
                label="Background",
                param_type=ParamType.ENUM,
                default="auto",
                options=["auto", "transparent", "opaque"],
                description="Background for the generated image",
            ),
            ModelParam(
                name="quality",
                label="Quality",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "medium", "high"],
                description="Quality level for generation",
            ),
            ModelParam(
                name="input_fidelity",
                label="Input Fidelity",
                param_type=ParamType.ENUM,
                default="high",
                options=["low", "high"],
                description="Fidelity to input image (for editing)",
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


# =============================================================================
# TEXT GENERATION MODELS
# =============================================================================

def _register_text_models(registry: ModelRegistry):
    """Text generation models for all providers"""

    # --- AIML (No suffix) ---

    registry.register(ModelConfig(
        id="gemini-3-flash-aiml",
        name="Gemini 3 Flash",
        description="Fast and cheap Gemini via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="google/gemini-3-flash-preview",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=51,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="google/gemini-3-flash-preview",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="max_tokens",
                label="Max Tokens",
                param_type=ParamType.INT,
                default=15000,
                min_val=500,
                max_val=25000,
                description="Maximum length of response",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gemini-3-pro-aiml",
        name="Gemini 3 Pro",
        description="Latest Google reasoning via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="google/gemini-3-pro-preview",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=56,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="google/gemini-3-pro-preview",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="max_tokens",
                label="Max Tokens",
                param_type=ParamType.INT,
                default=25000,
                min_val=1000,
                max_val=50000,
                description="Maximum length of response",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="claude-sonnet-4-5-aiml",
        name="Claude Sonnet 4.5",
        description="Claude Sonnet 4.5 is the best coding model to date",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="anthropic/claude-sonnet-4.5",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=101,
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
        id="gpt-5-nano-aiml",
        name="GPT Nano",
        description="Fast GPT via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5-nano-2025-08-07",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=171,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-5-nano-2025-08-07",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="low",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-5.1-aiml",
        name="GPT-5.1",
        description="GPT-5.1 via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5-1",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=176,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-5-1",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="none",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-5.2-aiml",
        name="GPT-5.2",
        description="GPT-5.2 via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5-2",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=181,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="openai/gpt-5-2",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="low",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="grok-4.1-r-aiml",
        name="Grok 4.1 Reasoning",
        description="Grok 4.1 via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="x-ai/grok-4-1-fast-reasoning",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=301,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="x-ai/grok-4-1-fast-reasoning",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="grok-4.1-f--aiml",
        name="Grok 4.1 Fast",
        description="Grok 4.1 via AIML",
        provider=Provider.AIML,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="x-ai/grok-4-1-fast-non-reasoning",
        requires_api_key="aiml",
        supports_images=True,
        supports_batch=False,
        priority=301,
        params=[
            ModelParam(
                name="aiml_model_name",
                label="Model Name",
                param_type=ParamType.STRING,
                default="x-ai/grok-4-1-fast-non-reasoning",
                description="AIML model identifier",
                api_name="model",
            ),
            ModelParam(
                name="temperature",
                label="Temperature",
                param_type=ParamType.FLOAT,
                default=1.0,
                min_val=0.3,
                max_val=2.0,
                description="Creativity level",
            ),
        ],
    ))

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
        name="Gemini 3 Pro (Repl)",
        description="Latest Google reasoning with thinking via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="google/gemini-3-pro",
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
        id="gpt-5-nano-repl",
        name="GPT nano (Repl)",
        description="Fast and cheap GPT-5 via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5-nano",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=172,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="none",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
            ModelParam(
                name="verbosity",
                label="Verbosity",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Response verbosity",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-5.1-repl",
        name="GPT-5.1 (Repl)",
        description="OpenAI GPT-5.1 - balanced reasoning via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5.1",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=177,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="none",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
            ModelParam(
                name="verbosity",
                label="Verbosity",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Response verbosity",
            ),
        ],
    ))

    registry.register(ModelConfig(
        id="gpt-5.2-repl",
        name="GPT-5.2 (Repl)",
        description="OpenAI GPT-5.2 - latest advanced reasoning via Replicate",
        provider=Provider.REPLICATE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="openai/gpt-5.2",
        requires_api_key="replicate",
        supports_images=True,
        supports_batch=False,
        priority=182,
        params=[
            ModelParam(
                name="reasoning_effort",
                label="Reasoning",
                param_type=ParamType.ENUM,
                default="low",
                options=["none", "low", "medium", "high"],
                description="How much reasoning to apply",
            ),
            ModelParam(
                name="verbosity",
                label="Verbosity",
                param_type=ParamType.ENUM,
                default="medium",
                options=["low", "medium", "high"],
                description="Response verbosity",
            ),
        ],
    ))

    # --- GOOGLE (suffix: Google) ---

    registry.register(ModelConfig(
        id="gemini-3-flash-preview",
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
        id="gemini-3-pro-preview",
        name="Gemini 3 Pro (Google)",
        description="Latest Google reasoning with thinking",
        provider=Provider.GOOGLE,
        category=ModelCategory.TEXT_GENERATION,
        endpoint="gemini-3-pro-preview",
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