# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reusable, non-allocating property rows and explicit owner-aware UI edits."""
from dataclasses import replace
import bpy

from . import authoring, placement, resolver
from .adapters import CAVITY, SIZE
from .edits import authoring_edit
from .interaction import ValueEdit, owners
from .registry import DeviceLayer, PropertyError


def available(context):
    obj = context.active_object
    return (obj is not None and obj.mode == 'CUSTOM' and obj.custom_mode == 'sculptcore.sculpt'
            and context.scene.sculptcore_generic_properties and context.tool_settings.sculpt.brush is not None)


def _redraw(_self=None, _context=None):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ('PROPERTIES', 'VIEW_3D'):
                area.tag_redraw()


def _resolve(context, identifier):
    local, parent = owners(context)
    definition = authoring.registry.get(identifier)
    if not placement.applicable(definition, local.owner):
        raise PropertyError("This property does not apply to the active brush")
    return local, parent, resolver.resolve(authoring.registry, identifier, local, parent)


def _name(owner):
    return "Scene" if owner.kind == 'SCENE' else "Brush"


def _kind(result):
    return getattr(result.value_domain, 'kind', result.definition.scalar_type)


def _label(result):
    value = str(result.value) if _kind(result) in ('BOOL', 'INT32') else '{:.5g}'.format(result.value)
    if result.definition.identifier == SIZE:
        value += " px" if _kind(result) == 'INT32' else " BU"
    return "{}: {}".format(result.definition.label, value)


class _PropertyOperator:
    @classmethod
    def poll(cls, context):
        return available(context)

    @classmethod
    def description(cls, context, properties):
        try:
            _, _, result = _resolve(context, properties.identifier)
            return "{}\nValue: {}. Input stack: {}".format(
                result.definition.description, _name(result.value_owner), _name(result.stack_owner))
        except (PropertyError, ReferenceError):
            return "Edit the effective brush property owner"


