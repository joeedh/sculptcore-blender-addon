# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Test-owned headed curve editor, event helpers, screenshots and opt-in debug server."""

import importlib.util
import json
import os
from pathlib import Path
import time

import bpy

repository = Path(__file__).resolve().parents[2]
output = repository / "claudeMemory" / "tests" / os.environ.get("OWNED_CURVE_EDITOR_OUTPUT", "owned-curve-editor-final")
output.mkdir(parents=True, exist_ok=True)
state = {"draws": 0, "callbacks": 0, "path": "owned_editor_root.item.curve", "owner": "SCENE"}


def updated(self, context):
    state["callbacks"] += 1
    behavior = state.get("callback_behavior")
    if behavior == "delete_owner" and isinstance(self.id_data, bpy.types.Brush):
        bpy.data.brushes.remove(self.id_data)
        state["owner"] = "SCENE"
    elif behavior == "unregister":
        bpy.props.RemoveProperty(OwnedEditorItem, attr="curve")
        state["declaration_removed"] = True


class OwnedEditorItem(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty(update=updated)


class OwnedEditorRoot(bpy.types.PropertyGroup):
    item: bpy.props.PointerProperty(type=OwnedEditorItem)


def owner():
    kind = state["owner"]
    if kind == "SCENE":
        return bpy.context.scene
    if kind == "TREE":
        return bpy.data.materials["OwnedEditorMaterial"].node_tree
    return bpy.data.brushes["OwnedEditorBrush"]


class OWNEDCURVE_PT_editor_test(bpy.types.Panel):
    bl_label = "Owned Curve Editor Test"
    bl_idname = "OWNEDCURVE_PT_editor_test"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Item"
    bl_order = -10000

    def draw(self, context):
        state["draws"] += 1
        if state.get("declaration_removed"):
            self.layout.label(text="Test declaration removed")
            return
        self.layout.template_owned_curve_mapping(owner(), state["path"])


for cls in (OwnedEditorItem, OwnedEditorRoot, OWNEDCURVE_PT_editor_test):
    bpy.utils.register_class(cls)
for cls in (bpy.types.Scene, bpy.types.Brush, bpy.types.NodeTree):
    cls.owned_editor_root = bpy.props.PointerProperty(type=OwnedEditorRoot)
    cls.owned_editor_items = bpy.props.CollectionProperty(type=OwnedEditorItem)
bpy.data.brushes.new("OwnedEditorBrush", mode='SCULPT')
material = bpy.data.materials.new("OwnedEditorMaterial")
material.use_nodes = True
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.show_region_ui = True


def event(kind, value='PRESS', x=None, y=None, **kwargs):
    window = bpy.context.window_manager.windows[0]
    if x is None:
        x, y = state.get("cursor", (500, 500))
    state["cursor"] = (int(x), int(y))
    window.event_simulate(type=kind, value=value, x=int(x), y=int(y), **kwargs)


def click(x, y):
    event('MOUSEMOVE', 'NOTHING', x, y)
    event('LEFTMOUSE', 'PRESS', x, y)
    event('LEFTMOUSE', 'RELEASE', x, y)


def screenshot(name):
    path = output / (name + ".png")
    bpy.ops.screen.screenshot(filepath=str(path))
    return str(path)


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def describe():
    data = owner()
    return {
        "draws": state["draws"], "callbacks": state["callbacks"],
        "root_set": data.is_property_set("owned_editor_root"),
        "curve_set": data.is_property_set("owned_editor_root") and data.owned_editor_root.item.curve is not None,
        "areas": [(a.type, a.x, a.y, a.width, a.height) for a in bpy.context.screen.areas],
    }


spec = importlib.util.spec_from_file_location("owned_editor_debug_helper", repository / "tools" / "blender_debug.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
server = helper.load_server()
helper.publish_connection(output / "connection.json", server.start())
bpy.app.driver_namespace["owned_editor_test"] = {
    "state": state, "owner": owner, "event": event, "click": click,
    "screenshot": screenshot, "redraw": redraw, "describe": describe,
}


def ready():
    assert not owner().is_property_set("owned_editor_root"), "Drawing allocated absent storage"
    bpy.ops.ed.undo_push(message="Owned editor unset baseline")
    screenshot("initial")
    print("OWNED_EDITOR_READY", json.dumps(describe()), flush=True)
    return None


bpy.app.timers.register(ready, first_interval=2.0)
deadline = time.monotonic() + 1800


def timeout():
    if time.monotonic() >= deadline:
        print("OWNED_EDITOR_TIMEOUT", flush=True)
        bpy.ops.wm.quit_blender()
        return None
    return 10.0


bpy.app.timers.register(timeout, first_interval=10.0)
