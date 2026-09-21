# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Session-level engine object lifecycle: brush/executor construction, the
grids-native capability check, and stroke begin/end."""

from .. import convert, engine, mapping


def _ensure_brush(session):
    """The session's reusable engine Brush (built once)."""
    if session.brush_obj is None:
        mgr = engine.manager()
        session.brush_obj = mgr.construct("sculptcore::brush::Brush")
    return session.brush_obj


def _ensure_executor(session):
    """The session's CommandExecutor, bound to its tree + brush, with a
    per-session MeshLog wired in so each stroke records an undo step."""
    if session.executor is None:
        mgr = engine.manager()
        ctor = mgr.get_struct("sculptcore::brush::CommandExecutor").find_constructor("main")
        session.executor = mgr.construct_with(ctor, session.tree(), _ensure_brush(session))
        session.meshlog = mgr.construct("sculptcore::meshlog::MeshLog")
        session.executor.meshLog = session.meshlog
        # Csr (ring-1 CSR adjacency) for the smooth family's for_neighbor source,
        # matching the engine's other sculpt consumer. Bit-identical to the
        # LiveDisk default on our freshly built meshes and marginally faster (Q1a
        # A/B); a dyntopo step overrides it back to LiveDisk internally.
        session.executor.setNeighborMode(1)
    return session.executor


# Cached MASK/BSMOOTH kernel ids: the binding enum introspection walks
# descriptors and costs ~20 ms — far too much per stroke.
_bsmooth_kernel_id = None


def grids_capable(session, brush_type):
    """Whether a stroke of ``brush_type`` can run grids-native (multires
    session + engine roster kernel). MASK qualifies since MK4 made the store
    the addon's one mask truth (the slot column is a cache the fold/sync
    machinery keeps honest).

    Brushes that write an attribute layer are answered by the engine roster
    itself, from the attribute's storage class: Blender declares only the mask
    as a host grid attribute, so colour and face sets are ``Derived`` and take
    the cage route (mesh path + a per-dab write-back) instead."""
    global _bsmooth_kernel_id
    if not session.multires_ptr:
        return False
    if _bsmooth_kernel_id is None:
        mgr = engine.manager()
        items = mgr.get("sculptcore::brush::SculptBrushes").items
        _bsmooth_kernel_id = int(items['BSMOOTH'])
    lib = engine.capi().lib
    # The multires is not optional here: an attribute brush's route is its
    # attribute's storage class, which is per-object state (a host that CAN
    # store multires attributes declares them, and only then may a kernel
    # write grid elements). session.multires_ptr is live -- the early return
    # above refused a session without one.
    return bool(lib.GridStroke_supported(session.multires_ptr, int(brush_type)))


def program_grids_capable(session, main_kernel):
    """Whether an autosmooth program ``[main_kernel, BSMOOTH]`` can run
    grids-native: both entries must pass ``grids_capable``."""
    if not grids_capable(session, main_kernel):
        return False
    return grids_capable(session, _bsmooth_kernel_id)


def toggle_kernel_name(mode, brush, session):
    """Kernel for a Shift/Alt stroke toggle (vanilla brush_toggle semantics).

    Shift over a paint brush blurs colour, as vanilla sculpt does. On multires
    the stroke runs through the engine's cage-dab entry (CageSmooth_*): dabs
    execute on the cage colour column at cage resolution — the 1-ring average a
    neighbour-reading smooth needs — and the touched grids re-derive per dab
    (grids-native-completion CS2/CS3).

    A plain function rather than inline invoke code: the verify harness drives
    ``stroke_begin``/``apply_dab`` directly and never runs the modal operator.
    """
    if mode != 'SMOOTH':
        return "MASK"
    if brush is not None and brush.sculpt_brush_type in mapping.COLOR_TYPES:
        return "COLORSMOOTH"
    return "BSMOOTH"


