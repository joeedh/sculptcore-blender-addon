# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exact typed host/native evaluator parity against the actual fixture DLL."""
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys

from run_blender_native_tests import suppress_error_dialogs
from test_plan6_evaluation import evaluator, layer, FLOAT_MAX, PreparedResponse
from generic_property_test_package.registry import DEVICE_TYPES, scalar

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'engine/python'))
import sculptcore
from sculptcore.brush_properties import DeviceLayer, UniformProperties

rng = random.Random(9182026)
dll = root / 'engine/build/native/sculptcore_capi.dll'
operations = ('REPLACE', 'MULTIPLY', 'ADD', 'SUBTRACT', 'DIFFERENCE')
comparisons = 0
with suppress_error_dialogs(), ExitStack() as owners:
    manager = sculptcore.init(str(dll))
    brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
    executor = owners.enter_context(manager.construct_with(
        manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), None, brush))
    tool = int(manager.get('sculptcore::brush::SculptBrushes').items['TYPEDPROBE'])
    access = UniformProperties(manager, executor, tool)
    indices = {item.name: item.index for item in access.uniforms}

    def compare(kind, base, layers, samples, *, low=None, high=None):
        global comparisons
        index = indices[{'FLOAT32': 'typed_gain', 'INT32': 'typed_count', 'BOOL': 'typed_enabled'}[kind]]
        host = evaluator(kind, base, layers, low=low, high=high)
        access.write(index, base)
        native_layers = []
        for item in layers:
            native_layers.append(DeviceLayer(DEVICE_TYPES.index(item.device), mode=operations.index(item.operation),
                factor=item.factor, enabled=item.enabled, samples=item.response.samples,
                response_kind=item.response.kind, parameters=item.response.parameters))
        access.replace_stack(index, tuple(native_layers))
        brush.clearDeviceInputs()
        for device, sample in enumerate(samples):
            if sample is not None:
                brush.pushDeviceInput(device, sample)
        native = access.read(index, evaluate=True)
        # Extra host-only domains have integral/inward FLOAT32 endpoints. Clamping
        # the unrestricted native result to these endpoints is independent here.
        _, bound_low, bound_high = host._domain
        native = bound_low if native < bound_low else bound_high if native > bound_high else native
        if kind == 'BOOL':
            native = bool(native)
        actual = host.evaluate(samples)
        same = struct.pack('f', actual) == struct.pack('f', native) if kind == 'FLOAT32' else actual == native
        assert same and type(actual) is type(native), (kind, base, layers, samples, actual, native)
        assert access.read(index) == base
        comparisons += 1

    for kind in ('FLOAT32', 'INT32', 'BOOL'):
        for index in range(160):
            base = (scalar('FLOAT32', rng.uniform(-4, 4)) if kind == 'FLOAT32' else
                    rng.choice((-2147483648, -3, 0, 3, 16777217, 2147483647)) if kind == 'INT32' else
                    bool(index % 2))
            layers = []
            for device in rng.sample(DEVICE_TYPES, rng.randrange(5)):
                response_kind = rng.randrange(3)
                response = (PreparedResponse('TABLE', tuple(scalar('FLOAT32', rng.uniform(-2, 3))
                                                           for _ in range(rng.choice((2, 3, 7, 256)))))
                            if response_kind == 0 else
                            PreparedResponse('CONSTANT', parameters=(rng.uniform(-3, 4),)) if response_kind == 1 else
                            PreparedResponse('TWO_STEP', parameters=(.5000000000000001, -.25, 1.75)))
                layers.append(layer(response, device=device, operation=rng.choice(operations),
                                    factor=rng.choice((0, .3, .5, 1)), enabled=rng.randrange(4) != 0))
            samples = tuple(rng.choice((None, -.3, .5, .5000000596046448, 1.3, math.nan, rng.random()))
                            for _ in range(4))
            compare(kind, base, tuple(layers), samples)
        base = True if kind == 'BOOL' else 3
        if kind == 'FLOAT32':
            base = 3.0
        for response in (1e300, -1e300, .5000000000000001):
            for factor in (0, .5, 1):
                compare(kind, base, (layer(response, operation='REPLACE', factor=factor),), (.5, None, None, None))
    # Exact endpoints, knot-neighbors, negative zero and subnormal table samples.
    tiny = struct.unpack('f', struct.pack('I', 1))[0]
    for table in ((-0.0, -0.0), (tiny, tiny * 2), (-FLOAT_MAX, FLOAT_MAX), (.25, -.75, 1.0)):
        response = PreparedResponse('TABLE', table)
        for sample in (0.0, -0.0, tiny, .4999999701976776, .5, .5000000596046448, 1.0):
            compare('FLOAT32', -0.0, (layer(response, operation='REPLACE'),), (sample, None, None, None))
    for factor in (0, 1):
        compare('FLOAT32', -FLOAT_MAX, (layer(FLOAT_MAX, operation='REPLACE', factor=factor),), (.5, None, None, None))
    for sample in (1e300, -1e300, math.inf):
        compare('INT32', 16777217, (layer(99, operation='REPLACE'),), (sample, None, None, None))
    compare('INT32', 1, (layer(0, operation='REPLACE'),), (.5, None, None, None), low=.2, high=1.6)
    compare('FLOAT32', 0.0, (layer(1, operation='REPLACE'),), (.5, None, None, None), low=0, high=.1)
    compare('BOOL', True, (layer(0, operation='REPLACE'),), (.5, None, None, None), low=.1)
result = dict(passed=True, comparisons=comparisons, bitwise_float32=True, dll=str(dll),
              sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), seed=9182026)
(root / 'claudeMemory/tests/plan6-domains-native.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_DOMAINS_NATIVE_PASS', json.dumps(result), flush=True)
