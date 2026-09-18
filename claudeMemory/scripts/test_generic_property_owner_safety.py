# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual native owner eligibility, clean no-ops, asset persistence and load lifetime."""
import json
import builtins
from dataclasses import replace
from pathlib import Path
import sys
import threading
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package

package, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import PropertyError

ROOT = Path(__file__).resolve().parents[1] / 'tests/plan4-owner-assets'
LIBRARY = ROOT / 'library'
LIBRARY.mkdir(parents=True, exist_ok=True)
NAMES = ('Plan4EditedOwner', 'Plan4ActiveOwner')
KEY = native.STRENGTH
DEFINITION = native.STRENGTH_DEFINITION
checks = []


def check(label, condition):
    assert condition, label
    checks.append(label)


def reject(label, operation):
    try:
        operation()
    except PropertyError:
        checks.append(label)
    else:
        raise AssertionError('Accepted: ' + label)


def store(owner):
    return native.NativeStrengthOwner(owner, epoch=1)


def asset_file(name):
    return LIBRARY / 'Saved/Brushes' / (name + '.asset.blend')


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier='Plan4OwnerSafety',
        relative_asset_identifier='Saved/Brushes/{0}.asset.blend/Brush/{0}'.format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


def stale_operations(value):
    return (
        lambda: value.identity,
        lambda: value.editable,
        lambda: value.capability(DEFINITION),
        lambda: value.read_value(DEFINITION),
        lambda: value.value_mode(KEY),
        lambda: value.unified(KEY),
        lambda: value.inherits_stack(KEY),
        lambda: value.write_value(DEFINITION, .375),
        lambda: value.write_mode(KEY, 'UNIFIED'),
        lambda: value.write_stack_inheritance(KEY, False),
        lambda: value.write_unified(KEY, False),
    )


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
lifecycle.register()
if phase == 'verify':
    with bpy.data.libraries.load(str(asset_file(NAMES[0]))) as (_, target):
        target.brushes = [NAMES[0]]
    check('fresh process native asset readback', store(target.brushes[0]).read_value(DEFINITION).value == .375)
