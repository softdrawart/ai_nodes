# -*- coding: utf-8 -*-
import os
import time
import zipfile
import json
import shutil
from datetime import datetime

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty, CollectionProperty
from bpy.types import Operator

from .utils import (
    refresh_previews_and_collections, get_generations_folder,
    get_unique_filename, log_verbose
)
from .nodes_core import NeuroNodeBase, node_preview_collection
from .nodes_ops_common import get_node_tree
from .constants import LOG_PREFIX


# =============================================================================
# UI HELPER OPERATORS
# =============================================================================

class NEURO_OT_refresh_node_preview(Operator):
    """Force refresh preview - saves edited image to disk and reloads preview"""
    bl_idname = "neuro.refresh_node_preview"
    bl_label = "Refresh Preview"
    node_name: StringProperty()

    def execute(self, context):
        from . import nodes_core

        NeuroNodeBase._failed_previews.clear()

        ntree = get_node_tree(context, None)
        if not ntree or not self.node_name:
            self.report({'WARNING'}, "No node specified")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'WARNING'}, "Node not found")
            return {'CANCELLED'}

        # Get image path from node
        path = ""
        if hasattr(node, 'get_image_path'):
            path = node.get_image_path()
        elif hasattr(node, 'result_path'):
            path = node.result_path

        if not path:
            self.report({'WARNING'}, "No image path")
            return {'CANCELLED'}

        abs_path = os.path.normpath(os.path.abspath(path))
        img_name = os.path.basename(path)
        print(f"[{LOG_PREFIX} Refresh] Looking for image: {img_name}")
        print(f"[{LOG_PREFIX} Refresh] Full path: {abs_path}")

        # STEP 1: Find ALL Blender images that might be related to this path
        # Check multiple matching criteria
        matching_images = []

        for img in bpy.data.images:
            match = False
            match_reason = ""

            # Check 1: Exact name match
            if img.name == img_name:
                match = True
                match_reason = "exact name"

            # Check 2: Name without extension
            elif os.path.splitext(img.name)[0] == os.path.splitext(img_name)[0]:
                match = True
                match_reason = "name without ext"

            # Check 3: Filepath match
            elif img.filepath:
                try:
                    img_filepath = os.path.normpath(os.path.abspath(bpy.path.abspath(img.filepath)))
                    if img_filepath == abs_path:
                        match = True
                        match_reason = "filepath"
                except Exception:
                    pass

            # Check 4: Partial name match (handle Blender's name mangling like .001)
            elif img_name.split('.')[0] in img.name or img.name.split('.')[0] in img_name:
                match = True
                match_reason = "partial name"

            if match:
                matching_images.append((img, match_reason))
                print(f"[{LOG_PREFIX} Refresh] Found match: '{img.name}' via {match_reason}")

        # STEP 2: Save all matching images to disk
        saved = False
        for img, reason in matching_images:
            print(
                f"[{LOG_PREFIX} Refresh] Processing: {img.name} (dirty={img.is_dirty}, packed={img.packed_file is not None})")

            try:
                # Ensure filepath is set
                if not img.filepath:
                    img.filepath_raw = path
                    print(f"[{LOG_PREFIX} Refresh] Set filepath to: {path}")

                # Handle packed images
                if img.packed_file:
                    print(f"[{LOG_PREFIX} Refresh] Image is packed, unpacking...")
                    try:
                        # Save the packed data to the file path
                        img.filepath_raw = path
                        img.save()
                        saved = True
                        print(f"[{LOG_PREFIX} Refresh] Saved packed image directly")
                    except Exception as e:
                        print(f"[{LOG_PREFIX} Refresh] Direct save failed: {e}")
                        try:
                            img.save_render(path)
                            saved = True
                            print(f"[{LOG_PREFIX} Refresh] Saved via save_render")
                        except Exception as e2:
                            print(f"[{LOG_PREFIX} Refresh] save_render failed: {e2}")

                # Handle dirty (modified) images
                elif img.is_dirty:
                    print(f"[{LOG_PREFIX} Refresh] Image is dirty, saving...")
                    try:
                        img.save()
                        saved = True
                        print(f"[{LOG_PREFIX} Refresh] Saved dirty image")
                    except Exception as e:
                        print(f"[{LOG_PREFIX} Refresh] Save failed: {e}")
                        try:
                            img.filepath_raw = path
                            img.save()
                            saved = True
                        except Exception:
                            try:
                                img.save_render(path)
                                saved = True
                            except Exception:
                                pass

                # Reload from disk
                img.reload()
                print(f"[{LOG_PREFIX} Refresh] Reloaded: {img.name}")

            except Exception as e:
                print(f"[{LOG_PREFIX} Refresh] Error processing {img.name}: {e}")

        # STEP 3: Clear ALL preview cache entries (aggressive clearing)
        if nodes_core.node_preview_collection:
            # Clear entries that match this path in any way
            keys_to_remove = []
            for key in list(nodes_core.node_preview_collection.keys()):
                # Match by full path prefix
                if key.startswith(abs_path):
                    keys_to_remove.append(key)
                # Also match by filename in case paths differ
                elif img_name in key:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                try:
                    del nodes_core.node_preview_collection[key]
                    print(f"[{LOG_PREFIX} Refresh] Removed cache: {key}")
                except Exception:
                    pass

            print(f"[{LOG_PREFIX} Refresh] Cleared {len(keys_to_remove)} cache entries")

        # STEP 4: Touch file to update mtime (forces preview reload)
        if os.path.exists(path):
            try:
                os.utime(path, None)
                print(f"[{LOG_PREFIX} Refresh] Touched file: {path}")
            except OSError as e:
                print(f"[{LOG_PREFIX} Refresh] Could not touch file: {e}")

        # STEP 5: Force redraw all node editor areas
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.tag_redraw()

        if saved:
            self.report({'INFO'}, "Image saved and preview refreshed")
        else:
            self.report({'INFO'}, "Preview cache cleared")

        return {'FINISHED'}


class NEURO_OT_node_history_nav(Operator):
    """Navigate through node's generated image history"""
    bl_idname = "neuro.node_history_nav"
    bl_label = "Navigate History"

    node_name: StringProperty()
    direction: IntProperty(default=1)  # 1 = next, -1 = previous

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node or not hasattr(node, 'get_history_list'):
            return {'CANCELLED'}

        history = node.get_history_list()
        if not history:
            return {'CANCELLED'}

        # Calculate new index
        new_index = node.history_index + self.direction
        new_index = max(0, min(new_index, len(history) - 1))

        # Update node
        node.history_index = new_index

        # Get entry (handles both old string format and new dict format)
        entry = node.get_history_entry(new_index) if hasattr(node, 'get_history_entry') else None
        if entry:
            new_path = entry.get("path", "")
            new_model = entry.get("model", "")
        else:
            # Fallback for old format
            item = history[new_index]
            new_path = item if isinstance(item, str) else item.get("path", "")
            new_model = ""

        if new_path and os.path.exists(new_path):
            node.result_path = new_path
            if new_model:
                node.model_used = new_model

            # Invalidate old preview to force refresh
            if node_preview_collection:
                key = os.path.normpath(os.path.abspath(new_path))
                if key in node_preview_collection:
                    try:
                        del node_preview_collection[key]
                    except Exception:
                        pass

        if context.area:
            context.area.tag_redraw()

        return {'FINISHED'}


class NEURO_OT_node_double_click_view(Operator):
    """Double-click a node to view its image in Image Editor"""
    bl_idname = "neuro.node_double_click_view"
    bl_label = "View Node Image"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (context.area and context.area.type == 'NODE_EDITOR' and
                context.space_data and hasattr(context.space_data, 'tree_type') and
                context.space_data.tree_type == 'NeuroGenNodeTree')

    def invoke(self, context, event):
        # Get the node under the mouse
        ntree = context.space_data.node_tree
        if not ntree:
            return {'PASS_THROUGH'}

        # Find active node (Blender sets this on click, which happens before double-click)
        node = ntree.nodes.active
        if not node:
            return {'PASS_THROUGH'}

        # Get image path from the node
        image_path = None

        # Special: Merge Design node — cycle active result on double-click (A→B→C→D)
        if node.bl_idname == 'NeuroMergeStyleNode' and hasattr(node, 'active_result'):
            slots = ['A', 'B', 'C', 'D']
            paths = {
                'A': node.result_path_a, 'B': node.result_path_b,
                'C': node.result_path_c, 'D': node.result_path_d,
            }
            cur = node.active_result
            idx = slots.index(cur) if cur in slots else 0
            for i in range(1, 5):
                nxt = slots[(idx + i) % 4]
                p = paths.get(nxt, "")
                if p and os.path.exists(p):
                    node.active_result = nxt
                    image_path = p
                    break

            if image_path:
                bpy.ops.neuro.node_view_full_image(image_path=image_path)
                return {'FINISHED'}

        # Special: Reference node — cycle through images on double-click
        if node.bl_idname == 'NeuroReferenceNode' and hasattr(node, 'get_image_paths_list'):
            paths = node.get_image_paths_list()
            if len(paths) > 1:
                idx = min(node.current_index, len(paths) - 1)
                new_idx = (idx + 1) % len(paths)
                node.current_index = new_idx
                node.image_path = paths[new_idx]
                bpy.ops.neuro.node_view_full_image(image_path=paths[new_idx])
                return {'FINISHED'}
            elif len(paths) == 1:
                bpy.ops.neuro.node_view_full_image(image_path=paths[0])
                return {'FINISHED'}

        # Priority 1: result_path (Generate, Inpaint, Tools, etc.)
        if hasattr(node, 'result_path') and node.result_path:
            if os.path.exists(node.result_path):
                image_path = node.result_path

        # Priority 2: get_image_path() (Reference nodes, etc.)
        if not image_path and hasattr(node, 'get_image_path'):
            try:
                path = node.get_image_path()
                if path and os.path.exists(path):
                    image_path = path
            except Exception:
                pass

        if not image_path:
            # Not a node with an image, let Blender handle the double-click normally
            return {'PASS_THROUGH'}

        # Open the image — reuse existing view_full_image operator
        bpy.ops.neuro.node_view_full_image(image_path=image_path)
        return {'FINISHED'}


