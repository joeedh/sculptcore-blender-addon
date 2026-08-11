# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headed cancel-path test for the C++ dab-loop stroke operator.

Exercises the two teardown routes that never run in the benchmarks:

1. **ESC mid-stroke** (modal's own ``{'RIGHTMOUSE', 'ESC'}`` branch →
   ``_finish(context, 'CANCELLED')``) with ``sculptcore_cpp_dab_loop`` on:
   the dabs already applied must stay (cancel keeps the delta-undo step),
   and a second, released stroke must work afterwards — proving the session
   survived the cancel.
2. **``cancel()`` proper** (window close while the modal runs, where
   ``context.area`` is gone): a third stroke is left un-released and Blender
   is quit. Any exception in ``cancel()`` prints a traceback that the
   harness greps for; the checks up to that point have already been scored.

Run::

    blender.exe --factory-startup --enable-event-simulate --no-window-focus \
        -p 0 0 1280 800 --python-exit-code 1 \
        --python claudeMemory/scripts/test_stroke_cancel.py

Verdict lines are ``  ok  ...`` / ``  FAIL ...`` plus a final
``test_stroke_cancel: scripted checks passed`` before the quit; the caller
must also grep stdout for ``Traceback`` (an exception inside ``cancel()``
does not change the exit code).
"""

import bpy
from mathutils import Vector

from sculptcore_addon import engine as sc_engine
from sculptcore_addon import stroke as sc_stroke

failures = []


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg), flush=True)
    if not cond:
        failures.append(msg)


def find_view3d():
    window = bpy.context.window_manager.windows[0]
    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                return {"window": window, "area": area, "region": region}
    raise RuntimeError("no VIEW_3D/WINDOW region -- is this a headed run?")


def probe_z():
    """Surface height at the object origin, read through the engine session
    (the evaluated mesh is useless in-mode: the multires modifier's viewport
    evaluation is suppressed, so it reports the untouched base cage)."""
    session = sc_engine.sessions[bpy.context.object.name]
    hit = sc_stroke.raycast(session, (0.0, 0.0, 3.0), (0.0, 0.0, -1.0))
    if hit is None:
        raise RuntimeError("probe ray missed the surface")
    return float(hit[0][2])


def stroke_points(ctx, num_steps):
    region = ctx["region"]
    inset_x, inset_y = region.width * 0.35, region.height * 0.35
    start = Vector((region.x + inset_x, region.y + inset_y))
    end = Vector((region.x + region.width - inset_x, region.y + region.height - inset_y))
    delta = (end - start) / (num_steps - 1)
    return [start + delta * i for i in range(num_steps)]


def push(window, kind, value, point):
    window.event_simulate(type=kind, value=value, x=int(point.x), y=int(point.y))


class Runner:
    """One phase per timer tick, so every event burst gets its own
    wm_event_do_handlers pass before the next phase inspects the result."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.window = ctx["window"]
        self.points = stroke_points(ctx, 8)
        self.phase = 0
        self.z_start = None
        self.z_after_esc = None

    def step(self):
        try:
            return self.dispatch()
        except Exception:
            import traceback
            traceback.print_exc()
            failures.append("runner raised")
            self.quit()
            return None

    def dispatch(self):
        p = self.points
        if self.phase == 0:
            # The essentials brush asset loads asynchronously; until it is the
            # active brush the stroke keymap has nothing to invoke. Events
            # simulated before the viewport has actually drawn are dropped
            # too, so wait for a few real frames (the bench's warmup phase).
            brush = bpy.context.tool_settings.sculpt.brush
            if brush is None or brush.name != "Draw" or DRAWS[0] < 10:
                print("  [dbg] waiting: brush={!r} draws={:d}".format(
                    brush.name if brush else None, DRAWS[0]), flush=True)
                # An idle viewport stops redrawing; keep frames coming so
                # the draw gate can actually be met.
                self.ctx["area"].tag_redraw()
                return 0.25
            # The first press into the viewport is reliably swallowed (the
            # bench loses its first stroke to the same thing — its JSONs
            # show dabs_per_stroke min=0); feed it a throwaway click at the
            # stroke start point, far enough from the centre probe that even
            # a landed dab cannot bias it. NOT near the edges: the toolbar
            # (left) switches the active tool, the tool header (top) and
            # nav gizmo (top-right) eat clicks without absorbing the loss.
            push(self.window, 'MOUSEMOVE', 'NOTHING', p[0])
            push(self.window, 'LEFTMOUSE', 'PRESS', p[0])
            push(self.window, 'LEFTMOUSE', 'RELEASE', p[0])
        elif self.phase == 1:
            self.z_start = probe_z()
            # Stroke 1: press + moves, NO release, then ESC next tick.
            push(self.window, 'MOUSEMOVE', 'NOTHING', p[0])
            push(self.window, 'LEFTMOUSE', 'PRESS', p[0])
            for point in p[1:5]:
                push(self.window, 'MOUSEMOVE', 'NOTHING', point)
        elif self.phase == 2:
            push(self.window, 'ESC', 'PRESS', p[4])
        elif self.phase == 3:
            # ESC keeps the applied dabs; a flat surface here means the
            # stroke never applied anything (or the cancel rolled it back).
            self.z_after_esc = probe_z()
            check(abs(self.z_after_esc - self.z_start) > 1e-4,
                  "ESC kept applied dabs (z {:.5f} -> {:.5f})".format(
                      self.z_start, self.z_after_esc))
            check(bpy.context.object.mode == 'CUSTOM',
                  "still in SculptCore mode after ESC")
            # Stroke 2: full press/move/release — session must still work.
            push(self.window, 'MOUSEMOVE', 'NOTHING', p[0])
            push(self.window, 'LEFTMOUSE', 'PRESS', p[0])
            for point in p[1:]:
                push(self.window, 'MOUSEMOVE', 'NOTHING', point)
            push(self.window, 'LEFTMOUSE', 'RELEASE', p[-1])
        elif self.phase == 4:
            check(COUNTS["invoke"] >= 2 and COUNTS["modal"] > COUNTS["invoke"],
                  "both strokes reached the operator (invokes={:d} modals={:d})".format(
                      COUNTS["invoke"], COUNTS["modal"]))
            z = probe_z()
            check(abs(z - self.z_after_esc) > 1e-4,
                  "post-ESC stroke sculpted ({:.5f} -> {:.5f})".format(self.z_after_esc, z))
            print("test_stroke_cancel: scripted checks passed"
                  if not failures else
                  "test_stroke_cancel: {:d} FAILURE(S)".format(len(failures)), flush=True)
            # Stroke 3: press + moves, no release — quit with the modal live
            # so Blender runs cancel() (context.area is torn down by then).
            push(self.window, 'MOUSEMOVE', 'NOTHING', p[0])
            push(self.window, 'LEFTMOUSE', 'PRESS', p[0])
            for point in p[1:5]:
                push(self.window, 'MOUSEMOVE', 'NOTHING', point)
        elif self.phase == 5:
            print("test_stroke_cancel: quitting mid-stroke (cancel() path)", flush=True)
            self.quit()
            return None
        self.phase += 1
        return 0.25

    def quit(self):
        # Not wm.quit_blender here: with a modal handler live it prompts on
        # some platforms; event-simulated window close is closest to a user
        # close anyway, but quit_blender after event flush is deterministic.
        bpy.ops.wm.quit_blender()


