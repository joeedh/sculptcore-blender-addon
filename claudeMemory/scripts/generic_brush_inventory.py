# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Annotate the frozen RNA/source inventory with reviewed migration dispositions."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "claudeMemory/tests/generic-brush-v0"
DESTINATION = ROOT / "claudeMemory/design/generic-brush-inventory-v1.json"
COMMON = {
    "sculpt_brush_type": ("kernel", "selector", "mapped types; POSE unavailable"),
    "direction": ("direction", "ADD/SUBTRACT; XOR Ctrl", "all except smooth"),
    "stroke_method": ("stroke_method", "native enum", "ANCHORED/DRAG_DOT previews; AIRBRUSH/LINE/CURVE currently spacer"),
    "size": ("size_pixels", "pixel diameter; /2 to radius", "all"),
    "unprojected_size": ("size_world", "world diameter; /2 to radius", "all; corrected SCENE sizing"),
    "use_locked_size": ("size_mode", "VIEW/SCENE", "all; coupled size block"),
    "strength": ("strength", "dimensionless", "all; THUMB scales drag; SHARP x2; PINCH pinch reads dormant local"),
    "spacing": ("spacing", "percent diameter; max(value,1)/100", "spaced strokes"),
    "plane_offset": ("plane_offset", "native offset", "CLAY/CLAY_STRIPS/PLANE/MULTIPLANE_SCRAPE"),
    "crease_pinch_factor": ("snake_pinch", "2*(.5-native) snake hook; +-native^2 crease/blob",
                            "SNAKE_HOOK/CREASE/BLOB"),
    "hardness": ("hardness", "fraction radius", "falloff-capable kernels"),
    "auto_smooth_factor": ("autosmooth", "dimensionless multi-pass strength", "non-SMOOTH with auto smooth"),
    "use_accumulate": ("accumulate", "boolean; forced for DRAW_SHARP", "kernel/capability dependent"),
    "use_space_attenuation": ("spacing_attenuation", "overlap normalization", "spaced non-grab/non-snake"),
    "sculpt_plane": ("sculpt_plane", "native enum", "CLAY/CLAY_STRIPS/PLANE"),
    "use_original_normal": ("original_normal", "boolean", "CLAY/CLAY_STRIPS"),
    "use_original_plane": ("original_plane", "boolean", "CLAY_STRIPS"),
    "normal_radius_factor": ("normal_radius_factor", "fraction radius", "CLAY/CLAY_STRIPS/PLANE"),
    "area_radius_factor": ("area_radius_factor", "fraction radius", "PLANE"),
    "stabilize_normal": ("stabilize_normal", "dimensionless", "PLANE"),
    "stabilize_plane": ("stabilize_plane", "dimensionless", "PLANE"),
    "plane_height": ("plane_height", "fraction radius", "PLANE"),
    "plane_depth": ("plane_depth", "fraction radius", "PLANE"),
    "plane_inversion_mode": ("plane_inversion_mode", "native enum", "PLANE"),
    "tip_roundness": ("tip_roundness", "fraction radius", "CLAY_STRIPS/PAINT"),
    "tip_scale_x": ("tip_scale_x", "fraction radius", "CLAY_STRIPS/PAINT"),
    "curve_distance_falloff_preset": ("falloff_preset", "generated enum", "falloff-capable kernels"),
    "curve_distance_falloff": ("falloff_custom", "native distance->factor", "falloff-capable kernels"),
    "falloff_shape": ("falloff_shape", "SPHERE; PROJECTED currently translated to SPHERE", "all; preserve limitation"),
    "color": ("color", "linear RGB; alpha=1", "PAINT/COLOR"),
    "cursor_color_add": ("cursor_color", "display RGB", "cursor only"),
    "texture": ("texture", "Texture ID reference", "texture-capable kernels"),
    "texture_slot": ("texture_mapping", "native specialized block", "texture-capable kernels"),
}
PRESSURE = {
    "use_pressure_strength": "strength", "sculptcore_use_pressure_strength": "strength",
    "use_pressure_size": "size", "sculptcore_use_pressure_size": "size",
    "curve_strength": "strength", "curve_size": "size",
}
CAVITY = {"use_automasking_cavity", "use_automasking_cavity_inverted",
          "use_automasking_custom_cavity_curve", "cavity_factor", "cavity_blur_steps", "cavity_curve"}


