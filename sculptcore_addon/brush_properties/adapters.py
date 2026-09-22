# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Authoritative native numeric settings; no engine loading or shadow values."""
from dataclasses import dataclass
from types import MappingProxyType

from .lifecycle import OwnerGuard
from .native import STRENGTH, STRENGTH_DEFINITION
from .native_v0 import ROWS
from .registry import Definition, Position, PropertyError, NativeCurveReference, scalar
from .resolver import Capability, ValueSource

SIZE = 'sculptcore.brush.size'
PIXELS = SIZE + '_pixels'
WORLD = SIZE + '_world'
SIZE_ALIASES = (PIXELS, WORLD)
CAVITY = 'sculptcore.brush.cavity'
SIZE_DEFINITION = Definition(SIZE, "Size", 'FLOAT32', 70.0, .0010000000474974513,
                             3.4028234663852886e38, 1.0, 1000.0,
                             "Native brush diameter in the selected size mode",
                             positions=(Position('VIEW3D_HEADER', 10), Position('BRUSH_SETTINGS', 10)))
DEFINITIONS = (STRENGTH_DEFINITION, SIZE_DEFINITION) + tuple(
    Definition(identifier, path.rsplit('.', 1)[-1].replace('_', ' ').title(), kind, default,
               minimum, maximum, soft_min, soft_max, description, dynamic=dynamic,
               positions=(Position('BRUSH_SETTINGS', 30 + index),))
    for index, (identifier, path, kind, default, minimum, maximum, soft_min, soft_max,
                description, dynamic) in enumerate(ROWS))
BY_ID = MappingProxyType({definition.identifier: definition for definition in DEFINITIONS})
PATHS = MappingProxyType({row[0]: row[1] for row in ROWS} | {STRENGTH: 'strength'})


def policy_identifier(identifier):
    if identifier in SIZE_ALIASES:
        return SIZE
    if identifier.startswith(CAVITY + '.'):
        return CAVITY + '.cavity_factor'
    return identifier


@dataclass(frozen=True)
class ValueDomain:
    kind: str
    minimum: float
    maximum: float
    soft_minimum: float
    soft_maximum: float
    unit: str
    path: str

    def validate(self, value):
        # The common semantic size may arrive as an exactly integral FLOAT32.
        if self.kind == 'INT32' and type(value) is float and value.is_integer():
            value = int(value)
        converted = scalar(self.kind, value)
        if not self.minimum <= value <= self.maximum or not self.minimum <= converted <= self.maximum:
            raise PropertyError("Value is outside the current native domain")
        return converted


@dataclass(frozen=True)
class SizeBlock:
    pixels: int
    world: float
    mode: str
    owner_identity: tuple


