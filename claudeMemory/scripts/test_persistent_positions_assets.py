# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""External Brush placement no-op/dirty state, save/revert and rollback."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, Position, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-positions-assets'
LIBRARY = DIRECTORY / 'library'
LIBRARY.mkdir(parents=True, exist_ok=True)
NAMES = ('PositionsEditedOwner', 'PositionsActiveOwner')
registry = Registry()
DEFAULTS = (Position('HEADER', 10),)
CUSTOM = (Position('PANEL', -10), Position('MENU', 20))
definition = registry.register(Definition('test.positions', 'Positions', 'BOOL', True, 0, 1, 0, 1, positions=DEFAULTS))
checks = []
lifecycle.register()


def store(owner):
    return PersistentOwnerStore(owner, registry)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def asset_file(name):
    return LIBRARY / 'Saved/Brushes' / (name + '.asset.blend')


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier='PersistentPositionsTests',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    with bpy.data.libraries.load(str(asset_file(NAMES[0]))) as (_, target):
        target.brushes = [NAMES[0]]
    check('fresh asset explicit positions', store(target.brushes[0]).read_positions(definition) == CUSTOM)
else:
    baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(name='PersistentPositionsTests', directory=str(LIBRARY))
    bpy.ops.object.mode_set(mode='SCULPT')
    bpy.data.brushes['GenericLegacyV0'].asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier='Brush/GenericLegacyV0') == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference='PersistentPositionsTests', catalog_path='') == {'FINISHED'}
        brush = activate(name)
        store(brush).reset_positions(definition)
        assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited, active = activate(NAMES[0]), activate(NAMES[1])
    before = edited[ROOT].to_dict() if ROOT in edited else None
    store(edited).reset_positions(definition)
    check('untouched reset keeps asset data and both owners clean', not edited.has_unsaved_changes
          and not active.has_unsaved_changes and (edited[ROOT].to_dict() if ROOT in edited else None) == before)
    store(edited).write_positions(definition, ())
    check('explicit empty dirties only inactive owner', edited.has_unsaved_changes and not active.has_unsaved_changes)
    edited = activate(NAMES[0])
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    active = activate(NAMES[1])
    store(edited).write_positions(definition, ())
    check('repeated empty is clean', not edited.has_unsaved_changes and not active.has_unsaved_changes)
    store(edited).reset_positions(definition)
    check('reset of empty dirties actual owner', edited.has_unsaved_changes and not active.has_unsaved_changes)
    edited = activate(NAMES[0])
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    active = activate(NAMES[1])
    store(edited).reset_positions(definition)
    check('repeated reset is clean', not edited.has_unsaved_changes and not active.has_unsaved_changes)
    store(edited).write_positions(definition, CUSTOM)
    edited = activate(NAMES[0])
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited = activate(NAMES[0])
    old = store(edited)
    old.write_positions(definition, ())
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    check('Revert restores saved plural placements', store(reverted).read_positions(definition) == CUSTOM)
    try:
        old.read_positions(definition)
    except PropertyError:
        check('Revert retires placement store')
    else:
        raise AssertionError('Stale store survived')
    active = activate(NAMES[1])
    store(bpy.context.scene).write_positions(definition, CUSTOM)
    check('Scene placement leaves both assets clean',
          not reverted.has_unsaved_changes and not active.has_unsaved_changes)
    entry = reverted[ROOT]['records'][record_key(definition.identifier)]['positions'][record_key('MENU')]
    entry['sort_index'] = {'broken': True}
    before = reverted[ROOT].to_dict()
    try:
        store(reverted).write_positions(definition, (Position('PANEL', 99), CUSTOM[-1]))
    except PropertyError:
        pass
    else:
        raise AssertionError('Non-scalar late field accepted')
    check('late rollback preserves entire root and clean assets', reverted[ROOT].to_dict() == before
          and not reverted.has_unsaved_changes and not active.has_unsaved_changes)

lifecycle.unregister()
(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
print('PERSISTENT_POSITIONS_ASSETS_PASS', phase, len(checks), flush=True)
