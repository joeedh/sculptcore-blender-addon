# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Custom selection and actual mapping payloads through external asset Save/Revert."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle, sampling
from generic_property_test_package.curves import CurveBank
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-custom-assets'
LIBRARY = DIRECTORY / 'library'
LIBRARY.mkdir(parents=True, exist_ok=True)
NAMES = ('CustomEditedOwner', 'CustomActiveOwner')
registry = Registry()
definition = registry.register(Definition('test.asset.custom', 'Custom', 'BOOL', True, 0, 1, 0, 1))
lifecycle.register()
bank = CurveBank(registry)
bank.register()
checks = []


def store(owner):
    return PersistentOwnerStore(owner, registry, curve_bank=bank)


def mapping(owner):
    target = store(owner)
    return bank.mapping(target, definition, bank.reference(target, definition, 'PRESSURE'))


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def asset_file(name):
    return LIBRARY / 'Saved/Brushes' / (name + '.asset.blend')


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier='CustomCurveTests',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    with bpy.data.libraries.load(str(asset_file(NAMES[0])), link=True) as (_, target):
        target.brushes = [NAMES[0]]
    brush = target.brushes[0]
    check('fresh asset custom selection', store(brush).read_stack(definition)[0].enabled is False)
    check('fresh asset custom payload', mapping(brush).curves[0].points[-1].location.y == .375)
    linked = store(brush)
    check('fresh linked fixture is read-only', brush.library is not None and not linked.editable)
    response = sampling.resolved_response(linked, definition, linked.read_stack(definition)[0].curve)
    check('linked read-only mapping can be sampled', abs(response.samples[-1] - .375) < 1e-6)
    for operation in (lambda: bank.initialize(linked, definition, 'SPEED'),
                      lambda: bank.remove(linked, definition, 'PRESSURE')):
        try:
            operation()
        except PropertyError:
            check('linked mutation rejected')
        else:
            raise AssertionError('Linked mutation succeeded')
else:
    baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(name='CustomCurveTests', directory=str(LIBRARY))
    bpy.ops.object.mode_set(mode='SCULPT')
    bpy.data.brushes['GenericLegacyV0'].asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier='Brush/GenericLegacyV0') == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference='CustomCurveTests', catalog_path='') == {'FINISHED'}
        brush = activate(name)
        value = store(brush)
        reference = bank.initialize(value, definition, 'PRESSURE')
        bank.mapping(value, definition, reference).curves[0].points[-1].location.y = .375
        value.write_stack(definition, (DeviceLayer(
            'PRESSURE', False, curve=bank.reference(value, definition, 'PRESSURE')),))
        assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited, active = activate(NAMES[0]), activate(NAMES[1])
    value = store(edited)
    for _ in range(5):
        value.write_stack(definition, value.read_stack(definition))
        bank.initialize(value, definition, 'PRESSURE')
        sampling.resolved_response(value, definition, value.read_stack(definition)[0].curve)
    check('custom reads and identical selection/initialize keep assets clean',
          not edited.has_unsaved_changes and not active.has_unsaved_changes)
    old = bank.reference(value, definition, 'PRESSURE')
    mapping(edited).curves[0].points[-1].location.y = .625
    check('inactive custom widget payload edit dirties only actual owner',
          edited.has_unsaved_changes and not active.has_unsaved_changes)
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    check('Revert restores custom payload and selection', mapping(reverted).curves[0].points[-1].location.y == .375
          and store(reverted).read_stack(definition)[0].enabled is False and not reverted.has_unsaved_changes)
    try:
        bank.mapping(value, definition, old)
    except PropertyError:
        check('Revert retires old custom reference and owner')
    else:
        raise AssertionError('Old owner survived Revert')
    active = activate(NAMES[1])
    parent = store(bpy.context.scene)
    ref = bank.initialize(parent, definition, 'PRESSURE')
    parent.write_stack(definition, (DeviceLayer('PRESSURE', curve=ref),))
    bank.mapping(parent, definition, ref).curves[0].points[-1].location.y = .125
    check('Scene custom edits keep assets clean', not reverted.has_unsaved_changes and not active.has_unsaved_changes)

bank.unregister()
lifecycle.unregister()
(DIRECTORY / (phase + '.json')).write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('CUSTOM_ASSETS_OK', phase, len(checks), flush=True)
