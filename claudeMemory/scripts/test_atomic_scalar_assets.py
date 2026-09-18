# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Atomic scalar authoring on external assets and rejected native API owners."""
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
_, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-atomic-assets'
LIBRARY = DIRECTORY / 'library'
LIBRARY.mkdir(parents=True, exist_ok=True)
NAMES = ('AtomicEditedOwner', 'AtomicActiveOwner')
registry = Registry()
definition = registry.register(Definition('test.atomic', 'Atomic', 'FLOAT32', .5, 0, 10, 0, 1))
registry.register(native.STRENGTH_DEFINITION)
checks = []
lifecycle.register()
bpy.types.Brush.atomic_test_curve = bpy.props.CurveMappingProperty()


def store(owner):
    return PersistentOwnerStore(owner, registry)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def reject(name, function):
    try:
        function()
    except (PermissionError, ValueError, TypeError, ReferenceError):
        checks.append(name)
    else:
        raise AssertionError('Accepted ' + name)


def asset_file(name):
    return LIBRARY / 'Saved/Brushes' / (name + '.asset.blend')


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier='AtomicScalarTests',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    with bpy.data.libraries.load(str(asset_file(NAMES[0]))) as (_, target):
        target.brushes = [NAMES[0]]
    brush = target.brushes[0]
    check('fresh external asset scalar readback', store(brush).read_value(definition).value == .375)
    check('fresh external asset curve readback', brush.atomic_test_curve.curves[0].points[-1].location.y == .375)
else:
    baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(name='AtomicScalarTests', directory=str(LIBRARY))
    bpy.ops.object.mode_set(mode='SCULPT')
    source = bpy.data.brushes['GenericLegacyV0']
    source.asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier='Brush/GenericLegacyV0') == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference='AtomicScalarTests', catalog_path='') == {'FINISHED'}
        brush = activate(name)
        store(brush).write_value(definition, .375)
        brush.curve_mapping_initialize('atomic_test_curve').curves[0].points[-1].location.y = .375
        assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited = activate(NAMES[0])
    active = activate(NAMES[1])
    value = store(edited)
    key = edited.atomic_test_curve.curve_mapping_cache_key()
    for _ in range(8):
        value.write_value(definition, .375 + 1e-10)
        assert value.read_value(definition).value == .375
        value.metadata(definition.identifier)
    check('generic reads and quantized no-op writes keep both assets clean',
          not edited.has_unsaved_changes and not active.has_unsaved_changes)
    before = edited[ROOT].to_dict()
    reject('later invalid UI batch leaves asset clean', lambda: edited.id_properties_update_atomic(ROOT, (
        ('SET', ('would_be_added',), 7, None), ('SET', ('bad_metadata',), .5, {'default': 'invalid'}))))
    check('failure preserves root and both dirty flags', before == edited[ROOT].to_dict()
          and not edited.has_unsaved_changes and not active.has_unsaved_changes)
    value.write_value(definition, .75)
    check('inactive generic Brush edit dirties only its owner', edited.has_unsaved_changes and not active.has_unsaved_changes)
    check('metadata publication preserves owned curve runtime identity',
          edited.atomic_test_curve.curve_mapping_cache_key() == key)
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    check('generic Save .375 edit .75 Revert .375', store(reverted).read_value(definition).value == .375
          and not reverted.has_unsaved_changes)
    reject('asset Revert retires old store', lambda: value.read_value(definition))
    active = activate(NAMES[1])
    scene = bpy.context.scene.copy()
    store(scene).write_value(definition, .625)
    store(scene).write_unified(definition.identifier, True)
    check('generic Scene writes keep both assets clean', not reverted.has_unsaved_changes and not active.has_unsaved_changes)
    missing_id = 'sculptcore.brush.strength'
    native_before = reverted.strength
    native_flag = reverted.use_unified_strength
    store(reverted).write_mode(missing_id, 'NEVER')
    check('persistent native policy dirties owner while preserving native values', reverted.has_unsaved_changes
          and reverted.strength == native_before and reverted.use_unified_strength == native_flag
          and not active.has_unsaved_changes)
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    active = activate(NAMES[1])

    fixture = bpy.data.brushes.new('AtomicLinkedFixture', mode='SCULPT')
    linked_file = DIRECTORY / 'linked.blend'
    bpy.data.libraries.write(str(linked_file), {fixture}, fake_user=True)
    with bpy.data.libraries.load(str(linked_file), link=True) as (_, target):
        target.brushes = [fixture.name]
    linked = target.brushes[0]
    reject('native API rejects read-only linked no-op', lambda: linked.id_properties_update_atomic(ROOT, ()))
    bpy.context.scene['atomic_link'] = linked
    override = linked.override_create(remap_local_usages=False)
    assert override is not None
    reject('native API rejects override no-op', lambda: override.id_properties_update_atomic(ROOT, ()))
    evaluated = bpy.context.scene.evaluated_get(bpy.context.evaluated_depsgraph_get())
    reject('native API rejects evaluated no-op', lambda: evaluated.id_properties_update_atomic(ROOT, ()))
    dead = bpy.data.brushes.new('AtomicDeadFixture', mode='SCULPT')
    retained = dead.id_properties_update_atomic
    bpy.data.brushes.remove(dead)
    reject('retained native method rejects deleted owner', lambda: retained(ROOT, ()))
    check('owner rejection leaves both assets clean', not reverted.has_unsaved_changes and not active.has_unsaved_changes)

del bpy.types.Brush.atomic_test_curve
lifecycle.unregister()
(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
print('ATOMIC_SCALAR_ASSETS_PASS', phase, len(checks), flush=True)
