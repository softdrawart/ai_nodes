# -*- coding: utf-8 -*-
"""
AI Nodes - Character Texture Workflow Node
Team-internal node for semi-automated character texturing pipeline.

Pipeline:
  1. Setup camera (manual button)
  2. Create back-view duplicate (manual button, persists until cleanup)
  3. Capture viewport render (manual button, shows preview, re-capturable)
  4. Generate AI enhance (2 variations, pick from grid)
  5. UV setup + project + bake (automated)
  6. AI inpaint gaps (2 variations, pick from grid)
  7. Done — output to socket
"""

import os
import json
import threading
import time
from math import radians

import bpy
import bmesh
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty,
    IntProperty, FloatProperty,
)
from bpy.types import Node, Operator

from ..nodes_core import NeuroNodeBase, node_preview_collection
from ..constants import LOG_PREFIX
from ..utils import (
    get_all_api_keys, get_generations_folder, get_unique_filename,
    cancel_event,
)
from ..nodes_ops_common import (
    get_node_tree, log_node_generation, log_node_result,
    run_node_worker, save_generation_result, get_artist_tool_model,
)

# Status tracking
try:
    from .. import status_manager
    HAS_STATUS = True
except ImportError:
    HAS_STATUS = False


# =============================================================================
# CONSTANTS
# =============================================================================

CHAR_CAM_NAME = "AI_CharCam"

# Default camera transform (from reference — converted cm to meters)
CAM_LOCATION = (0.72, -6.2004, 1.35)
CAM_ROTATION = (radians(90), 0.0, 0.0)
CAM_ORTHO_SCALE = 2.82

# Pipeline step IDs
STEP_IDLE = 0
STEP_CAPTURED = 1
STEP_AI_ENHANCE = 2
STEP_PICK_ENHANCE = 3
STEP_UV_BAKE = 4
STEP_CONFIRM_BAKE = 5       # Show bake result, user confirms before inpaint
STEP_AI_INPAINT = 6
STEP_PICK_INPAINT = 7
STEP_DONE = 8

STEP_LABELS = {
    STEP_IDLE: "",
    STEP_CAPTURED: "Captured — ready to generate",
    STEP_AI_ENHANCE: "Generating textures...",
    STEP_PICK_ENHANCE: "Pick best result",
    STEP_UV_BAKE: "UV setup & baking...",
    STEP_CONFIRM_BAKE: "Review bake result",
    STEP_AI_INPAINT: "Inpainting gaps...",
    STEP_PICK_INPAINT: "Pick best inpaint",
    STEP_DONE: "Done",
}

DEFAULT_ENHANCE_PROMPT = (
    "This is frontal and back view of a character. "
    "Regenerate full character texture for both views in digital painting style "
    "also improving face skin textures and geometry. "
    "Use underlying colors as color pick. "
    "Preserve pixel to pixel accuracy and keep exactly same edges. "
    "Maintain perfect consistency across both views."
)

INPAINT_PROMPT = (
    "Inpaint all grey (#808080) areas inside UV islands of this texture atlas. "
    "Seamlessly fill gaps by extending surrounding painted texture like photoshop content-aware fill"
    "(skin, cloth, leather, hair). "
    "DO NOT touch the magenta (#FF00FF) background. "
    "Preserve existing painted pixels exactly. "
    "Match style, lighting and detail."
)


# =============================================================================
# NODE CLASS
# =============================================================================

