# =============================================================================
# STATUS MANAGER - Generation Queue, Error Log, Status Bar
# =============================================================================
# Professional status tracking
# =============================================================================

import bpy
import traceback  # Added for debug
from bpy.props import StringProperty, IntProperty, BoolProperty, CollectionProperty
from bpy.types import PropertyGroup
from collections import deque
from datetime import datetime
import threading
import json

# =============================================================================
# GLOBALS
# =============================================================================

_lock = threading.Lock()

# Job queue - list of dicts with job info
_job_queue = []  # [{id, node_name, model, status, start_time, error}, ...]
_job_counter = 0

# Error log - circular buffer
_error_log = deque(maxlen=50)

# Current status
_current_status = {
    "running": 0,
    "queued": 0,
    "completed_session": 0,
    "failed_session": 0,
    "last_model": "",
    "last_error": "",
}

# Flag to trigger redraw (checked by timer)
_needs_redraw = False


# =============================================================================
# JOB QUEUE API
# =============================================================================

def add_job(node_name: str, model: str, node_type: str = "Generate") -> int:
    """Add a job to the queue. Returns job ID."""
    global _job_counter, _needs_redraw
    with _lock:
        _job_counter += 1
        job = {
            "id": _job_counter,
            "node_name": node_name,
            "node_type": node_type,
            "model": model,
            "status": "queued",  # queued, running, completed, failed, cancelled
            "start_time": datetime.now(),
            "end_time": None,
            "error": None,
        }
        _job_queue.append(job)
        _current_status["queued"] += 1
        _needs_redraw = True
        return _job_counter


def start_job(job_id: int):
    """Mark job as running."""
    global _needs_redraw
    with _lock:
        for job in _job_queue:
            if job["id"] == job_id:
                job["status"] = "running"
                job["start_time"] = datetime.now()
                _current_status["queued"] = max(0, _current_status["queued"] - 1)
                _current_status["running"] += 1
                _current_status["last_model"] = job["model"]
                _needs_redraw = True
                break


def complete_job(job_id: int, success: bool = True, error: str = None):
    """Mark job as completed or failed."""
    global _needs_redraw
    node_name = ""
    model = ""

    with _lock:
        for job in _job_queue:
            if job["id"] == job_id:
                job["end_time"] = datetime.now()
                node_name = job.get("node_name", "")
                model = job.get("model", "")
                if success:
                    job["status"] = "completed"
                    _current_status["completed_session"] += 1
                else:
                    job["status"] = "failed"
                    job["error"] = error
                    _current_status["failed_session"] += 1
                    _current_status["last_error"] = (error or "Unknown error")[:100]
                _current_status["running"] = max(0, _current_status["running"] - 1)
                _needs_redraw = True
                break

    # Add error outside of lock to avoid potential deadlock
    if not success and error:
        add_error(error, node_name, model)


def cancel_job(job_id: int):
    """Mark job as cancelled."""
    global _needs_redraw
    with _lock:
        for job in _job_queue:
            if job["id"] == job_id:
                old_status = job["status"]
                job["status"] = "cancelled"
                job["end_time"] = datetime.now()
                if old_status == "running":
                    _current_status["running"] = max(0, _current_status["running"] - 1)
                elif old_status == "queued":
                    _current_status["queued"] = max(0, _current_status["queued"] - 1)
                _needs_redraw = True
                break


def get_running_jobs():
    """Get list of currently running jobs."""
    with _lock:
        return [j for j in _job_queue if j["status"] == "running"]


def get_queued_jobs():
    """Get list of queued jobs."""
    with _lock:
        return [j for j in _job_queue if j["status"] == "queued"]


def get_recent_jobs(count: int = 10):
    """Get most recent jobs."""
    with _lock:
        return list(reversed(_job_queue[-count:]))


def get_status():
    """Get current status dict."""
    with _lock:
        return dict(_current_status)


def clear_completed():
    """Clear completed/failed jobs from queue."""
    global _job_queue, _needs_redraw
    with _lock:
        _job_queue = [j for j in _job_queue if j["status"] in ("queued", "running")]
        _needs_redraw = True


# =============================================================================
# ERROR LOG API
# =============================================================================

def add_error(message: str, node_name: str = "", model: str = ""):
    """Add error to log."""
    global _needs_redraw
    with _lock:
        entry = {
            "time": datetime.now(),
            "message": (message or "Unknown error")[:200],  # Truncate long errors
            "node": node_name or "",
            "model": model or "",
        }
        _error_log.append(entry)
        _needs_redraw = True


