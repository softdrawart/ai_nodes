# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Gallery & Viewport Operators
Gallery management, viewport setup, and visual processing.
"""

import os

import bpy
from bpy.types import Operator

from .utils import (
    refresh_previews_and_collections, get_preview_collection
)


# =============================================================================
# VIEWPORT OPERATORS
# =============================================================================

class NEURO_OT_setup_matcap_normal(Operator):
    """Quick setup: Switch viewport to matcap normal view"""
    bl_idname = "neuro.setup_matcap_normal"
    bl_label = "Setup Normal Matcap"
    bl_description = "Switch 3D viewport to solid shading with check_normal+y matcap"

    def execute(self, context):
        scn = context.scene

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active

                if (space.shading.type == 'SOLID' and
                        space.shading.light == 'MATCAP' and
                        hasattr(space.shading, 'studio_light') and
                        space.shading.studio_light == 'check_normal+y.exr'):
                    self.report({'INFO'}, "Already in normal matcap view")
                    return {'FINISHED'}

                if not scn.neuro_stored_shading_type or scn.neuro_stored_shading_type == 'SOLID':
                    scn.neuro_stored_shading_type = space.shading.type
                    scn.neuro_stored_shading_light = space.shading.light
                    if hasattr(space.shading, 'studio_light'):
                        scn.neuro_stored_studio_light = space.shading.studio_light

                space.shading.type = 'SOLID'
                space.shading.light = 'MATCAP'
                space.shading.studio_light = 'check_normal+y.exr'
                area.tag_redraw()
                self.report({'INFO'}, "Switched to normal matcap view")
                return {'FINISHED'}

        self.report({'WARNING'}, "No 3D viewport found")
        return {'CANCELLED'}


class NEURO_OT_revert_matcap(Operator):
    """Revert viewport to previous shading"""
    bl_idname = "neuro.revert_matcap"
    bl_label = "Revert Matcap"
    bl_description = "Restore viewport to previous shading mode"

    def execute(self, context):
        scn = context.scene

        if not scn.neuro_stored_shading_type:
            self.report({'WARNING'}, "No stored shading to revert to")
            return {'CANCELLED'}

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = scn.neuro_stored_shading_type
                space.shading.light = scn.neuro_stored_shading_light
                if scn.neuro_stored_studio_light:
                    space.shading.studio_light = scn.neuro_stored_studio_light
                area.tag_redraw()
                self.report({'INFO'}, "Reverted to previous shading")
                return {'FINISHED'}

        return {'CANCELLED'}


# =============================================================================
# GALLERY LOAD/VIEW
# =============================================================================

class NEURO_OT_load_generated(Operator):
    """Load selected generated image into Image Editor"""
    bl_idname = "neuro.load_generated"
    bl_label = "Load"
    bl_description = "Load this image in the Image Editor"

    path: bpy.props.StringProperty()

    def execute(self, context):
        p = self.path
        if not os.path.exists(p):
            self.report({'ERROR'}, "File not found")
            return {'CANCELLED'}

        try:
            # Use safe_show_in_editor to prevent .001 duplicates
            from .utils import safe_show_in_editor
            img = safe_show_in_editor(p, reload_existing=True)
            if img:
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Failed to load image")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to open image: {e}")
            return {'CANCELLED'}


# =============================================================================
# GALLERY DELETE
# =============================================================================

class NEURO_OT_delete_generated(Operator):
    """Delete generated image (Shift+Click to delete entire batch)"""
    bl_idname = "neuro.delete_generated"
    bl_label = "Delete"
    bl_description = "Delete this image (Shift+Click = delete entire batch)"

    index: bpy.props.IntProperty()
    delete_batch: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        self.delete_batch = event.shift
        return self.execute(context)

    def execute(self, context):
        pcoll = get_preview_collection()
        scn = context.scene

        if 0 <= self.index < len(scn.neuro_generated_images):
            target = scn.neuro_generated_images[self.index]
            target_batch_id = target.batch_id

            if self.delete_batch and target_batch_id:
                indices_to_remove = []
                for i, gen in enumerate(scn.neuro_generated_images):
                    if gen.batch_id == target_batch_id:
                        if pcoll and gen.path:
                            key = os.path.normpath(os.path.abspath(gen.path))
                            if key in pcoll:
                                try:
                                    pcoll.pop(key, None)
                                except Exception:
                                    pass
                        if os.path.exists(gen.path):
                            try:
                                os.remove(gen.path)
                            except Exception as e:
                                print(f"[{LOG_PREFIX}] Failed to delete file: {e}")
                        indices_to_remove.append(i)

                for i in reversed(indices_to_remove):
                    scn.neuro_generated_images.remove(i)

                self.report({'INFO'}, f"Deleted {len(indices_to_remove)} images from batch")
            else:
                gen = scn.neuro_generated_images[self.index]

                if pcoll and gen.path:
                    key = os.path.normpath(os.path.abspath(gen.path))
                    if key in pcoll:
                        try:
                            pcoll.pop(key, None)
                        except Exception:
                            pass

                if os.path.exists(gen.path):
                    try:
                        os.remove(gen.path)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed to delete file: {e}")

                scn.neuro_generated_images.remove(self.index)

            refresh_previews_and_collections(scn)
        return {'FINISHED'}


class NEURO_OT_delete_texture(Operator):
    """Delete generated texture (Shift+Click to delete entire batch)"""
    bl_idname = "neuro.delete_texture"
    bl_label = "Delete"
    bl_description = "Delete this texture (Shift+Click = delete entire batch)"

    index: bpy.props.IntProperty()
    delete_batch: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        self.delete_batch = event.shift
        return self.execute(context)

    def execute(self, context):
        pcoll = get_preview_collection()
        scn = context.scene

        if 0 <= self.index < len(scn.neuro_generated_textures):
            target = scn.neuro_generated_textures[self.index]
            target_batch_id = target.batch_id

            if self.delete_batch and target_batch_id:
                indices_to_remove = []
                for i, tex in enumerate(scn.neuro_generated_textures):
                    if tex.batch_id == target_batch_id:
                        if pcoll and tex.path:
                            key = os.path.normpath(os.path.abspath(tex.path))
                            if key in pcoll:
                                try:
                                    pcoll.pop(key, None)
                                except Exception:
                                    pass
                        if os.path.exists(tex.path):
                            try:
                                os.remove(tex.path)
                            except Exception as e:
                                print(f"[{LOG_PREFIX}] Failed to delete file: {e}")
                        indices_to_remove.append(i)

                for i in reversed(indices_to_remove):
                    scn.neuro_generated_textures.remove(i)

                self.report({'INFO'}, f"Deleted {len(indices_to_remove)} textures from batch")
            else:
                tex = scn.neuro_generated_textures[self.index]

                if pcoll and tex.path:
                    key = os.path.normpath(os.path.abspath(tex.path))
                    if key in pcoll:
                        try:
                            pcoll.pop(key, None)
                        except Exception:
                            pass

                if os.path.exists(tex.path):
                    try:
                        os.remove(tex.path)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed to delete file: {e}")

                scn.neuro_generated_textures.remove(self.index)

            refresh_previews_and_collections(scn)
        return {'FINISHED'}


class NEURO_OT_clear_generated(Operator):
    """Clear all generated images from gallery (does not delete files)"""
    bl_idname = "neuro.clear_generated"
    bl_label = "Clear All"
    bl_description = "Clear all images from gallery (files are kept on disk)"

    def execute(self, context):
        pcoll = get_preview_collection()
        scn = context.scene

        if pcoll:
            for gen in scn.neuro_generated_images:
                if gen.path:
                    key = os.path.normpath(os.path.abspath(gen.path))
                    if key in pcoll:
                        try:
                            pcoll.pop(key, None)
                        except Exception:
                            pass

        scn.neuro_generated_images.clear()
        refresh_previews_and_collections(scn)
        return {'FINISHED'}


class NEURO_OT_clear_textures(Operator):
    """Clear all generated textures from gallery (does not delete files)"""
    bl_idname = "neuro.clear_textures"
    bl_label = "Clear All"
    bl_description = "Clear all textures from gallery (files are kept on disk)"

    def execute(self, context):
        pcoll = get_preview_collection()
        scn = context.scene

        if pcoll:
            for tex in scn.neuro_generated_textures:
                if tex.path:
                    key = os.path.normpath(os.path.abspath(tex.path))
                    if key in pcoll:
                        try:
                            pcoll.pop(key, None)
                        except Exception:
                            pass

        scn.neuro_generated_textures.clear()
        refresh_previews_and_collections(scn)
        return {'FINISHED'}


# =============================================================================
# GALLERY NAVIGATION
# =============================================================================

class NEURO_OT_relocate_gallery_images(Operator):
    """Relocate missing images in the sidebar gallery"""
    bl_idname = "neuro.relocate_gallery_images"
    bl_label = "Relocate Missing Images"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        name="Directory",
        description="Search directory for missing images",
        subtype='DIR_PATH'
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scn = context.scene
        search_dir = self.directory

        if not search_dir or not os.path.isdir(search_dir):
            self.report({'ERROR'}, "Invalid directory")
            return {'CANCELLED'}

        # Build a map of filenames to full paths in the search directory
        file_map = {}
        for root, dirs, files in os.walk(search_dir):
            for filename in files:
                lower_name = filename.lower()
                if lower_name.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif')):
                    if filename not in file_map:
                        file_map[filename] = os.path.join(root, filename)

        relocated_count = 0
        missing_count = 0

        # Check generated images
        for gen in scn.neuro_generated_images:
            if gen.path and not os.path.exists(gen.path):
                filename = os.path.basename(gen.path)
                if filename in file_map:
                    gen.path = file_map[filename]
                    relocated_count += 1
                else:
                    missing_count += 1

        # Check generated textures
        for tex in scn.neuro_generated_textures:
            if tex.path and not os.path.exists(tex.path):
                filename = os.path.basename(tex.path)
                if filename in file_map:
                    tex.path = file_map[filename]
                    relocated_count += 1
                else:
                    missing_count += 1

        # Refresh previews
        refresh_previews_and_collections(scn)

        if relocated_count > 0:
            self.report({'INFO'}, f"Relocated {relocated_count} image path(s)")
        if missing_count > 0:
            self.report({'WARNING'}, f"{missing_count} image(s) still missing")
        if relocated_count == 0 and missing_count == 0:
            self.report({'INFO'}, "No missing images found")

        return {'FINISHED'}


class NEURO_OT_batch_navigate(Operator):
    """Navigate through images in a batch"""
    bl_idname = "neuro.batch_navigate"
    bl_label = "Navigate Batch"

    batch_id: bpy.props.StringProperty()
    direction: bpy.props.IntProperty()
    is_texture: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        scn = context.scene

        batch_entry = None
        for entry in scn.neuro_batch_view_index:
            if entry.batch_id == self.batch_id:
                batch_entry = entry
                break

        if not batch_entry:
            batch_entry = scn.neuro_batch_view_index.add()
            batch_entry.batch_id = self.batch_id
            batch_entry.current_index = 0

        collection = scn.neuro_generated_textures if self.is_texture else scn.neuro_generated_images
        batch_count = sum(1 for item in collection if item.batch_id == self.batch_id)

        new_idx = (batch_entry.current_index + self.direction) % batch_count
        batch_entry.current_index = new_idx

        return {'FINISHED'}


class NEURO_OT_toggle_favorite(Operator):
    """Toggle favorite status"""
    bl_idname = "neuro.toggle_favorite"
    bl_label = "Toggle Favorite"
    bl_description = "Mark/unmark this as favorite"

    index: bpy.props.IntProperty()
    is_texture: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        scn = context.scene
        collection = scn.neuro_generated_textures if self.is_texture else scn.neuro_generated_images

        if 0 <= self.index < len(collection):
            item = collection[self.index]
            item.favorite = not item.favorite
            status = "favorited" if item.favorite else "unfavorited"
            self.report({'INFO'}, f"Image {status}")

        return {'FINISHED'}


# =============================================================================
# REGISTRATION
# =============================================================================

GALLERY_OPERATOR_CLASSES = (
    NEURO_OT_setup_matcap_normal,
    NEURO_OT_revert_matcap,
    NEURO_OT_load_generated,
    NEURO_OT_delete_generated,
    NEURO_OT_delete_texture,
    NEURO_OT_clear_generated,
    NEURO_OT_clear_textures,
    NEURO_OT_relocate_gallery_images,
    NEURO_OT_batch_navigate,
    NEURO_OT_toggle_favorite,
)


def register():
    for cls in GALLERY_OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(GALLERY_OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)