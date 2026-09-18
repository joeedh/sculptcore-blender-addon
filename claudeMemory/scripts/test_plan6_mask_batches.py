# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual DLL mask program/batch parity, preflight and grid undo."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import numpy as np
from sculptcore_addon import engine
from sculptcore_addon.mapping import PROP_RADIUS, PROP_STRENGTH
from sculptcore.brush_properties import FLOAT32, DeviceLayer, replace_command_stack

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
prop = {'Radius': PROP_RADIUS, 'Strength': PROP_STRENGTH}
empty = np.empty(0, dtype=np.float32)
checks = []
coords = np.array([(x / 4, y / 4, 0) for y in range(-8, 9) for x in range(-8, 9)], dtype=np.float32)
corners = np.array([(y * 17 + x, y * 17 + x + 1, (y + 1) * 17 + x + 1, (y + 1) * 17 + x)
                    for y in range(16) for x in range(16)], dtype=np.int32).ravel()
offsets = np.arange(0, len(corners) + 1, 4, dtype=np.int32)
dabs = np.array([(-.5 + .25 * i, 0, 0, 0, 0, 1, 4) for i in range(4)], dtype=np.float32)
samples = np.array(((.2, .1, 0, 0, 3, 0), (.5, .7, 0, 0, 3, 0),
                    (1, 1, 0, 0, 3, 1), (0, 0, 0, 0, 0, 0)), dtype=np.float32)


def run(grid, order, prepared, batched):
    with ExitStack() as owners:
        mesh = lib.Mesh_fromArrays(coords.ravel(), len(coords), corners, len(corners), offsets, len(offsets) - 1)
        assert mesh
        owners.callback(lib.freeMesh, mesh)
        tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
        owners.callback(lib.SpatialTree_free, tree)
        brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
        brush.radius, brush.strength = 4, .3
        brush.writeProps()
        if grid:
            mr = lib.Multires_new(mesh, 2, 0, 0, 0)
            owners.callback(lib.Multires_free, mr)
            n = lib.Multires_levelVertCount(mr, 1)
            nf = lib.Multires_levelVertCount(mr, 2)
            seed = np.linspace(.1, .2, n, dtype=np.float32)
            fine_seed = np.linspace(.2, .3, nf, dtype=np.float32)
            assert lib.Multires_writeDomainMask(mr, 1, seed, n)
            assert lib.Multires_writeDomainMask(mr, 2, fine_seed, nf)
            session = lib.GridStroke_new(mr, 1, brush.ptr)
            owners.callback(lib.GridStroke_free, session)
            assert lib.GridStroke_begin(session)
        else:
            n = len(coords)
            seed = np.linspace(.1, .2, n, dtype=np.float32)
            assert lib.Mesh_writeVertFloatAttr(mesh, b'.spatial.v.mask', seed)
            tree_object = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
            executor = owners.enter_context(manager.construct_with(
                manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), tree_object, brush))
            executor.beginStep(False)
            session = executor.ptr
        program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
        for name in order:
            index = program.addCommand(int(tools[name]))
            program.setCommandFloat(index, int(prop['Radius']), .2 if name == 'DRAW' else 1.0)
            program.setCommandFloat(index, int(prop['Strength']), .15 if name == 'DRAW' else .3)
            if prepared:
                replace_command_stack(manager, program, index, 'radius', FLOAT32,
                                      (DeviceLayer(0 if name == 'DRAW' else 1, mode=2, samples=(0, 1)),))
                replace_command_stack(manager, program, index, 'strength', FLOAT32,
                                      (DeviceLayer(0, samples=(0, 1)),) if name == 'DRAW' else ())

        def masks(level=1):
            data = np.empty(n if level == 1 else nf, dtype=np.float32)
            if grid:
                assert lib.Multires_readDomainMask(mr, level, data, len(data))
            else:
                assert lib.Mesh_readVertFloatAttr(mesh, b'.spatial.v.mask', data)
            return data

        def apply(start, count):
            dab = np.ascontiguousarray(dabs[start:start + count].ravel())
            inputs = np.ascontiguousarray(samples[start:start + count].ravel())
            if grid:
                return lib.GridStroke_dabBatchProgramInputs(session, program.ptr, count, dab, .3,
                                                           inputs, empty, 0, int(prepared))
            return lib.MeshStroke_dabBatchProgramInputs(session, tree, mesh, brush.ptr, program.ptr,
                                                       count, dab, .3, inputs, 1, empty, 0, int(prepared))

        if prepared and batched:
            assert apply(0, len(dabs)) >= 0
        else:
            for i, sample in enumerate(samples):
                if not prepared:
                    program.clear()
                    pressure, tilt = map(float, sample[:2])
                    present = int(sample[4])
                    for index, name in enumerate(order):
                        assert program.addCommand(int(tools[name])) == index
                        radius = (.2 + (pressure if present & 1 else 0) if name == 'DRAW'
                                  else 1.0 + (tilt if present & 2 else 0))
                        strength = .15 * (pressure if present & 1 else 1) if name == 'DRAW' else .3
                        program.setCommandFloat(index, int(prop['Radius']), radius)
                        program.setCommandFloat(index, int(prop['Strength']), strength)
                assert apply(i, 1) >= 0
        if grid:
            lib.GridStroke_end(session)
        else:
            executor.endStep()
        after = masks()
        assert np.max(np.abs(after - seed)) > .001
        if grid:
            fine_after = masks(2)
            assert lib.GridStroke_undo(session)
            assert np.array_equal(masks(), seed)
            assert np.array_equal(masks(2), fine_seed)
            assert lib.GridStroke_redo(session)
            assert np.array_equal(masks(), after)
            assert np.array_equal(masks(2), fine_after)
        return after


for grid in (False, True):
    for order in (('MASK',), ('DRAW', 'MASK'), ('MASK', 'DRAW')):
        reference = run(grid, order, False, False)
        for batch in (False, True):
            actual = run(grid, order, True, batch)
            assert np.allclose(actual, reference, atol=2e-6, rtol=0), (grid, order, batch, np.max(abs(actual-reference)))
            checks.append(dict(grid=grid, order=order, batch=batch, max_error=float(np.max(abs(actual-reference)))))

dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-mask-batches.json').write_text(json.dumps(result, indent=2))
print('PLAN6_MASK_BATCHES_PASS', json.dumps(result))
