# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only v0 generated-property translation; never import a DLL or author data."""

from types import MappingProxyType

from .frozen_v0 import LEGACY_ROWS
from .registry import Definition, PropertyError, scalar
from .resolver import ValueSource

DEFINITIONS = tuple(Definition(identifier, name, 'FLOAT32', default, minimum, maximum, soft_min, soft_max,
                               description, unit, dynamic)
                    for identifier, kernel, name, default, minimum, maximum, soft_min, soft_max,
                    description, unit, dynamic in LEGACY_ROWS)
ASSOCIATIONS = MappingProxyType({row[0]: (row[1], row[2]) for row in LEGACY_ROWS})
BY_ID = MappingProxyType({item.identifier: item for item in DEFINITIONS})


def read_value(store, definition):
    """Fallback only when no explicit generic value exists; no migration occurs."""
    association = ASSOCIATIONS.get(definition.identifier)
    if association is None or store.kind != 'BRUSH':
        return ValueSource()
    store._guard.check()
    reader = getattr(store.owner, 'system_property_scalar', None)
    if not callable(reader):
        raise PropertyError("Nonmutating legacy property inspection API is unavailable")
    try:
        present, kind, value = reader(('sculptcore', association[1]))
    except (ValueError, TypeError, ReferenceError, RuntimeError) as error:
        raise PropertyError("Legacy scalar cannot be inspected: " + association[1]) from error
    if not present:
        return ValueSource(source='LEGACY')
    if kind not in ('FLOAT', 'DOUBLE'):
        raise PropertyError("Legacy float has incompatible raw storage; data preserved")
    # RNA accepts DOUBLE backing and converts it once to its FLOAT property type.
    value = definition.validate(scalar('FLOAT32', value))
    return ValueSource(value, True, 'LEGACY')
