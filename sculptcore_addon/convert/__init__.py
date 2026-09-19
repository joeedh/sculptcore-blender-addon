# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Mesh <-> SculptCore conversion, split by concern:

- ``core`` -- the enter/flush/exit/refresh lifecycle (the public entry point).
- ``attrs`` -- face-set/color/edge-flag/UV + generic bridged-attribute bridging.
- ``vertex_data`` -- custom normals, shape keys, skin, vertex groups, mask.
- ``topology`` -- leaf-level position/topology array readback.
- ``multires_bridge`` -- the multires grids-provider cage/slot bridge.
- ``constants`` -- the Blender<->engine attribute-name/type constants.

Every name below is re-exported at the package level so ``convert.foo``
keeps working exactly as it did when this was a single flat module.
"""

from .constants import (
    _BL_MASK, _SC_MASK, _BL_FACE_SET, _SC_GROUP, _EDGE_FLAG_MAP, _SC_COLOR,
    _DEFAULT_COLOR_NAME, _UV_SMOOTH_TO_ENGINE, _DOMAIN_TO_ENGINE, _AT_FLOAT, _AT_FLOAT2,
    _AT_FLOAT3, _AT_FLOAT4, _AT_BOOL, _AT_INT, _AT_INT2, _USE_NONE, _USE_COLOR, _USE_UV,
    _ATTR_TYPE_MAP, _SKIP_ATTR_NAMES, _DOT_ATTR_EXCEPTIONS, _DOT_ATTR_PREFIXES,
    _SC_CUSTOM_NORMAL, _BL_CUSTOM_NORMAL, _SC_KEY_PREFIX, _SC_SKIN_RADIUS, _SC_SKIN_FLAGS,
    _SKIN_ROOT, _SKIN_LOOSE
)
from .topology import (
    _read_positions, _gather_arrays, _flush_positions_fast, _read_loose_edges,
    _mesh_counts, _mesh_vert_num, mesh_vert_num, mesh_face_num, mesh_corner_num,
    mesh_positions, mesh_topo_arrays
)
from .attrs import (
    _default_face_set, _load_face_sets, _flush_face_sets, _point_float_color, _load_color,
    _flush_color, _load_edge_flags, _pair_keys, _match_pairs, _engine_edge_pairs,
    _flush_edge_flags, _load_uv, _flush_uv, _attr_is_bridgeable_name, _bridge_use,
    _bridge_descriptor, _write_bridged_attr, _edge_flag_names, _load_bridged_attrs,
    _vert_carry_maps, _reconcile_bridged_attrs, _read_layer_designations,
    _restore_layer_designations, _flush_bridged_attrs
)
from .vertex_data import (
    _load_custom_normals, _flush_custom_normals, _sc_key_name, _shape_key_names,
    _write_key_column, _load_shape_keys, _reconcile_shape_keys, _flush_shape_keys,
    _flush_basis_key, _read_skin_arrays, _load_skin, _reconcile_skin, _flush_skin,
    _load_vertex_groups, _flush_vertex_groups, _load_mask, _flush_mask
)
from .multires_bridge import (
    _eval_multires_top, ensure_multires_slot, use_grids_provider, use_slot_provider,
    sync_grid_attr_settings, sync_cage_face_attrs, cage_face_group_bytes,
    restamp_cage_face_attrs, sync_cage_vert_color, cage_vert_color_bytes,
    restamp_cage_vert_color, sync_slot_mask, fold_slot_mask, _rebind_multires_views,
    multires_store_blob, multires_restore_blob, _multires_desync,
    sync_multires_total_levels, set_multires_level, _flush_multires
)
from .core import (
    ConvertError, validate, enter, _enter_multires, _seed_cage_material_index,
    _seed_cage_draw_attrs, _flush_topology_rebuild, flush, draw_refresh, exit_, refresh,
    resync_if_diverged
)

__all__ = (
    "_BL_MASK", "_SC_MASK", "_BL_FACE_SET", "_SC_GROUP", "_EDGE_FLAG_MAP", "_SC_COLOR",
    "_DEFAULT_COLOR_NAME", "_UV_SMOOTH_TO_ENGINE", "_DOMAIN_TO_ENGINE", "_AT_FLOAT", "_AT_FLOAT2",
    "_AT_FLOAT3", "_AT_FLOAT4", "_AT_BOOL", "_AT_INT", "_AT_INT2", "_USE_NONE", "_USE_COLOR",
    "_USE_UV", "_ATTR_TYPE_MAP", "_SKIP_ATTR_NAMES", "_DOT_ATTR_EXCEPTIONS", "_DOT_ATTR_PREFIXES",
    "_SC_CUSTOM_NORMAL", "_BL_CUSTOM_NORMAL", "_SC_KEY_PREFIX", "_SC_SKIN_RADIUS",
    "_SC_SKIN_FLAGS", "_SKIN_ROOT", "_SKIN_LOOSE",
    "_read_positions", "_gather_arrays", "_flush_positions_fast", "_read_loose_edges",
    "_mesh_counts", "_mesh_vert_num", "mesh_vert_num", "mesh_face_num", "mesh_corner_num",
    "mesh_positions", "mesh_topo_arrays",
    "_default_face_set", "_load_face_sets", "_flush_face_sets", "_point_float_color",
    "_load_color", "_flush_color", "_load_edge_flags", "_pair_keys", "_match_pairs",
    "_engine_edge_pairs", "_flush_edge_flags", "_load_uv", "_flush_uv",
    "_attr_is_bridgeable_name", "_bridge_use", "_bridge_descriptor", "_write_bridged_attr",
    "_edge_flag_names", "_load_bridged_attrs", "_vert_carry_maps", "_reconcile_bridged_attrs",
    "_read_layer_designations", "_restore_layer_designations", "_flush_bridged_attrs",
    "_load_custom_normals", "_flush_custom_normals", "_sc_key_name", "_shape_key_names",
    "_write_key_column", "_load_shape_keys", "_reconcile_shape_keys", "_flush_shape_keys",
    "_flush_basis_key", "_read_skin_arrays", "_load_skin", "_reconcile_skin", "_flush_skin",
    "_load_vertex_groups", "_flush_vertex_groups", "_load_mask", "_flush_mask",
    "_eval_multires_top", "ensure_multires_slot", "use_grids_provider", "use_slot_provider",
    "sync_grid_attr_settings", "sync_cage_face_attrs", "cage_face_group_bytes",
    "restamp_cage_face_attrs", "sync_cage_vert_color", "cage_vert_color_bytes",
    "restamp_cage_vert_color", "sync_slot_mask", "fold_slot_mask", "_rebind_multires_views",
    "multires_store_blob", "multires_restore_blob", "_multires_desync",
    "sync_multires_total_levels", "set_multires_level", "_flush_multires",
    "ConvertError", "validate", "enter", "_enter_multires", "_seed_cage_material_index",
    "_seed_cage_draw_attrs", "_flush_topology_rebuild", "flush", "draw_refresh", "exit_",
    "refresh", "resync_if_diverged",
)

