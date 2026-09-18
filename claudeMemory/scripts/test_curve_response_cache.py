# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent response oracles and bounded cache tests without Blender/engine imports."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package.registry import PropertyError, ResponseCurve
from generic_property_test_package.responses import PreparedResponse, SampleConfig, evaluate, sample
from generic_property_test_package.sampling import ResponseCache
from generic_property_test_package.edits import authoring_edit, _active
from types import SimpleNamespace


class ResponseTests(unittest.TestCase):
    def test_commit_failure_cancels(self):
        calls = []
        def commit(*_args):
            raise RuntimeError('commit failure')
        owner = SimpleNamespace(authoring_edit_begin=lambda **kw: 12, authoring_edit_commit=commit,
                                authoring_edit_cancel=lambda token: calls.append(token))
        store = SimpleNamespace(owner=owner, identity=('test',), _guard=SimpleNamespace(check=lambda **kw: True))
        with self.assertRaisesRegex(RuntimeError, 'commit failure'):
            with authoring_edit(store):
                pass
        self.assertEqual(calls, [12])
        self.assertFalse(_active)

    def test_presets(self):
        expected = dict(LINEAR=.25, ROOT=.5, SQUARE=.0625, SMOOTHSTEP=.15625,
                        SMOOTHERSTEP=.103515625, SPHERE=math.sqrt(.4375), POW4=.00390625, INVSQUARE=.4375)
        for name, middle in expected.items():
            curve = ResponseCurve(name)
            self.assertEqual(evaluate(curve, -1), 0)
            self.assertEqual(evaluate(curve, 2), 1)
            self.assertAlmostEqual(evaluate(curve, .25), middle)

    def test_analytic_thresholds(self):
        for threshold in (0, .5, 1):
            curve = ResponseCurve('TWO_STEP', (threshold, -3, 16777217))
            self.assertEqual(evaluate(curve, threshold), 16777217)
            if threshold:
                self.assertEqual(evaluate(curve, math.nextafter(threshold, -math.inf)), -3)
            self.assertEqual(evaluate(curve, math.nextafter(threshold, math.inf)), 16777217)
            response = ResponseCache().generated(curve)
            self.assertEqual(response.kind, 'TWO_STEP')
            self.assertEqual(response.samples, ())
        self.assertEqual(evaluate(ResponseCurve('CONSTANT', (1e100,)), .5), 1e100)

    def test_generated_reuse_and_eviction(self):
        cache = ResponseCache(4)
        curve = ResponseCurve('SQUARE')
        active = cache.generated(curve)
        self.assertIs(active, cache.generated(ResponseCurve('SQUARE')))
        self.assertEqual(cache.bakes, 1)
        for i in range(300):
            cache.generated(ResponseCurve('CONSTANT', (i,)))
        self.assertEqual((len(cache.sources), len(cache.contents), len(cache.identities)), (4, 4, 4))
        self.assertTrue(all(type(value) is int for value in cache.sources.values()))
        self.assertEqual(active.samples[-1], 1)
        cache.clear()
        self.assertFalse(cache.sources or cache.contents or cache.identities)

    def test_hash_collisions_do_not_alias(self):
        class Key:
            def __init__(self, value):
                self.value = value
            def __hash__(self):
                return 1
            def __eq__(self, other):
                return isinstance(other, Key) and self.value == other.value
        cache = ResponseCache()
        a, b = PreparedResponse('CONSTANT', parameters=(1,)), PreparedResponse('CONSTANT', parameters=(2,))
        cache.put(Key('a'), a, SampleConfig())
        cache.put(Key('b'), b, SampleConfig())
        self.assertIs(cache.get(Key('a')), a)
        self.assertIs(cache.get(Key('b')), b)

    def test_direction_hardness_and_validation(self):
        self.assertEqual(sample(lambda x: x, SampleConfig(3, reverse=True)), (1, .5, 0))
        self.assertEqual(sample(lambda x: x, SampleConfig(3, hardness=1)), (0, 1, 1))
        self.assertEqual(sample(lambda x: 2 * x, SampleConfig(3, clamp_output=True)), (0, 1, 1))
        for count in (0, 1, True, 65537):
            with self.assertRaises(PropertyError):
                SampleConfig(count)
        with self.assertRaises(PropertyError):
            sample(lambda x: float('nan'), SampleConfig())
        with self.assertRaises(PropertyError):
            sample(lambda x: 1e100, SampleConfig())


if __name__ == '__main__':
    unittest.main()
