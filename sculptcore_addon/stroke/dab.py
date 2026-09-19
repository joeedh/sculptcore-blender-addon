# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Single-dab and dab-program application, plain and grab-class."""

from .. import brush_policy, engine
from ._util import _float3
from .dyntopo import _refresh_queries
from .session import _ensure_executor


def apply_dab(session, brush_type, center, normal, radius, *, grab_add=False):
    """Run one dab at an object-space center/normal. `center`/`normal` are
    3-tuples; `brush_type` is the SculptBrushes enum value. Returns the
    number of spatial nodes the dab touched (0 = brush missed the surface);
    grids-native strokes return the moved-vert count instead."""
    import sculptcore

    if session.last_stroke_cage:
        # Cage-dab route: one primary image per call (symmetry mirrors arrive
        # as their own calls, already reflected). Strength was written by
        # apply_dab_state's per-pass override; the pressure LUT is folded in
        # there too, so the engine's own stays off.
        import numpy as np
        dab = np.array([center[0], center[1], center[2],
                        normal[0], normal[1], normal[2], radius],
                       dtype=np.float32)
        lib = engine.capi().lib
        if lib.CageSmooth_supportsResolved(session.cage_smooth_ptr, int(brush_type)):
            return lib.CageSmooth_dabResolved(session.cage_smooth_ptr, int(brush_type), *center, *normal)
        if session.generic_runtime is not None:
            return -1
        return lib.CageSmooth_dabCurrentInputs(
            session.cage_smooth_ptr, int(brush_type), dab, session.brush_obj.strength)
    if session.last_stroke_grids:
        # Grids-native: the engine queries its own GridTree, mirrors the slot
        # mesh, and refreshes normals/bounds — no filterNodes/_refresh_queries.
        lib = engine.capi().lib
        if lib.GridStroke_supportsResolved(session.grid_ptr, int(brush_type), None):
            return lib.GridStroke_dabResolved(session.grid_ptr, int(brush_type), *center, *normal)
        if getattr(session, "generic_runtime", None) is not None:
            return -1
        return lib.GridStroke_dab(
            session.grid_ptr, int(brush_type),
            center[0], center[1], center[2],
            normal[0], normal[1], normal[2], 0)

    mgr = engine.manager()
    executor = _ensure_executor(session)
    tree = session.tree()

    if executor.supportsResolved(brush_type):
        if grab_add:
            return engine.capi().lib.MeshStroke_dabResolvedImage(
                executor.ptr, int(brush_type), *center, *normal, 1)
        return engine.capi().lib.MeshStroke_dabResolved(executor.ptr, int(brush_type), *center, *normal)
    if getattr(session, "generic_runtime", None) is not None or not executor.preflightRaw(brush_type):
        return -1

    center_v = _float3(mgr, *center)
    normal_v = _float3(mgr, *normal)
    nodes = mgr.construct("litestl::util::Vector<sculptcore::spatial::SpatialNode*,4>")
    filter_r = brush_policy.filter_radius(brush_type, radius, session.brush_obj, session)
    try:
        if not tree.filterNodes(center_v, filter_r, nodes):
            return 0
        # New logical dab primary image: grab-class kernels re-base from the
        # stroke-start position each dab instead of accumulating (mirrors the
        # native harness). No-op for non-grab kernels.
        executor.setGrabAccumAdd(False)
        executor.execBrush(session.mesh(), brush_type, nodes, center_v, normal_v)
        if not executor.lastUniformValidationOk():
            return -1
        # applyDab clears this after every dab; these exec paths bypass it, so
        # without the clear the stroke re-runs its once-per-stroke work (uniform
        # validation, the BSMOOTH boundary-class refresh) on every dab.
        executor.clearIsFirstOfStep()
        count = len(sculptcore.BoundVector(mgr, nodes.ptr, nodes.bind_type))
    finally:
        for obj in (nodes, center_v, normal_v):
            obj.dispose()
    # After the node handles are released: updateQueries may split or merge
    # leaves, which invalidates them.
    _refresh_queries(session)
    return count


