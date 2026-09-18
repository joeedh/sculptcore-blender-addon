# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Command ancestry and immutable execution boundary tests, without Blender."""
from dataclasses import FrozenInstanceError, replace
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
package_path = ROOT / 'sculptcore_addon/brush_properties'
spec = importlib.util.spec_from_file_location('plan6_properties', package_path / '__init__.py',
                                            submodule_search_locations=[str(package_path)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)

from plan6_properties.commands import Command, ExecutionLayer, ExecutionValue, Parent, resolve_commands
from plan6_properties.registry import Definition, DeviceLayer, PropertyError
from plan6_properties.responses import PreparedResponse

GAIN = Definition('sculptcore.gain', 'Gain', 'FLOAT32', .25, 0, 10, 0, 1)
COUNT = Definition('sculptcore.count', 'Count', 'INT32', 16777217, -2147483648, 2147483647, 0, 20000000)
ENABLED = Definition('sculptcore.enabled', 'Enabled', 'BOOL', True, 0, 1, 0, 1)
STATIC = Definition('sculptcore.static', 'Static', 'BOOL', False, 0, 1, 0, 1, dynamic=False)
PRESSURE = ExecutionLayer('PRESSURE', PreparedResponse('TABLE', (0.0, 1.0)))
SPEED = ExecutionLayer('SPEED', PreparedResponse('CONSTANT', parameters=(.5,)), operation='ADD')


class CommandTests(unittest.TestCase):
    def test_forward_parent_order_independent_and_separate_stacks(self):
        brush = (ExecutionValue(GAIN, .75, (PRESSURE,)),)
        root = Command('main', 1, (GAIN,), values=((GAIN.identifier, .5),))
        child = Command('smooth', 2, (GAIN,), Parent('COMMAND', 'main'), stacks=((GAIN.identifier, (SPEED,)),))
        for order in ((child, root), (root, child)):
            result = resolve_commands(order, brush)
            self.assertEqual(tuple(item.name for item in result), tuple(item.name for item in order))
            mapped = {item.name: item.properties[0] for item in result}
            self.assertEqual(mapped['smooth'].value, .5)
            self.assertEqual(mapped['smooth'].stack, (SPEED,))
            self.assertEqual(mapped['main'].stack, (PRESSURE,))
        self.assertEqual(brush[0].value, .75)

    def test_defaults_empty_and_transitive_empty_are_distinct_from_absence(self):
        brush = (ExecutionValue(GAIN, .75, (PRESSURE,)),)
        commands = (
            Command('brush', 1, (GAIN,)),
            Command('defaults', 1, (GAIN,), Parent('DEFAULTS')),
            Command('empty', 1, (GAIN,), stacks=((GAIN.identifier, ()),)),
            Command('child', 1, (GAIN,), Parent('COMMAND', 'empty')),
        )
        result = resolve_commands(commands, brush)
        self.assertEqual([item.properties[0].stack for item in result], [(PRESSURE,), (), (), ()])
        self.assertEqual([item.properties[0].value for item in result], [.75, .25, .75, .75])
        self.assertFalse(hasattr(result[0], 'parent'))

    def test_cross_kernel_ids_never_inherit_by_engine_spelling(self):
        first = replace(GAIN, identifier='sculptcore.bsmooth.projection')
        second = replace(GAIN, identifier='sculptcore.nudge.projection', default=.125)
        result = resolve_commands((
            Command('a', 1, (first,), values=((first.identifier, .75),)),
            Command('b', 2, (second,), Parent('COMMAND', 'a')),
        ), ())
        self.assertEqual(result[1].properties[0].value, .125)
        with self.assertRaises(PropertyError):
            Command('b', 2, (second,), values=((first.identifier, .75),))

    def test_strict_typed_overrides_and_schema(self):
        result = resolve_commands((Command('a', 1, (COUNT, ENABLED, STATIC)),), ())
        self.assertEqual(result[0].properties[0].value, 16777217)
        self.assertIs(result[0].properties[1].value, True)
        for definition, value in ((COUNT, 1.5), (COUNT, True), (ENABLED, 1), (GAIN, float('nan'))):
            with self.subTest(definition=definition.identifier, value=value), self.assertRaises(PropertyError):
                Command('a', 1, (definition,), values=((definition.identifier, value),))
        with self.assertRaises(PropertyError):
            resolve_commands((Command('a', 1, (replace(GAIN, maximum=20),)),), (ExecutionValue(GAIN, .5),))

    def test_cycles_missing_and_duplicate_names(self):
        cases = (
            (Command('a', 1, (), Parent('COMMAND', 'a')),),
            (Command('ok', 1, ()), Command('a', 1, (), Parent('COMMAND', 'b')),
             Command('b', 1, (), Parent('COMMAND', 'a'))),
            (Command('a', 1, (), Parent('COMMAND', 'missing')),),
            (Command('a', 1, ()), Command('a', 2, ())),
        )
        for commands in cases:
            with self.subTest(commands=commands), self.assertRaises(PropertyError):
                resolve_commands(commands, ())
        chain = [Command(str(index), 1, (GAIN,), Parent('COMMAND', str(index + 1))) for index in range(1500)]
        chain.append(Command('1500', 1, (GAIN,)))
        self.assertEqual(len(resolve_commands(chain, ())), 1501)

    def test_duplicate_and_unavailable_stacks_reject_before_maps(self):
        for values, stacks in (
            (((GAIN.identifier, .5), (GAIN.identifier, .25)), ()),
            ((), ((GAIN.identifier, ()), (GAIN.identifier, ()))),
            ((), ((GAIN.identifier, None),)),
            ((), ((GAIN.identifier, (PRESSURE, PRESSURE)),)),
            ((), ((GAIN.identifier, (DeviceLayer('PRESSURE'),)),)),
        ):
            with self.assertRaises(PropertyError):
                Command('a', 1, (GAIN,), values=values, stacks=stacks)
        with self.assertRaises(PropertyError):
            Command('a', 1, (STATIC,), stacks=((STATIC.identifier, ()),))
        with self.assertRaises(PropertyError):
            ExecutionLayer('PRESSURE', PreparedResponse('CONSTANT', parameters=(1,)), False, factor=2)

    def test_snapshot_copies_containers_and_has_no_owners(self):
        stack, definitions, values = [PRESSURE], [GAIN], [[GAIN.identifier, .5]]
        command = Command('a', 1, definitions, values=values, stacks=[[GAIN.identifier, stack]])
        result = resolve_commands([command], ())
        stack.clear()
        definitions.clear()
        values[0][1] = .75
        self.assertEqual(result[0].properties[0].value, .5)
        self.assertEqual(result[0].properties[0].stack, (PRESSURE,))
        with self.assertRaises(FrozenInstanceError):
            result[0].properties[0].value = .75


if __name__ == '__main__':
    unittest.main()
