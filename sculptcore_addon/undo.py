# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Tier-2 delta undo: couple Blender's ``CUSTOM_MODE`` undo steps to the engine's
per-session ``MeshLog``. Each stroke pushes one step (:func:`push`); Blender
drives one meshlog undo/redo per step transition (:func:`decode`); an evicted
step frees its meshlog entry (:func:`free`).

The ``CUSTOM_MODE`` undo type decodes the *active* step as well as the
destination (``UNDOTYPE_FLAG_DECODE_ACTIVE_STEP``), so on undo Blender calls us
for the step being left (``is_final`` false) and then the destination
(``is_final`` true); on redo it calls us for each step entered. Each pushed step
records the meshlog applied-step count with it applied (``target``, mirroring
``curStep_``). :func:`decode` *seeks* the meshlog cursor to the right count:

  * undo, leaving this step (not final): seek to ``target - 1`` (revert it).
  * undo, landing on this step (final): seek to ``target`` (keep it applied).
  * redo (entering this step): seek to ``target``.

Seeking (rather than a single step) makes the cursor robust even across a
memfile boundary that decodes to a memfile step this type never sees. The
Blender-side ``state_id`` is a global key routing :func:`decode`/:func:`free`
to the right session; the session generation detects a rebuilt session.

Multires sessions (P8 C4) additionally snapshot the displacement store
(``blob_before``/``blob_after`` — consecutive steps share one bytes object).
When the meshlog/grid-log seek is unavailable — a level switch or an earlier
blob restore reset the history and bumped the generation — decode falls back
to restoring the step's blob at its recorded level, which is exact because
every stroke's edits are written back into the store by stroke end. Mesh-path
steps snapshot at push time; grids-native steps push NO blob (the grid log's
block swaps are the payload) and receive theirs retroactively from
:func:`materialize_grid_blobs` at the boundary that kills their log. The
level switch itself needs no step here: the ``sculpt_levels`` property edit
pushes a memfile step, and undoing that re-drives the engine through the
depsgraph handler.
"""

import bpy

from . import convert, engine

# Global step key -> (object_name, meshlog_step_id, target_cursor, generation,
# blob_before, blob_after, level). Keyed globally because undo_free() receives
# only the key (no object). target is the meshlog applied-step count when the
# mesh is at this step; generation detects a session rebuilt out from under
# these keys. The blobs/level are None/0 for plain-Mesh sessions.
_pending = {}
_next_key = 1

# Sentinel tagging attribute-snapshot steps in _pending (identity-compared, so
# an object named "ATTR" can't collide). Attr steps: (tag, object_name,
# generation, kind, attr_name_bytes, blob_before, blob_after) — the op wrote
# an engine column directly (no meshlog entry), so decode restores the right
# snapshot instead of seeking (see push_attr). ``kind`` selects the column
# domain/type; each entry is (numpy dtype, count-getter, writer-getter).
_ATTR_TAG = ("attr",)

# Grids-native stroke steps (multires W1): the stroke lives in the engine's
# GridStrokeLog, not the meshlog. Entries: (tag, object_name, generation,
# grid_generation, target_cursor, blob_before, blob_after, level). Decode
# seeks the grid log (fast, bit-exact) when the session/level/history still
# match; otherwise it falls back to the store-blob restore, exactly like the
# meshlog steps' C4 fallback.
_GRID_TAG = ("grid",)

_ATTR_KINDS = {
    'VERT_F32': ("float32",
                 lambda session: convert.mesh_vert_num(session.mesh_ptr),
                 lambda lib: lib.Mesh_writeVertFloatAttr),
    'FACE_I32': ("int32",
                 lambda session: convert.mesh_face_num(session.mesh_ptr),
                 lambda lib: lib.Mesh_writeFaceIntAttr),
    # Corner FLOAT2 (UV) columns: len(values) is floats, so 2 per corner.
    'CORNER_F32x2': ("float32",
                     lambda session: convert.mesh_corner_num(session.mesh_ptr) * 2,
                     lambda lib: lib.Mesh_writeCornerFloat2Attr),
}


def materialize_grid_blobs(session):
    """Retro-attach store blobs to blob-less grid steps while their history is
    still seekable. Pure-grids runs push no per-stroke blobs (the log's block
    swaps are the undo payload), so every operation that kills the grid log —
    a level switch/restack, a mesh-path writeback, a store-blob restore, the
    meshlog store heal — must call this first: the log's undo/redo swap store
    blocks bit-exactly, so seeking the live history reproduces each step's
    store state, one serialize per step, once per boundary instead of per
    stroke. Ends back at the current cursor and re-roots
    ``session.multires_last_blob`` at the current state's snapshot.

    Degrades gracefully: a dead domain/history means the states are already
    unreachable (their steps keep ``None`` blobs and decode skips them), and
    positions evicted by the undo limiter simply stop the seek."""
    if session.grid_ptr is None or not session.multires_ptr:
        return
    lib = engine.capi().lib
    # hasGridDomain first: GridStroke_sync would *build* a dropped domain
    # (a multi-second hitch at 1M) just to report the history cleared.
    if not lib.Multires_hasGridDomain(session.multires_ptr, session.grid_level):
        return
    if lib.GridStroke_sync(session.grid_ptr) != 1:
        return
    # Live-history grid entries by absolute cursor target, and the seek
    # positions their missing blobs need. blob_after of step t lives at
    # position t; blob_before at t - 1 (shared with the step below).
    live = {}
    need = set()
    for key, info in _pending.items():
        if info[0] is not _GRID_TAG:
            continue
        _tag, _name, generation, grid_gen, target, bb, ba, level = info
        if (generation != session.generation
                or grid_gen != session.grid_generation
                or level != session.grid_level):
            continue
        live[target] = key
        if ba is None:
            need.add(target)
        if bb is None:
            need.add(target - 1)
    if not need:
        return
    home = session.grid_cursor
    blobs = {}

    def snap():
        if session.grid_cursor in need and session.grid_cursor not in blobs:
            blobs[session.grid_cursor] = convert.multires_store_blob(
                session, skip_writeback=True)

    snap()
    while session.grid_cursor < max(need) and lib.GridStroke_redo(session.grid_ptr):
        session.grid_cursor += 1
        snap()
    while session.grid_cursor > min(need) and lib.GridStroke_undo(session.grid_ptr):
        session.grid_cursor -= 1
        snap()
    while session.grid_cursor < home and lib.GridStroke_redo(session.grid_ptr):
        session.grid_cursor += 1
    if session.grid_cursor != home:
        # A seek the engine accepted going out was refused coming back —
        # should be unreachable (swaps are symmetric); latch loudly.
        print("SculptCore: grid blob materialization ended at cursor {} "
              "(expected {})".format(session.grid_cursor, home))
    for target, key in live.items():
        _tag, name, generation, grid_gen, t, bb, ba, level = _pending[key]
        if ba is None:
            ba = blobs.get(t)
        if bb is None:
            bb = blobs.get(t - 1)
        _pending[key] = (_GRID_TAG, name, generation, grid_gen, t, bb, ba, level)
    current = blobs.get(home)
    if current is not None:
        session.multires_last_blob = current


def engine_diverged(ob, session):
    """Note that the engine state has moved past the object's data. Strokes do
    not write back, so this is the normal state of a live session; the point is
    that any undo step written from here on carries data the engine does *not*
    mirror, and an undo returning to it must leave the live state alone. Only
    a rebuild from the data (convert.refresh) claims the opposite."""
    session.data_state = 0
    if ob is not None and ob.custom_mode_state:
        ob.custom_mode_state = 0


def _tag_view3d_redraw(context):
    window_manager = (context or bpy.context).window_manager
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def push(context, ob, session):
    """Record one undo step for the stroke just ended on ``ob``'s session."""
    global _next_key
    engine_diverged(ob, session)
    if session.last_stroke_grids:
        # Grids-native stroke: one GridStrokeLog step, no meshlog entry and no
        # per-stroke store blob — the log's block swaps ARE the undo payload
        # (blob demotion, seams design §3). Boundaries that kill the log
        # (level switch/restack, a mesh-path writeback, a blob restore, the
        # meshlog store heal) retro-attach blobs to these entries while the
        # history is still seekable (materialize_grid_blobs), so the
        # dead-history fallback stays exact. The first step of a log roots
        # its pre-state in the last boundary's snapshot.
        lib = engine.capi().lib
        blob_before = session.multires_last_blob if session.grid_cursor == 1 else None
        # undoBytes is the whole history; report this step's delta.
        total = int(lib.GridStroke_undoBytes(session.grid_ptr))
        size = max(0, total - session.grid_undo_bytes_base)
        session.grid_undo_bytes_base = total
        key = _next_key
        _next_key += 1
        _pending[key] = (_GRID_TAG, ob.name, session.generation,
                         session.grid_generation, session.grid_cursor,
                         blob_before, None, session.grid_level)
        bpy.ops.object.custom_mode_undo_push(
            'EXEC_DEFAULT', message="Sculpt Stroke", state_id=key, size=size)
        return
    log = session.meshlog
    if log is None:
        return
    step_id = int(log.lastStepId())
    if step_id < 0:
        return
    size = int(log.stepMemSize(step_id))
    blob_before = blob_after = None
    level = 0
    if session.multires_ptr:
        # C4: snapshot the store (post-writeback, so this stroke is included);
        # the previous snapshot is this step's pre-state. Each blob is shared
        # with the neighbouring step, so count it once for the undo limiter.
        # The writeback below is a boundary for any live grid history — give
        # its steps their blobs first (this also re-roots multires_last_blob
        # at the current state, so blob_before is the true pre-state even
        # after a run of blob-less grids strokes).
        materialize_grid_blobs(session)
        blob_before = session.multires_last_blob
        blob_after = convert.multires_store_blob(session)
        session.multires_last_blob = blob_after
        level = session.multires_active_level
        if blob_after is not None:
            size += len(blob_after)
    key = _next_key
    _next_key += 1
    # target = applied-step count with this stroke applied (mirrors curStep_).
    _pending[key] = (ob.name, step_id, session.meshlog_cursor, session.generation,
                     blob_before, blob_after, level)
    bpy.ops.object.custom_mode_undo_push(
        'EXEC_DEFAULT', message="Sculpt Stroke", state_id=key, size=size)


