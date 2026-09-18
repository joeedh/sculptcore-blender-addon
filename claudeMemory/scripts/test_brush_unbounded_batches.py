# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real DLL unbounded batch symmetry, numerical reference and rejection checks."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

import numpy as np
import sculptcore
from sculptcore_addon import engine
from sculptcore.brush_properties import FLOAT32, set_command_scalar


manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
empty = np.empty(0, dtype=np.float32)
coords = np.array([(x / 4, y / 4, .04 * ((x + 2 * y) % 3))
                   for y in range(-6, 7) for x in range(-6, 7)], dtype=np.float32)
corners = np.array([(y * 13 + x, y * 13 + x + 1, (y + 1) * 13 + x + 1, (y + 1) * 13 + x)
                    for y in range(12) for x in range(12)], dtype=np.int32).ravel()
offsets = np.arange(0, len(corners) + 1, 4, dtype=np.int32)
signs = np.array([(-1, 1, 1), (1, -1, 1)], dtype=np.float32)
dabs = np.array([(.3, -.2, .1, 0, 0, 1, 1.2), (.5, .2, .1, 0, 0, 1, 1.7)], dtype=np.float32)
samples = np.tile(np.array((1, 0, 0, 0, 0, 0), dtype=np.float32), (len(dabs), 1))
primary_frame = np.array(((.25, -.15, .1), (.08, -.03, .1), (.8, .1, .6)), dtype=np.float32)
checks = []


def kelvinlet(points, center, radius, extent, frame):
    """Original formula evaluated in double precision, independent of native code."""
    p = points.astype(np.float64)
    radius = float(radius)
    r = p - frame[0].astype(np.float64)
    force = frame[1].astype(np.float64)
    a = (1 + float(np.float32(.4))) / 2
    b = a / (4 * (1 - float(np.float32(.4))))
    e = np.sqrt(np.sum(r * r, axis=1) + radius * radius)
    c1 = (a - b) / e + .5 * a * radius * radius / e ** 3
    delta = (force * c1[:, None] + r * (b * (r @ force) / e ** 3)[:, None]) * radius / (1.5 * a - b)
    if extent > 0:
        cutoff = float(np.float32(radius) * np.float32(extent))
        t = np.clip((cutoff - np.linalg.norm(p - center.astype(np.float64), axis=1)) / (.2 * cutoff), 0, 1)
        delta *= (t * t * (3 - 2 * t))[:, None]
    return (p + delta).astype(np.float32)


