# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generated stack persistence, atomic dirty state and external asset Revert."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-stacks-assets'
LIBRARY = DIRECTORY / 'library'
LIBRARY.mkdir(parents=True, exist_ok=True)
NAMES = ('StackEditedOwner', 'StackActiveOwner')
registry = Registry()
definition = registry.register(Definition('test.stack', 'Stack', 'BOOL', True, 0, 1, 0, 1))
original = (DeviceLayer('PRESSURE', False, 'ADD', .25, ResponseCurve('TWO_STEP', (.5, -2., 3.))),)
edited_stack = (DeviceLayer('SPEED'), DeviceLayer('PRESSURE'))
checks = []
lifecycle.register()
bpy.types.Brush.stack_test_curve = bpy.props.CurveMappingProperty()


def store(owner):
    return PersistentOwnerStore(owner, registry)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def asset_file(name):
    return LIBRARY / 'Saved/Brushes' / (name + '.asset.blend')


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier='PersistentStackTests',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    with bpy.data.libraries.load(str(asset_file(NAMES[0]))) as (_, target):
        target.brushes = [NAMES[0]]
    brush = target.brushes[0]
    check('fresh asset preserves disabled generated stack', store(brush).read_stack(definition) == original)
    check('fresh asset preserves unrelated owned curve', brush.stack_test_curve.curves[0].points[-1].location.y == .375)
else:
    baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(name='PersistentStackTests', directory=str(LIBRARY))
    bpy.ops.object.mode_set(mode='SCULPT')
    bpy.data.brushes['GenericLegacyV0'].asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier='Brush/GenericLegacyV0') == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference='PersistentStackTests', catalog_path='') == {'FINISHED'}
        brush = activate(name)
        store(brush).write_stack(definition, original)
        brush.curve_mapping_initialize('stack_test_curve').curves[0].points[-1].location.y = .375
        assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited, active = activate(NAMES[0]), activate(NAMES[1])
    value = store(edited)
    key = edited.stack_test_curve.curve_mapping_cache_key()
    for _ in range(5):
        assert value.read_stack(definition) == original
        value.write_stack(definition, original)
    check('reads and identical writes keep both assets clean',
          not edited.has_unsaved_changes and not active.has_unsaved_changes)
    try:
        value.write_stack(definition, (original[0], original[0]))
    except PropertyError:
        pass
    else:
        raise AssertionError('Duplicate accepted')
    check('rejected duplicate leaves both clean', not edited.has_unsaved_changes and not active.has_unsaved_changes)
    value.write_stack(definition, edited_stack)
    check('inactive stack edit dirties only actual owner',
          edited.has_unsaved_changes and not active.has_unsaved_changes)
    check('stack publication preserves owned curve runtime key',
          edited.stack_test_curve.curve_mapping_cache_key() == key)
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    check('Revert restores saved disabled generated stack', store(reverted).read_stack(definition) == original
          and not reverted.has_unsaved_changes)
    try:
        value.read_stack(definition)
    except PropertyError:
        check('Revert retires old stack store')
    else:
        raise AssertionError('Old stack store survived Revert')
    active = activate(NAMES[1])
    store(bpy.context.scene).write_stack(definition, edited_stack)
    check('Scene stack write keeps both assets clean',
          not reverted.has_unsaved_changes and not active.has_unsaved_changes)
    # Raw fixture corruption does not notify; the rejected transaction must not either.
    record = reverted[ROOT]['records'][record_key(definition.identifier)]
    record['layers']['PRESSURE']['factor'] = {'broken': True}
    before = reverted[ROOT].to_dict()
    try:
        store(reverted).write_stack(definition, edited_stack)
    except PropertyError:
        pass
    else:
        raise AssertionError('Non-scalar accepted')
    check('late transaction failure preserves root and clean assets', before == reverted[ROOT].to_dict()
          and not reverted.has_unsaved_changes and not active.has_unsaved_changes)

del bpy.types.Brush.stack_test_curve
lifecycle.unregister()
(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
print('PERSISTENT_STACKS_ASSETS_PASS', phase, len(checks), flush=True)
