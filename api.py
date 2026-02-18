# -*- coding: utf-8 -*-
"""
Blender AI Nodes - API Module
API handlers for Providers models.

Supports both legacy mode (using constants.py) and new mode (using model_registry.py).
"""

import os
import io
import sys
import base64
import urllib.request
import traceback
import bpy
from typing import List, Optional, Any, Dict

from .utils import (
    guess_mime, register_temp_file, unique_temp_path,
    temp_files_registry, log_verbose
)

# Global cache for local model session to improve speed
# Keeps model in RAM and don't reload it every time
_rembg_session = None

# =============================================================================
# MODULE-LEVEL IMPORTS (set during initialization)
# =============================================================================

# These will be set by the main module after checking dependencies
Image = None
Client = None
types = None
fal_client = None
replicate_client = None


def init_api_modules(image_module, client_class, types_module, fal_module, replicate_module=None):
    """Initialize API modules with actual imports"""
    global Image, Client, types, fal_client, replicate_client
    Image = image_module
    Client = client_class
    types = types_module
    fal_client = fal_module
    replicate_client = replicate_module


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _prepare_images_as_data_urls(image_paths: List[str]) -> List[str]:
    """Convert image file paths to base64 data URLs"""
    if not image_paths or not Image:
        return []

    image_urls = []
    for path in image_paths:
        if not os.path.exists(path):
            print(f"[API] Warning: Image not found: {path}")
            continue
        try:
            img = Image.open(path)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode()
            image_urls.append(f"data:image/png;base64,{img_b64}")
        except Exception as e:
            print(f"[API] Error loading {path}: {e}")

    return image_urls


def _download_image_to_pil(url: str, prefix: str = "download") -> Optional[Any]:
    """Download image from URL and return as PIL Image"""
    temp_path = register_temp_file(unique_temp_path(prefix=prefix))
    try:
        urllib.request.urlretrieve(url, temp_path)
        pil_img = Image.open(temp_path)
        pil_img.load()
        return pil_img
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                temp_files_registry.discard(temp_path)
            except Exception:
                pass


def _extract_images_from_fal_result(result: dict, prefix: str = "fal") -> List[Any]:
    """Extract PIL images from Fal.AI response"""
    images = []

    if not result:
        return images

    # Handle different response formats
    images_data = None
    if "images" in result:
        images_data = result["images"]
    elif "image" in result:
        images_data = [result["image"]]
    elif "output" in result:
        output = result["output"]
        images_data = output if isinstance(output, list) else [output]

    if not images_data:
        print(f"[API] Unexpected response format: {list(result.keys()) if result else 'None'}")
        return images

    for img_data in images_data:
        img_url = None
        if isinstance(img_data, dict) and "url" in img_data:
            img_url = img_data["url"]
        elif isinstance(img_data, str):
            img_url = img_data

        if img_url:
            pil_img = _download_image_to_pil(img_url, prefix=prefix)
            if pil_img:
                images.append(pil_img)

    return images


def get_fal_image_size(aspect_ratio: str) -> str:
    """Map UI aspect ratios to Fal.AI size strings"""
    mapping = {
        "1:1": "1024x1024",
        "3:4": "1024x1536",
        "4:3": "1536x1024",
        "16:9": "1536x1024",
        "9:16": "1024x1536",
        "21:9": "1536x1024",
    }
    return mapping.get(aspect_ratio, "1024x1024")


# =============================================================================
# FAL.AI ENDPOINT MAPPING
# =============================================================================

# GPT Image 1.0 uses different endpoint structure than 1.5
# GPT Image 1.0: fal-ai/gpt-image-1/text-to-image, fal-ai/gpt-image-1/edit-image
# GPT Image 1.5: fal-ai/gpt-image-1.5, fal-ai/gpt-image-1.5/edit
# Gemini via Fal: fal-ai/nano-banana, fal-ai/nano-banana/edit

_FAL_MODEL_ENDPOINTS = {
    # GPT Image 1.0 - has /text-to-image and /edit-image suffixes
    "gpt-image-1": {
        "generate": "fal-ai/gpt-image-1/text-to-image",
        "edit": "fal-ai/gpt-image-1/edit-image",
    },
    # GPT Image 1.5 - base path for generate, /edit for edit
    "gpt-image-1.5": {
        "generate": "fal-ai/gpt-image-1.5",
        "edit": "fal-ai/gpt-image-1.5/edit",
    },
    # Gemini via Fal
    "fal-gemini-2.5": {
        "generate": "fal-ai/nano-banana",
        "edit": "fal-ai/nano-banana/edit",
    },
    "fal-gemini-3-pro": {
        "generate": "fal-ai/nano-banana-pro",
        "edit": "fal-ai/nano-banana-pro/edit",
    },
}


def _get_fal_endpoint(model_id: str, has_images: bool = False) -> str:
    """Get Fal.AI endpoint for a model"""
    # Try model_registry first
    try:
        from .model_registry import get_model
        config = get_model(model_id)
        if config:
            return config.get_endpoint(has_images)
    except ImportError:
        pass

    # Fallback to hardcoded mapping
    if model_id in _FAL_MODEL_ENDPOINTS:
        endpoints = _FAL_MODEL_ENDPOINTS[model_id]
        return endpoints["edit"] if has_images else endpoints["generate"]

    # Unknown model - try generic pattern
    print(f"[API] Warning: Unknown model {model_id}, using generic endpoint")
    base = f"fal-ai/{model_id}"
    return f"{base}/edit" if has_images else base


def _get_model_max_batch(model_id: str) -> int:
    """Get max batch size for a model"""
    try:
        from .model_registry import get_model
        config = get_model(model_id)
        if config:
            return config.max_batch_size
    except ImportError:
        pass
    return 4  # Default


def _validate_session(model_id):
    """
    Keeps session validated if global token is passed.
    """

    try:
        from .config import session_run, is_internal
        return session_run(model_id or {})
    except ImportError:
        # Config module not available
        return model_id or {}


# =============================================================================
# UNIFIED FAL.AI GENERATION
# =============================================================================

