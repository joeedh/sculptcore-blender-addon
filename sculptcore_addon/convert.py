# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Mesh <-> SculptCore conversion (positions-only slice).

The invariant everything else relies on: the Blender Mesh ID is the
persistent store — ``flush()`` makes it match the engine's state on demand
(called by Blender before memfile undo encode, file save and render, via the
mode's ``flush`` callback). Engine-side state that has no Mesh
representation (the spatial tree) is rebuilt on ``refresh``/re-enter, never
serialized.

v1 layer policy (attributes beyond positions) lands with the mask/face-set/
color/UV copy stage; until then non-position data is untouched in the Mesh
and stays valid because topology ops are not yet reachable.
"""

from . import engine, multires
from .session import Session

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


class ConvertError(RuntimeError):
    pass


def _read_positions(mesh, out):
    """Bulk-read vertex positions into `out` (a `verts_num * 3` float32 array).
    The `position` attribute is a contiguous float3 array, so `foreach_get` on
    it is an order of magnitude faster than the `vertices.co` collection
    accessor at scale (~40 ms -> ~3 ms at 1M verts)."""
    attr = mesh.attributes.get("position")
    if attr is not None and attr.data_type == 'FLOAT_VECTOR':
        attr.data.foreach_get("vector", out)
    else:
        mesh.vertices.foreach_get("co", out)


def _gather_arrays(mesh):
    """The Mesh ID's topology in Blender's native flat layout."""
    import numpy as np

    verts_num = len(mesh.vertices)
    corners_num = len(mesh.loops)
    faces_num = len(mesh.polygons)

    positions = np.empty(verts_num * 3, dtype=np.float32)
    _read_positions(mesh, positions)

    # The `.corner_vert` builtin attribute is a contiguous int array; reading it
    # is ~2x faster than `loops.vertex_index`. Fall back for meshes that predate
    # it.
    corner_verts = np.empty(corners_num, dtype=np.int32)
    cv_attr = mesh.attributes.get(".corner_vert")
    if cv_attr is not None and cv_attr.data_type == 'INT':
        cv_attr.data.foreach_get("value", corner_verts)
    else:
        mesh.loops.foreach_get("vertex_index", corner_verts)

    face_offsets = np.empty(faces_num + 1, dtype=np.int32)
    if faces_num:
        mesh.polygons.foreach_get("loop_start", face_offsets[:faces_num])
    face_offsets[faces_num] = corners_num

    return positions, corner_verts, face_offsets


def validate(ob, ignore_multires=False):
    """v1 entry rules (sculpt-modifier-coupling research): shape keys are
    carried as passengers when the fork's Mesh.set_topology exists (it keeps
    the key blocks sized to the vertex count — without it, a topology rebuild
    on a keyed mesh is a release-build buffer overrun in
    BKE_keyblock_update_from_mesh, so the refusal stands). Sculpting writes
    the basis, so entry requires the basis key active. Warn-and-proceed on
    enabled modifiers and loose edges. Multires sessions pass
    ``ignore_multires`` — their modifier is supported (converted, not
    ignored), so it is excluded from the enabled-modifier warning."""
    mesh = ob.data
    if mesh.shape_keys is not None:
        if ignore_multires:
            raise ConvertError(
                "SculptCore: cannot enter on {!r} — shape keys plus multires "
                "are not supported together".format(ob.name))
        if not hasattr(mesh, "set_topology"):
            raise ConvertError(
                "SculptCore: cannot enter on {!r} — shape keys need a Blender "
                "with Mesh.set_topology (topology changes would corrupt the "
                "key blocks)".format(ob.name))
        if not mesh.shape_keys.use_relative:
            raise ConvertError(
                "SculptCore: cannot enter on {!r} — absolute shape keys are "
                "not supported".format(ob.name))
        if ob.active_shape_key_index != 0:
            raise ConvertError(
                "SculptCore: cannot enter on {!r} — make the Basis shape key "
                "active first (sculpting edits the basis; other keys ride "
                "along)".format(ob.name))

    warnings = []
    if any(md.show_viewport for md in ob.modifiers
           if not (ignore_multires and md.type == 'MULTIRES')):
        warnings.append("enabled modifiers are ignored while sculpting")
    if any(edge.is_loose for edge in mesh.edges):
        warnings.append("loose edges will not survive topology-changing sculpting")
    for message in warnings:
        print("SculptCore: warning: {:s} ({:s})".format(message, ob.name))


def enter(ob):
    """Build the engine mesh + spatial tree from the Mesh ID and register
    the session. Objects with a multires modifier take the P8 stack path;
    everything else converts the plain Mesh."""
    md = multires.modifier(ob)
    if md is not None and md.total_levels >= 1:
        return _enter_multires(ob, md)
    validate(ob)
    capi = engine.capi()

    positions, corner_verts, face_offsets = _gather_arrays(ob.data)
    verts_num = len(positions) // 3

    mesh_ptr = capi.lib.Mesh_fromArrays(
        positions, verts_num,
        corner_verts, len(corner_verts),
        face_offsets, len(face_offsets) - 1,
    )
    if not mesh_ptr:
        raise ConvertError("SculptCore: engine rejected mesh {!r}".format(ob.data.name))

    tree_ptr = capi.lib.Mesh_buildSpatialTree(mesh_ptr, 0, 0, 0)
    if not tree_ptr:
        capi.lib.freeMesh(mesh_ptr)
        raise ConvertError("SculptCore: spatial tree build failed for {!r}".format(ob.data.name))

    _load_mask(ob.data, mesh_ptr, verts_num)
    _load_face_sets(ob.data, mesh_ptr)
    _load_color(ob.data, mesh_ptr, verts_num)
    has_uv = _load_uv(ob.data, mesh_ptr)
    _load_edge_flags(ob.data, mesh_ptr, recompute=has_uv)

    session = Session(ob.name, mesh_ptr, tree_ptr, verts_num)
    engine.sessions[ob.name] = session

    # Engine vertex indices equal Blender indices at enter (Mesh_fromArrays
    # creates verts in order); rebuilt after every topology flush. The maps
    # carry host-only per-vertex state (loose edges, mid-session layers)
    # across rebuilds.
    import numpy as np
    session.vert_map_prev = np.arange(verts_num, dtype=np.int32)

    # Seed the remaining user attribute layers so they ride the engine through
    # dyntopo + undo and can be rebuilt after a topology change.
    _load_bridged_attrs(ob.data, mesh_ptr, session)
    _load_vertex_groups(ob, mesh_ptr)
    _load_skin(ob.data, mesh_ptr, verts_num)
    _load_custom_normals(ob.data, mesh_ptr, session)
    _load_shape_keys(ob.data, mesh_ptr, session)

    # Register the tree for external-provider viewport draw, keyed by the
    # object's session_uid (the key Blender's draw path passes). Switch it to the
    # dynamic per-attribute layout (color@0, uv@1) so the provider exposes them,
    # then fill the GPU-node buffers once so the initial geometry draws.
    session.draw_key = int(ob.session_uid)
    lib = engine.capi().lib
    lib.sc_external_draw_register(session.draw_key, tree_ptr)
    lib.sc_external_draw_enable_dynamic(tree_ptr)
    lib.sc_external_draw_set_default_group(tree_ptr, _default_face_set(ob.data))
    lib.sc_external_draw_update(session.draw_key)

    return session


def _eval_multires_top(ob, md, level):
    """Blender's displaced top-level surface in subdiv-vertex order, plus the
    depsgraph it was read through. `md.levels`/`md.sculpt_levels` are restored,
    but the modifier's viewport display is left ON for the caller to deal with:
    enter has to remember the pre-mode value before suppressing it, a
    mid-session restack only has to suppress it again.

    Both level properties are pinned because the modifier evaluates at whichever
    one `multires_get_level()` picks, and this mode is one of the sculpt-paint
    custom modes it answers with `sculptlvl` for (the same branch vanilla sculpt
    mode takes)."""
    import bpy
    import numpy as np

    prev_levels = md.levels
    prev_sculpt_levels = md.sculpt_levels
    md.show_viewport = True
    md.levels = level
    md.sculpt_levels = level
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    eval_mesh = ob.evaluated_get(depsgraph).data
    top = np.empty(len(eval_mesh.vertices) * 3, dtype=np.float64)
    eval_mesh.vertices.foreach_get("co", top)
    md.levels = prev_levels
    md.sculpt_levels = prev_sculpt_levels
    return top.reshape(-1, 3), depsgraph


def _enter_multires(ob, md):
    """Multires enter (P8): build an engine Multires stack over the base cage,
    import the object's displaced top-level surface (CD_MDISPS via the
    evaluated modifier), and register the stack's top-level tree for draw. The
    modifier's viewport display is suppressed while the mode is active — the
    provider draws the engine surface — and restored on exit. The mask is
    exchanged per grid element (the one layer Blender persists there); UV,
    color and face sets are seeded on the cage and subdivided from it."""
    import ctypes

    import bpy
    import numpy as np

    validate(ob, ignore_multires=True)
    lib = engine.capi().lib
    context = bpy.context
    level = md.total_levels

    base_arrays = _gather_arrays(ob.data)

    prev_show = md.show_viewport
    top, depsgraph = _eval_multires_top(ob, md, level)
    md.show_viewport = False

    mr = cage = None
    try:
        mr, cage = multires.build_engine(base_arrays, level)
        mr_map = multires.build_map(ob, depsgraph, mr, level, len(top))
        multires.import_displacement(mr, mr_map, top)
    except Exception:
        if mr:
            lib.Multires_free(mr)
        if cage:
            lib.freeMesh(cage)
        md.show_viewport = prev_show
        raise

    # Per-node draw materials: the grids source stamps node materials from the
    # cage's FACE material_index at registration (use_grids_provider below),
    # and the cage is built from bare arrays with no attribute bridge — seed
    # it explicitly first.
    _seed_cage_material_index(ob.data, cage)

    # UV / color / face sets reach the viewport by being subdivided from the
    # cage onto the grid samples, so the cage must carry them too. Blender can
    # persist exactly one per-grid-element layer of its own (the scalar paint
    # mask); everything else is derived, which is what the declaration says.
    # (The two settings those layers are keyed on go in below, once there is a
    # session to cache them on — sync_grid_attr_settings.)
    _seed_cage_draw_attrs(ob.data, cage)
    lib.Multires_declareHostGridAttr(mr, _SC_MASK, _AT_FLOAT)

    # Lazy slot (extdraw v2 end state): nothing materializes at enter — the
    # grids provider draws the domain, grids strokes edit the chain in place,
    # and the level mesh + tree build on first mesh-path need
    # (ensure_multires_slot). The chain-only seed left nothing resident.
    lib.Multires_setActiveLevelLazy(mr, level)
    mesh_ptr = 0
    tree_ptr = 0

    # Mask (A4): seed the engine mask from the grid paint mask — straight
    # into the grid domain + store (no slot column yet). The exchange
    # follows the active level (see set_multires_level).
    depsgraph = context.evaluated_depsgraph_get()
    mask_base = multires.import_mask(ob, depsgraph, mesh_ptr, mr_map, mr, level)

    session = Session(ob.name, mesh_ptr, tree_ptr,
                      lib.Multires_levelVertCount(mr, level))
    session.multires_mask_base = mask_base
    session.blender_verts_num = len(ob.data.vertices)
    session.multires_ptr = mr
    session.cage_ptr = cage
    session.multires_map = mr_map
    session.multires_level = level
    session.multires_active_level = level
    session.multires_show_viewport = prev_show
    # The domain-direct mask import (above) already synced domain + store.
    session.grid_mask_dirty = False
    engine.sessions[ob.name] = session
    sync_grid_attr_settings(ob, session)

    session.draw_key = int(ob.session_uid)
    # Multires draws from the grids source (extdraw v2): geometry/mask come
    # straight from the level's grid domain — the slot tree never builds its
    # GPU buffers unless a mesh-path tool flips the provider (below).
    use_grids_provider(session)

    # Honor the modifier's sculpt level (C2); the import left the top active.
    sculpt_level = min(max(md.sculpt_levels, 1), level)
    if sculpt_level != level:
        set_multires_level(ob, sculpt_level)

    # The imported state is the first undo push's pre-state (C4).
    session.multires_last_blob = multires_store_blob(session)
    return session


def _seed_cage_material_index(mesh, cage_ptr):
    """Copy the Blender mesh's FACE ``material_index`` layer onto the engine
    cage mesh (same face order — the cage is built from the base arrays).
    No-op when absent (single-material objects usually carry no layer)."""
    import ctypes

    import numpy as np

    attr = mesh.attributes.get("material_index")
    if attr is None or attr.domain != 'FACE' or attr.data_type != 'INT':
        return
    values = np.empty(len(attr.data), dtype=np.int32)
    attr.data.foreach_get("value", values)
    engine.capi().lib.Mesh_writeAttr(
        cage_ptr, _DOMAIN_TO_ENGINE['FACE'], b"material_index", _AT_INT,
        _USE_NONE, values.ctypes.data_as(ctypes.c_void_p))


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


def _seed_cage_draw_attrs(mesh, cage_ptr):
    """Copy the Blender mesh's UV map, vertex colors and face sets onto the
    engine multires cage. The grids draw path has no slot mesh to read them
    from: it subdivides these cage layers onto the grid samples itself (engine
    ``subdiv/grid_attrs.h``), so a layer missing here is a layer the viewport
    draws with its default (white / zero UV / untinted)."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib

    uv_layer = mesh.uv_layers.active
    if uv_layer is not None:
        values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
        uv_attr = mesh.attributes.get(uv_layer.name)
        if uv_attr is not None and uv_attr.domain == 'CORNER' and uv_attr.data_type == 'FLOAT2':
            uv_attr.data.foreach_get("vector", values)
        else:
            uv_layer.data.foreach_get("uv", values)
        # AttrUse UV is what marks this the *UV map* among corner float2 layers,
        # and the engine picks the face-varying subdivision rule off that tag.
        lib.Mesh_writeAttr(cage_ptr, _DOMAIN_TO_ENGINE['CORNER'], b"uv", _AT_FLOAT2,
                           _USE_UV, values.ctypes.data_as(ctypes.c_void_p))

    color_attr = _point_float_color(mesh)
    if color_attr is not None:
        values = np.empty(len(mesh.vertices) * 4, dtype=np.float32)
        color_attr.data.foreach_get("color", values)
        lib.Mesh_writeAttr(cage_ptr, _DOMAIN_TO_ENGINE['POINT'], _SC_COLOR, _AT_FLOAT4,
                           _USE_COLOR, values.ctypes.data_as(ctypes.c_void_p))

    fs_attr = mesh.attributes.get(_BL_FACE_SET)
    if fs_attr is not None and fs_attr.domain == 'FACE' and fs_attr.data_type == 'INT':
        values = np.empty(len(mesh.polygons), dtype=np.int32)
        fs_attr.data.foreach_get("value", values)
        lib.Mesh_writeAttr(cage_ptr, _DOMAIN_TO_ENGINE['FACE'], _SC_GROUP, _AT_INT,
                           _USE_NONE, values.ctypes.data_as(ctypes.c_void_p))