def push_attr(context, ob, session, message, kind, attr, blob_before, blob_after):
    """Record one undo step for a whole-column attribute write (e.g. mask
    flood fill). The engine meshlog never sees such writes, so the step
    carries before/after snapshots; decode restores them. ``kind`` is an
    _ATTR_KINDS key, ``attr`` the engine column name (bytes), blobs the raw
    column bytes."""
    global _next_key
    engine_diverged(ob, session)
    key = _next_key
    _next_key += 1
    if attr == convert._SC_MASK:
        session.grid_mask_dirty = True
        convert.refresh_grids_mask(session)
    _pending[key] = (_ATTR_TAG, ob.name, session.generation,
                     kind, attr, blob_before, blob_after)
    bpy.ops.object.custom_mode_undo_push(
        'EXEC_DEFAULT', message=message, state_id=key,
        size=len(blob_before) + len(blob_after))


def _decode_attr(context, ob, session, info, direction, is_final):
    """Restore an attribute snapshot. Leaving a step on undo restores its
    pre-state; landing on one (or entering on redo) restores its post-state.
    A length mismatch (topology diverged from this step's state, e.g. an
    out-of-order decode around dyntopo steps) skips the restore rather than
    corrupting the column."""
    import numpy as np

    _tag, _name, generation, kind, attr, blob_before, blob_after = info
    if generation != session.generation:
        return
    blob = blob_before if (direction < 0 and not is_final) else blob_after
    dtype, count_fn, writer_fn = _ATTR_KINDS[kind]
    values = np.frombuffer(blob, dtype=dtype)
    if count_fn(session) != len(values):
        return
    writer_fn(engine.capi().lib)(session.mesh_ptr, attr, np.ascontiguousarray(values))
    if attr == convert._SC_MASK:
        session.grid_mask_dirty = True
        convert.refresh_grids_mask(session)
    # Flush on the leave decode too, not only on the final one: an undo whose
    # destination is a step this type never decodes (e.g. the mode-enter
    # memfile boundary) would otherwise leave the restored column engine-only,
    # with the Mesh still showing the undone state.
    convert.flush(ob)
    if is_final:
        _tag_view3d_redraw(context)


