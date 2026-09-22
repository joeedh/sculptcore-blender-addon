# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual native authority, size, pressure metadata and compound cavity gates."""
from dataclasses import replace
import itertools
import json
from pathlib import Path
import bpy

from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import (
    BY_ID, CAVITY, SIZE, SIZE_ALIASES, STRENGTH, radius_from_diameter, snake_pinch, spacing_fraction,
    accumulate_value, invert_for_dab, strength_multiplier)
from sculptcore_addon.brush_properties.bindings import (
    binding, set_cavity_mode, texture_slot_binding, strength_for_kernel)
from sculptcore_addon.brush_properties.edits import authoring_edit
from sculptcore_addon.brush_properties.registry import DeviceLayer, PropertyError, ResponseCurve
from sculptcore_addon.brush_properties.resolver import resolve, set_value, set_stack
from sculptcore_addon.brush_properties.storage import ROOT, record_key

checks = []
registry = authoring.registry
bank = authoring.curve_bank
b = bpy.data.brushes.new('Native Adapter', mode='SCULPT')
s = bpy.context.scene


def stores():
    return authoring.store(b), authoring.store(s)


def check(label, condition):
    assert condition, label
    checks.append(label)


def rejects(label, call):
    try:
        call()
    except (PropertyError, ValueError, TypeError, PermissionError):
        checks.append(label)
        return
    raise AssertionError(label)


local, parent = stores()
check('registration supplies complete frozen native catalog',
      all(registry.get(key) == value for key, value in BY_ID.items()))
for mode, unified, inherited in itertools.product(('UNIFIED', 'ALWAYS', 'NEVER'), (False, True), (False, True)):
    local.write_mode(STRENGTH, mode)
    parent.write_unified(STRENGTH, unified)
    local.write_stack_inheritance(STRENGTH, inherited)
    b.strength = .25
    s.tool_settings.sculpt.unified_paint_settings.strength = .75
    parent.write_stack(registry.get(STRENGTH), (DeviceLayer('SPEED', curve=ResponseCurve('SQUARE')),))
    result = resolve(registry, STRENGTH, local, parent)
    want_parent = mode == 'ALWAYS' or mode == 'UNIFIED' and unified
    check('owner truth {} {} {}'.format(mode, unified, inherited),
          result.value_owner is (parent if want_parent else local)
          and result.stack_owner is (parent if inherited else local))
    set_value(registry, STRENGTH, local, parent, .5)
    check('dormant strength {}'.format((mode, unified, inherited)),
          b.strength == (.25 if want_parent else .5)
          and s.tool_settings.sculpt.unified_paint_settings.strength == (.5 if want_parent else .75))
local.write_mode(STRENGTH, 'NEVER')
local.write_stack_inheritance(STRENGTH, False)
for name in ('spacing', 'plane_offset', 'snake_pinch', 'hardness', 'autosmooth', 'accumulate', 'spacing_attenuation'):
    definition = registry.get('sculptcore.brush.' + name)
    path = local._native.binding(definition.identifier)[1]
    value = False if definition.scalar_type == 'BOOL' else 12 if name == 'spacing' else .375
    local.write_value(definition, value)
    check('authoritative ' + name, getattr(b, path) == value and local.read_value(definition).value == value)
    record = local._record(definition.identifier)
    check('no scalar mirror ' + name, record is None or 'value' not in record)

size = registry.get(SIZE)
local.write_mode(SIZE, 'NEVER')
b.use_locked_size = 'VIEW'
b.size = 100
b.unprojected_size = .75
check('pixel metadata uses current native definition', local.metadata(SIZE)['description']
      == b.bl_rna.properties['size'].description and local.metadata(SIZE)['max'] == 10000)
set_value(registry, SIZE, local, parent, 200)
check('pixel setter preserves actual proportional world behavior', b.size == 200 and b.unprojected_size == 1.5)
local._native.write_size_mode('SCENE')
check('world metadata uses current native units and bounds', local.metadata(SIZE)['subtype']
      == b.bl_rna.properties['unprojected_size'].subtype
      and local.metadata(SIZE)['min'] == b.bl_rna.properties['unprojected_size'].hard_min)
set_value(registry, SIZE, local, parent, .375)
check('world setter preserves actual asymmetric pixel behavior', b.size == 200 and b.unprojected_size == .375)
key_world = resolve(registry, SIZE, local, parent).invalidation_key
local._native.write_size_mode('VIEW')
check('size mode changes effective metadata and key',
      resolve(registry, SIZE, local, parent).value_domain.kind == 'INT32'
      and key_world != resolve(registry, SIZE, local, parent).invalidation_key)
