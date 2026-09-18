# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Inspect the test-owned second window without changing the first dialog."""
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
window = bpy.context.window_manager.windows[1]
for area in window.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.show_region_ui = True
        area.tag_redraw()


def screenshot():
    with bpy.context.temp_override(window=window):
        bpy.ops.screen.screenshot(filepath="C:/dev/blender/sculptcore-blender-addon/claudeMemory/tests/owned-curve-editor-final/second_window.png")
    return None


bpy.app.timers.register(screenshot, first_interval=0.3)