class NativeOwner:
    def __init__(self, owner, *, epoch=0):
        self._guard = OwnerGuard(owner, epoch=epoch)
        self.owner = owner
        self.kind = self._guard.kind

    def handles(self, identifier):
        self._guard.check()
        return (identifier in BY_ID and
                (self.kind == 'BRUSH' or identifier in (STRENGTH, SIZE, *SIZE_ALIASES)
                 or identifier.startswith(CAVITY + '.')))

    def settings(self):
        self._guard.check()
        if self.kind == 'BRUSH':
            return self.owner
        sculpt = self.owner.tool_settings.sculpt
        return sculpt.unified_paint_settings if sculpt is not None else None

    def cavity(self):
        self._guard.check()
        parent = self.owner if self.kind == 'BRUSH' else self.owner.tool_settings.sculpt
        return parent.mesh_automasking_settings if parent is not None else None

    def binding(self, identifier):
        if not self.handles(identifier):
            raise PropertyError("No authoritative native value binding")
        if identifier.startswith(CAVITY + '.'):
            parent, path = self.cavity(), PATHS[identifier].split('.', 1)[1]
        else:
            parent = self.settings() if identifier in (STRENGTH, SIZE, *SIZE_ALIASES) else self.owner
            path = ('unprojected_size' if parent and parent.use_locked_size == 'SCENE' else 'size'
                    ) if identifier == SIZE else PATHS[identifier]
        if parent is None:
            raise PropertyError("Native settings are unavailable")
        return parent, path

    def capability(self, definition):
        try:
            self.binding(definition.identifier)
        except PropertyError:
            return Capability(False, False, False, 'native_owner_unavailable')
        return Capability(True, definition.identifier not in SIZE_ALIASES, False,
                          'generic_execution_adapter_pending')

    def value_domain(self, definition):
        parent, path = self.binding(definition.identifier)
        prop = parent.bl_rna.properties[path]
        kind = {'FLOAT': 'FLOAT32', 'INT': 'INT32', 'BOOLEAN': 'BOOL'}[prop.type]
        if kind == 'BOOL':
            return ValueDomain(kind, 0, 1, 0, 1, 'NONE', path)
        return ValueDomain(kind, prop.hard_min, prop.hard_max, prop.soft_min, prop.soft_max, prop.unit, path)

    def read_value(self, definition):
        parent, path = self.binding(definition.identifier)
        return ValueSource(getattr(parent, path), True, 'NATIVE')

    def validate_value(self, definition, value):
        # Frozen registry validation remains fixed; native bounds further constrain it.
        value = definition.validate(value)
        return self.value_domain(definition).validate(value)

    def write_value(self, definition, value):
        self._guard.check(write=True)
        value = self.validate_value(definition, value)
        parent, path = self.binding(definition.identifier)
        if getattr(parent, path) == value:
            return
        if definition.identifier in (SIZE, *SIZE_ALIASES):
            pixels, world = parent.size, parent.unprojected_size
            if path == 'size':
                world = scalar('FLOAT32', world * scalar('FLOAT32', value / pixels))
                pixels = value
            else:
                world = value
            # Blender's pixel setter rescales its world partner without clamping.
            for name, paired in (('size', pixels), ('unprojected_size', world)):
                prop = parent.bl_rna.properties[name]
                if not prop.hard_min <= paired <= prop.hard_max:
                    raise PropertyError("Size edit would put the paired native value outside its range")
        setattr(parent, path, value)

    def size_block(self):
        parent = self.settings()
        if parent is None:
            raise PropertyError("Native size settings are unavailable")
        return SizeBlock(parent.size, parent.unprojected_size, parent.use_locked_size, self._guard.identity)

    def write_size_mode(self, mode):
        self._guard.check(write=True)
        if mode not in ('VIEW', 'SCENE'):
            raise PropertyError("Unknown native size mode")
        parent = self.settings()
        if parent is None:
            raise PropertyError("Native size settings are unavailable")
        if parent.use_locked_size != mode:
            parent.use_locked_size = mode

    def unified(self, identifier):
        parent = self.settings()
        if self.kind != 'SCENE' or parent is None:
            return False
        return getattr(parent, 'use_unified_size' if policy_identifier(identifier) == SIZE
                       else 'use_unified_strength')

    def write_unified(self, identifier, enabled):
        self._guard.check(write=True)
        if self.kind != 'SCENE' or type(enabled) is not bool:
            raise PropertyError("Unified native flags belong to Scene")
        parent = self.settings()
        if parent is None:
            raise PropertyError("Native unified settings are unavailable")
        path = 'use_unified_size' if policy_identifier(identifier) == SIZE else 'use_unified_strength'
        if getattr(parent, path) != enabled:
            setattr(parent, path, enabled)

    def pressure_path(self, identifier):
        self._guard.check()
        if self.kind != 'BRUSH' or identifier not in (STRENGTH, SIZE):
            raise PropertyError("Native pressure belongs to Brush strength/size")
        suffix = 'strength' if identifier == STRENGTH else 'size'
        supported = getattr(self.owner.sculpt_capabilities, 'has_' + suffix + '_pressure')
        path = ('use_pressure_' if supported else 'sculptcore_use_pressure_') + suffix
        if not hasattr(self.owner, path):
            raise PropertyError("Native/shadow pressure capability is unavailable")
        return path

    def pressure_enabled(self, identifier):
        return getattr(self.owner, self.pressure_path(identifier))

    def write_pressure(self, identifier, enabled):
        self._guard.check(write=True)
        path = self.pressure_path(identifier)
        if type(enabled) is not bool:
            raise PropertyError("Pressure enable requires bool")
        if getattr(self.owner, path) != enabled:
            setattr(self.owner, path, enabled)

    def curve_reference(self, identifier):
        flag = self.pressure_path(identifier)
        path = 'curve_strength' if identifier == STRENGTH else 'curve_size'
        try:
            key = self.owner.authoring_native_curve_key(path)
        except (ValueError, TypeError, PermissionError) as error:
            raise PropertyError(str(error)) from error
        return NativeCurveReference(self._guard.identity, identifier, 'PRESSURE', path, flag, key)

    def curve_mapping(self, reference):
        reference = NativeCurveReference(reference.owner_identity, reference.identifier, reference.device,
                                         reference.path, reference.enable_path, reference.mapping_key)
        if self.curve_reference(reference.identifier) != reference:
            raise PropertyError("Native curve reference is stale or belongs to another owner")
        return getattr(self.owner, reference.path)


def radius_from_diameter(diameter):
    return scalar('FLOAT32', diameter) / 2.0


def spacing_fraction(percent):
    return max(1, percent) / 100.0


def snake_pinch(factor):
    return 2.0 * (.5 - factor)


def strength_multiplier(brush_type):
    return 2.0 if brush_type == 'DRAW_SHARP' else 1.0


def accumulate_value(brush_type, authored, *, has_accumulate=True, operation_mode=None):
    return (operation_mode in ('SMOOTH', 'MASK') or brush_type == 'DRAW_SHARP'
            or not has_accumulate or authored)


def direction_sign(direction, invert=False):
    from ..mapping import DIRECTION_INVERTED
    if type(direction) is not str or type(invert) is not bool:
        raise PropertyError("Invalid brush direction")
    return -1 if (direction in DIRECTION_INVERTED) != invert else 1


def invert_for_dab(direction, invert, *, allow_invert=True):
    """The bridge's direction test (every BRUSH_DIR_IN item, see
    mapping.DIRECTION_INVERTED) and the smoothing override."""
    from ..mapping import DIRECTION_INVERTED
    if type(direction) is not str or type(invert) is not bool or type(allow_invert) is not bool:
        raise PropertyError("Invalid dab direction policy")
    return (invert != (direction in DIRECTION_INVERTED)) if allow_invert else False