def apply_grab_dab(session, brush_type, anchor, cursor, normal, radius, accum_add=False):
    """Grab-class dab: deform the fixed region under `anchor` by the
    cumulative cursor delta (`brush.grabTo`/`grabFrom`). The dab centers on the
    anchor and the node filter widens by the drag distance so the anchored
    region stays covered as the cursor moves away — and, for an `@unbounded`
    kernel, by the field's own extent (see brush_policy.filter_radius).

    `accum_add` marks a later symmetry image of the same logical dab: False
    (the primary) begins a new logical dab and re-bases every touched vert from
    its stroke-start position; True adds this image's delta on top, so a vertex
    on a symmetry plane touched by two images sums both reflections."""
    mgr = engine.manager()
    executor = _ensure_executor(session)
    brush = session.brush_obj
    tree = session.tree()
    gf = brush.grabFrom.vec
    gt = brush.grabTo.vec
    drag = 0.0
    # The kernels consume grabTo as the cumulative drag *delta* (the grab
    # write-back re-bases each vert as orig + grabTo * falloff), not as the
    # absolute cursor point.
    for i in range(3):
        gf[i] = anchor[i]
        gt[i] = cursor[i] - anchor[i]
        drag += (cursor[i] - anchor[i]) ** 2
    drag = drag ** 0.5

    if session.last_stroke_grids:
        lib = engine.capi().lib
        if lib.GridStroke_supportsResolved(session.grid_ptr, int(brush_type), None):
            return lib.GridStroke_dabResolvedImage(
                session.grid_ptr, int(brush_type), *anchor, *normal, int(accum_add))
        if getattr(session, "generic_runtime", None) is not None:
            return -1
        # Grids-native anchored grab: the engine pins the first dab's leaf
        # region (radius + the @unbounded floor) — no drag widening needed.
        return engine.capi().lib.GridStroke_dab(
            session.grid_ptr, int(brush_type),
            anchor[0], anchor[1], anchor[2],
            normal[0], normal[1], normal[2], 1 if accum_add else 0)

    if executor.supportsResolved(brush_type):
        return engine.capi().lib.MeshStroke_dabResolvedImage(
            executor.ptr, int(brush_type), *anchor, *normal, int(accum_add))
    if getattr(session, "generic_runtime", None) is not None or not executor.preflightRaw(brush_type):
        return -1

    anchor_v = _float3(mgr, *anchor)
    normal_v = _float3(mgr, *normal)
    nodes = mgr.construct("litestl::util::Vector<sculptcore::spatial::SpatialNode*,4>")
    filter_r = brush_policy.filter_radius(brush_type, radius, brush, session, drag=drag)
    try:
        if not tree.filterNodes(anchor_v, filter_r, nodes):
            return 0
        executor.setGrabAccumAdd(accum_add)
        executor.execBrush(session.mesh(), brush_type, nodes, anchor_v, normal_v)
        if not executor.lastUniformValidationOk():
            return -1
        executor.clearIsFirstOfStep()
        import sculptcore
        count = len(sculptcore.BoundVector(mgr, nodes.ptr, nodes.bind_type))
    finally:
        for obj in (nodes, anchor_v, normal_v):
            obj.dispose()
    _refresh_queries(session)
    return count


def set_snake_hook_state(session, center, delta):
    """Write the snakehook kernel's ctx vectors for one dab image: `grabFrom` is
    the dab center, `grabTo` the drag step it should apply. The kernel drags
    by `grabTo` and gathers toward `grabFrom + grabTo`, so leaving these at their
    (0,0,0) defaults gathers every vert toward the object origin instead of
    hooking. Set before the dab, like apply_grab_dab's write."""
    brush = session.brush_obj
    gf = brush.grabFrom.vec
    gt = brush.grabTo.vec
    for i in range(3):
        gf[i] = center[i]
        gt[i] = delta[i]


