# -*- coding: utf-8 -*-
"""
Blender AI Nodes - AI Geometry Nodes Generator

Generates Blender Geometry Nodes setups from natural language descriptions.
Uses LLM to write Python code that creates node trees, then executes it.
"""

import bpy
import threading
import queue
import traceback
import math  # DONT TOUCH
from bpy.props import (
    StringProperty, BoolProperty, PointerProperty, EnumProperty, IntProperty
)
from bpy.types import Node, Operator

from .nodes_core import NeuroNodeBase

# =============================================================================
# SYSTEM PROMPT FOR CODE GENERATION
# =============================================================================

GEONODES_SYSTEM_PROMPT = """You are a Blender 4.5+ Geometry Nodes expert. Generate Python code that creates geometry node setups.

CRITICAL RULES:
1. Return ONLY raw Python code. No explanations, no markdown.
2. The variable `target_object` is already defined.
3. The variable `modifier_name` is already defined.
4. DO NOT create new objects.
5. ALWAYS create a NEW node tree.

BLENDER 4.5 API - MANDATORY STRUCTURE:
```python
# Create node tree
node_tree = bpy.data.node_groups.new(name=modifier_name, type='GeometryNodeTree')
nodes = node_tree.nodes
links = node_tree.links

# BLENDER 4.5: Create sockets via interface (NOT node_tree.inputs/outputs!)
node_tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
node_tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

# Create Group Input/Output nodes
group_input = nodes.new('NodeGroupInput')
group_input.location = (-300, 0)
group_output = nodes.new('NodeGroupOutput')
group_output.location = (300, 0)

# Your nodes here...
my_node = nodes.new('GeometryNodeMeshCube')
my_node.location = (0, 0)

# Link by INDEX (0 = first socket = Geometry)
links.new(group_input.outputs[0], my_node.inputs[0])
links.new(my_node.outputs[0], group_output.inputs[0])

# Add modifier
mod = target_object.modifiers.new(name=modifier_name, type='NODES')
mod.node_group = node_tree
```

CRITICAL - NEVER USE (OLD API - BROKEN IN 4.0+):
- node_tree.inputs["Geometry"] - WRONG!
- node_tree.outputs["Geometry"] - WRONG!
- node_tree.inputs.new() - WRONG!
- node_tree.outputs.new() - WRONG!

ALWAYS USE (BLENDER 4.5 API):
- node_tree.interface.new_socket(name='X', in_out='INPUT', socket_type='NodeSocketGeometry')
- node_tree.interface.new_socket(name='X', in_out='OUTPUT', socket_type='NodeSocketGeometry')
- Access sockets by INDEX: group_input.outputs[0], group_output.inputs[0]

VALID NODE TYPES:
- Mesh: 'GeometryNodeMeshCube', 'GeometryNodeMeshCylinder', 'GeometryNodeMeshSphere', 'GeometryNodeMeshCone', 'GeometryNodeMeshGrid', 'GeometryNodeMeshIcoSphere'
- Curve: 'GeometryNodeCurvePrimitiveCircle', 'GeometryNodeCurvePrimitiveLine', 'GeometryNodeCurveQuadraticBezier'
- Instance: 'GeometryNodeInstanceOnPoints', 'GeometryNodeRealizeInstances', 'GeometryNodeRotateInstances', 'GeometryNodeScaleInstances'
- Transform: 'GeometryNodeSetPosition', 'GeometryNodeTransform', 'GeometryNodeJoinGeometry'
- Math: 'ShaderNodeMath', 'ShaderNodeVectorMath', 'FunctionNodeRandomValue'
- Input: 'GeometryNodeInputPosition', 'GeometryNodeInputNormal', 'GeometryNodeInputIndex'
- Group: 'NodeGroupInput', 'NodeGroupOutput'

Remember: Return ONLY executable Python code, no markdown."""

