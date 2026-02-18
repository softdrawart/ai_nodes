# -*- coding: utf-8 -*-
import bpy
from ..model_registry import get_registry, ModelCategory, Provider


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
        except:
            pass
    return set()


def _filter_disabled(items, disabled_set):
    """Filter out disabled models from enum items list.
    Keeps separators (items starting with _) and non-disabled models.
    """
    filtered = [item for item in items
                if item[0].startswith('_') or item[0] not in disabled_set]
    return filtered if filtered else None  # Return None to signal fallback needed


def get_node_generation_models(self, context):
    """Dynamic getter for generation models in nodes - uses active provider.

    Supports adding models from secondary providers based on preferences:
    - Fal + fal_include_google_models → add Google models
    - AIML + aiml_include_google_models → add Google models
    - Google + google_include_fal_models → add Fal models
    - Replicate + replicate_include_google_models → add Google models
    """
    # Safety fallback - always return valid items
    fallback = [
        ("nano-banana", "Nano Banana", ""),
        ("nano-banana-pro", "Nano Banana Pro", ""),
    ]

    if not context:
        return fallback

    try:
        from ..model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()
        if not registry:
            return fallback

        # Get active provider from preferences
        prefs = None
        for name in ["blender_ai_nodes", "ai_nodes", __package__]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if prefs and hasattr(prefs, 'active_provider'):
            active = prefs.active_provider
            provider_map = {
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
                'aiml': Provider.AIML,
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

            if items and len(items) > 0:
                # Filter disabled models
                disabled = _get_disabled_models(context)
                items = _filter_disabled(items, disabled)
                return items if items else fallback

        # Fallback
        items = registry.get_blender_enum_items(ModelCategory.IMAGE_GENERATION)
        if items and len(items) > 0:
            disabled = _get_disabled_models(context)
            items = _filter_disabled(items, disabled)
            return items if items else fallback
        return fallback
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Node model enum error: {e}")
        return fallback


def get_node_text_models(self, context):
    """Dynamic getter for text models in nodes - uses active provider.

    Special handling for Fal provider: Since Fal has no LLM capabilities,
    uses the configured text source (AIML or Replicate, mutually exclusive).
    Google models can be added alongside any text source.
    """
    # Safety fallback
    fallback = [
        ("gpt-5.1", "GPT-5.1", ""),
        ("gemini-3-pro-google", "Gemini 3.0 Pro (Google)", ""),
    ]

    if not context:
        return fallback

    try:
        from ..model_registry import get_registry, ModelCategory, Provider

        registry = get_registry()
        if not registry:
            return fallback

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

                if items and len(items) > 0:
                    return items

                # No text source configured - return warning item
                return [
                    ("none", "No LLM Source (Configure in Settings)", "Fal has no LLM. Enable AIML or Replicate.")]

            # Normal provider handling
            provider_map = {
                'replicate': Provider.REPLICATE,
                'google': Provider.GOOGLE,
                'fal': Provider.FAL,
                'aiml': Provider.AIML,
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

            if items and len(items) > 0:
                # Filter disabled models
                disabled = _get_disabled_models(context)
                items = _filter_disabled(items, disabled)
                return items if items else fallback

        # Fallback
        items = registry.get_blender_enum_items(ModelCategory.TEXT_GENERATION)
        if items and len(items) > 0:
            disabled = _get_disabled_models(context)
            items = _filter_disabled(items, disabled)
            return items if items else fallback
        return fallback
    except Exception as e:
        print(f"[{ADDON_NAME_CONFIG}] Node text model enum error: {e}")
        return fallback