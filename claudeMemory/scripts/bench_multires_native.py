# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Headed performance benchmark for Blender's NATIVE sculpt mode on multires.

This measures *frame time*, not just operator time, so it must run with a real
window and a live event loop -- the suspected regression is in the draw path.
Run it as::

    blender.exe --factory-startup --no-window-focus -p 0 0 1280 800 \
        --python-exit-code 1 --python bench_multires_native.py -- \
        --out results.json [--grid 64] [--level 4] [--disable-addon]

Nothing here touches SculptCore; ``--disable-addon`` exists precisely to take
the always-enabled add-on out of the picture so the fork's C++ changes can be
measured on their own.

Method
------
Scene setup runs synchronously while Blender is still starting up. The timed
work cannot: a frame is only produced when the event loop gets control back.
So the measurement is a state machine driven by ``bpy.app.timers``, with two
draw handlers on ``SpaceView3D`` recording timestamps:

* ``PRE_VIEW``  -> start of the 3D viewport draw
* ``POST_PIXEL`` -> end of it

giving three numbers per phase:

* ``view_ms``  POST_PIXEL - PRE_VIEW, the viewport draw alone.
* ``frame_ms`` POST_PIXEL to the next POST_PIXEL. In the idle phase the draw
  handler re-tags its own region, so frames run back to back and this delta
  includes buffer swap and therefore GPU time -- the honest "what does the
  viewport feel like" number.
* ``stroke_ms`` the ``sculpt.brush_stroke`` operator itself (sculpt phase only).

The scene construction, the brush activation and the stroke shape are lifted
from Blender's own ``tests/performance/tests/sculpt.py`` so the numbers stay
comparable to the official benchmark.

Known limits -- read before trusting a comparison
-------------------------------------------------
1. **Both builds must carry the same optimization flags.** Check the generated
   ``build.ninja`` for ``/O2 /Ob2 /DNDEBUG``, not just ``CMAKE_BUILD_TYPE`` and
   the ``WITH_*`` options: Blender only *appends* to
   ``CMAKE_CXX_FLAGS_RELEASE``, so a build directory whose cache entry for it is
   empty compiles unoptimized with asserts live and looks 2-5x slower at
   everything. That difference dwarfs anything being measured here.

2. **``idle_frame_ms`` is vsync-capped** (~16.7 ms on a 60 Hz display), so it
   cannot resolve any draw that already fits in a frame. ``idle_view_ms`` and
   ``sculpt_view_ms`` are CPU-side and uncapped -- use those to compare draw
   cost, and treat ``idle_frame_ms`` only as "did we fall below refresh".

3. **``sculpt.optimize`` discards unflushed multires displacement**, so the
   surface has to be read *before* the bvh phase, which is why the phase order
   below is sculpt -> read -> bvh rather than sculpt -> bvh -> read. Verified on
   stock main: one stroke at strength 0.1 leaves ``peak_z`` 0.00556, and five
   ``sculpt.optimize`` calls take it back to exactly 0, while the same sequence
   on ``--mode mesh`` keeps its displacement. Multires strokes land in the
   subdiv-CCG grids and are only written back to MDisps at sync points; freeing
   and rebuilding the PBVH without a flush loses them. Reading after the bvh
   phase made every multires run report ``deformed=false`` and looked like the
   strokes were doing nothing.

4. Displacement is only visible in **object mode**: with multires active, sculpt
   mode evaluates to CCG grids rather than a Mesh, so the evaluated object's
   data is just the base cage. The base mesh stays flat by design -- the edit
   lives in the grids, not in base vertex coordinates.