def run(grid, program_mode, extent, policy, batched, view_mask=False, reject=False):
    print('UNBOUNDED_CASE', grid, program_mode, extent, policy, batched, view_mask, reject, flush=True)
    with ExitStack() as owners:
        mesh = lib.Mesh_fromArrays(coords.ravel(), len(coords), corners, len(corners), offsets, len(offsets) - 1)
        owners.callback(lib.freeMesh, mesh)
        tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
        owners.callback(lib.SpatialTree_free, tree)
        brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
        brush.radius, brush.strength = 1.2, .2
        brush.unboundedExtent = extent
        brush.automask_view_normal = view_mask
        brush.view_normal_limit = 1.4
        brush.view_normal_falloff = 1.0
        brush.writeProps()

        def frame_write(frame):
            for name, values in zip(('grabFrom', 'grabTo', 'viewDir'), frame):
                for axis, value in enumerate(values):
                    getattr(brush, name).vec[axis] = float(value)

        def frame_read():
            return np.array([[getattr(brush, name).vec[axis] for axis in range(3)]
                             for name in ('grabFrom', 'grabTo', 'viewDir')], dtype=np.float32)

        frame_write(primary_frame)
        if grid:
            mr = lib.Multires_new(mesh, 2, 0, 0, 0)
            owners.callback(lib.Multires_free, mr)
            n = lib.Multires_levelSampleCount(mr, 1)
            session = lib.GridStroke_new(mr, 1, brush.ptr)
            owners.callback(lib.GridStroke_free, session)
            lib.GridStroke_setAnchoredGrab(session, 0)
            assert lib.GridStroke_begin(session)
        else:
            n = len(coords)
            bound_tree = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
            executor = owners.enter_context(manager.construct_with(
                manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), bound_tree, brush))
            executor.setAnchoredGrab(False)
            executor.beginStep(False)
            session = executor.ptr
        program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
        if program_mode:
            assert program.addCommand(int(tools['DRAW'])) == 0
            set_command_scalar(manager, program, 0, 'strength', FLOAT32, 0)
        assert program.addCommand(int(tools['KELVINLET'])) == int(program_mode)

        def positions():
            if grid:
                result = np.empty(n * 3, dtype=np.float32)
                assert lib.Multires_levelPositionsOut(mr, 1, result)
                return result.reshape(-1, 3)
            bound_mesh = manager.get_bound_pointer(manager.get('sculptcore::mesh::Mesh'), mesh, deref=False)
            with sculptcore.construct_from_items(manager, manager.get('float'), []) as dump:
                bound_mesh.dumpVertCo(dump)
                return dump.numpy().reshape(-1, 4)[:, 1:4].copy()

        def invoke(rows, images):
            data = np.ascontiguousarray(rows, dtype=np.float32).ravel()
            inputs = np.ascontiguousarray(samples[:len(rows)].ravel())
            mirrors = np.ascontiguousarray(images, dtype=np.float32).ravel()
            target = program.ptr if program_mode else int(tools['KELVINLET'])
            if grid:
                call = lib.GridStroke_dabBatchProgramInputs if program_mode else lib.GridStroke_dabBatchInputs
                return call(session, target, len(rows), data, .2, inputs, mirrors, len(images), policy)
            call = lib.MeshStroke_dabBatchProgramInputs if program_mode else lib.MeshStroke_dabBatchInputs
            # Force the raw mesh reference to visit every leaf even without cutoff.
            return call(session, tree, mesh, brush.ptr, target, len(rows), data, .2, inputs,
                        1e6 if policy == 0 else 1,
                        mirrors, len(images), policy)

        original = positions()
        expected = original.copy()
        assert invoke([], []) == 0
        assert np.array_equal(original, positions())
        if reject:
            brush.unboundedExtent = 2
            invalid = dabs.copy()
            invalid[1, 6] = np.finfo(np.float32).max
            assert invoke(invalid, []) == -1
            expected = kelvinlet(original, dabs[0, :3], dabs[0, 6], 2, primary_frame)
            assert np.max(abs(positions() - expected)) < 2e-6
            assert brush.radius == float(dabs[0, 6])
            assert np.array_equal(frame_read(), primary_frame)
            saved = positions()
            brush.unboundedExtent = float('inf')
            assert invoke([], []) == -1
            assert np.array_equal(saved, positions())
            brush.unboundedExtent = extent
        else:
            for row in dabs:
                for sign in (np.ones(3, dtype=np.float32), *signs):
                    expected = kelvinlet(expected, row[:3] * sign, row[6], extent, primary_frame * sign)
            if batched:
                assert invoke(dabs, signs) >= 0
            else:
                for row in dabs:
                    for sign in (np.ones(3, dtype=np.float32), *signs):
                        frame_write(primary_frame * sign)
                        image = row.copy()
                        image[:3] *= sign
                        image[3:6] *= sign
                        assert invoke([image], []) >= 0
                frame_write(primary_frame)
            assert np.array_equal(frame_read(), primary_frame)
            if not view_mask:
                assert np.max(abs(positions() - expected)) < 2e-6
        result = positions()
        assert np.isfinite(result).all()
        assert np.max(abs(result - original)) > .01
        if grid:
            lib.GridStroke_end(session)
            assert lib.GridStroke_undo(session)
            assert np.array_equal(positions(), original)
            assert lib.GridStroke_redo(session)
            assert np.array_equal(positions(), result)
        else:
            executor.endStep()
        return result


for grid in (False, True):
    for program_mode in (False, True):
        for extent in (0, 2):
            expected = run(grid, program_mode, extent, 1, False)
            if not grid and not program_mode:
                raw = run(False, False, extent, 0, False)
                assert np.array_equal(raw, expected)
            for policy in (1, 2):
                actual = run(grid, program_mode, extent, policy, True)
                assert np.array_equal(actual, expected)
                checks.append(dict(grid=grid, program=program_mode, extent=extent, policy=policy))
        expected = run(grid, program_mode, 2, 1, False, view_mask=True)
        actual = run(grid, program_mode, 2, 1, True, view_mask=True)
        assert np.array_equal(actual, expected)
        for policy in (1, 2):
            run(grid, program_mode, 2, policy, True, reject=True)

dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-unbounded-batches.json').write_text(json.dumps(result, indent=2))
print('PLAN6_UNBOUNDED_BATCHES_PASS', json.dumps(result), flush=True)

import bpy
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
