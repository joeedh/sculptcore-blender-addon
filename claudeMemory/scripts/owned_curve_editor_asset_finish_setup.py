# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Finish asynchronous asset setup after the event loop has loaded the first asset."""
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
assert bpy.context.tool_settings.sculpt.brush.name == "OwnedEditorBrush"
assert bpy.ops.brush.asset_save_as(name="OwnedEditorOther", asset_library_reference="OwnedEditorAssets", catalog_path="") == {'FINISHED'}
t["state"]["owner"] = "BRUSH"
t["state"]["callback_behavior"] = None
t["state"]["asset_calls"] = t["state"]["callbacks"]
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.show_region_asset_shelf = False
t["redraw"]()
