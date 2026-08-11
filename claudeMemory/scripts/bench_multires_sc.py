# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headed A/B benchmark: SculptCore multires strokes vs native multires strokes.

Both engines are driven by the *same* synthesized event stream --
``Window.event_simulate`` press / move.../release into the 3D viewport -- so the
drive mechanism cannot bias the comparison. Native sculpt's ``sculpt.brush_stroke``
and ``sculptcore.brush_stroke`` are both modal LMB operators, so one event
sequence exercises whichever mode the object happens to be in.

Run it as::

    blender.exe --factory-startup --enable-event-simulate --no-window-focus \
        -p 0 0 1280 800 --python-exit-code 1 --python bench_multires_sc.py -- \
        --out results.json --engine sculptcore [--grid 64] [--level 4]

``--enable-event-simulate`` is mandatory; without it ``event_simulate`` raises.

The stroke model
----------------
Events are generated against the *wall clock*, not the frame clock: a stroke is
``--stroke-secs`` of samples at ``--event-hz`` along the viewport diagonal, and
a timer that runs once per main-loop pass pushes every sample whose timestamp
has come due. When a frame stalls, no pass runs, samples accrue, and the next
pass pushes the backlog at once -- exactly how a real device queue behaves.
All but the newest sample of a backlog are pushed as ``INBETWEEN_MOUSEMOVE``,
mirroring ``wm_event_add_mousemove``'s demotion of stale queued moves (which
``event_simulate`` bypasses -- it appends via ``WM_event_add``). Consequences
that are *supposed* to show up here, because they show up live: a slow frame
costs input samples demoted to inbetweens; native samples inbetweens for path
fidelity while the SculptCore modal currently ignores them; every presented
frame during a stroke pays the mid-stroke flush and viewport draw.

This replaced a burst-mode bench (whole stroke pushed in one pass, consumed in
~one frame) whose ``cycle_ms``/``sculpt_phase_ms`` were honest *throughput*
numbers but under-sampled per-event and per-frame costs by 10-100x against
interactive use, and hid exactly the gap users feel.

Metrics
-------
``stroke_frame_ms`` -- interval between presented frames while a stroke is in
flight (pooled over all strokes; median/p90/max). This is the perceptual
smoothness number and the headline A/B metric; both engines report it
identically. The first frame of each stroke is excluded (its interval spans
the inter-stroke gap).

``latency_ms`` -- at each presented stroke frame, wall time since the newest
move event pushed before that frame's handlers ran: input-to-present lag,
including queue wait.

``stroke_wall_ms`` -- press push to the first presented frame after release,
per stroke. ``frames_per_stroke`` and the ``events`` counters (moves,
inbetweens pushed) say how the stroke was delivered and consumed.

``sculpt_phase_ms`` / ``sculpt_frames`` -- wall time and frame count for the
whole sculpt phase, gaps included (kept for cross-run continuity; the gap makes
it a weaker A/B number than stroke_wall_ms).

``stroke_ms`` is the operator's own busy time, summed over invoke + every modal
call, per stroke. SculptCore's is measured by wrapping the Python operator;
native sculpt's modal is C++ and cannot be wrapped, so for ``--engine native``
this key is absent and the frame/latency/wall metrics are the comparison.

