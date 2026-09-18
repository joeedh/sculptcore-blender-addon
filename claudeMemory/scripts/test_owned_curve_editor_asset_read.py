# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read the actual headed editor asset fixture in a separate Blender process."""
import bpy
from pathlib import Path


class OwnedEditorItem(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty()


class OwnedEditorRoot(bpy.types.PropertyGroup):
    item: bpy.props.PointerProperty(type=OwnedEditorItem)


bpy.utils.register_class(OwnedEditorItem)
bpy.utils.register_class(OwnedEditorRoot)
bpy.types.Brush.owned_editor_root = bpy.props.PointerProperty(type=OwnedEditorRoot)
root = Path(__file__).resolve().parents[1] / "tests/owned-curve-editor-final/assets/Saved/Brushes"
for name in ("OwnedEditorBrush", "OwnedEditorOther"):
    with bpy.data.libraries.load(str(root / (name + ".asset.blend"))) as (_, target):
        target.brushes = [name]
    curve = target.brushes[0].owned_editor_root.item.curve
    assert curve.curves[0].points[-1].location.y == 0.375
    assert len(curve.curve_mapping_cache_key()) == 2
del target, _
del bpy.types.Brush.owned_editor_root
bpy.utils.unregister_class(OwnedEditorRoot)
bpy.utils.unregister_class(OwnedEditorItem)
print("OWNED_CURVE_EDITOR_ASSET_FRESH_READ_PASS", flush=True)
