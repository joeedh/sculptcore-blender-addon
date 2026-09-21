# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Attribute the plane-frame policy's per-dab cost in-process.

Same mesh, same dab sequence, the Clay autosmooth program on the mesh path
(what the Clay essentials brush runs), four policies interleaved so a cache
or clock drift cannot alias onto one of them:

- ``off``    the executor default (raycast frame)
- ``area``   AREA normal about the cursor, accumulate on (gather per dab)
- ``area-na`` the same, non-accumulate (stroke-start data)
- ``hold``   Original Normal held: the frame resolves once, then only the hook runs

The numbers drift ~2x across rounds on this box (order and warmup effects), so
this attributes cost between the configurations and is not a gate; the
interleaved headed A/B in ``run_stroke_bench.mjs`` is the authority.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \\
        --python claudeMemory/scripts/profile_plane_frame.py -- [--grid 1000] [--rounds 4]
"""

import sys
import time

import bpy

from sculptcore_addon import convert, engine, handlers, mapping, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
GRID = int(argv[argv.index('--grid') + 1]) if '--grid' in argv else 1000
ROUNDS = int(argv[argv.index('--rounds') + 1]) if '--rounds' in argv else 4
RADIUS = 0.12
DABS = 60

bpy.ops.mesh.primitive_grid_add(x_subdivisions=GRID, y_subdivisions=GRID, size=4)
ob = bpy.context.object
for v in ob.data.vertices:
    v.co.z = 0.05 * ((v.co.x * 3.1) % 1.0) * ((v.co.y * 2.3) % 1.0)
session = convert.enter(ob)
kernel = int(engine.manager().get("sculptcore::brush::SculptBrushes").items['CLAY'])
sc_brush = stroke._ensure_brush(session)
stroke._ensure_executor(session)
program = stroke.build_program(session, kernel, smooth_factor=0.25)

AREA = (mapping.PLANE_NORMAL_MODES['AREA'], mapping.PLANE_CENTER_CURSOR, False, False,
        0.75, 0.75, 0.0, 0.0, 0.0, 0.0, 1.0)
HOLD = (mapping.PLANE_NORMAL_MODES['AREA'], mapping.PLANE_CENTER_CURSOR, True, False,
        0.75, 0.75, 0.0, 0.0, 0.0, 0.0, 1.0)
FRAMES = {
    'off': (mapping.PLANE_FRAME_DEFAULT, True),
    'area': (AREA, True),        # gather per dab from the live data
    'area-na': (AREA, False),    # gather from the stroke-start data
    'hold': (HOLD, True),        # frame held after dab 1: hook only
}
points = [(-1.5 + 3.0 * i / (DABS - 1), 0.3 * ((i * 7) % 5) / 4.0) for i in range(DABS)]


def run_stroke(frame, accumulate):
    sc_brush = stroke._ensure_brush(session)
    stroke._ensure_executor(session)
    stroke.stroke_begin(session, accumulate=accumulate, anchored_grab=False, plane_frame=frame)
    sc_brush.strength = 0.3
    sc_brush.radius = RADIUS
    sc_brush.invert = False
    sc_brush.planeoff = 0.4
    sc_brush.planeSide = 1.0
    sc_brush.writeProps()
    t0 = time.perf_counter()
    for x, y in points:
        hit = stroke.raycast(session, (x, y, 3.0), (0.0, 0.0, -1.0))
        stroke.set_image_sign(session, (1, 1, 1))
        stroke.apply_dab_program(session, program, hit[0], hit[1], RADIUS, kernel=kernel)
    ms = (time.perf_counter() - t0) * 1000.0
    stroke.stroke_end(session)
    return ms


results = {name: [] for name in FRAMES}
for rnd in range(ROUNDS):
    order = list(FRAMES) if rnd % 2 == 0 else list(reversed(FRAMES))
    for name in order:
        frame, accumulate = FRAMES[name]
        # Fresh geometry and a warm process for every measurement: an untimed
        # default stroke first, then the timed one on top of it.
        convert.exit_(ob)
        session = convert.enter(ob)
        program = stroke.build_program(session, kernel, smooth_factor=0.25)
        run_stroke(mapping.PLANE_FRAME_DEFAULT, True)
        ms = run_stroke(frame, accumulate)
        results[name].append(ms)
        print("round {:d} {:8s} {:8.1f} ms/stroke  {:6.2f} ms/dab".format(rnd, name, ms, ms / DABS), flush=True)
print("PROFILE_PLANE_FRAME " + "  ".join(
    "{}: median {:.1f} ms/stroke".format(name, sorted(v)[len(v) // 2]) for name, v in results.items()), flush=True)
