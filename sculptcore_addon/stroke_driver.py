# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
The engine's C++ ``BrushStrokeDriver`` as the addon's stroke sampler.

Owns the driver object and the Blender -> driver view conversion; nothing else
in the addon should know about ``setViewRow`` conventions or the driver's
top-left screen origin. The addon feeds raw pointer events in and gets evenly
spaced dab points back out, replacing ``StrokeSpacer`` + ``stroke_math``
(scene toggle ``sculptcore_cpp_stroke_driver``; see ``stroke._dab_at``).

Two conventions differ from Blender and are absorbed here:

- The driver's ``Mat4`` is **row-vector** (path.ux convention), so mathutils
  matrices are transposed on the way in.
- ``StrokeView::project``/``unproject`` put the screen origin at the **top
  left**, while ``event.mouse_region_y`` counts from the bottom. Events are
  y-flipped on the way in and emitted samples flipped back on the way out, so
  callers only ever see Blender region coordinates.

**The driver runs as a pure spacer here.** It is constructed with the no-arg
form, so its internal ``rayCast`` always misses and every emitted sample is
re-raycast host-side by ``stroke._apply_spaced_dab`` (which already routes
multires sessions through the GridTree). Letting the driver raycast would need
a synthetic far eye under orthographic views, and ``SpatialNode::castRay`` is
float32 throughout — a distant ray origin loses hit precision by construction.
This keeps plain-mesh and grids strokes on one code path and leaves the
driver's spline, arc-length walk and per-dab pressure interpolation as the
whole of what is adopted.
"""

from collections import namedtuple

from . import engine

# One emitted dab, copied out of the engine's DabSample before the next poll()
# clears the driver's output buffer. `screen` is an (x, y) pair in Blender's
# bottom-left region coordinates.
DabPoint = namedtuple("DabPoint", ("screen", "pressure", "invert"))

# StrokeSpaceMode.SCREEN / StrokeMethod.PATH, resolved once from the engine
# enums (the binding's item introspection walks descriptors and is too slow to
# repeat per stroke).
_MODE_IDS = None


def _mode_ids():
    global _MODE_IDS
    if _MODE_IDS is None:
        mgr = engine.manager()
        _MODE_IDS = (
            int(mgr.get("sculptcore::brush::StrokeSpaceMode").items["SCREEN"]),
            int(mgr.get("sculptcore::brush::StrokeMethod").items["PATH"]),
        )
    return _MODE_IDS


def make_driver():
    """A fresh screen-spaced PATH driver. The caller owns it and must
    ``dispose()`` it at stroke end."""
    mgr = engine.manager()
    driver = mgr.construct("sculptcore::brush::BrushStrokeDriver")
    space_mode, stroke_method = _mode_ids()
    driver.spaceMode = space_mode
    driver.strokeMethod = stroke_method
    # Spacing is measured in screen pixels, so the pushed radius is one too.
    driver.radiusIsWorld = False
    return driver


def push_view(driver, context):
    """Push the current view snapshot. Required before every ``poll()`` batch:
    ``StrokeView::unproject`` divides by ``viewSize``, so an unset view yields
    NaN rather than a stale-but-usable one."""
    region = context.region
    rv3d = context.region_data
    ob = context.active_object

    # Row-vector convention: transpose so setViewRow's row r is the driver's
    # m[r], i.e. mathutils' column r.
    render_mat = rv3d.perspective_matrix.transposed()
    obmat = ob.matrix_world.transposed()
    for row in range(4):
        driver.setViewRow(0, row, *render_mat[row])
        driver.setViewRow(1, row, *obmat[row])

    # The camera position the driver derives its view rays from. Under an
    # orthographic view there is no single eye point; the driver's rays are
    # unused here (it never raycasts), so the view matrix's origin stands in.
    eye = rv3d.view_matrix.inverted().translation
    clip_start = getattr(context.space_data, "clip_start", 0.01)
    driver.setViewParams(eye[0], eye[1], eye[2],
                         float(region.width), float(region.height),
                         float(region.width), float(region.height),
                         clip_start, True)


def push_event(driver, coord, region_height, pressure, invert, radius, spacing,
               tilt=(0.0, 0.0), twist=0.0):
    """Enqueue one pointer sample.

    ``coord`` is a Blender region ``(x, y)``; ``radius`` is the brush's pixel
    radius and ``spacing`` its spacing fraction (``brush.spacing / 100``) —
    together SCREEN mode's ``spacingDist = spacing * 2 * radius`` reproduces
    vanilla's ``radius * spacing / 50`` exactly. Strength is not read back, so
    a placeholder is pushed; the addon computes strength per dab itself."""
    driver.push(float(coord[0]), float(region_height) - float(coord[1]),
                float(pressure), float(tilt[0]), float(tilt[1]), float(twist),
                bool(invert), False, float(radius), 1.0, float(spacing))


def poll_dabs(driver, region_height):
    """Drain the driver and return this batch's dabs as a list of
    ``DabPoint``. Materialized rather than yielded: ``poll()`` clears the
    driver's sample buffer, so nothing may outlive the next call."""
    count = driver.poll()
    dabs = []
    for i in range(count):
        sample = driver.sampleAt(i)
        if sample is None:
            continue
        screen = sample.screenP.vec
        dabs.append(DabPoint(
            (float(screen[0]), float(region_height) - float(screen[1])),
            float(sample.pressure), bool(sample.invert)))
    return dabs


def flush_dabs(driver, region_height):
    """Signal pointer-up and drain the trailing spline segment (the one the
    driver's 1-segment lookahead was holding back)."""
    driver.end()
    return poll_dabs(driver, region_height)
