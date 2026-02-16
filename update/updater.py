# -*- coding: utf-8 -*-
"""
Unified Update System for AI Nodes
======================================
Single module handling: version check, download, install, restore, restart.
Detects internal vs commercial builds and routes accordingly.

Designed for pyd compilation to hide endpoints and auth logic.
"""

import os
import sys
import json
import hashlib
import shutil
import tempfile
import threading
import time
import traceback

import bpy
from bpy.types import Operator

try:
    LOG_PREFIX = LOG_PREFIX  # from builtins, set in __init__.py
except NameError:
    LOG_PREFIX = "AINODES"


# =============================================================================
# ENDPOINTS (hidden when compiled to .pyd)
# =============================================================================

_API_BASE = "https://api.neuronodes.io"
_EP_CHECK = f"{_API_BASE}/v1/update/check"

_CHECK_INTERVAL = 86400  # 24h in seconds
_DOWNLOAD_TIMEOUT = 120

# =============================================================================
# STATE
# =============================================================================

_state = {
    "checking": False,
    "downloading": False,
    "available": False,
    "ready_restart": False,
    "error": "",
    "progress": "",
    "new_version": "",
    "changelog": "",
    "download_url": "",
    "sha256": "",
}

_last_check_time = 0.0


# =============================================================================
# HELPERS
# =============================================================================

def _get_addon_version():
    """Get current addon version string from bl_info."""
    try:
        root = __package__.split(".")[0]
        pkg = sys.modules.get(root)
        if pkg and hasattr(pkg, "bl_info"):
            v = pkg.bl_info.get("version", (0, 0, 0))
            return ".".join(map(str, v))
    except Exception:
        pass
    return "0.0.0"


