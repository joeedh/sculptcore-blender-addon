# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Authoritative native strength values with explicitly transient policy injection."""

from dataclasses import dataclass, field

from .lifecycle import OwnerGuard
from .registry import Definition, Position, PropertyError
from .resolver import Capability, MODES, ValueSource

STRENGTH = 'sculptcore.brush.strength'
STRENGTH_DEFINITION = Definition(
    STRENGTH, "Strength", 'FLOAT32', 1.0, 0.0, 10.0, 0.0, 1.0,
    "How powerful the effect of the brush is when applied",
    positions=(Position('VIEW3D_HEADER', 20), Position('BRUSH_SETTINGS', 20)))
NATIVE_DEFAULTS = {'BRUSH': 1.0, 'SCENE': 0.5}


@dataclass
class TransientPolicy:
    """Experimental policy state; no IDProperty, saved schema or migration is performed."""

    modes: dict = field(default_factory=dict)
    stack_inheritance: dict = field(default_factory=dict)


class NativeStrengthOwner:
    """Use only for a current operation; lifecycle changes invalidate all retained stores."""

    def __init__(self, owner, *, epoch, policy=None):
        self._guard = OwnerGuard(owner, epoch=epoch)
        self.owner = owner
        self.kind = self._guard.kind
        self.policy = policy if policy is not None else TransientPolicy()

    @property
    def identity(self):
        return self._guard.identity

    @property
    def editable(self):
        return self._guard.check()

    def _settings(self):
        self._guard.check()
        if self.kind == 'BRUSH':
            return self.owner
        sculpt = self.owner.tool_settings.sculpt
        return sculpt.unified_paint_settings if sculpt is not None else None

    def capability(self, definition):
        self._guard.check()
        available = (definition.identifier == STRENGTH and definition.scalar_type == 'FLOAT32'
                     and self._settings() is not None)
        return Capability(available, False, False,
                          'native_pressure_adapter_pending' if available else 'native_owner_unavailable')

    def read_value(self, definition):
        self._identifier(definition.identifier)
        if definition.scalar_type != 'FLOAT32':
            raise PropertyError("Native strength requires a float32 definition")
        settings = self._settings()
        if settings is None:
            raise PropertyError("Native sculpt settings are unavailable")
        return ValueSource(settings.strength, True, 'NATIVE')

    def read_stack(self, definition):
        self._identifier(definition.identifier)
        raise PropertyError("Native pressure adapter is not implemented")

    def value_mode(self, identifier):
        self._identifier(identifier)
        return self.policy.modes.get(identifier, 'UNIFIED')

    def unified(self, identifier):
        self._identifier(identifier)
        settings = self._settings()
        return settings.use_unified_strength if self.kind == 'SCENE' and settings is not None else False

    def inherits_stack(self, identifier):
        self._identifier(identifier)
        return self.policy.stack_inheritance.get(identifier, False)

    def write_value(self, definition, value):
        self._guard.check(write=True)
        if not self.capability(definition).value:
            raise PropertyError("Native strength write is unavailable")
        converted = STRENGTH_DEFINITION.validate(definition.validate(value))
        settings = self._settings()
        if settings.strength != converted:
            settings.strength = converted

    def write_stack(self, definition, layers):
        self._guard.check(write=True)
        raise PropertyError("Native pressure adapter is not implemented")

    def write_mode(self, identifier, mode):
        self._metadata_edit(identifier, 'BRUSH')
        if mode not in MODES:
            raise PropertyError("Invalid value inheritance mode")
        self.policy.modes[identifier] = mode

    def write_stack_inheritance(self, identifier, enabled):
        self._metadata_edit(identifier, 'BRUSH')
        if type(enabled) is not bool:
            raise PropertyError("Stack inheritance requires bool")
        self.policy.stack_inheritance[identifier] = enabled

    def write_unified(self, identifier, enabled):
        self._metadata_edit(identifier, 'SCENE')
        if type(enabled) is not bool or self._settings() is None:
            raise PropertyError("Native unified strength is unavailable or invalid")
        settings = self._settings()
        if settings.use_unified_strength != enabled:
            settings.use_unified_strength = enabled

    def _identifier(self, identifier):
        self._guard.check()
        if identifier != STRENGTH:
            raise PropertyError("Native strength adapter received another definition")

    def _metadata_edit(self, identifier, kind):
        self._guard.check(write=True)
        if identifier != STRENGTH or self.kind != kind:
            raise PropertyError("Native metadata write targets an unsupported or read-only owner")
