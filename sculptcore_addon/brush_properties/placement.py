# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Non-allocating placement and applicability for every generic UI location."""
from . import shift_smooth
from .adapters import CAVITY, SIZE_ALIASES
from .legacy import ASSOCIATIONS
from .registry import Position

LOCATIONS = (
    ('VIEW3D_HEADER', "Tool Header"),
    ('BRUSH_SETTINGS', "Brush Settings"),
    ('CONTEXT_MENU', "Context Menu"),
    ('AUTOMASKING', "Automasking"),
    ('SHIFT_SMOOTH', "Shift Smooth"),
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
        return brush.sculpt_brush_type in PINCH_FACTOR_TYPES
    if identifier == shift_smooth.RAKE:
        return KERNEL_BY_TYPE.get(brush.sculpt_brush_type) == 'FEATURE_ALIGN'
    if identifier == 'sculptcore.brush.plane_offset':
        return brush.sculpt_brush_type in PLANE_OFFSET_TYPES
    gate = PLANE_FRAME_ROWS.get(identifier)
    if gate is not None:
        return brush.sculpt_brush_type in gate
    return True


# Vanilla's `supports_plane_offset` (the FLATTEN/FILL/SCRAPE types folded into
# PLANE in 5.x).
PLANE_OFFSET_TYPES = ('CLAY', 'CLAY_STRIPS', 'CLAY_THUMB', 'PLANE')
# The plane-frame rows show where the engine policy reads them
# (mapping.plane_frame): vanilla's own gates, minus the types whose policy
# fixes the value (MULTIPLANE_SCRAPE's forced AREA normal, PLANE's ignored
# Original toggles).
PLANE_FRAME_ROWS = {
    'sculptcore.brush.original_normal': ('CLAY', 'CLAY_STRIPS'),
    'sculptcore.brush.original_plane': ('CLAY', 'CLAY_STRIPS'),
    'sculptcore.brush.normal_radius_factor': ('CLAY', 'CLAY_STRIPS', 'PLANE', 'MULTIPLANE_SCRAPE'),
    'sculptcore.brush.area_radius_factor': ('PLANE',),
    'sculptcore.brush.stabilize_normal': ('PLANE',),
    'sculptcore.brush.stabilize_plane': ('PLANE',),
    # Vanilla's `supports_plane_height` / `supports_plane_depth` (PLANE only)
    # and `supports_tip_roundness` (the cube-tip types, mapping.TIP_SHAPE_TYPES).
    'sculptcore.brush.plane_height': ('PLANE',),
    'sculptcore.brush.plane_depth': ('PLANE',),
    'sculptcore.brush.tip_roundness': ('CLAY_STRIPS', 'PAINT'),
    'sculptcore.brush.tip_scale_x': ('CLAY_STRIPS', 'PAINT'),
}
SCULPT_PLANE_TYPES = ('CLAY', 'CLAY_STRIPS', 'PLANE')
# Vanilla's `supports_pinch_factor` minus Blob's sibling Crease's own reading:
# the one crease_pinch_factor row serves Snake Hook (remapped) and the crease
# kernel's signed square (stroke_runtime._brush_extras).
PINCH_FACTOR_TYPES = ('SNAKE_HOOK', 'CREASE', 'BLOB')
# The plane brush's inversion mode (a retained native enum, mapping.plane_swap_on_invert).
PLANE_INVERSION_TYPES = ('PLANE',)


def positions(store, definition):
    saved = store.read_positions(definition)
    # A saved empty list is an explicit placement choice. Defaults below augment
    # the frozen definitions without changing their serialized contract identity.
    record = store._record(definition.identifier)
    if record is not None and 'positions_version' in record:
        return saved
    if automasking(definition.identifier):
        from .automasking_ui import ORDER
        return (Position('AUTOMASKING', ORDER.index(definition.identifier) * 10),)
    if definition.identifier in shift_smooth.ORDER:
        return (Position('SHIFT_SMOOTH', shift_smooth.ORDER.index(definition.identifier) * 10),)
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
