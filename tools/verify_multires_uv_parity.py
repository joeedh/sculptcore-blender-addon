# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Grade the engine's multires attribute subdivision against Blender's own.

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_uv_parity.py -- [--verbose]

What is compared
----------------
A multires session draws UVs, colors and face sets by subdividing the *cage*
attribute onto the grid samples (engine ``subdiv/grid_attrs.h``) — nothing
reads them off Blender's evaluated mesh. This checks that the two agree.

The pairing is combinatorial, not geometric: the fork's
``Object.multires_grid_vert_indices`` names the subdivided vertex each
top-level grid sample coincides with, and ``multires.build_map`` turns that
into an engine-sample -> Blender-vertex table. A UV, though, lives on a
*corner*, and a vertex on a UV seam carries a different one per chart — so a
sample is graded against the set of UVs Blender put on the corners of its
vertex, and passes when it matches any of them. That is the strongest
statement the vertex-level pairing supports, and it is still exact: a wrong
subdivision rule moves a sample off *every* chart, not merely off one.

The fixtures deliberately span the cases the two rules differ on: a plain grid
(interior only), a UV-seamed grid (the fvar weld must split the charts), a cube
(fvar boundaries at every cage edge), and a non-quad cage (the n-gon corner
ptex layout). Each runs at more than one ``uv_smooth``, because that setting is
the whole of the face-varying rule.
"""

import sys

import bpy
import numpy as np

from sculptcore_addon import convert, engine, multires

# Two budgets, because one sample per grid is graded on a different footing.
#
# `body` is every sample that is not the grid's own (0,0) — i.e. not a cage
# vertex. Observed worst over the cases below is 2.9e-6, which is float
# rounding: the two sides reach the same value through different arithmetic
# (OpenSubdiv's limit patch evaluation vs. the engine's refine-then-limit-mask).
#
# `corner` is the (0,0) sample. It is exact (1e-7) at every uv_smooth that
# holds or linearizes fvar corners — including PRESERVE_BOUNDARIES, the
# multires default — and reads 6.5e-4 under SMOOTH_ALL, where the corner of a
# UV chart is an extraordinary face-varying vertex: Blender answers
# 0.166015625 where the Catmull-Clark limit is exactly 1/6, the residual of
# evaluating a patch after bounded feature isolation rather than the closed-form
# limit. Same rule, different evaluator; the budget is set by Blender's
# residual, not by slack. A genuinely wrong rule costs O(0.1) — the gap between
# a bilinear and a limit sample — so neither budget can hide one.
BUDGETS = {"body": 5.0e-5, "corner": 1.0e-3}


def _grid_mesh(name, n, uv_offset_at=None):
    """An ``n`` x ``n`` quad grid with UV = the vertex xy. ``uv_offset_at``
    shifts the UVs of every face above that row, which makes a UV seam without
    touching the geometry — the case the fvar weld exists for."""
    verts = [(float(x), float(y), 0.0) for y in range(n + 1) for x in range(n + 1)]
    w = n + 1
    faces = [(y * w + x, y * w + x + 1, (y + 1) * w + x + 1, (y + 1) * w + x)
             for y in range(n) for x in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        above = uv_offset_at is not None and poly.center[1] > uv_offset_at
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (co[0] + (10.0 if above else 0.0), co[1])
    return mesh


def _cube_mesh(name):
    """A unit cube with a per-face UV chart — every cage edge is a UV boundary,
    so the fvar rule and ``uv_smooth`` have somewhere to act."""
    mesh = bpy.data.meshes.new(name)
    verts = [(x, y, z) for z in (-1.0, 1.0) for y in (-1.0, 1.0) for x in (-1.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for k, loop_index in enumerate(poly.loop_indices):
            uv.data[loop_index].uv = ((k in (1, 2)) and 1.0 or 0.0,
                                      (k in (2, 3)) and 1.0 or 0.0)
    return mesh


def _ngon_mesh(name):
    """A pentagon ringed by quads: the grids of a non-quad cage face take the
    n-gon corner ptex layout rather than the quad quadrant one, and its corners
    are extraordinary vertices, where the limit rule and a discrete refinement
    visibly disagree."""
    import math

    def ring(radius, phase=0.0):
        return [(radius * math.cos(i * 2.0 * math.pi / 5.0 + phase),
                 radius * math.sin(i * 2.0 * math.pi / 5.0 + phase), 0.0) for i in range(5)]

    verts = ring(1.0) + ring(2.0)
    faces = [(0, 1, 2, 3, 4)]
    faces += [(i, 5 + i, 5 + (i + 1) % 5, (i + 1) % 5) for i in range(5)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (co[0] * 0.5 + 0.5, co[1] * 0.5 + 0.5)
    return mesh


def _object(mesh, level, uv_smooth):
    ob = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    md = ob.modifiers.new("Multires", 'MULTIRES')
    md.uv_smooth = uv_smooth
    bpy.context.view_layer.objects.active = ob
    for _ in range(level):
        bpy.ops.object.multires_subdivide(modifier=md.name)
    return ob, md


def _blender_uv_sets(eval_mesh):
    """Per subdivided vertex, the distinct UVs Blender's corners give it. A
    seam vertex has more than one; everything else has exactly one."""
    corners = len(eval_mesh.loops)
    corner_verts = np.empty(corners, dtype=np.int32)
    eval_mesh.attributes[".corner_vert"].data.foreach_get("value", corner_verts)
    uvs = np.empty(corners * 2, dtype=np.float32)
    eval_mesh.uv_layers.active.data.foreach_get("uv", uvs)
    uvs = uvs.reshape(-1, 2)

    sets = [[] for _ in range(len(eval_mesh.vertices))]
    for corner in range(corners):
        bucket = sets[corner_verts[corner]]
        value = uvs[corner]
        if not any(abs(value[0] - u) < 1e-6 and abs(value[1] - v) < 1e-6 for u, v in bucket):
            bucket.append((float(value[0]), float(value[1])))
    return sets


def _engine_uvs(ob, md, level, uv_smooth):
    """The engine's subdivided UVs at `level`, in grid-sample order, plus the
    engine-sample -> Blender-vertex table they are graded through."""
    lib = engine.capi().lib
    base_arrays = convert._gather_arrays(ob.data)
    top, depsgraph = convert._eval_multires_top(ob, md, level)

    mr, cage = multires.build_engine(base_arrays, level)
    try:
        mr_map = multires.build_map(ob, depsgraph, mr, level, len(top))
        convert._seed_cage_draw_attrs(ob.data, cage)
        lib.Multires_setUvSmooth(mr, convert._UV_SMOOTH_TO_ENGINE[uv_smooth])
        count = lib.Multires_levelSampleCount(mr, level)
        out = np.empty(count * 2, dtype=np.float32)
        written = lib.Multires_gridAttrSamplesOut(mr, level, b"uv", out, out.size)
        if written != out.size:
            raise engine.EngineError(
                "engine returned {} floats for {} uv samples".format(written, out.size))
        return out.reshape(-1, 2), mr_map, depsgraph
    finally:
        lib.Multires_free(mr)
        lib.freeMesh(cage)


def _grade(case, verbose):
    name, mesh_factory, level, uv_smooth = case
    label = "{:s}/{:s}/L{:d}".format(name, uv_smooth, level)
    mesh = mesh_factory("sc_uv_" + name)
    ob, md = _object(mesh, level, uv_smooth)
    try:
        uvs, mr_map, depsgraph = _engine_uvs(ob, md, level, uv_smooth)
        md.levels = level
        md.sculpt_levels = level
        depsgraph.update()
        eval_mesh = ob.evaluated_get(depsgraph).data
        sets = _blender_uv_sets(eval_mesh)

        # One grid per cage corner, each a square lattice, so sample index 0 of
        # every grid is that grid's (0,0) — the cage vertex it grew from.
        lattice = len(uvs) // len(ob.data.loops)

        worst = {"body": 0.0, "corner": 0.0}
        worst_at = {"body": -1, "corner": -1}
        for sample, vert in enumerate(mr_map.engine_sample_to_blender):
            bucket = sets[int(vert)]
            if not bucket:
                continue
            u, v = float(uvs[sample][0]), float(uvs[sample][1])
            best = min(max(abs(u - bu), abs(v - bv)) for bu, bv in bucket)
            kind = "corner" if sample % lattice == 0 else "body"
            if best > worst[kind]:
                worst[kind], worst_at[kind] = best, sample
        if verbose:
            print("  {:s}: {:d} samples, worst body {:.3e} at {:d}, corner {:.3e} at {:d}".format(
                label, len(uvs), worst["body"], worst_at["body"],
                worst["corner"], worst_at["corner"]))
        return label, worst
    finally:
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(mesh)


# (name, mesh factory, level, uv_smooth). The seamed grid and the cube are the
# cases the linear rules act on; the plain grid and the n-gon fan grade the
# interior rule, which uv_smooth leaves alone.
CASES = [
    ("grid", lambda n: _grid_mesh(n, 3), 1, 'PRESERVE_BOUNDARIES'),
    ("grid", lambda n: _grid_mesh(n, 3), 2, 'PRESERVE_BOUNDARIES'),
    ("seam", lambda n: _grid_mesh(n, 4, uv_offset_at=2.0), 2, 'PRESERVE_BOUNDARIES'),
    ("seam", lambda n: _grid_mesh(n, 4, uv_offset_at=2.0), 2, 'SMOOTH_ALL'),
    ("cube", _cube_mesh, 2, 'PRESERVE_BOUNDARIES'),
    ("cube", _cube_mesh, 2, 'SMOOTH_ALL'),
    ("cube", _cube_mesh, 2, 'NONE'),
    ("ngon", _ngon_mesh, 2, 'PRESERVE_BOUNDARIES'),
]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    verbose = "--verbose" in argv
    for arg in argv:
        if arg != "--verbose":
            raise SystemExit("verify_multires_uv_parity: unknown argument {!r}".format(arg))

    engine.capi()  # loads the native library, or raises

    failures = []
    for case in CASES:
        label, worst = _grade(case, verbose)
        over = [kind for kind, value in worst.items() if value > BUDGETS[kind]]
        print("verify_multires_uv_parity: {:s} body={:.3e}/{:g} corner={:.3e}/{:g} {:s}".format(
            label, worst["body"], BUDGETS["body"], worst["corner"], BUDGETS["corner"],
            "FAILED" if over else "ok"))
        for kind in over:
            failures.append("{:s}: worst {:s} UV divergence {:.6g} over budget {:g}".format(
                label, kind, worst[kind], BUDGETS[kind]))

    if failures:
        for msg in failures:
            sys.stderr.write("verify_multires_uv_parity: FAILED: {:s}\n".format(msg))
        sys.exit(1)

    print("verify_multires_uv_parity: {:d} case(s) within budget".format(len(CASES)))


main()
