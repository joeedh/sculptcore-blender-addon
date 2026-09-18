# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare native semantic collections with the independent typed host evaluator."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import random
import struct
import sys

import bpy
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE
from sculptcore_addon.brush_properties.commands import ExecutionLayer
from sculptcore_addon.brush_properties.registry import Definition, PropertyError
from sculptcore_addon.brush_properties.responses import PreparedResponse
from sculptcore_addon.brush_properties.snapshots import PropertySnapshot

root = Path(__file__).resolve().parents[2]
for name in ('stroke_settings', 'native_evaluation'):
    full_name = 'sculptcore_addon.brush_properties.' + name
    spec = importlib.util.spec_from_file_location(full_name, root / 'sculptcore_addon/brush_properties' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke
from sculptcore_addon.brush_properties.native_evaluation import NativeEvaluation

brush = bpy.data.brushes.new('Native Semantic Test', mode='SCULPT')
brush.sculpt_brush_type = 'SNAKE_HOOK'
settings = capture_stroke(brush, bpy.context.scene)
rng = random.Random(9182026)
layers = (
    ExecutionLayer('PRESSURE', PreparedResponse('CONSTANT', parameters=(.5,)), operation='MULTIPLY'),
    ExecutionLayer('SPEED', PreparedResponse('TWO_STEP', parameters=(.5000000000000001, -.5, .75)),
                   operation='ADD'),
)
properties = tuple(replace(item, stack=layers) if item.definition.dynamic else item
                   for item in settings.properties)
for kind, base, low, high in (('FLOAT32', .25, -1, 1), ('INT32', 16777217, -2147483648, 2147483647),
                              ('BOOL', True, 0, 1)):
    definition = Definition('test.' + kind, kind, kind, base, low, high, low, high)
    properties += (PropertySnapshot(definition, definition, definition.default, True, 'TEST', layers,
                                    True, False, ()),)
settings = replace(settings, properties=properties)
rows, radii, channels = [], [], []
for index in range(100):
    values = tuple(rng.choice((None, .5, .5000000596046448, rng.random())) for _ in range(4))
    mask = sum(1 << device for device, value in enumerate(values) if value is not None)
    rows.append(tuple(0.0 if value is None else value for value in values) + (mask,))
    radii.append(.01 + index / 100)
    channels.append(values)
comparisons = 0
with NativeEvaluation(settings) as native:
    output = native.evaluate(rows, radii)
    for row, values in enumerate(channels):
        radius = struct.unpack('f', struct.pack('f', radii[row]))[0]
        for column, item in enumerate(settings.properties):
            identifier = item.definition.identifier
            expected = settings.value(identifier, values, **({'projected_radius': radius} if identifier == SIZE else {}))
            actual = output[row, column]
            if type(expected) is float:
                assert struct.pack('f', expected) == struct.pack('f', actual), (row, identifier, expected, actual)
            else:
                assert expected == actual, (row, identifier, expected, actual)
            comparisons += 1
    for bad_rows, bad_radii in (([rows[0][:-1] + (16,)], [1]), ([rows[0]], [-1])):
        try:
            native.evaluate(bad_rows, bad_radii)
        except PropertyError:
            pass
        else:
            raise AssertionError('Malformed native input accepted')
try:
    native.evaluate(rows, radii)
except PropertyError:
    pass
else:
    raise AssertionError('Closed collection remained usable')
(root / 'claudeMemory/tests/plan6-native-semantics.json').write_text(
    json.dumps(dict(passed=True, comparisons=comparisons), indent=2) + '\n', encoding='utf-8')
print('PLAN6_NATIVE_SEMANTICS_PASS', comparisons)
if not bpy.app.background:
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=.3)