GEONODES_EDIT_PROMPT = """You are editing an existing Geometry Nodes Python script. The user wants changes.

RULES:
1. Return ONLY the complete modified Python code. No explanations.
2. Keep the same structure but apply the requested changes.
3. Variables `target_object` and `modifier_name` are pre-defined.
4. The EXISTING CODE is provided below - modify it according to user request.

BLENDER 4.5 API REMINDER:
- NEVER use node_tree.inputs["X"] or node_tree.outputs["X"] - BROKEN!
- Use node_tree.interface.new_socket() for creating sockets
- Access via index: group_input.outputs[0], group_output.inputs[0]

EXISTING CODE:
{existing_code}

USER REQUEST: {user_request}

Return the complete modified Python code:"""


def sanitize_geonode_code(code: str) -> str:
    """
    Fix common Blender 4.x API incompatibilities in generated code.
    The AI sometimes generates old 3.x API calls that break in 4.0+.
    """
    import re

    sanitized = code

    # Remove markdown code blocks if present
    sanitized = re.sub(r'^```python\s*', '', sanitized)
    sanitized = re.sub(r'^```\s*', '', sanitized)
    sanitized = re.sub(r'\s*```$', '', sanitized)

    # Pattern: node_tree.inputs.new() -> interface.new_socket()
    # Old: node_tree.inputs.new('NodeSocketGeometry', 'Geometry')
    # New: node_tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    sanitized = re.sub(
        r"(\w+)\.inputs\.new\s*\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)",
        r"\1.interface.new_socket(name='\3', in_out='INPUT', socket_type='\2')",
        sanitized
    )
    sanitized = re.sub(
        r"(\w+)\.outputs\.new\s*\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)",
        r"\1.interface.new_socket(name='\3', in_out='OUTPUT', socket_type='\2')",
        sanitized
    )

    # Pattern: Direct access like node_tree.inputs["Geometry"] is trickier
    # These need to be replaced with interface socket creation + index access
    # For now, we'll just print a warning and hope the updated prompt fixed it
    if '.inputs["' in sanitized or ".inputs['" in sanitized:
        if 'node_tree' in sanitized or 'tree' in sanitized:
            print(f"[{LOG_PREFIX} GeoNodes] Warning: Code may use deprecated node_tree.inputs['X'] API")

    if '.outputs["' in sanitized or ".outputs['" in sanitized:
        if 'node_tree' in sanitized or 'tree' in sanitized:
            print(f"[{LOG_PREFIX} GeoNodes] Warning: Code may use deprecated node_tree.outputs['X'] API")

    return sanitized


# =============================================================================
# GEOMETRY NODES GENERATOR NODE
# =============================================================================

