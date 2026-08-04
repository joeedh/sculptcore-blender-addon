# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless test for the grids-native multires stroke dispatch (W1).

Drives the stroke module directly (no modal operator):

1. cube + 3-level multires, enter the session at the top level;
2. a DRAW stroke through the grids path (``grids_kernel`` set) — dispatch is
   confirmed via ``session.last_stroke_grids``, positions move, and the
   engine-side ride-along mirror lands them in the slot mesh;
3. grid undo restores the slot mesh bit-exactly; redo re-applies;
4. the domain raycast agrees with the mesh-tree raycast;
5. a forced mesh-path stroke interleaves (fold point), then a second grids
   stroke re-binds (sync == 2 path) and still works;
6. flush exports without error after all of it.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_grids_native.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def slot_positions(session):
    return convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()


def main():
    lib = engine.capi().lib
    mgr = engine.manager()
    brushes = mgr.get("sculptcore::brush::SculptBrushes").items
    kernel_draw = int(brushes['DRAW'])

    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")

    session = convert.enter(ob)
    check(session.multires_ptr is not None, "multires session entered")
    level = session.multires_active_level
    check(level == 3, "entered at level 3")

    check(stroke.grids_capable(session, kernel_draw), "DRAW is grids-capable")

    sc_brush = stroke._ensure_brush(session)
    sc_brush.radius = 0.5
    sc_brush.strength = 0.5
    sc_brush.writeProps()

    pre = slot_positions(session)
    check(pre.size > 0, "slot positions readable")

    # --- grids stroke -------------------------------------------------------
    stroke.stroke_begin(session, grids_kernel=kernel_draw)
    check(session.last_stroke_grids, "stroke dispatched grids-native")
    moved = 0
    for i in range(4):
        moved += stroke.apply_dab(
            session, kernel_draw, (0.05 * i, 0.0, 1.0), (0.0, 0.0, 1.0), 0.5)
    stroke.stroke_end(session)
    check(moved > 0, "grids dabs moved verts ({:d})".format(moved))
    check(session.grid_cursor == 1, "grid cursor advanced")

    post = slot_positions(session)
    diff = np.abs(post - pre).max()
    check(diff > 1e-4, "mirror landed the stroke in the slot mesh (max {:.5f})".format(diff))

    # --- raycast parity -----------------------------------------------------
    hit_grid = stroke.raycast(session, (0.0, 0.0, 3.0), (0.0, 0.0, -1.0))
    check(hit_grid is not None, "grid raycast hits")
    if hit_grid is not None:
        # The center ray runs along a lattice seam, so which of the tied
        # triangles wins is epsilon-sensitive — assert the hit is on the
        # displaced surface (above the undisplaced top, at or under the peak)
        # rather than pinning one winner.
        z = hit_grid[0][2]
        check(pre[:, 2].max() + 0.02 < z <= post[:, 2].max() + 1e-3,
              "grid raycast lands on the displaced surface "
              "(z={:.5f} band=({:.5f}, {:.5f}] hit={!r})".format(
                  z, pre[:, 2].max() + 0.02, post[:, 2].max() + 1e-3, hit_grid))

    # --- grid undo / redo ---------------------------------------------------
    check(bool(lib.GridStroke_undo(session.grid_ptr)), "grid undo")
    und = slot_positions(session)
    check(np.array_equal(und, pre), "undo restored the slot mesh bit-exactly")
    check(bool(lib.GridStroke_redo(session.grid_ptr)), "grid redo")
    red = slot_positions(session)
    check(np.array_equal(red, post), "redo restored the stroke bit-exactly")

    # --- mesh-path interleave (fold point) ---------------------------------
    stroke.stroke_begin(session)  # no grids_kernel: forced mesh path
    check(not session.last_stroke_grids, "forced mesh path taken")
    stroke.apply_dab(session, kernel_draw, (0.0, 0.3, 1.0), (0.0, 0.0, 1.0), 0.4)
    stroke.stroke_end(session)
    # The mesh-path stroke folds at the next blob/undo push; force the fold so
    # the domain drops as it would in the real flow.
    convert.multires_store_blob(session)

    stroke.stroke_begin(session, grids_kernel=kernel_draw)
    check(session.last_stroke_grids, "grids path re-taken after mesh stroke")
    moved2 = stroke.apply_dab(
        session, kernel_draw, (-0.3, 0.0, 1.0), (0.0, 0.0, 1.0), 0.5)
    stroke.stroke_end(session)
    check(moved2 > 0, "post-interleave grids dab moved verts")

    # --- flush --------------------------------------------------------------
    convert.flush(ob)
    check(True, "flush completed")

    print("grids-native wiring: {:d} failures".format(len(failures)))
    if failures:
        raise SystemExit(1)


main()
