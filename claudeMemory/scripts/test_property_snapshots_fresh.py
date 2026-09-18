# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Saved generic engine fields and repeated DLL-off production registration."""
import json
from pathlib import Path
from unittest.mock import patch

import bpy
import sculptcore_addon as addon
from sculptcore_addon.brush_properties import authoring, legacy
from sculptcore_addon.brush_properties.curves import declaration_name
from sculptcore_addon.brush_properties.engine_catalogue import DEFINITIONS
from sculptcore_addon.brush_properties.snapshots import capture
from sculptcore_addon.brush_properties.storage import ROOT

OUT = Path(__file__).resolve().parents[1] / 'tests'
checks = []
ids = tuple(item.identifier for item in DEFINITIONS)
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'plan6-snapshots.blend'))
brush = bpy.data.brushes['Plan6Snapshot']
scene = bpy.context.scene
local, parent = authoring.store(brush), authoring.store(scene)
snapshot = capture(authoring.registry, ids, local, parent)
assert tuple(item.value for item in snapshot) == (False, .75, .75, False)
assert tuple(local.read_value(item).value for item in DEFINITIONS) == (True, .25, .25, True)
checks.append('fresh process preserves overrides, inheritance and dormant local values')
assert authoring.DEFINITIONS is legacy.DEFINITIONS
assert set(authoring.refresh_manifest([])) == {item.identifier for item in legacy.DEFINITIONS}
checks.append('legacy manifest catalogue remains separate')
for definition in DEFINITIONS:
    for owner_type in (bpy.types.Brush, bpy.types.Scene):
        for device in ('PRESSURE', 'TILT_X', 'TILT_Y', 'SPEED'):
            assert not hasattr(owner_type, declaration_name(definition.identifier, device))
checks.append('static fields declare no custom curves')
addon.unregister()
with patch.object(addon.engine, 'capi', side_effect=RuntimeError('Engine deliberately unavailable')), \
        patch.object(addon.engine_props, '_walk_manifests', side_effect=RuntimeError('No manifest')):
    for index in range(2):
        addon.register()
        authoring.register()
        assert len(authoring.registry.definitions()) == 27 and len(authoring.curve_bank._entries) == 62
        fresh = bpy.data.brushes.new('Plan6DllOff{}'.format(index), mode='SCULPT')
        result = capture(authoring.registry, ids, authoring.store(fresh))
        assert tuple(item.value for item in result) == tuple(item.default for item in DEFINITIONS)
        assert all(not item.present and not item.execution_available and item.stack == () for item in result)
        assert ROOT not in fresh
        persisted = capture(authoring.registry, ids, authoring.store(brush), authoring.store(scene))
        assert tuple(item.value for item in persisted) == (False, .75, .75, False)
        bpy.data.brushes.remove(fresh)
        addon.unregister()
        checks.append('DLL-off registration/defaults/persisted reads cycle {}'.format(index))
addon.register()
(OUT / 'plan6-snapshots-fresh.checks.json').write_text(json.dumps(dict(passed=True, checks=checks), indent=2))
print('PLAN6_SNAPSHOTS_FRESH_PASS', len(checks), flush=True)
