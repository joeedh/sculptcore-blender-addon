# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless sweep of the multires acceleration-structure granularities.

Times, per (grid, level) scene and per tuning config, the three costs that
`multires_tuning.h` trades against each other:

* ``enter_ms``      — session enter: grid domain + GridTree + GridDrawSource
                      build and its first full fill;
* ``dab_ms``        — grids-native dab (GridTree query + brush region);
* ``refill_ms``     — ``sc_external_draw_update``, the CPU half of the draw
                      path (dirty draw-node refill after each dab).

The GPU half — draw-call count, the host's per-node batch sync — is not
visible headless; ``bench_multires_sc.py`` (headed) measures that and must
confirm anything decided here.

Configs are applied through the engine's sweep env vars (SC_MR_LEAF_TARGET /
SC_MR_DRAW_TRIS), which `multires_tuning.cc` re-reads on every build, so one
process covers a whole sweep. Each config enters from the same pristine base
mesh: the teardown frees the session WITHOUT flushing, so no config inherits
the previous one's displacement.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \\
        --python claudeMemory/scripts/bench_multires_tuning.py -- \\
        --out results.json --grid 64 --level 4 \\
        --configs "auto,leaf=512,leaf=2048,tris=8192"
"""

import ctypes
import json
import os
import statistics
import sys
import time

import bpy

ARGS = None
RESULT = {"scenes": []}


def log(msg):
    print("[tune] {}".format(msg), flush=True)


def parse_args():
    import argparse

    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="JSON result path (a FILE, not a dir)")
    p.add_argument("--grid", type=int, default=64, help="Base cage grid resolution (verts/side)")
    p.add_argument("--level", type=int, default=4, help="Multires levels")
    p.add_argument("--configs", default="auto",
                   help="Comma-separated configs: 'auto', 'fixed' (pre-autotune "
                        "constants), 'leaf=N', 'tris=N', or 'leaf=N;tris=M'")
    p.add_argument("--dabs", type=int, default=24, help="Timed dabs per config")
    p.add_argument("--radius", type=float, default=0.15, help="Dab radius (object space)")
    p.add_argument("--repeats", type=int, default=1, help="Passes over the config list")
    return p.parse_args(argv)


def parse_config(spec):
    """'leaf=1024;tris=8192' -> {'label': ..., 'env': {...}}."""
    env = {}
    if spec == "fixed":
        # The pre-autotune constants, as the A/B baseline.
        env = {"SC_MR_AUTOTUNE": "0"}
    elif spec != "auto":
        for part in spec.split(";"):
            key, _, val = part.partition("=")
            key = key.strip()
            if key == "leaf":
                env["SC_MR_LEAF_TARGET"] = val.strip()
            elif key == "tris":
                env["SC_MR_DRAW_TRIS"] = val.strip()
            elif key == "slotleaf":
                env["SC_MR_SLOT_LEAF"] = val.strip()
            else:
                raise SystemExit("unknown config key {!r} in {!r}".format(key, spec))
    return {"label": spec, "env": env}


SWEEP_VARS = ("SC_MR_AUTOTUNE", "SC_MR_LEAF_TARGET", "SC_MR_DRAW_TRIS",
              "SC_MR_SLOT_LEAF", "SC_MR_SLOT_DEPTH", "SC_MR_SLOT_GPU_TRIS")


def apply_env(env):
    """Set exactly `env`; clear every other sweep var (os.environ writes reach
    the engine's getenv through putenv)."""
    for name in SWEEP_VARS:
        if name in env:
            os.environ[name] = str(env[name])
        else:
            os.environ.pop(name, None)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def build_object(grid, level):
    """A `grid`x`grid` plane with `level` multires subdivisions — the same
    scene bench_multires_sc.py builds, minus the headed bits."""
    if bpy.context.object:
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    group = bpy.data.node_groups.new("Test", 'GeometryNodeTree')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    out_node = group.nodes.new('NodeGroupOutput')
    grid_node = group.nodes.new('GeometryNodeMeshGrid')
    grid_node.inputs["Size X"].default_value = 2.0
    grid_node.inputs["Size Y"].default_value = 2.0
    grid_node.inputs["Vertices X"].default_value = grid
    grid_node.inputs["Vertices Y"].default_value = grid
    group.links.new(grid_node.outputs["Mesh"], out_node.inputs[0])

    bpy.ops.mesh.primitive_plane_add(size=2, align='WORLD', location=(0, 0, 0))
    ob = bpy.context.object
    md = ob.modifiers.new("Test", 'NODES')
    md.node_group = group
    bpy.ops.object.modifier_apply(modifier="Test")
    base_faces = len(ob.data.polygons)

    mmd = ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(level):
        bpy.ops.object.multires_subdivide(modifier=mmd.name, mode='CATMULL_CLARK')
    return ob, base_faces


# ---------------------------------------------------------------------------
# One config
# ---------------------------------------------------------------------------


def tuning_stats(lib, mr_ptr, level):
    buf = (ctypes.c_int * 8)()
    lib.Multires_tuningStats(ctypes.c_void_p(mr_ptr), level, buf, 8)
    keys = ("leaf_target", "leaves", "draw_tri_target", "draw_nodes",
            "verts", "grids", "grid_side", "slot_leaf_limit")
    return dict(zip(keys, list(buf)))


def dab_centers(count, radius):
    """A stroke that walks the plane, so successive dabs hit fresh leaves."""
    span = 1.6
    out = []
    for i in range(count):
        t = (i + 0.5) / count
        # The cage is the z=0 plane; a dab centered off the surface misses.
        out.append((-span / 2.0 + span * t, 0.25 * (1.0 if i % 2 else -1.0), 0.0))
    return out


def run_config(ob, level, config, lib):
    from sculptcore_addon import convert, engine, stroke

    apply_env(config["env"])

    t0 = time.perf_counter()
    session = convert.enter(ob)
    enter_ms = (time.perf_counter() - t0) * 1000.0

    row = dict(config)
    row["enter_ms"] = enter_ms
    try:
        mgr = engine.manager()
        kernel = int(mgr.get("sculptcore::brush::SculptBrushes").items['DRAW'])
        row["stats"] = tuning_stats(lib, session.multires_ptr,
                                    session.multires_active_level)

        brush = stroke._ensure_brush(session)
        brush.radius = ARGS.radius
        brush.strength = 0.1
        brush.writeProps()

        dab_ms, refill_ms, moved = [], [], 0
        stroke.stroke_begin(session, grids_kernel=kernel)
        if not session.last_stroke_grids:
            raise RuntimeError("stroke did not dispatch grids-native")
        for center in dab_centers(ARGS.dabs, ARGS.radius):
            # loadProps writes strength*pressure back into the Brush, so the
            # per-dab state must be re-set or the stroke fades out.
            brush.radius = ARGS.radius
            brush.strength = 0.1
            brush.writeProps()
            t0 = time.perf_counter()
            moved += stroke.apply_dab(session, kernel, center, (0.0, 0.0, 1.0), ARGS.radius)
            dab_ms.append((time.perf_counter() - t0) * 1000.0)
            t0 = time.perf_counter()
            lib.sc_external_draw_update(ctypes.c_uint(session.draw_key))
            refill_ms.append((time.perf_counter() - t0) * 1000.0)
        stroke.stroke_end(session)

        row["moved_verts"] = moved
        row["dab_ms"] = summarize(dab_ms)
        row["refill_ms"] = summarize(refill_ms)
        row["stroke_ms"] = sum(dab_ms) + sum(refill_ms)
    finally:
        # Teardown WITHOUT convert.flush: the base mesh stays pristine, so the
        # next config enters from identical geometry.
        if session.draw_key:
            lib.sc_external_draw_unregister(ctypes.c_uint(session.draw_key))
        engine.sessions.pop(ob.name, None)
        session.free()
    return row


def summarize(samples):
    if not samples:
        return {}
    s = sorted(samples)
    return {"median": statistics.median(s), "mean": statistics.fmean(s),
            "min": s[0], "max": s[-1], "n": len(s)}


def main():
    global ARGS
    ARGS = parse_args()

    from sculptcore_addon import engine, handlers

    # A depsgraph handler mid-bench would re-enter the addon's own sync path.
    if handlers._on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

    lib = engine.capi().lib
    lib.Multires_tuningStats.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    lib.Multires_tuningStats.restype = ctypes.c_int

    configs = [parse_config(s.strip()) for s in ARGS.configs.split(",") if s.strip()]

    log("building grid={} level={}".format(ARGS.grid, ARGS.level))
    t0 = time.perf_counter()
    ob, base_faces = build_object(ARGS.grid, ARGS.level)
    log("scene built in {:.1f}s ({} base faces)".format(time.perf_counter() - t0, base_faces))

    scene = {"grid": ARGS.grid, "level": ARGS.level, "base_faces": base_faces,
             "dabs": ARGS.dabs, "radius": ARGS.radius, "runs": []}
    for rep in range(ARGS.repeats):
        for config in configs:
            row = run_config(ob, ARGS.level, config, lib)
            row["repeat"] = rep
            scene["runs"].append(row)
            log("{:<24} enter {:7.1f} ms  dab {:6.2f} ms  refill {:6.2f} ms  "
                "leaves {:6d}  nodes {:6d}  moved {:8d}".format(
                    row["label"], row["enter_ms"], row["dab_ms"]["median"],
                    row["refill_ms"]["median"], row["stats"]["leaves"],
                    row["stats"]["draw_nodes"], row["moved_verts"]))
    RESULT["scenes"].append(scene)

    with open(ARGS.out, "w") as f:
        json.dump(RESULT, f, indent=1)
    log("wrote {}".format(ARGS.out))


main()
