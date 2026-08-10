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

Metric
------
``cycle_ms`` -- wall time from pushing one stroke's events to the ``POST_PIXEL``
of the frame that follows. Blender's main loop is
``do_notifiers (bpy timers) -> do_handlers (our events) -> draw``, so pushing
from a timer callback means a single pass covers input handling *and* the
redraw the edit dirtied. That is the number the user feels, and it is the only
one both engines can report identically.

``sculpt_phase_ms`` / ``sculpt_frames`` -- wall time and frame count for the
whole 20-stroke sculpt phase. ``cycle_ms`` only spans a stroke's leading edge,
so it saturates at the vsync quantum and hides per-dab cost; this is the
throughput number, and both engines report it identically.

``stroke_ms`` is the operator's own time, summed over invoke + every modal call.
SculptCore's is measured by wrapping the Python operator; native sculpt's modal
is C++ and cannot be wrapped, so for ``--engine native`` this key is absent and
``cycle_ms`` is the comparison.

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
    parser.add_argument("--brush", default="Draw", help="Essentials brush asset name")
    parser.add_argument("--brush-size", type=int, default=50, help="Brush radius in pixels")
    parser.add_argument("--warmup", type=int, default=20, help="Frames to discard before each phase")
    parser.add_argument("--idle-frames", type=int, default=60, help="Frames to time with no edits")
    parser.add_argument("--strokes", type=int, default=20, help="Timed strokes")
    parser.add_argument("--stroke-steps", type=int, default=20, help="Move events per stroke")
    parser.add_argument("--undo-steps", type=int, default=8, help="Cap the undo stack")
    parser.add_argument("--cpp-driver", action="store_true",
                        help="Enable the sculptcore_cpp_stroke_driver scene toggle (SculptCore only)")
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
    parser.add_argument("--paced-stroke", action="store_true",
                        help="Push one event per main-loop pass so every dab gets its own frame. "
                             "Required for a meaningful GPU trace -- see push_stroke's docstring")
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
        if ARGS.cpp_driver:
            bpy.context.scene.sculptcore_cpp_stroke_driver = True
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
    # Small deformation so repeated strokes do not reshape the test object, and a
    # pinned size/spacing so both engines lay down the same number of dabs.
    brush.strength = 0.1
    brush.size = size
    brush.spacing = 10
    unified = bpy.context.tool_settings.sculpt.unified_paint_settings
    unified.use_unified_size = False
    unified.use_unified_strength = False
    RESULT["brush"] = {"name": name, "size": brush.size, "spacing": brush.spacing,
                       "strength": brush.strength}


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
        if WALL is not None:
            WALL.add("draw", self.pre, now)
        self.prev_post = now
        self.post = now
        self.frames += 1

    def reset(self):
        self.view_ms = []
        self.frame_ms = []
        self.prev_post = 0.0


TIMING = Timing()