"""

import json
import sys
import time
import traceback

import bpy
from mathutils import Vector

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


def parse_args():
    import argparse

    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Path to write the JSON result to")
    parser.add_argument("--label", default="", help="Free-form name for this configuration")
    parser.add_argument("--grid", type=int, default=64,
                        help="Vertices per side of the base grid (base quads = (grid-1)^2)")
    parser.add_argument("--level", type=int, default=4, help="Multires subdivision depth")
    parser.add_argument("--mode", choices=("multires", "mesh"), default="multires",
                        help="'mesh' is the control: the same vertex count sculpted directly, with no "
                             "multires modifier. If it regresses too, the cause is build-wide rather "
                             "than anything to do with multires.")
    parser.add_argument("--brush", default="Draw", help="Essentials brush asset name")
    parser.add_argument("--warmup", type=int, default=20, help="Frames to discard before each phase")
    parser.add_argument("--idle-frames", type=int, default=90, help="Frames to time with no edits")
    parser.add_argument("--strokes", type=int, default=25, help="Sculpt+redraw iterations to time")
    parser.add_argument("--stroke-steps", type=int, default=20, help="Dabs per timed stroke")
    parser.add_argument("--disable-addon", action="store_true",
                        help="Unregister the SculptCore add-on before measuring")
    parser.add_argument("--undo-steps", type=int, default=8,
                        help="Cap the undo stack. Sculpt strokes push undo nodes whether or not the "
                             "script asks for them, and at this face count the factory default of 32 "
                             "can exhaust memory mid-run. Pinning it makes both builds identical.")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="Abort and write partial results after this many seconds of measuring")
    return parser.parse_args(argv)


ARGS = parse_args()
RESULT = {
    "label": ARGS.label,
    "mode": ARGS.mode,
    "grid": ARGS.grid,
    "level": ARGS.level,
    "blender_version": ".".join(str(v) for v in bpy.app.version),
    "build_hash": bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash,
    "build_branch": (bpy.app.build_branch.decode()
                     if isinstance(bpy.app.build_branch, bytes) else bpy.app.build_branch),
    "binary": bpy.app.binary_path,
}

# ---------------------------------------------------------------------------
# Add-on control
# ---------------------------------------------------------------------------


def addon_state():
    """A cheap fingerprint of whether SculptCore is registered right now."""
    # ObjectModeType is a fork-only RNA type; on stock main it is simply absent.
    mode_type = getattr(bpy.types, "ObjectModeType", None)
    modes = ({getattr(t, "bl_idname", "") for t in mode_type.__subclasses__()}
             if mode_type is not None else set())
    return {
        "module_imported": "sculptcore_addon" in sys.modules,
        "custom_mode_api": mode_type is not None,
        "brush_prop": bool(bpy.types.Brush.bl_rna.properties.get("sculptcore")),
        "mode_registered": "sculptcore.sculpt" in modes,
        "depsgraph_handlers": len(bpy.app.handlers.depsgraph_update_post),
    }


def disable_addon():
    import addon_utils
    RESULT["addon_before"] = addon_state()
    try:
        addon_utils.disable("sculptcore_addon", default_set=False)
    except Exception as ex:  # noqa: BLE001 - reported, not swallowed
        RESULT["addon_disable_error"] = "{}: {}".format(type(ex).__name__, ex)
    RESULT["addon_after"] = addon_state()


# ---------------------------------------------------------------------------
# Scene -- follows tests/performance/tests/sculpt.py
# ---------------------------------------------------------------------------


def find_view3d():
    """The window/area/region of the first 3D viewport.

    Only these three are kept, never a whole ``context.copy()``: that snapshot is
    taken before the test object exists, and its stale ``object``/``mode`` keys
    make ``sculpt.brush_stroke`` fail its poll. Overriding just the space lets
    everything else resolve against the live context.
    """
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                return {"window": window, "area": area, "region": region}
    raise RuntimeError("no VIEW_3D/WINDOW region -- is this a headed run?")


def build_object(grid, level, mode):
    """A grid plane, either multires-subdivided to `level` or already dense.

    Both variants land on the same sculpt-level vertex count so the two are
    directly comparable.
    """
    if mode == "mesh":
        # (grid-1)^2 * 4^level quads => a side of (grid-1) * 2^level + 1 verts.
        grid = (grid - 1) * (2 ** level) + 1
        level = 0
    if bpy.context.object:
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.outliner.orphans_purge()

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

    subdivide_ms = []
    if level:
        mmd = ob.modifiers.new("Multires", 'MULTIRES')
        t0 = time.perf_counter()
        for _ in range(level):
            t = time.perf_counter()
            bpy.ops.object.multires_subdivide(modifier=mmd.name, mode='CATMULL_CLARK')
            subdivide_ms.append((time.perf_counter() - t) * 1000.0)
        RESULT["subdivide_ms_total"] = (time.perf_counter() - t0) * 1000.0
        RESULT["multires_levels"] = mmd.total_levels
        RESULT["multires_sculpt_level"] = mmd.sculpt_levels

    # Measured here, while still in object mode: with multires active, sculpt
    # mode evaluates to CCG grids rather than a Mesh, so the evaluated object's
    # data is only the base cage and would report the wrong vertex count.
    RESULT["surface_before"] = surface_state()

    bpy.ops.object.mode_set(mode='SCULPT')

    RESULT["base_faces"] = base_faces
    RESULT["sculpt_faces"] = base_faces * (4 ** level)
    RESULT["subdivide_ms_per_level"] = subdivide_ms
    return ob


def surface_state():
    """Evaluated vertex count and peak |Z| deflection.

    The test object starts as a flat Z=0 plane and the Draw brush pushes along
    the normal, so a non-zero peak proves the strokes actually landed on the
    mesh instead of sweeping past it -- a miss would otherwise just look like a
    very fast build. Reading the evaluated object's ``data`` is the subdivided
    multires mesh with no copy, so this also measures the real sculpt-level
    vertex count rather than trusting base_faces * 4^level.
    """
    import numpy as np

    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.context.object.evaluated_get(depsgraph).data
    count = len(mesh.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    return {"verts": count, "peak_z": float(np.abs(coords.reshape(-1, 3)[:, 2]).max())}


def prepare_brush(name):
    bpy.ops.brush.asset_activate(
        asset_library_type='ESSENTIALS',
        relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/' + name)
    # Keep the deformation small so repeated strokes do not reshape the test object.
    bpy.context.tool_settings.sculpt.brush.strength = 0.1


def generate_stroke(ctx, num_steps, flip):
    template = {
        "name": "stroke",
        "mouse": (0.0, 0.0),
        "mouse_event": (0, 0),
        "is_start": True,
        "location": (0, 0, 0),
        "pressure": 1.0,
        "time": 1.0,
        "size": 1.0,
        "x_tilt": 0,
        "y_tilt": 0,
    }
    w, h = ctx["area"].width, ctx["area"].height
    # Sweep the viewport diagonal, alternating direction so the surface does not
    # drift in one direction over the run.
    start, end = Vector((w, h)), Vector((0, 0))
    if flip:
        start, end = end, start
    delta = (end - start) / (num_steps - 1)

    stroke = []
    for i in range(num_steps):
        step = template.copy()
        step["mouse_event"] = start + delta * i
        stroke.append(step)
    return stroke


# ---------------------------------------------------------------------------
# Frame timing
# ---------------------------------------------------------------------------

class Timing:
    def __init__(self):
        self.pre = 0.0
        self.post = 0.0
        self.prev_post = 0.0
        self.frames = 0
        self.view_ms = []
        self.frame_ms = []
        self.collect = False

    def on_pre(self):
        self.pre = time.perf_counter()

    def on_post(self):
        now = time.perf_counter()
        if self.collect:
            self.view_ms.append((now - self.pre) * 1000.0)
            if self.prev_post:
                self.frame_ms.append((now - self.prev_post) * 1000.0)
        self.prev_post = now
        self.post = now
        self.frames += 1

    def reset(self):
        self.view_ms = []
        self.frame_ms = []
        self.prev_post = 0.0


TIMING = Timing()


def stats(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    n = len(ordered)
    return {
        "n": n,
        "mean": sum(ordered) / n,
        "median": ordered[n // 2],
        "min": ordered[0],
        "p90": ordered[min(n - 1, int(n * 0.9))],
        "max": ordered[-1],
    }


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

# Redraws are driven from the timer, never from the draw handler: a tag_redraw()
# issued *during* a draw is cleared when that draw completes, so a self-tagging
# handler stops after one frame. Blender's main loop fires due timers once per
# pass and then draws whatever is tagged, so returning 0.0 from the timer gives
# one back-to-back frame per pass -- a saturated redraw loop whose frame-to-frame
# delta includes buffer swap, i.e. GPU time.
YIELD = 0.0


def log(msg):
    print("[bench] {}".format(msg), flush=True)


class Bench:
    def __init__(self, ctx):
        self.ctx = ctx
        self.phase = "warmup_idle"
        self.count = 0
        self.stroke_ms = []
        self.pending_frame = False
        self.redraw_ms = []
        self.t_tag = 0.0
        self.flip = False
        self.t_start = time.perf_counter()
        self.t_phase = self.t_start
        self.last_log = 0.0

    def tag(self):
        self.ctx["region"].tag_redraw()

    def enter(self, phase):
        log("{} done in {:.1f}s -> {}".format(self.phase, time.perf_counter() - self.t_phase, phase))
        self.phase = phase
        self.t_phase = time.perf_counter()

    def step(self):
        try:
            now = time.perf_counter()
            if now - self.last_log > 5.0:
                self.last_log = now
                log("phase={} frames={} strokes={} idle_samples={} t={:.0f}s".format(
                    self.phase, TIMING.frames, self.count, len(TIMING.frame_ms), now - self.t_start))
            if now - self.t_start > ARGS.timeout:
                RESULT["error"] = "timed out in phase '{}' after {:.0f}s".format(
                    self.phase, now - self.t_start)
                log(RESULT["error"])
                finish()
                return None
            return self._step()
        except Exception:
            RESULT["error"] = traceback.format_exc()
            log(RESULT["error"])
            finish()
            return None

    def _step(self):
        if self.phase == "warmup_idle":
            self.tag()
            if TIMING.frames >= ARGS.warmup:
                TIMING.reset()
                TIMING.collect = True
                self.enter("idle")
            return YIELD

        if self.phase == "idle":
            self.tag()
            if len(TIMING.frame_ms) >= ARGS.idle_frames:
                TIMING.collect = False
                RESULT["idle_view_ms"] = stats(TIMING.view_ms)
                RESULT["idle_frame_ms"] = stats(TIMING.frame_ms)
                TIMING.reset()
                self.count = 0
                self.enter("sculpt")
            return YIELD

        if self.phase == "sculpt":
            if self.pending_frame:
                # The redraw asked for after the last stroke has landed.
                if TIMING.post > self.t_tag:
                    self.redraw_ms.append((TIMING.post - self.t_tag) * 1000.0)
                    self.pending_frame = False
                else:
                    self.tag()
                    return YIELD

            if self.count >= ARGS.strokes:
                RESULT["stroke_ms"] = stats(self.stroke_ms)
                RESULT["stroke_redraw_ms"] = stats(self.redraw_ms)
                RESULT["sculpt_view_ms"] = stats(TIMING.view_ms)
                RESULT["undo_memory"] = bpy.app.memory_usage_undo()
                TIMING.collect = False
                # Read the surface here, NOT after the bvh phase: sculpt.optimize
                # throws away multires displacement that has not been flushed
                # back to MDisps, which reads as "the strokes did nothing".
                # Object mode is the only place the grids evaluate to a Mesh.
                bpy.ops.object.mode_set(mode='OBJECT')
                RESULT["surface_after"] = surface_state()
                log("after: verts={} peak_z={:.5f}".format(
                    RESULT["surface_after"]["verts"], RESULT["surface_after"]["peak_z"]))
                bpy.ops.object.mode_set(mode='SCULPT')
                self.enter("bvh")
                return YIELD

            stroke = generate_stroke(self.ctx, ARGS.stroke_steps, self.flip)
            self.flip = not self.flip
            TIMING.collect = True
            with bpy.context.temp_override(**self.ctx):
                t = time.perf_counter()
                bpy.ops.sculpt.brush_stroke(stroke=stroke, override_location=True)
                self.stroke_ms.append((time.perf_counter() - t) * 1000.0)
            self.count += 1
            # Time the redraw the edit just dirtied: PBVH draw-buffer rebuild
            # happens here, not inside the operator.
            self.t_tag = time.perf_counter()
            self.pending_frame = True
            self.tag()
            return YIELD

        if self.phase == "bvh":
            measurements = []
            with bpy.context.temp_override(**self.ctx):
                for _ in range(5):
                    t = time.perf_counter()
                    bpy.ops.sculpt.optimize()
                    measurements.append((time.perf_counter() - t) * 1000.0)
            RESULT["bvh_rebuild_ms"] = stats(measurements)
            bpy.ops.object.mode_set(mode='OBJECT')
            self.enter("done")
            return YIELD

        finish()
        return None


def process_memory():
    """Peak working set. Blender exposes no general memory stat, only undo's."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return {"peak_working_set": counters.PeakWorkingSetSize,
                    "working_set": counters.WorkingSetSize}
        return {"error": "GetProcessMemoryInfo failed: {}".format(ctypes.GetLastError())}
    except Exception as ex:  # noqa: BLE001 - a missing memory stat must not fail a run
        return {"error": "{}: {}".format(type(ex).__name__, ex)}


