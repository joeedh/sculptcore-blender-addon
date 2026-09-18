# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed manifest readiness must agree with checked runtime support."""
import json
from pathlib import Path
import bpy
from sculptcore_addon import engine_props
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE_ALIASES
from sculptcore_addon.brush_properties.resolver import resolve

brush = bpy.data.brushes.new('Readiness', mode='SCULPT')
local, parent = authoring.store(brush), authoring.store(bpy.context.scene)
results = {}
for definition in authoring.registry.definitions():
    result = resolve(authoring.registry, definition.identifier, local, parent)
    results[definition.identifier] = dict(ready=result.execution_available, diagnostics=result.diagnostics)
    assert result.execution_available == (definition.identifier not in SIZE_ALIASES), results
authoring.refresh_manifest(())
assert not resolve(authoring.registry, 'sculptcore.brush.strength', local, parent).execution_available
engine_props._walk_manifests()
assert resolve(authoring.registry, 'sculptcore.brush.strength', local, parent).execution_available
destination = Path(__file__).resolve().parents[1] / 'tests/plan6-execution-readiness.json'
destination.write_text(json.dumps(dict(passed=True, definitions=results), indent=2), encoding='utf-8')
print('PLAN6_EXECUTION_READINESS_PASS', flush=True)
