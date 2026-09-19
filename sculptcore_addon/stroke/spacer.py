# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Screen-space dab spacing along the mouse path (``StrokeSpacer``)."""

from .. import stroke_input, stroke_math


class StrokeSpacer:
    """Screen-space dab spacer: buffers the 2D mouse path and emits evenly
    spaced points along a centripetal Catmull-Rom spline (``stroke_math``),
    carrying the walk position across segments so cadence never clusters at a
    joint. Compared to the old linear-polyline walk this smooths jittery input
    (the parity route to Blender's stabilized stroke) without changing dab
    density: the same interval (the operator's vanilla-matched spacing) is
    walked, and each emitted point is still projected onto the surface by the
    operator.

    The first control point emits one raw dab immediately; a 1-segment lookahead
    holds each interior segment until its right neighbor arrives (the
    centripetal tangent needs the next point), so spline dabs lag input by one
    move; the trailing segment is flushed with a right-clamp on release
    (``flush``). A non-positive interval bypasses the spline and emits every
    input point. Supplying samples returns ``(point, sample)`` pairs; otherwise
    emitted points are ``(x, y)`` tuples."""

    def __init__(self):
        self.points = []
        self.inputs = []
        self.walk_carry = 0.0
        self._flushed = False

    def add(self, p, spacing, sample=None):
        """Dab points for the newly arrived control point ``p`` (an ``(x, y)``
        pair). The first call emits ``p`` itself (raw); later calls emit the
        spaced points of the segment whose right neighbor ``p`` just
        completed."""
        p = (float(p[0]), float(p[1]))
        if self.inputs and (sample is None) != (self.inputs[0] is None):
            raise ValueError("A spacer cannot mix sampled and position-only inputs")
        self.points.append(p)
        self.inputs.append(sample)
        self._flushed = False
        n = len(self.points)
        if n == 1 or spacing <= 0.0:
            return [(p, sample)] if sample is not None else [p]
        if n < 3:
            # The first segment still lacks the right neighbor its tangent needs.
            return []
        # points[n-3] -> points[n-2], with right neighbor points[n-1] = p.
        return self._walk_segment(n - 3, right_clamp=False, spacing=spacing)

    def flush(self, spacing):
        """Emit the trailing segment (the last two points) with a right-clamp,
        on stroke release. No-op for a single-point stroke or non-positive
        spacing."""
        n = len(self.points)
        if self._flushed or n < 2 or spacing <= 0.0:
            return []
        self._flushed = True
        return self._walk_segment(n - 2, right_clamp=True, spacing=spacing)

    def _walk_segment(self, i, right_clamp, spacing):
        """Arc-length-walk the Catmull-Rom segment ``points[i] -> points[i+1]``,
        clamping the outer control points at the path ends."""
        pts = self.points
        p1, p2 = pts[i], pts[i + 1]
        p0 = pts[i - 1] if i >= 1 else p1
        p3 = p2 if right_clamp else pts[i + 2]
        bez = stroke_math.cr_to_bezier(p0, p1, p2, p3)
        sampled = self.inputs[i] is not None
        emitted, self.walk_carry = stroke_math.arc_length_walk(
            bez, spacing, self.walk_carry, with_fractions=sampled)
        if sampled:
            emitted = [(point, stroke_input.InputSample.interpolate(self.inputs[i], self.inputs[i + 1], fraction))
                       for point, fraction in emitted]
        return emitted
