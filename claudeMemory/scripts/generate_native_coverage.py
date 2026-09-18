# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Account for every inventory owner/path without collapsing shared stable IDs."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'claudeMemory/design/generic-brush-inventory-v1.json'
inventory = json.loads(source.read_text(encoding='utf-8'))
rows = []
for entry in inventory['rows']:
    path = entry['path']
    status = 'supported' if entry['supported'] else 'preserved_excluded'
    if not entry['supported']:
        adapter = 'none'
        gate = 'inventory_exclusion_preserved'
    elif path.startswith('Texture.'):
        adapter = 'retained_texture_resource'
        gate = 'native_inventory_rna_coverage'
    elif path.startswith('Brush.texture_slot.'):
        adapter = 'bindings.texture_slot_binding'
        gate = 'native_inventory_rna_coverage'
    elif path.startswith('Brush.sculptcore.'):
        adapter = 'legacy.read_value'
        gate = 'frozen_authoring'
    elif '.cavity_curve' in path:
        adapter = 'bindings.binding:cavity_curve'
        gate = 'native_adapters'
    elif '.mesh_automasking_settings.' in path:
        adapter = 'NativeOwner:compound_cavity'
        gate = 'native_adapters'
    elif 'pressure_' in path or path in ('Brush.curve_size', 'Brush.curve_strength'):
        adapter = 'NativeOwner:pressure'
        gate = 'native_adapters'
    elif path.endswith(('size', 'strength', 'use_unified_size', 'use_unified_strength')):
        adapter = 'NativeOwner:coupled_size_strength'
        gate = 'native_adapters'
    elif path.rsplit('.', 1)[-1] in ('spacing', 'plane_offset', 'crease_pinch_factor', 'hardness',
                                    'auto_smooth_factor', 'use_accumulate', 'use_space_attenuation'):
        adapter = 'NativeOwner:scalar'
        gate = 'native_adapters'
    else:
        adapter = 'bindings.binding:retained_native'
        gate = 'native_inventory_rna_coverage'
    rows.append(dict(owner=entry['owner'], path=path, stable_ids=entry['stable_ids'], status=status,
                     adapter=adapter, gate=gate, classification=entry['classification'],
                     compatibility=entry['migration']))
assert len({(row['owner'], row['path']) for row in rows}) == len(rows)
result = dict(schema_version=1, inventory_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              counts=dict(collections.Counter(row['status'] for row in rows)), rows=rows)
target = ROOT / 'claudeMemory/design/generic-brush-native-coverage-v1.json'
target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(result['counts'])