def get_errors(count: int = 20):
    """Get recent errors."""
    with _lock:
        return list(reversed(list(_error_log)))[:count]


def clear_errors():
    """Clear error log."""
    global _needs_redraw
    with _lock:
        _error_log.clear()
        _current_status["last_error"] = ""
        _needs_redraw = True


def get_error_count():
    """Get total error count."""
    with _lock:
        return len(_error_log)


# =============================================================================
# STATUS BAR
# =============================================================================

_redraw_timer_running = False


def _trigger_redraw():
    """Schedule a UI redraw (called from main thread only)."""
    global _needs_redraw
    _needs_redraw = True


def _redraw_timer():
    """Timer callback to handle UI redraws safely from main thread."""
    global _needs_redraw, _redraw_timer_running

    if _needs_redraw:
        _needs_redraw = False
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    # Only redraw status bar to avoid UI freeze
                    if area.type == 'STATUSBAR':
                        area.tag_redraw()
        except Exception:
            pass

    # Keep timer running - check every 1 second
    return 1.0


def draw_status_bar(self, context):
    """Draw status in Blender's native status bar (Providers -> Queue -> Errors)."""
    # Use global context if local is missing/invalid
    ctx = context if context else bpy.context

    if not ctx or not hasattr(ctx, "scene"):
        # print("[Status Bar Debug] Invalid context or scene missing")
        return

    try:
        layout = self.layout
        row = layout.row(align=True)

        # --- PART 1: PROVIDER STATUS (First) ---
        try:
            prefs = None
            # Robust preference lookup
            for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
                if name and name in ctx.preferences.addons:
                    addon = ctx.preferences.addons[name]
                    if addon:
                        prefs = addon.preferences
                        break

            if prefs:
                scn = ctx.scene
                active_provider = getattr(prefs, 'active_provider', 'aiml')
                keys_checked = getattr(scn, 'neuro_keys_checked', False)

                # Map provider id → API key property name on prefs
                _KEY_PROPS = {
                    "aiml": "aiml_api_key",
                    "google": "gemini_api_key",
                    "replicate": "replicate_api_key",
                    "fal": "fal_api_key",
                }

                def draw_prov_icon(p_row, name, enabled_prop, status_attr, prov_id):
                    if not getattr(prefs, enabled_prop, False):
                        return

                    # Check if key exists in prefs (persists across files)
                    key_prop = _KEY_PROPS.get(prov_id, "")
                    has_key = bool(getattr(prefs, key_prop, "").strip()) if key_prop else False

                    if not has_key:
                        icon = 'QUESTION'  # No key entered at all
                    elif keys_checked:
                        # API verification ran — use verified result
                        status_val = getattr(scn, status_attr, False)
                        icon = 'CHECKMARK' if status_val else 'ERROR'
                    else:
                        # Key present but not yet verified
                        icon = 'CHECKMARK'

                    sub = p_row.row(align=True)
                    if active_provider == prov_id:
                        sub.alert = True
                    sub.label(text=name, icon=icon)
                    p_row.separator()

                draw_prov_icon(row, "AIML", "provider_aiml_enabled", "neuro_aiml_status", "aiml")
                draw_prov_icon(row, "Google", "provider_google_enabled", "neuro_google_status", "google")
                draw_prov_icon(row, "Rep", "provider_replicate_enabled", "neuro_replicate_status", "replicate")
                draw_prov_icon(row, "Fal", "provider_fal_enabled", "neuro_fal_status", "fal")

        except Exception as e:
            pass

        # Separator
        row.separator(factor=1.0)
        row.label(text="|")
        row.separator(factor=1.0)

        # --- PART 2: QUEUE STATUS (Second) ---
        try:
            status = get_status()
            running = status.get("running", 0)
            error_count = get_error_count()

            sub = row.row(align=True)
            if running > 0:
                sub.alert = True
                sub.label(text=f"[ Running: {running} ]")
            else:
                sub.label(text="[ Idle ]")
        except Exception as e:
            pass

        # --- PART 3: ERRORS (Last) ---
        try:
            if error_count > 0:
                row.separator(factor=1.0)
                sub = row.row(align=True)
                sub.alert = True
                sub.operator("neuro.show_errors_popup", text=f"Errors ({error_count})", icon='INFO')
        except Exception:
            pass


    except Exception as e:
        pass


