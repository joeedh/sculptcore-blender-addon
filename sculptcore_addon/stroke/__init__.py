# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The interactive stroke: a modal operator plus the reusable dab core the
operator and headless tests both drive, split by concern:

- ``operator``/``operator_apply``/``operator_preview`` -- the modal operator
  (``SCULPTCORE_OT_brush_stroke``), its plain/grab/batched dab application and
  its anchored/drag-dot preview-bracket application.
- ``session`` -- engine Brush/CommandExecutor lifecycle, grids-native
  capability checks, stroke begin/end.
- ``dab`` -- single-dab and dab-program application (plain and grab-class).
- ``dyntopo`` -- dynamic-topology cadence and remesh-dab dispatch.
- ``raycast`` -- view-ray unprojection and casting against the engine tree.
- ``spacer`` -- ``StrokeSpacer``, the screen-space dab-spacing state machine.
- ``_util``/``_draw`` -- tiny leaf helpers (float3 construction, the
  viewport-frame counter the mid-stroke refresh cadence gates on).

Dabs are spaced along the 2D mouse path (interval = pixel radius x spacing /
50 — vanilla's percentage-of-diameter semantics, residual carried across
segments) and each spaced point is projected onto the surface, so stroke
density is independent of both the mouse event rate and the surface deforming
under the stroke. The spacing walk is the Python StrokeSpacer below; behind
the ``sculptcore_cpp_dab_loop`` scene toggle the emitted points of a plain
spaced stroke are then resolved and applied engine-side, batched per pointer
event (``_apply_batch``), instead of looped per dab through Python.
The viewport updates through the external draw provider; the Mesh ID is
written back lazily by the mode's flush callback (memfile encode / save /
render), keeping dabs and stroke release free of the full Mesh write. The
throttled Mesh flush remains only as the no-provider fallback. The dab core
is engine-only (no ``bpy`` state), so ``enter -> N synthetic dabs -> exit``
is scriptable end-to-end.

Every name below is re-exported at the package level so ``stroke.foo`` keeps
working exactly as it did when this was a single flat module.
"""

from .spacer import StrokeSpacer
from .session import (
    _ensure_brush, _ensure_executor, _grid_session, grids_capable, program_grids_capable,
    stroke_begin, stroke_end, toggle_kernel_name
)
from .dyntopo import (
    DYNTOPO_EDGE_MIN_FACTOR, _DYNTOPO_RELATIVE_SCALE, _DYNTOPO_REFINE_MODES, _refresh_queries,
    apply_dyntopo_dab, build_dyntopo_params, configure_dyntopo_params, dyntopo_due,
    dyntopo_max_edge, smooth_iteration_strengths
)
from .dab import (
    apply_dab, apply_dab_program, apply_grab_dab, build_program, preflight_preview,
    set_snake_hook_state
)
from .raycast import (
    _coord_on_plane, _cursor_on_anchor_plane, _pixel_to_world_length, _ray_from_coord,
    _ray_from_event, _ray_origin_dir, _world_radius, raycast
)
from .operator import SCULPTCORE_OT_brush_stroke, register, unregister

__all__ = (
    "StrokeSpacer",
    "_ensure_brush", "_ensure_executor", "_grid_session", "grids_capable",
    "program_grids_capable", "stroke_begin", "stroke_end", "toggle_kernel_name",
    "DYNTOPO_EDGE_MIN_FACTOR", "_DYNTOPO_RELATIVE_SCALE", "_DYNTOPO_REFINE_MODES",
    "_refresh_queries", "apply_dyntopo_dab", "build_dyntopo_params", "configure_dyntopo_params",
    "dyntopo_due", "dyntopo_max_edge", "smooth_iteration_strengths",
    "apply_dab", "apply_dab_program", "apply_grab_dab", "build_program", "preflight_preview",
    "set_snake_hook_state",
    "_coord_on_plane", "_cursor_on_anchor_plane", "_pixel_to_world_length", "_ray_from_coord",
    "_ray_from_event", "_ray_origin_dir", "_world_radius", "raycast",
    "SCULPTCORE_OT_brush_stroke", "register", "unregister",
)