class SCULPTCORE_OT_property_value(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.property_value"
    bl_label = "Edit Brush Property"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    float_value: bpy.props.FloatProperty(name="Value", precision=5, options={'SKIP_SAVE'})
    int_value: bpy.props.IntProperty(name="Value", options={'SKIP_SAVE'})
    bool_value: bpy.props.BoolProperty(name="Value", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        try:
            self._edit = ValueEdit(context, self.identifier)
            setattr(self, self._field(), self._edit.initial)
            return context.window_manager.invoke_props_dialog(self, width=320)
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def _field(self):
        return {'FLOAT32': 'float_value', 'INT32': 'int_value', 'BOOL': 'bool_value'}[self._edit.kind]

    def draw(self, context):
        result = self._edit.resolved
        self.layout.label(text="{} — {}".format(result.definition.label, _name(result.value_owner)))
        self.layout.prop(self, self._field(), text="Value")
        if self._edit.kind != 'BOOL':
            self.layout.label(text="Range: {:g} to {:g}".format(self._edit.domain.minimum, self._edit.domain.maximum))
        if self.identifier == SIZE:
            self.layout.label(text="Pixel diameter" if self._edit.kind == 'INT32' else "Diameter in Blender units")

    def execute(self, context):
        try:
            _, _, result = _resolve(context, self.identifier)
            if not result.execution_available:
                raise PropertyError("Property execution is unavailable in this build")
            if not hasattr(self, '_edit'):
                self._edit = ValueEdit(context, self.identifier)
            self._edit.check(context)
            self._edit.set(context, getattr(self, self._field()))
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class SCULPTCORE_OT_property_action(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.property_action"
    bl_label = "Change Brush Property"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    action: bpy.props.EnumProperty(items=tuple((key, label, '') for key, label in (
        ('BOOLEAN', "Toggle Value"), ('PRESSURE', "Toggle Pressure"), ('UNIFIED', "Toggle Unified Value"),
        ('MODE', "Value Inheritance"), ('STACK_INHERIT', "Toggle Stack Inheritance"))), options={'SKIP_SAVE'})
    mode: bpy.props.EnumProperty(items=tuple((key, label, '') for key, label in (
        ('UNIFIED', "Use Unified Flag"), ('ALWAYS', "Always Inherit"), ('NEVER', "Never Inherit"),
        ('NATIVE_CAVITY', "Native Cavity Policy"))), options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            local, parent, result = _resolve(context, self.identifier)
            if not result.execution_available:
                raise PropertyError("Property execution is unavailable in this build")
            if self.action == 'BOOLEAN':
                if _kind(result) != 'BOOL':
                    raise PropertyError("This property is not boolean")
                ValueEdit(context, self.identifier).set(context, not result.value)
            else:
                owner = (result.stack_owner if self.action == 'PRESSURE' else
                         parent if self.action == 'UNIFIED' else local)
                with authoring_edit(owner, "Edit " + result.definition.label):
                    if self.action == 'PRESSURE':
                        if not result.definition.dynamic or not result.stack_available:
                            raise PropertyError("Device dynamics are unavailable for this property")
                        layer = next((layer for layer in result.stack if layer.device == 'PRESSURE'), None)
                        layer = replace(layer, enabled=not layer.enabled) if layer else DeviceLayer('PRESSURE')
                        resolver.update_layer(authoring.registry, self.identifier, local, parent, layer)
                    elif self.action == 'UNIFIED':
                        if local.value_mode(self.identifier) != 'UNIFIED':
                            raise PropertyError("Unified flags apply only in Unified inheritance mode")
                        resolver.set_unified(authoring.registry, self.identifier, parent,
                                             not parent.unified(self.identifier))
                    elif self.action == 'MODE':
                        resolver.set_value_mode(authoring.registry, self.identifier, local, self.mode)
                    else:
                        if not result.definition.dynamic:
                            raise PropertyError("Static properties do not have device stacks")
                        resolver.set_stack_inheritance(authoring.registry, self.identifier, local,
                                                       not local.inherits_stack(self.identifier))
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


def _action(layout, identifier, action, *, text='', icon='NONE', depressed=False, enabled=True):
    row = layout.row(align=True)
    row.enabled = enabled
    op = row.operator('sculptcore.property_action', text=text, icon=icon, depress=depressed)
    op.identifier, op.action = identifier, action
    return op


def draw_row(layout, context, definition):
    """Resolve for this draw only. No default records, curves or shadow RNA values."""
    try:
        local, parent, result = _resolve(context, definition.identifier)
        row = layout.row(align=True)
        value = row.row(align=True)
        value.enabled = result.value_owner.editable and result.execution_available
        if _kind(result) == 'BOOL':
            _action(value, definition.identifier, 'BOOLEAN', text=definition.label,
                    icon='CHECKBOX_HLT' if result.value else 'CHECKBOX_DEHLT')
        else:
            value.operator_context = 'INVOKE_DEFAULT'
            op = value.operator('sculptcore.property_value', text=_label(result))
            op.identifier = definition.identifier
        row.label(text='', icon='SCENE_DATA' if result.value_owner.kind == 'SCENE' else 'BRUSH_DATA')
        if definition.dynamic:
            layer = next((layer for layer in result.stack or () if layer.device == 'PRESSURE'), None)
            _action(row, definition.identifier, 'PRESSURE', icon='STYLUS_PRESSURE',
                    depressed=bool(layer and layer.enabled), enabled=result.stack_owner.editable
                    and result.stack_available and result.execution_available)
            if result.stack_owner.identity != result.value_owner.identity:
                row.label(text="Stack: " + _name(result.stack_owner))
            row.operator_context = 'INVOKE_DEFAULT'
            op = row.operator('sculptcore.property_stack', text='', icon='PREFERENCES')
            op.identifier = definition.identifier
        if local.value_mode(definition.identifier) == 'UNIFIED':
            _action(row, definition.identifier, 'UNIFIED', icon='WORLD', depressed=parent.unified(definition.identifier),
                    enabled=parent.editable and result.execution_available)
        row.operator_context = 'INVOKE_DEFAULT'
        op = row.operator('sculptcore.property_metadata', text='', icon='DOWNARROW_HLT')
        op.identifier = definition.identifier
        if not result.execution_available:
            layout.label(text="Unavailable in this build", icon='ERROR')
    except (PropertyError, ReferenceError) as error:
        layout.label(text=definition.label + ": " + str(error), icon='ERROR')


def draw_location(layout, context, location):
    local, _ = owners(context)
    for definition in placement.located(local, location):
        draw_row(layout, context, definition)


class SCULPTCORE_OT_property_metadata(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.property_metadata"
    bl_label = "Brush Property Details"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=360)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        try:
            local, parent, result = _resolve(context, self.identifier)
            layout.label(text=result.definition.label)
            layout.label(text="Value: {} • Input stack: {}".format(_name(result.value_owner), _name(result.stack_owner)))
            layout.label(text=result.definition.description)
            layout.label(text="Value inheritance")
            choices = [('UNIFIED', "Unified"), ('ALWAYS', "Always"), ('NEVER', "Never")]
            if self.identifier.startswith(CAVITY + '.'):
                choices.append(('NATIVE_CAVITY', "Native"))
            row = layout.row(align=True)
            for mode, label in choices:
                op = _action(row, self.identifier, 'MODE', text=label,
                             depressed=local.value_mode(self.identifier) == mode,
                             enabled=local.editable and result.execution_available)
                op.mode = mode
            if result.definition.dynamic:
                _action(layout, self.identifier, 'STACK_INHERIT', text="Inherit Input Stack",
                        icon='CHECKBOX_HLT' if local.inherits_stack(self.identifier) else 'CHECKBOX_DEHLT',
                        enabled=local.editable and result.execution_available)
            layout.label(text={'FLOAT32': "Number", 'INT32': "Whole number", 'BOOL': "On / Off"}[_kind(result)])
            for diagnostic in result.diagnostics:
                layout.label(text=diagnostic, icon='INFO')
        except (PropertyError, ReferenceError) as error:
            layout.label(text=str(error), icon='ERROR')


_search = {}


class SCULPTCORE_PT_all_properties(bpy.types.Panel):
    bl_label = "All Brush Properties"
    # The Properties Tool tab draws the View3D Tool-category panels.
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_context = 'sculptcore.sculpt'
    bl_order = -10

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'PROPERTIES' and available(context)

    def draw(self, context):
        layout = self.layout
        layout.prop(context.window_manager, 'sculptcore_property_search', text='', icon='VIEWZOOM')
        query = context.window_manager.sculptcore_property_search.casefold().strip()
        brush = context.tool_settings.sculpt.brush
        for definition in authoring.registry.definitions():
            if (placement.applicable(definition, brush)
                    and (not query or query in (definition.label + ' ' + definition.identifier).casefold())):
                draw_row(layout, context, definition)


_classes = (SCULPTCORE_OT_property_value, SCULPTCORE_OT_property_action,
            SCULPTCORE_OT_property_metadata, SCULPTCORE_PT_all_properties)


def register():
    bpy.types.WindowManager.sculptcore_property_search = bpy.props.StringProperty(
        name="Search Properties", options={'SKIP_SAVE', 'TEXTEDIT_UPDATE'},
        update=_redraw,
        get=lambda self: _search.get(self.as_pointer(), ''),
        set=lambda self, value: _search.__setitem__(self.as_pointer(), value))
    for cls in _classes:
        bpy.utils.register_class(cls)
    from . import stack_ui
    stack_ui.register()


def unregister():
    from . import stack_ui
    stack_ui.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.sculptcore_property_search
    _search.clear()
