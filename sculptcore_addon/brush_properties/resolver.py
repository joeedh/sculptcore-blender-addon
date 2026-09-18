# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Resolve and edit effective owners through a non-allocating authoring-store interface."""

from dataclasses import dataclass, replace
from typing import Protocol

from .registry import Definition, PropertyError, validated_stack

MODES = ('UNIFIED', 'ALWAYS', 'NEVER')


@dataclass(frozen=True)
class Capability:
    value: bool = True
    stack: bool = True
    execution: bool = True
    reason: str = ""

    def __post_init__(self):
        if (any(type(value) is not bool for value in (self.value, self.stack, self.execution))
                or type(self.reason) is not str):
            raise PropertyError("Malformed owner capability")


@dataclass(frozen=True)
class ValueSource:
    value: object = None
    present: bool = False
    source: str = 'GENERIC'

    def __post_init__(self):
        if (type(self.present) is not bool or type(self.source) is not str
                or (not self.present and self.value is not None)):
            raise PropertyError("Malformed authored value presence/source")


class OwnerStore(Protocol):
    """Identity includes the caller's lifecycle epoch; stores remain valid only for the current operation."""

    identity: tuple
    kind: str
    editable: bool

    def capability(self, definition: Definition) -> Capability: ...
    def read_value(self, definition: Definition) -> ValueSource: ...
    def read_stack(self, definition: Definition) -> tuple: ...
    def value_mode(self, identifier: str) -> str: ...
    def unified(self, identifier: str) -> bool: ...
    def inherits_stack(self, identifier: str) -> bool: ...
    def write_value(self, definition: Definition, value): ...
    def write_stack(self, definition: Definition, layers: tuple): ...
    def write_mode(self, identifier: str, mode: str): ...
    def write_unified(self, identifier: str, enabled: bool): ...
    def write_stack_inheritance(self, identifier: str, enabled: bool): ...


@dataclass(frozen=True)
class Resolved:
    definition: Definition
    value: object
    value_owner: OwnerStore
    stack: tuple | None
    stack_owner: OwnerStore
    value_source: ValueSource
    stack_available: bool
    execution_available: bool
    diagnostics: tuple
    invalidation_key: tuple
    value_domain: object = None


def _resolve(registry, identifier, local, parent, read_stack, read_value=True):
    definition = registry.get(identifier)
    if local.kind not in definition.owners:
        raise PropertyError("Definition does not support this owner")
    if local.kind == 'SCENE':
        parent = None
    elif local.kind != 'BRUSH' or (parent is not None and parent.kind != 'SCENE'):
        raise PropertyError("The supported hierarchy is Brush -> Scene")
    local_cap = local.capability(definition)
    if type(local_cap) is not Capability:
        raise PropertyError("Malformed local capability")
    if not local_cap.value:
        raise PropertyError("Local value capability is unavailable")
    parent_cap = (parent.capability(definition) if parent is not None and 'SCENE' in definition.owners
                  else Capability(False, False, False, 'parent_unavailable'))
    if type(parent_cap) is not Capability:
        raise PropertyError("Malformed parent capability")
    mode = local.value_mode(identifier) if local.kind == 'BRUSH' else 'NEVER'
    inherited_stack = local.inherits_stack(identifier) if local.kind == 'BRUSH' else False
    unified = parent.unified(identifier) if parent is not None and parent_cap.value else False
    cavity_mode = mode == 'NATIVE_CAVITY' and identifier.startswith('sculptcore.brush.cavity.')
    if (mode not in MODES and not cavity_mode) or type(inherited_stack) is not bool or type(unified) is not bool:
        raise PropertyError("Malformed inheritance metadata")
    want_parent = mode == 'ALWAYS' or (mode == 'UNIFIED' and unified)
    if cavity_mode:
        if not hasattr(local, 'native_cavity_parent'):
            raise PropertyError("Native cavity policy requires a cavity adapter")
        want_parent = local.native_cavity_parent(parent)
    diagnostics = []
    if hasattr(local, 'diagnostics'):
        diagnostics.extend(local.diagnostics(definition))
    value_owner = parent if want_parent and parent_cap.value else local
    if mode != 'NEVER' and not parent_cap.value:
        diagnostics.append('value:parent_unavailable')
    stack_owner = parent if inherited_stack and parent_cap.stack else local
    if inherited_stack and not parent_cap.stack:
        diagnostics.append('stack:parent_unavailable')
    stack_cap = parent_cap if stack_owner is parent else local_cap
    value_cap = parent_cap if value_owner is parent else local_cap
    source = value_owner.read_value(definition) if read_value else ValueSource()
    if type(source) is not ValueSource:
        raise PropertyError("Malformed authored value source")
    authored = source.value if source.present else definition.default
    value = (value_owner.validate_value(definition, authored) if read_value and hasattr(value_owner, 'validate_value')
             else definition.validate(authored))
    layers = validated_stack(stack_owner.read_stack(definition)) if stack_cap.stack and read_stack else None
    if layers and not definition.dynamic:
        raise PropertyError("Static definitions cannot carry a device stack")
    if not stack_cap.stack:
        diagnostics.append('stack:unavailable')
    execution_available = value_cap.execution and stack_cap.execution and stack_cap.stack
    if not execution_available:
        diagnostics.append('execution:unavailable')
        for capability in (value_cap, stack_cap):
            if not capability.execution and capability.reason:
                reason = 'execution:' + capability.reason
                if reason not in diagnostics:
                    diagnostics.append(reason)
    domain = value_owner.value_domain(definition) if hasattr(value_owner, 'value_domain') else definition
    key = (registry.revision, definition, domain, local.identity, parent.identity if parent is not None else None,
           local_cap, parent_cap, mode, unified, inherited_stack, value_owner.identity, stack_owner.identity,
           source, value, layers, tuple(diagnostics))
    return Resolved(definition, value, value_owner, layers, stack_owner, source, stack_cap.stack,
                    execution_available, tuple(diagnostics), key, domain)


