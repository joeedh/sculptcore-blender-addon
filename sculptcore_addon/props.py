# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Scene-level SculptCore settings (save with the file). Minimal for now: the
dynamic-topology toggle and its target edge length. Engine-only brush
uniforms grow into a generated Brush.sculptcore group later (brush-mapping
M2).

Plus the two shadow pen-pressure toggles below, which are per-brush rather
than per-scene.
"""

import bpy

# Pen-pressure toggles this mode owns, for the brushes where Blender's own
# `Brush.use_pressure_strength` / `use_pressure_size` are inert: vanilla gates
# them on `sculpt_capabilities.has_*_pressure`, which is False for its whole
# is_grab_tool set (snake hook, pose, thumb, rotate...), so the stored value on
# those brushes never drove anything and the shipped assets carry it arbitrarily
# — Snake Hook, for one, ships with strength pressure on. Our kernels do scale
# by strength there, so the toggle has to mean something; reading a property we
# own gives it a default we control (off, matching vanilla's effective
# behavior) without writing to the user's brush. mapping.pressure_prop_names
# picks between these and vanilla's for each brush; nothing else should read
# them directly.
_PRESSURE_PROPS = {
    "sculptcore_use_pressure_strength": (
        "Strength Pressure",
        "Scale the brush strength by pen pressure",
    ),
    "sculptcore_use_pressure_size": (
        "Size Pressure",
        "Scale the brush size by pen pressure",
    ),
}


def register():
    for name, (label, description) in _PRESSURE_PROPS.items():
        setattr(bpy.types.Brush, name, bpy.props.BoolProperty(
            name=label,
            description=description,
            default=False,
        ))
    bpy.types.Scene.sculptcore_dyntopo = bpy.props.BoolProperty(
        name="Dynamic Topology",
        description="Dynamically remesh under the brush while sculpting. "
                    "Unavailable while sculpting a multires level, whose "
                    "topology comes from the subdivision grids",
        default=False,
    )
    # Detail size/mode come from Blender's own dyntopo settings
    # (tool_settings.sculpt.detail_*, see stroke.dyntopo_max_edge); only the
    # enable flag and the engine's remesh cadence are addon state.
    bpy.types.Scene.sculptcore_dyntopo_spacing = bpy.props.FloatProperty(
        name="Detail Spacing",
        description="Stroke travel between remesh passes, in brush diameters "
                    "(0 remeshes on every dab). Higher values remesh less often "
                    "for cheaper strokes",
        default=0.5,
        min=0.0,
        soft_max=2.0,
    )
    # Engine remesher tuning (DynTopoParams; defaults mirror the engine's).
    bpy.types.Scene.sculptcore_dyntopo_flips = bpy.props.BoolProperty(
        name="Edge Flips",
        description="Flip interior edges to the shorter diagonal each round, "
                    "keeping triangles well-shaped and refinement convergent "
                    "(disable for the pre-flip baseline behavior)",
        default=True,
    )
    bpy.types.Scene.sculptcore_dyntopo_smooth = bpy.props.BoolProperty(
        name="Tangential Smooth",
        description="Slide remeshed vertices toward their neighborhood "
                    "centroid in the tangent plane, equalizing triangle sizes "
                    "without shrinking the surface or eroding sculpted detail",
        default=False,
    )
    bpy.types.Scene.sculptcore_dyntopo_smooth_lambda = bpy.props.FloatProperty(
        name="Smooth Factor",
        description="Relaxation step for the tangential smoothing",
        default=0.5,
        min=0.0,
        max=1.0,
    )
    bpy.types.Scene.sculptcore_dyntopo_max_rounds = bpy.props.IntProperty(
        name="Max Rounds",
        description="Refinement rounds per remesh pass before giving up "
                    "(later dabs finish any remaining work)",
        default=50,
        min=1,
        soft_max=100,
    )
    bpy.types.Scene.sculptcore_dyntopo_split_budget = bpy.props.IntProperty(
        name="Split Budget",
        description="Maximum edge splits per remesh pass, bounding the cost "
                    "of a first touch on coarse geometry (0 = unlimited; "
                    "later dabs finish the refinement)",
        default=0,
        min=0,
        soft_max=100000,
    )
    bpy.types.Scene.sculptcore_dyntopo_collapse_budget = bpy.props.IntProperty(
        name="Collapse Budget",
        description="Maximum edge collapses per remesh pass, bounding the "
                    "cost of decimating dense geometry (0 = unlimited)",
        default=0,
        min=0,
        soft_max=100000,
    )
    bpy.types.Scene.sculptcore_reproject_uvs = bpy.props.BoolProperty(
        name="Reproject UVs",
        description="Re-anchor UVs when smoothing slides vertices along the "
                    "surface (smooth brushes, autosmooth and the dyntopo "
                    "tangential smooth), so textures do not swim",
        default=True,
    )
    bpy.types.Scene.sculptcore_uv_margin = bpy.props.FloatProperty(
        name="Chart Margin",
        description="Padding added around each UV chart before packing "
                    "(Project UVs from Seams)",
        default=0.01,
        min=0.0,
        max=0.25,
        subtype='FACTOR',
    )
    # Signed off 2026-08-10 (design/cpp-dab-loop.md §13) and default on; the
    # toggle stays as the rollback switch until the per-dab Python path is
    # retired.
    bpy.types.Scene.sculptcore_cpp_dab_loop = bpy.props.BoolProperty(
        name="C++ Dab Loop",
        description="Run the per-dab raycast/apply loop of plain spaced "
                    "strokes in the engine, batched per pointer event, "
                    "instead of per dab through Python",
        default=True,
    )


def unregister():
    for name in _PRESSURE_PROPS:
        delattr(bpy.types.Brush, name)
    del bpy.types.Scene.sculptcore_dyntopo
    del bpy.types.Scene.sculptcore_dyntopo_spacing
    del bpy.types.Scene.sculptcore_dyntopo_flips
    del bpy.types.Scene.sculptcore_dyntopo_smooth
    del bpy.types.Scene.sculptcore_dyntopo_smooth_lambda
    del bpy.types.Scene.sculptcore_dyntopo_max_rounds
    del bpy.types.Scene.sculptcore_dyntopo_split_budget
    del bpy.types.Scene.sculptcore_dyntopo_collapse_budget
    del bpy.types.Scene.sculptcore_reproject_uvs
    del bpy.types.Scene.sculptcore_uv_margin
    del bpy.types.Scene.sculptcore_cpp_dab_loop
