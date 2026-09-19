# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Non-allocating placement and applicability for every generic UI location."""
from .adapters import CAVITY, SIZE_ALIASES
from .legacy import ASSOCIATIONS
from .registry import Position

LOCATIONS = (
    ('VIEW3D_HEADER', "Tool Header"),
    ('BRUSH_SETTINGS', "Brush Settings"),
    ('CONTEXT_MENU', "Context Menu"),
    ('AUTOMASKING', "Automasking"),
)


def automasking(identifier):
    from .engine_catalogue import DEFINITIONS
    return identifier.startswith(CAVITY + '.') or identifier in {item.identifier for item in DEFINITIONS}


def applicable(definition, brush):
    from ..mapping import KERNEL_BY_TYPE
    identifier = definition.identifier
    if identifier in SIZE_ALIASES:
        return False
    association = ASSOCIATIONS.get(identifier)
    if association:
        return association[0] in (KERNEL_BY_TYPE.get(brush.sculpt_brush_type), 'BSMOOTH')
    if identifier == 'sculptcore.brush.snake_pinch':
        return brush.sculpt_brush_type == 'SNAKE_HOOK'
    if identifier == 'sculptcore.brush.plane_offset':
        return brush.sculpt_brush_type in ('CLAY', 'CLAY_STRIPS', 'CLAY_THUMB', 'FLATTEN', 'FILL', 'SCRAPE')
    return True


def positions(store, definition):
    saved = store.read_positions(definition)
    # A saved empty list is an explicit placement choice. Defaults below augment
    # the frozen definitions without changing their serialized contract identity.
    record = store._record(definition.identifier)
    if record is not None and 'positions_version' in record:
        return saved
    if automasking(definition.identifier):
        return (Position('AUTOMASKING', 50),)
    if definition.identifier in ('sculptcore.brush.size', 'sculptcore.brush.strength'):
        return (*saved, Position('CONTEXT_MENU', 10 if definition.identifier.endswith('.size') else 20))
    result = saved or (Position('BRUSH_SETTINGS', 100),)
    if definition.identifier in ('sculptcore.brush.autosmooth', 'sculptcore.brush.snake_pinch',
                                  'sculptcore.brush.plane_offset'):
        result += (Position('CONTEXT_MENU', 30),)
    return result


def located(store, location):
    result = []
    for definition in store.registry.definitions():
        if applicable(definition, store.owner):
            for position in positions(store, definition):
                if position.location == location:
                    result.append((position.sort_index, definition.identifier, definition))
    return tuple(item[2] for item in sorted(result))
