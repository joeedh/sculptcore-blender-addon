# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check command construction and exported stack transport in the staged package."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import numpy as np

from sculptcore_addon import engine
from sculptcore_addon.brush_properties.commands import Command, Parent, build_program, resolve_commands
from sculptcore_addon.brush_properties.registry import Definition
from sculptcore.brush_properties import (
    FLOAT32, INT32, BrushPropertyError, DeviceLayer, inherit_command_stack, replace_command_stack,
)

manager = engine.manager()
dll = Path(manager.capi.lib._name).resolve()
assert 'lib/sculptcore' in dll.as_posix()
tools = manager.get('sculptcore::brush::SculptBrushes').items
assert 'TYPEDPROBE' not in tools
tool = int(tools['DRAW'])
strength = Definition('sculptcore.brush.strength', 'Strength', 'FLOAT32', .5, 0, 1, 0, 1)
commands = resolve_commands((Command('main', tool, (strength,), Parent('DEFAULTS')),), ())
checks = []
with ExitStack() as owners:
    program = owners.enter_context(build_program(manager, commands, {(tool, strength.identifier): 'strength'}))
    replace_command_stack(manager, program, 0, 'radius', FLOAT32,
                          (DeviceLayer(0, mode=2, response_kind='TWO_STEP', parameters=(.5000000000000001, .25, 1)),))
    try:
        inherit_command_stack(program, 0, 'radius', INT32)
    except BrushPropertyError:
        pass
    else:
        raise AssertionError('Wrong-type removal must reject')
    inherit_command_stack(program, 0, 'radius', FLOAT32)
    replace_command_stack(manager, program, 0, 'radius', FLOAT32, ())

    # Exercise the legacy wrappers themselves, including their zero-dab path.
    lib = manager.capi.lib
    coords = np.array((-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0), dtype=np.float32)
    corners, offsets = np.array((0, 1, 2, 3), dtype=np.int32), np.array((0, 4), dtype=np.int32)
    mesh = lib.Mesh_fromArrays(coords, 4, corners, 4, offsets, 1)
    assert mesh
    owners.callback(lib.freeMesh, mesh)
    tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
    assert tree
    owners.callback(lib.SpatialTree_free, tree)
    tree_object = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
    brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
    brush.radius, brush.strength = 2, .25
    brush.writeProps()
    executor = owners.enter_context(manager.construct_with(
        manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), tree_object, brush))
    executor.beginStep(False)
    owners.callback(executor.endStep)
    mr = lib.Multires_new(mesh, 2, 0, 0, 0)
    assert mr
    owners.callback(lib.Multires_free, mr)
    session = lib.GridStroke_new(mr, 2, brush.ptr)
    assert session
    owners.callback(lib.GridStroke_free, session)
    assert lib.GridStroke_begin(session) == 1
    owners.callback(lib.GridStroke_end, session)
    raw = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
    raw.addCommand(tool)
    replace_command_stack(manager, raw, 0, 'radius', FLOAT32, ())
    dab = np.array((100, 100, 100, 0, 0, 1, 20), dtype=np.float32)
    empty = np.empty(0, dtype=np.float32)
    previous = brush.radius, brush.strength, brush.invert
    for n in (0, 1):
        data = dab if n else empty
        assert lib.MeshStroke_dabBatchProgram(executor.ptr, tree, mesh, brush.ptr, raw.ptr, n,
                                              data, .75, 1, .5, 1, 1, empty, 0) == -1
        assert (brush.radius, brush.strength, brush.invert) == previous
        assert lib.GridStroke_dabBatchProgram(session, raw.ptr, n, data, .75, 1, .5, 1, empty, 0) == -1
        assert (brush.radius, brush.strength, brush.invert) == previous
    checks.append('Legacy mesh/grid batch wrappers reject stack-only overrides on zero-dab and miss paths')

result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=[
    'Production addon-only runtime loaded from packaged lib directory',
    'Packaged host DAG builder and scalar/empty-stack C APIs construct a candidate',
    'Packaged analytic stack replacement, type rejection and inheritance restoration',
] + checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-packaged-api.checks.json').write_text(
    json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_PACKAGED_API_PASS', json.dumps(result), flush=True)
