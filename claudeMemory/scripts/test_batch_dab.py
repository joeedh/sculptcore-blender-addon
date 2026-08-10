# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless smoke test for the C++ dab-loop batch c-api (design/cpp-dab-loop.md
variant B): the four flat entry points the ``sculptcore_cpp_dab_loop`` scene
toggle routes through, driven directly (no modal operator).

1. mesh arm: dense grid object, ``MeshStroke_castBatch`` resolves rays with
   the expected hit mask, ``MeshStroke_dabBatch`` moves geometry, and a mirror
   sign vector moves the reflected region too;
2. mesh arm sentinel: a null tree/executor returns -1, not a crash;
3. grids arm: cube + 3-level multires, ``GridStroke_castBatch`` +
   ``GridStroke_dabBatch`` on the bound session displace the surface
   (checked via the domain raycast before/after).

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_batch_dab.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
NO_SIGNS = np.zeros(0, dtype=np.float32)


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def down_rays(coords, z=3.0):
    """n x 6 ray batch: origins above the given (x, y) points, aimed -z."""
    rays = np.zeros((len(coords), 6), dtype=np.float32)
    for i, (x, y) in enumerate(coords):
        rays[i, 0:3] = (x, y, z)
        rays[i, 5] = -1.0
    return rays


def cast(lib, fn, handle, rays):
    n = len(rays)
    hits = np.zeros((n, 6), dtype=np.float32)
    mask = np.zeros(n, dtype=np.uint8)
    count = fn(handle, n, rays, hits, mask)
    return count, hits, mask


def dabs_from(hits, mask, radius):
    rows = hits[mask.astype(bool)]
    dabs = np.empty((len(rows), 7), dtype=np.float32)
    dabs[:, 0:6] = rows
    dabs[:, 6] = radius
    return dabs


def main():
    lib = engine.capi().lib
    mgr = engine.manager()
    kernel_draw = int(mgr.get("sculptcore::brush::SculptBrushes").items['DRAW'])

    # --- mesh arm -----------------------------------------------------------
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=2)
    ob = bpy.context.object
    session = convert.enter(ob)
    check(session.multires_ptr is None, "mesh arm: plain session")
    sc_brush = stroke._ensure_brush(session)
    sc_brush.radius = 0.3
    sc_brush.strength = 0.5
    sc_brush.writeProps()
    executor = stroke._ensure_executor(session)
    tree_ptr = session.tree().ptr

    stroke.stroke_begin(session, anchored_grab=False)
    # 3 rays on the surface near x=+0.5, one deliberate miss outside the grid.
    rays = down_rays([(0.5, -0.1), (0.5, 0.0), (0.5, 0.1), (5.0, 5.0)])
    count, hits, mask = cast(lib, lib.MeshStroke_castBatch, tree_ptr, rays)
    check(count == 3, "castBatch resolved 3 of 4 rays (got {:d})".format(count))
    check(list(mask) == [1, 1, 1, 0], "hit mask marks the miss")
    check(abs(float(hits[0, 2])) < 1e-4, "hit landed on the grid plane")

    before = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    dabs = dabs_from(hits, mask, 0.3)
    signs = np.array([-1.0, 1.0, 1.0], dtype=np.float32)  # X mirror
    moved = lib.MeshStroke_dabBatch(
        executor.ptr, tree_ptr, session.mesh().ptr, sc_brush.ptr,
        kernel_draw, len(dabs), dabs, 0.5, 0, 1.0, 0, 1.0, signs, 1)
    stroke.stroke_end(session)
    check(moved > 0, "dabBatch touched nodes (got {:d})".format(moved))
    after = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3)
    delta = np.abs(after - before).max(axis=1)
    primary = delta[(np.abs(before[:, 0] - 0.5) < 0.15)
                    & (np.abs(before[:, 1]) < 0.15)].max()
    mirrored = delta[(np.abs(before[:, 0] + 0.5) < 0.15)
                     & (np.abs(before[:, 1]) < 0.15)].max()
    untouched = delta[np.abs(before[:, 0]) < 0.05].max()
    check(primary > 1e-4, "primary region moved ({:.5f})".format(primary))
    check(mirrored > 1e-4, "mirror region moved ({:.5f})".format(mirrored))
    check(untouched < primary * 0.5,
          "mid-plane stayed put ({:.5f} vs {:.5f})".format(untouched, primary))

    # Sentinel: null handles must report -1, never crash.
    check(lib.MeshStroke_castBatch(None, 1, rays[:1], np.zeros((1, 6), np.float32),
                                   np.zeros(1, np.uint8)) == -1,
          "castBatch null tree -> -1")
    check(lib.MeshStroke_dabBatch(None, tree_ptr, session.mesh().ptr, sc_brush.ptr,
                                  kernel_draw, 1, dabs[:1], 0.5, 0, 1.0, 0, 1.0,
                                  NO_SIGNS, 0) == -1,
          "dabBatch null executor -> -1")
    convert.exit_(ob)

    # --- grids arm ----------------------------------------------------------
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")
    session = convert.enter(ob)
    check(session.multires_ptr is not None, "grids arm: multires session")
    sc_brush = stroke._ensure_brush(session)
    sc_brush.radius = 0.4
    sc_brush.strength = 0.5
    sc_brush.writeProps()

    stroke.stroke_begin(session, grids_kernel=kernel_draw)
    check(session.last_stroke_grids, "grids stroke dispatched")

    probe = stroke.raycast(session, (0.0, -0.3, 3.0), (0.0, 0.0, -1.0))
    check(probe is not None, "probe ray hits before the batch")
    z_before = probe[0][2]

    rays = down_rays([(0.0, -0.3), (0.0, 0.0), (0.0, 0.3)])
    count, hits, mask = cast(lib, lib.GridStroke_castBatch, session.grid_ptr, rays)
    check(count == 3, "grids castBatch resolved 3 rays (got {:d})".format(count))
    moved = lib.GridStroke_dabBatch(
        session.grid_ptr, kernel_draw, count, dabs_from(hits, mask, 0.4),
        0.5, 0, 1.0, 0, NO_SIGNS, 0)
    check(moved > 0, "grids dabBatch moved verts (got {:d})".format(moved))
    stroke.stroke_end(session)

    probe = stroke.raycast(session, (0.0, -0.3, 3.0), (0.0, 0.0, -1.0))
    check(probe is not None, "probe ray hits after the batch")
    check(abs(probe[0][2] - z_before) > 1e-4,
          "surface displaced ({:.5f} -> {:.5f})".format(z_before, probe[0][2]))
    convert.exit_(ob)

    if failures:
        raise SystemExit("test_batch_dab: {:d} failure(s)".format(len(failures)))
    print("test_batch_dab: all checks passed")


main()
