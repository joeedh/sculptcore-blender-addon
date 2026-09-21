# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Persistent scalar and owner-aware stack authoring with atomic publication."""

import base64
import hashlib
import json
import math
import re

from .lifecycle import OwnerGuard
from .adapters import NativeOwner, STRENGTH, SIZE, SIZE_ALIASES, CAVITY, BY_ID, policy_identifier
from .registry import CURVE_PRESET_ARITY, DEVICE_TYPES, DeviceLayer, PropertyError, ResponseCurve, validated_stack
from .registry import Position, validated_positions
from .registry import CustomCurveReference, NativeCurveReference
from .resolver import Capability, MODES, ValueSource
from . import legacy

ROOT = 'sculptcore_properties'
SCHEMA_VERSION = 1
STACK_VERSION = 1
POSITIONS_VERSION = 1


def _root(owner):
    root = owner.get(ROOT)
    if root is None and ROOT not in owner:
        return None
    if not _group(root) or type(root.get('schema_version')) is not int:
        raise PropertyError("Malformed generic property schema header")
    if root['schema_version'] != SCHEMA_VERSION:
        raise PropertyError("Unsupported generic property schema; data preserved")
    if 'records' in root and not _group(root['records']):
        raise PropertyError("Malformed generic property records group")
    return root


def _positions_header(record, *, reading):
    if record is None:
        return False
    if 'positions' in record and not _group(record['positions']):
        raise PropertyError("Malformed positions group")
    version_set, order_set = 'positions_version' in record, 'positions_order' in record
    if version_set:
        version = record['positions_version']
        if type(version) is not int or version != POSITIONS_VERSION:
            raise PropertyError("Unsupported or malformed positions version; data preserved")
    if reading and version_set != order_set:
        raise PropertyError("Incomplete positions header")
    return version_set or order_set


def _stack_header(record, *, reading):
    """Validate only on stack access; other fields preserve unknown stack schemas."""
    if record is None:
        return False
    present = any(name in record for name in ('stack_version', 'layer_order', 'layers'))
    if 'stack_version' in record:
        version = record['stack_version']
        if type(version) is not int or version != STACK_VERSION:
            raise PropertyError("Unsupported or malformed device stack version; data preserved")
    elif reading and present:
        raise PropertyError("Missing device stack version")
    if 'layers' in record and not _group(record['layers']):
        raise PropertyError("Malformed device layer group")
    return present


def record_key(identifier):
    digest = hashlib.sha256(identifier.encode('utf-8')).digest()
    return 'p_' + base64.b32encode(digest).decode('ascii').rstrip('=').lower()


def _group(value):
    from idprop.types import IDPropertyGroup
    return isinstance(value, IDPropertyGroup)


def value_metadata(definition):
    """Return fresh per-definition metadata without touching an owner."""
    subtypes = {'NONE': 'NONE', 'ROTATION': 'ANGLE', 'LENGTH': 'DISTANCE'}
    try:
        subtype = subtypes[definition.unit]
    except KeyError:
        raise PropertyError("Unsupported property unit: " + definition.unit) from None
    result = dict(default=definition.default, description=definition.description, subtype=subtype)
    if definition.scalar_type == 'BOOL':
        if definition.unit != 'NONE':
            raise PropertyError("Boolean properties cannot have a physical unit")
        return result
    minimum, maximum = definition.minimum, definition.maximum
    soft_min, soft_max = definition.soft_minimum, definition.soft_maximum
    if definition.scalar_type == 'INT32':
        minimum, maximum = math.ceil(minimum), math.floor(maximum)
        soft_min = min(maximum, max(minimum, math.ceil(soft_min)))
        soft_max = max(soft_min, min(maximum, max(minimum, math.floor(soft_max))))
    result.update(min=minimum, max=maximum, soft_min=soft_min, soft_max=soft_max)
    return result


