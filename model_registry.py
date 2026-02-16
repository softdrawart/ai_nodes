# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Model Configuration Registry
Extensible model definitions for easy addition of new AI models with custom parameters.

Supports multiple providers (Google, Fal.AI, Replicate, etc.) with a unified interface.

Usage:
    from .model_registry import (
        get_model, register_model, ModelConfig, ModelParam, ParamType,
        Provider, get_image_models, get_text_models
    )

    # Get a model config
    config = get_model("gpt-image-1.5")

    # Build API args with user's param values
    args = build_api_args("gpt-image-1.5", {"prompt": "..."}, {"quality": "high"})
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class ParamType(Enum):
    """Types of model parameters"""
    ENUM = "enum"  # Dropdown selection
    STRING = "string"  # Text input
    INT = "int"  # Integer number
    FLOAT = "float"  # Decimal number
    BOOL = "bool"  # Checkbox


class Provider(Enum):
    """Supported API providers"""
    GOOGLE = "google"  # Direct Google Gemini API
    FAL = "fal"  # Fal.AI (backup)
    REPLICATE = "replicate"  # Replicate.ai (primary alternative)
    TRIPO = "tripo"  # Tripo 3D mesh generation
    AIML = "aiml"  # AIML API (unified access to multiple models)


class ModelCategory(Enum):
    """Model categories for organization"""
    IMAGE_GENERATION = "image"
    TEXT_GENERATION = "text"
    IMAGE_EDITING = "edit"
    MESH_GENERATION = "mesh"  # 3D model generation
    UTILITY = "utility"  # Background removal, upscaling, etc.


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ModelParam:
    """
    Definition of a model-specific parameter.

    Attributes:
        name: Internal name (e.g., "background")
        label: UI label (e.g., "Background")
        param_type: Parameter type (ENUM, STRING, INT, etc.)
        default: Default value
        options: For ENUM type - list of choices
        min_val: For numeric types - minimum value
        max_val: For numeric types - maximum value
        step: For numeric types - step increment
        description: Tooltip text
        api_name: API param name if different from `name`
        visible: Whether to show in UI by default
        advanced: If True, only show in "advanced" mode
    """
    name: str
    label: str
    param_type: ParamType
    default: Any
    options: Optional[List[str]] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    description: str = ""
    api_name: Optional[str] = None
    visible: bool = True  # User can toggle this off to use default
    advanced: bool = False  # Only show in advanced/expanded mode

    def get_api_name(self) -> str:
        """Get the name to use in API calls"""
        return self.api_name if self.api_name else self.name

    def get_blender_items(self) -> List[tuple]:
        """Get items for Blender EnumProperty"""
        if self.param_type != ParamType.ENUM or not self.options:
            return []
        return [(opt, opt.replace("_", " ").title(), "") for opt in self.options]

    def validate(self, value: Any) -> Any:
        """Validate and coerce value to correct type"""
        if self.param_type == ParamType.ENUM:
            if self.options and value not in self.options:
                return self.default
            return value
        elif self.param_type == ParamType.INT:
            val = int(value)
            if self.min_val is not None:
                val = max(int(self.min_val), val)
            if self.max_val is not None:
                val = min(int(self.max_val), val)
            return val
        elif self.param_type == ParamType.FLOAT:
            val = float(value)
            if self.min_val is not None:
                val = max(self.min_val, val)
            if self.max_val is not None:
                val = min(self.max_val, val)
            return val
        elif self.param_type == ParamType.BOOL:
            return bool(value)
        return value


