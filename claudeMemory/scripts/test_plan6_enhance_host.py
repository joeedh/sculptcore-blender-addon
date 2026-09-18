# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepared ENHANCE through addon routing, including materialized multires meshes."""
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import bpy
import numpy as np
import sculptcore
from sculptcore_addon import engine, stroke
from sculptcore.brush_properties import BrushPropertyError, FLOAT32, INT32, UniformProperties, set_command_scalar

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
enhance = int(tools['ENHANCE'])
checks = []
references = {}
prepared_calls = []

for name in ('MeshStroke_dabResolved', 'MeshStroke_dabProgramResolved'):
    native = getattr(lib, name)

    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        prepared_calls.append((_name, result))
        assert result >= 0, (_name, result)
        return result

    setattr(lib, name, checked)


def positions(session):
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().reshape(-1, 4)[:, 1:].copy()


for multires, nonaccum, program_mode, delivery in product((False, True), (False, True), (False, True), range(3)):
    raw_reference = delivery == 2
    if raw_reference and program_mode:
        continue
    batched = delivery != 0
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=12, size=4)
    obj = bpy.context.object
    for vertex in obj.data.vertices:
        x, y, _ = vertex.co
        vertex.co.z = .08 * math.cos(4 * x) * math.sin(3 * y)
    if multires:
        obj.modifiers.new('Multires', 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier='Multires')
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength = 4, .35
    brush.enhance_rings, brush.enhance_inner = 4, 1
    brush.writeProps()
    assert not stroke.grids_capable(session, enhance)
    stroke.stroke_begin(session, accumulate=not nonaccum, grids_kernel=enhance)
    assert not session.last_stroke_grids
    if multires:
        assert session.draw_provider_kind == 'SLOT'
        assert session.mesh_ptr == lib.Multires_activeMesh(session.multires_ptr)
    executor = stroke._ensure_executor(session)
    assert executor.supportsResolved(enhance)
    uniforms = UniformProperties(manager, executor, enhance)
    rings = next(item for item in uniforms.uniforms if item.name == 'enhance_rings')
    assert rings.scalar_type == INT32 and not rings.dynamic
    assert uniforms.read(rings.index) == 4
    uniforms.write(rings.index, -7)
    assert brush.enhance_rings == -7
    brush.enhance_rings = 4
    assert uniforms.read(rings.index) == 4
    try:
        uniforms.configure(rings.index, 0)
    except BrushPropertyError:
        pass
    else:
        raise AssertionError('Static ENHANCE setting accepted a device stack')
    original = positions(session)
    start_calls = len(prepared_calls)
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(enhance)
        set_command_scalar(manager, program, 0, 'enhance_rings', INT32, 2)
        set_command_scalar(manager, program, 0, 'enhance_inner', INT32, 0)
        program.addCommand(enhance)
        set_command_scalar(manager, program, 1, 'enhance_rings', INT32, 5)
        set_command_scalar(manager, program, 1, 'enhance_inner', INT32, 2)
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .15)
        if batched:
            rows = np.array(((0, 0, 0, 0, 0, 1, 4), (.3, .1, 0, 0, 0, 1, 4)), dtype=np.float32)
            samples = np.array(((1, 0, 0, 0, 0, 0),) * 2, dtype=np.float32)
            empty = np.empty(0, dtype=np.float32)
            function = lib.MeshStroke_dabBatchProgramInputs if program_mode else lib.MeshStroke_dabBatchInputs
            target = program.ptr if program_mode else enhance
            status = function(executor.ptr, session.tree_ptr, session.mesh_ptr, brush.ptr, target,
                              2, rows.ravel(), .35, samples.ravel(), 1, empty, 0, 0 if raw_reference else 1)
            assert status >= 0
            if not raw_reference:
                prepared_calls.append(('required prepared batch', status))
        else:
            for center in ((0, 0, 0), (.3, .1, 0)):
                if program_mode:
                    assert stroke.apply_dab_program(session, program, center, (0, 0, 1), 4,
                                                    kernel=enhance) >= 0
                else:
                    assert stroke.apply_dab(session, enhance, center, (0, 0, 1), 4) >= 0
            assert len(prepared_calls) - start_calls == 2
        assert brush.enhance_rings == 4 and brush.enhance_inner == 1
        moved = positions(session)
        assert np.isfinite(moved).all() and np.max(abs(moved - original)) > 1e-5
        key = multires, nonaccum, program_mode
        if batched:
            assert np.array_equal(moved, references[key]), key
        else:
            references[key] = moved
        if program_mode:
            for slot in (0, 1):
                set_command_scalar(manager, program, slot, 'enhance_rings', INT32, -7)
                set_command_scalar(manager, program, slot, 'enhance_inner', INT32, 2147483647)
            assert stroke.apply_dab_program(session, program, (0, 0, 0), (0, 0, 1), 4,
                                            kernel=enhance) >= 0
            assert np.array_equal(moved, positions(session))
            assert brush.enhance_rings == 4 and brush.enhance_inner == 1
            set_command_scalar(manager, program, 1, 'enhance_inner', FLOAT32, 1)
            empty = np.empty(0, dtype=np.float32)
            assert lib.MeshStroke_dabBatchProgramInputs(
                executor.ptr, session.tree_ptr, session.mesh_ptr, brush.ptr, program.ptr,
                0, empty, .35, empty, 1, empty, 0, 1) == -1
            assert np.array_equal(moved, positions(session))
    stroke.stroke_end(session)
    checks.append(dict(multires=multires, nonaccum=nonaccum, program=program_mode, batched=batched,
                       raw_reference=raw_reference,
                       max_motion=float(np.max(abs(moved - original))), vertices=len(moved),
                       prepared_calls=prepared_calls[start_calls:]))

bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-enhance-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_ENHANCE_HOST_PASS', json.dumps(result), flush=True)

if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
