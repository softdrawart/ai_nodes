# -*- coding: utf-8 -*-
"""
Addon Proxy - Routes all generation through api
"""

import os
import io
import json
import base64
import time
import urllib.request
import urllib.error

from ..utils import log_verbose
from .config_proxy import _PROXY_BASE_GEN as _PROXY_BASE
from .config_proxy import _PROXY_BASE_ERROR

# =============================================================================
# ENDPOINTS (base URL hidden in compiled config_proxy.pyd)
# =============================================================================

_EP_GENERATE = _PROXY_BASE + "/generate"
_EP_BALANCE = _PROXY_BASE + "/balance"
_EP_VALIDATE = _PROXY_BASE + "/validate"
_EP_TRIPO_UPLOAD = _PROXY_BASE + "/tripo/upload"
_EP_TRIPO_TASK = _PROXY_BASE + "/tripo/task"
_EP_TRIPO_BALANCE = _PROXY_BASE + "/tripo/balance"
_PROXY_NAME = "PROXY"

# Request timeout (seconds) - generous for batches queued server-side
_REQUEST_TIMEOUT = 300


def _extract_status(result):
    """Extract numeric HTTP status from proxy response.

    Handles three formats:
      - Direct: {"status": 429}  (sync path / _proxy_request error dict)
      - Async job: {"status": "error", "vertex_status": 429}  (Cloud Run callback)
      - Legacy: {"message": "...429...RESOURCE_EXHAUSTED..."}  (status lost, sniff message)
    """
    s = result.get("status")
    if isinstance(s, int):
        return s
    vs = result.get("vertex_status")
    if isinstance(vs, int):
        return vs
    msg = str(result.get("message", ""))
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return 429
    return 500


# =============================================================================
# HTTP HELPERS
# =============================================================================

def _poll_job(job_id, api_key, total_timeout):
    """Poll async generation job until completion."""
    poll_url = f"{_PROXY_BASE}/generate/status?job_id={job_id}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    start = time.time()
    poll_interval = 0.5

    while time.time() - start < total_timeout:
        # Sleep exactly once per loop iteration
        time.sleep(poll_interval)
        if poll_interval < 2:
            poll_interval += 0.25

        try:
            req = urllib.request.Request(poll_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=9) as resp:
                data = json.loads(resp.read().decode("utf-8"))

                # Broaden the status check to prevent returning early on intermediate states
                if data.get("status") in ["processing", "queued", "pending", "starting"]:
                    continue
                return data

        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue  # Not ready yet
            if e.code == 429:
                log_verbose("Poll rate limited (429), backing off", _PROXY_NAME)
                # Removed time.sleep() here to prevent the double-sleep bug.
                # The sleep at the top of the loop will handle the delay.
                # Optionally increase backoff limit to 5 seconds if heavily rate limited:
                poll_interval = min(poll_interval + 1, 5)
                continue
            raise

        except urllib.error.URLError as e:
            # Catch standard network/socket timeouts so the script doesn't crash
            log_verbose(f"Poll network timeout ({e.reason}), retrying...", _PROXY_NAME)
            continue

        except (TimeoutError, OSError) as e:
            # socket.timeout during resp.read() isn't wrapped by URLError
            log_verbose(f"Poll read timeout ({e}), retrying...", _PROXY_NAME)
            continue

    return {"error": True, "message": "Generation timed out while polling"}


