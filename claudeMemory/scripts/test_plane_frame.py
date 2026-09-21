# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Plane-brush frame policy, host side: the per-type table, the two push
sites, the per-dab image sign and the batch path.

The engine's own gate (tests/test_plane_frame.cc) proves the frame
resolution; this script proves the addon hands the engine what vanilla's
``calc_brush_plane`` would, on both executors:

- ``mapping.plane_frame`` per brush type, raw Brush and generic capture alike
- a VIEW-normal Clay dab deforms along the pushed view axis only — mesh and
  grids, so both ``stroke_begin`` push sites are live
- the Original-normal hold: a second dab on tilted ground keeps the first
  dab's frame (the surface changes, the deformation direction does not)
- per-dab (``set_image_sign``) and batch (``MeshStroke_dabBatch`` with signs)
  X-mirror strokes agree bit-for-bit on the mesh executor

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \\
        --python claudeMemory/scripts/test_plane_frame.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, mapping, stroke
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
RADIUS = 0.35
STRENGTH = 0.5
UP = (0.0, 0.0, 1.0)


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def kernel_id(name):
    return int(engine.manager().get("sculptcore::brush::SculptBrushes").items[name])


def make_grid(name, height=None):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=48, y_subdivisions=48, size=2)
    ob = bpy.context.object
    ob.name = ob.data.name = name
    if height is not None:
        for v in ob.data.vertices:
            v.co.z = height(v.co.x, v.co.y)
    return ob


def make_multires(name):
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.name = ob.data.name = name
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")
    return ob


def write_dab_props(sc_brush, planeoff=0.4):
    sc_brush.strength = STRENGTH
    sc_brush.radius = RADIUS
    sc_brush.invert = False
    sc_brush.planeoff = planeoff
    sc_brush.planeSide = 1.0
    sc_brush.writeProps()


def positions(session, grids):
    if grids:
        convert.ensure_multires_slot(session)
    return convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()


def policy_table():
    """The per-type dispatch of calc_brush_plane, read raw and through the
    generic capture (which must agree)."""
    b = bpy.data.brushes.new("Plane Policy", mode='SCULPT')
    b.sculpt_plane = 'VIEW'
    b.use_original_normal = True
    b.use_original_plane = True
    b.normal_radius_factor = 0.6
    b.area_radius_factor = 0.8
    b.stabilize_normal = 0.3
    b.stabilize_plane = 0.7
    axis = (0.0, 1.0, 0.0)
    view = mapping.PLANE_NORMAL_MODES['VIEW']
    expected = {
        'CLAY': (view, mapping.PLANE_CENTER_CURSOR, True, True, 0.6, 0.6, 0.0, 0.0, *axis),
        'CLAY_STRIPS': (view, mapping.PLANE_CENTER_AREA, True, True, 0.6, 0.6, 0.0, 0.0, *axis),
        'PLANE': (view, mapping.PLANE_CENTER_AREA, False, False, 0.6, 0.8, 0.3, 0.7, *axis),
        'MULTIPLANE_SCRAPE': (mapping.PLANE_NORMAL_MODES['AREA'], mapping.PLANE_CENTER_CURSOR,
                              False, False, 0.6, 0.6, 0.0, 0.0, *axis),
        'DRAW': mapping.PLANE_FRAME_DEFAULT,
    }
    for brush_type, want in expected.items():
        b.sculpt_brush_type = brush_type
        raw = mapping.plane_frame(b, None, axis)
        close = all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(raw, want)) and len(raw) == len(want)
        check(close, "policy {:s}: raw {!r}".format(brush_type, raw))
        if brush_type == 'DRAW':
            continue
        settings = capture_stroke(b, bpy.context.scene)
        generic = mapping.plane_frame(b, settings, axis)
        check(generic == raw, "policy {:s}: generic capture agrees".format(brush_type))
    # area_radius_factor 0 falls back to the normal factor (vanilla's `> 0` test).
    b.sculpt_brush_type = 'PLANE'
    b.area_radius_factor = 0.0
    fallback = mapping.plane_frame(b, None, axis)
    check(fallback[5] == fallback[4], "policy PLANE: zero area factor -> normal factor")
    # The registry rows and the retained enum exist for the UI/authoring layer.
    for row in ('original_normal', 'original_plane', 'normal_radius_factor',
                'area_radius_factor', 'stabilize_normal', 'stabilize_plane'):
        check(authoring.registry.get('sculptcore.brush.' + row) is not None, "registry row " + row)
    from sculptcore_addon.brush_properties.bindings import RETAINED, binding
    check('sculptcore.brush.sculpt_plane' in RETAINED, "sculpt_plane is a retained binding")
    binding(authoring.registry, 'sculptcore.brush.sculpt_plane', authoring.store(b),
            authoring.store(bpy.context.scene)).rna()
    bpy.data.brushes.remove(b)