def _get_addon_dir():
    """Get addon root directory (parent of update/ package)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_backup_dir():
    """Get backup directory path."""
    addon_dir = _get_addon_dir()
    addon_folder = os.path.basename(addon_dir)
    addon_parent = os.path.dirname(addon_dir)
    return os.path.join(addon_parent, f"_{addon_folder}_backup")


def _is_internal():
    """Check if this is an internal build."""
    try:
        from ..config import is_internal
        return is_internal()
    except Exception:
        return False


def _get_license_key():
    """Read license key from addon preferences."""
    try:
        root = __package__.split(".")[0]
        prefs = bpy.context.preferences.addons.get(root)
        if prefs:
            return getattr(prefs.preferences, "license_key", "")
    except Exception:
        pass
    return ""


def _get_machine_fingerprint():
    """Machine fingerprint — same logic as config_proxy."""
    import platform
    try:
        import uuid
        parts = [platform.node(), str(uuid.getnode()), platform.machine(), platform.system()]
        return hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]
    except Exception:
        return hashlib.sha256(platform.node().encode()).hexdigest()[:32]


def _version_tuple(s):
    """Parse '1.8.5' -> (1, 8, 5)."""
    try:
        return tuple(int(x) for x in s.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def has_backup():
    """Check if a backup exists that can be restored."""
    backup_dir = _get_backup_dir()
    if not os.path.isdir(backup_dir):
        return False
    # Must have __init__.py.bak (our marker) or __init__.py
    return (
        os.path.exists(os.path.join(backup_dir, "__init__.py.bak"))
        or os.path.exists(os.path.join(backup_dir, "__init__.py"))
    )


def get_state():
    """Public: get current update state dict for UI."""
    return dict(_state)


# =============================================================================
# BACKUP HELPERS
# =============================================================================

def _create_backup(addon_dir, backup_dir):
    """Create backup of addon_dir, hiding __init__.py from Blender."""
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)

    shutil.copytree(addon_dir, backup_dir)

    # Rename __init__.py -> __init__.py.bak so Blender doesn't
    # register the backup as a second addon in the addons list
    backup_init = os.path.join(backup_dir, "__init__.py")
    if os.path.exists(backup_init):
        os.rename(backup_init, backup_init + ".bak")

    print(f"[{LOG_PREFIX} Update] Backed up to {backup_dir}")


def _restore_backup(addon_dir, backup_dir):
    """Restore addon from backup directory."""
    # Restore __init__.py name first
    bak_init = os.path.join(backup_dir, "__init__.py.bak")
    real_init = os.path.join(backup_dir, "__init__.py")
    if os.path.exists(bak_init) and not os.path.exists(real_init):
        os.rename(bak_init, real_init)

    # Wipe current and copy backup over
    shutil.rmtree(addon_dir, ignore_errors=True)
    shutil.copytree(backup_dir, addon_dir)
    print(f"[{LOG_PREFIX} Update] Restored from backup")


# =============================================================================
# CHECK
# =============================================================================

def check_for_update(force=False, callback=None):
    """
    Check API for a new version. Background thread.
    Respects cooldown unless force=True.
    """
    global _last_check_time

    if _state["checking"] or _state["downloading"]:
        return

    now = time.time()
    if not force and (now - _last_check_time) < _CHECK_INTERVAL:
        return

    _state["checking"] = True
    _state["error"] = ""
    _state["progress"] = "Checking for updates..."
    _state["available"] = False

    def _worker():
        import urllib.request
        import urllib.error

        global _last_check_time

        try:
            current = _get_addon_version()
            internal = _is_internal()

            # Build request payload
            payload = {
                "current_version": current,
                "blender_version": bpy.app.version_string,
                "machine_id": _get_machine_fingerprint(),
                "build_type": "internal" if internal else "commercial",
            }

            # Auth: commercial sends license key, internal sends fingerprint only
            if not internal:
                key = _get_license_key()
                if not key:
                    _state["error"] = "No license key"
                    _state["checking"] = False
                    _state["progress"] = ""
                    _schedule_callback(callback)
                    return
                payload["license_key"] = key

            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                _EP_CHECK,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            _last_check_time = time.time()

            if data.get("up_to_date", True):
                _state["available"] = False
                _state["progress"] = ""
                _state["new_version"] = ""
                return

            # Update available
            _state["available"] = True
            _state["new_version"] = data.get("version", "?")
            _state["changelog"] = data.get("changelog", "")
            _state["download_url"] = data.get("download_url", "")
            _state["sha256"] = data.get("sha256", "")
            _state["progress"] = f"v{_state['new_version']} available"
            print(f"[{LOG_PREFIX} Update] v{current} -> v{_state['new_version']}")

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            _state["error"] = f"HTTP {e.code}"
            print(f"[{LOG_PREFIX} Update] HTTP {e.code}: {body}")
            _last_check_time = time.time()  # Don't spam on server errors
        except Exception as e:
            _state["error"] = str(e)[:100]
            print(f"[{LOG_PREFIX} Update] Check failed: {e}")
        finally:
            _state["checking"] = False
            _schedule_callback(callback)

    threading.Thread(target=_worker, daemon=True).start()


# =============================================================================
# DOWNLOAD & INSTALL
# =============================================================================

def download_and_install(callback=None):
    """Download zip, verify SHA256, backup, extract over addon dir. Background thread."""
    if _state["downloading"] or not _state["download_url"]:
        return

    _state["downloading"] = True
    _state["error"] = ""
    _state["progress"] = "Downloading..."
    _state["ready_restart"] = False

    def _worker():
        import urllib.request
        import zipfile

        addon_dir = _get_addon_dir()
        backup_dir = _get_backup_dir()
        tmp_dir = None

        try:
            # ── Download ──
            tmp_dir = tempfile.mkdtemp(prefix="neuro_update_")
            zip_path = os.path.join(tmp_dir, "update.zip")

            req = urllib.request.Request(_state["download_url"])
            with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            _state["progress"] = f"Downloading... {int(downloaded / total * 100)}%"

            print(f"[{LOG_PREFIX} Update] Downloaded {downloaded} bytes")

            # ── Verify SHA256 ──
            expected = _state.get("sha256", "")
            if expected:
                _state["progress"] = "Verifying..."
                sha = hashlib.sha256()
                with open(zip_path, "rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        sha.update(block)
                actual = sha.hexdigest()
                if actual.lower() != expected.lower():
                    raise ValueError(f"SHA256 mismatch: {actual[:16]}... vs {expected[:16]}...")
                print(f"[{LOG_PREFIX} Update] SHA256 OK")

            # ── Validate zip ──
            _state["progress"] = "Validating..."
            if not zipfile.is_zipfile(zip_path):
                raise ValueError("Not a valid zip file")

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                if not any(n.endswith("__init__.py") for n in names):
                    raise ValueError("Zip missing __init__.py")

                # Find addon root prefix inside zip
                zip_prefix = ""
                for n in names:
                    if n.endswith("__init__.py") and n.count("/") <= 1:
                        if "/" in n:
                            zip_prefix = n.split("/")[0] + "/"
                        break

            # ── Backup ──
            _state["progress"] = "Backing up..."
            _create_backup(addon_dir, backup_dir)

            # ── Extract over current ──
            _state["progress"] = "Installing..."
            extract_dir = os.path.join(tmp_dir, "extracted")

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            source = os.path.join(extract_dir, zip_prefix.rstrip("/")) if zip_prefix else extract_dir
            if not os.path.isdir(source):
                source = extract_dir

            files_updated = 0
            for root, dirs, files in os.walk(source):
                rel = os.path.relpath(root, source)
                dest = os.path.join(addon_dir, rel) if rel != "." else addon_dir
                os.makedirs(dest, exist_ok=True)
                for fname in files:
                    try:
                        shutil.copy2(os.path.join(root, fname), os.path.join(dest, fname))
                        files_updated += 1
                    except PermissionError:
                        print(f"[{LOG_PREFIX} Update] Skipped locked: {fname}")

            # ── Done ──
            _state["ready_restart"] = True
            _state["available"] = False
            _state["progress"] = f"v{_state['new_version']} installed — restart Blender"
            print(f"[{LOG_PREFIX} Update] {files_updated} files updated. Restart to apply.")

        except Exception as e:
            traceback.print_exc()
            _state["error"] = str(e)[:150]
            _state["progress"] = f"Failed: {str(e)[:60]}"

            # Auto-restore from backup on failure
            try:
                if os.path.exists(backup_dir):
                    _restore_backup(addon_dir, backup_dir)
            except Exception as re:
                print(f"[{LOG_PREFIX} Update] Auto-restore failed: {re}")
        finally:
            _state["downloading"] = False
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            _schedule_callback(callback)

    threading.Thread(target=_worker, daemon=True).start()


def _schedule_callback(callback):
    if callback:
        def _run():
            callback(dict(_state))
            return None
        bpy.app.timers.register(_run, first_interval=0.1)


# =============================================================================
# OPERATORS
# =============================================================================

class NEURO_OT_check_update(Operator):
    """Check for addon updates"""
    bl_idname = "neuro.check_update"
    bl_label = "Check for Updates"

    def execute(self, context):
        def on_done(state):
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()

        check_for_update(force=True, callback=on_done)
        self.report({"INFO"}, "Checking for updates...")
        return {"FINISHED"}


class NEURO_OT_install_update(Operator):
    """Download and install the available update"""
    bl_idname = "neuro.install_update"
    bl_label = "Install Update"

    def execute(self, context):
        if not _state.get("download_url"):
            self.report({"WARNING"}, "No update available")
            return {"CANCELLED"}

        def on_done(state):
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()

        download_and_install(callback=on_done)
        self.report({"INFO"}, "Downloading update...")
        return {"FINISHED"}


class NEURO_OT_restore_backup(Operator):
    """Restore previous addon version from backup"""
    bl_idname = "neuro.restore_backup"
    bl_label = "Restore Previous Version"
    bl_description = "Revert to the version installed before the last update"

    @classmethod
    def poll(cls, context):
        return has_backup()

    def execute(self, context):
        addon_dir = _get_addon_dir()
        backup_dir = _get_backup_dir()

        if not os.path.isdir(backup_dir):
            self.report({"ERROR"}, "No backup found")
            return {"CANCELLED"}

        try:
            _restore_backup(addon_dir, backup_dir)

            # Clean up backup after successful restore
            shutil.rmtree(backup_dir, ignore_errors=True)

            _state["ready_restart"] = True
            _state["available"] = False
            _state["progress"] = "Previous version restored — restart Blender"

            self.report({"INFO"}, "Restored. Restart Blender to apply.")
        except Exception as e:
            self.report({"ERROR"}, f"Restore failed: {e}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class NEURO_OT_restart_blender(Operator):
    """Restart Blender to apply update"""
    bl_idname = "neuro.restart_blender"
    bl_label = "Restart Blender"
    bl_description = "Save and restart Blender to apply the update"

    def execute(self, context):
        if bpy.data.filepath:
            try:
                bpy.ops.wm.save_mainfile()
            except Exception:
                pass

        import subprocess
        args = [bpy.app.binary_path]
        if bpy.data.filepath:
            args.append(bpy.data.filepath)

        try:
            subprocess.Popen(args)
        except Exception as e:
            self.report({"ERROR"}, f"Could not restart: {e}")
            return {"CANCELLED"}

        bpy.ops.wm.quit_blender()
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


# =============================================================================
# UI DRAW HELPERS
# =============================================================================

def draw_update_ui(layout):
    """Draw full update section in addon preferences."""
    state = get_state()
    current = _get_addon_version()

    box = layout.box()
    row = box.row(align=True)
    row.label(text=f"Version: {current}", icon="INFO")

    if state["checking"]:
        row.label(text="Checking...", icon="FILE_REFRESH")

    elif state["downloading"]:
        row.label(text=state["progress"] or "Downloading...", icon="IMPORT")

    elif state["ready_restart"]:
        row.alert = True
        row.label(text=state["progress"], icon="ERROR")
        row.operator("neuro.restart_blender", text="Restart", icon="FILE_REFRESH")

    elif state["available"]:
        sub = row.row(align=True)
        sub.alert = True
        sub.label(text=f"v{state['new_version']} available")
        sub.operator("neuro.install_update", text="Update", icon="IMPORT")
        if state["changelog"]:
            box.label(text=state["changelog"][:80], icon="TEXT")

    elif state["error"]:
        row.label(text=f"Error: {state['error'][:50]}", icon="ERROR")
        row.operator("neuro.check_update", text="Retry", icon="FILE_REFRESH")

    else:
        row.label(text="Up to date", icon="CHECKMARK")
        row.operator("neuro.check_update", text="Check", icon="FILE_REFRESH")

    # Restore button — only visible when backup exists
    if has_backup() and not state["downloading"]:
        restore_row = box.row(align=True)
        restore_row.operator("neuro.restore_backup", text="Restore Previous Version", icon="LOOP_BACK")


def draw_status_bar(row):
    """Minimal status bar indicator for status_manager."""
    state = get_state()

    if state["ready_restart"]:
        sub = row.row(align=True)
        sub.alert = True
        sub.operator("neuro.restart_blender", text="Restart to Update", icon="FILE_REFRESH")
    elif state["available"]:
        sub = row.row(align=True)
        sub.alert = True
        sub.operator("neuro.install_update", text=f"Update v{state['new_version']}", icon="IMPORT")
    elif state["downloading"]:
        row.label(text=state["progress"] or "Updating...", icon="IMPORT")


# =============================================================================
# AUTO-CHECK TIMER
# =============================================================================

_timer_registered = False


def _auto_check_timer():
    """Startup check, then repeats every 24h."""
    check_for_update()
    return _CHECK_INTERVAL


# =============================================================================
# REGISTRATION
# =============================================================================

_classes = [
    NEURO_OT_check_update,
    NEURO_OT_install_update,
    NEURO_OT_restore_backup,
    NEURO_OT_restart_blender,
]


def register():
    global _timer_registered
    for cls in _classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass

    if not _timer_registered:
        bpy.app.timers.register(_auto_check_timer, first_interval=8.0, persistent=True)
        _timer_registered = True


def unregister():
    global _timer_registered

    if _timer_registered:
        try:
            bpy.app.timers.unregister(_auto_check_timer)
        except Exception:
            pass
        _timer_registered = False

    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass