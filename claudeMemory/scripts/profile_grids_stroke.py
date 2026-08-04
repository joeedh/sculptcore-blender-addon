# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless per-phase timing of the grids-native stroke path at the bench
workload (63x63 grid base, 4 multires levels ~= 1M verts). Answers where the
per-stroke wall time goes after W1: dab python overhead vs stroke_end vs the
undo blob vs draw refresh.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/profile_grids_stroke.py
"""

import time

import bpy

from sculptcore_addon import convert, engine, handlers, mapping, stroke, undo

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)


def main():
    lib = engine.capi().lib
    mgr = engine.manager()
    kernel_draw = int(mgr.get("sculptcore::brush::SculptBrushes").items['DRAW'])

    bpy.ops.mesh.primitive_grid_add(x_subdivisions=63, y_subdivisions=63, size=2.0)
    ob = bpy.context.object
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(4):
        bpy.ops.object.multires_subdivide(modifier="Multires")

    t0 = time.perf_counter()
    session = convert.enter(ob)
    print("enter: {:.0f} ms".format((time.perf_counter() - t0) * 1000))
    level = session.multires_active_level
    print("level {} verts {}".format(level, convert.mesh_vert_num(session.mesh_ptr)))

    sc_brush = stroke._ensure_brush(session)
    sc_brush.radius = 0.06
    sc_brush.strength = 0.1
    sc_brush.writeProps()

    n_strokes = 5
    dabs = 42
    t_begin = t_state = t_ray = t_dab = t_end = t_blob = t_push_rest = 0.0
    for s in range(n_strokes):
        t = time.perf_counter()
        stroke.stroke_begin(session, grids_kernel=kernel_draw)
        t_begin += time.perf_counter() - t
        assert session.last_stroke_grids
        y = -0.5 + 0.2 * s
        for i in range(dabs):
            x = -0.8 + 1.6 * i / (dabs - 1)
            t = time.perf_counter()
            mapping.apply_dab_state(None, None, sc_brush, world_radius=0.06,
                                    invert=False, strength_override=0.1,
                                    allow_invert=False)
            t_state += time.perf_counter() - t
            t = time.perf_counter()
            stroke.raycast(session, (x, y, 3.0), (0.0, 0.0, -1.0))
            t_ray += time.perf_counter() - t
            t = time.perf_counter()
            stroke.apply_dab(session, kernel_draw, (x, y, 0.0), (0.0, 0.0, 1.0), 0.06)
            t_dab += time.perf_counter() - t
        t = time.perf_counter()
        stroke.stroke_end(session)
        t_end += time.perf_counter() - t
        t = time.perf_counter()
        blob = convert.multires_store_blob(session)
        session.multires_last_blob = blob
        t_blob += time.perf_counter() - t

    per = 1000.0 / n_strokes
    print("per-stroke ms: begin={:.1f} dab_state={:.1f} raycast={:.1f} "
          "dabs={:.1f} end={:.1f} blob={:.1f}".format(
              t_begin * per, t_state * per, t_ray * per, t_dab * per,
              t_end * per, t_blob * per))
    print("per-dab ms: state={:.3f} raycast={:.3f} dab={:.3f}".format(
        t_state * per / dabs, t_ray * per / dabs, t_dab * per / dabs))
    print("undo bytes: {:.1f} MB (blob {:.1f} MB)".format(
        lib.GridStroke_undoBytes(session.grid_ptr) / 1e6,
        (len(blob) if blob else 0) / 1e6))


main()
