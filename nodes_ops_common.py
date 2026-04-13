# -*- coding: utf-8 -*-
import os
import time
import threading
import bpy

from .utils import (
    get_generations_folder, get_unique_filename,
    log_verbose, cancel_event, get_api_keys
)

# Status tracking
try:
    from . import status_manager
    HAS_STATUS = True
except ImportError:
    HAS_STATUS = False

# =============================================================================
# LOGGING & DEBUG HELPERS
# =============================================================================

def log_node_generation(node_type, model_id, prompt, input_images=None, params=None, provider=None):
    """Log detailed node generation info for debugging"""
    log_verbose(f"[{node_type}]: {model_id} - START", "Node Gen")
    if provider:
        log_verbose(f"Provider: {provider}", "Node Gen")
    log_verbose(f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}", "Node Gen")
    if input_images:
        log_verbose(f"Input Images: {len(input_images)} file(s)", "Node Gen")
        for i, img in enumerate(input_images):
            log_verbose(f"  [{i + 1}] {os.path.basename(img)}", "Node Gen")
    if params:
        log_verbose(f"Parameters: {params}", "Node Gen")


def log_node_result(node_type, model_id, success, result_path=None, error=None, duration=None):
    """Log node generation result"""
    status = "SUCCESS" if success else "FAILED"
    log_verbose(f"[{node_type}]: {model_id} - {status}", "Node Gen")
    if result_path:
        log_verbose(f"  Output: {os.path.basename(result_path)}", "Node Gen")
    if error:
        log_verbose(f"  Error: {error}", "Node Gen")
    if duration:
        log_verbose(f"  Duration: {duration:.2f}s", "Node Gen")


# =============================================================================
# WORKER HELPERS
# =============================================================================

def run_node_worker(ntree_name, node_name, work_func, on_complete, log_type=None, model_id=""):
    """
    Run async work in background thread with automatic node update.

    Reduces boilerplate for threaded node operations.

    Args:
        ntree_name: Node tree name (str)
        node_name: Node name (str)
        work_func: Callable() -> result (any). Raises exception on error.
        on_complete: Callable(node, result, error_msg, duration) -> None
                     Called in main thread to update node state.
        log_type: Optional log category name for verbose logging
        model_id: Model identifier for status tracking
    """
    # Start background timer for UI updates
    from .nodes_core import start_background_timer
    start_background_timer()

    # Add to status queue
    job_id = None
    if HAS_STATUS:
        job_id = status_manager.add_job(node_name, model_id or log_type or "Unknown", log_type or "Operation")
        status_manager.start_job(job_id)

    def worker():
        result = None
        error_msg = None
        start_time = time.time()

        try:
            cancel_event.clear()
            result = work_func()
        except Exception as e:
            if not cancel_event.is_set():
                error_msg = str(e)
                print(f"[{log_type or 'Worker'}] Error: {e}")

        duration = time.time() - start_time

        # Log result if type specified
        if log_type:
            log_node_result(log_type, result is not None and not cancel_event.is_set(),
                            result if isinstance(result, str) else None,
                            error_msg, duration)

        # Update job status
        if HAS_STATUS and job_id:
            if cancel_event.is_set():
                status_manager.cancel_job(job_id)
            elif result is not None and error_msg is None:
                status_manager.complete_job(job_id, success=True)
            else:
                status_manager.complete_job(job_id, success=False, error=error_msg)

        def update():
            tree = bpy.data.node_groups.get(ntree_name)
            if tree:
                node = tree.nodes.get(node_name)
                if node:
                    if cancel_event.is_set():
                        if hasattr(node, 'is_processing'):
                            node.is_processing = False
                        if hasattr(node, 'is_generating'):
                            node.is_generating = False
                        if hasattr(node, 'status_message'):
                            node.status_message = "Cancelled"
                    else:
                        on_complete(node, result, error_msg, duration)
                        # === PERF: Invalidate file cache after result_path may have changed ===
                        from .nodes_core import NeuroNodeBase
                        rp = getattr(node, 'result_path', '')
                        if rp:
                            NeuroNodeBase.invalidate_file_cache(rp)
            return None

        bpy.app.timers.register(update, first_interval=0.1)

    threading.Thread(target=worker, daemon=True).start()


def save_generation_result(image, folder_type, prefix):
    """Save PIL image to generations folder, returns path or None"""
    if not image:
        return None
    gen_dir = get_generations_folder(folder_type)
    filename = get_unique_filename(gen_dir, prefix)
    result_path = os.path.join(gen_dir, filename)
    image.save(result_path, format="PNG")
    return result_path


def get_node_tree(context, tree_name_prop):
    """Helper to safely get the node tree from property or context"""
    # 1. Try to get specific tree by name (Batch Mode)
    if tree_name_prop:
        tree = bpy.data.node_groups.get(tree_name_prop)
        if tree:
            return tree

    # 2. Try to get from active context (UI Mode)
    if context.space_data and hasattr(context.space_data, 'node_tree'):
        return context.space_data.node_tree

    return None


def get_artist_tool_model(context, tool_type):
    from .model_registry import resolve_model
    canonical_map = {
        'text': 'text-gemini-pro',
        'nano': 'nano-banana-mini',
        'pro':  'nano-banana-pro',
    }
    canonical = canonical_map.get(tool_type, 'nano-banana-pro')
    return resolve_model(canonical, context=context)