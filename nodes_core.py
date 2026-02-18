# -*- coding: utf-8 -*-
import os
import json
import bpy
from bpy.props import StringProperty, IntProperty
from bpy.types import NodeTree, Node, NodeSocket
from .utils import get_preview_collection

_background_timer_running = False
_force_update_interval = 2.0  # seconds

# Image sync timer for auto-pack support
_image_sync_timer_running = False
_image_sync_interval = 1.5  # seconds


def _image_sync_timer():
    """
    Background timer that syncs dirty/packed images to disk.
    This enables auto-preview updates when user edits images with auto-pack enabled.
    Only syncs images that are likely from AI Nodes (in generations folder or node paths).
    """
    global _image_sync_timer_running

    try:
        # First check if there are any AINodes node trees - skip if not
        has_neuro_trees = any(
            ng.bl_idname == 'NeuroGenNodeTree'
            for ng in bpy.data.node_groups
        )
        if not has_neuro_trees:
            return _image_sync_interval

        # Collect all image paths used by AI Nodes
        neuro_image_paths = set()
        for ng in bpy.data.node_groups:
            if ng.bl_idname == 'NeuroGenNodeTree':
                for node in ng.nodes:
                    # Get paths from various node types
                    if hasattr(node, 'result_path') and node.result_path:
                        neuro_image_paths.add(os.path.normpath(os.path.abspath(node.result_path)))
                    if hasattr(node, 'get_image_path'):
                        try:
                            path = node.get_image_path()
                            if path:
                                neuro_image_paths.add(os.path.normpath(os.path.abspath(path)))
                        except Exception:
                            pass
                    if hasattr(node, 'image_path') and node.image_path:
                        neuro_image_paths.add(os.path.normpath(os.path.abspath(node.image_path)))

        if not neuro_image_paths:
            return _image_sync_interval

        synced_any = False

        for img in bpy.data.images:
            # Skip images without filepath
            if not img.filepath or img.filepath.startswith('<'):
                continue

            try:
                abs_path = os.path.normpath(os.path.abspath(bpy.path.abspath(img.filepath)))
            except Exception:
                continue

            # Only sync if this image is used by a AINodes node
            if abs_path not in neuro_image_paths:
                continue

            # Check if image needs syncing
            if not img.is_dirty:
                continue

            try:
                # Save the image to disk
                img.save()
                synced_any = True

                # Clear the preview cache for this path
                if node_preview_collection:
                    keys_to_remove = [k for k in list(node_preview_collection.keys())
                                      if k.startswith(abs_path)]
                    for key in keys_to_remove:
                        try:
                            del node_preview_collection[key]
                        except Exception:
                            pass

            except Exception:
                pass  # Silently fail

        # If we synced anything, trigger redraw
        if synced_any:
            try:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'NODE_EDITOR':
                            area.tag_redraw()
            except Exception:
                pass

    except Exception:
        pass  # Timer must not raise

    return _image_sync_interval  # Keep running


def start_image_sync_timer():
    """Start the image sync timer"""
    global _image_sync_timer_running
    if not _image_sync_timer_running:
        _image_sync_timer_running = True
        bpy.app.timers.register(_image_sync_timer,
                                first_interval=_image_sync_interval,
                                persistent=True)


def stop_image_sync_timer():
    """Stop the image sync timer"""
    global _image_sync_timer_running
    _image_sync_timer_running = False
    try:
        if bpy.app.timers.is_registered(_image_sync_timer):
            bpy.app.timers.unregister(_image_sync_timer)
    except Exception:
        pass


def _background_node_update_timer():
    """
    Persistent timer that forces node editor redraws.
    Runs every 2 seconds even when Blender window loses focus.
    This ensures progress updates are visible when users switch to other apps.
    """
    global _background_timer_running

    # Check if any node tree has generating nodes
    has_active = False
    for node_group in bpy.data.node_groups:
        if node_group.bl_idname == 'NeuroGenNodeTree':
            for node in node_group.nodes:
                if getattr(node, 'is_generating', False) or getattr(node, 'is_processing', False):
                    has_active = True
                    break
            if has_active:
                break

    if not has_active:
        # No active generations, stop timer
        _background_timer_running = False
        return None

    # Force redraw all node editor areas
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.tag_redraw()
    except Exception:
        pass  # Context might be invalid during shutdown

    return _force_update_interval  # Continue running