def generate_with_fal(
        model_id: str,
        prompt: str,
        image_paths: List[str] = None,
        num_outputs: int = 1,
        api_key: str = "",
        timeout: int = 60,
        aspect_ratio: str = "1:1",
        model_params: Dict[str, Any] = None,
        progress_callback=None,
        cancel_event=None,
) -> List[Any]:
    """
    Unified Fal.AI generation handler.

    Works with GPT Image, Gemini via Fal, and future models.
    Uses model_registry if available, falls back to hardcoded endpoints otherwise.

    Args:
        model_id: Model identifier (e.g., "gpt-image-1.5")
        prompt: Generation prompt
        image_paths: Optional list of input image paths
        num_outputs: Number of images to generate
        api_key: Fal.AI API key
        timeout: Request timeout
        aspect_ratio: Aspect ratio string (e.g., "1:1", "16:9")
        model_params: Model-specific parameters (e.g., {"quality": "high", "background": "transparent"})
        progress_callback: Optional progress callback
        cancel_event: Optional threading.Event for cancellation

    Returns:
        List of PIL Image objects
    """
    if fal_client is None:
        raise Exception("fal_client not installed")

    if not api_key or len(api_key) < 10:
        raise Exception("FAL API key is empty or too short")

    os.environ["FAL_KEY"] = api_key

    log_verbose(f"Using model: {model_id}", "Fal")

    # Prepare images
    image_urls = _prepare_images_as_data_urls(image_paths or [])
    has_images = len(image_urls) > 0

    # Get endpoint
    endpoint = _get_fal_endpoint(model_id, has_images)
    log_verbose(f"Endpoint: {endpoint}", "Fal")

    # Build arguments
    args = {"prompt": prompt}

    # Add size for models that support it (only if not match_input_image)
    if model_id.startswith("gpt-image") and aspect_ratio and aspect_ratio != "match_input_image":
        size = get_fal_image_size(aspect_ratio)
        args["image_size"] = size

    # Add images if editing
    if has_images:
        # Grok Imagen expects 'image_url' (singular), not 'image_urls'
        if "grok-imagen" in model_id:
            args["image_url"] = image_urls[0]  # Single URL
        else:
            args["image_urls"] = image_urls

    # Add model-specific params (filter out default/placeholder values)
    if model_params:
        for key, value in model_params.items():
            # Skip values that shouldn't be sent to API
            if value in ("match_input_image", "1K", "auto"):
                continue
            args[key] = value
        log_verbose(f"Model params: {model_params}", "Fal")

    # Generate
    results = []
    max_outputs = min(num_outputs, _get_model_max_batch(model_id))

    for i in range(max_outputs):
        if cancel_event and cancel_event.is_set():
            log_verbose(f"Generation cancelled at {i}/{max_outputs}", "Fal")
            break

        try:
            result = fal_client.subscribe(endpoint, arguments=args, with_logs=True)
            images = _extract_images_from_fal_result(result, prefix=f"fal_{model_id.replace('.', '_')}")
            results.extend(images)

            if progress_callback:
                progress_callback(((i + 1) / max_outputs) * 100.0)

        except Exception as e:
            error_str = str(e).lower()
            if "cancel" in error_str or "abort" in error_str:
                print(f"[Fal] Generation was cancelled")
                break
            print(f"[Fal] Generation error: {e}")
            raise

    return results


# =============================================================================
# AIML API IMAGE GENERATION
# =============================================================================

