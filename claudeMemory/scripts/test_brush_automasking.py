# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""UI-authored cavity/view-normal/backface settings affect mesh/grid geometry."""
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
from sculptcore_addon.brush_properties.adapters import CAVITY, STRENGTH, SIZE
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke
from sculptcore_addon.brush_properties.stroke_runtime import StrokeRuntime
from sculptcore_addon.stroke_input import InputSample
ui_mode = '--' in sys.argv and sys.argv[sys.argv.index('--') + 1:] == ['ui']
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

def run_cases():
    cases = list(product((False, True), (False, True), range(10)))
    for case in cases:
        grid, program_mode, view_case = case
        brush_type = 'DRAW'
        enabled, cull, ray, changes = (
            (False, True, (0, 0, 1), True),
            (True, False, (0, 0, 1), True),
            (True, True, (0, 0, 1), False),
            (True, True, (0, 0, -1), True),
            (True, False, (1, 0, 0), False),
        )[view_case] if view_case < 5 else (False, False, (0, 0, -1), view_case not in (7, 9))
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
        bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
            relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
        native_brush = bpy.context.tool_settings.sculpt.brush
        bpy.context.scene.sculptcore_generic_properties = True
        native_brush.sculpt_brush_type = brush_type
        native_brush.strength = .125
        native_brush.use_space_attenuation = False
        native_brush.curve_distance_falloff_preset = 'SMOOTH'
        native_brush.plane_offset = .1
        local, parent = authoring.store(native_brush), authoring.store(bpy.context.scene)
        local.write_mode(STRENGTH, 'ALWAYS')
        parent.write_value(authoring.registry.get(STRENGTH), .4)
        local.write_stack(authoring.registry.get(STRENGTH), (
            DeviceLayer('PRESSURE', operation='MULTIPLY', curve=ResponseCurve('LINEAR')),))
        local.write_stack(authoring.registry.get(SIZE), (
            DeviceLayer('SPEED', operation='ADD', curve=ResponseCurve('CONSTANT', (.3,))),))
        def write_ui(identifier, value):
            definition = authoring.registry.get(identifier)
            if not ui_mode:
                from sculptcore_addon.brush_properties.resolver import resolve_value
                resolve_value(authoring.registry, identifier, local, parent).value_owner.write_value(definition, value)
                return
            field = {'FLOAT32': 'float_value', 'INT32': 'int_value', 'BOOL': 'bool_value'}[definition.scalar_type]
            assert bpy.ops.sculptcore.property_value('EXEC_DEFAULT', True, identifier=identifier,
                                                     **{field: value}) == {'FINISHED'}

        for suffix, value in (('automask_view_normal', enabled), ('cull_backfaces', cull),
                              ('view_normal_limit', 1.2), ('view_normal_falloff', .3)):
            identifier = 'sculptcore.brush.' + suffix
            local.write_mode(identifier, 'ALWAYS')
            write_ui(identifier, value)
        # Alternate local and Scene cavity ownership. Custom constants independently
        # prove curve application before inversion, including complete suppression.
        local.write_mode(CAVITY + '.cavity_factor', 'ALWAYS' if program_mode else 'NEVER')
        cavity_owner = bpy.context.scene if program_mode else native_brush
        for suffix, value in (('use_automasking_cavity', view_case >= 5 and view_case != 9),
                              ('use_automasking_cavity_inverted', view_case in (6, 9)),
                              ('cavity_factor', .75), ('cavity_blur_steps', 3),
                              ('use_automasking_custom_cavity_curve', view_case >= 7)):
            write_ui(CAVITY + '.' + suffix, value)
        if view_case >= 7:
            settings = (cavity_owner if not program_mode else cavity_owner.tool_settings.sculpt).mesh_automasking_settings
            settings.cavity_curve.initialize()
            for point in settings.cavity_curve.curves[0].points:
                point.location[1] = 0 if view_case == 7 else 1
            settings.cavity_curve.update()
        settings = capture_stroke(native_brush, bpy.context.scene)
        kernel = int(tools[settings.kernel_name])
        runtime = StrokeRuntime(settings, session, kernel)
        assert bool(brush.automask_cavity) == (view_case >= 5)
        assert bool(brush.cavity_inverted) == (view_case in (6, 9))
        assert bool(brush.cavity_use_curve) == (view_case >= 7)
        assert brush.cavity_blur_steps == 3 and brush.cavity_factor == .75
        assert bool(brush.automask_view_normal) == enabled and bool(brush.cull_backfaces) == cull
        assert abs(brush.view_normal_limit - 1.2) < 1e-6 and abs(brush.view_normal_falloff - .3) < 1e-6
        session.generic_runtime = runtime
        runtime.view_direction = ray
        runtime.view_image()
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
        runtime.close()
        session.generic_runtime = None
        assert native_brush.strength == .125
        stroke.stroke_end(session)
        final = positions()
        assert (not np.array_equal(final, original)) == changes, case
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
        print('PLAN6_GENERIC_AUTOMASK_HOST_CASE_PASS', case, flush=True)
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    dll = Path(lib._name).resolve()
    result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
    (Path(__file__).resolve().parents[1] / 'tests/plan6-generic-automask-host.json').write_text(json.dumps(result, indent=2))
    print('PLAN6_GENERIC_AUTOMASK_HOST_PASS', flush=True)

if ui_mode:
    def run_ui():
        import traceback
        try:
            bpy.context.preferences.edit.use_global_undo = True
            area = next(item for item in bpy.context.screen.areas if item.type == 'VIEW_3D')
            region = next(item for item in area.regions if item.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.ed.undo_push(message='Automasking UI baseline')
                run_cases()
        except Exception:
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
    bpy.app.timers.register(run_ui, first_interval=1)
else:
    run_cases()
