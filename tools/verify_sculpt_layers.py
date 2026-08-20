# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Gate the sculpt-layer stack wiring (grids-native-completion LD3).

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_sculpt_layers.py -- [--verbose]

What is checked
---------------
A sculpt layer is an extra displacement channel the LAYERDRAW kernel writes
into; the composited surface is base + sum(weight_i * layer_i). On multires
the stack lives in the grid store (one channel per layer, settings rows on
the cage); on a plain mesh it is a "slayer" vertex attribute plus a
mesh-side settings row. The stroke operator creates the write target on
first use (layers.ensure_stroke_target), and every structural stack op
pushes one MR_LAYERS undo step (layer table + edit target + store blob).

1. routing — every mapped kernel exists in the loaded DLL's enum (a stale
   vendored build without the extra kernels fails here, not mid-stroke),
   and a LAYER brush resolves to LAYERDRAW via ``mapping.kernel_enum``;
2. plain mesh — ensure_stroke_target creates the "slayer" settings row
   (idempotently); a LAYERDRAW stroke moves verts through the mesh
   executor's LayerEditScope fold, the meshlog step undoes and redoes it
   bit-exactly, and flush shows the result to Blender;
3. multires create-on-first-use — a fresh session has no stack and the
   grids roster declines LAYERDRAW; ensure_stroke_target creates + targets
   a layer (one MR_LAYERS step), re-ensures the slot scratch row, and the
   roster flips to capable;
4. a grids-native LAYERDRAW stroke lands in the store's "slayer" channel
   while channel 0 stays byte-identical (the LD1 attribution contract),
   and the grid step undoes/redoes the channel;
5. MR_LAYERS undo — undoing add-layer removes the stack (channel and all),
   redo restores it, and the grid step redone on top of the restored blob
   brings the stroke's content back exactly (the dead-history fallback);
   removing a layer with content is fully undoable — the money gate;
6. recomposite — with the layer no longer the edit target, weight 0 / 2 / 1
   scales the composited slot positions (base + weight * delta), and
   disabling the layer removes its contribution;
7. the registered operators against a real headless mode entry
   (object.custom_mode_toggle): add / add / mirror-weight round trip /
   set-target toggle / toggle-enabled / remove, with the WindowManager
   mirror tracking the engine stack, ending with a clean mode exit.

