# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Capture/read pre-migration fixtures with the staged Blender and engine.

Run in background Blender with -- capture|verify OUTPUT_DIRECTORY.
Capture refuses to replace its frozen oracle. Verify runs in a fresh process.
"""

import ast
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np

from sculptcore_addon import convert, engine, engine_props, handlers, mapping, stroke


ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "local_strength": 0.25, "scene_strength": 0.75,
    "local_size": 80, "scene_size": 160,
    "local_cavity": [1.75, 3, 0.375], "scene_cavity": [0.625, 1, 0.875],
    "spacing": 23, "dyntopo_spacing": 0.875, "smooth_lambda": 0.375,
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def metadata(owner):
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.identifier == "rna_type":
            continue
        row = {"type": prop.type, "readonly": prop.is_readonly,
               "description": prop.description}
        for name in ("default", "hard_min", "hard_max", "soft_min", "soft_max", "unit", "subtype"):
            value = getattr(prop, name, None)
            if isinstance(value, (str, int, float, bool)):
                row[name] = value
        if getattr(prop, "is_array", False):
            row["default"] = list(prop.default_array)
        if prop.type == 'ENUM':
            row["items"] = [item.identifier for item in prop.enum_items]
        result[prop.identifier] = row
    return result


def edit_endpoint(curve, endpoint):
    curve.initialize()
    curve.curves[0].points[-1].location.y = endpoint
    curve.update()


def cavity_values(settings):
    return [settings.cavity_factor, settings.cavity_blur_steps,
            settings.cavity_curve.curves[0].points[-1].location.y]


def check_settings(brush):
    paint = bpy.context.tool_settings.sculpt
    unified = paint.unified_paint_settings
    assert brush.strength == EXPECTED["local_strength"]
    assert brush.size == EXPECTED["local_size"]
    assert mapping.unified_size(paint, brush) == EXPECTED["scene_size"]
    assert mapping.pixel_radius(paint, brush) == 80
    assert unified.strength == EXPECTED["scene_strength"]
    assert brush.spacing == EXPECTED["spacing"]
    assert not brush.sculptcore_use_pressure_strength
    assert brush.sculptcore_use_pressure_size
    assert brush.use_pressure_strength and not brush.use_pressure_size
    assert brush.curve_strength.curves[0].points[-1].location.y == 0.625
    assert brush.curve_size.curves[0].points[-1].location.y == 0.875
    assert brush.curve_distance_falloff_preset == 'CUSTOM'
    assert brush.curve_distance_falloff.curves[0].points[-1].location.y == 0.125
    assert bpy.context.scene.sculptcore_dyntopo_spacing == EXPECTED["dyntopo_spacing"]
    assert bpy.context.scene.sculptcore_dyntopo_smooth_lambda == EXPECTED["smooth_lambda"]
    local, scene = brush.mesh_automasking_settings, paint.mesh_automasking_settings
    assert cavity_values(local) == EXPECTED["local_cavity"]
    assert cavity_values(scene) == EXPECTED["scene_cavity"]
    assert local.use_automasking_custom_cavity_curve and scene.use_automasking_custom_cavity_curve
    for b, s, expected in ((False, False, None), (False, True, scene),
                           (True, False, local), (True, True, local)):
        local.use_automasking_cavity = b
        scene.use_automasking_cavity = s
        assert mapping.cavity_settings(brush, paint) == expected
    for b, s in ((False, True), (True, False), (True, True)):
        local.use_automasking_cavity = False
        scene.use_automasking_cavity = False
        local.use_automasking_cavity_inverted = b
        scene.use_automasking_cavity_inverted = s
        assert mapping.cavity_settings(brush, paint) == (local if b else scene)
    local.use_automasking_cavity_inverted = False
    scene.use_automasking_cavity_inverted = False
    local.use_automasking_cavity = True
    scene.use_automasking_cavity = True


def make_fixture():
    brush = bpy.data.brushes.new("GenericLegacyV0", mode='SCULPT')
    brush.use_fake_user = True
    brush.strength = EXPECTED["local_strength"]
    brush.size = EXPECTED["local_size"]
    brush.spacing = EXPECTED["spacing"]
    brush.use_pressure_strength = True
    brush.use_pressure_size = False
    brush.sculptcore_use_pressure_strength = False
    brush.sculptcore_use_pressure_size = True
    brush.curve_distance_falloff_preset = 'CUSTOM'
    edit_endpoint(brush.curve_strength, 0.625)
    edit_endpoint(brush.curve_size, 0.875)
    edit_endpoint(brush.curve_distance_falloff, 0.125)
    paint = bpy.context.tool_settings.sculpt
    unified = paint.unified_paint_settings
    unified.use_unified_size = unified.use_unified_strength = True
    unified.size = EXPECTED["scene_size"]
    unified.strength = EXPECTED["scene_strength"]
    for settings, values in ((brush.mesh_automasking_settings, EXPECTED["local_cavity"]),
                             (paint.mesh_automasking_settings, EXPECTED["scene_cavity"])):
        settings.use_automasking_cavity = True
        settings.cavity_factor, settings.cavity_blur_steps = values[:2]
        settings.use_automasking_custom_cavity_curve = True
        edit_endpoint(settings.cavity_curve, values[2])
    scene = bpy.context.scene
    scene.sculptcore_dyntopo_spacing = EXPECTED["dyntopo_spacing"]
    scene.sculptcore_dyntopo_smooth_lambda = EXPECTED["smooth_lambda"]
    names = sorted(prop.identifier for prop in brush.sculptcore.bl_rna.properties
                   if prop.type == 'FLOAT')
    assert "planeSide" in names
    assert not brush.sculptcore.is_property_set("planeSide")
    for i, name in enumerate(name for name in names if name != "planeSide"):
        prop = brush.sculptcore.bl_rna.properties[name]
        if i % 2:
            setattr(brush.sculptcore, name, prop.default)
        elif i % 3 == 0:
            setattr(brush.sculptcore, name, min(prop.hard_max, max(prop.hard_min, prop.default + 0.125)))
    return brush


def authored(group):
    return {p.identifier: {"value": getattr(group, p.identifier),
                           "set": group.is_property_set(p.identifier)}
            for p in group.bl_rna.properties if p.type == 'FLOAT'}


def source_inventory(brush):
    paint = bpy.context.tool_settings.sculpt
    owners = {
        "Brush": brush, "Brush.sculptcore": brush.sculptcore,
        "Brush.mesh_automasking_settings": brush.mesh_automasking_settings,
        "Scene.tool_settings.sculpt": paint,
        "Scene.tool_settings.sculpt.unified_paint_settings": paint.unified_paint_settings,
        "Scene.tool_settings.sculpt.mesh_automasking_settings": paint.mesh_automasking_settings,
        "Scene": bpy.context.scene, "Brush.texture_slot": brush.texture_slot,
        "Mesh": bpy.context.object.data,
    }
    for kind in ('BLEND', 'CLOUDS', 'DISTORTED_NOISE', 'IMAGE', 'MAGIC', 'MARBLE',
                 'MUSGRAVE', 'NOISE', 'STUCCI', 'VORONOI', 'WOOD'):
        owners["Texture." + kind] = bpy.data.textures.new("Inventory" + kind, type=kind)
    fields = {name: metadata(owner) for name, owner in owners.items()}
    accesses = {}
    sources = list((ROOT / "sculptcore_addon").glob("*.py"))
    native_ui = ROOT.parent / "main/scripts/startup/bl_ui"
    sources += [native_ui / (name + ".py") for name in
                ("properties_paint_common", "space_view3d_toolbar", "space_view3d")]
    for source in sorted(sources):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = node.attr if isinstance(node, ast.Attribute) else (
                node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None)
            if name:
                accesses.setdefault(name, set()).add("{}:{}".format(source.name, node.lineno))
    rows = []
    for owner_name, props in fields.items():
        for name, meta in props.items():
            if name not in accesses and owner_name not in {"Brush", "Brush.sculptcore"} and not owner_name.startswith("Texture."):
                continue
            classification = "generic_brush"
            disposition = "native adapter; retain native storage"
            if owner_name.startswith("Scene") and "mesh_automasking" not in owner_name and "unified" not in owner_name:
                classification, disposition = "scene_only", "retain existing scene RNA"
            if owner_name == "Mesh":
                classification, disposition = "scene_only", "retain object/mesh state; not brush-owned"
            if (meta["readonly"] and meta["type"] not in {'POINTER', 'COLLECTION'}) or name in {"stroke_pivot", "brush", "sculptcore_layers"}:
                classification, disposition = "transient_state", "exclude from generic saved records"
            if meta["type"] in {'POINTER', 'COLLECTION'}:
                disposition = "retain native owned container/reference; children follow their own adapters"
            if owner_name.startswith("Texture."):
                disposition = "retain Texture ID settings and specialized native UI; native bake/script adapter"
            if owner_name == "Brush.sculptcore":
                disposition = "frozen legacy fan-out to kernel IDs; preserve raw group"
            rows.append({"path": owner_name + "." + name, "owner": owner_name,
                         "classification": classification, "migration": disposition,
                         "metadata": meta, "references": sorted(accesses.get(name, ()))})
    operators = []
    for source in sorted((ROOT / "sculptcore_addon").glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not any(ast.unparse(base).endswith("Operator") for base in cls.bases):
                continue
            for node in cls.body:
                if isinstance(node, ast.AnnAssign):
                    operators.append({"path": cls.name + "." + ast.unparse(node.target),
                                      "owner": "operator instance", "classification": "operator_argument",
                                      "migration": "retain operator argument; no generic storage",
                                      "declaration": ast.unparse(node.annotation),
                                      "reference": "{}:{}".format(source.name, node.lineno)})
    return {"rows": rows, "operator_arguments": operators, "rna_snapshot": fields}


def run_stroke(brush, pressure, *, use_fixture=False):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=32, y_subdivisions=32, size=2)
    ob = bpy.context.object
    if use_fixture:
        for vert in ob.data.vertices:
            vert.co.z = -0.15 * (vert.co.x ** 2 + vert.co.y ** 2)
        ob.data.update()
    before = np.array([tuple(v.co) for v in ob.data.vertices], dtype=np.float32)
    session = convert.enter(ob)
    sc = stroke._ensure_brush(session)
    kernel = mapping.kernel_enum(engine.manager(), brush)
    paint = bpy.context.tool_settings.sculpt if use_fixture else None
    unified = paint.unified_paint_settings if paint else None
    mapping.apply_brush_settings(brush, unified, sc, paint=paint)
    mapping.apply_pressure_dynamics(brush, sc, use_strength=pressure, use_size=False)
    stroke.stroke_begin(session, anchored_grab=False)
    for x in (-0.2, 0.0, 0.2):
        if brush.sculpt_brush_type == 'NUDGE':
            sc.strokeDirHostSet = True
            sc.strokeDir.vec[0], sc.strokeDir.vec[1], sc.strokeDir.vec[2] = 0.7071068, 0.0, -0.7071068
        mapping.apply_dab_state(brush, unified, sc, world_radius=0.35, invert=False)
        sc.clearDeviceInputs()
        sc.pushDeviceInput(0, 0.5)
        stroke.apply_dab(session, kernel, (x, 0.0, 0.0), (0.0, 0.0, 1.0), 0.35)
    stroke.stroke_end(session)
    positions = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    convert.exit_(ob)
    bpy.data.objects.remove(ob, do_unlink=True)
    assert float(np.abs(positions - before).max()) > 0.0001
    return positions


def main():
    phase, out_arg = sys.argv[sys.argv.index("--") + 1:]
    out = Path(out_arg).resolve()
    out.mkdir(parents=True, exist_ok=True)
    oracle = out / "baseline.json"
    if phase == "capture" and oracle.exists():
        raise RuntimeError("Refusing to replace the frozen baseline")
    assert phase in {"capture", "verify", "inventory", "geometry-capture", "geometry-verify"}
    if phase.startswith("geometry-"):
        geometry_oracle = out / "fixture-geometry.json"
        capturing = phase == "geometry-capture"
        assert not capturing or not geometry_oracle.exists(), "Refusing to replace geometry oracle"
        bpy.ops.wm.open_mainfile(filepath=str(out / "legacy.blend"))
        if handlers._on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)
        brush = bpy.data.brushes["GenericLegacyV0"]
        check_settings(brush)
        expected = {} if capturing else json.loads(geometry_oracle.read_text(encoding="utf-8"))
        for brush_type in ('DRAW', 'CLAY', 'PLANE', 'NUDGE'):
            brush.sculpt_brush_type = brush_type
            for pressure in (False, True):
                key = "fixture_{}_{}".format(brush_type.lower(), "pressure" if pressure else "plain")
                positions = run_stroke(brush, pressure, use_fixture=True)
                if capturing:
                    assert np.array_equal(positions, run_stroke(brush, pressure, use_fixture=True))
                    np.save(out / (key + ".npy"), positions)
                    expected[key] = {"sha256": hashlib.sha256(positions.tobytes()).hexdigest(),
                                     "kernel": mapping.KERNEL_BY_TYPE[brush_type],
                                     "path": "mesh Python apply_dab", "pressure": 0.5 if pressure else None,
                                     "effective_strength": 0.75, "planeSide": brush.sculptcore.planeSide,
                                     "cavity": EXPECTED["local_cavity"]}
                else:
                    assert np.array_equal(positions, np.load(out / (key + ".npy"))), key
        if capturing:
            write_json(geometry_oracle, expected)
        print("GENERIC_BRUSH_FIXTURE_GEOMETRY_PASS " + phase, flush=True)
        return
    if phase == "inventory":
        brush = bpy.data.brushes.new("Inventory", mode='SCULPT')
        write_json(out / "inventory.json", source_inventory(brush))
        write_json(out / "registered-rna.json", metadata(brush.sculptcore))
        dll = Path(engine.capi().lib._name).resolve()
        write_json(out / "runtime.json", {
            "blender": bpy.app.binary_path, "dll": str(dll),
            "dll_sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
            "modules": {m.__name__: {"path": m.__file__,
                        "sha256": hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
                        for m in (mapping, engine_props, stroke)},
        })
        print("GENERIC_BRUSH_INVENTORY_PASS", flush=True)
        return
    if handlers._on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)
    if phase == "capture":
        brush = make_fixture()
        check_settings(brush)
        frozen = {
            "version": 0, "blender": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode(), "expected": EXPECTED,
            "generated": authored(brush.sculptcore),
            "manifests": engine_props._walk_manifests(),
            "generated_rna": metadata(brush.sculptcore),
            "source_sha256": {name: hashlib.sha256((ROOT / "sculptcore_addon" / name).read_bytes()).hexdigest()
                              for name in ("mapping.py", "engine_props.py", "props.py", "stroke.py")},
        }
        write_json(out / "inventory.json", source_inventory(brush))
        bpy.ops.wm.save_as_mainfile(filepath=str(out / "legacy.blend"))
        bpy.ops.object.mode_set(mode='SCULPT')
        library = out / "library"
        library.mkdir(exist_ok=True)
        bpy.context.preferences.filepaths.asset_libraries.new(name="GenericBaseline", directory=str(library))
        brush.asset_mark()
        assert bpy.ops.brush.asset_activate(asset_library_type='LOCAL',
                                           relative_asset_identifier="Brush/GenericLegacyV0") == {'FINISHED'}
        assert bpy.ops.brush.asset_save_as(name="GenericLegacyV0", asset_library_reference="GenericBaseline",
                                          catalog_path="") == {'FINISHED'}
        bpy.ops.object.mode_set(mode='OBJECT')
    else:
        frozen = json.loads(oracle.read_text(encoding="utf-8"))
        bpy.ops.wm.open_mainfile(filepath=str(out / "legacy.blend"))
        brush = bpy.data.brushes["GenericLegacyV0"]
        check_settings(brush)
        assert authored(brush.sculptcore) == frozen["generated"]
        library_file = out / "library/Saved/Brushes/GenericLegacyV0.asset.blend"
        with bpy.data.libraries.load(str(library_file), link=False) as (_, target):
            target.brushes = ["GenericLegacyV0"]
        external = target.brushes[0]
        assert authored(external.sculptcore) == frozen["generated"]
        check_settings(external)
    dab_brush = bpy.data.brushes.new("DeterministicBaseline", mode='SCULPT')
    dab_brush.strength = 0.5
    for pressure in (False, True):
        key = "pressure" if pressure else "plain"
        result = run_stroke(dab_brush, pressure)
        if phase == "capture":
            repeat = run_stroke(dab_brush, pressure)
            assert np.array_equal(result, repeat), "baseline must be deterministic"
            np.save(out / (key + ".npy"), result)
            frozen[key] = {"sha256": hashlib.sha256(result.tobytes()).hexdigest(),
                           "max_z": float(result[:, 2].max()), "shape": list(result.shape)}
        else:
            assert np.array_equal(result, np.load(out / (key + ".npy"))), key
    if phase == "capture":
        write_json(oracle, frozen)
    print("GENERIC_BRUSH_BASELINE_PASS " + phase, flush=True)


main()
