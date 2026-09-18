# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dependency-free tests of the actual modal spacer and acquisition sampler."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'sculptcore_addon' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stroke_math, stroke_input = load('stroke_math'), load('stroke_input')
tree = ast.parse((ROOT / 'sculptcore_addon/stroke.py').read_text())
spacer_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'StrokeSpacer')
namespace = dict(stroke_math=stroke_math, stroke_input=stroke_input)
exec(compile(ast.Module(body=[spacer_class], type_ignores=[]), 'stroke.py', 'exec'), namespace)
StrokeSpacer = namespace['StrokeSpacer']
InputSample, InputSampler = stroke_input.InputSample, stroke_input.InputSampler


def event(time=1.0, pressure=1.0, tilt=(0.0, 0.0), **overrides):
    values = dict(is_tablet=True, has_pressure=pressure is not None,
                  pressure=pressure or 0.0, has_time=time is not None, time=time or 0.0,
                  tilt=tilt, has_tilt_x=True, has_tilt_y=True, is_input_sample=True)
    values.update(overrides)
    return SimpleNamespace(**values)


class StrokeInputs(unittest.TestCase):
    def test_presence_and_zero(self):
        sampler = InputSampler()
        first = sampler.read(event(pressure=0, tilt=(-1, 0), has_tilt_y=False), (0, 0))
        self.assertEqual(first.channels, (0, 0, None, 0))
        self.assertEqual(first.batch_row(), (0, 0, 0, 0, 11))
        absent = sampler.read(event(time=None, pressure=None, has_tilt_x=False, has_tilt_y=False), (1, 1))
        self.assertEqual(absent.channels, (None, None, None, None))
        self.assertEqual(sampler.read(event(is_tablet=False), (1, 1)).pressure, 1)

    def test_time_reset_and_generated_moves(self):
        sampler = InputSampler(1000)
        self.assertIsNone(sampler.read(event(time=None), (0, 0)).speed)
        self.assertEqual(sampler.read(event(10), (0, 0)).speed, 0)
        self.assertIsNone(sampler.read(event(10.1, is_input_sample=False), (1000, 0)))
        self.assertAlmostEqual(sampler.read(event(10.2), (100, 0)).speed, .5)
        self.assertIsNone(sampler.read(event(10.2), (150, 0)).speed)
        self.assertEqual(sampler.read(event(11), (150, 0)).speed, 0)
        self.assertIsNone(sampler.read(event(9), (150, 0)).time)
        self.assertEqual(sampler.read(event(12), (150, 0)).speed, 0)
        self.assertEqual(sampler.read(event(12.1), (150, 0)).speed, 0)
        for invalid in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                InputSampler(invalid)

    def test_straight_arc_interpolation_and_release(self):
        spacer = StrokeSpacer()
        sampler = InputSampler()
        a = sampler.read(event(1, .2, (-1, 0)), (0, 0))
        b = sampler.read(event(1.1, 1, (1, 0)), (100, 0))
        first = spacer.add((0, 0), 25, a)
        self.assertEqual(first, [((0, 0), a)])
        self.assertEqual(spacer.add((100, 0), 25, b), [])
        points = spacer.flush(25)
        self.assertEqual(len(points), 4)
        for index, (point, sample) in enumerate(points, 1):
            self.assertAlmostEqual(point[0], index * 25, delta=.12)
            self.assertAlmostEqual(sample.pressure, .2 + .2 * index, places=6)
            self.assertAlmostEqual(sample.tilt_x, .25 * index, places=6)
            self.assertAlmostEqual(sample.time, 1 + .025 * index, places=6)
            self.assertAlmostEqual(sample.speed, 1, places=6)
        self.assertEqual(spacer.flush(25), [])

    def test_lookahead_uses_source_segment(self):
        spacer = StrokeSpacer()
        spacer.add((0, 0), 25, InputSample(pressure=.2))
        spacer.add((100, 0), 25, InputSample(pressure=1))
        points = spacer.add((200, 0), 25, InputSample(pressure=0))
        self.assertAlmostEqual(points[0][1].pressure, .4, places=6)
        self.assertAlmostEqual(points[-1][1].pressure, 1, places=6)

    def test_curved_uneven_knots_use_arc(self):
        points = ((-5, -50), (0, 0), (200, 30), (205, 300))
        bez = stroke_math.cr_to_bezier(*points)
        emitted, carry = stroke_math.arc_length_walk(bez, 20, 3, with_fractions=True)
        total = sum(stroke_math._dist(stroke_math.eval_cubic(bez, i / 32),
                                     stroke_math.eval_cubic(bez, (i + 1) / 32)) for i in range(32))
        self.assertGreater(len(emitted), 5)
        differs_from_parameter = False
        for index, (point, fraction) in enumerate(emitted):
            self.assertAlmostEqual(fraction, (17 + 20 * index) / total)
            # A point evaluated with this arc fraction as cubic t is generally elsewhere.
            differs_from_parameter |= stroke_math._dist(point, stroke_math.eval_cubic(bez, fraction)) > 1
        self.assertTrue(differs_from_parameter)
        self.assertLess(carry, 20)

    def test_missing_endpoint_and_fresh_upload(self):
        a, b = InputSample(.8, .2, None, 0, 1), InputSample(None, .6, .9, None, None)
        sample = InputSample.interpolate(a, b, .5)
        self.assertEqual(sample.channels, (None, .4, None, None))
        class Brush:
            def __init__(self): self.values = {0: 1, 1: 1, 2: 1, 3: 1}
            def clearDeviceInputs(self): self.values.clear()
            def pushDeviceInput(self, device, value): self.values[device] = value
        brush = Brush()
        sample.upload(brush)
        self.assertEqual(brush.values, {1: .4})

    def test_legacy_positions_and_grouping(self):
        coords = [(0, 0), (12, 30), (70, 18), (250, 90), (250, 90)]
        sampled, legacy = StrokeSpacer(), StrokeSpacer()
        emitted, expected = [], []
        for i, point in enumerate(coords):
            emitted.extend(sampled.add(point, 10, InputSample(pressure=i / 4)))
            expected.extend(legacy.add(point, 10))
        emitted.extend(sampled.flush(10))
        expected.extend(legacy.flush(10))
        self.assertEqual([point for point, sample in emitted], expected)
        with self.assertRaises(ValueError):
            sampled.add((0, 0), 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
