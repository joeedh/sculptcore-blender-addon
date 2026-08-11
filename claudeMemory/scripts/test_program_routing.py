# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless test for brush-program (autosmooth) routing — plan
claudeMemory/plans/program-grids-routing.md, verify stage.

1. multires cube: ``program_grids_capable`` says yes; with the
   ``sculptcore_grids_programs`` kill switch off it says no (pre-plan routing);
2. an autosmooth program stroke dispatches grids-native
   (``apply_dab_program`` -> ``GridStroke_dabProgram``), moves verts, and the
   draw provider stays GRIDS;
3. grid undo restores the slot mesh bit-exactly; redo re-applies;
4. S4 parity: the per-dab program arm vs ``GridStroke_dabBatchProgram`` on
   identical dabs, within the grids executor's thread noise (1e-6 — see
   test_batch_parity.py for the bound's provenance);
5. S5 parity: the same A/B on a plain mesh vs ``MeshStroke_dabBatchProgram``,
   bit-exact (the mesh executor is run-deterministic);
6. flush exports without error.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_program_routing.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
NO_SIGNS = np.zeros(0, dtype=np.float32)

RADIUS = 0.35
STRENGTH = 0.5
SMOOTH = 0.25
EVENTS = [
    ([(0.5, -0.2), (0.5, -0.1), (0.5, 0.0), (0.5, 0.1), (0.5, 0.2)], False),
    ([(0.3, 0.4), (0.4, 0.4), (0.5, 0.4)], True),
]


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def slot_positions(session):
    return convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()


def draw_kernel():
    return int(engine.manager().get(
        "sculptcore::brush::SculptBrushes").items['DRAW'])


def make_multires(name):
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.name = ob.data.name = name
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")
    return ob


def make_grid(name):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=2)
    ob = bpy.context.object
    ob.name = ob.data.name = name
    return ob


def resolve_dabs(session, points):
    hits = []
    for x, y in points:
        hit = stroke.raycast(session, (x, y, 3.0), (0.0, 0.0, -1.0))
        if hit is not None:
            hits.append(hit)
    dabs = np.empty((len(hits), 7), dtype=np.float32)
    for i, (p, nrm, _face) in enumerate(hits):
        dabs[i, 0:3] = p
        dabs[i, 3:6] = nrm
        dabs[i, 6] = RADIUS
    return dabs


def write_dab_props(sc_brush, invert):
    sc_brush.strength = STRENGTH
    sc_brush.radius = RADIUS
    sc_brush.invert = bool(invert)
    sc_brush.writeProps()


def python_program_arm(session, prog, kernel):
    for points, invert in EVENTS:
        dabs = resolve_dabs(session, points)
        for row in dabs:
            write_dab_props(session.brush_obj, invert)
            stroke.apply_dab_program(
                session, prog,
                tuple(float(v) for v in row[0:3]),
                tuple(float(v) for v in row[3:6]), RADIUS, kernel=kernel)


def routing_and_undo():
    kernel = draw_kernel()
    ob = make_multires("prog_routing")
    session = convert.enter(ob)
    check(session.multires_ptr is not None, "multires session entered")

    check(stroke.program_grids_capable(session, kernel),
          "autosmooth program is grids-capable")
    bpy.context.scene.sculptcore_grids_programs = False
    check(not stroke.program_grids_capable(session, kernel),
          "kill switch off restores pre-plan (mesh) routing")
    bpy.context.scene.sculptcore_grids_programs = True

    prog = stroke.build_program(session, kernel, SMOOTH)
    sc_brush = stroke._ensure_brush(session)
    write_dab_props(sc_brush, False)

    convert.ensure_multires_slot(session)
    pre = slot_positions(session)

    stroke.stroke_begin(session, grids_kernel=kernel)
    check(session.last_stroke_grids, "program stroke dispatched grids-native")
    moved = 0
    for i in range(4):
        write_dab_props(sc_brush, False)
        moved += stroke.apply_dab_program(
            session, prog, (0.05 * i, 0.0, 1.0), (0.0, 0.0, 1.0), RADIUS,
            kernel=kernel)
    stroke.stroke_end(session)
    check(moved > 0, "program dabs moved verts ({:d})".format(moved))
    check(session.draw_provider_kind == 'GRIDS', "provider stayed GRIDS")

    post = slot_positions(session)
    check(np.abs(post - pre).max() > 1e-4, "program stroke landed in the slot")

    lib = engine.capi().lib
    check(bool(lib.GridStroke_undo(session.grid_ptr)), "grid undo")
    check(np.array_equal(slot_positions(session), pre),
          "undo restored the slot bit-exactly")
    check(bool(lib.GridStroke_redo(session.grid_ptr)), "grid redo")
    check(np.array_equal(slot_positions(session), post),
          "redo restored the stroke bit-exactly")

    convert.flush(ob)
    check(True, "flush completed")
    convert.exit_(ob)