@dataclass
class ModelConfig:
    """
    Complete configuration for a generation model.

    Attributes:
        id: Unique identifier (e.g., "gpt-image-1.5")
        name: Display name for UI
        description: Description tooltip
        provider: API provider (FAL, GOOGLE, REPLICATE, etc.)
        category: Model category (IMAGE_GENERATION, TEXT_GENERATION, etc.)

        endpoint: Primary endpoint path
        edit_endpoint: Editing endpoint (for image-to-image)

        supports_images: Can accept input images
        supports_batch: Can generate multiple outputs
        max_batch_size: Maximum outputs per request
        supports_streaming: Supports streaming responses (for text)

        size_param_name: API parameter name for image size
        size_options: Available size options
        default_size: Default size option

        params: List of model-specific parameters

        requires_api_key: Which API key type is needed
        timeout_default: Default timeout in seconds

        enabled: Whether model is enabled (user can disable)
        priority: Sort order (lower = higher in list)
    """
    # Identity
    id: str
    name: str
    description: str = ""
    provider: Provider = Provider.FAL
    category: ModelCategory = ModelCategory.IMAGE_GENERATION

    # Endpoints
    endpoint: str = ""
    edit_endpoint: Optional[str] = None

    # Capabilities
    supports_images: bool = True
    supports_batch: bool = True
    max_batch_size: int = 4
    supports_streaming: bool = False

    # Size/Resolution
    size_param_name: str = "image_size"
    size_options: List[str] = field(default_factory=lambda: ["1024x1024"])
    default_size: str = "1024x1024"

    # Model-specific parameters
    params: List[ModelParam] = field(default_factory=list)

    # Requirements
    requires_api_key: str = "fal"
    timeout_default: int = 60

    # UI State
    enabled: bool = True
    priority: int = 100  # Lower = higher in list

    def get_param(self, name: str) -> Optional[ModelParam]:
        """Get a parameter by name"""
        for p in self.params:
            if p.name == name:
                return p
        return None

    def get_visible_params(self, include_advanced: bool = False) -> List[ModelParam]:
        """Get parameters that should be visible in UI"""
        return [p for p in self.params
                if p.visible and (include_advanced or not p.advanced)]

    def get_endpoint(self, has_input_images: bool = False) -> str:
        """Get appropriate endpoint based on whether we have input images"""
        if has_input_images and self.edit_endpoint:
            return self.edit_endpoint
        return self.endpoint


# =============================================================================
# MODEL REGISTRY
# =============================================================================