COUNTS = {"invoke": 0, "modal": 0}
DRAWS = [0]


def _on_draw():
    DRAWS[0] += 1


def _count_calls():
    cls = sc_stroke.SCULPTCORE_OT_brush_stroke
    orig_invoke, orig_modal = cls.invoke, cls.modal

    def invoke(self, context, event):
        COUNTS["invoke"] += 1
        return orig_invoke(self, context, event)

    def modal(self, context, event):
        COUNTS["modal"] += 1
        return orig_modal(self, context, event)

    cls.invoke, cls.modal = invoke, modal


def main():
    if not bpy.app.use_event_simulate:
        raise RuntimeError("run Blender with --enable-event-simulate")
    _count_calls()
    # The factory-startup splash swallows pointer events (the bench loses its
    # first stroke to it — dabs_per_stroke min=0); this test cannot afford to.
    bpy.context.preferences.view.show_splash = False

    ctx = find_view3d()
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=2)
    ob = bpy.context.object
    ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(2):
        bpy.ops.object.multires_subdivide(modifier="Multires")

    with bpy.context.temp_override(**ctx):
        bpy.ops.view3d.view_all()

    bpy.context.scene.sculptcore_cpp_dab_loop = True
    bpy.ops.object.custom_mode_toggle(mode_id="sculptcore.sculpt")
    if ob.mode != 'CUSTOM' or ob.custom_mode != "sculptcore.sculpt":
        raise RuntimeError("failed to enter SculptCore mode (mode={!r})".format(ob.mode))

    bpy.ops.brush.asset_activate(
        asset_library_type='ESSENTIALS',
        relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')

    bpy.types.SpaceView3D.draw_handler_add(_on_draw, (), 'WINDOW', 'POST_PIXEL')
    runner = Runner(ctx)
    bpy.app.timers.register(runner.step, first_interval=0.5)


main()
