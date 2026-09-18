# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Blender generated-stack storage, independent owners and repair gates."""
from array import array
from dataclasses import replace
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
_, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import (
    CURVE_PRESET_ARITY, DEVICE_TYPES, Definition, DeviceLayer, PropertyError, Registry, ResponseCurve)
from generic_property_test_package.resolver import resolve, set_stack, set_layer_enabled, update_layer, set_value
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-stacks'
DIRECTORY.mkdir(parents=True, exist_ok=True)
registry = Registry()
FLOAT = registry.register(Definition('test.float', 'Float', 'FLOAT32', .5, 0, 10, 0, 1))
INTEGER = registry.register(Definition('test.int', 'Integer', 'INT32', 16777217, 0, 2147483647, 0, 20000000))
BOOLEAN = registry.register(Definition('test.bool', 'Boolean', 'BOOL', True, 0, 1, 0, 1))
STATIC = registry.register(replace(FLOAT, identifier='test.static', dynamic=False))
registry.register(native.STRENGTH_DEFINITION)
LOCAL = (DeviceLayer('PRESSURE', False, 'ADD', .375, ResponseCurve('CONSTANT', (-2.,))),
         DeviceLayer('TILT_X', curve=ResponseCurve('TWO_STEP', (1., -3., 1e100))))
PARENT = (DeviceLayer('SPEED', operation='REPLACE', curve=ResponseCurve('SQUARE')),)
checks = []
lifecycle.register()


def store(owner):
    return PersistentOwnerStore(owner, registry)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def reject(name, function):
    try:
        function()
    except PropertyError:
        checks.append(name)
    else:
        raise AssertionError('Accepted: ' + name)


def record(owner, definition=FLOAT):
    return owner[ROOT]['records'][record_key(definition.identifier)]


def layer(owner, device='PRESSURE'):
    return record(owner)['layers'][device]


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'without-authoring.blend'))
    brush = bpy.data.brushes['PersistentStackBrush']
    scene = bpy.data.scenes['PersistentStackScene']
    for definition in (FLOAT, INTEGER, BOOLEAN):
        check('fresh typed stack ' + definition.scalar_type, store(brush).read_stack(definition) == LOCAL)
    check('fresh Scene stack', store(scene).read_stack(FLOAT) == PARENT)
    check('fresh opaque sibling', layer(brush)['unknown']['payload'] == b'keep')
