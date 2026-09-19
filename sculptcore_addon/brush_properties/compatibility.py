# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Frozen public RNA aliases and non-mutating overlays for pending raw edits."""

from . import legacy
from .registry import PropertyError, scalar
from .resolver import ValueSource


def overlay(store, definition):
    """Return a pending legacy value, or None to read independent data."""
    association = legacy.ASSOCIATIONS.get(definition.identifier)
    if store.kind != 'BRUSH' or association is None:
        return None
    from . import migration
    from .storage import _root
    name = association[1]
    root = _root(store.owner)
    state = migration.state(root)
    if state is None:
        return None
    sources = state['sources']
    old = migration._saved_source(sources, name)
    current = migration._source(store.owner, name)
    if old == current:
        return None
    return (ValueSource(definition.validate(scalar('FLOAT32', current[2])), True, 'LEGACY')
            if current[0] else ValueSource(source='LEGACY'))


def callbacks(name):
    """Transforms keep real RNA storage, public paths and authored presence."""
    def get_transform(group, value, is_set):
        from . import migration
        from .storage import _root, record_key
        from ..mapping import KERNEL_BY_TYPE
        owner = group.id_data
        # RNA getters also run in driver evaluation and temporary Mains. Read
        # only the supplied ID's scalar storage; never resolve Main or mutate it.
        kernel = KERNEL_BY_TYPE.get(owner.sculpt_brush_type)
        definition = next((item for item in legacy.DEFINITIONS
                           if legacy.ASSOCIATIONS[item.identifier] == (kernel, name)), None)
        if definition is None:
            return value
        root = _root(owner)
        if root is None:
            return value
        state = migration.state(root)
        if state is not None:
            previous = migration._saved_source(state['sources'], name)
            if previous[0] != is_set or (is_set and previous[2] != group.get(name)):
                return value if is_set else definition.default
        record = root.get('records', {}).get(record_key(definition.identifier))
        if record is not None and (not hasattr(record, 'get') or record.get('identifier') != definition.identifier
                                   or record.get('scalar_type') != definition.scalar_type):
            raise PropertyError("Mismatched generic property record identity or type")
        if record is not None and 'value' in record:
            return definition.validate(record['value'])
        return value if is_set else definition.default

    def update(group, context):
        from . import authoring, migration
        from .storage import ROOT
        owner = group.id_data
        if not owner.is_evaluated and ROOT in owner:
            migration.migrate(authoring.store(owner), force=(name,))

    return dict(get_transform=get_transform, update=update)