def view_axis_dab(name, grids):
    """A Clay dab with the VIEW normal and a +Y view axis moves verts along Y
    only: the frame the operator pushes is the one the kernel deforms with."""
    ob = make_multires(name) if grids else make_grid(name)
    session = convert.enter(ob)
    kernel = kernel_id('CLAY')
    stroke._ensure_brush(session)
    if not grids:
        stroke._ensure_executor(session)
    frame = (mapping.PLANE_NORMAL_MODES['VIEW'], mapping.PLANE_CENTER_CURSOR, False, False,
             1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    stroke.stroke_begin(session, anchored_grab=False, grids_kernel=kernel if grids else None,
                        plane_frame=frame)
    check(session.last_stroke_grids == grids, "{:s}: path dispatched".format(name))
    before = positions(session, grids)
    write_dab_props(session.brush_obj)
    top = (0.0, 0.0, 1.0) if grids else (0.0, 0.0, 0.0)
    hit = stroke.raycast(session, (top[0], top[1], 3.0), (0.0, 0.0, -1.0))
    check(hit is not None, "{:s}: cursor hits the surface".format(name))
    stroke.set_image_sign(session, (1, 1, 1))
    moved = stroke.apply_dab(session, kernel, hit[0], (0.3, 0.0, 0.954), RADIUS)
    check(moved > 0, "{:s}: dab moved geometry ({:d})".format(name, moved))
    stroke.stroke_end(session)
    after = positions(session, grids)
    delta = after - before
    mask = np.linalg.norm(delta, axis=1) > 1e-7
    off_axis = float(np.abs(delta[mask][:, [0, 2]]).max()) if mask.any() else -1.0
    check(mask.any() and off_axis < 1e-6,
          "{:s}: {:d} verts moved along Y only (off-axis {:.2e})".format(name, int(mask.sum()), off_axis))
    convert.exit_(ob)


def original_normal_hold(name):
    """Original Normal on a tilted patch: the first dab's frame is the one
    the second dab deforms with, even though the second cursor sits on ground
    with a different normal. Without the hold the second dab follows the
    local surface."""
    def run(hold):
        ob = make_grid(name + ('_hold' if hold else '_free'),
                       height=lambda x, y: 0.0 if x < 0.0 else 0.6 * x)
        session = convert.enter(ob)
        kernel = kernel_id('CLAY')
        stroke._ensure_brush(session)
        stroke._ensure_executor(session)
        frame = (mapping.PLANE_NORMAL_MODES['AREA'], mapping.PLANE_CENTER_CURSOR, hold, False,
                 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        stroke.stroke_begin(session, accumulate=True, anchored_grab=False, plane_frame=frame)
        before = positions(session, False)
        write_dab_props(session.brush_obj)
        for x in (-0.5, 0.5):
            hit = stroke.raycast(session, (x, 0.0, 3.0), (0.0, 0.0, -1.0))
            stroke.set_image_sign(session, (1, 1, 1))
            stroke.apply_dab(session, kernel, hit[0], hit[1], RADIUS)
        stroke.stroke_end(session)
        delta = positions(session, False) - before
        convert.exit_(ob)
        # The slope-side dab's displacement direction.
        side = delta[(before[:, 0] > 0.3)]
        side = side[np.linalg.norm(side, axis=1) > 1e-7]
        mean = side.mean(axis=0)
        return mean / np.linalg.norm(mean)
    held = run(True)
    free = run(False)
    tilt_held = np.degrees(np.arccos(min(1.0, abs(float(held[2])))))
    tilt_free = np.degrees(np.arccos(min(1.0, abs(float(free[2])))))
    check(tilt_held < 3.0, "original normal held: slope dab moves along the flat frame ({:.2f} deg)".format(tilt_held))
    check(tilt_free > 15.0, "original normal free: slope dab follows the slope ({:.2f} deg)".format(tilt_free))


def mirror_parity(name):
    """X-mirror Clay stroke with the AREA frame: the per-dab path (primary
    then mirror through set_image_sign) and the batch path (signs row) agree
    bit-for-bit, so the batch lambda's image scope matches the host calls."""
    def run(batch):
        ob = make_grid(name + ('_batch' if batch else '_py'),
                       height=lambda x, y: 0.15 * np.sin(3.0 * x) * np.cos(2.0 * y))
        session = convert.enter(ob)
        kernel = kernel_id('CLAY')
        stroke._ensure_brush(session)
        stroke._ensure_executor(session)
        frame = (mapping.PLANE_NORMAL_MODES['AREA'], mapping.PLANE_CENTER_AREA, False, False,
                 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 1.0)
        stroke.stroke_begin(session, accumulate=True, anchored_grab=False, plane_frame=frame)
        before = positions(session, False)
        points = [(0.5, -0.2), (0.5, -0.1), (0.5, 0.0), (0.5, 0.1), (0.5, 0.2)]
        dabs = np.empty((len(points), 7), dtype=np.float32)
        for i, (x, y) in enumerate(points):
            p, n, _face = stroke.raycast(session, (x, y, 3.0), (0.0, 0.0, -1.0))
            dabs[i, 0:3] = p
            dabs[i, 3:6] = n
            dabs[i, 6] = RADIUS
        sign = (-1.0, 1.0, 1.0)
        if batch:
            signs = np.array(sign, dtype=np.float32)
            write_dab_props(session.brush_obj)
            moved = engine.capi().lib.MeshStroke_dabBatch(
                stroke._ensure_executor(session).ptr, session.tree().ptr, session.mesh().ptr,
                session.brush_obj.ptr, kernel, len(dabs), dabs, STRENGTH, 0, 1.0, 0, 1.0, signs, 1)
            check(moved >= 0, "{:s}: batch accepted ({:d})".format(name, moved))
        else:
            for row in dabs:
                write_dab_props(session.brush_obj)
                center = tuple(float(v) for v in row[0:3])
                normal = tuple(float(v) for v in row[3:6])
                stroke.set_image_sign(session, (1, 1, 1))
                stroke.apply_dab(session, kernel, center, normal, RADIUS)
                stroke.set_image_sign(session, sign)
                stroke.apply_dab(session, kernel,
                                 tuple(center[i] * sign[i] for i in range(3)),
                                 tuple(normal[i] * sign[i] for i in range(3)), RADIUS)
        stroke.stroke_end(session)
        after = positions(session, False)
        convert.exit_(ob)
        return before, after
    b0, py = run(False)
    b1, bt = run(True)
    check(np.array_equal(b0, b1), "{:s}: identical starting geometry".format(name))
    moved = float(np.abs(py - bt).max())
    check(np.array_equal(py, bt), "{:s}: per-dab vs batch bit-exact (max |delta| = {!r})".format(name, moved))
    left = np.abs(py - b0)[b0[:, 0] < -0.2].max()
    right = np.abs(py - b0)[b0[:, 0] > 0.2].max()
    check(left > 1e-3 and right > 1e-3,
          "{:s}: both images sculpted (left {:.4f}, right {:.4f})".format(name, left, right))


def main():
    policy_table()
    view_axis_dab("plane_view_mesh", grids=False)
    view_axis_dab("plane_view_grids", grids=True)
    original_normal_hold("plane_orig")
    mirror_parity("plane_mirror")
    if failures:
        raise SystemExit("test_plane_frame: {:d} failure(s)".format(len(failures)))
    print("test_plane_frame: all checks passed")


main()
