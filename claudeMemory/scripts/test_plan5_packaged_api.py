# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise new response/bulk capabilities and replacement targets in the staged package."""
from contextlib import ExitStack
import json
import math
from pathlib import Path
import bpy
from sculptcore_addon import engine, mapping
from sculptcore_addon.brush_properties import sampling
from sculptcore.brush_properties import CommonProperties, DeviceLayer, replace_fixed_curve

checks = []
manager = engine.manager()
assert 'TYPEDPROBE' not in manager.get('sculptcore::brush::SculptBrushes').items
brush = bpy.data.brushes.new('PackagedResponse', mode='SCULPT')
brush.curve_distance_falloff_preset = 'CUSTOM'
brush.mesh_automasking_settings.use_automasking_cavity = True
brush.mesh_automasking_settings.use_automasking_custom_cavity_curve = True
memo = {}
with ExitStack() as owners:
    targets = [owners.enter_context(manager.construct('sculptcore::brush::Brush')) for _ in range(2)]
    for target in targets:
        access = CommonProperties(manager, target)
        access.write(0, 1)
        access.replace_stack(0, (DeviceLayer(0, mode=0, response_kind='TWO_STEP',
                                           parameters=(math.nextafter(.5, 1), .25, .75)),))
        target.pushDeviceInput(0, .5)
        assert access.read(0, evaluate=True) == .25
        target.pushDeviceInput(0, 1)
        assert access.read(0, evaluate=True) == .75
        access.write(5, False)
        access.replace_stack(5, (DeviceLayer(0, mode=0, response_kind='CONSTANT', parameters=(1,)),))
        assert access.read(5, evaluate=True) is True
        replace_fixed_curve(manager, target, 'falloff', (0.0,) * 256)
        replace_fixed_curve(manager, target, 'cavity', (1.0,) * 256)
        before = memo.get('table_uploads', 0)
        mapping._bake_falloff(brush, target, memo)
        mapping._apply_cavity(brush.mesh_automasking_settings, target, memo)
        assert memo['table_uploads'] == before + 2
        mapping._bake_falloff(brush, target, memo)
        mapping._apply_cavity(brush.mesh_automasking_settings, target, memo)
        assert memo['table_uploads'] == before + 2
        checks.append('packaged analytic and bulk API on target ' + str(len(checks)))
    assert memo['table_uploads'] == 4
    checks.append('new engine target receives cached falloff and cavity tables')
path = Path(__file__).resolve().parents[1] / 'tests/plan5-packaged-api.checks.json'
path.write_text(json.dumps(checks, indent=2) + '\n')
print('PLAN5_PACKAGED_API_PASS', flush=True)
