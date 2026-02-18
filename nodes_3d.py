# -*- coding: utf-8 -*-
"""
Blender AI Nodes - 3D Generation Nodes (Tripo)

Node-based 3D mesh generation using Tripo's API.
Supports text-to-3D, image-to-3D, multiview-to-3D generation, and Smart LowPoly retopology.
"""

import os
import threading
import queue
import bpy
from bpy.props import (
    StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty
)
from bpy.types import Node, Operator

from .nodes_core import NeuroNodeBase


# =============================================================================
# CUSTOM SOCKET FOR TASK ID
# =============================================================================

class TripoTaskSocket(bpy.types.NodeSocket):
    """Socket for passing Tripo task IDs between nodes"""
    bl_idname = 'TripoTaskSocket'
    bl_label = 'Tripo Task'

    task_id: StringProperty(default="")

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.2, 0.8, 0.4, 1.0)  # Green color for task sockets


# =============================================================================
# TRIPO GENERATE NODE
# =============================================================================

class TripoGenerateNode(NeuroNodeBase, Node):
    """3D Generate (Tripo) - Generate 3D models from text or images"""
    bl_idname = 'TripoGenerateNode'
    bl_label = '3D Generate (Tripo)'
    bl_icon = 'MESH_MONKEY'
    bl_width_default = 280
    bl_width_min = 200

    # --- Mode Selection ---
    generation_mode: EnumProperty(
        name="Mode",
        items=[
            ('TEXT', 'Text to 3D', 'Generate from text prompt'),
            ('IMAGE', 'Image to 3D', 'Generate from single image'),
            ('MULTIVIEW', 'Multi-View', 'Generate from multiple angles (front required)'),
        ],
        default='IMAGE',
        description="Generation mode",
        update=lambda self, ctx: self.update_sockets()
    )

    # --- Inputs ---
    prompt: StringProperty(name="Prompt", default="",
                           description="Text description for generation")
    negative_prompt: StringProperty(name="Negative", default="",
                                    description="What to avoid in generation")

    # --- Model Settings ---
    model_version: EnumProperty(
        name="Model",
        items=[
            ('v3.0-20250812', 'v3.0 (Latest)', 'Latest model version'),
            ('v2.5-20250123', 'v2.5', 'Version 2.5'),
            ('v2.0-20240919', 'v2.0', 'Version 2.0'),
        ],
        default='v3.0-20250812'
    )

    # --- Quality Settings ---
    texture: BoolProperty(name="Texture", default=True,
                          description="Generate with textures")
    pbr: BoolProperty(name="PBR", default=True,
                      description="Generate PBR materials")
    texture_quality: EnumProperty(
        name="Texture Quality",
        items=[('standard', 'Standard', ''), ('detailed', 'Detailed', '')],
        default='standard'
    )
    geometry_quality: EnumProperty(
        name="Geometry Quality",
        items=[('standard', 'Standard', ''), ('detailed', 'Detailed', '')],
        default='standard'
    )

    # --- Mesh Settings ---
    quad: BoolProperty(name="Quad Mesh", default=False,
                       description="Generate quad mesh instead of triangles")
    use_face_limit: BoolProperty(name="Limit Faces", default=False)
    face_limit: IntProperty(name="Face Limit", default=10000, min=1000, max=2000000)
    auto_size: BoolProperty(name="Auto Size", default=False,
                            description="Scale to real-world dimensions (meters)")

    # --- Style ---
    style: EnumProperty(
        name="Style",
        items=[
            ('original', 'Original', 'Keep original style'),
            ('person:person2cartoon', 'Cartoon', 'Cartoon style'),
            ('object:clay', 'Clay', 'Clay appearance'),
            ('object:steampunk', 'Steampunk', 'Steampunk aesthetic'),
            ('object:barbie', 'Barbie', 'Barbie style'),
            ('object:christmas', 'Christmas', 'Christmas style'),
        ],
        default='original'
    )

    # --- State ---
    is_generating: BoolProperty(default=False)
    progress: IntProperty(default=0, min=0, max=100)
    status_message: StringProperty(default="")
    result_path: StringProperty(default="")  # Path to downloaded GLB
    result_task_id: StringProperty(default="")  # Task ID for downstream editing
    model_name: StringProperty(default="")  # Name prefix for imported mesh
    auto_import: BoolProperty(name="Auto Import", default=True,
                              description="Automatically import model into scene")

    show_settings: BoolProperty(name="Settings", default=False)

    def init(self, context):
        # Image input (used for IMAGE mode, and as Front for MULTIVIEW)
        self.inputs.new('NeuroImageSocket', "Image")
        # Multi-view inputs (only visible in MULTIVIEW mode)
        # Order matches Splitter outputs: Front(Image), Left, Right, Back
        self.inputs.new('NeuroImageSocket', "Left")
        self.inputs.new('NeuroImageSocket', "Right")
        self.inputs.new('NeuroImageSocket', "Back")
        # Prompt input for TEXT mode
        self.inputs.new('NeuroTextSocket', "Prompt In")

        # Output socket for task ID (for downstream editing like Smart LowPoly)
        self.outputs.new('TripoTaskSocket', "Task ID")

        # Update socket visibility
        self.update_sockets()

    def update_sockets(self):
        """Update socket visibility based on generation mode"""
        # Multi-view sockets
        for name in ["Left", "Right", "Back"]:
            socket = self.inputs.get(name)
            if socket:
                socket.hide = (self.generation_mode != 'MULTIVIEW')

        # Image socket - show for IMAGE and MULTIVIEW modes
        image_socket = self.inputs.get("Image")
        if image_socket:
            image_socket.hide = (self.generation_mode == 'TEXT')
            # Rename based on mode for clarity
            if self.generation_mode == 'MULTIVIEW':
                image_socket.name = "Front"
            else:
                image_socket.name = "Image"

        # Prompt socket - show for TEXT mode
        prompt_socket = self.inputs.get("Prompt In")
        if prompt_socket:
            prompt_socket.hide = (self.generation_mode != 'TEXT')

    def copy(self, node):
        self.is_generating = False
        self.progress = 0
        self.status_message = ""
        self.result_path = ""
        self.result_task_id = ""

    def draw_buttons(self, context, layout):
        # Mode selector
        layout.prop(self, "generation_mode", text="")

        # Mode-specific inputs
        if self.generation_mode == 'TEXT':
            layout.prop(self, "prompt", text="")
            layout.prop(self, "negative_prompt", text="Negative")
        elif self.generation_mode == 'MULTIVIEW':
            col = layout.column(align=True)
            col.label(text="Connect: Front (required), Left, Right, Back", icon='INFO')

        # Model name for import
        layout.prop(self, "model_name", text="Name")

        # Settings toggle
        row = layout.row()
        row.prop(self, "show_settings", icon='TRIA_DOWN' if self.show_settings else 'TRIA_RIGHT',
                 emboss=False)
        row.prop(self, "auto_import", text="", icon='IMPORT')

        if self.show_settings:
            box = layout.box()
            box.prop(self, "model_version")
            box.prop(self, "style")

            row = box.row(align=True)
            row.prop(self, "texture")
            row.prop(self, "pbr")

            row = box.row(align=True)
            row.prop(self, "texture_quality", text="")
            row.prop(self, "geometry_quality", text="")

            box.prop(self, "quad")
            box.prop(self, "auto_size")

            row = box.row(align=True)
            row.prop(self, "use_face_limit", text="")
            sub = row.row()
            sub.enabled = self.use_face_limit
            sub.prop(self, "face_limit", text="Faces")

        # Progress / Generate button
        if self.is_generating:
            col = layout.column(align=True)
            col.progress(factor=self.progress / 100.0, text=self.status_message or "Generating...")
            col.operator("tripo.node_cancel", text="Cancel", icon='X')
        else:
            row = layout.row(align=True)
            row.scale_y = 1.5
            op = row.operator("tripo.node_generate", text="Generate 3D", icon='MESH_MONKEY')
            op.node_name = self.name

        # Result info with manual import option
        if self.result_path and os.path.exists(self.result_path):
            layout.label(text=os.path.basename(self.result_path), icon='CHECKMARK')
            row = layout.row(align=True)
            op = row.operator("tripo.manual_import", text="Import", icon='IMPORT')
            op.file_path = self.result_path
            op.name_prefix = self.model_name or "Tripo"
        elif self.result_task_id and not self.is_generating:
            # Task completed but file missing
            layout.label(text=f"Task: {self.result_task_id[:16]}...", icon='INFO')

        # Show task ID if available (for downstream use)
        if self.result_task_id and self.result_path:
            row = layout.row()
            row.scale_y = 0.8
            row.label(text=f"Task: {self.result_task_id[:16]}...", icon='LINKED')

    def draw_label(self):
        if self.is_generating:
            return f"Generating... {self.progress}%"
        if self.status_message:
            return self.status_message
        return "3D Generate (Tripo)"

    def get_input_image_path(self, socket_name: str) -> str:
        """
        Get image path from connected node, handling multi-output nodes (Splitters)
        and Blender Image objects.
        """
        socket = self.inputs.get(socket_name)
        if not socket or not socket.is_linked:
            return ""

        try:
            link = socket.links[0]
            from_node = link.from_node
            from_socket_name = link.from_socket.name

            # 1. Check for dict output (Common in splitters)
            for dict_name in ['output_paths', 'image_paths', 'saved_paths', 'results']:
                if hasattr(from_node, dict_name):
                    data_dict = getattr(from_node, dict_name)
                    if isinstance(data_dict, dict):
                        if from_socket_name in data_dict:
                            return data_dict[from_socket_name]
                        if from_socket_name.lower() in data_dict:
                            return data_dict[from_socket_name.lower()]

            # 2. Check for attributes matching socket name (e.g. node.rear_path)
            clean_name = from_socket_name.lower().replace(" ", "_")
            potential_attrs = [
                f"{clean_name}_path",
                f"path_{clean_name}",
                f"{clean_name}_image",
                clean_name
            ]

            for attr in potential_attrs:
                if hasattr(from_node, attr):
                    val = getattr(from_node, attr)
                    if isinstance(val, str) and len(val) > 1:
                        if val.startswith("//"):
                            val = bpy.path.abspath(val)
                        if os.path.exists(val):
                            return val
                    # Handle Blender Image Object
                    if hasattr(val, 'filepath'):
                        image_path = bpy.path.abspath(val.filepath)
                        if os.path.exists(image_path):
                            return image_path

            # 3. Fallback for single-output nodes
            for attr in ['result_path', 'image_path', 'filepath']:
                if hasattr(from_node, attr):
                    path = getattr(from_node, attr)
                    if path and isinstance(path, str) and os.path.exists(path):
                        return path

        except Exception:
            pass

        return ""

    def get_prompt_text(self) -> str:
        """Get prompt from input or property"""
        socket = self.inputs.get("Prompt In")
        if socket and socket.is_linked:
            for link in socket.links:
                from_node = link.from_node
                if hasattr(from_node, 'text'):
                    return from_node.text
                if hasattr(from_node, 'result_text'):
                    return from_node.result_text
        return self.prompt


