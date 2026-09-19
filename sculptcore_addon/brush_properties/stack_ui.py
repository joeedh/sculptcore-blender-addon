# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Ordered device-stack controls and effective-owner response editors."""
from dataclasses import replace
import bpy

from . import authoring, resolver
from .curves import declaration_name
from .customize import customize
from .edits import authoring_edit
from .interaction import ValueEdit, owners
from .registry import CURVE_PRESET_ARITY, DeviceLayer, NativeCurveReference, PropertyError, ResponseCurve
from .ui import _PropertyOperator, _name, _redraw, _resolve

_devices = tuple((key, label, description) for key, label, description in (
    ('PRESSURE', "Pressure", "Pen pressure"), ('TILT_X', "Tilt X", "Horizontal pen tilt when available"),
    ('TILT_Y', "Tilt Y", "Vertical pen tilt when available"), ('SPEED', "Speed", "Normalized stroke speed")))
_presets = (('KEEP', "Keep Response", "Keep the current response unchanged"),) + tuple(
    (key, key.replace('_', ' ').title(), '') for key in CURVE_PRESET_ARITY)
_operations = tuple((key, key.title(), '') for key in ('REPLACE', 'MULTIPLY', 'ADD', 'SUBTRACT', 'DIFFERENCE'))


class StackEdit:
    def __init__(self, context, identifier):
        self.local, self.parent, self.result = _resolve(context, identifier)
        self.owner = self.result.stack_owner
        if not self.result.definition.dynamic or not self.result.stack_available or not self.result.execution_available:
            raise PropertyError("Device dynamics are unavailable for this property")
        self.owner._guard.check(write=True)

    def check(self, context, *, contents=True):
        self.owner._guard.check(write=True)
        local, parent = owners(context)
        if (local.identity, parent.identity) != (self.local.identity, self.parent.identity):
            raise PropertyError("Brush or scene changed during the edit")
        current = resolver.resolve(authoring.registry, self.result.definition.identifier, local, parent)
        if current.stack_owner.identity != self.owner.identity or (contents and current.stack != self.result.stack):
            raise PropertyError("Input stack changed during the edit; reopen the editor")
        return current

    def write(self, context, layers):
        self.check(context)
        with authoring_edit(self.owner, "Edit " + self.result.definition.label + " Inputs"):
            resolver.set_stack(authoring.registry, self.result.definition.identifier, self.local, self.parent, layers)