def _proxy_request(method, url, data=None, api_key="", timeout=None):
    """Make authenticated request to  proxy."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    body = json.dumps(data).encode("utf-8") if data else (b"" if method == "POST" else None)
    max_retries = 5

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or _REQUEST_TIMEOUT) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if resp.status == 202 and "job_id" in resp_data:
                    return _poll_job(resp_data["job_id"], api_key, timeout or _REQUEST_TIMEOUT)
                return resp_data

        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < max_retries:
                    # Exponential backoff: 2, 4, 8, 16, 32 seconds (Total 62s)
                    delay = 2 ** (attempt + 1)
                    log_verbose(f"Rate limited (429), retry {attempt + 1}/{max_retries} in {delay}s", _PROXY_NAME)
                    try:
                        e.read()  # Consume the body
                    except Exception:
                        pass
                    time.sleep(delay)
                    continue
                else:
                    # Capture the 429 error properly if all retries are exhausted
                    try:
                        error_body = json.loads(e.read().decode("utf-8"))
                        msg = error_body.get("message", f"HTTP 429 (Retries Exhausted)")
                    except Exception:
                        msg = "HTTP 429: Rate limit exceeded and retries exhausted."
                    return {"error": True, "status": 429, "message": msg}

            # Handle other HTTP errors
            try:
                error_body = json.loads(e.read().decode("utf-8"))
                msg = error_body.get("message", f"HTTP {e.code}")
            except Exception:
                msg = f"HTTP {e.code}"

            log_verbose(f"Proxy error {e.code}: {msg}", _PROXY_NAME)
            return {"error": True, "status": e.code, "message": msg}

        except urllib.error.URLError as e:
            log_verbose(f"Proxy network error: {e.reason}", _PROXY_NAME)
            return {"error": True, "message": str(e.reason)}
        except Exception as e:
            log_verbose(f"Proxy request failed: {e}", _PROXY_NAME)
            return {"error": True, "message": str(e)}


def _download_image_to_pil(url, prefix="proxy"):
    """Download image from URL, return PIL Image."""
    try:
        from PIL import Image
    except ImportError:
        from ..dependencies import ensure_pil
        Image = ensure_pil()

    from ..utils import register_temp_file, unique_temp_path

    temp_path = register_temp_file(unique_temp_path(prefix=prefix))
    try:
        urllib.request.urlretrieve(url, temp_path)
        img = Image.open(temp_path)
        img.load()
        return img
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# =============================================================================
# IMAGE HELPERS
# =============================================================================

def _prepare_images_b64(image_paths):
    """Convert to PNG. Single image: full resolution. Multiple: max 1536 px."""
    if not image_paths:
        return []

    try:
        from PIL import Image
    except ImportError:
        return []

    resize = len(image_paths) > 1
    result = []
    for path in image_paths:
        if not os.path.exists(path):
            continue
        try:
            img = Image.open(path)
            if resize:
                w, h = img.size
                if max(w, h) > 1536:
                    ratio = 1536 / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            result.append(f"data:image/png;base64,{b64}")
        except Exception as e:
            log_verbose(f"Failed to encode {path}: {e}", f"{_PROXY_NAME}")
    return result


def _images_from_response(result):
    """Extract PIL Images from proxy response.

    Handles two formats:
      - image_urls: list of URLs (from Fal/Replicate)
      - images: list of {mime_type, data} base64 (from Google)
    """
    pil_images = []

    # Format 1: URLs (Fal, Replicate)
    for url in (result.get("image_urls") or []):
        img = _download_image_to_pil(url, prefix=f"{_PROXY_NAME}")
        if img:
            pil_images.append(img)

    # Format 2: Inline base64 (Google)
    try:
        from PIL import Image as PILImage
    except ImportError:
        PILImage = None

    for img_data in (result.get("images") or []):
        try:
            if PILImage is None:
                raise ImportError("PIL not available")

            # Extract base64 string whether it's a Data URI string or a dictionary
            if isinstance(img_data, str):
                b64_str = img_data.split(",", 1)[-1] if "," in img_data else img_data
            else:
                b64_str = img_data.get("data", "")

            raw = base64.b64decode(b64_str)
            img = PILImage.open(io.BytesIO(raw))
            img.load()
            pil_images.append(img)
        except Exception as e:
            print(f"[PROXY] Failed to decode inline image: {e}")
            log_verbose(f"Failed to decode inline image: {e} "
                        f"(type={type(img_data).__name__}, "
                        f"len={len(img_data) if isinstance(img_data, (str, bytes)) else '?'})",
                        f"{_PROXY_NAME}")

    return pil_images


# =============================================================================
# PUBLIC API — Called from api.py
# =============================================================================

def validate_key(api_key):
    """
    Validate  key against proxy server.

    Returns:
        (True, user_id, balance) on success
        (False, error_message, None) on failure
    """
    result = _proxy_request("POST", _EP_VALIDATE, api_key=api_key, timeout=15)

    if result.get("error"):
        return (False, result.get("message", "Validation failed"), None)

    if result.get("valid"):
        return (True, result.get("user_id", ""), result.get("balance", 0.0))

    return (False, "Invalid key", None)


def check_balance(api_key):
    """
    Get current balance and usage for  key.

    Returns:
        dict with {balance, usage_today, usage_month, ...} or None on error
    """
    result = _proxy_request("GET", _EP_BALANCE, api_key=api_key, timeout=15)

    if result.get("error"):
        log_verbose(f"Balance check failed: {result.get('message')}", f"{_PROXY_NAME}")
        return None

    return result


def fetch_models(api_key=""):
    """
    Fetch available models from  proxy.

    Returns:
        list of dicts: [{id, cost, cost_4k, enabled, provider, type}, ...] or []
    """
    url = _PROXY_BASE.rsplit("/proxy", 1)[0] + "/proxy/models"
    result = _proxy_request("GET", url, api_key=api_key, timeout=15)

    if result and not result.get("error") and "models" in result:
        return result["models"]

    log_verbose(f"Model list fetch failed: {result}", f"{_PROXY_NAME}")
    return []


def generate_image(model_id, prompt, image_paths=None, num_outputs=1,
                   params=None, neurotoken_key="", timeout=360):
    """
    Generate images via  proxy.

    Args:
        model_id: Model identifier (e.g. "nano-banana-google", "gpt-image-1.5-fal")
        prompt: Generation prompt
        image_paths: Optional list of input image paths
        num_outputs: Number of outputs (currently 1 per request via proxy)
        params: Model-specific parameters dict
        neurotoken_key: The  API key
        timeout: Request timeout

    Returns:
        List of PIL Image objects
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    images_b64 = _prepare_images_b64(image_paths)
    params = dict(params) if params else {}

    # Clean params — remove values that shouldn't be sent
    clean_params = {}
    skip_values = {"match_input_image", "1K", "auto"}
    for k, v in params.items():
        if v not in skip_values:
            clean_params[k] = v

    payload = {
        "model_id": model_id,
        "prompt": prompt,
        "images": images_b64 if images_b64 else None,
        "params": clean_params,
        "num_outputs": num_outputs,
    }

    log_verbose(f"Proxy generate: {model_id}", f"{_PROXY_NAME}")
    result = _proxy_request("POST", _EP_GENERATE, data=payload,
                            api_key=neurotoken_key, timeout=timeout)

    if result.get("error"):
        msg = result.get("message", "Generation failed")
        status = _extract_status(result)
        # Surface specific error types
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        elif status == 402:
            raise ValueError(f"Insufficient balance: {msg}")
        elif status == 429:
            raise ValueError(f"Rate limit: {msg}")
        else:
            raise RuntimeError(f"Proxy error: {msg}")

    # Log balance info
    balance = result.get("balance")
    cost = result.get("cost")
    if balance is not None:
        log_verbose(f"Cost: ${cost:.4f}, Balance: ${balance:.4f}", f"{_PROXY_NAME}")

    # Extract images
    pil_images = _images_from_response(result)

    if not pil_images:
        # Debug: show what the response actually contained
        keys = list(result.keys())
        has_urls = bool(result.get("image_urls"))
        has_imgs = bool(result.get("images"))
        raise RuntimeError(
            f"Proxy returned no images (keys={keys}, "
            f"image_urls={has_urls}, images={has_imgs})"
        )

    return pil_images


