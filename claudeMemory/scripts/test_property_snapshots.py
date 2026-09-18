# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Effective snapshots against real Brush/Scene RNA, curves and restoration."""
from dataclasses import fields, is_dataclass, replace
import itertools
import json
from pathlib import Path
import threading
from unittest.mock import patch

import bpy
from sculptcore_addon.brush_properties import authoring, customize, lifecycle, sampling
from sculptcore_addon.brush_properties.adapters import BY_ID, PIXELS, SIZE, STRENGTH, WORLD, NativeOwner
from sculptcore_addon.brush_properties.commands import prepare_stack
from sculptcore_addon.brush_properties.curves import declaration_name
from sculptcore_addon.brush_properties.engine_catalogue import DEFINITIONS as ENGINE_DEFINITIONS
from sculptcore_addon.brush_properties.registry import DeviceLayer, PropertyError, ResponseCurve, scalar
from sculptcore_addon.brush_properties.resolver import Capability, resolve
from sculptcore_addon.brush_properties.snapshots import capture
from sculptcore_addon.brush_properties.storage import ROOT

OUT = Path(__file__).resolve().parents[1] / 'tests'
checks = []
registry = authoring.registry
brush = bpy.data.brushes.new('Plan6Snapshot', mode='SCULPT')
brush.use_fake_user = True
scene = bpy.context.scene
local, parent = authoring.store(brush), authoring.store(scene)


def check(label, condition):
    assert condition, label
    checks.append(label)


def reject(label, function):
    try:
        function()
    except PropertyError:
        checks.append(label)
    else:
        raise AssertionError(label)


def snap(identifier, owner=None):
    return capture(registry, (identifier,), local if owner is None else owner, parent)[0]


def immutable(value):
    if type(value) in (str, int, float, bool, bytes, type(None)):
        return
    if type(value) in (tuple, frozenset):
        for item in value:
            immutable(item)
        return
    assert is_dataclass(value) and value.__dataclass_params__.frozen, type(value)
    for field in fields(value):
        immutable(getattr(value, field.name))


engine_ids = tuple(item.identifier for item in ENGINE_DEFINITIONS)
initial = capture(registry, engine_ids, local, parent)
check('unset defaults allocate no generic storage', ROOT not in brush and ROOT not in scene)
check('engine defaults remain unset with frozen generic domain', all(
    not item.present and item.value_domain == item.definition and not item.execution_available
    and item.stack_available and item.stack == () for item in initial))
check('exact engine float32 defaults', tuple(item.value for item in initial) == (
    False, scalar('FLOAT32', 1.5707964), scalar('FLOAT32', .43633232), False))
check('angle metadata radians and rounded pi bounds', all(
    item.definition.unit == 'ROTATION' and item.definition.maximum == scalar('FLOAT32', 3.141592653589793)
    for item in initial[1:3]))
native_initial = capture(registry, (SIZE, STRENGTH, PIXELS, WORLD), local, parent)
check('native reads allocate no generic storage or owned curves', ROOT not in brush and ROOT not in scene
      and all(getattr(brush, name) is None for (owner_type, name) in authoring.curve_bank._entries
              if owner_type is bpy.types.Brush))
immutable(native_initial)
nu = registry.get('sculptcore.kernel.kelvinlet.nu')
check('unset legacy presence', not snap(nu.identifier).present and snap(nu.identifier).source == 'LEGACY')
brush.sculptcore[nu.label] = .375
legacy = snap(nu.identifier)
check('authored legacy remains visible', legacy.present and legacy.source == 'LEGACY' and legacy.value == .375)
local.write_value(nu, .25)
check('generic override preserves dormant legacy', snap(nu.identifier).source == 'GENERIC'
      and snap(nu.identifier).value == .25 and brush.sculptcore[nu.label] == .375)

strength = registry.get(STRENGTH)
brush.strength = .25
scene.tool_settings.sculpt.unified_paint_settings.strength = .75
for store, preset in ((local, 'SQUARE'), (parent, 'ROOT')):
    store.write_stack(strength, (DeviceLayer('PRESSURE', curve=ResponseCurve(preset)),))
    customize.customize(store, strength, 'PRESSURE', reseed=True, undo=False)
snapshots = []
for inherit_value, inherit_stack in itertools.product((False, True), repeat=2):
    local.write_mode(STRENGTH, 'ALWAYS' if inherit_value else 'NEVER')
    local.write_stack_inheritance(STRENGTH, inherit_stack)
    result = snap(STRENGTH)
    snapshots.append(result)
    check('independent effective owners {} {}'.format(inherit_value, inherit_stack),
          result.value == (.75 if inherit_value else .25) and result.source == 'NATIVE'
          and abs(result.stack[0].response.evaluate(.5) - (.5 ** .5 if inherit_stack else .25)) < 1e-4)

