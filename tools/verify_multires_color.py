# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate multires colour paint (plans/grid-domain-attributes.md P4 + C1-C3).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_color.py -- [--verbose]

What is checked
---------------
Colour is a *cage* attribute that a subdivided level only mirrors: Blender
declares no multires attribute domain, so ``color`` is ``Derived`` and the cage
is its authority. The grid elements are a cache, and a brush may not author a
cache — so the bind refuses the grids-native route (C2), and every dab
travels *down*: onto the cage, immediately, with the grids it touched
re-derived from what the cage now holds.

That write-back is exact rather than a fit: sample (0, 0) of every grid *is* its
corner's cage vert, at weight one, under the ptex-bilinear rule. What it cannot
do is resolve finer than the cage, and the rule that makes the collapse honest
is that sub-face paint comes out as **no paint** — never as paint that shows at
grid resolution and evaporates when some later dab happens to move a neighbour.

So the gates run a stroke's whole life:

1. the storage class decides the route, and it is the only thing that does:
   COLOR is declined because ``color`` is ``Derived``;
2. the cage carries the ``color`` float4 point layer the derived samples are
   built from — without it the draw path has nothing to paint over;
3. the dab paints the materialized slot, and the per-dab scatter carries it onto
   the cage *within the dab* — after which the whole level is already a pure
   function of the cage, so nothing at grid resolution outlives its own dab;
4. the stroke's undo push finds the cage already written and only pairs it with
   the stroke-start snapshot;
5. from the cage it reaches ``ob.data``;
6. undo takes it back off and re-derives the level from the restored cage; redo
   puts it back, with the flush in between not scattering the undone paint on
   again;
7. a dab smaller than a base face paints *nothing* durable: no cage vert moves,
   the slot comes back to its cage-derived values, and the stroke records no
   cage column at all (the accepted resolution collapse of routing colour
   through the cage, §6.2, gated so it stays a decision rather than a surprise);
8. and the same holds mid-stroke, which is where it used to fail: a fine dab
   followed by a coarse one leaves no fine-resolution paint behind for the
   coarse dab's re-derive to sweep away (C1);
9. all of it survives save + reload, which is the point of all of it.

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

# A 2 x 2 cage: vert (x, y) is index y * 3 + x. Each dab below is centred on one
# cage vert and small enough to reach no other, so "which verts changed" is a
# closed-form expectation and not a measurement.
DAB_NORMAL = (0.0, 0.0, 1.0)
DAB_CENTER = (1.0, 1.0, 0.0)
DAB_RADIUS = 0.8
DAB_COLOR = (0.9, 0.1, 0.05, 1.0)
CENTER_VERT = 4
# A second cage vert, far enough from the fine dab below that one cannot
# re-derive the other's grids.
CORNER_CENTER = (2.0, 2.0, 0.0)
CORNER_VERT = 8
MESH_COLOR = (0.05, 0.9, 0.1, 1.0)
# Well inside a base face and far from every cage vert's own sample.
FINE_CENTER = (0.5, 0.5, 0.0)
FINE_RADIUS = 0.2
FINE_COLOR = (0.1, 0.1, 0.9, 1.0)


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


def _changed_verts(before, after):
    """Which verts differ between two float4-per-vert columns, or None if the
    two are not comparable at all."""
    if before is None or after is None or len(before) != len(after):
        return None
    rows_a = before.reshape(-1, 4)
    rows_b = after.reshape(-1, 4)
    return [int(v) for v in np.flatnonzero(np.any(rows_a != rows_b, axis=1))]


def _cage_derived(session):
    """Re-derive the whole level from the cage and report whether that changed
    anything — the collapse invariant, read directly.

    A ``Derived`` attribute's grid elements are a cache, so once a dab has been
    scattered no sample may hold a value the cage cannot reproduce. Anything
    still holding one is paint the viewport shows and the .blend will not."""
    before = _colors(session.mesh_ptr)
    convert.restamp_cage_vert_color(session)
    after = _colors(session.mesh_ptr)
    if before is None or after is None:
        return False
    return bool(np.array_equal(before, after))


def _begin_color_stroke(session, kernel):
    """Start a colour stroke the way the stroke operator does: mark the layer
    it paints and read the cage's pre-stroke state, since from here on every
    dab writes it (see stroke.py and undo.snapshot_cage_columns)."""
    stroke.stroke_begin(session, grids_kernel=kernel)
    session.last_stroke_color = True
    undo.snapshot_cage_columns(session)


