# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender numerical ownership checks; import isolation does not unload the startup addon."""

import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package

package, native = load_package()
from generic_property_test_package.registry import Registry, PropertyError
from generic_property_test_package import lifecycle
from generic_property_test_package.resolver import resolve, set_value, set_value_mode, set_unified, set_stack

registry = Registry()
lifecycle.register()
registry.register(native.STRENGTH_DEFINITION)
key = native.STRENGTH
brushes = [bpy.data.brushes.new('Plan4 native ' + str(i), mode='SCULPT') for i in range(2)]
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.object.mode_set(mode='OBJECT')
scenes = [bpy.context.scene.copy() for _ in range(2)]
empty_scene = bpy.data.scenes.new('Plan4 uninitialized Scene')
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


try:
    local = [native.NativeStrengthOwner(owner, epoch=1) for owner in brushes]
    parent = [native.NativeStrengthOwner(owner, epoch=1) for owner in scenes]
    before = [tuple(owner.keys()) for owner in brushes + scenes]
    missing_parent = native.NativeStrengthOwner(empty_scene, epoch=1)
    set_value_mode(registry, key, local[0], 'ALWAYS')
    fallback = resolve(registry, key, local[0], missing_parent)
    check('uninitialized Scene falls back without allocation',
          fallback.value_owner is local[0] and 'value:parent_unavailable' in fallback.diagnostics
          and empty_scene.tool_settings.sculpt is None)
    set_value_mode(registry, key, local[0], 'UNIFIED')
    for store in local + parent:
        value = resolve(registry, key, store)
        check('fresh native presence ' + str(store.identity), value.value_source.present)
        check('owner-specific native default ' + str(store.identity),
              value.value == native.NATIVE_DEFAULTS[store.kind])
    brushes[0].strength, brushes[1].strength = .25, .375
    for i, value in enumerate((.75, .875)):
        scenes[i].tool_settings.sculpt.unified_paint_settings.strength = value
        set_unified(registry, key, parent[i], True)
    check('scene switch reads current native owner',
          resolve(registry, key, local[0], parent[0]).value == .75 and
          resolve(registry, key, local[0], parent[1]).value == .875)
    check('unavailable stack is explicit', resolve(registry, key, local[0], parent[0]).stack is None)
    set_value(registry, key, local[0], parent[1], .625)
    check('inactive scene write targets actual scene',
          scenes[1].tool_settings.sculpt.unified_paint_settings.strength == .625 and
          scenes[0].tool_settings.sculpt.unified_paint_settings.strength == .75 and
          brushes[0].strength == .25 and brushes[1].strength == .375)
    set_value_mode(registry, key, local[0], 'NEVER')
    check('dormant local restored', resolve(registry, key, local[0], parent[0]).value == .25)
    old_native_flag = brushes[0].use_unified_strength
    set_value(registry, key, local[0], parent[0], .5)
    check('effective local write', brushes[0].strength == .5 and brushes[1].strength == .375)
    brushes[0].strength = .3125
    check('ordinary native edit visible', resolve(registry, key, local[0], parent[0]).value == .3125)
    set_value_mode(registry, key, local[0], 'ALWAYS')
    set_unified(registry, key, parent[0], False)
    check('always ignores unified flag', resolve(registry, key, local[0], parent[0]).value == .75)
    check('native per-brush flag untouched', brushes[0].use_unified_strength == old_native_flag)
    for function, arguments in (
            (local[0].write_unified, (key, True)),
            (parent[0].write_mode, (key, 'NEVER')),
            (local[0].write_mode, ('unknown', 'ALWAYS')),
            (local[0].write_stack_inheritance, (key, 1)),
            (parent[0].write_unified, (key, 1))):
        try:
            function(*arguments)
        except PropertyError:
            pass
        else:
            raise AssertionError('Accepted malformed direct native metadata write')
    check('direct native metadata writes respect owner and type',
          brushes[0].use_unified_strength == old_native_flag and local[0].value_mode(key) == 'ALWAYS'
          and parent[0].unified(key) is False)
    for bad in (True, float('nan'), -1, 11, 10**400):
        try:
            set_value(registry, key, local[0], parent[0], bad)
        except PropertyError:
            pass
        else:
            raise AssertionError('Accepted invalid strength')
    check('invalid writes preserve both owners', brushes[0].strength == .3125 and
          scenes[0].tool_settings.sculpt.unified_paint_settings.strength == .75)
    try:
        set_stack(registry, key, local[0], parent[0], ())
    except PropertyError:
        checks.append('native stack editing explicitly unavailable')
    else:
        raise AssertionError('Native pressure silently replaced by empty stack')
    check('no persistent records created', before == [tuple(owner.keys()) for owner in brushes + scenes])
    new_epoch = native.NativeStrengthOwner(brushes[0], epoch=2)
    check('lifecycle epoch participates in identity', local[0].identity != new_epoch.identity)
    report = dict(passed=True, checks=checks, scope='Numerical ownership and isolated import; no persistence or dirty-state gate')
    (Path(__file__).resolve().parents[1] / 'tests/plan4-native-results.json').write_text(json.dumps(report, indent=2))
    print('PLAN4_NATIVE_FOUNDATION_PASS', len(checks), flush=True)
finally:
    lifecycle.unregister()
    for owner in brushes:
        bpy.data.brushes.remove(owner)
    for owner in scenes:
        bpy.data.scenes.remove(owner)
    bpy.data.scenes.remove(empty_scene)
