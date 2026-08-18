# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate multires colour paint as a grid session channel (plans/grid-domain-attributes.md P4).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_color.py -- [--verbose]

What is checked
---------------
Under ``Scene.sculptcore_grid_attrs`` a colour stroke on a multires object runs
grids-native: the engine binds a *session* channel of the grid store, paints a
dense mirror of it, and folds the mirror back at stroke end. Session channels
are engine-owned — they ride the store blob (so undo sees them) and are excluded
at the flush boundary, so the paint reaches neither the cage nor ``ob.data``.

That makes "nothing moved on the host side" the observable half of P4, and it is
only meaningful next to the two things that must move: the routing decision, and
the mesh path it replaces. So the gates are

1. the kill switch decides the route — ``grids_capable`` is False with it off and
   True with it on (the engine answers this off its own attr-binding roster, not
   a tool list);
2. the cage carries the ``color`` float4 point layer the derived draw samples are
   built from — without it the grids draw path has nothing to paint over;
3. a grids-native colour dab paints verts, and leaves the cage, the materialized
   slot mesh and ``ob.data`` byte-identical;
4. its undo step decodes without disturbing any of them (the store swap pushes
   itself back out to the derived draw samples, which is engine-side, but the
   swap runs through this path);
5. with the switch off the same dab takes the mesh path and *does* land on the
   slot mesh — which is what proves gate 3 is a routing result and not a dab that
   quietly missed.