class NEURO_OT_node_view_full_image(Operator):
    bl_idname = "neuro.node_view_full_image"
    bl_label = "View Full Image"
    image_path: StringProperty()

    def execute(self, context):
        if not self.image_path or not os.path.exists(self.image_path):
            return {'CANCELLED'}

        abs_path = os.path.abspath(self.image_path)
        img_name = os.path.basename(self.image_path)

        # Find existing image first (avoid duplicates)
        img = None

        # Method 1: Find by filepath (most reliable — handles autopack/Save As)
        for existing_img in bpy.data.images:
            if existing_img.filepath:
                try:
                    existing_path = os.path.abspath(bpy.path.abspath(existing_img.filepath))
                    if existing_path == abs_path:
                        img = existing_img
                        break
                except Exception:
                    pass

        # Method 2: Find by name ONLY if filepath matches too
        # (Don't use bare name lookup — causes cross-node image collision after Save As)
        if not img:
            candidate = bpy.data.images.get(img_name)
            if candidate and candidate.filepath:
                try:
                    if os.path.abspath(bpy.path.abspath(candidate.filepath)) == abs_path:
                        img = candidate
                except Exception:
                    pass

        # Method 3: Load fresh only if not found
        if not img:
            img = bpy.data.images.load(self.image_path)
        else:
            # Reload to get latest version
            img.reload()

        # Find Image Editor — if none exists, open a new window
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = img
                return {'FINISHED'}

        # No Image Editor found — open new window
        try:
            bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
            # The new window's area defaults to whatever was duplicated,
            # so find it and switch to IMAGE_EDITOR
            new_window = context.window_manager.windows[-1]
            for area in new_window.screen.areas:
                area.type = 'IMAGE_EDITOR'
                area.spaces.active.image = img
                break
        except Exception:
            # Fallback: just split current area
            try:
                override = context.copy()
                for area in context.screen.areas:
                    if area.type in ('NODE_EDITOR', 'VIEW_3D', 'PROPERTIES'):
                        override['area'] = area
                        break
                with context.temp_override(**override):
                    bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)
                # Find the newly created area (last IMAGE_EDITOR type after split)
                for area in context.screen.areas:
                    if area.type == override['area'].type:
                        area.type = 'IMAGE_EDITOR'
                        area.spaces.active.image = img
                        break
            except Exception as e:
                print(f"[{LOG_PREFIX}] Could not open Image Editor: {e}")

        return {'FINISHED'}


class NEURO_OT_node_open_paint_smart(Operator):
    """Open image in configured editor (Blender paint or Photoshop)"""
    bl_idname = "neuro.node_open_paint_smart"
    bl_label = "Open in Editor"
    node_name: StringProperty()

    def execute(self, context):
        import bpy as _bpy
        editor = 'BLENDER'
        for pkg in [__package__, "ai_nodes"]:
            if pkg and pkg in context.preferences.addons:
                editor = getattr(context.preferences.addons[pkg].preferences, 'editor_type', 'BLENDER')
                break

        if editor == 'BLENDER':
            return _bpy.ops.neuro.node_open_paint(node_name=self.node_name)

        # ── PHOTOSHOP MODE ─────────────────────────────────────────────
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Already a PS Bridge node — open in PS directly
        if node.bl_idname == 'NeuroPSBridgeNode':
            return _bpy.ops.neuro.ps_edit(node_name=node.name)

        # Verify we have an image
        img_path = None
        if hasattr(node, 'result_path') and node.result_path and os.path.exists(node.result_path):
            img_path = node.result_path
        elif hasattr(node, 'get_image_path'):
            img_path = node.get_image_path()
        if not img_path or not os.path.exists(img_path):
            self.report({'WARNING'}, "No image to open")
            return {'CANCELLED'}

        # Create PS Bridge node beside source
        ps_node = ntree.nodes.new('NeuroPSBridgeNode')
        ps_node.location = (node.location.x + node.width + 50, node.location.y)

        # Connect first visible image output → PS Bridge input
        for sock in node.outputs:
            if sock.bl_idname == 'NeuroImageSocket' and not sock.hide:
                ps_in = ps_node.inputs.get("Image")
                if ps_in:
                    ntree.links.new(sock, ps_in)
                break

        _bpy.ops.neuro.ps_edit(node_name=ps_node.name)
        return {'FINISHED'}


class NEURO_OT_node_open_paint(Operator):
    """Open image in new window with Paint Mode"""
    bl_idname = "neuro.node_open_paint"
    bl_label = "Open in Paint Mode"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)

        # Determine the image path based on node type
        img_path = None

        # 1. Try result_path (NeuroGenerateNode)
        if hasattr(node, 'result_path') and node.result_path:
            img_path = node.result_path

        # 2. If not found, try get_image_path() (NeuroReferenceNode, Splitter, etc.)
        if (not img_path or not os.path.exists(img_path)) and hasattr(node, 'get_image_path'):
            img_path = node.get_image_path()

        # 3. Verify existence
        if not img_path or not os.path.exists(img_path):
            self.report({'WARNING'}, "No image to open")
            return {'CANCELLED'}

        # Save backup before editing (PrePaint save)
        try:
            backup_dir = os.path.join(os.path.dirname(img_path), "_prepaint_backups")
            os.makedirs(backup_dir, exist_ok=True)

            base_name = os.path.splitext(os.path.basename(img_path))[0]
            ext = os.path.splitext(img_path)[1]
            backup_path = os.path.join(backup_dir, f"{base_name}_backup{ext}")

            # Only create backup if not already exists or image is newer
            if not os.path.exists(backup_path) or os.path.getmtime(img_path) > os.path.getmtime(backup_path):
                import shutil
                shutil.copy2(img_path, backup_path)
                print(f"[{LOG_PREFIX} Paint] Created backup: {backup_path}")

            # Store backup path in node for revert
            if hasattr(node, 'prepaint_backup'):
                node.prepaint_backup = backup_path

        except Exception as e:
            print(f"[{LOG_PREFIX} Paint] Backup failed: {e}")

        abs_path = os.path.abspath(img_path)
        img_name = os.path.basename(img_path)

        # Load/get the image - prefer finding by filepath first
        img = None

        # Method 1: Find by filepath (most reliable — handles autopack/Save As)
        for existing_img in bpy.data.images:
            if existing_img.filepath:
                try:
                    existing_path = os.path.abspath(bpy.path.abspath(existing_img.filepath))
                    if existing_path == abs_path:
                        img = existing_img
                        break
                except Exception:
                    pass

        # Method 2: Find by name ONLY if filepath matches too
        # (Don't use bare name lookup — causes cross-node image collision after Save As)
        if not img:
            candidate = bpy.data.images.get(img_name)
            if candidate and candidate.filepath:
                try:
                    if os.path.abspath(bpy.path.abspath(candidate.filepath)) == abs_path:
                        img = candidate
                except Exception:
                    pass

        # Method 3: Load fresh
        if not img:
            try:
                img = bpy.data.images.load(img_path)
                print(f"[{LOG_PREFIX} Paint] Loaded new image: {img.name}")
            except Exception:
                self.report({'ERROR'}, f"Could not load image: {img_path}")
                return {'CANCELLED'}

        # CRITICAL: Ensure filepath is set correctly (prevents "Image not available" errors)
        if not img.filepath or img.filepath == "":
            img.filepath_raw = abs_path
            print(f"[{LOG_PREFIX} Paint] Set filepath: {abs_path}")

        # Reload from disk to ensure we have latest version
        try:
            img.reload()
        except Exception:
            pass

        # Open new window
        bpy.ops.wm.window_new()
        new_window = context.window_manager.windows[-1]

        # Change area to Image Editor in Paint mode
        for area in new_window.screen.areas:
            area.type = 'IMAGE_EDITOR'
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = img
                    space.mode = 'PAINT'
            break

        # Deferred brush setup — must wait for new window to process events
        def _setup_brush():
            try:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'IMAGE_EDITOR':
                            for space in area.spaces:
                                if space.type == 'IMAGE_EDITOR' and space.mode == 'PAINT':
                                    # Found the paint window — override context to set brush
                                    with bpy.context.temp_override(window=window, area=area):
                                        brush = bpy.context.tool_settings.image_paint.brush
                                        if brush:
                                            brush.color = (0.596, 0.0, 0.753)  # #9800C0 purple
                                            brush.strength = 0.5
                                            brush.size = 50
                                    return None  # Done, stop timer
            except Exception as e:
                print(f"[{LOG_PREFIX} Paint] Brush setup: {e}")
            return None

        bpy.app.timers.register(_setup_brush, first_interval=0.3)

        self.report({'INFO'}, f"Editing: {img_name} - Press Refresh button after saving")
        return {'FINISHED'}


