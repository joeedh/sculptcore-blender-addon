# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Owner-pinned edits shared by numeric rows, radial controls and size shortcuts.

An edit pins its owner for one gesture and restores it on cancellation; it
pushes no undo step (see `edits.authoring_edit`).
"""
from . import authoring
from .edits import authoring_edit
from .registry import PropertyError, finite
from .resolver import resolve_value


def owners(context):
    sculpt = context.tool_settings.sculpt
    brush = sculpt.brush if sculpt else None
    if brush is None:
        raise PropertyError("Select a sculpt brush first")
    return authoring.store(brush), authoring.store(context.scene)


class ValueEdit:
    """One gesture and one owner; cancellation restores coupled values."""

    def __init__(self, context, identifier):
        self.local, self.parent = owners(context)
        self.resolved = resolve_value(authoring.registry, identifier, self.local, self.parent)
        self.owner = self.resolved.value_owner
        if not self.owner.editable:
            raise PropertyError("The effective owner is read-only; save an editable copy")
        self.identifier = identifier
        self.initial = self.resolved.value
        self.domain = self.resolved.value_domain
        self.kind = getattr(self.domain, 'kind', self.resolved.definition.scalar_type)
        self.scope = None

    def check(self, context):
        local, parent = owners(context)
        if (local.identity, parent.identity) != (self.local.identity, self.parent.identity):
            raise PropertyError("Brush or scene changed during the edit")
        current = resolve_value(authoring.registry, self.identifier, local, parent)
        if current.value_owner.identity != self.owner.identity or current.value_domain != self.domain:
            raise PropertyError("Property owner or size mode changed during the edit")
        self.owner._guard.check(write=True)

    def begin(self):
        if self.scope is not None:
            raise PropertyError("The property gesture is already active")
        self.scope = authoring_edit(self.owner, "Edit " + self.resolved.definition.label)
        self.scope.__enter__()

    def write(self, context, value):
        self.check(context)
        if self.scope is None:
            raise PropertyError("Begin the property gesture before writing")
        self.owner.write_value(self.resolved.definition, value)

    def finish(self, *, cancel=False):
        scope, self.scope = self.scope, None
        if scope is None:
            return
        if cancel:
            error = _Cancelled()
            scope.__exit__(_Cancelled, error, None)
        else:
            scope.__exit__(None, None, None)

    def set(self, context, value):
        self.begin()
        try:
            self.write(context, value)
        except BaseException:
            self.finish(cancel=True)
            raise
        self.finish()

    def scaled(self, factor):
        return self.bounded(self.initial * factor)

    def bounded(self, value):
        if not finite(value):
            raise PropertyError("Enter a finite number")
        value = min(self.domain.maximum, max(self.domain.minimum, value))
        if self.kind == 'INT32':
            value = int(value + .5)
        return value


class _Cancelled(Exception):
    pass
