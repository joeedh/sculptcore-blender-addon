# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Dynamic-topology cadence and remesh-dab dispatch."""

from .. import engine
from ._util import _float3
from .session import _ensure_executor


def smooth_iteration_strengths(strength):
    """Vanilla smooth-brush semantics (#iteration_strengths): the strength
    (clamped to 1) maps to `int(strength * 4)` full-strength relaxation
    passes per dab plus one remainder pass, so higher strength iterates more
    instead of overshooting a single pass."""
    clamped = min(max(strength, 0.0), 1.0)
    count = int(clamped * 4)
    last = 4.0 * (clamped - count / 4.0)
    passes = [1.0] * count
    if last > 1e-4:
        passes.append(last)
    return passes


# Vanilla dyntopo detail constants (sculpt_dyntopo.hh).
DYNTOPO_EDGE_MIN_FACTOR = 0.4       # EDGE_LENGTH_MIN_FACTOR
_DYNTOPO_RELATIVE_SCALE = 0.4       # RELATIVE_SCALE_FACTOR

# Blender detail_refine_method -> engine DynTopoMode value.
_DYNTOPO_REFINE_MODES = {'SUBDIVIDE': 0, 'COLLAPSE': 1, 'SUBDIVIDE_COLLAPSE': 2}


def dyntopo_max_edge(sculpt, ob, world_radius, pixel_radius, pixel_size):
    """Object-space max edge length from Blender's dyntopo detail settings
    (ports #constant_to_detail_size / #brush_to_detail_size /
    #relative_to_detail_size). RELATIVE and BRUSH scale with the dab's world
    radius; CONSTANT/MANUAL are view-independent."""
    method = sculpt.detail_type_method
    if method in {'CONSTANT', 'MANUAL'}:
        # mat4_to_scale equivalent: the mean axis scale of the object matrix.
        scale_vector = ob.matrix_world.to_scale()
        scale = (abs(scale_vector[0]) + abs(scale_vector[1]) + abs(scale_vector[2])) / 3.0
        return 1.0 / (max(sculpt.constant_detail_resolution, 0.0001) * max(scale, 1e-8))
    if method == 'BRUSH':
        return world_radius * sculpt.detail_percent / 100.0
    return ((world_radius / max(pixel_radius, 1.0))
            * (sculpt.detail_size * pixel_size) / _DYNTOPO_RELATIVE_SCALE)


def configure_dyntopo_params(params, scene, refine_method):
    """Apply the per-scene remesher tuning (props.py) plus the refine method
    onto a DynTopoParams. An unset refine method (older files carry DNA
    flags 0, which RNA reads as '') falls back to the default Both."""
    params.mode = _DYNTOPO_REFINE_MODES.get(refine_method, 2)
    params.do_flips = scene.sculptcore_dyntopo_flips
    params.do_smooth = scene.sculptcore_dyntopo_smooth
    params.smooth_lambda = scene.sculptcore_dyntopo_smooth_lambda
    params.reproject_uvs = scene.sculptcore_reproject_uvs
    params.max_rounds = scene.sculptcore_dyntopo_max_rounds
    params.max_splits = scene.sculptcore_dyntopo_split_budget
    params.max_collapses = scene.sculptcore_dyntopo_collapse_budget


def build_dyntopo_params(session, l_max, l_min):
    """Reusable DynTopoParams (edge-length bounds in object space)."""
    mgr = engine.manager()
    if session.dtparams is None:
        session.dtparams = mgr.construct("sculptcore::dyntopo::DynTopoParams")
    p = session.dtparams
    p.l_max = l_max
    p.l_min = min(l_min, l_max * 0.5)
    return p


def dyntopo_due(stroke_s, last_dyntopo_s, spacing):
    """Whether a remesh is due at stroke arc-length ``stroke_s``: true once the
    stroke has travelled ``spacing`` since the last remesh at ``last_dyntopo_s``.
    A ``spacing`` of 0 is due on every dab (the every-dab baseline)."""
    return stroke_s - last_dyntopo_s >= spacing


def _refresh_queries(session):
    """The query-correctness half of the spatial update, run after every dab.

    The dab moved verts, which leaves every node bound it touched stale, and the
    node filter (and raycast, and picking) reads those bounds. A brush that
    carries geometry *out* of its own node bounds — snake hook and grab most
    of all — otherwise stalls the moment the tip leaves the region the tree
    still thinks it occupies: the next dab's filterNodes finds nothing and the
    stroke silently dies mid-drag.

    Deliberately not the full ``tree.update(gpu)``: the GPU-buffer half belongs
    once per frame in the draw path (convert.draw_refresh), not per dab."""
    session.tree().updateQueries()


def apply_dyntopo_dab(session, program, center, normal, radius, params, seed):
    """Run a program dab, validating supported prepared commands before remeshing.

    ``params=None`` skips remeshing between the host's scheduled topology passes.
    Other command capabilities retain the legacy ``applyDab`` route.
    """
    mgr = engine.manager()
    executor = _ensure_executor(session)
    if executor.supportsResolvedProgram(program):
        moved = engine.capi().lib.MeshStroke_dabProgramResolvedDyntopo(
            executor.ptr, program.ptr, *center, *normal, radius, params.ptr if params is not None else None, seed)
        if moved >= 0:
            _refresh_queries(session)
        return moved
    if getattr(session, "generic_runtime", None) is not None:
        return -1
    center_v = _float3(mgr, *center)
    normal_v = _float3(mgr, *normal)
    try:
        executor.setGrabAccumAdd(False)
        moved = executor.applyDab(program, center_v, normal_v, radius, params, seed)
    finally:
        center_v.dispose()
        normal_v.dispose()
    if moved >= 0:
        _refresh_queries(session)
    return moved
