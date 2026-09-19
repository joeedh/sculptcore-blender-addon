# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""One automasking renderer, using only settings consumed by SculptCore."""
from .adapters import CAVITY
from .engine_catalogue import AUTOMASK_VIEW_NORMAL, CULL_BACKFACES, VIEW_NORMAL_FALLOFF, VIEW_NORMAL_LIMIT

_CAVITY_LABELS = {
    'use_automasking_cavity': "Cavity",
    'use_automasking_cavity_inverted': "Cavity (Inverted)",
    'cavity_factor': "Cavity Factor",
    'cavity_blur_steps': "Cavity Blur",
    'use_automasking_custom_cavity_curve': "Custom Cavity Curve",
}
LABELS = {CAVITY + '.' + key: label for key, label in _CAVITY_LABELS.items()}
LABELS.update({VIEW_NORMAL_LIMIT: "View Normal Limit (rad)", VIEW_NORMAL_FALLOFF: "View Normal Falloff (rad)"})
ORDER = (*tuple(CAVITY + '.' + key for key in _CAVITY_LABELS), AUTOMASK_VIEW_NORMAL,
         VIEW_NORMAL_LIMIT, VIEW_NORMAL_FALLOFF, CULL_BACKFACES)


def value_enabled(context, identifier):
    from .ui import _resolve
    if identifier in (VIEW_NORMAL_LIMIT, VIEW_NORMAL_FALLOFF, CULL_BACKFACES):
        return bool(_resolve(context, AUTOMASK_VIEW_NORMAL)[2].value)
    if identifier.startswith(CAVITY + '.') and identifier.rsplit('.', 1)[1] not in (
            'use_automasking_cavity', 'use_automasking_cavity_inverted'):
        settings = _resolve(context, CAVITY + '.cavity_factor')[2].value_owner._native.cavity()
        return settings.use_automasking_cavity or settings.use_automasking_cavity_inverted
    return True


def active(context):
    from .ui import available, _resolve
    if available(context):
        return any(_resolve(context, key)[2].value for key in (
            CAVITY + '.use_automasking_cavity', CAVITY + '.use_automasking_cavity_inverted', AUTOMASK_VIEW_NORMAL))
    from ..mapping import cavity_settings
    return cavity_settings(context.tool_settings.sculpt.brush, context.tool_settings.sculpt) is not None


def draw(layout, context):
    from .ui import available, draw_location, _resolve
    if not available(context):
        from ..mapping import cavity_settings
        brush = context.tool_settings.sculpt.brush
        settings = cavity_settings(brush, context.tool_settings.sculpt) or brush.mesh_automasking_settings
        layout.label(text="Brush" if settings == brush.mesh_automasking_settings else "Scene", icon='INFO')
        for key, label in _CAVITY_LABELS.items():
            row = layout.row()
            row.enabled = (key.startswith('use_automasking_cavity') or settings.use_automasking_cavity
                           or settings.use_automasking_cavity_inverted)
            row.prop(settings, key, text=label)
        if settings.use_automasking_custom_cavity_curve:
            layout.template_curve_mapping(settings, 'cavity_curve', brush=True)
        return
    draw_location(layout, context, 'AUTOMASKING')
    if _resolve(context, AUTOMASK_VIEW_NORMAL)[2].value:
        layout.label(text="Mask reaches zero at the limit", icon='INFO')
        layout.label(text="Falloff is the angle before the limit")


_original_draw = None


def _native_draw(self, context):
    from ..menus import _in_mode
    if _in_mode(context) and context.tool_settings.sculpt.brush:
        draw(self.layout, context)
    else:
        _original_draw(self, context)


def register():
    global _original_draw
    from bl_ui.space_view3d import VIEW3D_PT_mesh_paint_automasking
    _original_draw = VIEW3D_PT_mesh_paint_automasking.draw
    VIEW3D_PT_mesh_paint_automasking.draw = _native_draw


def unregister():
    global _original_draw
    from bl_ui.space_view3d import VIEW3D_PT_mesh_paint_automasking
    if VIEW3D_PT_mesh_paint_automasking.draw is _native_draw:
        VIEW3D_PT_mesh_paint_automasking.draw = _original_draw
    _original_draw = None
