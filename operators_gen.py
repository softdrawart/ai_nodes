# -*- coding: utf-8 -*-
"""
Blender AI Nodes - Generation Operators Module
Large generation operators for images, textures, and materials.
"""

import os
import math
import time
import threading
from datetime import datetime

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

from .constants import MODIFIERS_MAP, MAP_PROMPTS
from .utils import (
    get_api_keys, check_is_saved, get_generations_folder, unique_temp_path,
    register_temp_file, cleanup_temp_files, sanitize_filename, get_unique_filename,
    get_model_name_display, refresh_previews_and_collections, get_texture_api_size,
    progress_timer, cancel_event, temp_files_registry,
    get_conversation_history, set_conversation_history, clear_conversation_history,
    update_status, clear_status_bar
)
from .operators import get_current_gen_id, increment_gen_id
from . import status_manager

# =============================================================================
# IMAGE GENERATION OPERATOR
# =============================================================================

class NEURO_OT_generate_image(bpy.types.Operator):
    bl_idname = "neuro.generate_image"
    bl_label = "Generate"
    bl_description = "Generate images with Gemini or GPT Image"

    def execute(self, context):
        from .dependencies import FAL_AVAILABLE, REPLICATE_AVAILABLE
        from .api import generate_images
        from .utils import get_all_api_keys
        from .model_registry import get_model, Provider

        if not check_is_saved(self, context):
            return {'CANCELLED'}

        scn = context.scene
        prompt = scn.neuro_prompt_image.strip()
        google_key, fal_key, replicate_key, aiml_key = get_api_keys(context)
        all_api_keys = get_all_api_keys(context)

        if not prompt:
            self.report({'ERROR'}, "Please enter a prompt")
            return {'CANCELLED'}

        # Append modifiers to prompt
        modifiers = []
        if scn.neuro_mod_isometric:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_isometric", ""))
        if scn.neuro_mod_detailed:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_detailed", ""))
        if scn.neuro_mod_soft:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_soft", ""))
        if scn.neuro_mod_clean:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_clean", ""))
        if scn.neuro_mod_vibrant:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_vibrant", ""))
        if scn.neuro_mod_casual:
            modifiers.append(MODIFIERS_MAP.get("neuro_mod_casual", ""))

        if modifiers:
            prompt = prompt + " " + " ".join(modifiers)

        model_name = scn.neuro_generation_model

        # Check API keys based on model
        config = get_model(model_name)
        if config:
            required_key = config.requires_api_key
            key_value = all_api_keys.get(required_key, "").strip()
            if not key_value:
                key_names = {"google": "Google", "replicate": "Replicate", "fal": "Fal.AI", "aiml": "AIML"}
                self.report({'ERROR'}, f"Please enter {key_names.get(required_key, required_key)} API key in settings")
                return {'CANCELLED'}
        else:
            # Fallback for unknown models
            if model_name.startswith("gpt-image") or model_name.startswith("fal-gemini"):
                if not fal_key.strip():
                    self.report({'ERROR'}, "Please enter Fal.AI API key in settings")
                    return {'CANCELLED'}
            else:
                if not google_key.strip():
                    self.report({'ERROR'}, "Please enter Google API key in settings")
                    return {'CANCELLED'}

        refs = [r.path for r in scn.neuro_reference_images if os.path.exists(r.path)]
        num_out = max(1, min(4, scn.neuro_num_outputs))

        model_display = get_model_name_display(model_name)

        my_gen_id = increment_gen_id()

        cancel_event.clear()
        scn.neuro_is_generating = True
        update_status(context, f"Generating with {model_display}...")

        # --- STATUS MANAGER START ---
        job_id = status_manager.add_job(f"Image: {prompt[:30]}", model_name, "Generate")
        status_manager.start_job(job_id)

        # Build model_params from registry
        model_params = {}
        try:
            from .model_registry import get_model
            config = get_model(model_name)
            if config:
                for param in config.params:
                    model_params[param.name] = param.default
        except Exception:
            pass

        def worker_job(prompt_local, refs_local, num_local, model_local, api_keys_local, timeout,
                       aspect_ratio, resolution, use_thoughts, model_params_local, gen_id, job_id):
            if gen_id != get_current_gen_id() or cancel_event.is_set():
                status_manager.cancel_job(job_id)
                return

            error_message = None
            imgs = []
            timed_out = False

            try:
                def update_progress(value):
                    pass

                progress_timer.start()

                # Handle thought signatures for Gemini 3
                if use_thoughts and model_local.startswith("gemini-3"):
                    result = generate_images(
                        model_id=model_local,
                        prompt=prompt_local,
                        image_paths=refs_local,
                        num_outputs=num_local,
                        api_keys=api_keys_local,
                        timeout=timeout,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                        model_params=model_params_local,
                        use_thought_signatures=True,
                        conversation_history=get_conversation_history(),
                        progress_callback=update_progress,
                        cancel_event=cancel_event,
                    )
                    imgs, new_history = result
                    set_conversation_history(new_history)
                    user_turns = sum(1 for turn in new_history if turn.get("role") == "user")
                    print(f"[{LOG_PREFIX}] Conversation: {user_turns} user turn(s)")
                else:
                    if not use_thoughts:
                        clear_conversation_history()
                    imgs = generate_images(
                        model_id=model_local,
                        prompt=prompt_local,
                        image_paths=refs_local,
                        num_outputs=num_local,
                        api_keys=api_keys_local,
                        timeout=timeout,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                        model_params=model_params_local,
                        progress_callback=update_progress,
                        cancel_event=cancel_event,
                    )

                progress_timer.stop()

            except TimeoutError:
                timed_out = True
                error_message = "Generation timed out"
                progress_timer.stop()
            except Exception as e:
                error_str = str(e)
                if "401" in error_str or "unauthorized" in error_str.lower():
                    error_message = "Invalid API key"
                elif "503" in error_str or "overloaded" in error_str:
                    error_message = "Server overloaded"
                else:
                    error_message = str(e)[:100]
                progress_timer.stop()
                if not cancel_event.is_set():
                    print(f"[{LOG_PREFIX}] Gen error: {e}")

            # Status Manager Update
            if cancel_event.is_set():
                status_manager.cancel_job(job_id)
            elif imgs:
                status_manager.complete_job(job_id, success=True)
            else:
                status_manager.complete_job(job_id, success=False, error=error_message)

            saved_paths = []
            if gen_id == get_current_gen_id() and not cancel_event.is_set() and imgs:
                batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                gen_dir = get_generations_folder()

                words = prompt_local.split()[:3]
                base_name = "_".join(word for word in words if len(word) > 2) or "generated"
                base_name = sanitize_filename(base_name)

                for i, pil_img in enumerate(imgs, 1):
                    filename = get_unique_filename(gen_dir, base_name)
                    save_path = os.path.join(gen_dir, filename)
                    try:
                        pil_img.save(save_path, format="PNG")
                        saved_paths.append((save_path, prompt_local, batch_id, i, len(imgs), model_local))
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed saving image:", e)

            def main_thread_update():
                if gen_id != get_current_gen_id():
                    clear_status_bar(bpy.context)
                    return None

                scn_inner = bpy.context.scene
                scn_inner.neuro_is_generating = False

                if cancel_event.is_set():
                    update_status(bpy.context, "Generation cancelled")
                    clear_status_bar(bpy.context)
                    return None

                if saved_paths:
                    for path, orig_prompt, b_id, b_idx, b_total, model_name in saved_paths:
                        entry = scn_inner.neuro_generated_images.add()
                        entry.path = path
                        entry.prompt = orig_prompt
                        entry.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        entry.batch_id = b_id
                        entry.batch_index = b_idx
                        entry.batch_total = b_total
                        entry.favorite = False
                        entry.model_used = model_name

                    refresh_previews_and_collections(scn_inner)
                    msg = f"Generated {len(saved_paths)} image(s)"
                    update_status(bpy.context, msg)

                    try:
                        from .utils import safe_show_in_editor
                        first_path = saved_paths[0][0]
                        safe_show_in_editor(first_path, reload_existing=True)
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Failed to auto-load image: {e}")
                else:
                    msg = error_message or ("Timed out" if timed_out else "Failed")
                    update_status(bpy.context, msg)

                cleanup_temp_files()

                def clear_bar():
                    clear_status_bar(bpy.context)
                    return None

                bpy.app.timers.register(clear_bar, first_interval=5.0)
                return None

            bpy.app.timers.register(main_thread_update, first_interval=0.2)

        resolution = scn.neuro_texture_resolution
        use_thoughts = scn.neuro_use_thought_signatures

        # PASS JOB_ID HERE
        threading.Thread(target=worker_job,
                         args=(prompt, refs, num_out, model_name, all_api_keys, scn.neuro_timeout,
                               scn.neuro_aspect_ratio, resolution, use_thoughts, model_params, my_gen_id, job_id),
                         daemon=True).start()
        return {'FINISHED'}