def _grid_session(session):
    """The engine grids stroke session for the active multires level, created
    lazily and recreated on level change (a session binds one level). None
    when creation fails."""
    lib = engine.capi().lib
    level = session.multires_active_level
    if session.grid_ptr and session.grid_level != level:
        lib.GridStroke_free(session.grid_ptr)
        session.grid_ptr = None
        session.grid_generation += 1
        session.grid_cursor = 0
    if not session.grid_ptr:
        brush = _ensure_brush(session)
        ptr = lib.GridStroke_new(session.multires_ptr, level, brush.ptr)
        if not ptr:
            return None
        session.grid_ptr = ptr
        session.grid_level = level
        session.grid_generation += 1
        session.grid_cursor = 0
        session.grid_undo_bytes_base = 0
        # The addon relies on the engine-side ride-along mirror to keep the
        # slot mesh (extdraw, flush, mesh-path queries) current, and defers
        # normal refreshes to the frame cadence (closely-spaced dabs overlap
        # ~90%, so per-dab refresh recomputes the same fans many times).
        lib.GridStroke_setMirror(ptr, 1)
        lib.GridStroke_setDeferNormals(ptr, 1)
    return session.grid_ptr


def stroke_begin(session, *, has_dyntopo=False, accumulate=True, anchored_grab=True,
                 grids_kernel=None, cage_kernel=None, plane_frame=None):
    """``plane_frame`` is the plane-family frame policy for this stroke
    (``mapping.plane_frame``'s tuple); None leaves the executor default (the
    raycast frame). Pushed to whichever executor runs the stroke — a grids
    begin that fails falls through to the mesh push below."""
    session.last_stroke_grids = False
    session.last_stroke_cage = False
    if plane_frame is None:
        from .. import mapping
        plane_frame = mapping.PLANE_FRAME_DEFAULT
    if grids_kernel is not None and grids_capable(session, grids_kernel):
        grid = _grid_session(session)
        if grid is not None:
            lib = engine.capi().lib
            lib.GridStroke_setNonAccum(grid, 0 if accumulate else 1)
            lib.GridStroke_setAnchoredGrab(grid, 1 if anchored_grab else 0)
            lib.GridStroke_setPlaneFrame(grid, *_plane_frame_args(plane_frame))
            # A fold point (mesh-path stroke, level op) may have rebuilt the
            # domain, which cleared the grid undo history.
            if lib.GridStroke_sync(grid) == 2:
                session.grid_generation += 1
                session.grid_cursor = 0
                session.grid_undo_bytes_base = 0
            if lib.GridStroke_begin(grid):
                session.last_stroke_grids = True
                session.stroke_gen += 1
                session.filter_high_water = 0.0
                # Grids strokes draw from the grids source; flip back if a
                # mesh-path tool moved the provider to the slot tree.
                if session.draw_provider_kind != 'GRIDS':
                    convert.use_grids_provider(session)
                return
    if cage_kernel is not None and session.multires_ptr:
        # Cage-dab colour smoothing (CS3): the stroke's dabs run engine-side
        # on the cage colour column and re-derive the touched grids. The rest
        # of the mesh-path stroke shape below still runs — the executor step
        # is empty, but it is a real meshlog step, so undo.push pairs this
        # stroke's cage columns with its own step id.
        lib = engine.capi().lib
        ptr = lib.CageSmooth_new(session.multires_ptr, session.multires_active_level,
                                 _ensure_brush(session).ptr)
        if ptr and not lib.CageSmooth_begin(ptr, convert._SC_COLOR):
            lib.CageSmooth_free(ptr)
            ptr = None
        if ptr:
            session.cage_smooth_ptr = ptr
            session.last_stroke_cage = True
    if session.multires_ptr and not session.last_stroke_cage:
        convert.ensure_multires_slot(session)
    if (session.multires_ptr and session.draw_provider_kind != 'SLOT'
            and not session.last_stroke_cage):
        # Mesh-path stroke on a multires session: its edits land in the slot
        # mesh, which the grids source cannot see — draw the slot tree for
        # the duration (first flip pays the slot GPU-buffer build; the
        # ride-along mirror keeps the slot current, so no heal is needed).
        # A cage stroke's epilogue re-derives into both draw sources, so it
        # keeps whichever provider is active.
        convert.use_slot_provider(session)
    executor = _ensure_executor(session)
    executor.beginStep(has_dyntopo)
    session.dyntopo_active = has_dyntopo
    # A nonzero, per-stroke generation is required for grab-class kernels
    # (they orig-stamp against it); harmless for the rest.
    session.stroke_gen += 1
    executor.setStrokeGen(session.stroke_gen)
    # Anchoring is a property of the *stroke*, not the kernel: it decides
    # whether a @grabmode kernel deforms from each vert's stroke-start position
    # (fixed region, absolute drag) or accumulates dab to dab like any other
    # brush. The engine defaults it on; set it explicitly so a path-mode
    # kelvinlet would build up instead of re-basing every dab.
    executor.setAnchoredGrab(anchored_grab)
    session.filter_high_water = 0.0
    # Vanilla's per-brush "Accumulate": with it off, the engine measures each
    # accumulable command from a stroke-start snapshot (nonAccum mode) so
    # repeated passes within one stroke don't build up.
    executor.setNonAccum(not accumulate)
    executor.setPlaneFrame(*_plane_frame_args(plane_frame))


