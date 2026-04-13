# -*- coding: utf-8 -*-
"""
Neurotoken Utilities — All neurotoken-related logic in one place.

Derives model lists and routing from existing UNIFIED_MODELS + ModelConfig.
No manual model maps — everything auto-computed from models.py and model_registry.py.
"""

import re
from .constants import LOG_PREFIX

# =============================================================================
# NEUROTOKEN STATE ACCESS (delegates to config_proxy)
# =============================================================================

def is_nt_active():
    """Check if neurotoken mode is active."""
    try:
        from .config.config_proxy import is_neurotoken_mode
        return is_neurotoken_mode()
    except ImportError:
        pass
    try:
        from .config import is_neurotoken_mode
        return is_neurotoken_mode()
    except ImportError:
        return False


def get_nt_key():
    """Get the active neurotoken key."""
    try:
        from .config.config_proxy import get_neurotoken
        return get_neurotoken()
    except ImportError:
        pass
    try:
        from .config import get_neurotoken
        return get_neurotoken()
    except ImportError:
        return ""


# =============================================================================
# ROUTING LOGIC — Worker can route: google, openai, fal, replicate
# =============================================================================

# Priority chains for picking which provider variant the worker should use.
# Image: prefer Google (vertex), then OpenAI (direct), then Fal, then Replicate.
# Text:  prefer Google (vertex), then OpenAI (direct), then Replicate.
_NT_IMAGE_CHAIN = ("google", "openai", "fal", "replicate")
_NT_TEXT_CHAIN = ("google", "openai", "replicate")


def _get_category_for_canonical(canonical, variants):
    """Determine if a canonical model is image or text by checking any variant's ModelConfig."""
    from .model_registry import get_model, ModelCategory

    for provider_id in variants.values():
        config = get_model(provider_id)
        if config:
            if config.category == ModelCategory.TEXT_GENERATION:
                return "text"
            elif config.category in (ModelCategory.IMAGE_GENERATION, ModelCategory.IMAGE_EDITING):
                return "image"
            elif config.category == ModelCategory.UTILITY:
                return "utility"
    return "image"  # fallback


def resolve_nt_variant(canonical, variants):
    """Pick the best worker-routable variant for a canonical model.

    Args:
        canonical: e.g. "nano-banana", "text-gemini-flash"
        variants: dict from UNIFIED_MODELS, e.g. {"google": "...", "fal": "...", ...}

    Returns:
        Provider-specific model_id string, or None if no routable variant exists.
    """
    cat = _get_category_for_canonical(canonical, variants)

    if cat == "text":
        chain = _NT_TEXT_CHAIN
    else:
        chain = _NT_IMAGE_CHAIN

    for provider in chain:
        if provider in variants:
            return variants[provider]

    # Last resort: first available variant
    return next(iter(variants.values()), None)


# =============================================================================
# DISPLAY NAME DERIVATION
# =============================================================================

# Provider suffixes to strip from display names
_PROVIDER_SUFFIXES = re.compile(
    r'\s*\((?:Google|Fal|Repl|Replicate|Fal\.AI)\)\s*$',
    re.IGNORECASE
)


def _clean_display_name(name):
    """Strip provider suffix from model name.
    'Nano Banana (Google)' → 'Nano Banana'
    'Claude Sonnet 4.5 (Repl)' → 'Claude Sonnet 4.5'
    """
    return _PROVIDER_SUFFIXES.sub('', name).strip()


# =============================================================================
# ENUM ITEMS FOR BLENDER DROPDOWNS
# =============================================================================

def get_nt_enum_items(category_filter):
    """Build Blender EnumProperty items for neurotoken mode.

    Derives everything from UNIFIED_MODELS + ModelConfig registry.
    No manual maps needed.

    Args:
        category_filter: "image" or "text"

    Returns:
        list of (id, name, description) tuples, or None if not in NT mode / no models
    """
    if not is_nt_active():
        return None

    from .model_registry import UNIFIED_MODELS, get_model

    items = []

    for canonical, variants in UNIFIED_MODELS.items():
        cat = _get_category_for_canonical(canonical, variants)
        if cat != category_filter:
            continue

        # Pick best worker-routable variant
        nt_id = resolve_nt_variant(canonical, variants)
        if not nt_id:
            continue

        # Get display info from ModelConfig
        config = get_model(nt_id)
        if config:
            name = _clean_display_name(config.name)
            desc = config.description or ""
            priority = config.priority
        else:
            name = canonical.replace("-", " ").title()
            desc = ""
            priority = 999

        items.append((nt_id, name, desc, priority))

    # Sort by priority (same ordering as normal provider lists)
    items.sort(key=lambda x: (x[3], x[1]))

    # Return as standard Blender enum tuples (drop priority)
    return [(i[0], i[1], i[2]) for i in items] if items else None


# =============================================================================
# KEY BYPASS — Makes all gatekeepers pass in neurotoken mode
# =============================================================================

_NT_PLACEHOLDER = "neurotoken"


def nt_bypass_api_keys():
    """Return placeholder API keys dict for neurotoken mode.
    All gatekeepers see non-empty keys and pass through.
    api.py intercepts before any key is actually used.

    Returns:
        dict with all provider keys set to "neurotoken", or None if not in NT mode
    """
    if not is_nt_active():
        return None
    return {
        "google": _NT_PLACEHOLDER,
        "fal": _NT_PLACEHOLDER,
        "replicate": _NT_PLACEHOLDER,
        "tripo": _NT_PLACEHOLDER,
        "openai": _NT_PLACEHOLDER,
    }


def nt_bypass_api_keys_tuple():
    """Return placeholder key tuple (google, fal, replicate) for neurotoken mode.

    Returns:
        Tuple of 3 placeholder strings, or None if not in NT mode
    """
    if not is_nt_active():
        return None
    return (_NT_PLACEHOLDER, _NT_PLACEHOLDER, _NT_PLACEHOLDER)


# =============================================================================
# STATE RESTORE (on scene load / Blender restart)
# =============================================================================

def restore_neurotoken_state():
    """Restore neurotoken state from saved preferences after scene load/restart.

    Call from load handler or startup timer. Runs synchronously (call from background thread).

    Returns:
        True if neurotoken was restored, False otherwise
    """
    import bpy

    # If already active (scene reload), just refresh balance
    if is_nt_active():
        try:
            from .config.config_proxy import refresh_neurotoken_balance, get_neurotoken_balance
        except ImportError:
            from .config import refresh_neurotoken_balance, get_neurotoken_balance
        refresh_neurotoken_balance()
        bal = get_neurotoken_balance()
        bal_str = f"\U0001F9E0{bal:.2f}" if bal else "0.00"

        def _update():
            try:
                bpy.context.scene.neurotoken_balance = bal_str
            except Exception:
                pass
            return None

        bpy.app.timers.register(_update, first_interval=0.1)
        return True

    # Not active — try to restore from saved key in prefs
    prefs = _get_prefs()
    if not prefs:
        return False

    key = getattr(prefs, 'neurotoken_key', '').strip()
    if not key or len(key) < 8:
        return False

    try:
        from .config.config_proxy import activate_neurotoken
    except ImportError:
        from .config import activate_neurotoken

    ok, user_or_err, balance = activate_neurotoken(key)
    if not ok:
        return False

    bal_str = f"\U0001F9E0{balance:.2f}" if balance else "0.00"

    def _update_prefs():
        try:
            prefs.neurotoken_status = 'ACTIVE'
            prefs.neurotoken_user_id = user_or_err
            prefs.neurotoken_message = f"Active — {bal_str}"
            bpy.context.scene.neurotoken_balance = bal_str
        except Exception:
            pass
        return None

    bpy.app.timers.register(_update_prefs, first_interval=0.1)
    print(f"[{LOG_PREFIX}] Token auto-restored: {user_or_err}")
    return True


def _get_prefs():
    """Get addon preferences."""
    import bpy
    for name in ["ai_nodes"]:
        if name in bpy.context.preferences.addons:
            return bpy.context.preferences.addons[name].preferences
    # Try by package
    try:
        for addon_name in bpy.context.preferences.addons:
            addon_mod = bpy.context.preferences.addons[addon_name]
            if hasattr(addon_mod, 'preferences') and hasattr(addon_mod.preferences, 'neurotoken_key'):
                return addon_mod.preferences
    except Exception:
        pass
    return None