else:
    baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(name='Plan4OwnerSafety', directory=str(LIBRARY))
    bpy.ops.object.mode_set(mode='SCULPT')
    source = bpy.data.brushes['GenericLegacyV0']
    source.asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier='Brush/GenericLegacyV0') == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference='Plan4OwnerSafety', catalog_path='') == {'FINISHED'}
        brush = activate(name)
        brush.strength = .375
        assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited = activate(NAMES[0])
    active = activate(NAMES[1])
    local = store(edited)
    check('both external assets start clean', not edited.has_unsaved_changes and not active.has_unsaved_changes)
    before = (tuple(edited.keys()), tuple(active.keys()))
    for _ in range(10):
        assert local.read_value(DEFINITION).value == .375
        local.write_value(DEFINITION, .375 + 1e-10)
    check('quantized native no-op and repeated reads stay clean',
          not edited.has_unsaved_changes and not active.has_unsaved_changes
          and before == (tuple(edited.keys()), tuple(active.keys())))
    for bad in (True, float('nan'), -1, 11):
        reject('invalid native value ' + repr(bad), lambda bad=bad: local.write_value(DEFINITION, bad))
    reject('widened definition cannot bypass authoritative RNA bounds',
           lambda: local.write_value(replace(DEFINITION, maximum=100), 11))
    check('invalid native writes keep both assets clean', not edited.has_unsaved_changes and not active.has_unsaved_changes)
    local.write_value(DEFINITION, .75)
    check('inactive native Brush edit dirties only owner', edited.has_unsaved_changes and not active.has_unsaved_changes
          and edited.strength == .75 and active.strength == .375)
    activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    edited = bpy.context.tool_settings.sculpt.brush
    check('native asset revert restores authoritative value', store(edited).read_value(DEFINITION).value == .375
          and not edited.has_unsaved_changes)
    reject('reverted owner invalidates its old store', lambda: local.read_value(DEFINITION))
    active = activate(NAMES[1])
    current = bpy.context.scene
    inactive = current.copy()
    parent = store(inactive)
    settings = inactive.tool_settings.sculpt.unified_paint_settings
    original_strength = current.tool_settings.sculpt.unified_paint_settings.strength
    parent.write_value(DEFINITION, .625)
    parent.write_unified(KEY, True)
    parent.write_value(DEFINITION, .625)
    parent.write_unified(KEY, True)
    check('inactive Scene native edits preserve active Scene and clean assets',
          settings.strength == .625 and settings.use_unified_strength
          and current.tool_settings.sculpt.unified_paint_settings.strength == original_strength
          and not edited.has_unsaved_changes and not active.has_unsaved_changes)

    # A real linked Brush and a real library override, including unchanged requests.
    fixture = bpy.data.brushes.new('Plan4Linked', mode='SCULPT')
    fixture.strength = .375
    linked_path = ROOT / 'linked.blend'
    bpy.data.libraries.write(str(linked_path), {fixture}, fake_user=True)
    with bpy.data.libraries.load(str(linked_path), link=True) as (_, target):
        target.brushes = [fixture.name]
    linked = target.brushes[0]
    linked_store = store(linked)
    check('linked native owner can be read', linked_store.read_value(DEFINITION).value == .375)
    reject('linked no-op writes still reject', lambda: linked_store.write_value(DEFINITION, .375))
    reject('linked policy writes reject', lambda: linked_store.write_mode(KEY, 'NEVER'))
    # A direct local reference promotes the loaded, initially unused linked ID
    # to external, which is required by Blender's override creation API.
    current['plan4_linked_fixture'] = linked
    override = linked.override_create(remap_local_usages=False)
    assert override is not None and override.override_library is not None
    override_store = store(override)
    reject('override no-op writes still reject', lambda: override_store.write_value(DEFINITION, .375))
    reject('override policy writes reject', lambda: override_store.write_mode(KEY, 'NEVER'))
    check('rejected linked/override requests preserve contents', linked.strength == .375 and override.strength == .375)
    evaluated = current.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert evaluated.is_evaluated
    reject('evaluated Scene cannot construct store', lambda: store(evaluated))
    doomed = bpy.data.brushes.new('Plan4Deleted', mode='SCULPT')
    dead_store = store(doomed)
    bpy.data.brushes.remove(doomed)
    replacement = bpy.data.brushes.new('Plan4Deleted', mode='SCULPT')
    for index, operation in enumerate(stale_operations(dead_store)):
        reject('deleted/replaced owner rejects operation ' + str(index), operation)
    check('replacement owner remains unchanged', replacement.strength == 1.0)

    # Checking the thread must precede all RNA access, including store construction.
    errors = []
    current_store = store(active)

    def wrong_thread():
        for operation in (lambda: store(active), lambda: current_store.read_value(DEFINITION),
                          lambda: current_store.write_value(DEFINITION, .375)):
            try:
                operation()
            except PropertyError as error:
                errors.append(str(error))

    thread = threading.Thread(target=wrong_thread)
    thread.start()
    thread.join()
    check('worker thread rejected before RNA access', len(errors) == 3 and all('main thread' in error for error in errors))
    identity = current_store.identity
    lifecycle.register()
    check('register is idempotent', current_store.identity == identity
          and all(callbacks.count(lifecycle._invalidate) == 1 for callbacks in lifecycle._handler_lists))
    handler_lists = lifecycle._handler_lists
    lifecycle.unregister()
    check('unregister removes all lifecycle callbacks',
          all(lifecycle._invalidate not in callbacks for callbacks in handler_lists))
    reject('unregister invalidates stores', lambda: current_store.read_value(DEFINITION))
    original_import = builtins.__import__

    def without_engine(name, *args, **kwargs):
        if name.split('.')[0] in ('sculptcore', 'engine', 'sculptcore_addon'):
            raise AssertionError('Lifecycle registration imported the engine: ' + name)
        return original_import(name, *args, **kwargs)

    with patch('builtins.__import__', without_engine):
        lifecycle.register()
    checks.append('lifecycle registration requires no engine imports')
    reject('re-register never revives old store', lambda: current_store.read_value(DEFINITION))
    check('fresh store after register works', store(active).read_value(DEFINITION).value == .375)

    # Keep a store made by a later pre-handler: post invalidation must retire it too.
    before_load = store(active)
    pre_stores = []

    def capture_before_load(_):
        pre_stores.append(store(bpy.context.scene))

    bpy.app.handlers.load_pre.append(capture_before_load)
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    reject('file load invalidates pre-existing store', lambda: before_load.read_value(DEFINITION))
    assert len(pre_stores) == 1
    reject('file load invalidates store created inside pre-handler', lambda: pre_stores[0].value_mode(KEY))
    check('persistent lifecycle survives load', store(bpy.context.scene).identity is not None)
    failed_load_store = store(bpy.context.scene)
    try:
        bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'not-present.blend'))
    except RuntimeError:
        pass
    reject('failed file load also invalidates old stores', lambda: failed_load_store.value_mode(KEY))
    check('new store works after failed load', store(bpy.context.scene).identity is not None)

lifecycle.unregister()
(ROOT / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
print('PLAN4_OWNER_SAFETY_PASS', phase, len(checks), flush=True)