def generate_with_aiml(
        model_id: str,
        prompt: str,
        image_paths: List[str] = None,
        num_outputs: int = 1,
        api_key: str = "",
        timeout: int = 60,
        aspect_ratio: str = "1:1",
        model_params: Dict[str, Any] = None,
        progress_callback=None,
        cancel_event=None,
) -> List[Any]:
    """
    Generate images using AIML API.

    AIML provides unified access to multiple AI models through a single API.

    Args:
        model_id: Model identifier (e.g., "gpt-image-1-aiml")
        prompt: Generation prompt
        image_paths: Optional list of input image paths for editing
        num_outputs: Number of images to generate (n parameter)
        api_key: AIML API key
        timeout: Request timeout in seconds
        aspect_ratio: Aspect ratio string (converted to size)
        model_params: Model-specific parameters
        progress_callback: Optional progress callback
        cancel_event: Optional threading.Event for cancellation

    Returns:
        List of PIL Image objects
    """
    import requests
    import base64
    from io import BytesIO

    if not api_key:
        raise ValueError("AIML API key is required")

    if not Image:
        raise RuntimeError("Pillow is required for AIML generation")

    model_params = dict(model_params) if model_params else {}
    image_paths = image_paths or []
    results = []

    # Pre-filter model_params to remove default/placeholder values that shouldn't be sent
    # This prevents "Invalid payload" errors from APIs that don't accept these
    keys_to_remove = [k for k, v in model_params.items()
                      if v in ("match_input_image", "1K", "auto")]
    for key in keys_to_remove:
        del model_params[key]

    # Get model config for endpoint info
    from .model_registry import get_model
    config = get_model(model_id)

    # Determine the AIML model name
    # Priority: model_params > config.endpoint > strip -aiml suffix
    aiml_model = model_params.get("aiml_model_name")
    if not aiml_model and config:
        aiml_model = config.endpoint
    if not aiml_model:
        aiml_model = model_id.replace("-aiml", "") if model_id.endswith("-aiml") else model_id

    # Check if this is an edit request (has input images)
    is_edit = len(image_paths) > 0

    # For edit mode, check if there's a separate edit endpoint
    if is_edit and config and hasattr(config, 'edit_endpoint') and config.edit_endpoint:
        aiml_model = config.edit_endpoint

    # Check if this is GPT-Image model (needs special handling)
    is_gpt_image = "gpt-image" in aiml_model.lower()

    # GPT-Image models with input images need multipart form data to /edits endpoint
    use_multipart = is_gpt_image and is_edit and len(image_paths) > 0

    if use_multipart:
        # Use edit endpoint with multipart form data
        url = "https://api.aimlapi.com/v1/images/edits"
        headers = {
            "Authorization": f"Bearer {api_key}",
            # Don't set Content-Type - requests will set it automatically for multipart
        }
    else:
        # Use generation endpoint with JSON
        url = "https://api.aimlapi.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    try:
        if use_multipart:
            # === MULTIPART FORM DATA FOR GPT-IMAGE EDITING ===
            # Build form data
            form_data = {
                "model": aiml_model,
                "prompt": prompt,
            }

            # Add size parameter
            aspect_ratio = model_params.get("aspect_ratio", "1:1")
            gpt_image_size_map = {
                "1:1": "1024x1024",
                "2:3": "1024x1536",
                "3:2": "1536x1024",
                "3:4": "1024x1536",
                "4:3": "1536x1024",
                "9:16": "1024x1536",
                "16:9": "1536x1024",
            }
            form_data["size"] = gpt_image_size_map.get(aspect_ratio, "1024x1024")

            # Add quality
            quality = model_params.get("quality", "medium")
            if quality == "auto":
                quality = "medium"
            form_data["quality"] = quality

            # Add background if specified
            if "background" in model_params:
                form_data["background"] = model_params["background"]

            # Prepare files for upload
            # GPT-Image accepts multiple images via 'image' field
            # IMPORTANT: Resize images to prevent 413 Payload Too Large errors
            files = []
            file_handles = []  # Keep track of file handles to close later
            temp_resized_files = []  # Track temp files for cleanup

            # Maximum dimension for AIML uploads (API limit is ~20MB, we target ~4MB)
            MAX_DIMENSION = 1536

            for i, path in enumerate(image_paths):
                if os.path.exists(path):
                    # Detect mime type
                    if path.lower().endswith(".png"):
                        mime = "image/png"
                        img_format = "PNG"
                    elif path.lower().endswith((".jpg", ".jpeg")):
                        mime = "image/jpeg"
                        img_format = "JPEG"
                    elif path.lower().endswith(".webp"):
                        mime = "image/webp"
                        img_format = "WEBP"
                    else:
                        mime = "image/png"
                        img_format = "PNG"

                    # Load and potentially resize image
                    try:
                        img = Image.open(path)
                        width, height = img.size

                        # Resize if any dimension exceeds MAX_DIMENSION
                        if width > MAX_DIMENSION or height > MAX_DIMENSION:
                            # Calculate new size maintaining aspect ratio
                            if width > height:
                                new_width = MAX_DIMENSION
                                new_height = int(height * (MAX_DIMENSION / width))
                            else:
                                new_height = MAX_DIMENSION
                                new_width = int(width * (MAX_DIMENSION / height))

                            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                            log_verbose(
                                f"Resized image from {width}x{height} to {new_width}x{new_height} for AIML upload",
                                "AIML")

                            # Save to temp file
                            from .utils import unique_temp_path, register_temp_file
                            temp_path = register_temp_file(
                                unique_temp_path(prefix="aiml_resize", ext=img_format.lower()))

                            # Convert RGBA to RGB for JPEG
                            if img_format == "JPEG" and img.mode == "RGBA":
                                img = img.convert("RGB")

                            img.save(temp_path, format=img_format, quality=90 if img_format == "JPEG" else None)
                            temp_resized_files.append(temp_path)

                            f = open(temp_path, "rb")
                            file_handles.append(f)
                            filename = os.path.basename(temp_path)
                        else:
                            # Use original file
                            f = open(path, "rb")
                            file_handles.append(f)
                            filename = os.path.basename(path)

                        img.close()
                    except Exception as e:
                        log_verbose(f"Failed to process image {path}: {e}", "AIML")
                        # Fallback: use original file
                        f = open(path, "rb")
                        file_handles.append(f)
                        filename = os.path.basename(path)

                    # Use 'image' as field name (API accepts array of images)
                    files.append(("image", (filename, f, mime)))

            log_verbose(f"AIML GPT-Image edit: model={aiml_model}, images={len(files)}, size={form_data.get('size')}",
                        "AIML")

            if progress_callback:
                progress_callback(10.0)

            try:
                # Make multipart request
                response = requests.post(
                    url,
                    headers=headers,
                    data=form_data,
                    files=files,
                    timeout=timeout
                )
            finally:
                # Close all file handles
                for f in file_handles:
                    f.close()

        else:
            # === JSON PAYLOAD FOR GENERATION (no images) ===
            payload = {
                "model": aiml_model,
                "prompt": prompt,
                "response_format": "b64_json"
            }

            # [FIX] Imagen models fail with response_format, others benefit from it
            if "imagen" not in aiml_model.lower():
                payload["response_format"] = "b64_json"

            # Handle GPT-Image models - they use 'size' not aspect_ratio/resolution
            if is_gpt_image:
                aspect_ratio = model_params.get("aspect_ratio", "1:1")
                gpt_image_size_map = {
                    "1:1": "1024x1024",
                    "2:3": "1024x1536",
                    "3:2": "1536x1024",
                    "3:4": "1024x1536",
                    "4:3": "1536x1024",
                    "9:16": "1024x1536",
                    "16:9": "1536x1024",
                }
                payload["size"] = gpt_image_size_map.get(aspect_ratio, "1024x1024")

                quality = model_params.get("quality", "medium")
                if quality == "auto":
                    quality = "medium"
                payload["quality"] = quality

                if "background" in model_params:
                    payload["background"] = model_params["background"]
            else:
                # Non-GPT-Image models - use standard parameters
                if "quality" in model_params:
                    payload["quality"] = model_params["quality"]
                if "background" in model_params:
                    payload["background"] = model_params["background"]
                if "aspect_ratio" in model_params and model_params["aspect_ratio"] != "match_input_image":
                    payload["aspect_ratio"] = model_params["aspect_ratio"]
                # Only send resolution if explicitly set to 2K or 4K (1K is default everywhere)
                if "resolution" in model_params and model_params["resolution"] in ("2K", "4K"):
                    payload["resolution"] = model_params["resolution"]

                # Add images for non-GPT-Image models (base64/URL method)
                if is_edit and len(image_paths) > 0 and "imagen" not in aiml_model.lower():
                    image_urls = []
                    for path in image_paths:
                        if path.startswith("http"):
                            image_urls.append(path)
                        elif os.path.exists(path):
                            with open(path, "rb") as f:
                                img_data = f.read()
                            if path.lower().endswith(".png"):
                                mime = "image/png"
                            elif path.lower().endswith((".jpg", ".jpeg")):
                                mime = "image/jpeg"
                            else:
                                mime = "image/png"
                            data_url = f"data:{mime};base64,{base64.b64encode(img_data).decode('utf-8')}"
                            image_urls.append(data_url)
                    if image_urls:
                        payload["image_urls"] = image_urls

            # Common optional params
            if "enhance_prompt" in model_params:
                payload["enhance_prompt"] = model_params["enhance_prompt"]
            if "person_generation" in model_params:
                payload["person_generation"] = model_params["person_generation"]
            if "safety_setting" in model_params:
                payload["safety_setting"] = model_params["safety_setting"]

            log_verbose(f"AIML API request: model={aiml_model}, edit={is_edit}, has_images={len(image_paths)}", "AIML")

            if progress_callback:
                progress_callback(10.0)

            # Make JSON request
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout
            )

        if cancel_event and cancel_event.is_set():
            return results

        if progress_callback:
            progress_callback(80.0)

        response.raise_for_status()
        data = response.json()

        # Parse response - AIML format:
        # {"images": [{"url": "...", "content_type": "...", ...}], "description": "..."}
        if "images" in data:
            for item in data["images"]:
                if cancel_event and cancel_event.is_set():
                    break

                if "url" in item:
                    # Download image from URL
                    img_response = requests.get(item["url"], timeout=30)
                    img_response.raise_for_status()
                    img = Image.open(BytesIO(img_response.content))
                    img.load()
                    results.append(img)
                elif "b64_json" in item:
                    # Base64 encoded image (fallback)
                    img_data = base64.b64decode(item["b64_json"])
                    img = Image.open(BytesIO(img_data))
                    img.load()
                    results.append(img)

        # Also check OpenAI-compatible format (fallback)
        elif "data" in data:
            for item in data["data"]:
                if cancel_event and cancel_event.is_set():
                    break

                if "url" in item:
                    img_response = requests.get(item["url"], timeout=30)
                    img_response.raise_for_status()
                    img = Image.open(BytesIO(img_response.content))
                    img.load()
                    results.append(img)
                elif "b64_json" in item:
                    img_data = base64.b64decode(item["b64_json"])
                    img = Image.open(BytesIO(img_data))
                    img.load()
                    results.append(img)

        if progress_callback:
            progress_callback(100.0)

        log_verbose(f"AIML generated {len(results)} image(s)", "AIML")

    except requests.exceptions.HTTPError as e:
        error_msg = str(e)
        try:
            error_data = e.response.json()
            if "error" in error_data:
                error_msg = error_data["error"].get("message", str(e))
        except Exception:
            pass
        print(f"[AIML] HTTP error: {error_msg}")
        raise RuntimeError(f"AIML API error: {error_msg}")

    except Exception as e:
        print(f"[AIML] Generation error: {e}")
        raise

    return results


