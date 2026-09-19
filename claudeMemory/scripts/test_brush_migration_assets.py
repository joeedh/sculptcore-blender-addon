# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Production migration, owned curves, placement and save-reminder asset lifecycle."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import addon_utils
import bpy
from sculptcore_addon.brush_properties import authoring, migration, resolver
from sculptcore_addon.brush_properties.registry import DeviceLayer, Position, PropertyError, ResponseCurve
from sculptcore_addon.brush_properties.storage import ROOT
from brush_save_reminder import changes, diff

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/brush-migration-assets'
LIBRARY = DIRECTORY / 'library'
ASSETS = LIBRARY / 'Saved/Brushes'
ASSETS.mkdir(parents=True, exist_ok=True)
phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'create'
name = 'GenericLegacyV0'
path = ASSETS / (name + '.asset.blend')
saved_name = 'GenericMigratedV1'
saved_path = ASSETS / (saved_name + '.asset.blend')
identifier = 'sculptcore.kernel.kelvinlet.nu'
definition = authoring.registry.get(identifier)
checks = []


def check(label, value):
    assert value, label
    checks.append(label)


def reject(label, operation):
    try:
        operation()
    except PropertyError:
        checks.append(label)
    else:
        raise AssertionError(label)


def activate(asset_name):
    assert bpy.ops.brush.asset_activate(asset_library_type='CUSTOM', asset_library_identifier='MigrationTests',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(asset_name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


def curve(owner):
    store = authoring.store(owner)
    return authoring.curve_bank.mapping(store, definition, authoring.curve_bank.reference(store, definition, 'SPEED'))


if phase == 'disabled':
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'new.blend'))
    addon_utils.disable('sculptcore_addon', default_set=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'disabled.blend'))
    addon_utils.enable('sculptcore_addon', default_set=False)
    check('re-enable restores custom mapping declaration', curve(bpy.data.brushes['MigrationLocalCopy']).curves[0].points[-1].location.y == .625)
elif phase == 'verify':
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'disabled.blend'))
    owner = bpy.data.brushes['MigrationLocalCopy']
    check('addon-disabled resave retains owned mapping', curve(owner).curves[0].points[-1].location.y == .625)
    check('addon-disabled resave retains saved placement', authoring.store(owner).read_positions(definition)
          == (Position('BRUSH_SETTINGS', 4), Position('CONTEXT_MENU', 7)))
    with bpy.data.libraries.load(str(saved_path), link=True) as (_, target):
        target.brushes = [saved_name]
    linked = target.brushes[0]
    check('fresh linked custom mapping independent of local copy', curve(linked).curves[0].points[-1].location.y == .375)
    check('fresh linked generic value', authoring.store(linked).read_value(definition).value == .25)
    with bpy.data.libraries.load(str(path), link=True) as (_, target):
        target.brushes = [name]
    check('explicitly saved old asset reloads migrated', migration.FIELD in target.brushes[0][ROOT]
          and authoring.store(target.brushes[0]).read_value(definition).value == .25)
    reject('linked generic edit requires editable copy', lambda: authoring.store(linked).write_value(definition, .125))
    reject('linked curve edit requires editable copy', lambda: authoring.curve_bank.initialize(authoring.store(linked), definition, 'TILT_X'))
    before = linked.has_unsaved_changes
    authoring.refresh_manifest(())
    result = resolver.resolve(authoring.registry, identifier, authoring.store(linked))
    check('missing kernel preserves authored value and reports unavailable', result.value == .25
          and 'execution:kernel_unavailable' in result.diagnostics and linked.has_unsaved_changes == before)
else:
    source = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/library/Saved/Brushes/GenericLegacyV0.asset.blend'
    shutil.copyfile(source, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    bpy.context.preferences.filepaths.asset_libraries.new(name='MigrationTests', directory=str(LIBRARY))
    bpy.context.scene.sculptcore_generic_properties = True
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    owner = activate(name)
    check('late legacy activation starts unmigrated', ROOT not in owner)
    migration.activate(bpy.context)
    check('late active asset migrates lazily', migration.FIELD in owner[ROOT])
    check('migration leaves library unchanged', hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    check('migration dirties only active asset for explicit save', owner in changes.unsaved_brushes())
    report = diff.diff_all(changes.describe_all([owner]))[owner.name]
    check('standalone reminder reports generic changes', report.available and any('Custom property' in row[0] for row in report.rows))
    store = authoring.store(owner)
    store.write_value(definition, .25)
    reference = authoring.curve_bank.initialize(store, definition, 'SPEED')
    curve(owner).curves[0].points[-1].location.y = .375
    reference = authoring.curve_bank.reference(store, definition, 'SPEED')
    store.write_stack(definition, (DeviceLayer('SPEED', curve=reference), DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE'))))
    store.write_positions(definition, (Position('BRUSH_SETTINGS', 4), Position('CONTEXT_MENU', 7)))
    bpy.ops.brush.asset_save_as(name=saved_name, asset_library_reference='MigrationTests', catalog_path='')
    owner = activate(saved_name)
    check('new external asset has independent curve', curve(owner).curves[0].points[-1].location.y == .375)
    copy = owner.copy()
    copy.name = 'MigrationLocalCopy'
    copy.use_fake_user = True
    curve(copy).curves[0].points[-1].location.y = .625
    check('Brush.copy curve independent', curve(owner).curves[0].points[-1].location.y == .375)
    curve(owner).curves[0].points[-1].location.y = .75
    check('nested owned curve dirties correct asset', owner in changes.unsaved_brushes())
    report = diff.diff_all(changes.describe_all([owner]))[owner.name]
    check('standalone reminder reports custom curve edits', report.available and any('(curve)' in row[0] for row in report.rows))
    bpy.ops.brush.asset_revert()
    owner = bpy.context.tool_settings.sculpt.brush
    check('Revert restores custom curve and clean status', curve(owner).curves[0].points[-1].location.y == .375 and not owner.has_unsaved_changes)
    check('Revert retains saved independent preset', authoring.store(owner).read_stack(definition)[1].curve.preset == 'SQUARE')
    bpy.ops.brush.asset_save()
    check('explicit asset save leaves frozen library untouched', hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    old_asset = activate(name)
    bpy.ops.brush.asset_save()
    check('explicit old-asset save persists migration', hashlib.sha256(path.read_bytes()).hexdigest() != digest
          and not old_asset.has_unsaved_changes)
    bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
        relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
    essential = bpy.context.tool_settings.sculpt.brush
    migration.activate(bpy.context)
    check('Essentials saving requires a copy', changes.describe(essential)['disposition'] == changes.SAVE_AS_COPY)
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'new.blend'))

(DIRECTORY / (phase + '.json')).write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('BRUSH_MIGRATION_ASSETS_OK', phase, len(checks), flush=True)
