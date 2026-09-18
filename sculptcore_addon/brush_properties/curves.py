# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit shared declarations for owner-aware mappings; no engine dependency."""

import base64
from dataclasses import dataclass
import hashlib
import itertools

from .lifecycle import _main_thread
from .registry import CustomCurveReference, DEVICE_TYPES, PropertyError

_generations = itertools.count(1)
_leases = {}


def declaration_name(identifier, device):
    digest = hashlib.sha256((identifier + '\0' + device).encode('utf-8')).digest()
    return 'sc_curve_' + base64.b32encode(digest).decode('ascii').rstrip('=').lower()


@dataclass
class _Lease:
    contract: tuple
    token: int
    count: int = 0


def _key(owner_type, name):
    import bpy
    try:
        return bpy.props.curve_mapping_declaration_key(owner_type, name)
    except (ValueError, TypeError, RuntimeError) as error:
        raise PropertyError("Curve declaration is unavailable: " + name) from error


class CurveBank:
    """A registered snapshot; unrelated banks can share identical declarations safely."""

    def __init__(self, registry):
        self.registry = registry
        self._entries = {}
        self._definitions = {}
        self._generation = 0

    def register(self):
        _main_thread()
        import bpy
        if self._generation:
            if self._definitions != {item.identifier: item for item in self.registry.definitions()}:
                raise PropertyError("Registry changed; unregister this bank before registering its new snapshot")
            for (owner_type, name), lease in self._entries.items():
                if _key(owner_type, name) != lease.token:
                    raise PropertyError("Curve declaration was replaced externally")
            return
        if not callable(getattr(bpy.props, 'curve_mapping_declaration_key', None)):
            raise PropertyError("Owned curve declaration identity API is unavailable")
        definitions = {item.identifier: item for item in self.registry.definitions()}
        wanted = {}
        for definition in definitions.values():
            if not definition.dynamic:
                continue
            for kind in sorted(definition.owners):
                owner_type = bpy.types.Brush if kind == 'BRUSH' else bpy.types.Scene
                for device in DEVICE_TYPES:
                    if (kind == 'BRUSH' and device == 'PRESSURE' and definition.identifier in
                            ('sculptcore.brush.strength', 'sculptcore.brush.size')):
                        continue
                    name = declaration_name(definition.identifier, device)
                    entry, contract = (owner_type, name), (definition, device)
                    if entry in wanted and wanted[entry] != contract:
                        raise PropertyError("Curve declaration hash collision")
                    wanted[entry] = contract
                    lease = _leases.get(entry)
                    if lease is not None:
                        if lease.contract != contract or _key(owner_type, name) != lease.token:
                            raise PropertyError("Conflicting or externally replaced curve declaration")
                    elif hasattr(owner_type, name):
                        raise PropertyError("Curve declaration name is already in use")
        acquired, created = {}, set()
        try:
            for entry, contract in wanted.items():
                owner_type, name = entry
                lease = _leases.get(entry)
                if lease is None:
                    definition, device = contract
                    setattr(owner_type, name, bpy.props.CurveMappingProperty(
                        name=definition.label + ' ' + device, description=definition.description))
                    try:
                        lease = _Lease(contract, _key(owner_type, name))
                    except Exception:
                        # No callbacks run in our declaration constructor.
                        delattr(owner_type, name)
                        raise
                    _leases[entry] = lease
                    created.add(entry)
                lease.count += 1
                acquired[entry] = lease
        except Exception:
            self._release(acquired, remove=created)
            raise
        self._entries, self._definitions = acquired, definitions
        self._generation = next(_generations)

    @staticmethod
    def _release(entries, *, remove=None):
        for entry, lease in reversed(tuple(entries.items())):
            lease.count -= 1
            if lease.count:
                continue
            owner_type, name = entry
            if _leases.get(entry) is lease:
                del _leases[entry]
            if remove is not None and entry not in remove:
                continue
            try:
                current = _key(owner_type, name)
            except PropertyError:
                continue
            if current == lease.token:
                delattr(owner_type, name)

    def unregister(self):
        _main_thread()
        self._generation = 0
        entries, self._entries = self._entries, {}
        self._definitions = {}
        self._release(entries)

    def _target(self, store, definition, device):
        _main_thread()
        store._checked_definition(definition)
        if not self._generation or self._definitions.get(definition.identifier) != definition:
            raise PropertyError("Curve definition is not in the registered bank snapshot")
        if device not in DEVICE_TYPES:
            raise PropertyError("Unsupported curve device")
        import bpy
        owner_type = bpy.types.Brush if store.kind == 'BRUSH' else bpy.types.Scene
        name = declaration_name(definition.identifier, device)
        lease = self._entries.get((owner_type, name))
        if lease is None or lease.contract != (definition, device) or _key(owner_type, name) != lease.token:
            raise PropertyError("Curve declaration is unavailable or stale")
        return name, lease.token

    def reference(self, store, definition, device):
        name, token = self._target(store, definition, device)
        try:
            mapping = getattr(store.owner, name)
            if mapping is None:
                raise PropertyError("Custom mapping is absent; initialize explicitly")
            key = tuple(mapping.curve_mapping_cache_key())
        except (ReferenceError, ValueError, RuntimeError) as error:
            raise PropertyError("Custom mapping is invalid or stale") from error
        return CustomCurveReference(store.identity, definition.identifier, device, self._generation, token, key)

    def mapping(self, store, definition, reference):
        if type(reference) is not CustomCurveReference:
            raise PropertyError("Expected an owner-aware custom mapping reference")
        reference = CustomCurveReference(reference.owner_identity, reference.identifier, reference.device,
                                         reference.bank_generation, reference.declaration_key, reference.mapping_key)
        current = self.reference(store, definition, reference.device)
        if current != reference:
            raise PropertyError("Custom mapping reference is stale or belongs to another destination")
        return getattr(store.owner, declaration_name(definition.identifier, reference.device))

    def initialize(self, store, definition, device):
        store._write_allowed()
        store._stack_descriptions(definition)
        name, _ = self._target(store, definition, device)
        try:
            store.owner.curve_mapping_initialize(name, preset='LINEAR')
        except (ReferenceError, ValueError, RuntimeError, PermissionError) as error:
            raise PropertyError(str(error)) from error
        return self.reference(store, definition, device)

    def remove(self, store, definition, device):
        store._write_allowed()
        descriptions = store._stack_descriptions(definition)
        name, _ = self._target(store, definition, device)
        if any(item[0] == device and item[4] == 'CUSTOM' for item in descriptions):
            raise PropertyError("Custom mapping is selected by the local stack; deselect it first")
        try:
            mapping = getattr(store.owner, name)
            if mapping is not None:
                mapping.curve_mapping_cache_key()
                store.owner.property_unset(name)
        except (ReferenceError, ValueError, RuntimeError, PermissionError) as error:
            raise PropertyError(str(error)) from error
