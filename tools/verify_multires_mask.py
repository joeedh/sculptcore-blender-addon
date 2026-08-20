# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate the multires paint mask on the store (grids-native-completion MK2/MK4).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_multires_mask.py -- [--verbose]

What is checked
---------------
The store's ``mask`` channel is the addon's one mask truth (MK4): import
copies the grid paint mask into it exactly at the top level (store sample
order == engine sample order) and seeds coarser levels by injection; export
is the exact inverse read of the top level. Slot-mesh mask columns and the
level domains' dense mirrors are caches, refreshed against the engine's
``Multires_maskGeneration`` counter — there is no push protocol left to
forget to run.

MASK strokes run grids-native (MK2): the kernel edits the level's grid
domain, and stroke end folds the edits into the store as an EDIT
(upward delta-prolongation, downward debt). So the gates check:

1. routing — ``grids_capable`` accepts MASK on a multires session, and the
   stroke actually dispatches grids-native;
2. a no-edit round trip is bit-identical — enter + flush returns exactly the
   stored lattice, and a maskless object stays maskless (no zero CD layer);
3. a grids MASK stroke on a *maskless* object creates mask content: the
   domain reads it back, the store holds it after stroke end, and the
   generation counter records the change;
4. the stroke is visible to a mesh-path read — materializing the slot syncs
   its ``.spatial.v.mask`` column to what the stroke wrote, without any
   explicit mask plumbing at the call site;
5. a level switch restricts it down — the coarse level's domain shows the
   mask (9-point full weighting spends the down-debt), the coarse slot's
   column agrees, and switching back finds the top level's detail intact;
6. flush exports the store's top level into the CD layer, exactly.

Whether the mask overlay *renders* right across level switches is the half a
headless run cannot see, and is checked by eye.
"""

import sys

import bpy
import numpy as np

from sculptcore_addon import convert, engine, stroke

VERBOSE = False
FAILURES = []

# Same closed-form geometry as verify_multires_color: a flat 2 x 2 quad cage
# at z = 0, subdivided twice. A dab straight down covers a predictable patch.
LEVEL = 2
DAB_NORMAL = (0.0, 0.0, 1.0)
DAB_CENTER = (1.0, 1.0, 0.0)
DAB_RADIUS = 0.8


def check(condition, message):
    if condition:
        if VERBOSE:
            print("  ok   {:s}".format(message))
    else:
        FAILURES.append(message)
        print("  FAIL {:s}".format(message))


def _base_grid(name, n):
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


def _blender_mask(ob):
    """The stored grid paint mask in Blender subdiv-vert order, or None when
    the object has no mask layer."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    if not has_mask:
        return None
    return np.array(values, dtype=np.float32)


