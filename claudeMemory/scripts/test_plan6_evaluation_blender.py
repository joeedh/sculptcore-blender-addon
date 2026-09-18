# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual effective-owner snapshots through typed host unit conversion."""
import json
from pathlib import Path
from unittest.mock import patch
import bpy

from sculptcore_addon.brush_properties import authoring, customize, lifecycle, sampling
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH
from sculptcore_addon.brush_properties.evaluation import ScalarEvaluator, SPACING, SNAKE_PINCH
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve, scalar
from sculptcore_addon.brush_properties.snapshots import capture
from sculptcore_addon.brush_properties.storage import ROOT

checks = []
registry = authoring.registry
brush = bpy.data.brushes.new('Plan6Evaluation', mode='SCULPT')
scene = bpy.context.scene
local, parent = authoring.store(brush), authoring.store(scene)
ids = (SPACING, SNAKE_PINCH, STRENGTH, SIZE)
for identifier in ids:
    local.write_mode(identifier, 'ALWAYS')
    local.write_stack_inheritance(identifier, False)
parent.write_value(registry.get(SPACING), 3)
parent.write_value(registry.get(SNAKE_PINCH), .75)
brush.spacing = 21
brush.crease_pinch_factor = .625
brush.strength = .125
ups = scene.tool_settings.sculpt.unified_paint_settings
ups.strength = .25
brush.size, brush.unprojected_size, brush.use_locked_size = 101, .125, 'VIEW'
ups.size, ups.unprojected_size, ups.use_locked_size = 303, .75, 'SCENE'
for identifier in (SPACING, SNAKE_PINCH):
    local.write_stack(registry.get(identifier), (DeviceLayer('SPEED', curve=ResponseCurve('CONSTANT', (.5,))),))
local.write_stack(registry.get(STRENGTH), (DeviceLayer('PRESSURE', operation='ADD',
                                                     curve=ResponseCurve('CONSTANT', (.25,))),))
customize.customize(local, registry.get(STRENGTH), 'PRESSURE', reseed=True, undo=False)
parent.write_stack(registry.get(SIZE), (DeviceLayer('TILT_X', operation='ADD',
                                                  curve=ResponseCurve('CONSTANT', (.125,))),))
customize.customize(parent, registry.get(SIZE), 'TILT_X', undo=False)
local.write_stack_inheritance(SIZE, True)
before = (brush[ROOT].to_dict(), scene[ROOT].to_dict())
snapshots = capture(registry, ids, local, parent)
compiled = {item.definition.identifier: ScalarEvaluator(item) for item in snapshots}
assert (brush[ROOT].to_dict(), scene[ROOT].to_dict()) == before
checks.append('capture/compilation preserves persistent records and independent owners')
inputs = (.5, .5, None, .5)
assert compiled[SPACING].evaluate(inputs) == 2
assert compiled[SPACING].engine_value(inputs) == scalar('FLOAT32', .02)
assert brush.spacing == 21
checks.append('Scene INT32 spacing rounds before percent conversion; dormant local is intact')
assert compiled[SNAKE_PINCH].engine_value(inputs) == .25 and brush.crease_pinch_factor == .625
checks.append('native-domain snake dynamics precede its nonlinear-direction remap')
assert compiled[STRENGTH].engine_value(inputs, strength_scale=2) == 1
assert brush.strength == .125 and ups.strength == .25
checks.append('Scene strength with Brush native custom curve evaluates before compensation')
size = compiled[SIZE].snapshot.size
assert (size.pixels, size.world, size.mode) == (303, .75, 'SCENE')
assert compiled[SIZE].engine_value(inputs, projected_radius=.375) == .5
assert compiled[SIZE].engine_value(inputs, projected_radius=.1875) == .3125
checks.append('effective SIZE pair and Scene custom stack evaluate once on supplied object-space radius')

bakes = sampling.cache.bakes
sampling.clear()
lifecycle._invalidate()
bpy.data.brushes.remove(brush)
with patch.object(lifecycle, '_main_thread', side_effect=AssertionError('No owner access during evaluation')), \
        patch.object(sampling, 'resolved_response', side_effect=AssertionError('No curve sampling per dab')):
    for _ in range(200):
        assert compiled[SPACING].engine_value(inputs) == scalar('FLOAT32', .02)
        assert compiled[SNAKE_PINCH].engine_value(inputs) == .25
        assert compiled[STRENGTH].engine_value(inputs, strength_scale=2) == 1
        assert compiled[SIZE].engine_value(inputs, projected_radius=.375) == .5
assert sampling.cache.bakes == bakes
checks.append('800 warm evaluations survive owner deletion/cache retirement with no owner access or new bakes')
result = dict(passed=True, checks=checks, warm_evaluations=800, extra_bakes=0)
out = Path(__file__).resolve().parents[1] / 'tests/plan6-domains-blender.checks.json'
out.write_text(json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_DOMAINS_BLENDER_PASS', len(checks), flush=True)
