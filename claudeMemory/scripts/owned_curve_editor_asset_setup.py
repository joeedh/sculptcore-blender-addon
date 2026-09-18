# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare scratch external brush assets for actual dialog edits."""
from pathlib import Path
import bpy

t = bpy.app.driver_namespace["owned_editor_test"]
root = Path("C:/dev/blender/sculptcore-blender-addon/claudeMemory/tests/owned-curve-editor-final")
library = root / "assets"
library.mkdir(exist_ok=True)
bpy.context.preferences.filepaths.asset_libraries.new(name="OwnedEditorAssets", directory=str(library))
with bpy.data.libraries.load(str(root.parent / "generic-brush-v0/legacy.blend")) as (_, target):
    target.brushes = ["GenericLegacyV0"]
source = target.brushes[0]
source.name = "OwnedEditorSource"
source.asset_mark()
source.curve_mapping_initialize("owned_editor_root.item.curve").curves[0].points[-1].location.y = 0.375
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.brush.asset_activate(asset_library_type='LOCAL', relative_asset_identifier="Brush/OwnedEditorSource")
for name in ("OwnedEditorBrush", "OwnedEditorOther"):
    assert bpy.ops.brush.asset_save_as(name=name, asset_library_reference="OwnedEditorAssets", catalog_path="") == {'FINISHED'}
t["state"]["owner"] = "BRUSH"
t["state"]["callback_behavior"] = None
t["state"]["asset_calls"] = t["state"]["callbacks"]
t["redraw"]()
assert not bpy.data.brushes["OwnedEditorBrush"].has_unsaved_changes
assert not bpy.data.brushes["OwnedEditorOther"].has_unsaved_changes
del target, _