def generate_text(model_id, prompt, image_paths=None, params=None,
                  neurotoken_key="", timeout=120):
    """
    Generate text via  proxy.

    Args:
        model_id: Model identifier
        prompt: The text prompt
        image_paths: Optional input images
        params: Model-specific params (thinking_level, etc.)
        neurotoken_key: The  API key
        timeout: Request timeout

    Returns:
        Generated text string
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    images_b64 = _prepare_images_b64(image_paths)
    params = dict(params) if params else {}

    payload = {
        "model_id": model_id,
        "prompt": prompt,
        "images": images_b64 if images_b64 else None,
        "params": params,
    }

    log_verbose(f"Proxy text gen: {model_id}", f"{_PROXY_NAME}")
    result = _proxy_request("POST", _EP_GENERATE, data=payload,
                            api_key=neurotoken_key, timeout=timeout)

    if result.get("error"):
        msg = result.get("message", "Generation failed")
        status = _extract_status(result)
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        elif status == 402:
            raise ValueError(f"Insufficient balance: {msg}")
        elif status == 429:
            raise ValueError(f"Rate limit: {msg}")
        else:
            raise RuntimeError(f"Proxy error: {msg}")

    # Log balance
    balance = result.get("balance")
    cost = result.get("cost")
    if balance is not None:
        log_verbose(f"Cost: ${cost:.4f}, Balance: ${balance:.4f}", f"{_PROXY_NAME}")

    text = result.get("text", "")
    if not text:
        raise RuntimeError("Proxy returned no text")

    return text


def remove_background(image_path, neurotoken_key="", timeout=120):
    """
    Remove background via  proxy (fal-ai/birefnet).

    Args:
        image_path: Path to input image
        neurotoken_key: The  API key
        timeout: Request timeout

    Returns:
        Path to output image with background removed, or None on failure
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    images_b64 = _prepare_images_b64([image_path])
    if not images_b64:
        raise ValueError("Failed to encode input image")

    payload = {
        "model_id": "birefnet-fal",
        "prompt": "",
        "images": images_b64,
        "params": {},
    }

    log_verbose("Proxy bg removal: birefnet-fal", f"{_PROXY_NAME}")
    result = _proxy_request("POST", _EP_GENERATE, data=payload,
                            api_key=neurotoken_key, timeout=timeout)

    if result.get("error"):
        msg = result.get("message", "BG removal failed")
        status = _extract_status(result)
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        elif status == 402:
            raise ValueError(f"Insufficient balance: {msg}")
        else:
            raise RuntimeError(f"Proxy error: {msg}")

    # Log balance
    balance = result.get("balance")
    cost = result.get("cost")
    if balance is not None:
        log_verbose(f"Cost: ${cost:.4f}, Balance: ${balance:.4f}", f"{_PROXY_NAME}")

    # Download result image to temp file
    image_urls = result.get("image_urls", [])
    if not image_urls:
        raise RuntimeError("Proxy returned no image for BG removal")

    from ..utils import register_temp_file, unique_temp_path
    output_path = register_temp_file(unique_temp_path(prefix="nobg_proxy"))
    urllib.request.urlretrieve(image_urls[0], output_path)
    return output_path


