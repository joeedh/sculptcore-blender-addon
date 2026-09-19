# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generic owner snapshots and native semantic values reach mesh/grid geometry."""
import hashlib
from itertools import product
import json
from pathlib import Path
import bpy
import numpy as np
import sculptcore
from sculptcore.brush_properties import FLOAT32, set_command_scalar, replace_fixed_curve
from sculptcore_addon import convert, engine, layers, stroke

import importlib.util
import sys
root = Path(__file__).resolve().parents[2]
for name in ('stroke_settings', 'native_evaluation', 'stroke_runtime'):
    full_name = 'sculptcore_addon.brush_properties.' + name
    spec = importlib.util.spec_from_file_location(full_name, root / 'sculptcore_addon/brush_properties' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import STRENGTH, SIZE
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke
from sculptcore_addon.brush_properties.stroke_runtime import StrokeRuntime
from sculptcore_addon.stroke_input import InputSample
manager, lib = engine.manager(), engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
calls, checks = [], []
for name in ('MeshStroke_dabResolved', 'MeshStroke_dabProgramResolved',
             'GridStroke_dabResolved', 'GridStroke_dabProgramResolved'):
    native = getattr(lib, name)
    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        calls.append((_name, result))
        assert result >= 0, (_name, result)
        return result
    setattr(lib, name, checked)

cases = list(product((False, True), (False, True), ('DRAW', 'INFLATE', 'CLAY', 'NUDGE')))
for case in cases:
    grid, program_mode, brush_type = case
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=12, size=4)
    obj = bpy.context.object
    if grid:
        obj.modifiers.new('Multires', 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier='Multires')
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    native_brush = bpy.data.brushes.new('Generic ' + brush_type, mode='SCULPT')
    native_brush.sculpt_brush_type = brush_type
    native_brush.strength = .125
    native_brush.use_space_attenuation = False
    native_brush.curve_distance_falloff_preset = 'CONSTANT' if brush_type == 'DRAW' else 'SMOOTH'
    native_brush.plane_offset = .1
    local, parent = authoring.store(native_brush), authoring.store(bpy.context.scene)
    local.write_mode(STRENGTH, 'ALWAYS')
    parent.write_value(authoring.registry.get(STRENGTH), .4)
    local.write_stack(authoring.registry.get(STRENGTH), (
        DeviceLayer('PRESSURE', operation='MULTIPLY', curve=ResponseCurve('LINEAR')),))
    local.write_stack(authoring.registry.get(SIZE), (
        DeviceLayer('SPEED', operation='ADD', curve=ResponseCurve('CONSTANT', (.3,))),))
    settings = capture_stroke(native_brush, bpy.context.scene)
    kernel = int(tools[settings.kernel_name])
    runtime = StrokeRuntime(settings, session, kernel)
    if grid:
        convert.ensure_multires_slot(session)
    stroke.stroke_begin(session, accumulate=True, anchored_grab=False,
                        grids_kernel=kernel if grid else None)
    assert session.last_stroke_grids == grid
    executor = None if grid else stroke._ensure_executor(session)
    assert (lib.GridStroke_supportsResolved(session.grid_ptr, kernel, None) if grid
            else executor.supportsResolved(kernel)), case
    def positions():
        if grid:
            n = lib.Multires_levelSampleCount(session.multires_ptr, session.multires_active_level)
            result = np.empty(n * 3, dtype=np.float32)
            assert lib.Multires_levelPositionsOut(session.multires_ptr, session.multires_active_level, result)
            return result
        with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
            session.mesh().dumpVertCo(data)
            return data.numpy().copy()
    original = positions()
    stride = 3 if grid else 4
    expected = original.reshape(-1, stride)[:, :3].copy()
    first_call = len(calls)
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(kernel)
        program.addCommand(int(tools['DRAW']))
        set_command_scalar(manager, program, 1, 'radius', FLOAT32, 1.3)
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .1)
        for dab_index, pressure in enumerate((.25, .75)):
            sample = InputSample(pressure=pressure, speed=.5)
            row = runtime.evaluate([sample], [.6])[0]
            payload = runtime.prepare(row, sample)
            runtime.publish(payload)
            radius = payload[0][1]
            assert abs(radius - .9) < 1e-6
            assert abs(brush.strength - .4 * pressure) < 1e-6
            sample.upload(brush)
            if program_mode:
                assert stroke.apply_dab_program(session, program, (.2 * dab_index, 0, 0), (0, 0, 1), radius, kernel=kernel) >= 0
            else:
                assert stroke.apply_dab(session, kernel, (.2 * dab_index, 0, 0), (0, 0, 1), radius) >= 0
            if brush_type == 'DRAW':
                stages = [(radius, .4 * pressure)] + ([(1.3, .1)] if program_mode else [])
                for stage_radius, stage_strength in stages:
                    distance = np.linalg.norm(expected - (.2 * dab_index, 0, 0), axis=1)
                    expected[distance <= stage_radius, 2] += stage_strength * stage_radius * .5
    runtime.close()
    assert native_brush.strength == .125
    stroke.stroke_end(session)
    final = positions()
    assert not np.array_equal(final, original), case
    if brush_type == 'DRAW':
        assert np.allclose(final.reshape(-1, stride)[:, :3], expected, atol=2e-6, rtol=0), (case, 'hard boundary')
    if grid:
        assert lib.GridStroke_undo(session.grid_ptr)
    else:
        session.meshlog.undo(session.mesh(), session.tree())
    assert np.array_equal(positions(), original), (case, 'undo')
    if grid:
        assert lib.GridStroke_redo(session.grid_ptr)
    else:
        session.meshlog.redo(session.mesh(), session.tree())
    assert np.array_equal(positions(), final), (case, 'redo')
    assert len(calls) - first_call == 2
    checks.append(dict(case=case, calls=calls[first_call:]))
    print('PLAN6_RUNTIME_HOST_CASE_PASS', case, flush=True)
bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(lib._name).resolve()
result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-runtime-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_RUNTIME_HOST_PASS', flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(quit_after_startup, first_interval=1)
