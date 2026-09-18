# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real owner and immutable-curve checks for the consumer synchronization boundary."""
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH, CAVITY
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve
from sculptcore_addon.brush_properties.storage import ROOT

root = Path(__file__).resolve().parents[2]
name = 'sculptcore_addon.brush_properties.stroke_settings'
spec = importlib.util.spec_from_file_location(name, root / 'sculptcore_addon/brush_properties/stroke_settings.py')
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
capture = module.capture_stroke
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


brush = bpy.data.brushes.new('Generic Stroke Settings', mode='SCULPT')
brush.sculpt_brush_type = 'DRAW'
scene = bpy.context.scene
scene.tool_settings.sculpt.unified_paint_settings.use_unified_size = False
scene.tool_settings.sculpt.unified_paint_settings.use_unified_strength = False
before = (list(brush.keys()), list(scene.keys()))
first = capture(brush, scene)
check('capture does not allocate persistent data', ROOT not in brush and ROOT not in scene
      and before == (list(brush.keys()), list(scene.keys())))
local, parent = authoring.store(brush), authoring.store(scene)
registry = authoring.registry
brush.strength = .25
scene.tool_settings.sculpt.unified_paint_settings.strength = .75
local.write_stack(registry.get(STRENGTH), (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
parent.write_stack(registry.get(STRENGTH), (DeviceLayer('SPEED', curve=ResponseCurve('CONSTANT', (.5,))),))
for value_parent in (False, True):
    for stack_parent in (False, True):
        local.write_mode(STRENGTH, 'ALWAYS' if value_parent else 'NEVER')
        local.write_stack_inheritance(STRENGTH, stack_parent)
        settings = capture(brush, scene)
        expected = (.75 if value_parent else .25) * (.5 if stack_parent else .25)
        check('separate owners {} {}'.format(value_parent, stack_parent),
              abs(settings.value(STRENGTH, (.5, None, None, .2)) - expected) < 1e-5)
check('dormant native strength survives resolution', brush.strength == .25)
local.write_mode(SIZE, 'NEVER')
brush.use_locked_size = 'SCENE'
brush.unprojected_size = .8
settings = capture(brush, scene)
check('scene diameter avoids projection', abs(settings.base_radius(lambda _: 999, 2) - .2) < 1e-7)
brush.use_locked_size = 'VIEW'
brush.size = 120
settings = capture(brush, scene)
check('view diameter is halved before projection', settings.base_radius(lambda pixels: pixels / 100) == .6)
spacing = registry.get('sculptcore.brush.spacing')
brush.spacing = 11
local.write_stack(spacing, (DeviceLayer('TILT_X', operation='MULTIPLY',
                                      curve=ResponseCurve('CONSTANT', (.5,))),))
settings = capture(brush, scene)
channels = (None, .2, None, None)
check('integer rounding before spacing unit conversion', settings.value(spacing.identifier, channels) == 6
      and abs(settings.engine_value(spacing.identifier, channels) - .06) < 1e-7)
frozen = settings.properties, settings.falloff
brush.spacing = 99
brush.strength = .1
brush.size = 200
check('active snapshot remains independent of RNA edits', settings.properties == frozen[0]
      and settings.falloff == frozen[1] and settings.value(spacing.identifier, channels) == 6
      and settings.size.pixels == 120)
brush.sculpt_brush_type = 'SNAKE_HOOK'
brush.crease_pinch_factor = .25
snake = registry.get('sculptcore.brush.snake_pinch')
local.write_stack(snake, (DeviceLayer('PRESSURE', operation='ADD',
                                    curve=ResponseCurve('CONSTANT', (.5,))),))
settings = capture(brush, scene)
check('snake remap follows dynamics', settings.engine_value(snake.identifier, (.1, None, None, None)) == -.5)
brush.sculpt_brush_type = 'DRAW'
hardness = registry.get('sculptcore.brush.hardness')
parent.write_value(hardness, .8)
local.write_mode(hardness.identifier, 'ALWAYS')
settings = capture(brush, scene)
check('effective scene hardness shapes falloff', settings.falloff.evaluate(.5) == 1)
from sculptcore_addon import mapping
local.write_stack(spacing, ())
local.write_mode(spacing.identifier, 'NEVER')
brush.use_space_attenuation = True
for preset in (*mapping._PRESET_FALLOFF, 'CUSTOM'):
    brush.curve_distance_falloff_preset = preset
    for amount in (1, 6, 10, 33, 99, 100):
        brush.spacing = amount
        captured = capture(brush, scene)
        assert captured.overlap() == mapping.overlap_attenuation(brush), (preset, amount)
check('exact legacy overlap for all presets independent of hardness', True)
cavity = scene.tool_settings.sculpt.mesh_automasking_settings
cavity.use_automasking_cavity = True
cavity.use_automasking_custom_cavity_curve = True
local.write_mode(CAVITY + '.cavity_factor', 'ALWAYS')
settings = capture(brush, scene)
check('effective cavity curve sampled', settings.cavity is not None)
old = settings.cavity
cavity.cavity_curve.curves[0].points[-1].location = (1, .25)
cavity.cavity_curve.update()
new = capture(brush, scene)
check('curve revision changes next snapshot only', settings.cavity == old and new.cavity != old)
(root / 'claudeMemory/tests/plan6-stroke-settings.json').write_text(
    json.dumps(dict(passed=True, checks=checks), indent=2) + '\n', encoding='utf-8')
print('PLAN6_STROKE_SETTINGS_PASS', len(checks))
if not bpy.app.background:
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=.3)
