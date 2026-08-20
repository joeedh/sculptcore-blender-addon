# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate multires colour paint (plans/grid-domain-attributes.md P4 + B2a).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_color.py -- [--verbose]

What is checked
---------------
Under ``Scene.sculptcore_grid_attrs`` a colour stroke on a multires object runs
grids-native: the engine binds a *session* channel of the grid store, paints a
dense mirror of it, and folds the mirror back at stroke end. Neither that
channel nor the materialized slot's column outlives the session, and Blender has
no multires attribute domain to move them into — so B2a gives the paint a
durable home in the object's own data instead, by writing it back onto the
**cage**. That write is exact restriction rather than a fit: sample (0, 0) of
every grid *is* its corner's cage vert, at weight one.

So the gates run a stroke's whole life:

1. the kill switch decides the route — ``grids_capable`` is False with it off
   and True with it on (the engine answers this off its own attr-binding
   roster, not a tool list);
2. the cage carries the ``color`` float4 point layer the derived draw samples
   are built from — without it the grids draw path has nothing to paint over;
3. a grids-native dab paints grid verts and moves nothing on the host yet;
4. the stroke's undo push is what carries it onto the cage — one vert, and
   every grid corner sample bit-identical to a cage vert (the restriction claim
   graded against the store itself, not against the walk that pairs them);
5. from the cage it reaches ``ob.data``;
6. undo takes it back off and redo puts it back, with the flush in between not
   scattering the undone paint on again;
7. a dab smaller than a base face durably paints nothing — the accepted
   resolution collapse of routing colour through the cage (§6.2), gated so it
   stays a decision rather than a surprise;
8. with the switch off the same stroke takes the mesh path, and the write-back
   reads the slot column instead of the store — the other of its two sources;
9. both survive save + reload, which is the point of all of it.

Whether the paint *renders* — at grid resolution during the session, not at its
cage restriction — is the half no headless run can see, and is checked by eye.
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


def _grid_corners(session):
    """Sample (0, 0) of every grid of the active level, read out of the store's
    ``color`` channel through the channel c-api (B1).

    That sample *is* the grid's cage vert under the bilinear rule, at weight
    one, so it is the only value the write-back may legally copy — which makes
    it the oracle for "exact restriction" that the cage column cannot be on its
    own. Positions would not do: those follow the limit stencil, which moves a
    boundary corner off its cage vert entirely.
    """
    lib = engine.capi().lib
    mr = session.multires_ptr
    level = session.multires_active_level
    channel = lib.Multires_gridChannelFind(mr, convert._SC_COLOR)
    if channel <= 0:
        return None
    per_grid = lib.Multires_gridChannelGridFloats(mr, level, channel)
    if per_grid <= 0:
        return None
    grids = lib.Multires_levelSampleCount(mr, level) // (per_grid // 4)
    values = np.zeros(per_grid * grids, dtype=np.float32)
    if lib.Multires_gridChannelRead(mr, level, channel, 0, grids, values,
                                    values.size) != values.size:
        return None
    return values.reshape(grids, per_grid)[:, :4]