# =============================================================================
# SMART LOWPOLY NODE
# =============================================================================

class TripoSmartLowPolyNode(NeuroNodeBase, Node):
    """Smart LowPoly (Tripo) - Retopologize 3D models for game-ready meshes"""
    bl_idname = 'TripoSmartLowPolyNode'
    bl_label = 'Smart LowPoly (Tripo)'
    bl_icon = 'MOD_DECIM'
    bl_width_default = 280
    bl_width_min = 200

    # --- Model Version ---
    model_version: EnumProperty(
        name="Model",
        items=[
            ('P-v2.0-20251225', 'v2.0 (Latest)', 'Latest Smart LowPoly model'),
        ],
        default='P-v2.0-20251225'
    )

    # --- Settings ---
    quad: BoolProperty(name="Quad Mesh", default=False,
                       description="Generate quad mesh instead of triangles")
    face_limit: IntProperty(name="Face Limit", default=4000, min=500, max=20000,
                            description="Target polygon count (1000-20000 for tris, 500-10000 for quads)")
    bake: BoolProperty(name="Bake Normals", default=True,
                       description="Bake normal maps from high-poly")

    def get_clamped_face_limit(self):
        """Get face_limit clamped to valid range based on quad setting"""
        if self.quad:
            return max(500, min(10000, self.face_limit))
        else:
            return max(1000, min(20000, self.face_limit))

    # --- State ---
    is_processing: BoolProperty(default=False)
    progress: IntProperty(default=0, min=0, max=100)
    status_message: StringProperty(default="")
    result_path: StringProperty(default="")
    result_task_id: StringProperty(default="")
    model_name: StringProperty(default="LowPoly")
    auto_import: BoolProperty(name="Auto Import", default=True,
                              description="Automatically import model into scene")

    def init(self, context):
        # Input: Task ID from generation node
        self.inputs.new('TripoTaskSocket', "Task ID")
        # Output: Task ID for further processing
        self.outputs.new('TripoTaskSocket', "Task ID")

    def copy(self, node):
        self.is_processing = False
        self.progress = 0
        self.status_message = ""
        self.result_path = ""
        self.result_task_id = ""

    def draw_buttons(self, context, layout):
        # Model version
        layout.prop(self, "model_version")

        # Face limit with range hint
        row = layout.row(align=True)
        row.prop(self, "face_limit")
        row.separator()
        # Show valid range based on quad mode
        range_text = "500-10K" if self.quad else "1K-20K"
        row.label(text=range_text)

        # Show warning if value out of range
        clamped = self.get_clamped_face_limit()
        if clamped != self.face_limit:
            layout.label(text=f"Will use {clamped}", icon='INFO')

        row = layout.row(align=True)
        row.prop(self, "quad")
        row.prop(self, "bake")

        # Model name for import
        layout.prop(self, "model_name", text="Name")

        row = layout.row()
        row.prop(self, "auto_import", icon='IMPORT')

        # Progress / Process button
        if self.is_processing:
            col = layout.column(align=True)
            col.progress(factor=self.progress / 100.0, text=self.status_message or "Processing...")
            col.operator("tripo.lowpoly_cancel", text="Cancel", icon='X')
        else:
            row = layout.row(align=True)
            row.scale_y = 1.5
            op = row.operator("tripo.smart_lowpoly", text="Retopologize", icon='MOD_DECIM')
            op.node_name = self.name

        # Result info with manual import option
        if self.result_path and os.path.exists(self.result_path):
            layout.label(text=os.path.basename(self.result_path), icon='CHECKMARK')
            row = layout.row(align=True)
            op = row.operator("tripo.manual_import", text="Import", icon='IMPORT')
            op.file_path = self.result_path
            op.name_prefix = self.model_name or "LowPoly"
        elif self.result_task_id and not self.is_processing:
            # Task completed but file missing - show task ID
            layout.label(text=f"Task: {self.result_task_id[:12]}...", icon='INFO')

    def draw_label(self):
        if self.is_processing:
            return f"Processing... {self.progress}%"
        if self.status_message:
            return self.status_message
        return "Smart LowPoly (Tripo)"

    def get_input_task_id(self) -> str:
        """Get task ID from connected node"""
        socket = self.inputs.get("Task ID")
        if not socket or not socket.is_linked:
            return ""

        try:
            link = socket.links[0]
            from_node = link.from_node

            # Check for task ID attributes
            for attr in ['result_task_id', 'task_id']:
                if hasattr(from_node, attr):
                    val = getattr(from_node, attr)
                    if val and isinstance(val, str):
                        return val
        except Exception:
            pass

        return ""