# =============================================================================
# TEXTURE GENERATION OPERATOR
# =============================================================================

class NEURO_OT_generate_texture(bpy.types.Operator):
    bl_idname = "neuro.generate_texture"
    bl_label = "Generate Texture"
    bl_description = "Generate texture for selected object using current camera view"

    uv_behavior: bpy.props.EnumProperty(
        name="UV Handling",
        items=[
            ('NEW', "Create New UV Slot", "Create a new UV Map (Safe)"),
            ('OVERWRITE', "Overwrite Active", "Project onto current UV Map (Destructive)"),
        ],
        default='NEW'
    )
    process_remove_bg: bpy.props.BoolProperty(
        name="Remove Background",
        description="Remove background via Fal.AI before generating map (Recommended)",
        default=True
    )

    def invoke(self, context, event):
        from .dependencies import FAL_AVAILABLE

        scn = context.scene
        gen_type = getattr(scn, "neuro_texture_gen_type", "COLOR")

        if gen_type != 'COLOR':
            if len(scn.neuro_reference_images) > 0 and FAL_AVAILABLE:
                path = scn.neuro_reference_images[0].path
                fname = os.path.basename(path)
                if not fname.startswith("nobg_"):
                    return context.window_manager.invoke_props_dialog(self, width=300)
            return self.execute(context)

        obj = context.active_object
        is_gpt = scn.neuro_generation_model == "gpt-image-1"
        has_uvs = obj and obj.type == 'MESH' and len(obj.data.uv_layers) > 0

        if is_gpt or has_uvs:
            return context.window_manager.invoke_props_dialog(self, width=350)
        else:
            return self.execute(context)

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        gen_type = getattr(scn, "neuro_texture_gen_type", "COLOR")

        if gen_type != 'COLOR':
            col = layout.column()
            col.label(text="Input Pre-processing", icon='FILTER')
            col.prop(self, "process_remove_bg", icon='BRUSH_DATA')
            col.label(text="Removes background for better map extraction.", icon='INFO')
        else:
            obj = context.active_object
            if scn.neuro_generation_model == "gpt-image-1":
                box = layout.box()
                box.label(text=" GPT Image Model Selected", icon='ERROR')
                box.label(text="Creates concepts, not aligned textures.")
                layout.separator()

            if obj and obj.type == 'MESH' and len(obj.data.uv_layers) > 0:
                box = layout.box()
                box.label(text="Object has existing UVs!", icon='UV')
                row = box.row()
                row.prop(self, "uv_behavior", expand=True)
                if self.uv_behavior == 'OVERWRITE':
                    box.label(text=" Destroys current UVs!", icon='CANCEL')

    def execute(self, context):
        from .dependencies import FAL_AVAILABLE, REPLICATE_AVAILABLE
        from .api import generate_images, remove_background
        from .utils import get_all_api_keys

        if not check_is_saved(self, context):
            return {'CANCELLED'}

        scn = context.scene
        gen_type = getattr(scn, "neuro_texture_gen_type", "COLOR")
        prompt = scn.neuro_prompt_texture.strip()
        google_key, fal_key, replicate_key, aiml_key = get_api_keys(context)
        all_api_keys = get_all_api_keys(context)

        my_gen_id = increment_gen_id()
        cancel_event.clear()
        scn.neuro_is_generating = True

        # === PATH 1: PBR MAP GENERATION ===
        if gen_type != 'COLOR':
            if len(scn.neuro_reference_images) == 0:
                self.report({'ERROR'}, "Map generation requires an input image")
                return {'CANCELLED'}

            ref_path = scn.neuro_reference_images[0].path
            if not os.path.exists(ref_path):
                return {'CANCELLED'}
            if not google_key:
                return {'CANCELLED'}

            model_name = "gemini-3-pro-image-preview"
            final_prompt = MAP_PROMPTS.get(gen_type, prompt)

            scn.neuro_status = f"Preparing {gen_type.lower()} map..."

            # --- STATUS MANAGER ---
            job_id = status_manager.add_job(f"Map: {gen_type}", model_name, "Texture")
            status_manager.start_job(job_id)

            # Check if BG removal is available
            has_bg_removal = (REPLICATE_AVAILABLE and all_api_keys.get("replicate")) or \
                            (FAL_AVAILABLE and all_api_keys.get("fal"))

            def map_worker(ref_img, p_text, model, g_key, api_keys, type_tag, do_bg_removal, can_remove_bg, gen_id, job_id):
                import shutil
                proc_img = ref_img
                saved_paths = []
                was_cancelled = False
                was_zombie = False

                def is_cancelled():
                    return gen_id != get_current_gen_id() or cancel_event.is_set()

                def set_status(msg):
                    def _update():
                        if gen_id == get_current_gen_id() and bpy.context and bpy.context.scene:
                            bpy.context.scene.neuro_status = msg
                        return None

                    bpy.app.timers.register(_update)

                try:
                    if gen_id != get_current_gen_id():
                        was_zombie = True
                        return

                    if do_bg_removal and can_remove_bg:
                        if is_cancelled():
                            was_cancelled = True
                            return

                        if not os.path.basename(ref_img).startswith("nobg_"):
                            try:
                                set_status("Removing background...")
                                temp_nobg = remove_background(ref_img, api_keys)

                                if temp_nobg and not is_cancelled():
                                    ref_dir = get_generations_folder("references")
                                    perm_path = os.path.join(ref_dir, os.path.basename(temp_nobg))
                                    shutil.move(temp_nobg, perm_path)
                                    temp_files_registry.discard(temp_nobg)

                                    def update_input_ref():
                                        try:
                                            if bpy.context and bpy.context.scene:
                                                refs = bpy.context.scene.neuro_reference_images
                                                if len(refs) > 0:
                                                    refs[0].path = perm_path
                                                    refresh_previews_and_collections(bpy.context.scene)
                                        except Exception:
                                            pass
                                        return None

                                    bpy.app.timers.register(update_input_ref)
                                    proc_img = perm_path

                            except Exception as e:
                                print(f"[{LOG_PREFIX}] BG Remove failed: {e}")

                    if is_cancelled():
                        was_cancelled = True
                        return

                    set_status(f"Generating {type_tag.lower()} map...")
                    try:
                        api_keys = {"google": g_key, "fal": fal_key, "repl":replicate_key,"aiml": aiml_key}
                        imgs = generate_images(
                            model_id=model,
                            prompt=p_text,
                            image_paths=[proc_img],
                            num_outputs=1,
                            api_keys=api_keys,
                            timeout=60,
                            aspect_ratio="1:1",
                            resolution="1K",
                            cancel_event=cancel_event,
                        )
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Map Gen Error: {e}")
                        imgs = []

                    if imgs and not is_cancelled():
                        gen_dir = get_generations_folder("textures")
                        base_name = f"{type_tag.lower()}_map"
                        for i, img in enumerate(imgs):
                            fname = get_unique_filename(gen_dir, base_name)
                            fpath = os.path.join(gen_dir, fname)
                            try:
                                img.save(fpath, format="PNG")
                                saved_paths.append((fpath, p_text, datetime.now().strftime("%Y%m%d_%H%M%S"),
                                                    i + 1, len(imgs), "Map", model, type_tag))
                            except Exception as e:
                                print(f"[{LOG_PREFIX}] Save error: {e}")

                except Exception as e:
                    print(f"[{LOG_PREFIX}] Map Worker Error: {e}")

                    # Status Manager Update
                    if was_cancelled or cancel_event.is_set():
                        status_manager.cancel_job(job_id)
                    elif saved_paths:  # Check paths, not imgs (imgs might be empty if save failed)
                        status_manager.complete_job(job_id, success=True)
                    else:
                        status_manager.complete_job(job_id, success=False, error="Map gen failed")

                finally:
                    def update_ui():
                        if gen_id != get_current_gen_id():
                            return None

                        s = bpy.context.scene
                        s.neuro_is_generating = False

                        if cancel_event.is_set():
                            s.neuro_status = "Generation cancelled"
                            return None

                        for p, txt, bid, idx, tot, obj, mod, mtype in saved_paths:
                            t = s.neuro_generated_textures.add()
                            t.path = p
                            t.prompt = txt
                            t.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            t.batch_id = bid
                            t.target_object = obj
                            t.model_used = mod
                            if hasattr(t, "map_type"):
                                t.map_type = mtype

                        refresh_previews_and_collections(s)

                        if saved_paths:
                            s.neuro_status = f"Generated {type_tag.capitalize()} Map"
                        else:
                            s.neuro_status = f"{type_tag} map generation failed"

                        cleanup_temp_files()
                        return None

                    bpy.app.timers.register(update_ui)

            threading.Thread(target=map_worker,
                             args=(ref_path, final_prompt, model_name, google_key, all_api_keys, gen_type,
                                   self.process_remove_bg, has_bg_removal, my_gen_id, job_id),
                             daemon=True).start()
            return {'FINISHED'}

        # === PATH 2: STANDARD TEXTURE GENERATION ===

        if not prompt:
            self.report({'ERROR'}, "Please enter a prompt")
            return {'CANCELLED'}
        if not google_key.strip():
            self.report({'ERROR'}, "Please enter API key in settings")
            return {'CANCELLED'}

        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}
        if not context.scene.camera:
            self.report({'ERROR'}, "No active camera in scene")
            return {'CANCELLED'}

        target_name_for_file = scn.neuro_texture_obj_desc.strip()
        if not target_name_for_file:
            target_name_for_file = obj.name if obj else "texture"

        target_name_for_file = sanitize_filename(target_name_for_file)

        cam = context.scene.camera

        # Find 3D View
        view3d_area = None
        view3d_space = None
        view3d_region = None
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    view3d_area = area
                    view3d_space = area.spaces.active
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            view3d_region = region
                            break
                    break
            if view3d_area:
                break

        if not view3d_area:
            self.report({'ERROR'}, "No 3D viewport found")
            return {'CANCELLED'}

        num_out = max(1, min(4, scn.neuro_num_outputs))
        model_name = scn.neuro_generation_model

        update_status(context, "Preparing texture generation...")

        # UV Handling
        if self.uv_behavior == 'NEW':
            try:
                if len(obj.data.uv_layers) < 8:
                    new_uv = obj.data.uv_layers.new(name="NEURO_UV")
                    obj.data.uv_layers.active = new_uv
            except Exception as e:
                print(f"[{LOG_PREFIX}] UV Creation Error: {e}")

        # Store View States
        stored_states = {
            'shading_type': view3d_space.shading.type,
            'shading_light': view3d_space.shading.light,
            'show_overlays': view3d_space.overlay.show_overlays
        }
        if hasattr(view3d_space.shading, 'studio_light'):
            stored_states['studio_light'] = view3d_space.shading.studio_light

        override = {
            'window': context.window_manager.windows[0],
            'screen': context.window_manager.windows[0].screen,
            'area': view3d_area,
            'region': view3d_region,
            'space_data': view3d_space,
            'scene': context.scene,
            'active_object': obj,
            'object': obj,
            'selected_objects': [obj],
            'selected_editable_objects': [obj]
        }

        try:
            # Setup View
            with context.temp_override(**override):
                bpy.ops.view3d.localview()

            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            time.sleep(0.1)

            with context.temp_override(**override):
                bpy.ops.view3d.view_camera()

            max_attempts = 10
            for attempt in range(max_attempts):
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                time.sleep(0.05)
                if view3d_space.region_3d.view_perspective == 'CAMERA':
                    break
                if attempt == max_attempts - 1:
                    self.report({'WARNING'}, "Camera view may not be fully active")

            time.sleep(0.15)
            context.view_layer.update()

            # Store Transforms
            original_scale = obj.scale.copy()
            original_location = obj.location.copy()
            stored_ortho_scale = None
            if cam.data.type == 'ORTHO':
                stored_ortho_scale = cam.data.ortho_scale

            # Center Object to Camera
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            geometric_center = sum(bbox_corners, Vector()) / 8.0

            cam_pos = cam.matrix_world.translation
            cam_forward_axis = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
            vec_cam_to_center = geometric_center - cam_pos
            point_on_axis = cam_pos + cam_forward_axis * vec_cam_to_center.dot(cam_forward_axis)

            correction_vector = point_on_axis - geometric_center
            obj.location += correction_vector
            context.view_layer.update()

            # Resolution setup
            render = scn.render
            original_res_x = render.resolution_x
            original_res_y = render.resolution_y
            original_filepath = render.filepath
            original_film_transparent = render.film_transparent

            target_res = int(scn.neuro_texture_resolution)
            render.resolution_x = target_res
            render.resolution_y = target_res

            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            radius = 0
            for corner in bbox_corners:
                radius = max(radius, (corner - geometric_center).length)

            if cam.data.type == 'PERSPECTIVE':
                fov_y = cam.data.angle_y
                aspect_ratio = render.resolution_x / render.resolution_y
                fov_x = 2 * math.atan(math.tan(fov_y / 2) * aspect_ratio)
                dist_y = radius / math.tan(fov_y / 2)
                dist_x = radius / math.tan(fov_x / 2)
                safe_distance = max(dist_x, dist_y)
                obj.location = cam_pos + cam_forward_axis * safe_distance
            elif cam.data.type == 'ORTHO':
                cam.data.ortho_scale = radius * 2

            context.view_layer.update()

            # Apply Frame %
            coords_2d = [world_to_camera_view(scn, cam, corner) for corner in bbox_corners]
            min_x = min(c.x for c in coords_2d)
            max_x = max(c.x for c in coords_2d)
            min_y = min(c.y for c in coords_2d)
            max_y = max(c.y for c in coords_2d)

            width_on_screen = max_x - min_x
            height_on_screen = max_y - min_y

            if width_on_screen > 0 and height_on_screen > 0:
                fill_percent = scn.neuro_texture_frame_percent / 100.0
                current_fill = max(width_on_screen, height_on_screen)
                if current_fill > 0.01:
                    scale_factor = fill_percent / current_fill
                    if cam.data.type == 'PERSPECTIVE':
                        current_distance = (obj.location - cam_pos).length
                        new_distance = current_distance / scale_factor
                        obj.location = cam_pos + (obj.location - cam_pos).normalized() * new_distance
                    elif cam.data.type == 'ORTHO':
                        cam.data.ortho_scale /= scale_factor

            context.view_layer.update()

            # UV Projection
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')

            override['mode'] = 'EDIT_MESH'
            with context.temp_override(**override):
                bpy.ops.uv.project_from_view(camera_bounds=False, correct_aspect=True, clip_to_bounds=False,
                                             scale_to_bounds=False)

            bpy.ops.object.mode_set(mode='OBJECT')

            # Capture Setup
            view3d_space.overlay.show_overlays = False
            view3d_space.shading.type = 'SOLID'
            view3d_space.shading.light = 'MATCAP'
            view3d_space.shading.studio_light = 'check_normal+y.exr'

            context.view_layer.update()

            for _ in range(3):
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
                time.sleep(0.05)

            render.film_transparent = True

            normal_path = register_temp_file(unique_temp_path(prefix="normal_capture"))
            render.filepath = normal_path

            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
            time.sleep(0.15)

            with context.temp_override(**override):
                bpy.ops.render.opengl(write_still=True, view_context=True)

            time.sleep(0.2)

            # Restore Scene
            render.resolution_x = original_res_x
            render.resolution_y = original_res_y
            render.filepath = original_filepath
            render.film_transparent = original_film_transparent

            obj.scale = original_scale
            obj.location = original_location
            if stored_ortho_scale is not None:
                cam.data.ortho_scale = stored_ortho_scale
            context.view_layer.update()

            view3d_space.overlay.show_overlays = stored_states['show_overlays']
            view3d_space.shading.type = stored_states['shading_type']
            view3d_space.shading.light = stored_states['shading_light']
            if 'studio_light' in stored_states:
                view3d_space.shading.studio_light = stored_states['studio_light']

            with context.temp_override(**override):
                bpy.ops.view3d.localview()

            if not os.path.exists(normal_path) or os.path.getsize(normal_path) < 1000:
                self.report({'ERROR'}, "Failed to capture viewport image")
                scn.neuro_is_generating = False
                return {'CANCELLED'}

            update_status(context, "Generating texture...")

            # --- STATUS MANAGER ---
            job_id = status_manager.add_job(f"Texture: {prompt[:30]}", model_name, "Texture")
            status_manager.start_job(job_id)

            refs = [r.path for r in scn.neuro_reference_images if os.path.exists(r.path)]
            all_images = [normal_path] + refs

            texture_res = scn.neuro_texture_resolution

            def worker_job(prompt_local, images, num_local, model_local, api_keys_local, timeout,
                           file_name_base, aspect_ratio, texture_resolution, gen_id, job_id):
                if gen_id != get_current_gen_id():
                    status_manager.cancel_job(job_id)
                    return

                try:
                    def update_progress(value):
                        pass

                    progress_timer.start()

                    api_size, actual_res = get_texture_api_size(texture_resolution, model_local)

                    # Determine resolution for API
                    res_for_api = "2K" if texture_resolution == "2048" else "1K"

                    imgs = generate_images(
                        model_id=model_local,
                        prompt=prompt_local,
                        image_paths=images,
                        num_outputs=num_local,
                        api_keys=api_keys_local,
                        timeout=timeout,
                        aspect_ratio=aspect_ratio,
                        resolution=res_for_api,
                        progress_callback=update_progress,
                        cancel_event=cancel_event,
                    )

                    progress_timer.stop()
                    timed_out = False

                except TimeoutError:
                    imgs = []
                    timed_out = True
                    progress_timer.stop()
                except Exception as e:
                    imgs = []
                    timed_out = False
                    progress_timer.stop()
                    if gen_id == get_current_gen_id() and not cancel_event.is_set():
                        print(f"[{LOG_PREFIX}] Worker exception:", e)

                    # Status Manager
                    if cancel_event.is_set():
                        status_manager.cancel_job(job_id)
                    elif imgs:
                        status_manager.complete_job(job_id, success=True)
                    else:
                        status_manager.complete_job(job_id, success=False, error="Texture gen failed")

                saved_paths = []
                batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

                if gen_id == get_current_gen_id() and not cancel_event.is_set() and imgs:
                    gen_dir = get_generations_folder("textures")
                    base_name = file_name_base

                    for i, pil_img in enumerate(imgs, 1):
                        filename = get_unique_filename(gen_dir, base_name)
                        save_path = os.path.join(gen_dir, filename)
                        try:
                            pil_img.save(save_path, format="PNG")
                            saved_paths.append(
                                (save_path, prompt_local, batch_id, i, len(imgs), obj.name, model_local, 'COLOR'))
                        except Exception as e:
                            print(f"[{LOG_PREFIX}] Failed saving texture:", e)

                def main_thread_update():
                    if gen_id != get_current_gen_id():
                        clear_status_bar(bpy.context)
                        return

                    scn_inner = bpy.context.scene
                    scn_inner.neuro_is_generating = False

                    if cancel_event.is_set():
                        update_status(bpy.context, "Generation cancelled")
                        clear_status_bar(bpy.context)
                        return

                    for path, orig_prompt, b_id, b_idx, b_total, target_obj, model_name, m_type in saved_paths:
                        entry = scn_inner.neuro_generated_textures.add()
                        entry.path = path
                        entry.prompt = orig_prompt
                        entry.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        entry.batch_id = b_id
                        entry.batch_index = b_idx
                        entry.batch_total = b_total
                        entry.target_object = target_obj
                        entry.favorite = False
                        entry.model_used = model_name
                        if hasattr(entry, "map_type"):
                            entry.map_type = m_type

                    refresh_previews_and_collections(scn_inner)

                    if saved_paths:
                        msg = f"Generated {len(saved_paths)} texture(s)"
                        update_status(bpy.context, msg)
                    else:
                        if timed_out:
                            update_status(bpy.context, "Texture generation timed out")
                        else:
                            update_status(bpy.context, "Texture generation failed")

                    cleanup_temp_files()

                    # Clear status bar after 5 seconds
                    def clear_bar():
                        clear_status_bar(bpy.context)
                        return None

                    bpy.app.timers.register(clear_bar, first_interval=5.0)

                    return None

                bpy.app.timers.register(main_thread_update, first_interval=0.2)

            threading.Thread(target=worker_job,
                             args=(prompt, all_images, num_out, model_name, all_api_keys, scn.neuro_timeout,
                                   target_name_for_file, "1:1", texture_res, my_gen_id, job_id),
                             daemon=True).start()

        except Exception as e:
            self.report({'ERROR'}, f"Failed to prepare texture: {e}")
            print(f"[{LOG_PREFIX}] Texture prep error: {e}")
            import traceback
            traceback.print_exc()
            view3d_space.overlay.show_overlays = stored_states.get('show_overlays', True)
            scn.neuro_is_generating = False
            return {'CANCELLED'}

        return {'FINISHED'}


