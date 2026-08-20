# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate the multires face-set write-back (plans/grid-domain-attributes.md P3).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_face_sets.py -- [--verbose]

What is checked
---------------
A face set painted while sculpting a multires level lands on the *materialized
slot* — a level mesh the LRU may evict at any time, whose group column is a
derived copy of the cage's. The multires store next to it carries displacements
only. So without a write-back the paint has no home: it disappears at the next
eviction and never reaches the .blend.

``Multires::scatterFaceIntToCage`` is that route, and Blender's own rule on
multires is per *base* face and unweighted (sculpt_face_set.cc), so a partially
painted cage face is claimed whole. The gates below are that rule end to end:

1. a partial paint of one grid claims exactly its base face, and comes back
   uniform across every grid of that face (a non-uniform face would make the
   next write-back read its untouched cells as a fresh disagreement);
2. what reaches ``ob.data`` is the same column, so it survives save + reload;
3. undoing the edit restores the cage and re-derives the slot from it;
4. a *stroke* step carries the same column, since it is a meshlog step rather
   than an attribute step and takes the other of the two decode routes.

This deliberately grades the *rule*, not stock Blender's multires: the
comparison is against what the per-base-face rule predicts.

The cage route (C1-C3)
----------------------
A face set is a *cage* attribute that a subdivided level only mirrors: Blender
declares no multires attribute domain, so ``group`` is ``Derived`` and the cage
is its authority. That is enforced at the bind (C2) rather than left to a
switch, so POLYGROUP never runs grids-native here however
``Scene.sculptcore_grid_attrs`` is set, and every dab travels *down* -- onto the
cage, immediately, with the grids it touched re-derived from what the cage now
holds. Second battery:

5. the storage class decides the route, not the kill switch: POLYGROUP is
   declined with it off *and* on;
6. the dab's own paint reaches the cage within the dab, not at stroke end --
   this is what makes the class true rather than nominal;
7. ``undo.push`` pairs it with the stroke-start snapshot, undo restores the cage
   column and redo puts it back;
8. the object starts with *no* face-set column at all, so the seed also has to
   invent the cage's implicit default group rather than seeding zeros -- which
   would otherwise scatter "no group" onto every face the stroke missed.