# =============================================================================
# OPERATORS
# =============================================================================

class TRIPO_OT_node_generate(Operator):
    bl_idname = "tripo.node_generate"
    bl_label = "Generate 3D"
    bl_description = "Generate 3D model using Tripo"
    bl_options = {'REGISTER'}

    node_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.tree_type == 'NeuroGenNodeTree'

    def execute(self, context):
        ntree = context.space_data.node_tree
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # --- 1. PREPARE DATA (Main Thread) ---
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs or not prefs.tripo_api_key:
            self.report({'ERROR'}, "Tripo API key missing")
            return {'CANCELLED'}

        api_key = prefs.tripo_api_key

        from . import api_tripo
        if not api_tripo.TRIPO_AVAILABLE:
            if not api_tripo.init_tripo():
                self.report({'ERROR'}, "Tripo SDK missing")
                return {'CANCELLED'}

        mode = node.generation_mode
        # Ensure sockets are in correct state (may not have updated after file load)
        node.update_sockets()
        settings = {
            "model_version": node.model_version,
            "texture": node.texture,
            "pbr": node.pbr,
            "texture_quality": node.texture_quality,
            "geometry_quality": node.geometry_quality,
            "quad": node.quad,
            "auto_size": node.auto_size,
            "face_limit": node.face_limit if node.use_face_limit else None,
            "style": node.style if node.style != 'original' else None,
        }

        try:
            input_data = {}
            if mode == 'TEXT':
                input_data['prompt'] = node.get_prompt_text()
                input_data['negative_prompt'] = node.negative_prompt
                if not input_data['prompt']: raise ValueError("Prompt required")

            elif mode == 'IMAGE':
                # Use "Image" socket (or "Front" if renamed)
                image_socket = node.inputs.get("Image") or node.inputs.get("Front")
                if image_socket:
                    path = node.get_input_image_path(image_socket.name)
                else:
                    path = ""
                if not path: raise ValueError("Image required")
                input_data['image_path'] = path


            elif mode == 'MULTIVIEW':
                # Tripo SDK expects order: [Front, Back, Left, Right]
                # Socket may still be named "Image" if update_sockets() didn't fire after load
                front_path = (node.get_input_image_path("Front")
                              or node.get_input_image_path("Image"))
                paths = [
                    front_path,                          # Index 0: Front (required)
                    node.get_input_image_path("Back"),   # Index 1: Back
                    node.get_input_image_path("Left"),   # Index 2: Left
                    node.get_input_image_path("Right"),  # Index 3: Right
                ]
                if not paths[0]: raise ValueError("Front image required")
                input_data['image_paths'] = paths
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # --- 2. THREAD COMMUNICATION ---
        msg_queue = queue.Queue()
        node.is_generating = True
        node.progress = 0
        node.status_message = "Starting..."
        node.result_task_id = ""  # Clear previous task ID

        def run_generation():
            try:
                def callback(prog, msg):
                    msg_queue.put(("PROGRESS", prog, msg))

                if mode == 'TEXT':
                    result = api_tripo.generate_text_to_model(
                        api_key=api_key,
                        prompt=input_data['prompt'],
                        negative_prompt=input_data['negative_prompt'],
                        progress_callback=callback,
                        **settings
                    )
                elif mode == 'IMAGE':
                    result = api_tripo.generate_image_to_model(
                        api_key=api_key,
                        image_path=input_data['image_path'],
                        progress_callback=callback,
                        **settings
                    )
                elif mode == 'MULTIVIEW':
                    result = api_tripo.generate_multiview_to_model(
                        api_key=api_key,
                        image_paths=input_data['image_paths'],
                        progress_callback=callback,
                        **settings
                    )

                if result.status == "success" and result.model_path:
                    msg_queue.put(("SUCCESS", result.model_path, node.auto_import,
                                   node.model_name, result.task_id))
                else:
                    msg_queue.put(("FAILED", result.error_message or "Unknown error"))

            except Exception as e:
                msg_queue.put(("ERROR", str(e)))

        thread = threading.Thread(target=run_generation)
        thread.daemon = True
        thread.start()

        # --- 3. UPDATE TIMER ---
        def update_ui():
            while not msg_queue.empty():
                try:
                    msg = msg_queue.get_nowait()
                    msg_type = msg[0]

                    if msg_type == "PROGRESS":
                        node.progress = msg[1]
                        node.status_message = msg[2]
                        # Safe update tag
                        if hasattr(node.id_data, "update_tag"):
                            node.id_data.update_tag()
                        elif hasattr(node.id_data, "tag_update"):
                            node.id_data.tag_update()

                    elif msg_type == "SUCCESS":
                        model_path = msg[1]
                        print(f"[Tripo Generate] SUCCESS - model_path: {model_path}")
                        node.result_path = model_path
                        node.result_task_id = msg[4]  # Store task ID
                        node.is_generating = False

                        if msg[2] and model_path:  # Auto import + valid path
                            imported = api_tripo.import_glb_to_blender(model_path, msg[3] or "Tripo")
                            if imported:
                                node.status_message = "Complete!"
                            else:
                                node.status_message = "Done (import failed)"
                        else:
                            node.status_message = "Complete!"

                        # Auto-refresh balance after generation
                        refresh_tripo_balance()
                        return None

                    elif msg_type == "FAILED":
                        node.status_message = f"Failed: {msg[1]}"
                        node.is_generating = False
                        return None

                    elif msg_type == "ERROR":
                        node.status_message = f"Error: {msg[1]}"
                        node.is_generating = False
                        print(f"[Tripo Generate] Error: {msg[1]}")
                        return None

                except queue.Empty:
                    break

            if thread.is_alive():
                return 0.5

            if node.is_generating:
                node.is_generating = False
                node.status_message = "Stopped"
            return None

        bpy.app.timers.register(update_ui)
        return {'FINISHED'}


