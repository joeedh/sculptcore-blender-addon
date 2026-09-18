# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Test old-reader preservation of the selected owned-curve IDProperty format.

Run producer with -- create DIR, older reader with -- resave DIR, then the
producer again with -- verify DIR. No curve declarations or node trees used.
"""

from array import array
import json
from pathlib import Path
import sys

import bpy


phase, directory = sys.argv[sys.argv.index("--") + 1:]
root = Path(directory).resolve()
root.mkdir(parents=True, exist_ok=True)


def definition():
    return {
        "_type": "blender.owned_curve_mapping", "_version": 1,
        "clip": array('d', (0.0, 0.0, 1.0, 1.0)), "use_clip": 1,
        "extend": "EXTRAPOLATED", "default_handle": "AUTO",
        "points": [{"x": 0.0, "y": 0.0, "handle": "AUTO"},
                   {"x": 1.0, "y": 0.375, "handle": "VECTOR"}],
        "future_key": "preserve verbatim",
    }


def check(brush, scene):
    expected = definition()
    expected["clip"] = list(expected["clip"])
    for owner in (brush, scene):
        curve = owner["curve_test"]["items"][0]["curve"]
        assert curve.to_dict() == expected
        assert type(curve["_version"]) is int and type(curve["use_clip"]) is int
        assert curve["clip"].typecode == 'd'
        for point in curve["points"]:
            assert type(point["x"]) is float and type(point["y"]) is float
            assert type(point["handle"]) is str
    assert not bpy.data.node_groups
    assert brush["curve_test"]["items"][0]["curve"]["points"][1]["y"] == 0.375


if phase == "create":
    assert not (root / "owned-definitions.blend").exists(), "Refusing to replace fixture"
    brush = bpy.data.brushes.new("OwnedDefinitionCompatibility", mode='SCULPT')
    brush.use_fake_user = True
    brush.asset_mark()
    scene = bpy.context.scene
    for owner in (brush, scene):
        owner["curve_test"] = {"items": [{"curve": definition()}]}
    check(brush, scene)
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "owned-definitions.blend"))
    bpy.data.libraries.write(str(root / "owned-asset.blend"), {brush}, fake_user=True)
elif phase == "resave":
    bpy.ops.wm.open_mainfile(filepath=str(root / "owned-definitions.blend"))
    check(bpy.data.brushes["OwnedDefinitionCompatibility"], bpy.context.scene)
    bpy.ops.wm.save_as_mainfile(filepath=str(root / "old-reader-resaved.blend"))
    bpy.ops.wm.open_mainfile(filepath=str(root / "owned-asset.blend"))
    brush = bpy.data.brushes["OwnedDefinitionCompatibility"]
    assert brush["curve_test"]["items"][0]["curve"]["points"][1]["y"] == 0.375
    bpy.data.libraries.write(str(root / "old-reader-asset.blend"), {brush}, fake_user=True)
    (root / "reader.json").write_text(json.dumps({"version": bpy.app.version_string,
                                                 "binary": bpy.app.binary_path}, indent=2) + "\n")
else:
    assert phase == "verify"
    bpy.ops.wm.open_mainfile(filepath=str(root / "old-reader-resaved.blend"))
    brush = bpy.data.brushes["OwnedDefinitionCompatibility"]
    check(brush, bpy.context.scene)
    original = brush["curve_test"].to_dict()
    with bpy.data.libraries.load(str(root / "old-reader-asset.blend"), link=False) as (_, target):
        target.brushes = ["OwnedDefinitionCompatibility"]
    assert target.brushes[0]["curve_test"].to_dict() == original
    copied = brush.copy()
    copied["curve_test"]["items"][0]["curve"]["points"][1]["y"] = 0.75
    assert brush["curve_test"]["items"][0]["curve"]["points"][1]["y"] == 0.375
print("OWNED_CURVE_STORAGE_COMPAT_PASS " + phase, flush=True)