# =============================================================================
# APPLY TEXTURE OPERATOR
# =============================================================================

class NEURO_OT_apply_texture(bpy.types.Operator):
    """Apply texture to selected object's material"""
    bl_idname = "neuro.apply_texture"
    bl_label = "Apply Material"
    bl_description = "Apply this texture to the selected object's material"

    path: bpy.props.StringProperty()
    target_object: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.active_object

        if self.target_object:
            target = bpy.data.objects.get(self.target_object)
            if target:
                obj = target

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a mesh object")
            return {'CANCELLED'}

        if not os.path.exists(self.path):
            self.report({'ERROR'}, "Texture file not found")
            return {'CANCELLED'}

        map_type = 'COLOR'
        for t in context.scene.neuro_generated_textures:
            if t.path == self.path:
                if hasattr(t, "map_type"):
                    map_type = t.map_type
                break

        # Use safe_load_image to prevent .001 duplicates
        from .utils import safe_load_image
        img = safe_load_image(self.path, reload_existing=False)
        if not img:
            self.report({'ERROR'}, "Failed to load texture image")
            return {'CANCELLED'}

        mat = obj.data.materials[0] if obj.data.materials else None
        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_Neuro")
            obj.data.materials.append(mat)

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        output_node = None
        principled = None

        for node in nodes:
            if node.type == 'OUTPUT_MATERIAL':
                output_node = node
            elif node.type == 'BSDF_PRINCIPLED':
                principled = node

        if not output_node:
            output_node = nodes.new(type='ShaderNodeOutputMaterial')
            output_node.location = (300, 0)

        if not principled:
            principled = nodes.new(type='ShaderNodeBsdfPrincipled')
            principled.location = (0, 0)
            links.new(principled.outputs['BSDF'], output_node.inputs['Surface'])

        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.image = img

        X_TEX = -600
        X_MID = -300
        X_BSDF = 0

        offset_x = X_TEX
        offset_y = 0

        if map_type == 'COLOR':
            offset_y = 0
            if hasattr(img, 'colorspace_settings'):
                img.colorspace_settings.name = 'sRGB'

                # Check Scene first, then fallback to Prefs, then default 'EN'
            lang = 'EN'
            if hasattr(context.scene, 'manual_language'):
                lang = context.scene.manual_language
            else:
                # Fallback to checking preferences just in case
                try:
                    prefs = context.preferences.addons[__package__].preferences
                    lang = getattr(prefs, 'manual_language', 'EN')
                except Exception:
                    pass

            group_name = "Texture_Quick_Edit_Ru" if lang == 'RU' else "Texture_Quick_Edit_En"

            group_tree = bpy.data.node_groups.get(group_name)

            if not group_tree:
                try:
                    addon_dir = os.path.dirname(os.path.realpath(__file__))
                    assets_path = os.path.join(addon_dir, "assets", "Nodes.blend")

                    if os.path.exists(assets_path):
                        with bpy.data.libraries.load(assets_path, link=False) as (data_from, data_to):
                            if group_name in data_from.node_groups:
                                data_to.node_groups = [group_name]

                        if data_to.node_groups:
                            group_tree = data_to.node_groups[0]
                except Exception as e:
                    print(f"[{LOG_PREFIX}] Failed to load {group_name}: {e}")

                # Create Node
                if group_tree:
                    group_node = nodes.new(type='ShaderNodeGroup')
                    group_node.node_tree = group_tree
                    group_node.label = "Quick Edit"

                    tex_node.location = (X_TEX, offset_y)
                    group_node.location = (X_MID, offset_y)
                    principled.location = (X_BSDF, 0)

                    try:
                        # Robust linking
                        if 'Color' in group_node.inputs:
                            links.new(tex_node.outputs['Color'], group_node.inputs['Color'])
                        else:
                            links.new(tex_node.outputs['Color'], group_node.inputs[0])

                        if 'Color' in group_node.outputs:
                            links.new(group_node.outputs['Color'], principled.inputs['Base Color'])
                        else:
                            links.new(group_node.outputs[0], principled.inputs['Base Color'])
                    except Exception as e:
                        print(f"[{LOG_PREFIX}] Group linking failed: {e}")
                        links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                else:
                    tex_node.location = (X_MID, offset_y)
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])

        elif map_type in ['ROUGHNESS', 'METALLIC']:
            offset_y = -300 if map_type == 'ROUGHNESS' else -600
            if hasattr(img, 'colorspace_settings'):
                img.colorspace_settings.name = 'Non-Color'

            ramp = nodes.new(type='ShaderNodeValToRGB')

            tex_node.location = (X_TEX, offset_y)
            ramp.location = (X_MID, offset_y)

            target_socket = 'Roughness' if map_type == 'ROUGHNESS' else 'Metallic'
            links.new(tex_node.outputs['Color'], ramp.inputs['Fac'])
            links.new(ramp.outputs['Color'], principled.inputs[target_socket])

        elif map_type == 'HEIGHT':
            offset_y = -900
            if hasattr(img, 'colorspace_settings'):
                img.colorspace_settings.name = 'Non-Color'

            bump = nodes.new(type='ShaderNodeBump')
            bump.inputs['Strength'].default_value = 1.0
            bump.inputs['Distance'].default_value = 0.1

            tex_node.location = (X_TEX, offset_y)
            bump.location = (X_MID, offset_y)

            links.new(tex_node.outputs['Color'], bump.inputs['Height'])
            links.new(bump.outputs['Normal'], principled.inputs['Normal'])

        tex_node.location = (principled.location.x + offset_x, principled.location.y + offset_y)

        self.report({'INFO'}, f"Applied {map_type} to {obj.name}")
        return {'FINISHED'}