See bench_multires_native.py for the event-loop traps this inherits (timer state
machine, tag from the timer not the draw handler, no whole ``context.copy()``,
multires evaluates to CCG grids so vertex counts are read in object mode).
"""

import importlib
import json
import os
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
    parser.add_argument("--engine", choices=("native", "sculptcore"), default="native")
    parser.add_argument("--grid", type=int, default=64,
                        help="Vertices per side of the base grid (base quads = (grid-1)^2)")
    parser.add_argument("--level", type=int, default=4, help="Multires subdivision depth")
    parser.add_argument("--mode", choices=("multires", "mesh"), default="multires",
                        help="'mesh' is the control: the same vertex count with no multires stack")
    parser.add_argument("--brush", default="Clay",
                        help="Essentials brush asset name. Clay is the default because it is the "
                             "user-reported gap scenario: its default autosmooth routes the "
                             "SculptCore stroke through the program (mesh-materialized) path")
    parser.add_argument("--brush-size", type=int, default=50, help="Brush radius in pixels")
    parser.add_argument("--warmup", type=int, default=20, help="Frames to discard before each phase")
    parser.add_argument("--idle-frames", type=int, default=60, help="Frames to time with no edits")
    parser.add_argument("--strokes", type=int, default=12, help="Timed strokes")
    parser.add_argument("--event-hz", type=float, default=200.0,
                        help="Input sample rate the synthesized device generates at (tablets and "
                             "gaming mice sit at 125-266 Hz)")
    parser.add_argument("--stroke-secs", type=float, default=1.2,
                        help="Wall-clock duration of each stroke; speed follows from the fixed "
                             "viewport-diagonal path length")
    parser.add_argument("--gap-secs", type=float, default=0.3,
                        help="Pause between strokes (stroke-end work settles; a real user's lift)")
    parser.add_argument("--undo-steps", type=int, default=8, help="Cap the undo stack")
    parser.add_argument("--cpp-driver", action=argparse.BooleanOptionalAction, default=None,
                        help="Force the sculptcore_cpp_dab_loop scene toggle on (--cpp-driver) or "
                             "off (--no-cpp-driver); omitted = as shipped (default ON since "
                             "2026-08-10 sign-off). SculptCore only")
    parser.add_argument("--profile", action="store_true",
                        help="cProfile the sculpt phase (SculptCore only; Python-side cost)")
    parser.add_argument("--engine-trace", action="store_true",
                        help="Time every engine call by name (SculptCore only). Wraps the ctypes "
                             "marshaller's single choke point, so the totals cover marshalling "
                             "plus the C++ work cProfile cannot see into.")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="Abort and write partial results after this many seconds")
    parser.add_argument("--gpu-trace", type=int, default=0, metavar="N",
                        help="Capture N frames with RenderDoc during the sculpt phase. Requires "
                             "launching under 'renderdoccmd capture'; fails loudly if not hooked")
    parser.add_argument("--trace-after-strokes", type=int, default=3,
                        help="Warm strokes to run before the capture is armed, so first-use GPU "
                             "buffer and shader creation is not what gets traced")
    parser.add_argument("--capture-dir", default="",
                        help="Directory to write .rdc captures into (default: beside --out)")
    parser.add_argument("--wall-trace", action="store_true",
                        help="Record a timestamped span timeline (operator calls, draws, depsgraph "
                             "evaluations, bench steps) for the sculpt phase, to attribute wall "
                             "time that sits outside the operator. Works for both engines; the "
                             "per-operator-call spans are SculptCore-only (native's modal is C++)")
    return parser.parse_args(argv)


ARGS = parse_args()
RESULT = {
    "label": ARGS.label,
    "engine": ARGS.engine,
    "mode": ARGS.mode,
    "grid": ARGS.grid,
    "level": ARGS.level,
    "event_hz": ARGS.event_hz,
    "stroke_secs": ARGS.stroke_secs,
    "gap_secs": ARGS.gap_secs,
    "blender_version": ".".join(str(v) for v in bpy.app.version),
    "binary": bpy.app.binary_path,
    "cpp_driver": ARGS.cpp_driver,
}


def log(msg):
    print("[bench] {}".format(msg), flush=True)


# ---------------------------------------------------------------------------
# Scene -- follows tests/performance/tests/sculpt.py
# ---------------------------------------------------------------------------


def find_view3d():
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                return {"window": window, "area": area, "region": region}
    raise RuntimeError("no VIEW_3D/WINDOW region -- is this a headed run?")


def build_object(grid, level, mode):
    if mode == "mesh":
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

    if level:
        mmd = ob.modifiers.new("Multires", 'MULTIRES')
        t0 = time.perf_counter()
        for _ in range(level):
            bpy.ops.object.multires_subdivide(modifier=mmd.name, mode='CATMULL_CLARK')
        RESULT["subdivide_ms_total"] = (time.perf_counter() - t0) * 1000.0
        RESULT["multires_levels"] = mmd.total_levels

    # Read while still in object mode: with multires active, sculpt evaluates to
    # CCG grids rather than a Mesh and the count would be the base cage's.
    RESULT["surface_before"] = surface_state()
    RESULT["base_faces"] = base_faces
    RESULT["sculpt_faces"] = base_faces * (4 ** level)
    return ob


def surface_state():
    import numpy as np

    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.context.object.evaluated_get(depsgraph).data
    count = len(mesh.vertices)
    coords = np.empty(count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    return {"verts": count, "peak_z": float(np.abs(coords.reshape(-1, 3)[:, 2]).max())}


def enter_mode(engine):
    if engine == "native":
        bpy.ops.object.mode_set(mode='SCULPT')
    else:
        if ARGS.cpp_driver is not None:
            bpy.context.scene.sculptcore_cpp_dab_loop = ARGS.cpp_driver
        RESULT["cpp_driver"] = bpy.context.scene.sculptcore_cpp_dab_loop
        bpy.ops.object.custom_mode_toggle(mode_id="sculptcore.sculpt")
        ob = bpy.context.active_object
        if ob.mode != 'CUSTOM' or ob.custom_mode != "sculptcore.sculpt":
            raise RuntimeError("failed to enter SculptCore mode (mode={!r})".format(ob.mode))


def leave_mode(engine):
    if engine == "native":
        bpy.ops.object.mode_set(mode='OBJECT')
    else:
        bpy.ops.object.custom_mode_toggle()


def prepare_brush(name, size):
    bpy.ops.brush.asset_activate(
        asset_library_type='ESSENTIALS',
        relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/' + name)
    brush = bpy.context.tool_settings.sculpt.brush
    if brush is None or brush.name != name:
        raise RuntimeError("asset_activate left {!r} active, wanted {!r}".format(
            None if brush is None else brush.name, name))
    # Small deformation so repeated strokes do not reshape the test object, and a
    # pinned size/spacing so both engines lay down the same number of dabs.
    # Everything else -- autosmooth above all -- keeps the asset's defaults: the
    # whole point of benching Clay is the pipeline its default autosmooth picks.
    brush.strength = 0.1
    brush.size = size
    brush.spacing = 10
    unified = bpy.context.tool_settings.sculpt.unified_paint_settings
    unified.use_unified_size = False
    unified.use_unified_strength = False
    RESULT["brush"] = {"name": name, "size": brush.size, "spacing": brush.spacing,
                       "strength": brush.strength,
                       "auto_smooth_factor": getattr(brush, "auto_smooth_factor", None)}


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
        self.latency_ms = []
        self.collect = False
        # Stamped by the bench at every move push; on_post reads it to turn a
        # presented frame into an input-to-present latency sample.
        self.last_push = 0.0

    def on_pre(self):
        self.pre = time.perf_counter()

    def on_post(self):
        now = time.perf_counter()
        if self.collect:
            self.view_ms.append((now - self.pre) * 1000.0)
            if self.prev_post:
                self.frame_ms.append((now - self.prev_post) * 1000.0)
            if self.last_push:
                self.latency_ms.append((now - self.last_push) * 1000.0)
        if WALL is not None:
            WALL.add("draw", self.pre, now)
        self.prev_post = now
        self.post = now
        self.frames += 1

    def reset(self):
        self.view_ms = []
        self.frame_ms = []
        self.latency_ms = []
        self.prev_post = 0.0
        self.last_push = 0.0


TIMING = Timing()


class WallTrace:
    """Raw span timeline for the sculpt phase.

    Each record is ``[kind, t_ms, dur_ms]`` with ``t_ms`` relative to the base
    stamped when the sculpt phase starts. Kinds:

    - ``push``       one or more due events entered the queue (dur 0)
    - ``step``       the bench timer callback ran (dur = its own body)
    - ``op:invoke`` / ``op:modal``  one operator call (SculptCore only)
    - ``draw``       PRE_VIEW -> POST_PIXEL of one 3D view redraw
    - ``dgeval``     depsgraph_update_pre -> _post bracket: the C-side
                     evaluation plus every post handler
    - ``dg``         the addon's own _on_depsgraph_update body

    The gaps between these spans are the unattributed wall time -- WM event
    dispatch, non-view3d drawing, buffer swap / vsync, and main-loop plumbing.
    """

    def __init__(self):
        self.records = []
        self.enabled = False
        self.base = 0.0
        self._dg_pre = 0.0
        self._orig_dg = None

    def add(self, kind, t_start, t_end):
        if self.enabled:
            self.records.append([kind, (t_start - self.base) * 1000.0,
                                 (t_end - t_start) * 1000.0])

    def start(self):
        self.base = time.perf_counter()
        self.enabled = True

    def install(self):
        bpy.app.handlers.depsgraph_update_pre.append(self._on_dg_pre)
        bpy.app.handlers.depsgraph_update_post.append(self._on_dg_post)
        try:
            from sculptcore_addon import handlers as sc_handlers
        except ImportError:
            return
        orig = sc_handlers._on_depsgraph_update
        trace = self

        # Swap the registered handler entry itself: the handler list holds a
        # direct reference, so rebinding the module attribute alone would not
        # reroute calls.
        def dg_wrapper(scene, depsgraph=None):
            t = time.perf_counter()
            try:
                return orig(scene, depsgraph)
            finally:
                trace.add("dg", t, time.perf_counter())

        handler_list = bpy.app.handlers.depsgraph_update_post
        if orig in handler_list:
            handler_list[handler_list.index(orig)] = dg_wrapper
            self._orig_dg = (handler_list, dg_wrapper, orig)

    def _on_dg_pre(self, scene, depsgraph=None):
        self._dg_pre = time.perf_counter()

    def _on_dg_post(self, scene, depsgraph=None):
        self.add("dgeval", self._dg_pre, time.perf_counter())

    def restore(self):
        for handler_list, fn in ((bpy.app.handlers.depsgraph_update_pre, self._on_dg_pre),
                                 (bpy.app.handlers.depsgraph_update_post, self._on_dg_post)):
            if fn in handler_list:
                handler_list.remove(fn)
        if self._orig_dg is not None:
            handler_list, wrapper, orig = self._orig_dg
            if wrapper in handler_list:
                handler_list[handler_list.index(wrapper)] = orig


WALL = WallTrace() if ARGS.wall_trace else None


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
# SculptCore operator instrumentation
# ---------------------------------------------------------------------------
#
# The Python operator's methods are looked up on the class at call time, so
# wrapping them here needs no addon change. Native sculpt's modal is C++ and has
# no equivalent -- which is why the frame/latency metrics, not stroke_ms, are
# the A/B numbers.

class OpProbe:
    def __init__(self):
        self.op_ms = 0.0
        self.dabs = 0
        self.running = False
        self.finished = 0
        self._orig = {}

    def install(self):
        cls = bpy.types.SCULPTCORE_OT_brush_stroke
        probe = self

        # The wrapper's signature must be exactly (self, context, event):
        # bpy_class_call sizes the argument tuple from the callback's
        # co_argcount, and default parameters count toward it -- an extra
        # `_orig=orig` default leaves NULL slots in that tuple and segfaults
        # CPython. Capture through a closure factory instead.
        def make_wrapper(orig, is_invoke):
            kind = "op:invoke" if is_invoke else "op:modal"

            def wrapper(self, context, event):
                t = time.perf_counter()
                try:
                    return orig(self, context, event)
                finally:
                    now = time.perf_counter()
                    probe.op_ms += (now - t) * 1000.0
                    if WALL is not None:
                        WALL.add(kind, t, now)
                    if is_invoke:
                        probe.running = True
                    dabs = getattr(self, "_dab_count", None)
                    if dabs is not None:
                        probe.dabs = dabs
            return wrapper

        for name in ("invoke", "modal"):
            orig = getattr(cls, name)
            probe._orig[name] = orig
            setattr(cls, name, make_wrapper(orig, name == "invoke"))

        orig_finish = cls._finish

        # _finish is called *from* modal, whose wrapper already times it -- this
        # one only counts completions, it must not add to op_ms.
        def finish_wrapper(self, context, status):
            try:
                return orig_finish(self, context, status)
            finally:
                probe.running = False
                probe.finished += 1

        probe._orig["_finish"] = orig_finish
        cls._finish = finish_wrapper

    def restore(self):
        cls = bpy.types.SCULPTCORE_OT_brush_stroke
        for name, orig in self._orig.items():
            setattr(cls, name, orig)

    def take(self):
        ms, dabs = self.op_ms, self.dabs
        self.op_ms = 0.0
        return ms, dabs


PROBE = OpProbe() if ARGS.engine == "sculptcore" else None


class EngineTrace:
    """Per-engine-call wall time, keyed by ``Owner::method``.

    Every bound-object call funnels through ``sculptcore._marshal.invoke_method``
    (``_classgen`` resolves it as a module attribute per call, so patching the
    module works), and the ctypes call to the DLL happens inside it. cProfile
    stops at that boundary; this does not.
    """

    def __init__(self):
        self.total = {}
        self.calls = {}
        self.enabled = False
        self._orig = None

    def install(self):
        from sculptcore import _marshal

        self._orig = _marshal.invoke_method
        orig = self._orig
        trace = self

        def wrapper(manager, method, self_ptr, args):
            if not trace.enabled:
                return orig(manager, method, self_ptr, args)
            t = time.perf_counter()
            try:
                return orig(manager, method, self_ptr, args)
            finally:
                dt = (time.perf_counter() - t) * 1000.0
                owner = getattr(getattr(method, "owner", None), "name", "?")
                key = "{}::{}".format(owner, method.name)
                trace.total[key] = trace.total.get(key, 0.0) + dt
                trace.calls[key] = trace.calls.get(key, 0) + 1

        _marshal.invoke_method = wrapper

    def restore(self):
        if self._orig is not None:
            from sculptcore import _marshal
            _marshal.invoke_method = self._orig

    def report(self, limit=25):
        rows = sorted(self.total.items(), key=lambda kv: -kv[1])[:limit]
        return [{"call": k, "total_ms": v, "calls": self.calls[k],
                 "per_call_ms": v / self.calls[k]} for k, v in rows]


TRACE = EngineTrace() if (ARGS.engine_trace and ARGS.engine == "sculptcore") else None


class FuncTrace:
    """Wall time for a handful of addon-level functions, so engine-call totals
    can be attributed to a stroke phase (dab / raycast / draw / undo)."""

    # "attr" may be "Class.method" — the operator modal is the outermost addon
    # frame the event loop enters, so it is what bounds "time in the addon".
    TARGETS = (
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._dab_at"),
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._apply_spaced_dab"),
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._apply_one_image"),
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._mid_redraw"),
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._publish_pivot"),
        ("sculptcore_addon.stroke", "SCULPTCORE_OT_brush_stroke._finish"),
        ("sculptcore_addon.stroke", "apply_dab"),
        ("sculptcore_addon.stroke", "apply_dab_program"),
        ("sculptcore_addon.stroke", "raycast"),
        ("sculptcore_addon.stroke", "_refresh_queries"),
        ("sculptcore_addon.stroke", "stroke_end"),
        ("sculptcore_addon.convert", "draw_refresh"),
        ("sculptcore_addon.convert", "multires_store_blob"),
        ("sculptcore_addon.convert", "flush"),
        ("sculptcore_addon.mapping", "apply_dab_state"),
        ("sculptcore_addon.undo", "push"),
        ("sculptcore_addon.handlers", "_on_depsgraph_update"),
        ("sculptcore_addon.cursor", "draw"),
    )

    def __init__(self):
        self.total = {}
        self.calls = {}
        self.enabled = False
        self._orig = []

    def install(self):
        import importlib

        trace = self

        def make(name, orig):
            def wrapper(*a, **kw):
                if not trace.enabled:
                    return orig(*a, **kw)
                t = time.perf_counter()
                try:
                    return orig(*a, **kw)
                finally:
                    dt = (time.perf_counter() - t) * 1000.0
                    trace.total[name] = trace.total.get(name, 0.0) + dt
                    trace.calls[name] = trace.calls.get(name, 0) + 1
            return wrapper

        for module_name, attr in self.TARGETS:
            try:
                owner = importlib.import_module(module_name)
                name = attr
                if "." in attr:
                    cls_name, name = attr.split(".", 1)
                    owner = getattr(owner, cls_name)
                orig = getattr(owner, name)
            except (ImportError, AttributeError):
                continue
            self._orig.append((owner, name, orig))
            setattr(owner, name, make("{}.{}".format(module_name.rsplit(".", 1)[-1], attr), orig))

    def restore(self):
        for module, attr, orig in self._orig:
            setattr(module, attr, orig)

    def report(self):
        rows = sorted(self.total.items(), key=lambda kv: -kv[1])
        return [{"func": k, "total_ms": v, "calls": self.calls[k],
                 "per_call_ms": v / self.calls[k]} for k, v in rows]


FUNCS = FuncTrace() if (ARGS.engine_trace and ARGS.engine == "sculptcore") else None


class CApiTrace(FuncTrace):
    """Same, for the plain ``extern "C"`` entry points the addon calls straight
    off the CDLL — those bypass the bound-method marshaller EngineTrace wraps.

    ctypes caches a resolved function in the CDLL instance ``__dict__``, so a
    plain ``setattr`` shadows it for every later lookup.
    """

    TARGETS = ("Multires_writeback", "Multires_serializeStore", "Multires_restoreStore",
               "Mesh_writeVertPositions", "Multires_setActiveLevel")

    def install(self):
        from sculptcore_addon import engine as sc_engine

        lib = sc_engine.capi().lib
        trace = self

        def make(name, orig):
            def wrapper(*a):
                if not trace.enabled:
                    return orig(*a)
                t = time.perf_counter()
                try:
                    return orig(*a)
                finally:
                    dt = (time.perf_counter() - t) * 1000.0
                    trace.total[name] = trace.total.get(name, 0.0) + dt
                    trace.calls[name] = trace.calls.get(name, 0) + 1
            return wrapper

        for name in self.TARGETS:
            try:
                orig = getattr(lib, name)
            except AttributeError:
                continue
            self._orig.append((lib, name, orig))
            setattr(lib, name, make(name, orig))


CAPI = CApiTrace() if (ARGS.engine_trace and ARGS.engine == "sculptcore") else None

# Set by connect_capture() when --gpu-trace is on; None otherwise.
CAPTURE = None


def connect_capture():
    """Attach to the RenderDoc hook, or raise.

    Called before the scene is built so a run that was launched without
    ``renderdoccmd capture`` fails in a second rather than after a minute of
    multires subdivision. gpu_trace lives beside this script; Blender's
    ``--python`` does set ``__file__``, unlike qrenderdoc's embedded exec.
    """
    global CAPTURE

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gpu_trace

    CAPTURE = gpu_trace.Capture.connect()
    out_dir = ARGS.capture_dir or os.path.join(os.path.dirname(os.path.abspath(ARGS.out)), "captures")
    prefix = "{}-{}".format(ARGS.label or "bench", ARGS.engine)
    template = CAPTURE.configure(out_dir, prefix)
    RESULT["renderdoc"] = {"version": "{}.{}.{}".format(*CAPTURE.version), "template": template}
    log("RenderDoc {}.{}.{} hooked; captures -> {}".format(*(CAPTURE.version + (template,))))


# ---------------------------------------------------------------------------
# Wall-clock stroke
# ---------------------------------------------------------------------------

def stroke_points(ctx, num_samples, flip):
    """Window-space samples sweeping the viewport diagonal at constant speed.

    event_simulate takes *window* coordinates; region.x/y is the region's origin
    inside the window. The sweep is inset so every sample lands on the object.
    """
    region = ctx["region"]
    inset_x, inset_y = region.width * 0.2, region.height * 0.2
    start = Vector((region.x + inset_x, region.y + inset_y))
    end = Vector((region.x + region.width - inset_x, region.y + region.height - inset_y))
    if flip:
        start, end = end, start
    delta = (end - start) / (num_samples - 1)
    return [start + delta * i for i in range(num_samples)]


def push_event(window, kind, value, point):
    window.event_simulate(type=kind, value=value, x=int(point.x), y=int(point.y))


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

# The step timer returns 0.0 always: one callback per main-loop pass. During a
# stroke that is the whole point -- the pusher must get a chance to run (and
# catch up) exactly as often as the event loop itself spins, no more, no less.
YIELD = 0.0


class Bench:
    def __init__(self, ctx):
        self.ctx = ctx
        self.phase = "warmup_idle"
        self.count = 0
        self.t_start = time.perf_counter()
        self.t_phase = self.t_start
        self.last_log = 0.0
        self.profiler = None

        # Per-stroke accumulators.
        self.stroke_wall_ms = []
        self.frames_per_stroke = []
        self.op_ms = []
        self.dabs = []
        self.moves_pushed = 0
        self.inbetween_pushed = 0

        # In-flight stroke state ("gap" -> "stroking" -> "settling").
        self.stroke_state = "gap"
        self.samples = None
        self.num_samples = max(2, int(round(ARGS.event_hz * ARGS.stroke_secs)))
        self.pushed = 0
        self.t_press = 0.0
        self.t_release = 0.0
        self.t_next_stroke = 0.0
        self.frames_at_press = 0
        self.flip = False
        self.finished_base = 0
        self._primed_strength = 0.0
        self._primed_autosmooth = None
        self._prime_frames = 0
        self._brush_ready = False

        self.capture_armed = False
        self.captures_before = 0
        self.drain_passes = 0
        # Never arm more frames than the post-warmup strokes can plausibly
        # present: TriggerMultiFrameCapture takes the next N presents whatever
        # they contain, so an over-long arm spills onto idle frames and quietly
        # averages non-sculpt frames into the trace. Stroke frame counts vary
        # here (that is the regime), so clamp against a floor of 15 fps -- a
        # stroke presenting slower than that is itself the finding.
        available = int(max(0, ARGS.strokes - ARGS.trace_after_strokes) * ARGS.stroke_secs * 15.0)
        self.capture_target = min(ARGS.gpu_trace, available)
        if ARGS.gpu_trace and self.capture_target < ARGS.gpu_trace:
            log("clamped --gpu-trace {} -> {} (>= {} stroke frames follow warmup at 15 fps)".format(
                ARGS.gpu_trace, self.capture_target, available))

    def tag(self):
        self.ctx["region"].tag_redraw()

    def enter(self, phase):
        log("{} done in {:.1f}s -> {}".format(self.phase, time.perf_counter() - self.t_phase, phase))
        self.phase = phase
        self.t_phase = time.perf_counter()

    def step(self):
        t_step = time.perf_counter()
        try:
            result = self._step_guarded()
        finally:
            if WALL is not None:
                WALL.add("step", t_step, time.perf_counter())
        return result

    def _step_guarded(self):
        try:
            now = time.perf_counter()
            if now - self.last_log > 5.0:
                self.last_log = now
                log("phase={} frames={} strokes={} t={:.0f}s".format(
                    self.phase, TIMING.frames, self.count, now - self.t_start))
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
            if not self._brush_ready and TIMING.frames >= 1:
                # brush.asset_activate is a silent no-op at --python script
                # time in a headed session -- it returns without switching and
                # the factory Draw brush stays active (headless it works).
                # Activate from inside the event loop, after a frame has run.
                prepare_brush(ARGS.brush, ARGS.brush_size)
                self._brush_ready = True
            if TIMING.frames >= ARGS.warmup:
                # The first simulated viewport click of a headed session is
                # swallowed (same family as the swallowed splash click), which
                # would turn stroke 0 into a no-op. Spend a sacrificial click
                # here, at zero strength so that if it *does* land it deforms
                # nothing -- the operator still runs, which is the priming.
                brush = bpy.context.tool_settings.sculpt.brush
                self._primed_strength = brush.strength
                brush.strength = 0.0
                # Autosmooth is NOT scaled by the main strength: a Clay priming
                # dab would still relax geometry. Zero it for the click too.
                self._primed_autosmooth = getattr(brush, "auto_smooth_factor", None)
                if self._primed_autosmooth:
                    brush.auto_smooth_factor = 0.0
                center = stroke_points(self.ctx, 2, False)[0]
                push_event(self.ctx["window"], 'MOUSEMOVE', 'NOTHING', center)
                push_event(self.ctx["window"], 'LEFTMOUSE', 'PRESS', center)
                push_event(self.ctx["window"], 'LEFTMOUSE', 'RELEASE', center)
                self._prime_frames = TIMING.frames
                self.enter("prime")
            return YIELD

        if self.phase == "prime":
            self.tag()
            if TIMING.frames >= self._prime_frames + 5:
                brush = bpy.context.tool_settings.sculpt.brush
                brush.strength = self._primed_strength
                if self._primed_autosmooth:
                    brush.auto_smooth_factor = self._primed_autosmooth
                if PROBE is not None:
                    RESULT["priming_click_landed"] = PROBE.finished > 0
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
                if ARGS.profile and PROBE is not None:
                    import cProfile
                    self.profiler = cProfile.Profile()
                    self.profiler.enable()
                for tracer in (TRACE, FUNCS, CAPI):
                    if tracer is not None:
                        tracer.enabled = True
                if WALL is not None:
                    WALL.start()
                if PROBE is not None:
                    PROBE.take()  # discard the priming click's op time
                    self.finished_base = PROBE.finished
                self.t_next_stroke = time.perf_counter()
                self.enter("sculpt")
            return YIELD

        if self.phase == "sculpt":
            return self._step_sculpt()

        if self.phase == "drain_capture":
            # Safety net only: the arm was clamped against a conservative
            # frames-per-stroke floor (see __init__), so this normally exits on
            # the first pass. If it ever has to spin, the frames it captures are
            # idle ones and the log line below is the warning that the trace is
            # polluted.
            self.drain_passes += 1
            written = CAPTURE.num_captures() - self.captures_before
            if written >= self.capture_target or self.drain_passes > 240:
                if written < self.capture_target:
                    log("WARNING: capture drained on idle frames -- got {}/{}".format(
                        written, self.capture_target))
                return self._finalize()
            self.tag()
            return YIELD

        finish()
        return None

    # -- sculpt phase -------------------------------------------------------

    def arm_capture(self):
        """Arm the RenderDoc capture once the engine is warm.

        Deliberately not at stroke 0: the first stroke pays for lazy GPU buffer
        creation and shader compilation in both engines, and tracing that
        measures startup rather than steady-state sculpting.
        """
        if CAPTURE is None or self.capture_armed or not self.capture_target:
            return
        if self.count < ARGS.trace_after_strokes:
            return
        self.captures_before = CAPTURE.num_captures()
        CAPTURE.set_title("{} {} grid={} level={}".format(
            ARGS.label or "bench", ARGS.engine, ARGS.grid, ARGS.level))
        CAPTURE.trigger_multi(self.capture_target)
        self.capture_armed = True
        log("armed RenderDoc capture: {} frames from stroke {}".format(
            self.capture_target, self.count))

    def _step_sculpt(self):
        """One pass of the wall-clock stroke machine.

        ``stroking`` pushes every sample whose device timestamp has come due
        since the last pass. On a smooth run that is one or two per pass; after
        a stalled frame it is the whole backlog at once -- the device queue
        model. All but the newest of a backlog go in as INBETWEEN_MOUSEMOVE,
        which is what ``wm_event_add_mousemove`` would have demoted them to had
        they arrived from a real device (event_simulate's WM_event_add path
        skips that logic). Native sculpt samples inbetweens into the stroke
        path; the SculptCore modal currently drops them -- a real parity gap
        this bench is supposed to expose, not paper over.

        No tag_redraw during a stroke: the stroke operator dirties the region
        itself, and forcing extra frames here would fake a redraw cadence
        neither engine produces for a real user.
        """
        now = time.perf_counter()
        window = self.ctx["window"]

        if self.stroke_state == "gap":
            if now < self.t_next_stroke:
                return YIELD
            if self.count >= ARGS.strokes:
                return self._finish_sculpt()
            self.arm_capture()
            self.samples = stroke_points(self.ctx, self.num_samples, self.flip)
            self.flip = not self.flip
            TIMING.collect = True
            # The first frame interval of this stroke would span the gap;
            # zeroing prev_post makes on_post skip it.
            TIMING.prev_post = 0.0
            self.frames_at_press = TIMING.frames
            self.t_press = time.perf_counter()
            # Hover move first so the press lands with a cursor position, as a
            # real press does.
            push_event(window, 'MOUSEMOVE', 'NOTHING', self.samples[0])
            push_event(window, 'LEFTMOUSE', 'PRESS', self.samples[0])
            TIMING.last_push = self.t_press
            if WALL is not None:
                WALL.add("push", self.t_press, self.t_press)
            self.pushed = 1
            self.stroke_state = "stroking"
            return YIELD

        if self.stroke_state == "stroking":
            due = min(self.num_samples - 1, int((now - self.t_press) * ARGS.event_hz))
            if due >= self.pushed:
                t_push = time.perf_counter()
                for i in range(self.pushed, due + 1):
                    kind = 'MOUSEMOVE' if i == due else 'INBETWEEN_MOUSEMOVE'
                    push_event(window, kind, 'NOTHING', self.samples[i])
                    if i == due:
                        self.moves_pushed += 1
                    else:
                        self.inbetween_pushed += 1
                TIMING.last_push = t_push
                if WALL is not None:
                    WALL.add("push", t_push, t_push)
                self.pushed = due + 1
            if self.pushed >= self.num_samples:
                push_event(window, 'LEFTMOUSE', 'RELEASE', self.samples[-1])
                self.t_release = time.perf_counter()
                self.stroke_state = "settling"
            return YIELD

        # settling: the release is in the queue; the stroke is over once the
        # operator has finished (SculptCore; native's C++ modal is invisible,
        # so a presented frame after the release stands in) and that frame --
        # the one carrying stroke_end / undo-push cost -- has been presented.
        op_done = PROBE is None or not PROBE.running
        frame_done = TIMING.post > self.t_release
        if not (op_done and frame_done):
            # Normally the stroke-end redraw arrives by itself; if nothing has
            # presented for a while the queue went quiet (e.g. a cancelled
            # stroke tagged nothing) -- nudge, or settle waits for the timeout.
            if now - self.t_release > 0.3:
                self.tag()
            return YIELD

        TIMING.collect = False
        self.stroke_wall_ms.append((TIMING.post - self.t_press) * 1000.0)
        self.frames_per_stroke.append(TIMING.frames - self.frames_at_press)
        if PROBE is not None:
            ms, dabs = PROBE.take()
            self.op_ms.append(ms)
            self.dabs.append(dabs)
        self.count += 1
        self.t_next_stroke = time.perf_counter() + ARGS.gap_secs
        self.stroke_state = "gap"
        return YIELD

    def _finish_sculpt(self):
        TIMING.collect = False
        if self.profiler is not None:
            self.profiler.disable()
            RESULT["profile"] = format_profile(self.profiler)
        RESULT["sculpt_phase_ms"] = (time.perf_counter() - self.t_phase) * 1000.0
        RESULT["sculpt_frames"] = TIMING.frames
        RESULT["stroke_frame_ms"] = stats(TIMING.frame_ms)
        RESULT["latency_ms"] = stats(TIMING.latency_ms)
        RESULT["sculpt_view_ms"] = stats(TIMING.view_ms)
        RESULT["stroke_wall_ms"] = stats(self.stroke_wall_ms)
        RESULT["frames_per_stroke"] = stats(self.frames_per_stroke)
        RESULT["events"] = {
            "per_stroke": self.num_samples,
            "moves": self.moves_pushed,
            "inbetween": self.inbetween_pushed,
        }
        for key, tracer in (("engine_trace", TRACE), ("func_trace", FUNCS),
                            ("capi_trace", CAPI)):
            if tracer is not None:
                tracer.enabled = False
                RESULT[key] = tracer.report()
        if WALL is not None:
            WALL.enabled = False
            RESULT["wall_trace"] = [[k, round(t, 3), round(d, 3)]
                                    for k, t, d in WALL.records]
        if PROBE is not None:
            RESULT["stroke_ms"] = stats(self.op_ms)
            RESULT["dabs_per_stroke"] = stats(self.dabs)
            RESULT["strokes_finished"] = PROBE.finished - self.finished_base

        # Stay in the mode while captures are still outstanding: leaving it
        # would draw (and capture) object-mode frames.
        if CAPTURE is not None and self.capture_armed:
            self.enter("drain_capture")
            return YIELD
        return self._finalize()

    def _finalize(self):
        RESULT["undo_memory"] = bpy.app.memory_usage_undo()
        if CAPTURE is not None:
            RESULT["captures"] = CAPTURE.captures()[self.captures_before:]
            log("wrote {} captures".format(len(RESULT["captures"])))
        # Read the surface in object mode: multires displacement lives in
        # the grids, and the base cage stays flat by design.
        leave_mode(ARGS.engine)
        RESULT["surface_after"] = surface_state()
        log("after: verts={} peak_z={:.5f}".format(
            RESULT["surface_after"]["verts"], RESULT["surface_after"]["peak_z"]))
        self.enter("done")
        return YIELD


def format_profile(profiler, limit=40):
    import io
    import pstats

    buf = io.StringIO()
    pstats.Stats(profiler, stream=buf).sort_stats("tottime").print_stats(limit)
    return buf.getvalue()


def process_memory():
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
    for hook in (PROBE, TRACE, FUNCS, CAPI, WALL):
        if hook is not None:
            try:
                hook.restore()
            except Exception:  # noqa: BLE001 - teardown must not mask the result
                pass
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
    if not (bpy.app.use_event_simulate if hasattr(bpy.app, "use_event_simulate") else True):
        raise RuntimeError("run Blender with --enable-event-simulate")

    if ARGS.gpu_trace:
        connect_capture()

    bpy.context.preferences.edit.undo_steps = ARGS.undo_steps
    # A cursor overlay redraw per mouse move would be timed as stroke cost in one
    # engine and not the other; both draw one, so it stays on, but the brush
    # cursor's own settings are pinned below by prepare_brush.

    ctx = find_view3d()
    log("building engine={} mode={} grid={} level={}".format(
        ARGS.engine, ARGS.mode, ARGS.grid, ARGS.level))
    t = time.perf_counter()
    build_object(ARGS.grid, ARGS.level, ARGS.mode)
    log("built {} sculpt faces ({} evaluated verts) in {:.1f}s".format(
        RESULT["sculpt_faces"], RESULT["surface_before"]["verts"], time.perf_counter() - t))

    with bpy.context.temp_override(**ctx):
        bpy.ops.view3d.view_all()
        bpy.ops.ed.undo_push()

    t = time.perf_counter()
    enter_mode(ARGS.engine)
    RESULT["enter_mode_ms"] = (time.perf_counter() - t) * 1000.0
    log("entered {} mode in {:.0f} ms".format(ARGS.engine, RESULT["enter_mode_ms"]))
    # The brush is prepared from the first warmup tick, not here: at script
    # time brush.asset_activate is a silent no-op in a headed session, and
    # ToolSettings.sculpt has no active brush until BKE_paint_init has run.

    if PROBE is not None:
        PROBE.install()
    for tracer in (TRACE, FUNCS, CAPI):
        if tracer is not None:
            tracer.install()
    if WALL is not None:
        WALL.install()

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