def resolve(registry, identifier, local, parent=None):
    return _resolve(registry, identifier, local, parent, True)


def resolve_value(registry, identifier, local, parent=None):
    """Resolve a displayed base value without reading or sampling device curves."""
    return _resolve(registry, identifier, local, parent, False)


def _editable(owner):
    if not owner.editable:
        raise PropertyError("Effective owner is read-only; create an editable copy")


def set_value(registry, identifier, local, parent, value):
    result = _resolve(registry, identifier, local, parent, False, False)
    value = (result.value_owner.validate_value(result.definition, value)
             if hasattr(result.value_owner, 'validate_value') else result.definition.validate(value))
    _editable(result.value_owner)
    result.value_owner.write_value(result.definition, value)


def set_stack(registry, identifier, local, parent, layers):
    result = _resolve(registry, identifier, local, parent, False, False)
    layers = validated_stack(layers)
    if not result.stack_available or (layers and not result.definition.dynamic):
        raise PropertyError("Device stack authoring is unavailable")
    _editable(result.stack_owner)
    result.stack_owner.write_stack(result.definition, layers)


def update_layer(registry, identifier, local, parent, layer):
    layer, = validated_stack((layer,))
    result = resolve(registry, identifier, local, parent)
    if result.stack is None:
        raise PropertyError("Device stack authoring is unavailable")
    layers = list(result.stack)
    index = next((i for i, old in enumerate(layers) if old.device == layer.device), len(layers))
    if index == len(layers):
        layers.append(layer)
    else:
        layers[index] = layer
    set_stack(registry, identifier, local, parent, layers)


def set_layer_enabled(registry, identifier, local, parent, device, enabled):
    result = resolve(registry, identifier, local, parent)
    layer = next((layer for layer in result.stack or () if layer.device == device), None)
    if layer is None:
        raise PropertyError("Device entry is absent")
    update_layer(registry, identifier, local, parent, replace(layer, enabled=enabled))


def set_value_mode(registry, identifier, local, mode):
    definition = registry.get(identifier)
    cavity = mode == 'NATIVE_CAVITY' and identifier.startswith('sculptcore.brush.cavity.')
    if local.kind != 'BRUSH' or local.kind not in definition.owners or (mode not in MODES and not cavity):
        raise PropertyError("Value inheritance belongs to Brush")
    if type(local.capability(definition)) is not Capability or not local.capability(definition).value:
        raise PropertyError("Local value capability is unavailable")
    _editable(local)
    local.write_mode(identifier, mode)


def set_stack_inheritance(registry, identifier, local, enabled):
    definition = registry.get(identifier)
    if local.kind != 'BRUSH' or local.kind not in definition.owners or type(enabled) is not bool:
        raise PropertyError("Stack inheritance belongs to Brush and requires bool")
    if type(local.capability(definition)) is not Capability or not local.capability(definition).value:
        raise PropertyError("Local value capability is unavailable")
    _editable(local)
    local.write_stack_inheritance(identifier, enabled)


def set_unified(registry, identifier, scene, enabled):
    definition = registry.get(identifier)
    if scene.kind != 'SCENE' or scene.kind not in definition.owners or type(enabled) is not bool:
        raise PropertyError("Unified flags belong to Scene and require bool")
    if type(scene.capability(definition)) is not Capability or not scene.capability(definition).value:
        raise PropertyError("Scene value capability is unavailable")
    _editable(scene)
    scene.write_unified(identifier, enabled)
