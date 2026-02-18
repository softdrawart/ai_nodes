# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Tripo 3D API Integration

Wrapper around the official tripo3d SDK for 3D mesh generation.
Includes Windows-specific threading fixes and retry logic.
"""

import os
import asyncio
import tempfile
import sys
import time
from typing import Optional, List, Callable
from dataclasses import dataclass

# =============================================================================
# TRIPO SDK AVAILABILITY
# =============================================================================

TRIPO_AVAILABLE = False
TripoClient = None
TripoAPIError = None
TaskStatus = None


def init_tripo():
    """Initialize Tripo SDK. Call after dependencies are installed."""
    global TRIPO_AVAILABLE, TripoClient, TripoAPIError, TaskStatus
    try:
        from tripo3d import TripoClient as TC, TripoAPIError as TAE, TaskStatus as TS
        TripoClient = TC
        TripoAPIError = TAE
        TaskStatus = TS
        TRIPO_AVAILABLE = True
        return True
    except ImportError:
        TRIPO_AVAILABLE = False
        return False


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TripoResult:
    task_id: str
    status: str
    model_path: Optional[str] = None
    rendered_image_path: Optional[str] = None
    progress: int = 0
    error_message: Optional[str] = None


# =============================================================================
# CONFIGURATION
# =============================================================================

TRIPO_MODEL_VERSION = "v3.0-20250812"
SMART_LOWPOLY_VERSION = "P-v2.0-20251225"

DEFAULT_SETTINGS = {
    "model_version": TRIPO_MODEL_VERSION,
    "texture": True,
    "pbr": True,
    "texture_quality": "standard",
    "geometry_quality": "standard",
    "auto_size": False,
    "quad": False,
    "face_limit": None,
    "style": None,
    "orientation": "default",
}

DEFAULT_LOWPOLY_SETTINGS = {
    "model_version": SMART_LOWPOLY_VERSION,
    "quad": False,
    "face_limit": 4000,
    "bake": True,
}


# =============================================================================
# ASYNC UTILS (WINDOWS FIX)
# =============================================================================

def run_async(coro):
    """Run async coroutine safely, handling Windows loop policies."""

    # FIX: Windows Selector Policy prevents WinError 10053/10054 in threads
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass  # Policy might already be set

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return loop.run_until_complete(coro)


async def _execute_with_retry(func, *args, progress_callback=None, **kwargs):
    """Executes API call with aggressive retry logic."""
    max_retries = 3
    last_exception = None

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            # Retry on Network errors OR Server 500 errors
            is_network = "connection" in error_str or "winerror" in error_str or "client" in error_str
            is_server = "500" in error_str or "502" in error_str or "503" in error_str or "json" in error_str

            if is_network or is_server:
                last_exception = e
                wait_time = (attempt + 1) * 2
                if progress_callback:
                    progress_callback(2, f"Retrying connection ({attempt + 1}/{max_retries})...")
                print(f"[Tripo] Retry {attempt + 1} due to: {e}")
                await asyncio.sleep(wait_time)
            else:
                raise e

    raise last_exception or RuntimeError("Operation failed after retries")


def validate_image(path):
    """Ensure image is valid before sending to avoid 500 errors."""
    if not path: return False
    if not os.path.exists(path): return False
    if os.path.getsize(path) == 0: return False  # Empty files crash servers
    return True


# =============================================================================
# MAIN API FUNCTIONS - GENERATION
# =============================================================================

def generate_multiview_to_model(
        api_key: str,
        image_paths: List[Optional[str]],
        progress_callback: Optional[Callable[[int, str], None]] = None,
        **settings
) -> TripoResult:
    if not TRIPO_AVAILABLE: raise RuntimeError("Tripo SDK not available")

    # Clean paths
    clean_paths = [p for p in image_paths if validate_image(p)]

    if not clean_paths:
        raise FileNotFoundError("No valid images found (check file paths/sizes)")

    merged = {**DEFAULT_SETTINGS, **settings}

    async def _generate():
        async with TripoClient(api_key=api_key) as client:

            async def do_upload():
                if progress_callback: progress_callback(5, "Uploading images...")
                return await client.multiview_to_model(
                    images=clean_paths,
                    model_version=merged["model_version"],
                    face_limit=merged["face_limit"],
                    texture=merged["texture"],
                    pbr=merged["pbr"],
                    texture_quality=merged["texture_quality"],
                    auto_size=merged["auto_size"],
                    quad=merged["quad"],
                )

            task_id = await _execute_with_retry(do_upload, progress_callback=progress_callback)
            if progress_callback: progress_callback(10, f"Processing: {task_id}")
            return await _poll_task(client, task_id, progress_callback)

    return run_async(_generate())


def generate_image_to_model(api_key: str, image_path: str, progress_callback=None, **settings):
    if not TRIPO_AVAILABLE: raise RuntimeError("Tripo SDK not available")
    if not validate_image(image_path): raise FileNotFoundError(f"Invalid image: {image_path}")

    merged = {**DEFAULT_SETTINGS, **settings}

    async def _generate():
        async with TripoClient(api_key=api_key) as client:
            async def do_upload():
                if progress_callback: progress_callback(5, "Uploading image...")
                return await client.image_to_model(
                    image=image_path,
                    model_version=merged["model_version"],
                    face_limit=merged["face_limit"],
                    texture=merged["texture"],
                    pbr=merged["pbr"],
                    texture_quality=merged["texture_quality"],
                    auto_size=merged["auto_size"],
                    quad=merged["quad"],
                )

            task_id = await _execute_with_retry(do_upload, progress_callback=progress_callback)
            return await _poll_task(client, task_id, progress_callback)

    return run_async(_generate())


def generate_text_to_model(api_key: str, prompt: str, negative_prompt="", progress_callback=None, **settings):
    if not TRIPO_AVAILABLE: raise RuntimeError("Tripo SDK not available")
    merged = {**DEFAULT_SETTINGS, **settings}

    async def _generate():
        async with TripoClient(api_key=api_key) as client:
            async def do_req():
                return await client.text_to_model(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    model_version=merged["model_version"],
                    face_limit=merged["face_limit"],
                    texture=merged["texture"],
                    pbr=merged["pbr"],
                    texture_quality=merged["texture_quality"],
                    geometry_quality=merged["geometry_quality"],
                    style=merged["style"],
                    auto_size=merged["auto_size"],
                    quad=merged["quad"],
                )

            task_id = await _execute_with_retry(do_req, progress_callback=progress_callback)
            return await _poll_task(client, task_id, progress_callback)

    return run_async(_generate())


# =============================================================================
# EDITING API FUNCTIONS - SMART LOWPOLY
# =============================================================================

def smart_lowpoly(
        api_key: str,
        original_task_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        **settings
) -> TripoResult:
    """
    Perform Smart LowPoly retopology on a generated model.

    Args:
        api_key: Tripo API key
        original_task_id: Task ID from a previous generation
        progress_callback: Optional callback for progress updates
        **settings: Override defaults (model_version, quad, face_limit, bake)

    Returns:
        TripoResult with retopologized model path
    """
    if not TRIPO_AVAILABLE:
        raise RuntimeError("Tripo SDK not available")

    merged = {**DEFAULT_LOWPOLY_SETTINGS, **settings}

    async def _retopo():
        async with TripoClient(api_key=api_key) as client:
            async def do_request():
                if progress_callback:
                    progress_callback(5, "Starting Smart LowPoly...")
                return await client.smart_lowpoly(
                    original_model_task_id=original_task_id,
                    model_version=merged["model_version"],
                    quad=merged["quad"],
                    face_limit=merged["face_limit"],
                    bake=merged["bake"],
                )

            task_id = await _execute_with_retry(do_request, progress_callback=progress_callback)
            if progress_callback:
                progress_callback(10, f"Retopologizing: {task_id}")
            return await _poll_task(client, task_id, progress_callback)

    return run_async(_retopo())


# =============================================================================
# TASK POLLING
# =============================================================================

async def _poll_task(client, task_id: str, progress_callback=None) -> TripoResult:
    """Poll task status with real progress updates."""
    polling_interval = 2.0
    max_wait_time = 600  # 10 minutes max
    elapsed = 0

    if progress_callback:
        progress_callback(10, f"Processing: {task_id[:8]}...")

    # Check if client has get_task method for manual polling
    has_get_task = hasattr(client, 'get_task') and callable(getattr(client, 'get_task'))

    try:
        if not has_get_task:
            # Fallback to wait_for_task (no progress updates)
            print("[Tripo] Using wait_for_task (no progress updates)")
            task = await client.wait_for_task(task_id, polling_interval=5.0)
        else:
            # Manual polling with progress updates
            while elapsed < max_wait_time:
                try:
                    task = await client.get_task(task_id)
                except Exception as e:
                    print(f"[Tripo] get_task error: {e}, retrying...")
                    await asyncio.sleep(polling_interval)
                    elapsed += polling_interval
                    continue

                # Check status
                status_str = str(task.status).upper() if task.status else ""

                if task.status == TaskStatus.SUCCESS or "SUCCESS" in status_str:
                    break
                elif task.status == TaskStatus.FAILED or "FAILED" in status_str:
                    return TripoResult(task_id, "failed", error_message="Task failed on server")
                elif "CANCELLED" in status_str or "BANNED" in status_str:
                    return TripoResult(task_id, "failed", error_message=f"Task {status_str}")

                # Update progress from task (if available)
                if progress_callback:
                    task_progress = getattr(task, 'progress', None)
                    if task_progress is not None and isinstance(task_progress, (int, float)):
                        # Map 0-100 to 10-85 range (leave room for download)
                        display_progress = 10 + int(float(task_progress) * 0.75)
                        status_text = f"Processing: {int(task_progress)}%"
                    else:
                        # Fallback: estimate based on elapsed time
                        display_progress = min(10 + int(elapsed / 4), 80)
                        status_text = "Processing..."

                    progress_callback(display_progress, status_text)

                await asyncio.sleep(polling_interval)
                elapsed += polling_interval

            # Check if we timed out
            if elapsed >= max_wait_time:
                return TripoResult(task_id, "failed", error_message="Timeout waiting for task")

        # Task succeeded - download
        if progress_callback:
            progress_callback(90, "Downloading model...")

        output_dir = tempfile.gettempdir()

        # Retry download on failure
        result = await _execute_with_retry(
            client.download_task_models,
            task=task,
            output_dir=output_dir,
            progress_callback=progress_callback
        )

        model_path = next((p for p in result.values() if p), None)
        print(f"[Tripo] Task {task_id} complete. Model path: {model_path}")

        if progress_callback:
            progress_callback(100, "Complete!")

        return TripoResult(task_id, "success", model_path=model_path, progress=100)

    except Exception as e:
        print(f"[Tripo] Task {task_id} error: {e}")
        return TripoResult(task_id, "error", error_message=str(e))


# =============================================================================
# BLENDER IMPORT
# =============================================================================

def import_glb_to_blender(model_path: str, name_prefix: str = "Tripo"):
    """Import 3D model into Blender (supports glb, gltf, fbx, obj, stl)."""
    import bpy

    # Validate path
    if not model_path:
        print("[Tripo] Import failed: model_path is empty")
        return []

    if not os.path.exists(model_path):
        print(f"[Tripo] Import failed: file not found: {model_path}")
        return []

    file_size = os.path.getsize(model_path)
    if file_size == 0:
        print(f"[Tripo] Import failed: file is empty: {model_path}")
        return []

    print(f"[Tripo] Importing: {model_path} ({file_size} bytes)")

    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

    bpy.ops.object.select_all(action='DESELECT')

    # Detect file format and use appropriate importer
    ext = os.path.splitext(model_path)[1].lower()

    try:
        if ext in ['.glb', '.gltf']:
            bpy.ops.import_scene.gltf(filepath=model_path, merge_vertices=True)
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=model_path)
        elif ext == '.obj':
            # Blender 4.0+ uses different OBJ importer
            if bpy.app.version >= (4, 0, 0):
                bpy.ops.wm.obj_import(filepath=model_path)
            else:
                bpy.ops.import_scene.obj(filepath=model_path)
        elif ext == '.stl':
            bpy.ops.import_mesh.stl(filepath=model_path)
        else:
            # Try GLTF as fallback
            print(f"[Tripo] Unknown format '{ext}', trying GLTF importer...")
            bpy.ops.import_scene.gltf(filepath=model_path, merge_vertices=True)
    except Exception as e:
        print(f"[Tripo] {ext.upper()} import failed: {e}")
        # Try alternative importers as fallback
        if ext == '.fbx':
            try:
                print("[Tripo] Trying GLTF importer as fallback...")
                bpy.ops.import_scene.gltf(filepath=model_path, merge_vertices=True)
            except Exception as e2:
                print(f"[Tripo] GLTF fallback also failed: {e2}")
                return []
        else:
            return []

    new_objects = [o for o in bpy.context.selected_objects]
    for obj in new_objects:
        obj.name = f"{name_prefix}_{obj.name}"
        obj.rotation_euler[0] += 1.5708
        obj.select_set(True)

    if new_objects:
        bpy.context.view_layer.objects.active = new_objects[0]
        print(f"[Tripo] Imported {len(new_objects)} object(s): {[o.name for o in new_objects]}")
    else:
        print("[Tripo] Import completed but no objects were created")

    return new_objects