# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reusable, non-allocating property rows and explicit owner-aware UI edits.

Rows edit their value inline. Each definition gets a WindowManager property
whose getter resolves the effective owner for the draw and whose setter
commits one authoring edit; nothing is stored on the WindowManager, so the
widget can never go stale against the Brush or Scene it edits. Edits push no
undo step (see `edits.authoring_edit`), so a slider drag, which applies on
every mouse move, costs one owner snapshot per move and nothing else.
"""
from dataclasses import replace
import bpy

from . import authoring, placement, resolver
from .adapters import BY_ID, CAVITY, PIXELS, SIZE, WORLD
from .edits import authoring_edit
from .interaction import ValueEdit, owners
from .registry import DeviceLayer, PropertyError


def available(context):
    obj = context.active_object
    return (obj is not None and obj.mode == 'CUSTOM' and obj.custom_mode == 'sculptcore.sculpt'
            and context.scene.sculptcore_generic_properties and context.tool_settings.sculpt.brush is not None)


def _redraw(_self=None, _context=None):
    """Refresh every region that draws property rows.

    The 3D viewport's main region is left alone: no property edit changes what
    it renders, and Blender's own brush edits only redraw its paint cursor
    (`NC_BRUSH`/`NA_EDITED`). A slider drag applies on every mouse move, so a
    full viewport redraw per move is what made the sliders drag on a big mesh.
    """
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
            elif area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type != 'WINDOW':
                        region.tag_redraw()


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


def _description(definition):
    from .engine_catalogue import VIEW_NORMAL_LIMIT
    if definition.identifier == VIEW_NORMAL_LIMIT:
        return "Angle at which the view-normal mask reaches zero"
    return definition.description


# Inline value widgets: one WindowManager property per (definition, scalar kind).
# Size is the one definition whose resolved kind depends on the owner's size
# mode, so it gets a pixel INT32 widget and a world-unit FLOAT32 widget.
_PROPERTY_PREFIX = 'scgp_'
_SUFFIX = {'FLOAT32': '_f', 'INT32': '_i', 'BOOL': '_b'}
_value_properties = {}


def value_property(identifier, kind):
    """The WindowManager property name drawing this definition at this kind, or None."""
    return _value_properties.get((identifier, kind))


def _value_kind(definition, kind):
    if definition.identifier == SIZE:
        return BY_ID[PIXELS if kind == 'INT32' else WORLD]
    return definition


def _widget_value(kind, value):
    if kind == 'BOOL':
        return bool(value)
    if kind == 'INT32':
        return int(value + .5) if type(value) is float else int(value)
    return float(value)


def _value_getter(identifier, kind, default):
    def get(_self):
        try:
            _, _, result = _resolve(bpy.context, identifier)
            return _widget_value(kind, result.value)
        except (PropertyError, ReferenceError, RuntimeError):
            return default
    return get


def _value_setter(identifier, kind):
    def set(_self, value):
        context = bpy.context
        try:
            edit = ValueEdit(context, identifier)
            if edit.kind != kind:
                raise PropertyError("The property's size mode changed under the widget")
            if not _resolve(context, identifier)[2].execution_available:
                raise PropertyError("Property execution is unavailable in this build")
            edit.set(context, bool(value) if kind == 'BOOL' else edit.bounded(value))
        except (PropertyError, ReferenceError, RuntimeError) as error:
            # A property setter has no operator to report through.
            print("SculptCore: cannot edit {}: {}".format(identifier, error))
        _redraw()
    return set


def _value_property_definition(definition, kind):
    from .storage import record_key, value_metadata
    domain = _value_kind(definition, kind)
    metadata = value_metadata(domain)
    common = dict(name=definition.label, description=_description(definition), options={'SKIP_SAVE'},
                  get=_value_getter(definition.identifier, kind, _widget_value(kind, domain.default)),
                  set=_value_setter(definition.identifier, kind))
    if kind == 'BOOL':
        prop = bpy.props.BoolProperty(**common)
    elif kind == 'INT32':
        prop = bpy.props.IntProperty(min=metadata['min'], max=metadata['max'], soft_min=metadata['soft_min'],
                                     soft_max=metadata['soft_max'],
                                     subtype='PIXEL' if definition.identifier == SIZE else 'NONE', **common)
    else:
        unit = 'LENGTH' if definition.identifier == SIZE else domain.unit
        prop = bpy.props.FloatProperty(min=metadata['min'], max=metadata['max'], soft_min=metadata['soft_min'],
                                       soft_max=metadata['soft_max'], precision=3, unit=unit, **common)
    return _PROPERTY_PREFIX + record_key(definition.identifier)[2:] + _SUFFIX[kind], prop


def _register_value_properties():
    for definition in authoring.registry.definitions():
        kinds = ('INT32', 'FLOAT32') if definition.identifier == SIZE else (definition.scalar_type,)
        for kind in kinds:
            name, prop = _value_property_definition(definition, kind)
            setattr(bpy.types.WindowManager, name, prop)
            _value_properties[(definition.identifier, kind)] = name


def _unregister_value_properties():
    for name in _value_properties.values():
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    _value_properties.clear()


class _PropertyOperator:
    @classmethod
    def poll(cls, context):
        return available(context)

    @classmethod
    def description(cls, context, properties):
        try:
            _, _, result = _resolve(context, properties.identifier)
            return "{}\nValue: {}. Input stack: {}".format(
                _description(result.definition), _name(result.value_owner), _name(result.stack_owner))
        except (PropertyError, ReferenceError):
            return "Edit the effective brush property owner"


class SCULPTCORE_OT_property_value(_PropertyOperator, bpy.types.Operator):
    """Scripted entry point for a typed value edit; the rows themselves edit inline."""
    bl_idname = "sculptcore.property_value"
    bl_label = "Edit Brush Property"
    identifier: bpy.props.StringProperty(options={'SKIP_SAVE'})
    float_value: bpy.props.FloatProperty(name="Value", precision=5, options={'SKIP_SAVE'})
    int_value: bpy.props.IntProperty(name="Value", options={'SKIP_SAVE'})
    bool_value: bpy.props.BoolProperty(name="Value", options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            _, _, result = _resolve(context, self.identifier)
            if not result.execution_available:
                raise PropertyError("Property execution is unavailable in this build")
            edit = ValueEdit(context, self.identifier)
            field = {'FLOAT32': 'float_value', 'INT32': 'int_value', 'BOOL': 'bool_value'}[edit.kind]
            edit.set(context, getattr(self, field))
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
        ('MODE', "Value Inheritance"), ('STACK_INHERIT', "Toggle Stack Inheritance"),
        ('SIZE_MODE', "Size Units"))), options={'SKIP_SAVE'})
    size_mode: bpy.props.EnumProperty(items=(('VIEW', "Pixels", ''), ('SCENE', "Blender Units", '')),
                                      options={'SKIP_SAVE'})
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
            elif self.action == 'SIZE_MODE':
                if self.identifier != SIZE:
                    raise PropertyError("Size units apply only to brush size")
                with authoring_edit(result.value_owner, "Change Brush Size Units"):
                    result.value_owner._native.write_size_mode(self.size_mode)
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
        from .automasking_ui import LABELS, value_enabled
        region = context.region
        narrow = (region is not None and region.width < 340 and
                  (region.type == 'UI' or (context.area.type == 'PROPERTIES' and region.type == 'WINDOW')))
        container = layout.column(align=True) if narrow else layout
        row = container.row(align=True)
        value = row.row(align=True)
        value.enabled = (result.value_owner.editable and result.execution_available
                         and value_enabled(context, definition.identifier))
        kind = _kind(result)
        name = value_property(definition.identifier, kind)
        if name is None:
            raise PropertyError("No inline widget for a {} value".format(kind))
        domain = _value_kind(definition, kind)
        value.prop(context.window_manager, name, text=LABELS.get(definition.identifier, definition.label),
                   slider=kind == 'FLOAT32' and (domain.soft_minimum, domain.soft_maximum) == (0.0, 1.0))
        if narrow:
            row = container.row(align=True)
        if definition.identifier == CAVITY + '.use_automasking_custom_cavity_curve' and result.value:
            curve = row.row(align=True)
            curve.enabled = value.enabled
            curve.operator_context = 'INVOKE_DEFAULT'
            curve.operator('sculptcore.native_response', text='', icon='FCURVE').target = 'CAVITY'
        row.label(text='', icon='SCENE_DATA' if result.value_owner.kind == 'SCENE' else 'BRUSH_DATA')
        if definition.dynamic:
            layer = next((layer for layer in result.stack or () if layer.device == 'PRESSURE'), None)
            _action(row, definition.identifier, 'PRESSURE', icon='STYLUS_PRESSURE',
                    depressed=bool(layer and layer.enabled), enabled=result.stack_owner.editable
                    and result.stack_available and result.execution_available)
            if result.stack_owner.identity != result.value_owner.identity and not narrow:
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
        if narrow and definition.dynamic and result.stack_owner.identity != result.value_owner.identity:
            container.label(text="Inputs: " + _name(result.stack_owner))
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
            layout.label(text=_description(result.definition))
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
            if self.identifier == SIZE:
                row = layout.row(align=True)
                for mode, label in (('VIEW', "Pixels"), ('SCENE', "Blender Units")):
                    op = _action(row, self.identifier, 'SIZE_MODE', text=label,
                                 depressed=(_kind(result) == 'INT32') == (mode == 'VIEW'),
                                 enabled=result.value_owner.editable and result.execution_available)
                    op.size_mode = mode
            row = layout.row()
            row.enabled = local.editable
            row.operator_context = 'INVOKE_DEFAULT'
            op = row.operator('sculptcore.property_placement', text="Edit Locations", icon='PREFERENCES')
            op.identifier = self.identifier
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
    bl_order = 100  # Last in the tab, after the vanilla brush panels.

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
    _register_value_properties()
    for cls in _classes:
        bpy.utils.register_class(cls)
    from . import automasking_ui, placement_ui, stack_ui
    stack_ui.register()
    placement_ui.register()
    automasking_ui.register()


def unregister():
    from . import automasking_ui, placement_ui, stack_ui
    automasking_ui.unregister()
    placement_ui.unregister()
    stack_ui.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    _unregister_value_properties()
    del bpy.types.WindowManager.sculptcore_property_search
    _search.clear()