class ModelRegistry:
    """
    Central registry for all model configurations.
    Singleton pattern - use get_registry() to access.
    """

    def __init__(self):
        self._models: Dict[str, ModelConfig] = {}
        self._param_visibility: Dict[str, Dict[str, bool]] = {}  # model_id -> {param_name: visible}

    def register(self, config: ModelConfig) -> ModelConfig:
        """Register a model configuration"""
        self._models[config.id] = config
        # Initialize param visibility from defaults
        self._param_visibility[config.id] = {p.name: p.visible for p in config.params}
        return config

    def unregister(self, model_id: str) -> bool:
        """Remove a model from registry"""
        if model_id in self._models:
            del self._models[model_id]
            if model_id in self._param_visibility:
                del self._param_visibility[model_id]
            return True
        return False

    def get(self, model_id: str) -> Optional[ModelConfig]:
        """Get model configuration by ID"""
        return self._models.get(model_id)

    def get_all(self) -> List[ModelConfig]:
        """Get all registered models, sorted by priority"""
        return sorted(self._models.values(), key=lambda m: (m.priority, m.name))

    def get_by_provider(self, provider: Provider) -> List[ModelConfig]:
        """Get all models for a specific provider"""
        return [m for m in self.get_all() if m.provider == provider and m.enabled]

    def get_by_category(self, category: ModelCategory) -> List[ModelConfig]:
        """Get all models of a specific category"""
        return [m for m in self.get_all() if m.category == category and m.enabled]

    def get_image_models(self) -> List[ModelConfig]:
        """Get all image generation models"""
        return [m for m in self.get_all()
                if m.category in (ModelCategory.IMAGE_GENERATION, ModelCategory.IMAGE_EDITING)
                and m.enabled]

    def get_text_models(self) -> List[ModelConfig]:
        """Get all text generation models"""
        return [m for m in self.get_all()
                if m.category == ModelCategory.TEXT_GENERATION and m.enabled]

    def get_blender_enum_items(self, category: Optional[ModelCategory] = None) -> List[tuple]:
        """Get model items for Blender EnumProperty"""
        if category:
            models = self.get_by_category(category)
        else:
            models = [m for m in self.get_all() if m.enabled]
        return [(m.id, m.name, m.description) for m in models]

    def get_filtered_enum_items(self, category: Optional[ModelCategory] = None,
                                enabled_providers: Optional[set] = None,
                                disabled_models: Optional[set] = None) -> List[tuple]:
        """
        Get model items filtered by enabled providers and disabled models.

        Args:
            category: Filter by model category
            enabled_providers: Set of enabled provider names (e.g., {"google", "replicate"})
            disabled_models: Set of explicitly disabled model IDs
        """
        enabled_providers = enabled_providers or {"google", "fal", "replicate"}
        disabled_models = disabled_models or set()

        models = self.get_all()

        # Filter by category
        if category:
            models = [m for m in models if m.category == category]

        # Filter by provider and model enabled status
        filtered = []
        for m in models:
            if not m.enabled:
                continue
            if m.provider.value not in enabled_providers:
                continue
            if m.id in disabled_models:
                continue
            filtered.append(m)

        return [(m.id, m.name, m.description) for m in filtered]

    # --- Param Visibility Management ---

    def set_param_visible(self, model_id: str, param_name: str, visible: bool):
        """Set whether a parameter is visible in UI"""
        if model_id not in self._param_visibility:
            self._param_visibility[model_id] = {}
        self._param_visibility[model_id][param_name] = visible

    def is_param_visible(self, model_id: str, param_name: str) -> bool:
        """Check if a parameter is visible"""
        if model_id in self._param_visibility:
            return self._param_visibility[model_id].get(param_name, True)
        return True

    def get_visible_params(self, model_id: str, include_advanced: bool = False) -> List[ModelParam]:
        """Get visible parameters for a model, respecting user preferences"""
        model = self.get(model_id)
        if not model:
            return []

        result = []
        for p in model.params:
            if not include_advanced and p.advanced:
                continue
            if self.is_param_visible(model_id, p.name):
                result.append(p)
        return result

    # --- Model Enable/Disable ---

    def set_enabled(self, model_id: str, enabled: bool):
        """Enable or disable a model"""
        if model_id in self._models:
            self._models[model_id].enabled = enabled

    def is_enabled(self, model_id: str) -> bool:
        """Check if a model is enabled"""
        model = self.get(model_id)
        return model.enabled if model else False

    # --- Provider Switching ---

    def get_base_model_name(self, model_id: str) -> str:
        """
        Get the base name of a model (without provider suffix).
        Used for provider switching - same model different provider.

        Examples:
            nano-banana -> nano-banana
            nano-banana-google -> nano-banana
            nano-banana-fal -> nano-banana
            gpt-image-1.5 -> gpt-image-1.5
            gpt-image-1.5-fal -> gpt-image-1.5
        """
        # Remove known provider suffixes
        for suffix in ["-google", "-fal", "-replicate"]:
            if model_id.endswith(suffix):
                return model_id[:-len(suffix)]
        return model_id

    def get_model_for_provider(self, base_model_id: str, provider: Provider) -> Optional[str]:
        """
        Get the model ID for a specific provider given a base model.

        Args:
            base_model_id: The base model ID (e.g., "nano-banana-pro")
            provider: The desired provider

        Returns:
            The model ID for that provider, or None if not available
        """
        base_name = self.get_base_model_name(base_model_id)

        # Build expected IDs
        if provider == Provider.REPLICATE:
            # Replicate is base (no suffix)
            candidates = [base_name]
        elif provider == Provider.GOOGLE:
            candidates = [f"{base_name}-google", base_name]
        elif provider == Provider.FAL:
            candidates = [f"{base_name}-fal", base_name]
        else:
            candidates = [base_name]

        for candidate_id in candidates:
            model = self.get(candidate_id)
            if model and model.provider == provider:
                return candidate_id

        return None

    def get_models_for_active_provider(self,
                                       category: ModelCategory,
                                       active_provider: Provider) -> List[tuple]:
        """
        Get enum items for models of a category from the active provider.

        Args:
            category: The model category (IMAGE_GENERATION, TEXT_GENERATION, etc.)
            active_provider: The currently selected provider

        Returns:
            List of (id, name, description) tuples for Blender EnumProperty
        """
        models = [m for m in self.get_all()
                  if m.category == category
                  and m.provider == active_provider
                  and m.enabled]
        return [(m.id, m.name, m.description) for m in models]