def run_grids_program(name, batch):
    kernel = draw_kernel()
    ob = make_multires(name)
    session = convert.enter(ob)
    prog = stroke.build_program(session, kernel, SMOOTH)
    stroke._ensure_brush(session)
    stroke.stroke_begin(session, grids_kernel=kernel)
    check(session.last_stroke_grids, "{:s}: grids dispatched".format(name))
    if batch:
        lib = engine.capi().lib
        for points, invert in EVENTS:
            dabs = resolve_dabs(session, points)
            moved = lib.GridStroke_dabBatchProgram(
                session.grid_ptr, prog.ptr, len(dabs), dabs,
                STRENGTH, int(invert), 1.0, 0, NO_SIGNS, 0)
            check(moved >= 0,
                  "grids dabBatchProgram accepted (got {:d})".format(moved))
    else:
        python_program_arm(session, prog, kernel)
    stroke.stroke_end(session)
    convert.ensure_multires_slot(session)
    positions = slot_positions(session)
    convert.exit_(ob)
    return positions


def run_mesh_program(name, batch):
    kernel = draw_kernel()
    ob = make_grid(name)
    session = convert.enter(ob)
    prog = stroke.build_program(session, kernel, SMOOTH)
    stroke._ensure_brush(session)
    stroke._ensure_executor(session)
    stroke.stroke_begin(session, anchored_grab=False)
    if batch:
        lib = engine.capi().lib
        for points, invert in EVENTS:
            dabs = resolve_dabs(session, points)
            moved = lib.MeshStroke_dabBatchProgram(
                stroke._ensure_executor(session).ptr, session.tree().ptr,
                session.mesh().ptr, session.brush_obj.ptr, prog.ptr,
                len(dabs), dabs, STRENGTH, int(invert), 1.0, 0, 1.0,
                NO_SIGNS, 0)
            check(moved >= 0,
                  "mesh dabBatchProgram accepted (got {:d})".format(moved))
    else:
        python_program_arm(session, prog, kernel)
    stroke.stroke_end(session)
    positions = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    convert.exit_(ob)
    return positions


def main():
    routing_and_undo()

    py = run_grids_program("prog_grids_py", batch=False)
    bt = run_grids_program("prog_grids_batch", batch=True)
    check(py.shape == bt.shape, "grids program arms: same vert count")
    moved = float(np.abs(py - bt).max()) if py.shape == bt.shape else -1.0
    check(py.shape == bt.shape and moved <= 1e-6,
          "S4 grids program parity within thread noise "
          "(max |delta| = {!r})".format(moved))

    py = run_mesh_program("prog_mesh_py", batch=False)
    bt = run_mesh_program("prog_mesh_batch", batch=True)
    check(py.shape == bt.shape, "mesh program arms: same vert count")
    moved = float(np.abs(py - bt).max()) if py.shape == bt.shape else -1.0
    check(py.shape == bt.shape and np.array_equal(py, bt),
          "S5 mesh program parity bit-exact (max |delta| = {!r})".format(moved))
    changed = float(np.abs(py[:, 2]).max())
    check(changed > 1e-3, "mesh program arm actually sculpted ({:.5f})".format(changed))

    if failures:
        raise SystemExit(
            "test_program_routing: {:d} failure(s)".format(len(failures)))
    print("test_program_routing: all checks passed")


main()
