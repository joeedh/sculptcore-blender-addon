# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Blender response cache, customization, rollback and lifecycle gate."""
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch
import bpy
from sculptcore_addon.brush_properties.authoring import curve_bank as production_bank
production_bank.unregister()

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle, curves, sampling, customize
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.storage import PersistentOwnerStore
from generic_property_test_package.adapters import DEFINITIONS, STRENGTH
from generic_property_test_package.responses import SampleConfig

checks = []
def check(name, condition=True):
    assert condition, name
    checks.append(name)
    print('PLAN5_CHECK', name, flush=True)

def reject(name, action):
    try:
        action()
    except (PropertyError, ValueError, RuntimeError, OverflowError):
        check(name)
    else:
        raise AssertionError(name)

registry = Registry()
definition = registry.register(Definition('test.plan5', 'Response', 'FLOAT32', 1, -10, 10, 0, 1))
for item in DEFINITIONS:
    registry.register(item)
lifecycle.register()
bank = curves.CurveBank(registry)
bank.register()
def store(owner):
    return PersistentOwnerStore(owner, registry, curve_bank=bank)
brush = bpy.data.brushes.new('Plan5Curves', mode='SCULPT')
local = store(brush)
name = curves.declaration_name(definition.identifier, 'PRESSURE')
local.write_stack(definition, (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
layer = local.read_stack(definition)[0]
generated = sampling.resolved_response(local, definition, layer.curve)
check('generated response allocates no mapping', getattr(brush, name) is None)
check('identical preset shares immutable table', generated is sampling.cache.generated(ResponseCurve('SQUARE')))
customize.customize(local, definition, 'PRESSURE', undo=False)
mapping = getattr(brush, name)
check('customize seeds 256 points', len(mapping.curves[0].points) == 256)
check('custom seed matches preset', abs(mapping.curves[0].points[128].location.y - (128 / 255) ** 2) < 1e-7)
check('custom seed vector handles', all(p.handle_type == 'VECTOR' for p in mapping.curves[0].points))
reference = local.read_stack(definition)[0].curve
first = sampling.resolved_response(local, definition, reference)
bakes = sampling.cache.bakes
check('owned unchanged revision reuses samples', sampling.resolved_response(local, definition, reference) is first)
mapping.curves[0].points[3].select = not mapping.curves[0].points[3].select
reference = local.read_stack(definition)[0].curve
check('selection does not bake', sampling.resolved_response(local, definition, reference) is first
      and sampling.cache.bakes == bakes)
copy = brush.copy()
copy_store = store(copy)
check('copied owner shares canonical samples', sampling.resolved_response(
    copy_store, definition, copy_store.read_stack(definition)[0].curve) is first and sampling.cache.bakes == bakes)
mapping.curves[0].points[-1].location = (1, .75)
reject('old mapping reference rejects', lambda: sampling.resolved_response(local, definition, reference))
reference = local.read_stack(definition)[0].curve
changed = sampling.resolved_response(local, definition, reference)
print('EDIT_SAMPLE', changed.samples[-1], 'BAKES', bakes, sampling.cache.bakes, flush=True)
check('actual owned point edit bakes once', abs(changed.samples[-1] - .75) < 1e-5
      and sampling.cache.bakes == bakes + 1)
local.write_stack(definition, (DeviceLayer('PRESSURE', curve=ResponseCurve('ROOT')),))
customize.customize(local, definition, 'PRESSURE', undo=False)
check('CUSTOM restores dormant curve', getattr(brush, name).curves[0].points[-1].location.y == .75)
diagnostic = customize.customize(local, definition, 'PRESSURE', reseed=True,
                                 preset=ResponseCurve('TWO_STEP', (.5, -2, 3)), undo=False)
check('step reseed reports approximation', bool(diagnostic))
check('seed preserves out of range levels', not getattr(brush, name).use_clip
      and getattr(brush, name).curves[0].points[0].location.y == -2
      and getattr(brush, name).curves[0].points[-1].location.y == 3)
before = sampling.canonical_mapping(getattr(brush, name))
reject('overflow seed rejects before mutation', lambda: customize.customize(
    local, definition, 'PRESSURE', reseed=True, preset=ResponseCurve('CONSTANT', (1e100,)), undo=False))
check('overflow preserved mapping', before == sampling.canonical_mapping(getattr(brush, name)))
original_seed = customize._seed
def fail_seed(mapping, values):
    mapping.curves[0].points[-1].location = (1, .125)
    raise RuntimeError('injected seed failure')
with patch.object(customize, '_seed', fail_seed):
    reject('seed failure rolls back', lambda: customize.customize(
        local, definition, 'PRESSURE', reseed=True, preset=ResponseCurve('LINEAR'), undo=False))
local = store(brush)
check('rollback restores exact mapping', before == sampling.canonical_mapping(getattr(brush, name)))
strength = registry.get(STRENGTH)
brush.curve_strength.curves[0].points[-1].location = (1, .375)
local.write_stack(strength, (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
customize.customize(local, strength, 'PRESSURE', undo=False)
check('native pressure CUSTOM preserves dormant authority', brush.curve_strength.curves[0].points[-1].location.y == .375)
native = sampling.native_response(brush, 'curve_strength')
bakes = sampling.cache.bakes
check('native warm reuse', sampling.native_response(brush, 'curve_strength') is native)
brush.curve_strength.curves[0].points[-1].location = (1, .625)
edited_native = sampling.native_response(brush, 'curve_strength')
print('NATIVE_EDIT_SAMPLE', edited_native.samples[-1], 'BAKES', bakes, sampling.cache.bakes, flush=True)
check('native edit rebakes', abs(edited_native.samples[-1] - .625) < 1e-6
      and sampling.cache.bakes == bakes + 1)
mapping = getattr(brush, name)
for field, value in (('use_clip', True), ('clip_max_y', 2.0), ('extend', 'HORIZONTAL')):
    setattr(mapping, field, value)
    ref = local.read_stack(definition)[0].curve
    before_bakes = sampling.cache.bakes
    sampling.resolved_response(local, definition, ref)
    check('evaluation field invalidates ' + field, sampling.cache.bakes == before_bakes + 1)
active = sampling.native_response(brush, 'curve_strength')
for i in range(270):
    brush.curve_strength.curves[0].points[-1].location = (1, i / 300)
    sampling.native_response(brush, 'curve_strength')
check('cache and revision indices bounded', all(len(part) <= 256 for part in (
    sampling.cache.sources, sampling.cache.contents, sampling.cache.identities)))
check('eviction leaves active immutable response usable', abs(active.samples[-1] - .625) < 1e-6)
for i in range(270):
    copied = brush.copy()
    copied_store = store(copied)
    sampling.resolved_response(copied_store, definition, copied_store.read_stack(definition)[0].curve)
    bpy.data.brushes.remove(copied)
check('owner switching leaves bounded value-only indices', len(sampling.cache.sources) <= 256)
library = Path(__file__).resolve().parents[1] / 'tests/brush-cache-readonly.blend'
# This check owns its input; it must not depend on a prior headed undo run.
bpy.data.libraries.write(str(library), {brush})
with bpy.data.libraries.load(str(library), link=True) as (available, linked):
    linked.brushes = [brush.name]
readonly = linked.brushes[0]
check('read-only asset is actually linked', readonly.library is not None and not readonly.is_editable)
reject('read-only customization rejects', lambda: customize.customize(store(readonly), definition, 'PRESSURE', undo=False))
epoch = sampling.epoch
lifecycle._invalidate()
check('lifecycle clears samples and increments upload epoch', sampling.epoch == epoch + 1 and not sampling.cache.contents)
reject('lifecycle retires old store', lambda: local.read_stack(definition))
bank.unregister()
lifecycle.unregister()
target = Path(__file__).resolve().parents[1] / 'tests/plan5-curves.checks.json'
target.write_text(json.dumps(checks, indent=2) + '\n')
print('PLAN5_CURVES_PASSED', len(checks), flush=True)
