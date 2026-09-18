# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise public input ABI and exact typed command overrides through the built DLL."""
from contextlib import ExitStack
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys
from run_blender_native_tests import suppress_error_dialogs

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'engine/python'))
import sculptcore
from sculptcore.brush_properties import UniformProperties, DeviceLayer, set_command_scalar, INT32, BOOL

dll = root / 'engine/build/native/sculptcore_capi.dll'
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
    access = UniformProperties(manager, executor, tool)
    by_name = {uniform.name: uniform.index for uniform in access.uniforms}
    access.replace_stack(by_name['typed_enabled'], [DeviceLayer(0)])
    access.replace_stack(by_name['typed_count'], [DeviceLayer(1, mode=2)])
    access.replace_stack(by_name['typed_gain'], [DeviceLayer(2)])
    program = owners.enter_context(manager.construct('sculptcore::brush::BrushProgram'))
    program.addCommand(tool)
    set_command_scalar(manager, program, 0, 'typed_count', INT32, 16777217)
    set_command_scalar(manager, program, 0, 'typed_enabled', BOOL, True)
    brush.radius, brush.strength = 10, 1
    brush.writeProps()
    executor.beginStep(False)
    fn = lib.MeshStroke_dabBatchProgramInputs
    fn.argtypes = [ptr, ptr, ptr, ptr, ptr, C.c_int, fp, C.c_float, fp, C.c_float, fp, C.c_int, C.c_int]
    fn.restype = C.c_int
    dabs = (C.c_float * 28)(*([0, 0, 0, 0, 0, 1, 10] * 4))
    samples = (C.c_float * 24)(.5, 0, .5, 0, 7, 0, .49, 0, .5, 0, 7, 0,
                                1, 1, .5, 0, 7, 0, 0, 0, 0, 0, 0, 0)
    assert fn(executor.ptr, tree, mesh, brush.ptr, program.ptr, 4, dabs, 1, samples, 1, None, 0, 1) > 0
    out = (C.c_float * 9)()
    lib.Mesh_toArrays(mesh, out, corners, offsets, None)
    for i in range(3):
        assert abs(out[i * 3] - positions[i * 3] - .375) < 1e-6, list(out)
    assert access.read(by_name['typed_count']) == 16777217
    # Invalid row must reject before replacing the previous sample or dab values.
    samples[4] = 16
    old_radius, old_strength = brush.radius, brush.strength
    assert fn(executor.ptr, tree, mesh, brush.ptr, program.ptr, 4, dabs, 2, samples, 1, None, 0, 1) == -1
    assert (brush.radius, brush.strength) == (old_radius, old_strength)
    executor.endStep()
result = dict(passed=True, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),
              checks=['Public per-dab float/int/bool geometry', 'Exact integer command override',
                      'Missing input after present input', 'Invalid batch rejects without changing dab state'])
(root / 'claudeMemory/tests/plan3-public-inputs-python.json').write_text(json.dumps(result, indent=2))
print('PLAN3_PUBLIC_INPUTS_PYTHON_PASS', json.dumps(result))