def _paint_dab(session, kernel, color, center=DAB_CENTER, radius=DAB_RADIUS):
    """One colour dab straight down onto the flat surface. The engine's per-dab
    ``loadProps`` writes the post-dynamics values back into the Brush fields, so
    strength and radius are set here rather than once."""
    sc_brush = stroke._ensure_brush(session)
    vec = sc_brush.brushColor.vec
    vec[0], vec[1], vec[2], vec[3] = color
    sc_brush.strength = 1.0
    sc_brush.radius = radius
    sc_brush.invert = False
    sc_brush.writeProps()
    return stroke.apply_dab(session, kernel, center, DAB_NORMAL, radius)


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

    # --- gate 3: a grids-native dab paints, and the host does not move yet ---
    stroke.stroke_begin(session, grids_kernel=color_kernel)
    check(session.last_stroke_grids, "the stroke routed grids-native")
    session.last_stroke_color = True  # the stroke operator's job, and this is not it
    moved = _paint_dab(session, color_kernel, DAB_COLOR)
    stroke.stroke_end(session)
    check(moved > 0, "the dab painted {:d} grid verts".format(moved))

    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "the dab itself left the cage untouched - it wrote a session channel")
    slot_after = _colors(session.mesh_ptr)
    check((slot_before is None) == (slot_after is None)
          and (slot_before is None or np.array_equal(slot_after, slot_before)),
          "and left the materialized slot untouched")

    # --- gate 4: the undo push is what carries the paint onto the cage ---
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key)
    check(step is not None, "the grids colour stroke pushed an undo step")
    check(step is not None and step[8] is not None and step[9] is not None,
          "the step carries both sides of the cage colour column")

    cage_after = _colors(session.cage_ptr)
    changed = _changed_verts(cage_before, cage_after)
    check(changed == [CENTER_VERT],
          "exactly the cage vert under the dab centre changed (got {!r})".format(changed))
    check(cage_after is not None
          and float(cage_after[CENTER_VERT * 4] - cage_before[CENTER_VERT * 4]) > 0.5,
          "and moved towards the dab colour rather than being reseeded")

    # The claim B2a rests on: the write is restriction, not a fit. Every grid's
    # sample (0, 0) has to come back bit-identical on some cage vert, and the
    # four grids meeting at the painted vert have to agree on what it took.
    corners = _grid_corners(session)
    check(corners is not None, "the store's colour channel reads back per grid")
    if corners is not None and cage_after is not None:
        cage_rows = {tuple(row) for row in cage_after.reshape(-1, 4)}
        check(all(tuple(row) in cage_rows for row in corners),
              "every grid corner sample is exactly some cage vert's colour")
        painted = tuple(cage_after[CENTER_VERT * 4:CENTER_VERT * 4 + 4])
        agree = sum(1 for row in corners if tuple(row) == painted)
        check(agree == 4,
              "the four grids meeting at that vert agree on it (got {:d})".format(agree))

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
    # The seek itself, not the blob fallback: a live cursor means the store swap
    # ran, which is the path that pushes a session channel back out to the
    # derived draw samples.
    check(session.grid_cursor == 0, "undo seeked the grid log itself")
    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "undo restored the cage colour column")
    convert.flush(ob)
    check(np.array_equal(_colors(session.cage_ptr), cage_before),
          "and the flush after it does not scatter the undone paint back on")
    check(np.array_equal(_mesh_colors(ob.data), data_before),
          "ob.data came back with it")
    undo.decode(bpy.context, ob, key, 1, False)
    check(np.array_equal(_colors(session.cage_ptr), cage_after),
          "redo put the cage colour column back")

    # --- gate 7: a dab finer than the cage leaves nothing durable ---
    # The accepted trade of routing colour through the cage (plan §6.2): the
    # write-back resolves to base verts, so a dab reaching none of them is
    # session paint and nothing more. Gated so it stays a decision.
    cage_fine = _colors(session.cage_ptr)
    stroke.stroke_begin(session, grids_kernel=color_kernel)
    session.last_stroke_color = True
    moved = _paint_dab(session, color_kernel, FINE_COLOR,
                       center=FINE_CENTER, radius=FINE_RADIUS)
    stroke.stroke_end(session)
    check(moved > 0, "the sub-face dab painted {:d} grid verts".format(moved))
    check(convert.sync_cage_vert_color(session) == 0,
          "a dab smaller than a base face changes no cage vert")
    check(np.array_equal(_colors(session.cage_ptr), cage_fine),
          "so the cage is unchanged by it")

    convert.flush(ob)
    convert.exit_(ob)

    # --- gate 8: the mesh path lands home too, through the slot column ---
    # On its own object, because the source pick is store-first (multires.cc,
    # "the store wins ... a grids-native stroke writes the channel and
    # materializes no level mesh"): a session whose store channel a grids stroke
    # already allocated at this level reads the store, so the slot branch is
    # only reachable where no grids stroke ever ran. That is also the only place
    # it is reachable in earnest — the switch is a dev tool, and post-P5 a
    # multires colour stroke is grids-native or nothing.
    scene.sculptcore_grid_attrs = False
    mesh_ob = _object("colmesh", 2, 2)
    convert.enter(mesh_ob)
    mesh_session = engine.sessions[mesh_ob.name]
    convert.ensure_multires_slot(mesh_session)
    cage_pre_mesh = _colors(mesh_session.cage_ptr)
    slot_pre_mesh = _colors(mesh_session.mesh_ptr)
    stroke.stroke_begin(mesh_session, grids_kernel=color_kernel)
    check(not mesh_session.last_stroke_grids,
          "the same stroke takes the mesh path with the switch off")
    mesh_session.last_stroke_color = True
    moved = _paint_dab(mesh_session, color_kernel, MESH_COLOR)
    stroke.stroke_end(mesh_session)
    check(moved > 0, "the mesh-path dab touched {:d} nodes".format(moved))
    slot_post_mesh = _colors(mesh_session.mesh_ptr)
    check(slot_post_mesh is not None and slot_pre_mesh is not None
          and not np.array_equal(slot_post_mesh, slot_pre_mesh),
          "the mesh-path dab painted the materialized slot")
    check(convert.sync_cage_vert_color(mesh_session) == 1,
          "and the write-back read the slot column onto one cage vert")
    cage_mesh = _colors(mesh_session.cage_ptr)
    changed = _changed_verts(cage_pre_mesh, cage_mesh)
    check(changed == [CENTER_VERT],
          "the vert under that dab, and only it, changed (got {!r})".format(changed))
    check(cage_mesh is not None and cage_pre_mesh is not None
          and float(cage_mesh[CENTER_VERT * 4 + 1] - cage_pre_mesh[CENTER_VERT * 4 + 1]) > 0.5,
          "and took the dab's colour, same as the grids route")
    convert.flush(mesh_ob)
    convert.exit_(mesh_ob)

    # --- gate 9: it survives save + reload, which is the point of all of it ---
    path = os.path.join(tempfile.gettempdir(), "sculptcore_multires_color_gate.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    reloaded = _mesh_colors(bpy.data.objects["colgrid"].data)
    check(reloaded is not None and data_after is not None
          and np.allclose(reloaded[CENTER_VERT * 4:CENTER_VERT * 4 + 4],
                          data_after[CENTER_VERT * 4:CENTER_VERT * 4 + 4], atol=1e-6),
          "the grids-route paint survived save + reload")
    reloaded = _mesh_colors(bpy.data.objects["colmesh"].data)
    check(reloaded is not None and cage_mesh is not None
          and np.allclose(reloaded[CENTER_VERT * 4:CENTER_VERT * 4 + 4],
                          cage_mesh[CENTER_VERT * 4:CENTER_VERT * 4 + 4], atol=1e-6),
          "the mesh-route paint survived it too")
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
