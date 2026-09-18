# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise prepared attribute brushes through installed addon routing."""
import hashlib
from itertools import product
import json
from pathlib import Path

import bpy
import numpy as np
import sculptcore
from sculptcore.brush_properties import FLOAT32, set_command_scalar
from sculptcore_addon import convert, engine, stroke

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
calls, checks = [], []
for name in ('MeshStroke_dabResolved', 'MeshStroke_dabProgramResolved'):
    native = getattr(lib, name)

    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        calls.append((_name, result))
        assert result >= 0, (_name, result)
        return result

    setattr(lib, name, checked)


def state(session):
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        coordinates = data.numpy().copy()
    colors = np.zeros(convert.mesh_vert_num(session.mesh_ptr) * 4, dtype=np.float32)
    groups = np.zeros(convert.mesh_face_num(session.mesh_ptr), dtype=np.int32)
    assert lib.Mesh_readVertFloat4Attr(session.mesh_ptr, convert._SC_COLOR, colors)
    assert lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)
    return coordinates, colors, groups


def equal(left, right):
    return all(np.array_equal(a, b) for a, b in zip(left, right))


for tool, multires, program_mode, preview in product(
        ('COLOR', 'COLORSMOOTH', 'POLYGROUP', 'FEATURE_ALIGN'), (False, True), (False, True), (False, True)):
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=12, size=4)
    obj = bpy.context.object
    for vertex in obj.data.vertices:
        vertex.co.z = .05 * np.sin(3 * vertex.co.x + vertex.co.y)
    color = obj.data.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    values = np.empty(len(obj.data.vertices) * 4, dtype=np.float32)
    for i in range(len(obj.data.vertices)):
        values[i * 4:i * 4 + 4] = (.1 + .04 * (i % 7), .2, .3, 1)
    color.data.foreach_set('color', values)
    obj.data.color_attributes.active_color_index = 0
    group = obj.data.attributes.new('.sculpt_face_set', 'INT', 'FACE')
    group.data.foreach_set('value', np.ones(len(obj.data.polygons), dtype=np.int32))
    if multires:
        obj.modifiers.new('Multires', 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier='Multires')
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength, brush.activeGroup = .8, .3, 5
    for index, value in enumerate((.8, .1, .5, 1)):
        brush.brushColor.vec[index] = value
    brush.writeProps()
    kernel = int(tools[tool])
    # Materialized attribute execution; the dedicated cage route has its own gate.
    stroke.stroke_begin(session, accumulate=True, anchored_grab=False)
    executor = stroke._ensure_executor(session)
    assert executor.supportsResolved(kernel), tool
    original = state(session)
    first_call = len(calls)
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(kernel)
        program.addCommand(kernel)
        set_command_scalar(manager, program, 1, 'radius', FLOAT32, 1.3)
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .1)

        def apply():
            if program_mode:
                return stroke.apply_dab_program(session, program, (0, 0, 0), (0, 0, 1), .8, kernel=kernel)
            return stroke.apply_dab(session, kernel, (0, 0, 0), (0, 0, 1), .8)

        center = stroke._float3(manager, 0, 0, 0)
        try:
            if preview:
                executor.beginPreviewDab(center, .01)
                assert apply() >= 0
                executor.rollbackPreviewDab()
                stroke._refresh_queries(session)
                assert equal(state(session), original), (tool, multires, 'preview rollback')
                executor.beginPreviewDab(center, .01)
            assert apply() >= 0
            assert apply() >= 0
            final = state(session)
            assert not equal(final, original), (tool, multires, 'unchanged')
            if preview:
                executor.commitPreviewDab()
        finally:
            center.dispose()
    stroke.stroke_end(session)
    session.meshlog.undo(session.mesh(), session.tree())
    assert equal(state(session), original), (tool, multires, program_mode, 'undo')
    session.meshlog.redo(session.mesh(), session.tree())
    assert equal(state(session), final), (tool, multires, program_mode, 'redo')
    assert len(calls) - first_call == (3 if preview else 2)
    checks.append(dict(tool=tool, multires=multires, program=program_mode, preview=preview,
                       calls=calls[first_call:]))

bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-attributes-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_ATTRIBUTES_HOST_PASS', json.dumps(result), flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