# =============================================================================
# TRIPO 3D PROXY — Called from api_tripo.py (NT mode)
# =============================================================================

def proxy_tripo_upload(image_path, neurotoken_key=""):
    """
    Upload image to Tripo via NT proxy (for image-to-3D and multiview).

    Returns:
        file_token string on success
    Raises:
        ValueError / RuntimeError on failure
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    images_b64 = _prepare_images_b64([image_path])
    if not images_b64:
        raise ValueError(f"Failed to encode image: {image_path}")

    payload = {"image": images_b64[0]}
    log_verbose(f"Proxy Tripo upload: {os.path.basename(image_path)}", f"{_PROXY_NAME}")
    result = _proxy_request("POST", _EP_TRIPO_UPLOAD, data=payload,
                            api_key=neurotoken_key, timeout=60)

    if result.get("error"):
        msg = result.get("message", "Upload failed")
        status = result.get("status", 500)
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        elif status == 402:
            raise ValueError(f"Insufficient balance: {msg}")
        else:
            raise RuntimeError(f"Tripo upload error: {msg}")

    file_token = result.get("file_token")
    if not file_token:
        raise RuntimeError("Tripo upload returned no file_token")
    return file_token


def proxy_tripo_task(mode, params, neurotoken_key=""):
    """
    Create a Tripo 3D generation task via NT proxy.

    Args:
        mode: "text_to_model" | "image_to_model" | "multiview_to_model"
        params: dict — mode-specific params (prompt, file_token, etc.)
        neurotoken_key: The  API key

    Returns:
        dict with {task_id, cost, balance}
    Raises:
        ValueError / RuntimeError on failure
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    payload = {"mode": mode, "params": params}
    log_verbose(f"Proxy Tripo task: {mode}", f"{_PROXY_NAME}")
    result = _proxy_request("POST", _EP_TRIPO_TASK, data=payload,
                            api_key=neurotoken_key, timeout=30)

    if result.get("error"):
        msg = result.get("message", "Task creation failed")
        status = result.get("status", 500)
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        elif status == 402:
            raise ValueError(f"Insufficient balance: {msg}")
        elif status == 429:
            raise ValueError(f"Tripo daily limit reached: {msg}")
        else:
            raise RuntimeError(f"Tripo task error: {msg}")

    task_id = result.get("task_id")
    if not task_id:
        raise RuntimeError("Tripo task returned no task_id")

    balance = result.get("balance")
    cost = result.get("cost")
    if balance is not None:
        log_verbose(f"Tripo cost: ${cost:.4f}, Balance: ${balance:.4f}", f"{_PROXY_NAME}")

    return result


def proxy_tripo_poll(task_id, neurotoken_key=""):
    """
    Poll Tripo task status via NT proxy.

    Returns:
        dict with {status, progress, download_url} or similar
    Raises:
        ValueError / RuntimeError on failure
    """
    if not neurotoken_key:
        raise ValueError(f"{_PROXY_BASE} key is required")

    url = f"{_EP_TRIPO_TASK}/{task_id}"
    result = _proxy_request("GET", url, api_key=neurotoken_key, timeout=30)

    if result.get("error"):
        msg = result.get("message", "Poll failed")
        status = result.get("status", 500)
        if status == 401:
            raise ValueError(f"{_PROXY_BASE} auth failed: {msg}")
        else:
            raise RuntimeError(f"Tripo poll error: {msg}")

    return result


def proxy_tripo_balance(neurotoken_key=""):
    """
    Get Tripo daily usage/limit from NT proxy.

    Returns:
        dict with {daily_limit, usage_today, available} or None on error
    """
    if not neurotoken_key:
        return None

    result = _proxy_request("GET", _EP_TRIPO_BALANCE, api_key=neurotoken_key, timeout=15)

    if result.get("error"):
        log_verbose(f"Tripo balance check failed: {result.get('message')}", f"{_PROXY_NAME}")
        return None

    return result