# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Public base lookup must not break independent mode or addon re-registration."""
import json
from pathlib import Path
import bpy
import sculptcore_addon

base = bpy.types.ObjectModeType
assert sculptcore_addon.SculptCoreMode.__bases__[0] is base


class BaseProbeOne(base):
    bl_idname = 'authoring.base_probe_one'
    bl_label = 'Base Probe One'
    bl_object_types = {'MESH'}


class BaseProbeTwo(base):
    bl_idname = 'authoring.base_probe_two'
    bl_label = 'Base Probe Two'
    bl_object_types = {'MESH'}


checks = []
for cycle in range(3):
    for cls in (BaseProbeOne, BaseProbeTwo):
        bpy.utils.register_class(cls)
        assert cls.__bases__[0] is bpy.types.ObjectModeType is base
    for cls in (BaseProbeTwo, BaseProbeOne):
        bpy.utils.unregister_class(cls)
        assert bpy.types.ObjectModeType is base
    sculptcore_addon.unregister()
    assert sculptcore_addon.SculptCoreMode.__bases__[0] is bpy.types.ObjectModeType
    sculptcore_addon.register()
    assert bpy.types.ObjectModeType is base
    checks.append('two independent modes and full addon cycle {}'.format(cycle))
path = Path(__file__).resolve().parents[1] / 'tests/plan4-object-mode-base.checks.json'
path.write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('OBJECT_MODE_BASE_OK', len(checks), flush=True)
