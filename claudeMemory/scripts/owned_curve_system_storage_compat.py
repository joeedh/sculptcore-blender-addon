# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise the dynamic-RNA storage root, including undeclared old-reader saves.

This supplements the raw custom-property format test. The groups here are
ordinary PropertyGroups, not the future CurveMappingProperty API.
"""

from array import array
import json
from pathlib import Path
import sys

import bpy


phase, directory = sys.argv[sys.argv.index("--") + 1:]
root = Path(directory).resolve()
root.mkdir(parents=True, exist_ok=True)
NAME = "OwnedCurveSystemCompatibility"


class OwnedCurveCompatItem(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()


class OwnedCurveCompatRoot(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=OwnedCurveCompatItem)


def register():
    bpy.utils.register_class(OwnedCurveCompatItem)
    bpy.utils.register_class(OwnedCurveCompatRoot)
    for cls in (bpy.types.Brush, bpy.types.Scene):
        cls.owned_curve_compat = bpy.props.PointerProperty(type=OwnedCurveCompatRoot)


def unregister():
    for cls in (bpy.types.Brush, bpy.types.Scene):
        del cls.owned_curve_compat
    bpy.utils.unregister_class(OwnedCurveCompatRoot)
    bpy.utils.unregister_class(OwnedCurveCompatItem)


def check(owner):
    assert len(owner.owned_curve_compat.items) == 1
    item = owner.owned_curve_compat.items[0]
    assert item.label == "response"
    definition = item["curve"]
    assert definition["_type"] == "blender.owned_curve_mapping"
    assert type(definition["_version"]) is int and definition["_version"] == 1
    assert definition["clip"].typecode == 'd'
    assert definition["points"][1]["y"] == 0.375
    assert type(definition["points"][1]["y"]) is float
    assert definition["future_key"] == "retained"


if phase == "create":
    assert not (root / "system-definitions.blend").exists(), "Frozen fixture exists"
    register()
    brush = bpy.data.brushes.new(NAME, mode='SCULPT')
    brush.use_fake_user = True
    brush.asset_mark()
    for owner in (brush, bpy.context.scene):
        item = owner.owned_curve_compat.items.add()
        item.label = "response"
        item["curve"] = {
            "_type": "blender.owned_curve_mapping", "_version": 1,
            "clip": array('d', (0.0, 0.0, 1.0, 1.0)), "use_clip": 1,
            "extend": "EXTRAPOLATED", "default_handle": "AUTO",
            "points": [{"x": 0.0, "y": 0.0, "handle": "AUTO"},
                       {"x": 1.0, "y": 0.375, "handle": "VECTOR"}],
            "future_key": "retained",
        }
        check(owner)
    unregister()
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "system-definitions.blend"))
    bpy.data.libraries.write(str(root / "system-asset.blend"), {brush}, fake_user=True)
elif phase == "resave":
    # Crucially, no registration before or during the older reader's resave.
    bpy.ops.wm.open_mainfile(filepath=str(root / "system-definitions.blend"))
    assert not hasattr(bpy.types.Brush, "owned_curve_compat")
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "system-resaved.blend"))
    bpy.ops.wm.open_mainfile(filepath=str(root / "system-asset.blend"))
    bpy.data.libraries.write(str(root / "system-asset-resaved.blend"),
                             {bpy.data.brushes[NAME]}, fake_user=True)
    (root / "reader.json").write_text(json.dumps({
        "version": bpy.app.version_string, "binary": bpy.app.binary_path,
    }, indent=2) + "\n")
else:
    assert phase == "verify"
    register()
    bpy.ops.wm.open_mainfile(filepath=str(root / "system-resaved.blend"))
    check(bpy.data.brushes[NAME])
    check(bpy.context.scene)
    with bpy.data.libraries.load(str(root / "system-asset-resaved.blend")) as (_, target):
        target.brushes = [NAME]
    check(target.brushes[0])
    unregister()

print("OWNED_CURVE_SYSTEM_STORAGE_COMPAT_PASS " + phase, flush=True)
