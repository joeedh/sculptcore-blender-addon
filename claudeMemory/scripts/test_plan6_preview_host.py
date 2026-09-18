# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepared preview replacement/cancel through installed addon lifecycle helpers."""
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import bpy
import numpy as np
import sculptcore
from sculptcore_addon import engine, stroke
from sculptcore.brush_properties import FLOAT32, INT32, set_command_scalar

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
checks, references, calls = [], {}, []
for suffix in ('dabResolved', 'dabResolvedImage', 'dabProgramResolved', 'dabProgramResolvedImage'):
    name = 'MeshStroke_' + suffix
    native = getattr(lib, name)

    def checked(*args, _native=native, _name=name):
        status = _native(*args)
        assert status >= 0, (_name, status)
        calls.append((_name, status))
        return status

    setattr(lib, name, checked)


def positions(session):
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().reshape(-1, 4)[:, 1:].copy()


for tool_name, multires, nonaccum, program_mode, replacements in product(
        ('DRAW', 'GRAB', 'KELVINLET', 'ENHANCE'), (False, True), (False, True), (False, True), (False, True)):
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=12, size=4)
    obj = bpy.context.object
    for vertex in obj.data.vertices:
        x, y, _ = vertex.co
        vertex.co.z = .08 * math.cos(3 * x) * math.sin(4 * y)
    if multires:
        obj.modifiers.new('Multires', 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier='Multires')
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength = 1, .3
    brush.unboundedExtent = 0
    brush.automask_cavity = True
    brush.cavity_factor = .2
    brush.writeProps()
    kernel = int(tools[tool_name])
    # Modal settings setup creates this executor before the lazy slot exists.
    executor = stroke._ensure_executor(session)
    # Preview routing deliberately materializes multires; grids have no preview log.
    stroke.stroke_begin(session, accumulate=not nonaccum, anchored_grab=tool_name in ('GRAB', 'KELVINLET'))
    assert not session.last_stroke_grids and session.mesh_ptr
    executor = stroke._ensure_executor(session)
    assert executor.tree.ptr == session.tree_ptr
    original = positions(session)
    start_calls = len(calls)
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(kernel)
        program.addCommand(int(tools['BSMOOTH']))
        set_command_scalar(manager, program, 1, 'radius', FLOAT32, 3)
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .13)
        selected = program if program_mode else None
        for radius in (2.3, .6, 1.2) if replacements else (1.2,):
            brush.radius, brush.strength = radius, .3
            brush.writeProps()
            assert stroke.preflight_preview(session, kernel, selected)
            if executor.previewActive():
                executor.rollbackPreviewDab()
                stroke._refresh_queries(session)
                assert np.array_equal(positions(session), original)
            for image in (0, 1):
                center = (-.3 if image else .3, 0, 0)
                with stroke._float3(manager, *center) as vector:
                    if image:
                        executor.extendPreviewDab(vector, .01)
                    else:
                        executor.beginPreviewDab(vector, .01)
                for axis in range(3):
                    brush.grabFrom.vec[axis] = center[axis]
                    brush.grabTo.vec[axis] = (-.2 if image else .2, .1, .3)[axis]
                assert executor.supportsResolvedProgram(program) if program_mode else executor.supportsResolved(kernel)
                if program_mode:
                    stroke.apply_dab_program(session, program, center, (0, 0, 1), radius,
                                             kernel=kernel, grab_add=bool(image))
                else:
                    stroke.apply_dab(session, kernel, center, (0, 0, 1), radius, grab_add=bool(image))
            valid = positions(session)
            assert not stroke.preflight_preview(session, kernel, selected, (float('nan'), 0, 0), (0, 0, 1))
            assert executor.previewActive() and np.array_equal(positions(session), valid)
            set_command_scalar(manager, program, 1, 'radius', INT32, 3)
            assert not stroke.preflight_preview(session, kernel, program)
            assert executor.previewActive() and np.array_equal(positions(session), valid)
            set_command_scalar(manager, program, 1, 'radius', FLOAT32, 3)
        final = positions(session)
        assert np.isfinite(final).all() and np.max(abs(final - original)) > 1e-6
        key = tool_name, multires, nonaccum, program_mode
        if replacements:
            assert np.allclose(final, references[key], rtol=0, atol=3e-6), key
        else:
            references[key] = final.copy()
        executor.commitPreviewDab()
    stroke.stroke_end(session)
    stroke.stroke_begin(session, accumulate=not nonaccum, anchored_grab=False)
    with stroke._float3(manager, 0, 0, 0) as vector:
        executor.beginPreviewDab(vector, .01)
    stroke.apply_dab(session, int(tools['DRAW']), (0, 0, 0), (0, 0, 1), 1.2)
    executor.rollbackPreviewDab()
    stroke._refresh_queries(session)
    assert np.array_equal(positions(session), final)
    stroke.stroke_end(session)
    checks.append(dict(tool=tool_name, multires=multires, nonaccum=nonaccum, program=program_mode,
                       replacements=replacements, prepared_calls=calls[start_calls:]))

bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-preview-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_PREVIEW_HOST_PASS', json.dumps(result), flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
