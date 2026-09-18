# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender atomic scalar/policy storage, opaque preservation and persistence."""
from array import array
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys
import threading

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
_, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, PropertyError, Registry
from generic_property_test_package.resolver import resolve, set_value
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-atomic'
DIRECTORY.mkdir(parents=True, exist_ok=True)
checks = []
registry = Registry()
definitions = (
    Definition('test.float', 'Float', 'FLOAT32', .5, 0, 10, 0, 1, 'Float tooltip'),
    Definition('test.int', 'Integer', 'INT32', 16777217, -2147483648, 2147483647, 0, 20000000),
    Definition('test.bool', 'Boolean', 'BOOL', True, 0, 1, 0, 1),
    Definition('test.fractional', 'Integer bounds', 'INT32', 2, 1.25, 7.75, 2.25, 6.75),
    native.STRENGTH_DEFINITION,
)
for definition in definitions:
    registry.register(definition)
FLOAT, INTEGER, BOOLEAN, FRACTIONAL, STRENGTH = definitions
lifecycle.register()


def store(owner):
    return PersistentOwnerStore(owner, registry)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def reject(name, function, types=(ValueError, TypeError, OverflowError, PermissionError)):
    try:
        function()
    except types:
        checks.append(name)
    else:
        raise AssertionError('Accepted: ' + name)


def snapshot(owner, root):
    value = owner.get(root)
    return value.to_dict() if hasattr(value, 'to_dict') else value


def record(owner, definition):
    return owner[ROOT]['records'][record_key(definition.identifier)]


def metadata(owner, definition):
    path = '["{}"]["records"]["{}"]'.format(ROOT, record_key(definition.identifier))
    return owner.path_resolve(path, False).id_properties_ui('value').as_dict()


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    # A separate bpy-only process has already loaded/resaved this file with
    # authoring modules unavailable; this process checks semantic readback.
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'without-authoring.blend'))
    brush = bpy.data.brushes['AtomicSavedBrush']
    check('fresh process exact int', store(brush).read_value(INTEGER).value == 16777217)
    check('fresh process bool', store(brush).read_value(BOOLEAN).value is False)
    check('fresh process saved policy', store(brush).value_mode(FLOAT.identifier) == 'ALWAYS')
    check('fresh process unknown payload', list(brush[ROOT]['opaque']['float32']) == [.25, .5])
    check('resave without authoring modules preserves records', store(brush).read_value(INTEGER).value == 16777217)
