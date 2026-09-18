# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fresh native/owned state, independent copies, real assets and readonly failures."""
import json
from pathlib import Path
import bpy
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH
from sculptcore_addon.brush_properties.curves import declaration_name
from sculptcore_addon.brush_properties.registry import PropertyError
from sculptcore_addon.brush_properties.storage import ROOT

root = Path(__file__).resolve().parents[1] / 'tests'
bpy.ops.wm.open_mainfile(filepath=str(root / 'plan4-native-adapters.blend'))
b = bpy.data.brushes['Native Adapter']
local, parent = authoring.store(b), authoring.store(bpy.context.scene)
checks = []


def check(label, condition):
    assert condition, label
    checks.append(label)


for identifier in (STRENGTH, SIZE):
    definition = authoring.registry.get(identifier)
    check('fresh Brush owns tilt custom ' + identifier, local.read_stack(definition)[0].device == 'TILT_X')
    check('fresh Scene owns pressure custom ' + identifier, parent.read_stack(definition)[0].device == 'PRESSURE')
    check('fresh native pressure disabled ' + identifier, not local._native.pressure_enabled(identifier))
copy = b.copy()
copy.name = 'Native Independent Copy'
copy.use_fake_user = True
copied = authoring.store(copy)
old = authoring.curve_bank.reference(local, authoring.registry.get(SIZE), 'TILT_X')
new = authoring.curve_bank.reference(copied, authoring.registry.get(SIZE), 'TILT_X')
check('copy has independent owner and mapping identity', old.owner_identity != new.owner_identity
      and old.mapping_key[0] != new.mapping_key[0])
mapping = getattr(copy, declaration_name(SIZE, 'TILT_X'))
mapping.curves[0].points[-1].location.y = .3125
check('copy curve edit leaves original dormant data',
      getattr(b, declaration_name(SIZE, 'TILT_X')).curves[0].points[-1].location.y == 1)
copy.strength = .875
check('copy native scalar independent', b.strength != copy.strength)
copy.asset_mark()
copy.asset_data.description = 'Plan 4 native adapter asset fixture'
asset = root / 'plan4-native-adapter-asset.blend'
bpy.data.libraries.write(str(asset), {copy}, fake_user=True)
bpy.data.brushes.remove(copy)
with bpy.data.libraries.load(str(asset), link=True) as (source, target):
    target.brushes = ['Native Independent Copy']
linked = target.brushes[0]
linked_store = authoring.store(linked)
check('linked asset preserves native and generic authoring',
      linked_store.read_value(authoring.registry.get(STRENGTH)).value == .875
      and linked_store.read_stack(authoring.registry.get(SIZE))[0].curve.owner_identity == linked_store.identity)
before = linked[ROOT].to_dict()
try:
    linked_store.write_stack(authoring.registry.get(SIZE), ())
except PropertyError:
    pass
else:
    raise AssertionError('linked asset accepted stack edit')
check('readonly native edit leaves complete metadata intact', linked[ROOT].to_dict() == before)
bpy.data.brushes.remove(linked)
with bpy.data.libraries.load(str(asset), link=False) as (source, target):
    target.brushes = ['Native Independent Copy']
editable = target.brushes[0]
assert editable.library is None
edited = authoring.store(editable)
edited.write_value(authoring.registry.get(STRENGTH), .625)
check('editable appended asset writes native value', editable.strength == .625)
check('editable asset retains custom payload', edited.read_stack(authoring.registry.get(SIZE))[0].device == 'TILT_X')
(root / 'plan4-native-adapters-fresh.checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('NATIVE_ADAPTERS_FRESH_OK', len(checks), flush=True)