# =============================================================================
# REPLICATE IMAGE GENERATION
# =============================================================================

def generate_with_replicate(
        model_id: str,
        prompt: str,
        image_paths: List[str] = None,
        num_outputs: int = 1,
        api_key: str = "",
        timeout: int = 60,
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        model_params: Dict[str, Any] = None,
        progress_callback=None,
        cancel_event=None,
        openai_api_key: str = "",
) -> List[Any]:
    """
    Generate images using Replicate API.

    Args:
        model_id: Model identifier (e.g., "google/nano-banana", "openai/gpt-image-1.5")
        prompt: Generation prompt
        image_paths: Optional list of input image paths
        num_outputs: Number of images to generate
        api_key: Replicate API token
        timeout: Request timeout (not directly used, Replicate handles internally)
        aspect_ratio: Aspect ratio string
        resolution: Resolution for models that support it
        model_params: Model-specific parameters
        progress_callback: Optional progress callback
        cancel_event: Optional threading.Event for cancellation
        openai_api_key: OpenAI API key (required for openai/ models on Replicate)

    Returns:
        List of PIL Image objects
    """
    if replicate_client is None:
        raise Exception("replicate module not installed")

    if not api_key or len(api_key) < 10:
        raise Exception("Replicate API key is empty or too short")

    os.environ["REPLICATE_API_TOKEN"] = api_key

    log_verbose(f"Using model: {model_id}", "Replicate")

    # Get endpoint from registry
    from .model_registry import get_model
    config = get_model(model_id)
    endpoint = config.endpoint if config else model_id

    log_verbose(f"Endpoint: {endpoint}", "Replicate")

    # Build input arguments
    input_args = {"prompt": prompt}

    # Handle input images
    if image_paths:
        image_urls = _prepare_images_as_data_urls(image_paths)
        if image_urls:
            # GPT Image models use "input_images" as a list
            if "gpt-image" in model_id:
                input_args["input_images"] = image_urls
            elif "nano-banana" in endpoint or "nano-banana" in model_id:
                # nano-banana on Replicate uses "image_input" array
                input_args["image_input"] = image_urls
                log_verbose(f"Added image_input array: {len(image_urls)} image(s)", "Replicate")
            else:
                input_args["image"] = image_urls[0]
            log_verbose(f"Input images count: {len(image_urls)}", "Replicate")

    # Inject OpenAI API key ONLY for gpt-image-1 (not 1.5) on Replicate
    # gpt-image-1.5 does NOT require OpenAI key, only Replicate key
    needs_openai_key = ("gpt-image-1" in model_id or "gpt-image-1" in endpoint) and \
                       "gpt-image-1.5" not in model_id and "gpt-image-1.5" not in endpoint

    if needs_openai_key:
        if openai_api_key and len(openai_api_key) > 10:
            input_args["openai_api_key"] = openai_api_key
            log_verbose("OpenAI API key injected for GPT Image 1", "Replicate")
        else:
            raise Exception("OpenAI API key required for GPT Image 1 on Replicate. "
                            "Add your OpenAI key in addon preferences, or use GPT Image 1.5 instead.")

    # Add model-specific params first (these take priority, but filter out defaults)
    if model_params:
        for key, value in model_params.items():
            # Skip values that shouldn't be sent to API
            if value in ("match_input_image", "1K", "auto"):
                continue
            input_args[key] = value
        log_verbose(f"Model params: {model_params}", "Replicate")

    # Add aspect ratio if not already in model_params
    if "aspect_ratio" not in input_args:
        if aspect_ratio and aspect_ratio != "match_input_image":
            input_args["aspect_ratio"] = aspect_ratio

    # Add resolution for models that support it (if not already in model_params)
    if "resolution" not in input_args and "nano-banana-pro" in endpoint:
        input_args["resolution"] = resolution

    # Generate
    results = []
    max_outputs = min(num_outputs, 4)  # Replicate typically supports up to 4

    log_verbose(f"Final input_args keys: {list(input_args.keys())}", "Replicate")
    log_verbose(f"Endpoint: {endpoint}, has images: {'image_url' in input_args or 'image' in input_args or 'input_images' in input_args}", "Replicate")

    for i in range(max_outputs):
        if cancel_event and cancel_event.is_set():
            log_verbose(f"Generation cancelled at {i}/{max_outputs}", "Replicate")
            break

        try:
            output = replicate_client.run(endpoint, input=input_args)

            # Handle output - can be list of FileOutput or single FileOutput
            if output:
                if isinstance(output, list):
                    for item in output:
                        url = item.url if hasattr(item, 'url') else str(item)
                        pil_img = _download_image_to_pil(url, prefix="replicate")
                        if pil_img:
                            results.append(pil_img)
                else:
                    url = output.url if hasattr(output, 'url') else str(output)
                    pil_img = _download_image_to_pil(url, prefix="replicate")
                    if pil_img:
                        results.append(pil_img)

            if progress_callback:
                progress_callback(((i + 1) / max_outputs) * 100.0)

        except Exception as e:
            error_str = str(e).lower()
            if "cancel" in error_str or "abort" in error_str:
                print(f"[Replicate] Generation was cancelled")
                break
            print(f"[Replicate] Generation error: {e}")
            raise

    return results


# =============================================================================
# UNIFIED IMAGE GENERATION ENTRY POINT
# =============================================================================

