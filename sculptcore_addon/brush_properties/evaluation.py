# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Typed host evaluation for spacing, smooth passes and other scalar consumers.

Compile at synchronization; evaluate only immutable data per dab. This does not
authorize an execution path or install native stacks. Consumers must avoid applying
the same stack again after using an evaluated result.
"""
from dataclasses import dataclass
import math
import struct

from .adapters import SIZE, STRENGTH, ValueDomain
from .registry import DEVICE_TYPES, Definition, PropertyError, finite
from .snapshots import PropertySnapshot

FLOAT_MAX = 3.4028234663852886e38
SPACING = 'sculptcore.brush.spacing'
SNAKE_PINCH = 'sculptcore.brush.snake_pinch'
_DEVICE_INDEX = {name: index for index, name in enumerate(DEVICE_TYPES)}


def _f32(value):
    try:
        return struct.unpack('f', struct.pack('f', value))[0]
    except (OverflowError, struct.error):
        return math.copysign(math.inf, value)


def _adjacent(value, upward):
    if value == 0:
        return struct.unpack('f', struct.pack('I', 1 if upward else 0x80000001))[0]
    bits = struct.unpack('I', struct.pack('f', value))[0]
    bits += 1 if (value > 0) == upward else -1
    return struct.unpack('f', struct.pack('I', bits))[0]


def typed_bounds(domain):
    """Intersect metadata with its representable stored values before clamping."""
    if type(domain) not in (Definition, ValueDomain):
        raise PropertyError("Expected an immutable scalar domain")
    kind = domain.kind if type(domain) is ValueDomain else domain.scalar_type
    low, high = domain.minimum, domain.maximum
    if not finite(low) or not finite(high) or low > high:
        raise PropertyError("Invalid scalar domain")
    if kind == 'FLOAT32':
        low, high = max(low, -FLOAT_MAX), min(high, FLOAT_MAX)
        if low > high:
            raise PropertyError("Empty representable scalar domain")
        rounded_low, rounded_high = _f32(low), _f32(high)
        low = _adjacent(rounded_low, True) if rounded_low < low else rounded_low
        high = _adjacent(rounded_high, False) if rounded_high > high else rounded_high
    elif kind in ('INT32', 'BOOL'):
        limits = (-2147483648, 2147483647) if kind == 'INT32' else (0, 1)
        low, high = math.ceil(max(low, limits[0])), math.floor(min(high, limits[1]))
    else:
        raise PropertyError("Unsupported scalar domain")
    if low > high:
        raise PropertyError("Empty representable scalar domain")
    return kind, low, high


def _inputs(channels):
    channels = tuple(channels)
    if len(channels) != 4 or any(value is not None and type(value) not in (float, int) for value in channels):
        raise PropertyError("Expected four optional numeric device channels")
    result = []
    for value in channels:
        # Native transport narrows before input presence and response clamping.
        value = _f32(value) if value is not None and finite(value) else None
        result.append(value if value is not None and math.isfinite(value) else None)
    return tuple(result)


def _response(response, sample, real):
    if response.kind == 'CONSTANT':
        return real(response.parameters[0])
    x = 0.0 if sample < 0 else 1.0 if sample > 1 else sample
    if response.kind == 'TWO_STEP':
        threshold, low, high = response.parameters
        return real(low if x < threshold else high)
    values = response.samples
    x = real(real(x) * real(len(values) - 1))
    index = int(x)
    if index >= len(values) - 1:
        return real(values[-1])
    factor = real(x - real(index))
    return real(real(real(values[index]) * real(1.0 - factor)) + real(real(values[index + 1]) * factor))


def _apply(value, layer, sample, real):
    response = _response(layer.response, sample, real)
    if not math.isfinite(response):
        return value
    if layer.operation == 'MULTIPLY':
        combined = real(value * response)
    elif layer.operation == 'ADD':
        combined = real(value + response)
    elif layer.operation == 'SUBTRACT':
        combined = real(value - response)
    elif layer.operation == 'DIFFERENCE':
        combined = real(value - response if value > response else response - value)
    else:
        combined = response
    if not math.isfinite(combined):
        return value
    result = real(value + real(real(combined - value) * real(layer.factor)))
    return result if math.isfinite(result) else value


@dataclass(frozen=True)
class ScalarEvaluator:
    """Compile a validated snapshot once, without retaining any authoring owner."""
    snapshot: PropertySnapshot

    def __post_init__(self):
        if type(self.snapshot) is not PropertySnapshot:
            raise PropertyError("Expected a validated immutable property snapshot")
        domain = (('FLOAT32', 0.0, FLOAT_MAX) if self.snapshot.definition.identifier == SIZE
                  else typed_bounds(self.snapshot.value_domain))
        object.__setattr__(self, '_domain', domain)
        object.__setattr__(self, '_layers', tuple((_DEVICE_INDEX[layer.device], layer)
                                               for layer in self.snapshot.stack))

    def evaluate(self, channels, *, projected_radius=None):
        is_size = self.snapshot.definition.identifier == SIZE
        if is_size:
            if not finite(projected_radius) or not 0 <= projected_radius <= FLOAT_MAX:
                raise PropertyError("Semantic size requires a finite projected object-space radius")
            base = _f32(projected_radius)
        else:
            if projected_radius is not None:
                raise PropertyError("Projected radius is only valid for semantic size")
            base = self.snapshot.value
        inputs = _inputs(channels)
        kind, low, high = self._domain
        real = _f32 if kind == 'FLOAT32' else float
        value, applied = real(base), False
        for device, layer in self._layers:
            if layer.enabled and inputs[device] is not None:
                value = _apply(value, layer, inputs[device], real)
                applied = True
        if not applied and low <= base <= high:
            return base
        value = low if value < low else high if value > high else value
        if kind == 'INT32':
            return math.floor(value + .5) if value >= 0 else math.ceil(value - .5)
        if kind == 'BOOL':
            return value >= .5
        return value

    def engine_value(self, channels, *, projected_radius=None, strength_scale=1.0):
        """Convert only after typed semantic evaluation; SIZE already uses radius."""
        identifier = self.snapshot.definition.identifier
        value = self.evaluate(channels, projected_radius=projected_radius)
        return to_engine(identifier, value, strength_scale=strength_scale)


def to_engine(identifier, value, *, strength_scale=1.0):
    """Translate an already evaluated typed scalar from host or native evaluation."""
    if not finite(strength_scale) or strength_scale < 0 or (identifier != STRENGTH and strength_scale != 1):
        raise PropertyError("Only strength accepts finite nonnegative family/overlap compensation")
    if identifier == SPACING:
        if type(value) is not int:
            raise PropertyError("Native spacing requires integer percent")
        value = _f32(value / 100.0)
    elif identifier == SNAKE_PINCH:
        value = _f32(2.0 * _f32(.5 - value))
    elif identifier == STRENGTH:
        value = _f32(value * strength_scale)
    if not math.isfinite(value):
        raise PropertyError("Engine unit conversion overflowed")
    return value
