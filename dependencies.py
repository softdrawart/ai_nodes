# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Dependencies Module
Library management, security verification, and package installation.
"""

import sys
import os
import subprocess
import tempfile
import json
import urllib.request
import hashlib
import shutil
import threading  # Added for download thread

import bpy


# =============================================================================
# LIBRARY PATH MANAGEMENT
# =============================================================================

def get_addon_libs_path():
    """Returns the path to the 'libs' folder inside the addon directory"""
    base_dir = os.path.dirname(os.path.realpath(__file__))
    libs_dir = os.path.join(base_dir, "libs")
    return libs_dir


def ensure_libs_path():
    """Ensure libs path is in sys.path"""
    libs_path = get_addon_libs_path()
    if libs_path not in sys.path:
        sys.path.insert(0, libs_path)
    return libs_path


# =============================================================================
# DEPENDENCY FLAGS
# =============================================================================

DEPENDENCIES_INSTALLED = False
FAL_AVAILABLE = False
REPLICATE_AVAILABLE = False
REMBG_AVAILABLE = False
PREVIEWS_AVAILABLE = False

# Safe Import for Previews
try:
    import bpy.utils.previews

    PREVIEWS_AVAILABLE = True
except (ImportError, AttributeError, RuntimeError):
    pass


def get_rembg_libs_path():
    """Returns the path to the 'libs_rembg' folder - separate from main libs to avoid conflicts"""
    base_dir = os.path.dirname(os.path.realpath(__file__))
    libs_dir = os.path.join(base_dir, "libs_rembg")
    return libs_dir


def check_rembg():
    """
    Check if rembg is installed by verifying file existence.
    Does NOT import the library to avoid crashes during UI drawing.
    """
    global REMBG_AVAILABLE

    libs_dir = get_rembg_libs_path()

    # Check for site-packages/rembg or direct folder
    # Windows/standard pip structure check
    rembg_path = os.path.join(libs_dir, "rembg")

    if os.path.exists(rembg_path) and os.path.isdir(rembg_path):
        # Add to path only if confirmed existing, but DON'T import yet
        # Importing here causes crashes if DLLs are missing/conflicting
        if libs_dir not in sys.path:
            sys.path.insert(0, libs_dir)
        REMBG_AVAILABLE = True
        return True

    REMBG_AVAILABLE = False
    return False


def check_dependencies():
    """
    Check and import dependencies. Returns tuple of (deps_installed, fal_available, modules).
    Verifies PHYSICAL EXISTENCE of files to prevent 'Ghost' installs from memory cache.
    """
    global DEPENDENCIES_INSTALLED, FAL_AVAILABLE, REPLICATE_AVAILABLE

    # 1. PHYSICAL CHECK
    libs_path = get_addon_libs_path()
    critical_check_path = os.path.join(libs_path, "google", "genai")

    if not os.path.exists(critical_check_path):
        DEPENDENCIES_INSTALLED = False
        FAL_AVAILABLE = False
        REPLICATE_AVAILABLE = False
        return False, False, {}

    modules = {
        'PIL': None,
        'Image': None,
        'ImageGrab': None,
        'pydantic': None,
        'google_genai': None,
        'Client': None,
        'types': None,
        'fal_client': None,
        'replicate': None,
    }

    try:
        import PIL
        from PIL import Image, ImageGrab
        import pydantic
        import google.genai
        from google.genai import Client, types

        modules['PIL'] = PIL
        modules['Image'] = Image
        modules['ImageGrab'] = ImageGrab
        modules['pydantic'] = pydantic
        modules['google_genai'] = google.genai
        modules['Client'] = Client
        modules['types'] = types

        DEPENDENCIES_INSTALLED = True

        # Optional: fal_client
        try:
            import fal_client
            modules['fal_client'] = fal_client
            FAL_AVAILABLE = True
        except ImportError:
            # print(f"[{LOG_PREFIX}] fal_client not found (Optional)")
            FAL_AVAILABLE = False

        # Optional: replicate
        try:
            import replicate
            modules['replicate'] = replicate
            REPLICATE_AVAILABLE = True
        except ImportError:
            # print(f"[{LOG_PREFIX}] replicate not found (Optional)")
            REPLICATE_AVAILABLE = False

    except ImportError as e:
        print(f"[{LOG_PREFIX}] Dependency Missing: {e}")
        DEPENDENCIES_INSTALLED = False
        FAL_AVAILABLE = False
        REPLICATE_AVAILABLE = False

    return DEPENDENCIES_INSTALLED, FAL_AVAILABLE, modules


# =============================================================================
# DUMMY CLASSES (for when dependencies are missing)
# =============================================================================

class DummyClient:
    """Dummy Client class to prevent crashes when google.genai is not installed"""

    def __init__(self, api_key=None, http_options=None):
        pass

    @property
    def models(self):
        return self

    def generate_content(self, **kwargs):
        return None

    def list(self, **kwargs):
        return []


class DummyTypes:
    """Dummy types class to prevent crashes when google.genai is not installed"""

    class GenerateContentConfig:
        pass

    class Part:
        pass

    class SafetySetting:
        pass

    class ImageConfig:
        pass

    class HttpOptions:
        pass


# =============================================================================
# VERIFIED PACKAGES (Security)
# =============================================================================

VERIFIED_PACKAGES = {
    "google-genai": {
        "version": "1.60.0",
        "hash": None,
    },
    "fal-client": {
        "version": "0.12.0",
        "hash": None,
    },
    "replicate": {
        "version": "1.0.7",
        "hash": None,  # Verify via PyPI
    },
    "Pillow": {
        "version": "12.1.0",
        "hash": None,  # Platform-specific, verified via PyPI
    },
    "tripo3d": {
        "version": "0.3.10",
        "hash": None,  # Verify via PyPI
    },
    "aiohttp": {
        "version": "3.13.3",
        "hash": None,  # Platform-specific, required by tripo3d
    },
}


# =============================================================================
# SECURITY FUNCTIONS
# =============================================================================

def get_pypi_wheel_info(package_name: str, version: str) -> dict:
    """Fetch wheel info from PyPI for verification."""
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
        return {f["filename"]: f["digests"]["sha256"] for f in data.get("urls", [])}
    except Exception as e:
        print(f"[Security] PyPI fetch failed for {package_name}: {e}")
        return {}


def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_downloaded_wheel(wheel_path: str, package_name: str, version: str) -> tuple:
    """Verify wheel hash. Returns (is_valid, message)."""
    file_hash = calculate_file_hash(wheel_path)
    filename = os.path.basename(wheel_path)

    pkg_info = VERIFIED_PACKAGES.get(package_name)
    if not pkg_info:
        return True, "Not a primary package, skipping verification"

    expected_hash = pkg_info.get("hash")

    # If we have a stored hash, check it
    if expected_hash:
        if file_hash == expected_hash:
            return True, f"✓ Hash verified"
        # Might be platform-specific wheel, check PyPI

    # Verify against PyPI (for platform-specific wheels like Pillow)
    pypi_hashes = get_pypi_wheel_info(package_name, version)
    if filename in pypi_hashes:
        if file_hash == pypi_hashes[filename]:
            return True, f"✓ Hash verified via PyPI"
        else:
            return False, f"✗ HASH MISMATCH! Expected {pypi_hashes[filename][:16]}..."

    # Check if hash matches any PyPI wheel (different filename format)
    for pypi_file, pypi_hash in pypi_hashes.items():
        if file_hash == pypi_hash:
            return True, f"✓ Hash verified via PyPI ({pypi_file})"

    # If we expected a specific hash but didn't match
    if expected_hash and file_hash != expected_hash:
        return False, f"✗ HASH MISMATCH! Got {file_hash[:16]}..."

    return True, "Hash check skipped (dependency)"


def check_ip_location():
    """Check current IP location using ipleak.net service."""
    try:
        url = 'https://ipleak.net/json/'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return {
                'success': True,
                'ip': data.get('ip', 'Unknown'),
                'country': data.get('country_name', 'Unknown'),
                'city': data.get('city_name', 'Unknown'),
                'org': data.get('isp_name', 'Unknown')
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# =============================================================================
# INSTALLATION OPERATORS
# =============================================================================

class NEURO_OT_install_deps(bpy.types.Operator):
    """Securely install required AI libraries with hash verification"""
    bl_idname = "neuro.install_dependencies"
    bl_label = "Install/Update Libraries"
    bl_description = "Downloads and verifies google-genai, pillow, and fal-client"

    def execute(self, context):
        libs_dir = get_addon_libs_path()

        # 1. WINDOWS LOCK CHECK
        if DEPENDENCIES_INSTALLED and sys.platform == "win32":
            #self.report({'ERROR'}, "Cannot update loaded libraries on Windows!")

            def draw_error(self, context):
                layout = self.layout
                layout.label(text="⚠️  Windows File Lock detected", icon='ERROR')
                layout.label(text="Blender has locked the library files.")
                layout.separator()
                layout.label(text="To Force Update:")
                layout.label(text="1. Close Blender completely.")
                layout.label(text="2. Delete the 'libs' folder (click below).")
                layout.separator()
                # Added Open Folder button directly in popup
                layout.operator("neuro.open_libs_folder", text="Open Libs Folder", icon='FILE_FOLDER')
                layout.separator()
                layout.label(text="3. Open Blender and click Install again.")

            context.window_manager.popup_menu(draw_error, title="Update Failed", icon='ERROR')
            return {'CANCELLED'}

        # 2. CLEAN INSTALL - Remove corrupted libs if dependencies failed to load
        if os.path.exists(libs_dir) and not DEPENDENCIES_INSTALLED:
            try:
                import shutil
                shutil.rmtree(libs_dir)
                print(f"[{LOG_PREFIX}] Cleaned old libs folder: {libs_dir}")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Could not clean libs folder: {e}")

        os.makedirs(libs_dir, exist_ok=True)

        # 3. GET CORRECT PYTHON EXECUTABLE
        python_exe = sys.executable

        # Handle case where sys.executable might point to Blender itself
        if sys.platform == "win32":
            blender_dir = os.path.dirname(python_exe)
            possible_pythons = [
                os.path.join(blender_dir, f"{bpy.app.version[0]}.{bpy.app.version[1]}", "python", "bin", "python.exe"),
                os.path.join(blender_dir, "python", "bin", "python.exe"),
            ]
            for py_path in possible_pythons:
                if os.path.exists(py_path):
                    python_exe = py_path
                    break
        elif sys.platform == "darwin":
            blender_dir = os.path.dirname(python_exe)
            possible_pythons = [
                os.path.join(blender_dir, "..", "Resources", f"{bpy.app.version[0]}.{bpy.app.version[1]}", "python",
                             "bin", "python3.11"),
                os.path.join(blender_dir, f"{bpy.app.version[0]}.{bpy.app.version[1]}", "python", "bin", "python3.11"),
            ]
            for py_path in possible_pythons:
                if os.path.exists(py_path):
                    python_exe = py_path
                    break

        print(f"[{LOG_PREFIX}] Using Python: {python_exe}")

        # 4. ENSURE PIP IS AVAILABLE
        try:
            subprocess.run([python_exe, "-m", "ensurepip", "--default-pip"], capture_output=True, timeout=60)
        except Exception as e:
            print(f"[{LOG_PREFIX}] ensurepip note: {e}")

        try:
            subprocess.run([python_exe, "-m", "pip", "install", "--upgrade", "pip"], capture_output=True, timeout=120)
        except Exception as e:
            print(f"[{LOG_PREFIX}] pip upgrade note: {e}")

        # 5. SECURE INSTALL - Download, verify, then install
        print("[Security] Starting secure package installation...")

        # Create temp directory for downloads
        temp_download_dir = tempfile.mkdtemp(prefix="blender_neuro_nodes_")
        verification_results = []
        all_verified = True

        try:
            # Primary packages with hash verification
            for pkg_name, pkg_info in VERIFIED_PACKAGES.items():
                version = pkg_info["version"]
                print(f"[Security] Downloading {pkg_name}=={version}...")

                # Download wheel only (no install yet)
                download_cmd = [
                    python_exe, "-m", "pip", "download",
                    f"{pkg_name}=={version}",
                    "--dest", temp_download_dir,
                    "--no-deps",
                    "--prefer-binary",
                ]

                result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    verification_results.append(f"✗ {pkg_name}: Download failed")
                    all_verified = False
                    continue

                # Find downloaded wheel
                wheel_path = None
                pkg_name_normalized = pkg_name.lower().replace("-", "_")
                for f in os.listdir(temp_download_dir):
                    if f.lower().startswith(pkg_name_normalized) and f.endswith(".whl"):
                        wheel_path = os.path.join(temp_download_dir, f)
                        break

                if not wheel_path:
                    # Try exact match
                    for f in os.listdir(temp_download_dir):
                        if pkg_name.lower() in f.lower() and f.endswith(".whl"):
                            wheel_path = os.path.join(temp_download_dir, f)
                            break

                if not wheel_path:
                    verification_results.append(f"✗ {pkg_name}: Wheel not found")
                    all_verified = False
                    continue

                # Verify hash
                is_valid, msg = verify_downloaded_wheel(wheel_path, pkg_name, version)
                verification_results.append(f"{msg} {pkg_name}=={version}")

                if not is_valid:
                    all_verified = False
                    print(f"[Security] FAILED: {pkg_name} - {msg}")
                else:
                    print(f"[Security] {msg} {pkg_name}")

            # If any verification failed, abort
            if not all_verified:
                self.report({'ERROR'}, "Security verification failed! Check console.")

                def draw_security_error(self, context):
                    self.layout.label(text="⚠️  SECURITY VERIFICATION FAILED", icon='ERROR')
                    self.layout.separator()
                    for r in verification_results:
                        icon = 'CHECKMARK' if r.startswith("✓") else 'ERROR'
                        self.layout.label(text=r, icon=icon)
                    self.layout.separator()
                    self.layout.label(text="Installation aborted for your safety.")
                    self.layout.label(text="Contact addon developer if this persists.")

                context.window_manager.popup_menu(draw_security_error, title="Security Alert", icon='ERROR')
                return {'CANCELLED'}

            # 6. ALL VERIFIED - Now install everything
            print("[Security] All packages verified! Installing...")

            # Install with dependencies
            requirements = [
                f"google-genai=={VERIFIED_PACKAGES['google-genai']['version']}",
                f"fal-client=={VERIFIED_PACKAGES['fal-client']['version']}",
                f"replicate=={VERIFIED_PACKAGES['replicate']['version']}",
                f"Pillow=={VERIFIED_PACKAGES['Pillow']['version']}",
                f"aiohttp=={VERIFIED_PACKAGES['aiohttp']['version']}",
                f"tripo3d=={VERIFIED_PACKAGES['tripo3d']['version']}",
            ]

            pip_cmd = [
                python_exe, "-m", "pip", "install",
                "--target", libs_dir,
                "--upgrade",
                "--no-user",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--prefer-binary",
            ]
            pip_cmd.extend(requirements)

            result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                print(f"[{LOG_PREFIX}] pip stderr: {result.stderr}")
                self.report({'ERROR'}, "Installation failed. Check System Console.")
                return {'CANCELLED'}

            # 7. VERIFY INSTALLATION
            if libs_dir not in sys.path:
                sys.path.insert(0, libs_dir)

            print("[Security] Installation complete. Verifying imports...")

            def draw_success(self, context):
                self.layout.label(text="✓ Secure Installation Complete!", icon='CHECKMARK')
                self.layout.separator()
                self.layout.label(text="All packages verified.")
                self.layout.separator()
                # Loud Restart Warning
                row = self.layout.row()
                row.alert = True
                row.label(text="RESTART BLENDER NOW", icon='FILE_REFRESH')
                self.layout.label(text="Libraries will not work until restart.")

            context.window_manager.popup_menu(draw_success, title="Success", icon='CHECKMARK')

            # 8. CALL EXPLICIT RESTART DIALOG
            def call_restart_dialog():
                # invoke_default triggers the popup UI
                bpy.ops.neuro.restart_message('INVOKE_DEFAULT')
                return None

            bpy.app.timers.register(call_restart_dialog, first_interval=0.1)

            try:
                from . import get_addon_name
                context.preferences.addons[get_addon_name()].preferences.needs_restart = True
            except Exception:
                pass

        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "Installation timed out. Check internet connection.")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        finally:
            # Cleanup temp directory
            try:
                import shutil
                shutil.rmtree(temp_download_dir)
            except Exception:
                pass

        return {'FINISHED'}


class NEURO_OT_open_libs_folder(bpy.types.Operator):
    """Open the libraries folder in File Explorer"""
    bl_idname = "neuro.open_libs_folder"
    bl_label = "Open Libs Folder"

    def execute(self, context):
        libs_path = get_addon_libs_path()
        if not os.path.exists(libs_path):
            os.makedirs(libs_path)
        bpy.ops.wm.path_open(filepath=libs_path)
        return {'FINISHED'}


class NEURO_OT_check_package_updates(bpy.types.Operator):
    """[DEV] Check for package updates and show new hashes"""
    bl_idname = "neuro.check_package_updates"
    bl_label = "Check Package Updates"
    bl_description = "Developer tool: Check PyPI for newer package versions"

    def execute(self, context):
        updates = []

        for pkg_name, pkg_info in VERIFIED_PACKAGES.items():
            current_version = pkg_info["version"]

            try:
                url = f"https://pypi.org/pypi/{pkg_name}/json"
                with urllib.request.urlopen(url, timeout=10) as response:
                    data = json.loads(response.read().decode())

                latest_version = data["info"]["version"]

                if latest_version != current_version:
                    # Get hash for latest
                    wheel_hash = None
                    for file_info in data.get("urls", []):
                        if file_info["packagetype"] == "bdist_wheel":
                            if "py3-none-any" in file_info["filename"]:
                                wheel_hash = file_info["digests"]["sha256"]
                                break
                    if not wheel_hash:
                        for file_info in data.get("urls", []):
                            if file_info["packagetype"] == "bdist_wheel":
                                wheel_hash = file_info["digests"]["sha256"]
                                break

                    updates.append({
                        "name": pkg_name,
                        "current": current_version,
                        "latest": latest_version,
                        "hash": wheel_hash or "platform-specific",
                    })

            except Exception as e:
                print(f"[Security] Check failed for {pkg_name}: {e}")

        if updates:
            def draw_updates(self, context):
                self.layout.label(text="Package Updates Available:", icon='INFO')
                self.layout.separator()
                for u in updates:
                    self.layout.label(text=f"{u['name']}: {u['current']} → {u['latest']}")
                    self.layout.label(text=f"  Hash: {u['hash'][:32]}...")
                self.layout.separator()
                self.layout.label(text="Copy new config to VERIFIED_PACKAGES")

            context.window_manager.popup_menu(draw_updates, title="Dev: Package Updates", icon='FILE_REFRESH')

            # Also print to console for easy copy
            print("\n" + "=" * 60)
            print("VERIFIED_PACKAGES UPDATE:")
            print("=" * 60)
            for u in updates:
                print(f'''    "{u['name']}": {{
        "version": "{u['latest']}",
        "hash": "{u['hash']}",
    }},''')
            print("=" * 60 + "\n")
        else:
            self.report({'INFO'}, "All packages are up to date")

        return {'FINISHED'}


class NEURO_OT_check_vpn(bpy.types.Operator):
    """Check your current IP location and VPN status"""
    bl_idname = "neuro.check_vpn"
    bl_label = "Check VPN/IP"
    bl_description = "Check your current IP location (important for Gemini API access)"

    def execute(self, context):
        import threading

        scn = context.scene
        scn.neuro_vpn_status = "Checking IP location..."

        def worker_job():
            result = check_ip_location()

            def main_thread_update():
                scn_inner = bpy.context.scene

                if result['success']:
                    status = f"{result['ip']} | {result['city']}, {result['country']}"
                    scn_inner.neuro_vpn_status = status
                else:
                    scn_inner.neuro_vpn_status = f"Check failed: {result['error']}"

                return None

            bpy.app.timers.register(main_thread_update, first_interval=0.1)

        threading.Thread(target=worker_job, daemon=True).start()
        return {'FINISHED'}


class NEURO_OT_install_rembg(bpy.types.Operator):
    """Install local background removal tool (rembg) - Uses CPU (Stable)"""
    bl_idname = "neuro.install_rembg"
    bl_label = "Install Background Removal Tool"
    bl_description = "Install rembg library (CPU version for stability)"

    def execute(self, context):
        import threading
        import shutil

        global REMBG_AVAILABLE

        # Use SEPARATE folder to avoid conflicts with main libs
        libs_dir = get_rembg_libs_path()

        # CLEANUP: Delete to remove broken GPU/NumPy 2.x versions
        if os.path.exists(libs_dir):
            try:
                print(f"[Rembg] Removing old libraries to ensure stability...")
                shutil.rmtree(libs_dir)
            except Exception as e:
                print(f"[Rembg] Warning: Could not clean old libs: {e}")

        os.makedirs(libs_dir, exist_ok=True)

        if libs_dir not in sys.path:
            sys.path.insert(0, libs_dir)

        python_exe = sys.executable

        # ... (keep prefs retrieval code) ...
        prefs = None
        try:
            prefs = context.preferences.addons[__package__].preferences
        except Exception:
            pass

        def install_worker():
            nonlocal prefs
            try:
                print(f"[Rembg] Installing library to {libs_dir}...")

                pip_cmd = [
                    python_exe, "-m", "pip", "install",
                    "--target", libs_dir,
                    "--upgrade",
                    "--no-user",
                    "--no-warn-script-location",
                    "--disable-pip-version-check",
                    "--force-reinstall",
                    "--ignore-installed",
                    # PIN PACKAGES TO FIX "No backend found" and DLL ERROR:
                    "numpy<2.0.0",  # FORCE NumPy 1.x (Critical for onnxruntime binary compat)
                    "onnxruntime==1.17.3",  # STABLE older version that avoids new DLL conflicts
                    "rembg[cpu]>=2.0.60",  # Newer version for BiRefNet support
                ]

                result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=600)

                if result.returncode != 0:
                    print(f"[Rembg] pip stderr: {result.stderr}")

                    def show_error():
                        def draw_err(self, context):
                            self.layout.label(text="Installation failed!", icon='ERROR')
                            self.layout.label(text="Check System Console for details.")

                        bpy.context.window_manager.popup_menu(draw_err, title="Error", icon='ERROR')
                        return None

                    bpy.app.timers.register(show_error, first_interval=0.1)
                    return

                print("[Rembg] Library installed, pre-downloading model...")

                # Step 2: Pre-download the model by doing a test removal
                try:
                    # Make sure our libs path is first
                    if libs_dir not in sys.path:
                        sys.path.insert(0, libs_dir)

                    # Clear any cached imports
                    for mod_name in list(sys.modules.keys()):
                        if 'rembg' in mod_name or 'onnx' in mod_name:
                            del sys.modules[mod_name]

                    import rembg
                    from PIL import Image
                    import io

                    # Create 10x10 red test image
                    test_img = Image.new('RGB', (10, 10), color='red')
                    img_bytes = io.BytesIO()
                    test_img.save(img_bytes, format='PNG')
                    img_bytes.seek(0)

                    # Don't download BiRefNet here, wait for explicit download button
                    # Just verify import works
                    print("[Rembg] Import successful.")

                    global REMBG_AVAILABLE
                    REMBG_AVAILABLE = True

                    def show_success():
                        def draw_success(self, context):
                            self.layout.label(text="Background Removal Tool Ready!", icon='CHECKMARK')
                            self.layout.separator()
                            self.layout.label(text="Library installed.")
                            self.layout.label(text="Click 'Download Model' to finish setup.")

                        bpy.context.window_manager.popup_menu(draw_success, title="Success", icon='CHECKMARK')
                        return None

                    bpy.app.timers.register(show_success, first_interval=0.1)

                except ImportError as e:
                    print(f"[Rembg] Import failed after install: {e}")
                    import traceback
                    traceback.print_exc()

                    # Specific warning for DLL errors
                    msg_title = "Restart Required"
                    msg_icon = "FILE_REFRESH"
                    msg_text = "Please restart Blender to complete setup."

                    if "DLL load failed" in str(e):
                        msg_title = "DLL Load Error"
                        msg_icon = "ERROR"
                        msg_text = "DLL conflict detected. Restarting Blender usually fixes this."

                    # Library installed but needs restart to import
                    if prefs:
                        prefs.rembg_needs_restart = True

                    def show_restart():
                        def draw_restart(self, context):
                            self.layout.label(text="Library Installed!", icon='CHECKMARK')
                            self.layout.separator()
                            self.layout.label(text=msg_text)
                            self.layout.label(text="Model will download on first use.")

                        bpy.context.window_manager.popup_menu(draw_restart, title=msg_title, icon=msg_icon)
                        return None

                    bpy.app.timers.register(show_restart, first_interval=0.1)

                except Exception as e:
                    print(f"[Rembg] Model pre-download failed: {e}")
                    import traceback
                    traceback.print_exc()

            except subprocess.TimeoutExpired:
                def show_timeout():
                    def draw_timeout(self, context):
                        self.layout.label(text="Installation timed out!", icon='ERROR')
                        self.layout.label(text="Check internet connection.")

                    bpy.context.window_manager.popup_menu(draw_timeout, title="Error", icon='ERROR')
                    return None

                bpy.app.timers.register(show_timeout, first_interval=0.1)

            except Exception as e:
                print(f"[Rembg] Install error: {e}")
                import traceback
                traceback.print_exc()

                def show_error():
                    def draw_err(self, context):
                        self.layout.label(text=f"Error: {str(e)[:50]}", icon='ERROR')

                    bpy.context.window_manager.popup_menu(draw_err, title="Error", icon='ERROR')
                    return None

                bpy.app.timers.register(show_error, first_interval=0.1)

        # Run in background thread so UI doesn't freeze
        self.report({'INFO'}, "Installing rembg... Check console for progress.")
        thread = threading.Thread(target=install_worker, daemon=True)
        thread.start()

        return {'FINISHED'}


class NEURO_OT_restart_message(bpy.types.Operator):
    """Explicit blocking dialog to force restart"""
    bl_idname = "neuro.restart_message"
    bl_label = "Restart Required"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # The 'OK' button triggers this
        bpy.ops.wm.quit_blender()
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.alert = True
        box.label(text="Installation Complete!", icon='CHECKMARK')
        box.separator()
        box.label(text="Blender must restart to load the new libraries.")
        box.label(text="Click 'OK' below to Exit Blender now.", icon='FILE_REFRESH')
        box.separator()
        box.label(text="(Unsaved changes? Click Cancel instead)", icon='INFO')


# ADDED: Operator to download the model file explicitly
class NEURO_OT_download_rembg_model(bpy.types.Operator):
    """Download the BiRefNet model file explicitly (~170MB)"""
    bl_idname = "neuro.download_rembg_model"
    bl_label = "Download Model"
    bl_description = "Download the BiRefNet model file (~170MB). Required before use."

    def execute(self, context):
        from .api import trigger_model_download

        # Run in thread to avoid UI freeze
        def download_worker():
            success, msg = trigger_model_download()

            def show_result():
                def draw_res(self, context):
                    if success:
                        self.layout.label(text="Download Started!", icon='CHECKMARK')
                        self.layout.label(text="Check console for progress.")
                    else:
                        self.layout.label(text="Error", icon='ERROR')
                        self.layout.label(text=msg)

                bpy.context.window_manager.popup_menu(draw_res, title="Model Download", icon='INFO')
                return None

            bpy.app.timers.register(show_result, first_interval=0.1)

        threading.Thread(target=download_worker, daemon=True).start()
        self.report({'INFO'}, "Downloading model... Check console.")
        return {'FINISHED'}


# =============================================================================
# REGISTRATION
# =============================================================================

DEPENDENCY_CLASSES = (
    NEURO_OT_install_deps,
    NEURO_OT_check_package_updates,
    NEURO_OT_check_vpn,
    NEURO_OT_install_rembg,
    NEURO_OT_download_rembg_model,
    NEURO_OT_open_libs_folder,
    NEURO_OT_restart_message,
)


def register():
    for cls in DEPENDENCY_CLASSES:
        bpy.utils.register_class(cls)

    # FORCE CHECK ON STARTUP
    # This updates the global variable so the Node Editor knows the tool is ready
    check_rembg()


def unregister():
    for cls in reversed(DEPENDENCY_CLASSES):
        bpy.utils.unregister_class(cls)