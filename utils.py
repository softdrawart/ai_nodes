# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Utilities Module
Helper functions, file management, preview handling, and common utilities.
"""

import os
import re
import math
import time
import tempfile
import threading
import atexit
from datetime import datetime

import bpy

# =============================================================================
# GLOBAL STATE
# =============================================================================

preview_collection = None
generation_lock = threading.Lock()
cancel_event = threading.Event()
temp_files_registry = set()
current_generation_id = 0

# Thought Signatures: Store conversation history for multi-turn generation
gemini_conversation_history = []


def log_verbose(message, prefix=LOG_PREFIX):
    """Log message only if verbose logging is enabled in addon preferences"""
    try:
        # Get addon name directly to avoid function ordering issues
        addon_name = __package__ or __name__.split('.')[0]
        if addon_name and addon_name in bpy.context.preferences.addons:
            prefs = bpy.context.preferences.addons[addon_name].preferences
            if hasattr(prefs, 'verbose_logging') and prefs.verbose_logging:
                print(f"[{prefix}] {message}")
    except Exception:
        pass  # Silently fail if can't check preference


def get_preview_collection():
    """Get the preview collection (use this instead of direct import)"""
    global preview_collection
    return preview_collection


def get_conversation_history():
    """Get conversation history (use this instead of direct import)"""
    global gemini_conversation_history
    return gemini_conversation_history


def get_conversation_turn_count():
    """Get the number of user turns in conversation (not total messages)"""
    global gemini_conversation_history
    # Count only user turns, not model responses
    return sum(1 for turn in gemini_conversation_history if turn.get("role") == "user")


def clear_conversation_history():
    """Clear the conversation history"""
    global gemini_conversation_history
    gemini_conversation_history = []


def set_conversation_history(history):
    """Set the conversation history"""
    global gemini_conversation_history
    gemini_conversation_history = history


# =============================================================================
# FILE PATH UTILITIES
# =============================================================================

def get_base_storage_path():
    """Get a safe base path for saving files"""
    if bpy.data.is_saved:
        base = bpy.path.abspath("//")
    else:
        base = os.path.join(tempfile.gettempdir(), "Blender_AI_Generations")
    return base


def get_generations_folder(subfolder=""):
    """Get the generations folder path, creating it if necessary"""
    base = get_base_storage_path()

    if bpy.data.is_saved:
        base = os.path.join(base, "generations")

    if subfolder:
        base = os.path.join(base, subfolder)

    try:
        os.makedirs(base, exist_ok=True)
    except PermissionError:
        print(f"[{LOG_PREFIX}] Permission denied at {base}, switching to Temp")
        base = os.path.join(tempfile.gettempdir(), "Blender_AI_Generations", subfolder)
        os.makedirs(base, exist_ok=True)

    return base


def unique_temp_path(prefix="temp_ref", ext="png"):
    """Generate a unique temporary file path"""
    base = tempfile.gettempdir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(base, f"{prefix}_{ts}.{ext}")


def register_temp_file(filepath):
    """Register a temporary file for later cleanup"""
    global temp_files_registry
    temp_files_registry.add(filepath)
    return filepath


def cleanup_temp_files():
    """Clean up all registered temporary files"""
    global temp_files_registry
    for filepath in list(temp_files_registry):
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"[{LOG_PREFIX}] Cleaned up temp file: {filepath}")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to cleanup {filepath}: {e}")
        temp_files_registry.discard(filepath)


def cleanup_orphaned_temps():
    """Clean up orphaned temp files from previous sessions. Runs once at startup."""
    blend_dir = bpy.path.abspath("//")
    if not blend_dir or blend_dir == "//" or not os.path.isdir(blend_dir):
        return None

    patterns = ["temp_ref_", "render_ref_", "clipboard_ref_", "normal_capture_", "nobg_", "gpt_image_"]
    cleaned = 0

    try:
        for filename in os.listdir(blend_dir):
            if any(filename.startswith(p) for p in patterns) and filename.endswith(".png"):
                filepath = os.path.join(blend_dir, filename)
                try:
                    if time.time() - os.path.getmtime(filepath) > 3600:
                        os.remove(filepath)
                        cleaned += 1
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Failed to cleanup orphan {filename}: {e}")

        if cleaned > 0:
            print(f"[{LOG_PREFIX}] Cleaned up {cleaned} orphaned temp files")
    except Exception as e:
        print(f"[{LOG_PREFIX}] Orphan cleanup error: {e}")

    return None


# =============================================================================
# FILENAME UTILITIES
# =============================================================================

def sanitize_filename(prompt):
    """Sanitize a string for use as a filename"""
    clean = re.sub(r'[^a-zA-Z0-9_-]+', '_', prompt.strip())[:60]
    return clean or "Neuro_Result"


def extract_object_name_from_prompt(prompt):
    """Extract text from [brackets] in prompt for better naming."""
    match = re.search(r'\[([^\]]+)\]', prompt)
    if match:
        extracted = match.group(1)
        clean = re.sub(r'[^a-zA-Z0-9_-]+', '_', extracted.strip())[:40]
        return clean if clean else "object"
    return "object"


def get_unique_filename(base_dir, base_name, extension="png"):
    """Generate unique filename with incrementing numbers."""
    counter = 1
    while True:
        filename = f"{base_name}_{counter:03d}.{extension}"
        full_path = os.path.join(base_dir, filename)
        if not os.path.exists(full_path):
            return filename
        counter += 1
        if counter > 999:
            timestamp = datetime.now().strftime("%H%M%S")
            return f"{base_name}_{timestamp}.{extension}"


# =============================================================================
# MIME TYPE UTILITIES
# =============================================================================

def guess_mime(path):
    """Guess MIME type from file extension"""
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp'
    }
    return mime_map.get(ext, 'image/png')


# =============================================================================
# SAFE IMAGE LOADING (prevents .001 duplicates)
# =============================================================================

def safe_load_image(filepath, reload_existing=True):
    """Load an image into Blender without creating .001 duplicates.

    This function checks if an image with the same filepath is already loaded.
    If so, it optionally reloads the existing image instead of creating a duplicate.

    Args:
        filepath: Path to the image file
        reload_existing: If True, reload existing image data. If False, just return existing.

    Returns:
        bpy.types.Image object, or None if loading fails
    """
    if not filepath or not os.path.exists(filepath):
        return None

    # Normalize the filepath for comparison
    abs_path = os.path.normpath(os.path.abspath(filepath))

    # Check if image with this filepath already exists
    for img in bpy.data.images:
        if img.filepath:
            existing_path = os.path.normpath(os.path.abspath(bpy.path.abspath(img.filepath)))
            if existing_path == abs_path:
                # Image already loaded
                if reload_existing:
                    try:
                        img.reload()
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Warning: Could not reload image {filepath}: {e}")
                return img

    # Image not found, load it fresh
    try:
        img = bpy.data.images.load(filepath)
        return img
    except Exception as e:
        print(f"[{LOG_PREFIX}] Failed to load image {filepath}: {e}")
        return None


def safe_show_in_editor(filepath, reload_existing=True):
    """Load image and show it in the Image Editor.

    This is a convenience function that combines safe_load_image
    with displaying the result in the Image Editor.

    Args:
        filepath: Path to the image file
        reload_existing: If True, reload existing image data

    Returns:
        bpy.types.Image object, or None if loading fails
    """
    img = safe_load_image(filepath, reload_existing)
    if img:
        # Show in Image Editor if one exists
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                for space in area.spaces:
                    if space.type == 'IMAGE_EDITOR':
                        space.image = img
                        break
                break
    return img


# =============================================================================
# MODEL & STATUS UTILITIES
# =============================================================================

def get_model_name_display(model_id):
    """Get display name for model in status messages.

    Automatically pulls from model_registry if available,
    falls back to pattern matching for legacy/unknown models.
    """
    if not model_id:
        return "Unknown"

    # Try to get from model registry first (automatic!)
    try:
        from .model_registry import get_model
        config = get_model(model_id)
        if config and config.name:
            return config.name
    except Exception:
        pass

    # Fallback: pattern matching for legacy models or if registry lookup fails
    mid = str(model_id).lower()

    # GPT models
    if "gpt-image-1.5" in mid:
        return "GPT Image 1.5"
    if "gpt-image-1" in mid:
        return "GPT Image 1.0"
    if "gpt-5.2" in mid:
        return "GPT-5.2"
    if "gpt-5.1" in mid:
        return "GPT-5.1"
    if "gpt-5-nano" in mid or "gpt-nano" in mid:
        return "GPT-5 Nano"

    # Grok models
    if "grok-4" in mid or "grok4" in mid:
        return "Grok 4"
    if "grok-imagine" in mid:
        return "Grok Imagine"
    if "grok" in mid:
        return "Grok"

    # Imagen
    if "imagen-4" in mid:
        return "Imagen 4"
    if "imagen" in mid:
        return "Imagen"

    # Nano Banana models
    if "nano-banana-pro" in mid:
        return "Nano Banana Pro"
    if "nano-banana" in mid:
        return "Nano Banana"

    # Gemini text models
    if "gemini-3-pro" in mid:
        return "Gemini 3 Pro"
    if "gemini-3-flash" in mid:
        return "Gemini 3 Flash"
    if "gemini-2.5" in mid:
        return "Gemini 2.5"
    if "gemini" in mid:
        return "Gemini"

    # Claude
    if "claude" in mid:
        return "Claude"

    # If nothing matched, try to make a readable name from the ID
    # e.g., "some-model-aiml" -> "Some Model"
    clean_id = model_id.replace("-aiml", "").replace("-repl", "").replace("-fal", "").replace("-google", "")
    clean_id = clean_id.replace("-", " ").replace("_", " ").title()
    if clean_id and clean_id != model_id:
        return clean_id

    return "Unknown"


def get_status_icon(status):
    """Get appropriate icon for status message"""
    status_lower = status.lower()
    if "success" in status_lower or "generated" in status_lower or "applied" in status_lower:
        return 'CHECKMARK'
    elif "error" in status_lower or "failed" in status_lower or "cancel" in status_lower:
        return 'ERROR'
    elif "generating" in status_lower or "preparing" in status_lower or "sending" in status_lower or "capturing" in status_lower or "removing" in status_lower:
        return 'TIME'
    return 'INFO'


def update_status(context, message, also_scene=True):
    """Update status (Scene property only, avoiding status bar conflict)."""
    # NOTE: We removed context.workspace.status_text_set() because it
    # conflicts with status_manager's custom draw function.

    # Update scene property for panel display
    if also_scene:
        try:
            if context and context.scene:
                context.scene.neuro_status = message
        except Exception:
            pass


def clear_status_bar(context):
    """Clear status (Deprioritized to avoid conflicts)."""
    # Do nothing - let status_manager handle the UI
    pass


def license_key_update(self, context):
    """Reset status when license key is modified"""
    self.license_status = 'NONE'
    self.license_message = ""


# =============================================================================
# ASPECT RATIO & RESOLUTION UTILITIES
# =============================================================================

def get_aspect_ratio_for_api(aspect_ratio):
    """Convert aspect ratio to API format"""
    mapping = {
        "1:1": "1:1",
        "3:4": "3:4",
        "4:3": "4:3",
        "16:9": "16:9",
        "9:16": "9:16",
        "21:9": "21:9",
    }
    return mapping.get(aspect_ratio, "auto")


def get_fal_image_size(ratio_str):
    """Map UI aspect ratios to the specific resolutions enforced by Fal gpt-image-1"""
    mapping = {
        "1:1": "1024x1024",
        "3:4": "1024x1536",
        "4:3": "1536x1024",
        "16:9": "1536x1024",
        "9:16": "1024x1536",
        "21:9": "1536x1024",
    }
    return mapping.get(ratio_str, "1024x1024")


def get_texture_api_size(target_res, model_name):
    """Get the closest available API resolution for texture generation."""
    target = int(target_res)

    if model_name == "gpt-image-1":
        if target <= 1024:
            return "1024x1024", 1024
        elif target <= 1536:
            return "1536x1536", 1536
        else:
            return "2048x2048", 2048
    else:
        if target <= 1024:
            return "1:1", 1024
        else:
            return "1:1", 1024


# =============================================================================
# PREVIEW MANAGEMENT
# =============================================================================

def init_preview_collection():
    """Initialize the preview collection"""
    global preview_collection
    try:
        import bpy.utils.previews
        if preview_collection is None:
            preview_collection = bpy.utils.previews.new()
    except (ImportError, AttributeError, RuntimeError):
        pass
    return preview_collection


def cleanup_preview_collection():
    """Clean up the preview collection"""
    global preview_collection
    try:
        import bpy.utils.previews
        if preview_collection is not None:
            try:
                bpy.utils.previews.remove(preview_collection)
            except Exception as e:
                print(f"[{LOG_PREFIX}] Preview cleanup warning: {e}")
            finally:
                preview_collection = None
    except ImportError:
        preview_collection = None


def refresh_previews_and_collections(scene):
    """Main-thread: update preview_collection from both reference & generated lists."""
    global preview_collection

    if preview_collection is None or scene is None:
        return

    try:
        active_paths = set()
        for r in scene.neuro_reference_images:
            if r.path and os.path.exists(r.path):
                active_paths.add(os.path.normpath(os.path.abspath(r.path)))
        for g in scene.neuro_generated_images:
            if g.path and os.path.exists(g.path):
                active_paths.add(os.path.normpath(os.path.abspath(g.path)))
        for t in scene.neuro_generated_textures:
            if t.path and os.path.exists(t.path):
                active_paths.add(os.path.normpath(os.path.abspath(t.path)))

        # Remove stale previews
        try:
            existing_keys = list(preview_collection.keys())
            for key in existing_keys:
                if key not in active_paths:
                    try:
                        preview_collection.pop(key, None)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Previews] cleanup error: {e}")

        # Load new previews
        for path in active_paths:
            if not os.path.exists(path):
                continue
            key = os.path.normpath(path)

            try:
                if key in preview_collection:
                    preview_collection.pop(key, None)
                preview_collection.load(key, path, 'IMAGE')
            except Exception as e:
                print(f"[Previews] failed to load {path}: {e}")

    except Exception as e:
        print(f"[Previews] refresh error: {e}")


def trigger_preview_refresh():
    """Trigger preview refresh on startup/load"""
    if bpy.context and bpy.context.scene:
        refresh_previews_and_collections(bpy.context.scene)
    return None


# =============================================================================
# PROGRESS TIMER
# =============================================================================

class NeuroProgressTimer:
    """Simulates progress for AINodes since it has no progress API"""

    def __init__(self):
        self.start_time = None
        self.is_running = False
        self.current_progress = 0.0
        self.completed = False

    def start(self):
        self.start_time = time.time()
        self.is_running = True
        self.current_progress = 0.0
        self.completed = False
        bpy.context.scene.neuro_progress = 0.0
        bpy.app.timers.register(self._update_progress, first_interval=0.1)

    def stop(self):
        self.is_running = False
        self.completed = True
        bpy.context.scene.neuro_progress = 100.0

    def _update_progress(self):
        if not self.is_running or self.completed:
            return None

        elapsed = time.time() - self.start_time
        target_progress = min(0.95, 1.0 - math.exp(-elapsed / 8.0))

        self.current_progress += (target_progress - self.current_progress) * 0.3
        bpy.context.scene.neuro_progress = round(self.current_progress * 100.0)

        return 0.15


# Global progress timer instance
progress_timer = NeuroProgressTimer()


# =============================================================================
# API KEY UTILITIES
# =============================================================================

def get_api_keys(context):
    """Robustly get API keys from addon preferences.

    Returns:
        Tuple of (google_key, fal_key, replicate_key, aiml_key)
    """
    google_key = ""
    fal_key = ""
    replicate_key = ""
    aiml_key = ""

    addon_name = get_addon_name()
    potential_names = [addon_name, "blender_ai_nodes", "ai_nodes"]

    prefs = None
    for name in potential_names:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break

    if prefs:
        google_key = getattr(prefs, 'gemini_api_key', "")
        fal_key = getattr(prefs, 'fal_api_key', "")
        replicate_key = getattr(prefs, 'replicate_api_key', "")
        aiml_key = getattr(prefs, 'aiml_api_key', "")
    else:
        print(f"[{LOG_PREFIX}] Error: Could not find preferences. checked: {potential_names}")

    return google_key, fal_key, replicate_key, aiml_key


def get_all_api_keys(context):
    """Get all API keys from addon preferences.

    Returns:
        Dict with "google", "fal", "replicate", "tripo", "openai", "aiml" keys
    """
    keys = {"google": "", "fal": "", "replicate": "", "tripo": "", "openai": "", "aiml": ""}

    addon_name = get_addon_name()
    potential_names = [addon_name, "blender_ai_nodes", "ai_nodes"]

    prefs = None
    for name in potential_names:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break

    if prefs:
        keys["google"] = getattr(prefs, "gemini_api_key", "")
        keys["fal"] = getattr(prefs, "fal_api_key", "")
        keys["replicate"] = getattr(prefs, "replicate_api_key", "")
        keys["tripo"] = getattr(prefs, "tripo_api_key", "")
        keys["openai"] = getattr(prefs, "openai_api_key", "")
        keys["aiml"] = getattr(prefs, "aiml_api_key", "")

    return keys


def get_enabled_providers(context):
    """Get set of enabled provider names.

    Returns:
        Set of enabled provider names (e.g., {"google", "replicate"})
    """
    enabled = set()

    addon_name = get_addon_name()
    potential_names = [addon_name, "blender_ai_nodes", "ai_nodes"]

    prefs = None
    for name in potential_names:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break

    if prefs:
        if getattr(prefs, "provider_google_enabled", True):
            enabled.add("google")
        if getattr(prefs, "provider_replicate_enabled", True):
            enabled.add("replicate")
        if getattr(prefs, "provider_fal_enabled", False):
            enabled.add("fal")
        if getattr(prefs, "provider_aiml_enabled", False):
            enabled.add("aiml")
    else:
        # Defaults if prefs not found
        enabled = {"google", "aiml"}

    return enabled


def get_fal_text_provider(context):
    """Get the text provider to use when Fal is the active provider.

    Fal.ai has no LLM capabilities, so we need to fallback to another provider
    for text operations (prompt upgrade, text generation, etc.)

    Priority: AIML (conflicts with Replicate), then Replicate (conflicts with AIML).
    Google models can be added via fal_include_google_models but don't replace primary text source.

    Returns:
        str: Provider name ('aiml', 'replicate', or None if no text source available)
    """
    addon_name = get_addon_name()
    potential_names = [addon_name, "blender_ai_nodes", "ai_nodes"]

    prefs = None
    for name in potential_names:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break

    if not prefs:
        return None

    # Check if we're even using Fal
    if prefs.active_provider != 'fal':
        return prefs.active_provider  # Return the active provider if not Fal

    scn = context.scene

    # Priority 1: AIML if enabled (conflicts with Replicate)
    if getattr(prefs, 'fal_text_from_aiml', False):
        aiml_key = getattr(prefs, 'aiml_api_key', '')
        aiml_status = getattr(scn, 'neuro_aiml_status', False)
        if aiml_key and aiml_status:
            return 'aiml'
        # If AIML selected but not connected, still try if key exists
        if aiml_key:
            log_verbose("AIML selected for Fal text but connection status unknown, trying anyway")
            return 'aiml'

    # Priority 2: Replicate if enabled (conflicts with AIML)
    if getattr(prefs, 'fal_text_from_replicate', False):
        replicate_key = getattr(prefs, 'replicate_api_key', '')
        if replicate_key:
            return 'replicate'

    # Legacy fallback: Check fal_text_from_google for backward compatibility
    if getattr(prefs, 'fal_text_from_google', False):
        google_key = getattr(prefs, 'gemini_api_key', '')
        google_status = getattr(scn, 'neuro_google_status', False)
        if google_key and google_status:
            return 'google'
        if google_key:
            log_verbose("Google selected for Fal text but connection status unknown, trying anyway")
            return 'google'

    # Priority 4: fal_include_google_models also enables Google as text source
    # (User can see Google models, so they should also work for text operations)
    if getattr(prefs, 'fal_include_google_models', False):
        google_key = getattr(prefs, 'gemini_api_key', '')
        google_status = getattr(scn, 'neuro_google_status', False)
        if google_key and google_status:
            return 'google'
        if google_key:
            log_verbose("Google models included for Fal, using for text operations")
            return 'google'

    # No text source available
    return None


def get_text_api_key_for_fal(context):
    """Get the API key for text operations when Fal is active.

    Returns:
        Tuple of (provider_name, api_key) or (None, None) if not available
    """
    provider = get_fal_text_provider(context)
    if not provider:
        return None, None

    addon_name = get_addon_name()
    potential_names = [addon_name, "blender_ai_nodes", "ai_nodes"]

    prefs = None
    for name in potential_names:
        if name and name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            break

    if not prefs:
        return None, None

    if provider == 'aiml':
        return 'aiml', getattr(prefs, 'aiml_api_key', '')
    elif provider == 'google':
        return 'google', getattr(prefs, 'gemini_api_key', '')
    elif provider == 'replicate':
        return 'replicate', getattr(prefs, 'replicate_api_key', '')

    return None, None


# =============================================================================
# FILE SAVE CHECK
# =============================================================================

def check_is_saved(operator_self, context):
    """Returns True if saved, else shows error popup"""
    if not context.blend_data.is_saved:
        def draw_popup(self, context):
            self.layout.label(text="File Not Saved!", icon='ERROR')
            self.layout.label(text="You must save your .blend file before generating.")
            self.layout.label(text="This ensures your images are saved safely.")

        context.window_manager.popup_menu(draw_popup, title="Save Required", icon='ERROR')
        operator_self.report({'ERROR'}, "Save file required")
        return False
    return True


# =============================================================================
# ASSET LOADING
# =============================================================================

def load_bundled_node_groups():
    """Load node groups from a bundled .blend file"""
    from .constants import get_assets_path

    blend_path = os.path.join(get_assets_path(), "Nodes.blend")

    if not os.path.exists(blend_path):
        print(f"[{LOG_PREFIX}] Asset file not found: {blend_path}")
        return None

    groups_to_import = ["Texture_Quick_Edit_En", "Texture_Quick_Edit_Ru"]

    try:
        with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
            data_to.node_groups = [
                name for name in data_from.node_groups
                if name in groups_to_import and name not in bpy.data.node_groups
            ]

        if data_to.node_groups:
            print(f"[{LOG_PREFIX}] Loaded node groups: {data_to.node_groups}")
    except Exception as e:
        print(f"[{LOG_PREFIX}] Failed to load node groups: {e}")

    return None


# =============================================================================
# ADDON NAME HELPER
# =============================================================================

def get_addon_name():
    """Get the addon package name for preferences lookup"""
    # __package__ gives us 'blender_neuro_nodes' when imported as a package
    return __package__ or __name__.split('.')[0]


# =============================================================================
# UI STATE RESET
# =============================================================================

def reset_ui_states():
    """Reset UI states to prevent stuck 'Generating...' status on startup"""
    context = bpy.context
    if not context or not hasattr(bpy.data, "scenes"):
        return 0.1

    for scn in bpy.data.scenes:
        if hasattr(scn, "neuro_is_generating"):
            scn.neuro_is_generating = False

        if hasattr(scn, "neuro_status"):
            if scn.neuro_status in ["Canceling...", "Generating...", "Preparing...", "Removing background..."]:
                scn.neuro_status = ""

    # CHANGED: Force-reset restart flags
    try:
        addon_name = get_addon_name()
        if addon_name and addon_name in context.preferences.addons:
            prefs = context.preferences.addons[addon_name]
            if prefs and hasattr(prefs, 'preferences'):
                if hasattr(prefs.preferences, 'needs_restart'):
                    prefs.preferences.needs_restart = False
                if hasattr(prefs.preferences, 'rembg_needs_restart'):
                    prefs.preferences.rembg_needs_restart = False
    except Exception as e:
        print(f"[{LOG_PREFIX}] Could not reset needs_restart: {e}")

    print(f"[{LOG_PREFIX}] UI States Reset")

    # Trigger auto-validation of API keys after a short delay
    bpy.app.timers.register(_trigger_auto_validation, first_interval=2.0)

    return None


def _trigger_auto_validation():
    """Auto-validate API keys on startup if any are configured"""
    try:
        context = bpy.context
        addon_name = get_addon_name()
        if not addon_name or addon_name not in context.preferences.addons:
            return None

        prefs = context.preferences.addons[addon_name].preferences

        # Check if any keys are configured
        has_keys = any([
            getattr(prefs, 'aiml_api_key', ''),
            getattr(prefs, 'google_api_key', ''),
            getattr(prefs, 'fal_api_key', ''),
            getattr(prefs, 'replicate_api_key', ''),
        ])

        if has_keys:
            # Trigger the test all connections operator
            try:
                bpy.ops.neuro.test_all_connections()
                print(f"[{LOG_PREFIX}] Auto-validated API keys on startup")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Auto-validation failed: {e}")
    except Exception as e:
        print(f"[{LOG_PREFIX}] Auto-validation error: {e}")

    return None  # Don't repeat


# =============================================================================
# CLEANUP REGISTRATION
# =============================================================================

def register_cleanup():
    """Register cleanup functions"""
    atexit.register(cleanup_temp_files)


def unregister_cleanup():
    """Unregister cleanup functions"""
    cleanup_temp_files()