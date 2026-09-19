# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender <-> engine attribute-name/type constants shared across the
convert package (mask, face-set, color, edge-flag, UV, custom-normal, shape-
key and skin-layer keys; the AttrType/AttrUse/domain enum mirrors)."""


# Blender mask attribute (float, point domain) <-> the engine's mask column.
_BL_MASK = ".sculpt_mask"


_SC_MASK = b".spatial.v.mask"


# Blender face sets (int, face domain) <-> the engine's `group` face attr.
_BL_FACE_SET = ".sculpt_face_set"


_SC_GROUP = b"group"


# Blender edge flags <-> the engine's boundary bool edge attrs (P11). The
# engine derives its own edges, so both directions key edges by vertex pair,
# never by index (see _load_edge_flags/_flush_edge_flags).
_EDGE_FLAG_MAP = (
    ("uv_seam", b".boundary.edge.seam"),
    ("sharp_edge", b".boundary.edge.sharp"),
)


# Vertex colors <-> the engine's `color` float4 vertex attr. v1 handles the
# active color attribute when it is POINT-domain FLOAT_COLOR (the exact match);
# corner/byte colors are left untouched (a warning is logged on flush).
_SC_COLOR = b"color"



_DEFAULT_COLOR_NAME = "Color"


# MultiresModifier.uv_smooth -> the engine's UvSmooth (subdiv/grid_attrs.h),
# which mirrors DNA's eSubsurfUVSmooth. Named rather than positional: the RNA
# identifiers are stable where the enum's integer order is an implementation
# detail on the Blender side.
_UV_SMOOTH_TO_ENGINE = {
    'NONE': 0,
    'PRESERVE_CORNERS': 1,
    'PRESERVE_CORNERS_AND_JUNCTIONS': 2,
    'PRESERVE_CORNERS_JUNCTIONS_AND_CONCAVE': 3,
    'PRESERVE_BOUNDARIES': 4,
    'SMOOTH_ALL': 5,
}


# Blender attribute domain -> engine ElemType flag. Edge indices have no
# correspondence across the boundary (the engine derives its own edges), so
# EDGE-domain values are pair-matched by endpoints on both directions
# (Mesh_edgeVertsOut is the identity channel) instead of copied in order.
_DOMAIN_TO_ENGINE = {'POINT': 1, 'EDGE': 2, 'CORNER': 4, 'FACE': 16}


# Engine AttrType values (extern/sculptcore/source/mesh/attribute_enums.h).
_AT_FLOAT, _AT_FLOAT2, _AT_FLOAT3, _AT_FLOAT4 = 1, 2, 4, 8


_AT_BOOL, _AT_INT, _AT_INT2 = 16, 32, 64


# Engine AttrUse values (semantic tag; UV/COLOR keep a re-imported layer typed).
_USE_NONE, _USE_COLOR, _USE_UV = 0, 2, 4


# Blender data_type -> (engine AttrType, component count, numpy dtype, the
# `foreach_get`/`foreach_set` property on the layer's data). The engine type may
# be wider than the Blender one (a byte color rides the engine's FLOAT4); the
# Blender type is recreated exactly from the stored descriptor on read-back.
_ATTR_TYPE_MAP = {
    'FLOAT':        (_AT_FLOAT,  1, "float32", "value"),
    'FLOAT2':       (_AT_FLOAT2, 2, "float32", "vector"),
    'FLOAT_VECTOR': (_AT_FLOAT3, 3, "float32", "vector"),
    'FLOAT_COLOR':  (_AT_FLOAT4, 4, "float32", "color"),
    'BYTE_COLOR':   (_AT_FLOAT4, 4, "float32", "color"),
    'FLOAT4':       (_AT_FLOAT4, 4, "float32", "vector"),
    'INT':          (_AT_INT,    1, "int32",   "value"),
    'INT32_2D':     (_AT_INT2,   2, "int32",   "value"),
    'BOOLEAN':      (_AT_BOOL,   1, "uint8",   "value"),
    'QUATERNION':   (_AT_FLOAT4, 4, "float32", "value"),
}


# Never bridged: "position" (its own path), and every "."-prefixed layer —
# Blender's convention for internal/managed data (topology links `.corner_vert`,
# selections `.select_vert`, and the dedicated `.sculpt_mask`/`.sculpt_face_set`).
# User-created attributes never start with a dot. (The active color name is added
# dynamically in _load_bridged_attrs.)
_SKIP_ATTR_NAMES = {"position"}


# Dot-prefixed layers bridged despite the rule above: selection/hide state and
# the per-UV-map sublayers (vert select / edge select / pin) are user work
# state, not topology links, and losing them across a rebuild loses work the
# user cannot see being lost. The edge-domain pair rides the pair-matched edge
# bridge like any other edge attribute. The engine treats all of these as
# ordinary passenger layers — there is no hide concept engine-side, so hidden
# geometry stays sculptable during the session and comes back hidden but
# possibly modified.
_DOT_ATTR_EXCEPTIONS = {".select_vert", ".select_poly", ".select_edge",
                        ".hide_vert", ".hide_poly", ".hide_edge"}


_DOT_ATTR_PREFIXES = (".vs.", ".es.", ".pn.")


# Encoded custom normals (the corner-fan short2 form of `custom_normal`)
#
# The free (FLOAT_VECTOR) storage forms ride the generic bridge; the encoded
# INT16_2D corner form cannot — it is only meaningful relative to a smooth-fan
# structure a topology change destroys. So the bridge carries *directions*:
# decode on enter via Mesh.corner_normals (the resolved corner normals,
# whichever storage form the file used), store an engine corner FLOAT3 that
# dyntopo lerps like any direction field, and re-encode into the new fans on
# rebuild. Bit-exact round-tripping across a topology change is impossible in
# principle; a session that never rebuilds never re-encodes.
_SC_CUSTOM_NORMAL = b".blender.custom_normal"


_BL_CUSTOM_NORMAL = "custom_normal"


# Shape keys (1.4)
#
# Each non-basis key block is one engine FLOAT3 point column, index-keyed —
# a KeyBlock stores *absolute* coordinates (deltas against relative_key are
# taken at evaluation time), so the default midpoint merge a dyntopo collapse
# applies is exactly right, the same as for positions. The basis block is
# never bridged: sculpting edits the mesh positions, which *are* the basis
# (vanilla sculpt on the basis key behaves the same), so the basis simply
# follows the position flush. Block metadata (value, ranges, vgroup,
# relative_key, order) lives on the Key ID, which nothing in the rebuild
# touches once Mesh.set_topology keeps the blocks alive and sized.
_SC_KEY_PREFIX = ".blender.key."


# Skin-modifier vertices (CD_MVERT_SKIN)
#
# Not a generic attribute — `mesh.attributes` cannot see it — so it gets a
# dedicated pair of engine vertex columns: the two radii as a FLOAT2 (lerped
# by dyntopo like any float column) and the root/loose flags packed into an
# INT (integer default merge copies one side, which is right for flags).
# Without this every Skin-modifier asset loses all its radii on the first
# topology rebuild.
_SC_SKIN_RADIUS = b".blender.skin.radius"


_SC_SKIN_FLAGS = b".blender.skin.flags"


_SKIN_ROOT, _SKIN_LOOSE = 1, 2
