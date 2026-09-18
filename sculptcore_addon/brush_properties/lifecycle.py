# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Operation-scoped owner handles, invalidated independently of the engine."""

import threading

from .registry import PropertyError

_generation = 0
_registered = False
_handler_lists = ()


def _main_thread():
    if threading.current_thread() is not threading.main_thread():
        raise PropertyError("Brush property access requires the main thread")


def _invalidate(*_args):
    global _generation
    _generation += 1
    from . import sampling
    sampling.clear()


def _restoration_revision(owner):
    if not hasattr(owner, 'authoring_revision'):
        return 0
    try:
        return owner.authoring_revision()
    except (ValueError, PermissionError) as error:
        raise PropertyError("Brush property owner is not an accessible original Main ID") from error


def register():
    """No saved data, declarations or engine imports are needed for lifetime tracking."""
    global _registered, _handler_lists
    _main_thread()
    if _registered:
        return
    import bpy
    handlers = bpy.app.handlers
    names = ('undo_pre', 'undo_post', 'redo_pre', 'redo_post',
             'load_pre', 'load_post', 'load_post_fail')
    _handler_lists = tuple(getattr(handlers, name) for name in names)
    handlers.persistent(_invalidate)
    for callbacks in _handler_lists:
        if _invalidate not in callbacks:
            callbacks.append(_invalidate)
    _invalidate()
    _registered = True


def unregister():
    global _registered, _handler_lists
    _main_thread()
    _invalidate()
    _registered = False
    for callbacks in _handler_lists:
        if _invalidate in callbacks:
            callbacks.remove(_invalidate)
    _handler_lists = ()


class OwnerGuard:
    """Never retain a nested RNA pointer; validate the ID before each operation."""

    def __init__(self, owner, *, epoch):
        _main_thread()
        if not _registered:
            raise PropertyError("Brush property lifecycle is not registered")
        if type(epoch) is not int:
            raise PropertyError("Caller epoch must be an integer")
        self._generation = _generation
        self.owner = owner
        try:
            identifier = owner.bl_rna.identifier
            if identifier not in ('Brush', 'Scene'):
                raise PropertyError("Expected a native Brush or Scene")
            self.kind = identifier.upper()
            self._uid = int(owner.session_uid)
            self._restoration = _restoration_revision(owner)
        except (ReferenceError, AttributeError) as error:
            raise PropertyError("Brush property owner is no longer available") from error
        self._identity = (self._generation, epoch, self.kind, self._uid)
        self.check()

    def check(self, *, write=False):
        _main_thread()
        if not _registered or self._generation != _generation:
            raise PropertyError("Brush property owner handle is stale; resolve it again")
        import bpy
        try:
            owner = self.owner
            if _restoration_revision(owner) != self._restoration:
                raise PropertyError("Brush property owner was restored; resolve it again")
            if int(owner.session_uid) != self._uid or owner.is_evaluated:
                raise PropertyError("Brush property owner is not the original live ID")
            owners = bpy.data.brushes if self.kind == 'BRUSH' else bpy.data.scenes
            if not any(candidate == owner for candidate in owners):
                raise PropertyError("Brush property owner is not in the current Main")
            editable = owner.is_editable and owner.override_library is None
            if write and not editable:
                raise PropertyError("Brush property owner is read-only or an unsupported override")
            return editable
        except (ReferenceError, AttributeError) as error:
            raise PropertyError("Brush property owner is no longer available") from error

    @property
    def identity(self):
        self.check()
        return self._identity