def generate_images(
        model_id: str,
        prompt: str,
        image_paths: List[str] = None,
        num_outputs: int = 1,
        api_keys: Dict[str, str] = None,
        timeout: int = 60,
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        model_params: Dict[str, Any] = None,
        # Thought signatures (Gemini 3 only)
        use_thought_signatures: bool = False,
        conversation_history: list = None,
        progress_callback=None,
        cancel_event=None,
):

    """
    Unified image generation entry point.

    Routes to appropriate provider (Google Gemini or Fal.AI) based on model_id.

    Args:
        model_id: Model identifier (e.g., "gemini-2.5-flash-image", "gpt-image-1.5")
        prompt: Generation prompt
        image_paths: Optional list of input image paths for editing
        num_outputs: Number of images to generate
        api_keys: Dict with "google" and/or "fal" API keys
        timeout: Request timeout in seconds
        aspect_ratio: Aspect ratio string (e.g., "1:1", "16:9")
        resolution: Resolution for Gemini 3 ("1K", "2K", "4K")
        model_params: Model-specific parameters from registry
        use_thought_signatures: Enable multi-turn conversation (Gemini 3 only)
        conversation_history: Previous turns for multi-turn
        progress_callback: Optional progress callback
        cancel_event: Optional threading.Event for cancellation

    Returns:
        List of PIL Image objects
        If use_thought_signatures=True: (images, new_history) tuple
    """

    from .model_registry import Provider

    api_keys = api_keys or {}
    model_params = model_params or {}
    image_paths = image_paths or []

    config = _validate_session(model_id)

    if config is None:
        raise ValueError("License validation failed. Please check your license key.")

    provider = config.provider

    # Route to appropriate provider
    if provider == Provider.REPLICATE:
        replicate_key = api_keys.get("replicate", "")
        if not replicate_key:
            raise ValueError("Replicate API key required for this model")

        return generate_with_replicate(
            model_id=model_id,
            prompt=prompt,
            image_paths=image_paths,
            num_outputs=num_outputs,
            api_key=replicate_key,
            timeout=timeout,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model_params=model_params,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            openai_api_key=api_keys.get("openai", ""),
        )

    elif provider == Provider.FAL:
        fal_key = api_keys.get("fal", "")
        if not fal_key:
            raise ValueError("Fal.AI API key required for this model")

        return generate_with_fal(
            model_id=model_id,
            prompt=prompt,
            image_paths=image_paths,
            num_outputs=num_outputs,
            api_key=fal_key,
            timeout=timeout,
            aspect_ratio=aspect_ratio,
            model_params=model_params,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    elif provider == Provider.GOOGLE:
        google_key = api_keys.get("google", "")
        if not google_key:
            raise ValueError("Google API key required for this model")

        # Extract google_search from model_params
        google_search = model_params.pop("google_search", False)

        return generate_with_gemini(
            prompt=prompt,
            image_paths=image_paths,
            num_outputs=num_outputs,
            model_name=model_id,
            api_key=google_key,
            timeout=timeout,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            use_thought_signatures=use_thought_signatures,
            conversation_history=conversation_history,
            google_search=google_search,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    elif provider == Provider.AIML:
        aiml_key = api_keys.get("aiml", "")
        if not aiml_key:
            raise ValueError("AIML API key required for this model")

        return generate_with_aiml(
            model_id=model_id,
            prompt=prompt,
            image_paths=image_paths,
            num_outputs=num_outputs,
            api_key=aiml_key,
            timeout=timeout,
            aspect_ratio=aspect_ratio,
            model_params=model_params,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    else:
        raise ValueError(f"Unknown provider: {provider}")


# =============================================================================
# GOOGLE GEMINI GENERATION (Direct API)
# =============================================================================

def generate_with_gemini(prompt, image_paths, num_outputs=1, model_name="gemini-2.5-flash-image",
                         api_key="", timeout=60, aspect_ratio="1:1", resolution="1K",
                         use_thought_signatures=False, conversation_history=None,
                         google_search=False,
                         progress_callback=None, cancel_event=None):
    """
    Send prompt and images to Gemini and return list of Pillow images.

    Args:
        prompt: Text prompt
        image_paths: List of image file paths
        num_outputs: Number of images to generate
        model_name: Gemini model name
        api_key: Google API key
        timeout: Request timeout in seconds
        aspect_ratio: Aspect ratio string
        resolution: Resolution string ("1K", "2K", "4K")
        use_thought_signatures: Enable thought signatures for multi-turn (Gemini 3 only)
        conversation_history: Previous conversation turns for multi-turn generation
        google_search: Enable Google Search tool for real-time information
        progress_callback: Optional progress callback
        cancel_event: Optional cancellation event

    Returns:
        If use_thought_signatures: (images, new_history) tuple
        Otherwise: images list
    """
    if not api_key:
        raise ValueError("API key is required")

    if Client is None or types is None:
        raise Exception("google.genai not installed")

    timeout_ms = int(timeout * 1000)
    client = Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))

    current_user_parts = None

    # Build contents for this request
    if use_thought_signatures:
        if conversation_history:
            contents = list(conversation_history)
        else:
            contents = []

        current_user_parts = [{"text": prompt}]
        for path in image_paths:
            try:
                with open(path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode()
                    current_user_parts.append({
                        "inlineData": {
                            "mimeType": guess_mime(path),
                            "data": img_data
                        }
                    })
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to read {path}: {e}")

        contents.append({"role": "user", "parts": current_user_parts})
    else:
        contents = [prompt]
        for path in image_paths:
            try:
                with open(path, "rb") as f:
                    contents.append(types.Part.from_bytes(mime_type=guess_mime(path), data=f.read()))
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to read {path}: {e}")

    # Configure Image options - only include aspect_ratio if not match_input_image
    img_config_args = {}
    if aspect_ratio and aspect_ratio != "match_input_image":
        img_config_args["aspect_ratio"] = aspect_ratio

    if model_name == "gemini-3-pro-image-preview":
        res_map = {"1024": "1K", "2048": "2K", "4096": "4K"}
        api_res = res_map.get(str(resolution), resolution)
        img_config_args["image_size"] = api_res
        print(f"[{LOG_PREFIX}] Using resolution: {api_res}")

    # Build config with optional tools
    config_args = {
        "response_modalities": ["IMAGE"],
        "image_config": types.ImageConfig(**img_config_args),
    }

    # Add Google Search tool if enabled
    if google_search:
        config_args["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        print(f"[{LOG_PREFIX}] Google Search enabled")

    config = types.GenerateContentConfig(**config_args)

    results = []
    new_history = list(conversation_history) if conversation_history else []
    history_updated = False

    actual_num_outputs = 1 if use_thought_signatures else num_outputs

    for i in range(actual_num_outputs):
        if cancel_event and cancel_event.is_set():
            break

        if progress_callback:
            progress_callback((i / actual_num_outputs) * 100.0)

        #added chunk retry
        try:
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    response = client.models.generate_content(
                        model=model_name, contents=contents, config=config
                    )
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e).lower()
                    # Retry on network/chunked errors
                    is_network = ("chunked" in error_str or "peer closed" in error_str
                                  or "incomplete" in error_str or "connection" in error_str
                                  or "reset" in error_str)
                    if is_network and attempt < max_retries:
                        print(f"[{LOG_PREFIX}] Network error, retry {attempt + 1}/{max_retries}: {e}")
                        import time
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise  # Not retryable or exhausted retries

            # Check if response has parts
            if not response or not response.parts:
                print(f"[{LOG_PREFIX}] Empty response or no parts returned")
                continue

            model_parts = []

            for part in response.parts:
                is_thought = getattr(part, "thought", False)
                if is_thought:
                    print(f"[{LOG_PREFIX}] Skipping thought part")
                    continue

                sig = getattr(part, "thought_signature", None) or getattr(part, "thoughtSignature", None)

                if getattr(part, "inline_data", None):
                    try:
                        img_bytes = io.BytesIO(part.inline_data.data)
                        img = Image.open(img_bytes)
                        img.load()
                        results.append(img)

                        if use_thought_signatures and not history_updated:
                            part_dict = {
                                "inlineData": {
                                    "mimeType": part.inline_data.mime_type,
                                    "data": base64.b64encode(part.inline_data.data).decode()
                                }
                            }
                            if sig:
                                part_dict["thoughtSignature"] = sig
                                print(f"[{LOG_PREFIX}] Image has signature: {sig[:30]}...")
                            model_parts.append(part_dict)

                        if progress_callback:
                            progress_callback(((i + 1) / actual_num_outputs) * 100.0)
                        break
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Image decode failed: {e}")

                elif getattr(part, "text", None):
                    print(f"[{LOG_PREFIX}] text:", part.text)
                    if use_thought_signatures and not history_updated:
                        part_dict = {"text": part.text}
                        if sig:
                            part_dict["thoughtSignature"] = sig
                            print(f"[{LOG_PREFIX}] Text has signature: {sig[:30]}...")
                        model_parts.append(part_dict)

            if use_thought_signatures and model_parts and not history_updated:
                if current_user_parts:
                    new_history.append({"role": "user", "parts": current_user_parts})
                new_history.append({"role": "model", "parts": model_parts})
                history_updated = True
                print(f"[{LOG_PREFIX}] History now has {len(new_history) // 2} turns")

        except Exception as e:
            error_str = str(e).lower()
            print(f"[{LOG_PREFIX}] Generation error: {e}")

            if "timeout" in error_str or "deadline" in error_str:
                raise TimeoutError("Generation timed out")
            elif "400" in str(e) or "user location" in error_str or "not supported" in error_str:
                raise PermissionError("API_LOCATION_ERROR: Gemini API is not available in your region. Use a VPN.")
            elif "403" in str(e) or "permission" in error_str or "forbidden" in error_str:
                raise PermissionError("API_PERMISSION_ERROR: API key doesn't have permission or quota exceeded.")
            elif "401" in str(e) or "unauthorized" in error_str or "invalid" in error_str:
                raise PermissionError("API_AUTH_ERROR: Invalid API key.")
            elif "429" in str(e) or "quota" in error_str or "rate" in error_str:
                raise PermissionError("API_QUOTA_ERROR: Rate limit or quota exceeded. Wait and try again.")
            elif "chunked" in error_str or "peer closed" in error_str or "incomplete" in error_str:
                raise ConnectionError("API_NETWORK_ERROR: Connection interrupted. Check network/VPN and try again.")
            elif "500" in str(e) or "503" in str(e) or "server" in error_str:
                raise ConnectionError("API_SERVER_ERROR: Gemini servers are overloaded. Try again later.")

    if use_thought_signatures:
        return results, new_history
    return results


# =============================================================================
# PROMPT UPGRADE
# =============================================================================

def upgrade_prompt_with_gemini(original_prompt, image_paths, upgrade_template, model_name="gemini-2.5-pro",
                               api_key="", timeout=60):
    """Use Gemini to analyze images and upgrade the prompt."""
    if not api_key:
        raise ValueError("API key is required")

    if Client is None or types is None:
        raise Exception("google.genai not installed")

    timeout_ms = int(timeout * 1000)
    client = Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))

    formatted_prompt = upgrade_template.format(original_prompt=original_prompt)

    contents = [formatted_prompt]
    for path in image_paths:
        try:
            with open(path, "rb") as f:
                contents.append(types.Part.from_bytes(mime_type=guess_mime(path), data=f.read()))
        except Exception as e:
            print(f"[{LOG_PREFIX}] Failed to read {path}: {e}")

    config = types.GenerateContentConfig(
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_ONLY_HIGH"
            ),
        ],
        temperature=0.7,
    )

    try:
        response = client.models.generate_content(model=model_name, contents=contents, config=config)
        if response.text:
            return response.text.strip()
        return None

    except Exception as e:
        print(f"[{LOG_PREFIX}] Prompt upgrade error: {e}")
        if "timeout" in str(e).lower() or "deadline" in str(e).lower():
            raise TimeoutError("Prompt upgrade timed out")
        return None


