# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent owner-table and typed authoring checks without Blender or a DLL."""

import builtins
from dataclasses import FrozenInstanceError, replace
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_package():
    path = ROOT / 'sculptcore_addon/brush_properties'
    spec = importlib.util.spec_from_file_location('generic_property_test_package', path / '__init__.py',
                                                submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in ('bpy', 'sculptcore', 'sculptcore_addon', 'engine'):
            raise AssertionError('Unexpected Blender/engine dependency: ' + name)
        return original(name, *args, **kwargs)

    with patch('builtins.__import__', guarded):
        spec.loader.exec_module(module)
        native_spec = importlib.util.spec_from_file_location(spec.name + '.native', path / 'native.py')
        native = importlib.util.module_from_spec(native_spec)
        sys.modules[native_spec.name] = native
        native_spec.loader.exec_module(native)
        storage_spec = importlib.util.spec_from_file_location(spec.name + '.storage', path / 'storage.py')
        storage = importlib.util.module_from_spec(storage_spec)
        sys.modules[storage_spec.name] = storage
        storage_spec.loader.exec_module(storage)
    return module, native


package, native = load_package()
from generic_property_test_package.registry import (
    Definition, DeviceLayer, Position, PropertyError, Registry, ResponseCurve, UnknownDefinition)
from generic_property_test_package.resolver import (
    Capability, ValueSource, resolve, set_layer_enabled, set_stack, set_stack_inheritance,
    set_unified, set_value, set_value_mode, update_layer)

KEY = 'sculptcore.test.value'


class Store:
    """Test fixture only, implementing the eventual RNA storage protocol."""

    def __init__(self, kind, serial):
        self.kind, self.identity, self.editable = kind, (1, kind, serial), True
        self.values, self.stacks, self.modes, self.flags, self.inherits = {}, {}, {}, {}, {}
        self.cap = Capability()

    def capability(self, definition): return self.cap
    def read_value(self, definition): return self.values.get(definition.identifier, ValueSource())
    def read_stack(self, definition): return self.stacks.get(definition.identifier, ())
    def value_mode(self, identifier): return self.modes.get(identifier, 'UNIFIED')
    def unified(self, identifier): return self.flags.get(identifier, False)
    def inherits_stack(self, identifier): return self.inherits.get(identifier, False)
    def write_value(self, definition, value): self.values[definition.identifier] = ValueSource(value, True)
    def write_stack(self, definition, layers): self.stacks[definition.identifier] = layers
    def write_mode(self, identifier, mode): self.modes[identifier] = mode
    def write_unified(self, identifier, enabled): self.flags[identifier] = enabled
    def write_stack_inheritance(self, identifier, enabled): self.inherits[identifier] = enabled


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.definition = self.registry.register(Definition(KEY, 'Value', 'FLOAT32', .5, 0, 10, 0, 1))
        self.brush, self.scene = Store('BRUSH', 1), Store('SCENE', 2)
        self.brush.write_value(self.definition, .25)
        self.scene.write_value(self.definition, .75)
        self.local_stack = (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),)
        self.scene_stack = (DeviceLayer('SPEED', operation='ADD'),)
        self.brush.stacks[KEY], self.scene.stacks[KEY] = self.local_stack, self.scene_stack

    def read(self):
        return resolve(self.registry, KEY, self.brush, self.scene)

    def test_all_twelve_owner_combinations_and_effective_writes(self):
        for mode in ('UNIFIED', 'ALWAYS', 'NEVER'):
            for unified in (False, True):
                for inherit in (False, True):
                    with self.subTest(mode=mode, unified=unified, inherit=inherit):
                        self.setUp()
                        set_value_mode(self.registry, KEY, self.brush, mode)
                        set_unified(self.registry, KEY, self.scene, unified)
                        set_stack_inheritance(self.registry, KEY, self.brush, inherit)
                        result = self.read()
                        parent_value = mode == 'ALWAYS' or (mode == 'UNIFIED' and unified)
                        self.assertIs(result.value_owner, self.scene if parent_value else self.brush)
                        self.assertIs(result.stack_owner, self.scene if inherit else self.brush)
                        self.assertEqual(result.value, .75 if parent_value else .25)
                        self.assertEqual(result.stack, self.scene_stack if inherit else self.local_stack)
                        set_value(self.registry, KEY, self.brush, self.scene, .625)
                        self.assertEqual(self.scene.values[KEY].value, .625 if parent_value else .75)
                        self.assertEqual(self.brush.values[KEY].value, .25 if parent_value else .625)
                        set_stack(self.registry, KEY, self.brush, self.scene, ())
                        self.assertEqual(self.brush.stacks[KEY], self.local_stack if inherit else ())
                        self.assertEqual(self.scene.stacks[KEY], () if inherit else self.scene_stack)

    def test_policy_edits_preserve_dormant_values_and_root_never_inherits(self):
        set_value_mode(self.registry, KEY, self.brush, 'ALWAYS')
        self.assertEqual(self.read().value, .75)
        set_value_mode(self.registry, KEY, self.brush, 'NEVER')
        self.assertEqual(self.read().value, .25)
        self.assertEqual(self.scene.modes, {})
        root = resolve(self.registry, KEY, self.scene, self.brush)
        self.assertIs(root.value_owner, self.scene)
        with self.assertRaises(PropertyError): set_value_mode(self.registry, KEY, self.scene, 'ALWAYS')
        self.brush.editable = False
        with self.assertRaises(PropertyError): set_stack_inheritance(self.registry, KEY, self.brush, True)
        self.assertEqual(self.brush.inherits, {})

    def test_read_only_effective_owner_and_invalid_write_atomicity(self):
        set_value_mode(self.registry, KEY, self.brush, 'ALWAYS')
        self.brush.editable = False
        set_value(self.registry, KEY, self.brush, self.scene, .625)
        self.scene.editable = False
        for bad in (.5, float('nan'), True, 11):
            with self.assertRaises(PropertyError): set_value(self.registry, KEY, self.brush, self.scene, bad)
        self.assertEqual(self.brush.values[KEY].value, .25)
        self.assertEqual(self.scene.values[KEY].value, .625)

    def test_absent_defaults_and_unknowns_never_allocate_or_delete(self):
        self.brush.values.clear()
        self.brush.stacks.clear()
        for _ in range(5):
            result = self.read()
            self.assertEqual((result.value, result.stack, result.value_source.present), (.5, (), False))
        self.assertEqual((self.brush.values, self.brush.stacks), ({}, {}))
        self.brush.values['future.unknown'] = ValueSource(77, True)
        with self.assertRaises(UnknownDefinition): resolve(self.registry, 'future.unknown', self.brush, self.scene)
        self.assertEqual(self.brush.values['future.unknown'].value, 77)

    def test_independent_capability_fallbacks_and_keys(self):
        set_value_mode(self.registry, KEY, self.brush, 'ALWAYS')
        set_stack_inheritance(self.registry, KEY, self.brush, True)
        before = self.read().invalidation_key
        self.scene.cap = Capability(True, False)
        result = self.read()
        self.assertIs(result.value_owner, self.scene)
        self.assertIs(result.stack_owner, self.brush)
        self.assertIn('stack:parent_unavailable', result.diagnostics)
        self.assertNotEqual(before, result.invalidation_key)
        self.scene.cap = Capability(False, True)
        result = self.read()
        self.assertIs(result.value_owner, self.brush)
        self.assertIs(result.stack_owner, self.scene)
        self.assertIn('value:parent_unavailable', result.diagnostics)
        self.scene.cap = self.brush.cap = Capability(True, False, False)
        result = self.read()
        self.assertIsNone(result.stack)
        self.assertFalse(result.execution_available)
        set_value(self.registry, KEY, self.brush, self.scene, .625)
        with self.assertRaises(PropertyError): set_stack(self.registry, KEY, self.brush, self.scene, ())

    def test_unique_ordered_devices_and_disabled_preservation(self):
        layer = DeviceLayer('TILT_X', factor=.25, curve=ResponseCurve('TWO_STEP', (.5, -1, 2)))
        update_layer(self.registry, KEY, self.brush, self.scene, layer)
        set_layer_enabled(self.registry, KEY, self.brush, self.scene, 'TILT_X', False)
        result = self.read()
        self.assertEqual(result.stack, self.local_stack + (replace(layer, enabled=False),))
        with self.assertRaises(PropertyError):
            set_stack(self.registry, KEY, self.brush, self.scene, (layer, layer))
        self.assertEqual(self.read().stack, result.stack)
        self.brush.stacks[KEY] = (layer, layer)
        with self.assertRaises(PropertyError): self.read()
        self.assertEqual(self.brush.stacks[KEY], (layer, layer))
        set_stack(self.registry, KEY, self.brush, self.scene, (layer,))
        self.assertEqual(self.read().stack, (layer,))
        with self.assertRaises(PropertyError): DeviceLayer('PRESSURE', enabled=False, factor=float('nan'))
        with self.assertRaises(PropertyError): DeviceLayer('TWIST')

    def test_scalar_types_ranges_and_exact_integer(self):
        integer = Definition('test.int', 'Count', 'INT32', 16777217, -2147483648, 2147483647, 0, 20)
        boolean = Definition('test.bool', 'Enabled', 'BOOL', True, 0, 1, 0, 1)
        self.assertEqual(integer.validate(16777217), 16777217)
        for invalid in (True, 1.0, 2147483648, -2147483649):
            with self.assertRaises(PropertyError): integer.validate(invalid)
        for invalid in (1, 0, .5):
            with self.assertRaises(PropertyError): boolean.validate(invalid)
        for invalid in (True, float('inf'), float('nan'), 10**400, 1e100, -1):
            with self.assertRaises(PropertyError): self.definition.validate(invalid)
        for definition in (integer, boolean):
            self.registry.register(definition)
            set_value(self.registry, definition.identifier, self.brush, self.scene, definition.default)
            self.assertEqual(resolve(self.registry, definition.identifier, self.brush, self.scene).value,
                             definition.default)

    def test_definition_deep_immutability_positions_and_registry_revision(self):
        positions = [Position('HEADER'), Position('PANEL', 2)]
        definition = replace(self.definition, positions=positions)
        registry = Registry()
        registry.register(definition)
        revision = registry.revision
        registry.register(definition)
        self.assertEqual(registry.revision, revision)
        positions.clear()
        self.assertEqual(len(definition.positions), 2)
        with self.assertRaises(FrozenInstanceError): definition.positions[0].sort_index = 1
        with self.assertRaises(PropertyError): registry.register(replace(definition, label='Conflict'))
        self.assertEqual(registry.revision, revision)
        with self.assertRaises(PropertyError): replace(definition, soft_maximum=11)
        with self.assertRaises(PropertyError): replace(definition, positions=(Position('HEADER'),) * 2)
        before = self.read().invalidation_key
        self.registry.register(replace(self.definition, identifier='test.extra'))
        self.assertNotEqual(before, self.read().invalidation_key)

    def test_execution_availability_does_not_discard_authoring(self):
        before = self.read()
        self.brush.cap = Capability(True, True, False, 'kernel_missing')
        after = self.read()
        self.assertEqual((before.value, before.stack), (after.value, after.stack))
        self.assertFalse(after.execution_available)
        self.assertNotEqual(before.invalidation_key, after.invalidation_key)
        self.assertEqual(self.brush.values[KEY].value, .25)

    def test_owner_restricted_metadata_and_malformed_capabilities(self):
        self.registry.register(replace(self.definition, identifier='test.scene', owners={'SCENE'}))
        self.registry.register(replace(self.definition, identifier='test.brush', owners={'BRUSH'}))
        for function, identifier, owner, argument in (
                (set_value_mode, 'test.scene', self.brush, 'ALWAYS'),
                (set_stack_inheritance, 'test.scene', self.brush, True),
                (set_unified, 'test.brush', self.scene, True)):
            with self.assertRaises(PropertyError): function(self.registry, identifier, owner, argument)
        self.assertEqual((self.brush.modes, self.brush.inherits, self.scene.flags), ({}, {}, {}))
        for keywords in ({'value': 'False'}, {'stack': 0}, {'execution': 1}, {'reason': []}):
            with self.assertRaises(PropertyError): Capability(**keywords)
        for keywords in ({'present': 'False'}, {'source': []}, {'value': 1, 'present': False}):
            with self.assertRaises(PropertyError): ValueSource(**keywords)
        self.scene.cap = object()
        with self.assertRaises(PropertyError): set_value(self.registry, KEY, self.brush, self.scene, .5)
        self.assertEqual(self.brush.values[KEY].value, .25)

    def test_whole_value_replacement_can_repair_without_consuming_invalid_old_value(self):
        self.brush.values[KEY] = ValueSource(float('nan'), True)
        with self.assertRaises(PropertyError): self.read()
        set_value(self.registry, KEY, self.brush, self.scene, .625)
        self.assertEqual(self.read().value, .625)


if __name__ == '__main__':
    unittest.main(verbosity=2)
