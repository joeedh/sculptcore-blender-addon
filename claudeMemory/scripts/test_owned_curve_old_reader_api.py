# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Materialize old-reader-preserved system fixtures through the new RNA API."""
import json
from pathlib import Path
import bpy


class OwnedCurveCompatItem(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    curve: bpy.props.CurveMappingProperty()


class OwnedCurveCompatRoot(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=OwnedCurveCompatItem)


bpy.utils.register_class(OwnedCurveCompatItem)
bpy.utils.register_class(OwnedCurveCompatRoot)
for cls in (bpy.types.Brush, bpy.types.Scene):
    cls.owned_curve_compat = bpy.props.PointerProperty(type=OwnedCurveCompatRoot)
root = Path(__file__).resolve().parents[1] / "tests"
checks = []


def check(owner):
    item = owner.owned_curve_compat.items[0]
    mapping = item.curve
    assert isinstance(mapping, bpy.types.CurveMapping)
    assert mapping.curves[0].points[-1].location.y == 0.375
    assert mapping.evaluate(mapping.curves[0], 1.0) == 0.375
    assert item["curve"]["future_key"] == "retained"


for folder in ("owned-curve-system-compat-v1", "owned-curve-system-compat-prefork-v1"):
    directory = root / folder
    bpy.ops.wm.open_mainfile(filepath=str(directory / "system-resaved.blend"))
    check(bpy.data.brushes["OwnedCurveSystemCompatibility"])
    check(bpy.context.scene)
    with bpy.data.libraries.load(str(directory / "system-asset-resaved.blend")) as (_, target):
        target.brushes = ["OwnedCurveSystemCompatibility"]
    check(target.brushes[0])
    del target, _
    checks.append(folder)
for cls in (bpy.types.Brush, bpy.types.Scene):
    del cls.owned_curve_compat
bpy.utils.unregister_class(OwnedCurveCompatRoot)
bpy.utils.unregister_class(OwnedCurveCompatItem)
(root / "owned-curve-rna/old-reader-api.json").write_text(json.dumps(checks, indent=2) + "\n")
print("OWNED_CURVE_OLD_READER_API_PASS 2 readers, Brush/Scene/library", flush=True)