rejects('fractional pixel diameter rejected', lambda: set_value(registry, SIZE, local, parent, 20.5))
saved = local._native.size_block()
try:
    with authoring_edit(local, undo=False):
        local.write_value(size, 300)
        local._native.write_size_mode('SCENE')
        raise RuntimeError('cancel')
except RuntimeError:
    pass
rejects('rollback expires old stores', lambda: local.read_value(size))
local, parent = stores()
check('exact unequal paired size cancel', local._native.size_block() == saved)
for alias in SIZE_ALIASES:
    local.write_mode(alias, 'ALWAYS')
    check('size alias shares value policy ' + alias, local.value_mode(SIZE) == 'ALWAYS')
    rejects('alias has no second stack ' + alias, lambda: local.write_stack(registry.get(alias), ()))
local.write_mode(SIZE, 'NEVER')
b.size = 1
b.unprojected_size = 3.4028234663852886e38
rejects('paired world overflow rejected before pixel setter', lambda: local.write_value(size, 2))
check('overflow rejection preserves pair', b.size == 1 and b.unprojected_size == 3.4028234663852886e38)
b.unprojected_size = .0010000000474974513
b.size = 2
b.unprojected_size = .0010000000474974513
rejects('paired world underflow rejected', lambda: local.write_value(size, 1))
b.unprojected_size = .5
check('independent geometry semantics', radius_from_diameter(.75) == .375 and spacing_fraction(25) == .25
      and snake_pinch(.75) == -.5)
check('brush family policies retain authored source', strength_multiplier('DRAW_SHARP') == 2
      and strength_multiplier('DRAW') == 1 and accumulate_value('DRAW_SHARP', False)
      and accumulate_value('DRAW', False, operation_mode='SMOOTH')
      and accumulate_value('GRAB', False, has_accumulate=False) and not accumulate_value('DRAW', False))
b.sculpt_brush_type = 'PINCH'
b.strength = .25
s.tool_settings.sculpt.unified_paint_settings.strength = .75
local.write_mode(STRENGTH, 'ALWAYS')
check('PINCH extra preserves explicit local-source exception',
      strength_for_kernel(registry, local, parent, 'PINCH') == (.75, .25)
      and 'legacy:pinch_extra_uses_local_strength' in resolve(registry, STRENGTH, local, parent).diagnostics)
b.sculpt_brush_type = 'DRAW'
local.write_mode(STRENGTH, 'NEVER')
b.color = (.25, .5, .75)
s.tool_settings.sculpt.unified_paint_settings.color = (.75, .5, .25)
s.tool_settings.sculpt.unified_paint_settings.use_unified_color = True
color = binding(registry, 'sculptcore.brush.color', local, parent)
check('retained paint color keeps inventory local source', tuple(color.read()) == (.25, .5, .75))
color.write((.125, .25, .5))
check('retained paint color writes local native storage', tuple(b.color) == (.125, .25, .5)
      and tuple(s.tool_settings.sculpt.unified_paint_settings.color) == (.75, .5, .25))
# Every BRUSH_DIR_IN item inverts, not only the draw family's SUBTRACT: Pinch
# names its inverted item MAGNIFY and Inflate DEFLATE.
for direction, invert, allowed in itertools.product(
        ('ADD', 'SUBTRACT', 'DEFAULT', 'DEFLATE', 'MAGNIFY', 'INFLATE', 'PINCH'), (False, True), (False, True)):
    check('legacy direction policy ' + str((direction, invert, allowed)),
          invert_for_dab(direction, invert, allow_invert=allowed)
          == (bool(invert) ^ (direction in ('SUBTRACT', 'DEFLATE', 'MAGNIFY')) if allowed else False))