# =============================================================================
# UI PANELS
# =============================================================================

class NEURO_PT_status_panel(bpy.types.Panel):
    """Status panel in Node Editor sidebar"""
    bl_label = "Status"
    bl_idname = "NEURO_PT_status_panel"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = PANELS_NAME
    bl_order = 0  # Show at top

    @classmethod
    def poll(cls, context):
        return (context.space_data and
                hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree')

    def draw(self, context):
        layout = self.layout
        status = get_status()

        # Current Activity
        running_jobs = get_running_jobs()
        queued_jobs = get_queued_jobs()

        if running_jobs or queued_jobs:
            box = layout.box()

            # Running
            for job in running_jobs:
                row = box.row(align=True)

                # Split row: Left (Icon + Name) | Right (Time)
                split = row.split(factor=0.75)

                # Left side
                left = split.row(align=True)
                left.label(text="", icon='RENDER_ANIMATION')
                left.label(text=job["node_name"])  # Prompt is already shortened

                # Right side
                right = split.row(align=True)
                right.alignment = 'RIGHT'

                if job["start_time"]:
                    elapsed = (datetime.now() - job["start_time"]).seconds
                    right.label(text=f"{elapsed}s")
                else:
                    right.label(text="...")

            # Queued
            for job in queued_jobs[:3]:
                row = box.row(align=True)
                row.label(text=job["node_name"], icon='TIME')

            if len(queued_jobs) > 3:
                box.label(text=f"+{len(queued_jobs) - 3} more in queue")
        else:
            layout.label(text="No active jobs", icon='CHECKMARK')

        # Error Log Button
        error_count = get_error_count()
        if error_count > 0:
            layout.separator()
            row = layout.row()
            row.alert = True
            row.operator("neuro.show_error_log", text=f"View Errors ({error_count})", icon='ERROR')
            row.operator("neuro.clear_errors", text="", icon='X')


class NEURO_PT_error_log_panel(bpy.types.Panel):
    """Error log panel - shown when there are errors"""
    bl_label = "Error Log"
    bl_idname = "NEURO_PT_error_log_panel"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = PANELS_NAME
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return (context.space_data and
                hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree' and
                get_error_count() > 0)

    def draw(self, context):
        layout = self.layout
        errors = get_errors(10)

        if not errors:
            layout.label(text="No errors")
            return

        for err in errors:
            box = layout.box()

            # Time and node
            row = box.row(align=True)
            time_str = err["time"].strftime("%H:%M:%S")
            row.label(text=time_str, icon='TIME')
            if err["node"]:
                row.label(text=err["node"])

            # Error message (wrapped)
            col = box.column(align=True)
            msg = err["message"]
            # Split into lines of ~40 chars
            while msg:
                col.label(text=msg[:45])
                msg = msg[45:]

        layout.separator()
        layout.operator("neuro.clear_errors", text="Clear All", icon='X')


# =============================================================================
# OPERATORS
# =============================================================================

class NEURO_OT_show_error_log(bpy.types.Operator):
    """Show error log"""
    bl_idname = "neuro.show_error_log"
    bl_label = "Show Error Log"

    def execute(self, context):
        # Just expand the error log panel
        self.report({'INFO'}, f"Found {get_error_count()} errors - see Error Log panel")
        return {'FINISHED'}


class NEURO_OT_show_errors_popup(bpy.types.Operator):
    """Show errors in popup and clear on close"""
    bl_idname = "neuro.show_errors_popup"
    bl_label = "Errors"
    bl_options = {'REGISTER'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=400)

    def draw(self, context):
        layout = self.layout
        errors = get_errors(10)

        if not errors:
            layout.label(text="No errors", icon='CHECKMARK')
            return

        layout.label(text=f"Recent Errors ({len(errors)})", icon='ERROR')
        layout.separator()

        for err in errors:
            box = layout.box()
            row = box.row(align=True)
            time_str = err["time"].strftime("%H:%M:%S")
            row.label(text=time_str, icon='TIME')
            if err["node"]:
                row.label(text=err["node"])
            if err["model"]:
                row.label(text=f"[{err['model'][:20]}]")

            # Error message
            msg = err["message"]
            col = box.column(align=True)
            # Split into lines of ~50 chars
            while msg:
                col.label(text=msg[:55])
                msg = msg[55:]

        layout.separator()
        row = layout.row(align=True)
        row.operator("neuro.send_error_report", text="Send Report", icon='URL')
        row.operator("neuro.clear_errors", text="Clear All", icon='X')

    def cancel(self, context):
        # Clear errors when popup is closed
        clear_errors()


class NEURO_OT_clear_errors(bpy.types.Operator):
    """Clear all errors from log"""
    bl_idname = "neuro.clear_errors"
    bl_label = "Clear Errors"

    def execute(self, context):
        clear_errors()
        NEURO_OT_send_error_report._sent = False
        self.report({'INFO'}, "Error log cleared")
        return {'FINISHED'}


class NEURO_OT_clear_completed_jobs(bpy.types.Operator):
    """Clear completed jobs from queue"""
    bl_idname = "neuro.clear_completed_jobs"
    bl_label = "Clear Completed"

    def execute(self, context):
        clear_completed()
        return {'FINISHED'}


class NEURO_OT_send_error_report(bpy.types.Operator):
    """Send error report to developers"""
    bl_idname = "neuro.send_error_report"
    bl_label = "Send Error Report"
    bl_description = "Send recent errors to developers for debugging"

    _sent = False  # Class-level flag to prevent spam

    @classmethod
    def poll(cls, context):
        return get_error_count() > 0 and not cls._sent

    def execute(self, context):
        import threading

        errors = get_errors(20)
        if not errors:
            self.report({'WARNING'}, "No errors to send")
            return {'CANCELLED'}

        # Collect report data
        report = self._build_report(context, errors)

        def send_worker():
            import urllib.request
            import urllib.error

            try:
                data = json.dumps(report).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.neuronodes.io/v1/error/report",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        def _ok():
                            NEURO_OT_send_error_report._sent = True
                            return None
                        bpy.app.timers.register(_ok, first_interval=0.1)
                        print(f"[{LOG_PREFIX}] Error report sent ({len(errors)} errors)")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to send error report: {e}")

        threading.Thread(target=send_worker, daemon=True).start()
        self.report({'INFO'}, "Sending error report...")
        return {'FINISHED'}

    def _build_report(self, context, errors):
        """Build anonymized error report payload."""
        import platform
        import hashlib

        # Addon version
        addon_version = "unknown"
        try:
            import sys
            root = __package__.split(".")[0] if __package__ else ""
            pkg = sys.modules.get(root)
            if pkg and hasattr(pkg, "bl_info"):
                v = pkg.bl_info.get("version", (0, 0, 0))
                addon_version = ".".join(map(str, v))
        except Exception:
            pass

        # Anonymous machine ID (same fingerprint as updater)
        try:
            import uuid
            parts = [platform.node(), str(uuid.getnode()), platform.machine(), platform.system()]
            machine_hash = hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]
        except Exception:
            machine_hash = "unknown"

        # Format errors
        formatted = []
        for err in errors:
            formatted.append({
                "time": err["time"].strftime("%Y-%m-%d %H:%M:%S"),
                "node": err.get("node", ""),
                "model": err.get("model", ""),
                "message": err.get("message", "")[:300],
            })

        return {
            "addon_version": addon_version,
            "blender_version": bpy.app.version_string,
            "os": f"{platform.system()} {platform.release()}",
            "machine_id": machine_hash,
            "error_count": len(formatted),
            "errors": formatted,
        }

# =============================================================================
# REGISTRATION
# =============================================================================

classes = [
    NEURO_PT_status_panel,
    NEURO_PT_error_log_panel,
    NEURO_OT_show_error_log,
    NEURO_OT_show_errors_popup,
    NEURO_OT_clear_errors,
    NEURO_OT_send_error_report,
    NEURO_OT_clear_completed_jobs,
]


def register():
    global _redraw_timer_running
    for cls in classes:
        bpy.utils.register_class(cls)

    # Append to Blender's native status bar (bottom of window)
    bpy.types.STATUSBAR_HT_header.append(draw_status_bar)

    # Start redraw timer
    if not _redraw_timer_running:
        bpy.app.timers.register(_redraw_timer, persistent=True)
        _redraw_timer_running = True


def unregister():
    global _redraw_timer_running

    # Stop redraw timer
    if _redraw_timer_running:
        try:
            bpy.app.timers.unregister(_redraw_timer)
        except Exception:
            pass
        _redraw_timer_running = False

    # Remove status bar draw
    try:
        bpy.types.STATUSBAR_HT_header.remove(draw_status_bar)
    except Exception:
        pass

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass