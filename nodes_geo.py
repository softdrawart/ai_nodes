# -*- coding: utf-8 -*-
"""
Blender AI Nodes - AI Geometry Nodes Generator

JSON schema approach:
- LLM fills a strict JSON spec (no raw Python, no exec())
- Curated node reference in prompt (not runtime catalog)
- Deterministic builder creates the node tree from validated JSON
- Retry with error feedback on failure
"""

import bpy
import json
import re
import threading
import queue
import traceback
import math  # DONT TOUCH
from bpy.props import (
    StringProperty, BoolProperty, PointerProperty, EnumProperty, IntProperty
)
from bpy.types import Node, Operator

from .nodes_core import NeuroNodeBase
from .constants import LOG_PREFIX


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

GEONODES_SYSTEM_PROMPT = """You are a Blender 4.5+ Geometry Nodes expert. Return ONLY a valid JSON object. No markdown, no explanation, no code fences.

JSON SCHEMA:
{
  "interface": {
    "inputs":  [{"name": "Geometry", "type": "NodeSocketGeometry"}, {"name": "Count", "type": "NodeSocketInt", "default": 5}],
    "outputs": [{"name": "Geometry", "type": "NodeSocketGeometry"}]
  },
  "nodes": [
    {
      "id": "unique_id",
      "type": "GeometryNodeMeshCube",
      "props": {},
      "inputs": {"Size": [2.0, 2.0, 2.0]},
      "location": [0, 0]
    }
  ],
  "links": [
    {"from": "group_input.Geometry", "to": "set_pos.Geometry"}
  ]
}

RULES:
- "id": unique string per node. "group_input" and "group_output" are reserved (auto-created).
- "type": must be a real Blender 4.5 node type (see reference below).
- "props": enum properties ONLY (operation, mode, data_type, domain). Set BEFORE inputs.
- "inputs": default values for UNLINKED sockets by socket name. Float=number, Int=int, Bool=true/false, Vector=[x,y,z], Color=[r,g,b,a]. VECTORS ARE ALWAYS ARRAYS, never a single number.
- "links": format is "node_id.Socket Name". For duplicate socket names use "node_id.Socket Name[1]" for the second. The [n] index is ONLY for sockets that share the same name (like two "Value" inputs on Math). You CANNOT use it to address vector components — "Size[1]" does NOT mean "Y component of Size". To control individual axes of a Vector socket, use ShaderNodeCombineXYZ to build the vector from separate floats, then link CombineXYZ.Vector → the Vector socket.
- "location": [x, y] for layout. Space nodes ~250px apart horizontally.
- Always include Geometry interface input+output unless generating entirely new geometry from scratch.
- Define nodes in data-flow order.
- ALWAYS expose key user-adjustable parameters as extra interface inputs so they appear as controls in the modifier panel. Examples: counts, density, scale, spacing, randomness seeds, dimensions. Use descriptive names. Valid socket types for interface inputs: NodeSocketFloat, NodeSocketInt, NodeSocketBool, NodeSocketVector, NodeSocketColor. Link these from group_input to the node inputs that should be adjustable.
- When an INSTANCE OBJECT is provided (see below), you MUST use it as the instanced element via GeometryNodeObjectInfo. Connect ObjectInfo.Geometry → InstanceOnPoints.Instance (or similar). Do NOT build replacement geometry — use the provided object.

NODE REFERENCE (common types):

Mesh Primitives:
  GeometryNodeMeshCube — in: Size(Vec), Vertices X/Y/Z(Int) | out: Mesh(Geo), UV Map
  GeometryNodeMeshCylinder — in: Vertices(Int), Side Segments(Int), Fill Segments(Int), Radius(Float), Depth(Float) | out: Mesh(Geo), Top, Side, Bottom
  GeometryNodeMeshCone — in: Vertices(Int), Side Segments(Int), Fill Segments(Int), Radius Top/Bottom(Float), Depth(Float) | out: Mesh(Geo), Top, Side, Bottom
  GeometryNodeMeshGrid — in: Size X/Y(Float), Vertices X/Y(Int) | out: Mesh(Geo), UV Map
  GeometryNodeMeshIcoSphere — in: Radius(Float), Subdivisions(Int) | out: Mesh(Geo), UV Map
  GeometryNodeMeshUVSphere — in: Segments(Int), Rings(Int), Radius(Float) | out: Mesh(Geo), UV Map
  GeometryNodeMeshCircle — in: Vertices(Int), Radius(Float) | out: Mesh(Geo)
  GeometryNodeMeshLine — props: mode=OFFSET/END_POINTS | in: Count(Int), Start Location(Vec), Offset(Vec) | out: Mesh(Geo)

Curve Primitives:
  GeometryNodeCurvePrimitiveCircle — props: mode=POINTS/RADIUS | in: Resolution(Int), Radius(Float) | out: Curve(Geo)
  GeometryNodeCurvePrimitiveLine — props: mode=POINTS/DIRECTION | in: Start(Vec), End(Vec) | out: Curve(Geo)
  GeometryNodeCurveQuadraticBezier — in: Resolution(Int), Start(Vec), Middle(Vec), End(Vec) | out: Curve(Geo)
  GeometryNodeCurvePrimitiveBezierSegment — in: Resolution(Int), Start(Vec), Start Handle(Vec), End Handle(Vec), End(Vec) | out: Curve(Geo)
  GeometryNodeCurveStar — in: Points(Int), Inner Radius(Float), Outer Radius(Float) | out: Curve(Geo)
  GeometryNodeCurveSpiral — in: Rotations(Float), Start Radius(Float), End Radius(Float), Height(Float) | out: Curve(Geo)

Curve Operations:
  GeometryNodeCurveToMesh — in: Curve(Geo), Profile Curve(Geo), Fill Caps(Bool) | out: Mesh(Geo)
  GeometryNodeFillCurve — in: Curve(Geo) | out: Mesh(Geo)
  GeometryNodeResampleCurve — props: mode=COUNT/LENGTH/EVALUATED | in: Curve(Geo), Count(Int) | out: Curve(Geo)
  GeometryNodeReverseCurve — in: Curve(Geo) | out: Curve(Geo)
  GeometryNodeSubdivideCurve — in: Curve(Geo), Cuts(Int) | out: Curve(Geo)
  GeometryNodeTrimCurve — in: Curve(Geo), Start(Float), End(Float) | out: Curve(Geo)
  GeometryNodeCurveSetHandles — props: handle_type=FREE/AUTO/VECTOR/ALIGN | in: Curve(Geo) | out: Curve(Geo)

Instances:
  GeometryNodeInstanceOnPoints — in: Points(Geo), Instance(Geo), Pick Instance(Bool), Rotation(Vec), Scale(Vec) | out: Instances(Geo)
  NOTE: Scale on InstanceOnPoints is a MULTIPLIER relative to the instance object's own size (1.0 = original size). Use values like [1.0, 1.0, 0.8] to [1.0, 1.0, 1.2] for subtle variation — NOT absolute dimensions like [0.04, 0.22, 0.25].
  GeometryNodeRealizeInstances — in: Geometry(Geo) | out: Geometry(Geo)
  GeometryNodeRotateInstances — in: Instances(Geo), Rotation(Vec) | out: Instances(Geo)
  GeometryNodeScaleInstances — in: Instances(Geo), Scale(Vec) | out: Instances(Geo)
  GeometryNodeTranslateInstances — in: Instances(Geo), Translation(Vec) | out: Instances(Geo)

Transform & Geometry:
  GeometryNodeSetPosition — in: Geometry(Geo), Position(Vec), Offset(Vec) | out: Geometry(Geo)
  GeometryNodeTransform — in: Geometry(Geo), Translation(Vec), Rotation(Vec), Scale(Vec) | out: Geometry(Geo)
  GeometryNodeJoinGeometry — in: Geometry(Geo) [multi-input] | out: Geometry(Geo)
  GeometryNodeMergeByDistance — in: Geometry(Geo), Distance(Float) | out: Geometry(Geo)
  GeometryNodeSetShadeSmooth — in: Geometry(Geo), Shade Smooth(Bool) | out: Geometry(Geo)
  GeometryNodeSubdivisionSurface — in: Mesh(Geo), Level(Int) | out: Mesh(Geo)
  GeometryNodeDualMesh — in: Mesh(Geo) | out: Dual Mesh(Geo)
  GeometryNodeFlipFaces — in: Mesh(Geo) | out: Mesh(Geo)
  GeometryNodeExtrudeMesh — props: mode=VERTICES/EDGES/FACES | in: Mesh(Geo), Offset(Vec), Offset Scale(Float) | out: Mesh(Geo), Top, Side
  GeometryNodeScaleElements — props: domain=FACE/EDGE | in: Geometry(Geo), Scale(Float), Center(Vec) | out: Geometry(Geo)
  GeometryNodeDeleteGeometry — props: domain=POINT/EDGE/FACE | in: Geometry(Geo), Selection(Bool) | out: Geometry(Geo)
  GeometryNodeSeparateGeometry — props: domain=POINT/EDGE/FACE | in: Geometry(Geo), Selection(Bool) | out: Selection(Geo), Inverted(Geo)
  GeometryNodeConvexHull — in: Geometry(Geo) | out: Convex Hull(Geo)
  GeometryNodeBoundBox — in: Geometry(Geo) | out: Bounding Box(Geo), Min(Vec), Max(Vec)
  GeometryNodeMeshBoolean — props: operation=INTERSECT/UNION/DIFFERENCE | in: Mesh 1(Geo), Mesh 2(Geo) | out: Mesh(Geo)

Math:
  ShaderNodeMath — props: operation=ADD/SUBTRACT/MULTIPLY/DIVIDE/POWER/SQRT/ABSOLUTE/MINIMUM/MAXIMUM/ROUND/FLOOR/CEIL/MODULO/SINE/COSINE/TANGENT/GREATER_THAN/LESS_THAN/COMPARE/SMOOTH_MIN/SMOOTH_MAX/WRAP/SNAP/PINGPONG | in: Value(Float), Value(Float) | out: Value(Float)
  ShaderNodeVectorMath — props: operation=ADD/SUBTRACT/MULTIPLY/DIVIDE/SCALE/LENGTH/DISTANCE/NORMALIZE/CROSS_PRODUCT/DOT_PRODUCT/MINIMUM/MAXIMUM/FLOOR/CEIL/MODULO/FRACTION/WRAP/SNAP/SINE/COSINE/TANGENT/ABSOLUTE | in: Vector(Vec), Vector(Vec), Scale(Float) | out: Vector(Vec), Value(Float)
  FunctionNodeBooleanMath — props: operation=AND/OR/NOT/NAND/NOR/XNOR/XOR | in: Boolean(Bool), Boolean(Bool) | out: Boolean(Bool)
  ShaderNodeMapRange — props: data_type=FLOAT/FLOAT_VECTOR | in: Value(Float), From Min(Float), From Max(Float), To Min(Float), To Max(Float) | out: Result(Float)
  ShaderNodeClamp — props: clamp_type=MINMAX/RANGE | in: Value(Float), Min(Float), Max(Float) | out: Result(Float)
  FunctionNodeCompare — props: data_type=FLOAT/INT/VECTOR/STRING, operation=GREATER_THAN/LESS_THAN/GREATER_EQUAL/LESS_EQUAL/EQUAL/NOT_EQUAL | in: A(Float), B(Float) | out: Result(Bool)

Input:
  GeometryNodeInputPosition — out: Position(Vec)
  GeometryNodeInputNormal — out: Normal(Vec)
  GeometryNodeInputIndex — out: Index(Int)
  GeometryNodeInputID — out: ID(Int)
  GeometryNodeInputSceneTime — out: Seconds(Float), Frame(Float)

Random & Noise:
  FunctionNodeRandomValue — props: data_type=FLOAT/INT/FLOAT_VECTOR/BOOLEAN | in: Min(Float), Max(Float), Seed(Int) | out: Value
  ShaderNodeTexNoise — props: noise_dimensions=1D/2D/3D/4D | in: Vector(Vec), Scale(Float), Detail(Float), Roughness(Float), Lacunarity(Float), Distortion(Float) | out: Fac(Float), Color(Color)
  ShaderNodeTexVoronoi — props: voronoi_dimensions=1D/2D/3D/4D, feature=F1/F2/SMOOTH_F1/DISTANCE_TO_EDGE/N_SPHERE_RADIUS | in: Vector(Vec), Scale(Float), Randomness(Float) | out: Distance(Float), Color(Color), Position(Vec)
  ShaderNodeTexWave — props: wave_type=BANDS/RINGS | in: Vector(Vec), Scale(Float), Distortion(Float), Detail(Float) | out: Color(Color), Fac(Float)
  ShaderNodeTexGradient — props: gradient_type=LINEAR/QUADRATIC/EASING/DIAGONAL/SPHERICAL/RADIAL | in: Vector(Vec) | out: Color(Color), Fac(Float)
  ShaderNodeTexWhiteNoise — props: noise_dimensions=1D/2D/3D/4D | in: Vector(Vec) | out: Value(Float), Color(Color)

Attribute:
  GeometryNodeStoreNamedAttribute — props: data_type=FLOAT/INT/FLOAT_VECTOR/FLOAT_COLOR/BOOLEAN, domain=POINT/EDGE/FACE/CORNER | in: Geometry(Geo), Name(Str), Value | out: Geometry(Geo)
  GeometryNodeCaptureAttribute — props: data_type=FLOAT/INT/FLOAT_VECTOR/FLOAT_COLOR/BOOLEAN | in: Geometry(Geo), Value | out: Geometry(Geo), Attribute

Utilities:
  GeometryNodeSwitch — props: input_type=GEOMETRY/FLOAT/INT/BOOLEAN/VECTOR/STRING | in: Switch(Bool), False/True | out: Output
  ShaderNodeMix — props: data_type=FLOAT/VECTOR/RGBA, blend_type=MIX/ADD/MULTIPLY/SCREEN/OVERLAY | in: Factor(Float), A, B | out: Result
  ShaderNodeSeparateXYZ — in: Vector(Vec) | out: X(Float), Y(Float), Z(Float)
  ShaderNodeCombineXYZ — in: X(Float), Y(Float), Z(Float) | out: Vector(Vec)
  ShaderNodeValToRGB — in: Fac(Float) | out: Color(Color), Alpha(Float)
  FunctionNodeInputVector — out: Vector(Vec)
  ShaderNodeValue — out: Value(Float)
  FunctionNodeInputInt — out: Integer(Int)
  FunctionNodeInputBool — out: Boolean(Bool)
  FunctionNodeInputColor — out: Color(Color)

Material & UV:
  GeometryNodeSetMaterial — in: Geometry(Geo), Material(Material) | out: Geometry(Geo)

Object Info:
  GeometryNodeObjectInfo — in: Object(Object), As Instance(Bool) | out: Location(Vec), Rotation(Vec), Scale(Vec), Geometry(Geo)

Point Distribution:
  GeometryNodeDistributePointsOnFaces — props: distribute_method=RANDOM/POISSON | in: Mesh(Geo), Density(Float), Seed(Int) | out: Points(Geo), Normal(Vec), Rotation(Vec)
  GeometryNodeMeshToPoints — props: mode=VERTICES/EDGES/FACES/CORNERS | in: Mesh(Geo) | out: Points(Geo)
  GeometryNodePointsToVertices — in: Points(Geo) | out: Mesh(Geo)

Geometry Info:
  GeometryNodeProximity — props: target_element=POINTS/EDGES/FACES | in: Target(Geo), Source Position(Vec) | out: Position(Vec), Distance(Float)
  GeometryNodeRaycast — in: Target Geometry(Geo), Source Position(Vec), Ray Direction(Vec), Ray Length(Float) | out: Is Hit(Bool), Hit Position(Vec), Hit Normal(Vec), Hit Distance(Float)

MULTI-INPUT SOCKETS (GeometryNodeJoinGeometry):
Join Geometry has a multi-input. Connect multiple sources to the same socket:
  {"from": "cube.Mesh", "to": "join.Geometry"},
  {"from": "sphere.Mesh", "to": "join.Geometry"}

IMPORTANT - OUTPUT SOCKET NAMES:
- ShaderNodeMath outputs "Value" (NOT "Result")
- ShaderNodeVectorMath outputs "Vector" and "Value" (NOT "Result")
- ShaderNodeMapRange outputs "Result" (this one IS "Result")
- ShaderNodeClamp outputs "Result" (this one IS "Result")
- FunctionNodeCompare outputs "Result" (this one IS "Result")

EXAMPLE (scattered spheres on displaced surface with user controls):
{
  "interface": {
    "inputs": [
      {"name": "Geometry", "type": "NodeSocketGeometry"},
      {"name": "Density", "type": "NodeSocketFloat", "default": 8.0},
      {"name": "Sphere Radius", "type": "NodeSocketFloat", "default": 0.05},
      {"name": "Noise Scale", "type": "NodeSocketFloat", "default": 4.0},
      {"name": "Displacement", "type": "NodeSocketFloat", "default": 0.3},
      {"name": "Seed", "type": "NodeSocketInt", "default": 5}
    ],
    "outputs": [{"name": "Geometry", "type": "NodeSocketGeometry"}]
  },
  "nodes": [
    {"id": "pos", "type": "GeometryNodeInputPosition", "props": {}, "inputs": {}, "location": [-500, -150]},
    {"id": "noise", "type": "ShaderNodeTexNoise", "props": {}, "inputs": {"Detail": 6.0}, "location": [-250, -150]},
    {"id": "scale_vec", "type": "ShaderNodeVectorMath", "props": {"operation": "SCALE"}, "inputs": {}, "location": [0, -150]},
    {"id": "set_pos", "type": "GeometryNodeSetPosition", "props": {}, "inputs": {}, "location": [250, 0]},
    {"id": "distribute", "type": "GeometryNodeDistributePointsOnFaces", "props": {"distribute_method": "POISSON"}, "inputs": {}, "location": [500, 0]},
    {"id": "ico", "type": "GeometryNodeMeshIcoSphere", "props": {}, "inputs": {"Subdivisions": 2}, "location": [500, -250]},
    {"id": "instance", "type": "GeometryNodeInstanceOnPoints", "props": {}, "inputs": {}, "location": [750, 0]},
    {"id": "realize", "type": "GeometryNodeRealizeInstances", "props": {}, "inputs": {}, "location": [1000, 0]},
    {"id": "join", "type": "GeometryNodeJoinGeometry", "props": {}, "inputs": {}, "location": [1250, 0]}
  ],
  "links": [
    {"from": "pos.Position", "to": "noise.Vector"},
    {"from": "group_input.Noise Scale", "to": "noise.Scale"},
    {"from": "noise.Fac", "to": "scale_vec.Vector"},
    {"from": "group_input.Displacement", "to": "scale_vec.Scale"},
    {"from": "group_input.Geometry", "to": "set_pos.Geometry"},
    {"from": "scale_vec.Vector", "to": "set_pos.Offset"},
    {"from": "set_pos.Geometry", "to": "distribute.Mesh"},
    {"from": "group_input.Density", "to": "distribute.Density"},
    {"from": "group_input.Seed", "to": "distribute.Seed"},
    {"from": "distribute.Points", "to": "instance.Points"},
    {"from": "ico.Mesh", "to": "instance.Instance"},
    {"from": "group_input.Sphere Radius", "to": "ico.Radius"},
    {"from": "instance.Instances", "to": "realize.Geometry"},
    {"from": "set_pos.Geometry", "to": "join.Geometry"},
    {"from": "realize.Geometry", "to": "join.Geometry"},
    {"from": "join.Geometry", "to": "group_output.Geometry"}
  ]
}"""

GEONODES_EDIT_PROMPT = """You are editing an existing Geometry Nodes setup. Modify the JSON below according to the user request. Return the COMPLETE modified JSON only.

EXISTING:
{existing_json}

REQUEST: {user_request}"""


# =============================================================================
# JSON VALIDATION
# =============================================================================

def _validate_spec(spec):
    """Basic structural validation. Returns list of error strings."""
    errors = []

    if not isinstance(spec, dict):
        return ["Root must be a JSON object"]

    for key in ('interface', 'nodes', 'links'):
        if key not in spec:
            errors.append(f"Missing key: '{key}'")
    if errors:
        return errors

    seen_ids = set()
    for i, ns in enumerate(spec.get('nodes', [])):
        nid = ns.get('id', f'__unnamed_{i}')
        if nid in ('group_input', 'group_output'):
            errors.append(f"Node id '{nid}' is reserved")
        if nid in seen_ids:
            errors.append(f"Duplicate node id: '{nid}'")
        seen_ids.add(nid)

        if 'type' not in ns:
            errors.append(f"Node '{nid}': missing 'type'")

    valid_ids = {'group_input', 'group_output'} | seen_ids
    for link in spec.get('links', []):
        for key in ('from', 'to'):
            endpoint = link.get(key, '')
            if '.' not in endpoint:
                errors.append(f"Link '{key}': '{endpoint}' must be 'node_id.Socket Name'")
                continue
            node_id = endpoint.split('.', 1)[0]
            if node_id not in valid_ids:
                errors.append(f"Link '{key}': unknown node '{node_id}'")

    return errors


# =============================================================================
# DETERMINISTIC BUILDER
# =============================================================================

def _find_socket(sockets, name_expr):
    """
    Resolve socket by name, with optional [n] index for duplicates.
    "Value"    -> first socket named "Value"
    "Value[1]" -> second socket named "Value"
    """
    m = re.match(r'^(.+?)\[(\d+)\]$', name_expr)
    if m:
        name, idx = m.group(1), int(m.group(2))
    else:
        name, idx = name_expr, 0

    count = 0
    for s in sockets:
        if s.name == name:
            if count == idx:
                return s
            count += 1

    # Fallback: raw integer index
    try:
        i = int(name_expr)
        if 0 <= i < len(sockets):
            return sockets[i]
    except ValueError:
        pass

    return None


def _set_socket_default(sock, value):
    """
    Safely set a socket default value, handling type coercion.
    Vectors need arrays, floats need numbers, etc.
    """
    if not hasattr(sock, 'default_value'):
        return

    current = sock.default_value

    # Vector/Color socket — current value has length
    if hasattr(current, '__len__'):
        if isinstance(value, (list, tuple)):
            for i in range(min(len(value), len(current))):
                try:
                    current[i] = float(value[i])
                except (TypeError, ValueError):
                    pass
        else:
            # Scalar for vector socket -> fill all components
            for i in range(len(current)):
                try:
                    current[i] = float(value)
                except (TypeError, ValueError):
                    pass
    else:
        # Scalar socket
        if isinstance(value, (list, tuple)):
            sock.default_value = value[0] if value else 0
        elif isinstance(value, bool) and not isinstance(current, bool):
            sock.default_value = int(value)
        else:
            try:
                sock.default_value = type(current)(value)
            except (TypeError, ValueError):
                sock.default_value = value


def build_geo_tree(spec, target_object, modifier_name):
    """
    Build a geometry node tree from validated JSON spec.
    Returns (node_tree_or_None, warning_string_or_None).
    """
    warnings = []
    node_tree = bpy.data.node_groups.new(name=modifier_name, type='GeometryNodeTree')
    nodes = node_tree.nodes
    links = node_tree.links

    try:
        # ── Interface sockets ──
        for s in spec['interface'].get('inputs', []):
            sock_item = node_tree.interface.new_socket(
                name=s['name'], in_out='INPUT',
                socket_type=s.get('type', 'NodeSocketGeometry')
            )
            if 'default' in s and hasattr(sock_item, 'default_value'):
                try:
                    val = s['default']
                    if hasattr(sock_item.default_value, '__len__'):
                        if isinstance(val, (list, tuple)):
                            for i in range(min(len(val), len(sock_item.default_value))):
                                sock_item.default_value[i] = float(val[i])
                        else:
                            for i in range(len(sock_item.default_value)):
                                sock_item.default_value[i] = float(val)
                    else:
                        sock_item.default_value = type(sock_item.default_value)(val)
                except Exception as e:
                    warnings.append(f"Interface '{s['name']}' default={s['default']}: {e}")
        for s in spec['interface'].get('outputs', []):
            node_tree.interface.new_socket(
                name=s['name'], in_out='OUTPUT',
                socket_type=s.get('type', 'NodeSocketGeometry')
            )

        # ── Group Input / Output ──
        group_input = nodes.new('NodeGroupInput')
        group_input.location = (-400, 0)
        group_output = nodes.new('NodeGroupOutput')
        group_output.location = (600, 0)
        node_map = {'group_input': group_input, 'group_output': group_output}

        # ── Create nodes ──
        for ns in spec['nodes']:
            nid   = ns['id']
            ntype = ns['type']

            try:
                node = nodes.new(ntype)
            except Exception as e:
                warnings.append(f"[{nid}] Failed to create '{ntype}': {e}")
                continue

            loc = ns.get('location', [0, 0])
            node.location = (loc[0], loc[1])
            node.name  = nid
            node.label = ns.get('label', '')
            node_map[nid] = node

            # Props FIRST (may change available sockets)
            for prop_name, prop_val in ns.get('props', {}).items():
                try:
                    setattr(node, prop_name, prop_val)
                except Exception as e:
                    warnings.append(f"[{nid}] prop '{prop_name}'={prop_val}: {e}")

            # Input defaults (unlinked sockets)
            for sock_name, value in ns.get('inputs', {}).items():
                sock = _find_socket(node.inputs, sock_name)
                if sock is None:
                    warnings.append(f"[{nid}] input '{sock_name}' not found")
                    continue
                try:
                    _set_socket_default(sock, value)
                except Exception as e:
                    warnings.append(f"[{nid}] '{sock_name}'={value}: {e}")

        # ── Links ──
        for ls in spec['links']:
            from_expr = ls['from']
            to_expr   = ls['to']

            # Source (output socket)
            if '.' not in from_expr:
                warnings.append(f"Link: bad source format '{from_expr}'")
                continue
            from_id, from_sock_name = from_expr.split('.', 1)
            from_node = node_map.get(from_id)
            if not from_node:
                warnings.append(f"Link: source node '{from_id}' not found")
                continue
            from_sock = _find_socket(from_node.outputs, from_sock_name)
            if not from_sock:
                warnings.append(f"Link: source '{from_expr}' socket not found")
                continue

            # Target (input socket)
            if '.' not in to_expr:
                warnings.append(f"Link: bad target format '{to_expr}'")
                continue
            to_id, to_sock_name = to_expr.split('.', 1)
            to_node = node_map.get(to_id)
            if not to_node:
                warnings.append(f"Link: target node '{to_id}' not found")
                continue
            to_sock = _find_socket(to_node.inputs, to_sock_name)
            if not to_sock:
                warnings.append(f"Link: target '{to_expr}' socket not found")
                continue

            links.new(from_sock, to_sock)

        # ── Modifier ──
        existing_mod = target_object.modifiers.get(modifier_name)
        if existing_mod:
            old_tree = existing_mod.node_group
            target_object.modifiers.remove(existing_mod)
            if old_tree and old_tree.users == 0:
                bpy.data.node_groups.remove(old_tree)

        mod = target_object.modifiers.new(name=modifier_name, type='NODES')
        mod.node_group = node_tree

        if warnings:
            return node_tree, "Built with warnings:\n" + "\n".join(warnings)
        return node_tree, None

    except Exception as e:
        try:
            bpy.data.node_groups.remove(node_tree)
        except Exception:
            pass
        return None, f"Build failed: {e}\n{traceback.format_exc()}"


# =============================================================================
# SERIALIZER (existing tree -> JSON for edit mode)
# =============================================================================

_SKIP_TYPES = {
    'NodeGroupInput', 'NodeGroupOutput', 'NodeReroute', 'NodeFrame',
    'NodeUndefined', 'GeometryNodeGroup', 'ShaderNodeGroup',
}


def serialize_geo_tree(node_tree):
    """Read an existing geo-node tree into a JSON-compatible dict."""
    spec = {
        'interface': {'inputs': [], 'outputs': []},
        'nodes': [],
        'links': [],
    }

    for item in node_tree.interface.items_tree:
        if hasattr(item, 'in_out'):
            entry = {'name': item.name, 'type': item.socket_type}
            if item.in_out == 'INPUT':
                spec['interface']['inputs'].append(entry)
            elif item.in_out == 'OUTPUT':
                spec['interface']['outputs'].append(entry)

    gi_node = go_node = None
    for node in node_tree.nodes:
        if node.bl_idname == 'NodeGroupInput':
            gi_node = node
            continue
        if node.bl_idname == 'NodeGroupOutput':
            go_node = node
            continue
        if node.bl_idname in _SKIP_TYPES:
            continue

        ns = {
            'id': node.name,
            'type': node.bl_idname,
            'location': [int(node.location.x), int(node.location.y)],
            'props': {},
            'inputs': {},
        }

        for prop_id in node.bl_rna.properties.keys():
            prop = node.bl_rna.properties[prop_id]
            if (prop.type == 'ENUM' and not prop.is_hidden and not prop.is_readonly
                    and prop_id not in ('bl_idname', 'bl_label', 'bl_icon',
                                        'type', 'bl_description', 'select')):
                try:
                    ns['props'][prop_id] = getattr(node, prop_id)
                except Exception:
                    pass

        for s in node.inputs:
            if s.is_linked or not hasattr(s, 'default_value'):
                continue
            if s.bl_idname == 'NodeSocketGeometry':
                continue
            try:
                val = s.default_value
                if hasattr(val, '__len__'):
                    val = list(val)
                ns['inputs'][s.name] = val
            except Exception:
                pass

        spec['nodes'].append(ns)

    def _node_id(node):
        if node == gi_node:
            return 'group_input'
        if node == go_node:
            return 'group_output'
        return node.name

    def _sock_ref(node, socket, direction):
        nid = _node_id(node)
        sockets = node.outputs if direction == 'out' else node.inputs
        same_name = [s for s in sockets if s.name == socket.name]
        if len(same_name) > 1:
            idx = same_name.index(socket)
            return f"{nid}.{socket.name}[{idx}]"
        return f"{nid}.{socket.name}"

    for link in node_tree.links:
        spec['links'].append({
            'from': _sock_ref(link.from_node, link.from_socket, 'out'),
            'to':   _sock_ref(link.to_node, link.to_socket, 'in'),
        })

    return spec


# =============================================================================
# NODE CLASS
# =============================================================================

class NeuroGeoNodesNode(NeuroNodeBase, Node):
    """AI Geometry Nodes - Generate node setups from text descriptions"""
    bl_idname  = 'NeuroGeoNodesNode'
    bl_label   = 'AI Geo Nodes'
    bl_icon    = 'GEOMETRY_NODES'
    bl_width_default = 300
    bl_width_min     = 250

    prompt: StringProperty(
        name="Request",
        description="Describe the geometry nodes setup you want",
        default="", maxlen=0
    )
    target_object: PointerProperty(
        name="Target", type=bpy.types.Object,
        description="Object to apply the geometry nodes modifier to",
        poll=lambda self, obj: obj.type == 'MESH'
    )
    instance_object: PointerProperty(
        name="Instance", type=bpy.types.Object,
        description="Object to use as instance (scattered copies, array element, etc.)"
    )
    modifier_name: StringProperty(
        name="Modifier Name", default="AI_GeoNodes",
        description="Name for the generated modifier"
    )
    auto_execute: BoolProperty(
        name="Auto Execute", default=True,
        description="Automatically build after generation"
    )
    auto_layout: BoolProperty(
        name="Auto Layout", default=True,
        description="Arrange nodes after generation"
    )
    max_retries: IntProperty(
        name="Retries", default=1, min=0, max=3,
        description="Retry on failure"
    )

    # State
    is_generating:     BoolProperty(default=False)
    status_message:    StringProperty(default="")
    generated_code:    StringProperty(default="")
    last_error:        StringProperty(default="")
    execution_success: BoolProperty(default=False)

    # UI
    show_code:     BoolProperty(name="Show JSON", default=False)
    show_settings: BoolProperty(name="Settings",  default=False)

    def init(self, context):
        self.inputs.new('NeuroTextSocket', "Code In")
        self.inputs.new('NeuroTextSocket', "Prompt In")
        self.outputs.new('NeuroTextSocket', "Code Out")

    def copy(self, node):
        self.is_generating  = False
        self.status_message = ""
        self.last_error     = ""

    def get_prompt_text(self):
        socket = self.inputs.get("Prompt In")
        if socket and socket.is_linked:
            try:
                from_node = socket.links[0].from_node
                if hasattr(from_node, 'text'):
                    return from_node.text
                if hasattr(from_node, 'result_text'):
                    return from_node.result_text
            except Exception:
                pass
        return self.prompt

    def get_input_code(self):
        socket = self.inputs.get("Code In")
        if socket and socket.is_linked:
            try:
                from_node = socket.links[0].from_node
                if hasattr(from_node, 'generated_code') and from_node.generated_code:
                    return from_node.generated_code
                if hasattr(from_node, 'text'):
                    return from_node.text
                if hasattr(from_node, 'result_text'):
                    return from_node.result_text
            except Exception:
                pass
        return ""

    def get_edit_json(self):
        input_json = self.get_input_code()
        if input_json:
            try:
                json.loads(input_json)
                return input_json
            except json.JSONDecodeError:
                pass

        if self.target_object:
            mod = self.target_object.modifiers.get(self.modifier_name)
            if mod and mod.node_group:
                try:
                    return json.dumps(serialize_geo_tree(mod.node_group), indent=2)
                except Exception:
                    pass
        return None

    def _has_edit_source(self):
        """Cheap check for edit mode — no serialization, just existence checks."""
        # Check input socket
        socket = self.inputs.get("Code In")
        if socket and socket.is_linked:
            return True
        # Check if target has our modifier with a node group
        if self.target_object:
            mod = self.target_object.modifiers.get(self.modifier_name)
            if mod and mod.node_group:
                return True
        return False

    def draw_buttons(self, context, layout):
        layout.prop(self, "target_object", text="Target")
        layout.prop(self, "instance_object", text="Instance")

        col = layout.column(align=True)
        col.prop(self, "prompt", text="")

        # Settings
        row = layout.row()
        row.prop(self, "show_settings",
                 icon='TRIA_DOWN' if self.show_settings else 'TRIA_RIGHT',
                 emboss=False)
        if self.show_settings:
            box = layout.box()
            box.prop(self, "modifier_name")
            box.prop(self, "max_retries")
            row = box.row(align=True)
            row.prop(self, "auto_execute")
            row.prop(self, "auto_layout")

        # Generate / Edit
        if self.is_generating:
            layout.label(text=self.status_message or "Generating...", icon='TIME')
            layout.operator("neuro.geonodes_cancel", text="Cancel", icon='X')
        else:
            row = layout.row(align=True)
            row.scale_y = 1.4
            # Cheap check: does input code or existing modifier exist?
            # Avoids full serialize_geo_tree() every frame
            has_edit = bool(self._has_edit_source())
            label = "Edit" if has_edit else "Generate"
            icon  = 'GREASEPENCIL' if has_edit else 'GEOMETRY_NODES'
            op = row.operator("neuro.geonodes_generate", text=label, icon=icon)
            op.node_name = self.name

            if self.generated_code and not self.auto_execute:
                op = row.operator("neuro.geonodes_execute", text="", icon='PLAY')
                op.node_name = self.name
                op.tree_name = self.id_data.name

        # Status
        if self.last_error:
            box = layout.box()
            box.alert = True
            err = self.last_error[:100] + "..." if len(self.last_error) > 100 else self.last_error
            box.label(text=err, icon='ERROR')
        elif self.execution_success:
            layout.label(text="Applied successfully", icon='CHECKMARK')

        # JSON preview
        if self.generated_code:
            row = layout.row()
            row.prop(self, "show_code",
                     icon='TRIA_DOWN' if self.show_code else 'TRIA_RIGHT',
                     emboss=False, text="Generated JSON")
            row.operator("neuro.geonodes_copy_code", text="", icon='COPYDOWN').node_name = self.name
            if self.show_code:
                box = layout.box()
                box.scale_y = 0.6
                lines = self.generated_code.split('\n')[:12]
                for line in lines:
                    if line.strip():
                        box.label(text=line[:70])
                if len(self.generated_code.split('\n')) > 12:
                    box.label(text="... (truncated)")

            col = layout.column()
            col.scale_y = 0.7
            col.label(text="Manual node changes will be overwritten", icon='INFO')

        if not self.generated_code:
            col = layout.column()
            col.scale_y = 0.7
            col.label(text="Uses latest Claude Opus", icon='LIGHT')

    def draw_label(self):
        if self.is_generating:
            return "Generating..."
        if self.target_object:
            return f"GeoNodes \u2192 {self.target_object.name}"
        return "AI Geo Nodes"


# =============================================================================
# OPERATORS
# =============================================================================

class NEURO_OT_geonodes_generate(Operator):
    """Generate geometry nodes from description"""
    bl_idname  = "neuro.geonodes_generate"
    bl_label   = "Generate Geo Nodes"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        try:
            from . import status_manager
            has_status_manager = True
        except ImportError:
            has_status_manager = False

        ntree = context.space_data.node_tree
        if not ntree:
            self.report({'ERROR'}, "No node tree")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node:
            self.report({'ERROR'}, "Node not found")
            return {'CANCELLED'}

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

        existing_json = node.get_edit_json()
        is_edit = bool(existing_json)

        # Build instance context for the prompt
        instance_context = ""
        instance_obj = node.instance_object
        if instance_obj:
            # Get bounding box dimensions for scale reference
            dims = instance_obj.dimensions
            dim_str = f"{dims.x:.3f} x {dims.y:.3f} x {dims.z:.3f}"
            instance_context = (
                f"\n\nINSTANCE OBJECT: '{instance_obj.name}' (dimensions: {dim_str} meters) is provided."
                f"\nYou MUST use a 'GeometryNodeObjectInfo' node with id 'instance_info' to bring it in."
                f"\nThe object reference is set automatically after build — leave the Object input empty."
                f"\nConnect instance_info.Geometry → InstanceOnPoints.Instance (or similar)."
                f"\nREMEMBER: InstanceOnPoints Scale is a MULTIPLIER. The instance is already {dim_str}m."
                f"\nFor variation, use scale values like [1.0, 1.0, 0.8] to [1.0, 1.0, 1.2], NOT absolute dimensions."
                f"\nDo NOT create replacement geometry — use this instance object."
            )

        from .model_registry import resolve_model
        model_id = resolve_model("text-claude-opus", context=context)

        from .utils import get_all_api_keys
        api_keys = get_all_api_keys(context)

        node.is_generating    = True
        node.status_message   = "Connecting..."
        node.last_error       = ""
        node.execution_success = False

        job_id = None
        if has_status_manager:
            job_id = status_manager.add_job(node.name, model_id, "GeoNodes")
            status_manager.start_job(job_id)

        msg_queue   = queue.Queue()
        max_retries = node.max_retries

        def run_generation():
            try:
                from .api import generate_text

                if is_edit:
                    full_prompt = (
                        GEONODES_SYSTEM_PROMPT + "\n\n" +
                        GEONODES_EDIT_PROMPT.format(
                            existing_json=existing_json,
                            user_request=prompt
                        ) + instance_context
                    )
                else:
                    full_prompt = (
                        GEONODES_SYSTEM_PROMPT +
                        f"\n\nCreate a Geometry Nodes setup: {prompt}"
                        + instance_context
                    )

                attempt = 0
                last_errors = []

                while attempt <= max_retries:
                    label = f"Retry {attempt}..." if attempt > 0 else "Generating..."
                    msg_queue.put(("STATUS", label))

                    result = generate_text(
                        prompt=full_prompt,
                        model_id=model_id,
                        api_keys=api_keys,
                        model_params={"max_tokens": 48000},
                        timeout=600,
                    )

                    if not result:
                        last_errors.append("Empty API response")
                        attempt += 1
                        continue

                    # Strip markdown fences
                    raw = result.strip()
                    raw = re.sub(r'^```(?:json)?\s*', '', raw)
                    raw = re.sub(r'\s*```$', '', raw)
                    raw = raw.strip()

                    # Parse
                    try:
                        spec = json.loads(raw)
                    except json.JSONDecodeError as e:
                        err = f"Invalid JSON: {e}"
                        last_errors.append(err)
                        if attempt < max_retries:
                            full_prompt = (
                                GEONODES_SYSTEM_PROMPT +
                                f"\n\nYour previous response had errors:\n{err}"
                                f"\n\nFix and return valid JSON for: {prompt}"
                            )
                            attempt += 1
                            continue
                        break

                    # Validate
                    msg_queue.put(("STATUS", "Validating..."))
                    val_errors = _validate_spec(spec)

                    if val_errors:
                        err = "\n".join(val_errors)
                        last_errors.append(err)
                        if attempt < max_retries:
                            full_prompt = (
                                GEONODES_SYSTEM_PROMPT +
                                f"\n\nYour JSON had errors:\n{err}"
                                f"\n\nFix them. Original request: {prompt}"
                                f"\n\nBroken JSON:\n{raw}"
                            )
                            attempt += 1
                            continue
                        break

                    # Success
                    msg_queue.put(("SUCCESS", json.dumps(spec, indent=2)))
                    return

                msg_queue.put(("ERROR", "Failed:\n" + "\n---\n".join(last_errors)))

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
                except queue.Empty:
                    break

                if msg[0] == "STATUS":
                    node.status_message = msg[1]

                elif msg[0] == "SUCCESS":
                    node.generated_code = msg[1]
                    node.is_generating  = False
                    node.status_message = ""
                    if has_status_manager and job_id:
                        status_manager.complete_job(job_id, success=True)
                    if node.auto_execute:
                        bpy.ops.neuro.geonodes_execute(
                            node_name=node.name, tree_name=ntree.name
                        )
                    return None

                elif msg[0] == "ERROR":
                    node.is_generating  = False
                    node.last_error     = msg[1]
                    node.status_message = ""
                    if has_status_manager and job_id:
                        status_manager.complete_job(job_id, success=False, error=msg[1])
                    return None

            if thread.is_alive():
                return 0.3
            return None

        bpy.app.timers.register(update_ui)
        return {'FINISHED'}


class NEURO_OT_geonodes_execute(Operator):
    """Build geometry node tree from JSON"""
    bl_idname  = "neuro.geonodes_execute"
    bl_label   = "Execute Geo Nodes Code"
    bl_options = {'REGISTER', 'UNDO'}

    node_name: StringProperty()
    tree_name: StringProperty()

    def execute(self, context):
        ntree = None
        if self.tree_name:
            ntree = bpy.data.node_groups.get(self.tree_name)
        if not ntree and context.space_data and hasattr(context.space_data, 'node_tree'):
            ntree = context.space_data.node_tree
        if not ntree:
            self.report({'ERROR'}, "Node tree not found")
            return {'CANCELLED'}

        node = ntree.nodes.get(self.node_name)
        if not node or not node.generated_code:
            self.report({'ERROR'}, "No JSON to build")
            return {'CANCELLED'}
        if not node.target_object:
            self.report({'ERROR'}, "No target object")
            return {'CANCELLED'}

        try:
            spec = json.loads(node.generated_code)
        except json.JSONDecodeError as e:
            node.execution_success = False
            node.last_error = f"Invalid JSON: {e}"
            self.report({'ERROR'}, node.last_error)
            return {'CANCELLED'}

        tree, error = build_geo_tree(spec, node.target_object, node.modifier_name)

        if tree is None:
            node.execution_success = False
            node.last_error = error or "Build failed"
            self.report({'ERROR'}, node.last_error[:200])
            return {'CANCELLED'}

        # Wire instance object into ObjectInfo nodes
        if node.instance_object and tree:
            for geo_node in tree.nodes:
                if geo_node.bl_idname == 'GeometryNodeObjectInfo':
                    obj_input = geo_node.inputs.get('Object')
                    if obj_input:
                        try:
                            obj_input.default_value = node.instance_object
                        except Exception as e:
                            print(f"[{LOG_PREFIX} GeoNodes] Failed to set instance object: {e}")

        node.execution_success = True
        if error:
            node.last_error = error
            self.report({'WARNING'}, error[:200])
        else:
            node.last_error = ""

        if node.auto_layout:
            self._layout_nodes(node.target_object, node.modifier_name)

        self.report({'INFO'}, f"Applied to {node.target_object.name}")
        return {'FINISHED'}

    def _layout_nodes(self, obj, modifier_name):
        try:
            mod = obj.modifiers.get(modifier_name)
            if not mod or not mod.node_group:
                return
            tree = mod.node_group

            def depth(n, visited=None):
                if visited is None:
                    visited = set()
                if n.name in visited:
                    return 0
                visited.add(n.name)
                d = -1
                for inp in n.inputs:
                    if inp.is_linked:
                        for lnk in inp.links:
                            d = max(d, depth(lnk.from_node, visited))
                return d + 1

            by_depth = {}
            for n in tree.nodes:
                d = depth(n)
                by_depth.setdefault(d, []).append(n)

            for d, group in by_depth.items():
                for i, n in enumerate(group):
                    n.location = (d * 250, -i * 150)
        except Exception as e:
            print(f"[{LOG_PREFIX} GeoNodes] Auto-layout failed: {e}")


class NEURO_OT_geonodes_cancel(Operator):
    """Cancel generation"""
    bl_idname  = "neuro.geonodes_cancel"
    bl_label   = "Cancel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        ntree = context.space_data.node_tree
        if ntree:
            for node in ntree.nodes:
                if node.bl_idname == 'NeuroGeoNodesNode' and node.is_generating:
                    node.is_generating  = False
                    node.status_message = "Cancelled"
        return {'FINISHED'}


class NEURO_OT_geonodes_copy_code(Operator):
    """Copy generated JSON to clipboard"""
    bl_idname  = "neuro.geonodes_copy_code"
    bl_label   = "Copy JSON"
    bl_options = {'INTERNAL'}

    node_name: StringProperty()

    def execute(self, context):
        ntree = context.space_data.node_tree
        if not ntree:
            return {'CANCELLED'}
        node = ntree.nodes.get(self.node_name)
        if node and node.generated_code:
            context.window_manager.clipboard = node.generated_code
            self.report({'INFO'}, "JSON copied to clipboard")
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