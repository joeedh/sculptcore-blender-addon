# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed prepared grab: addon direct images, programs, batches and native grids."""
import hashlib
from itertools import product
import json
from pathlib import Path
import sys

import bpy
import numpy as np
import sculptcore
from sculptcore_addon import engine, stroke
from sculptcore.brush_properties import FLOAT32, set_command_scalar

manager = engine.manager()
lib = engine.capi().lib
kelvinlet = '--kelvinlet' in sys.argv
grab = int(manager.get('sculptcore::brush::SculptBrushes').items['KELVINLET' if kelvinlet else 'GRAB'])
checks, references, calls = [], {}, []
for domain in ('Mesh', 'Grid'):
    for suffix in ('dabResolvedImage', 'dabProgramResolved'):
        name = domain + 'Stroke_' + suffix
        native = getattr(lib, name)

        def checked(*args, _native=native, _name=name):
            result = _native(*args)
            calls.append((_name, result))
            assert result >= 0, (_name, result)
            return result

        setattr(lib, name, checked)


def positions(session):
    if session.last_stroke_grids:
        level = session.grid_level
        count = lib.Multires_levelSampleCount(session.multires_ptr, level)
        data = np.empty(count * 3, dtype=np.float32)
        assert lib.Multires_levelPositionsOut(session.multires_ptr, level, data)
        return data.reshape(-1, 3)
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().reshape(-1, 4)[:, 1:].copy()


def field_delta(base, center, force, radius):
    """Original elasticity formula in double precision, independent of the kernel."""
    radius = float(np.float32(radius))
    r = base.astype(np.float64) - np.asarray(center, dtype=np.float32)
    force = np.asarray(force, dtype=np.float32)
    a = (1 + float(np.float32(.4))) / 2
    b = a / (4 * (1 - float(np.float32(.4))))
    e = np.sqrt(np.sum(r * r, axis=1) + radius * radius)
    c1 = (a - b) / e + .5 * a * radius * radius / e ** 3
    delta = (force * c1[:, None] + r * (b * (r @ force) / e ** 3)[:, None]) * radius / (1.5 * a - b)
    cutoff = float(np.float32(radius) * np.float32(1.5))
    t = np.clip((cutoff - np.linalg.norm(r, axis=1)) / (.2 * cutoff), 0, 1)
    return delta * (t * t * (3 - 2 * t))[:, None], t > 0


for multires, nonaccum, program_mode, symmetry, batched in product((False, True), repeat=5):
    # Program symmetry has an independent native oracle; direct addon program
    # calls represent a primary image. Standalone images cover the host mirror API.
    if program_mode and symmetry:
        continue
    if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=14, y_subdivisions=14, size=4)
    obj = bpy.context.object
    if multires:
        obj.modifiers.new('Multires', 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier='Multires')
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    session = engine.sessions[obj.name]
    brush = stroke._ensure_brush(session)
    brush.radius, brush.strength = .7, .35
    brush.unboundedExtent = 1.5
    brush.writeProps()
    stroke.stroke_begin(session, accumulate=not nonaccum, anchored_grab=True, grids_kernel=grab)
    assert session.last_stroke_grids == multires
    executor = stroke._ensure_executor(session)
    assert (lib.GridStroke_supportsResolved(session.grid_ptr, grab, None) if multires
            else executor.supportsResolved(grab))
    original = positions(session)
    expected = original.astype(np.float64)
    start_calls = len(calls)
    with manager.construct('sculptcore::brush::BrushProgram') as program:
        program.addCommand(grab)
        program.addCommand(grab)
        set_command_scalar(manager, program, 1, 'radius', FLOAT32, 3)
        set_command_scalar(manager, program, 1, 'strength', FLOAT32, .15)
        for index, radius in enumerate((.7, 2.5, 1.1)):
            center = (.3, 0, 0)
            delta = (.3, .1, .3 * (index + 1))
            brush.radius, brush.strength = radius, .35
            brush.writeProps()
            for axis in range(3):
                brush.grabFrom.vec[axis] = center[axis]
                brush.grabTo.vec[axis] = delta[axis]
            if batched:
                rows = np.array((*center, 0, 0, 1, radius), dtype=np.float32)
                samples = np.array((1, 0, 0, 0, 0, 0), dtype=np.float32)
                signs = np.array((-1, 1, 1) if symmetry else (), dtype=np.float32)
                suffix = 'dabBatchProgramInputs' if program_mode else 'dabBatchInputs'
                target = program.ptr if program_mode else grab
                function = getattr(lib, ('Grid' if multires else 'Mesh') + 'Stroke_' + suffix)
                args = ([session.grid_ptr] if multires else
                        [executor.ptr, session.tree_ptr, session.mesh_ptr, brush.ptr])
                args += [target, 1, rows, .35, samples]
                if not multires:
                    args += [1]
                status = function(*args, signs, int(symmetry), 1)
                assert status >= 0
                calls.append(('required prepared batch', status))
            elif program_mode:
                assert stroke.apply_dab_program(session, program, center, (0, 0, 1), radius, kernel=grab) >= 0
            else:
                cursor = tuple(center[a] + delta[a] for a in range(3))
                assert stroke.apply_grab_dab(session, grab, center, cursor, (0, 0, 1), radius) >= 0
                if symmetry:
                    mirror_center = (-center[0], center[1], center[2])
                    mirror_cursor = (-cursor[0], cursor[1], cursor[2])
                    assert stroke.apply_grab_dab(session, grab, mirror_center, mirror_cursor,
                                                (0, 0, 1), radius, accum_add=True) >= 0
            moved = positions(session)
            assert np.isfinite(moved).all() and np.max(abs(moved - original)) > 1e-5
            if kelvinlet:
                written = np.zeros(len(original), dtype=bool)
                for sign in ((1, 1, 1), (-1, 1, 1)) if symmetry else ((1, 1, 1),):
                    image_center = np.asarray(center) * sign
                    image_force = np.asarray(delta) * sign
                    for stage_radius in (radius, 3) if program_mode else (radius,):
                        change, supported = field_delta(original, image_center, image_force, stage_radius)
                        first = supported & ~written
                        expected[first] = original[first]
                        expected[supported] += change[supported]
                        written |= supported
                error = float(np.max(abs(moved - expected)))
                assert error < 2e-5, (multires, program_mode, symmetry, batched, index, error)
            key = multires, nonaccum, program_mode, symmetry, index
            if batched:
                assert np.allclose(moved, references[key], rtol=0, atol=2e-6), key
            else:
                references[key] = moved.copy()
        assert len(calls) > start_calls
    stroke.stroke_end(session)
    checks.append(dict(multires=multires, nonaccum=nonaccum, program=program_mode, symmetry=symmetry,
                       batched=batched, vertices=len(moved), prepared_calls=calls[start_calls:]))

bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, checks=checks, kelvinlet=kelvinlet,
              dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
output_name = 'plan6-grab-kelvinlet-host.json' if kelvinlet else 'plan6-grab-host.json'
(Path(__file__).resolve().parents[1] / 'tests' / output_name).write_text(json.dumps(result, indent=2))
print('PLAN6_GRAB_HOST_PASS', json.dumps(result), flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=1)
