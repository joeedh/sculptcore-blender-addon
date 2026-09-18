# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stable definitions and validated immutable scalar/stack descriptions, independent of Blender."""

from dataclasses import dataclass
import math
import re
import struct
from types import MappingProxyType

DEVICE_TYPES = ('PRESSURE', 'TILT_X', 'TILT_Y', 'SPEED')
CURVE_PRESET_ARITY = MappingProxyType({
    'LINEAR': 0, 'ROOT': 0, 'SQUARE': 0, 'SMOOTHSTEP': 0,
    'SMOOTHERSTEP': 0, 'SPHERE': 0, 'POW4': 0, 'INVSQUARE': 0,
    'CONSTANT': 1, 'TWO_STEP': 3,
})


class PropertyError(ValueError):
    """An authoring request or stored description violates the v1 contract."""


class UnknownDefinition(PropertyError):
    pass


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def scalar(kind, value):
    if kind == 'BOOL':
        if type(value) is not bool:
            raise PropertyError("Boolean values must be bool")
        return value
    if kind == 'INT32':
        if type(value) is not int or not -2147483648 <= value <= 2147483647:
            raise PropertyError("Integer values must fit signed int32")
        return value
    if kind != 'FLOAT32' or not finite(value):
        raise PropertyError("Expected a finite scalar with a supported type")
    try:
        result = struct.unpack('f', struct.pack('f', value))[0]
    except (OverflowError, struct.error):
        raise PropertyError("Float value is outside float32 storage") from None
    if not math.isfinite(result):
        raise PropertyError("Float value is outside float32 storage")
    return result


@dataclass(frozen=True)
class Position:
    location: str
    sort_index: int = 0

    def __post_init__(self):
        if type(self.location) is not str or not self.location or '\0' in self.location:
            raise PropertyError("Positions require a nonempty location without NUL")
        try:
            encoded = self.location.encode('utf-8')
        except UnicodeError:
            raise PropertyError("Position location must be valid UTF-8") from None
        if len(encoded) > 1024 or type(self.sort_index) is not int:
            raise PropertyError("Positions require a stable location and integer sort index")
        scalar('INT32', self.sort_index)


def validated_positions(positions):
    positions = tuple(positions)
    if len(positions) > 128 or any(type(position) is not Position for position in positions):
        raise PropertyError("Expected at most 128 immutable positions")
    positions = tuple(Position(position.location, position.sort_index) for position in positions)
    if len({position.location for position in positions}) != len(positions):
        raise PropertyError("A property can appear only once per UI location")
    return positions


@dataclass(frozen=True)
class ResponseCurve:
    """Generated curve descriptor; carries no saved mapping."""

    preset: str = 'LINEAR'
    parameters: tuple = ()

    def __post_init__(self):
        parameters = tuple(self.parameters)
        object.__setattr__(self, "parameters", parameters)
        if self.preset not in CURVE_PRESET_ARITY or len(parameters) != CURVE_PRESET_ARITY[self.preset]:
            raise PropertyError("Unknown curve descriptor or incorrect parameter count")
        if any(not finite(value) for value in parameters):
            raise PropertyError("Curve parameters must be finite")
        if self.preset == 'TWO_STEP' and not 0 <= parameters[0] <= 1:
            raise PropertyError("Step threshold must be in [0, 1]")


@dataclass(frozen=True)
class CustomCurveReference:
    """Operation-scoped identity; reconstruct from the destination owner, never serialize."""

    owner_identity: tuple
    identifier: str
    device: str
    bank_generation: int
    declaration_key: int
    mapping_key: tuple

    def __post_init__(self):
        if (type(self.owner_identity) is not tuple or len(self.owner_identity) != 4
                or any(type(self.owner_identity[index]) is not int for index in (0, 1, 3))
                or self.owner_identity[0] <= 0 or self.owner_identity[3] <= 0
                or type(self.owner_identity[2]) is not str or self.owner_identity[2] not in ('BRUSH', 'SCENE')
                or type(self.identifier) is not str or not self.identifier
                or type(self.device) is not str or self.device not in DEVICE_TYPES
                or type(self.bank_generation) is not int or self.bank_generation <= 0
                or type(self.declaration_key) is not int or self.declaration_key <= 0
                or type(self.mapping_key) is not tuple or len(self.mapping_key) != 2
                or any(type(value) is not int or value <= 0 for value in self.mapping_key)):
            raise PropertyError("Malformed custom mapping reference")