def start_background_timer():
    """Start the background update timer if not already running"""
    global _background_timer_running
    if not _background_timer_running:
        _background_timer_running = True
        # persistent=True ensures timer runs even when Blender is minimized/unfocused
        bpy.app.timers.register(_background_node_update_timer,
                                first_interval=_force_update_interval,
                                persistent=True)


def stop_background_timer():
    """Stop the background timer"""
    global _background_timer_running
    _background_timer_running = False
    try:
        if bpy.app.timers.is_registered(_background_node_update_timer):
            bpy.app.timers.unregister(_background_node_update_timer)
    except Exception:
        pass


# =============================================================================
# GLOBAL PREVIEW COLLECTION FOR NODES
# =============================================================================
node_preview_collection = None


# =============================================================================
# NODE TREE DEFINITION
# =============================================================================

class NeuroGenNodeTree(NodeTree):
    """Node tree for AI image generation workflows"""
    bl_idname = 'NeuroGenNodeTree'
    bl_label = "AI Nodes Editor"
    bl_icon = 'IMAGE_DATA'

    preview_scale: IntProperty(
        name="Preview Scale",
        description="Preview image size multiplier",
        default=12, min=10, max=26
    )

    @classmethod
    def poll(cls, context):
        return True


# =============================================================================
# CUSTOM SOCKETS
# =============================================================================

class NeuroImageSocket(NodeSocket):
    bl_idname = 'NeuroImageSocket'
    bl_label = "Image Socket"
    image_path: StringProperty(name="Image Path", default="")

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.4, 0.8, 0.4, 1.0)  # Green


class NeuroTextSocket(NodeSocket):
    bl_idname = 'NeuroTextSocket'
    bl_label = "Text Socket"
    text_value: StringProperty(name="Text", default="")

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.6, 0.6, 0.6, 1.0)  # Grey


class NeuroHistorySocket(NodeSocket):
    """Socket for passing conversation history between nodes (Gemini 3 Pro only)"""
    bl_idname = 'NeuroHistorySocket'
    bl_label = "History Socket"

    # History is stored as JSON string
    history_data: StringProperty(name="History Data", default="[]")

    def draw(self, context, layout, node, text):
        # Show connection status
        if self.is_linked:
            layout.label(text=text, icon='LINKED')
        else:
            layout.label(text=text)

    def draw_color(self, context, node):
        return (0.9, 0.6, 0.2, 1.0)  # Orange for history


# =============================================================================
# HISTORY MIXIN - Shared image history functionality
# =============================================================================

class HistoryMixin:
    """Mixin for nodes that need image history navigation.

    Requires these properties on the node:
        image_history: StringProperty(default="[]")
        history_index: IntProperty(default=0, min=0)
        result_path: StringProperty()
        model_used: StringProperty()
    """

    def get_history_list(self):
        """Get image history as list of dicts"""
        try:
            history = getattr(self, 'image_history', '[]')
            return json.loads(history) if history else []
        except Exception:
            return []

    def add_to_history(self, path, model=""):
        """Add new image to history"""
        history = self.get_history_list()
        entry = {"path": path, "model": model}
        # Avoid duplicates
        existing_paths = [h.get("path") if isinstance(h, dict) else h for h in history]
        if path not in existing_paths:
            history.append(entry)
        # Limit history size
        if len(history) > 50:
            history = history[-50:]
        self.image_history = json.dumps(history)
        self.history_index = len(history) - 1

    def get_history_entry(self, index):
        """Get history entry at index, returns dict with 'path' and 'model'"""
        history = self.get_history_list()
        if 0 <= index < len(history):
            item = history[index]
            if isinstance(item, dict):
                return item
            return {"path": item, "model": ""}
        return None

    def navigate_history(self, direction):
        """Navigate history by direction (-1 or 1), returns (new_path, new_model) or None"""
        history = self.get_history_list()
        if not history:
            return None

        new_index = self.history_index + direction
        new_index = max(0, min(new_index, len(history) - 1))
        self.history_index = new_index

        entry = self.get_history_entry(new_index)
        if entry:
            return entry.get("path", ""), entry.get("model", "")
        return None


# =============================================================================
# BASE NODE CLASS
# =============================================================================

