# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Probe node-backed brush curves using real asset operators in a scratch library.

Run with Blender --background --factory-startup --python-exit-code 1 --python
this_file -- create|reload|verify SCRATCH_DIRECTORY. Never saves user preferences.
"""

import json
from pathlib import Path
import sys

import bpy


class CurveAssetProbeSettings(bpy.types.PropertyGroup):
    tree: bpy.props.PointerProperty(type=bpy.types.NodeTree)


def emit(label, **values):
    print("CURVE_PROBE " + json.dumps({"check": label, **values}), flush=True)


def active():
    return bpy.context.tool_settings.sculpt.brush


def mapping(brush):
    return brush.curve_asset_probe.tree.nodes["response"].mapping


def ordinate(brush):
    return float(mapping(brush).curves[0].points[1].location.y)


def edit(brush, value):
    curve = mapping(brush)
    curve.curves[0].points[1].location.y = value
    curve.update()
    bpy.context.view_layer.update()


def activate(name):
    result = bpy.ops.brush.asset_activate(
        asset_library_type='CUSTOM', asset_library_identifier="CurveProbe",
        relative_asset_identifier="Saved/Brushes/{}.asset.blend/Brush/{}".format(name, name))
    assert result == {'FINISHED'}, result
    return active()


def main():
    phase, scratch_arg = sys.argv[sys.argv.index("--") + 1:]
    scratch = Path(scratch_arg).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    library_path = scratch / "library"
    library_path.mkdir(exist_ok=True)
    bpy.context.preferences.filepaths.asset_libraries.new(name="CurveProbe", directory=str(library_path))
    bpy.utils.register_class(CurveAssetProbeSettings)
    bpy.types.Brush.curve_asset_probe = bpy.props.PointerProperty(type=CurveAssetProbeSettings)
    bpy.ops.object.mode_set(mode='SCULPT')
    emit("build", version=bpy.app.version_string,
         build_hash=bpy.app.build_hash.decode(), phase=phase)

    if phase == "create":
        brush = bpy.data.brushes.new("CurveProbeSource", mode='SCULPT')
        brush.asset_mark()
        tree = bpy.data.node_groups.new(".CurveProbeStorage", 'ShaderNodeTree')
        node = tree.nodes.new('ShaderNodeFloatCurve')
        node.name = "response"
        node.mapping.initialize()
        brush.curve_asset_probe.tree = tree
        edit(brush, 0.625)
        bpy.ops.brush.asset_activate(asset_library_type='LOCAL',
                                    relative_asset_identifier="Brush/CurveProbeSource")
        result = bpy.ops.brush.asset_save_as(
            name="CurveProbe", asset_library_reference="CurveProbe", catalog_path="")
        assert result == {'FINISHED'}, result
        brush = active()
        assert abs(ordinate(brush) - 0.625) < 1e-6
        emit("save_as_external", brush_library=brush.library.filepath,
             tree_library=brush.curve_asset_probe.tree.library.filepath,
             tree_editable=brush.curve_asset_probe.tree.is_editable,
             y=ordinate(brush), dirty=brush.has_unsaved_changes)
        assert (library_path / "Saved/Brushes/CurveProbe.asset.blend").is_file()
        return

    if phase == "verify":
        brush = activate("CurveProbe")
        assert abs(ordinate(brush) - 0.375) < 1e-6
        emit("fresh_process_saved_edit", y=ordinate(brush))
        edit(brush, 0.75)
        old_tree_pointer = brush.curve_asset_probe.tree.as_pointer()
        result = bpy.ops.brush.asset_revert()
        assert result == {'FINISHED'}, result
        brush = active()
        emit("isolated_revert_dependency", expected_y=0.375, actual_y=ordinate(brush),
             reused_tree=brush.curve_asset_probe.tree.as_pointer() == old_tree_pointer,
             tree_users=brush.curve_asset_probe.tree.users,
             dirty=brush.has_unsaved_changes)
        brush.strength = brush.strength
        emit("native_property_update_marks_dirty", dirty=brush.has_unsaved_changes)
        return

    brush = activate("CurveProbe")
    assert abs(ordinate(brush) - 0.625) < 1e-6
    emit("fresh_process_reload", y=ordinate(brush),
         tree_editable=brush.curve_asset_probe.tree.is_editable,
         dirty=brush.has_unsaved_changes)

    edit(brush, 0.375)
    emit("curve_edit_dirty", y=ordinate(brush), dirty=brush.has_unsaved_changes)
    brush.update_tag()
    bpy.context.view_layer.update()
    emit("brush_update_tag_dirty", dirty=brush.has_unsaved_changes)

    result = bpy.ops.brush.asset_save()
    assert result == {'FINISHED'}, result
    emit("save_external_edit", y=ordinate(brush), dirty=brush.has_unsaved_changes)
    with bpy.data.libraries.load(brush.library.filepath, link=False) as (source, target):
        target.brushes = ["CurveProbe"]
    disk_brush = target.brushes[0]
    assert abs(ordinate(disk_brush) - 0.375) < 1e-6
    emit("saved_dependency_readback", y=ordinate(disk_brush))

    # A generic ID.copy and the brush asset's own duplication operator differ.
    shallow = brush.copy()
    emit("id_copy_shares_tree", shared=shallow.curve_asset_probe.tree == brush.curve_asset_probe.tree)
    original_tree = brush.curve_asset_probe.tree
    result = bpy.ops.brush.asset_save_as(
        name="CurveProbeLocalCopy", asset_library_reference='LOCAL', catalog_path="")
    assert result == {'FINISHED'}, result
    local_brush = active()
    assert local_brush.curve_asset_probe.tree != original_tree
    edit(local_brush, 0.125)
    assert abs(ordinate(brush) - 0.375) < 1e-6
    emit("local_asset_copy_independent", source_y=ordinate(brush), copy_y=ordinate(local_brush))

    brush = activate("CurveProbe")
    result = bpy.ops.brush.asset_save_as(
        name="CurveProbeExternalCopy", asset_library_reference="CurveProbe", catalog_path="")
    assert result == {'FINISHED'}, result
    external_copy = active()
    assert external_copy.curve_asset_probe.tree != original_tree
    edit(external_copy, 0.875)
    assert abs(ordinate(brush) - 0.375) < 1e-6
    emit("external_asset_copy_independent", source_y=ordinate(brush), copy_y=ordinate(external_copy))

    brush = activate("CurveProbe")
    edit(brush, 0.75)
    original_pointer = brush.curve_asset_probe.tree.as_pointer()
    result = bpy.ops.brush.asset_revert()
    assert result == {'FINISHED'}, result
    brush = active()
    emit("revert_dependency", expected_y=0.375, actual_y=ordinate(brush),
         reused_tree=brush.curve_asset_probe.tree.as_pointer() == original_pointer,
         dirty=brush.has_unsaved_changes)


main()