@dataclass(frozen=True)
class NativeCurveReference:
    """Canonical native mapping data and current capability-selected flag path."""

    owner_identity: tuple
    identifier: str
    device: str
    path: str
    enable_path: str
    mapping_key: bytes

    def __post_init__(self):
        if (type(self.owner_identity) is not tuple or len(self.owner_identity) != 4
                or self.owner_identity[2] != 'BRUSH'
                or any(type(self.owner_identity[i]) is not int for i in (0, 1, 3))
                or self.owner_identity[0] <= 0 or self.owner_identity[3] <= 0
                or self.identifier not in ('sculptcore.brush.strength', 'sculptcore.brush.size')
                or self.device != 'PRESSURE' or type(self.mapping_key) is not bytes or not self.mapping_key
                or self.path not in ('curve_strength', 'curve_size')
                or self.enable_path not in ('use_pressure_strength', 'use_pressure_size',
                                            'sculptcore_use_pressure_strength', 'sculptcore_use_pressure_size')):
            raise PropertyError("Malformed native curve reference")


@dataclass(frozen=True)
class DeviceLayer:
    device: str
    enabled: bool = True
    operation: str = 'MULTIPLY'
    factor: float = 1.0
    curve: ResponseCurve | CustomCurveReference | NativeCurveReference = ResponseCurve()

    def __post_init__(self):
        if self.device not in DEVICE_TYPES:
            raise PropertyError("Device input is unavailable in v1")
        if type(self.enabled) is not bool or self.operation not in (
                'REPLACE', 'MULTIPLY', 'ADD', 'SUBTRACT', 'DIFFERENCE'):
            raise PropertyError("Invalid device enable state or mix operation")
        if not finite(self.factor) or not 0 <= self.factor <= 1:
            raise PropertyError("Mix factor must be finite in [0, 1]")
        if type(self.curve) not in (ResponseCurve, CustomCurveReference, NativeCurveReference):
            raise PropertyError("Expected an immutable curve descriptor")
        if type(self.curve) in (CustomCurveReference, NativeCurveReference) and self.curve.device != self.device:
            raise PropertyError("Custom mapping device differs from its layer")


def validated_stack(layers):
    layers = tuple(layers)
    if any(type(layer) is not DeviceLayer for layer in layers):
        raise PropertyError("Invalid device layer")
    if len({layer.device for layer in layers}) != len(layers):
        raise PropertyError("Duplicate input device; imported data requires explicit repair")
    return layers


@dataclass(frozen=True)
class Definition:
    identifier: str
    label: str
    scalar_type: str
    default: object
    minimum: float
    maximum: float
    soft_minimum: float
    soft_maximum: float
    description: str = ""
    unit: str = 'NONE'
    dynamic: bool = True
    owners: frozenset = frozenset(('BRUSH', 'SCENE'))
    positions: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "owners", frozenset(self.owners))
        object.__setattr__(self, "positions", validated_positions(self.positions))
        if not isinstance(self.identifier, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", self.identifier):
            raise PropertyError("Definition requires a stable identifier")
        if (not isinstance(self.label, str) or not self.label or not isinstance(self.description, str)
                or not isinstance(self.unit, str) or type(self.dynamic) is not bool
                or not self.owners or not self.owners <= {'BRUSH', 'SCENE'}):
            raise PropertyError("Invalid label, dynamics or owner capability")
        bounds = (self.minimum, self.soft_minimum, self.soft_maximum, self.maximum)
        if any(not finite(value) for value in bounds) or tuple(sorted(bounds)) != bounds:
            raise PropertyError("Invalid hard/soft limits")
        if self.scalar_type == 'INT32' and (math.ceil(self.minimum) > math.floor(self.maximum)
                                          or self.minimum < -2147483648 or self.maximum > 2147483647):
            raise PropertyError("Invalid integer domain")
        if self.scalar_type == 'BOOL' and (self.minimum < 0 or self.maximum > 1):
            raise PropertyError("Invalid boolean domain")
        object.__setattr__(self, "default", self.validate(self.default))

    def validate(self, value):
        converted = scalar(self.scalar_type, value)
        if not self.minimum <= value <= self.maximum or not self.minimum <= converted <= self.maximum:
            raise PropertyError("Value is outside the definition's range")
        return converted


class Registry:
    def __init__(self):
        self._definitions = {}
        self._revision = 0

    @property
    def revision(self):
        return self._revision

    def register(self, definition):
        if type(definition) is not Definition:
            raise PropertyError("Expected an immutable definition")
        old = self._definitions.get(definition.identifier)
        if old is not None:
            if old != definition:
                raise PropertyError("Conflicting definition for " + definition.identifier)
            return old
        self._definitions[definition.identifier] = definition
        self._revision += 1
        return definition

    def get(self, identifier):
        try:
            return self._definitions[identifier]
        except KeyError:
            raise UnknownDefinition(identifier) from None

    def definitions(self):
        return tuple(self._definitions[key] for key in sorted(self._definitions))
