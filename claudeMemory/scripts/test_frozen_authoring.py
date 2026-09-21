# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Production catalogue and frozen legacy reads with engine entry points disabled."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import bpy
import sculptcore_addon as addon
from sculptcore_addon.brush_properties import authoring, capabilities, legacy, migration
from sculptcore_addon.brush_properties.curves import declaration_name
from sculptcore_addon.brush_properties.registry import DeviceLayer, PropertyError, Registry, scalar
from sculptcore_addon.brush_properties.storage import ROOT, PersistentOwnerStore
from sculptcore_addon.brush_properties.resolver import resolve

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-frozen'
DIRECTORY.mkdir(parents=True, exist_ok=True)
checks = []


def check(name, condition=True):
    assert condition, name
    checks.append(name)
    print('FROZEN_CHECK ' + name, flush=True)


def reject(name, action, types=(PropertyError,)):
    try:
        action()
    except types:
        check(name)
    else:
        raise AssertionError('Accepted: ' + name)


with patch.object(bpy.props, 'CurveMappingProperty', None):
    reject('missing owned-curve host capability diagnosed', capabilities.require_host, (RuntimeError,))
with patch.object(capabilities, 'ENGINE_EXPORTS', ('DeliberatelyMissingTypedExport',)):
    reject('missing typed-engine capability diagnosed', capabilities.verify_roundtrip, (RuntimeError,))


baseline = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/legacy.blend'
bpy.ops.wm.open_mainfile(filepath=str(baseline))
brush = bpy.data.brushes['GenericLegacyV0']
target = authoring.store(brush)
expected = json.loads(baseline.with_name('baseline.json').read_text())['generated']
check('frozen association count', len(legacy.DEFINITIONS) == 7 and len(set(v[1] for v in legacy.ASSOCIATIONS.values())) == 5)
before = {name: brush.system_property_scalar(('sculptcore', name)) for name in expected}
for definition in legacy.DEFINITIONS:
    kernel, name = legacy.ASSOCIATIONS[definition.identifier]
    value = target.read_value(definition)
    check('legacy presence ' + definition.identifier, value.present == expected[name]['set'])
    check('legacy effective ' + definition.identifier,
          resolve(authoring.registry, definition.identifier, target).value == expected[name]['value'])
    if not definition.dynamic:
        reject('static stack rejected ' + definition.identifier,
               lambda d=definition: target.write_stack(d, (DeviceLayer('PRESSURE'),)))
        check('no static curve declaration ' + definition.identifier,
              not hasattr(bpy.types.Brush, declaration_name(definition.identifier, 'PRESSURE')))
check('repeated reads leave raw values unchanged', before == {
    name: brush.system_property_scalar(('sculptcore', name)) for name in expected})
check('legacy read creates no generic root', ROOT not in brush)

# Migration extends this frozen fixture, rather than creating another plan suite.
migrated = brush.copy()
migrated.name = 'FrozenMigratedV1'
migrated.use_fake_user = True
migrated_store = authoring.store(migrated)
native_before = tuple(migrated_store.read_value(item) for item in authoring.NATIVE_DEFINITIONS)
native_flags = ('use_pressure_strength', 'use_pressure_size', 'sculptcore_use_pressure_strength',
                'sculptcore_use_pressure_size', 'use_unified_strength', 'use_unified_size')
flags_before = tuple(getattr(migrated, name) for name in native_flags)
curve_paths = ('curve_strength', 'curve_size', 'curve_distance_falloff', 'mesh_automasking_settings.cavity_curve')
curves_before = tuple(migrated.authoring_native_curve_key(path) for path in curve_paths)
scene_before = tuple(authoring.store(bpy.context.scene).read_value(item) for item in authoring.NATIVE_DEFINITIONS)
unified = bpy.context.scene.tool_settings.sculpt.unified_paint_settings
unified_before = (unified.use_unified_strength, unified.use_unified_size)
with patch.object(addon.engine, 'capi', side_effect=AssertionError('Migration cannot consult a DLL')), \
        patch.object(addon.engine_props, '_walk_manifests', side_effect=AssertionError('No live defaults')):
    check('migration imports frozen names', migration.migrate(migrated_store) == tuple(migration.BY_NAME))