for identifier in (STRENGTH, SIZE):
    definition = registry.get(identifier)
    # Discard only the test fixture's stack metadata to exercise a truly absent stack.
    record = local._record(identifier)
    if record is not None:
        for field in ('stack_version', 'layer_order', 'layers'):
            if field in record:
                del record[field]
    for brush_type in ('DRAW', 'GRAB', 'SNAKE_HOOK'):
        b.sculpt_brush_type = brush_type
        local._native.write_pressure(identifier, True)
        layers = local.read_stack(definition)
        check('native pressure capability ' + identifier + brush_type,
              layers[0].device == 'PRESSURE' and layers[0].enabled)
        reference = local._native.curve_reference(identifier)
        mapping = local._native.curve_mapping(reference)
        before = reference.mapping_key
        local.write_stack(definition, (DeviceLayer('PRESSURE', False, curve=ResponseCurve('SQUARE')),))
        check('preset preserves dormant native mapping ' + identifier + brush_type,
              local._native.curve_reference(identifier).mapping_key == before
              and not local.read_stack(definition)[0].enabled)
        record = local._record(identifier)
        check('native enabled has no saved authority ' + identifier + brush_type,
              'enabled' not in record['layers']['PRESSURE'])
        setattr(b, local._native.pressure_path(identifier), True)
        check('script flag change stays authoritative ' + identifier + brush_type,
              local.read_stack(definition)[0].enabled)
        local.write_stack(definition, ())
        check('explicit empty disables pressure ' + identifier + brush_type,
              local.read_stack(definition) == () and local._record(identifier)['layer_order'] == '')
        local._native.write_pressure(identifier, True)
        check('script re-enable creates single virtual entry ' + identifier + brush_type,
              len(local.read_stack(definition)) == 1)
        local.write_stack(definition, local.read_stack(definition))
        check('virtual native custom entry normalizes ' + identifier + brush_type,
              local._record(identifier)['layers']['PRESSURE']['preset'] == 'CUSTOM')
    b.sculpt_brush_type = 'DRAW'
    custom = bank.initialize(local, definition, 'TILT_X')
    local.write_stack(definition, (DeviceLayer('TILT_X', curve=custom),))
    check('non-pressure native property uses owned curve ' + identifier,
          local.read_stack(definition)[0].curve == custom)
    rejects('native pressure cannot allocate bank shadow ' + identifier,
            lambda: bank.initialize(local, definition, 'PRESSURE'))
    scene_custom = bank.initialize(parent, definition, 'PRESSURE')
    parent.write_stack(definition, (DeviceLayer('PRESSURE', curve=scene_custom),))
    native_key = local._native.curve_reference(identifier).mapping_key
    local.write_stack_inheritance(identifier, True)
    check('Scene owned curve inheritance ' + identifier,
          resolve(registry, identifier, local, parent).stack[0].curve == scene_custom
          and local._native.curve_reference(identifier).mapping_key == native_key)
    local.write_stack_inheritance(identifier, False)

factor = registry.get(CAVITY + '.cavity_factor')
bc, sc = b.mesh_automasking_settings, s.tool_settings.sculpt.mesh_automasking_settings
bc.cavity_factor, sc.cavity_factor = 1.75, .625
for bm, sm in itertools.product(('OFF', 'NORMAL', 'INVERTED'), repeat=2):
    for block, mode in ((bc, bm), (sc, sm)):
        block.use_automasking_cavity = False
        block.use_automasking_cavity_inverted = False
        if mode != 'OFF':
            setattr(block, 'use_automasking_cavity' + ('_inverted' if mode == 'INVERTED' else ''), True)
    result = resolve(registry, factor.identifier, local, parent)
    want_scene = bm == 'OFF' and sm != 'OFF'
    check('cavity block truth ' + bm + sm, result.value_owner is (parent if want_scene else local)
          and result.value == (.625 if want_scene else 1.75))
    check('cavity native curve shares owner ' + bm + sm,
          binding(registry, CAVITY + '.cavity_curve', local, parent).store is result.value_owner)
bc.use_automasking_cavity = True
sc.use_automasking_cavity_inverted = True
target = set_cavity_mode(registry, local, parent, 'OFF')
check('cavity off pins local edit then reveals Scene', target is local
      and resolve(registry, factor.identifier, local, parent).value_owner is parent)
local.write_mode(factor.identifier, 'NEVER')
check('explicit cavity policy preserves dormant Scene block',
      resolve(registry, factor.identifier, local, parent).value == 1.75
      and sc.use_automasking_cavity_inverted and sc.cavity_factor == .625)
local.write_mode(CAVITY + '.cavity_blur_steps', 'ALWAYS')
check('cavity fields share one policy', local.value_mode(factor.identifier) == 'ALWAYS')
direction = binding(registry, 'sculptcore.brush.direction', local, parent)
rejects('native direction rejects unsupported Object context', lambda: direction.write('SUBTRACT'))
bpy.ops.object.mode_set(mode='SCULPT')
direction.write('SUBTRACT')
check('retained native enum binding', b.direction == 'SUBTRACT' and direction.read() == 'SUBTRACT')
rejects('invalid retained enum', lambda: direction.write('INVALID'))
bpy.ops.object.mode_set(mode='OBJECT')
for field in ('offset', 'scale', 'map_mode'):
    check('retained texture slot ' + field, texture_slot_binding(local, field).rna()[1] == field)

path = Path(__file__).resolve().parents[1] / 'tests/plan4-native-adapters.checks.json'
path.write_text(json.dumps(checks, indent=2), encoding='utf-8')
b.use_fake_user = True
bpy.ops.wm.save_as_mainfile(filepath=str(path.parent / 'plan4-native-adapters.blend'))
print('NATIVE_ADAPTERS_OK', len(checks), flush=True)