# =============================================================================
# REGENERATE OPERATORS
# =============================================================================

class NEURO_OT_regenerate_image(bpy.types.Operator):
    """Regenerate using the original prompt"""
    bl_idname = "neuro.regenerate_image"
    bl_label = "Regenerate"
    bl_description = "Regenerate using the original prompt"

    index: bpy.props.IntProperty()

    def execute(self, context):
        scn = context.scene

        if 0 <= self.index < len(scn.neuro_generated_images):
            gen = scn.neuro_generated_images[self.index]
            original_prompt = gen.prompt

            if original_prompt:
                scn.neuro_prompt_image = original_prompt
                bpy.ops.neuro.generate_image()
                self.report({'INFO'}, f"Regenerating with prompt: {original_prompt[:50]}...")
            else:
                self.report({'ERROR'}, "No original prompt found")
                return {'CANCELLED'}

        return {'FINISHED'}


class NEURO_OT_regenerate_texture(bpy.types.Operator):
    """Regenerate texture using the original prompt"""
    bl_idname = "neuro.regenerate_texture"
    bl_label = "Regenerate"
    bl_description = "Regenerate texture using the original prompt"

    index: bpy.props.IntProperty()

    def execute(self, context):
        scn = context.scene

        if 0 <= self.index < len(scn.neuro_generated_textures):
            tex = scn.neuro_generated_textures[self.index]
            original_prompt = tex.prompt

            if original_prompt:
                scn.neuro_prompt_texture = original_prompt
                bpy.ops.neuro.generate_texture()
                self.report({'INFO'}, f"Regenerating texture with prompt: {original_prompt[:50]}...")
            else:
                self.report({'ERROR'}, "No original prompt found")
                return {'CANCELLED'}

        return {'FINISHED'}