def _default_face_set(mesh):
    """Blender's invisible/default face-set id (Mesh.face_sets_color_default,
    fork RNA; usually 1) — the engine must leave that group untinted in its
    fset overlay stream, where its own "no group" is 0."""
    return int(getattr(mesh, "face_sets_color_default", 1))


def _load_face_sets(mesh, mesh_ptr):
    """Seed the engine `group` face attr from the Blender `.sculpt_face_set`
    attribute (int, face). No-op when the mesh carries no face sets."""
    import numpy as np

    attr = mesh.attributes.get(_BL_FACE_SET)
    if attr is None or attr.domain != 'FACE' or attr.data_type != 'INT':
        return
    values = np.empty(len(mesh.polygons), dtype=np.int32)
    attr.data.foreach_get("value", values)
    engine.capi().lib.Mesh_writeFaceIntAttr(mesh_ptr, _SC_GROUP, values)


def _flush_face_sets(mesh, mesh_ptr):
    """Write the engine `group` face attr back into `.sculpt_face_set`,
    creating it on first use. No-op when the engine has no face groups."""
    import numpy as np

    values = np.empty(len(mesh.polygons), dtype=np.int32)
    if not engine.capi().lib.Mesh_readFaceIntAttr(mesh_ptr, _SC_GROUP, values):
        return
    attr = mesh.attributes.get(_BL_FACE_SET)
    if attr is None:
        attr = mesh.attributes.new(_BL_FACE_SET, 'INT', 'FACE')
    attr.data.foreach_set("value", values)


def _point_float_color(mesh):
    """The active color attribute if it is the POINT/FLOAT_COLOR match the
    engine's `color` float4 vertex attr expects, else None."""
    attr = mesh.color_attributes.active_color
    if attr is not None and attr.domain == 'POINT' and attr.data_type == 'FLOAT_COLOR':
        return attr
    return None


def _load_color(mesh, mesh_ptr, verts_num):
    """Seed the engine `color` attr from the active POINT/FLOAT_COLOR color
    attribute. No-op when there is none of that kind."""
    import numpy as np

    attr = _point_float_color(mesh)
    if attr is None:
        return
    values = np.empty(verts_num * 4, dtype=np.float32)
    attr.data.foreach_get("color", values)
    engine.capi().lib.Mesh_writeVertFloat4Attr(mesh_ptr, _SC_COLOR, values)


def _flush_color(mesh, mesh_ptr, verts_num, color_name=None):
    """Write the engine `color` attr back into the POINT/FLOAT_COLOR color
    attribute it mirrors: the layer recorded at enter (`color_name`), created
    when missing — a rebuild recreating layers may have auto-assigned the
    active designation to an unrelated color layer, so the name wins over the
    active designation. Leaves corner/byte color attributes untouched (logs a
    warning)."""
    import numpy as np

    values = np.empty(verts_num * 4, dtype=np.float32)
    if not engine.capi().lib.Mesh_readVertFloat4Attr(mesh_ptr, _SC_COLOR, values):
        return
    attr = None
    if color_name:
        cand = mesh.color_attributes.get(color_name)
        if cand is None:
            # The rebuild dropped it (or the user deleted it); recreate under
            # its own name. Falling back to the *active* layer here would
            # clobber whichever unrelated color layer attributes.new
            # auto-assigned during the rebuild.
            attr = mesh.color_attributes.new(color_name, 'FLOAT_COLOR', 'POINT')
            if mesh.color_attributes.active_color is None:
                mesh.color_attributes.active_color = attr
        elif cand.domain == 'POINT' and cand.data_type == 'FLOAT_COLOR':
            attr = cand
        else:
            print("SculptCore: color attribute {!r} is no longer "
                  "POINT/FLOAT_COLOR; painted colors not written back".format(color_name))
            return
    if attr is None:
        attr = _point_float_color(mesh)
    if attr is None:
        if mesh.color_attributes.active_color is not None:
            print("SculptCore: active color attribute is not POINT/FLOAT_COLOR; "
                  "painted colors not written back")
            return
        attr = mesh.color_attributes.new(_DEFAULT_COLOR_NAME, 'FLOAT_COLOR', 'POINT')
        mesh.color_attributes.active_color = attr
    attr.data.foreach_set("color", values)