class WallTrace:
    """Raw span timeline for the sculpt phase.

    Each record is ``[kind, t_ms, dur_ms]`` with ``t_ms`` relative to the base
    stamped when the sculpt phase starts. Kinds:

    - ``push``       a stroke's event burst entered the queue (dur 0)
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
# no equivalent -- which is why cycle_ms, not stroke_ms, is the A/B metric.

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
# Event-driven stroke
# ---------------------------------------------------------------------------

def stroke_points(ctx, num_steps, flip):
    """Window-space points sweeping the viewport diagonal.

    event_simulate takes *window* coordinates; region.x/y is the region's origin
    inside the window. The sweep is inset so every sample lands on the object.
    """
    region = ctx["region"]
    inset_x, inset_y = region.width * 0.2, region.height * 0.2
    start = Vector((region.x + inset_x, region.y + inset_y))
    end = Vector((region.x + region.width - inset_x, region.y + region.height - inset_y))
    if flip:
        start, end = end, start
    delta = (end - start) / (num_steps - 1)
    return [start + delta * i for i in range(num_steps)]


def stroke_events(points):
    """The ``(type, value, point)`` sequence for one press / move.../release stroke."""
    first, last = points[0], points[-1]
    events = [('MOUSEMOVE', 'NOTHING', first), ('LEFTMOUSE', 'PRESS', first)]
    events.extend(('MOUSEMOVE', 'NOTHING', point) for point in points[1:])
    events.append(('LEFTMOUSE', 'RELEASE', last))
    return events


def push_event(window, event):
    kind, value, point = event
    window.event_simulate(type=kind, value=value, x=int(point.x), y=int(point.y))


def push_stroke(window, points):
    """One press / move.../release burst into the window's event queue.

    All of it is handled in a single ``wm_event_do_handlers`` pass, so the frame
    that follows is the one the whole stroke dirtied. event_simulate appends via
    WM_event_add (not wm_event_add_mousemove), so no move is demoted to
    INBETWEEN_MOUSEMOVE -- both engines see every sample.

    That single-pass property is what makes this the right shape for throughput
    (it is why ``sculpt_phase_ms`` is honest) and the *wrong* shape for a GPU
    trace: a whole stroke collapses into roughly one redraw, so a capture sees
    one frame carrying twenty dabs' worth of deferred work rather than the
    per-dab frames a real stroke produces. ``--paced-stroke`` pushes these same
    events one per main-loop pass instead, which is what the trace mode uses.
    """
    for event in stroke_events(points):
        push_event(window, event)


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

YIELD = 0.0


class Bench:
    def __init__(self, ctx):
        self.ctx = ctx
        self.phase = "warmup_idle"
        self.count = 0
        self.cycle_ms = []
        self.op_ms = []
        self.dabs = []
        self.pending = False
        self.t_push = 0.0
        self.flip = False
        self.t_start = time.perf_counter()
        self.t_phase = self.t_start
        self.last_log = 0.0
        self.profiler = None

        # Paced-stroke cursor: None until the first stroke is built, then the
        # remaining events of the stroke in flight.
        self.events = None

        self.capture_armed = False
        self.captures_before = 0
        self.drain_passes = 0
        # Never arm more frames than the post-warmup strokes will actually
        # present: TriggerMultiFrameCapture takes the next N presents whatever
        # they contain, so an over-long arm spills onto idle frames and quietly
        # averages non-sculpt frames into the trace.
        per_stroke_frames = (ARGS.stroke_steps + 2) if ARGS.paced_stroke else 1
        available = max(0, ARGS.strokes - ARGS.trace_after_strokes) * per_stroke_frames
        self.capture_target = min(ARGS.gpu_trace, available)
        if ARGS.gpu_trace and self.capture_target < ARGS.gpu_trace:
            log("clamped --gpu-trace {} -> {} (only {} stroke frames follow warmup)".format(
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
                if ARGS.profile and PROBE is not None:
                    import cProfile
                    self.profiler = cProfile.Profile()
                    self.profiler.enable()
                for tracer in (TRACE, FUNCS, CAPI):
                    if tracer is not None:
                        tracer.enabled = True
                if WALL is not None:
                    WALL.start()
                self.enter("sculpt")
            return YIELD

        if self.phase == "sculpt":
            if ARGS.paced_stroke:
                return self._step_sculpt_paced()
            return self._step_sculpt_burst()

        if self.phase == "drain_capture":
            # Safety net only: TriggerMultiFrameCapture is armed with a frame
            # count the remaining strokes are guaranteed to cover (see
            # arm_capture), so this normally exits on the first pass. If it ever
            # has to spin, the frames it captures are idle ones and the log line
            # below is the warning that the trace is polluted.
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

    def _step_sculpt_burst(self):
        if self.pending:
            if TIMING.post > self.t_push:
                self.cycle_ms.append((TIMING.post - self.t_push) * 1000.0)
                if PROBE is not None:
                    ms, dabs = PROBE.take()
                    self.op_ms.append(ms)
                    self.dabs.append(dabs)
                self.pending = False
            else:
                self.tag()
                return YIELD

        if self.count >= ARGS.strokes:
            return self._finish_sculpt()

        self.arm_capture()
        points = stroke_points(self.ctx, ARGS.stroke_steps, self.flip)
        self.flip = not self.flip
        TIMING.collect = True
        self.t_push = time.perf_counter()
        push_stroke(self.ctx["window"], points)
        if WALL is not None:
            WALL.add("push", self.t_push, self.t_push)
        self.count += 1
        self.pending = True
        self.tag()
        return YIELD

    def _step_sculpt_paced(self):
        """One event per main-loop pass, so every dab gets its own frame.

        ``wm_event_do_handlers`` drains the queue once per pass, so a single
        queued event is handled alone and the redraw that follows belongs to
        that dab. ``cycle_ms`` is therefore per-dab latency in this mode rather
        than per-stroke -- which is both what an interactive stroke feels like
        and what makes each captured frame attributable to one dab.
        """
        if self.pending:
            if TIMING.post <= self.t_push:
                self.tag()
                return YIELD
            self.cycle_ms.append((TIMING.post - self.t_push) * 1000.0)
            self.pending = False

        if not self.events:
            if self.events is not None:
                # The stroke just drained; PROBE accumulates across its events.
                self.count += 1
                if PROBE is not None:
                    ms, dabs = PROBE.take()
                    self.op_ms.append(ms)
                    self.dabs.append(dabs)
            if self.count >= ARGS.strokes:
                return self._finish_sculpt()
            self.arm_capture()
            self.events = stroke_events(stroke_points(self.ctx, ARGS.stroke_steps, self.flip))
            self.flip = not self.flip

        TIMING.collect = True
        self.t_push = time.perf_counter()
        push_event(self.ctx["window"], self.events.pop(0))
        self.pending = True
        self.tag()
        return YIELD

    def _finish_sculpt(self):
        TIMING.collect = False
        if self.profiler is not None:
            self.profiler.disable()
            RESULT["profile"] = format_profile(self.profiler)
        # Engine-agnostic throughput: cycle_ms only spans the leading
        # edge of a stroke (push -> first redraw), and stroke_ms needs
        # the operator probe, which native sculpt has no equivalent of.
        RESULT["sculpt_phase_ms"] = (time.perf_counter() - self.t_phase) * 1000.0
        RESULT["sculpt_frames"] = TIMING.frames
        RESULT["cycle_ms"] = stats(self.cycle_ms)
        RESULT["sculpt_view_ms"] = stats(TIMING.view_ms)
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
            RESULT["strokes_finished"] = PROBE.finished

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
    # After the mode is entered, not before: ToolSettings.sculpt has no active
    # brush until BKE_paint_init has run, so tool_settings.sculpt.brush is None.
    prepare_brush(ARGS.brush, ARGS.brush_size)

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
