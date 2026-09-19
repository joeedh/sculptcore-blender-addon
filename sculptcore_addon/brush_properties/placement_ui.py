# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Staged edits of Brush-local placement, independent of effective value owners."""
import bpy

from . import authoring, placement
from .edits import authoring_edit
from .interaction import owners
from .registry import Position, PropertyError
from .ui import _PropertyOperator, _redraw

_locations = placement.LOCATIONS
_fields = ('header', 'settings', 'menu', 'automasking')


class PlacementEdit:
    def __init__(self, context, identifier):
        self.local, _ = owners(context)
        self.definition = authoring.registry.get(identifier)
        if not placement.applicable(self.definition, self.local.owner):
            raise PropertyError("This property does not apply to the active brush")
        self.local._guard.check(write=True)
        self.initial = self.snapshot()

    def snapshot(self):
        positions = placement.positions(self.local, self.definition)
        record = self.local._record(self.definition.identifier)
        return positions, record is not None and 'positions_version' in record

    def write(self, context, positions, *, reset=False):
        self.local._guard.check(write=True)
        current, _ = owners(context)
        if current.identity != self.local.identity or self.snapshot() != self.initial:
            raise PropertyError("Brush or placement changed during the edit; reopen the editor")
        with authoring_edit(self.local, "Edit Property Placement"):
            if reset:
                self.local.reset_positions(self.definition)
            else:
                self.local.write_positions(self.definition, positions)


class SCULPTCORE_OT_property_placement(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.property_placement"
    bl_label = "Property Placement"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    reset: bpy.props.BoolProperty(name="Use Default Locations", options={'SKIP_SAVE'})
    header: bpy.props.BoolProperty(name="Tool Header", options={'SKIP_SAVE'})
    settings: bpy.props.BoolProperty(name="Brush Settings", options={'SKIP_SAVE'})
    menu: bpy.props.BoolProperty(name="Context Menu", options={'SKIP_SAVE'})
    automasking: bpy.props.BoolProperty(name="Automasking", options={'SKIP_SAVE'})
    header_order: bpy.props.IntProperty(name="Order", options={'SKIP_SAVE'})
    settings_order: bpy.props.IntProperty(name="Order", options={'SKIP_SAVE'})
    menu_order: bpy.props.IntProperty(name="Order", options={'SKIP_SAVE'})
    automasking_order: bpy.props.IntProperty(name="Order", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        try:
            self._edit = PlacementEdit(context, self.identifier)
            self.reset = False
            current = {item.location: item.sort_index for item in self._edit.initial[0]}
            for field, (location, _) in zip(_fields, _locations):
                setattr(self, field, location in current)
                setattr(self, field + '_order', current.get(location, 100))
            return context.window_manager.invoke_props_dialog(self, width=400)
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text=self._edit.definition.label + " — Brush Layout")
        layout.prop(self, 'reset')
        content = layout.column()
        content.enabled = not self.reset
        for field, (_, label) in zip(_fields, _locations):
            row = content.row(align=True)
            row.prop(self, field, text=label)
            order = row.row()
            order.enabled = getattr(self, field)
            order.prop(self, field + '_order')
        layout.label(text="Lower order appears first; equal orders sort by property ID")
        layout.label(text="Always discoverable in All Brush Properties")

    def execute(self, context):
        try:
            edit = self._edit if hasattr(self, '_edit') else PlacementEdit(context, self.identifier)
            known = {location for location, _ in _locations}
            # Keep positions from other versions/surfaces, even when none of the
            # currently editable locations is selected.
            positions = tuple(item for item in edit.initial[0] if item.location not in known) + tuple(
                Position(location, getattr(self, field + '_order'))
                for field, (location, _) in zip(_fields, _locations)
                if getattr(self, field))
            edit.write(context, positions, reset=self.reset)
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


def register():
    bpy.utils.register_class(SCULPTCORE_OT_property_placement)


def unregister():
    bpy.utils.unregister_class(SCULPTCORE_OT_property_placement)