else:
    scene = bpy.data.scenes.new('AtomicScalarScene')
    api = scene.id_properties_update_atomic
    check('native no-op delete leaves root absent', not api('test_atomic', (('DELETE', ('missing',)),))
          and 'test_atomic' not in scene)
    reject('invalid later scalar preserves absent root', lambda: api('test_atomic', (
        ('SET', ('one',), 1, None), ('SET', ('two',), float('nan'), None))))
    reject('invalid later UI rolls back absent ancestors', lambda: api('test_atomic', (
        ('SET', ('one',), 1, None), ('SET', ('two',), .5, {'subtype': 'INVALID_SUBTYPE'}))))
    check('both rejected batches left root absent', 'test_atomic' not in scene)
    check('typed batch commits', api('test_atomic', (
        ('SET', ('f',), .375, {'min': 0., 'max': 1., 'step': .1}),
        ('SET', ('i',), 16777217, None), ('SET', ('b',), True, None))))
    initial = snapshot(scene, 'test_atomic')
    old_ui = scene.path_resolve('["test_atomic"]').id_properties_ui('f').as_dict()
    reject('later invalid UI preserves existing scalar and metadata', lambda: api('test_atomic', (
        ('SET', ('i',), 123, None), ('SET', ('f',), .625, {'default': 'invalid'}))))
    check('existing transaction rolled back exactly', snapshot(scene, 'test_atomic') == initial and
          scene.path_resolve('["test_atomic"]').id_properties_ui('f').as_dict() == old_ui)
    check('normalized UI no-op uses stored float step', not api('test_atomic', (
        ('SET', ('f',), .375, {'min': 0., 'max': 1., 'step': .1}),)))
    for label, operations in (
            ('overlapping', (('SET', ('a',), 1, None), ('SET', ('a', 'b'), 2, None))),
            ('duplicate', (('SET', ('a',), 1, None), ('SET', ('a',), 2, None))),
            ('embedded NUL', (('SET', ('a\0b',), 1, None),)),
            ('long key', (('SET', ('x' * 64,), 1, None),)),
            ('deep path', (('SET', ('x',) * 33, 1, None),)),
            ('container value', (('SET', ('a',), {}, None),)),
            ('bad ancestor', (('SET', ('i', 'nested'), 1, None),))):
        reject(label + ' rejects without changes', lambda operations=operations: api('test_atomic', operations))
        assert snapshot(scene, 'test_atomic') == initial
    class EvilList(list):
        def __iter__(self):
            raise AssertionError('Must not call user iterators')
    reject('outer subclass rejected', lambda: api('test_atomic', EvilList()))
    gc.disable()
    assert not api('test_atomic', ()) and not gc.isenabled()
    gc.enable()
    assert not api('test_atomic', ()) and gc.isenabled()
    check('GC state restored for enabled and disabled callers')
    failures = []
    def worker():
        try:
            api('test_atomic', ())
        except PermissionError:
            failures.append(True)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    check('native worker-thread no-op rejects', failures == [True])

    assert api('test_atomic', (('SET', ('enum_value',), 1, None),))
    scene.path_resolve('["test_atomic"]').id_properties_ui('enum_value').update(
        items=[('ONE', 'One', ''), ('TWO', 'Two', '')], description='Before')
    enum_before = scene.path_resolve('["test_atomic"]').id_properties_ui('enum_value').as_dict()['items']
    assert api('test_atomic', (('SET', ('enum_value',), 1, {'description': 'After'}),))
    check('description update preserves opaque enum items',
          scene.path_resolve('["test_atomic"]').id_properties_ui('enum_value').as_dict()['items'] == enum_before)
    check('same enum metadata is a no-op', not api('test_atomic', (
        ('SET', ('enum_value',), 1, {'description': 'After'}),)))
    before_overflow = snapshot(scene, 'test_atomic')
    reject('finite UI step overflow rejects atomically', lambda: api('test_atomic', (
        ('SET', ('i',), 10, None), ('SET', ('f',), .375, {'step': 1e300}))))
    check('UI overflow preserves root', snapshot(scene, 'test_atomic') == before_overflow)

    class OpaqueItem(bpy.types.PropertyGroup):
        value: bpy.props.IntProperty()
    class OpaqueRoot(bpy.types.PropertyGroup):
        scalar: bpy.props.FloatProperty()
        entries: bpy.props.CollectionProperty(type=OpaqueItem)
    for cls in (OpaqueItem, OpaqueRoot):
        bpy.utils.register_class(cls)
    bpy.types.Scene.atomic_opaque = bpy.props.PointerProperty(type=OpaqueRoot)
    scene.atomic_opaque.scalar = .25
    scene.atomic_opaque.id_properties_ui('scalar').update(description='Opaque float32', default=.125)
    scene.atomic_opaque.entries.add()
    scene.atomic_opaque.entries.clear()
    scene['test_atomic'].update(scene.atomic_opaque.id_properties_ensure())
    scene['test_atomic']['float32_array'] = array('f', [.25, .5])
    scene['test_atomic']['empty_int_array'] = array('i', [])
    scene['test_atomic']['unknown'] = {'nested': True, 'bytes': b'opaque'}
    cube = bpy.data.objects['Cube']
    scene['test_atomic']['unknown_id'] = cube
    users = cube.users
    unknown_before = snapshot(scene, 'test_atomic')
    reject('static float cannot become double', lambda: api('test_atomic', (('SET', ('scalar',), .5, None),)))
    reject('ID pointer cannot be removed', lambda: api('test_atomic', (('DELETE', ('unknown_id',)),)))
    reject('group cannot be replaced', lambda: api('test_atomic', (('SET', ('unknown',), 1, None),)))
    check('opaque failure preservation', snapshot(scene, 'test_atomic') == unknown_before and cube.users == users)
    assert api('test_atomic', (('SET', ('i',), 123, None),))
    opaque = scene['test_atomic']
    check('opaque float array and empty array types preserved', opaque['float32_array'].typecode == 'f'
          and opaque['empty_int_array'].typecode == 'i')
    check('empty collection remains an IDProperty collection', type(opaque['entries']) is list and opaque['entries'] == [])
    check('opaque references and bytes preserved', opaque['unknown_id'] == cube and cube.users == users
          and opaque['unknown']['bytes'] == b'opaque')
    check('opaque metadata preserved', scene.path_resolve('["test_atomic"]').id_properties_ui('scalar').as_dict()['default'] == .125)
    reject('static flag survives unrelated successful commit', lambda: api('test_atomic', (('SET', ('scalar',), .5, None),)))
    del bpy.types.Scene.atomic_opaque
    for cls in (OpaqueRoot, OpaqueItem):
        bpy.utils.unregister_class(cls)

    brush = bpy.data.brushes.new('AtomicSavedBrush', mode='SCULPT')
    brush.use_fake_user = True
    parent = store(scene)
    local = store(brush)
    check('missing generic values remain absent', not local.read_value(FLOAT).present and ROOT not in brush)
    local.write_mode(FLOAT.identifier, 'UNIFIED')
    local.write_stack_inheritance(FLOAT.identifier, False)
    check('default policy no-op leaves absent storage', ROOT not in brush)
    local.write_value(INTEGER, 16777217)
    local.write_value(BOOLEAN, False)
    local.write_value(FRACTIONAL, 2)
    check('stored int and bool stay distinct', type(record(brush, INTEGER)['value']) is int
          and type(record(brush, BOOLEAN)['value']) is bool)
    bounds = metadata(brush, FRACTIONAL)
    check('fractional integer metadata intersection', [bounds[key] for key in ('min', 'max', 'soft_min', 'soft_max')] == [2, 7, 3, 6])
    check('bool metadata uses supported fields', metadata(brush, BOOLEAN)['default'] is True)
    for mode in ('UNIFIED', 'ALWAYS', 'NEVER'):
        for unified in (False, True):
            for inherit in (False, True):
                local.write_value(FLOAT, .25)
                parent.write_value(FLOAT, .75)
                local.write_mode(FLOAT.identifier, mode)
                parent.write_unified(FLOAT.identifier, unified)
                local.write_stack_inheritance(FLOAT.identifier, inherit)
                local, parent = store(brush), store(scene)
                inherited = mode == 'ALWAYS' or (mode == 'UNIFIED' and unified)
                result = resolve(registry, FLOAT.identifier, local, parent)
                assert result.value == (.75 if inherited else .25) and result.stack == ()
                assert local.inherits_stack(FLOAT.identifier) is inherit
                set_value(registry, FLOAT.identifier, local, parent, .625)
                assert local.read_value(FLOAT).value == (.25 if inherited else .625)
                assert parent.read_value(FLOAT).value == (.625 if inherited else .75)
    check('all twelve persistent policy/value combinations and effective writes')
    local.write_mode(FLOAT.identifier, 'ALWAYS')
    brush[ROOT]['opaque'] = {'float32': array('f', [.25, .5]), 'future': b'keep'}
    brush[ROOT]['records']['future_record'] = {'future_payload': 7}
    for bad in (1, True, .1, float('nan'), 11.):
        record(brush, FLOAT)['value'] = bad
        reject('malformed saved float ' + repr(bad), lambda: local.read_value(FLOAT))
        local.write_value(FLOAT, .375)
        assert local.read_value(FLOAT).value == .375
    check('unknown data survives explicit scalar repair', brush[ROOT]['opaque']['future'] == b'keep'
          and brush[ROOT]['records']['future_record']['future_payload'] == 7)
    copied = brush.copy()
    store(copied).write_value(INTEGER, 42)
    check('Brush copy has independent scalar records', local.read_value(INTEGER).value == 16777217)
    old_native = brush.strength
    old_flag = brush.use_unified_strength
    local.write_mode(STRENGTH.identifier, 'ALWAYS')
    check('native policy does not duplicate native values', 'value' not in record(brush, STRENGTH)
          and brush.strength == old_native and brush.use_unified_strength == old_flag)
    missing = bpy.data.scenes.new('AtomicNoSculpt')
    check('native missing parent remains unavailable', not store(missing).capability(STRENGTH).value
          and resolve(registry, STRENGTH.identifier, local, store(missing)).value_owner is local)
    brush[ROOT]['schema_version'] = 99
    before = snapshot(brush, ROOT)
    reject('future schema rejects native writes first', lambda: local.write_value(STRENGTH, .5))
    reject('future schema rejects generic writes', lambda: local.write_value(INTEGER, 22))
    check('future schema and native value preserved', snapshot(brush, ROOT) == before and brush.strength == old_native)
    brush[ROOT]['schema_version'] = 1
    reject('native strength has no generic UI path', lambda: local.value_path(STRENGTH.identifier))
    local.write_value(STRENGTH, .625)
    check('persistent store delegates native Brush writes', brush.strength == .625
          and 'value' not in record(brush, STRENGTH))
    bpy.ops.object.mode_set(mode='SCULPT')
    bpy.ops.object.mode_set(mode='OBJECT')
    native_scene = bpy.context.scene.copy()
    store(native_scene).write_value(STRENGTH, .875)
    store(native_scene).write_unified(STRENGTH.identifier, True)
    check('persistent store delegates native Scene writes without duplicates',
          native_scene.tool_settings.sculpt.unified_paint_settings.strength == .875
          and native_scene.tool_settings.sculpt.unified_paint_settings.use_unified_strength
          and ROOT not in native_scene)
    malformed = bpy.data.brushes.new('AtomicMalformed', mode='SCULPT')
    for payload in ({}, {'schema_version': True, 'records': {}},
                    {'schema_version': 1, 'records': 1}):
        malformed[ROOT] = payload
        saved = snapshot(malformed, ROOT)
        reject('malformed schema preserves data ' + repr(payload), lambda: store(malformed).write_value(FLOAT, .5))
        assert snapshot(malformed, ROOT) == saved
    malformed[ROOT] = {'schema_version': 1}
    store(malformed).write_value(FLOAT, .5)
    check('flag-first schema lazily creates records', store(malformed).read_value(FLOAT).value == .5)
    for field, bad, good in (('identifier', 'wrong', FLOAT.identifier), ('scalar_type', 'BOOL', 'FLOAT32'),
                             ('value_mode', 'INVALID', 'UNIFIED'), ('inherit_stack', 1, False),
                             ('unified', 0, False)):
        record(malformed, FLOAT)[field] = bad
        reject('malformed record ' + field, lambda: store(malformed).read_value(FLOAT))
        record(malformed, FLOAT)[field] = good
    for bad in ({'opaque': 7}, array('i', [1, 2])):
        record(malformed, FLOAT)['value'] = bad
        reject('non-scalar explicit repair rejected', lambda: store(malformed).write_value(FLOAT, .5))
    bpy.data.brushes.remove(malformed)
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'records.blend'))
    check('saved fixture without any generic property declarations')

(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
lifecycle.unregister()
print('ATOMIC_SCALAR_STORAGE_PASS', phase, len(checks), flush=True)