def _plane_frame_args(plane_frame):
    """The setter's argument list from the policy tuple: two enum ints, two
    bools (a C int argtype takes a bool too), then the seven floats."""
    normal, center, orig_normal, orig_plane, *rest = plane_frame
    return (int(normal), int(center), bool(orig_normal), bool(orig_plane),
            *(float(v) for v in rest))


def set_image_sign(session, sign=(1, 1, 1)):
    """Tell the stroke's executor which symmetry image the next dab is, so a
    plane-frame kernel's mirror takes the reflected primary frame instead of a
    gather of its own. The primary (sign (1, 1, 1)) must be set before each
    logical dab, before its mirrors; the batch paths scope this per row on the
    engine side, so only the per-dab paths call it."""
    is_mirror = tuple(sign) != (1, 1, 1)
    if session.last_stroke_grids:
        engine.capi().lib.GridStroke_setImageSign(
            session.grid_ptr, float(sign[0]), float(sign[1]), float(sign[2]), int(is_mirror))
        return
    if session.last_stroke_cage:
        return
    _ensure_executor(session).setImageSign(float(sign[0]), float(sign[1]), float(sign[2]), is_mirror)


def stroke_end(session):
    if session.last_stroke_grids:
        # Grids-native: endStep folded the stroke into the store already
        # (restricted writeback) and closed the grid undo step; the engine
        # mirror kept the slot mesh + normals current per dab.
        engine.capi().lib.GridStroke_end(session.grid_ptr)
        session.grid_cursor += 1
        return
    if session.last_stroke_cage and session.cage_smooth_ptr:
        # Close the cage session first; the (empty) executor step below still
        # ends normally so the stroke owns a meshlog step for undo.push.
        lib = engine.capi().lib
        lib.CageSmooth_end(session.cage_smooth_ptr)
        lib.CageSmooth_free(session.cage_smooth_ptr)
        session.cage_smooth_ptr = None
    executor = _ensure_executor(session)
    if session.dyntopo_active:
        executor.endDynTopoStroke()
    executor.endStep()
    # endStep() advanced the meshlog's applied-step count; mirror it (a stroke
    # begun after an undo truncates the redo branch, so +1 is always correct).
    session.meshlog_cursor += 1
    # A mesh-path MASK stroke on multires wrote only the slot column; fold it
    # into the store (no-op when the stroke touched no mask, or no multires).
    convert.fold_slot_mask(session)
    # Normals only over the leaves the stroke dirtied. Mesh.recalc_normals() is
    # O(whole mesh) and thaws the topology, so on a multires cage it cost half a
    # second per stroke plus a frozen-topology rebuild on the next dab.
    session.tree().updateNormals()
