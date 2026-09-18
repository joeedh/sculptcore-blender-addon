# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Blender custom-stack ownership, declaration lifetimes and persistence."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle, curves
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key
from generic_property_test_package.resolver import resolve, set_stack

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-custom'
DIRECTORY.mkdir(parents=True, exist_ok=True)
CHECKS = []
registry = Registry()
FLOAT = registry.register(Definition('test.custom', 'Custom', 'FLOAT32', .5, 0, 10, 0, 1))
INT = registry.register(Definition('test.integer', 'Integer', 'INT32', 2, 0, 10, 0, 10))
BOOL = registry.register(Definition('test.boolean', 'Boolean', 'BOOL', True, 0, 1, 0, 1))
lifecycle.register()
bank = curves.CurveBank(registry)
bank.register()


def check(name, condition=True):
    assert condition, name
    CHECKS.append(name)
    print('CUSTOM_CHECK ' + name, flush=True)


def reject(name, action, types=(PropertyError,)):
    try:
        action()
    except types:
        check(name)
    else:
        raise AssertionError('Accepted ' + name)


def store(owner, **kwargs):
    return PersistentOwnerStore(owner, registry, curve_bank=bank, **kwargs)


def record(owner):
    return owner[ROOT]['records'][record_key(FLOAT.identifier)]


def endpoint(owner, definition=FLOAT, device='PRESSURE'):
    target = store(owner)
    reference = bank.reference(target, definition, device)
    return bank.mapping(target, definition, reference).curves[0].points[-1].location.y


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'without-authoring.blend'))
    brush = bpy.data.brushes['CustomStackBrush']
    scene = bpy.data.scenes['CustomStackScene']
    for definition in (FLOAT, INT, BOOL):
        check('fresh custom ' + definition.scalar_type, store(brush).read_stack(definition)[0].curve.mapping_key[0] > 0)
    check('fresh mapping edits', endpoint(brush) == .25 and endpoint(scene) == .75)
    check('fresh Scene CUSTOM selection', store(scene).read_stack(FLOAT)[0].enabled is False)