class NEURO_OT_node_revert_paint(Operator):
    """Revert image to pre-paint backup"""
    bl_idname = "neuro.node_revert_paint"
    bl_label = "Revert to Backup"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get current image path
        img_path = None
        if hasattr(node, 'result_path') and node.result_path:
            img_path = node.result_path
        elif hasattr(node, 'get_image_path'):
            img_path = node.get_image_path()

        if not img_path:
            self.report({'WARNING'}, "No image to revert")
            return {'CANCELLED'}

        # Find backup
        backup_path = None
        if hasattr(node, 'prepaint_backup') and node.prepaint_backup:
            backup_path = node.prepaint_backup
        else:
            # Try to find backup in standard location
            backup_dir = os.path.join(os.path.dirname(img_path), "_prepaint_backups")
            base_name = os.path.splitext(os.path.basename(img_path))[0]
            ext = os.path.splitext(img_path)[1]
            backup_path = os.path.join(backup_dir, f"{base_name}_backup{ext}")

        if not backup_path or not os.path.exists(backup_path):
            self.report({'WARNING'}, "No backup found")
            return {'CANCELLED'}

        # Restore backup
        try:
            import shutil
            shutil.copy2(backup_path, img_path)

            # Reload image in Blender
            for img in bpy.data.images:
                if img.filepath:
                    try:
                        existing_path = os.path.abspath(bpy.path.abspath(img.filepath))
                        if existing_path == os.path.abspath(img_path):
                            img.reload()
                            break
                    except Exception:
                        pass

            self.report({'INFO'}, "Reverted to backup")
        except Exception as e:
            self.report({'ERROR'}, f"Revert failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class NEURO_OT_node_copy_image_file(bpy.types.Operator):
    """Copy image file to clipboard (Windows only)"""
    bl_idname = "neuro.node_copy_image_file"
    bl_label = "Copy Image"

    image_path: bpy.props.StringProperty()

    def execute(self, context):
        import subprocess
        import os

        path = os.path.abspath(self.image_path)
        if not os.path.exists(path):
            self.report({'WARNING'}, "Image file not found")
            return {'CANCELLED'}

        try:
            # PowerShell command to copy the FILE to clipboard (works for pasting in Discord/Explorer/PS)
            cmd = f'powershell -c "Set-Clipboard -Path \'{path}\'"'
            subprocess.run(cmd, shell=True)
            self.report({'INFO'}, "Image copied to clipboard")
        except Exception as e:
            self.report({'ERROR'}, f"Copy failed: {e}")

        return {'FINISHED'}


class NEURO_OT_node_toggle_inpaint(Operator):
    """Paint over the area you want to change with the purple brush, """  \
    """then enable this toggle. Your prompt will only affect the painted zone — """  \
    """everything else stays untouched.\n"""  \
    """Tip: Use with 'Open Paint' button. """  \
    """Works best with Nano Banana (Google) models"""
    bl_idname = "neuro.node_toggle_inpaint"
    bl_label = "Toggle Inpaint"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node or not hasattr(node, 'use_inpaint'):
            return {'CANCELLED'}

        node.use_inpaint = not node.use_inpaint

        if node.use_inpaint:
            self.report({'INFO'}, "Inpaint ON — generation targets painted area only")
        else:
            self.report({'INFO'}, "Inpaint OFF — normal generation")
        return {'FINISHED'}


# =============================================================================
# FILE / LOAD / IMPORT OPERATORS
# =============================================================================

class NEURO_OT_node_load_file(Operator):
    bl_idname = "neuro.node_load_file"
    bl_label = "Load"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        node = ntree.nodes.get(self.node_name)
        path = bpy.path.abspath(node.file_path)
        if os.path.exists(path):
            node.image_path = path
            node.status_message = "Loaded"
        else:
            node.status_message = "Not found"
        return {'FINISHED'}


class NEURO_OT_node_load_files_multi(Operator):
    """Load multiple images into a single Reference node with grid preview"""
    bl_idname = "neuro.node_load_files_multi"
    bl_label = "Load Multiple Images"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    node_name: StringProperty(default="")
    tree_name: StringProperty(default="")

    def invoke(self, context, event):
        if context.space_data and hasattr(context.space_data, 'node_tree') and context.space_data.node_tree:
            self.tree_name = context.space_data.node_tree.name
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        ntree = get_node_tree(context, self.tree_name or None)
        if not ntree:
            return {'CANCELLED'}

        node = None
        if self.node_name:
            node = ntree.nodes.get(self.node_name)
        if not node:
            node = ntree.nodes.new('NeuroReferenceNode')
            node.location = (0, 0)

        image_paths = []
        for f in self.files:
            filepath = os.path.join(self.directory, f.name)
            if os.path.exists(filepath):
                image_paths.append(filepath)

        if image_paths:
            node.set_image_paths_list(image_paths)
            node.image_path = image_paths[0]  # backward compat for single-image display
            node.source_type = 'FILE'
            node.status_message = f"Loaded {len(image_paths)} images"

        # Force redraw of node editor areas
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.tag_redraw()

        return {'FINISHED'}


class NEURO_OT_node_ref_navigate(Operator):
    """Navigate between loaded images in Reference node"""
    bl_idname = "neuro.node_ref_navigate"
    bl_label = "Navigate Images"
    node_name: StringProperty()
    direction: IntProperty(default=1)  # +1 = next, -1 = prev

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node: return {'CANCELLED'}

        paths = node.get_image_paths_list()
        if len(paths) < 2: return {'FINISHED'}

        new_idx = (node.current_index + self.direction) % len(paths)
        node.current_index = new_idx
        node.image_path = paths[new_idx]

        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class NEURO_OT_node_ref_clear(Operator):
    """Clear all images from Reference node"""
    bl_idname = "neuro.node_ref_clear"
    bl_label = "Clear Images"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree: return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if node and hasattr(node, 'clear_images'):
            node.clear_images()
            node.status_message = ""

        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class NEURO_OT_node_from_editor(Operator):
    bl_idname = "neuro.node_from_editor"
    bl_label = "From Editor"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        node = ntree.nodes.get(self.node_name)
        img = None
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR' and area.spaces.active.image:
                img = area.spaces.active.image
                break
        if not img: return {'CANCELLED'}

        if img.filepath and os.path.exists(bpy.path.abspath(img.filepath)):
            node.image_path = bpy.path.abspath(img.filepath)
            node.status_message = "Loaded"
        else:
            ref_dir = get_generations_folder("references")
            save_path = os.path.join(ref_dir, f"editor_{datetime.now().strftime('%H%M%S')}.png")
            try:
                img.save_render(save_path)
                node.image_path = save_path
                node.status_message = "Saved"
            except Exception:
                node.status_message = "Error"
        return {'FINISHED'}


class NEURO_OT_node_load_blender_image(Operator):
    """Load selected Blender image to disk for API use"""
    bl_idname = "neuro.node_load_blender_image"
    bl_label = "Load Blender Image"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        node = ntree.nodes.get(self.node_name)
        img = bpy.data.images.get(node.blender_image)
        if not img: return {'CANCELLED'}

        if img.filepath and os.path.exists(bpy.path.abspath(img.filepath)):
            node.image_path = bpy.path.abspath(img.filepath)
            node.status_message = f"Loaded: {node.blender_image}"
        else:
            ref_dir = get_generations_folder("references")
            save_path = os.path.join(ref_dir, f"blender_{datetime.now().strftime('%H%M%S')}.png")
            try:
                img.save_render(save_path)
                node.image_path = save_path
                node.status_message = f"Saved: {node.blender_image}"
            except Exception:
                node.status_message = "Error saving"
        return {'FINISHED'}


class NEURO_OT_node_from_render(Operator):
    """Grab current Render Result"""
    bl_idname = "neuro.node_from_render"
    bl_label = "From Render"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        node = ntree.nodes.get(self.node_name)
        img = bpy.data.images.get('Render Result')
        if not img: return {'CANCELLED'}

        ref_dir = get_generations_folder("references")
        save_path = os.path.join(ref_dir, f"render_{datetime.now().strftime('%H%M%S')}.png")
        try:
            img.save_render(save_path)
            node.image_path = save_path
            node.status_message = "Render grabbed"
        except Exception:
            node.status_message = "Error"
        return {'FINISHED'}


class NEURO_OT_node_from_clipboard(Operator):
    bl_idname = "neuro.node_from_clipboard"
    bl_label = "Paste"
    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        node = ntree.nodes.get(self.node_name)
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if not img: return {'CANCELLED'}
            ref_dir = get_generations_folder("references")
            save_path = os.path.join(ref_dir, f"clip_{datetime.now().strftime('%H%M%S')}.png")
            img.save(save_path, format="PNG")
            node.image_path = save_path
            node.status_message = "Pasted"
        except Exception:
            node.status_message = "Error"
        return {'FINISHED'}


# =============================================================================
# NODE GRAPH UTILS (Duplicate, Connect, Run Batch, Export/Import)
# =============================================================================

class NEURO_OT_duplicate_nodes(Operator):
    """Duplicate selected nodes with their connections"""
    bl_idname = "neuro.duplicate_nodes"
    bl_label = "Duplicate Nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if not ntree:
            return {'CANCELLED'}

        selected = [n for n in ntree.nodes if n.select]
        if not selected:
            return {'CANCELLED'}

        # Store links that connect selected nodes to each other
        internal_links = []
        # Store links from external nodes TO selected nodes (inputs)
        input_links = []

        for link in ntree.links:
            from_selected = link.from_node in selected
            to_selected = link.to_node in selected

            if from_selected and to_selected:
                # Internal link between selected nodes
                internal_links.append({
                    'from_node': link.from_node.name,
                    'from_socket': link.from_socket.name,
                    'to_node': link.to_node.name,
                    'to_socket': link.to_socket.name,
                })
            elif to_selected and not from_selected:
                # External node connects TO a selected node
                input_links.append({
                    'from_node': link.from_node.name,
                    'from_socket': link.from_socket.name,
                    'to_node': link.to_node.name,
                    'to_socket': link.to_socket.name,
                })

        # Create duplicates
        node_map = {}  # old_name -> new_node
        offset = (50, -50)

        for node in selected:
            # Create new node of same type
            try:
                new_node = ntree.nodes.new(node.bl_idname)
            except Exception as e:
                print(f"[{LOG_PREFIX}] Failed to duplicate node {node.name}: {e}")
                continue

            # Copy location with offset
            new_node.location = (node.location.x + offset[0], node.location.y + offset[1])
            new_node.width = node.width

            # Copy properties
            for prop in node.bl_rna.properties:
                if prop.is_readonly:
                    continue
                if prop.identifier in ('rna_type', 'name', 'select', 'location', 'width', 'height'):
                    continue
                # Skip generation state properties
                if prop.identifier in ('is_generating', 'is_processing', 'progress'):
                    continue
                try:
                    val = getattr(node, prop.identifier)
                    setattr(new_node, prop.identifier, val)
                except Exception:
                    pass

            node_map[node.name] = new_node

        # Recreate internal links between duplicated nodes
        for link_data in internal_links:
            from_node = node_map.get(link_data['from_node'])
            to_node = node_map.get(link_data['to_node'])
            if from_node and to_node:
                from_socket = from_node.outputs.get(link_data['from_socket'])
                to_socket = to_node.inputs.get(link_data['to_socket'])
                if from_socket and to_socket:
                    try:
                        ntree.links.new(from_socket, to_socket)
                    except Exception:
                        pass

        # Recreate input links (from external nodes to new duplicates)
        for link_data in input_links:
            from_node = ntree.nodes.get(link_data['from_node'])
            to_node = node_map.get(link_data['to_node'])
            if from_node and to_node:
                from_socket = from_node.outputs.get(link_data['from_socket'])
                to_socket = to_node.inputs.get(link_data['to_socket'])
                if from_socket and to_socket:
                    try:
                        ntree.links.new(from_socket, to_socket)
                    except Exception:
                        pass

        # Deselect old nodes, select new ones
        for node in selected:
            node.select = False
        for new_node in node_map.values():
            new_node.select = True

        # Set active node
        if node_map:
            ntree.nodes.active = list(node_map.values())[0]

        # Start transform (move) mode
        bpy.ops.transform.translate('INVOKE_DEFAULT')

        return {'FINISHED'}


class NEURO_OT_auto_connect_nodes(Operator):
    """Auto-connect selected nodes. Connects all compatible socket pairs."""
    bl_idname = "neuro.auto_connect_nodes"
    bl_label = "Auto Connect"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if not ntree: return {'CANCELLED'}

        selected = [n for n in ntree.nodes if n.select]
        if len(selected) != 2:
            self.report({'INFO'}, "Select exactly 2 nodes")
            return {'CANCELLED'}

        n1, n2 = selected[0], selected[1]
        # Sort by X location (left node is source)
        if n1.location.x > n2.location.x:
            n1, n2 = n2, n1

        # Check for Splitter -> Tripo multiview special case
        if n1.bl_idname == 'NeuroImageSplitterNode' and n2.bl_idname == 'TripoGenerateNode':
            n2.generation_mode = 'MULTIVIEW'
            # Map by position, not name (handles both Universal and MultiView modes)
            splitter_outputs = [s for s in n1.outputs if s.bl_idname == 'NeuroImageSocket']
            tripo_inputs_names = ["Front", "Left", "Right", "Back"]  # or "Image" for Front
            for i, in_name in enumerate(tripo_inputs_names):
                if i < len(splitter_outputs):
                    in_sock = n2.inputs.get(in_name) or (n2.inputs.get("Image") if in_name == "Front" else None)
                    if splitter_outputs[i] and in_sock and not in_sock.is_linked:
                        ntree.links.new(splitter_outputs[i], in_sock)
            return {'FINISHED'}

        # Define node types that have prompts we don't want to cross-connect
        prompt_node_types = {'NeuroGenerateNode', 'NeuroArtistToolsNode', 'NeuroDesignVariationsNode'}
        both_are_prompt_nodes = n1.bl_idname in prompt_node_types and n2.bl_idname in prompt_node_types

        # Standard auto-connect: ALL compatible socket pairs
        connected = 0

        # Group sockets by type for smarter matching
        socket_type_priority = [
            'NeuroImageSocket',  # Images first
            'NeuroHistorySocket',  # History second
            'NeuroTextSocket',  # Text last
        ]

        for socket_type in socket_type_priority:
            for out in n1.outputs:
                if out.bl_idname != socket_type or out.hide:
                    continue

                # Skip Prompt output when connecting between two generation/edit nodes
                if both_are_prompt_nodes and socket_type == 'NeuroTextSocket' and out.name == "Prompt Out":
                    continue

                for inp in n2.inputs:
                    if inp.bl_idname != socket_type or inp.hide or inp.is_linked:
                        continue

                    # Skip Prompt input when connecting between two generation/edit nodes
                    if both_are_prompt_nodes and socket_type == 'NeuroTextSocket' and inp.name == "Prompt In":
                        continue

                    # Match by name if possible, otherwise first available
                    if out.name == inp.name or not any(
                            o.name == inp.name for o in n1.outputs if o.bl_idname == socket_type):
                        ntree.links.new(out, inp)
                        connected += 1
                        break  # Move to next output

        # Fallback: try any remaining unconnected compatible pairs
        for out in n1.outputs:
            if out.hide:
                continue

            # Skip Prompt in fallback too
            if both_are_prompt_nodes and out.bl_idname == 'NeuroTextSocket' and out.name == "Prompt Out":
                continue

            for inp in n2.inputs:
                if out.bl_idname == inp.bl_idname and not inp.is_linked and not inp.hide:
                    # Skip Prompt input
                    if both_are_prompt_nodes and inp.bl_idname == 'NeuroTextSocket' and inp.name == "Prompt In":
                        continue
                    ntree.links.new(out, inp)
                    connected += 1
                    break

        if connected > 0:
            self.report({'INFO'}, f"Connected {connected} socket(s)")
            return {'FINISHED'}

        self.report({'WARNING'}, "No compatible sockets found")
        return {'CANCELLED'}


class NEURO_OT_run_selection(Operator):
    """Run all selected Generate, Upgrade, and Text nodes - parallel when possible"""
    bl_idname = "neuro.run_selection"
    bl_label = "Run Selection"
    bl_description = "Run selected nodes (independent nodes run in parallel)"
    bl_options = {'REGISTER'}

    _dependencies = {}
    _node_types = {}
    _completed = set()
    _running = set()
    _failed = set()
    _run_tree = ""
    _timer_running = False

    @classmethod
    def poll(cls, context):
        if not (context.space_data and hasattr(context.space_data,
                                               'tree_type') and context.space_data.tree_type == 'NeuroGenNodeTree' and context.space_data.node_tree):
            return False
        runnable = {'NeuroGenerateNode', 'NeuroUpgradePromptNode', 'NeuroTextGenNode'}
        return any(n.select and n.bl_idname in runnable for n in context.space_data.node_tree.nodes)

    def execute(self, context):
        ntree = context.space_data.node_tree
        cls = NEURO_OT_run_selection
        runnable = {'NeuroGenerateNode', 'NeuroUpgradePromptNode', 'NeuroTextGenNode'}

        nodes = [n for n in ntree.nodes if n.select and n.bl_idname in runnable]
        if not nodes:
            self.report({'ERROR'}, "No runnable nodes selected")
            return {'CANCELLED'}

        print("-" * 30)
        print(f"[{LOG_PREFIX} Batch] Init: {len(nodes)} nodes")

        names = {n.name for n in nodes}
        cls._dependencies = {n.name: set() for n in nodes}
        cls._node_types = {n.name: n.bl_idname for n in nodes}

        for n in nodes:
            for inp in n.inputs:
                if inp.is_linked:
                    for link in inp.links:
                        if link.from_node.name in names:
                            cls._dependencies[n.name].add(link.from_node.name)

        cls._completed = set()
        cls._running = set()
        cls._failed = set()
        cls._run_tree = ntree.name

        ready = [n for n, deps in cls._dependencies.items() if not deps]
        if not ready:
            self.report({'ERROR'}, "Circular dependency detected")
            return {'CANCELLED'}

        print(f"[{LOG_PREFIX} Batch] Roots: {ready}")
        started = 0
        for name in ready:
            if cls._start_node_operation(ntree, name):
                started += 1

        self.report({'INFO'}, f"Batch started: {started} nodes")
        if len(cls._dependencies) > 0:
            cls._timer_running = True
            bpy.app.timers.register(cls._check_and_continue, first_interval=0.5)
        return {'FINISHED'}

    @classmethod
    def _start_node_operation(cls, ntree, node_name):
        if node_name in cls._running: return False
        node = ntree.nodes.get(node_name)
        if not node:
            cls._failed.add(node_name)
            return False

        type = cls._node_types.get(node_name)
        print(f"[{LOG_PREFIX} Batch] Starting: {node_name} ({type})")
        cls._running.add(node_name)

        # Stagger start to prevent API race conditions
        time.sleep(0.1)

        try:
            res = {'CANCELLED'}
            if type == 'NeuroGenerateNode':
                res = bpy.ops.neuro.node_generate(node_name=node_name, tree_name=ntree.name)
            elif type == 'NeuroUpgradePromptNode':
                res = bpy.ops.neuro.node_upgrade_prompt(node_name=node_name, tree_name=ntree.name)
            elif type == 'NeuroTextGenNode':
                res = bpy.ops.neuro.node_generate_text(node_name=node_name, tree_name=ntree.name)

            if 'CANCELLED' in res:
                print(f"[{LOG_PREFIX} Batch] Operator cancelled: {node_name}")
                cls._running.discard(node_name)
                cls._failed.add(node_name)
                return False
            return True
        except Exception as e:
            print(f"[{LOG_PREFIX} Batch] Exception: {node_name} - {e}")
            cls._running.discard(node_name)
            cls._failed.add(node_name)
            return False

    @staticmethod
    def _check_and_continue():
        cls = NEURO_OT_run_selection
        if not cls._run_tree: return None
        ntree = bpy.data.node_groups.get(cls._run_tree)
        if not ntree: return None

        newly_done = []
        for name in list(cls._running):
            node = ntree.nodes.get(name)
            if not node:
                newly_done.append(name)
                continue

            is_busy = getattr(node, 'is_generating', False) or \
                      getattr(node, 'is_upgrading', False) or \
                      getattr(node, 'is_processing', False)

            if not is_busy:
                status = getattr(node, 'status_message', "")
                if any(x in status for x in ["Error", "Failed", "Cancelled"]):
                    print(f"[{LOG_PREFIX} Batch] Failed: {name} ({status})")
                    cls._failed.add(name)
                    cls._running.discard(name)
                else:
                    print(f"[{LOG_PREFIX} Batch] Done: {name}")
                    newly_done.append(name)

        for name in newly_done:
            cls._running.discard(name)
            cls._completed.add(name)

        ready = []
        for name, deps in cls._dependencies.items():
            if name in cls._completed or name in cls._running or name in cls._failed: continue
            if not deps.isdisjoint(cls._failed):
                print(f"[{LOG_PREFIX} Batch] Skipping {name} (dep failed)")
                cls._failed.add(name)
                continue
            if deps.issubset(cls._completed): ready.append(name)

        for name in ready: cls._start_node_operation(ntree, name)

        all_nodes = set(cls._dependencies.keys())
        finished = cls._completed.union(cls._failed)

        if not cls._running and not ready:
            if finished == all_nodes:
                print(f"[{LOG_PREFIX} Batch] Finished. Done: {len(cls._completed)}, Failed: {len(cls._failed)}")
                cls._dependencies = {}
                cls._completed = set()
                cls._running = set()
                cls._failed = set()
                cls._run_tree = ""
                cls._timer_running = False
                return None

            print(f"[{LOG_PREFIX} Batch] Stall. Remaining: {all_nodes - finished}")
            return None

        return 0.5


class BlenderJSONEncoder(json.JSONEncoder):
    """
    A custom JSON Encoder that converts Blender's math types and property arrays
    into JSON-serializable Python types.
    """

    def default(self, obj):
        # Get type name for explicit checks (more reliable than isinstance with Blender types)
        type_name = type(obj).__name__

        # 1. Handle mathutils types explicitly by name
        if type_name in ('Vector', 'Color', 'Euler', 'Quaternion'):
            return list(obj)

        if type_name == 'Matrix':
            return [list(row) for row in obj]

        # 2. Handle Blender property arrays (bpy_prop_array, etc.)
        if 'bpy_prop_array' in type_name or 'IDPropertyArray' in type_name:
            return list(obj)

        # 3. Handle any object with to_list() method
        if hasattr(obj, 'to_list'):
            return obj.to_list()

        # 4. Handle any object with to_tuple() method
        if hasattr(obj, 'to_tuple'):
            return list(obj.to_tuple())

        # 5. Fallback for other iterables (but not strings/bytes/dicts)
        if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, dict)):
            try:
                return list(obj)
            except (TypeError, ValueError):
                pass

        # 6. Let the base class handle it or raise TypeError
        return super().default(obj)