for definition in legacy.DEFINITIONS:
    name = legacy.ASSOCIATIONS[definition.identifier][1]
    source = migrated_store.read_value(definition)
    check('migration authored presence ' + definition.identifier, source.present == expected[name]['set'])
    check('migration frozen value ' + definition.identifier,
          resolve(authoring.registry, definition.identifier, migrated_store).value == expected[name]['value'])
    if source.present:
        check('migration uses generic storage ' + definition.identifier, source.source == 'GENERIC')
check('migration retains native values', native_before == tuple(
    migrated_store.read_value(item) for item in authoring.NATIVE_DEFINITIONS))
check('migration retains pressure and native unified flags', flags_before == tuple(
    getattr(migrated, name) for name in native_flags))
check('migration retains native curves', curves_before == tuple(
    migrated.authoring_native_curve_key(path) for path in curve_paths))
check('migration leaves Scene values and policy unchanged', scene_before == tuple(
    authoring.store(bpy.context.scene).read_value(item) for item in authoring.NATIVE_DEFINITIONS)
    and unified_before == (unified.use_unified_strength, unified.use_unified_size))
check('migration preserves rollback raw data', before == {
    name: migrated.system_property_scalar(('sculptcore', name)) for name in expected})
token = migrated.authoring_edit_begin(undo=False)
check('migration repeat has no pending names', migration.migrate(migrated_store) == ())
check('migration repeat makes no authoring change', not migrated.authoring_edit_commit(token))

fanout = tuple(item for item in legacy.DEFINITIONS if item.identifier.endswith('.planeSide'))
migrated_store.write_value(fanout[0], -.25)
migrated.sculptcore['planeSide'] = .5
check('legacy changed name synchronized once', migration.migrate(migrated_store) == ('planeSide',))
check('legacy raw write fans out even after divergence', all(
    migrated_store.read_value(item).value == .5 for item in fanout))
del migrated.sculptcore['planeSide']
check('legacy unset synchronized', migration.migrate(migrated_store) == ('planeSide',))
check('legacy unset restores frozen defaults and presence', all(
    not migrated_store.read_value(item).present
    and resolve(authoring.registry, item.identifier, migrated_store).value == item.default for item in fanout))

mixed = brush.copy()
mixed.name = 'FrozenMixedMigration'
mixed.use_fake_user = True
mixed_store = authoring.store(mixed)
mixed_store.write_value(fanout[0], -.75)
mixed_store.write_positions(fanout[0], ())
del mixed[ROOT][migration.FIELD]  # Simulate a v1 record authored before migration shipped.
mixed[ROOT]['opaque'] = {'future': b'keep'}
mixed.sculptcore['unknown_legacy'] = {'future': [1, 2]}
check('mixed initial migration runs', bool(migration.migrate(mixed_store)))
check('mixed migration preserves independent value and placement', mixed_store.read_value(fanout[0]).value == -.75
      and mixed_store.read_positions(fanout[0]) == ())
check('migration preserves unknown generic and legacy data', mixed[ROOT]['opaque']['future'] == b'keep'
      and list(mixed.sculptcore['unknown_legacy']['future']) == [1, 2])

# Validate the entire candidate before publication, including a bad last source.
mixed.sculptcore['mu'] = 2.0
del mixed.sculptcore['projection']
mixed.sculptcore['projection'] = 'invalid'
saved = mixed[ROOT].to_dict()
reject('malformed late legacy source rejects migration', lambda: migration.migrate(mixed_store))
check('migration failure publishes nothing', mixed[ROOT].to_dict() == saved)
del mixed.sculptcore['projection']
mixed.sculptcore['projection'] = 0.0
migration.migrate(mixed_store)
for field, version in (('schema_version', 99), (migration.FIELD, 99)):
    if field == migration.FIELD:
        mixed[ROOT][field]['version'] = version
    else:
        mixed[ROOT][field] = version
    saved = mixed[ROOT].to_dict()
    reject('newer migration data rejected ' + field, lambda: migration.migrate(mixed_store))
    check('newer migration data unchanged ' + field, mixed[ROOT].to_dict() == saved)
    if field == migration.FIELD:
        mixed[ROOT][field]['version'] = migration.VERSION
    else:
        mixed[ROOT][field] = 1
