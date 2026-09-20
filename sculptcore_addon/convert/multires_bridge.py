# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The multires-specific half of the convert package: the grids-provider
cage/slot bridge, cage draw-attr sync + undo restamping, and the multires
store blob."""

from .. import engine, multires
from .constants import _SC_COLOR, _SC_GROUP, _SC_MASK, _UV_SMOOTH_TO_ENGINE
from .topology import _mesh_vert_num, mesh_face_num, mesh_vert_num
from .attrs import _default_face_set, _flush_color, _flush_face_sets



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



def ensure_multires_slot(session):
    """Materialize the active level's slot mesh + tree for a mesh-path reader
    (executor stroke, slot draw provider, slot mask/attr ops). The build
    reads the chain — which the grids path edits in place — so positions and
    normals are current by construction; the mask column syncs from the
    store, the one mask truth (MK4). No-op when already resident (the
    ride-along mirror keeps a resident slot current)."""
    if session.mesh_ptr or not session.multires_ptr:
        return
    lib = engine.capi().lib
    level = session.multires_active_level
    lib.Multires_setActiveLevel(session.multires_ptr, level)
    session.mesh_ptr = lib.Multires_activeMesh(session.multires_ptr)
    session.tree_ptr = lib.Multires_activeTree(session.multires_ptr)
    if session.executor is not None:
        session.executor.tree = session.tree()
    # The Mesh wrapper is cached against the pointer it was bound to, and the
    # slot just moved from absent to resident.
    session.mesh_obj = None
    session.verts_num = _mesh_vert_num(session.mesh_ptr)
    session.topo_stamp = lib.Mesh_topoStamp(session.mesh_ptr)
    session.slot_mask_gen = 0
    sync_slot_mask(session)
    # A materialized slot starts with no sculpt-layer settings row; under a
    # live edit target the mesh path's LayerEditScope needs one (LD3). A zero
    # scratch row at weight 1 composites nothing, and stroke-end attribution
    # to the store channel follows the mr edit target, not this row.
    if (lib.Multires_editTarget(session.multires_ptr) >= 0
            and lib.Mesh_sculptLayerCount(session.mesh_ptr) == 0):
        lib.Mesh_sculptLayerAdd(session.mesh_ptr)



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
    # An already-resident slot may hold a mask column older than the store
    # (grids MASK strokes while the grids provider was showing).
    sync_slot_mask(session)
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



def sync_cage_face_attrs(session):
    """Push a face-set edit on a subdivided level back onto the cage. The cage
    is the only copy that persists: the slot is an LRU cache and the store's
    Face channel is engine-owned session state — so without this a face set
    painted on a subdivided level is gone at the next eviction or mode exit.

    Blender writes a face set on multires to the whole base face, unweighted,
    which is what the engine's scatter reproduces (Multires::scatterFaceIntToCage).
    Returns the number of base faces changed, and marks only the grids behind
    them on both draw paths."""
    if not session.multires_ptr:
        return 0
    return engine.capi().lib.Multires_scatterFaceIntToCage(
        session.multires_ptr, session.multires_active_level, _SC_GROUP)



def cage_face_group_bytes(session):
    """The cage's `group` face column as raw int32 bytes — the undo payload for
    a face-set edit on a multires object, where the slot the edit was made on is
    an evictable cache and the cage is what persists. A cage that has no face
    sets yet reads as the host's default group, which is what the engine's own
    ensureFaceGroups() flood-fills on first write. None without a cage."""
    import numpy as np

    if not session.cage_ptr:
        return None
    count = mesh_face_num(session.cage_ptr)
    if count <= 0:
        return None
    values = np.full(count, int(session.multires_default_group or 0), dtype=np.int32)
    engine.capi().lib.Mesh_readFaceIntAttr(session.cage_ptr, _SC_GROUP, values)
    return values.tobytes()



def restamp_cage_face_attrs(session):
    """Re-derive from a cage face layer that was written whole (an undo restore
    of #cage_face_group_bytes): drop the derived grid layers keyed on it and
    re-stamp the resident level mesh, so cage, grids and slot agree again.

    Unlike #sync_cage_face_attrs this cannot know what moved, so it takes the
    full invalidation — a whole-column restore may have changed anything."""
    if not session.multires_ptr:
        return
    lib = engine.capi().lib
    lib.Multires_invalidateGridAttr(session.multires_ptr, _SC_GROUP)
    if session.mesh_ptr:
        lib.Multires_syncSlotAttrs(session.multires_ptr, session.multires_active_level)
        if session.tree_ptr and session.draw_provider_kind == 'SLOT':
            lib.refreshTreeRequestedAttrs(session.tree_ptr)



def sync_cage_vert_color(session):
    """Push a colour edit on a subdivided level back onto the cage — the
    vertex-domain twin of #sync_cage_face_attrs, and for the same reason:
    Blender has no multires attribute domain, so the store channel (engine-owned
    session state) and the slot column (an evictable cache) both die at mode
    exit, and the cage is the only copy of painted colour that reaches
    ``ob.data``.

    Exact, not a fit: grid sample (0, 0) is its corner's cage vert at weight one
    under the ptex-bilinear rule, so this is restriction. What it cannot do is
    resolve finer than the cage — a dab smaller than a base face changes no cage
    vert and so leaves nothing behind. That is the accepted trade of routing
    multires colour through the cage (plans/grid-domain-attributes.md §6.2), not
    a bug to engineer away.

    ``session.dab_regions`` (the spheres painted since the last call) goes with
    it so those grids re-derive whether or not a cage vert moved. Leaving
    nothing behind has to mean *nothing*: without the region a sub-face dab's
    paint would sit on screen at grid resolution until some later dab moved a
    neighbouring cage vert and swept it away.

    Returns the number of cage verts changed."""
    import ctypes

    if not session.multires_ptr:
        return 0
    dabs = session.dab_regions
    count = len(dabs) // 4
    buf = (ctypes.c_float * len(dabs))(*dabs) if count else None
    return engine.capi().lib.Multires_scatterVertFloat4ToCage(
        session.multires_ptr, session.multires_active_level, _SC_COLOR, buf, count)



def cage_vert_color_bytes(session):
    """The cage's `color` vertex column as raw float32 bytes (4 per vert) — the
    undo payload for a colour edit on a multires object, the same argument as
    #cage_face_group_bytes. A cage with no colour layer yet reads as white,
    which is what the engine's own scatter floods a first-ever one with. None
    without a cage."""
    import numpy as np

    if not session.cage_ptr:
        return None
    count = mesh_vert_num(session.cage_ptr)
    if count <= 0:
        return None
    values = np.ones(count * 4, dtype=np.float32)
    engine.capi().lib.Mesh_readVertFloat4Attr(session.cage_ptr, _SC_COLOR, values)
    return values.tobytes()



def restamp_cage_vert_color(session):
    """Re-derive from a cage colour layer written whole (an undo restore of
    #cage_vert_color_bytes) — the colour twin of #restamp_cage_face_attrs.

    Unlike the forward scatter this DOES re-derive: a whole-column restore is
    not a finer-than-cage edit being coarsened, it is the cage becoming the
    truth again, so the derived samples must follow it rather than keep the
    undone paint."""
    if not session.multires_ptr:
        return
    lib = engine.capi().lib
    lib.Multires_invalidateGridAttr(session.multires_ptr, _SC_COLOR)
    if session.mesh_ptr:
        lib.Multires_syncSlotAttrs(session.multires_ptr, session.multires_active_level)
        if session.tree_ptr and session.draw_provider_kind == 'SLOT':
            lib.refreshTreeRequestedAttrs(session.tree_ptr)



def sync_slot_mask(session):
    """Refresh the resident slot mesh's mask column from the store when the
    store's mask moved underneath it (Multires_maskGeneration): level switch,
    blob restore, restack, grids MASK strokes. No-op without a resident slot
    or while the recorded generation is current — slot_mask_gen resets to 0
    on rebind and the engine counter starts at 1, so a fresh slot always
    refreshes once."""
    if not session.mesh_ptr or not session.multires_ptr:
        return
    lib = engine.capi().lib
    gen = lib.Multires_maskGeneration(session.multires_ptr)
    if gen == session.slot_mask_gen:
        return
    import numpy as np

    level = session.multires_active_level
    nv = lib.Multires_levelVertCount(session.multires_ptr, level)
    mask = np.zeros(nv, dtype=np.float32)
    if lib.Multires_readDomainMask(session.multires_ptr, level, mask, nv):
        lib.Mesh_writeVertFloatAttr(session.mesh_ptr, _SC_MASK, mask)
        if session.tree_ptr and session.draw_provider_kind == 'SLOT':
            lib.refreshTreeRequestedAttrs(session.tree_ptr)
    session.slot_mask_gen = gen



def fold_slot_mask(session):
    """Fold mesh-path mask edits — the resident slot's `.spatial.v.mask`
    column — into the store as an EDIT (upward delta-prolongation, down-debt),
    keyed on an actual diff against the domain, so it is a no-op when nothing
    wrote the column. Covers the mesh-path MASK fallback stroke and attr-undo
    restores, both of which write the column without touching the store."""
    if not session.mesh_ptr or not session.multires_ptr:
        return
    import numpy as np

    lib = engine.capi().lib
    if lib.Multires_maskGeneration(session.multires_ptr) != session.slot_mask_gen:
        # The store moved since the column last synced (a grids MASK stroke,
        # a restore): the column is a stale cache, not host edits — folding
        # it would overwrite the newer store content. Host mask-edit paths
        # always sync first (use_slot_provider), so a stale column cannot be
        # carrying legitimate edits.
        return
    level = session.multires_active_level
    nv = lib.Multires_levelVertCount(session.multires_ptr, level)
    col = np.empty(nv, dtype=np.float32)
    if not lib.Mesh_readVertFloatAttr(session.mesh_ptr, _SC_MASK, col):
        return
    cur = np.zeros(nv, dtype=np.float32)
    if not lib.Multires_readDomainMask(session.multires_ptr, level, cur, nv):
        return
    changed = np.nonzero(col != cur)[0].astype(np.int32)
    if not len(changed):
        return
    lib.Multires_editDomainMask(session.multires_ptr, level,
                                np.ascontiguousarray(changed),
                                np.ascontiguousarray(col[changed], dtype=np.float32),
                                len(changed))
    # The fold bumped the generation while the column already IS the store's
    # new content: record it, or sync_slot_mask would rewrite the column
    # with the values it was just given.
    session.slot_mask_gen = lib.Multires_maskGeneration(session.multires_ptr)



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
    # The new slot's column was seeded whenever it was materialized; force a
    # store->column refresh against the store's current generation.
    session.slot_mask_gen = 0
    if session.draw_key:
        # Level switch (or slot rematerialization): rebind the provider. The
        # grids source is bound to one level, so it re-registers for the new
        # one; a session that was flipped to the slot provider re-registers
        # the new slot tree instead.
        if session.draw_provider_kind == 'SLOT':
            use_slot_provider(session)
        else:
            use_grids_provider(session)
    if session.mesh_ptr:
        sync_slot_mask(session)



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
        from .. import undo
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
    # The restore bumped the store's mask generation; the rebind above
    # early-returns when the slot pointers did not change, so sync the
    # resident column here explicitly.
    sync_slot_mask(session)
    # The restore invalidated every grid domain too — the engine grids
    # session re-binds on its next sync, and its undo history is gone.
    session.grid_generation += 1
    session.grid_cursor = 0
    session.grid_undo_bytes_base = 0
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
    from .. import undo
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
    lives in the store (MK4) and crosses level switches there; the arriving
    slot's column refreshes from it in _rebind_multires_views. CD export
    happens only at flush."""
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
        from .. import undo
        undo.materialize_grid_blobs(session)
        # Mesh-path mask edits live only in the slot column until folded;
        # the switch drops the slot, so fold before it goes.
        fold_slot_mask(session)
    if session.mesh_ptr:
        actual = lib.Multires_setActiveLevel(session.multires_ptr, level)
    else:
        # Lazy slot: switch on the chain only; the new level stays
        # unmaterialized until a mesh-path tool needs it.
        actual = lib.Multires_setActiveLevelLazy(session.multires_ptr, level)
    _rebind_multires_views(session, actual)
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
    is exported from the store's top level (MK4) — after folding any pending
    slot-column edits, so a mesh-path stroke or attr-undo reaches the file."""
    import bpy

    depsgraph = bpy.context.evaluated_depsgraph_get()
    if session.multires_active_level != session.multires_level:
        # Below top level the bake's level dance settles down-prop debt on
        # the way back — a fold that kills the grid log. Blob demotion means
        # its steps may hold no snapshots yet; attach them first (top-level
        # sessions skip the dance, so this stays off the common flush path
        # — decode calls flush on every seek).
        from .. import undo
        undo.materialize_grid_blobs(session)
    # Face sets ride the cage, and a mesh-path stroke edited the slot's derived
    # copy — push it home before the readback, or what reaches `.sculpt_face_set`
    # is the pre-stroke cage. Runs while the slot is certainly still resident.
    sync_cage_face_attrs(session)
    # Colour rides the cage for the same reason, and needs the same push: a
    # grids-native stroke wrote the store's session channel, a mesh-path one the
    # slot's derived column, and neither reaches ob.data (§6.2 of
    # plans/grid-domain-attributes.md).
    sync_cage_vert_color(session)
    if session.cage_ptr:
        _flush_face_sets(ob.data, session.cage_ptr)
        _flush_color(ob.data, session.cage_ptr, len(ob.data.vertices),
                     session.color_attr_name)
    fold_slot_mask(session)
    multires.export_mask(ob, depsgraph, session.multires_map, session.multires_ptr)
    multires.export_bake(ob, depsgraph, session.multires_ptr, session.multires_map)
    # Multires_levelPositionsOut reads the chain now — the bake no longer
    # moves the active level, so there is no level dance to undo (and a
    # below-top save no longer settles down-prop debt or kills grid logs).
    if session.draw_key:
        engine.capi().lib.sc_external_draw_update(session.draw_key)
