# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual DLL command transport, candidate publication and geometry regression."""
from contextlib import ExitStack
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

from run_blender_native_tests import suppress_error_dialogs

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'engine/python'))
import sculptcore
from sculptcore.brush_properties import (
    BOOL, FLOAT32, INT32, BrushPropertyError, DeviceLayer, _primitive_vector,
    inherit_command_stack, replace_command_stack,
)

path = root / 'sculptcore_addon/brush_properties'
spec = importlib.util.spec_from_file_location('plan6_host', path / '__init__.py',
                                            submodule_search_locations=[str(path)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from plan6_host.commands import Command, ExecutionLayer, Parent, build_program, resolve_commands
from plan6_host.registry import Definition
from plan6_host.responses import PreparedResponse

dll = root / 'engine/build/native/sculptcore_capi.dll'
checks = []
with suppress_error_dialogs(), ExitStack() as owners:
    manager = sculptcore.init(str(dll))
    lib = manager.capi.lib
    fp, ip, ptr = C.POINTER(C.c_float), C.POINTER(C.c_int), C.c_void_p
    lib.Mesh_fromArrays.argtypes = [fp, C.c_int, ip, C.c_int, ip, C.c_int]
    lib.Mesh_fromArrays.restype = ptr
    lib.Mesh_buildSpatialTree.argtypes = [ptr, C.c_int, C.c_int, C.c_int]
    lib.Mesh_buildSpatialTree.restype = ptr
    lib.freeMesh.argtypes = [ptr]
    lib.SpatialTree_free.argtypes = [ptr]
    lib.Mesh_toArrays.argtypes = [ptr, fp, ip, ip, ip]
    positions = (C.c_float * 9)(-.5, -.5, 0, .5, -.5, 0, 0, .5, 0)
    corners, offsets = (C.c_int * 3)(0, 1, 2), (C.c_int * 2)(0, 3)
    mesh = lib.Mesh_fromArrays(positions, 3, corners, 3, offsets, 1)
    owners.callback(lib.freeMesh, mesh)
    tree = lib.Mesh_buildSpatialTree(mesh, 0, 0, 0)
    owners.callback(lib.SpatialTree_free, tree)
    tree_object = manager.get_bound_pointer(manager.get('sculptcore::spatial::SpatialTree'), tree, deref=False)
    brush = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
    executor = owners.enter_context(manager.construct_with(
        manager.get_struct('sculptcore::brush::CommandExecutor').find_constructor('main'), tree_object, brush))
    tool = int(manager.get('sculptcore::brush::SculptBrushes').items['TYPEDRESOLVED'])
    gain = Definition('probe.gain', 'Gain', 'FLOAT32', .25, 0, 1, 0, 1)
    count = Definition('probe.count', 'Count', 'INT32', 16777217, -2147483648, 2147483647, 0, 20000000)
    enabled = Definition('probe.enabled', 'Enabled', 'BOOL', True, 0, 1, 0, 1)
    layers = (
        (gain.identifier, (ExecutionLayer('PRESSURE', PreparedResponse('CONSTANT', parameters=(.5,))),)),
        (count.identifier, (ExecutionLayer('TILT_X', PreparedResponse('TABLE', (0.0, 1.0)), operation='ADD'),)),
        (enabled.identifier, (ExecutionLayer('TILT_Y', PreparedResponse('TWO_STEP', parameters=(.5, 0, 1))),)),
    )
    commands = resolve_commands((Command('main', tool, (gain, count, enabled), Parent('DEFAULTS'), stacks=layers),), ())
    names = {(tool, gain.identifier): 'typed_gain', (tool, count.identifier): 'typed_count',
             (tool, enabled.identifier): 'typed_enabled'}
    program = owners.enter_context(build_program(manager, commands, names))
    brush.radius, brush.strength = 10, 1
    brush.writeProps()
    executor.beginStep(False)
    owners.callback(executor.endStep)
    fn = lib.MeshStroke_dabBatchProgramInputs
    fn.argtypes = [ptr, ptr, ptr, ptr, ptr, C.c_int, fp, C.c_float, fp, C.c_float, fp, C.c_int, C.c_int]
    fn.restype = C.c_int
    dabs = (C.c_float * 7)(0, 0, 0, 0, 0, 1, 10)
    samples = (C.c_float * 6)(.5, 0, .5, 0, 7, 0)

    def geometry():
        out = (C.c_float * 9)()
        lib.Mesh_toArrays(mesh, out, corners, offsets, None)
        return tuple(out)

    def run(expected, target=program, policy=1, n=1):
        before = geometry()
        result = fn(executor.ptr, tree, mesh, brush.ptr, target.ptr, n,
                    dabs if n else None, 1, samples if n else None, 1, None, 0, policy)
        after = geometry()
        if expected is None:
            assert result == -1 and after == before
        else:
            assert result >= 0
            for vertex in range(3):
                assert abs(after[vertex * 3] - before[vertex * 3] - expected) < 1e-6, (before, after, expected)

    run(.125)
    samples[2] = .49
    run(0)
    samples[2], samples[1] = .5, 1
    run(0)
    samples[4] = 0
    run(.25)
    samples[1], samples[4] = 0, 7
    checks.append('Cold independent float/int/bool command stacks and changing/absent inputs affect geometry')

    replace_command_stack(manager, program, 0, 'typed_gain', FLOAT32, ())
    run(.25)
    arrays = (('int32', [0]), ('int32', [1]), ('float', [1]), ('int32', [1]),
              ('int32', [0, 1]), ('float', [.5]), ('int32', [0]), ('double', [0, 0, 0]))
    with ExitStack() as buffers:
        vectors = [buffers.enter_context(_primitive_vector(manager, kind, values)) for kind, values in arrays]
        before = [list(vector) for vector in vectors]
        replace_native = lib.BrushProgram_replaceResponseDynamicsChecked
        assert replace_native(program.ptr, 0, b'typed_gain', FLOAT32, *(v.ptr for v in vectors)) != 0
        assert before == [list(vector) for vector in vectors]
        assert replace_native(program.ptr, -1, b'typed_gain', FLOAT32, *(v.ptr for v in vectors)) != 0
    try:
        inherit_command_stack(program, 0, 'typed_gain', BOOL)
    except BrushPropertyError:
        pass
    else:
        raise AssertionError('Expected type rejection')
    run(.25)
    checks.append('Failed checked replacement/removal preserves explicit empty and caller buffers')

    threshold = .5000000000000001
    replace_command_stack(manager, program, 0, 'typed_gain', FLOAT32,
                          (DeviceLayer(0, response_kind='TWO_STEP', parameters=(threshold, .5, 1.5)),))
    run(.125)
    samples[0] = .5000000596046448
    run(.375)
    inherit_command_stack(program, 0, 'typed_gain', FLOAT32)
    run(.25)
    checks.append('Analytic double threshold survives reflection transport and removal restores inheritance')

    previous = program.ptr
    original = replace_command_stack
    calls = []

    def fail_late(*args):
        calls.append(args[3])
        if len(calls) == 2:
            raise BrushPropertyError(-1)
        return original(*args)

    with patch('sculptcore.brush_properties.replace_command_stack', fail_late):
        try:
            build_program(manager, commands, names)
        except BrushPropertyError:
            pass
        else:
            raise AssertionError('Expected candidate failure')
    assert program.ptr == previous and len(calls) == 2
    run(.25)
    checks.append('Late candidate upload failure preserves the previous executable program')

    raw = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
    raw.addCommand(tool)
    replace_command_stack(manager, raw, 0, 'radius', FLOAT32, ())
    old_values = brush.radius, brush.strength, brush.invert
    run(None, raw, policy=0, n=0)
    run(None, raw, policy=0)
    assert (brush.radius, brush.strength, brush.invert) == old_values
    checks.append('Stack-only explicit empty rejects raw zero-dab and batch execution without overlay changes')

result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(), checks=checks)
(root / 'claudeMemory/tests/plan6-command-bindings.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_COMMAND_BINDINGS_PASS', json.dumps(result))
