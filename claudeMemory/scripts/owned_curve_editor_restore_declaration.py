# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Restore the intentionally removed test declaration for further editor cases."""
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
namespace = t["owner"].__globals__
namespace["OwnedEditorItem"].curve = bpy.props.CurveMappingProperty(update=namespace["updated"])
t["state"]["callback_behavior"] = None
t["state"]["declaration_removed"] = False
t["state"]["owner"] = "SCENE"
t["redraw"]()
