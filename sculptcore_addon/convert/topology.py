# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Leaf-level mesh readback: positions, topology arrays and per-Mesh vert/
face/corner counts. No dependency on the rest of the convert package."""

from .. import engine



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
