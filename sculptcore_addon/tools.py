# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Toolbar tool for the mode.

Custom modes share the ``CTX_MODE_CUSTOM`` tool-storage slot (both the C
tool system and the Python toolbar key off it), so the tool registers under
the ``'CUSTOM'`` context-mode key. The stroke itself comes from the
"SculptCore Mode" keymap (via the viewport's dynamic keymap handler), so the
tool carries no keymap of its own — it is the toolbar presence + brush
cursor that makes the mode's default tool resolve (silencing the
`builtin.select_box not found` fallback).
"""

import bpy

_CONTEXT_MODE = 'CUSTOM'


class SculptCoreBrushTool(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = _CONTEXT_MODE
    bl_idname = "sculptcore.brush"
    bl_label = "Brush"
    bl_description = "Sculpt with the active brush"
    bl_icon = "ops.sculpt.border_hide"
    bl_widget = None
    # Stroke input is handled by the "SculptCore Mode" keymap.
    bl_keymap = None
    # The tool drives brush assets on the shared sculpt Paint; without this
    # flag UnifiedPaintPanel.get_brush_mode returns None and every brush
    # panel hides.
    bl_options = {'USE_BRUSHES'}

    def draw_settings(context, layout, _tool):
        # Mirrors _draw_tool_settings_context_mode.SCULPT: brush popup
        # selector, then unified-aware size/strength with their unified and
        # pen-pressure toggles. The same draw runs in the 3D viewport's
        # horizontal tool header and in the Properties editor's Active Tool tab;
        # the pressure-response-curve expander only makes sense in the vertical
        # Properties layout (it is too cramped in the header, which is why
        # vanilla drops it there too), so it is gated on the editor type.
        from bl_ui.properties_paint_common import BrushAssetShelf, UnifiedPaintPanel

        from . import mapping

        paint = context.tool_settings.sculpt
        brush = paint.brush
        BrushAssetShelf.draw_popup_selector(layout, context, brush)
        if brush is None:
            return
        capabilities = brush.sculpt_capabilities
        ups = paint.unified_paint_settings
        in_properties = context.area is not None and context.area.type == 'PROPERTIES'

        # Which brushes get pen-pressure toggles at all: exactly the ones whose
        # strokes consume pressure, i.e. everything mapping.is_grab_class rejects
        # (see stroke.invoke, which builds the response LUTs and registers the
        # engine dynamics under that same test). Vanilla's own capability flags
        # are a different set — BKE's is_grab_tool also covers snake hook, pose,
        # thumb and rotate, whose SculptCore kernels do scale by strength — so
        # they are not used here; vanilla_panels applies the same rule to the
        # sidebar's Brush Settings panel.
        has_pressure = not mapping.is_grab_class(brush)
        strength_prop, size_prop = mapping.pressure_prop_names(brush)
        size_pressure_name = size_prop if has_pressure else None
        size = "size"
        size_owner = ups if ups.use_unified_size else brush
        if size_owner.use_locked_size == 'SCENE':
            size = "unprojected_size"
        size_row = UnifiedPaintPanel.prop_unified(
            layout, context, brush, size,
            pressure_name=size_pressure_name,
            unified_name="use_unified_size",
            text="Size", slider=True, header=True,
        )
        if size_pressure_name and in_properties:
            UnifiedPaintPanel.prop_custom_pressure(
                layout, context, size_row, brush,
                pressure_name=size_pressure_name,
                curve_visibility_name="show_size_curve",
                custom_curve_name="curve_size",
            )
        pressure_name = strength_prop if has_pressure else None
        strength_row = UnifiedPaintPanel.prop_unified(
            layout, context, brush, "strength",
            pressure_name=pressure_name,
            unified_name="use_unified_strength",
            text="Strength", header=True,
        )
        if pressure_name and in_properties:
            UnifiedPaintPanel.prop_custom_pressure(
                layout, context, strength_row, brush,
                pressure_name=pressure_name,
                curve_visibility_name="show_strength_curve",
                custom_curve_name="curve_strength",
            )
        if capabilities.has_direction:
            layout.row().prop(brush, "direction", expand=True, text="")


def register():
    from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active

    # register_tool indexes _tools[context_mode] directly, so the custom-mode
    # slot must exist first (built-in modes have static entries).
    VIEW3D_PT_tools_active._tools.setdefault(_CONTEXT_MODE, [None])
    bpy.utils.register_tool(SculptCoreBrushTool, separator=False)


def unregister():
    try:
        bpy.utils.unregister_tool(SculptCoreBrushTool)
    except Exception:
        pass
