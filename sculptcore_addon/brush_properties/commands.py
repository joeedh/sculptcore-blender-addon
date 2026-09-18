# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Owner-free command snapshots. Inputs use normalized execution definitions.

Native size projection and other semantic adapters run before this boundary.
Ancestry uses stable IDs; native names are only introduced during serialization.
"""
from dataclasses import dataclass

from .registry import Definition, DEVICE_TYPES, PropertyError, finite, scalar
from .responses import PreparedResponse


def _name(value):
    if type(value) is not str or not value or '\0' in value:
        raise PropertyError("Expected a nonempty name without NUL")
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PropertyError("Name must be valid UTF-8") from None
    return value


@dataclass(frozen=True)
class ExecutionLayer:
    device: str
    response: PreparedResponse
    enabled: bool = True
    operation: str = 'MULTIPLY'
    factor: float = 1.0

    def __post_init__(self):
        if (self.device not in DEVICE_TYPES or type(self.response) is not PreparedResponse
                or type(self.enabled) is not bool or self.operation not in
                ('REPLACE', 'MULTIPLY', 'ADD', 'SUBTRACT', 'DIFFERENCE')
                or not finite(self.factor) or not 0 <= self.factor <= 1):
            raise PropertyError("Invalid prepared device layer")
        object.__setattr__(self, 'factor', scalar('FLOAT32', self.factor))


def _stack(layers):
    if layers is None:
        raise PropertyError("Unavailable stacks cannot execute")
    layers = tuple(layers)
    if any(type(layer) is not ExecutionLayer for layer in layers):
        raise PropertyError("Execution stacks require owner-free prepared responses")
    if len({layer.device for layer in layers}) != len(layers):
        raise PropertyError("Duplicate command input device")
    return layers


def prepare_stack(resolved):
    """Sample using the effective stack owner at the synchronization boundary.

    This prepares responses only; it does not activate execution capabilities or
    translate semantic scalar domains (e.g. native size) into engine domains.
    """
    from .registry import validated_stack
    from .resolver import Resolved
    from .sampling import resolved_response

    if type(resolved) is not Resolved or not resolved.stack_available or resolved.stack is None:
        raise PropertyError("Effective stack is unavailable")
    layers = validated_stack(resolved.stack)
    if layers and not resolved.definition.dynamic:
        raise PropertyError("Static properties cannot have device stacks")
    return tuple(ExecutionLayer(layer.device,
                                resolved_response(resolved.stack_owner, resolved.definition, layer.curve),
                                layer.enabled, layer.operation, layer.factor) for layer in layers)


@dataclass(frozen=True)
class ExecutionValue:
    definition: Definition
    value: object
    stack: tuple = ()

    def __post_init__(self):
        if type(self.definition) is not Definition:
            raise PropertyError("Expected an execution definition")
        object.__setattr__(self, 'value', self.definition.validate(self.value))
        object.__setattr__(self, 'stack', _stack(self.stack))
        if self.stack and not self.definition.dynamic:
            raise PropertyError("Static properties cannot have device stacks")


@dataclass(frozen=True)
class Parent:
    kind: str = 'BRUSH'
    name: str = ""

    def __post_init__(self):
        if self.kind not in ('BRUSH', 'COMMAND', 'DEFAULTS'):
            raise PropertyError("Unknown command parent kind")
        if self.kind == 'COMMAND':
            _name(self.name)
        elif self.name != "":
            raise PropertyError("Only command parents have names")


def _pairs(items, convert):
    result = []
    seen = set()
    for identifier, value in items:
        _name(identifier)
        if identifier in seen:
            raise PropertyError("Duplicate override: " + identifier)
        seen.add(identifier)
        result.append((identifier, convert(value)))
    return tuple(result)


@dataclass(frozen=True)
class Command:
    name: str
    kernel: int
    definitions: tuple
    parent: Parent = Parent()
    values: tuple = ()
    stacks: tuple = ()

    def __post_init__(self):
        _name(self.name)
        if type(self.kernel) is not int or not 0 <= self.kernel <= 2147483647:
            raise PropertyError("Invalid command kernel")
        if type(self.parent) is not Parent:
            raise PropertyError("Command parent must be explicitly tagged")
        definitions = tuple(self.definitions)
        if any(type(item) is not Definition for item in definitions):
            raise PropertyError("Expected target-specific execution definitions")
        by_id = {item.identifier: item for item in definitions}
        if len(by_id) != len(definitions):
            raise PropertyError("Duplicate target property")
        values = _pairs(self.values, lambda value: value)
        stacks = _pairs(self.stacks, _stack)
        for identifier, value in values:
            if identifier not in by_id:
                raise PropertyError("Override is outside the command target: " + identifier)
            by_id[identifier].validate(value)
        for identifier, stack in stacks:
            if identifier not in by_id or not by_id[identifier].dynamic:
                raise PropertyError("Stack override requires a target dynamic property: " + identifier)
        object.__setattr__(self, 'definitions', definitions)
        object.__setattr__(self, 'values', tuple((key, by_id[key].validate(value)) for key, value in values))
        object.__setattr__(self, 'stacks', stacks)


@dataclass(frozen=True)
class ResolvedCommand:
    name: str
    kernel: int
    properties: tuple

    def __post_init__(self):
        _name(self.name)
        if type(self.kernel) is not int or not 0 <= self.kernel <= 2147483647:
            raise PropertyError("Invalid resolved kernel")
        properties = tuple(self.properties)
        if any(type(item) is not ExecutionValue for item in properties):
            raise PropertyError("Expected immutable execution properties")
        if len({item.definition.identifier for item in properties}) != len(properties):
            raise PropertyError("Duplicate resolved property")
        object.__setattr__(self, 'properties', properties)


def resolve_commands(commands, brush):
    """Flatten a DAG in execution order; missing parent IDs use target defaults.

    Every eligible property carries an explicit stack, including empty. No RNA,
    owner stores, inheritance flags, or mutable containers survive in the result.
    """
    commands, brush = tuple(commands), tuple(brush)
    if any(type(command) is not Command for command in commands):
        raise PropertyError("Expected immutable commands")
    if any(type(item) is not ExecutionValue for item in brush):
        raise PropertyError("Expected an owner-free brush snapshot")
    by_name = {command.name: command for command in commands}
    brush_values = {item.definition.identifier: item for item in brush}
    if len(by_name) != len(commands) or len(brush_values) != len(brush):
        raise PropertyError("Duplicate command or brush property")
    resolved = {}
    visiting = set()

    def visit(command):
        if command.name in resolved:
            return resolved[command.name]
        if command.name in visiting:
            raise PropertyError("Command inheritance cycle: " + command.name)
        visiting.add(command.name)
        if command.parent.kind == 'COMMAND':
            if command.parent.name not in by_name:
                raise PropertyError("Missing parent command: " + command.parent.name)
            parent = {item.definition.identifier: item for item in visit(by_name[command.parent.name]).properties}
        else:
            parent = brush_values if command.parent.kind == 'BRUSH' else {}
        values, stacks = dict(command.values), dict(command.stacks)
        properties = []
        for definition in command.definitions:
            identifier = definition.identifier
            inherited = parent.get(identifier)
            if inherited is not None and inherited.definition != definition:
                raise PropertyError("Incompatible execution definition: " + identifier)
            value = values.get(identifier, inherited.value if inherited is not None else definition.default)
            stack = stacks.get(identifier, inherited.stack if inherited is not None else ())
            properties.append(ExecutionValue(definition, value, stack))
        result = ResolvedCommand(command.name, command.kernel, tuple(properties))
        visiting.remove(command.name)
        resolved[command.name] = result
        return result

    # Iterative ancestry walk avoids Python recursion limits for valid long chains.
    for command in commands:
        chain, seen, current = [], set(), command
        while current.name not in resolved:
            if current.name in seen:
                raise PropertyError("Command inheritance cycle: " + current.name)
            seen.add(current.name)
            chain.append(current)
            if current.parent.kind != 'COMMAND':
                break
            if current.parent.name not in by_name:
                raise PropertyError("Missing parent command: " + current.parent.name)
            current = by_name[current.parent.name]
        for entry in reversed(chain):
            visit(entry)
    return tuple(resolved[command.name] for command in commands)


def build_program(manager, commands, names):
    """Create a candidate native program; caller publishes only the returned object.

    names maps (kernel, stable ID) to authoritative manifest spelling. Every
    command uploads complete values and explicit eligible stacks, even empties.
    Dispose the returned program when replacing it. A failed build disposes only
    its candidate and never touches the caller's previous executable program.
    """
    from sculptcore.brush_properties import DeviceLayer, replace_command_stack, set_command_scalar

    commands = tuple(commands)
    scalar_types = {'FLOAT32': 0, 'INT32': 4, 'BOOL': 10}
    operations = {'REPLACE': 0, 'MULTIPLY': 1, 'ADD': 2, 'SUBTRACT': 3, 'DIFFERENCE': 4}
    devices = {'PRESSURE': 0, 'TILT_X': 1, 'TILT_Y': 2, 'SPEED': 3}
    payload = []
    for command in commands:
        if type(command) is not ResolvedCommand or type(command.properties) is not tuple:
            raise PropertyError("Expected a resolved command")
        used = set()
        properties = []
        for item in command.properties:
            if type(item) is not ExecutionValue:
                raise PropertyError("Expected a resolved execution value")
            try:
                name = _name(names[command.kernel, item.definition.identifier])
            except KeyError:
                raise PropertyError("Missing native property translation") from None
            if name in used:
                raise PropertyError("Duplicate native command target: " + name)
            used.add(name)
            layers = tuple(DeviceLayer(devices[layer.device], operations[layer.operation], layer.factor,
                                       layer.enabled, layer.response.samples, layer.response.kind,
                                       layer.response.parameters) for layer in item.stack)
            properties.append((name, scalar_types[item.definition.scalar_type], item.value,
                               layers if item.definition.dynamic else None))
        payload.append((command.kernel, tuple(properties)))
    program = manager.construct('sculptcore::brush::BrushProgram')
    try:
        for kernel, properties in payload:
            index = program.addCommand(kernel)
            for name, kind, value, layers in properties:
                set_command_scalar(manager, program, index, name, kind, value)
                if layers is not None:
                    replace_command_stack(manager, program, index, name, kind, layers)
        return program
    except BaseException:
        program.dispose()
        raise
