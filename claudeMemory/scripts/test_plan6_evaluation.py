# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent typed arithmetic and conversion expectations without Blender/DLL."""
from dataclasses import replace
import math
import struct
import unittest

from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package.adapters import BY_ID, SIZE, ValueDomain
from generic_property_test_package.commands import ExecutionLayer
from generic_property_test_package.evaluation import FLOAT_MAX, ScalarEvaluator, typed_bounds
from generic_property_test_package.registry import Definition, PropertyError, scalar
from generic_property_test_package.responses import PreparedResponse
from generic_property_test_package.snapshots import PropertySnapshot, SizeSnapshot

SAMPLES = (.5, .5, .5, .5)


def layer(response, *, device='PRESSURE', operation='MULTIPLY', factor=1.0, enabled=True):
    if not isinstance(response, PreparedResponse):
        response = PreparedResponse('CONSTANT', parameters=(response,))
    return ExecutionLayer(device, response, enabled, operation, factor)


def evaluator(kind, base, layers=(), *, low=None, high=None, identifier='test.scalar'):
    defaults = {'FLOAT32': (-FLOAT_MAX, FLOAT_MAX), 'INT32': (-2147483648, 2147483647), 'BOOL': (0, 1)}
    low = defaults[kind][0] if low is None else low
    high = defaults[kind][1] if high is None else high
    definition = Definition(identifier, 'Scalar', kind, base, low, high, low, high)
    return ScalarEvaluator(PropertySnapshot(definition, definition, definition.default, True, 'GENERIC',
                                            tuple(layers), True, False, ('execution:unavailable',)))