# =============================================================================
# BACKGROUND REMOVAL (Fal.AI)
# =============================================================================

def remove_background_fal(image_path, api_key):
    """Remove background from image using Fal.AI BiRefNet"""
    if fal_client is None:
        raise Exception("fal_client not installed")

    print(f"[Fal.AI] Setting FAL_KEY for bg removal, length: {len(api_key)} chars")
    if not api_key or len(api_key) < 10:
        raise Exception("FAL API key is empty or too short")

    os.environ["FAL_KEY"] = api_key

    img = Image.open(image_path)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()
    data_url = f"data:image/png;base64,{img_base64}"

    try:
        result = fal_client.subscribe(
            "fal-ai/birefnet",
            arguments={"image_url": data_url},
            with_logs=True
        )

        if result and 'image' in result and 'url' in result['image']:
            output_path = register_temp_file(unique_temp_path(prefix="nobg"))
            urllib.request.urlretrieve(result['image']['url'], output_path)
            return output_path

        return None
    except Exception as e:
        print(f"[Fal.AI] Background removal error: {e}")
        return None


def remove_background_replicate(image_path, api_key):
    """Remove background from image using Replicate BiRefNet"""
    if replicate_client is None:
        raise Exception("replicate module not installed")

    print(f"[Replicate] Setting API token for bg removal, length: {len(api_key)} chars")
    if not api_key or len(api_key) < 10:
        raise Exception("Replicate API key is empty or too short")

    os.environ["REPLICATE_API_TOKEN"] = api_key

    # Convert image to data URL
    img = Image.open(image_path)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()
    data_url = f"data:image/png;base64,{img_base64}"

    try:
        # Use pinned BiRefNet model
        output = replicate_client.run(
            "men1scus/birefnet:f74986db0355b58403ed20963af156525e2891ea3c2d499bfbfb2a28cd87c5d7",
            input={"image": data_url}
        )

        if output:
            # Output is FileOutput object with url attribute
            url = output.url if hasattr(output, 'url') else str(output)
            output_path = register_temp_file(unique_temp_path(prefix="nobg_rep"))
            urllib.request.urlretrieve(url, output_path)
            return output_path

        return None
    except Exception as e:
        print(f"[Replicate] Background removal error: {e}")
        return None