_3D_EXT = {'.glb', '.gltf', '.fbx', '.obj', '.stl', '.ply'}


class NEURO_OT_node_export(Operator):
    bl_idname = "neuro.node_export"
    bl_label = "Export Node Tree"
    filepath: StringProperty(subtype='FILE_PATH')
    include_images: BoolProperty(name="Include Images", default=True)
    include_3d: BoolProperty(name="Include 3D Files", default=True)
    filter_glob: StringProperty(default="*.json;*.zip", options={'HIDDEN'})

    def invoke(self, context, event):
        if context.space_data.node_tree:
            use_zip = self.include_images or self.include_3d
            self.filepath = context.space_data.node_tree.name + (".zip" if use_zip else ".json")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "include_images")
        layout.prop(self, "include_3d")

    def execute(self, context):
        import sys
        _bl = sys.modules.get(__package__)
        version_str = ".".join(map(str, _bl.bl_info["version"])) if (_bl and hasattr(_bl, 'bl_info')) else "unknown"

        ntree = context.space_data.node_tree
        if not ntree: return {'CANCELLED'}

        data = {
            "version": version_str,
            "tree_name": ntree.name,
            "preview_scale": getattr(ntree, 'preview_scale', 1.0),
            "nodes": [],
            "links": [],
            "images": {},
            "models": {}
        }
        image_paths = {}
        model_paths = {}

        for node in ntree.nodes:
            node_data = {
                "name": node.name,
                "type": node.bl_idname,
                "location": list(node.location),
                "width": node.width,
                "properties": {}
            }

            # --- SIMPLIFIED PROPERTY LOOP (The Encoder handles the types now) ---
            for prop in node.bl_rna.properties:
                if prop.is_readonly or prop.identifier in ('rna_type', 'name', 'select', 'location',
                                                           'is_generating', 'is_processing', 'bl_idname'):
                    continue
                try:
                    # We just grab the value raw. The BlenderJSONEncoder will fix it later.
                    val = getattr(node, prop.identifier)
                    node_data["properties"][prop.identifier] = val
                except Exception:
                    pass
            # -------------------------------------------------------------------

            # Route file path properties to images or models based on extension
            path_props = ['result_path', 'image_path', 'front_path', 'left_path', 'right_path', 'back_path']
            for p in path_props:
                val = getattr(node, p, "")
                if not val or not os.path.exists(val):
                    continue
                ext = os.path.splitext(val)[1].lower()
                if ext in _3D_EXT:
                    if self.include_3d:
                        key = f"model_{len(model_paths)}"
                        model_paths[key] = val
                        node_data["properties"][f"{p}_key"] = key
                else:
                    if self.include_images:
                        key = f"img_{len(image_paths)}"
                        image_paths[key] = val
                        node_data["properties"][f"{p}_key"] = key

            data["nodes"].append(node_data)

        for link in ntree.links:
            data["links"].append({
                "from_node": link.from_node.name,
                "from_socket": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket": link.to_socket.name,
            })

        data["images"] = {k: os.path.basename(v) for k, v in image_paths.items()}
        data["models"] = {k: os.path.basename(v) for k, v in model_paths.items()}

        use_zip = (self.include_images and image_paths) or (self.include_3d and model_paths)
        if use_zip:
            if not self.filepath.endswith('.zip'): self.filepath = self.filepath.rsplit('.', 1)[0] + '.zip'
            with zipfile.ZipFile(self.filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('nodes.json', json.dumps(data, indent=2, cls=BlenderJSONEncoder))
                for k, p in image_paths.items():
                    zf.write(p, f"images/{os.path.basename(p)}")
                for k, p in model_paths.items():
                    zf.write(p, f"models/{os.path.basename(p)}")
        else:
            if not self.filepath.endswith('.json'): self.filepath = self.filepath.rsplit('.', 1)[0] + '.json'
            with open(self.filepath, 'w') as f:
                json.dump(data, f, indent=2, cls=BlenderJSONEncoder)

        self.report({'INFO'}, f"Exported: {os.path.basename(self.filepath)}")
        return {'FINISHED'}


class NEURO_OT_node_import(Operator):
    bl_idname = "neuro.node_import"
    bl_label = "Import Node Tree"
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.json;*.zip", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            data, imgs_dir = None, None
            if self.filepath.endswith('.zip'):
                with zipfile.ZipFile(self.filepath, 'r') as zf:
                    data = json.loads(zf.read('nodes.json'))
                    imgs_dir = get_generations_folder("imported")
                    for item in zf.namelist():
                        if item.startswith('images/'): zf.extract(item, imgs_dir)
            else:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)

            tree_name = data.get("tree_name", "Imported")
            cnt = 1
            while tree_name in bpy.data.node_groups:
                tree_name = f"{data.get('tree_name', 'Imported')}_import{cnt:03d}"
                cnt += 1

            ntree = bpy.data.node_groups.new(tree_name, 'NeuroGenNodeTree')
            if "preview_scale" in data: ntree.preview_scale = data["preview_scale"]

            node_map = {}
            for nd in data.get("nodes", []):
                try:
                    node = ntree.nodes.new(nd["type"])
                except Exception:
                    continue
                node.name = nd["name"]
                node.location = nd.get("location", (0, 0))
                node.width = nd.get("width", 200)

                props = nd.get("properties", {})
                for k, v in props.items():
                    if k.endswith('_key'): continue
                    if hasattr(node, k):
                        try:
                            prop = node.bl_rna.properties.get(k)
                            # Handle array properties (Color, Vector, etc.)
                            if prop and prop.type == 'FLOAT' and prop.is_array and isinstance(v, list):
                                attr = getattr(node, k)
                                for i, val in enumerate(v):
                                    if i < len(attr):
                                        attr[i] = val
                            else:
                                setattr(node, k, v)
                        except Exception:
                            pass

                if imgs_dir:
                    for p in ['result_path', 'image_path', 'front_path', 'left_path', 'right_path', 'back_path']:
                        key = f"{p}_key"
                        if key in props and props[key] in data.get("images", {}):
                            img_p = os.path.join(imgs_dir, "images", data["images"][props[key]])
                            if os.path.exists(img_p): setattr(node, p, img_p)

                node_map[nd["name"]] = node

            for ld in data.get("links", []):
                fn = node_map.get(ld["from_node"])
                tn = node_map.get(ld["to_node"])
                if fn and tn:
                    fs = fn.outputs.get(ld["from_socket"])
                    ts = tn.inputs.get(ld["to_socket"])
                    if fs and ts: ntree.links.new(fs, ts)

            if hasattr(context.space_data, 'node_tree'): context.space_data.node_tree = ntree
            self.report({'INFO'}, f"Imported: {tree_name}")
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


