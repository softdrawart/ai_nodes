# -*- coding: utf-8 -*-
import bpy
from ..model_registry import get_registry, ModelCategory, Provider
from ..constants import ADDON_NAME_CONFIG
import time as _time

# Enum getter cache — avoids registry query + JSON parse every frame
_enum_cache_image = None    # (items_list, timestamp)
_enum_cache_text = None     # (items_list, timestamp)
_ENUM_CACHE_TTL = 5.0       # seconds

def invalidate_model_enum_cache():
    """Call this on provider switch, NeuroToken activate/deactivate, model enable/disable."""
    global _enum_cache_image, _enum_cache_text
    _enum_cache_image = None
    _enum_cache_text = None


# Also cache _get_disabled_models result (avoids JSON parse every call)
_disabled_cache = None       # (disabled_set, timestamp)
_DISABLED_CACHE_TTL = 10.0   # seconds


def _get_disabled_models(context):
    """Get set of disabled model IDs from preferences (cached 10s)."""
    global _disabled_cache
    import json

    now = _time.monotonic()
    if _disabled_cache and (now - _disabled_cache[1]) < _DISABLED_CACHE_TTL:
        return _disabled_cache[0]

    prefs = None
    for name in ["ai_nodes", __package__]:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break
    result = set()
    if prefs and hasattr(prefs, 'disabled_models'):
        try:
            result = set(json.loads(prefs.disabled_models))
        except Exception:
            pass
    _disabled_cache = (result, now)
    return result


def _filter_disabled(items, disabled_set):
    """Filter out disabled models from enum items list.
    Keeps separators (items starting with _) and non-disabled models.
    """
    filtered = [item for item in items
                if item[0].startswith('_') or item[0] not in disabled_set]
    return filtered if filtered else None  # Return None to signal fallback needed


def get_node_generation_models(self, context):
    """Dynamic getter for generation models in nodes — CACHED."""
    global _enum_cache_image

    fallback = [
        ("nano-banana", "Nano Banana", ""),
        ("nano-banana-pro", "Nano Banana Pro", ""),
    ]

    if not context:
        return fallback

    # Cache check — return immediately if fresh
    now = _time.monotonic()
    if _enum_cache_image and (now - _enum_cache_image[1]) < _ENUM_CACHE_TTL:
        return _enum_cache_image[0]

    try:
        from ..model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()
        if not registry:
            return fallback

        # --- NeuroToken mode: derive from UNIFIED_MODELS ---
        try:
            from ..token_utils import get_nt_enum_items
            nt_items = get_nt_enum_items("image")
            if nt_items:
                disabled = _get_disabled_models(context)
                filtered = _filter_disabled(nt_items, disabled)
                result = filtered if filtered else fallback
                _enum_cache_image = (result, now)
                return result
        except ImportError:
            pass

        # Get active provider from preferences
        prefs = None
        for name in ["ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if prefs and hasattr(prefs, 'active_provider'):
            active = prefs.active_provider
            provider_map = {
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
            }
            provider = provider_map.get(active, Provider.GOOGLE)

            items = registry.get_models_for_active_provider(
                category=ModelCategory.IMAGE_GENERATION,
                active_provider=provider
            )
            items = list(items) if items else []

            # Cross-provider includes
            if active == 'fal' and getattr(prefs, 'fal_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_separator", "-- Google Models --", ""))
                    items.extend(google_items)

            elif active == 'google' and getattr(prefs, 'google_include_fal_models', False):
                fal_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.FAL
                )
                if fal_items:
                    items.append(("_fal_separator", "-- Fal.AI Models --", ""))
                    items.extend(fal_items)

            elif active == 'replicate' and getattr(prefs, 'replicate_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.IMAGE_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_separator", "-- Google Models --", ""))
                    items.extend(google_items)

            if items and len(items) > 0:
                disabled = _get_disabled_models(context)
                items = _filter_disabled(items, disabled)
                result = items if items else fallback
                _enum_cache_image = (result, now)
                return result

        # Fallback
        items = registry.get_blender_enum_items(ModelCategory.IMAGE_GENERATION)
        if items and len(items) > 0:
            disabled = _get_disabled_models(context)
            items = _filter_disabled(items, disabled)
            result = items if items else fallback
            _enum_cache_image = (result, now)
            return result

        return fallback
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Node model enum error: {e}")
        return fallback


def get_node_text_models(self, context):
    """Dynamic getter for text models in nodes — CACHED."""
    global _enum_cache_text

    fallback = [
        ("text-gpt-oai", "GPT", ""),
        ("gemini-3-pro-google", "Gemini 3.0 Pro (Google)", ""),
    ]

    if not context:
        return fallback

    # Cache check
    now = _time.monotonic()
    if _enum_cache_text and (now - _enum_cache_text[1]) < _ENUM_CACHE_TTL:
        return _enum_cache_text[0]

    try:
        from ..model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()
        if not registry:
            return fallback

        # --- NeuroToken mode ---
        try:
            from ..token_utils import get_nt_enum_items
            nt_items = get_nt_enum_items("text")
            if nt_items:
                disabled = _get_disabled_models(context)
                filtered = _filter_disabled(nt_items, disabled)
                result = filtered if filtered else fallback
                _enum_cache_text = (result, now)
                return result
        except ImportError:
            pass

        # Get active provider
        prefs = None
        for name in ["ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if prefs and hasattr(prefs, 'active_provider'):
            active = prefs.active_provider

            # Special handling for Fal
            if active == 'fal':
                text_provider = None
                items = []

                if getattr(prefs, 'fal_text_from_replicate', False):
                    replicate_key = getattr(prefs, 'replicate_api_key', '')
                    if replicate_key:
                        text_provider = Provider.REPLICATE

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

                if items and len(items) > 0:
                    disabled = _get_disabled_models(context)
                    items = _filter_disabled(items, disabled)
                    result = items if items else fallback
                    _enum_cache_text = (result, now)
                    return result

                result = [("_no_llm", "No LLM Provider", "Enable Replicate in Settings.")]
                _enum_cache_text = (result, now)
                return result

            # Normal provider handling
            provider_map = {
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
            }
            provider = provider_map.get(active, Provider.GOOGLE)

            items = registry.get_models_for_active_provider(
                category=ModelCategory.TEXT_GENERATION,
                active_provider=provider
            )
            items = list(items) if items else []

            if active == 'replicate' and getattr(prefs, 'replicate_include_google_models', False):
                google_items = registry.get_models_for_active_provider(
                    category=ModelCategory.TEXT_GENERATION,
                    active_provider=Provider.GOOGLE
                )
                if google_items:
                    items.append(("_google_text_separator", "-- Google LLMs --", ""))
                    items.extend(google_items)

            if items and len(items) > 0:
                disabled = _get_disabled_models(context)
                items = _filter_disabled(items, disabled)
                result = items if items else fallback
                _enum_cache_text = (result, now)
                return result

        # Fallback
        items = registry.get_blender_enum_items(ModelCategory.TEXT_GENERATION)
        if items and len(items) > 0:
            disabled = _get_disabled_models(context)
            items = _filter_disabled(items, disabled)
            result = items if items else fallback
            _enum_cache_text = (result, now)
            return result

        return fallback
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Node text model enum error: {e}")
        return fallback