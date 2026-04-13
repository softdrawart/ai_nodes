# -*- coding: utf-8 -*-
"""QuickTools: header popover that runs artist-tool actions on the active node.

Spawns a fresh NeuroArtistToolsNode (or NeuroImageSplitterNode for Split)
linked downstream of the active node so every existing neuro.node_artist_*
operator works unchanged.
"""

import os
import bpy
from bpy.props import StringProperty, EnumProperty
from bpy.types import Operator, Panel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_node(context):
    sd = getattr(context, "space_data", None)
    if not sd or getattr(sd, "tree_type", "") != "NeuroGenNodeTree":
        return None, None
    ntree = sd.edit_tree or sd.node_tree
    if not ntree:
        return None, None
    return ntree, ntree.nodes.active


def _node_image_path(node):
    """Best-effort image path produced by `node`, or '' if none."""
    if not node:
        return ""
    p = ""
    if hasattr(node, "get_image_path"):
        try:
            p = node.get_image_path() or ""
        except TypeError:
            try:
                p = node.get_image_path(None) or ""
            except Exception:
                p = ""
        except Exception:
            p = ""
    if not p:
        p = getattr(node, "result_path", "") or ""
    if p and os.path.exists(p):
        return p
    return ""


def _image_output_sockets(node):
    """Return list of NeuroImageSocket outputs on node."""
    if not node:
        return []
    return [s for s in node.outputs if s.bl_idname == "NeuroImageSocket"]


def _pick_source_socket(node, preferred_name=""):
    outs = _image_output_sockets(node)
    if not outs:
        return None
    if preferred_name:
        for s in outs:
            if s.name == preferred_name:
                return s
    return outs[0]


def _find_or_spawn_tool(ntree, active, source_socket):
    """Always spawn a fresh NeuroArtistToolsNode linked from source_socket."""
    tool = ntree.nodes.new("NeuroArtistToolsNode")
    tool.location = (active.location.x + active.width + 50.0, active.location.y)
    try:
        ntree.links.new(source_socket, tool.inputs["Image"])
    except Exception:
        pass
    return tool


def _find_or_spawn_splitter(ntree, active, source_socket):
    """Always spawn a fresh NeuroImageSplitterNode linked from source_socket."""
    node = ntree.nodes.new("NeuroImageSplitterNode")
    node.location = (active.location.x + active.width + 50.0, active.location.y)
    try:
        ntree.links.new(source_socket, node.inputs["Image"])
    except Exception:
        pass
    return node


def _make_active(ntree, node):
    for n in ntree.nodes:
        n.select = False
    node.select = True
    ntree.nodes.active = node


def _wm_socket(context):
    """Return the currently selected socket name from wm, validated against active node."""
    wm = context.window_manager
    return getattr(wm, "neuro_quick_socket", "")


# ---------------------------------------------------------------------------
# Socket selector operator
# ---------------------------------------------------------------------------

class NEURO_OT_quicktools_set_socket(Operator):
    """Select which image output socket to process"""
    bl_idname = "neuro.quicktools_set_socket"
    bl_label = "Select Socket"
    bl_options = {'REGISTER', 'INTERNAL'}

    socket_name: StringProperty()

    def execute(self, context):
        context.window_manager.neuro_quick_socket = self.socket_name
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Dispatcher operator: spawn NeuroArtistToolsNode / NeuroImageSplitterNode
# ---------------------------------------------------------------------------

_ACTION_ITEMS = [
    ('DESCRIBE',   "Describe",   "Analyze image — list detected objects"),
    ('UPSCALE',    "Upscale",    "Upscale / enhance image"),
    ('FLIP',       "Flip",       "Flip / mirror image"),
    ('ANGLE',      "Angle",      "Change viewing angle"),
    ('DECOMPOSE',  "Decompose",  "Decompose image into parts"),
    ('SEPARATION', "Separation", "Keep / delete elements (set text in spawned node)"),
    ('MULTIVIEW',  "Multiview",  "Generate front/left/right/rear views"),
    ('SPLIT',      "Split",      "Split 2x2 grid image into 4 images"),
]

_ACTION_TO_MODE = {
    'DESCRIBE': 'DESCRIBE',
    'UPSCALE': 'UPSCALE',
    'FLIP': 'FLIP',
    'ANGLE': 'ANGLE',
    'DECOMPOSE': 'DECOMPOSE',
    'SEPARATION': 'SEPARATION',
    'MULTIVIEW': 'MULTIVIEW',
}

_ACTION_TO_OP = {
    'DESCRIBE':   'neuro.node_artist_describe',
    'UPSCALE':    'neuro.node_artist_upscale',
    'FLIP':       'neuro.node_artist_flip',
    'ANGLE':      'neuro.node_artist_angle',
    'DECOMPOSE':  'neuro.node_artist_decompose',
    'MULTIVIEW':  'neuro.node_artist_multiview',
    # SPLIT uses NeuroImageSplitterNode — handled separately in execute()
    # SEPARATION intentionally omitted — needs element text; user fills it in the spawned node.
}


class NEURO_OT_quicktools_run(Operator):
    """Spawn an Artist Tools node (or Image Splitter for Split) linked from the active node and run the chosen action"""
    bl_idname = "neuro.quicktools_run"
    bl_label = "QuickTools Run"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=_ACTION_ITEMS, default='DESCRIBE')
    flip_direction: EnumProperty(
        items=[('HORIZONTAL', "Horizontal", ""), ('VERTICAL', "Vertical", ""), ('BOTH', "Both", "")],
        default='HORIZONTAL',
    )
    angle_preset: EnumProperty(
        items=[('ISOMETRIC', "Isometric", ""), ('ISOMETRIC2', "Isometric V2", ""),
               ('FRONT', "Front", ""), ('SIDE', "Side", ""), ('TOP', "Top", ""),
               ('CUSTOM', "Custom", "")],
        default='ISOMETRIC',
    )
    upscale_preset: EnumProperty(
        items=[('UPSCALE', "Upscale", ""), ('UPSCALE_ENHANCE', "Upscale + Enhance", ""),
               ('IMPROVE', "Polish", ""), ('CREATIVE', "Creative Finish", "")],
        default='UPSCALE_ENHANCE',
    )
    source_socket: StringProperty(default="")

    def execute(self, context):
        ntree, active = _active_node(context)
        if not ntree or not active:
            self.report({'WARNING'}, "No active node")
            return {'CANCELLED'}

        src = _pick_source_socket(active, self.source_socket)
        if src is None:
            self.report({'WARNING'}, "Active node has no image output")
            return {'CANCELLED'}

        # SPLIT needs NeuroImageSplitterNode, not an artist tools node
        if self.action == 'SPLIT':
            splitter = _find_or_spawn_splitter(ntree, active, src)
            _make_active(ntree, splitter)
            try:
                bpy.ops.neuro.node_split_image(node_name=splitter.name)
            except Exception as e:
                self.report({'ERROR'}, f"QuickTools: {e}")
                return {'CANCELLED'}
            return {'FINISHED'}

        # All other actions: always spawn a fresh NeuroArtistToolsNode downstream
        tool = _find_or_spawn_tool(ntree, active, src)

        # Configure mode / params
        mode = _ACTION_TO_MODE.get(self.action)
        if mode:
            try:
                tool.tool_mode = mode
            except Exception:
                pass

        if self.action == 'FLIP':
            tool.flip_direction = self.flip_direction
        elif self.action == 'ANGLE':
            tool.angle_preset = self.angle_preset
        elif self.action == 'UPSCALE':
            tool.upscale_preset = self.upscale_preset

        _make_active(ntree, tool)

        if self.action == 'SEPARATION':
            self.report({'INFO'}, "Artist Tools node ready — enter element text and click Run")
            return {'FINISHED'}

        op_id = _ACTION_TO_OP.get(self.action)
        if not op_id:
            return {'CANCELLED'}

        mod, name = op_id.split('.')
        try:
            getattr(getattr(bpy.ops, mod), name)(node_name=tool.name)
        except Exception as e:
            self.report({'ERROR'}, f"QuickTools: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Submenus (Upscale / Flip / Angle)
# ---------------------------------------------------------------------------

class NEURO_MT_quicktools_upscale(bpy.types.Menu):
    bl_label = "Upscale"
    bl_idname = "NEURO_MT_quicktools_upscale"

    def draw(self, context):
        layout = self.layout
        for pid, plabel, _ in [
            ('UPSCALE', "Upscale", ""),
            ('UPSCALE_ENHANCE', "Upscale + Enhance", ""),
            ('IMPROVE', "Polish", ""),
            ('CREATIVE', "Creative Finish", ""),
        ]:
            op = layout.operator("neuro.quicktools_run", text=plabel, icon='FULLSCREEN_EXIT')
            op.action = 'UPSCALE'
            op.upscale_preset = pid


class NEURO_MT_quicktools_flip(bpy.types.Menu):
    bl_label = "Flip"
    bl_idname = "NEURO_MT_quicktools_flip"

    def draw(self, context):
        layout = self.layout
        for pid, plabel in [
            ('HORIZONTAL', "Horizontal"),
            ('VERTICAL', "Vertical"),
            ('BOTH', "Both (180°)"),
        ]:
            op = layout.operator("neuro.quicktools_run", text=plabel, icon='MOD_MIRROR')
            op.action = 'FLIP'
            op.flip_direction = pid


class NEURO_MT_quicktools_angle(bpy.types.Menu):
    bl_label = "Angle"
    bl_idname = "NEURO_MT_quicktools_angle"

    def draw(self, context):
        layout = self.layout
        for pid, plabel in [
            ('ISOMETRIC', "Isometric"),
            ('ISOMETRIC2', "Isometric V2"),
            ('FRONT', "Front"),
            ('SIDE', "Side"),
            ('TOP', "Top Down"),
            ('CUSTOM', "Custom (edit in node)"),
        ]:
            op = layout.operator("neuro.quicktools_run", text=plabel, icon='ORIENTATION_GIMBAL')
            op.action = 'ANGLE'
            op.angle_preset = pid


# ---------------------------------------------------------------------------
# Popover panel
# ---------------------------------------------------------------------------

class NEURO_PT_quick_tools(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'HEADER'
    bl_label = "QuickTools"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        ntree, active = _active_node(context)

        if not ntree:
            layout.label(text="Open an AI Nodes tree", icon='INFO')
            return

        if not active:
            layout.label(text="Select a node with an image", icon='INFO')
            return

        img_path = _node_image_path(active)
        outs = _image_output_sockets(active)

        header = layout.row()
        header.label(text=f"Active: {active.name}", icon='NODE')

        if not outs and not img_path:
            layout.label(text="Node has no image output", icon='ERROR')
            return

        # --- Socket switcher when node has multiple image outputs ---
        wm = context.window_manager
        selected_socket = getattr(wm, "neuro_quick_socket", "")
        valid_names = [s.name for s in outs]
        if selected_socket not in valid_names:
            selected_socket = valid_names[0] if valid_names else ""

        if len(outs) > 1:
            row = layout.row(align=True)
            row.label(text="Output:")
            for s in outs:
                op = row.operator(
                    "neuro.quicktools_set_socket",
                    text=s.name,
                    depress=(s.name == selected_socket),
                )
                op.socket_name = s.name

        socket_name = selected_socket

        # --- Image actions (spawn artist / splitter tool) ---
        col = layout.column(align=True)
        col.label(text="Image Actions", icon='TOOL_SETTINGS')

        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, align=True)

        op = grid.operator("neuro.quicktools_run", text="Describe", icon='VIEWZOOM')
        op.action = 'DESCRIBE'
        op.source_socket = socket_name

        op = grid.operator("neuro.quicktools_run", text="Decompose", icon='MOD_EXPLODE')
        op.action = 'DECOMPOSE'
        op.source_socket = socket_name

        op = grid.operator("neuro.quicktools_run", text="Multiview", icon='VIEW_CAMERA')
        op.action = 'MULTIVIEW'
        op.source_socket = socket_name

        op = grid.operator("neuro.quicktools_run", text="Split 2x2", icon='MESH_GRID')
        op.action = 'SPLIT'
        op.source_socket = socket_name

        op = grid.operator("neuro.quicktools_run", text="Separation", icon='SELECT_EXTEND')
        op.action = 'SEPARATION'
        op.source_socket = socket_name

        # Submenus for preset-bearing actions
        col.separator(factor=0.5)
        row = col.row(align=True)
        row.menu("NEURO_MT_quicktools_upscale", text="Upscale", icon='FULLSCREEN_EXIT')
        row.menu("NEURO_MT_quicktools_flip", text="Flip", icon='MOD_MIRROR')
        row.menu("NEURO_MT_quicktools_angle", text="Angle", icon='ORIENTATION_GIMBAL')

        # --- Pass-through actions (operate on active node directly) ---
        layout.separator()
        col = layout.column(align=True)
        col.label(text="Utilities", icon='MODIFIER')

        row = col.row(align=True)
        sub = row.row(align=True)
        sub.enabled = bool(img_path)
        op = sub.operator("neuro.node_copy_image_file", text="Copy File", icon='COPYDOWN')
        op.image_path = img_path or ""

        sub = row.row(align=True)
        sub.enabled = bool(img_path)
        op = sub.operator("neuro.add_to_shader", text="Add to Shader", icon='NODE_MATERIAL')
        op.node_name = active.name

        row = col.row(align=True)
        sub = row.row(align=True)
        sub.enabled = bool(img_path)
        op = sub.operator("neuro.node_remove_bg", text="Remove BG", icon='IMAGE_RGB_ALPHA')
        op.node_name = active.name

        sub = row.row(align=True)
        sub.enabled = bool(img_path)
        op = sub.operator("neuro.node_open_paint_smart", text="Paint", icon='BRUSH_DATA')
        op.node_name = active.name

        if not img_path:
            layout.separator()
            layout.label(text="No image yet — generate one first", icon='INFO')


# ---------------------------------------------------------------------------
# Registration helpers (called from nodes.py CLASSES list)
# ---------------------------------------------------------------------------

def register():
    bpy.types.WindowManager.neuro_quick_socket = bpy.props.StringProperty(
        name="QuickTools Selected Socket", default=""
    )


def unregister():
    try:
        del bpy.types.WindowManager.neuro_quick_socket
    except Exception:
        pass


CLASSES = (
    NEURO_OT_quicktools_set_socket,
    NEURO_OT_quicktools_run,
    NEURO_MT_quicktools_upscale,
    NEURO_MT_quicktools_flip,
    NEURO_MT_quicktools_angle,
    NEURO_PT_quick_tools,
)
