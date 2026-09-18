# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise checked configuration through the exact fixture-enabled native DLL."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import math
from unittest.mock import patch
import numpy as np

from run_blender_native_tests import suppress_error_dialogs

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "engine/python"))
import sculptcore
from sculptcore._bulk import construct_from_items
from sculptcore._descriptors import read_litestl_string
from sculptcore.brush_properties import (
    BOOL, FLOAT32, INT32, BrushPropertyError, CommonProperties, DeviceLayer, UniformProperties,
)

dll = (root / "engine/build/native/sculptcore_capi.dll").resolve()
checks = []


def rejects(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except (BrushPropertyError, ValueError, TypeError, IndexError, OverflowError):
        return
    raise AssertionError("Expected rejection")


def bulk(manager, executor, token, index, scalar_type, arrays):
    with ExitStack() as stack:
        vectors = [stack.enter_context(construct_from_items(manager, manager.get(kind), values))
                   for kind, values in zip(("int32", "int32", "float", "int32", "int32", "float"), arrays)]
        before = [list(vector) for vector in vectors]
        status = executor.replaceUniformDynamicsChecked(token, index, scalar_type, *vectors)
        assert before == [list(vector) for vector in vectors], "Native call modified caller arrays"
        return status


with suppress_error_dialogs(), ExitStack() as owners:
    manager = sculptcore.init(str(dll))
    assert Path(manager.capi.lib._name).resolve() == dll
    brush = owners.enter_context(manager.construct("sculptcore::brush::Brush"))
    other = owners.enter_context(manager.construct("sculptcore::brush::Brush"))
    ctor = manager.get_struct("sculptcore::brush::CommandExecutor").find_constructor("main")
    executor = owners.enter_context(manager.construct_with(ctor, None, brush))
    second = owners.enter_context(manager.construct_with(ctor, None, brush))
    items = manager.get("sculptcore::brush::SculptBrushes").items
    view = UniformProperties(manager, executor, int(items["TYPEDPROBE"]))
    by_name = {uniform.name: uniform for uniform in view.uniforms}
    gain, count, enabled = [by_name[name].index for name in ("typed_gain", "typed_count", "typed_enabled")]
    assert view.read(count) == 16777217 and type(view.read(count)) is int
    assert view.read(enabled) is True and view.read(gain) == 0.25
    assert view.read(by_name["typed_low"].index) == -(2 ** 31)
    assert view.read(by_name["typed_high"].index) == 2 ** 31 - 1
    view.write(count, 16777219)
    view.write(enabled, False)
    view.write(gain, 4.0)
    assert view.read(count) == 16777219 and view.read(enabled) is False and view.read(gain) == 4
    checks.append("Exact float/int/bool authored values and int32 endpoints")

    static_bool = by_name["typed_static"].index
    static_int = by_name["typed_high"].index
    limited = by_name["typed_limited"].index
    view.write(static_bool, False)
    view.write(static_int, 16777219)
    assert view.read(static_bool) is False and view.read(static_int) == 16777219
    generation = brush.configurationGeneration()
    rejects(view.write, limited, 0)
    rejects(view.read, static_bool, evaluate=True)
    assert brush.configurationGeneration() == generation and view.read(limited) == 2
    view = UniformProperties(manager, executor, int(items["TYPEDPROBE"]))
    assert view.read(static_bool) is False and view.read(static_int) == 16777219
    view.write(static_bool, True)
    checks.append("Static checked values share native working slots and survive regenerated defaults")

    native_brush = owners.enter_context(manager.construct("sculptcore::brush::Brush"))
    native_executor = owners.enter_context(manager.construct_with(ctor, None, native_brush))
    native_view = UniformProperties(manager, native_executor, int(items["CLAY"]))
    side = next(uniform.index for uniform in native_view.uniforms if uniform.name == "planeSide")
    native_brush.planeSide = -1.0
    assert native_view.read(side) == -1
    native_view.write(side, 1.0)
    assert native_brush.planeSide == 1
    checks.append("Static native member reads and writes agree through the actual CLAY manifest")

    generation = brush.configurationGeneration()
    for index, value in ((count, 1.5), (count, True), (count, 2 ** 32),
                         (enabled, 1), (enabled, 0.5), (gain, float("inf")), (gain, True)):
        rejects(view.write, index, value)
    for index, scalar_type, value in ((count, INT32, 1.5), (count, INT32, 2 ** 31),
                                     (enabled, BOOL, 0.5), (gain, FLOAT32, float("nan"))):
        assert executor.writeUniformScalarChecked(view.token, index, scalar_type, value) != 0
    assert executor.writeUniformScalarChecked(view.token, count, BOOL, 1) != 0
    rejects(view.read, 2 ** 32)
    rejects(view.read, gain, evaluate=1)
    rejects(UniformProperties, manager, executor, 2 ** 32)
    assert brush.configurationGeneration() == generation and view.read(count) == 16777219
    checks.append("Python pre-marshalling and native numeric rejection preserve generation/values")

    brush.pushDeviceInput(0, 0.5)
    brush.pushDeviceInput(1, 0.25)
    view.replace_stack(gain, [DeviceLayer(0, mode=2), DeviceLayer(1)])
    assert view.read(gain, evaluate=True) == 1.125
    view.move(gain, 1, 0)
    assert view.read(gain, evaluate=True) == 1.5
    view.enable(gain, 0, False)
    view.replace_table(gain, 0, (0.8, 0.8))
    # Legacy duplicate add must preserve position, table and disabled flag.
    executor.addUniformDynamic(gain, 0, 2, 1)
    assert view.read(gain, evaluate=True) == 1
    view.enable(gain, 0, True)
    assert abs(view.read(gain, evaluate=True) - 1.8) < 1e-6
    view.configure(gain, 0, 1, 1)
    assert abs(view.read(gain, evaluate=True) - 0.8) < 1e-6
    checks.append("Ordered mixes, move, upsert, enable and bulk table preservation")

    generation = brush.configurationGeneration()
    expected = view.read(gain, evaluate=True)
    for operation, args in (
        (view.configure, (gain, 2 ** 32)), (view.enable, (gain, 0, 2)),
        (view.move, (gain, 0, 3)), (view.replace_table, (gain, 0, (1,))),
        (view.replace_stack, (gain, [DeviceLayer(0), DeviceLayer(0)])),
        (view.replace_stack, (gain, [DeviceLayer(3, factor=float("nan"))])),
        (view.configure, (by_name["typed_static"].index, 0)),
    ):
        rejects(operation, *args)
    invalid = (
        ([0, 0], [1, 1], [1, 1], [1, 1], [0, 0, 0], []),
        ([0], [1], [1], [1], [1, 1], [0]),
        ([0], [1], [1], [1], [0, 1], [0]),
        ([0], [1], [1], [1], [0, 2], [0, float("inf")]),
        ([0], [], [1], [1], [0, 0], []),
        ([4], [1], [1], [1], [0, 0], []),
        ([0], [9], [1], [1], [0, 0], []),
        ([0], [1], [1.5], [1], [0, 0], []),
        ([0], [1], [1], [2], [0, 0], []),
    )
    for arrays in invalid:
        assert bulk(manager, executor, view.token, gain, FLOAT32, arrays) != 0
    assert brush.configurationGeneration() == generation
    assert view.read(gain, evaluate=True) == expected
    checks.append("Failed bulk/configuration operations are atomic; vectors remain caller-owned")

    view.replace_stack(count, [DeviceLayer(0, mode=2)])
    assert view.read(count, evaluate=True) == 16777220
    view.write(enabled, True)
    view.replace_stack(enabled, [DeviceLayer(0)])
    brush.pushDeviceInput(0, 0.49)
    assert view.read(enabled, evaluate=True) is False and view.read(enabled) is True
    brush.pushDeviceInput(0, 0.5)
    assert view.read(enabled, evaluate=True) is True
    checks.append("Typed integer rounding and boolean threshold use changing device inputs")

    view.replace_stack(gain, [DeviceLayer(0, samples=(1, 1))])
    view.set_sample(gain, 0, 0, 3, 0.1)
    rejects(view.read, gain, evaluate=True)
    view.enable(gain, 0, False)
    rejects(view.read, gain, evaluate=True)
    generation = brush.configurationGeneration()
    assert executor.setUniformDynamicSampleChecked(view.token, gain, FLOAT32, 0, 4, 3, 1) != 0
    assert brush.configurationGeneration() == generation
    view.set_sample(gain, 0, 0, 3, 0.2)
    view.set_sample(gain, 0, 1, 3, 0.3)
    rejects(view.read, gain, evaluate=True)
    view.set_sample(gain, 0, 2, 3, 0.4)
    assert view.read(gain, evaluate=True) == 4
    view.enable(gain, 0, True)
    assert abs(view.read(gain, evaluate=True) - 1.2) < 1e-6
    view.set_sample(gain, 0, 1, 3, 0.5)
    assert view.read(gain, evaluate=True) == 2
    view.set_sample(gain, 0, 0, 4, 0.1)
    view.replace_table(gain, 0, ())
    assert view.read(gain, evaluate=True) == 2
    view.clear_stack(gain)
    assert view.read(gain, evaluate=True) == 4
    checks.append("Pending uploads reject evaluation until publication; bulk/clear cancel staging")

    token = view.token
    snapshot = owners.enter_context(executor.uniformSnapshotChecked(token, count))
    result = owners.enter_context(executor.readUniformScalarChecked(token, count, INT32, False))
    assert result.status == 0 and result.value == 16777219
    # Caller-writable legacy metadata cannot change checked mapping or snapshot.
    executor.queriedUniformEntry(count).scalarType = BOOL
    view.write(count, 16777221)
    assert view.read(count) == 16777221 and snapshot.scalarType == INT32
    other_view = UniformProperties(manager, second, int(items["TYPEDPROBE"]))
    assert other_view.token != token
    assert second.writeUniformScalarChecked(token, count, INT32, 1) != 0
    executor.brush = other
    rejects(view.read, count)
    executor.brush = brush
    assert view.read(count) == 16777221
    fresh = UniformProperties(manager, executor, int(items["TYPEDPROBE"]))
    assert fresh.token != token
    rejects(view.read, count)
    token = fresh.token
    UniformProperties(manager, executor, int(items["KELVINLET"]))
    assert executor.uniformQueryToken() != token
    rejects(fresh.read, count)
    token = executor.uniformQueryToken()
    assert executor.queryUniformManifest(99999) == -1
    assert executor.uniformQueryToken() != token
    with executor.uniformSnapshotChecked(token, 0) as stale:
        assert stale.status != 0
    assert read_litestl_string(snapshot.name.ptr) == "typed_count"
    assert getattr(snapshot, "def") == 16777217 and result.value == 16777219
    checks.append("Stale/wrong-owner/wrong-executor queries reject; owned results survive requery")

    assert other.writeCommonScalarChecked(5, BOOL, 1) == 0
    assert other.configureCommonDynamicChecked(5, BOOL, 0, 1, 1) == 0
    other.pushDeviceInput(0, 0)
    with other.readCommonScalarChecked(5, BOOL, True) as result:
        assert result.status == 0 and result.value == 0
    with other.readCommonScalarChecked(5, BOOL, False) as result:
        assert result.status == 0 and result.value == 1
    checks.append("Common invert adapter evaluates boolean dynamics without replacing authored value")

    common = CommonProperties(manager, other)
    common.write(5, True)
    assert common.read(5) is True and common.read(5, evaluate=True) is False
    rejects(common.write, 5, 1)
    rejects(common.read, 2 ** 32)
    rejects(common.configure, 0, 2 ** 32)
    common.write(0, 4.0)
    other.pushDeviceInput(0, 0.5)
    other.pushDeviceInput(1, 0.25)
    common.replace_stack(0, [DeviceLayer(0, mode=2), DeviceLayer(1)])
    assert common.read(0, evaluate=True) == 1.125
    common.move(0, 1, 0)
    common.enable(0, 0, False)
    common.replace_table(0, 0, (0.8, 0.8))
    common.configure(0, 0, 1)
    assert common.read(0, evaluate=True) == 1
    common.enable(0, 0, True)
    common.set_sample(0, 0, 0, 3, 0.5)
    rejects(common.read, 0, evaluate=True)
    common.clear_stack(0)
    assert common.read(0, evaluate=True) == 4
    checks.append("Common Python adapter shares strict selectors, scalar transport and all stack operations")

    view = UniformProperties(manager, executor, int(items['TYPEDPROBE']))
    for index, low, high in ((gain, .25, .75), (count, -3, 16777217), (enabled, 0, 1)):
        for threshold in (0.0, .5, 1.0, math.nextafter(.5, 1.0)):
            layer = DeviceLayer(0, mode=0, response_kind='TWO_STEP', parameters=(threshold, low, high))
            # No scalar element assignment may be used to marshal these vectors.
            with patch('sculptcore._bulk.BoundVector.set_uninitialized', side_effect=AssertionError('per-element copy')):
                view.replace_stack(index, (layer,))
            for input_value in (np.nextafter(np.float32(threshold), np.float32(-np.inf)),
                                np.float32(threshold), np.nextafter(np.float32(threshold), np.float32(np.inf))):
                brush.pushDeviceInput(0, float(input_value))
                expected = low if min(1, max(0, float(input_value))) < threshold else high
                assert view.read(index, evaluate=True) == expected, (index, threshold, input_value, expected)
        generation = brush.configurationGeneration()
        for layer in (DeviceLayer(0, response_kind='CONSTANT', parameters=(math.inf,)),
                      DeviceLayer(0, response_kind='TWO_STEP', parameters=(-1, 0, 1)),
                      DeviceLayer(0, response_kind='CONSTANT', parameters=(1,), samples=(0, 1))):
            rejects(view.replace_stack, index, (layer,))
            assert brush.configurationGeneration() == generation
        view.replace_stack(index, (DeviceLayer(0, mode=0, response_kind='CONSTANT', parameters=(high,)),))
        assert view.read(index, evaluate=True) == high
        view.replace_table(index, 0, (0, 1))
        brush.pushDeviceInput(0, 1)
        assert view.read(index, evaluate=True) == 1
    checks.append('Analytic float/int/bool transport, float-adjacent step boundaries, table switching and bulk copy')

    from test_generic_property_foundation import load_package
    load_package()
    from generic_property_test_package import sampling
    from generic_property_test_package.uploads import StackUploads
    memo = StackUploads()
    stack = ((0, (DeviceLayer(0, samples=(0, 1)),)), (5, (DeviceLayer(0),)))
    assert memo.install(other, common, stack, command='A')
    assert not memo.install(other, common, stack, command='A')
    assert memo.install(other, common, stack, command='B')
    assert memo.install(other, common, stack, command='A')
    common.clear_stack(0)
    assert memo.install(other, common, stack, command='A')
    sampling.clear()
    assert memo.install(other, common, stack, command='A')
    another = owners.enter_context(manager.construct('sculptcore::brush::Brush'))
    assert memo.install(another, CommonProperties(manager, another), stack, command='A')
    assert not memo.install(another, CommonProperties(manager, another), stack, command='A')
    checks.append('Upload memo isolates command A/B/A, cleared configurations, lifecycle epochs and engine instances')
    uniform_memo = StackUploads()
    uniform_stack = ((gain, (DeviceLayer(0, samples=[0, 1]),)),)
    assert uniform_memo.install(brush, view, uniform_stack)
    assert not uniform_memo.install(brush, view, uniform_stack)
    executor.queryUniformManifest(int(items['DRAW']))
    rejects(uniform_memo.install, brush, view, uniform_stack)
    checks.append('Warm upload reuse still rejects stale Uniform manifest tokens')

    from sculptcore.brush_properties import replace_fixed_curve, _primitive_vector
    for kind in ('falloff', 'cavity'):
        replace_fixed_curve(manager, other, kind, tuple(i / 255 for i in range(256)))
        rejects(replace_fixed_curve, manager, other, kind, (0, 1))
        rejects(replace_fixed_curve, manager, other, kind, (float('nan'),) * 256)
        method = other.replaceFalloffCurveChecked if kind == 'falloff' else other.replaceCavityCurveChecked
        with _primitive_vector(manager, 'float', [0, 1]) as vector:
            assert method(vector) is False
            assert list(vector) == [0, 1]
    checks.append('Fixed table bulk transport validates sizes/finiteness and preserves caller vectors')

report = {"passed": True, "dll": str(dll), "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
          "checks": checks}
print(json.dumps(report, indent=2))
