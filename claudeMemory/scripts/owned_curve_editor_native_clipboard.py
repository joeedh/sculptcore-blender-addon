# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create a temporary native RGB widget solely as an incompatible clipboard source."""
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
material = bpy.data.materials["OwnedEditorMaterial"]
node = material.node_tree.nodes.new('ShaderNodeRGBCurve')
t["native_clipboard_node"] = node


class OWNEDCURVE_OT_native_clipboard(bpy.types.Operator):
    bl_idname = "ownedcurve.native_clipboard"
    bl_label = "Native RGB Clipboard Test"

    def draw(self, context):
        self.layout.template_curve_mapping(node, "mapping", type='COLOR')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=450)

    def execute(self, context):
        return {'CANCELLED'}


bpy.utils.register_class(OWNEDCURVE_OT_native_clipboard)
bpy.ops.ownedcurve.native_clipboard('INVOKE_DEFAULT')
