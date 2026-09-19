# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fresh reload/linked reads of frozen authoring and actual clean external assets."""
import json
from pathlib import Path
import bpy
from sculptcore_addon.brush_properties import authoring, legacy, migration
from sculptcore_addon.brush_properties.registry import PropertyError, scalar
from sculptcore_addon.brush_properties.resolver import resolve
from sculptcore_addon.brush_properties.storage import ROOT

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-frozen'
bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'frozen.blend'))
nu = authoring.registry.get('sculptcore.kernel.kelvinlet.nu')
brush = bpy.data.brushes['GenericLegacyV0']
assert authoring.store(brush).read_value(nu).value == scalar('FLOAT32', .3)
assert authoring.store(bpy.data.brushes['FrozenIndependentCopy']).read_value(nu).value == .125
assert authoring.store(bpy.data.scenes['FrozenSwitchFirst']).feature_enabled() is True
assert authoring.store(bpy.data.brushes['FrozenDoubleLegacy']).read_value(nu).value == nu.maximum
assert authoring.curve_bank.reference(authoring.store(brush), nu, 'SPEED').mapping_key[0] > 0
checks = ['fresh generic value', 'fresh independent copy', 'fresh saved readiness switch',
          'fresh raw DOUBLE frozen boundary', 'fresh missing-engine authored custom curve']
expected = json.loads((Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/baseline.json').read_text(
    encoding='utf-8'))['generated']
migrated = bpy.data.brushes['FrozenMigratedV1']
store = authoring.store(migrated)
for definition in legacy.DEFINITIONS:
    name = legacy.ASSOCIATIONS[definition.identifier][1]
    assert store.read_value(definition).present == expected[name]['set']
    assert resolve(authoring.registry, definition.identifier, store).value == expected[name]['value']
checks.append('fresh migrated authored presence and frozen values')
token = migrated.authoring_edit_begin(undo=False)
assert migration.migrate(store) == ()
assert not migrated.authoring_edit_commit(token)
checks.append('fresh migration is an authoring no-op')
changed_store = authoring.store(bpy.data.brushes['FrozenChangedDefaults'])
assert all(not changed_store.read_value(item).present
           and resolve(authoring.registry, item.identifier, changed_store).value == item.default
           for item in legacy.DEFINITIONS)
checks.append('fresh changed-DLL defaults stayed unset')
assert authoring.store(bpy.data.brushes['FrozenMissingEngineMigration']).read_value(nu).value == scalar('FLOAT32', .3)
checks.append('fresh missing-engine migration')

library = Path(__file__).resolve().parents[1] / 'tests/generic-brush-v0/library'
files = sorted(library.rglob('*.blend'))
assert files, library
with bpy.data.libraries.load(str(files[0]), link=True) as (source, target):
    target.brushes = source.brushes[:1]
linked = target.brushes[0]
assert linked.library and not linked.is_editable
store = authoring.store(linked)
before = linked.has_unsaved_changes
for _ in range(5):
    for definition in authoring.DEFINITIONS:
        store.read_value(definition)
assert linked.has_unsaved_changes == before
checks.append('fresh linked asset reads preserve dirty state')
try:
    migration.migrate(store)
except PropertyError:
    pass
else:
    raise AssertionError('Migration accepted a linked legacy asset')
assert linked.has_unsaved_changes == before and ROOT not in linked
checks.append('linked migration refuses writes without dirtying')
bpy.data.brushes.remove(linked)
with bpy.data.libraries.load(str(files[0])) as (source, target):
    target.brushes = source.brushes[:1]
editable = target.brushes[0]
assert editable.library is None and editable.is_editable
before = editable.has_unsaved_changes
for definition in authoring.DEFINITIONS:
    authoring.store(editable).read_value(definition)
assert editable.has_unsaved_changes == before
checks.append('editable imported asset reads preserve dirty state')
(DIRECTORY / 'fresh.json').write_text(json.dumps(checks, indent=2))
print('FROZEN_FRESH_OK', len(checks), flush=True)