class TRIPO_OT_node_cancel(Operator):
    bl_idname = "tripo.node_cancel"
    bl_label = "Cancel"
    bl_description = "Cancel 3D generation"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if ntree:
            for node in ntree.nodes:
                if node.bl_idname == 'TripoGenerateNode' and node.is_generating:
                    node.is_generating = False
                    node.status_message = "Cancelled"
        return {'FINISHED'}


class TRIPO_OT_smart_lowpoly(Operator):
    """Perform Smart LowPoly retopology on a generated model"""
    bl_idname = "tripo.smart_lowpoly"
    bl_label = "Smart LowPoly"
    bl_description = "Retopologize model using Tripo's Smart LowPoly"
    bl_options = {'REGISTER'}

    node_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.tree_type == 'NeuroGenNodeTree'

    def execute(self, context):
        ntree = context.space_data.node_tree
        node = ntree.nodes.get(self.node_name)
        if not node:
            return {'CANCELLED'}

        # Get task ID from input
        task_id = node.get_input_task_id()
        if not task_id:
            self.report({'ERROR'}, "No Task ID connected. Connect a 3D Generate node first.")
            return {'CANCELLED'}

        # Get API key
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs or not prefs.tripo_api_key:
            self.report({'ERROR'}, "Tripo API key missing")
            return {'CANCELLED'}

        api_key = prefs.tripo_api_key

        from . import api_tripo
        if not api_tripo.TRIPO_AVAILABLE:
            if not api_tripo.init_tripo():
                self.report({'ERROR'}, "Tripo SDK missing")
                return {'CANCELLED'}

        # Prepare settings - use clamped face_limit based on quad mode
        settings = {
            "model_version": node.model_version,
            "quad": node.quad,
            "face_limit": node.get_clamped_face_limit(),
            "bake": node.bake,
        }

        print(f"[Smart LowPoly] Starting with task_id: {task_id}, settings: {settings}")

        # Thread communication
        msg_queue = queue.Queue()
        node.is_processing = True
        node.progress = 0
        node.status_message = "Starting..."
        node.result_task_id = ""

        def run_lowpoly():
            try:
                def callback(prog, msg):
                    msg_queue.put(("PROGRESS", prog, msg))

                result = api_tripo.smart_lowpoly(
                    api_key=api_key,
                    original_task_id=task_id,
                    progress_callback=callback,
                    **settings
                )

                print(
                    f"[Smart LowPoly] Result: status={result.status}, model_path={result.model_path}, task_id={result.task_id}")

                if result.status == "success" and result.model_path:
                    msg_queue.put(("SUCCESS", result.model_path, node.auto_import,
                                   node.model_name, result.task_id))
                else:
                    msg_queue.put(("FAILED", result.error_message or "Unknown error"))

            except Exception as e:
                print(f"[Smart LowPoly] Exception: {e}")
                msg_queue.put(("ERROR", str(e)))

        thread = threading.Thread(target=run_lowpoly)
        thread.daemon = True
        thread.start()

        def update_ui():
            while not msg_queue.empty():
                try:
                    msg = msg_queue.get_nowait()
                    msg_type = msg[0]

                    if msg_type == "PROGRESS":
                        node.progress = msg[1]
                        node.status_message = msg[2]
                        if hasattr(node.id_data, "update_tag"):
                            node.id_data.update_tag()

                    elif msg_type == "SUCCESS":
                        model_path = msg[1]
                        print(f"[Smart LowPoly] SUCCESS - model_path: {model_path}")
                        node.result_path = model_path
                        node.result_task_id = msg[4]
                        node.is_processing = False

                        if msg[2] and model_path:  # Auto import + valid path
                            imported = api_tripo.import_glb_to_blender(model_path, msg[3] or "LowPoly")
                            if imported:
                                node.status_message = "Complete!"
                            else:
                                node.status_message = "Done (import failed)"
                        else:
                            node.status_message = "Complete!"

                        refresh_tripo_balance()
                        return None

                    elif msg_type == "FAILED":
                        node.status_message = f"Failed: {msg[1]}"
                        node.is_processing = False
                        print(f"[Smart LowPoly] FAILED: {msg[1]}")
                        return None

                    elif msg_type == "ERROR":
                        node.status_message = f"Error: {msg[1]}"
                        node.is_processing = False
                        print(f"[Smart LowPoly] ERROR: {msg[1]}")
                        return None

                except queue.Empty:
                    break

            if thread.is_alive():
                return 0.5

            if node.is_processing:
                node.is_processing = False
                node.status_message = "Stopped"
            return None

        bpy.app.timers.register(update_ui)
        return {'FINISHED'}