class NEURO_OT_ps_edit(Operator):
    """Open the node's image in Adobe Photoshop"""
    bl_idname = "neuro.ps_edit"
    bl_label = "Edit in Photoshop"
    node_name: StringProperty()

    def execute(self, context):
        import subprocess
        prefs = None
        for pkg in [__package__, "ai_nodes"]:
            if pkg and pkg in context.preferences.addons:
                prefs = context.preferences.addons[pkg].preferences
                break
        if not prefs:
            self.report({'ERROR'}, "Could not find addon preferences")
            return {'CANCELLED'}

        ps_path = getattr(prefs, 'photoshop_exe_path', '')
        if not ps_path or not os.path.exists(ps_path):
            self.report({'ERROR'}, "Set Photoshop path in addon preferences (Tools tab)")
            return {'CANCELLED'}

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        img_path = node.get_image_path() if hasattr(node, 'get_image_path') else None
        if not img_path or not os.path.exists(img_path):
            self.report({'WARNING'}, "No image to edit")
            return {'CANCELLED'}

        try:
            subprocess.Popen([ps_path, img_path])
            self.report({'INFO'}, "Opened in Photoshop")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to launch Photoshop: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class NEURO_OT_ps_grab(Operator):
    """Grab the active Photoshop document as PNG into this node"""
    bl_idname = "neuro.ps_grab"
    bl_label = "Grab from Photoshop"
    node_name: StringProperty()

    def execute(self, context):
        import subprocess

        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get PS exe path from preferences (same as ps_edit)
        prefs = None
        for pkg in [__package__, "ai_nodes"]:
            if pkg and pkg in context.preferences.addons:
                prefs = context.preferences.addons[pkg].preferences
                break
        ps_exe = getattr(prefs, 'photoshop_exe_path', '') if prefs else ''
        if not ps_exe or not os.path.exists(ps_exe):
            self.report({'ERROR'}, "Set Photoshop path in addon preferences (Tools tab)")
            return {'CANCELLED'}

        gen_dir = get_generations_folder("nodes/ps_bridge")
        os.makedirs(gen_dir, exist_ok=True)
        temp_path = os.path.join(gen_dir, "_ps_grab_temp.png")
        js_path = temp_path.replace("\\", "/")
        # Also write doc name to a sidecar txt so Python can read it
        info_path = os.path.join(gen_dir, "_ps_grab_info.txt")
        info_js = info_path.replace("\\", "/")

        # Write ExtendScript — runs inside the already-open PS instance
        jsx_content = (
            'try {\n'
            '  var doc = app.activeDocument;\n'
            '  var dup = doc.duplicate("_grab_temp");\n'
            '  dup.flatten();\n'
            f'  var f = new File("{js_path}");\n'
            '  var opts = new PNGSaveOptions();\n'
            '  dup.saveAs(f, opts, true);\n'
            '  dup.close(SaveOptions.DONOTSAVECHANGES);\n'
            f'  var infoFile = new File("{info_js}");\n'
            '  infoFile.open("w");\n'
            '  infoFile.write(doc.name);\n'
            '  infoFile.close();\n'
            '} catch(e) {\n'
            f'  var infoFile = new File("{info_js}");\n'
            '  infoFile.open("w");\n'
            '  infoFile.write("ERROR:" + e.message);\n'
            '  infoFile.close();\n'
            '}\n'
        )
        jsx_path = os.path.join(gen_dir, "_ps_grab.jsx")
        with open(jsx_path, "w", encoding="utf-8") as fh:
            fh.write(jsx_content)

        # --- NEW: Clean up old files to prevent stale grabs ---
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        if os.path.exists(info_path):
            try:
                os.remove(info_path)
            except OSError:
                pass

        # --- NEW: Capture Blender's window focus (Windows only) ---
        hwnd = None
        if os.name == 'nt':
            import ctypes
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                pass

        # Run JSX directly via Photoshop CLI — no COM, no PowerShell
        try:
            result = subprocess.run(
                [ps_exe, jsx_path],
                capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "Photoshop grab timed out")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to launch Photoshop: {e}")
            return {'CANCELLED'}

        # --- NEW: Wait for PS to finish writing the info file ---
        import time
        wait_start = time.time()
        while not os.path.exists(info_path):
            if time.time() - wait_start > 15.0:  # 15 second timeout
                self.report({'ERROR'}, "Photoshop script timed out")
                return {'CANCELLED'}
            time.sleep(0.1)

        # --- NEW: Steal focus back to Blender ---
        if hwnd and os.name == 'nt':
            try:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

        # Read result from sidecar info file
        doc_name = "photoshop"
        if os.path.exists(info_path):
            with open(info_path, "r", encoding="utf-8") as fh:
                info = fh.read().strip()
            try:
                os.remove(info_path)
            except OSError:
                pass
            if info.startswith("ERROR:"):
                self.report({'ERROR'}, f"PS: {info[6:]}")
                return {'CANCELLED'}
            if info:
                doc_name = info

        # Cleanup temp jsx
        try:
            os.remove(jsx_path)
        except OSError:
            pass

        if not os.path.exists(temp_path):
            self.report({'ERROR'}, "No document open in Photoshop")
            return {'CANCELLED'}

        # Rename with document name
        base_name = os.path.splitext(doc_name)[0]
        filename = get_unique_filename(gen_dir, f"ps_{base_name}", extension="png")
        final_path = os.path.join(gen_dir, filename)
        os.replace(temp_path, final_path)

        node.result_path = final_path
        NeuroNodeBase.invalidate_file_cache(final_path)
        node.status_message = ""
        self.report({'INFO'}, f"Grabbed: {doc_name}")
        return {'FINISHED'}


