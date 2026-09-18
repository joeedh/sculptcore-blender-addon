# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Canonical generated responses and immutable engine-ready response descriptions."""
from dataclasses import dataclass
import math

from .registry import PropertyError, ResponseCurve, finite, scalar


def evaluate(curve, x):
    """Evaluate the frozen response formulas on normalized device input."""
    if type(curve) is not ResponseCurve or not finite(x):
        raise PropertyError("Expected a generated response and finite input")
    curve = ResponseCurve(curve.preset, curve.parameters)
    x = min(1.0, max(0.0, x))
    name, parameters = curve.preset, curve.parameters
    if name == 'CONSTANT':
        return parameters[0]
    if name == 'TWO_STEP':
        threshold, low, high = parameters
        return low if x < threshold else high
    if name == 'LINEAR':
        return x
    if name == 'ROOT':
        return math.sqrt(x)
    if name == 'SQUARE':
        return x * x
    if name == 'SMOOTHSTEP':
        return x * x * (3.0 - 2.0 * x)
    if name == 'SMOOTHERSTEP':
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)
    if name == 'SPHERE':
        return math.sqrt(max(0.0, 2.0 * x - x * x))
    if name == 'POW4':
        return x * x * x * x
    if name == 'INVSQUARE':
        return x * (2.0 - x)
    raise PropertyError("Unknown response preset")


@dataclass(frozen=True)
class SampleConfig:
    count: int = 256
    reverse: bool = False
    clamp_output: bool = False
    hardness: float = 0.0

    def __post_init__(self):
        if (type(self.count) is not int or not 2 <= self.count <= 65536
                or type(self.reverse) is not bool or type(self.clamp_output) is not bool
                or not finite(self.hardness) or not 0 <= self.hardness <= 1):
            raise PropertyError("Invalid response sampling configuration")


@dataclass(frozen=True)
class PreparedResponse:
    """TABLE samples or an analytic CONSTANT/TWO_STEP; no saved mapping or owner."""
    kind: str
    samples: tuple = ()
    parameters: tuple = ()

    def __post_init__(self):
        if type(self.samples) is not tuple or type(self.parameters) is not tuple:
            raise PropertyError("Prepared responses must be immutable")
        if self.kind == 'TABLE':
            if self.parameters or not 2 <= len(self.samples) <= 65536:
                raise PropertyError("Invalid response table")
            for value in self.samples:
                if scalar('FLOAT32', value) != value:
                    raise PropertyError("Response samples must be float32")
        elif self.kind in ('CONSTANT', 'TWO_STEP') and not self.samples:
            ResponseCurve(self.kind, self.parameters)
        else:
            raise PropertyError("Invalid prepared response")

    def evaluate(self, x):
        if not finite(x):
            raise PropertyError("Expected finite response input")
        if self.kind != 'TABLE':
            return evaluate(ResponseCurve(self.kind, self.parameters), x)
        x = min(1.0, max(0.0, x)) * (len(self.samples) - 1)
        index = min(int(x), len(self.samples) - 2)
        factor = x - index
        return self.samples[index] * (1.0 - factor) + self.samples[index + 1] * factor


def sample(function, config):
    """Bake at synchronization time; preserve legacy falloff hardness ordering."""
    if type(config) is not SampleConfig:
        raise PropertyError("Expected a sampling configuration")
    values = []
    for index in range(config.count):
        x = index / (config.count - 1)
        distance = 1.0 - x
        if config.hardness == 1:
            value = 1.0 if distance < 1 else 0.0
        elif config.hardness > 0 and distance < config.hardness:
            value = 1.0
        else:
            if config.hardness:
                x = 1.0 - (distance - config.hardness) / (1.0 - config.hardness)
            value = function(1.0 - x if config.reverse else x)
        if not finite(value):
            raise PropertyError("Curve produced a nonfinite sample")
        if config.clamp_output:
            value = min(1.0, max(0.0, value))
        values.append(scalar('FLOAT32', value))
    return tuple(values)