reject('migration never writes Scene', lambda: migration.migrate(authoring.store(bpy.context.scene)))

mixed.sculpt_brush_type = 'CLAY'
mixed.sculptcore.planeSide = .625
check('public RNA assignment fans out immediately', all(mixed_store.read_value(item).value == .625 for item in fanout))
mixed_store.write_value(fanout[0], .125)
check('public RNA reads active kernel independent value', mixed.sculptcore.planeSide == .125)
mixed.sculptcore.planeSide = .625
check('same raw RNA assignment reunifies diverged values', all(
    mixed_store.read_value(item).value == .625 for item in fanout))
mixed.sculptcore.property_unset('planeSide')
check('RNA unset overlays frozen default without draw mutation', all(
    not mixed_store.read_value(item).present for item in fanout))
mixed_store.write_value(fanout[0], .125)
check('generic edit atomically synchronizes pending unset', mixed_store.read_value(fanout[0]).value == .125
      and all(not mixed_store.read_value(item).present for item in fanout[1:]))
reject('Brush cannot own a legacy driver', lambda: mixed.driver_add('sculptcore.planeSide'), (TypeError, RuntimeError))
reject('Brush cannot own legacy keyframes', lambda: mixed.keyframe_insert('sculptcore.planeSide'), (TypeError, RuntimeError))
driver_scene = bpy.context.scene
driver_scene['legacy_alias_probe'] = 0.0
driver = driver_scene.driver_add('["legacy_alias_probe"]').driver
variable = driver.variables.new()
variable.name = 'value'
variable.type = 'SINGLE_PROP'
variable.targets[0].id_type = 'BRUSH'
variable.targets[0].id = mixed
variable.targets[0].data_path = 'sculptcore.planeSide'
driver.expression = 'value * 2'
driver_scene.frame_set(2)
check('driver variable reads preserved public RNA path', driver.is_valid
      and abs(driver_scene['legacy_alias_probe'] - .25) < 1e-7)
mixed_store.write_value(fanout[0], .375)
driver_scene.frame_set(3)
check('generic edits refresh driver variables', driver.is_valid
      and abs(driver_scene['legacy_alias_probe'] - .75) < 1e-7)
driver_scene.driver_remove('["legacy_alias_probe"]')
del driver_scene['legacy_alias_probe']

# Simulate a replacement DLL registering different RNA defaults. Reading those
# defaults creates ghost properties; they must not become authored legacy data.
addon.engine_props.unregister()
try:
    changed_rows = [(name, .25, False, 0.0, 1.0, -1, 0) for name in migration.BY_NAME]
    with patch.object(addon.engine_props, '_walk_manifests', return_value={'KELVINLET': changed_rows}):
        addon.engine_props.register()
    changed_defaults = bpy.data.brushes.new('FrozenChangedDefaults', mode='SCULPT')
    changed_defaults.use_fake_user = True
    check('replacement manifest cannot change public RNA defaults', changed_defaults.sculptcore.mu == 1.0
          and changed_defaults.sculptcore.planeSide == 1.0)
    changed_store = authoring.store(changed_defaults)
    migration.migrate(changed_store)
    check('changed DLL defaults do not become authored', all(
        not changed_store.read_value(item).present for item in legacy.DEFINITIONS))
    check('changed DLL cannot rewrite frozen defaults', all(
        resolve(authoring.registry, item.identifier, changed_store).value == item.default
        for item in legacy.DEFINITIONS))
finally:
    addon.engine_props.unregister()
    addon.engine_props.register()

nu = authoring.registry.get('sculptcore.kernel.kelvinlet.nu')
for changes in (dict(default=.1), dict(maximum=10), dict(dynamic=False), dict(owners=frozenset(('BRUSH',))),
                dict(scalar_type='INT32', default=0, minimum=0, maximum=1, soft_minimum=0, soft_maximum=1)):
    conflicting = Registry()
    wrong = conflicting.register(replace(nu, **changes))
    bad_store = PersistentOwnerStore(brush, conflicting)
    reject('reserved frozen contract ' + str(changes), lambda: bad_store.write_value(wrong, wrong.default))
