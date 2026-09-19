# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Modal size/strength editing with one pinned owner and one authoring undo scope."""
import bpy

from .adapters import SIZE, STRENGTH
from .interaction import ValueEdit
from .registry import PropertyError

_active = []
_digits = dict(zip(('ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'), '0123456789'))
_digits.update({'NUMPAD_' + str(i): str(i) for i in range(10)})


def active(context):
    return any(op._area == context.area and op._window == context.window for op in _active)


class SCULPTCORE_OT_brush_radial_control(bpy.types.Operator):
    bl_idname = "sculptcore.brush_radial_control"
    bl_label = "Edit Brush Property"
    bl_description = "Move horizontally or type a value; Shift adjusts precisely; Escape cancels"
    property: bpy.props.EnumProperty(items=(('SIZE', "Size", ""), ('STRENGTH', "Strength", "")))

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.mode == 'CUSTOM' and obj.custom_mode == 'sculptcore.sculpt'
                and context.area is not None and context.area.type == 'VIEW_3D'
                and context.region is not None and context.region.type == 'WINDOW'
                and context.tool_settings.sculpt.brush is not None)

    def invoke(self, context, event):
        if not context.scene.sculptcore_generic_properties:
            path = 'size' if self.property == 'SIZE' else 'strength'
            bpy.ops.wm.radial_control('INVOKE_DEFAULT',
                data_path_primary='tool_settings.sculpt.brush.' + path,
                data_path_secondary='tool_settings.sculpt.unified_paint_settings.' + path,
                use_secondary='tool_settings.sculpt.unified_paint_settings.use_unified_' + path,
                rotation_path='tool_settings.sculpt.brush.texture_slot.angle',
                color_path='tool_settings.sculpt.brush.cursor_color_add', image_id='tool_settings.sculpt.brush')
            return {'FINISHED'}
        self._edit = None
        self._timer = self._draw_handle = None
        self._window, self._area, self._region = context.window, context.area, context.region
        self._manager = context.window_manager
        try:
            self._edit = ValueEdit(context, SIZE if self.property == 'SIZE' else STRENGTH)
            self._value = self._edit.initial
            self._drag_value = self._value
            self._pixels_per_value = 200.0
            if self.property == 'SIZE':
                from dataclasses import replace
                from .. import engine, stroke
                from .stroke_settings import pixel_radius
                size = self._edit.owner._native.size_block()
                origin, direction = stroke._ray_origin_dir(context, (event.mouse_region_x, event.mouse_region_y))
                hit = stroke.raycast(engine.sessions[context.object.name], origin, direction)
                unit = replace(size, pixels=1) if size.mode == 'VIEW' else replace(size, world=1.0)
                self._pixels_per_value = pixel_radius(context, unit, hit[0] if hit else (0, 0, 0))
            self._center = (event.mouse_region_x - self._radius(), event.mouse_region_y)
            self._mouse_x = event.mouse_x
            self._text, self._precision = '', False
            self._edit.begin()
            _active.append(self)
            self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
            self._timer = self._manager.event_timer_add(.1, window=context.window)
            self._manager.modal_handler_add(self)
            self._status()
            return {'RUNNING_MODAL'}
        except (PropertyError, ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            self._finish(cancel=True)
            return {'CANCELLED'}

    def _radius(self):
        return (self._value * self._pixels_per_value if self.property == 'SIZE'
                else 32 + 128 * min(1, max(0, self._value)))

    def _status(self):
        value = self._text or '{:.4g}'.format(self._value)
        if self.property == 'SIZE':
            value += " px" if self._edit.kind == 'INT32' else " Blender units"
        owner = "Scene" if self._edit.owner.kind == 'SCENE' else "Brush"
        self._area.header_text_set("{}: {} ({}) — Enter: confirm, Esc: cancel, Shift: precision".format(
            self._edit.resolved.definition.label, value, owner))
        self._area.tag_redraw()

    def _draw(self):
        if bpy.context.area == self._area and bpy.context.region == self._region:
            from ..cursor import draw_ring
            draw_ring(*self._center, self._radius(), (1, 1, 1, .9))

    def _write(self, context, value):
        self._value = self._edit.bounded(value)
        self._edit.write(context, self._value)
        self._status()

    def _write_text(self, context):
        try:
            value = self._edit.bounded(float(self._text) if self._text else self._edit.initial)
        except ValueError:
            self._status()
            return False
        self._write(context, value)
        self._drag_value = self._value
        return True

    def modal(self, context, event):
        if self not in _active:
            return {'CANCELLED'}
        try:
            self._edit.check(context)
            if (context.area != self._area or not context.scene.sculptcore_generic_properties
                    or context.object is None or context.object.mode != 'CUSTOM'):
                return self._finish(cancel=True)
            if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
                return self._finish(cancel=True)
            if event.type in {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'} and event.value == 'PRESS':
                if self._text and not self._write_text(context):
                    self.report({'WARNING'}, "Enter a finite number")
                    return {'RUNNING_MODAL'}
                return self._finish()
            if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'}:
                self._precision = event.value == 'PRESS'
            elif event.type == 'MOUSEMOVE':
                if not self._text:
                    delta = (event.mouse_x - self._mouse_x) * (.1 if self._precision else 1)
                    domain = self._edit.domain
                    self._drag_value = min(domain.maximum, max(domain.minimum,
                        self._drag_value + delta / max(self._pixels_per_value, 1e-12)))
                    self._write(context, self._drag_value)
                self._mouse_x = event.mouse_x
            elif event.value == 'PRESS':
                char = _digits.get(event.type, {'PERIOD': '.', 'NUMPAD_PERIOD': '.',
                                               'MINUS': '-', 'NUMPAD_MINUS': '-', 'E': 'e'}.get(event.type))
                if event.type == 'BACK_SPACE':
                    self._text = self._text[:-1]
                elif char and len(self._text) < 64:
                    self._text += char
                else:
                    return {'RUNNING_MODAL'}
                self._write_text(context)
            return {'RUNNING_MODAL'}
        except (PropertyError, ReferenceError, RuntimeError) as error:
            self.report({'WARNING'}, str(error))
            return self._finish(cancel=True)

    def _finish(self, *, cancel=False):
        try:
            if self._edit is not None:
                self._edit.finish(cancel=cancel)
        finally:
            if self._timer is not None:
                self._manager.event_timer_remove(self._timer)
                self._timer = None
            if self._draw_handle is not None:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
                self._draw_handle = None
            if self in _active:
                _active.remove(self)
            try:
                self._area.header_text_set(None)
                self._area.tag_redraw()
            except ReferenceError:
                pass
        return {'CANCELLED'} if cancel else {'FINISHED'}

    def cancel(self, context):
        self._finish(cancel=True)


def register():
    bpy.utils.register_class(SCULPTCORE_OT_brush_radial_control)
    for callbacks in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        callbacks.append(cancel_all)


@bpy.app.handlers.persistent
def cancel_all(*_args):
    for op in tuple(_active):
        op._finish(cancel=True)


def unregister():
    cancel_all()
    for callbacks in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if cancel_all in callbacks:
            callbacks.remove(cancel_all)
    bpy.utils.unregister_class(SCULPTCORE_OT_brush_radial_control)