class NeuroNodeBase:
    """Base mixin for all AI Nodes"""
    _failed_previews = set()

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'NeuroGenNodeTree'

    def get_preview_scale(self):
        if self.id_data and hasattr(self.id_data, 'preview_scale'):
            return self.id_data.preview_scale
        return 12

    def draw_preview(self, layout, image_path):
        global node_preview_collection

        if not image_path or not os.path.exists(image_path):
            return False

        abs_path = os.path.normpath(os.path.abspath(image_path))

        # NOTE: Auto-sync of dirty/packed images is handled by the background timer
        # (_image_sync_timer). Do NOT do file I/O here - it blocks the UI thread.

        # Include file modification time in key to auto-invalidate on file change
        try:
            mtime = os.path.getmtime(image_path)
            key = f"{abs_path}:{mtime}"
        except OSError:
            key = abs_path

        if abs_path in NeuroNodeBase._failed_previews:
            box = layout.box()
            box.label(text="Preview Error", icon='ERROR')
            return False

        if node_preview_collection is None:
            try:
                import bpy.utils.previews
                node_preview_collection = bpy.utils.previews.new()
            except Exception:
                return False

        if key not in node_preview_collection:
            # Clean up old previews for this path (different mtime)
            old_keys = [k for k in node_preview_collection.keys() if k.startswith(abs_path + ":")]
            for old_key in old_keys:
                if old_key != key:
                    try:
                        del node_preview_collection[old_key]
                    except Exception:
                        pass

            try:
                node_preview_collection.load(key, image_path, 'IMAGE')
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to load node preview {key}: {e}")
                NeuroNodeBase._failed_previews.add(abs_path)
                return False

        if key in node_preview_collection:
            scale = self.get_preview_scale()
            layout.template_icon(icon_value=node_preview_collection[key].icon_id, scale=scale)
            return True
        return False

    def _find_blender_image(self, abs_path, img_name):
        """Find Blender image by path or name"""
        import bpy

        # Method 1: By filepath (most reliable)
        for img in bpy.data.images:
            if img.filepath:
                try:
                    img_filepath = os.path.normpath(os.path.abspath(bpy.path.abspath(img.filepath)))
                    if img_filepath == abs_path:
                        return img
                except Exception:
                    pass

        # Method 2: By exact name
        img = bpy.data.images.get(img_name)
        if img:
            return img

        # Method 3: Partial name match (handles Blender's .001 suffix)
        base_name = os.path.splitext(img_name)[0]
        for img in bpy.data.images:
            if base_name in img.name or img.name.startswith(base_name):
                return img

        return None

    def _auto_save_image(self, blender_img, target_path):
        """Auto-save dirty/packed image to disk for preview sync"""
        import bpy

        try:
            # Ensure filepath is set
            if not blender_img.filepath:
                blender_img.filepath_raw = target_path

            # Save the image (handles both dirty and packed)
            if blender_img.packed_file:
                # For packed images, save directly
                blender_img.filepath_raw = target_path
                blender_img.save()
            elif blender_img.is_dirty:
                blender_img.save()

            # Reload to clear dirty flag
            blender_img.reload()

        except Exception as e:
            # Fallback: try save_render
            try:
                blender_img.save_render(target_path)
            except Exception:
                pass  # Silently fail - don't break the UI

    def draw_action_row(self, layout, main_operator, main_text, main_icon,
                        cancel_operator=None, show_view=True, show_remove_bg=True):
        """Draw standardized action row: [View Full] [Main Action] [Remove BG]

        Args:
            layout: Blender UI layout
            main_operator: bl_idname of main action operator
            main_text: Button text
            main_icon: Button icon
            cancel_operator: bl_idname of cancel operator (shown during processing)
            show_view: Show view full image button
            show_remove_bg: Show remove background button
        """
        is_processing = getattr(self, 'is_processing', False) or getattr(self, 'is_generating', False)
        result_path = getattr(self, 'result_path', '')
        has_result = result_path and os.path.exists(result_path)

        row = layout.row(align=True)
        row.scale_y = 1.15

        if is_processing and cancel_operator:
            row.operator(cancel_operator, text="Cancel", icon='CANCEL').node_name = self.name
        else:
            # View Full Image (left)
            if show_view and has_result:
                op = row.operator("neuro.node_view_full_image", text="", icon='FULLSCREEN_ENTER')
                op.image_path = result_path

            # Main action button
            row.operator(main_operator, text=main_text, icon=main_icon).node_name = self.name

            # Remove BG (right)
            if show_remove_bg and has_result:
                row.operator("neuro.node_remove_bg", text="", icon='IMAGE_RGB_ALPHA' ).node_name = self.name

        return row