def _decode_grid(context, ob, session, info, direction, is_final):
    """Seek the grids stroke log for a grids-native step. Valid only while
    the session, level, and grid history the step was pushed against are all
    unchanged AND the engine session is still bound to the same domain
    (GridStroke_sync == 1); anything else falls back to the store-blob
    restore, which is exact (grids strokes write back at stroke end)."""
    _tag, _name, generation, grid_gen, target, blob_before, blob_after, level = info
    lib = engine.capi().lib
    live = (generation == session.generation
            and grid_gen == session.grid_generation
            and session.grid_ptr is not None
            and session.grid_level == level)
    if live and lib.GridStroke_sync(session.grid_ptr) != 1:
        # The domain was rebuilt under the session: history is gone.
        session.grid_generation += 1
        session.grid_cursor = 0
        session.grid_undo_bytes_base = 0
        session.grid_mask_dirty = True
        live = False
    if live:
        if direction < 0 and not is_final:
            target -= 1
        moved = False
        while session.grid_cursor > target and lib.GridStroke_undo(session.grid_ptr):
            session.grid_cursor -= 1
            moved = True
        while session.grid_cursor < target and lib.GridStroke_redo(session.grid_ptr):
            session.grid_cursor += 1
            moved = True
        if moved or is_final:
            landed = blob_after if (is_final or direction > 0) else blob_before
            if landed is not None:
                session.multires_last_blob = landed
            convert.flush(ob)
            _tag_view3d_redraw(context)
        return
    blob = blob_before if (direction < 0 and not is_final) else blob_after
    if blob is None:
        print("SculptCore: grids undo step for {!r} has no snapshot "
              "(history unrecoverable); step skipped".format(ob.name))
        return
    # The restore kills whatever grid history is currently live (generation
    # bump) — give its blob-less steps their snapshots first or a later redo
    # back into them lands on the message above.
    materialize_grid_blobs(session)
    if convert.multires_restore_blob(ob, session, blob, level):
        convert.flush(ob)
        _tag_view3d_redraw(context)