# Singleton instance
_registry: Optional[ModelRegistry] = None


def get_registry() -> ModelRegistry:
    """Get the singleton registry instance"""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
        # Import model definitions from models.py
        from .models import register_all_models
        register_all_models(_registry)
    return _registry


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def register_model(config: ModelConfig) -> ModelConfig:
    """Register a model configuration"""
    return get_registry().register(config)


def get_model(model_id: str) -> Optional[ModelConfig]:
    """Get model configuration by ID"""
    return get_registry().get(model_id)


def get_all_models() -> List[ModelConfig]:
    """Get all registered models"""
    return get_registry().get_all()


def get_image_models() -> List[ModelConfig]:
    """Get all image generation models"""
    return get_registry().get_image_models()


def get_text_models() -> List[ModelConfig]:
    """Get all text generation models"""
    return get_registry().get_text_models()


def get_blender_enum_items(category: Optional[ModelCategory] = None) -> List[tuple]:
    """Get model items for Blender EnumProperty"""
    return get_registry().get_blender_enum_items(category)


# =============================================================================
# API ARGUMENT BUILDING
# =============================================================================

def build_api_args(
        model_id: str,
        base_args: dict,
        param_values: dict,
        respect_visibility: bool = True
) -> dict:
    """
    Build complete API arguments including model-specific params.

    Args:
        model_id: The model identifier
        base_args: Base arguments (prompt, images, etc.)
        param_values: Dict of param_name -> value for model-specific params
        respect_visibility: If True, skip params that user has disabled

    Returns:
        Complete arguments dict for API call
    """
    registry = get_registry()
    config = registry.get(model_id)
    if not config:
        return base_args

    args = base_args.copy()

    for param in config.params:
        # Skip if user has disabled this param in UI
        if respect_visibility and not registry.is_param_visible(model_id, param.name):
            continue

        # Get value or use default
        value = param_values.get(param.name, param.default)
        value = param.validate(value)

        # Add to args with correct API name
        args[param.get_api_name()] = value

    return args


def get_model_defaults(model_id: str) -> dict:
    """Get default values for all model-specific params"""
    config = get_model(model_id)
    if not config:
        return {}
    return {p.name: p.default for p in config.params}


def get_size_for_aspect_ratio(model_id: str, aspect_ratio: str) -> str:
    """Get the appropriate size string for a model and aspect ratio"""
    config = get_model(model_id)
    if not config:
        return "1024x1024"

    # Standard aspect ratio to size mapping
    ratio_to_size = {
        "1:1": ["1024x1024", "512x512", "2048x2048"],
        "3:4": ["1024x1536", "768x1024"],
        "4:3": ["1536x1024", "1024x768"],
        "16:9": ["1536x1024", "1920x1080"],
        "9:16": ["1024x1536", "1080x1920"],
        "21:9": ["1536x1024"],
    }

    # Find matching size from model's options
    preferred = ratio_to_size.get(aspect_ratio, ["1024x1024"])
    for size in preferred:
        if size in config.size_options:
            return size

    # Fallback to model's default
    return config.default_size


# =============================================================================
# PROVIDER-SPECIFIC MODEL SELECTION HELPERS
# =============================================================================

