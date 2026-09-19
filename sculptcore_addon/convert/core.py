# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Mesh <-> SculptCore conversion: entry point (enter/flush/exit/refresh).

The invariant everything else relies on: the Blender Mesh ID is the
persistent store -- ``flush()`` makes it match the engine's state on demand
(called by Blender before memfile undo encode, file save and render, via the
mode's ``flush`` callback). Engine-side state that has no Mesh
representation (the spatial tree) is rebuilt on ``refresh``/re-enter, never
serialized.

v1 layer policy (attributes beyond positions) lands with the mask/face-set/
color/UV copy stage; until then non-position data is untouched in the Mesh
and stays valid because topology ops are not yet reachable.
"""

from .. import engine, multires
from ..session import Session
from .constants import _AT_FLOAT, _AT_FLOAT2, _AT_FLOAT4, _AT_INT, _BL_FACE_SET, _DOMAIN_TO_ENGINE, _SC_COLOR, _SC_GROUP, _SC_MASK, _USE_COLOR, _USE_NONE, _USE_UV
from .topology import _flush_positions_fast, _gather_arrays, _mesh_vert_num, _read_loose_edges
from .attrs import _default_face_set, _flush_bridged_attrs, _flush_color, _flush_edge_flags, _flush_face_sets, _flush_uv, _load_bridged_attrs, _load_color, _load_edge_flags, _load_face_sets, _load_uv, _point_float_color, _read_layer_designations, _reconcile_bridged_attrs, _restore_layer_designations
from .vertex_data import _flush_basis_key, _flush_custom_normals, _flush_mask, _flush_shape_keys, _flush_skin, _flush_vertex_groups, _load_custom_normals, _load_mask, _load_shape_keys, _load_skin, _load_vertex_groups, _reconcile_shape_keys, _reconcile_skin
from .multires_bridge import _eval_multires_top, _flush_multires, multires_store_blob, set_multires_level, sync_grid_attr_settings, use_grids_provider



class ConvertError(RuntimeError):
    pass



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

    # Mask (MK4): seed the store's mask channel from the grid paint mask —
    # every level, top exact + coarser by injection. The store is the one
    # mask truth from here on; slot columns and domain mirrors are caches,
    # refreshed by generation (sync_slot_mask / the engine's write hooks).
    depsgraph = context.evaluated_depsgraph_get()
    multires.import_mask(ob, depsgraph, mr_map, mr)

    session = Session(ob.name, mesh_ptr, tree_ptr,
                      lib.Multires_levelVertCount(mr, level))
    session.blender_verts_num = len(ob.data.vertices)
    session.multires_ptr = mr
    session.cage_ptr = cage
    session.multires_map = mr_map
    session.multires_level = level
    session.multires_active_level = level
    session.multires_show_viewport = prev_show
    # The colour layer the cage was seeded from is the one a painted level is
    # written back into (see _flush_multires), by name rather than by the active
    # designation — the rule the mesh path already follows.
    color_attr = _point_float_color(ob.data)
    session.color_attr_name = color_attr.name if color_attr is not None else None
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