def _decode_multires_blob(context, ob, session, info, direction, is_final):
    """C4 fallback: the step's meshlog is gone (level switch / blob restore),
    so restore its store snapshot. Leaving a step on undo restores its
    pre-state; landing on a step (or entering it on redo) restores its
    post-state. Neighbouring steps share blobs, so a leave + land pair on the
    same history edge restores the same bytes (idempotent)."""
    _name, _step_id, _target, _generation, blob_before, blob_after, level = info
    blob = blob_before if (direction < 0 and not is_final) else blob_after
    if blob is None:
        return
    materialize_grid_blobs(session)
    if convert.multires_restore_blob(ob, session, blob, level):
        convert.flush(ob)
        _tag_view3d_redraw(context)


def decode(context, ob, state_id, direction, is_final):
    """Seek the meshlog cursor to the step's target for ``ob``. On undo the
    step being left (not final) seeks to ``target - 1``; the destination
    (final) and any redo seek to ``target``. Multires steps whose meshlog
    died fall back to the store-snapshot restore."""
    session = engine.sessions.get(ob.name)
    if session is None:
        # Session gone (mode exited): the mesh is restored by memfile/refresh,
        # so there is nothing to replay at the engine level.
        return
    info = _pending.get(state_id)
    if info is None:
        return
    if ob.custom_mode_state != session.data_state:
        # The memfile step this decode rides on carries data from a different
        # vintage than the session was built at: an operator edited the object
        # underneath the mode (the multires ops, which the fork brackets with
        # flush + refresh), and the undo just put the other version back.
        # Rebuild from it *before* replaying engine state on top, or the step's
        # snapshot lands on the wrong base cage — multires_base_apply moves the
        # cage, so a stroke restored against the post-apply cage doubles its
        # displacement.
        convert.refresh(ob, claim_state=False)
        session = engine.sessions.get(ob.name)
        if session is None:
            return
    # The seek moves the engine off whatever data state it last mirrored, so
    # the object's data stops being the engine's own (the decode's own flush
    # re-asserts the engine onto the Mesh).
    engine_diverged(ob, session)
    if info[0] is _ATTR_TAG:
        _decode_attr(context, ob, session, info, direction, is_final)
        return
    if info[0] is _GRID_TAG:
        _decode_grid(context, ob, session, info, direction, is_final)
        return
    _object_name, _step_id, target, generation, _blob_before, blob_after, _level = info
    if session.multires_ptr and blob_after is not None and (
            generation != session.generation or session.meshlog is None):
        _decode_multires_blob(context, ob, session, info, direction, is_final)
        return
    if session.meshlog is None:
        return
    if generation != session.generation:
        # A foreign memfile decode rebuilt the session; this older step no
        # longer maps onto its fresh history. The memfile decode already
        # restored the mesh, so this is an engine-level no-op.
        return
    if direction < 0 and not is_final:
        # Undo leaving this step: drop below it.
        target -= 1
    log = session.meshlog
    mesh = session.mesh()
    tree = session.tree()
    moved = False
    # Seek the cursor to `target`: undo down / redo up. Guarded against the
    # meshlog's own bounds so an evicted-past target stops cleanly.
    while session.meshlog_cursor > target and session.meshlog_cursor > 0:
        log.undo(mesh, tree)
        session.meshlog_cursor -= 1
        moved = True
    while session.meshlog_cursor < target:
        log.redo(mesh, tree)
        session.meshlog_cursor += 1
        moved = True
    if moved:
        mesh.recalc_normals()
    # Flush on every final decode even when the cursor did not move: the undo
    # system may have decoded an older memfile below this step first (the
    # correct-order rule), replacing the Mesh data the engine no longer
    # matches. The flush re-asserts the engine state onto the Mesh.
    if moved or is_final:
        if session.multires_ptr:
            # Keep the C4 blob chain rooted at the landed state so a stroke
            # begun after this undo/redo records the right pre-state.
            _bb, _ba = info[4], info[5]
            landed = _ba if (is_final or direction > 0) else _bb
            if landed is not None:
                session.multires_last_blob = landed
            # Heal the store: the meshlog seek reverted slot-mesh edits the
            # store still carries (mesh-path pushes fold at push time). The
            # mesh path self-heals at its next writeback, but the grids path
            # rebuilds its domain FROM the store — re-encode now so it can't
            # resurrect the undone stroke. The writeback is a boundary for
            # any live grid history above this step; snapshot it first.
            materialize_grid_blobs(session)
            engine.capi().lib.Multires_writeback(
                session.multires_ptr, session.multires_active_level)
        convert.flush(ob)
        _tag_view3d_redraw(context)


