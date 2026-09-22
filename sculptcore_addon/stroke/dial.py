# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The screen-space dial the Twist (rotate) brush reads its angle from: the
port of BLI_dial_2d. The angle is measured from the direction of the first
pointer position that leaves a threshold circle around the stroke start, so
the first few pixels of a drag do not spin the region through arbitrary
angles, and full turns are tracked so a drag past 180 degrees keeps winding
instead of snapping back."""

import math


class Dial:
    def __init__(self, center, threshold):
        self._center = (float(center[0]), float(center[1]))
        self._threshold_sq = float(threshold) ** 2
        self._initial = None
        self._last_angle = 0.0
        self._rotations = 0

    def angle(self, position):
        """The counter-clockwise angle (radians) swept from the initial
        direction to `position`, plus the accumulated full turns. Inside the
        threshold circle the last angle is returned unchanged."""
        dx = float(position[0]) - self._center[0]
        dy = float(position[1]) - self._center[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= self._threshold_sq:
            return self._last_angle + 2.0 * math.pi * self._rotations
        length = math.sqrt(length_sq)
        dx, dy = dx / length, dy / length
        if self._initial is None:
            self._initial = (dx, dy)
        ix, iy = self._initial
        # Signed angle from the initial direction to the current one (vanilla
        # measures current-to-initial and negates the result; same thing).
        angle = math.atan2(ix * dy - iy * dx, ix * dx + iy * dy)
        # Crossing the +-pi seam: the sign flips while the magnitude is past
        # pi/2, which a small step near zero never does.
        if angle * self._last_angle < 0.0 and abs(self._last_angle) > math.pi / 2.0:
            self._rotations += -1 if self._last_angle < 0.0 else 1
        self._last_angle = angle
        return angle + 2.0 * math.pi * self._rotations
