# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Owned scalar curve asset Save As / Save / Revert and fresh-process readback."""
import json
from pathlib import Path
import sys
import bpy

phase = sys.argv[-1]
root = Path(__file__).resolve().parents[1] / "tests" / "owned-curve-assets"
library = root / "library"
library.mkdir(parents=True, exist_ok=True)
names = ("OwnedCurveEditedV1", "OwnedCurveActiveV1")
calls = []


def update(self, context):
    calls.append(self.id_data.name)


class OwnedAssetCurve(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty(update=update)


bpy.utils.register_class(OwnedAssetCurve)
bpy.types.Brush.owned_asset_curve = bpy.props.PointerProperty(type=OwnedAssetCurve)


def asset_file(name):
    return library / "Saved" / "Brushes" / (name + ".asset.blend")


def activate(name):
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier="OwnedCurveAssetTest",
        relative_asset_identifier="Saved/Brushes/{0}.asset.blend/Brush/{0}".format(name)) == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


def endpoint(brush):
    return brush.owned_asset_curve.curve.curves[0].points[-1].location.y


if phase == "read":
    with bpy.data.libraries.load(str(asset_file(names[0]))) as (_, target):
        target.brushes = [names[0]]
    assert endpoint(target.brushes[0]) == 0.375
    assert target.brushes[0].owned_asset_curve["curve"]["future_extension"] == "preserved"
else:
    assert phase == "test"
    bpy.ops.wm.open_mainfile(filepath=str(root.parent / "generic-brush-v0/legacy.blend"))
    bpy.context.preferences.filepaths.asset_libraries.new(name="OwnedCurveAssetTest", directory=str(library))
    bpy.ops.object.mode_set(mode='SCULPT')
    source = bpy.data.brushes["GenericLegacyV0"]
    source.asset_mark()
    source.curve_mapping_initialize("owned_asset_curve.curve")
    source.owned_asset_curve.curve.curves[0].points[-1].location = (1, 0.375)
    source.owned_asset_curve["curve"]["future_extension"] = "preserved"
    source.owned_asset_curve.curve_mapping_sync("curve")
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier="Brush/GenericLegacyV0") == {'FINISHED'}
    for name in names:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference="OwnedCurveAssetTest", catalog_path="") == {'FINISHED'}
        activate(name)
    edited = activate(names[0])
    edited.owned_asset_curve.curve.curves[0].points[-1].location = (1, 0.375)
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited = activate(names[0])
    active = activate(names[1])
    assert not edited.has_unsaved_changes and not active.has_unsaved_changes
    curve = edited.owned_asset_curve.curve
    point = curve.curves[0].points[-1]
    point.select = True
    curve.reset_view()
    curve.update()
    assert not edited.has_unsaved_changes
    before = len(calls)
    key_before_sync = curve.curve_mapping_cache_key()
    edited.owned_asset_curve.curve_mapping_sync("curve")
    assert curve.curve_mapping_cache_key() == key_before_sync
    assert not edited.has_unsaved_changes and len(calls) == before
    curve.curves[0].points[-1].location = (1, 0.75)
    assert endpoint(edited) == 0.75 and edited.has_unsaved_changes
    assert not active.has_unsaved_changes and len(calls) == before + 1
    assert calls[-1] == names[0]
    edited = activate(names[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    assert endpoint(reverted) == 0.375 and not reverted.has_unsaved_changes
    try:
        curve.curves
    except ReferenceError:
        pass
    else:
        raise AssertionError("Revert retained an old owned curve handle")
    assert reverted.owned_asset_curve["curve"]["future_extension"] == "preserved"
    assert endpoint(source) == 0.375
    (root / "test.json").write_text(json.dumps({
        "saved": 0.375, "edited": 0.75, "reverted": endpoint(reverted),
        "unrelated_active_clean": not active.has_unsaved_changes,
        "retained_handle_invalidated": True, "extension_preserved": True,
        "binary": bpy.app.binary_path,
    }, indent=2) + "\n")

del bpy.types.Brush.owned_asset_curve
bpy.utils.unregister_class(OwnedAssetCurve)
print("OWNED_CURVE_ASSETS_PASS " + phase, flush=True)