def finish():
    RESULT["memory"] = process_memory()
    with open(ARGS.out, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    print("BENCH WROTE {}".format(ARGS.out), flush=True)

    def quit():
        bpy.ops.wm.quit_blender()
        return None  # a timer callback must return a float or None, never a set

    bpy.app.timers.register(quit, first_interval=0.1)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main():
    if ARGS.disable_addon:
        disable_addon()
    else:
        RESULT["addon_before"] = addon_state()

    bpy.context.preferences.edit.undo_steps = ARGS.undo_steps
    RESULT["undo_steps"] = bpy.context.preferences.edit.undo_steps

    ctx = find_view3d()
    log("building mode={} grid={} level={}".format(ARGS.mode, ARGS.grid, ARGS.level))
    t = time.perf_counter()
    build_object(ARGS.grid, ARGS.level, ARGS.mode)
    log("built {} sculpt faces ({} evaluated verts) in {:.1f}s".format(
        RESULT["sculpt_faces"], RESULT["surface_before"]["verts"], time.perf_counter() - t))
    prepare_brush(ARGS.brush)

    with bpy.context.temp_override(**ctx):
        bpy.ops.view3d.view_all()
        # An undo stack is not created by default for a scripted session.
        bpy.ops.ed.undo_push()

    bpy.types.SpaceView3D.draw_handler_add(TIMING.on_pre, (), 'WINDOW', 'PRE_VIEW')
    bpy.types.SpaceView3D.draw_handler_add(TIMING.on_post, (), 'WINDOW', 'POST_PIXEL')

    bench = Bench(ctx)
    bpy.app.timers.register(bench.step, first_interval=0.5)


try:
    main()
except Exception:
    RESULT["error"] = traceback.format_exc()
    print(RESULT["error"])
    finish()
