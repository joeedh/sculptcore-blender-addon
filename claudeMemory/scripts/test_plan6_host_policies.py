# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed checked falloff and grid-layer routing with exact stroke undo."""
import hashlib
from itertools import product
import json
from pathlib import Path
import bpy
import numpy as np
import sculptcore
from sculptcore.brush_properties import FLOAT32, set_command_scalar, replace_fixed_curve
from sculptcore_addon import convert, engine, layers, stroke

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

cases = list(product((False, True), (False, True), range(4), (0, 2, 3)))
cases += [(True, program, 0, 0, True) for program in (False, True)]
for case in cases:
    grid, program_mode, shape, kind, *layered = case
    layered = bool(layered)
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
    brush.radius, brush.strength = .6, .2
    brush.falloff_shape, brush.falloff_kind = shape, kind
    replace_fixed_curve(manager, brush, 'falloff', tuple(.1 + .9 * i / 255 for i in range(256)))
    brush.writeProps()
    kernel = int(tools['LAYERDRAW' if layered else 'DRAW'])
    if layered:
        layers.ensure_stroke_target(bpy.context, obj, session)
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
        for _ in range(2):
            if program_mode:
                assert stroke.apply_dab_program(session, program, (0, 0, 0), (0, 0, 1), .6, kernel=kernel) >= 0
            else:
                assert stroke.apply_dab(session, kernel, (0, 0, 0), (0, 0, 1), .6) >= 0
    stroke.stroke_end(session)
    final = positions()
    assert not np.array_equal(final, original), case
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
    print('PLAN6_HOST_POLICIES_CASE_PASS', case, flush=True)
bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(lib._name).resolve()
result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-host-policies-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_HOST_POLICIES_PASS', flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(quit_after_startup, first_interval=1)