class NeuroGeoNodesNode(NeuroNodeBase, Node):
    """AI Geometry Nodes - Generate node setups from text descriptions"""
    bl_idname = 'NeuroGeoNodesNode'
    bl_label = 'AI Geo Nodes'
    bl_icon = 'GEOMETRY_NODES'
    bl_width_default = 300
    bl_width_min = 250

    # --- User Input ---
    prompt: StringProperty(
        name="Request",
        description="Describe the geometry nodes setup you want",
        default=""
    )

    target_object: PointerProperty(
        name="Target",
        type=bpy.types.Object,
        description="Object to apply the geometry nodes modifier to",
        poll=lambda self, obj: obj.type == 'MESH'
    )

    modifier_name: StringProperty(
        name="Modifier Name",
        default="AI_GeoNodes",
        description="Name for the generated modifier"
    )

    # --- Settings ---
    auto_execute: BoolProperty(
        name="Auto Execute",
        default=True,
        description="Automatically execute generated code"
    )

    auto_layout: BoolProperty(
        name="Auto Layout",
        default=True,
        description="Automatically arrange nodes after generation"
    )

    thinking_level: EnumProperty(
        name="Thinking",
        items=[
            ('low', "Normal", "Light thinking - balanced"),
            ('high', "Long", "Extended thinking - best quality, slowest"),
        ],
        default='high',
        description="AI thinking depth (deeper = better code, slower)"
    )

    # --- State ---
    is_generating: BoolProperty(default=False)
    status_message: StringProperty(default="")
    generated_code: StringProperty(default="")  # Store last generated code
    last_error: StringProperty(default="")
    execution_success: BoolProperty(default=False)

    # --- UI ---
    show_code: BoolProperty(name="Show Code", default=False)
    show_settings: BoolProperty(name="Settings", default=False)

    def init(self, context):
        # Input for code editing workflow
        self.inputs.new('NeuroTextSocket', "Code In")
        self.inputs.new('NeuroTextSocket', "Prompt In")
        # Output generated code
        self.outputs.new('NeuroTextSocket', "Code Out")

    def copy(self, node):
        self.is_generating = False
        self.status_message = ""
        self.last_error = ""

    def get_prompt_text(self):
        """Get prompt from input socket or local property"""
        socket = self.inputs.get("Prompt In")
        if socket and socket.is_linked:
            try:
                link = socket.links[0]
                from_node = link.from_node
                if hasattr(from_node, 'text'):
                    return from_node.text
                if hasattr(from_node, 'result_text'):
                    return from_node.result_text
            except Exception:
                pass
        return self.prompt

    def get_input_code(self):
        """Get code from input socket for editing"""
        socket = self.inputs.get("Code In")
        if socket and socket.is_linked:
            try:
                link = socket.links[0]
                from_node = link.from_node
                # Could be from another GeoNodes node or Text node
                if hasattr(from_node, 'generated_code') and from_node.generated_code:
                    return from_node.generated_code
                if hasattr(from_node, 'text'):
                    return from_node.text
                if hasattr(from_node, 'result_text'):
                    return from_node.result_text
            except Exception:
                pass
        return ""

    def draw_buttons(self, context, layout):
        # Target object
        layout.prop(self, "target_object", text="")

        # Prompt
        col = layout.column(align=True)
        col.prop(self, "prompt", text="")

        # Settings toggle
        row = layout.row()
        row.prop(self, "show_settings",
                 icon='TRIA_DOWN' if self.show_settings else 'TRIA_RIGHT',
                 emboss=False)

        if self.show_settings:
            box = layout.box()
            box.prop(self, "modifier_name")
            box.prop(self, "thinking_level")
            row = box.row(align=True)
            row.prop(self, "auto_execute")
            row.prop(self, "auto_layout")

        # Generate button
        if self.is_generating:
            layout.label(text=self.status_message or "Generating...", icon='TIME')
            layout.operator("neuro.geonodes_cancel", text="Cancel", icon='X')
        else:
            row = layout.row(align=True)
            row.scale_y = 1.4

            # Check if we have input code (edit mode)
            has_input_code = bool(self.get_input_code())
            if has_input_code:
                op = row.operator("neuro.geonodes_generate", text="Edit", icon='GREASEPENCIL')
            else:
                op = row.operator("neuro.geonodes_generate", text="Generate", icon='GEOMETRY_NODES')
            op.node_name = self.name

            # Manual execute button (if auto_execute is off or code exists)
            if self.generated_code and not self.auto_execute:
                op = row.operator("neuro.geonodes_execute", text="", icon='PLAY')
                op.node_name = self.name
                op.tree_name = self.id_data.name

        # Status / Error
        if self.last_error:
            box = layout.box()
            box.alert = True
            # Truncate long errors
            err_text = self.last_error[:80] + "..." if len(self.last_error) > 80 else self.last_error
            box.label(text=err_text, icon='ERROR')
        elif self.execution_success:
            layout.label(text="Applied successfully", icon='CHECKMARK')

        # Show code toggle
        if self.generated_code:
            row = layout.row()
            row.prop(self, "show_code",
                     icon='TRIA_DOWN' if self.show_code else 'TRIA_RIGHT',
                     emboss=False, text="Generated Code")
            row.operator("neuro.geonodes_copy_code", text="", icon='COPYDOWN').node_name = self.name

            if self.show_code:
                box = layout.box()
                box.scale_y = 0.6
                # Show first ~10 lines
                lines = self.generated_code.split('\n')[:10]
                for line in lines:
                    if line.strip():
                        box.label(text=line[:60])
                if len(self.generated_code.split('\n')) > 10:
                    box.label(text="... (truncated)")

        # Warning about manual changes
        if self.generated_code:
            col = layout.column()
            col.scale_y = 0.7
            col.label(text="Manual node changes will be overwritten", icon='INFO')

        # Google API recommendation
        if not self.generated_code:
            col = layout.column()
            col.scale_y = 0.7
            col.label(text="Uses Claude 4.5/Gemini 3 Pro", icon='LIGHT')

    def draw_label(self):
        if self.is_generating:
            return "Generating..."
        if self.target_object:
            return f"GeoNodes → {self.target_object.name}"
        return "AI Geo Nodes"