ups = scene.tool_settings.sculpt.unified_paint_settings
brush.size, ups.size = 101, 303
brush.unprojected_size, ups.unprojected_size = .25, .75
size = registry.get(SIZE)
local.write_stack(size, (DeviceLayer('SPEED', curve=ResponseCurve('CONSTANT', (.25,))),))
parent.write_stack(size, (DeviceLayer('TILT_X', curve=ResponseCurve('CONSTANT', (.75,))),))
for local_mode, inherit_value, inherit_stack in itertools.product(('VIEW', 'SCENE'), (False, True), (False, True)):
    brush.use_locked_size = local_mode
    ups.use_locked_size = 'SCENE' if local_mode == 'VIEW' else 'VIEW'
    local.write_mode(SIZE, 'ALWAYS' if inherit_value else 'NEVER')
    local.write_stack_inheritance(SIZE, inherit_stack)
    result = snap(SIZE)
    expected = ups if inherit_value else brush
    check('paired native size {} {} {}'.format(local_mode, inherit_value, inherit_stack),
          (result.size.pixels, result.size.world, result.size.mode)
          == (expected.size, expected.unprojected_size, expected.use_locked_size)
          and type(result.value) is (int if expected.use_locked_size == 'VIEW' else float)
          and result.value_domain.kind == ('INT32' if expected.use_locked_size == 'VIEW' else 'FLOAT32')
          and result.stack[0].device == ('TILT_X' if inherit_stack else 'SPEED'))
    snapshots.append(result)
    selected = parent if inherit_value else local
    native_block = selected._native.size_block()
    for field, invalid in (('pixels', 0), ('pixels', 101.0), ('world', 0.0), ('world', 1), ('mode', 'INVALID')):
        with patch.object(NativeOwner, 'size_block', return_value=replace(native_block, **{field: invalid})):
            reject('malformed paired size {} {} {}'.format(local_mode, inherit_value, field), lambda: snap(SIZE))
    active = 'pixels' if native_block.mode == 'VIEW' else 'world'
    with patch.object(NativeOwner, 'size_block', return_value=replace(native_block, **{active: 222 if active ==
                      'pixels' else .5})):
        reject('size active field mismatch', lambda: snap(SIZE))
for alias in (PIXELS, WORLD):
    result = snap(alias)
    check('unavailable static alias ' + alias,
          not result.stack_available and result.stack == () and not result.execution_available)

reject('duplicate request', lambda: capture(registry, (SIZE, SIZE), local, parent))
reject('unknown request', lambda: snap('unknown.property'))
with patch.object(local, 'capability', return_value=Capability(True, False, False)):
    local.write_mode(nu.identifier, 'NEVER')
    reject('unavailable dynamic stack', lambda: snap(nu.identifier))

# Cached native and owned mappings must still pass source-identity validation.
local.write_mode(STRENGTH, 'NEVER')
local.write_stack_inheritance(STRENGTH, False)
old = resolve(registry, STRENGTH, local, parent)
prepare_stack(old)
brush.curve_strength.curves[0].points[-1].location = (1, .5)
reject('warm stale native mapping', lambda: prepare_stack(old))
old = resolve(registry, STRENGTH, local, parent)
prepare_stack(old)
old_path = old.stack[0].curve.enable_path
for brush_type in ('GRAB', 'SNAKE_HOOK', 'DRAW'):
    brush.sculpt_brush_type = brush_type
    if local._native.pressure_path(STRENGTH) != old_path:
        break
assert local._native.pressure_path(STRENGTH) != old_path
reject('warm stale native pressure capability', lambda: prepare_stack(old))
brush.sculpt_brush_type = 'DRAW'
local.write_stack_inheritance(STRENGTH, True)
old = resolve(registry, STRENGTH, local, parent)
prepare_stack(old)
getattr(scene, declaration_name(STRENGTH, 'PRESSURE')).curves[0].points[-1].location = (1, .25)
reject('warm stale custom mapping', lambda: prepare_stack(old))

for item in snapshots + list(initial):
    immutable(item)
check('all snapshot graphs are immutable and owner-free', True)
saved_hash = hash(tuple(snapshots))
sampling.clear()
check('completed snapshots survive source edits and cache clear', saved_hash == hash(tuple(snapshots)))

errors = []


def worker():
    try:
        snap(nu.identifier)
    except PropertyError:
        errors.append(True)


thread = threading.Thread(target=worker)
thread.start()
thread.join()
check('capture requires main thread', errors == [True])

# Capture stale stores with empty and generated stacks, without a curve callback.
for layers in ((), (DeviceLayer('SPEED'),)):
    local.write_stack(nu, layers)
    prior = snap(nu.identifier)
    lifecycle._invalidate()
    reject('restoration invalidates empty/generated owner', lambda: snap(nu.identifier))
    local, parent = authoring.store(brush), authoring.store(scene)
    immutable(prior)

deleted = bpy.data.brushes.new('Plan6DeletedOwner', mode='SCULPT')
deleted_store = authoring.store(deleted)
prior = snap(engine_ids[0], deleted_store)
bpy.data.brushes.remove(deleted)
reject('removed empty-stack owner', lambda: snap(engine_ids[0], deleted_store))
immutable(prior)

for definition in ENGINE_DEFINITIONS:
    local.write_value(definition, True if definition.scalar_type == 'BOOL' else .25)
    parent.write_value(definition, False if definition.scalar_type == 'BOOL' else .75)
    local.write_mode(definition.identifier, 'ALWAYS')
    result = snap(definition.identifier)
    check('new engine settings use Scene generic values ' + definition.identifier,
          result.value == (False if definition.scalar_type == 'BOOL' else .75) and result.source == 'GENERIC'
          and not result.execution_available)
    check('dormant generic local value ' + definition.identifier,
          local.read_value(definition).value == (True if definition.scalar_type == 'BOOL' else .25))
check('catalogue and declarations', len(registry.definitions()) == 27 and len(authoring.curve_bank._entries) == 62)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'plan6-snapshots.blend'))
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'plan6-snapshots.blend'))
reject('file restoration invalidates previous stores', lambda: snap(nu.identifier))
check('completed snapshots survive file restoration', saved_hash == hash(tuple(snapshots)))
result = dict(passed=True, checks=checks, snapshot_hash_unchanged=saved_hash == hash(tuple(snapshots)))
(OUT / 'plan6-snapshots.checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_SNAPSHOTS_PASS', len(checks), flush=True)
