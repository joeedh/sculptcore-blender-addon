# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Immutable effective authoring state, captured before execution-domain translation.

Capture runs synchronously on the main thread. Results own no RNA, owner stores,
curve references or inheritance metadata; native values retain their actual type.
"""
from dataclasses import dataclass

from .adapters import BY_ID, PIXELS, SIZE, WORLD, ValueDomain
from .commands import ExecutionLayer, prepare_stack
from .lifecycle import _main_thread
from .registry import Definition, PropertyError
from .resolver import resolve


def _typed(domain, value):
    if type(domain) not in (ValueDomain, Definition):
        raise PropertyError("Snapshot requires an immutable scalar domain")
    kind = domain.kind if type(domain) is ValueDomain else domain.scalar_type
    expected = {'FLOAT32': float, 'INT32': int, 'BOOL': bool}.get(kind)
    if type(value) is not expected:
        raise PropertyError("Snapshot scalar has the wrong primitive type")
    if domain.validate(value) != value:
        raise PropertyError("Snapshot scalar is not canonical in its domain")
    return value


@dataclass(frozen=True)
class SizeSnapshot:
    pixels: int
    world: float
    mode: str
    pixel_domain: ValueDomain
    world_domain: ValueDomain

    def __post_init__(self):
        if (type(self.pixel_domain) is not ValueDomain or type(self.world_domain) is not ValueDomain
                or self.pixel_domain.kind != 'INT32' or self.pixel_domain.path != 'size'
                or self.world_domain.kind != 'FLOAT32' or self.world_domain.path != 'unprojected_size'
                or type(self.mode) is not str or self.mode not in ('VIEW', 'SCENE')):
            raise PropertyError("Invalid native size domains or mode")
        _typed(self.pixel_domain, self.pixels)
        _typed(self.world_domain, self.world)

    @property
    def active_value(self):
        return self.pixels if self.mode == 'VIEW' else self.world

    @property
    def active_domain(self):
        return self.pixel_domain if self.mode == 'VIEW' else self.world_domain


@dataclass(frozen=True)
class PropertySnapshot:
    definition: Definition
    value_domain: Definition | ValueDomain
    value: bool | int | float
    present: bool
    source: str
    stack: tuple
    stack_available: bool
    execution_available: bool
    diagnostics: tuple
    size: SizeSnapshot | None = None

    def __post_init__(self):
        if (type(self.definition) is not Definition or type(self.source) is not str
                or any(type(flag) is not bool for flag in
                       (self.present, self.stack_available, self.execution_available))):
            raise PropertyError("Invalid snapshot metadata")
        _typed(self.value_domain, self.value)
        stack, diagnostics = tuple(self.stack), tuple(self.diagnostics)
        if (any(type(layer) is not ExecutionLayer for layer in stack)
                or len({layer.device for layer in stack}) != len(stack)
                or any(type(item) is not str for item in diagnostics)):
            raise PropertyError("Snapshot requires immutable prepared layers and diagnostics")
        if (not self.stack_available and (self.definition.dynamic or stack or self.execution_available)
                or stack and not self.definition.dynamic):
            raise PropertyError("Invalid snapshot stack capability")
        if self.definition.identifier == SIZE:
            if (type(self.size) is not SizeSnapshot or self.value_domain != self.size.active_domain
                    or type(self.value) is not type(self.size.active_value) or self.value != self.size.active_value):
                raise PropertyError("Native size pair does not match the resolved scalar")
        elif self.size is not None:
            raise PropertyError("Only semantic size carries a paired native state")
        object.__setattr__(self, 'stack', stack)
        object.__setattr__(self, 'diagnostics', diagnostics)


def capture(registry, identifiers, local, parent=None):
    """Resolve a complete candidate; failure returns no partial snapshot.

    Fresh resolution validates owner lifetimes even when stacks are empty. Native
    size uses its effective value owner's entire pair, independent of stack owner.
    Execution capability remains exactly as reported by the authoring resolver.
    """
    _main_thread()
    identifiers = tuple(identifiers)
    if any(type(identifier) is not str for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise PropertyError("Snapshot IDs must be unique strings")
    for identifier in identifiers:
        registry.get(identifier)
    properties = []
    for identifier in identifiers:
        resolved = resolve(registry, identifier, local, parent)
        size = None
        if identifier == SIZE:
            native = getattr(resolved.value_owner, '_native', None)
            if native is None:
                raise PropertyError("Semantic size requires an authoritative native owner")
            block = native.size_block()
            size = SizeSnapshot(block.pixels, block.world, block.mode,
                                native.value_domain(BY_ID[PIXELS]), native.value_domain(BY_ID[WORLD]))
        stack = (prepare_stack(resolved) if resolved.stack_available else ())
        properties.append(PropertySnapshot(
            resolved.definition, resolved.value_domain, resolved.value,
            resolved.value_source.present, resolved.value_source.source, stack,
            resolved.stack_available, resolved.execution_available, resolved.diagnostics, size))
    return tuple(properties)