target.write_positions(nu, ())
check('metadata edit migrates authored legacy', target.read_value(nu).source == 'GENERIC')
plane = [item for item in legacy.DEFINITIONS if item.identifier.endswith('.planeSide')]
target.write_value(plane[0], -.25)
check('one fanout override independent', target.read_value(plane[0]).value == -.25
      and all(not target.read_value(item).present for item in plane[1:]))
brush.sculptcore['planeSide'] = .5
check('raw legacy script change overlays every fanout', all(target.read_value(item).value == .5 for item in plane))
brush.sculptcore['nu'] = .4
check('raw double follows native float conversion', target.read_value(nu).value == brush.sculptcore.nu)
double_brush = bpy.data.brushes.new('FrozenDoubleLegacy', mode='SCULPT')
double_brush.use_fake_user = True
double_brush.sculptcore['nu'] = .4
check('actual DOUBLE fixture', double_brush.system_property_scalar(('sculptcore', 'nu'))[1] == 'DOUBLE')
check('noncanonical DOUBLE converted once', authoring.store(double_brush).read_value(nu).value == double_brush.sculptcore.nu)
double_brush.sculptcore['nu'] = nu.maximum + 1e-10
check('DOUBLE boundary rounding matches native', authoring.store(double_brush).read_value(nu).value == nu.maximum)
target.write_value(nu, .3)
check('generic explicit value wins', target.read_value(nu).value == scalar('FLOAT32', .3))
scene = bpy.data.scenes.new('FrozenSwitchFirst')
parent = authoring.store(scene)
check('generic release default nonallocating', parent.feature_enabled() is True and ROOT not in scene)
parent.write_feature_enabled(True)
check('true no-op nonallocating', ROOT not in scene)
parent.write_feature_enabled(False)
check('saved explicit opt-out honored', not parent.feature_enabled())
parent.write_feature_enabled(True)
check('flag-first root valid', parent.feature_enabled() and not parent.read_value(nu).present
      and parent.read_stack(nu) == ())
parent.write_value(nu, .2)
parent.write_stack(nu, (DeviceLayer('PRESSURE'),))
parent.write_feature_enabled(False)
check('switch preserves authored values and stacks', parent.read_value(nu).value == scalar('FLOAT32', .2)
      and len(parent.read_stack(nu)) == 1)
scene[ROOT]['future'] = {'opaque': b'keep'}
parent.write_feature_enabled(True)
check('switch preserves unknowns', scene[ROOT]['future']['opaque'] == b'keep')
scene[ROOT]['schema_version'] = 99
snapshot = scene[ROOT].to_dict()
reject('future switch mutation', lambda: parent.write_feature_enabled(False))
check('future root preserved', scene[ROOT].to_dict() == snapshot)
scene[ROOT]['schema_version'] = 1
manifest = [(item.identifier, item.scalar_type, item.dynamic) for item in legacy.DEFINITIONS]
check('manifest match stays execution-disabled', all(
    reason == 'generic_execution_adapter_pending' for reason in authoring.refresh_manifest(manifest).values()))
check('store never claims execution', not target.capability(nu).execution)
authoring.refresh_manifest([(nu.identifier, 'INT32', True)])
check('manifest conflict diagnosed', target.capability(nu).reason == 'manifest_contract_mismatch')
authoring.refresh_manifest([])
check('missing kernel retains authoring', target.capability(nu).reason == 'kernel_unavailable'
      and target.read_value(nu).value == scalar('FLOAT32', .3))
check('specific resolved diagnostic', 'execution:kernel_unavailable' in resolve(
    authoring.registry, nu.identifier, target).diagnostics)
reject('duplicate manifest rejected', lambda: authoring.refresh_manifest([manifest[0], manifest[0]]))

# Actual production registration is exercised with all engine entry points failing.
addon.unregister()
with patch.object(addon, '_register_modules', side_effect=RuntimeError('Downstream registration failed')):
    reject('downstream registration failure', addon.register, (RuntimeError,))