# =============================================================================
# OPERATORS
# =============================================================================

class NEURO_OT_geonodes_generate(Operator):
    """Generate geometry nodes from description"""
    bl_idname = "neuro.geonodes_generate"
    bl_label = "Generate Geo Nodes"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        # Import status manager for job tracking
        try:
            from . import status_manager
            has_status_manager = True
        except ImportError:
            has_status_manager = False

        # Find node
        ntree = context.space_data.node_tree
        if not ntree:
            self.report({'ERROR'}, "No node tree")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}

        # Validate
        prompt = node.get_prompt_text()
        if not prompt:
            self.report({'ERROR'}, "Enter a description")
            return {'CANCELLED'}

        if not node.target_object:
            self.report({'ERROR'}, "Select a target object")
            return {'CANCELLED'}

        if node.target_object.type != 'MESH':
            self.report({'ERROR'}, "Target must be a mesh object")
            return {'CANCELLED'}

        # Check for edit mode (input code connected)
        input_code = node.get_input_code()
        is_edit_mode = bool(input_code)

        # Get preferences and API keys
        prefs = None
        for name in [__package__, "blender_ai_nodes", "ai_nodes"]:
            if name and name in context.preferences.addons:
                prefs = context.preferences.addons[name].preferences
                break

        if not prefs:
            self.report({'ERROR'}, "Could not find addon preferences")
            return {'CANCELLED'}

        # Get active provider and select model
        active_provider = getattr(prefs, 'active_provider', 'google')

        # Claude models for code generation (better at following templates)
        provider_models = {
            'replicate': 'claude-sonnet-4-5-repl',
            'aiml': 'claude-sonnet-4-5-aiml',
            'google': 'gemini-3-pro-preview',
            'fal': 'gemini-3-pro-preview',  # Fal fallback to Google
        }
        model_id = provider_models.get(active_provider, 'gemini-3-pro-preview')

        # Get API keys
        from .utils import get_all_api_keys
        api_keys = get_all_api_keys(context)

        # Validate we have the needed key
        key_map = {
            'replicate': 'replicate',
            'aiml': 'aiml',
            'google': 'google',
            'fal': 'google',  # Fal uses Google for text
        }
        required_key = key_map.get(active_provider, 'google')
        if not api_keys.get(required_key):
            self.report({'ERROR'}, f"{active_provider.upper()} API key required")
            return {'CANCELLED'}

        # Start generation
        node.is_generating = True
        node.status_message = "Connecting..."
        node.last_error = ""
        node.execution_success = False

        # Add job to status manager
        job_id = None
        if has_status_manager:
            job_id = status_manager.add_job(node.name, model_id, "GeoNodes")
            status_manager.start_job(job_id)

        msg_queue = queue.Queue()

        def run_generation():
            try:
                from .api import generate_text

                # Build prompt with system instruction
                if is_edit_mode:
                    full_prompt = GEONODES_SYSTEM_PROMPT + "\n\n" + GEONODES_EDIT_PROMPT.format(
                        existing_code=input_code,
                        user_request=prompt
                    )
                else:
                    full_prompt = GEONODES_SYSTEM_PROMPT + f"\n\nCreate a Blender Geometry Nodes setup: {prompt}"

                msg_queue.put(("STATUS", "Generating code..."))

                # Timeout based on thinking level
                timeout_map = {'none': 120, 'low': 300, 'high': 600}
                timeout = timeout_map.get(node.thinking_level, 300)

                # Use unified generate_text - routes to correct provider
                result = generate_text(
                    prompt=full_prompt,
                    model_id=model_id,
                    api_keys=api_keys,
                    timeout=timeout,
                )

                if result:
                    code = result.strip()
                    # Clean up any markdown artifacts
                    if code.startswith('```python'):
                        code = code[9:]
                    if code.startswith('```'):
                        code = code[3:]
                    if code.endswith('```'):
                        code = code[:-3]
                    code = code.strip()

                    msg_queue.put(("SUCCESS", code))
                else:
                    msg_queue.put(("ERROR", "No response from API"))

            except Exception as e:
                msg_queue.put(("ERROR", str(e)))
                traceback.print_exc()

        thread = threading.Thread(target=run_generation, daemon=True)
        thread.start()

        def update_ui():
            nonlocal job_id
            while not msg_queue.empty():
                try:
                    msg = msg_queue.get_nowait()
                    msg_type = msg[0]

                    if msg_type == "STATUS":
                        node.status_message = msg[1]

                    elif msg_type == "SUCCESS":
                        node.generated_code = msg[1]
                        node.is_generating = False
                        node.status_message = ""

                        # Complete job in status manager
                        if has_status_manager and job_id:
                            status_manager.complete_job(job_id, success=True)

                        # Auto execute if enabled
                        if node.auto_execute:
                            bpy.ops.neuro.geonodes_execute(node_name=node.name, tree_name=ntree.name)

                        return None

                    elif msg_type == "ERROR":
                        node.is_generating = False
                        node.last_error = msg[1]
                        node.status_message = ""

                        # Complete job with failure in status manager
                        if has_status_manager and job_id:
                            status_manager.complete_job(job_id, success=False, error=msg[1])

                        return None

                except queue.Empty:
                    break

            if thread.is_alive():
                return 0.3
            return None

        bpy.app.timers.register(update_ui)
        return {'FINISHED'}


