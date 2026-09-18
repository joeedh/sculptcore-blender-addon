# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later

"""Immutable device samples and acquisition-time derivatives for a stroke."""

from dataclasses import dataclass
import math


def _finite(value, low, high):
    value = float(value)
    return min(high, max(low, value)) if math.isfinite(value) else None


@dataclass(frozen=True)
class InputSample:
    pressure: float | None = None
    tilt_x: float | None = None
    tilt_y: float | None = None
    speed: float | None = None
    time: float | None = None
    invert: bool = False

    @property
    def channels(self):
        return (self.pressure, self.tilt_x, self.tilt_y, self.speed)

    def upload(self, brush):
        brush.clearDeviceInputs()
        for device, value in enumerate(self.channels):
            if value is not None:
                brush.pushDeviceInput(device, value)

    def batch_row(self):
        """Four normalized values followed by their exact small integer presence mask."""
        mask = sum(1 << i for i, value in enumerate(self.channels) if value is not None)
        return tuple(0.0 if value is None else value for value in self.channels) + (mask,)

    @staticmethod
    def interpolate(a, b, fraction):
        fraction = min(1.0, max(0.0, fraction))

        def mix(x, y):
            return None if x is None or y is None else x + (y - x) * fraction

        return InputSample(
            mix(a.pressure, b.pressure), mix(a.tilt_x, b.tilt_x), mix(a.tilt_y, b.tilt_y),
            b.speed if a.time is not None and b.time is not None else None,
            mix(a.time, b.time), b.invert,
        )


class InputSampler:
    def __init__(self, speed_reference=1000.0):
        self.speed_reference = float(speed_reference)
        if not math.isfinite(self.speed_reference) or self.speed_reference <= 0:
            raise ValueError("Speed reference must be finite and positive")
        self._anchor = None

    def read(self, event, coord, invert=False):
        # A redraw-generated move must not change spacing or derivative history.
        if not getattr(event, "is_input_sample", True):
            return None
        tablet = bool(event.is_tablet)
        pressure = 1.0 if not tablet else (
            _finite(event.pressure, 0.0, 1.0) if getattr(event, "has_pressure", True) else None)
        tilt = event.tilt if tablet else (0.0, 0.0)
        axes = []
        for index, name in enumerate(("has_tilt_x", "has_tilt_y")):
            value = _finite(tilt[index], -1.0, 1.0) if tablet and getattr(event, name, False) else None
            axes.append(None if value is None else (value + 1.0) * 0.5)
        time = float(event.time) if getattr(event, "has_time", False) else None
        if time is not None and (not math.isfinite(time) or time < 0):
            time = None
        speed = None
        if time is None:
            self._anchor = None
        elif self._anchor is None:
            speed = 0.0
            self._anchor = (tuple(coord), time)
        else:
            previous, previous_time = self._anchor
            if time <= previous_time:
                # Do not interpolate a segment through an invalid time transition.
                time = None
                self._anchor = None
            else:
                speed = min(1.0, math.dist(previous, coord) / (time - previous_time) / self.speed_reference)
                self._anchor = (tuple(coord), time)
        return InputSample(pressure, *axes, speed, time, bool(invert))