class TRIPO_OT_lowpoly_cancel(Operator):
    bl_idname = "tripo.lowpoly_cancel"
    bl_label = "Cancel"
    bl_description = "Cancel Smart LowPoly processing"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if ntree:
            for node in ntree.nodes:
                if node.bl_idname == 'TripoSmartLowPolyNode' and node.is_processing:
                    node.is_processing = False
                    node.status_message = "Cancelled"
        return {'FINISHED'}


class TRIPO_OT_manual_import(Operator):
    """Manually import a downloaded GLB file"""
    bl_idname = "tripo.manual_import"
    bl_label = "Manual Import"
    bl_description = "Import the downloaded model into the scene"
    bl_options = {'REGISTER', 'UNDO'}

    file_path: StringProperty()
    name_prefix: StringProperty(default="Tripo")

    def execute(self, context):
        from . import api_tripo

        if not self.file_path:
            self.report({'ERROR'}, "No file path specified")
            return {'CANCELLED'}

        if not os.path.exists(self.file_path):
            self.report({'ERROR'}, f"File not found: {self.file_path}")
            return {'CANCELLED'}

        imported = api_tripo.import_glb_to_blender(self.file_path, self.name_prefix)
        if imported:
            self.report({'INFO'}, f"Imported {len(imported)} object(s)")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Import failed - check console for details")
            return {'CANCELLED'}


