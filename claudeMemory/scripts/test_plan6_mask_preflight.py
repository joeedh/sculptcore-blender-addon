# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real DLL mask preflight and lazy channel creation matrix."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path

import numpy as np
from sculptcore_addon import engine

manager = engine.manager()
lib = engine.capi().lib
tools = manager.get('sculptcore::brush::SculptBrushes').items
mask, draw = int(tools['MASK']), int(tools['DRAW'])
empty = np.empty(0, dtype=np.float32)
samples = np.array((1, 0, 0, 0, 0, 0), dtype=np.float32)
checks = []


@contextmanager
def fixture():
    with ExitStack() as owners:
        xyz = np.array((-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0), dtype=np.float32)
        corners, offsets = np.array((0, 1, 2, 3), dtype=np.int32), np.array((0, 4), dtype=np.int32)
        mesh = lib.Mesh_fromArrays(xyz, 4, corners, 4, offsets, 1)
        owners.callback(lib.freeMesh, mesh)
        mr = lib.Multires_new(mesh, 2, 0, 0, 0)
        owners.callback(lib.Multires_free, mr)
        brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
        brush.radius, brush.strength = 4, .2
        brush.writeProps()
        session = lib.GridStroke_new(mr, 1, brush.ptr)
        owners.callback(lib.GridStroke_free, session)
        assert lib.GridStroke_begin(session)
        owners.callback(lib.GridStroke_end, session)
        yield owners, mr, brush, session


def invoke(session, target=mask, program=False, policy=1, n=1, radius=4, center=0, strength=.2):
    dab = np.array((center, center, center, 0, 0, 1, radius), dtype=np.float32)
    fn = lib.GridStroke_dabBatchProgramInputs if program else lib.GridStroke_dabBatchInputs
    return fn(session, target, n, dab if n else empty, strength, samples if n else empty, empty, 0, policy)


for shape in ((2, 0, 2), (1, 1, 1), (1, 0, 32)):
    with fixture() as (owners, mr, brush, session):
        ch = lib.Multires_gridChannelEnsure(mr, b'mask', *shape, 1, 1)
        assert ch >= 0
        program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
        program.addCommand(draw)
        program.addCommand(mask)
        before = brush.radius, brush.strength, brush.invert, lib.GridStroke_undoBytes(session)
        for use_program in (False, True):
            target = program.ptr if use_program else mask
            assert not lib.GridStroke_supportsResolved(session, mask, program.ptr if use_program else None)
            for policy in (0, 1, 2):
                for n in (0, 1):
                    assert invoke(session, target, use_program, policy, n, radius=0) == -1
                    assert before == (brush.radius, brush.strength, brush.invert,
                                      lib.GridStroke_undoBytes(session))
                    assert not lib.Multires_gridChannelLevelAllocated(mr, 1, ch)
                    assert not lib.Multires_gridChannelLevelAllocated(mr, 2, ch)
                    checks.append(('malformed', shape, use_program, policy, n))

for first in ('zero', 'miss', 'draw', 'invalid_program', 'validate_only'):
    with fixture() as (owners, mr, brush, session):
        assert lib.Multires_gridChannelFind(mr, b'mask') < 0
        if first == 'zero':
            assert invoke(session, radius=0) >= 0
        elif first == 'miss':
            assert invoke(session, center=100) >= 0
        elif first == 'draw':
            assert invoke(session, target=draw) >= 0
        elif first == 'validate_only':
            assert invoke(session, n=0) == 0
        else:
            program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
            program.addCommand(draw)
            program.addCommand(mask)
            program.addCommand(999999)
            before = brush.invert, lib.GridStroke_undoBytes(session)
            assert invoke(session, program.ptr, True) == -1
            assert before == (brush.invert, lib.GridStroke_undoBytes(session))
        assert lib.Multires_gridChannelFind(mr, b'mask') < 0
        assert invoke(session) >= 0
        assert lib.Multires_gridChannelFind(mr, b'mask') >= 0
        values = np.empty(lib.Multires_levelVertCount(mr, 1), dtype=np.float32)
        assert lib.Multires_readDomainMask(mr, 1, values, len(values))
        assert values.max() > 0
        checks.append(('first_then_mask', first))

with fixture() as (owners, mr, brush, session):
    assert invoke(session, strength=0) >= 0
    assert lib.Multires_gridChannelFind(mr, b'mask') >= 0
    checks.append(('zero_strength_broad_phase_hit',))

dll = Path(manager.capi.lib._name).resolve()
result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-mask-preflight.json').write_text(json.dumps(result, indent=2))
print('PLAN6_MASK_PREFLIGHT_PASS', len(checks))

