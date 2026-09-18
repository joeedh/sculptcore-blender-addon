# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate complete path-based coverage against the actual registered RNA."""
import hashlib
import json
from pathlib import Path
import bpy
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import BY_ID
from sculptcore_addon.brush_properties.bindings import RETAINED, binding, texture_slot_binding

root = Path(__file__).resolve().parents[1]
inventory_source = root / 'design/generic-brush-inventory-v1.json'
inventory = json.loads(inventory_source.read_text(encoding='utf-8'))
coverage = json.loads((root / 'design/generic-brush-native-coverage-v1.json').read_text(encoding='utf-8'))
assert coverage['inventory_sha256'] == hashlib.sha256(inventory_source.read_bytes()).hexdigest()
assert {(r['owner'], r['path']) for r in coverage['rows']} == {(r['owner'], r['path']) for r in inventory['rows']}
b = bpy.data.brushes.new('Native Coverage', mode='SCULPT')
local, parent = authoring.store(b), authoring.store(bpy.context.scene)
textures = {}
checks = []
for row in coverage['rows']:
    if row['status'] != 'supported':
        assert row['adapter'] == 'none' and row['compatibility']
        continue
    path = row['path']
    if path.startswith('Texture.'):
        _, kind, rest = path.split('.', 2)
        if kind not in textures:
            textures[kind] = bpy.data.textures.new('Coverage ' + kind, type=kind)
        target = textures[kind]
    elif path.startswith('Brush.'):
        target, rest = b, path.removeprefix('Brush.')
    elif path.startswith('Scene.'):
        target, rest = bpy.context.scene, path.removeprefix('Scene.')
    else:
        raise AssertionError(path)
    parts = rest.split('.')
    for part in parts[:-1]:
        target = getattr(target, part)
        assert target is not None, path
    assert parts[-1] in target.bl_rna.properties, path
    getattr(target, parts[-1])
    for identifier in row['stable_ids']:
        if identifier in BY_ID or identifier.startswith('sculptcore.kernel.'):
            assert authoring.registry.get(identifier)
        elif identifier in RETAINED or identifier.endswith(('.size_mode', '.cavity_curve')):
            binding(authoring.registry, identifier, local, parent).rna()
        else:
            raise AssertionError((path, identifier))
    if path.startswith('Brush.texture_slot.'):
        texture_slot_binding(local, parts[-1]).rna()
    checks.append(path)
assert len(checks) == coverage['counts']['supported']
(root / 'tests/plan4-native-inventory-coverage.checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('NATIVE_INVENTORY_COVERAGE_OK', len(checks), flush=True)
