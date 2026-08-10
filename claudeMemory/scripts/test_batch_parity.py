# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Bit-exact parity: the C++ dab-loop batch vs the shipping per-dab Python
cycle, on identical geometry with an identical dab sequence.

The Python arm replicates ``stroke._apply_spaced_dab``'s non-smooth tail
verbatim (per logical dab: field writes + writeProps once, then primary +
mirror through ``apply_dab``); the batch arm hands the same dabs, scalars and
mirror signs to ``MeshStroke_dabBatch`` / ``GridStroke_dabBatch``. Two events
per arm — one plain, one inverted — since invert is a per-event scalar in the
batch contract.

The mesh arm must match bit-for-bit (its executor is run-deterministic —
verified by running the Python arm twice). The grids executor is threaded
and NOT run-deterministic: two identical Python-arm runs differ by ~1 ULP
(1.19e-07 measured 2026-08-10), so the grids gate is a 1e-6 bound — orders
of magnitude below any semantic divergence (a missed overlap/invert fold
shows up at ~1e-2) but above the path's own reduction-order noise.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_batch_parity.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
NO_SIGNS = np.zeros(0, dtype=np.float32)

RADIUS = 0.35
STRENGTH = 0.5
# Two events: (points, invert). Constant-per-event scalars, per the contract.
EVENTS = [
    ([(0.5, -0.2), (0.5, -0.1), (0.5, 0.0), (0.5, 0.1), (0.5, 0.2)], False),
    ([(0.3, 0.4), (0.4, 0.4), (0.5, 0.4)], True),
]
MIRROR = [(-1.0, 1.0, 1.0)]  # X mirror


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def make_grid(name):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=2)
    ob = bpy.context.object
    ob.name = ob.data.name = name
    return ob


def make_multires(name):
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.name = ob.data.name = name
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")
    return ob


def resolve_dabs(session, points):
    """Cast the shared down-rays and return the n x 7 dab rows (batch layout);
    both arms consume these same resolved centers/normals."""
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
    # mapping.apply_dab_state's field writes, minus the bpy Brush read.
    sc_brush.strength = STRENGTH
    sc_brush.radius = RADIUS
    sc_brush.invert = bool(invert)
    sc_brush.writeProps()


def python_arm(session, kernel, mirrors):
    for points, invert in EVENTS:
        dabs = resolve_dabs(session, points)
        for row in dabs:
            write_dab_props(session.brush_obj, invert)
            center = tuple(float(v) for v in row[0:3])
            normal = tuple(float(v) for v in row[3:6])
            stroke.apply_dab(session, kernel, center, normal, RADIUS)
            for sign in mirrors:
                stroke.apply_dab(
                    session, kernel,
                    tuple(center[i] * sign[i] for i in range(3)),
                    tuple(normal[i] * sign[i] for i in range(3)), RADIUS)


def batch_arm_mesh(session, kernel, signs_flat, mirror_count):
    lib = engine.capi().lib
    for points, invert in EVENTS:
        dabs = resolve_dabs(session, points)
        moved = lib.MeshStroke_dabBatch(
            stroke._ensure_executor(session).ptr, session.tree().ptr,
            session.mesh().ptr, session.brush_obj.ptr, kernel,
            len(dabs), dabs, STRENGTH, int(invert), 1.0, 0, 1.0,
            signs_flat, mirror_count)
        check(moved >= 0, "mesh dabBatch accepted (got {:d})".format(moved))


def batch_arm_grids(session, kernel):
    lib = engine.capi().lib
    for points, invert in EVENTS:
        dabs = resolve_dabs(session, points)
        moved = lib.GridStroke_dabBatch(
            session.grid_ptr, kernel, len(dabs), dabs,
            STRENGTH, int(invert), 1.0, 0, NO_SIGNS, 0)
        check(moved >= 0, "grids dabBatch accepted (got {:d})".format(moved))


def run_mesh(name, batch):
    ob = make_grid(name)
    session = convert.enter(ob)
    kernel = int(engine.manager().get(
        "sculptcore::brush::SculptBrushes").items['DRAW'])
    stroke._ensure_brush(session)
    stroke._ensure_executor(session)
    stroke.stroke_begin(session, anchored_grab=False)
    if batch:
        signs_flat = np.array(MIRROR, dtype=np.float32).reshape(-1)
        batch_arm_mesh(session, kernel, signs_flat, len(MIRROR))
    else:
        python_arm(session, kernel, MIRROR)
    stroke.stroke_end(session)
    positions = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    convert.exit_(ob)
    return positions


def run_grids(name, batch):
    ob = make_multires(name)
    session = convert.enter(ob)
    kernel = int(engine.manager().get(
        "sculptcore::brush::SculptBrushes").items['DRAW'])
    stroke._ensure_brush(session)
    stroke.stroke_begin(session, grids_kernel=kernel)
    check(session.last_stroke_grids, "{:s}: grids stroke dispatched".format(name))
    if batch:
        batch_arm_grids(session, kernel)
    else:
        python_arm(session, kernel, [])
    stroke.stroke_end(session)
    convert.ensure_multires_slot(session)
    positions = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    convert.exit_(ob)
    return positions


def main():
    py = run_mesh("parity_mesh_py", batch=False)
    bt = run_mesh("parity_mesh_batch", batch=True)
    check(py.shape == bt.shape, "mesh arm: same vert count")
    moved = float(np.abs(py - bt).max()) if py.shape == bt.shape else -1.0
    check(py.shape == bt.shape and np.array_equal(py, bt),
          "mesh arm bit-exact (max |delta| = {!r})".format(moved))
    changed = float(np.abs(py[:, 2]).max())
    check(changed > 1e-3, "mesh arm actually sculpted ({:.5f})".format(changed))

    py = run_grids("parity_grids_py", batch=False)
    bt = run_grids("parity_grids_batch", batch=True)
    check(py.shape == bt.shape, "grids arm: same vert count")
    moved = float(np.abs(py - bt).max()) if py.shape == bt.shape else -1.0
    check(py.shape == bt.shape and moved <= 1e-6,
          "grids arm within thread noise (max |delta| = {!r})".format(moved))

    if failures:
        raise SystemExit("test_batch_parity: {:d} failure(s)".format(len(failures)))
    print("test_batch_parity: all checks passed")


main()