# =============================================================================
# BACKGROUND REMOVAL (Local)
# =============================================================================

def trigger_model_download():
    """Helper to trigger model download in background thread."""
    try:
        # Check if model exists first
        home = os.path.expanduser("~")
        model_path = os.path.join(home, ".u2net", "birefnet-general.onnx")
        if os.path.exists(model_path):
            return True, "Model already exists"

        from .dependencies import get_rembg_libs_path
        rembg_libs = get_rembg_libs_path()
        if os.path.exists(rembg_libs) and rembg_libs not in sys.path:
            sys.path.insert(0, rembg_libs)

        # Create dummy session to force download
        from rembg import new_session
        print("[BG Removal] Starting model download...")
        new_session("birefnet-general")
        return True, "Download started"
    except Exception as e:
        return False, str(e)


def remove_background(image_path, api_keys, active_provider=None):
    """Unified background removal."""
    api_keys = api_keys or {}
    providers_order = ['replicate', 'fal', 'local']
    if active_provider == 'fal': providers_order = ['fal', 'replicate', 'local']

    for provider in providers_order:
        if provider == 'replicate':
            key = api_keys.get("replicate", "")
            if key and replicate_client:
                res = remove_background_replicate(image_path, key)
                if res: return res
        elif provider == 'fal':
            key = api_keys.get("fal", "")
            if key and fal_client:
                res = remove_background_fal(image_path, key)
                if res: return res
        elif provider == 'local':
            res = remove_background_local(image_path)
            if res: return res

    # If all failed, show popup
    def show_failure(self, context):
        self.layout.label(text="Background Removal Failed", icon='ERROR')
        self.layout.label(text="Check System Console for details.")

    if bpy.context and bpy.context.window_manager:
        bpy.context.window_manager.popup_menu(show_failure, title="Failed", icon='ERROR')
    return None


def remove_background_local(image_path):
    """
    Remove background using local rembg with 'birefnet-general'.
    High precision model, ideal for hair and complex details.

    SPEED OPTIMIZATION: Uses global session cache to avoid 4s startup overhead.
    """
    global _rembg_session

    # Add rembg libs to path
    try:
        from .dependencies import get_rembg_libs_path
        rembg_libs = get_rembg_libs_path()
        if os.path.exists(rembg_libs) and rembg_libs not in sys.path:
            sys.path.insert(0, rembg_libs)
    except ImportError:
        pass

    try:
        import rembg
        from rembg import new_session
    except ImportError:
        print("[BG Removal] Libraries not found.")
        return None

    try:
        with open(image_path, 'rb') as f:
            input_data = f.read()

        # SESSION CACHING (The Speed Fix)
        if _rembg_session is None:
            print("[BG Removal] Initializing BiRefNet session (this happens once)...")
            # Using 'birefnet-general' (High Quality, ~170MB)
            _rembg_session = new_session("birefnet-general")
        else:
            print("[BG Removal] Using cached session (Fast path)")

        output_data = rembg.remove(input_data, session=_rembg_session)

        import tempfile
        ext = os.path.splitext(image_path)[1] or '.png'
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_nobg{ext}") as tmp:
            tmp.write(output_data)
            output_path = tmp.name

        print(f"[BG Removal] Saved to: {output_path}")
        return output_path

    except Exception as e:
        # traceback.print_exc()
        log_verbose(f"Error: {e}", "BG Removal")

        # Invalidate session on error
        _rembg_session = None

        def draw_err(self, context):
            self.layout.label(text="BiRefNet Error", icon='ERROR')
            if "download" in str(e).lower() or "connect" in str(e).lower():
                self.layout.label(text="Model download failed.")
                self.layout.label(text="Check internet connection.")
            else:
                self.layout.label(text="Check Console for details.")

        if bpy.context and bpy.context.window_manager:
            bpy.context.window_manager.popup_menu(draw_err, title="Error", icon='ERROR')
        return None


# =============================================================================
# TEXT GENERATION (Gemini)
# =============================================================================

