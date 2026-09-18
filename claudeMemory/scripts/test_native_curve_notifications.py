# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native brush curve/automasking owner regression and external Save/Revert.

Run with -- test DIR, then -- verify DIR in a fresh process. The test creates
two scratch external assets; it never saves user preferences or baseline files.
"""

import json
from pathlib import Path
import sys

import bpy


phase, directory = sys.argv[sys.argv.index("--") + 1:]
root = Path(directory).resolve()
library = root / "library"
library.mkdir(parents=True, exist_ok=True)
NAMES = ("NativeCurveEditedOwnerV1", "NativeCurveActiveOwnerV1")


def asset_file(name):
    return library / "Saved" / "Brushes" / (name + ".asset.blend")


def activate(name):
    result = bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier="NativeCurveOwnerTest",
        relative_asset_identifier="Saved/Brushes/{0}.asset.blend/Brush/{0}".format(name))
    assert result == {'FINISHED'}
    return bpy.context.tool_settings.sculpt.brush


def endpoint(brush):
    return brush.curve_strength.curves[0].points[-1].location.y


if phase == "verify":
    with bpy.data.libraries.load(str(asset_file(NAMES[0]))) as (_, target):
        target.brushes = [NAMES[0]]
    assert endpoint(target.brushes[0]) == 0.375
    print("NATIVE_CURVE_NOTIFICATIONS_PASS fresh-process readback", flush=True)
else:
    assert phase == "test"
    baseline = Path(__file__).resolve().parents[1] / "tests/generic-brush-v0/legacy.blend"
    bpy.ops.wm.open_mainfile(filepath=str(baseline))
    bpy.context.preferences.filepaths.asset_libraries.new(
        name="NativeCurveOwnerTest", directory=str(library))
    bpy.ops.object.mode_set(mode='SCULPT')
    source = bpy.data.brushes["GenericLegacyV0"]
    source.asset_mark()
    assert bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier="Brush/GenericLegacyV0") == {'FINISHED'}
    for name in NAMES:
        if not asset_file(name).exists():
            assert bpy.ops.brush.asset_save_as(
                name=name, asset_library_reference="NativeCurveOwnerTest", catalog_path="") == {'FINISHED'}
        activate(name)

    # Establish a real, repeatable mutation baseline even after an earlier run.
    edited = activate(NAMES[0])
    initial = edited.curve_strength
    initial.curves[0].points[-1].location.y = 0.625
    initial.curves[0].points[-1].handle_type = 'AUTO'
    if len(initial.curves[0].points) == 2:
        initial.curves[0].points.new(0.5, 0.5)
    assert len(initial.curves[0].points) == 3
    initial.use_clip = True
    initial.clip_max_y = 1.0
    initial.extend = 'EXTRAPOLATED'
    initial.update()
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    activate(NAMES[0])

    results = []

    def check_mutation(label, mutate):
        edited = activate(NAMES[0])
        assert bpy.ops.brush.asset_revert() == {'FINISHED'}
        edited = bpy.context.tool_settings.sculpt.brush
        active = activate(NAMES[1])
        assert not edited.has_unsaved_changes
        assert not active.has_unsaved_changes
        mutate(edited)
        assert edited.has_unsaved_changes, label + " did not dirty its owner"
        assert not active.has_unsaved_changes, label + " dirtied the active brush"
        results.append(label)

    check_mutation("point location", lambda b: setattr(
        b.curve_strength.curves[0].points[-1].location, "y", 0.375))
    check_mutation("point handle", lambda b: setattr(
        b.curve_strength.curves[0].points[-1], "handle_type", 'VECTOR'))
    check_mutation("point insertion", lambda b: b.curve_strength.curves[0].points.new(0.5, 0.25))
    # Setup saved three points, so removal independently changes the curve.
    check_mutation("point removal", lambda b: b.curve_strength.curves[0].points.remove(
        b.curve_strength.curves[0].points[1]))
    check_mutation("explicit update", lambda b: b.curve_strength.update())
    check_mutation("clip toggle", lambda b: setattr(b.curve_strength, "use_clip", False))
    check_mutation("clip bounds", lambda b: setattr(b.curve_strength, "clip_max_y", 2.0))
    check_mutation("extension", lambda b: setattr(b.curve_strength, "extend", 'HORIZONTAL'))
    check_mutation("black levels", lambda b: setattr(b.curve_strength, "black_level", (0.1, 0.0, 0.0)))
    check_mutation("white levels", lambda b: setattr(b.curve_strength, "white_level", (0.9, 1.0, 1.0)))
    check_mutation("automasking scalar", lambda b: setattr(
        b.mesh_automasking_settings, "cavity_factor", 2.5))
    check_mutation("automasking curve", lambda b: setattr(
        b.mesh_automasking_settings.cavity_curve.curves[0].points[-1].location, "y", 0.375))

    edited = activate(NAMES[0])
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    edited = bpy.context.tool_settings.sculpt.brush
    active = activate(NAMES[1])
    try:
        edited.curve_strength.curves[0].points.remove(active.curve_strength.curves[0].points[1])
    except RuntimeError:
        pass
    else:
        raise AssertionError("Foreign point removal succeeded")
    assert not edited.has_unsaved_changes and not active.has_unsaved_changes
    results.append("rejected foreign point removal leaves both owners clean")
    current_scene = bpy.context.scene
    inactive_scene = current_scene.copy()
    settings = inactive_scene.tool_settings.sculpt.mesh_automasking_settings
    current_factor = current_scene.tool_settings.sculpt.mesh_automasking_settings.cavity_factor
    assert settings.id_data == inactive_scene
    settings.cavity_factor = 2.5
    settings.cavity_curve.curves[0].points[-1].location.y = 0.375
    settings.cavity_curve.update()
    assert bpy.context.scene == current_scene
    assert current_scene.tool_settings.sculpt.mesh_automasking_settings.cavity_factor == current_factor
    assert not edited.has_unsaved_changes and not active.has_unsaved_changes
    results.append("inactive scene edits preserve current scene values and both brushes' dirty states")
    curve = edited.curve_strength
    curve.curves[0].points[-1].select = True
    curve.reset_view()
    curve.initialize()
    assert not edited.has_unsaved_changes
    results.append("selection/view/initialize leave brush clean")

    edited = activate(NAMES[0])
    edited.curve_strength.curves[0].points[-1].location.y = 0.375
    edited.curve_strength.update()
    assert edited.has_unsaved_changes
    assert bpy.ops.brush.asset_save() == {'FINISHED'}
    edited = activate(NAMES[0])
    assert not edited.has_unsaved_changes
    edited.curve_strength.curves[0].points[-1].location.y = 0.75
    edited.curve_strength.update()
    assert edited.has_unsaved_changes
    assert bpy.ops.brush.asset_revert() == {'FINISHED'}
    reverted = bpy.context.tool_settings.sculpt.brush
    assert endpoint(reverted) == 0.375
    assert not reverted.has_unsaved_changes
    results.append("Save .375 / edit .75 / Revert .375 with dirty state")
    (root / "results.json").write_text(json.dumps({
        "checks": results, "binary": bpy.app.binary_path,
        "version": bpy.app.version_string,
    }, indent=2) + "\n", encoding="utf-8")
    print("NATIVE_CURVE_NOTIFICATIONS_PASS " + str(len(results)), flush=True)