def _store_top(session):
    """The store's top-level mask channel in engine sample order, or None
    while the channel holds nothing there."""
    lib = engine.capi().lib
    mapping = session.multires_map
    ch = lib.Multires_gridChannelFind(session.multires_ptr, b"mask")
    if ch < 0 or not lib.Multires_gridChannelLevelAllocated(
            session.multires_ptr, mapping.level, ch):
        return None
    n = len(mapping.engine_sample_to_blender)
    w = mapping.grid_size
    values = np.empty(n, dtype=np.float32)
    if lib.Multires_gridChannelRead(session.multires_ptr, mapping.level, ch,
                                    0, n // (w * w), values, n) != n:
        return None
    return values


def _domain_mask(session, level):
    lib = engine.capi().lib
    nv = lib.Multires_levelVertCount(session.multires_ptr, level)
    values = np.zeros(nv, dtype=np.float32)
    if not lib.Multires_readDomainMask(session.multires_ptr, level, values, nv):
        return None
    return values


def _column_mask(session):
    if not session.mesh_ptr:
        return None
    lib = engine.capi().lib
    nv = convert.mesh_vert_num(session.mesh_ptr)
    values = np.empty(nv, dtype=np.float32)
    if not lib.Mesh_readVertFloatAttr(session.mesh_ptr, convert._SC_MASK, values):
        return None
    return values


def _mask_dab(session, kernel, center=DAB_CENTER, radius=DAB_RADIUS):
    """One MASK dab straight down. The engine's per-dab ``loadProps`` writes
    post-dynamics values back into the Brush fields, so strength and radius
    are re-set before every ``writeProps``."""
    sc_brush = stroke._ensure_brush(session)
    sc_brush.strength = 1.0
    sc_brush.radius = radius
    sc_brush.invert = False
    sc_brush.writeProps()
    return stroke.apply_dab(session, kernel, center, DAB_NORMAL, radius)


def run_round_trip():
    """Gate 2: enter + flush on a seeded mask is bit-identical, and a
    maskless object stays maskless."""
    ob = _object("maskrt", 2, LEVEL)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    values, _has = ob.multires_mask_to_vert_values(depsgraph)
    # A varying in-[0,1] seed: export clips to 0..1, so staying inside the
    # range is what makes "bit-identical" a fair demand.
    seed = (np.arange(len(values), dtype=np.float32) % 17) / 16.0
    ob.multires_mask_from_vert_values(depsgraph, seed)

    convert.enter(ob)
    session = engine.sessions[ob.name]
    stored = _store_top(session)
    check(stored is not None, "import created the store's mask channel")
    if stored is not None:
        mapping = session.multires_map
        check(np.array_equal(stored, seed[mapping.engine_sample_to_blender]),
              "the store top holds the seed exactly (order-paired copy)")
    convert.flush(ob)
    out = _blender_mask(ob)
    check(out is not None and np.array_equal(out, seed),
          "a no-edit round trip returns the seed bit-identically")
    convert.exit_(ob)

    bare = _object("maskless", 2, LEVEL)
    convert.enter(bare)
    bare_session = engine.sessions[bare.name]
    check(_store_top(bare_session) is None,
          "a maskless object seeds no store channel")
    convert.flush(bare)
    check(_blender_mask(bare) is None,
          "and flush creates no zero CD layer for it")
    convert.exit_(bare)


def run_stroke():
    """Gates 1 and 3-6: a grids-native MASK stroke, read back through every
    cache and across a level switch."""
    ob = _object("maskgrid", 2, LEVEL)
    convert.enter(ob)
    session = engine.sessions[ob.name]
    lib = engine.capi().lib

    mask_kernel = int(engine.manager().get("sculptcore::brush::SculptBrushes").items['MASK'])

    # --- gate 1: routing ---
    check(stroke.grids_capable(session, mask_kernel),
          "MASK is grids-capable on a multires session (the MK2 holdback is gone)")
    check(stroke.toggle_kernel_name('MASK', None, session) == "MASK",
          "the Ctrl toggle still names MASK")

    gen_before = int(lib.Multires_maskGeneration(session.multires_ptr))
    domain_before = _domain_mask(session, LEVEL)

    # --- gate 3: the stroke creates mask content on a maskless object ---
    stroke.stroke_begin(session, grids_kernel=mask_kernel)
    check(session.last_stroke_grids, "the MASK stroke dispatched grids-native")
    moved = _mask_dab(session, mask_kernel)
    check(moved > 0, "the dab touched {:d} verts".format(moved))
    domain_mid = _domain_mask(session, LEVEL)
    check(domain_mid is not None and domain_before is not None
          and float(domain_mid.max()) > 0.0
          and not np.array_equal(domain_mid, domain_before),
          "and raised the level domain's mask under the cursor")
    stroke.stroke_end(session)

    stored = _store_top(session)
    check(stored is not None and float(stored.max()) > 0.0,
          "stroke end folded the edits into the store's mask channel")
    gen_after = int(lib.Multires_maskGeneration(session.multires_ptr))
    check(gen_after > gen_before,
          "and the mask generation counter recorded the change "
          "({:d} -> {:d})".format(gen_before, gen_after))

    # --- gate 4: visible to a mesh-path read, with no mask plumbing ---
    convert.ensure_multires_slot(session)
    column = _column_mask(session)
    domain_now = _domain_mask(session, LEVEL)
    check(column is not None and domain_now is not None
          and np.array_equal(column, domain_now),
          "materializing the slot synced its mask column to the stroke")

    # --- gate 5: a level switch restricts it down, and back up loses nothing ---
    top_before_switch = _store_top(session)
    convert.set_multires_level(ob, 1)
    check(session.multires_active_level == 1, "switched to level 1")
    coarse = _domain_mask(session, 1)
    check(coarse is not None and float(coarse.max()) > 0.0,
          "the coarse domain shows the restricted mask (down-debt settled)")
    coarse_column = _column_mask(session)
    check(coarse_column is not None and coarse is not None
          and np.array_equal(coarse_column, coarse),
          "and the coarse slot's column agrees with it")
    convert.set_multires_level(ob, LEVEL)
    check(np.array_equal(_store_top(session), top_before_switch),
          "switching back finds the top level's mask detail intact")

    # --- gate 6: flush exports the store top exactly ---
    convert.flush(ob)
    out = _blender_mask(ob)
    stored = _store_top(session)
    check(out is not None and stored is not None, "flush created the CD mask layer")
    if out is not None and stored is not None:
        mapping = session.multires_map
        check(np.array_equal(out[mapping.engine_sample_to_blender],
                             np.clip(stored, 0.0, 1.0)),
              "and it holds the store's top level exactly")
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

    print("multires mask round-trip gate (MK4)")
    run_round_trip()

    print("grids-native MASK stroke gate (MK2)")
    run_stroke()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