class EvaluationTests(unittest.TestCase):
    def test_operations_and_order(self):
        for operation, expected in (('REPLACE', .5), ('MULTIPLY', 1), ('ADD', 2.5),
                                    ('SUBTRACT', 1.5), ('DIFFERENCE', 1.5)):
            self.assertEqual(evaluator('FLOAT32', 2, (layer(.5, operation=operation),)).evaluate(SAMPLES), expected)
        stack = (layer(.5), layer(.4, device='SPEED', operation='ADD'))
        self.assertEqual(evaluator('INT32', 3, stack).evaluate(SAMPLES), 2)
        self.assertEqual(evaluator('INT32', 3, tuple(reversed(stack))).evaluate(SAMPLES), 2)
        ordered = (layer(2, operation='ADD'), layer(3, device='SPEED'))
        self.assertEqual(evaluator('INT32', 1, ordered).evaluate(SAMPLES), 9)
        self.assertEqual(evaluator('INT32', 1, tuple(reversed(ordered))).evaluate(SAMPLES), 5)

    def test_integer_boolean_and_bounds(self):
        for value, expected in ((3, 2), (-3, -2), (16777217, 16777217)):
            response = 1 if value == 16777217 else .5
            self.assertEqual(evaluator('INT32', value, (layer(response),)).evaluate(SAMPLES), expected)
        self.assertEqual(evaluator('INT32', 2147483647, (layer(1, operation='ADD'),)).evaluate(SAMPLES), 2147483647)
        for response, expected in ((.49, False), (.5, True)):
            self.assertIs(evaluator('BOOL', True, (layer(response),)).evaluate(SAMPLES), expected)
        self.assertEqual(evaluator('INT32', 1, (layer(0, operation='REPLACE'),), low=.2, high=1.6).evaluate(SAMPLES), 1)
        self.assertEqual(evaluator('INT32', 1, (layer(3, operation='REPLACE'),), low=.1, high=2.9).evaluate(SAMPLES), 2)
        self.assertIs(evaluator('BOOL', True, (layer(0, operation='REPLACE'),), low=.1).evaluate(SAMPLES), True)
        self.assertIs(evaluator('BOOL', False, (layer(1, operation='REPLACE'),), high=.9).evaluate(SAMPLES), False)
        value = evaluator('FLOAT32', 0, (layer(1, operation='REPLACE'),), low=0, high=.1).evaluate(SAMPLES)
        self.assertEqual(value, struct.unpack('f', struct.pack('I', 0x3dcccccc))[0])
        with self.assertRaises(PropertyError):
            typed_bounds(ValueDomain('INT32', .1, .9, .1, .9, 'NONE', 'test'))

    def test_transport_and_analytic_precision(self):
        response = PreparedResponse('TWO_STEP', parameters=(.5000000000000001, 0, 1))
        ev = evaluator('BOOL', True, (layer(response),))
        self.assertIs(ev.evaluate(SAMPLES), False)
        self.assertIs(ev.evaluate((.5000000596046448, None, None, None)), True)
        ev = evaluator('INT32', 17, (layer(99, operation='REPLACE'),))
        for sample in (None, math.nan, math.inf, -math.inf, 1e300):
            self.assertEqual(ev.evaluate((sample, None, None, None)), 17)
        with self.assertRaises(PropertyError):
            ev.evaluate((True, None, None, None))
        with self.assertRaises(PropertyError):
            ev.evaluate((.5,))

    def test_overflow_and_inactive_layers(self):
        self.assertEqual(evaluator('FLOAT32', 2, (layer(1e300),)).evaluate(SAMPLES), 2)
        self.assertEqual(evaluator('INT32', 2, (layer(1e300),)).evaluate(SAMPLES), 2147483647)
        self.assertIs(evaluator('BOOL', True, (layer(1e300),)).evaluate(SAMPLES), True)
        for factor in (0, 1):
            ev = evaluator('FLOAT32', -FLOAT_MAX, (layer(FLOAT_MAX, operation='REPLACE', factor=factor),))
            self.assertEqual(ev.evaluate(SAMPLES), -FLOAT_MAX)
        self.assertEqual(evaluator('FLOAT32', 3, (layer(2, enabled=False),)).evaluate(SAMPLES), 3)
        ev = evaluator('FLOAT32', -0.0, ())
        self.assertEqual(struct.pack('f', ev.evaluate(SAMPLES)), struct.pack('f', -0.0))

    def test_unit_conversion_order(self):
        ev = evaluator('INT32', 3, (layer(.5),), low=1, high=1000, identifier='sculptcore.brush.spacing')
        self.assertEqual(ev.engine_value(SAMPLES), scalar('FLOAT32', .02))
        ev = evaluator('FLOAT32', .75, (layer(.5),), low=0, high=1, identifier='sculptcore.brush.snake_pinch')
        self.assertEqual(ev.engine_value(SAMPLES), .25)
        ev = evaluator('FLOAT32', .25, (layer(.25, operation='ADD'),), low=0, high=1,
                       identifier='sculptcore.brush.strength')
        self.assertEqual(ev.engine_value(SAMPLES, strength_scale=2), 1)
        self.assertEqual(ev.snapshot.value, .25)

    def test_size_requires_projected_radius(self):
        pixel = ValueDomain('INT32', 1, 10000, 1, 1000, 'NONE', 'size')
        world = ValueDomain('FLOAT32', scalar('FLOAT32', .001), FLOAT_MAX, .01, 1, 'LENGTH', 'unprojected_size')
        size = SizeSnapshot(101, .75, 'VIEW', pixel, world)
        snapshot = PropertySnapshot(BY_ID[SIZE], pixel, 101, True, 'NATIVE',
                                    (layer(.5),), True, False, (), size)
        ev = ScalarEvaluator(snapshot)
        with self.assertRaises(PropertyError):
            ev.evaluate(SAMPLES)
        self.assertEqual(ev.evaluate(SAMPLES, projected_radius=.125), .0625)
        self.assertEqual(ev.evaluate(SAMPLES, projected_radius=0), 0)
        world_snapshot = replace(snapshot, value_domain=world, value=.75, size=replace(size, mode='SCENE'))
        self.assertEqual(ScalarEvaluator(world_snapshot).evaluate(SAMPLES, projected_radius=.125), .0625)


if __name__ == '__main__':
    unittest.main()