class NEURO_OT_geonodes_execute(Operator):
    """Execute the generated geometry nodes code"""
    bl_idname = "neuro.geonodes_execute"
    bl_label = "Execute Geo Nodes Code"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()
    tree_name: StringProperty()

    def execute(self, context):
        # Find node tree safely (Context-agnostic)
        ntree = None
        if self.tree_name:
            ntree = bpy.data.node_groups.get(self.tree_name)

        # Fallback for manual clicks if tree_name wasn't passed
        if not ntree and context.space_data and hasattr(context.space_data, 'node_tree'):
            ntree = context.space_data.node_tree

        if not ntree:
            self.report({'ERROR'}, "Node tree not found (Context lost)")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node or not node.generated_code:
            self.report({'ERROR'}, "No code to execute")
            return {'CANCELLED'}

        if not node.target_object:
            self.report({'ERROR'}, "No target object")
            return {'CANCELLED'}

        # Remove existing modifier with same name
        obj = node.target_object
        existing_mod = obj.modifiers.get(node.modifier_name)
        if existing_mod:
            # Also remove the node group if it exists
            if existing_mod.node_group:
                old_tree_name = existing_mod.node_group.name
                obj.modifiers.remove(existing_mod)
                # Clean up old node group
                if old_tree_name in bpy.data.node_groups:
                    old_tree = bpy.data.node_groups[old_tree_name]
                    if old_tree.users == 0:
                        bpy.data.node_groups.remove(old_tree)
            else:
                obj.modifiers.remove(existing_mod)

        # Prepare execution scope
        exec_globals = {
            'bpy': bpy,
            '__builtins__': __builtins__,
            'math': math,  # Added math module just in case
        }
        exec_locals = {
            'target_object': node.target_object,
            'modifier_name': node.modifier_name,
        }

        # Sanitize code for Blender 4.x compatibility
        sanitized_code = sanitize_geonode_code(node.generated_code)

        # Execute the code
        try:
            exec(sanitized_code, exec_globals, exec_locals)
            node.execution_success = True
            node.last_error = ""

            # Auto layout if enabled
            if node.auto_layout:
                self.layout_nodes(node.target_object, node.modifier_name)

            self.report({'INFO'}, f"Applied to {node.target_object.name}")
            return {'FINISHED'}  # <--- CRITICAL: Must return FINISHED

        except SyntaxError as e:
            node.execution_success = False
            node.last_error = f"Syntax error line {e.lineno}: {e.msg}"
            self.report({'ERROR'}, node.last_error)
            return {'CANCELLED'}

        except Exception as e:
            node.execution_success = False
            node.last_error = str(e)
            self.report({'ERROR'}, f"Execution failed: {e}")
            traceback.print_exc()
            return {'CANCELLED'}

    def layout_nodes(self, obj, modifier_name):
        """Auto-arrange nodes in the generated node tree"""
        try:
            mod = obj.modifiers.get(modifier_name)
            if not mod or not mod.node_group:
                return

            node_tree = mod.node_group

            # Simple horizontal layout based on dependencies
            # Find nodes without inputs (start nodes)
            nodes_by_depth = {}

            def get_node_depth(node, visited=None):
                if visited is None:
                    visited = set()
                if node.name in visited:
                    return 0
                visited.add(node.name)

                max_input_depth = -1
                for input_socket in node.inputs:
                    if input_socket.is_linked:
                        for link in input_socket.links:
                            input_depth = get_node_depth(link.from_node, visited)
                            max_input_depth = max(max_input_depth, input_depth)

                return max_input_depth + 1

            # Calculate depths
            for node in node_tree.nodes:
                depth = get_node_depth(node)
                if depth not in nodes_by_depth:
                    nodes_by_depth[depth] = []
                nodes_by_depth[depth].append(node)

            # Position nodes
            x_spacing = 250
            y_spacing = 150

            for depth, nodes in nodes_by_depth.items():
                x = depth * x_spacing
                for i, node in enumerate(nodes):
                    y = -i * y_spacing
                    node.location = (x, y)

        except Exception as e:
            print(f"[GeoNodes] Auto-layout failed: {e}")


class NEURO_OT_geonodes_cancel(Operator):
    """Cancel generation"""
    bl_idname = "neuro.geonodes_cancel"
    bl_label = "Cancel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if ntree:
            for node in ntree.nodes:
                if node.bl_idname == 'NeuroGeoNodesNode' and node.is_generating:
                    node.is_generating = False
                    node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_geonodes_copy_code(Operator):
    """Copy generated code to clipboard"""
    bl_idname = "neuro.geonodes_copy_code"
    bl_label = "Copy Code"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = context.space_data.node_tree
        if not ntree:
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if node and node.generated_code:
            context.window_manager.clipboard = node.generated_code
            self.report({'INFO'}, "Code copied to clipboard")

        return {'FINISHED'}


# =============================================================================
# REGISTRATION
# =============================================================================

CLASSES = [
    NeuroGeoNodesNode,
    NEURO_OT_geonodes_generate,
    NEURO_OT_geonodes_execute,
    NEURO_OT_geonodes_cancel,
    NEURO_OT_geonodes_copy_code,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)