How the layer list panel draws — and the viewport recomposite — is the half
a headless run cannot see, and is checked by eye.
"""

import sys

import bpy
import numpy as np

from sculptcore_addon import convert, engine, layers, mapping, stroke

VERBOSE = False
FAILURES = []

# Same closed-form geometry as verify_multires_mask: a flat 2 x 2 quad cage
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


def _plain_object(name, n):
    ob = bpy.data.objects.new(name, _base_grid(name, n))
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    return ob


def _kernel():
    items = engine.manager().get("sculptcore::brush::SculptBrushes").items
    return int(items['LAYERDRAW'])


def _dab(session, kernel, center=DAB_CENTER, radius=DAB_RADIUS):
    """One LAYERDRAW dab straight down. The engine's per-dab ``loadProps``
    writes post-dynamics values back into the Brush fields, so strength and
    radius are re-set before every ``writeProps``."""
    sc_brush = stroke._ensure_brush(session)
    sc_brush.strength = 1.0
    sc_brush.radius = radius
    sc_brush.invert = False
    sc_brush.writeProps()
    return stroke.apply_dab(session, kernel, center, DAB_NORMAL, radius)


def _channel_top(session, ch, comps):
    """A store channel's top level in engine sample order (``comps`` floats
    per sample): zeros while the level is unallocated (a fresh channel holds
    nothing), None on a read failure."""
    lib = engine.capi().lib
    mr_map = session.multires_map
    samples = len(mr_map.engine_sample_to_blender)
    w = mr_map.grid_size
    n = samples * comps
    if ch < 0:
        return None
    if not lib.Multires_gridChannelLevelAllocated(session.multires_ptr,
                                                  mr_map.level, ch):
        return np.zeros(n, dtype=np.float32)
    values = np.empty(n, dtype=np.float32)
    if lib.Multires_gridChannelRead(session.multires_ptr, mr_map.level, ch,
                                    0, samples // (w * w), values, n) != n:
        return None
    return values


def _layer_channel(session):
    lib = engine.capi().lib
    return int(lib.Multires_gridChannelFind(session.multires_ptr, b"slayer"))


def _slot_positions(session):
    """Composited slot positions. Layer mutators drop the slot (the rebind
    leaves the session slot-less until the next mesh-path need), so
    materialize before every read."""
    convert.ensure_multires_slot(session)
    return convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()


def run_routing():
    """Gate 1: the loaded DLL carries every mapped kernel, and LAYER routes
    to LAYERDRAW."""
    mgr = engine.manager()
    items = mgr.get("sculptcore::brush::SculptBrushes").items
    missing = sorted({k for k in mapping.KERNEL_BY_TYPE.values()
                      if items.get(k) is None})
    check(not missing,
          "every mapped kernel exists in the engine enum (missing: {})".format(
              ", ".join(missing) or "none"))
    check('LAYER' not in mapping.UNSUPPORTED,
          "LAYER is no longer listed unsupported")
    brush = bpy.data.brushes.new("layer-verify", mode='SCULPT')
    brush.sculpt_brush_type = 'LAYER'
    check(mapping.kernel_enum(mgr, brush) == _kernel(),
          "kernel_enum routes a LAYER brush to LAYERDRAW")


def run_plain():
    """Gate 2: the plain-mesh path — settings row on first use, a stroke
    that moves verts, exact meshlog undo/redo, and a Blender-visible flush."""
    from sculptcore_addon import undo

    ob = _plain_object("layerplain", 2)
    convert.enter(ob)
    session = engine.sessions[ob.name]
    lib = engine.capi().lib
    kernel = _kernel()

    check(lib.Mesh_sculptLayerCount(session.mesh_ptr) == 0,
          "a fresh mesh session has no sculpt-layer row")
    layers.ensure_stroke_target(bpy.context, ob, session)
    check(lib.Mesh_sculptLayerCount(session.mesh_ptr) == 1,
          "ensure_stroke_target created the \"slayer\" row")
    layers.ensure_stroke_target(bpy.context, ob, session)
    check(lib.Mesh_sculptLayerCount(session.mesh_ptr) == 1,
          "and a second ensure is a no-op")

    p0 = convert.mesh_positions(session.mesh_ptr).copy()
    stroke.stroke_begin(session)
    check(not session.last_stroke_grids, "a plain-mesh stroke takes the mesh path")
    _dab(session, kernel)
    stroke.stroke_end(session)
    key = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key)
    check(step is not None and step[0] == ob.name,
          "the stroke pushed a meshlog step")

    p1 = convert.mesh_positions(session.mesh_ptr).copy()
    check(float(np.abs(p1 - p0).max()) > 1e-2,
          "the LAYERDRAW stroke moved verts (LayerEditScope fold)")
    undo.decode(bpy.context, ob, key, -1, False)
    check(np.array_equal(convert.mesh_positions(session.mesh_ptr), p0),
          "undo restored the pre-stroke positions exactly")
    undo.decode(bpy.context, ob, key, 1, False)
    check(np.array_equal(convert.mesh_positions(session.mesh_ptr), p1),
          "and redo brought the stroke back exactly")

    convert.flush(ob)
    out = np.empty(len(ob.data.vertices) * 3, dtype=np.float32)
    convert._read_positions(ob.data, out)
    check(float(np.abs(out.reshape(-1, 3)[:, 2]).max()) > 1e-2,
          "flush exported the displaced surface to Blender")
    convert.exit_(ob)


def run_multires():
    """Gates 3-5: create-on-first-use, the grids-native stroke with LD1
    attribution, and the MR_LAYERS undo round trips."""
    from sculptcore_addon import undo

    ob = _object("layergrid", 2, LEVEL)
    convert.enter(ob)
    session = engine.sessions[ob.name]
    lib = engine.capi().lib
    kernel = _kernel()

    check(layers.layer_count(session) == 0 and layers.edit_target(session) == -1,
          "a fresh multires session has no layer stack")
    check(not stroke.grids_capable(session, kernel),
          "and the grids roster declines LAYERDRAW without an edit target")

    key_add = undo._next_key
    layers.ensure_stroke_target(bpy.context, ob, session)
    check(layers.layer_count(session) == 1 and layers.edit_target(session) == 0,
          "ensure_stroke_target created and targeted a layer")
    step = undo._pending.get(key_add)
    check(step is not None and step[0] is undo._ATTR_TAG
          and step[3] == 'MR_LAYERS',
          "and pushed one MR_LAYERS step for it")
    convert.ensure_multires_slot(session)
    check(session.mesh_ptr
          and lib.Mesh_sculptLayerCount(session.mesh_ptr) == 1,
          "and slot materialization brings the scratch row with it")
    next_before = undo._next_key
    layers.ensure_stroke_target(bpy.context, ob, session)
    check(layers.layer_count(session) == 1 and undo._next_key == next_before,
          "a second ensure neither adds a layer nor pushes a step")
    check(stroke.grids_capable(session, kernel),
          "the grids roster now accepts LAYERDRAW (live edit target)")

    ch = _layer_channel(session)
    check(ch > 0, "the stack's \"slayer\" store channel exists")
    ch0_before = _channel_top(session, 0, 3)

    stroke.stroke_begin(session, grids_kernel=kernel)
    check(session.last_stroke_grids, "the stroke dispatched grids-native")
    _dab(session, kernel)
    stroke.stroke_end(session)
    key_stroke = undo._next_key
    undo.push(bpy.context, ob, session)
    step = undo._pending.get(key_stroke)
    check(step is not None and step[0] is undo._GRID_TAG,
          "and pushed a grids-native step")

    content = _channel_top(session, ch, 3)
    check(content is not None and float(np.abs(content).max()) > 1e-2,
          "the dab landed in the layer channel")
    ch0_after = _channel_top(session, 0, 3)
    check(ch0_before is not None and ch0_after is not None
          and np.array_equal(ch0_after, ch0_before),
          "while channel 0 stayed byte-identical (LD1 attribution)")

    undo.decode(bpy.context, ob, key_stroke, -1, False)
    zeroed = _channel_top(session, _layer_channel(session), 3)
    check(zeroed is not None and float(np.abs(zeroed).max()) < 1e-6,
          "undoing the stroke zeroed the layer channel")
    undo.decode(bpy.context, ob, key_stroke, 1, False)
    back = _channel_top(session, _layer_channel(session), 3)
    check(back is not None and np.array_equal(back, content),
          "and redo restored it exactly")

    # The MR_LAYERS round trip, in stack order: stroke off, add off, add
    # back, stroke back (the last through the dead-history blob fallback --
    # the add-undo's blob restore killed the grid log).
    undo.decode(bpy.context, ob, key_stroke, -1, False)
    undo.decode(bpy.context, ob, key_add, -1, False)
    check(layers.layer_count(session) == 0 and layers.edit_target(session) == -1,
          "undoing the add removed the stack")
    check(_layer_channel(session) < 0,
          "and the store channel with it")
    undo.decode(bpy.context, ob, key_add, 1, False)
    check(layers.layer_count(session) == 1 and layers.edit_target(session) == 0,
          "redoing the add restored the layer and its target")
    fresh = _channel_top(session, _layer_channel(session), 3)
    check(fresh is not None and float(np.abs(fresh).max()) < 1e-6,
          "with the channel back at zero")
    undo.decode(bpy.context, ob, key_stroke, 1, False)
    back = _channel_top(session, _layer_channel(session), 3)
    check(back is not None and np.array_equal(back, content),
          "and the grid step redone on top brought the content back exactly")

    # The money gate: removing a layer with content is fully undoable.
    key_remove = undo._next_key
    layers._structural(bpy.context, ob, session, "Remove Sculpt Layer",
                       lambda l, mr: l.Multires_layerRemove(mr, 0))
    check(layers.layer_count(session) == 0 and _layer_channel(session) < 0,
          "removing the layer dropped it and its channel")
    undo.decode(bpy.context, ob, key_remove, -1, False)
    restored = _channel_top(session, _layer_channel(session), 3)
    check(layers.layer_count(session) == 1 and restored is not None
          and np.array_equal(restored, content),
          "undoing the remove restored the layer, content and all")
    undo.decode(bpy.context, ob, key_remove, 1, False)
    check(layers.layer_count(session) == 0,
          "and redo removed it again")
    convert.exit_(ob)


def run_recomposite():
    """Gate 6: weight and enabled recomposite the slot surface (base +
    weight * delta), exercised off-target the way the panel does."""
    from sculptcore_addon import undo

    ob = _object("layerweight", 2, LEVEL)
    convert.enter(ob)
    session = engine.sessions[ob.name]
    lib = engine.capi().lib
    kernel = _kernel()

    layers.ensure_stroke_target(bpy.context, ob, session)
    stroke.stroke_begin(session, grids_kernel=kernel)
    _dab(session, kernel)
    stroke.stroke_end(session)
    undo.push(bpy.context, ob, session)

    p1 = _slot_positions(session)
    z1 = float(np.abs(p1[:, 2]).max())
    check(z1 > 5e-2, "the stroke displaced the composited surface")

    # A second layer takes the target so layer 0's weight is free to move
    # (setting the target's weight clears the target -- the engine rule the
    # panel honours by disabling that slider).
    layers._structural(bpy.context, ob, session, "Add Sculpt Layer",
                       layers._add_and_target)
    check(layers.edit_target(session) == 1, "a second layer took the target")

    def set_weight(value):
        # The panel's _weight_set path, minus the WindowManager mirror.
        undo.materialize_grid_blobs(session)
        lib.Multires_layerSetWeight(session.multires_ptr, 0, value)
        convert._rebind_multires_views(session, session.multires_active_level)

    set_weight(0.0)
    z = float(np.abs(_slot_positions(session)[:, 2]).max())
    check(z < 1e-5, "weight 0 removed the layer's contribution")
    set_weight(2.0)
    z = float(np.abs(_slot_positions(session)[:, 2]).max())
    check(abs(z - 2.0 * z1) < 1e-3, "weight 2 doubled it (base + w * delta)")
    set_weight(1.0)
    check(np.allclose(_slot_positions(session), p1, atol=1e-6),
          "and weight 1 restored the original surface")

    undo.materialize_grid_blobs(session)
    lib.Multires_layerSetEnabled(session.multires_ptr, 0, 0)
    convert._rebind_multires_views(session, session.multires_active_level)
    z = float(np.abs(_slot_positions(session)[:, 2]).max())
    check(z < 1e-5, "disabling the layer removed its contribution")
    undo.materialize_grid_blobs(session)
    lib.Multires_layerSetEnabled(session.multires_ptr, 0, 1)
    convert._rebind_multires_views(session, session.multires_active_level)
    check(np.allclose(_slot_positions(session), p1, atol=1e-6),
          "and re-enabling restored it")
    convert.exit_(ob)


def run_real_ops():
    """Gate 7: the registered operators and the WindowManager mirror against
    a real headless mode entry."""
    ob = _object("layerrealops", 2, LEVEL)
    result = bpy.ops.object.custom_mode_toggle(mode_id="sculptcore.sculpt")
    check(result == {'FINISHED'} and ob.mode == 'CUSTOM',
          "custom_mode_toggle entered the sculpt mode headlessly")
    session = engine.sessions.get(ob.name)
    check(session is not None and bool(session.multires_ptr),
          "and the mode enter built a multires session")
    if session is None:
        return
    lib = engine.capi().lib
    wm = bpy.context.window_manager

    check(bpy.ops.sculptcore.layer_add.poll(),
          "layer_add polls true on the multires session")
    bpy.ops.sculptcore.layer_add()
    check(layers.layer_count(session) == 1 and layers.edit_target(session) == 0
          and len(wm.sculptcore_layers) == 1,
          "the real add created + targeted a layer and synced the mirror")
    bpy.ops.sculptcore.layer_add()
    check(layers.layer_count(session) == 2 and layers.edit_target(session) == 1
          and len(wm.sculptcore_layers) == 2,
          "a second add stacked and re-targeted")

    wm.sculptcore_layers[0].weight = 0.5
    check(abs(lib.Multires_layerWeight(session.multires_ptr, 0) - 0.5) < 1e-6,
          "the mirror weight setter reached the engine")
    check(abs(wm.sculptcore_layers[0].weight - 0.5) < 1e-6,
          "and the getter reads it back live")

    bpy.ops.sculptcore.layer_set_target(index=0)
    check(layers.edit_target(session) == 0, "set_target moved the target")
    bpy.ops.sculptcore.layer_set_target(index=0)
    check(layers.edit_target(session) == -1,
          "and clicking the target again cleared it (toggle)")
    bpy.ops.sculptcore.layer_set_target(index=1)
    check(layers.edit_target(session) == 1, "then took the other layer")

    bpy.ops.sculptcore.layer_toggle_enabled(index=0)
    check(not lib.Multires_layerEnabled(session.multires_ptr, 0),
          "toggle_enabled switched the layer off")
    bpy.ops.sculptcore.layer_toggle_enabled(index=0)
    check(bool(lib.Multires_layerEnabled(session.multires_ptr, 0)),
          "and back on")

    bpy.ops.sculptcore.layer_remove(index=0)
    check(layers.layer_count(session) == 1
          and len(wm.sculptcore_layers) == 1,
          "remove dropped the layer and resized the mirror")
    bpy.ops.sculptcore.layer_sync()
    check(len(wm.sculptcore_layers) == layers.layer_count(session),
          "and sync agrees with the engine")

    bpy.ops.object.custom_mode_toggle()
    check(ob.mode != 'CUSTOM' and ob.name not in engine.sessions,
          "toggling again exited the mode and freed the session")


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

    print("sculpt-layer routing gate (LD3)")
    run_routing()

    print("plain-mesh layer stroke gate")
    run_plain()

    print("multires layer stack + undo gates")
    run_multires()

    print("layer recomposite gate")
    run_recomposite()

    print("real-mode operator gate")
    run_real_ops()

    if FAILURES:
        print("\nFAILED ({:d}):".format(len(FAILURES)))
        for message in FAILURES:
            print("  - {:s}".format(message))
        raise SystemExit(1)
    print("\nall gates passed")


if __name__ == "__main__":
    main()
