# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit grouped authoring edits; consuming operators must omit UNDO flags."""
from contextlib import contextmanager

from .registry import PropertyError

_active = {}


@contextmanager
def authoring_edit(store, name="Edit Brush Property", *, native_settings=True, undo=True):
    """Pin the resolved owner for the entire gesture, including cancellation."""
    store._guard.check(write=True)
    owner = store.owner
    key = store.identity
    if key in _active:
        raise PropertyError("An authoring edit is already active on this owner")
    try:
        token = owner.authoring_edit_begin(native_settings=native_settings, undo=undo)
    except (ValueError, TypeError, PermissionError) as error:
        raise PropertyError(str(error)) from error
    record = dict(owner=owner, token=token, native=native_settings, cancelled=False)
    _active[key] = record
    try:
        yield store
        if record['cancelled']:
            raise PropertyError("The grouped authoring edit was cancelled by a failed write")
        owner.authoring_edit_commit(token, name)
    except BaseException:
        # A stale token fails closed; do not silently discard failed restoration.
        if not record['cancelled']:
            owner.authoring_edit_cancel(token)
        raise
    finally:
        del _active[key]


@contextmanager
def rollback_edit(store):
    """Join a native outer scope, or create a rollback-only atomic write scope."""
    record = _active.get(store.identity)
    if record is None:
        with authoring_edit(store, native_settings=True, undo=False):
            yield
        return
    if not record['native'] or record['cancelled']:
        raise PropertyError("Native writes require an active native authoring scope")
    try:
        yield
    except BaseException:
        record['owner'].authoring_edit_cancel(record['token'])
        record['cancelled'] = True
        raise
