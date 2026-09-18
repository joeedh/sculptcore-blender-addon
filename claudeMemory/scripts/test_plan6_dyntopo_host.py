# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed prepared dyntopo through the addon, with rejection and exact undo."""
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import bpy
import numpy as np
import sculptcore
from sculptcore.brush_properties import FLOAT32, INT32, set_command_scalar
from sculptcore_addon import convert, engine, stroke

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
native = lib.MeshStroke_dabProgramResolvedDyntopo
calls, checks = [], []


def checked(*args):
    result = native(*args)
    calls.append(result)
    return result


lib.MeshStroke_dabProgramResolvedDyntopo = checked


def state(session):
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().copy(), convert._mesh_counts(session.mesh_ptr)[:3]


def equal(a, b):
    return np.array_equal(a[0], b[0]) and a[1] == b[1]


for nonaccum, cavity, smooth in product((False, True), repeat=3):
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    vertices = [(x / 6 - 1, y / 6 - 1, .04 * math.sin(3 * (x / 6 - 1) + y / 6 - 1))
                for y in range(13) for x in range(13)]
    faces = []
    for y in range(12):
        for x in range(12):
            a = y * 13 + x
            faces.extend(((a, a + 1, a + 14), (a, a + 14, a + 13)))
    mesh = bpy.data.meshes.new('Prepared topology')
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new('Prepared topology', mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength = .45, .15
    brush.automask_cavity, brush.cavity_factor, brush.cavity_blur_steps = cavity, .2, 1
    brush.writeProps()
    stroke.stroke_begin(session, has_dyntopo=True, accumulate=not nonaccum, anchored_grab=False)
    executor = stroke._ensure_executor(session)
    original = state(session)
    start = len(calls)
    params = stroke.build_dyntopo_params(session, .11, .02)
    params.max_rounds, params.max_splits, params.mode = 6, 70, 0
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(int(tools['DRAW']))
        program.addCommand(int(tools['BSMOOTH' if smooth else 'DRAW']))
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .08)
        set_command_scalar(manager, program, 1, 'radius', INT32, 1)
        assert stroke.apply_dyntopo_dab(session, program, (0, 0, 0), (0, 0, 1), .4, params, 17) < 0
        assert equal(state(session), original)
        set_command_scalar(manager, program, 1, 'radius', FLOAT32, .8)
        params.l_max = float('nan')
        assert stroke.apply_dyntopo_dab(session, program, (0, 0, 0), (0, 0, 1), .4, params, 17) < 0
        assert equal(state(session), original)
        params.l_max = .11
        assert stroke.apply_dyntopo_dab(session, program, (-.15, 0, 0), (0, 0, 1), .4, params, 17) > 0
        split = state(session)
        assert split[1][0] > original[1][0]
        assert stroke.apply_dyntopo_dab(session, program, (.15, 0, 0), (0, 0, 1), .4, None, 18) == 0
        skipped = state(session)
        assert skipped[1] == split[1] and not equal(skipped, split)
        params.l_max, params.l_min, params.mode, params.max_collapses = .4, .17, 1, 30
        assert stroke.apply_dyntopo_dab(session, program, (.15, 0, 0), (0, 0, 1), .4, params, 19) > 0
        assert state(session)[1][0] < split[1][0]
    stroke.stroke_end(session)
    final = state(session)
    session.meshlog.undo(session.mesh(), session.tree())
    assert equal(state(session), original), (nonaccum, cavity, smooth, 'undo')
    session.meshlog.redo(session.mesh(), session.tree())
    assert equal(state(session), final), (nonaccum, cavity, smooth, 'redo')
    assert len(calls) - start == 5
    checks.append(dict(nonaccum=nonaccum, cavity=cavity, smooth=smooth, calls=calls[start:],
                       vertices=[original[1][0], split[1][0], final[1][0]]))

legacy = []
references = {}
for nonaccum, resolved in product((False, True), repeat=2):
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    mesh = bpy.data.meshes.new('Legacy topology reference')
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new('Legacy topology reference', mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength = .4, .15
    brush.writeProps()
    stroke.stroke_begin(session, has_dyntopo=True, accumulate=not nonaccum, anchored_grab=False)
    executor = stroke._ensure_executor(session)
    params = stroke.build_dyntopo_params(session, .11, .02)
    params.max_rounds, params.max_splits, params.mode = 6, 70, 0
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(int(tools['DRAW']))
        for index, center in enumerate(((-.15, 0, 0), (.15, 0, 0), (.15, 0, 0))):
            if index == 2:
                params.l_max, params.l_min, params.mode, params.max_collapses = .4, .17, 1, 30
            selected = None if index == 1 else params
            if resolved:
                count = stroke.apply_dyntopo_dab(session, program, center, (0, 0, 1), .4, selected, 17 + index)
            else:
                position = stroke._float3(manager, *center)
                normal = stroke._float3(manager, 0, 0, 1)
                try:
                    executor.setGrabAccumAdd(False)
                    count = executor.applyDab(program, position, normal, .4, selected, 17 + index)
                finally:
                    position.dispose()
                    normal.dispose()
                stroke._refresh_queries(session)
            assert count >= 0
    stroke.stroke_end(session)
    result_state = state(session)
    if resolved:
        assert equal(result_state, references[nonaccum]), (nonaccum, 'legacy geometry/topology')
    else:
        references[nonaccum] = result_state
    legacy.append(dict(nonaccum=nonaccum, resolved=resolved, vertices=result_state[1][0]))

bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, checks=checks, legacy=legacy, dll=str(dll),
              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(Path(__file__).resolve().parents[1] / 'tests/plan6-dyntopo-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_DYNTOPO_HOST_PASS', json.dumps(result), flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
