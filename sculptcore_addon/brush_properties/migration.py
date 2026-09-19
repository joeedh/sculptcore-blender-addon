# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit, atomic v0 import and raw legacy synchronization, independent of a DLL.

This is an authoring operation, never a side effect of resolving or drawing.
Activation and public RNA compatibility must use the same synchronization policy
before this operation can be enabled automatically during rollout.
"""

from . import legacy
from .registry import PropertyError, scalar
from .storage import ROOT, SCHEMA_VERSION, _group, _root, record_key, value_metadata

VERSION = 1
FIELD = 'legacy_migration'
BY_NAME = {
    name: tuple(definition for definition in legacy.DEFINITIONS
                if legacy.ASSOCIATIONS[definition.identifier][1] == name)
    for name in sorted({name for kernel, name in legacy.ASSOCIATIONS.values()})
}


def _source(owner, name):
    try:
        present, kind, value = owner.system_property_scalar(('sculptcore', name))
    except (ValueError, TypeError, ReferenceError, RuntimeError) as error:
        raise PropertyError("Legacy scalar cannot be inspected: " + name) from error
    if not present:
        return (False, '', 0.0)
    if kind not in ('FLOAT', 'DOUBLE'):
        raise PropertyError("Legacy float has incompatible raw storage; data preserved: " + name)
    # Keep the exact raw source for change detection, and validate its RNA value
    # against every frozen destination before publishing any part of migration.
    for definition in BY_NAME[name]:
        definition.validate(scalar('FLOAT32', value))
    return (True, kind, value)


def _saved_source(group, name):
    item = group.get(name)
    if not _group(item):
        raise PropertyError("Missing or malformed legacy migration source: " + name)
    result = (item.get('present'), item.get('kind'), item.get('value'))
    present, kind, value = result
    if (type(present) is not bool or type(kind) is not str or type(value) is not float
            or (present and kind not in ('FLOAT', 'DOUBLE'))
            or (not present and (kind != '' or value != 0.0))):
        raise PropertyError("Malformed legacy migration source: " + name)
    if present:
        for definition in BY_NAME[name]:
            definition.validate(scalar('FLOAT32', value))
    return result


def migrate(store):
    """Import missing values, or fan out subsequent raw edits, in one transaction.

Return the names imported/synchronized; unchanged repeated calls do not publish
or dirty the owner. Unset is represented by absence of ``value``, retaining the
frozen definition default. Initial import preserves pre-existing generic values;
a later changed legacy name explicitly replaces all its associated local values.
Native settings, metadata, curves and the raw legacy group are never rewritten.
Call within an authoring edit when an interactive operation needs undo grouping.
"""
    store._guard.check()
    if store.kind != 'BRUSH':
        raise PropertyError("Legacy generated settings belong to Brush")
    root = _root(store.owner)
    state = root.get(FIELD) if root is not None else None
    if root is not None and FIELD in root:
        if (not _group(state) or type(state.get('version')) is not int
                or state['version'] != VERSION):
            raise PropertyError("Unsupported legacy migration version; data preserved")
        if not _group(state.get('sources')):
            raise PropertyError("Malformed legacy migration sources; data preserved")
    records = {definition.identifier: store._checked_definition(definition)
               for definition in legacy.DEFINITIONS}
    sources = {name: _source(store.owner, name) for name in BY_NAME}
    previous = ({name: _saved_source(state['sources'], name) for name in BY_NAME}
                if state is not None else {})
    changed = tuple(name for name, source in sources.items() if previous.get(name) != source)
    if not changed:
        return ()
    store._write_allowed()
    operations = [
        ('SET', ('schema_version',), SCHEMA_VERSION, None),
        ('SET', (FIELD, 'version'), VERSION, None),
    ]
    for name in changed:
        present, kind, value = sources[name]
        for field, item in zip(('present', 'kind', 'value'), sources[name]):
            operations.append(('SET', (FIELD, 'sources', name, field), item, None))
        for definition in BY_NAME[name]:
            record = records[definition.identifier]
            if state is None and record is not None and 'value' in record:
                # A user may have authored independent v1 values while opt-in
                # was under development; import must not overwrite those edits.
                store.read_value(definition)
                continue
            prefix = ('records', record_key(definition.identifier))
            if present:
                operations.extend((
                    ('SET', (*prefix, 'identifier'), definition.identifier, None),
                    ('SET', (*prefix, 'scalar_type'), definition.scalar_type, None),
                    ('SET', (*prefix, 'value'), definition.validate(scalar('FLOAT32', value)),
                     value_metadata(definition)),
                ))
            elif record is not None and 'value' in record:
                operations.append(('DELETE', (*prefix, 'value')))
    try:
        store.owner.id_properties_update_atomic(ROOT, tuple(operations))
    except (ValueError, TypeError, OverflowError, PermissionError) as error:
        raise PropertyError(str(error)) from error
    return changed
