# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Production authoring lifecycle and transient manifest readiness, independent of the engine."""

from types import MappingProxyType

from .curves import CurveBank
from .legacy import ASSOCIATIONS, DEFINITIONS
from .lifecycle import _main_thread
from .adapters import DEFINITIONS as NATIVE_DEFINITIONS
from .engine_catalogue import DEFINITIONS as ENGINE_DEFINITIONS
from .registry import PropertyError, Registry
from .shift_smooth import DEFINITIONS as SHIFT_SMOOTH_DEFINITIONS

registry = Registry()
for _definition in (*DEFINITIONS, *NATIVE_DEFINITIONS, *ENGINE_DEFINITIONS, *SHIFT_SMOOTH_DEFINITIONS):
    registry.register(_definition)
curve_bank = CurveBank(registry)
_manifest_status = MappingProxyType({})
_execution_ready = False


def register():
    curve_bank.register()
    from . import migration
    migration.register()


def unregister():
    global _manifest_status, _execution_ready
    from . import migration
    migration.unregister()
    curve_bank.unregister()
    _manifest_status = MappingProxyType({})
    _execution_ready = False


def refresh_manifest(rows, *, execution_ready=False):
    """Publish validated declarations and the installed consumer capability together."""
    _main_thread()
    global _manifest_status, _execution_ready
    if type(execution_ready) is not bool:
        raise PropertyError("Execution readiness must be boolean")
    if type(rows) not in (list, tuple):
        raise PropertyError("Manifest snapshot must be a list or tuple")
    received = {}
    for row in rows:
        if type(row) is not tuple or len(row) != 3:
            raise PropertyError("Manifest rows require (stable ID, scalar type, dynamic)")
        identifier, kind, dynamic = row
        if (type(identifier) is not str or type(kind) is not str or kind not in ('FLOAT32', 'INT32', 'BOOL')
                or type(dynamic) is not bool or identifier in received):
            raise PropertyError("Invalid or duplicate manifest contract")
        received[identifier] = (kind, dynamic)
    status = {}
    for definition in DEFINITIONS:
        entry = received.get(definition.identifier)
        status[definition.identifier] = ('kernel_unavailable' if entry is None else
                                         'manifest_contract_mismatch' if entry != (definition.scalar_type,
                                                                                 definition.dynamic) else
                                         '' if execution_ready else 'generic_execution_adapter_pending')
    _manifest_status = MappingProxyType(status)
    _execution_ready = execution_ready
    return _manifest_status


def diagnostic(identifier):
    _main_thread()
    if identifier in ASSOCIATIONS:
        return _manifest_status.get(identifier, 'kernel_unavailable')
    return '' if _execution_ready else 'generic_execution_adapter_pending'


def store(owner, *, epoch=0):
    from .storage import PersistentOwnerStore
    return PersistentOwnerStore(owner, registry, epoch=epoch, curve_bank=curve_bank,
                                execution_diagnostic=diagnostic)