def free(state_id):
    """Drop the meshlog entry for an evicted undo step (the store blobs go
    with the popped registry entry)."""
    info = _pending.pop(state_id, None)
    if info is None:
        return
    if info[0] is _ATTR_TAG:
        # No meshlog entry to free; the snapshots go with the popped entry.
        return
    if info[0] is _GRID_TAG:
        # Undo-limiter eviction truncates the engine log from the oldest end
        # so its memory tracks the retained steps — but only when this entry
        # IS the oldest of its live history: a redo-branch truncation frees
        # *newer* steps (the engine's beginStep already dropped those).
        _tag, object_name, generation, grid_gen, target, _bb, _ba, _level = info
        session = engine.sessions.get(object_name)
        if (session is None or session.grid_ptr is None
                or session.generation != generation
                or session.grid_generation != grid_gen
                or target > session.grid_cursor):
            return
        for other in _pending.values():
            if (other[0] is _GRID_TAG and other[1] == object_name
                    and other[2] == generation and other[3] == grid_gen
                    and other[4] < target):
                return
        engine.capi().lib.GridStroke_dropOldest(session.grid_ptr)
        return
    object_name, step_id, _target, generation, _bb, _ba, _level = info
    session = engine.sessions.get(object_name)
    if (session is not None and session.meshlog is not None
            and session.generation == generation):
        session.meshlog.freeStep(step_id)


def reset():
    """Forget all pending step keys (addon unregister / full reload)."""
    _pending.clear()
