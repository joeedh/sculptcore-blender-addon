# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Inspect accepted tiny-radius behavior in Blender's actual floating-point mode."""
from contextlib import ExitStack
import ctypes
import hashlib
import json
import math
from pathlib import Path
import struct

import numpy as np
import sculptcore
from sculptcore_addon import engine
from sculptcore.brush_properties import BrushPropertyError, CommonProperties, FLOAT32, set_command_scalar


manager = engine.manager()
lib = engine.capi().lib
tool = int(manager.get('sculptcore::brush::SculptBrushes').items['KELVINLET'])
records = []
for bits in (0x00200001, 0x00400000, 0x00800000, 0x3F800000):
    radius = math.ldexp(bits, -149) if bits < 0x00800000 else struct.unpack('<f', struct.pack('<I', bits))[0]
    with ExitStack() as owners:
        coords = np.array((0, 0, 0, 1, 0, 0, 0, 1, 0), dtype=np.float32)
        corners = np.array((0, 1, 2), dtype=np.int32)
        offsets = np.array((0, 3), dtype=np.int32)
        mesh = lib.Mesh_fromArrays(coords, 3, corners, 3, offsets, 1)
        owners.callback(lib.freeMesh, mesh)
        tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
        owners.callback(lib.SpatialTree_free, tree)
        brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
        brush.radius = radius
        brush.unboundedExtent = 0
        brush.grabTo.vec[2] = .25
        brush.writeProps()
        bound_tree = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
        ex = owners.enter_context(manager.construct_with(
            manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), bound_tree, brush))
        ex.setAnchoredGrab(False)
        ex.beginStep(False)
        status = lib.MeshStroke_dabResolved(ex.ptr, tool, 0, 0, 0, 0, 0, 1)
        ex.endStep()
        bound_mesh = manager.get_bound_pointer(manager.get('sculptcore::mesh::Mesh'), mesh, deref=False)
        with sculptcore.construct_from_items(manager, manager.get('float'), []) as dump:
            bound_mesh.dumpVertCo(dump)
            data = dump.numpy().reshape(-1, 4)[:, 1:4].copy()
        record = dict(bits=bits, input_radius=radius, stored_radius=brush.radius,
                      status=status, origin_z=float(data[0, 2]))
        assert status >= 0
        assert record['origin_z'] == (0 if record['stored_radius'] == 0 else .25)
        if record['stored_radius'] == 0:
            # Legacy reflection already delivered zero. Checked binary64 APIs
            # must reject loss occurring inside their own conversion boundary.
            brush.radius = 1
            brush.writeProps()
            access = CommonProperties(manager, brush)
            generation = brush.configurationGeneration()
            try:
                access.write(1, radius)
                raise AssertionError('Checked radius silently flushed to zero')
            except BrushPropertyError:
                pass
            assert access.read(1) == 1 and brush.configurationGeneration() == generation
            program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
            program.addCommand(tool)
            set_command_scalar(manager, program, 0, 'radius', FLOAT32, 1)
            for name in ('radius', 'unboundedExtent'):
                try:
                    set_command_scalar(manager, program, 0, name, FLOAT32, radius)
                    raise AssertionError('Checked override silently flushed to zero')
                except BrushPropertyError:
                    pass
            # Bypass float conversion only to model intact native data arriving
            # from an IEEE producer. The preflight must not interpret its bits
            # as disabled cutoff in this caller's floating environment.
            offset = next(offset for name, _type, offset in brush.bind_type.members if name == 'unboundedExtent')
            extent_bits = ctypes.c_uint32.from_address(brush.ptr + offset)
            extent_bits.value = bits
            ex.beginStep(False)
            empty = np.empty(0, dtype=np.float32)
            assert lib.MeshStroke_dabBatchInputs(ex.ptr, tree, mesh, brush.ptr, tool, 0,
                                                empty, .2, empty, 1, empty, 0, 1) == -1
            assert lib.MeshStroke_dabResolved(ex.ptr, tool, 0, 0, 0, 0, 0, 1) == -1
            assert extent_bits.value == bits
            ex.endStep()
            with sculptcore.construct_from_items(manager, manager.get('float'), []) as dump:
                bound_mesh.dumpVertCo(dump)
                after = dump.numpy().reshape(-1, 4)[:, 1:4].copy()
            assert np.array_equal(after, data)
            record['checked_rejection'] = True
            brush.unboundedExtent = 0
        records.append(record)
        print('DENORMAL_PROBE', json.dumps(record), flush=True)
output = Path(__file__).resolve().parents[1] / 'tests/plan6-kelvinlet-denormal-probe.json'
assert any(record['origin_z'] == .25 for record in records)
dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, cases=records, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
output.write_text(json.dumps(result, indent=2))
print('PLAN6_KELVINLET_DENORMAL_PASS', flush=True)