class NEURO_OT_node_manual(Operator):
    bl_idname = "neuro.node_manual"
    bl_label = "Manual"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=580)

    def execute(self, context):
        return {'FINISHED'}

    def get_language(self, context):
        """Get current manual language from preferences"""
        for name in [__package__, "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                return getattr(prefs, 'manual_language', 'EN')
        return 'EN'

    def draw(self, context):
        lang = self.get_language(context)
        if lang == 'RU':
            self.draw_slav(context)
        else:
            self.draw_en(context)

    # =============================================================================
    # MANUALS
    # =============================================================================

    def draw_en(self, context):
        """English manual"""
        layout = self.layout

        # Header
        layout.label(text="AI Node Editor", icon='NODE')
        layout.label(text="AI-assisted generation for professional workflows")
        layout.separator()

        # === KEYBOARD SHORTCUTS ===
        box = layout.box()
        box.label(text="Keyboard Shortcuts", icon='KEYINGSET')
        col = box.column(align=True)
        col.label(text="Shift+A          Add node menu")
        col.label(text="Shift+D          Duplicate node with connections")
        col.label(text="F                Auto-connect two selected nodes")
        col.label(text="X                Delete selected")
        col.label(text="Ctrl+B           Paste image from clipboard as Reference node")
        col.label(text="Double-click     View node image full screen")
        col.label(text="Enter            Generate on active node")

        layout.separator()

        # === IMAGE GENERATION ===
        box = layout.box()
        box.label(text="Generate / Edit Node", icon='IMAGE_DATA')
        col = box.column(align=True)
        col.label(text="Core image generation node. Text-to-image or image editing.")
        col.label(text="Connect an image to the socket to use as input.")
        col.label(text="History arrows navigate through all generated results.")
        col.label(text="Side buttons: Remove background for RGBA / paint mask.")

        layout.separator()

        # === REFERENCE NODE ===
        box = layout.box()
        box.label(text="Reference Node", icon='IMAGE_REFERENCE')
        col = box.column(align=True)
        col.label(text="Input images for editing, style transfer, or composition.")
        col.label(text="Supports: file browser, drag-drop, clipboard paste, render grab.")
        col.label(text="Multi-load: hold Shift in file browser or drop multiple files.")
        col.label(text="Grid preview shows all loaded images, arrows to navigate.")

        layout.separator()

        # === TEXT NODES ===
        box = layout.box()
        box.label(text="Text Nodes", icon='TEXT')
        col = box.column(align=True)
        col.label(text="Text Node - static text input, connect to prompts")
        col.label(text="   Open Editor button opens a full Blender text editor for long prompts")
        col.label(text="Merge Text - combine multiple text inputs with separator")
        col.label(text="Upgrade Prompt - LLM enhances your prompt for better results")
        col.label(text="Text Generation - freeform LLM text output")

        layout.separator()

        # === ARTIST TOOLS ===
        box = layout.box()
        box.label(text="Artist Tools Node", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.label(text="Template operations on images.")
        col.label(text="Get Objects List - AI analyzes, creates list of objects to remove")
        col.label(text="Separation - split composition into parts")
        col.label(text="Upscale / Quality - various methods to improve image quality")
        col.label(text="Flip / Mirror - simple image rotation and reflection")
        col.label(text="Change Angle - change camera position / isometry")
        col.label(text="Multiview - generate 4 orthographic views from single image")
        col.separator()
        col.label(text="Elements list: click to select, for 4+ items enable PRO")
        col.label(text="Selected elements can be copied or used for further generation")

        layout.separator()

        # === CHARACTER TEXTURE (TEAM) ===
        box = layout.box()
        box.label(text="Character Texture Node  [Team]", icon='ARMATURE_DATA')
        col = box.column(align=True)
        col.label(text="Semi-automated character texturing pipeline.")
        col.label(text="1. Setup Camera + Back Duplicate → 2. Capture Viewport")
        col.label(text="3. Edit enhance prompt if needed, then Generate")
        col.label(text="4. Pick best result (1/2). Retry adds a new batch — use < > to browse.")
        col.label(text="5. UV setup + bake runs automatically")
        col.label(text="6. Pick best gap-fill (1/2), click Apply")
        col.label(text="Redo Gap Fill — re-runs inpaint without losing enhance results")
        col.label(text="Connect Prompt In to override the enhance prompt from a Text node")

        layout.separator()

        # === DESIGN VARIATIONS ===
        box = layout.box()
        box.label(text="Design Variations Node", icon='MOD_ARRAY')
        col = box.column(align=True)
        col.label(text="Batch exploration of visual directions.")
        col.label(text="Simple mode: automatic variations from single image via prompt")
        col.label(text="Guided mode: specify desired changes, text model suggests variations")
        col.label(text="Results stored in history, navigate with arrows")

        layout.separator()

        # === UTILITIES ===
        box = layout.box()
        box.label(text="Utilities", icon='MODIFIER')
        col = box.column(align=True)
        col.label(text="Image Splitter - divide image into Front/Left/Right/Back")
        col.label(text="   Auto-connects to Tripo 3D multiview input (press F)")
        col.separator()
        col.label(text="Run Selection - execute multiple nodes in parallel")
        col.label(text="Export/Import - save results with node setup as .zip")
        col.label(text="Relocate - find moved image files in new location")

        layout.separator()

        # === 3D GENERATION ===
        box = layout.box()
        box.label(text="3D Generation (Tripo)", icon='MESH_MONKEY')
        col = box.column(align=True)
        col.label(text="Tripo Generate - image/text to 3D mesh")
        col.label(text="   Single image mode or multiview (4 orthographic images)")
        col.label(text="   Output: GLB mesh imported directly into scene")
        col.separator()
        col.label(text="Smart LowPoly - optimized low-poly generation")
        col.label(text="   Functionality from the paid web version")

        layout.separator()

        # === TIPS ===
        box = layout.box()
        box.label(text="Tips", icon='LIGHT')
        col = box.column(align=True)
        col.label(text="Sidebar (N panel) shows list of current generations")
        col.label(text="All results auto-save to generations folder")
        col.label(text="Double-click any result image to view it full screen")

    def draw_slav(self, context):
        """Russian manual"""
        layout = self.layout

        # Header
        layout.label(text="ЭЯЙ - Редактор Нод", icon='NODE')
        layout.label(text="ИИ-экосистема для профессиональных задач")
        layout.separator()

        # === KEYBOARD SHORTCUTS ===
        box = layout.box()
        box.label(text="Горячие клавиши", icon='KEYINGSET')
        col = box.column(align=True)
        col.label(text="Shift+A          Меню добавления нод")
        col.label(text="Shift+D          Дублировать ноду с соединениями")
        col.label(text="F                Авто-соединение двух выбранных нод")
        col.label(text="X                Удалить выбранное")
        col.label(text="Ctrl+B           Вставить изображение из буфера как Reference")
        col.label(text="Двойной клик     Просмотр изображения ноды на весь экран")
        col.label(text="Enter            Генерация на активной ноде")

        layout.separator()

        # === IMAGE GENERATION ===
        box = layout.box()
        box.label(text="Нода Генерации / Редактирования", icon='IMAGE_DATA')
        col = box.column(align=True)
        col.label(text="Основная нода. Текст-в-изображение или редактирование.")
        col.label(text="Подключите изображение в сокет для использования как инпут.")
        col.label(text="Стрелки истории переключают все сгенерированные результаты.")
        col.label(text="Боковые кнопки: Убрать фон для RGBA / рисовать маску.")

        layout.separator()

        # === REFERENCE NODE ===
        box = layout.box()
        box.label(text="Нода Reference (Референс)", icon='IMAGE_REFERENCE')
        col = box.column(align=True)
        col.label(text="Входные изображения для редактирования или композиции.")
        col.label(text="Поддержка: обзор файлов, drag-drop, буфер обмена, рендер.")
        col.label(text="Мульти-загрузка: зажмите Shift или перетащите несколько файлов.")
        col.label(text="Сетка превью показывает все загруженные изображения.")

        layout.separator()

        # === TEXT NODES ===
        box = layout.box()
        box.label(text="Текстовые Ноды", icon='TEXT')
        col = box.column(align=True)
        col.label(text="Text Node - статический текст, подключается к промптам")
        col.label(text="   Кнопка Open Editor открывает полноценный редактор текста")
        col.label(text="Merge Text - объединяет несколько текстов разделителем")
        col.label(text="Upgrade Prompt - LLM улучшает ваш промпт для лучших результатов")
        col.label(text="Text Generation - свободная генерация текста через LLM")

        layout.separator()

        # === ARTIST TOOLS ===
        box = layout.box()
        box.label(text="Нода Artist Tools", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.label(text="Шаблонные операции по изображениям.")
        col.label(text="Get Objects List - ИИ анализирует, создает список объектов для удаления")
        col.label(text="Separation - разделение композиции на части")
        col.label(text="Upscale / Quality - разные способы улучшения качества изображения")
        col.label(text="Flip / Mirror - простой поворот и отражение изображения")
        col.label(text="Change Angle - изменение положения камеры / изометрия")
        col.label(text="Multiview - генерация 4 ортогональных видов из одного изображения")
        col.separator()
        col.label(text="Список элементов: клик для выбора, для 4 и более лучше включить PRO")
        col.label(text="Выбранные элементы можно скопировать или использовать далее")

        layout.separator()

        # === CHARACTER TEXTURE (TEAM) ===
        box = layout.box()
        box.label(text="Нода Character Texture  [Team]", icon='ARMATURE_DATA')
        col = box.column(align=True)
        col.label(text="Полуавтоматический пайплайн текстурирования персонажа.")
        col.label(text="1. Настроить камеру + дубликат для вида сзади → 2. Захват вьюпорта")
        col.label(text="3. При необходимости отредактировать промпт или подключить свой, затем Generate")
        col.label(text="4. Выбрать лучший вариант (1/2). Retry добавляет новую партию — < > для навигации.")
        col.label(text="5. UV-развёртка и бейк выполняются автоматически")
        col.label(text="6. Выбрать лучший вариант заливки (1/2), нажать Apply")
        col.label(text="Redo Gap Fill — повторить инпейнт без потери результатов генерации")

        layout.separator()

        # === DESIGN VARIATIONS ===
        box = layout.box()
        box.label(text="Нода Design Variations", icon='MOD_ARRAY')
        col = box.column(align=True)
        col.label(text="Пакетное создание визуальных вариаций.")
        col.label(text="Simple mode: автоматические вариации из одного изображения по промпту")
        col.label(text="Guided mode: укажите желаемые изменения, текстовая модель предложит вариации")
        col.label(text="Результаты сохраняются в истории, навигация стрелками")

        layout.separator()

        # === UTILITIES ===
        box = layout.box()
        box.label(text="Утилиты", icon='MODIFIER')
        col = box.column(align=True)
        col.label(text="Image Splitter - разделение изображения на Front/Left/Right/Back")
        col.label(text="   Авто-подключение к Tripo 3D multiview (нажмите F)")
        col.separator()
        col.label(text="Run Selection - запуск нескольких нод параллельно")
        col.label(text="Export/Import - сохранение результатов с сетапом в .zip")
        col.label(text="Relocate - поиск перемещенных файлов изображений")

        layout.separator()

        # === 3D GENERATION ===
        box = layout.box()
        box.label(text="3D Генерация (Tripo)", icon='MESH_MONKEY')
        col = box.column(align=True)
        col.label(text="Tripo Generate - изображение/текст в 3D модель")
        col.label(text="   Режим одного изображения или multiview (4 ортогональных вида)")
        col.label(text="   Вывод: модель импортируется сразу в сцену")
        col.separator()
        col.label(text="Smart LowPoly - оптимизированная low-poly генерация")
        col.label(text="   Функционал из платной версии с сайта")

        layout.separator()

        # === TIPS ===
        box = layout.box()
        box.label(text="Советы", icon='LIGHT')
        col = box.column(align=True)
        col.label(text="Сайдбар (N панель) показывает список текущих генераций")
        col.label(text="Все результаты авто-сохраняются в папку generations")
        col.label(text="Двойной клик по изображению — просмотр на весь экран")


# =============================================================================
# ADD TO SHADER — Creates Image Texture node in material
# =============================================================================

class NEURO_OT_add_to_shader(Operator):
    """Add result image as texture node in active material"""
    bl_idname = "neuro.add_to_shader"
    bl_label = "Add to Shader"
    bl_description = "Create an Image Texture node in the active material with this image"
    node_name: StringProperty()

    def execute(self, context):
        # 1. Check object selection
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "Select an object first")
            return {'CANCELLED'}

        if obj.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object")
            return {'CANCELLED'}

        # 2. Check material
        if not obj.data.materials or not obj.active_material:
            self.report({'WARNING'}, "Object has no material. Create a material first.")
            return {'CANCELLED'}

        mat = obj.active_material
        if not mat.use_nodes:
            mat.use_nodes = True

        # 3. Get image path from node
        image_path = ""
        ntree = get_node_tree(context, None)
        if ntree and self.node_name:
            node = ntree.nodes.get(self.node_name)
            if node:
                if hasattr(node, 'result_path') and node.result_path:
                    image_path = node.result_path
                elif hasattr(node, 'get_image_path'):
                    image_path = node.get_image_path()

        if not image_path or not os.path.exists(image_path):
            self.report({'ERROR'}, "No image to add")
            return {'CANCELLED'}

        # 4. Load image into Blender
        img_name = os.path.basename(image_path)

        # Check if already loaded
        bpy_image = None
        for img in bpy.data.images:
            if img.filepath and os.path.normpath(os.path.abspath(
                    bpy.path.abspath(img.filepath))) == os.path.normpath(os.path.abspath(image_path)):
                bpy_image = img
                break

        if not bpy_image:
            bpy_image = bpy.data.images.load(image_path)

        # 5. Create Image Texture node in material
        node_tree = mat.node_tree
        tex_node = node_tree.nodes.new('ShaderNodeTexImage')
        tex_node.image = bpy_image
        tex_node.label = img_name

        # Position it to the left of existing nodes
        min_x = 0
        for n in node_tree.nodes:
            if n != tex_node and n.location.x < min_x:
                min_x = n.location.x
        tex_node.location = (min_x - 320, 0)

        self.report({'INFO'}, f"Added '{img_name}' to {mat.name}")
        return {'FINISHED'}


# =============================================================================
# REROUTE WITH MERGE — Shift+RMouse in node editor
# =============================================================================

def _segs_intersect(p1, p2, p3, p4):
    """Return True if line segment p1-p2 intersects p3-p4."""
    def cross2d(a, b):
        return a[0] * b[1] - a[1] * b[0]
    d1 = (p2[0] - p1[0], p2[1] - p1[1])
    d2 = (p4[0] - p3[0], p4[1] - p3[1])
    denom = cross2d(d1, d2)
    if abs(denom) < 1e-10:
        return False
    diff = (p3[0] - p1[0], p3[1] - p1[1])
    t = cross2d(diff, d2) / denom
    u = cross2d(diff, d1) / denom
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


def _socket_node_pos(node, socket, is_output):
    """Approximate node-space position of a socket centre."""
    sockets = node.outputs if is_output else node.inputs
    visible = [s for s in sockets if not s.hide]
    if socket not in visible:
        return None
    idx = visible.index(socket)
    x = node.location[0] + (node.width if is_output else 0)
    y = node.location[1] - 22 - idx * 22   # 22 ≈ header + per-socket height
    return (x, y)


class NEURO_OT_add_reroute_merged(Operator):
    """Shift+RMouse: drag across links to insert reroute nodes.
    Links sharing the same source socket are merged into one reroute."""
    bl_idname = "neuro.add_reroute_merged"
    bl_label = "Add Reroute (Merged)"
    bl_options = {'REGISTER', 'UNDO'}

    _draw_handle = None
    _start = None
    _end = None

    def _draw_callback(self, context):
        if self._start is None or self._end is None:
            return
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'LINES', {"pos": [self._start, self._end]})
            shader.bind()
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            gpu.state.blend_set('ALPHA')
            gpu.state.line_width_set(2.0)
            batch.draw(shader)
            gpu.state.blend_set('NONE')
            gpu.state.line_width_set(1.0)
        except Exception:
            pass

    def invoke(self, context, event):
        if context.area.type != 'NODE_EDITOR':
            return {'PASS_THROUGH'}
        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._end = self._start
        self._draw_handle = bpy.types.SpaceNodeEditor.draw_handler_add(
            self._draw_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type == 'MOUSEMOVE':
            self._end = (event.mouse_region_x, event.mouse_region_y)
            return {'RUNNING_MODAL'}
        if event.type == 'RIGHTMOUSE' and event.value == 'RELEASE':
            self._cleanup(context)
            self._end = (event.mouse_region_x, event.mouse_region_y)
            self._insert_reroutes(context)
            context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in {'ESC', 'LEFTMOUSE'}:
            self._cleanup(context)
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if self._draw_handle:
            bpy.types.SpaceNodeEditor.draw_handler_remove(self._draw_handle, 'WINDOW')
            self._draw_handle = None

    def _insert_reroutes(self, context):
        ntree = context.space_data.node_tree
        if not ntree or self._start == self._end:
            return
        v2d = context.region.view2d
        start_v = v2d.region_to_view(*self._start)
        end_v = v2d.region_to_view(*self._end)

        # Collect links crossed by the rubber-band line
        crossed = []
        for link in list(ntree.links):
            if link.is_muted:
                continue
            fp = _socket_node_pos(link.from_node, link.from_socket, True)
            tp = _socket_node_pos(link.to_node, link.to_socket, False)
            if fp and tp and _segs_intersect(start_v, end_v, fp, tp):
                crossed.append(link)

        if not crossed:
            return

        # Group by (from_node, from_socket) — same source → one reroute
        from collections import defaultdict
        groups = defaultdict(list)
        for link in crossed:
            key = (link.from_node.name, link.from_socket.name)
            groups[key].append(link)

        mid_v = ((start_v[0] + end_v[0]) / 2, (start_v[1] + end_v[1]) / 2)

        for i, (key, links) in enumerate(groups.items()):
            reroute = ntree.nodes.new('NodeReroute')
            reroute.location = (mid_v[0], mid_v[1] - i * 60)
            from_socket = links[0].from_socket
            to_sockets = [lk.to_socket for lk in links]
            for lk in links:
                ntree.links.remove(lk)
            ntree.links.new(from_socket, reroute.inputs[0])
            for ts in to_sockets:
                ntree.links.new(reroute.outputs[0], ts)