def generate_text_with_gemini(prompt, image_paths=None, model_name="gemini-3-pro-preview", api_key="",
                              thinking_level="high", use_google_search=False, timeout=120):
    """Generate text using Gemini with optional images and tools.

    Args:
        prompt: The text prompt
        image_paths: List of image file paths to include
        model_name: Gemini model to use
        api_key: Google API key
        thinking_level: "none", "low", or "high" (Gemini 3 only)
        use_google_search: Enable Google Search grounding
        timeout: Request timeout in seconds

    Returns:
        Generated text string or None on error
    """
    if not api_key:
        raise ValueError("API key is required")

    timeout_ms = int(timeout * 1000)
    client = Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))

    # Build contents
    contents = [prompt]

    # Add images if provided
    if image_paths:
        for path in image_paths:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        contents.append(types.Part.from_bytes(mime_type=guess_mime(path), data=f.read()))
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Failed to read {path}: {e}")

    # Build config
    config_args = {}

    # Thinking config for Gemini 3
    if "gemini-3" in model_name and thinking_level != "none":
        config_args["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

    # Google Search tool
    if use_google_search:
        config_args["tools"] = [types.Tool(google_search=types.GoogleSearch())]

    config = types.GenerateContentConfig(**config_args) if config_args else None

    try:
        if config:
            response = client.models.generate_content(model=model_name, contents=contents, config=config)
        else:
            response = client.models.generate_content(model=model_name, contents=contents)

        # Extract text from response
        if response and response.text:
            return response.text.strip()

        # Try to extract from parts
        if response and response.parts:
            text_parts = []
            for part in response.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
            if text_parts:
                return "\n".join(text_parts).strip()

        return None

    except Exception as e:
        print(f"[{LOG_PREFIX}] Text generation error: {e}")
        raise


# =============================================================================
# TEXT GENERATION (Replicate)
# =============================================================================

def generate_text_with_replicate(prompt, image_paths=None, model_id="gemini-3-pro", api_key="",
                                 model_params=None, timeout=120):
    """Generate text using Replicate API (GPT-5, Gemini 3 Pro).

    Args:
        prompt: The text prompt
        image_paths: List of image file paths to include
        model_id: Model identifier (replicate-gpt-5, replicate-gemini-3-pro)
        api_key: Replicate API key
        model_params: Model-specific parameters (verbosity, reasoning_effort, thinking_level)
        timeout: Request timeout in seconds (not directly used)

    Returns:
        Generated text string or None on error
    """
    if replicate_client is None:
        raise Exception("replicate module not installed")

    if not api_key:
        raise ValueError("Replicate API key is required")

    os.environ["REPLICATE_API_TOKEN"] = api_key
    model_params = model_params or {}

    # Get endpoint from registry
    from .model_registry import get_model
    config = get_model(model_id)
    endpoint = config.endpoint if config else model_id

    log_verbose(f"Text gen endpoint: {endpoint}", "Replicate")

    # Build input
    input_args = {"prompt": prompt}

    # Handle images
    if image_paths:
        image_urls = _prepare_images_as_data_urls(image_paths)
        if image_urls:
            if "gpt-5" in endpoint:
                input_args["image_input"] = image_urls  # GPT-5 uses array
            else:
                input_args["images"] = image_urls  # Gemini uses images array

    # Add model-specific params
    if "gpt-5" in endpoint:
        input_args["verbosity"] = model_params.get("verbosity", "medium")
        input_args["reasoning_effort"] = model_params.get("reasoning_effort", "minimal")
    elif "gemini-3" in endpoint:
        input_args["thinking_level"] = model_params.get("thinking_level", "low")

    try:
        # Use run() and collect output (not streaming)
        output = replicate_client.run(endpoint, input=input_args)

        # Output for text models is typically iterator or string
        if output:
            if isinstance(output, str):
                return output.strip()
            # Collect iterator output
            result_text = ""
            for chunk in output:
                if chunk:
                    result_text += str(chunk)
            return result_text.strip() if result_text else None

        return None

    except Exception as e:
        print(f"[Replicate] Text generation error: {e}")
        raise


# =============================================================================
# TEXT GENERATION (AIML)
# =============================================================================

def generate_text_with_aiml(prompt, image_paths=None, model_id="", api_key="",
                            model_params=None, timeout=120):
    """
    Generate text using AIML API (Chat Completions endpoint).

    Args:
        prompt: The text prompt
        image_paths: List of image file paths to include (multimodal)
        model_id: Model identifier (e.g. gpt-5-aiml)
        api_key: AIML API key
        model_params: Model-specific parameters
        timeout: Request timeout in seconds

    Returns:
        Generated text string
    """
    import requests
    import base64

    if not api_key:
        raise ValueError("AIML API key is required")

    model_params = model_params or {}
    image_paths = image_paths or []

    # Get endpoint from registry
    from .model_registry import get_model
    config = get_model(model_id)

    # Priority: params > endpoint > model_id
    aiml_model = model_params.get("aiml_model_name")
    if not aiml_model:
        aiml_model = config.endpoint if config else model_id

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Use Chat Completions API (works for all AIML models including GPT-5)
    url = "https://api.aimlapi.com/v1/chat/completions"

    # Build messages
    messages = []
    user_content = []

    # Add text prompt
    user_content.append({"type": "text", "text": prompt})

    # Add images (OpenAI Vision format)
    if image_paths:
        for path in image_paths:
            try:
                with open(path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")

                # Determine mime type
                mime = "image/jpeg"
                if path.lower().endswith(".png"):
                    mime = "image/png"
                elif path.lower().endswith(".webp"):
                    mime = "image/webp"

                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{img_data}"
                    }
                })
            except Exception as e:
                print(f"[AIML] Failed to read image {path}: {e}")

    messages.append({"role": "user", "content": user_content})

    # Build Payload
    payload = {
        "model": aiml_model,
        "messages": messages,
        "max_tokens": model_params.get("max_tokens", 2048),
        "temperature": model_params.get("temperature", 1.0),
        "stream": False
    }

    # Add reasoning_effort for models that support it (GPT-5 series)
    if "reasoning_effort" in model_params and "gpt-5" in aiml_model.lower():
        effort = model_params["reasoning_effort"]
        # Don't send 'none' as it may not be needed
        if effort and effort != "none":
            # !!! AIML does not support 'minimal', map it to 'low'
            if effort == "minimal":
                effort = "low"
            payload["reasoning_effort"] = effort

    log_verbose(f"AIML Text request: model={aiml_model}, params={model_params}", "AIML")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0].get("message", {}).get("content", "")
            return content.strip()

        return None

    except requests.exceptions.HTTPError as e:
        print(f"[AIML] Text generation error: {e}")
        raise
    except Exception as e:
        print(f"[AIML] Text generation error: {e}")
        raise


def generate_text(prompt, image_paths=None, model_id="", api_keys=None,
                  model_params=None, timeout=120):
    """
    Unified text generation entry point.

    Routes to appropriate provider based on model_id.
    """

    from .model_registry import Provider

    api_keys = api_keys or {}
    model_params = model_params or {}

    config = _validate_session(model_id)

    if config is None:
        raise ValueError("License validation failed. Please check your license key.")

    provider = config.provider

    if provider == Provider.REPLICATE:
        replicate_key = api_keys.get("replicate", "")
        if not replicate_key:
            raise ValueError("Replicate API key required")
        return generate_text_with_replicate(
            prompt=prompt,
            image_paths=image_paths,
            model_id=model_id,
            api_key=replicate_key,
            model_params=model_params,
            timeout=timeout,
        )
    elif provider == Provider.AIML:
        aiml_key = api_keys.get("aiml", "")
        if not aiml_key:
            raise ValueError("AIML API key required")
        return generate_text_with_aiml(
            prompt=prompt,
            image_paths=image_paths,
            model_id=model_id,
            api_key=aiml_key,
            model_params=model_params,
            timeout=timeout,
        )
    else:
        google_key = api_keys.get("google", "")
        if not google_key:
            raise ValueError("Google API key required")

        thinking_level = model_params.get("thinking_level", "none")
        use_google_search = model_params.get("use_google_search", False)

        return generate_text_with_gemini(
            prompt=prompt,
            image_paths=image_paths,
            model_name=model_id,
            api_key=google_key,
            thinking_level=thinking_level,
            use_google_search=use_google_search,
            timeout=timeout,
        )