class PersistentOwnerStore:
    """Reacquire raw groups per operation; never expose retained storage wrappers."""

    def __init__(self, owner, registry, *, epoch=0, curve_bank=None, execution_diagnostic=None):
        self._guard = OwnerGuard(owner, epoch=epoch)
        self.owner = owner
        self.kind = self._guard.kind
        self.registry = registry
        self.curve_bank = curve_bank
        self._execution_diagnostic = execution_diagnostic
        self._native = NativeOwner(owner, epoch=epoch)

    @property
    def identity(self):
        return self._guard.identity

    @property
    def editable(self):
        return self._guard.check() and hasattr(self.owner, 'id_properties_update_atomic')

    def _definition(self, identifier):
        self._guard.check()
        definition = self.registry.get(identifier)
        frozen = legacy.BY_ID.get(identifier)
        if frozen is not None and frozen != definition:
            raise PropertyError("Definition conflicts with the frozen legacy contract")
        if self.kind not in definition.owners:
            raise PropertyError("Definition does not support this owner")
        if identifier in BY_ID and definition != BY_ID[identifier]:
            raise PropertyError("Definition conflicts with the reserved native contract")
        return definition

    def _record(self, identifier):
        definition = self._definition(identifier)
        root = _root(self.owner)
        if root is None:
            return None
        records = root.get('records')
        if records is None:
            return None
        key = record_key(identifier)
        record = records.get(key)
        if record is None and key not in records:
            return None
        if (not _group(record) or record.get('identifier') != identifier
                or record.get('scalar_type') != definition.scalar_type):
            raise PropertyError("Mismatched generic property record identity or type")
        modes = (*MODES, 'NATIVE_CAVITY') if identifier.startswith(CAVITY + '.') else MODES
        if record.get('value_mode', 'UNIFIED') not in modes:
            raise PropertyError("Malformed value inheritance mode")
        for name in ('inherit_stack', 'unified'):
            if type(record.get(name, False)) is not bool:
                raise PropertyError("Malformed generic property flag: " + name)
        return record

    def _checked_definition(self, definition):
        if self._definition(definition.identifier) != definition:
            raise PropertyError("Store definition differs from the registered definition")
        return self._record(definition.identifier)

    def _write_allowed(self):
        self._guard.check(write=True)
        if not hasattr(self.owner, 'id_properties_update_atomic'):
            raise PropertyError("Atomic property storage is unavailable in this Blender build")

    def capability(self, definition):
        self._checked_definition(definition)
        reason = (self._execution_diagnostic(definition.identifier) if self._execution_diagnostic
                  else 'generic_execution_adapter_pending')
        if self._native.handles(definition.identifier):
            native = self._native.capability(definition)
            if not native.value:
                return native
            return Capability(native.value, native.stack, not reason and native.stack, reason)
        return Capability(True, True, not reason, reason)

    def diagnostics(self, definition):
        self._checked_definition(definition)
        if self.kind == 'BRUSH' and definition.identifier == STRENGTH and self.owner.sculpt_brush_type == 'PINCH':
            return ('legacy:pinch_extra_uses_local_strength',)
        return ()

    def read_value(self, definition):
        record = self._checked_definition(definition)
        if self._native.handles(definition.identifier):
            return self._native.read_value(definition)
        from .compatibility import overlay
        override = overlay(self, definition)
        if override is not None:
            return override
        if record is None or 'value' not in record:
            return legacy.read_value(self, definition)
        value = record['value']
        expected = {'FLOAT32': float, 'INT32': int, 'BOOL': bool}[definition.scalar_type]
        if type(value) is not expected:
            raise PropertyError("Stored scalar has the wrong type")
        converted = definition.validate(value)
        if converted != value:
            raise PropertyError("Stored float is not canonical FLOAT32")
        return ValueSource(converted, True)

    def read_stack(self, definition):
        if definition.identifier in SIZE_ALIASES:
            raise PropertyError("Size representations share the common size stack")
        native_pressure = self._has_native_pressure(definition)
        result = []
        for device, enabled, operation, factor, preset, parameters in self._stack_descriptions(definition):
            if preset == 'CUSTOM' and native_pressure and device == 'PRESSURE':
                curve = self._native.curve_reference(definition.identifier)
            elif preset == 'CUSTOM':
                curve = self._curve_bank().reference(self, definition, device)
            else:
                curve = ResponseCurve(preset, parameters)
            result.append(DeviceLayer(device, enabled, operation, factor, curve))
        if native_pressure and not any(layer.device == 'PRESSURE' for layer in result):
            record = self._checked_definition(definition)
            enabled = self._native.pressure_enabled(definition.identifier)
            if enabled or not _stack_header(record, reading=True):
                result.insert(0, DeviceLayer('PRESSURE', enabled, curve=self._native.curve_reference(
                    definition.identifier)))
        return tuple(result)

    def _has_native_pressure(self, definition):
        return self.kind == 'BRUSH' and definition.identifier in (STRENGTH, SIZE)

    def validate_value(self, definition, value):
        self._checked_definition(definition)
        return (self._native.validate_value(definition, value) if self._native.handles(definition.identifier)
                else definition.validate(value))

    def value_domain(self, definition):
        self._checked_definition(definition)
        return self._native.value_domain(definition) if self._native.handles(definition.identifier) else definition

    def _curve_bank(self):
        if self.curve_bank is None:
            raise PropertyError("Custom curve authoring requires an explicitly registered bank")
        return self.curve_bank

    def _stack_descriptions(self, definition):
        """Validate selection metadata without resolving any mapping payload."""
        record = self._checked_definition(definition)
        if not _stack_header(record, reading=True):
            return ()
        order = record.get('layer_order')
        if type(order) is not str or len(order) > 64:
            raise PropertyError("Malformed device order")
        devices = order.split(',') if order else []
        if (len(devices) > len(DEVICE_TYPES) or len(set(devices)) != len(devices)
                or any(device not in DEVICE_TYPES for device in devices)):
            raise PropertyError("Unknown or duplicate device in stack order")
        if devices and (not definition.dynamic or 'layers' not in record):
            raise PropertyError("Static definition or missing device layer data")
        result = []
        for device in devices:
            data = record['layers'].get(device)
            if not _group(data):
                raise PropertyError("Malformed active device layer")
            enabled, operation, factor, preset = (data.get(name) for name in
                                                  ('enabled', 'operation', 'factor', 'preset'))
            if self._has_native_pressure(definition) and device == 'PRESSURE':
                enabled = self._native.pressure_enabled(definition.identifier)
            parameters = tuple(data.get('parameter_' + str(index)) for index in range(3))
            if (type(enabled) is not bool or type(operation) is not str or type(factor) is not float
                    or type(preset) is not str or (preset != 'CUSTOM' and preset not in CURVE_PRESET_ARITY)
                    or any(type(value) is not float or not math.isfinite(value) for value in parameters)):
                raise PropertyError("Malformed device layer fields")
            count = CURVE_PRESET_ARITY.get(preset, 0)
            if any(value != 0.0 for value in parameters[count:]):
                raise PropertyError("Unused curve parameters must be zero")
            curve = ResponseCurve() if preset == 'CUSTOM' else ResponseCurve(preset, parameters[:count])
            DeviceLayer(device, enabled, operation, factor, curve)
            result.append((device, enabled, operation, factor, preset, parameters[:count]))
        return tuple(result)

    def value_mode(self, identifier):
        identifier = policy_identifier(identifier)
        record = self._record(identifier)
        default = 'NATIVE_CAVITY' if identifier.startswith(CAVITY + '.') else 'UNIFIED'
        return record.get('value_mode', default) if record is not None else default

    def native_cavity_parent(self, parent):
        self._guard.check()
        local = self._native.cavity()
        if local is not None and (local.use_automasking_cavity or local.use_automasking_cavity_inverted):
            return False
        shared = parent._native.cavity() if parent is not None else None
        return shared is not None and (shared.use_automasking_cavity or shared.use_automasking_cavity_inverted)

    def unified(self, identifier):
        identifier = policy_identifier(identifier)
        record = self._record(identifier)
        if identifier in (STRENGTH, SIZE):
            return self._native.unified(identifier)
        if self.kind != 'SCENE':
            return False
        # The Shift-smooth settings are shared across brushes until a Scene
        # record says otherwise (shift_smooth.UNIFIED_BY_DEFAULT).
        from .shift_smooth import UNIFIED_BY_DEFAULT
        default = identifier in UNIFIED_BY_DEFAULT
        return record.get('unified', default) if record is not None else default

    def inherits_stack(self, identifier):
        if identifier in SIZE_ALIASES:
            return False
        record = self._record(identifier)
        return record.get('inherit_stack', False) if record is not None else False

    def _publish(self, definition, field, value, ui=None):
        return self._publish_fields(definition, (((field,), value, ui),))

    def _publish_fields(self, definition, fields, *, delete_paths=()):
        self._write_allowed()
        self._checked_definition(definition)
        prefix = ('records', record_key(definition.identifier))
        operations = (
            ('SET', ('schema_version',), SCHEMA_VERSION, None),
            ('SET', (*prefix, 'identifier'), definition.identifier, None),
            ('SET', (*prefix, 'scalar_type'), definition.scalar_type, None),
        ) + tuple(('SET', (*prefix, *path), value, ui) for path, value, ui in fields)
        operations += tuple(('DELETE', (*prefix, *path)) for path in delete_paths)
        if self.kind == 'BRUSH' and definition.identifier in legacy.BY_ID:
            from .migration import operations as migration_operations
            _, imported = migration_operations(self)
            operations = tuple({operation[1]: operation for operation in imported + operations}.values())
        try:
            return self.owner.id_properties_update_atomic(ROOT, operations)
        except (ValueError, TypeError, OverflowError, PermissionError) as error:
            raise PropertyError(str(error)) from error

    def read_positions(self, definition):
        """Local placement override, independent of resolved value/stack owners."""
        record = self._checked_definition(definition)
        if not _positions_header(record, reading=True):
            return definition.positions
        encoded = record['positions_order']
        if type(encoded) is not str or len(encoded) > 16384:
            raise PropertyError("Malformed positions order")
        try:
            keys = json.loads(encoded)
        except (ValueError, RecursionError):
            raise PropertyError("Malformed positions order JSON") from None
        if (type(keys) is not list or len(keys) > 128
                or any(type(key) is not str or not re.fullmatch(r'p_[a-z2-7]{52}', key) for key in keys)
                or len(set(keys)) != len(keys)):
            raise PropertyError("Malformed or duplicate position keys")
        entries = record.get('positions')
        if keys and entries is None:
            raise PropertyError("Missing positions group")
        result = []
        for key in keys:
            entry = entries.get(key)
            if not _group(entry):
                raise PropertyError("Malformed active position")
            position = Position(entry.get('location'), entry.get('sort_index'))
            if record_key(position.location) != key:
                raise PropertyError("Position key and location disagree")
            result.append(position)
        return validated_positions(result)

    def write_positions(self, definition, positions):
        self._write_allowed()
        positions = validated_positions(positions)
        record = self._checked_definition(definition)
        _positions_header(record, reading=False)
        entries = record.get('positions') if record is not None else None
        keys = [record_key(position.location) for position in positions]
        fields = [(('positions_version',), POSITIONS_VERSION, None),
                  (('positions_order',), json.dumps(keys, separators=(',', ':')), None)]
        for key, position in zip(keys, positions):
            if entries is not None and key in entries:
                entry = entries[key]
                if not _group(entry) or entry.get('location') != position.location:
                    raise PropertyError("Existing position identity is malformed or collides")
            fields.extend(((('positions', key, 'location'), position.location, None),
                           (('positions', key, 'sort_index'), position.sort_index, None)))
        self._publish_fields(definition, fields)

    def reset_positions(self, definition):
        """Remove only override headers; preserve dormant location metadata."""
        self._write_allowed()
        record = self._checked_definition(definition)
        if not _positions_header(record, reading=False):
            return
        self._publish_fields(definition, (), delete_paths=(('positions_version',), ('positions_order',)))

    def write_value(self, definition, value):
        self._write_allowed()
        self._checked_definition(definition)
        if self._native.handles(definition.identifier):
            self._native.write_value(definition, value)
            return
        value = definition.validate(value)
        self._publish(definition, 'value', value, value_metadata(definition))

    def write_stack(self, definition, layers):
        self._write_allowed()
        if definition.identifier in SIZE_ALIASES:
            raise PropertyError("Size representations share the common size stack")
        native_pressure = self._has_native_pressure(definition)
        layers = validated_stack(layers)
        if layers and not definition.dynamic:
            raise PropertyError("Static definitions cannot carry a device stack")
        fields = [(("stack_version",), STACK_VERSION, None),
                  (("layer_order",), ','.join(layer.device for layer in layers), None)]
        for layer in layers:
            # Revalidate descriptors before building the complete transaction.
            if type(layer.curve) is NativeCurveReference:
                if not native_pressure or layer.device != 'PRESSURE':
                    raise PropertyError("Native pressure curve targets the wrong property/device")
                self._native.curve_mapping(layer.curve)
                if layer.curve.identifier != definition.identifier:
                    raise PropertyError("Native mapping belongs to another property")
                curve, preset, parameters = layer.curve, 'CUSTOM', ()
            elif type(layer.curve) is CustomCurveReference:
                if native_pressure and layer.device == 'PRESSURE':
                    raise PropertyError("Brush pressure uses its authoritative native curve")
                self._curve_bank().mapping(self, definition, layer.curve)
                if layer.curve.device != layer.device:
                    raise PropertyError("Custom mapping device differs from its layer")
                curve, preset, parameters = layer.curve, 'CUSTOM', ()
            else:
                curve = ResponseCurve(layer.curve.preset, layer.curve.parameters)
                preset, parameters = curve.preset, tuple(float(value) for value in curve.parameters)
            layer = DeviceLayer(layer.device, layer.enabled, layer.operation, layer.factor, curve)
            values = dict(enabled=layer.enabled, operation=layer.operation, factor=float(layer.factor),
                          preset=preset)
            if native_pressure and layer.device == 'PRESSURE':
                del values['enabled']
            for index in range(3):
                values['parameter_' + str(index)] = parameters[index] if index < len(parameters) else 0.0
            fields.extend((("layers", layer.device, name), value, None) for name, value in values.items())
        record = self._checked_definition(definition)
        present = _stack_header(record, reading=False)
        if not layers and not present and not native_pressure:
            return
        if native_pressure:
            from .edits import rollback_edit
            enabled = next((layer.enabled for layer in layers if layer.device == 'PRESSURE'), False)
            # Preflight the selected native/shadow binding before publishing metadata.
            self._native.pressure_path(definition.identifier)
            with rollback_edit(self):
                self._publish_fields(definition, fields)
                self._native.write_pressure(definition.identifier, enabled)
        else:
            self._publish_fields(definition, fields)

    def write_mode(self, identifier, mode):
        self._write_allowed()
        identifier = policy_identifier(identifier)
        definition = self._definition(identifier)
        old = self.value_mode(identifier)
        modes = (*MODES, 'NATIVE_CAVITY') if identifier.startswith(CAVITY + '.') else MODES
        if self.kind != 'BRUSH' or type(mode) is not str or mode not in modes:
            raise PropertyError("Invalid Brush value inheritance mode")
        if mode != old:
            self._publish(definition, 'value_mode', mode)

    def write_stack_inheritance(self, identifier, enabled):
        self._write_allowed()
        if identifier in SIZE_ALIASES:
            raise PropertyError("Size representations share the common size stack")
        definition = self._definition(identifier)
        old = self.inherits_stack(identifier)
        if self.kind != 'BRUSH' or type(enabled) is not bool:
            raise PropertyError("Stack inheritance requires a Brush and bool")
        if enabled != old:
            self._publish(definition, 'inherit_stack', enabled)

    def write_unified(self, identifier, enabled):
        self._write_allowed()
        identifier = policy_identifier(identifier)
        definition = self._definition(identifier)
        old = self.unified(identifier)
        if self.kind != 'SCENE' or type(enabled) is not bool:
            raise PropertyError("Unified flag requires a Scene and bool")
        if identifier in (STRENGTH, SIZE):
            self._native.write_unified(identifier, enabled)
        elif enabled != old:
            self._publish(definition, 'unified', enabled)

    def metadata(self, identifier):
        definition = self._definition(identifier)
        self._record(identifier)
        if self._native.handles(identifier):
            parent, path = self._native.binding(identifier)
            prop = parent.bl_rna.properties[path]
            result = dict(default=prop.default, description=prop.description, subtype=prop.subtype)
            if prop.type != 'BOOLEAN':
                result.update(min=prop.hard_min, max=prop.hard_max,
                              soft_min=prop.soft_min, soft_max=prop.soft_max)
            return result
        return value_metadata(definition)

    def feature_enabled(self):
        """Generic is the release default; preserve an explicit saved opt-out."""
        self._guard.check()
        if self.kind != 'SCENE':
            raise PropertyError("Generic readiness switch belongs to Scene")
        root = _root(self.owner)
        value = root.get('generic_path_enabled', True) if root is not None else True
        if type(value) is not bool:
            raise PropertyError("Malformed generic readiness switch")
        return value

    def write_feature_enabled(self, enabled):
        self._write_allowed()
        current = self.feature_enabled()
        if type(enabled) is not bool:
            raise PropertyError("Generic readiness switch requires bool")
        if current == enabled:
            return
        try:
            self.owner.id_properties_update_atomic(ROOT, (
                ('SET', ('schema_version',), SCHEMA_VERSION, None),
                ('SET', ('generic_path_enabled',), enabled, None)))
        except (ValueError, TypeError, OverflowError, PermissionError) as error:
            raise PropertyError(str(error)) from error

    def value_path(self, identifier):
        """Full generic RNA path; reacquire its parent group after every commit."""
        self._record(identifier)
        if self._native.handles(identifier):
            raise PropertyError("Native settings use their authoritative RNA paths")
        return '["{}"]["records"]["{}"]["value"]'.format(ROOT, record_key(identifier))