Whether the paint *renders* at cage resolution during the stroke is the half no
headless run can see, and is checked by eye.
"""

import os
import sys
import tempfile

import bpy
import numpy as np

from sculptcore_addon import convert, engine, stroke, undo

VERBOSE = False
FAILURES = []


def check(condition, message):
    if condition:
        if VERBOSE:
            print("  ok   {:s}".format(message))
    else:
        FAILURES.append(message)
        print("  FAIL {:s}".format(message))


def _base_grid(name, n):
    """An n x n quad grid — a cage whose faces are all quads, so every grid is
    one quadrant of one face and the runs the write-back walks are exactly 4."""
    verts = [(float(x), float(y), 0.0) for y in range(n + 1) for x in range(n + 1)]
    w = n + 1
    faces = [(y * w + x, y * w + x + 1, (y + 1) * w + x + 1, (y + 1) * w + x)
             for y in range(n) for x in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _object(name, n, level):
    ob = bpy.data.objects.new(name, _base_grid(name, n))
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    md = ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(level):
        bpy.ops.object.multires_subdivide(modifier=md.name)
    return ob


def _face_sets(mesh):
    attr = mesh.attributes.get(".sculpt_face_set")
    if attr is None:
        return None
    values = np.empty(len(mesh.polygons), dtype=np.int32)
    attr.data.foreach_get("value", values)
    return values


def _slot_groups(session):
    values = np.zeros(convert.mesh_face_num(session.mesh_ptr), dtype=np.int32)
    engine.capi().lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, values)
    return values


def run():
    lib = engine.capi().lib
    base_faces = 4
    grids = base_faces * 4  # one grid per cage corner
    ob = _object("fsgrid", 2, 2)

    convert.enter(ob)
    session = engine.sessions[ob.name]
    convert.ensure_multires_slot(session)
    check(bool(session.mesh_ptr) and bool(session.cage_ptr),
          "session has both a materialized slot and a cage")

    slot_faces = convert.mesh_face_num(session.mesh_ptr)
    cells = slot_faces // grids
    check(slot_faces == grids * cells and cells > 1,
          "slot is {:d} grid-major cells over {:d} grids".format(cells, grids))
    face_cells = cells * 4  # cells behind one cage face (its four grids)

    # Stroke start: allocate the fresh group id the same way stroke.py does.
    mesh_obj = session.mesh()
    mesh_obj.ensureFaceGroups()
    new_id = int(mesh_obj.newFaceGroupId())

    # Paint two cells of grid 0 only — a partial claim of cage face 0.
    groups = _slot_groups(session)
    groups[0] = new_id
    groups[2] = new_id
    lib.Mesh_writeFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)

    # --- gate 1: the per-base-face rule ---
    changed = convert.sync_cage_face_attrs(session)
    check(changed == 1,
          "the paint claimed exactly one base face (got {:d})".format(changed))
    after = _slot_groups(session)
    check(bool((after[:face_cells] == new_id).all()),
          "every cell of the claimed face came back uniform")
    check(bool((after[face_cells:] != new_id).all()),
          "no other base face was touched")
    check(convert.sync_cage_face_attrs(session) == 0,
          "a second write-back proposes nothing (the rule does not oscillate)")

    # --- gate 2: it reaches ob.data, and the file ---
    convert.flush(ob)
    values = _face_sets(ob.data)
    check(values is not None and len(values) == base_faces,
          "ob.data carries a base-domain .sculpt_face_set column")
    if values is not None:
        check(int((values == new_id).sum()) == 1,
              "exactly one base face reached ob.data with the new id")

    path = os.path.join(tempfile.gettempdir(), "sculptcore_face_sets_gate.blend")
    convert.exit_(ob)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    reloaded = _face_sets(bpy.data.objects["fsgrid"].data)
    check(reloaded is not None and int((reloaded == new_id).sum()) == 1,
          "the face set survived save + reload")
    os.unlink(path)

    # --- gate 3: undo ---
    ob = bpy.data.objects["fsgrid"]
    bpy.context.view_layer.objects.active = ob
    convert.enter(ob)
    session = engine.sessions[ob.name]
    convert.ensure_multires_slot(session)
    cage_before = convert.cage_face_group_bytes(session)

    groups = _slot_groups(session)
    groups[face_cells] = new_id + 1  # a cell of the second cage face
    lib.Mesh_writeFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)
    key = undo._next_key
    undo.push_face_sets(bpy.context, ob, session, "Edit Face Set", b"", b"")
    check(key in undo._pending, "the edit pushed a cage-domain undo step")
    convert.flush(ob)
    values = _face_sets(ob.data)
    check(values is not None and int((values == new_id + 1).sum()) == 1,
          "the second edit reached ob.data")

    # Undo *leaves* this step: direction -1, not final (the destination step is
    # the one that decodes with is_final).
    undo.decode(bpy.context, ob, key, -1, False)
    check(convert.cage_face_group_bytes(session) == cage_before,
          "undo restored the cage column")
    values = _face_sets(ob.data)
    check(values is not None and int((values == new_id + 1).sum()) == 0,
          "undo removed the second edit from ob.data")
    restamped = _slot_groups(session)
    check(bool((restamped[face_cells:face_cells * 2] != new_id + 1).all()),
          "undo re-derived the slot from the restored cage")

    # --- gate 4: the same, carried by a stroke step instead of an operator ---
    # A stroke's step is a meshlog step, not an _ATTR_TAG one, so the cage
    # column rides along inside it (undo.push's cage_before/cage_after) and
    # decode restores it after the seek.
    cage_pre = convert.cage_face_group_bytes(session)
    from sculptcore_addon import stroke as sc_stroke
    executor = sc_stroke._ensure_executor(session)
    executor.beginStep(False)
    executor.endStep()
    session.meshlog_cursor += 1  # what stroke.py's stroke end does
    session.last_stroke_face_sets = True
    # The stroke operator's other job: the cage's pre-stroke state is read at
    # the start now, because every dab writes it (undo.snapshot_cage_columns).
    undo.snapshot_cage_columns(session)
    groups = _slot_groups(session)
    groups[face_cells * 3] = new_id + 2
    lib.Mesh_writeFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key)
    check(step is not None and step[7] is not None and step[8] is not None,
          "a face-set stroke step carries both sides of the cage column")
    convert.flush(ob)
    values = _face_sets(ob.data)
    check(values is not None and int((values == new_id + 2).sum()) == 1,
          "the stroke's face set reached ob.data")

    undo.decode(bpy.context, ob, key, -1, False)
    check(convert.cage_face_group_bytes(session) == cage_pre,
          "undoing the stroke restored the cage column")
    values = _face_sets(ob.data)
    check(values is not None and int((values == new_id + 2).sum()) == 0,
          "undoing the stroke removed its face set from ob.data")

    convert.exit_(ob)


DAB_CENTER = (1.0, 1.0, 0.0)
DAB_NORMAL = (0.0, 0.0, 1.0)
DAB_RADIUS = 0.8
ACTIVE_GROUP = 7


def _cage_groups(session):
    blob = convert.cage_face_group_bytes(session)
    return None if blob is None else np.frombuffer(blob, dtype=np.int32).copy()


def _paint_dab(session, kernel):
    """One face-set dab straight down onto the flat surface. ``activeGroup`` is
    the id the kernel stamps; the per-dab ``loadProps`` rewrites strength and
    radius, so both are set here rather than once."""
    sc_brush = stroke._ensure_brush(session)
    sc_brush.activeGroup = ACTIVE_GROUP
    sc_brush.strength = 1.0
    sc_brush.radius = DAB_RADIUS
    sc_brush.invert = False
    sc_brush.writeProps()
    return stroke.apply_dab(session, kernel, DAB_CENTER, DAB_NORMAL, DAB_RADIUS)


def run_cage_route():
    """Gates 5-8: the same face set, painted through the cage route."""
    scene = bpy.context.scene
    kernel = int(engine.manager().get("sculptcore::brush::SculptBrushes").items['POLYGROUP'])
    # 4x4 rather than 2x2: on a 2x2 cage the dab's centre is the corner shared
    # by every face, and the per-base-face rule would claim the whole mesh --
    # true, but it would not distinguish a bounded dab from an unbounded one.
    ob = _object("fsgrid_grids", 4, 2)
    check(_face_sets(ob.data) is None,
          "the object starts with no face-set column (the seed must invent one)")

    scene.sculptcore_grid_attrs = False
    convert.enter(ob)
    session = engine.sessions[ob.name]
    convert.ensure_multires_slot(session)

    # --- gate 5: the storage class decides the route, not the switch ---
    check(not stroke.grids_capable(session, kernel),
          "POLYGROUP is declined with sculptcore_grid_attrs off")
    scene.sculptcore_grid_attrs = True
    check(not stroke.grids_capable(session, kernel),
          "and declined with it on too -- `group` is Derived, so its grid "
          "elements are a cache the kernel may not author (C2)")

    default_group = int(getattr(ob.data, "face_sets_color_default", 1))
    cage_before = _cage_groups(session)

    # --- gate 6: the dab's paint reaches the cage within the dab ---
    stroke.stroke_begin(session, grids_kernel=kernel)
    check(not session.last_stroke_grids,
          "the stroke takes the mesh path, which is the cage route's front end")
    session.last_stroke_face_sets = True  # the stroke operator's job; this is not it
    undo.snapshot_cage_columns(session)
    touched = _paint_dab(session, kernel)
    check(touched > 0,
          "the face dab reported {:d} touched nodes".format(touched))
    undo.scatter_cage_columns(session)  # what _dab_at does after every batch
    cage_mid = _cage_groups(session)
    check(not np.array_equal(cage_mid, cage_before),
          "the dab moved the cage before the stroke ended (C1: the cage is the "
          "author, so nothing at grid resolution outlives the dab)")
    # ...and the collapse itself: re-deriving the whole layer from the cage
    # reproduces the slot column bit for bit, so no cell still holds paint the
    # cage cannot make.
    slot_mid = _slot_groups(session)
    convert.restamp_cage_face_attrs(session)
    check(np.array_equal(_slot_groups(session), slot_mid),
          "and the level's cells are already a pure function of the cage")
    stroke.stroke_end(session)

    # --- gate 7: the undo push pairs it with the stroke-start snapshot ---
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    check(key in undo._pending, "the face-set stroke pushed an undo step")
    cage_after = _cage_groups(session)
    check(np.array_equal(cage_after, cage_mid),
          "the push found the cage already written and moved it no further")
    painted = 0 if cage_after is None else int(np.count_nonzero(cage_after == ACTIVE_GROUP))
    check(0 < painted < len(ob.data.polygons),
          "{:d} of {:d} cage faces adopted the active group"
          .format(painted, len(ob.data.polygons)))

    # --- gate 8: the untouched faces got the default group, not zero ---
    check(cage_after is not None
          and bool(np.all(cage_after[cage_after != ACTIVE_GROUP] == default_group)),
          "the faces the stroke missed hold the cage default group")
    convert.flush(ob)
    values = _face_sets(ob.data)
    check(values is not None and int((values == ACTIVE_GROUP).sum()) == painted,
          "the face set reached ob.data")

    undo.decode(bpy.context, ob, key, -1, False)
    check(np.array_equal(_cage_groups(session), cage_before),
          "undoing the stroke restored the cage face-set column")
    undo.decode(bpy.context, ob, key, 1, False)
    check(np.array_equal(_cage_groups(session), cage_after),
          "redoing the stroke put the cage face-set column back")

    convert.exit_(ob)
    scene.sculptcore_grid_attrs = False


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

    print("multires face-set write-back gate")
    run()
    run_cage_route()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