class NeuroCharacterTextureNode(NeuroNodeBase, Node):
    """Character Texture — semi-automated texturing pipeline"""
    bl_idname = 'NeuroCharacterTextureNode'
    bl_label = 'Character Texture'
    bl_icon = 'ARMATURE_DATA'
    bl_width_default = 300
    bl_width_min = 240

    # --- Object selection ---
    target_object_name: StringProperty(
        name="Object", default="",
        description="Target character mesh name",
    )

    # --- Settings ---
    tex_size: EnumProperty(
        name="Texture Size",
        items=[('1024', "1024", "1K texture"), ('2048', "2048", "2K texture")],
        default='1024',
    )
    uv_island_margin: FloatProperty(
        name="Island Margin", default=0.003, min=0.0, max=0.1, precision=4,
    )
    uv_angle_limit: IntProperty(
        name="Angle Limit", default=89, min=1, max=89,
    )

    # --- Pipeline state ---
    pipeline_step: IntProperty(name="Step", default=STEP_IDLE, min=0, max=12)
    status_message: StringProperty(name="Status", default="")
    is_generating: BoolProperty(name="Is Generating", default=False)

    # --- Results ---
    result_path: StringProperty(name="Result Path", default="")

    # Generation results (JSON arrays of batches: [[path1, path2], [path3, path4], ...])
    enhance_results: StringProperty(name="Enhance Results", default="[]")
    inpaint_results: StringProperty(name="Inpaint Results", default="[]")
    selected_enhance_index: IntProperty(name="Selected Enhance", default=0)
    selected_inpaint_index: IntProperty(name="Selected Inpaint", default=0)
    enhance_batch_index: IntProperty(name="Enhance Batch Index", default=0)
    inpaint_batch_index: IntProperty(name="Inpaint Batch Index", default=0)

    # Retry mode flags (set before pipeline step to append vs replace batches)
    enhance_retry_mode: BoolProperty(name="Enhance Retry", default=False)
    inpaint_retry_mode: BoolProperty(name="Inpaint Retry", default=False)

    # Editable enhance prompt (defaults to module-level constant)
    enhance_prompt: StringProperty(
        name="Enhance Prompt",
        default=DEFAULT_ENHANCE_PROMPT,
        description="Prompt sent to AI for texture enhancement",
    )

    # Internal tracking
    char_render_path: StringProperty(name="Render Path", default="")
    char_bake_path: StringProperty(name="Bake Path", default="")
    char_dup_name: StringProperty(name="Duplicate Name", default="")
    char_ai_uv_name: StringProperty(name="AI UV Layer", default="_AI")
    char_orig_uv_name: StringProperty(name="Original UV", default="")

    # -------------------------------------------------------------------------
    # INIT / COPY
    # -------------------------------------------------------------------------

    def init(self, context):
        self.pipeline_step = STEP_IDLE
        self.status_message = ""
        self.is_generating = False
        self.result_path = ""
        self.enhance_results = "[]"
        self.inpaint_results = "[]"
        self.enhance_batch_index = 0
        self.inpaint_batch_index = 0
        self.enhance_retry_mode = False
        self.inpaint_retry_mode = False
        self.enhance_prompt = DEFAULT_ENHANCE_PROMPT
        self.char_render_path = ""
        self.char_bake_path = ""
        self.char_dup_name = ""
        self.char_orig_uv_name = ""

        inp = self.inputs.new('NeuroImageSocket', "References")
        inp.link_limit = 4096
        self.inputs.new('NeuroTextSocket', "Prompt In")
        self.outputs.new('NeuroImageSocket', "Image")

    def copy(self, node):
        self.pipeline_step = STEP_IDLE
        self.is_generating = False
        self.status_message = ""
        self.result_path = ""
        self.enhance_results = "[]"
        self.inpaint_results = "[]"
        self.enhance_batch_index = 0
        self.inpaint_batch_index = 0
        self.enhance_retry_mode = False
        self.inpaint_retry_mode = False
        self.char_render_path = ""
        self.char_bake_path = ""
        self.char_dup_name = ""

    # -------------------------------------------------------------------------
    # SOCKET HELPERS
    # -------------------------------------------------------------------------

    def get_input_images(self):
        images = []
        if "References" in self.inputs and self.inputs["References"].is_linked:
            for link in self.inputs["References"].links:
                from_node = link.from_node
                if hasattr(from_node, 'get_all_image_paths'):
                    for path in from_node.get_all_image_paths():
                        if path and os.path.exists(path) and path not in images:
                            images.append(path)
                elif hasattr(from_node, 'get_image_path'):
                    try:
                        path = from_node.get_image_path(link.from_socket.name)
                    except TypeError:
                        path = from_node.get_image_path()
                    if path and os.path.exists(path) and path not in images:
                        images.append(path)
        return images

    def get_input_prompt(self):
        if "Prompt In" in self.inputs and self.inputs["Prompt In"].is_linked:
            for link in self.inputs["Prompt In"].links:
                if hasattr(link.from_node, 'get_output_prompt'):
                    return link.from_node.get_output_prompt()
                if hasattr(link.from_node, 'text_value'):
                    return link.from_node.text_value
        return ""

    def get_image_path(self, socket_name=None):
        """Return best available image — works at any pipeline step"""
        # Final result
        if self.result_path and self._path_exists_cached(self.result_path):
            return self.result_path
        # Currently selected enhance result
        enhance = self._get_results_list('enhance')
        if enhance:
            idx = min(self.selected_enhance_index, len(enhance) - 1)
            if self._path_exists_cached(enhance[idx]):
                return enhance[idx]
        # Bake result
        if self.char_bake_path and self._path_exists_cached(self.char_bake_path):
            return self.char_bake_path
        # Capture
        if self.char_render_path and self._path_exists_cached(self.char_render_path):
            return self.char_render_path
        return ""

    def get_all_image_paths(self):
        p = self.get_image_path()
        return [p] if p else []

    # -------------------------------------------------------------------------
    # RESULT LIST HELPERS
    # -------------------------------------------------------------------------

    def _get_all_batches(self, phase):
        """Return all batches as a list of lists. Handles legacy flat-list format."""
        raw = self.enhance_results if phase == 'enhance' else self.inpaint_results
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if not data:
            return []
        # Backward compat: flat list of strings → one batch
        if isinstance(data[0], str):
            return [data]
        return data

    def _get_results_list(self, phase):
        """Return paths for the currently viewed batch."""
        batches = self._get_all_batches(phase)
        if not batches:
            return []
        idx = self.enhance_batch_index if phase == 'enhance' else self.inpaint_batch_index
        idx = min(max(0, idx), len(batches) - 1)
        return batches[idx]

    def _set_results_list(self, phase, paths, append=False):
        """Store paths. If append=True, add a new batch instead of replacing."""
        if append:
            batches = self._get_all_batches(phase)
            batches.append(paths)
        else:
            batches = [paths]
        data = json.dumps(batches)
        if phase == 'enhance':
            self.enhance_results = data
            self.enhance_batch_index = len(batches) - 1
        else:
            self.inpaint_results = data
            self.inpaint_batch_index = len(batches) - 1

    # -------------------------------------------------------------------------
    # GRID PREVIEW (custom scale for side-by-side)
    # -------------------------------------------------------------------------

    def _draw_grid_preview(self, layout, paths):
        """Draw side-by-side image previews at reduced scale"""
        from .. import nodes_core as _nc

        pc = _nc.node_preview_collection
        if pc is None:
            try:
                import bpy.utils.previews
                _nc.node_preview_collection = bpy.utils.previews.new()
                pc = _nc.node_preview_collection
            except Exception:
                return

        valid_paths = [p for p in paths if self._path_exists_cached(p)]
        if not valid_paths:
            return

        base_scale = self.get_preview_scale()
        grid_scale = max(4, base_scale // max(len(valid_paths), 2))

        row = layout.row(align=True)
        for path in valid_paths:
            abs_path = os.path.normpath(os.path.abspath(path))
            mtime = self._get_file_mtime_cached(path)
            key = f"{abs_path}:{mtime}" if mtime else abs_path

            if key not in pc:
                try:
                    pc.load(key, path, 'IMAGE')
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Grid preview load error: {e}")
                    continue

            if key in pc:
                col = row.column(align=True)
                col.template_icon(icon_value=pc[key].icon_id, scale=grid_scale)

    # -------------------------------------------------------------------------
    # DRAW
    # -------------------------------------------------------------------------

    def draw_label(self):
        if self.is_generating:
            return STEP_LABELS.get(self.pipeline_step, "Working...")
        if self.status_message:
            return self.status_message
        return "Character Texture"

    def draw_buttons(self, context, layout):
        step = self.pipeline_step
        is_busy = self.is_generating
        has_obj = bool(self.target_object_name and bpy.data.objects.get(self.target_object_name))
        has_dup = bool(self.char_dup_name and bpy.data.objects.get(self.char_dup_name))
        has_capture = bool(self.char_render_path and self._path_exists_cached(self.char_render_path))

        # --- Object selector ---
        layout.prop_search(self, "target_object_name", context.scene, "objects", text="Object")

        # --- Settings ---
        if step <= STEP_CAPTURED:
            col = layout.column(align=True)
            col.prop(self, "tex_size", text="Size")
            row = col.row(align=True)
            row.prop(self, "uv_angle_limit", text="Angle")
            row.prop(self, "uv_island_margin", text="Margin")

        layout.separator()

        # =================================================================
        # IDLE / CAPTURED — manual setup buttons
        # =================================================================
        if step <= STEP_CAPTURED and not is_busy:

            # Row 1: Setup Camera | Duplicate toggle
            row = layout.row(align=True)
            row.operator("neuro.character_setup_camera", text="Setup Camera",
                         icon='CAMERA_DATA').node_name = self.name

            if not has_dup:
                op = row.operator("neuro.character_create_duplicate", text="Duplicate",
                                  icon='MOD_MIRROR')
                op.node_name = self.name
            else:
                op = row.operator("neuro.character_delete_duplicate", text="Remove Dup",
                                  icon='TRASH')
                op.node_name = self.name

            # Row 2: Capture / Recapture
            layout.separator()
            row = layout.row(align=True)
            row.scale_y = 1.2
            cap_text = "Recapture" if has_capture else "Capture Viewport"
            cap_icon = 'FILE_REFRESH' if has_capture else 'RENDER_STILL'
            op = row.operator("neuro.character_capture", text=cap_text, icon=cap_icon)
            op.node_name = self.name
            row.enabled = has_obj

            # Show capture preview
            if has_capture:
                layout.separator()
                self.draw_preview(layout, self.char_render_path)

            # Editable enhance prompt (greyed out when Prompt In socket is connected)
            if has_capture:
                prompt_linked = (
                    "Prompt In" in self.inputs and self.inputs["Prompt In"].is_linked
                )
                layout.separator()
                col = layout.column(align=True)
                col.enabled = not prompt_linked
                col.label(text="Enhance Prompt:" if not prompt_linked else "Enhance Prompt (overridden by socket):")
                col.prop(self, "enhance_prompt", text="")
                row = col.row(align=True)
                op = row.operator("neuro.open_text_editor", text="Open Editor", icon='GREASEPENCIL')
                op.node_name = self.name
                op.prop_name = "enhance_prompt"
                op = row.operator("neuro.paste_to_node", text="", icon='PASTEDOWN')
                op.node_name = self.name
                op.prop_name = "enhance_prompt"

            # Row 3: Generate (only after capture)
            if has_capture:
                layout.separator()
                row = layout.row(align=True)
                row.scale_y = 1.3
                op = row.operator("neuro.character_texture_generate", text="Generate",
                                  icon='PLAY')
                op.node_name = self.name

        # =================================================================
        # GENERATING (busy)
        # =================================================================
        elif is_busy:
            box = layout.box()
            box.label(text=STEP_LABELS.get(step, "Working..."), icon='TIME')
            if self.status_message:
                box.label(text=self.status_message)
            row = box.row()
            row.operator("neuro.character_texture_cancel", text="Cancel",
                         icon='CANCEL').node_name = self.name

        # =================================================================
        # PICK ENHANCE / INPAINT
        # =================================================================
        elif step == STEP_PICK_ENHANCE:
            self._draw_pick_ui(layout, 'enhance')

        elif step == STEP_PICK_INPAINT:
            self._draw_pick_ui(layout, 'inpaint')

        # =================================================================
        # CONFIRM BAKE — show bake result before inpaint
        # =================================================================
        elif step == STEP_CONFIRM_BAKE:
            box = layout.box()
            box.label(text="Bake result", icon='TEXTURE')
            if self.char_bake_path and self._path_exists_cached(self.char_bake_path):
                self.draw_preview(box, self.char_bake_path)
            else:
                box.label(text="(bake image not found)", icon='ERROR')
            row = box.row(align=True)
            row.scale_y = 1.2
            op = row.operator("neuro.character_texture_continue", text="Inpaint Gaps",
                              icon='PLAY')
            op.node_name = self.name
            op.phase = "confirm_bake"
            row.operator("neuro.character_texture_cancel", text="Cancel",
                         icon='CANCEL').node_name = self.name

        # =================================================================
        # DONE
        # =================================================================
        elif step == STEP_DONE:
            if self.result_path and self._path_exists_cached(self.result_path):
                self.draw_preview(layout, self.result_path)
                row = layout.row(align=True)
                op = row.operator("neuro.node_view_full_image", text="",
                                  icon='FULLSCREEN_ENTER')
                op.image_path = self.result_path
            box = layout.box()
            box.label(text="Pipeline complete", icon='CHECKMARK')
            row = box.row(align=True)
            op = row.operator("neuro.character_texture_continue", text="Redo Gap Fill",
                              icon='LOOP_BACK')
            op.node_name = self.name
            op.phase = 'redo_inpaint'
            op = row.operator("neuro.character_texture_run", text="Start Over",
                              icon='FILE_REFRESH')
            op.node_name = self.name
            if has_dup:
                row.operator("neuro.character_delete_duplicate", text="Remove Dup",
                             icon='TRASH').node_name = self.name

    def _draw_pick_ui(self, layout, phase):
        """Draw grid of results with pick buttons"""
        results = self._get_results_list(phase)
        sel_idx = self.selected_enhance_index if phase == 'enhance' else self.selected_inpaint_index

        if not results:
            layout.label(text="No results", icon='ERROR')
            return

        box = layout.box()
        label = "Pick texture" if phase == 'enhance' else "Pick inpaint"
        box.label(text=label, icon='RESTRICT_SELECT_OFF')

        # Batch navigation (shown when multiple batches exist)
        batches = self._get_all_batches(phase)
        total_batches = len(batches)
        cur_batch = self.enhance_batch_index if phase == 'enhance' else self.inpaint_batch_index
        if total_batches > 1:
            row = box.row(align=True)
            op = row.operator("neuro.character_texture_navigate", text="", icon='TRIA_LEFT')
            op.node_name = self.name
            op.phase = phase
            op.direction = 'prev'
            row.label(text=f"Batch {cur_batch + 1}/{total_batches}")
            op = row.operator("neuro.character_texture_navigate", text="", icon='TRIA_RIGHT')
            op.node_name = self.name
            op.phase = phase
            op.direction = 'next'

        # Side-by-side grid previews
        self._draw_grid_preview(box, results)

        # Pick buttons row (separate from previews)
        row = box.row(align=True)
        for i, path in enumerate(results):
            is_selected = (i == sel_idx)
            icon = 'RADIOBUT_ON' if is_selected else 'RADIOBUT_OFF'
            op = row.operator("neuro.character_texture_pick",
                              text=str(i + 1), icon=icon, depress=is_selected)
            op.node_name = self.name
            op.phase = phase
            op.index = i

        # Buttons row
        box.separator()
        row = box.row(align=True)
        row.scale_y = 1.2

        retry_phase = 'retry_enhance' if phase == 'enhance' else 'retry_inpaint'
        op_retry = row.operator("neuro.character_texture_continue",
                                text="Retry", icon='FILE_REFRESH')
        op_retry.node_name = self.name
        op_retry.phase = retry_phase

        apply_label = "Apply" if phase == 'inpaint' else "Continue"
        op = row.operator("neuro.character_texture_continue", text=apply_label,
                          icon='CHECKMARK')
        op.node_name = self.name
        op.phase = phase


# =============================================================================
# OPERATOR: SETUP CAMERA
# =============================================================================

class NEURO_OT_character_setup_camera(Operator):
    """Create or find ortho camera for character capture"""
    bl_idname = "neuro.character_setup_camera"
    bl_label = "Setup Character Camera"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        cam_obj = bpy.data.objects.get(CHAR_CAM_NAME)

        if cam_obj and cam_obj.type == 'CAMERA':
            self.report({'INFO'}, f"Camera '{CHAR_CAM_NAME}' exists — entering view")
        else:
            cam_data = bpy.data.cameras.new(CHAR_CAM_NAME)
            cam_data.type = 'ORTHO'
            cam_data.ortho_scale = CAM_ORTHO_SCALE
            cam_obj = bpy.data.objects.new(CHAR_CAM_NAME, cam_data)
            context.collection.objects.link(cam_obj)
            cam_obj.location = CAM_LOCATION
            cam_obj.rotation_euler = CAM_ROTATION
            self.report({'INFO'}, "Created ortho camera — adjust if needed")

        context.scene.camera = cam_obj
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.region_3d.view_perspective = 'CAMERA'
                        break
                break

        return {'FINISHED'}


# =============================================================================
# OPERATOR: CREATE DUPLICATE
# =============================================================================

class NEURO_OT_character_create_duplicate(Operator):
    """Create linked duplicate rotated 180 for back view"""
    bl_idname = "neuro.character_create_duplicate"
    bl_label = "Create Back Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        obj = bpy.data.objects.get(node.target_object_name)
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first")
            return {'CANCELLED'}

        # Clean up old duplicate
        if node.char_dup_name:
            old = bpy.data.objects.get(node.char_dup_name)
            if old:
                bpy.data.objects.remove(old, do_unlink=True)
            node.char_dup_name = ""

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.duplicate(linked=True)
        dup = context.active_object
        node.char_dup_name = dup.name

        dup.rotation_euler.z = obj.rotation_euler.z + radians(180)

        char_width = obj.dimensions.x
        dup.location.x = obj.location.x + char_width * 1.3

        self.report({'INFO'}, f"Created back-view duplicate: {dup.name}")
        return {'FINISHED'}


# =============================================================================
# OPERATOR: DELETE DUPLICATE
# =============================================================================

class NEURO_OT_character_delete_duplicate(Operator):
    """Remove the back-view duplicate"""
    bl_idname = "neuro.character_delete_duplicate"
    bl_label = "Remove Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        if node.char_dup_name:
            dup = bpy.data.objects.get(node.char_dup_name)
            if dup:
                bpy.data.objects.remove(dup, do_unlink=True)
            node.char_dup_name = ""
            self.report({'INFO'}, "Duplicate removed")
        return {'FINISHED'}


# =============================================================================
# OPERATOR: CAPTURE VIEWPORT
# =============================================================================

class NEURO_OT_character_capture(Operator):
    """Render viewport through character camera and save result"""
    bl_idname = "neuro.character_capture"
    bl_label = "Capture Viewport"
    bl_options = {'REGISTER'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        obj = bpy.data.objects.get(node.target_object_name)
        if not obj:
            self.report({'ERROR'}, "Object missing")
            return {'CANCELLED'}

        cam_obj = bpy.data.objects.get(CHAR_CAM_NAME)
        if not cam_obj or cam_obj.type != 'CAMERA':
            self.report({'ERROR'}, f"Camera '{CHAR_CAM_NAME}' not found — click Setup Camera")
            return {'CANCELLED'}

        scn = context.scene

        # Save originals
        orig_engine = scn.render.engine
        orig_film = scn.render.film_transparent
        orig_cam = scn.camera
        orig_res_x = scn.render.resolution_x
        orig_res_y = scn.render.resolution_y

        try:
            scn.render.engine = 'BLENDER_EEVEE_NEXT'
            scn.render.film_transparent = True
            scn.camera = cam_obj

            tex_size = int(node.tex_size)
            scn.render.resolution_x = tex_size
            scn.render.resolution_y = tex_size

            bpy.ops.render.render()

            # Save Render Result to disk
            gen_dir = get_generations_folder("team_char")
            render_filename = get_unique_filename(gen_dir, "char_render")
            render_path = os.path.join(gen_dir, render_filename)

            render_img = bpy.data.images.get('Render Result')
            if render_img:
                render_img.save_render(filepath=render_path, scene=scn)
            else:
                self.report({'ERROR'}, "No Render Result found")
                return {'CANCELLED'}

            # Invalidate old preview cache
            if node.char_render_path:
                NeuroNodeBase.invalidate_file_cache(node.char_render_path)

            node.char_render_path = render_path
            node.pipeline_step = STEP_CAPTURED
            node.status_message = "Captured"
            print(f"[{LOG_PREFIX}] Character capture saved: {render_path}")

            self.report({'INFO'}, "Viewport captured")

        finally:
            scn.render.engine = orig_engine
            scn.render.film_transparent = orig_film
            scn.camera = orig_cam
            scn.render.resolution_x = orig_res_x
            scn.render.resolution_y = orig_res_y

        return {'FINISHED'}


# =============================================================================
# OPERATOR: GENERATE (starts AI enhance)
# =============================================================================

class NEURO_OT_character_texture_generate(Operator):
    """Generate AI texture variations from captured viewport"""
    bl_idname = "neuro.character_texture_generate"
    bl_label = "Generate"
    bl_options = {'REGISTER'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        if not node.char_render_path or not os.path.exists(node.char_render_path):
            self.report({'ERROR'}, "No capture found — click Capture first")
            return {'CANCELLED'}

        obj = bpy.data.objects.get(node.target_object_name)
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Target object missing")
            return {'CANCELLED'}

        if not obj.data.materials:
            self.report({'ERROR'}, "Object has no materials")
            return {'CANCELLED'}

        # Store original UV
        if obj.data.uv_layers.active:
            node.char_orig_uv_name = obj.data.uv_layers.active.name
        else:
            node.char_orig_uv_name = ""

        node.pipeline_step = STEP_AI_ENHANCE
        node.is_generating = True
        node.status_message = "Generating texture variations..."
        node.enhance_results = "[]"
        node.inpaint_results = "[]"
        node.enhance_batch_index = 0
        node.inpaint_batch_index = 0
        node.enhance_retry_mode = False
        node.inpaint_retry_mode = False
        node.result_path = ""
        cancel_event.clear()

        _pipeline_step_ai_enhance(ntree.name, node.name)
        return {'FINISHED'}


# =============================================================================
# OPERATOR: RE-RUN (reset to idle)
# =============================================================================

class NEURO_OT_character_texture_run(Operator):
    """Reset pipeline to idle for re-run"""
    bl_idname = "neuro.character_texture_run"
    bl_label = "Re-run Pipeline"
    bl_options = {'REGISTER'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        node.pipeline_step = STEP_IDLE
        node.is_generating = False
        node.status_message = ""
        node.enhance_results = "[]"
        node.inpaint_results = "[]"
        node.enhance_batch_index = 0
        node.inpaint_batch_index = 0
        node.result_path = ""
        return {'FINISHED'}


# =============================================================================
# OPERATOR: CANCEL
# =============================================================================

class NEURO_OT_character_texture_cancel(Operator):
    """Cancel character texture pipeline"""
    bl_idname = "neuro.character_texture_cancel"
    bl_label = "Cancel"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        cancel_event.set()
        ntree = get_node_tree(context, None)
        if ntree:
            node = ntree.nodes.get(self.node_name)
            if node:
                if node.pipeline_step in (STEP_AI_INPAINT,) and node.char_bake_path:
                    node.pipeline_step = STEP_CONFIRM_BAKE
                elif node.char_render_path:
                    node.pipeline_step = STEP_CAPTURED
                else:
                    node.pipeline_step = STEP_IDLE
                node.is_generating = False
                node.status_message = "Cancelled"
        return {'FINISHED'}


# =============================================================================
# OPERATOR: PICK FROM GRID
# =============================================================================

class NEURO_OT_character_texture_pick(Operator):
    """Pick a generation result"""
    bl_idname = "neuro.character_texture_pick"
    bl_label = "Pick"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()
    phase: StringProperty()
    index: IntProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        if self.phase == 'enhance':
            node.selected_enhance_index = self.index
        else:
            node.selected_inpaint_index = self.index

        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


# =============================================================================
# OPERATOR: NAVIGATE BETWEEN BATCHES
# =============================================================================

class NEURO_OT_character_texture_navigate(Operator):
    """Navigate between generation batches"""
    bl_idname = "neuro.character_texture_navigate"
    bl_label = "Navigate Batch"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()
    phase: StringProperty()
    direction: StringProperty()  # 'prev' or 'next'

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        batches = node._get_all_batches(self.phase)
        total = len(batches)
        if total <= 1:
            return {'FINISHED'}

        delta = 1 if self.direction == 'next' else -1
        if self.phase == 'enhance':
            node.enhance_batch_index = max(0, min(total - 1, node.enhance_batch_index + delta))
            node.selected_enhance_index = 0
        else:
            node.inpaint_batch_index = max(0, min(total - 1, node.inpaint_batch_index + delta))
            node.selected_inpaint_index = 0

        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


# =============================================================================
# OPERATOR: CONTINUE AFTER PICK
# =============================================================================

class NEURO_OT_character_texture_continue(Operator):
    """Continue pipeline after picking a result"""
    bl_idname = "neuro.character_texture_continue"
    bl_label = "Continue"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()
    phase: StringProperty()

    def execute(self, context):
        ntree = get_node_tree(context, None)
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        ntree_name = ntree.name
        node_name = node.name

        if self.phase == 'enhance':
            results = node._get_results_list('enhance')
            idx = node.selected_enhance_index
            if not results or idx >= len(results):
                self.report({'ERROR'}, "No result selected")
                return {'CANCELLED'}

            picked_path = results[idx]
            node.pipeline_step = STEP_UV_BAKE
            node.is_generating = True
            node.status_message = "Setting up UV & projecting..."

            obj_name = node.target_object_name or ""
            if not obj_name:
                self.report({'ERROR'}, "Target object missing")
                return {'CANCELLED'}

            cam_name = CHAR_CAM_NAME

            def step_uv_bake():
                _pipeline_step_uv_bake(ntree_name, node_name, obj_name, cam_name,
                                       picked_path, context)
                return None

            bpy.app.timers.register(step_uv_bake, first_interval=0.2)

        elif self.phase == 'confirm_bake':
            # User reviewed bake result → start AI inpaint
            node.pipeline_step = STEP_AI_INPAINT
            node.is_generating = True
            node.status_message = "Inpainting texture gaps..."
            cancel_event.clear()
            _pipeline_step_ai_inpaint(ntree_name, node_name)

        elif self.phase == 'regenerate_inpaint':
            node.pipeline_step = STEP_AI_INPAINT
            node.is_generating = True
            node.inpaint_results = "[]"
            node.inpaint_batch_index = 0
            node.status_message = "Inpainting texture gaps..."
            cancel_event.clear()
            _pipeline_step_ai_inpaint(ntree_name, node_name)

        elif self.phase == 'retry_enhance':
            node.selected_enhance_index = 0
            node.enhance_retry_mode = True
            node.pipeline_step = STEP_AI_ENHANCE
            node.is_generating = True
            node.status_message = "Generating new batch..."
            cancel_event.clear()
            _pipeline_step_ai_enhance(ntree_name, node_name)

        elif self.phase == 'retry_inpaint':
            node.selected_inpaint_index = 0
            node.inpaint_retry_mode = True
            node.pipeline_step = STEP_AI_INPAINT
            node.is_generating = True
            node.status_message = "Generating new inpaint batch..."
            cancel_event.clear()
            _pipeline_step_ai_inpaint(ntree_name, node_name)

        elif self.phase == 'redo_inpaint':
            node.inpaint_results = "[]"
            node.inpaint_batch_index = 0
            node.inpaint_retry_mode = False
            node.result_path = ""
            node.pipeline_step = STEP_CONFIRM_BAKE
            node.is_generating = False
            node.status_message = "Review bake result"

        elif self.phase == 'inpaint':
            results = node._get_results_list('inpaint')
            idx = node.selected_inpaint_index
            if not results or idx >= len(results):
                self.report({'ERROR'}, "No result selected")
                return {'CANCELLED'}

            node.result_path = results[idx]
            node.pipeline_step = STEP_DONE
            node.is_generating = False
            node.status_message = "Done"

            if "Image" in node.outputs:
                for link in node.outputs["Image"].links:
                    to_sock = link.to_socket
                    if hasattr(to_sock, 'image_path'):
                        to_sock.image_path = node.result_path

        return {'FINISHED'}


# =============================================================================
# PIPELINE: AI ENHANCE
# =============================================================================

def _pipeline_step_ai_enhance(ntree_name, node_name):
    """Generate 2 texture variations from captured viewport render"""

    tree = bpy.data.node_groups.get(ntree_name)
    if not tree:
        return
    node = tree.nodes.get(node_name)
    if not node:
        return

    render_path = node.char_render_path
    if not render_path or not os.path.exists(render_path):
        node.is_generating = False
        node.status_message = "Render image missing"
        node.pipeline_step = STEP_IDLE
        return

    # Build prompt
    text_input = node.get_input_prompt()
    if text_input and text_input.strip():
        prompt = text_input.strip()
    else:
        prompt = node.enhance_prompt

    refs = node.get_input_images()
    if refs:
        prompt += " Use the provided reference images for style and color guidance."

    input_images = [render_path] + refs

    model_id = None
    api_keys = {}
    try:
        api_keys = get_all_api_keys(bpy.context)
        model_id = get_artist_tool_model(bpy.context, 'pro')
    except Exception as e:
        print(f"[{LOG_PREFIX}] Failed to get API keys/model: {e}")

    if not model_id:
        node.is_generating = False
        node.status_message = "No model available (check API keys)"
        node.pipeline_step = STEP_IDLE
        return

    log_node_generation("CharTexture:Enhance", model_id, prompt, input_images)

    def work_func():
        from ..api import generate_images
        cancel_event.clear()
        paths = []
        gen_dir = get_generations_folder("team_char")
        for i in range(2):
            if cancel_event.is_set():
                break
            try:
                imgs = generate_images(
                    model_id=model_id,
                    prompt=prompt,
                    image_paths=input_images,
                    num_outputs=1,
                    api_keys=api_keys,
                    timeout=180,
                    aspect_ratio="1:1",
                    cancel_event=cancel_event,
                )
                for img in (imgs or []):
                    fname = get_unique_filename(gen_dir, f"char_enhance_{i}")
                    fpath = os.path.join(gen_dir, fname)
                    img.save(fpath, format="PNG")
                    paths.append(fpath)
                    print(f"[{LOG_PREFIX}] Enhance variation {i+1} saved: {fpath}")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Enhance variation {i+1} failed: {e}")
        return paths

    def on_complete(node, result, error_msg, duration):
        if error_msg:
            node.is_generating = False
            node.status_message = f"Error: {error_msg}"
            node.pipeline_step = STEP_CAPTURED
            return

        paths = result or []
        print(f"[{LOG_PREFIX}] CharTexture:Enhance returned {len(paths)} images")
        if not paths:
            node.is_generating = False
            node.status_message = "No images generated"
            node.pipeline_step = STEP_CAPTURED
            return

        retry = node.enhance_retry_mode
        node.enhance_retry_mode = False
        node._set_results_list('enhance', paths, append=retry)
        node.selected_enhance_index = 0
        node.pipeline_step = STEP_PICK_ENHANCE
        node.is_generating = False
        node.status_message = "Pick best result"
        log_node_result("CharTexture:Enhance", True, duration=duration)

    run_node_worker(ntree_name, node_name, work_func, on_complete,
                    log_type="CharTexture:Enhance", model_id=model_id or "")



# =============================================================================
# PIPELINE: UV SETUP + PROJECT + BAKE
# =============================================================================

def _pipeline_step_uv_bake(ntree_name, node_name, obj_name, cam_name,
                           picked_path, context):
    """UV setup, camera project, island offset, bake — ends at CONFIRM_BAKE"""

    tree = bpy.data.node_groups.get(ntree_name)
    if not tree:
        return
    node = tree.nodes.get(node_name)
    if not node:
        return
    if cancel_event.is_set():
        node.is_generating = False
        node.pipeline_step = STEP_CAPTURED
        return

    obj = bpy.data.objects.get(obj_name)
    cam_obj = bpy.data.objects.get(cam_name)
    if not obj or not cam_obj:
        node.is_generating = False
        node.status_message = "Object or camera lost"
        node.pipeline_step = STEP_CAPTURED
        return

    tex_size = int(node.tex_size)
    scn = bpy.context.scene

    try:
        # =================================================================
        # 1. Create _AI UV layer + smart unwrap
        # =================================================================
        node.status_message = "Creating AI UV layer..."
        print(f"[{LOG_PREFIX}] Step: UV setup")

        mesh = obj.data
        ai_uv_name = node.char_ai_uv_name

        existing = mesh.uv_layers.get(ai_uv_name)
        if existing:
            mesh.uv_layers.remove(existing)

        ai_uv = mesh.uv_layers.new(name=ai_uv_name)
        mesh.uv_layers.active = ai_uv

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        bpy.ops.uv.smart_project(
            angle_limit=radians(node.uv_angle_limit),
            island_margin=node.uv_island_margin,
        )
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"[{LOG_PREFIX}] UV layer '{ai_uv_name}' created and unwrapped")

        if cancel_event.is_set():
            node.is_generating = False
            node.pipeline_step = STEP_CAPTURED
            return

        # =================================================================
        # 2. Create grey texture + connect to shader Base Color
        # =================================================================
        node.status_message = "Creating projection texture..."
        print(f"[{LOG_PREFIX}] Step: Grey texture + shader connect")

        grey_tex_name = f"_CharTex_{obj.name}_grey"
        old_grey = bpy.data.images.get(grey_tex_name)
        if old_grey:
            bpy.data.images.remove(old_grey)

        grey_img = bpy.data.images.new(grey_tex_name, tex_size, tex_size, alpha=False)
        grey_pixels = [0.5, 0.5, 0.5, 1.0] * (tex_size * tex_size)
        grey_img.pixels[:] = grey_pixels

        mat = obj.data.materials[0]
        if not mat.use_nodes:
            mat.use_nodes = True
        ntree_mat = mat.node_tree

        output_node = None
        for n in ntree_mat.nodes:
            if n.type == 'OUTPUT_MATERIAL' and n.is_active_output:
                output_node = n
                break

        shader_node = None
        if output_node and output_node.inputs['Surface'].is_linked:
            shader_node = output_node.inputs['Surface'].links[0].from_node

        # Create image texture node for grey (connected to shader for preview)
        tex_node = ntree_mat.nodes.new('ShaderNodeTexImage')
        tex_node.image = grey_img
        tex_node.location = (-400, 0)
        tex_node.label = "AI Projection"
        tex_node.name = "_CharTex_projection"

        # CRITICAL: Create UV Map node explicitly pointing at _AI UV layer
        # Without this, the texture reads from whichever UV is "active" —
        # which breaks baking when we switch active to original UV.
        uv_map_node = ntree_mat.nodes.new('ShaderNodeUVMap')
        uv_map_node.uv_map = ai_uv_name  # "_AI"
        uv_map_node.location = (-650, 0)
        uv_map_node.label = "AI UV"
        uv_map_node.name = "_CharTex_uv_map"
        ntree_mat.links.new(uv_map_node.outputs['UV'], tex_node.inputs['Vector'])

        if shader_node:
            color_input = None
            if 'Base Color' in shader_node.inputs:
                color_input = shader_node.inputs['Base Color']
            elif 'Color' in shader_node.inputs:
                color_input = shader_node.inputs['Color']
            if color_input:
                ntree_mat.links.new(tex_node.outputs['Color'], color_input)

        ntree_mat.nodes.active = tex_node

        if cancel_event.is_set():
            node.is_generating = False
            node.pipeline_step = STEP_CAPTURED
            return

        # =================================================================
        # 3. Project camera image via texture paint on BOTH objects
        #    Linked duplicate shares mesh data — front + back projection
        # =================================================================
        node.status_message = "Projecting AI texture..."
        print(f"[{LOG_PREFIX}] Step: Camera projection (both views)")

        picked_img = bpy.data.images.load(picked_path, check_existing=True)
        scn.camera = cam_obj

        # Find 3D viewport for context override
        view3d_area = None
        view3d_region = None
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                view3d_area = area
                for region in area.regions:
                    if region.type == 'WINDOW':
                        view3d_region = region
                        break
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.region_3d.view_perspective = 'CAMERA'
                        break
                break

        # Project on each object: original (front faces) + duplicate (back faces)
        dup_obj = bpy.data.objects.get(node.char_dup_name) if node.char_dup_name else None
        project_targets = [obj]
        if dup_obj:
            project_targets.append(dup_obj)

        for proj_obj in project_targets:
            bpy.ops.object.select_all(action='DESELECT')
            proj_obj.select_set(True)
            bpy.context.view_layer.objects.active = proj_obj
            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')

            if view3d_area and view3d_region:
                with bpy.context.temp_override(area=view3d_area, region=view3d_region):
                    bpy.ops.paint.project_image(image=picked_img.name)
            else:
                bpy.ops.paint.project_image(image=picked_img.name)

            bpy.ops.object.mode_set(mode='OBJECT')
            print(f"[{LOG_PREFIX}] Projected on: {proj_obj.name}")

        if cancel_event.is_set():
            node.is_generating = False
            node.pipeline_step = STEP_CAPTURED
            return

        # =================================================================
        # 4. Switch to original UV + move ONLY overlapping islands
        # =================================================================
        node.status_message = "Adjusting UV islands..."
        print(f"[{LOG_PREFIX}] Step: UV island overlap fix")

        orig_uv_name = node.char_orig_uv_name
        if orig_uv_name and orig_uv_name in mesh.uv_layers:
            mesh.uv_layers.active = mesh.uv_layers[orig_uv_name]

        moved = _move_overlapping_uv_islands(obj, offset_x=-1.0)
        print(f"[{LOG_PREFIX}] Moved {moved} overlapping islands out of bounds")

        if cancel_event.is_set():
            node.is_generating = False
            node.pipeline_step = STEP_CAPTURED
            return

        # =================================================================
        # 5. Create SEPARATE pink bake target (NOT connected to shader)
        # =================================================================
        node.status_message = "Preparing bake texture..."
        print(f"[{LOG_PREFIX}] Step: Bake setup")

        pink_tex_name = f"_CharTex_{obj.name}_bake"
        old_pink = bpy.data.images.get(pink_tex_name)
        if old_pink:
            bpy.data.images.remove(old_pink)

        pink_img = bpy.data.images.new(pink_tex_name, tex_size, tex_size, alpha=False)
        pink_pixels = [1.0, 0.0, 1.0, 1.0] * (tex_size * tex_size)
        pink_img.pixels[:] = pink_pixels

        # Create SEPARATE image texture node for bake target — NOT connected
        # This avoids "Circular dependency" error
        bake_node = ntree_mat.nodes.new('ShaderNodeTexImage')
        bake_node.image = pink_img
        bake_node.location = (-400, -300)
        bake_node.label = "Bake Target"
        bake_node.name = "_CharTex_bake_target"

        # Set bake_node as ACTIVE (bake writes to active node image)
        # tex_node stays connected to shader (bake reads from shader)
        ntree_mat.nodes.active = bake_node

        if cancel_event.is_set():
            node.is_generating = False
            node.pipeline_step = STEP_CAPTURED
            return

        # =================================================================
        # 6. Bake diffuse (Cycles) — on ORIGINAL UV layer
        # =================================================================
        node.status_message = "Baking diffuse..."
        print(f"[{LOG_PREFIX}] Step: Baking")

        # CRITICAL: ensure original UV is active for baking (not _AI)
        orig_uv_name = node.char_orig_uv_name
        if orig_uv_name and orig_uv_name in mesh.uv_layers:
            mesh.uv_layers.active = mesh.uv_layers[orig_uv_name]
            print(f"[{LOG_PREFIX}] Bake UV layer: {orig_uv_name}")
        else:
            print(f"[{LOG_PREFIX}] WARNING: original UV '{orig_uv_name}' not found, baking on active")

        orig_engine = scn.render.engine
        scn.render.engine = 'CYCLES'

        scn.render.bake.use_pass_direct = False
        scn.render.bake.use_pass_indirect = False
        scn.render.bake.use_pass_color = True
        scn.render.bake.use_selected_to_active = False
        scn.render.bake.max_ray_distance = 0.0

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.bake(type='DIFFUSE')

        scn.render.engine = orig_engine

        # Save bake to disk
        gen_dir = get_generations_folder("team_char")
        bake_filename = get_unique_filename(gen_dir, "char_bake")
        bake_path = os.path.join(gen_dir, bake_filename)
        pink_img.filepath_raw = bake_path
        pink_img.file_format = 'PNG'
        pink_img.save()
        node.char_bake_path = bake_path
        print(f"[{LOG_PREFIX}] Bake saved: {bake_path}")

        # =================================================================
        # Stop at CONFIRM_BAKE — user reviews before inpaint
        # =================================================================
        node.pipeline_step = STEP_CONFIRM_BAKE
        node.is_generating = False
        node.status_message = "Review bake result"

    except Exception as e:
        print(f"[{LOG_PREFIX}] UV/Bake pipeline error: {e}")
        import traceback
        traceback.print_exc()
        node.is_generating = False
        node.status_message = f"Error: {e}"
        node.pipeline_step = STEP_CAPTURED


# =============================================================================
# PIPELINE: AI INPAINT
# =============================================================================

def _pipeline_step_ai_inpaint(ntree_name, node_name):
    """Inpaint gaps on baked texture"""

    tree = bpy.data.node_groups.get(ntree_name)
    if not tree:
        return
    node = tree.nodes.get(node_name)
    if not node:
        return

    bake_path = node.char_bake_path
    if not bake_path or not os.path.exists(bake_path):
        node.is_generating = False
        node.status_message = "Bake image missing"
        node.pipeline_step = STEP_CAPTURED
        return

    prompt = INPAINT_PROMPT

    model_id = None
    api_keys = {}
    try:
        api_keys = get_all_api_keys(bpy.context)
        model_id = get_artist_tool_model(bpy.context, 'pro')
    except Exception as e:
        print(f"[{LOG_PREFIX}] Failed to get API keys/model for inpaint: {e}")

    if not model_id:
        node.is_generating = False
        node.status_message = "No model available"
        node.pipeline_step = STEP_CAPTURED
        return

    log_node_generation("CharTexture:Inpaint", model_id, prompt, [bake_path])

    def work_func():
        from ..api import generate_images
        cancel_event.clear()
        paths = []
        gen_dir = get_generations_folder("team_char")
        for i in range(2):
            if cancel_event.is_set():
                break
            try:
                imgs = generate_images(
                    model_id=model_id,
                    prompt=prompt,
                    image_paths=[bake_path],
                    num_outputs=1,
                    api_keys=api_keys,
                    timeout=180,
                    aspect_ratio="1:1",
                    cancel_event=cancel_event,
                )
                for img in (imgs or []):
                    fname = get_unique_filename(gen_dir, f"char_inpaint_{i}")
                    fpath = os.path.join(gen_dir, fname)
                    img.save(fpath, format="PNG")
                    paths.append(fpath)
                    print(f"[{LOG_PREFIX}] Inpaint variation {i+1} saved: {fpath}")
            except Exception as e:
                print(f"[{LOG_PREFIX}] Inpaint variation {i+1} failed: {e}")
        return paths

    def on_complete(node, result, error_msg, duration):
        if error_msg:
            node.is_generating = False
            node.status_message = f"Inpaint error: {error_msg}"
            node.pipeline_step = STEP_CAPTURED
            return

        paths = result or []
        print(f"[{LOG_PREFIX}] CharTexture:Inpaint returned {len(paths)} images")
        if not paths:
            node.is_generating = False
            node.status_message = "No inpaint results"
            node.pipeline_step = STEP_CAPTURED
            return

        retry = node.inpaint_retry_mode
        node.inpaint_retry_mode = False
        node._set_results_list('inpaint', paths, append=retry)
        node.selected_inpaint_index = 0
        node.pipeline_step = STEP_PICK_INPAINT
        node.is_generating = False
        node.status_message = "Pick best inpaint"
        log_node_result("CharTexture:Inpaint", True, duration=duration)

    run_node_worker(ntree_name, node_name, work_func, on_complete,
                    log_type="CharTexture:Inpaint", model_id=model_id or "")


# =============================================================================


# =============================================================================
# UV ISLAND HELPERS
# =============================================================================

def _move_overlapping_uv_islands(obj, offset_x=-1.0):
    """
    Move ONLY islands that overlap with another island.
    For each overlapping pair, move the one with fewer faces.
    Returns count of islands moved.
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.active
    if not uv_layer:
        bm.free()
        return 0

    # --- Build islands via flood-fill ---
    face_visited = set()
    islands = []

    for face in bm.faces:
        if face.index in face_visited:
            continue

        island_faces = []
        stack = [face]
        while stack:
            f = stack.pop()
            if f.index in face_visited:
                continue
            face_visited.add(f.index)
            island_faces.append(f)

            for loop in f.loops:
                uv = loop[uv_layer].uv.copy()
                for edge in loop.vert.link_edges:
                    for linked_face in edge.link_faces:
                        if linked_face.index in face_visited:
                            continue
                        for ll in linked_face.loops:
                            if ll.vert == loop.vert:
                                ll_uv = ll[uv_layer].uv
                                if (abs(ll_uv.x - uv.x) < 1e-5 and
                                        abs(ll_uv.y - uv.y) < 1e-5):
                                    stack.append(linked_face)
                                    break

        if island_faces:
            islands.append(island_faces)

    if len(islands) < 2:
        bm.free()
        return 0

    # --- Compute centroid per island ---
    island_centroids = []
    for island in islands:
        total_u, total_v = 0.0, 0.0
        count = 0
        for face in island:
            for loop in face.loops:
                total_u += loop[uv_layer].uv.x
                total_v += loop[uv_layer].uv.y
                count += 1
        if count > 0:
            island_centroids.append((total_u / count, total_v / count))
        else:
            island_centroids.append((999.0, 999.0))  # skip

    # --- Find stacked pairs: same centroid = mirrored/overlapping ---
    # Tolerance for centroid match (mirrored islands are nearly identical)
    CENTROID_TOL = 0.01
    overlapping_indices = set()
    for i in range(len(islands)):
        for j in range(i + 1, len(islands)):
            ci = island_centroids[i]
            cj = island_centroids[j]
            if (abs(ci[0] - cj[0]) < CENTROID_TOL and
                    abs(ci[1] - cj[1]) < CENTROID_TOL):
                # Stacked pair — move the one with fewer faces
                if len(islands[i]) <= len(islands[j]):
                    overlapping_indices.add(i)
                else:
                    overlapping_indices.add(j)
                print(f"[NEURO] Stacked island pair: {i} ({len(islands[i])} faces) <-> {j} ({len(islands[j])} faces)")

    # --- Move only the marked islands ---
    moved = 0
    for idx in overlapping_indices:
        for face in islands[idx]:
            for loop in face.loops:
                loop[uv_layer].uv.x += offset_x
        moved += 1

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return moved