else:
    brush = bpy.data.brushes.new('PersistentStackBrush', mode='SCULPT')
    brush.use_fake_user = True
    scene = bpy.data.scenes.new('PersistentStackScene')
    local, parent = store(brush), store(scene)
    check('absent read is empty', local.read_stack(FLOAT) == ())
    local.write_stack(FLOAT, ())
    check('absent clear allocates nothing', ROOT not in brush)
    check('authoring available but execution disabled', local.capability(FLOAT).stack
          and not local.capability(FLOAT).execution)
    for definition in (FLOAT, INTEGER, BOOLEAN):
        local.write_stack(definition, LOCAL)
        check('typed generated stack ' + definition.scalar_type, local.read_stack(definition) == LOCAL)
    local.write_value(INTEGER, 16777217)
    local.write_value(BOOLEAN, False)
    check('integer and boolean bases remain exact', local.read_value(INTEGER).value == 16777217
          and local.read_value(BOOLEAN).value is False)
    for preset, arity in CURVE_PRESET_ARITY.items():
        parameters = {0: (), 1: (1e100,), 3: (0., -1e100, 3.)}[arity]
        expected = tuple(DeviceLayer(device, curve=ResponseCurve(preset, parameters)) for device in DEVICE_TYPES)
        local.write_stack(FLOAT, expected)
        check('all devices preset ' + preset, local.read_stack(FLOAT) == expected)
    for operation in ('REPLACE', 'MULTIPLY', 'ADD', 'SUBTRACT', 'DIFFERENCE'):
        expected = (DeviceLayer('PRESSURE', operation=operation, factor=0.),)
        local.write_stack(FLOAT, expected)
        check('mix operation ' + operation, local.read_stack(FLOAT) == expected)
    local.write_stack(FLOAT, (DeviceLayer('PRESSURE', factor=1, curve=ResponseCurve('CONSTANT', (2,))),))
    normalized = local.read_stack(FLOAT)[0]
    check('integer descriptor inputs normalize to stored doubles', type(normalized.factor) is float
          and type(normalized.curve.parameters[0]) is float and normalized.curve.parameters == (2.,))
    for mode in ('UNIFIED', 'ALWAYS', 'NEVER'):
        for unified in (False, True):
            for inherit in (False, True):
                local.write_stack(FLOAT, LOCAL)
                parent.write_stack(FLOAT, PARENT)
                local.write_value(FLOAT, .25)
                parent.write_value(FLOAT, .75)
                local.write_mode(FLOAT.identifier, mode)
                parent.write_unified(FLOAT.identifier, unified)
                local.write_stack_inheritance(FLOAT.identifier, inherit)
                local, parent = store(brush), store(scene)
                result = resolve(registry, FLOAT.identifier, local, parent)
                assert result.stack == (PARENT if inherit else LOCAL)
                assert result.stack_owner is (parent if inherit else local)
                assert result.value == (.75 if mode == 'ALWAYS' or (mode == 'UNIFIED' and unified) else .25)
                replacement = (DeviceLayer('TILT_Y', enabled=False),)
                set_stack(registry, FLOAT.identifier, local, parent, replacement)
                assert local.read_stack(FLOAT) == (LOCAL if inherit else replacement)
                assert parent.read_stack(FLOAT) == (replacement if inherit else PARENT)
                assert local.read_value(FLOAT).value == .25 and parent.read_value(FLOAT).value == .75
                local_before, parent_before = local.read_stack(FLOAT), parent.read_stack(FLOAT)
                set_value(registry, FLOAT.identifier, local, parent, .625)
                assert local.read_stack(FLOAT) == local_before and parent.read_stack(FLOAT) == parent_before
    check('all twelve independent owner combinations and effective stack edits')
    local.write_stack_inheritance(FLOAT.identifier, False)
    local.write_mode(FLOAT.identifier, 'NEVER')
    local.write_stack(FLOAT, LOCAL)
    local.write_stack_inheritance(FLOAT.identifier, True)
    local.write_stack_inheritance(FLOAT.identifier, False)
    check('inheritance toggle restores dormant local stack',
          resolve(registry, FLOAT.identifier, local, parent).stack == LOCAL)
    update_layer(registry, FLOAT.identifier, local, parent, replace(LOCAL[0], enabled=True))
    set_layer_enabled(registry, FLOAT.identifier, local, parent, 'PRESSURE', False)
    check('existing device updates in place and disable retains settings', local.read_stack(FLOAT) == LOCAL)
    local.write_stack(FLOAT, tuple(reversed(LOCAL)))
    check('reorder changes order only', local.read_stack(FLOAT) == tuple(reversed(LOCAL)))
    layer(brush)['unknown'] = {'payload': b'keep', 'array': array('f', [.25, .5])}
    before = layer(brush).to_dict()
    local.write_stack(FLOAT, ())
    check('clear retains dormant device payload', local.read_stack(FLOAT) == () and layer(brush).to_dict() == before)
    local.write_stack(FLOAT, LOCAL)
    check('readd preserves extension fields', layer(brush)['unknown']['array'].typecode == 'f')
    immutable = local.read_stack(FLOAT)
    local.write_stack(FLOAT, PARENT)
    check('returned stack is an independent immutable snapshot', immutable == LOCAL)
    local.write_stack(FLOAT, LOCAL)
    reject('duplicate device write', lambda: local.write_stack(FLOAT, (LOCAL[0], LOCAL[0])))
    local.write_stack(native.STRENGTH_DEFINITION, ())
    check('native empty direct write disables pressure', not local._native.pressure_enabled(native.STRENGTH))
    check('native explicit empty read', local.read_stack(native.STRENGTH_DEFINITION) == ())
    reject('static disabled direct write', lambda: local.write_stack(STATIC, (LOCAL[0],)))
    local.write_stack(STATIC, ())
    check('static empty has no record', record_key(STATIC.identifier) not in brush[ROOT]['records'])
    reject('static resolver write', lambda: set_stack(registry, STATIC.identifier, local, parent, (LOCAL[0],)))
    local.write_value(STATIC, .5)
    record(brush, STATIC).update(record(brush))
    record(brush, STATIC)['identifier'] = STATIC.identifier
    reject('static persisted disabled stack direct read', lambda: local.read_stack(STATIC))
    reject('static persisted disabled stack resolver read', lambda: resolve(registry, STATIC.identifier, local, parent))
    local.write_stack(STATIC, ())
    check('static malformed stack can be explicitly cleared', local.read_stack(STATIC) == ())
    layer(brush)['factor'] = {'dormant': True}
    local.write_stack(FLOAT, ())
    check('clear preserves malformed dormant device data', local.read_stack(FLOAT) == ()
          and layer(brush)['factor']['dormant'] is True)
    del layer(brush)['factor']
    local.write_stack(FLOAT, LOCAL)
    for bad in (7, None):
        saved = record(brush)['layers'].to_dict()
        record(brush)['layers'] = bad
        before = brush[ROOT].to_dict()
        reject('malformed top-level layers read ' + repr(bad), lambda: local.read_stack(FLOAT))
        reject('malformed top-level layers clear ' + repr(bad), lambda: local.write_stack(FLOAT, ()))
        assert brush[ROOT].to_dict() == before
        del record(brush)['layers']
        record(brush)['layers'] = saved
    for field, bad in (('enabled', 1), ('factor', 1), ('factor', float('nan')),
                       ('operation', 'UNKNOWN'), ('preset', 'CUSTOM'), ('parameter_2', 1.),
                       ('parameter_0', float('inf'))):
        layer(brush)[field] = bad
        reject('malformed active disabled ' + field + ' ' + repr(bad), lambda: local.read_stack(FLOAT))
        local.write_stack(FLOAT, LOCAL)
        assert local.read_stack(FLOAT) == LOCAL
    for bad in ('PRESSURE,PRESSURE', 'FUTURE_INPUT', ',PRESSURE', 'x' * 65, 1):
        record(brush)['layer_order'] = bad
        reject('bad order ' + repr(bad), lambda: local.read_stack(FLOAT))
        local.write_stack(FLOAT, LOCAL)
    del record(brush)['stack_version']
    reject('partial header read', lambda: local.read_stack(FLOAT))
    local.write_stack(FLOAT, LOCAL)
    check('whole replacement repairs missing version', local.read_stack(FLOAT) == LOCAL)
    del record(brush)['layer_order']
    before = brush[ROOT].to_dict()
    reject('missing order read', lambda: local.read_stack(FLOAT))
    check('missing order read preserves all data', brush[ROOT].to_dict() == before)
    local.write_stack(FLOAT, LOCAL)
    check('whole replacement repairs missing order', local.read_stack(FLOAT) == LOCAL)
    for version in (True, 2):
        record(brush)['stack_version'] = version
        before = record(brush).to_dict()
        reject('version read ' + repr(version), lambda: local.read_stack(FLOAT))
        reject('version write ' + repr(version), lambda: local.write_stack(FLOAT, LOCAL))
        assert record(brush).to_dict() == before
        set_value(registry, FLOAT.identifier, local, parent, .625)
        local.write_mode(FLOAT.identifier, 'ALWAYS')
        check('scalar/policy preserve unknown stack ' + repr(version),
              record(brush)['stack_version'] == version and local.read_value(FLOAT).value == .625)
        record(brush)['stack_version'] = 1
        local.write_mode(FLOAT.identifier, 'NEVER')
    layer(brush)['factor'] = {'broken': True}
    before = brush[ROOT].to_dict()
    reject('later non-scalar leaf rolls back complete replacement',
           lambda: local.write_stack(FLOAT, tuple(reversed(LOCAL))))
    check('late failure preserves order and all fields', brush[ROOT].to_dict() == before)
    del layer(brush)['factor']
    local.write_stack(FLOAT, LOCAL)
    class StaticFixture(bpy.types.PropertyGroup):
        factor: bpy.props.IntProperty()
    bpy.utils.register_class(StaticFixture)
    bpy.types.Scene.stack_static_fixture = bpy.props.PointerProperty(type=StaticFixture)
    scene.stack_static_fixture.factor = 1
    layer(brush).update(scene.stack_static_fixture.id_properties_ensure())
    before = brush[ROOT].to_dict()
    reject('static scalar type mismatch rolls back', lambda: local.write_stack(FLOAT, tuple(reversed(LOCAL))))
    check('static failure preserves whole root', brush[ROOT].to_dict() == before)
    del layer(brush)['factor']
    local.write_stack(FLOAT, LOCAL)
    del bpy.types.Scene.stack_static_fixture
    bpy.utils.unregister_class(StaticFixture)
    for owner in (brush, scene):
        store(owner).write_stack(FLOAT, LOCAL)
        copied = owner.copy()
        store(copied).write_stack(FLOAT, PARENT)
        check(owner.bl_rna.identifier + ' copy owns independent stack', store(owner).read_stack(FLOAT) == LOCAL)
    parent.write_stack(FLOAT, PARENT)
    linked_file = DIRECTORY / 'linked.blend'
    bpy.data.libraries.write(str(linked_file), {brush}, fake_user=True)
    with bpy.data.libraries.load(str(linked_file), link=True) as (_, target):
        target.brushes = [brush.name]
    linked = store(target.brushes[0])
    check('read-only linked stack can be read', linked.read_stack(FLOAT) == LOCAL)
    reject('read-only linked identical write rejects', lambda: linked.write_stack(FLOAT, LOCAL))
    reject('read-only linked clear rejects', lambda: linked.write_stack(FLOAT, ()))
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'records.blend'))
    check('saved all typed stacks and opaque payload')

(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
lifecycle.unregister()
print('PERSISTENT_STACKS_PASS', phase, len(checks), flush=True)
