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
from sculptcore_addon.brush_properties import authoring, legacy
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
nu = authoring.registry.get('sculptcore.kernel.kelvinlet.nu')
for changes in (dict(default=.1), dict(maximum=10), dict(dynamic=False), dict(owners=frozenset(('BRUSH',))),
                dict(scalar_type='INT32', default=0, minimum=0, maximum=1, soft_minimum=0, soft_maximum=1)):
    conflicting = Registry()
    wrong = conflicting.register(replace(nu, **changes))
    bad_store = PersistentOwnerStore(brush, conflicting)
    reject('reserved frozen contract ' + str(changes), lambda: bad_store.write_value(wrong, wrong.default))
target.write_positions(nu, ())
check('metadata-only record sees authored legacy', target.read_value(nu).source == 'LEGACY')
plane = [item for item in legacy.DEFINITIONS if item.identifier.endswith('.planeSide')]
target.write_value(plane[0], -.25)
check('one fanout override independent', target.read_value(plane[0]).value == -.25
      and all(not target.read_value(item).present for item in plane[1:]))
brush.sculptcore['planeSide'] = .5
check('raw legacy script change visible to remaining fanout', all(
    target.read_value(item).value == .5 for item in plane[1:]) and target.read_value(plane[0]).value == -.25)
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
check('absent switch nonallocating', parent.feature_enabled() is False and ROOT not in scene)
parent.write_feature_enabled(False)
check('false no-op nonallocating', ROOT not in scene)
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
    check('production registration without engine', len(authoring.registry.definitions()) == 27)
    value = authoring.store(brush).read_value(plane[1])
    check('unregistered legacy RNA still readable', value.value == .5 and value.source == 'LEGACY')
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