# =============================================================================
# PBR MAP GENERATION OPERATOR
# =============================================================================

class NEURO_OT_generate_pbr_map(bpy.types.Operator):
    """Generate PBR map from texture"""
    bl_idname = "neuro.generate_pbr_map"
    bl_label = "Generate PBR Map"

    texture_index: bpy.props.IntProperty()
    map_type: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        map_descriptions = {
            'ROUGHNESS': "Generate Roughness map from this texture",
            'METALLIC': "Generate Metallic map from this texture",
            'HEIGHT': "Generate Height/Bump map from this texture"
        }
        return map_descriptions.get(properties.map_type, "Generate PBR map from this texture")

    def execute(self, context):
        from .api import generate_images
        from .utils import get_all_api_keys

        scn = context.scene

        if scn.neuro_is_generating:
            self.report({'WARNING'}, "Generation already in progress")
            return {'CANCELLED'}

        if not (0 <= self.texture_index < len(scn.neuro_generated_textures)):
            self.report({'ERROR'}, "Invalid texture index")
            return {'CANCELLED'}

        tex = scn.neuro_generated_textures[self.texture_index]
        if not os.path.exists(tex.path):
            self.report({'ERROR'}, "Texture file not found")
            return {'CANCELLED'}

        all_api_keys = get_all_api_keys(context)
        google_key = all_api_keys.get("google", "")

        if not google_key:
            self.report({'ERROR'}, "Google API key required for PBR maps")
            return {'CANCELLED'}

        prompt = MAP_PROMPTS.get(self.map_type, "")
        if not prompt:
            self.report({'ERROR'}, f"Unknown map type: {self.map_type}")
            return {'CANCELLED'}

        scn.neuro_is_generating = True
        scn.neuro_status = f"Generating {self.map_type.lower()} map..."

        cancel_event.clear()
        my_gen_id = increment_gen_id()

        source_path = tex.path
        source_batch_id = tex.batch_id
        source_batch_index = tex.batch_index
        source_timestamp = tex.timestamp
        target_object = tex.target_object
        map_type = self.map_type
        timeout = scn.neuro_timeout

        def pbr_worker():
            nonlocal source_path, prompt, map_type, target_object, my_gen_id, source_batch_id, source_batch_index, source_timestamp

            if my_gen_id != get_current_gen_id():
                return

            try:
                imgs = generate_images(
                    model_id="gemini-3-pro-image-preview",
                    prompt=prompt,
                    image_paths=[source_path],
                    num_outputs=1,
                    api_keys=all_api_keys,
                    timeout=timeout,
                    aspect_ratio="1:1",
                    resolution="1K",
                    cancel_event=cancel_event,
                )

                saved_path = None
                if imgs and my_gen_id == get_current_gen_id() and not cancel_event.is_set():
                    gen_dir = get_generations_folder("textures")
                    base_name = os.path.splitext(os.path.basename(source_path))[0]
                    filename = f"{base_name}_{map_type.lower()}.png"
                    save_path = os.path.join(gen_dir, filename)

                    counter = 1
                    while os.path.exists(save_path):
                        filename = f"{base_name}_{map_type.lower()}_{counter:02d}.png"
                        save_path = os.path.join(gen_dir, filename)
                        counter += 1

                    imgs[0].save(save_path, format="PNG")
                    saved_path = save_path

                def update_ui():
                    if my_gen_id != get_current_gen_id():
                        return None

                    scn_inner = bpy.context.scene
                    scn_inner.neuro_is_generating = False

                    if cancel_event.is_set():
                        scn_inner.neuro_status = "Generation cancelled"
                        return None

                    if saved_path:
                        batch_count = sum(1 for t in scn_inner.neuro_generated_textures
                                          if t.batch_id == source_batch_id)

                        entry = scn_inner.neuro_generated_textures.add()
                        entry.path = saved_path
                        entry.prompt = prompt
                        entry.timestamp = source_timestamp
                        entry.batch_id = source_batch_id
                        entry.batch_index = batch_count + 1
                        entry.batch_total = batch_count + 1
                        entry.target_object = target_object
                        entry.model_used = "gemini-3-pro-image-preview"
                        entry.map_type = map_type
                        entry.source_texture_idx = source_batch_index

                        refresh_previews_and_collections(scn_inner)
                        scn_inner.neuro_status = f"{map_type.capitalize()} map generated!"
                    else:
                        scn_inner.neuro_status = "Map generation failed"

                    return None

                bpy.app.timers.register(update_ui, first_interval=0.1)

            except Exception as e:
                def error_update():
                    if my_gen_id == get_current_gen_id():
                        bpy.context.scene.neuro_is_generating = False
                        bpy.context.scene.neuro_status = f"Error: {str(e)[:50]}"
                    return None

                bpy.app.timers.register(error_update, first_interval=0.1)

        threading.Thread(target=pbr_worker, daemon=True).start()
        return {'FINISHED'}


# =============================================================================
# REGISTRATION
# =============================================================================

GENERATION_OPERATOR_CLASSES = (
    NEURO_OT_generate_image,
    NEURO_OT_generate_texture,
    NEURO_OT_apply_texture,
    NEURO_OT_regenerate_image,
    NEURO_OT_regenerate_texture,
    NEURO_OT_generate_pbr_map,
)


def register():
    for cls in GENERATION_OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(GENERATION_OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)