def _load_edge_flags(mesh, mesh_ptr, recompute=False):
    """Seed the engine boundary edge flags (seam/sharp) from the Blender edge
    bool attributes. Engine vertex indices equal Blender indices at enter
    (Mesh_fromArrays creates verts in order), so edges are keyed by their
    vertex pair. Recomputes the boundary classification when anything was
    seeded — or when the caller passes ``recompute`` (UVs were seeded, which
    marks the whole mesh boundary-dirty) — so BSMOOTH/dyntopo see the seam/
    sharp features *and* the derived UV-chart boundaries from the first
    stroke."""
    import numpy as np

    lib = engine.capi().lib
    edges_num = len(mesh.edges)
    if not edges_num:
        return
    edge_verts = None
    seeded = recompute
    for bl_name, sc_name in _EDGE_FLAG_MAP:
        attr = mesh.attributes.get(bl_name)
        if attr is None or attr.domain != 'EDGE' or attr.data_type != 'BOOLEAN':
            continue
        values = np.empty(edges_num, dtype=np.uint8)
        attr.data.foreach_get("value", values.view(np.bool_))
        if not values.any():
            continue
        if edge_verts is None:
            edge_verts = np.empty(edges_num * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", edge_verts)
        lib.Mesh_writeEdgeFlagsByVerts(mesh_ptr, sc_name, edge_verts, values, edges_num)
        seeded = True
    if seeded:
        lib.Mesh_recomputeBoundary(mesh_ptr)


def _pair_keys(pairs):
    """Sorted vertex pairs packed into int64 keys (order-independent)."""
    import numpy as np

    lo = np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    hi = np.maximum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    return (lo << 32) | hi


def _match_pairs(dst_pairs, src_pairs):
    """For each dst vertex pair, the index of the matching src pair (-1 when
    unmatched). Both arrays are (n, 2); matching is endpoint-order-agnostic."""
    import numpy as np

    if not len(src_pairs) or not len(dst_pairs):
        return np.full(len(dst_pairs), -1, dtype=np.int64)
    src_keys = _pair_keys(src_pairs)
    order = np.argsort(src_keys)
    sorted_keys = src_keys[order]
    dst_keys = _pair_keys(dst_pairs)
    idx = np.searchsorted(sorted_keys, dst_keys)
    idx[idx >= len(sorted_keys)] = len(sorted_keys) - 1
    return np.where(sorted_keys[idx] == dst_keys, order[idx], -1)


def _engine_edge_pairs(mesh_ptr):
    """Every live engine edge's vertex pair, live-iteration order — the order
    the EDGE-domain attribute c-api reads and writes."""
    import numpy as np

    lib = engine.capi().lib
    count = lib.Mesh_edgeCount(mesh_ptr)
    pairs = np.empty(max(count, 1) * 2, dtype=np.int32)
    lib.Mesh_edgeVertsOut(mesh_ptr, pairs)
    return pairs[:count * 2].reshape(-1, 2)


def _flush_edge_flags(session, mesh, vert_map):
    """Recreate the Blender seam/sharp edge attributes from the engine
    boundary flags after a topology rebuild (`calc_edges=True` regenerated the
    edges with all flags dropped). `vert_map` maps engine vertex index ->
    rebuilt Blender index (Mesh_toArrays). Engine edges are matched to Blender
    edges by sorted vertex pair; flags whose edge no longer exists are
    silently dropped (dyntopo may have collapsed it)."""
    import numpy as np

    lib = engine.capi().lib
    edges_num = len(mesh.edges)
    engine_edges = lib.Mesh_edgeCount(session.mesh_ptr)
    if not edges_num or not engine_edges:
        return

    bl_order = bl_keys = None
    buf = np.empty(engine_edges * 2, dtype=np.int32)
    for bl_name, sc_name in _EDGE_FLAG_MAP:
        count = lib.Mesh_readEdgeFlags(session.mesh_ptr, sc_name, buf, engine_edges)
        if count <= 0:
            continue
        if bl_keys is None:
            bl_edge_verts = np.empty(edges_num * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", bl_edge_verts)
            keys = _pair_keys(bl_edge_verts.reshape(-1, 2))
            bl_order = np.argsort(keys)
            bl_keys = keys[bl_order]
        pairs = vert_map[buf[:count * 2].reshape(-1, 2)]
        keys = _pair_keys(pairs[np.all(pairs >= 0, axis=1)])
        idx = np.searchsorted(bl_keys, keys)
        idx[idx >= edges_num] = edges_num - 1
        matched = bl_order[idx[bl_keys[idx] == keys]]
        if not len(matched):
            continue
        values = np.zeros(edges_num, dtype=np.bool_)
        values[matched] = True
        attr = mesh.attributes.get(bl_name)
        if attr is None:
            attr = mesh.attributes.new(bl_name, 'BOOLEAN', 'EDGE')
        attr.data.foreach_set("value", values)


def _load_uv(mesh, mesh_ptr):
    """Seed the engine `uv` corner attribute from the active UV map (per-loop
    float2, loop order = the engine's corner order). Returns True when UVs
    were seeded (the engine marks the mesh boundary-dirty so the derived
    UV-chart edge flags can be recomputed). No-op with no UV map."""
    import numpy as np

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return False
    values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    # A UV map is a CORNER-domain FLOAT2 attribute; reading it through the
    # attribute API is a contiguous memcpy, ~300x faster than the per-element
    # `uv_layers.active.data.uv` accessor (~870 ms -> ~3 ms at 4M corners).
    uv_attr = mesh.attributes.get(uv_layer.name)
    if uv_attr is not None and uv_attr.domain == 'CORNER' and uv_attr.data_type == 'FLOAT2':
        uv_attr.data.foreach_get("vector", values)
    else:
        uv_layer.data.foreach_get("uv", values)
    engine.capi().lib.Mesh_writeCornerFloat2Attr(mesh_ptr, b"uv", values)
    return True


def _flush_uv(mesh, mesh_ptr):
    """Write the engine `uv` corner attr back into the active UV map, creating
    one when the mesh has none. Only called when the engine UVs diverged from
    the Mesh (session.uv_dirty — the UV-project operator / UV reprojection);
    regular strokes never touch UVs, so the default flush skips this."""
    import ctypes

    import numpy as np

    values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    # Engine domain CORNER (4) / AttrType FLOAT2 (2); see _DOMAIN_TO_ENGINE.
    if not engine.capi().lib.Mesh_readAttr(mesh_ptr, 4, b"uv", 2,
                                           values.ctypes.data_as(ctypes.c_void_p)):
        return
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        if uv_layer is None:
            return
    uv_attr = mesh.attributes.get(uv_layer.name)
    if uv_attr is not None and uv_attr.domain == 'CORNER' and uv_attr.data_type == 'FLOAT2':
        uv_attr.data.foreach_set("vector", values)
    else:
        uv_layer.data.foreach_set("uv", values)


# Generic user-attribute bridge
#
# User attribute layers (extra UV maps, color layers, custom vertex/face
# attributes, material indices, ...) are seeded into the engine on enter, so
# dyntopo interpolates them onto new geometry and the meshlog reverts them on
# undo. The topology-rebuild path drops all Blender customdata (clear_geometry),
# so these layers are recreated from the engine afterwards. Positions, topology
# builtins, and the dedicated brush-target layers (mask/face-set/active color)
# have their own paths and are skipped here.

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


def _attr_is_bridgeable_name(name):
    """False for names the bridge never touches: "position" and dot-prefixed
    internal layers, minus the explicit work-state exceptions."""
    if name in _SKIP_ATTR_NAMES:
        return False
    if not name.startswith("."):
        return True
    return name in _DOT_ATTR_EXCEPTIONS or name.startswith(_DOT_ATTR_PREFIXES)


def _bridge_use(mesh, name, data_type, domain, engine_type):
    """The engine AttrUse tag for a bridged layer, so a re-imported UV map or
    color layer keeps its semantic type. Only a layer `uv_layers` actually
    lists is a UV map — an arbitrary corner float2 (a flow field, a packed
    pair) must not inherit UV semantics (wedge blending, seam handling)."""
    if data_type in {'FLOAT_COLOR', 'BYTE_COLOR'}:
        return _USE_COLOR
    if (engine_type == _AT_FLOAT2 and domain == 'CORNER'
            and mesh.uv_layers.get(name) is not None):
        return _USE_UV
    return _USE_NONE


def _bridge_descriptor(mesh, attr):
    """The bridge descriptor for a Blender attribute layer, or None (logged)
    when its domain or type has no engine mapping. Name-based skips are the
    caller's business (they differ between enter and reconcile)."""
    engine_domain = _DOMAIN_TO_ENGINE.get(attr.domain)
    mapping = _ATTR_TYPE_MAP.get(attr.data_type)
    if engine_domain is None or mapping is None:
        print("SculptCore: attribute {!r} ({:s}/{:s}) is unsupported and "
              "will be dropped on topology change".format(
                  attr.name, attr.domain, attr.data_type))
        return None
    engine_type, ncomp, dtype, prop = mapping
    return {
        "name": attr.name,
        "name_bytes": attr.name.encode("utf-8"),
        "bl_domain": attr.domain,
        "bl_type": attr.data_type,
        "engine_domain": engine_domain,
        "engine_type": engine_type,
        "ncomp": ncomp,
        "dtype": dtype,
        "prop": prop,
        "use": _bridge_use(mesh, attr.name, attr.data_type, attr.domain, engine_type),
    }


def _write_bridged_attr(mesh_ptr, desc, values):
    """Write a bridged layer's values (live-iteration order) into the engine
    under its descriptor's name/type/use."""
    import ctypes

    engine.capi().lib.Mesh_writeAttr(
        mesh_ptr, desc["engine_domain"], desc["name_bytes"], desc["engine_type"],
        desc["use"], values.ctypes.data_as(ctypes.c_void_p))


def _edge_flag_names():
    return {bl_name for bl_name, _ in _EDGE_FLAG_MAP}


def _load_bridged_attrs(mesh, mesh_ptr, session):
    """Seed every user attribute layer into the engine and record a descriptor
    so :func:`_flush_bridged_attrs` can recreate it after a topology rebuild.
    Skips positions/topology builtins, the dedicated mask/face-set/color and
    seam/sharp layers, and unsupported Blender types (logged). EDGE-domain
    values are reordered into engine edge order by endpoint matching (engine
    vertex indices equal Blender's at enter); the engine's edges are derived
    from faces, so a value on a loose Blender edge has no engine edge to land
    on and rides the loose-edge snapshot instead (topology only — see
    _read_loose_edges)."""
    import numpy as np

    color = _point_float_color(mesh)
    if color is not None:
        session.color_attr_name = color.name
    edge_flags = _edge_flag_names()

    session.bridged_attrs = []
    engine_pairs = None
    for attr in mesh.attributes:
        if not _attr_is_bridgeable_name(attr.name):
            continue
        if color is not None and attr.name == color.name:
            continue
        if attr.name in edge_flags:
            continue
        if attr.name == _BL_CUSTOM_NORMAL and attr.data_type == 'INT16_2D':
            continue  # the encoded form has its own decode/re-encode path
        desc = _bridge_descriptor(mesh, attr)
        if desc is None:
            continue
        values = np.empty(len(attr.data) * desc["ncomp"], dtype=desc["dtype"])
        attr.data.foreach_get(desc["prop"], values)
        if desc["bl_domain"] == 'EDGE':
            if engine_pairs is None:
                engine_pairs = _engine_edge_pairs(mesh_ptr)
                bl_pairs = np.empty(len(mesh.edges) * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", bl_pairs)
                match = _match_pairs(engine_pairs, bl_pairs.reshape(-1, 2))
            ncomp = desc["ncomp"]
            engine_values = np.zeros(len(engine_pairs) * ncomp, dtype=desc["dtype"])
            hit = match >= 0
            engine_values.reshape(-1, ncomp)[hit] = \
                values.reshape(-1, ncomp)[match[hit]]
            values = engine_values
        _write_bridged_attr(mesh_ptr, desc, values)
        session.bridged_attrs.append(desc)


def _vert_carry_maps(session, vert_map):
    """(new_bl, old_bl, carry): for every live engine vertex, its rebuilt
    Blender index, its Blender index at the last sync (-1 when it did not
    exist then), and the mask of vertices present on both sides. The carry is
    how host-only per-vertex state crosses a rebuild. An engine index reused
    after a kill can pair a dead vertex's value with an unrelated new one —
    accepted, it is bounded to the brush region."""
    import numpy as np

    prev = session.vert_map_prev
    live_e = np.nonzero(vert_map >= 0)[0]
    new_bl = vert_map[live_e]
    old_bl = np.full(len(live_e), -1, dtype=np.int64)
    if prev is not None:
        in_prev = live_e < len(prev)
        old_bl[in_prev] = prev[live_e[in_prev]]
    return new_bl, old_bl, old_bl >= 0


def _reconcile_bridged_attrs(session, mesh, vert_map, counts):
    """Re-read the Mesh's attribute list immediately before it is destroyed.

    ``session.bridged_attrs`` was built at enter and there is no other read
    point in the session (``refresh`` is disabled for custom-undo modes and
    ``resync_if_diverged`` only compares vertex counts), so without this a
    layer created mid-session is silently dropped by the rebuild and a layer
    deleted mid-session is resurrected from its stale engine copy.

    A deleted layer's descriptor is dropped (its engine column stays, unread).
    A new supported layer is seeded into the engine: POINT-domain values are
    carried over for vertices that survived the topology change, via the
    engine-index maps (``session.vert_map_prev`` pairs engine indices with the
    Blender indices of the last sync, ``vert_map`` with the rebuilt ones); new
    vertices get the type default. An engine index reused after a kill can pair
    a dead vertex's value with an unrelated new one — accepted, it is bounded
    to the brush region. CORNER/FACE domains have no index map across the
    boundary, so their new layers keep their existence but start from defaults
    (logged)."""
    import numpy as np

    live = {}
    edge_flags = _edge_flag_names()
    for attr in mesh.attributes:
        if not _attr_is_bridgeable_name(attr.name) or attr.name in edge_flags:
            continue
        if attr.name == _BL_CUSTOM_NORMAL and attr.data_type == 'INT16_2D':
            continue  # dedicated decode/re-encode path
        # The layer the dedicated engine `color` column mirrors is the one
        # recorded at enter — a mid-session active-color change does not move
        # that column, so any *other* color layer stays generically bridged.
        if session.color_attr_name and attr.name == session.color_attr_name:
            continue
        live[attr.name] = (attr.domain, attr.data_type)

    kept = []
    known = set()
    for desc in session.bridged_attrs:
        state = live.get(desc["name"])
        if state == (desc["bl_domain"], desc["bl_type"]):
            kept.append(desc)
            known.add(desc["name"])
        # else: deleted (or deleted-and-recreated with a new shape, which the
        # created branch below re-seeds under its new descriptor).
    session.bridged_attrs = kept

    created = [name for name, state in live.items() if name not in known]
    if not created:
        return

    new_bl, old_bl, carry = _vert_carry_maps(session, vert_map)

    for name in created:
        attr = mesh.attributes.get(name)
        desc = _bridge_descriptor(mesh, attr)
        if desc is None:
            continue
        count = len(attr.data)
        ncomp = desc["ncomp"]
        if desc["bl_domain"] == 'POINT':
            old_values = np.empty(count * ncomp, dtype=desc["dtype"])
            attr.data.foreach_get(desc["prop"], old_values)
            new_count = counts[0]
            values = np.zeros(new_count * ncomp, dtype=desc["dtype"])
            values.reshape(new_count, ncomp)[new_bl[carry]] = \
                old_values.reshape(count, ncomp)[old_bl[carry]]
        else:
            if desc["bl_domain"] == 'EDGE':
                domain_count = engine.capi().lib.Mesh_edgeCount(session.mesh_ptr)
            else:
                domain_count = counts[{'CORNER': 1, 'FACE': 2}[desc["bl_domain"]]]
            values = np.zeros(domain_count * ncomp, dtype=desc["dtype"])
            print("SculptCore: attribute {!r} was created mid-session on the "
                  "{:s} domain; the layer survives the topology change but "
                  "its values reset (no index map across the rebuild)".format(
                      name, desc["bl_domain"]))
        _write_bridged_attr(session.mesh_ptr, desc, values)
        session.bridged_attrs.append(desc)


def _read_layer_designations(mesh):
    """Snapshot the active/default layer designations that
    ``clear_geometry()`` frees along with the layers (``clear_attribute_names``
    drops all six): the two color names plus the four UV-map designations.
    Read immediately before the rebuild — an enter-time snapshot would revert
    any designation the user changed mid-session. Without the restore, a
    single-UV textured mesh renders untextured after one dyntopo pass (no
    active UV designation means the draw cache skips UV extraction)."""
    uvs = mesh.uv_layers
    active = uvs.active
    clone = mesh.uv_layer_clone
    stencil = mesh.uv_layer_stencil
    return {
        "active_color": mesh.attributes.active_color_name or None,
        "default_color": mesh.attributes.default_color_name or None,
        "uv_active": active.name if active is not None else None,
        "uv_render": next((layer.name for layer in uvs if layer.active_render), None),
        "uv_clone": clone.name if clone is not None else None,
        "uv_stencil": stencil.name if stencil is not None else None,
    }


def _restore_layer_designations(mesh, snap):
    """Write the snapshotted designations back, after every layer exists again
    (``attributes.new`` auto-assigns the active color designation, so restoring
    must come after all layer recreation). The color setters accept dangling
    names without validation, so only names whose layer was actually recreated
    are written."""
    if snap["active_color"] and mesh.attributes.get(snap["active_color"]):
        mesh.attributes.active_color_name = snap["active_color"]
    if snap["default_color"] and mesh.attributes.get(snap["default_color"]):
        mesh.attributes.default_color_name = snap["default_color"]
    uvs = mesh.uv_layers
    layer = uvs.get(snap["uv_active"]) if snap["uv_active"] else None
    if layer is not None:
        uvs.active = layer
    layer = uvs.get(snap["uv_render"]) if snap["uv_render"] else None
    if layer is not None:
        layer.active_render = True
    layer = uvs.get(snap["uv_clone"]) if snap["uv_clone"] else None
    if layer is not None:
        mesh.uv_layer_clone = layer
    layer = uvs.get(snap["uv_stencil"]) if snap["uv_stencil"] else None
    if layer is not None:
        mesh.uv_layer_stencil = layer


def _flush_bridged_attrs(session, mesh, vert_map):
    """Recreate every bridged user attribute layer on the rebuilt Blender mesh
    from the engine's (interpolated / undo-reverted) values. Called on the
    topology-rebuild path only — the fast path leaves Blender customdata intact.
    A layer the engine no longer carries is skipped (leaves no stale data).
    EDGE-domain columns are gathered back by endpoint matching (engine pairs
    mapped through `vert_map`); rebuilt edges with no engine counterpart (the
    re-added loose edges) take the type default."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib
    domain_len = {'POINT': len(mesh.vertices), 'EDGE': len(mesh.edges),
                  'CORNER': len(mesh.loops), 'FACE': len(mesh.polygons)}
    edge_match = None
    for desc in session.bridged_attrs:
        count = domain_len[desc["bl_domain"]]
        ncomp = desc["ncomp"]
        if desc["bl_domain"] == 'EDGE':
            engine_pairs = _engine_edge_pairs(session.mesh_ptr)
            engine_values = np.empty(len(engine_pairs) * ncomp, dtype=desc["dtype"])
            if not lib.Mesh_readAttr(session.mesh_ptr, desc["engine_domain"],
                                     desc["name_bytes"], desc["engine_type"],
                                     engine_values.ctypes.data_as(ctypes.c_void_p)):
                continue
            if edge_match is None:
                mapped = np.where(engine_pairs >= 0, vert_map[engine_pairs], -1)
                mapped[np.any(engine_pairs < 0, axis=1)] = -1
                bl_pairs = np.empty(count * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", bl_pairs)
                edge_match = _match_pairs(bl_pairs.reshape(-1, 2), mapped)
            values = np.zeros(count * ncomp, dtype=desc["dtype"])
            hit = edge_match >= 0
            values.reshape(count, ncomp)[hit] = \
                engine_values.reshape(-1, ncomp)[edge_match[hit]]
        else:
            values = np.empty(count * ncomp, dtype=desc["dtype"])
            if not lib.Mesh_readAttr(session.mesh_ptr, desc["engine_domain"],
                                     desc["name_bytes"], desc["engine_type"],
                                     values.ctypes.data_as(ctypes.c_void_p)):
                continue
        try:
            attr = mesh.attributes.get(desc["name"])
            if attr is None:
                attr = mesh.attributes.new(desc["name"], desc["bl_type"], desc["bl_domain"])
            attr.data.foreach_set(desc["prop"], values)
        except (RuntimeError, TypeError) as error:
            # A reserved/builtin name Blender refuses to recreate, or a
            # domain-size mismatch; skip rather than abort the whole flush.
            print("SculptCore: could not restore attribute {!r}: {:s}".format(
                desc["name"], str(error)))


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


def _load_custom_normals(mesh, mesh_ptr, session):
    """Seed the engine direction column when the mesh carries the *encoded*
    custom-normal form. The free float3 forms are left to the generic
    bridge."""
    import ctypes

    import numpy as np

    attr = mesh.attributes.get(_BL_CUSTOM_NORMAL)
    if attr is None or attr.data_type != 'INT16_2D' or attr.domain != 'CORNER':
        return
    values = np.empty(len(mesh.loops) * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", values)
    engine.capi().lib.Mesh_writeAttr(mesh_ptr, 4, _SC_CUSTOM_NORMAL, _AT_FLOAT3,
                                     _USE_NONE,
                                     values.ctypes.data_as(ctypes.c_void_p))
    session.custom_normal_encoded = True


def _flush_custom_normals(session, mesh):
    """Re-encode the bridged directions into the rebuilt mesh's fans. Prefers
    the fork's Mesh.custom_normals_encode (encodes against current sharpness,
    never writes sharp_edge); falls back to normals_split_custom_set, whose
    fan-divergence scan can *add* sharp edges per call — logged once, since
    over many rebuilds that accumulates faceting."""
    import ctypes

    import numpy as np

    if not session.custom_normal_encoded:
        return
    lib = engine.capi().lib
    values = np.empty(len(mesh.loops) * 3, dtype=np.float32)
    if not lib.Mesh_readAttr(session.mesh_ptr, 4, _SC_CUSTOM_NORMAL, _AT_FLOAT3,
                             values.ctypes.data_as(ctypes.c_void_p)):
        return
    if hasattr(mesh, "custom_normals_encode"):
        mesh.custom_normals_encode(values.reshape(-1, 3))
    else:
        if not session.custom_normal_creep_warned:
            print("SculptCore: this Blender lacks Mesh.custom_normals_encode; "
                  "falling back to normals_split_custom_set, which may add "
                  "sharp edges on every topology flush")
            session.custom_normal_creep_warned = True
        mesh.normals_split_custom_set(values.reshape(-1, 3))


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


def _sc_key_name(index):
    return "{:s}{:d}".format(_SC_KEY_PREFIX, index).encode("utf-8")


def _shape_key_names(mesh):
    key = mesh.shape_keys
    return [kb.name for kb in key.key_blocks] if key is not None else []


def _write_key_column(mesh_ptr, index, values):
    import ctypes

    engine.capi().lib.Mesh_writeAttr(mesh_ptr, 1, _sc_key_name(index), _AT_FLOAT3,
                                     _USE_NONE, values.ctypes.data_as(ctypes.c_void_p))


def _load_shape_keys(mesh, mesh_ptr, session):
    """Seed each non-basis key block into the engine so dyntopo interpolates
    it and the meshlog reverts it on undo. No-op without shape keys."""
    import numpy as np

    key = mesh.shape_keys
    if key is None:
        return
    verts_num = len(mesh.vertices)
    for i, kb in enumerate(key.key_blocks):
        if i == 0:
            continue
        values = np.empty(verts_num * 3, dtype=np.float32)
        kb.data.foreach_get("co", values)
        _write_key_column(mesh_ptr, i, values)
    session.shape_key_names = _shape_key_names(mesh)


def _reconcile_shape_keys(session, mesh, vert_map):
    """The 1.8 read point for shape keys: when the block list changed
    mid-session (a key added, removed, renamed or reordered through the
    properties panel), re-seed every non-basis engine column from the current
    Blender data, carried across the index maps — the engine columns are
    index-keyed, so a stale pairing would write one key's data into
    another."""
    import numpy as np

    names = _shape_key_names(mesh)
    if names == session.shape_key_names:
        return
    nv = _mesh_vert_num(session.mesh_ptr)
    new_bl, old_bl, carry = _vert_carry_maps(session, vert_map)
    key = mesh.shape_keys
    old_count = len(mesh.vertices)
    for i, kb in enumerate(key.key_blocks if key is not None else []):
        if i == 0 or len(kb.data) != old_count:
            continue
        old_values = np.empty(old_count * 3, dtype=np.float32)
        kb.data.foreach_get("co", old_values)
        values = np.zeros(nv * 3, dtype=np.float32)
        values.reshape(nv, 3)[new_bl[carry]] = old_values.reshape(-1, 3)[old_bl[carry]]
        _write_key_column(session.mesh_ptr, i, values)
    session.shape_key_names = names


def _flush_shape_keys(session, mesh):
    """Write the non-basis key blocks back from their engine columns after a
    rebuild. Mesh.set_topology already resized every block to the new vertex
    count and reset it to the new base shape, so the basis is current and a
    column the engine somehow lost degrades to that reset, not a crash."""
    import ctypes

    import numpy as np

    key = mesh.shape_keys
    if key is None:
        return
    lib = engine.capi().lib
    verts_num = len(mesh.vertices)
    for i, kb in enumerate(key.key_blocks):
        if i == 0 or len(kb.data) != verts_num:
            continue
        values = np.empty(verts_num * 3, dtype=np.float32)
        if not lib.Mesh_readAttr(session.mesh_ptr, 1, _sc_key_name(i), _AT_FLOAT3,
                                 values.ctypes.data_as(ctypes.c_void_p)):
            continue
        kb.data.foreach_set("co", values)


def _flush_basis_key(mesh):
    """Keep the basis block equal to the mesh positions — for a keyed mesh
    the evaluated geometry comes from the Key data, so a sculpt that only
    moved mesh positions would be invisible outside the mode. Vanilla sculpt
    on the basis key does the same. Fast path only; the rebuild path's
    set_topology already reset every block to the new positions."""
    import numpy as np

    key = mesh.shape_keys
    if key is None or not len(key.key_blocks):
        return
    basis = key.key_blocks[0]
    verts_num = len(mesh.vertices)
    if len(basis.data) != verts_num:
        return
    values = np.empty(verts_num * 3, dtype=np.float32)
    _read_positions(mesh, values)
    basis.data.foreach_set("co", values)


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


def _read_skin_arrays(mesh, verts_num):
    """(radius float32 * 2, flags int32) read from the skin layer, or None."""
    import numpy as np

    if not len(mesh.skin_vertices):
        return None
    data = mesh.skin_vertices[0].data
    radius = np.empty(verts_num * 2, dtype=np.float32)
    data.foreach_get("radius", radius)
    root = np.empty(verts_num, dtype=np.bool_)
    data.foreach_get("use_root", root)
    loose = np.empty(verts_num, dtype=np.bool_)
    data.foreach_get("use_loose", loose)
    flags = root.astype(np.int32) * _SKIN_ROOT + loose.astype(np.int32) * _SKIN_LOOSE
    return radius, flags


def _load_skin(mesh, mesh_ptr, verts_num):
    """Seed the engine skin columns from the mesh's skin layer. No-op when the
    mesh carries none."""
    import ctypes

    arrays = _read_skin_arrays(mesh, verts_num)
    if arrays is None:
        return
    radius, flags = arrays
    lib = engine.capi().lib
    lib.Mesh_writeAttr(mesh_ptr, 1, _SC_SKIN_RADIUS, _AT_FLOAT2, _USE_NONE,
                       radius.ctypes.data_as(ctypes.c_void_p))
    lib.Mesh_writeAttr(mesh_ptr, 1, _SC_SKIN_FLAGS, _AT_INT, _USE_NONE,
                       flags.ctypes.data_as(ctypes.c_void_p))


def _reconcile_skin(session, mesh, vert_map):
    """The 1.8 read point for the skin layer: True when the mesh carries one
    now (the rebuild must restore it), seeding the engine columns first if the
    layer appeared mid-session (values carried across the index maps like
    _reconcile_bridged_attrs; new vertices default to zero)."""
    import ctypes

    import numpy as np

    if not len(mesh.skin_vertices):
        return False
    lib = engine.capi().lib
    nv = _mesh_vert_num(session.mesh_ptr)
    probe = np.empty(nv * 2, dtype=np.float32)
    if lib.Mesh_readAttr(session.mesh_ptr, 1, _SC_SKIN_RADIUS, _AT_FLOAT2,
                         probe.ctypes.data_as(ctypes.c_void_p)):
        return True
    arrays = _read_skin_arrays(mesh, len(mesh.vertices))
    if arrays is None:
        return False
    old_radius, old_flags = arrays
    new_bl, old_bl, carry = _vert_carry_maps(session, vert_map)
    radius = np.zeros(nv * 2, dtype=np.float32)
    radius.reshape(nv, 2)[new_bl[carry]] = old_radius.reshape(-1, 2)[old_bl[carry]]
    flags = np.zeros(nv, dtype=np.int32)
    flags[new_bl[carry]] = old_flags[old_bl[carry]]
    lib.Mesh_writeAttr(session.mesh_ptr, 1, _SC_SKIN_RADIUS, _AT_FLOAT2, _USE_NONE,
                       radius.ctypes.data_as(ctypes.c_void_p))
    lib.Mesh_writeAttr(session.mesh_ptr, 1, _SC_SKIN_FLAGS, _AT_INT, _USE_NONE,
                       flags.ctypes.data_as(ctypes.c_void_p))
    return True


def _flush_skin(session, mesh):
    """Recreate the skin layer from the engine columns after a rebuild. Layer
    creation has no direct RNA: prefer the fork's Mesh.skin_vertices_ensure
    when present, else round-trip through bmesh (whose skin layer access can
    create the CustomData layer). Never an operator — flush runs inside undo
    pushes and save handlers, and an operator call there re-enters the mode's
    own flush and frees the session under us."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib
    verts_num = len(mesh.vertices)
    radius = np.empty(verts_num * 2, dtype=np.float32)
    if not lib.Mesh_readAttr(session.mesh_ptr, 1, _SC_SKIN_RADIUS, _AT_FLOAT2,
                             radius.ctypes.data_as(ctypes.c_void_p)):
        return
    flags = np.zeros(verts_num, dtype=np.int32)
    lib.Mesh_readAttr(session.mesh_ptr, 1, _SC_SKIN_FLAGS, _AT_INT,
                      flags.ctypes.data_as(ctypes.c_void_p))

    if not len(mesh.skin_vertices):
        if hasattr(mesh, "skin_vertices_ensure"):
            mesh.skin_vertices_ensure()
        else:
            import bmesh
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                bm.verts.layers.skin.verify()
                bm.to_mesh(mesh)
            finally:
                bm.free()
        if not len(mesh.skin_vertices):
            print("SculptCore: could not recreate the skin vertex layer; "
                  "radii stay engine-side until the next flush")
            return
    data = mesh.skin_vertices[0].data
    data.foreach_set("radius", radius)
    data.foreach_set("use_root", (flags & _SKIN_ROOT) != 0)
    data.foreach_set("use_loose", (flags & _SKIN_LOOSE) != 0)


# Vertex groups
#
# Vertex groups are not Blender attributes — the weights live in MDeformVert,
# which `mesh.attributes` cannot see — so they get their own path rather than an
# _ATTR_TYPE_MAP entry. Both sides speak the same CSR layout: `offsets` holds
# vert_count + 1 entries in vertex order, slicing parallel group-index / weight
# arrays. A group index names a position in the *name table*, so the names are
# written before the weights, and read back from the engine rather than from
# whatever the object still has: the engine's table is the one its indices mean.


def _load_vertex_groups(ob, mesh_ptr):
    """Seed the object's vertex groups (names, then weights) into the engine, so
    dyntopo interpolates them onto new geometry and the meshlog reverts them on
    undo. No-op for an object with no groups, or against a Blender that predates
    the fork's bulk accessor."""
    import numpy as np

    groups = ob.vertex_groups
    if not len(groups) or not hasattr(ob.data, "vertex_group_data_get"):
        return

    lib = engine.capi().lib
    names = b"".join(vg.name.encode("utf-8") + b"\0" for vg in groups)
    lib.sc_mesh_weight_groups_set(mesh_ptr, names, len(groups))

    offsets, group_indices, weights = ob.data.vertex_group_data_get()
    if not group_indices:
        # Groups declared but nothing weighted: leave the engine without a
        # weights layer at all rather than one made of empty runs.
        return
    lib.sc_mesh_weights_set(mesh_ptr,
                            np.asarray(offsets, dtype=np.int32),
                            np.asarray(group_indices, dtype=np.int32),
                            np.asarray(weights, dtype=np.float32))


def _flush_vertex_groups(ob, session):
    """Restore the object's vertex groups from the engine after a topology
    rebuild — `clear_geometry` drops the group names along with the weights, and
    the weights cannot be written until the names they index exist again."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib
    count = lib.sc_mesh_weight_group_count(session.mesh_ptr)
    if count <= 0 or not hasattr(ob.data, "vertex_group_data_set"):
        return

    need = lib.sc_mesh_weight_groups_get(session.mesh_ptr, None, 0)
    buf = ctypes.create_string_buffer(need)
    lib.sc_mesh_weight_groups_get(session.mesh_ptr, buf, need)
    ob.vertex_groups.clear()
    for name in buf.raw[:need].split(b"\0")[:count]:
        ob.vertex_groups.new(name=name.decode("utf-8"))

    mesh = ob.data
    total = lib.sc_mesh_weights_element_count(session.mesh_ptr)
    offsets = np.empty(len(mesh.vertices) + 1, dtype=np.int32)
    group_indices = np.empty(total, dtype=np.int32)
    weights = np.empty(total, dtype=np.float32)
    if not lib.sc_mesh_weights_get(session.mesh_ptr, offsets, group_indices, weights):
        return
    mesh.vertex_group_data_set(offsets.tolist(), group_indices.tolist(), weights.tolist())


def _load_mask(mesh, mesh_ptr, verts_num):
    """Seed the engine mask column from the Blender `.sculpt_mask` attribute
    (float, point). No-op when the mesh carries no mask."""
    import numpy as np

    attr = mesh.attributes.get(_BL_MASK)
    if attr is None or attr.domain != 'POINT' or attr.data_type != 'FLOAT':
        return
    values = np.empty(verts_num, dtype=np.float32)
    attr.data.foreach_get("value", values)
    engine.capi().lib.Mesh_writeVertFloatAttr(mesh_ptr, _SC_MASK, values)


def _flush_mask(mesh, mesh_ptr, verts_num):
    """Write the engine mask column back into the Blender `.sculpt_mask`
    attribute, creating it on first use. No-op when the engine has no mask."""
    import numpy as np

    values = np.empty(verts_num, dtype=np.float32)
    if not engine.capi().lib.Mesh_readVertFloatAttr(mesh_ptr, _SC_MASK, values):
        return
    attr = mesh.attributes.get(_BL_MASK)
    if attr is None:
        attr = mesh.attributes.new(_BL_MASK, 'FLOAT', 'POINT')
    attr.data.foreach_set("value", values)


def _flush_positions_fast(session, mesh):
    """Positions-only write-back. `dumpVertCo` emits (engine_index, x, y, z)
    per live vert in the engine's live-iteration order — the same order
    `Mesh_toArrays` uses, so the i-th row is Blender vert i regardless of the
    freelist gaps dyntopo leaves in the engine index space. Write the coords in
    order; the index column is ignored."""
    import sculptcore

    mgr = engine.manager()
    mesh_obj = mgr.get_bound_pointer(
        mgr.get("sculptcore::mesh::Mesh"), session.mesh_ptr, deref=False)
    with sculptcore.construct_from_items(mgr, mgr.get("float"), []) as dump:
        mesh_obj.dumpVertCo(dump)
        data = dump.numpy().reshape(-1, 4)
        coords = data[:, 1:4].reshape(-1).copy()
        # Write through the contiguous `position` attribute (the fast-read path
        # in reverse); ~10x faster than `vertices.foreach_set("co", ...)`.
        attr = mesh.attributes.get("position")
        if attr is not None and attr.data_type == 'FLOAT_VECTOR':
            attr.data.foreach_set("vector", coords)
        else:
            mesh.vertices.foreach_set("co", coords)


def _flush_topology_rebuild(session, mesh):
    """Slow path — topology changed (dyntopo/remesh), so rebuild the Blender
    mesh geometry from a full engine export. Customdata is dropped by
    clear_geometry; the dedicated mask/face-set/color layers are re-flushed by
    the caller, and the bridged user attributes (UV maps, colors, custom attrs)
    are recreated here onto the new topology from their engine copies. Updates
    the session's sizes/stamp so the next flush is fast again.

    Everything that must survive the rebuild is read *here*, immediately
    before clear_geometry — the one point where the host state is both current
    and about to be destroyed. Returns the layer-designation snapshot for the
    caller to restore once the dedicated color/UV flushes have recreated their
    layers (they run after this)."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib
    nv, nc, nf, cap = (ctypes.c_int(0) for _ in range(4))
    lib.Mesh_arraySizes(session.mesh_ptr, ctypes.byref(nv), ctypes.byref(nc),
                        ctypes.byref(nf), ctypes.byref(cap))
    positions = np.empty(nv.value * 3, dtype=np.float32)
    corner_verts = np.empty(nc.value, dtype=np.int32)
    face_offsets = np.empty(nf.value + 1, dtype=np.int32)
    vert_map = np.empty(cap.value, dtype=np.int32)
    lib.Mesh_toArrays(session.mesh_ptr, positions, corner_verts, face_offsets, vert_map)

    # The 1.8 read point: reconcile mid-session attribute creation/deletion and
    # snapshot what clear_geometry destroys beyond the layers themselves.
    _reconcile_bridged_attrs(session, mesh, vert_map,
                             (nv.value, nc.value, nf.value))
    designations = _read_layer_designations(mesh)
    loose_edges = _read_loose_edges(session, mesh, vert_map)
    has_skin = _reconcile_skin(session, mesh, vert_map)
    _reconcile_shape_keys(session, mesh, vert_map)

    # Bulk rebuild (no per-face Python — dyntopo meshes get large). The fork's
    # Mesh.set_topology (F4) resizes every domain in place: layer
    # declarations, the six designations, the vertex-group name table,
    # animation data and shape-key blocks all survive, with values reset for
    # the flushes below to refill. Without it, fall back to
    # clear_geometry + add() + update(), which destroys all of those (the
    # designation snapshot above repairs what it can).
    loose_flat = loose_edges.reshape(-1) if loose_edges is not None else ()
    if hasattr(mesh, "set_topology"):
        # RNA float params accept numpy scalars; the int params insist on
        # Python ints, hence the tolist() (linear, dwarfed by the rebuild).
        mesh.set_topology(positions, corner_verts.tolist(), face_offsets.tolist(),
                          loose_flat.tolist() if len(loose_flat) else ())
    else:
        mesh.clear_geometry()
        mesh.vertices.add(nv.value)
        mesh.vertices.foreach_set("co", positions)
        mesh.loops.add(nc.value)
        mesh.loops.foreach_set("vertex_index", corner_verts)
        mesh.polygons.add(nf.value)
        mesh.polygons.foreach_set("loop_start", face_offsets[:nf.value])
        mesh.polygons.foreach_set("loop_total", np.diff(face_offsets))
        if loose_edges is not None:
            # Re-add loose edges before update(): clear_geometry removed
            # every edge and the face rebuild never calls edges.add().
            # calc_edges keeps existing edges.
            mesh.edges.add(len(loose_edges))
            mesh.edges.foreach_set("vertices", loose_flat)
        mesh.update(calc_edges=True)

    session.verts_num = nv.value
    session.topo_stamp = lib.Mesh_topoStamp(session.mesh_ptr)
    session.vert_map_prev = vert_map

    # Recreate the user attribute layers clear_geometry dropped, from their
    # engine copies (interpolated by dyntopo / reverted by the meshlog on undo).
    _flush_bridged_attrs(session, mesh, vert_map)
    _flush_edge_flags(session, mesh, vert_map)
    if has_skin:
        _flush_skin(session, mesh)
    _flush_custom_normals(session, mesh)
    _flush_shape_keys(session, mesh)
    return designations


def _read_loose_edges(session, mesh, vert_map):
    """Loose (wire) edges as an ``(n, 2)`` array of *rebuilt* Blender vertex
    indices, or None when there are none. Loose edges never enter the engine
    (Mesh_fromArrays takes faces only), so they are carried across the rebuild
    host-side: current endpoints are mapped old-Blender-index -> engine index
    (inverting ``session.vert_map_prev``) -> new index (``vert_map``). An edge
    whose endpoint died — or whose engine index was reused by new geometry, the
    same accepted imprecision as _reconcile_bridged_attrs — is dropped."""
    import numpy as np

    edges_num = len(mesh.edges)
    if not edges_num:
        return None
    loose = np.empty(edges_num, dtype=np.bool_)
    mesh.edges.foreach_get("is_loose", loose)
    if not loose.any():
        return None
    edge_verts = np.empty(edges_num * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", edge_verts)
    pairs = edge_verts.reshape(-1, 2)[loose]

    prev = session.vert_map_prev
    if prev is None:
        return None
    # Invert prev: old Blender index -> engine index.
    old_count = int(prev.max()) + 1
    eng_of_bl = np.full(max(old_count, int(pairs.max()) + 1), -1, dtype=np.int64)
    live_prev = np.nonzero(prev >= 0)[0]
    eng_of_bl[prev[live_prev]] = live_prev
    eng_pairs = eng_of_bl[pairs]
    valid = np.all((eng_pairs >= 0) & (eng_pairs < len(vert_map)), axis=1)
    new_pairs = np.full_like(eng_pairs, -1)
    new_pairs[valid] = vert_map[eng_pairs[valid]]
    new_pairs = new_pairs[np.all(new_pairs >= 0, axis=1)]
    return new_pairs.astype(np.int32) if len(new_pairs) else None


def _mesh_counts(mesh_ptr):
    """Live (verts, corners, faces, capacity) of an engine mesh. Counts may
    differ from the session's cached sizes after a topology change (e.g. an
    undo that reverted dyntopo); capacity sizes Mesh_toArrays' vert_map
    output (the engine index space including freelist gaps)."""
    import ctypes

    nv, nc, nf, cap = (ctypes.c_int(0) for _ in range(4))
    engine.capi().lib.Mesh_arraySizes(mesh_ptr, ctypes.byref(nv), ctypes.byref(nc),
                                      ctypes.byref(nf), ctypes.byref(cap))
    return nv.value, nc.value, nf.value, cap.value


def _mesh_vert_num(mesh_ptr):
    return _mesh_counts(mesh_ptr)[0]


def mesh_vert_num(mesh_ptr):
    """Live vertex count (public: the attribute ops/undo size their columns
    with this)."""
    return _mesh_counts(mesh_ptr)[0]


def mesh_face_num(mesh_ptr):
    """Live face count (public: see mesh_vert_num)."""
    return _mesh_counts(mesh_ptr)[2]


def mesh_corner_num(mesh_ptr):
    """Live corner (loop) count (public: see mesh_vert_num)."""
    return _mesh_counts(mesh_ptr)[1]


def mesh_positions(mesh_ptr):
    """Live vertex positions (float32, flat xyz) in live-iteration order."""
    import numpy as np

    verts_num, corners_num, faces_num, capacity = _mesh_counts(mesh_ptr)
    positions = np.empty(verts_num * 3, dtype=np.float32)
    corner_verts = np.empty(corners_num, dtype=np.int32)
    face_offsets = np.empty(faces_num + 1, dtype=np.int32)
    vert_map = np.empty(max(capacity, 1), dtype=np.int32)
    engine.capi().lib.Mesh_toArrays(mesh_ptr, positions, corner_verts,
                                    face_offsets, vert_map)
    return positions


def mesh_topo_arrays(mesh_ptr):
    """Dump the engine topology in live-iteration order: (corner_verts,
    face_offsets) as int32 arrays, matching the order of the attribute
    columns (see _flush_positions_fast on why the order lines up)."""
    import numpy as np

    verts_num, corners_num, faces_num, capacity = _mesh_counts(mesh_ptr)
    positions = np.empty(verts_num * 3, dtype=np.float32)
    corner_verts = np.empty(corners_num, dtype=np.int32)
    face_offsets = np.empty(faces_num + 1, dtype=np.int32)
    vert_map = np.empty(max(capacity, 1), dtype=np.int32)
    engine.capi().lib.Mesh_toArrays(mesh_ptr, positions, corner_verts,
                                    face_offsets, vert_map)
    return corner_verts, face_offsets


def ensure_multires_slot(session):
    """Materialize the active level's slot mesh + tree for a mesh-path reader
    (executor stroke, slot draw provider, slot mask/attr ops). The build
    reads the chain — which the grids path edits in place — so positions and
    normals are current by construction; the mask column is seeded from the
    grid domain, the mask truth while the slot was lazy. No-op when already
    resident (the ride-along mirror keeps a resident slot current)."""
    if session.mesh_ptr or not session.multires_ptr:
        return
    import numpy as np

    lib = engine.capi().lib
    level = session.multires_active_level
    lib.Multires_setActiveLevel(session.multires_ptr, level)
    session.mesh_ptr = lib.Multires_activeMesh(session.multires_ptr)
    session.tree_ptr = lib.Multires_activeTree(session.multires_ptr)
    session.verts_num = _mesh_vert_num(session.mesh_ptr)
    session.topo_stamp = lib.Mesh_topoStamp(session.mesh_ptr)
    nv = lib.Multires_levelVertCount(session.multires_ptr, level)
    mask = np.zeros(nv, dtype=np.float32)
    if lib.Multires_readDomainMask(session.multires_ptr, level, mask, nv):
        lib.Mesh_writeVertFloatAttr(session.mesh_ptr, _SC_MASK, mask)


def use_grids_provider(session):
    """Point the external-draw provider at the grids source for the session's
    active level (multires only). Draw then reads the grid domain directly —
    no slot mirror copy feeds the viewport, and the slot tree's GPU buffers
    never build. Re-registering replaces any previous source; the fresh
    source is born fully dirty, so the host reallocs its batches."""
    if not session.draw_key or not session.multires_ptr:
        return
    lib = engine.capi().lib
    lib.sc_external_draw_register_grids(
        session.draw_key, session.multires_ptr, session.multires_active_level)
    lib.sc_external_draw_update(session.draw_key)
    session.draw_provider_kind = 'GRIDS'


def use_slot_provider(session, ob=None):
    """Point the provider at the materialized slot tree — required while a
    mesh-path tool edits the slot, whose edits are invisible to the grid domain
    until the fold. First use pays the slot GPU-buffer build. (Overlays are no
    longer a reason to flip: the grids source carries color/uv/fset too, derived
    from the cage.)"""
    if not session.draw_key:
        return
    ensure_multires_slot(session)
    lib = engine.capi().lib
    lib.sc_external_draw_register(session.draw_key, session.tree_ptr)
    lib.sc_external_draw_enable_dynamic(session.tree_ptr)
    if ob is None:
        import bpy
        ob = bpy.data.objects.get(session.object_name)
    if ob is not None:
        lib.sc_external_draw_set_default_group(session.tree_ptr, _default_face_set(ob.data))
    lib.sc_external_draw_update(session.draw_key)
    session.draw_provider_kind = 'SLOT'


def sync_grid_attr_settings(ob, session, md=None):
    """Push the two host settings the engine's derived grid-attribute layers
    are keyed on — the modifier's ``uv_smooth`` (the face-varying UV rule) and
    the mesh's default face-set id (which group draws untinted). Both are
    user-editable while the mode is live, and a change drops the derived layers,
    so this returns True when it moved something and the caller owes the
    viewport an update."""
    if not session.multires_ptr:
        return False
    if md is None:
        md = multires.modifier(ob)
        if md is None:
            return False

    uv_smooth = _UV_SMOOTH_TO_ENGINE.get(md.uv_smooth, 4)
    group = _default_face_set(ob.data)
    if (uv_smooth == session.multires_uv_smooth
            and group == session.multires_default_group):
        return False

    lib = engine.capi().lib
    lib.Multires_setUvSmooth(session.multires_ptr, uv_smooth)
    lib.Multires_setDefaultGroupId(session.multires_ptr, group)
    # A resident slot mesh holds its own stamped copy of the derived layers
    # (materialize writes them); the invalidation above only drops the samples.
    if session.mesh_ptr:
        lib.Multires_syncSlotAttrs(session.multires_ptr, session.multires_active_level)
        if session.tree_ptr and session.draw_provider_kind == 'SLOT':
            lib.refreshTreeRequestedAttrs(session.tree_ptr)
    session.multires_uv_smooth = uv_smooth
    session.multires_default_group = group
    return True


def refresh_grids_mask(session):
    """Pull a changed slot-mesh mask column into the grids domain mirror NOW
    when the grids provider is displaying (mask flood fill, attr-undo): the
    op's visual feedback must not wait for the next grids stroke to run
    GridStroke_syncMask. Handles the sync==2 bookkeeping the stroke path
    normally does."""
    if (session.draw_provider_kind != 'GRIDS' or session.grid_ptr is None
            or not session.grid_mask_dirty):
        return
    lib = engine.capi().lib
    if lib.GridStroke_sync(session.grid_ptr) == 2:
        session.grid_generation += 1
        session.grid_cursor = 0
        session.grid_undo_bytes_base = 0
    lib.GridStroke_syncMask(session.grid_ptr)
    session.grid_mask_dirty = False


def _rebind_multires_views(session, active_level):
    """Point the session at the stack's current active mesh/tree. When the
    slot pointers changed (level switch, or an eviction rematerialized the
    slot), every cached wrapper bound to the old slot is reset, the meshlog
    history is dropped (the generation bump makes its undo steps decode as
    no-ops, like a refresh), and the draw provider moves to the new tree."""
    lib = engine.capi().lib
    # activeMesh/activeTree are null while the slot is lazy (never
    # materialized at this level) — the session then stays slot-less and
    # ensure_multires_slot fills the views on first mesh-path need.
    mesh_ptr = lib.Multires_activeMesh(session.multires_ptr) or 0
    tree_ptr = lib.Multires_activeTree(session.multires_ptr) or 0
    level_changed = active_level != session.multires_active_level
    session.multires_active_level = active_level
    if (mesh_ptr == session.mesh_ptr and tree_ptr == session.tree_ptr
            and not level_changed):
        # Same level, same (possibly absent) slot: nothing rebinds. A lazy
        # level switch has 0 == 0 pointers, so the level check is what keeps
        # the provider from staying bound to the old level's source.
        return
    session.mesh_ptr = mesh_ptr
    session.tree_ptr = tree_ptr
    session.verts_num = (_mesh_vert_num(mesh_ptr) if mesh_ptr else
                         lib.Multires_levelVertCount(session.multires_ptr, active_level))
    session.topo_stamp = lib.Mesh_topoStamp(mesh_ptr) if mesh_ptr else 0
    session.generation += 1
    # The executor points at the meshlog; dispose it first (as in free()).
    for obj in (session.executor, session.meshlog):
        if obj is not None and not getattr(obj, "_disposed", False):
            obj.dispose()
    session.executor = None
    session.meshlog = None
    session.meshlog_cursor = 0
    session.mesh_obj = None
    if session.draw_key:
        # Level switch (or slot rematerialization): rebind the provider. The
        # grids source is bound to one level, so it re-registers for the new
        # one; a session that was flipped to the slot provider re-registers
        # the new slot tree instead.
        if session.draw_provider_kind == 'SLOT':
            use_slot_provider(session)
        else:
            use_grids_provider(session)


def multires_store_blob(session, skip_writeback=False):
    """Snapshot the multires displacement store as bytes (C4 undo payload).
    The active level is written back first so pending slot-mesh edits are
    included — except with ``skip_writeback`` (grids-native strokes fold at
    stroke end and mirror the slot mesh, so the scan would compare a million
    bit-identical verts for nothing). Returns None on failure (or for
    plain-Mesh sessions)."""
    import ctypes

    if not session.multires_ptr:
        return None
    lib = engine.capi().lib
    if not skip_writeback:
        # A real writeback is a fold point: it can drop the grid domain and
        # kill the grid log. Blob demotion means live grid steps may hold no
        # snapshots yet — attach them while the history is still seekable.
        # (materialize itself serializes with skip_writeback=True, so this
        # cannot recurse.)
        from . import undo
        undo.materialize_grid_blobs(session)
        lib.Multires_writeback(session.multires_ptr, session.multires_active_level)
    size = ctypes.c_int(0)
    buf = lib.Multires_serializeStore(session.multires_ptr, ctypes.byref(size))
    if not buf or size.value <= 0:
        return None
    try:
        return ctypes.string_at(buf, size.value)
    finally:
        lib.freeMeshBuffer(buf)


def multires_restore_blob(ob, session, blob, level):
    """Restore a store snapshot and re-activate `level` (C4 undo fallback for
    steps whose meshlog died — a level switch or blob restore reset it). The
    restore invalidates every derived slot, so the views always rebind.
    Returns False when the blob no longer fits the cage (foreign rebuild)."""
    lib = engine.capi().lib
    if not lib.Multires_restoreStore(session.multires_ptr, blob, len(blob)):
        print("SculptCore: multires undo blob no longer matches {!r}; "
              "step skipped".format(ob.name))
        return False
    if session.mesh_ptr:
        actual = lib.Multires_setActiveLevel(session.multires_ptr, level)
    else:
        actual = lib.Multires_setActiveLevelLazy(session.multires_ptr, level)
    _rebind_multires_views(session, actual)
    # The restore invalidated the slot meshes and their mask columns with
    # them; re-seed at the restored level so mask state survives the seek.
    import bpy
    session.multires_mask_base = multires.import_mask(
        ob, bpy.context.evaluated_depsgraph_get(), session.mesh_ptr,
        session.multires_map, session.multires_ptr, actual)
    # The restore invalidated every grid domain too — the engine grids
    # session re-binds on its next sync, and its undo history is gone.
    session.grid_generation += 1
    session.grid_cursor = 0
    session.grid_undo_bytes_base = 0
    session.grid_mask_dirty = True
    # The store now equals this blob; a new stroke branches from here.
    session.multires_last_blob = blob
    return True


def _multires_desync(session, reason):
    """Report a modifier/engine divergence that only a re-enter can fix, once
    per session — the level-sync handler that gets here runs on every depsgraph
    update, so an unlatched print would repeat for as long as the mode is on."""
    if session.multires_desynced:
        return
    session.multires_desynced = True
    print("SculptCore: {}; exit and re-enter the mode to rebuild the engine "
          "multires stack".format(reason))


def sync_multires_total_levels(ob):
    """Follow the modifier's *level count* (C5): mirror Subdivide and Delete
    Higher into the engine stack so the two never disagree about how deep the
    hierarchy is.

    `Multires_addLevel` appends a smooth subdivision of the engine's current
    finest surface and `Multires_removeTopLevel` pops one, both preserving the
    surviving levels' displacement — so the engine keeps its own per-level
    decomposition instead of re-deriving everything from Blender's freshly
    subdivided CD_MDISPS (which would leave the coarse levels smooth and lose
    level switching's coarse edits).

    The grid lattice grows with the level, so the sample map is rebuilt. The
    paint mask lives on the level meshes that the restack drops, so it is
    re-seeded from CD_GRID_PAINT_MASK — current as of the last flush, since
    every stroke end bakes it out; only an in-stroke mask edit is lost.

    Two divergences cannot be repaired here, and both mark the session desynced
    (reported once — the caller runs on every depsgraph update) and wait for a
    re-enter: a base-cage change (Unsubdivide, Apply Base), which invalidates
    the whole stack rather than just its depth, and an engine stack that will
    not step all the way to the modifier's count. The second is unreachable
    short of the engine's level cap, but it cannot be papered over either: the
    exchange is keyed on Blender's *top* level, so tables built at a shallower
    engine depth would not even match sample counts."""
    import bpy

    session = engine.sessions.get(ob.name)
    if session is None or not session.multires_ptr or session.multires_desynced:
        return
    md = multires.modifier(ob)
    if md is None:
        return
    lib = engine.capi().lib
    want = int(md.total_levels)
    have = lib.Multires_maxLevel(session.multires_ptr)
    if want == have or want < 1 or have < 1:
        return
    if len(ob.data.vertices) != session.blender_verts_num:
        _multires_desync(session, "{!r}'s multires base cage changed ({} -> {} verts)".format(
            ob.name, session.blender_verts_num, len(ob.data.vertices)))
        return

    # addLevel/removeTopLevel write back and restack — a boundary for any
    # live grid history (blob demotion): snapshot its steps first.
    from . import undo
    undo.materialize_grid_blobs(session)
    while have < want:
        stepped = lib.Multires_addLevel(session.multires_ptr)
        if stepped <= have:
            break
        have = stepped
    while have > want and have > 1:
        stepped = lib.Multires_removeTopLevel(session.multires_ptr)
        if stepped >= have:
            break
        have = stepped
    session.multires_level = have
    if have != want:
        # Partially restacked: rebind first or mesh_ptr/tree_ptr keep naming a
        # slot the stepping dropped. The sample map stays stale, which the
        # desync flag is there to stop anything from building on.
        _rebind_multires_views(session, lib.Multires_setActiveLevel(session.multires_ptr, have))
        _multires_desync(session, "engine multires stack stopped at level {} of {} on {!r}".format(
            have, want, ob.name))
        return

    # Rebuild the correspondence at the new depth and re-point the session at
    # the (new) finest level, which addLevel/removeTopLevel left active.
    top, depsgraph = _eval_multires_top(ob, md, have)
    md.show_viewport = False
    session.multires_map = multires.build_map(ob, depsgraph, session.multires_ptr, have, len(top))
    _rebind_multires_views(session, lib.Multires_setActiveLevel(session.multires_ptr, have))
    session.multires_mask_base = multires.import_mask(
        ob, bpy.context.evaluated_depsgraph_get(), session.mesh_ptr,
        session.multires_map, session.multires_ptr, have)
    if session.draw_key:
        lib.sc_external_draw_update(session.draw_key)

    # The restack is the pre-state for the next undo push (C4); the old blob
    # describes a store with a different number of levels.
    session.multires_last_blob = multires_store_blob(session)

    sculpt_level = min(max(md.sculpt_levels, 1), have)
    if sculpt_level != have:
        set_multires_level(ob, sculpt_level)


def set_multires_level(ob, level):
    """Switch a multires session's active engine level (C2). The engine
    writes the outgoing level's edits back into the store; finer detail rides
    on top of coarser edits through the displacement cascade. The paint mask
    lives on the level mesh (dropped with the evicted slot), so leaving any
    level persists it to the grid paint mask (delta-based — see
    multires.export_mask) and arriving re-seeds from it at the new level's
    lattice."""
    import bpy

    session = engine.sessions.get(ob.name)
    if session is None or not session.multires_ptr:
        return
    lib = engine.capi().lib
    level = min(max(int(level), 1), session.multires_level)
    was = session.multires_active_level
    if level != was:
        # The switch writes back and re-derives levels — a boundary for the
        # outgoing level's grid history (blob demotion): snapshot its steps
        # while the log can still seek them.
        from . import undo
        undo.materialize_grid_blobs(session)
        session.multires_mask_base = multires.export_mask(
            ob, bpy.context.evaluated_depsgraph_get(), session.mesh_ptr,
            session.multires_map, session.multires_ptr, was,
            session.multires_mask_base)
    if session.mesh_ptr:
        actual = lib.Multires_setActiveLevel(session.multires_ptr, level)
    else:
        # Lazy slot: switch on the chain only; the new level stays
        # unmaterialized until a mesh-path tool needs it.
        actual = lib.Multires_setActiveLevelLazy(session.multires_ptr, level)
    _rebind_multires_views(session, actual)
    if actual != was:
        session.multires_mask_base = multires.import_mask(
            ob, bpy.context.evaluated_depsgraph_get(), session.mesh_ptr,
            session.multires_map, session.multires_ptr, actual)
        # A slot-column import is ahead of the domain until the next grids
        # sync; a domain-direct import (lazy) is current everywhere.
        session.grid_mask_dirty = bool(session.mesh_ptr)
    if actual != was:
        # The switch changed the store (downward settles down-propagation
        # into the coarser levels; either direction folds pending slot
        # edits), so the last snapshot no longer matches. Re-snapshot: that
        # blob roots the *pre*-state of the next stroke's undo step, and a
        # stale one would revert the switch's derivation along with the
        # stroke (same reasoning as the restack).
        session.multires_last_blob = multires_store_blob(session)


def _flush_multires(ob, session):
    """Multires write-back: bake the engine stack's top-level surface into the
    object's CD_MDISPS. The bake builds its own subdivision from the base mesh,
    so the suppressed modifier viewport state does not affect it. Dumping the
    top level moves the engine's active level there; restore the sculpt level
    afterwards (a no-op rebind while the slots stay resident). The paint mask
    is exported at whatever level is active — before the bake's level dance,
    while session.mesh_ptr certainly still names the active slot."""
    import bpy

    depsgraph = bpy.context.evaluated_depsgraph_get()
    if session.multires_active_level != session.multires_level:
        # Below top level the bake's level dance settles down-prop debt on
        # the way back — a fold that kills the grid log. Blob demotion means
        # its steps may hold no snapshots yet; attach them first (top-level
        # sessions skip the dance, so this stays off the common flush path
        # — decode calls flush on every seek).
        from . import undo
        undo.materialize_grid_blobs(session)
    session.multires_mask_base = multires.export_mask(
        ob, depsgraph, session.mesh_ptr, session.multires_map,
        session.multires_ptr, session.multires_active_level,
        session.multires_mask_base)
    multires.export_bake(ob, depsgraph, session.multires_ptr, session.multires_map)
    # Multires_levelPositionsOut reads the chain now — the bake no longer
    # moves the active level, so there is no level dance to undo (and a
    # below-top save no longer settles down-prop debt or kills grid logs).
    if session.draw_key:
        engine.capi().lib.sc_external_draw_update(session.draw_key)


def flush(ob):
    """Write engine state back into the Mesh ID. Fast path (positions only)
    while the topology is unchanged; slow path (full geometry rebuild) after
    dyntopo/remesh. Either way the v1 attribute layers are re-flushed.
    Multires sessions instead bake the engine surface into CD_MDISPS."""
    session = engine.sessions.get(ob.name)
    if session is None:
        return
    if session.multires_ptr:
        # Before the mesh_ptr guard: a lazy multires session has no slot
        # mesh, and skipping the bake here would save a stale CD_MDISPS.
        _flush_multires(ob, session)
        return
    if not session.mesh_ptr:
        return

    mesh = ob.data
    # The topo stamp catches forward topology edits, but a meshlog undo reverts
    # the topology without rolling the stamp back; a live-vs-Blender vertex-count
    # mismatch catches that case so undo/redo also take the rebuild path.
    designations = None
    if session.topology_changed() or _mesh_vert_num(session.mesh_ptr) != len(mesh.vertices):
        designations = _flush_topology_rebuild(session, mesh)
        # Vertex groups need the object, which the rebuild does not take. The
        # fast path leaves them alone: only new or removed vertices can change
        # them, and that is a topology change by definition.
        _flush_vertex_groups(ob, session)
    else:
        _flush_positions_fast(session, mesh)
        _flush_basis_key(mesh)

    _flush_mask(mesh, session.mesh_ptr, session.verts_num)
    _flush_face_sets(mesh, session.mesh_ptr)
    _flush_color(mesh, session.mesh_ptr, session.verts_num, session.color_attr_name)
    if designations is not None:
        # After _flush_color (which recreates the active color layer) and
        # before _flush_uv (which needs the active UV designation to find its
        # target instead of creating a duplicate map).
        _restore_layer_designations(mesh, designations)
    if session.uv_dirty:
        _flush_uv(mesh, session.mesh_ptr)
    mesh.update()
    session.blender_verts_num = len(mesh.vertices)

    # Refresh the external-provider GPU-node buffers so the viewport (which
    # draws from the provider, not this Mesh) reflects the stroke.
    if session.draw_key:
        engine.capi().lib.sc_external_draw_update(session.draw_key)


def draw_refresh(ob):
    """Refresh the external-draw GPU buffers and re-sync the object in the
    draw manager (a display-only SHADING tag, vanilla sculpt's per-step tag —
    without it the cached object sync never re-queries the provider). This is
    the per-dab viewport update; the Mesh itself stays untouched."""
    session = engine.sessions.get(ob.name)
    if session is not None and session.draw_key:
        engine.capi().lib.sc_external_draw_update(session.draw_key)
        ob.update_tag(refresh={'SHADING'})


def exit_(ob):
    """Flush and free the session (re-entrant: forced exits may repeat).
    Multires sessions also restore the modifier's viewport display."""
    session = engine.sessions.get(ob.name)
    if session is None:
        return
    try:
        flush(ob)
    finally:
        if session.draw_key:
            engine.capi().lib.sc_external_draw_unregister(session.draw_key)
        if session.multires_ptr:
            md = multires.modifier(ob)
            if md is not None:
                md.show_viewport = session.multires_show_viewport
        engine.sessions.pop(ob.name, None)
        session.free()


def refresh(ob, claim_state=True):
    """Foreign undo replaced the Mesh data: rebuild the engine mesh from the
    (new) Mesh ID; stale engine handles are detectable via the generation.

    ``claim_state`` marks the object's data as the engine's own by bumping
    ``Object.custom_mode_state`` (see handlers._resync_foreign_states): an
    undo step written after this rebuild carries data the engine mirrors, so
    returning to that step means rebuilding from it rather than keeping the
    live state. The undo handler's own rebuilds pass False — they adopt the
    state they just restored instead of minting a new one."""
    session = engine.sessions.get(ob.name)
    if session is None:
        return
    generation = session.generation + 1
    was_multires = session.multires_ptr is not None
    prev_show = session.multires_show_viewport
    # Freeing the session kills the grid stroke log, so this is one of the
    # boundaries undo.py's blob demotion names: the pushed grids steps carry no
    # snapshots of their own, and after the rebuild their history is
    # unreachable. Serialize them now, while the log can still be seeked, or
    # every stroke below this point becomes an undo that reports "history
    # unrecoverable" and does nothing.
    from . import undo
    undo.materialize_grid_blobs(session)
    session.free()
    if claim_state:
        ob.custom_mode_state = ob.custom_mode_state + 1
    new_session = enter(ob)
    new_session.generation = generation
    new_session.data_state = ob.custom_mode_state
    if was_multires and new_session.multires_ptr:
        # Mid-mode the modifier is already suppressed, so the re-enter recorded
        # False as the restore state; keep the original pre-enter state (an
        # undo that restored the DNA to visible re-records it correctly).
        new_session.multires_show_viewport = prev_show


def resync_if_diverged(ob):
    """Rebuild the session when the Blender Mesh no longer matches the engine —
    a foreign memfile undo changed the topology under a custom-undo mode (whose
    delta undo skips the generic refresh, see ed_undo.cc A3). Cheap: a vertex-
    count mismatch is the topology-change signal. Sculpting on a stale engine
    mesh would otherwise corrupt or crash; the rebuilt session bumps its
    generation so orphaned meshlog steps decode as no-ops (see undo.py).

    Returns True when it rebuilt (the caller's cached session handle is stale)."""
    session = engine.sessions.get(ob.name)
    if session is None or not session.mesh_ptr:
        return False
    if session.multires_ptr:
        # The Blender mesh is the cage; compare against the engine's cage
        # copy (the level meshes are derived and never match ob.data).
        if _mesh_vert_num(session.cage_ptr) != len(ob.data.vertices):
            refresh(ob)
            return True
        return False
    # Compare against the Blender count at the last sync, not the live engine
    # count: with deferred write-back the engine legitimately runs ahead of
    # the Mesh (e.g. an unflushed dyntopo stroke), and only a Mesh that
    # changed under us signals a foreign edit.
    if len(ob.data.vertices) != session.blender_verts_num:
        refresh(ob)
        return True
    return False
