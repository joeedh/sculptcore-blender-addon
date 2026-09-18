# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Make RGB clipboard source observably different from the destination."""
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
mapping = t["native_clipboard_node"].mapping
for curve in mapping.curves:
    curve.points[-1].location.y = 0.25
mapping.update()
bpy.ops.ownedcurve.native_clipboard('INVOKE_DEFAULT')