check('failed registration releases bank', not authoring.curve_bank._entries)
started = time.perf_counter()
with patch.object(addon.engine, 'capi', side_effect=RuntimeError('Engine deliberately unavailable')), \
        patch.object(addon.engine_props, '_walk_manifests', side_effect=RuntimeError('No manifest')):
    addon.register()
    authoring.register()
    check('production registration without engine', len(authoring.registry.definitions()) == 33)
    value = authoring.store(brush).read_value(plane[1])
    check('missing engine retains migrated reads and public RNA', value.value == .5 and hasattr(brush, 'sculptcore'))
    missing_engine = brush.copy()
    missing_engine.name = 'FrozenMissingEngineMigration'
    missing_engine.use_fake_user = True
    del missing_engine[ROOT][migration.FIELD]
    missing_store = authoring.store(missing_engine)
    check('migration runs without engine and retains public RNA', bool(migration.migrate(missing_store)))
    check('missing engine preserves independent generic edits', missing_store.read_value(nu).value == scalar('FLOAT32', .3))
    check('missing engine still fans out raw legacy data', missing_store.read_value(plane[1]).value == .5
          and missing_store.read_value(plane[1]).source == 'GENERIC')
    ref = authoring.curve_bank.initialize(authoring.store(brush), nu, 'SPEED')
    check('missing engine custom curve authoring', ref.mapping_key[0] > 0)
elapsed = time.perf_counter() - started
check('bank registration bounded', len(authoring.curve_bank._entries) == 62)
copy = brush.copy()
copy.name = 'FrozenIndependentCopy'
copy.use_fake_user = True
authoring.store(copy).write_value(nu, .125)
check('independent copied authoring', authoring.store(brush).read_value(nu).value == scalar('FLOAT32', .3)
      and authoring.store(copy).read_value(nu).value == .125)

# Standalone system getter probes: declared values, arbitrary raw scalars and malformed paths.
class SystemProbe(bpy.types.PropertyGroup):
    value: bpy.props.FloatProperty(default=.75)


bpy.utils.register_class(SystemProbe)
bpy.types.Brush.system_probe = bpy.props.PointerProperty(type=SystemProbe)
fresh = bpy.data.brushes.new('SystemScalarProbe', mode='SCULPT')
reader = fresh.system_property_scalar
check('absent system path', reader(('system_probe', 'value')) == (False, None, None))
_ = fresh.system_probe.value
check('default ghost remains absent', reader(('system_probe', 'value')) == (False, None, None))
fresh.system_probe.value = .75
check('authored default distinct', reader(('system_probe', 'value')) == (True, 'FLOAT', .75))
group = fresh.system_probe
for name, value, kind in [('integer', 5, 'INT'), ('double', .4, 'DOUBLE'),
                          ('boolean', True, 'BOOLEAN'), ('string', 'café', 'STRING')]:
    group[name] = value
    check('copied raw scalar ' + kind, reader(('system_probe', name)) == (True, kind, value))
group['broken'] = {'nested': [1, 2, 3]}
snapshot = group.to_dict() if hasattr(group, 'to_dict') else {key: group[key] for key in group.keys()}
for path in [(), ('missing\0',), ['system_probe'], ('system_probe', 'integer', 'x'),
             ('system_probe', 'broken'), ('system_probe', 'broken', 'nested')]:
    reject('invalid system path ' + str(path), lambda p=path: reader(p), (ValueError, TypeError))
group['bytes'] = b'opaque'
reject('bytes leaf rejected', lambda: reader(('system_probe', 'bytes')), (ValueError,))
check('unsupported raw preserved', group['bytes'] == b'opaque' and list(group['broken']['nested']) == [1, 2, 3])
errors = []


def worker():
    try:
        reader(('system_probe', 'value'))
    except RuntimeError:
        errors.append(True)


thread = threading.Thread(target=worker)
thread.start()
thread.join()
check('system reader main-thread guard', errors == [True])
bpy.data.brushes.remove(fresh)
reject('removed owner rejected', lambda: reader(('value',)), (ReferenceError, ValueError))
del bpy.types.Brush.system_probe
bpy.utils.unregister_class(SystemProbe)

brush.use_fake_user = True
bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'frozen.blend'))
(DIRECTORY / 'results.json').write_text(json.dumps(dict(checks=checks, registration_seconds=elapsed), indent=2))
print('FROZEN_AUTHORING_OK', len(checks), flush=True)