def main():
    inventory = json.loads((FIXTURES / "inventory.json").read_text(encoding="utf-8"))
    baseline = json.loads((FIXTURES / "baseline.json").read_text(encoding="utf-8"))
    rows = inventory["rows"]
    for row in rows:
        path, owner, meta = row["path"], row["owner"], row["metadata"]
        name = path.rsplit(".", 1)[1]
        row.update(stable_ids=[], pressure="none", unified="none", kernels="not a kernel uniform",
                   units=meta.get("unit", "NONE"), supported=False)
        if owner == "Brush":
            row["migration"] = "retain native data; omit unsupported SculptCore controls"
            if name in COMMON:
                semantic, units, kernels = COMMON[name]
                row.update(stable_ids=["sculptcore.brush." + semantic], units=units,
                           kernels=kernels, supported=True,
                           migration="native adapter; no second authoritative value")
            if name in {"strength", "size", "unprojected_size", "use_locked_size"}:
                row["unified"] = "legacy Scene.tool_settings.sculpt.unified_paint_settings.use_unified_" + (
                    "strength" if name == "strength" else "size")
            if name in {"strength", "size", "unprojected_size"}:
                row["pressure"] = "native/shadow enable selected by capability; native curve; no grab pressure"
            if name in PRESSURE:
                row.update(supported=True, pressure="unique pressure entry for " + PRESSURE[name],
                           stable_ids=["sculptcore.brush." + ("size" if PRESSURE[name] == "size" else "strength")],
                           migration="native stack adapter; local by default; generated presets preserve native curve",
                           kernels="non-grab; smooth uses host evaluation")
            if name.startswith("use_unified_"):
                row["migration"] = "preserve native per-brush flag; legacy scene-policy compatibility decision in contract"
        elif "mesh_automasking_settings" in owner:
            row.update(supported=name in CAVITY, unified="compound NATIVE_CAVITY precedence",
                       kernels="strength-consuming kernels; stroke-static")
            row["migration"] = ("native cavity block adapter; correct owner notifications" if name in CAVITY else
                                "retain unsupported native data; omit SculptCore UI")
            if name in CAVITY:
                row["stable_ids"] = ["sculptcore.brush.cavity." + name]
        elif owner == "Brush.sculptcore":
            row.update(supported=True, kernels=[], units="dimensionless", migration="frozen legacy fan-out")
            for kernel, entries in baseline["manifests"].items():
                if any(entry[0] == name for entry in entries):
                    row["kernels"].append(kernel)
                    row["stable_ids"].append("sculptcore.kernel.{}.{}".format(kernel.lower(), name))
            if name == "name":
                row.update(supported=False, classification="transient_state", migration="unused PropertyGroup label")
        elif "unified_paint_settings" in owner:
            row.update(supported=name in {"size", "unprojected_size", "strength", "use_locked_size",
                                         "use_unified_size", "use_unified_strength"},
                       migration="retain native Scene storage; effective-owner adapter for size/strength block")
            if name in COMMON:
                row["stable_ids"] = ["sculptcore.brush." + COMMON[name][0]]
            row["unified"] = "native scene flag selected by compatibility policy"
        elif owner.startswith("Texture.") or owner == "Brush.texture_slot":
            row.update(supported=True, kernels="texture-capable kernels", pressure="none",
                       migration="retain native Texture/slot; existing specialized bake/script adapter")
            if owner == "Brush.texture_slot" and name in {
                    "angle", "use_rake", "use_random", "random_angle", "mask_map_mode"}:
                row.update(supported=False, migration="retain native data; currently unmapped; omit generic control")
            if owner == "Brush.texture_slot" and name == "map_mode":
                row["migration"] = "retain native enum; AREA_PLANE/RANDOM/STENCIL use documented approximations in texture.py"
        if row["classification"] == "transient_state":
            row.update(supported=False, migration="retain runtime/native state; exclude from generic authoring")
    extra = [
        ("WindowManager.sculptcore_layers[*].weight", "WindowManager", "transient_state",
         "retain live engine layer mirror; never migrate to brush"),
        ("Object.modifiers[MULTIRES].sculpt_levels", "Object", "scene_only",
         "retain modifier state and existing level operators"),
        ("Texture.node_tree.nodes[*].RNA / sockets / ramps / mappings", "Texture/NodeTree", "generic_brush",
         "retain native graph; dynamic property walk in texture.py; no generic value duplication"),
        ("Texture.image pixels/colorspace/filepath", "Image", "generic_brush",
         "retain image resource and native bake fingerprint"),
        ("_MaskGesture.mode/value", "operator instance", "operator_argument",
         "retain mixin operator arguments inherited by gestures"),
        ("Brush.use_smooth_stroke", "Brush", "generic_brush",
         "native keymap toggle currently not consumed by StrokeSpacer; preserve value, omit until wired"),
        ("Brush.mask_texture_slot.* / mask_texture / stencil positions and dimensions", "Brush", "generic_brush",
         "retain native data/secondary stencil keymaps; secondary texture and placement currently unsupported"),
    ]
    exclusions = [{"path": path, "owner": owner, "classification": kind, "migration": disposition}
                  for path, owner, kind, disposition in extra]
    result = {"schema_version": 1, "baseline_version": 0, "rows": rows,
              "size_stack_id": "sculptcore.brush.size",
              "operator_arguments": inventory["operator_arguments"], "dynamic_paths_and_exclusions": exclusions}
    assert len({row["path"] for row in rows}) == len(rows)
    assert all(row["owner"] and row["migration"] and row["classification"] for row in rows)
    DESTINATION.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("GENERIC_BRUSH_INVENTORY_ANNOTATED {} rows, {} operator arguments".format(
        len(rows), len(inventory["operator_arguments"])))


if __name__ == "__main__":
    main()
