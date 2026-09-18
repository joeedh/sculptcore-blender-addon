# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headed RNA undo/redo, cache identity and curve-template smoke test."""
import json
from pathlib import Path
import traceback
import bpy

root = Path(__file__).resolve().parents[1] / "tests" / "owned-curve-rna"
state = {"phase": 0, "draws": 0}


class OwnedUndoItem(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty()


class OwnedUndoRoot(bpy.types.PropertyGroup):
    item: bpy.props.PointerProperty(type=OwnedUndoItem)


class OWNEDCURVE_PT_test(bpy.types.Panel):
    bl_label = "Owned Curve RNA Test"
    bl_idname = "OWNEDCURVE_PT_test"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Item"

    def draw(self, context):
        state["draws"] += 1
        scene = context.scene
        if scene.is_property_set("owned_undo_root"):
            self.layout.template_curve_mapping(scene.owned_undo_root.item, "curve")
        else:
            self.layout.label(text="Unset curve")


for cls in (OwnedUndoItem, OwnedUndoRoot, OWNEDCURVE_PT_test):
    bpy.utils.register_class(cls)
bpy.types.Scene.owned_undo_root = bpy.props.PointerProperty(type=OwnedUndoRoot)
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.show_region_ui = True


def endpoint():
    return bpy.context.scene.owned_undo_root.item.curve.curves[0].points[-1].location.y


def stale(value):
    try:
        value.curves
    except ReferenceError:
        return
    raise AssertionError("Undo kept an old curve wrapper attached")


def step():
    try:
        phase = state["phase"]
        if phase == 0:
            assert not bpy.context.scene.is_property_set("owned_undo_root")
            bpy.ops.ed.undo_push(message="Owned unset baseline")
        elif phase == 1:
            curve = bpy.context.scene.curve_mapping_initialize("owned_undo_root.item.curve")
            curve.curves[0].points[-1].location = (1, 0.375)
            state["created"] = curve
            state["created_key"] = curve.curve_mapping_cache_key()
            bpy.ops.ed.undo_push(message="Owned initialize")
        elif phase == 2:
            bpy.context.scene.owned_undo_root.item.curve.curves[0].points[-1].location = (1, 0.75)
            state["edited"] = bpy.context.scene.owned_undo_root.item.curve
            state["edited_key"] = state["edited"].curve_mapping_cache_key()
            state["captured_key_method"] = state["edited"].curve_mapping_cache_key
            bpy.ops.ed.undo_push(message="Owned edit")
        elif phase == 3:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert endpoint() == 0.375
            stale(state["edited"])
            key = bpy.context.scene.owned_undo_root.item.curve.curve_mapping_cache_key()
            assert key[0] != state["edited_key"][0]
            try:
                state["captured_key_method"]()
            except ReferenceError:
                pass
            else:
                raise AssertionError("Captured cache method survived undo")
            state["undo_key"] = key
        elif phase == 4:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert not bpy.context.scene.is_property_set("owned_undo_root")
            stale(state["created"])
        elif phase == 5:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert endpoint() == 0.375
            key = bpy.context.scene.owned_undo_root.item.curve.curve_mapping_cache_key()
            assert key[0] not in (state["created_key"][0], state["undo_key"][0])
        else:
            assert state["draws"] > 0
            (root / "headed.json").write_text(json.dumps({
                "undo_edit": 0.375, "undo_initialize_unset": True, "redo": endpoint(),
                "old_wrappers_invalidated": True, "template_draws": state["draws"],
                "editor_drag_tested": False,
                "cache_identity_and_captured_method_undo_redo": True,
            }, indent=2) + "\n")
            print("OWNED_CURVE_HEADED_PASS RNA/cache undo/redo and template", flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state["phase"] += 1
        for area in bpy.context.screen.areas:
            area.tag_redraw()
        return 0.4
    except Exception:
        traceback.print_exc()
        print("OWNED_CURVE_HEADED_FAIL", flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1.0)
