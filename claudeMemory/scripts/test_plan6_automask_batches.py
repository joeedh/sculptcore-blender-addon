# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed DLL automasking with independent constant-LUT strength oracles."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import numpy as np
import sculptcore
from sculptcore_addon import engine
from sculptcore_addon.mapping import PROP_RADIUS, PROP_STRENGTH
from sculptcore.brush_properties import (
    BOOL, INT32, FLOAT32, BrushPropertyError, set_command_scalar,
    replace_command_cavity_curve, inherit_command_cavity_curve,
)

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
empty = np.empty(0, dtype=np.float32)
coords = np.array([(x / 4, y / 4, .02 * ((x + y) % 3))
                   for y in range(-8, 9) for x in range(-8, 9)], dtype=np.float32)
corners = np.array([(y * 17 + x, y * 17 + x + 1, (y + 1) * 17 + x + 1, (y + 1) * 17 + x)
                    for y in range(16) for x in range(16)], dtype=np.int32).ravel()
offsets = np.arange(0, len(corners) + 1, 4, dtype=np.int32)
dabs = np.array([(-.3 + .2 * i, 0, 0, 0, 0, 1, 2) for i in range(3)], dtype=np.float32)
samples = np.tile(np.array((1, 0, 0, 0, 0, 0), dtype=np.float32), (3, 1))
checks = []


def run(grid, order, prepared, batched):
    print('AUTOMASK_CASE_BEGIN', grid, order, prepared, batched, flush=True)
    with ExitStack() as owners:
        mesh = lib.Mesh_fromArrays(coords.ravel(), len(coords), corners, len(corners), offsets, len(offsets) - 1)
        owners.callback(lib.freeMesh, mesh)
        tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
        owners.callback(lib.SpatialTree_free, tree)
        brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
        brush.radius, brush.strength = 2, .2
        brush.automask_cavity = prepared
        brush.cavity_use_curve = True
        for i in range(256):
            brush.setCavityCurveEntry(i, .75)
        brush.writeProps()
        if grid:
            mr = lib.Multires_new(mesh, 2, 0, 0, 0)
            owners.callback(lib.Multires_free, mr)
            n = lib.Multires_levelSampleCount(mr, 1)
            session = lib.GridStroke_new(mr, 1, brush.ptr)
            owners.callback(lib.GridStroke_free, session)
            assert lib.GridStroke_begin(session)
        else:
            n = len(coords)
            bound_tree = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
            executor = owners.enter_context(manager.construct_with(
                manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), bound_tree, brush))
            executor.beginStep(False)
            session = executor.ptr
        program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
        for index, name in enumerate(order):
            assert program.addCommand(int(tools[name])) == index
            factor = (.25, .75, .5)[index]
            program.setCommandFloat(index, PROP_RADIUS, .7 if index == 0 else 1.5)
            program.setCommandFloat(index, PROP_STRENGTH, .2 * (1 if prepared else factor))
            if prepared:
                set_command_scalar(manager, program, index, 'automask_cavity', BOOL, True)
                set_command_scalar(manager, program, index, 'cavity_blur_steps', INT32, 3)
                set_command_scalar(manager, program, index, 'cavity_factor', FLOAT32, 1.25)
                if index != 1:
                    replace_command_cavity_curve(manager, program, index, [factor] * 256)
                else:
                    replace_command_cavity_curve(manager, program, index, [.123] * 256)
                    inherit_command_cavity_curve(manager, program, index)
        if prepared:
            for bad in ([0] * 255, [float('nan')] * 256):
                try:
                    replace_command_cavity_curve(manager, program, 0, bad)
                    raise AssertionError('Invalid table accepted')
                except ValueError:
                    pass
            try:
                inherit_command_cavity_curve(manager, program, -1)
                raise AssertionError('Invalid command accepted')
            except BrushPropertyError:
                pass

        def invoke(start, count, policy, target=program):
            dab = np.ascontiguousarray(dabs[start:start + count].ravel())
            inputs = np.ascontiguousarray(samples[start:start + count].ravel())
            if grid:
                return lib.GridStroke_dabBatchProgramInputs(session, target.ptr, count, dab, .2,
                                                           inputs, empty, 0, policy)
            return lib.MeshStroke_dabBatchProgramInputs(session, tree, mesh, brush.ptr, target.ptr,
                                                       count, dab, .2, inputs, 1, empty, 0, policy)

        if prepared:
            fallback = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
            fallback.addCommand(int(tools['GRAB']))
            replace_command_cavity_curve(manager, fallback, 0, [.25] * 256)
            state = brush.radius, brush.strength, brush.automask_cavity, brush.cavity_factor
            for count in (0, 1):
                assert invoke(0, count, 0) == -1  # Raw cannot silently discard command LUTs.
                assert invoke(0, count, 2, fallback) == -1
                assert state == (brush.radius, brush.strength, brush.automask_cavity, brush.cavity_factor)
        if batched:
            assert invoke(0, len(dabs), int(prepared)) >= 0
        else:
            for i in range(len(dabs)):
                assert invoke(i, 1, int(prepared)) >= 0
        print('AUTOMASK_CASE_APPLIED', grid, order, prepared, batched, flush=True)
        assert brush.automask_cavity == prepared
        assert brush.cavity_factor == 1 and brush.cavity_blur_steps == 2 and brush.cavity_use_curve
        if grid:
            lib.GridStroke_end(session)
        else:
            executor.endStep()

        def positions():
            result = np.empty(n * 3, dtype=np.float32)
            if grid:
                assert lib.Multires_levelPositionsOut(mr, 1, result)
            else:
                mesh_object = manager.get_bound_pointer(manager.get('sculptcore::mesh::Mesh'), mesh, deref=False)
                with sculptcore.construct_from_items(manager, manager.get('float'), []) as dump:
                    mesh_object.dumpVertCo(dump)
                    result = dump.numpy().reshape(-1, 4)[:, 1:4].ravel().copy()
            return result

        result = positions()
        if grid:
            assert lib.GridStroke_undo(session)
            assert lib.GridStroke_redo(session)
            assert np.array_equal(positions(), result)
        return result


for grid in (False, True):
    for order in (('DRAW', 'MASK', 'DRAW'), ('DRAW', 'SMOOTH', 'DRAW')):
        expected = run(grid, order, False, False)
        for batch in (False, True):
            result = run(grid, order, True, batch)
            error = float(np.max(abs(result - expected)))
            assert error < 2e-6, (grid, order, batch, error)
            checks.append(dict(grid=grid, order=order, batch=batch, max_error=error))
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-automask-batches.json').write_text(json.dumps(result, indent=2))
print('PLAN6_AUTOMASK_BATCHES_PASS', json.dumps(result))