else:
    brush = bpy.data.brushes.new('CustomStackBrush', mode='SCULPT')
    brush.use_fake_user = True
    scene = bpy.data.scenes.new('CustomStackScene')
    local, parent = store(brush), store(scene)
    check('registration and absent reads do not allocate', ROOT not in brush and local.read_stack(FLOAT) == ())
    reject('absent custom reference rejects', lambda: bank.reference(local, FLOAT, 'PRESSURE'))
    for definition in (FLOAT, INT, BOOL):
        reference = bank.initialize(local, definition, 'PRESSURE')
        check('initialization leaves stack absent ' + definition.scalar_type, local.read_stack(definition) == ())
        local.write_stack(definition, (DeviceLayer('PRESSURE', curve=reference),))
        check('typed custom selection ' + definition.scalar_type, local.read_stack(definition)[0].curve == reference)
    reference = bank.reference(local, FLOAT, 'PRESSURE')
    mapping = bank.mapping(local, FLOAT, reference)
    mapping.curves[0].points[-1].location = (1, .25)
    reject('edited mapping retires old reference', lambda: bank.mapping(local, FLOAT, reference))
    current = local.read_stack(FLOAT)[0]
    check('read sees native revision', current.curve.mapping_key[1] > reference.mapping_key[1])
    reject('wrong device', lambda: local.write_stack(FLOAT, (replace(current, device='SPEED'),)))
    reject('wrong property', lambda: local.write_stack(INT, (current,)))
    reject('wrong owner', lambda: parent.write_stack(FLOAT, (current,)))
    reject('caller epoch', lambda: store(brush, epoch=10).write_stack(FLOAT, (current,)))
    reject('selected removal', lambda: bank.remove(local, FLOAT, 'PRESSURE'))
    local.write_stack(FLOAT, (replace(current, enabled=False),))
    reject('disabled selected removal', lambda: bank.remove(local, FLOAT, 'PRESSURE'))
    local.write_stack(FLOAT, (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
    check('preset keeps dormant mapping', endpoint(brush) == .25)
    local.write_stack(FLOAT, ())
    check('clear keeps dormant mapping', endpoint(brush) == .25)
    copy = brush.copy()
    copy_store = store(copy)
    check('dormant mapping copied', endpoint(copy) == .25)
    for definition in (INT, BOOL):
        check('active CUSTOM copy ' + definition.scalar_type,
              copy_store.read_stack(definition)[0].curve.owner_identity == copy_store.identity)
    copied_ref = bank.reference(copy_store, FLOAT, 'PRESSURE')
    check('copy independent record identity', copied_ref.mapping_key[0] != current.curve.mapping_key[0])
    bank.mapping(copy_store, FLOAT, copied_ref).curves[0].points[-1].location = (1, .625)
    check('copy edits independent', endpoint(brush) == .25 and endpoint(copy) == .625)
    bank.remove(copy_store, FLOAT, 'PRESSURE')
    reject('explicit removal succeeds', lambda: bank.reference(copy_store, FLOAT, 'PRESSURE'))
    parent_ref = bank.initialize(parent, FLOAT, 'PRESSURE')
    bank.mapping(parent, FLOAT, parent_ref).curves[0].points[-1].location = (1, .75)
    parent_ref = bank.reference(parent, FLOAT, 'PRESSURE')
    parent.write_stack(FLOAT, (DeviceLayer('PRESSURE', curve=parent_ref),))
    local.write_stack(FLOAT, (DeviceLayer('PRESSURE', curve=bank.reference(local, FLOAT, 'PRESSURE')),))
    local.write_stack_inheritance(FLOAT.identifier, True)
    resolved = resolve(registry, FLOAT.identifier, local, parent)
    check('Scene custom inheritance', resolved.stack[0].curve == parent_ref)
    set_stack(registry, FLOAT.identifier, local, parent, (replace(resolved.stack[0], enabled=False),))
    check('effective stack write leaves Brush dormant', local.read_stack(FLOAT)[0].enabled is True
          and parent.read_stack(FLOAT)[0].enabled is False)
    reject('inherited stack rejects local reference', lambda: set_stack(
        registry, FLOAT.identifier, local, parent, local.read_stack(FLOAT)))
    local.write_stack_inheritance(FLOAT.identifier, False)
    shared = curves.CurveBank(registry)
    shared.register()
    shared.unregister()
    check('shared lease survives other unregister', endpoint(brush) == .25)
    old_ref = bank.reference(local, FLOAT, 'PRESSURE')
    bank.unregister()
    bank.register()
    new_ref = bank.reference(local, FLOAT, 'PRESSURE')
    check('record key survives declaration re-registration', new_ref.mapping_key == old_ref.mapping_key)
    reject('old bank generation rejected', lambda: bank.mapping(local, FLOAT, old_ref))
    key_api = bpy.props.curve_mapping_declaration_key
    for name, action in (
            ('ordinary RNA', lambda: key_api(bpy.types.Brush, 'strength')),
            ('missing RNA', lambda: key_api(bpy.types.Brush, 'does_not_exist')),
            ('bad type', lambda: key_api(brush, 'strength')),
            ('NUL', lambda: key_api(bpy.types.Brush, 'strength\0ignored')),
            ('non RNA type', lambda: key_api(dict, 'strength'))):
        reject(name, action, (ValueError, TypeError, RuntimeError))
    class BorrowedRNA(bpy.types.PropertyGroup):
        bl_rna = bpy.types.Brush.bl_rna
    reject('borrowed RNA metadata', lambda: key_api(BorrowedRNA, 'strength'), (TypeError,))
    worker_errors = []

    def worker():
        try:
            key_api(bpy.types.Brush, curves.declaration_name(FLOAT.identifier, 'PRESSURE'))
        except RuntimeError:
            worker_errors.append(True)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    check('native worker guard', worker_errors == [True])
    name = curves.declaration_name(FLOAT.identifier, 'PRESSURE')
    deferred = bpy.types.Brush.__dict__[name]
    old_key = key_api(bpy.types.Brush, name)
    delattr(bpy.types.Brush, name)
    setattr(bpy.types.Brush, name, deferred)
    check('same deferred gets new native token', key_api(bpy.types.Brush, name) != old_key)
    reject('external replacement rejects references', lambda: bank.reference(local, FLOAT, 'PRESSURE'))
    bank.unregister()
    check('unregister preserves external replacement', hasattr(bpy.types.Brush, name))
    delattr(bpy.types.Brush, name)
    bank.register()
    # Rollback both fresh declarations and shared acquisitions on a mid-registration failure.
    expanded = Registry()
    for definition in registry.definitions():
        expanded.register(definition)
    added = expanded.register(replace(FLOAT, identifier='zzz.extra'))
    failing = curves.CurveBank(expanded)
    original = bpy.props.CurveMappingProperty
    calls = []

    def factory(**kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError('Injected declaration failure')
        return original(**kwargs)

    for attempt in range(2):
        calls.clear()
        with patch.object(bpy.props, 'CurveMappingProperty', factory):
            reject('partial registration rollback ' + str(attempt), failing.register, (RuntimeError,))
        check('rollback preserves original bank ' + str(attempt), endpoint(brush) == .25)
        check('rollback removes only new declarations ' + str(attempt), not any(
            hasattr(bpy.types.Brush, curves.declaration_name(added.identifier, device)) for device in curves.DEVICE_TYPES))
    failing.register()
    failing.unregister()
    check('registration succeeds after failures', endpoint(brush) == .25)
    collision = curves.CurveBank(registry)
    with patch.object(curves, 'declaration_name', return_value='sc_collision_test'):
        reject('hash collision preflight', collision.register)
    check('collision does not partially register', not hasattr(bpy.types.Brush, 'sc_collision_test'))
    registry.register(replace(FLOAT, identifier='test.new'))
    reject('registry growth requires explicit snapshot', bank.register)
    reject('new definition cannot allocate implicitly', lambda: bank.initialize(
        local, registry.get('test.new'), 'PRESSURE'))
    # Unknown/future metadata blocks mapping mutations without repairing it.
    record(brush)['stack_version'] = 99
    saved = brush[ROOT].to_dict()
    saved_key = bank.reference(local, FLOAT, 'PRESSURE').mapping_key
    reject('future schema initialize', lambda: bank.initialize(local, FLOAT, 'SPEED'))
    reject('future schema removal', lambda: bank.remove(local, FLOAT, 'SPEED'))
    check('rejected future stack mutations preserve payloads', brush[ROOT].to_dict() == saved
          and bank.reference(local, FLOAT, 'PRESSURE').mapping_key == saved_key)
    record(brush)['stack_version'] = 1
    record(brush)['layers']['PRESSURE']['preset'] = 'UNKNOWN'
    reject('malformed selection removal', lambda: bank.remove(local, FLOAT, 'SPEED'))
    record(brush)['layers']['PRESSURE']['preset'] = 'CUSTOM'
    brush[ROOT]['schema_version'] = 99
    saved = brush[ROOT].to_dict()
    reject('future root initialize', lambda: bank.initialize(local, FLOAT, 'SPEED'))
    reject('future root remove', lambda: bank.remove(local, FLOAT, 'SPEED'))
    check('future root preserved', brush[ROOT].to_dict() == saved)
    brush[ROOT]['schema_version'] = 1
    # Re-register snapshot preserves authored mappings, and save actual data.
    bank.unregister()
    bank.register()
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'custom.blend'))

(DIRECTORY / (phase + '.json')).write_text(json.dumps(CHECKS, indent=2), encoding='utf-8')
print('CUSTOM_STORAGE_OK', len(CHECKS), flush=True)
