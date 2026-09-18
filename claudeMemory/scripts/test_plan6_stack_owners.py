# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual owner-aware curve preparation for immutable command snapshots."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sculptcore_addon.brush_properties.authoring import curve_bank as production_bank
production_bank.unregister()
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import curves, customize, lifecycle, sampling
from generic_property_test_package.commands import prepare_stack
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.resolver import resolve
from generic_property_test_package.storage import PersistentOwnerStore

registry = Registry()
definition = registry.register(Definition('test.plan6', 'Command curve', 'FLOAT32', 1, 0, 10, 0, 1))
lifecycle.register()
bank = curves.CurveBank(registry)
bank.register()
brush = bpy.data.brushes.new('Plan6OwnerSnapshot', mode='SCULPT')
local = PersistentOwnerStore(brush, registry, curve_bank=bank)
parent = PersistentOwnerStore(bpy.context.scene, registry, curve_bank=bank)
local.write_value(definition, .25)
parent.write_value(definition, .75)
for store, preset in ((local, 'SQUARE'), (parent, 'ROOT')):
    store.write_stack(definition, (DeviceLayer('PRESSURE', curve=ResponseCurve(preset)),))
    customize.customize(store, definition, 'PRESSURE', undo=False)

checks = []
local.write_mode(definition.identifier, 'ALWAYS')
local.write_stack_inheritance(definition.identifier, False)
first = resolve(registry, definition.identifier, local, parent)
assert first.value == .75 and first.stack_owner is local
first_snapshot = prepare_stack(first)
assert abs(first_snapshot[0].response.evaluate(.5) - .25) < 1e-4
checks.append('Scene value with Brush custom stack samples effective stack owner')
local.write_mode(definition.identifier, 'NEVER')
local.write_stack_inheritance(definition.identifier, True)
second = resolve(registry, definition.identifier, local, parent)
assert second.value == .25 and second.stack_owner is parent
second_snapshot = prepare_stack(second)
assert abs(second_snapshot[0].response.evaluate(.5) - .5 ** .5) < 1e-4
checks.append('Brush value with Scene custom stack samples effective stack owner')
mapping = getattr(bpy.context.scene, curves.declaration_name(definition.identifier, 'PRESSURE'))
mapping.curves[0].points[-1].location = (1, .125)
try:
    prepare_stack(second)
except PropertyError:
    pass
else:
    raise AssertionError('Stale curve reference must fail before native upload')
sampling.clear()
assert abs(second_snapshot[0].response.evaluate(.5) - .5 ** .5) < 1e-4
assert abs(first_snapshot[0].response.evaluate(.5) - .25) < 1e-4
checks.append('Stale authoring references reject; completed snapshots survive edits and cache retirement')
bank.unregister()
lifecycle.unregister()
result = dict(passed=True, checks=checks)
(Path(__file__).resolve().parents[1] / 'tests/plan6-stack-owners.checks.json').write_text(
    json.dumps(result, indent=2), encoding='utf-8')
print('PLAN6_STACK_OWNERS_PASS', json.dumps(result), flush=True)