def get_stored_model_for_provider(context, category: ModelCategory, provider_name: str) -> str:
    """Get the stored model selection for a specific provider.

    Args:
        context: Blender context
        category: IMAGE_GENERATION or TEXT_GENERATION
        provider_name: 'replicate', 'google', or 'fal'

    Returns:
        Model ID string or empty string if not found
    """
    try:
        from .utils import get_addon_name
        addon_name = get_addon_name()
        if addon_name and addon_name in context.preferences.addons:
            prefs = context.preferences.addons[addon_name].preferences

            if category == ModelCategory.IMAGE_GENERATION:
                prop_name = f"selected_image_model_{provider_name}"
            else:
                prop_name = f"selected_text_model_{provider_name}"

            if hasattr(prefs, prop_name):
                return getattr(prefs, prop_name)
    except Exception as e:
        print(f"[Model Registry] Error getting stored model: {e}")

    return ""


def set_stored_model_for_provider(context, category: ModelCategory, provider_name: str, model_id: str):
    """Store the model selection for a specific provider.

    Args:
        context: Blender context
        category: IMAGE_GENERATION or TEXT_GENERATION
        provider_name: 'replicate', 'google', or 'fal'
        model_id: Model ID to store
    """
    try:
        from .utils import get_addon_name
        addon_name = get_addon_name()
        if addon_name and addon_name in context.preferences.addons:
            prefs = context.preferences.addons[addon_name].preferences

            if category == ModelCategory.IMAGE_GENERATION:
                prop_name = f"selected_image_model_{provider_name}"
            else:
                prop_name = f"selected_text_model_{provider_name}"

            if hasattr(prefs, prop_name):
                setattr(prefs, prop_name, model_id)
    except Exception as e:
        print(f"[Model Registry] Error storing model: {e}")


def get_active_provider(context) -> str:
    """Get the currently active provider from preferences."""
    try:
        from .utils import get_addon_name
        addon_name = get_addon_name()
        if addon_name and addon_name in context.preferences.addons:
            prefs = context.preferences.addons[addon_name].preferences
            return prefs.active_provider
    except Exception:
        pass
    return "replicate"


def get_enabled_providers(context) -> list:
    """Get list of enabled provider names."""
    try:
        from .utils import get_addon_name
        addon_name = get_addon_name()
        if addon_name and addon_name in context.preferences.addons:
            prefs = context.preferences.addons[addon_name].preferences
            enabled = []
            if prefs.provider_replicate_enabled:
                enabled.append('replicate')
            if prefs.provider_google_enabled:
                enabled.append('google')
            if prefs.provider_fal_enabled:
                enabled.append('fal')
            return enabled
    except Exception:
        pass
    return ['replicate', 'google']


# =============================================================================
# PROVIDER HANDLERS (Abstract interface for future expansion)
# =============================================================================

class ProviderHandler:
    """
    Abstract base for provider-specific API handling.
    Subclass this for each provider (Fal, Google, Replicate, etc.)
    """

    provider: Provider

    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate(
            self,
            model_config: ModelConfig,
            prompt: str,
            images: List[str] = None,
            params: dict = None,
            cancel_event=None,
    ) -> List[Any]:
        """Generate content using the model"""
        raise NotImplementedError

    def stream(
            self,
            model_config: ModelConfig,
            prompt: str,
            images: List[str] = None,
            params: dict = None,
    ):
        """Stream content (for text models)"""
        raise NotImplementedError


# Provider handler registry (for future use)
_provider_handlers: Dict[Provider, type] = {}


def register_provider_handler(provider: Provider, handler_class: type):
    """Register a handler class for a provider"""
    _provider_handlers[provider] = handler_class


def get_provider_handler(provider: Provider, api_key: str) -> Optional[ProviderHandler]:
    """Get an instantiated handler for a provider"""
    handler_class = _provider_handlers.get(provider)
    if handler_class:
        return handler_class(api_key)
    return None