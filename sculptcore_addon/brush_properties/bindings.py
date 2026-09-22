# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Operation-scoped bindings for retained nonnumeric native widgets."""
from dataclasses import dataclass
from types import MappingProxyType

from .adapters import CAVITY, SIZE, STRENGTH
from .registry import PropertyError
from .resolver import resolve

RETAINED = MappingProxyType({
    'sculptcore.brush.kernel': 'sculpt_brush_type',
    'sculptcore.brush.direction': 'direction',
    'sculptcore.brush.stroke_method': 'stroke_method',
    'sculptcore.brush.falloff_preset': 'curve_distance_falloff_preset',
    'sculptcore.brush.falloff_shape': 'falloff_shape',
    'sculptcore.brush.sculpt_plane': 'sculpt_plane',
    'sculptcore.brush.plane_inversion_mode': 'plane_inversion_mode',
    'sculptcore.brush.falloff_custom': 'curve_distance_falloff',
    'sculptcore.brush.color': 'color',
    'sculptcore.brush.cursor_color': 'cursor_color_add',
    'sculptcore.brush.texture': 'texture',
    'sculptcore.brush.texture_mapping': 'texture_slot',
})
TEXTURE_SLOT_FIELDS = ('texture', 'offset', 'scale', 'color', 'default_value', 'map_mode')


@dataclass(frozen=True)
class NativeBinding:
    """Re-resolve on each draw/action; the returned RNA parent is never cached."""
    store: object
    identifier: str
    path: str
    reason: str = 'retained_native_widget'

    @property
    def owner_identity(self):
        return self.store.identity

    def rna(self, *, write=False):
        self.store._guard.check(write=write)
        parent = self.store.owner
        parts = self.path.split('.')
        for part in parts[:-1]:
            parent = getattr(parent, part)
            if parent is None:
                raise PropertyError("Native widget settings are unavailable")
        prop = parent.bl_rna.properties.get(parts[-1])
        if prop is None or (write and prop.is_readonly):
            raise PropertyError("Native widget property is unavailable or read-only")
        return parent, parts[-1]

    def read(self):
        parent, name = self.rna()
        value = getattr(parent, name)
        return tuple(value) if getattr(parent.bl_rna.properties[name], 'is_array', False) else value

    def write(self, value):
        """Use native RNA validation. Resource widgets retain their native operators."""
        parent, name = self.rna(write=True)
        prop = parent.bl_rna.properties[name]
        if prop.type == 'ENUM':
            if type(value) is not str:
                raise PropertyError("Unknown native enum item")
        elif prop.type == 'FLOAT' and prop.is_array:
            from .registry import scalar
            if type(value) not in (tuple, list) or len(value) != prop.array_length:
                raise PropertyError("Invalid native vector length")
            value = tuple(scalar('FLOAT32', item) for item in value)
            if any(not prop.hard_min <= item <= prop.hard_max for item in value):
                raise PropertyError("Native vector is out of range")
        else:
            raise PropertyError("Use the retained native resource/curve widget")
        if self.read() != value:
            try:
                setattr(parent, name, value)
            except (TypeError, ValueError) as error:
                raise PropertyError(str(error)) from error


def binding(registry, identifier, local, parent=None):
    """Numeric coupled blocks use the same resolver as their scalar rows."""
    if identifier == 'sculptcore.brush.size_mode':
        target = resolve(registry, SIZE, local, parent).value_owner
        path = 'use_locked_size'
        if target.kind == 'SCENE':
            path = 'tool_settings.sculpt.unified_paint_settings.' + path
    elif identifier == CAVITY + '.cavity_curve':
        target = resolve(registry, CAVITY + '.cavity_factor', local, parent).value_owner
        path = 'mesh_automasking_settings.cavity_curve'
        if target.kind == 'SCENE':
            path = 'tool_settings.sculpt.' + path
    elif identifier == 'sculptcore.brush.color':
        local._guard.check()
        if local.kind != 'BRUSH':
            raise PropertyError("The retained paint color uses the local Brush source")
        target, path = local, 'color'
    elif identifier in RETAINED:
        local._guard.check()
        if local.kind != 'BRUSH':
            raise PropertyError("This retained native widget belongs to Brush")
        target, path = local, RETAINED[identifier]
    else:
        raise PropertyError("Unknown retained native widget")
    result = NativeBinding(target, identifier, path)
    result.rna()
    return result


def texture_slot_binding(local, field):
    if field not in TEXTURE_SLOT_FIELDS or local.kind != 'BRUSH':
        raise PropertyError("Unsupported texture slot field")
    result = NativeBinding(local, 'sculptcore.brush.texture_mapping', 'texture_slot.' + field,
                           'retained_texture_adapter')
    result.rna()
    return result


def set_cavity_mode(registry, local, parent, mode):
    """Pin the effective block before either mutually exclusive toggle changes."""
    if mode not in ('OFF', 'NORMAL', 'INVERTED'):
        raise PropertyError("Cavity mode must be OFF, NORMAL or INVERTED")
    from .edits import rollback_edit
    target = resolve(registry, CAVITY + '.cavity_factor', local, parent).value_owner
    target._guard.check(write=True)
    with rollback_edit(target):
        settings = target._native.cavity()
        if settings is None:
            raise PropertyError("Native cavity settings are unavailable")
        if mode == 'OFF':
            if settings.use_automasking_cavity:
                settings.use_automasking_cavity = False
            if settings.use_automasking_cavity_inverted:
                settings.use_automasking_cavity_inverted = False
        else:
            name = 'use_automasking_cavity' + ('_inverted' if mode == 'INVERTED' else '')
            if not getattr(settings, name):
                setattr(settings, name, True)
    return target


def strength_for_kernel(registry, local, parent, brush_type):
    """PINCH's extra pinch uniform retains the local-source legacy rule."""
    from .adapters import strength_multiplier
    effective = resolve(registry, STRENGTH, local, parent)
    extra_pinch = local.read_value(registry.get(STRENGTH)).value if brush_type == 'PINCH' else None
    return effective.value * strength_multiplier(brush_type), extra_pinch