def _paint_dab(session, kernel, color, center=DAB_CENTER, radius=DAB_RADIUS):
    """One colour dab straight down onto the flat surface. The engine's per-dab
    ``loadProps`` writes the post-dynamics values back into the Brush fields, so
    strength and radius are set here rather than once.

    Recording the dab's sphere is the stroke operator's job too (stroke.py's
    ``_apply_batch``): the per-dab scatter re-derives those grids whether or not
    a cage vert moved, which is what makes a sub-face dab come out painting
    nothing rather than painting and then evaporating."""
    sc_brush = stroke._ensure_brush(session)
    vec = sc_brush.brushColor.vec
    vec[0], vec[1], vec[2], vec[3] = color
    sc_brush.strength = 1.0
    sc_brush.radius = radius
    sc_brush.invert = False
    sc_brush.writeProps()
    touched = stroke.apply_dab(session, kernel, center, DAB_NORMAL, radius)
    session.dab_regions.extend((center[0], center[1], center[2], radius))
    return touched


def run():
    ob = _object("colgrid", 2, 2)

    convert.enter(ob)
    session = engine.sessions[ob.name]
    convert.ensure_multires_slot(session)
    check(bool(session.mesh_ptr) and bool(session.cage_ptr),
          "session has both a materialized slot and a cage")

    color_kernel = int(engine.manager().get("sculptcore::brush::SculptBrushes").items['COLOR'])

    # --- gate 1: the storage class decides the route, and it is the only
    # thing that does ---
    check(not stroke.grids_capable(session, color_kernel),
          "COLOR is declined — `color` is Derived, so its grid elements are "
          "a cache the kernel may not author (C2)")

    # --- gate 2: the cage carries what the derived samples subdivide ---
    cage_before = _colors(session.cage_ptr)
    check(cage_before is not None, "the cage carries a color float4 point layer")
    check(cage_before is not None and float(np.ptp(cage_before[0::4])) > 0.0,
          "the cage colours vary (a flat seed would hide an unseeded overlay)")
    slot_before = _colors(session.mesh_ptr)
    data_before = _mesh_colors(ob.data)

    # --- gate 3: the dab paints the slot, and lands on the cage within the dab ---
    _begin_color_stroke(session, color_kernel)
    check(not session.last_stroke_grids,
          "the stroke takes the mesh path, which is the cage route's front end")
    moved = _paint_dab(session, color_kernel, DAB_COLOR)
    check(moved > 0, "the dab touched {:d} nodes".format(moved))
    slot_painted = _colors(session.mesh_ptr)
    check(slot_painted is not None and slot_before is not None
          and not np.array_equal(slot_painted, slot_before),
          "and painted the materialized slot, which is what the viewport draws")

    undo.scatter_cage_columns(session)  # what stroke.py does after every batch
    cage_mid = _colors(session.cage_ptr)
    changed = _changed_verts(cage_before, cage_mid)
    check(changed == [CENTER_VERT],
          "the dab moved exactly the cage vert under its centre, before the "
          "stroke ended (got {!r})".format(changed))
    check(cage_mid is not None
          and float(cage_mid[CENTER_VERT * 4] - cage_before[CENTER_VERT * 4]) > 0.5,
          "and moved it towards the dab colour rather than reseeding it")
    check(_cage_derived(session),
          "and the level's samples are already a pure function of the cage")
    stroke.stroke_end(session)

    # --- gate 4: the undo push only pairs what the dabs already wrote ---
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key)
    check(step is not None, "the colour stroke pushed an undo step")
    check(step is not None and step[7] is not None and step[8] is not None,
          "the step carries both sides of the cage colour column")
    cage_after = _colors(session.cage_ptr)
    check(np.array_equal(cage_after, cage_mid),
          "the push found the cage already written and moved it no further")

    # --- gate 5: and from the cage it reaches ob.data ---
    convert.flush(ob)
    data_after = _mesh_colors(ob.data)
    changed = _changed_verts(data_before, data_after)
    check(changed == [CENTER_VERT],
          "the painted vert, and only it, reached ob.data (got {!r})".format(changed))
    check(data_after is not None and cage_after is not None
          and np.allclose(data_after[CENTER_VERT * 4:CENTER_VERT * 4 + 4],
                          cage_after[CENTER_VERT * 4:CENTER_VERT * 4 + 4], atol=1e-6),
          "ob.data holds what the cage holds")

    # --- gate 6: undo takes it back off the cage, redo puts it back ---
    undo.decode(bpy.context, ob, key, -1, False)
    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "undo restored the cage colour column")
    slot_undone = _colors(session.mesh_ptr)
    check(slot_undone is not None and slot_before is not None
          and np.array_equal(slot_undone, slot_before),
          "and re-derived the level from it, so the slot holds no undone paint")
    convert.flush(ob)
    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "the flush after it does not scatter the undone paint back on")
    check(np.array_equal(_mesh_colors(ob.data), data_before),
          "ob.data came back with it")
    undo.decode(bpy.context, ob, key, 1, False)
    check(np.array_equal(_colors(session.cage_ptr), cage_after),
          "redo put the cage colour column back")
    slot_redone = _colors(session.mesh_ptr)

    # --- gate 7: a dab finer than the cage leaves nothing at all ---
    # The accepted trade of routing colour through the cage (plan §6.2): the
    # write-back resolves to base verts, so a dab reaching none of them has
    # nowhere to land. The half that is not a trade but a requirement is that
    # its paint goes with it -- grid-resolution colour the cage cannot
    # reproduce is exactly what a Derived attribute may never hold.
    cage_fine = _colors(session.cage_ptr)
    _begin_color_stroke(session, color_kernel)
    moved = _paint_dab(session, color_kernel, FINE_COLOR,
                       center=FINE_CENTER, radius=FINE_RADIUS)
    check(moved > 0, "the sub-face dab touched {:d} nodes".format(moved))
    slot_fine = _colors(session.mesh_ptr)
    check(slot_fine is not None and slot_redone is not None
          and not np.array_equal(slot_fine, slot_redone),
          "and painted the slot, so there is something for the collapse to find")
    check(convert.sync_cage_vert_color(session) == 0,
          "a dab smaller than a base face changes no cage vert")
    session.dab_regions = []  # the other half of scatter_cage_columns
    check(np.array_equal(_colors(session.cage_ptr), cage_fine),
          "so the cage is unchanged by it")
    slot_collapsed = _colors(session.mesh_ptr)
    check(slot_collapsed is not None and not np.array_equal(slot_collapsed, slot_fine),
          "but the dab's own grids re-derived anyway (C1: no cage vert moved, "
          "so the dab region is the only handle on what to re-derive)")
    check(_cage_derived(session),
          "leaving nothing on screen the cage cannot reproduce")
    stroke.stroke_end(session)
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key)
    check(step is not None and step[7] is None and step[8] is None,
          "and the stroke records no cage column, having durably painted nothing")

    # --- gate 8: the same holds mid-stroke, which is where it used to fail ---
    # A fine dab followed by a coarse one: were the fine paint still sitting on
    # the slot, the coarse dab's re-derive would sweep it away, and the paint
    # would have been visible for exactly as long as it took a neighbour to
    # move. Both dabs collapse as they land, so there is nothing to sweep.
    cage_pre_pair = _colors(session.cage_ptr)
    _begin_color_stroke(session, color_kernel)
    _paint_dab(session, color_kernel, FINE_COLOR, center=FINE_CENTER, radius=FINE_RADIUS)
    undo.scatter_cage_columns(session)
    check(_cage_derived(session), "the fine dab collapsed within its own dab")
    moved = _paint_dab(session, color_kernel, MESH_COLOR, center=CORNER_CENTER)
    check(moved > 0, "the coarse dab after it touched {:d} nodes".format(moved))
    undo.scatter_cage_columns(session)
    cage_pair = _colors(session.cage_ptr)
    changed = _changed_verts(cage_pre_pair, cage_pair)
    check(changed == [CORNER_VERT],
          "only the coarse dab's own cage vert moved (got {!r})".format(changed))
    check(cage_pair is not None and cage_pre_pair is not None
          and float(cage_pair[CORNER_VERT * 4 + 1]
                    - cage_pre_pair[CORNER_VERT * 4 + 1]) > 0.5,
          "and took that dab's colour")
    check(_cage_derived(session),
          "and the level is still a pure function of the cage after both")
    stroke.stroke_end(session)
    undo.push(bpy.context, ob, session)

    convert.flush(ob)
    data_final = _mesh_colors(ob.data)
    convert.exit_(ob)

    # --- gate 9: it survives save + reload, which is the point of all of it ---
    path = os.path.join(tempfile.gettempdir(), "sculptcore_multires_color_gate.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    reloaded = _mesh_colors(bpy.data.objects["colgrid"].data)
    check(reloaded is not None and data_final is not None
          and np.allclose(reloaded, data_final, atol=1e-6),
          "the painted cage colours survived save + reload")
    os.unlink(path)


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

    print("multires colour gate")
    run()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