class SCULPTCORE_OT_stack_action(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.stack_action"
    bl_label = "Change Input Stack"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    device: bpy.props.EnumProperty(items=_devices, options={'SKIP_SAVE'})
    action: bpy.props.EnumProperty(items=tuple((key, label, '') for key, label in (
        ('ADD', "Add Input"), ('REMOVE', "Remove Input"), ('TOGGLE', "Toggle Input"), ('UP', "Move Up"),
        ('DOWN', "Move Down"), ('CUSTOM', "Use Custom Curve"), ('RESEED', "Replace Custom Curve From Preset"))),
        options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            edit = StackEdit(context, self.identifier)
            layers = list(edit.result.stack)
            index = next((i for i, layer in enumerate(layers) if layer.device == self.device), None)
            if self.action == 'ADD':
                if index is not None:
                    raise PropertyError("This input already has an entry")
                layers.append(DeviceLayer(self.device))
            else:
                if index is None:
                    raise PropertyError("The input entry no longer exists")
                if self.action in ('CUSTOM', 'RESEED'):
                    note = customize(edit.owner, edit.result.definition, self.device, reseed=self.action == 'RESEED')
                    if note:
                        self.report({'INFO'}, note)
                    _redraw()
                    return {'FINISHED'}
                if self.action == 'REMOVE':
                    del layers[index]
                elif self.action == 'TOGGLE':
                    layers[index] = replace(layers[index], enabled=not layers[index].enabled)
                else:
                    destination = index + (-1 if self.action == 'UP' else 1)
                    if not 0 <= destination < len(layers):
                        raise PropertyError("The input is already at the end of the stack")
                    layers[index], layers[destination] = layers[destination], layers[index]
            edit.write(context, tuple(layers))
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class SCULPTCORE_OT_stack_layer(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.stack_layer"
    bl_label = "Edit Input Response"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    device: bpy.props.EnumProperty(items=_devices, options={'SKIP_SAVE'})
    enabled: bpy.props.BoolProperty(name="Enabled", default=True, options={'SKIP_SAVE'})
    operation: bpy.props.EnumProperty(name="Mix", items=_operations, default='MULTIPLY', options={'SKIP_SAVE'})
    factor: bpy.props.FloatProperty(name="Mix Factor", min=0, max=1, default=1, options={'SKIP_SAVE'})
    preset: bpy.props.EnumProperty(name="Response", items=_presets, options={'SKIP_SAVE'})
    level: bpy.props.FloatProperty(name="Constant", default=1, options={'SKIP_SAVE'})
    threshold: bpy.props.FloatProperty(name="Threshold", min=0, max=1, default=.5, options={'SKIP_SAVE'})
    low: bpy.props.FloatProperty(name="Below Threshold", default=0, options={'SKIP_SAVE'})
    high: bpy.props.FloatProperty(name="At or Above Threshold", default=1, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        try:
            self._edit = StackEdit(context, self.identifier)
            layer = next(layer for layer in self._edit.result.stack if layer.device == self.device)
            self.enabled, self.operation, self.factor = layer.enabled, layer.operation, layer.factor
            self.preset = 'KEEP'
            if isinstance(layer.curve, ResponseCurve):
                self.preset = layer.curve.preset
                if self.preset == 'CONSTANT':
                    self.level, = layer.curve.parameters
                elif self.preset == 'TWO_STEP':
                    self.threshold, self.low, self.high = layer.curve.parameters
            return context.window_manager.invoke_props_dialog(self, width=360)
        except (PropertyError, ReferenceError, RuntimeError, StopIteration) as error:
            self.report({'ERROR'}, str(error) or "The input entry no longer exists")
            return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="{} — {}".format(self.device.replace('_', ' ').title(), _name(self._edit.owner)))
        for name in ('enabled', 'operation', 'factor', 'preset'):
            layout.prop(self, name)
        if self.preset == 'CONSTANT':
            layout.prop(self, 'level')
        elif self.preset == 'TWO_STEP':
            for name in ('threshold', 'low', 'high'):
                layout.prop(self, name)

    def execute(self, context):
        try:
            edit = self._edit if hasattr(self, '_edit') else StackEdit(context, self.identifier)
            edit.check(context)
            layers = list(edit.result.stack)
            index = next(i for i, layer in enumerate(layers) if layer.device == self.device)
            parameters = ((self.level,) if self.preset == 'CONSTANT' else
                          (self.threshold, self.low, self.high) if self.preset == 'TWO_STEP' else ())
            curve = layers[index].curve if self.preset == 'KEEP' else ResponseCurve(self.preset, parameters)
            layers[index] = replace(layers[index], enabled=self.enabled, operation=self.operation,
                                    factor=self.factor, curve=curve)
            edit.write(context, tuple(layers))
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError, StopIteration) as error:
            self.report({'ERROR'}, str(error) or "The input entry no longer exists")
            return {'CANCELLED'}


_native_editors = []


class NativeCurveEdit:
    """Pin native cavity/falloff owners without creating a generic mapping."""
    def __init__(self, context, target):
        self.local, self.parent = owners(context)
        self.value_edit = None
        if target == 'CAVITY':
            from .adapters import CAVITY
            self.value_edit = ValueEdit(context, CAVITY + '.cavity_factor')
            self.owner = self.value_edit.owner
            self.path = ('mesh_automasking_settings.cavity_curve' if self.owner.kind == 'BRUSH' else
                         'tool_settings.sculpt.mesh_automasking_settings.cavity_curve')
        else:
            self.owner = self.local
            self.path = 'curve_distance_falloff'
        self.owner._guard.check(write=True)

    def check(self, context):
        if self.value_edit is not None:
            self.value_edit.check(context)
        else:
            local, parent = owners(context)
            if (local.identity, parent.identity) != (self.local.identity, self.parent.identity):
                raise PropertyError("Brush or scene changed during the edit")
            self.owner._guard.check(write=True)


class SCULPTCORE_OT_native_response(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.native_response"
    bl_label = "Edit Brush Curve"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    target: bpy.props.EnumProperty(items=(('PRESSURE', "Pressure", ''), ('CAVITY', "Cavity", ''),
                                         ('FALLOFF', "Falloff", '')), options={'SKIP_SAVE'})
    _scope = None

    def invoke(self, context, event):
        self._scope = None
        try:
            if self.target == 'PRESSURE':
                self._edit = StackEdit(context, self.identifier)
                layer = next(layer for layer in self._edit.result.stack if layer.device == 'PRESSURE')
                if not isinstance(layer.curve, NativeCurveReference):
                    raise PropertyError("This input does not use a native pressure curve")
                self._path = layer.curve.path
                self._selection = self._edit.owner._stack_descriptions(self._edit.result.definition)
            else:
                self._edit = NativeCurveEdit(context, self.target)
                self._path = self._edit.path
            self._scope = authoring_edit(self._edit.owner, "Edit " + self.target.title() + " Curve")
            self._scope.__enter__()
            _native_editors.append(self)
            return context.window_manager.invoke_props_dialog(self, width=460)
        except (PropertyError, ReferenceError, RuntimeError, StopIteration) as error:
            self._finish(cancel=True)
            self.report({'ERROR'}, str(error) or "Pressure entry is absent")
            return {'CANCELLED'}

    def _check(self, context):
        if self._scope is None:
            raise PropertyError("The curve edit was cancelled")
        if self.target == 'PRESSURE':
            self._edit.check(context, contents=False)
            if self._edit.owner._stack_descriptions(self._edit.result.definition) != self._selection:
                raise PropertyError("Pressure settings changed during the edit")
        else:
            self._edit.check(context)

    def draw(self, context):
        try:
            self._check(context)
            owner = self._edit.owner.owner
            if self.target != 'PRESSURE':
                self.layout.label(text=self.target.title() + " — " + self._edit.owner.kind.title())
            parent, separator, name = self._path.rpartition('.')
            self.layout.template_curve_mapping(owner.path_resolve(parent) if separator else owner,
                                               name, brush=True, use_negative_slope=self.target == 'FALLOFF',
                                               show_presets=self.target == 'FALLOFF')
        except (PropertyError, ReferenceError) as error:
            self.layout.label(text=str(error), icon='ERROR')

    def _finish(self, *, cancel=False):
        scope, self._scope = self._scope, None
        if self in _native_editors:
            _native_editors.remove(self)
        if scope is not None:
            error = _CancelCurve() if cancel else None
            scope.__exit__(type(error) if error else None, error, None)

    def execute(self, context):
        try:
            self._check(context)
            self._finish()
            _redraw()
            return {'FINISHED'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self._finish(cancel=True)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def cancel(self, context):
        self._finish(cancel=True)


class _CancelCurve(Exception):
    pass


def _button(layout, identifier, device, action, *, text='', icon='NONE', enabled=True):
    row = layout.row(align=True)
    row.enabled = enabled
    op = row.operator('sculptcore.stack_action', text=text, icon=icon)
    op.identifier, op.device, op.action = identifier, device, action


class SCULPTCORE_OT_property_stack(_PropertyOperator, bpy.types.Operator):
    bl_idname = "sculptcore.property_stack"
    bl_label = "Input Stack"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=420)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        try:
            _, _, result = _resolve(context, self.identifier)
            layout = self.layout
            layout.label(text="{} — {} Inputs".format(result.definition.label, _name(result.stack_owner)))
            if not result.definition.dynamic or not result.stack_available or not result.execution_available:
                layout.label(text="Device dynamics are unavailable", icon='INFO')
                return
            layout.label(text="Inputs missing from the current device are skipped")
            if result.definition.scalar_type == 'INT32':
                layout.label(text="Rounded after mixing; halfway values round away from zero")
            elif result.definition.scalar_type == 'BOOL':
                layout.label(text="After mixing: 0.5 or higher is On")
            content = layout.column()
            content.enabled = result.stack_owner.editable
            for index, layer in enumerate(result.stack):
                box = content.box()
                row = box.row(align=True)
                _button(row, self.identifier, layer.device, 'TOGGLE', text=layer.device.replace('_', ' ').title(),
                        icon='CHECKBOX_HLT' if layer.enabled else 'CHECKBOX_DEHLT')
                _button(row, self.identifier, layer.device, 'UP', icon='TRIA_UP', enabled=index > 0)
                _button(row, self.identifier, layer.device, 'DOWN', icon='TRIA_DOWN',
                        enabled=index + 1 < len(result.stack))
                _button(row, self.identifier, layer.device, 'REMOVE', icon='X')
                row = box.row(align=True)
                row.operator_context = 'INVOKE_DEFAULT'
                preset = layer.curve.preset if isinstance(layer.curve, ResponseCurve) else 'CUSTOM'
                op = row.operator('sculptcore.stack_layer', text="{} · {:g} · {}".format(
                    layer.operation.title(), layer.factor, preset.replace('_', ' ').title()))
                op.identifier, op.device = self.identifier, layer.device
                if isinstance(layer.curve, ResponseCurve):
                    _button(row, self.identifier, layer.device, 'CUSTOM', text="Custom")
                    _button(box, self.identifier, layer.device, 'RESEED', text="Replace Custom From Preset")
                elif isinstance(layer.curve, NativeCurveReference):
                    op = row.operator('sculptcore.native_response', text="Edit Curve")
                    op.identifier = self.identifier
                else:
                    box.template_owned_curve_mapping(result.stack_owner.owner,
                                                     declaration_name(self.identifier, layer.device))
            row = content.row(align=True)
            present = {layer.device for layer in result.stack}
            for device, label, _ in _devices:
                if device not in present:
                    _button(row, self.identifier, device, 'ADD', text=label, icon='ADD')
        except (PropertyError, ReferenceError) as error:
            self.layout.label(text=str(error), icon='ERROR')


@bpy.app.handlers.persistent
def cancel_editors(*_args):
    for op in tuple(_native_editors):
        op._finish(cancel=True)


_classes = (SCULPTCORE_OT_stack_action, SCULPTCORE_OT_stack_layer,
            SCULPTCORE_OT_native_response, SCULPTCORE_OT_property_stack)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        handlers.append(cancel_editors)


def unregister():
    cancel_editors()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        handlers.remove(cancel_editors)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