class TRIPO_OT_refresh_balance(Operator):
    bl_idname = "tripo.refresh_balance"
    bl_label = "Refresh Tripo Balance"
    bl_description = "Refresh Tripo token balance"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import threading

        # Get API key
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs or not prefs.tripo_api_key:
            context.scene.tripo_balance = "No API Key"
            return {'CANCELLED'}

        api_key = prefs.tripo_api_key

        def fetch_balance():
            try:
                from . import api_tripo
                if not api_tripo.TRIPO_AVAILABLE:
                    api_tripo.init_tripo()

                if api_tripo.TRIPO_AVAILABLE:
                    # Run async balance check
                    async def get_bal():
                        async with api_tripo.TripoClient(api_key=api_key) as client:
                            balance = await client.get_balance()
                            return int(balance.balance)

                    bal = api_tripo.run_async(get_bal())

                    def update_ui():
                        bpy.context.scene.tripo_balance = str(bal)
                        return None

                    bpy.app.timers.register(update_ui, first_interval=0.1)
            except Exception as e:
                print(f"[Tripo] Balance check failed: {e}")

                def update_err():
                    bpy.context.scene.tripo_balance = "Error"
                    return None

                bpy.app.timers.register(update_err, first_interval=0.1)

        threading.Thread(target=fetch_balance, daemon=True).start()
        return {'FINISHED'}


def refresh_tripo_balance():
    """Helper function to refresh balance - call after generation"""
    try:
        bpy.ops.tripo.refresh_balance()
    except Exception:
        pass


# =============================================================================
# REGISTRATION
# =============================================================================

CLASSES = [
    TripoTaskSocket,
    TripoGenerateNode,
    TripoSmartLowPolyNode,
    TRIPO_OT_node_generate,
    TRIPO_OT_node_cancel,
    TRIPO_OT_smart_lowpoly,
    TRIPO_OT_lowpoly_cancel,
    TRIPO_OT_manual_import,
    TRIPO_OT_refresh_balance,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)