def build_program(session, main_kernel, smooth_factor=0.0):
    """Build a program `[main]`, or `[main, BSMOOTH]` when `smooth_factor > 0`
    (autosmooth). Owned by the session and reused across dabs; also the dab
    unit for the dyntopo path (applyDab takes a program)."""
    mgr = engine.manager()
    if session.program is None:
        session.program = mgr.construct("sculptcore::brush::BrushProgram")
    prog = session.program
    prog.clear()
    prog.addCommand(main_kernel)
    if smooth_factor > 0.0:
        smooth = int(mgr.get("sculptcore::brush::SculptBrushes").items["BSMOOTH"])
        idx = prog.addCommand(smooth)
        # Pin the chained smooth to non-inverted: it shares the Brush with the
        # main command, so a Ctrl-inverted dab would otherwise negate the
        # smooth strength too — an anti-Laplacian that explodes the mesh.
        prog.setCommandInvert(idx, False)
        # BrushProp::Strength == 0. The runtime can't marshal a string arg into
        # a util::string method param, so the smooth strength is overridden by
        # propId, not by name (setCommandFloatByName).
        if session.generic_runtime is not None:
            from sculptcore.brush_properties import set_command_scalar
            set_command_scalar(mgr, prog, idx, 'strength', 0, float(smooth_factor))
        else:
            prog.setCommandFloat(idx, 0, smooth_factor)
    return prog


def apply_dab_program(session, program, center, normal, radius, kernel=None, *, grab_add=False):
    """Run a BrushProgram (e.g. [main, BSMOOTH]) for one dab. ``kernel`` is the
    program's main kernel, used only to size the node filter (the chained
    BSMOOTH is never unbounded)."""
    import sculptcore

    if session.last_stroke_grids:
        # Grids-native program dab: one engine call runs every entry over one
        # shared node query (the engine widens it to the entries' field radii).
        lib = engine.capi().lib
        if lib.GridStroke_supportsResolved(session.grid_ptr, 0, program.ptr):
            return lib.GridStroke_dabProgramResolved(session.grid_ptr, program.ptr, *center, *normal)
        if session.generic_runtime is not None:
            return -1
        return lib.GridStroke_dabProgram(
            session.grid_ptr, program.ptr,
            center[0], center[1], center[2],
            normal[0], normal[1], normal[2])

    mgr = engine.manager()
    executor = _ensure_executor(session)
    tree = session.tree()
    if executor.supportsResolvedProgram(program):
        if grab_add:
            return engine.capi().lib.MeshStroke_dabProgramResolvedImage(
                executor.ptr, program.ptr, *center, *normal, 1)
        return engine.capi().lib.MeshStroke_dabProgramResolved(executor.ptr, program.ptr, *center, *normal)
    if getattr(session, "generic_runtime", None) is not None or not executor.preflightRawProgram(program):
        return -1
    center_v = _float3(mgr, *center)
    normal_v = _float3(mgr, *normal)
    nodes = mgr.construct("litestl::util::Vector<sculptcore::spatial::SpatialNode*,4>")
    filter_r = brush_policy.filter_radius(kernel, radius, session.brush_obj, session)
    try:
        if not tree.filterNodes(center_v, filter_r, nodes):
            return 0
        executor.setGrabAccumAdd(False)
        executor.execProgram(program, nodes, center_v, normal_v)
        if not executor.lastUniformValidationOk():
            return -1
        executor.clearIsFirstOfStep()
        count = len(sculptcore.BoundVector(mgr, nodes.ptr, nodes.bind_type))
    finally:
        for obj in (nodes, center_v, normal_v):
            obj.dispose()
    _refresh_queries(session)
    return count


def preflight_preview(session, kernel, program, center=None, normal=None):
    """Validate prepared settings before discarding the previous valid preview."""
    import math
    if any(vector is not None and not all(math.isfinite(value) for value in vector)
           for vector in (center, normal)):
        return False
    executor = _ensure_executor(session)
    supported = executor.supportsResolvedProgram(program) if program is not None else executor.supportsResolved(kernel)
    if not supported:
        if getattr(session, "generic_runtime", None) is not None:
            return False
        return executor.preflightRawProgram(program) if program is not None else executor.preflightRaw(kernel)
    import numpy as np
    lib = engine.capi().lib
    empty = np.empty(0, dtype=np.float32)
    function = lib.MeshStroke_dabBatchProgramInputs if program is not None else lib.MeshStroke_dabBatchInputs
    target = program.ptr if program is not None else int(kernel)
    return function(executor.ptr, session.tree_ptr, session.mesh_ptr, session.brush_obj.ptr,
                    target, 0, empty, session.brush_obj.strength, empty, 1, empty, 0, 1) >= 0
