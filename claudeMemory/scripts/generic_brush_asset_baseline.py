# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Legacy native-curve Save/Revert baseline in the isolated migration library."""

import json
from pathlib import Path
import sys

import bpy


phase, directory = sys.argv[sys.argv.index("--") + 1:]
root = Path(directory).resolve()
bpy.ops.wm.open_mainfile(filepath=str(root / "legacy.blend"))
bpy.context.preferences.filepaths.asset_libraries.new(name="GenericBaseline", directory=str(root / "library"))
bpy.ops.object.mode_set(mode='SCULPT')
name = "GenericLifecycleV0Ready"
if phase == "capture":
    bpy.data.brushes["GenericLegacyV0"].asset_mark()
    assert bpy.ops.brush.asset_activate(asset_library_type='LOCAL',
                                       relative_asset_identifier="Brush/GenericLegacyV0") == {'FINISHED'}


def active():
    return bpy.context.tool_settings.sculpt.brush


def endpoint(brush):
    return brush.curve_strength.curves[0].points[-1].location.y


def edit(value):
    curve = active().curve_strength
    curve.curves[0].points[-1].location.y = value
    curve.update()
    bpy.context.view_layer.update()


if phase == "capture":
    target = root / ("library/Saved/Brushes/" + name + ".asset.blend")
    assert not target.exists(), "Refusing to overwrite lifecycle fixture"
    assert bpy.ops.brush.asset_save_as(name=name, asset_library_reference="GenericBaseline",
                                      catalog_path="") == {'FINISHED'}
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier="GenericBaseline",
        relative_asset_identifier="Saved/Brushes/{}.asset.blend/Brush/{}".format(name, name)) == {'FINISHED'}
    assert endpoint(active()) == 0.625
    edit(0.375)
    edit_dirty = active().has_unsaved_changes
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    assert bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier="GenericBaseline",
        relative_asset_identifier="Saved/Brushes/{}.asset.blend/Brush/{}".format(name, name)) == {'FINISHED'}
    edit(0.75)
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    assert endpoint(active()) == 0.375
    source = active()
    duplicate = source.copy()
    duplicate.curve_strength.curves[0].points[-1].location.y = 0.125
    duplicate.curve_strength.update()
    assert endpoint(source) == 0.375
    (root / "asset-lifecycle.json").write_text(json.dumps({
        "native_curve_edit_dirty": edit_dirty, "saved_endpoint": 0.375,
        "unsaved_endpoint": 0.75, "reverted_endpoint": endpoint(source),
        "copy_independent": True,
    }, indent=2) + "\n", encoding="utf-8")
else:
    assert phase == "verify"
    with bpy.data.libraries.load(str(root / ("library/Saved/Brushes/" + name + ".asset.blend")),
                                link=False) as (_, target):
        target.brushes = [name]
    assert endpoint(target.brushes[0]) == 0.375
print("GENERIC_BRUSH_ASSET_BASELINE_PASS " + phase, flush=True)