Whether the paint *renders* is the other half of P4's gate and is checked by
eye: it needs a viewport.
"""

import sys

import bpy
import numpy as np

from sculptcore_addon import convert, engine, stroke, undo

VERBOSE = False
FAILURES = []

DAB_CENTER = (1.0, 1.0, 0.0)
DAB_NORMAL = (0.0, 0.0, 1.0)
DAB_RADIUS = 0.8


def check(condition, message):
    if condition:
        if VERBOSE:
            print("  ok   {:s}".format(message))
    else:
        FAILURES.append(message)
        print("  FAIL {:s}".format(message))


def _base_grid(name, n):
    """A flat n x n quad grid at z = 0 — every cage face is a quad, and the
    subdivided surface stays in the plane, so a dab straight down the z axis
    covers a predictable patch without a raycast."""
    verts = [(float(x), float(y), 0.0) for y in range(n + 1) for x in range(n + 1)]
    w = n + 1
    faces = [(y * w + x, y * w + x + 1, (y + 1) * w + x + 1, (y + 1) * w + x)
             for y in range(n) for x in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _seed_colors(mesh):
    """A POINT/FLOAT_COLOR layer with a per-vertex gradient: the engine binds
    the *active* colour attribute of exactly that kind, and a varying seed is
    what makes "the samples came back seeded" distinguishable from zeroed."""
    attr = mesh.color_attributes.new("Col", 'FLOAT_COLOR', 'POINT')
    values = np.empty(len(mesh.vertices) * 4, dtype=np.float32)
    for i in range(len(mesh.vertices)):
        values[i * 4:i * 4 + 4] = (0.1 + 0.02 * i, 0.2, 0.3, 1.0)
    attr.data.foreach_set("color", values)
    mesh.color_attributes.active_color_index = mesh.color_attributes.find(attr.name)
    return attr


def _object(name, n, level):
    ob = bpy.data.objects.new(name, _base_grid(name, n))
    _seed_colors(ob.data)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    md = ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(level):
        bpy.ops.object.multires_subdivide(modifier=md.name)
    return ob


def _colors(mesh_ptr):
    """The engine mesh's ``color`` float4 vertex column, or None when it has
    none (``Mesh_readVertFloat4Attr`` reports the layer's absence)."""
    if not mesh_ptr:
        return None
    count = convert.mesh_vert_num(mesh_ptr)
    values = np.empty(count * 4, dtype=np.float32)
    if not engine.capi().lib.Mesh_readVertFloat4Attr(mesh_ptr, convert._SC_COLOR, values):
        return None
    return values


def _mesh_colors(mesh):
    attr = mesh.color_attributes.get("Col")
    if attr is None:
        return None
    values = np.empty(len(mesh.vertices) * 4, dtype=np.float32)
    attr.data.foreach_get("color", values)
    return values


def _paint_dab(session, kernel, color):
    """One colour dab straight down onto the flat surface. The engine's per-dab
    ``loadProps`` writes the post-dynamics values back into the Brush fields, so
    strength and radius are set here rather than once."""
    sc_brush = stroke._ensure_brush(session)
    vec = sc_brush.brushColor.vec
    vec[0], vec[1], vec[2], vec[3] = color
    sc_brush.strength = 1.0
    sc_brush.radius = DAB_RADIUS
    sc_brush.invert = False
    sc_brush.writeProps()
    return stroke.apply_dab(session, kernel, DAB_CENTER, DAB_NORMAL, DAB_RADIUS)


def run():
    scene = bpy.context.scene
    ob = _object("colgrid", 2, 2)

    scene.sculptcore_grid_attrs = False
    convert.enter(ob)
    session = engine.sessions[ob.name]
    convert.ensure_multires_slot(session)
    check(bool(session.mesh_ptr) and bool(session.cage_ptr),
          "session has both a materialized slot and a cage")

    color_kernel = int(engine.manager().get("sculptcore::brush::SculptBrushes").items['COLOR'])

    # --- gate 1: the kill switch decides the route ---
    check(not stroke.grids_capable(session, color_kernel),
          "COLOR falls back to the mesh path with sculptcore_grid_attrs off")
    scene.sculptcore_grid_attrs = True
    check(stroke.grids_capable(session, color_kernel),
          "COLOR runs grids-native with sculptcore_grid_attrs on")

    # --- gate 2: the cage carries what the draw samples subdivide ---
    cage_before = _colors(session.cage_ptr)
    check(cage_before is not None, "the cage carries a color float4 point layer")
    check(cage_before is not None and float(np.ptp(cage_before[0::4])) > 0.0,
          "the cage colours vary (a flat seed would hide an unseeded overlay)")
    slot_before = _colors(session.mesh_ptr)
    data_before = _mesh_colors(ob.data)

    # --- gate 3: a grids-native dab paints, and moves nothing on the host ---
    stroke.stroke_begin(session, grids_kernel=color_kernel)
    check(session.last_stroke_grids, "the stroke routed grids-native")
    moved = _paint_dab(session, color_kernel, (0.9, 0.1, 0.05, 1.0))
    stroke.stroke_end(session)
    check(moved > 0, "the dab painted {:d} grid verts".format(moved))

    cage_after = _colors(session.cage_ptr)
    check(cage_after is not None and np.array_equal(cage_after, cage_before),
          "the paint left the cage untouched (a session channel, not a cage scatter)")
    slot_after = _colors(session.mesh_ptr)
    check((slot_before is None) == (slot_after is None)
          and (slot_before is None or np.array_equal(slot_after, slot_before)),
          "the paint left the materialized slot untouched")

    convert.flush(ob)
    data_after = _mesh_colors(ob.data)
    check((data_before is None) == (data_after is None)
          and (data_before is None or np.array_equal(data_after, data_before)),
          "the paint did not reach ob.data (session channels stop at the flush)")

    # --- gate 4: its undo step decodes ---
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    check(key in undo._pending, "the grids colour stroke pushed an undo step")
    undo.decode(bpy.context, ob, key, -1, False)
    # The seek itself, not the blob fallback: a live cursor means the store
    # swap ran, which is the path that pushes a session channel back out to the
    # derived draw samples.
    check(session.grid_cursor == 0, "undo seeked the grid log itself")
    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "undoing the stroke left the cage untouched too")

    # --- gate 5: the same dab on the mesh path does land on the slot ---
    # Without this, gate 3 would also pass for a dab that simply missed.
    scene.sculptcore_grid_attrs = False
    stroke.stroke_begin(session, grids_kernel=color_kernel)
    check(not session.last_stroke_grids,
          "the same stroke takes the mesh path with the switch off")
    moved = _paint_dab(session, color_kernel, (0.05, 0.9, 0.1, 1.0))
    stroke.stroke_end(session)
    check(moved > 0, "the mesh-path dab touched {:d} nodes".format(moved))
    slot_mesh_path = _colors(session.mesh_ptr)
    check(slot_mesh_path is not None and slot_after is not None
          and not np.array_equal(slot_mesh_path, slot_after),
          "the mesh-path dab painted the materialized slot")

    convert.exit_(ob)


def main():
    global VERBOSE

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    VERBOSE = "--verbose" in argv
    for arg in argv:
        if arg not in {"--verbose"}:
            raise SystemExit("unknown argument {!r}".format(arg))

    # The depsgraph handler rebuilds a session from the object's data on every
    # update; the direct convert.enter/flush calls below are that rebuild's job.
    from sculptcore_addon import handlers
    handlers.unregister()

    print("multires colour session-channel gate")
    run()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
