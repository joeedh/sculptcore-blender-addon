# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit, atomic v0 import and raw legacy synchronization, independent of a DLL.

This is an authoring operation, never a side effect of resolving or drawing.
Active editable assets migrate in memory; only explicit asset saves persist them.
"""

from . import legacy
from .registry import PropertyError, scalar
from .storage import ROOT, SCHEMA_VERSION, _group, _root, record_key, value_metadata

VERSION = 1
FIELD = 'legacy_migration'
_active = set()
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


def state(root):
    if root is None or FIELD not in root:
        return None
    value = root[FIELD]
    if (not _group(value) or type(value.get('version')) is not int or value['version'] != VERSION):
        raise PropertyError("Unsupported legacy migration version; data preserved")
    if not _group(value.get('sources')):
        raise PropertyError("Malformed legacy migration sources; data preserved")
    return value


def operations(store, *, force=()):
    """Import missing values, or fan out subsequent raw edits, in one transaction.

Return changed names and their atomic operations. Unset is absence of ``value``, retaining the
frozen definition default. Initial import preserves pre-existing generic values;
a later changed legacy name explicitly replaces all its associated local values.
Native settings, metadata, curves and the raw legacy group are never rewritten.
The caller may append an independent generic edit to the same transaction.
"""
    store._guard.check()
    if store.kind != 'BRUSH':
        raise PropertyError("Legacy generated settings belong to Brush")
    root = _root(store.owner)
    previous_state = state(root)
    records = {definition.identifier: store._checked_definition(definition)
               for definition in legacy.DEFINITIONS}
    sources = {name: _source(store.owner, name) for name in BY_NAME}
    previous = ({name: _saved_source(previous_state['sources'], name) for name in BY_NAME}
                if previous_state is not None else {})
    changed = tuple(name for name, source in sources.items()
                    if name in force or previous.get(name) != source)
    if not changed:
        return (), ()
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
            if previous_state is None and name not in force and record is not None and 'value' in record:
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
    return changed, tuple(operations)


def migrate(store, *, force=()):
    """Synchronize editable legacy data; repeated unchanged calls publish nothing."""
    changed, updates = operations(store, force=force)
    if not updates:
        return ()
    try:
        store.owner.id_properties_update_atomic(ROOT, updates)
    except (ValueError, TypeError, OverflowError, PermissionError) as error:
        raise PropertyError(str(error)) from error
    return changed


def activate(context):
    """Check only active SculptCore brushes, including assets selected after load."""
    from . import authoring
    obj = context.active_object
    sculpt = context.tool_settings.sculpt
    if (obj is None or obj.mode != 'CUSTOM' or obj.custom_mode != 'sculptcore.sculpt'
            or not context.scene.sculptcore_generic_properties or sculpt is None or sculpt.brush is None):
        return None
    brush = sculpt.brush
    key = (context.scene.session_uid, brush.session_uid)
    root = _root(brush)
    if key not in _active or (root is not None and FIELD in root):
        store = authoring.store(brush)
        if store.editable:
            from .edits import _active as edits
            if store.identity in edits:
                return key
            migrate(store)
        _active.add(key)
    return key


def _tick():
    import bpy
    visible = set()
    for window in bpy.context.window_manager.windows:
        with bpy.context.temp_override(window=window):
            try:
                key = activate(bpy.context)
                if key is not None:
                    visible.add(key)
            except (PropertyError, ReferenceError) as error:
                # Execution/rows retain their own diagnostics. Do not repeatedly
                # mutate or log a malformed asset from a timer.
                brush = bpy.context.tool_settings.sculpt.brush
                if brush is not None:
                    key = (window.scene.session_uid, brush.session_uid)
                    visible.add(key)
                    if key not in _active:
                        print("SculptCore brush migration: " + str(error))
                        _active.add(key)
    _active.intersection_update(visible)
    return .25


def _loaded(*_args):
    _active.clear()


def register():
    import bpy
    bpy.app.handlers.persistent(_loaded)
    if _loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_loaded)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=.25, persistent=True)


def unregister():
    import bpy
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    _active.clear()
