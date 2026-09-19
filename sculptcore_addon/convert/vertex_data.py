# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender <-> engine per-vertex data layers: custom normals, shape keys,
skin vertices, vertex groups and the sculpt mask."""

from .. import engine
from .constants import _AT_FLOAT2, _AT_FLOAT3, _AT_INT, _BL_CUSTOM_NORMAL, _BL_MASK, _SC_CUSTOM_NORMAL, _SC_KEY_PREFIX, _SC_MASK, _SC_SKIN_FLAGS, _SC_SKIN_RADIUS, _SKIN_LOOSE, _SKIN_ROOT, _USE_NONE
from .topology import _mesh_vert_num, _read_positions
from .attrs import _vert_carry_maps



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
