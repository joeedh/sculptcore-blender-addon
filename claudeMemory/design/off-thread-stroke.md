# Design: off-thread stroke execution and the sample queue

Status: **S0 (§3.3) shipped 2026-08-16 and closed the problem this document was
written for. Everything from §4 on is SHELVED — not pressure-tested, not
built, and no longer motivated by the sampling argument below** (see P-b).
Read §3 as the resolution; read §4–§11 as a costed option that was declined,
kept because it is the analysis anyone re-raising "sculpt off the main thread"
will need. Reviving it needs latency numbers from S1 first, not this text.
Written
from the user's question: *"make it so all sculpting happens off the main
thread, which is left free to collect pointer events … is it possible to
collect events off the main thread and have our own event queue (that would
of course require modifying the blender fork)?"*

The headline answers are both the opposite of what the framing assumed:

1. **No, events cannot be collected off the main thread** — not portably, and
   no fork change unlocks it. macOS forbids it at the OS level and Windows
   makes it self-defeating. §2.
2. **But this needs no fork change at all**, because the samples the stall is
   assumed to destroy are, on a tablet, already arriving intact and being
   dropped by `stroke.py`. §3 is the loss ledger; §3.3 is a one-function fix
   that should land before any threading work — **it landed, and it was
   enough**; the threading work was shelved rather than built (P-b).

Related: [design/cpp-dab-loop.md](cpp-dab-loop.md) (the C++ `StrokeRun`
runner — §6.2 here depends on it),
[plans/cpp-stroke-driver-adoption.md](../plans/cpp-stroke-driver-adoption.md)
(the engine's `BrushStrokeDriver`, already queue-shaped — §9).

## 1. The goal, restated in terms this repo can act on

The stated want is three things that are usually conflated:

- **(G1) Sampling fidelity** — every position the hand actually drew reaches
  the spacer, not just the ones that survived a stall.
- **(G2) Main-thread responsiveness** — the modal handler returns in
  microseconds, so the window keeps pumping, keeps redrawing, and keeps
  accepting ESC while sculpt work is outstanding.
- **(G3) Feedback for the resulting lag** — a drawn path in the viewport
  showing where the stroke is headed but has not yet been applied.

They have different costs. G1 is a ~15-line change (§3.3). G2 is the threading
project (§4–§8). G3 is a draw handler (§7) and is worth doing the moment G2
introduces visible lag, and pointless before that.

**What none of them buy: throughput.** The engine's dab apply is already
node-parallel (`brush_executor.h:816`, `:1042`, `grid_executor.h:927`), so the
main thread's stall is not idle time waiting to be reclaimed — it is the
machine doing the work. Moving the loop off-thread relocates that work; it does
not shrink it. Anyone reading this expecting a perf win should read
[design/cpp-dab-loop.md](cpp-dab-loop.md) instead, which is the perf lever.

## 2. Can events be collected off the main thread?

Verdict per platform, from the fork's GHOST sources:

**macOS — categorically no.** `[NSApp nextEventMatchingMask:]` and every
AppKit UI call are main-thread-only by Apple's contract. There is no fork-side
workaround; a worker calling into AppKit is undefined behavior, not a
performance tradeoff.

**Windows — technically yes, practically self-defeating.** Win32 message
queues are per-thread: `PeekMessageW` (`GHOST_SystemWin32.cc:440`, inside
`processEvents` at `:407`) only retrieves messages for windows *created by the
calling thread*. Collecting on a worker therefore requires creating the window
on the worker, which merely renames which thread is the UI thread — and the
sculpt work would then be the thing blocking it again. Wintab is bound the same
way: `WT_PACKET` arrives through the same WndProc (`:1886`).

**Linux — the only viable one, which is why it is not worth doing.** X11 with
`XInitThreads`, or a Wayland proxy event queue, would genuinely allow it. A
threading model that exists on one of three platforms is a maintenance
liability, not a feature.

**Conclusion: invert the plan.** The main thread stays the collector — that
job is an OS pump plus a queue append and costs nothing — and the *sculpting*
moves off. This is the standard inversion and it happens to be the one that
also needs no fork change.

## 3. The sample-loss ledger

Where a hand-drawn sample can actually die today, in order from the tablet
inward.

### 3.1 The OS layer — mouse loses, pen does not

- **Mouse.** Win32 synthesizes at most one pending `WM_MOUSEMOVE`; a stalled
  pump sees only the newest position. Genuine, unrecoverable-by-default loss.
  `GetMouseMovePointsEx` would recover up to 64 recent points; Blender does not
  call it anywhere in `intern/ghost`.
- **Wintab (the pen path that matters).** Blender negotiates the Wintab queue
  up to **500 packets** (`GHOST_Wintab.cc:90`, the `maxQueue` climb loop), and
  on each `WT_PACKET` message `GHOST_Wintab::getInput` drains the *whole*
  queue, emitting one `GHOST_WintabInfoWin32` per packet;
  `GHOST_SystemWin32::processWintabEvent` (`:949`) then pushes each as its own
  `GHOST_kEventCursorMove` (`:979`). At ~200 Hz that is ~2.5 s of stall before
  a single packet is lost.
- **Windows Ink / `WM_POINTER`** similarly loops the pointer-info history
  array and pushes one cursor event per entry (`GHOST_SystemWin32.cc:1117`).

So on the configuration this addon is actually sculpted with — a pen on
Windows — the full high-rate trace reaches Blender's window event queue.

### 3.2 Blender's WM layer — demotes, never discards

`wm_event_add_mousemove` (`wm_event_system.cc:5868`):

```c
  /* Some painting operators want accurate mouse events, they can
   * handle in between mouse move moves, others can happily ignore
   * them for better performance. */
  if (event_last && event_last->type == MOUSEMOVE) {
    event_last->type = INBETWEEN_MOUSEMOVE;
    event_last->flag = eWM_EventFlag(0);
  }
```

Every sample survives, in queue order, carrying its own `xy` and tablet data.
Only the *type* of the older ones changes. Inbetween events are delivered to
modal handlers normally — that is how native sculpt reads them
(`paint_stroke.cc:1395`), and how `sculpt_uv.cc:958` and
`wm_gesture_ops.cc:572` do.

### 3.3 The addon — this is where they die

`SCULPTCORE_OT_brush_stroke.modal` (`stroke.py:1480`) matches only
`'MOUSEMOVE'`, `'LEFTMOUSE'`, `'RIGHTMOUSE'`/`'ESC'`. Every
`INBETWEEN_MOUSEMOVE` falls through to the bare `return {'RUNNING_MODAL'}` at
`stroke.py:1501` and is discarded. When the main thread stalls, the stroke
teleports to the newest position and the intervening hand motion is thrown
away **by the addon**, not by Blender and not by Windows.

**(S0) Fix: route `INBETWEEN_MOUSEMOVE` into `_dab_at` alongside `MOUSEMOVE`,
skipping only the cursor-pressure publish and the `_mid_redraw` tail** — the
same split native makes at `paint_stroke.cc:1600` ("Don't update the paint
cursor in `INBETWEEN_MOUSEMOVE` events"). The spacer already rejects samples
closer than the spacing step, so this adds dabs only where the hand genuinely
moved further than one step between frames — which is exactly the geometry
being lost.

Caveat to measure, not assume: consuming the backlog means *more* dab work per
frame, which lengthens the stall, which grows the next backlog. The spacer
bounds this (dab count is arc-length-driven, not event-driven), but a
pathological flick could still stack a large batch into one frame. The
existing `_batch` path (`stroke.py:1209`) is the mitigation and should be the
default for this. This is the first thing S0 must be benchmarked for.

`claudeMemory/scripts/bench_multires_sc.py:976` already synthesizes an
`INBETWEEN_MOUSEMOVE` backlog model, so the harness for grading S0 exists.

**Landed 2026-08-16** (`stroke.py`: `_MOVE_EVENT_TYPES` at the module level,
the `modal()` branch, and `_dab_at(..., redraw=)`). Two decisions the fix made
that the paragraph above did not spell out:

- **Preview and grab-class strokes still take only `MOUSEMOVE`.** Both re-base
  from the stroke start on every input — the preview methods roll back the
  provisional dab and re-apply (`stroke.py:_dab_preview`), and grab is anchored
  (`stroke_begin(anchored_grab=True)`, which makes each dab re-derive every
  touched vert from its stroke-start position). An intermediate sample there is
  overwritten before it can be seen, so consuming the backlog would be pure
  wasted apply, not fidelity. Only the spaced-dab path gained samples.
- **The redraw is per batch, not per sample.** `_dab_at` grew a `redraw`
  parameter; inbetweens sculpt and skip `_mid_redraw` entirely. A demoted run
  always terminates in a live `MOUSEMOVE` (the WM demotes the *previous* last
  event, never the newest), so the batch is always presented — and if the
  pointer stops, the final event is by construction a `MOUSEMOVE`, so a stroke
  cannot strand un-presented.

The `StrokeSpacer` needed no change: it carries `walk_carry` across segments
(`stroke.py:130`), so dab cadence is set by arc length, not by control-point
count. Denser control points fit the hand path better without dabbing denser —
which is the whole of the win, and also why the extra samples do not multiply
dab work in proportion to their number.

## 4. Architecture: the sample queue

Main thread collects, worker sculpts, draw path reads a published snapshot.

```
 main thread                         worker thread
 ───────────                         ─────────────
 modal(event)                        loop:
   sample = {                          drain ring -> samples
     x, y, pressure, tilt, twist,      driver.push(...) / poll()
     invert, time,                     for each spaced dab:
     view_mat, obj_mat, eye,             raycast engine BVH
     pixel_radius, spacing,              writeProps + apply (+ symmetry)
     strength, brush params }           mark nodes dirty
   ring.push(sample)                    publish snapshot (gen++)
   region.tag_redraw()
   return RUNNING_MODAL              (engine dab is itself node-parallel)

 draw handler
   draw pending-path polyline
   provider reads snapshot[gen]
```

**Everything Blender-owned is snapshotted into the sample.** The worker must
never touch `context`, `bpy`, the depsgraph, or an RNA pointer. That includes
the view matrices: `stroke_driver.push_view` (`stroke_driver.py:75`) currently
reads `context.region_data` at poll time, which a worker cannot do. The view
must travel *in the sample*, one snapshot per event, which is also more correct
— it pins each dab to the view that was live when the hand was at that point,
instead of to whatever the view is when the worker gets around to it.

**Ring, not a Python `queue.Queue`.** Single-producer / single-consumer,
fixed capacity, POD entries. If it is implemented in Python the GIL makes it
trivially safe but see §6.2; the C++ version is a plain SPSC ring on the
engine side behind `StrokeRun_push`.

## 5. Why this is tractable here and not in native sculpt

**During a stroke the engine owns its own copy of the mesh.** `convert.enter`
moves data in at mode-enter and `convert.flush` / `convert.exit_` move it back;
between those, dabs mutate engine memory exclusively. `_mid_redraw`
(`stroke.py:1009`) already documents this: with the draw provider active, the
Mesh ID is not touched mid-stroke at all — only the provider's GPU buffers are
refreshed, and the Mesh write-back is deferred to the mode's flush callback.

So a worker mutating engine state mid-stroke touches **no DNA, no depsgraph, no
`bContext`, no `Main`**. The usual structural reason Blender cannot thread this
does not apply to SculptCore. That is the single fact this whole design rests
on, and it is worth stating loudly because it is not true of native sculpt.

The corollary is the boundary condition: anything that crosses back into
Blender — `convert.draw_refresh`, `convert.flush`, `undo.push`,
`ob.update_tag`, `_publish_pivot` — stays on the main thread, without
exception.

## 6. The four hard parts

### 6.1 The external-draw snapshot (the real one)

Today `convert.draw_refresh` (`convert.py:1967`) calls
`sc_external_draw_update(session.draw_key)` from the main thread and tags the
object `{'SHADING'}`; the fork's draw engines then call into the provider
during drawing, also on the main thread, and read per-node buffers keyed by the
stable `node_id` (extdraw ABI v2). With a worker mutating nodes, that is a
straight data race: the provider can read a node mid-rewrite.

Requirement: **double-buffer with a generation counter.** The worker builds
into a back buffer and publishes atomically (`gen++`); `sc_external_draw_update`
becomes "adopt the newest fully-published generation" rather than "rebuild
now". The provider always reads a complete, self-consistent set.

The existing frame gate is the natural publish trigger — `_mid_redraw` already
throttles on `_frames_presented` (`stroke.py:1009-1035`), a counter maintained
by the `_on_viewport_draw` handler (`stroke.py:42`). That machinery survives;
only its meaning changes from "rebuild now" to "adopt the latest".

**This is an engine + extdraw-ABI change and it is the bulk of the work.** It
is also the part that cannot be prototyped in Python.

**Dyntopo is out of scope for the first version.** Topology changes invalidate
`node_id` sets, and the disappearing-geometry bug that motivated stable
`node_id` in the first place (see the extdraw node_id memory) is exactly the
failure mode a racing snapshot would reintroduce. Gate off-thread execution to
non-dyntopo sessions until §6.1 is proven.

### 6.2 The GIL, and where the consumer loop lives

`ctypes.CDLL` (`engine/python/sculptcore/_capi.py:266`) releases the GIL for
the duration of each foreign call, so a Python `threading.Thread` calling
engine functions does genuinely run concurrently with the main thread — a
Python worker is not a non-starter.

But the per-dab path is not one call. `_dab_at` → `_apply_spaced_dab` /
`_apply_batch` do real Python work per dab: `mapping.apply_dab_state`, the
`loadProps`/`writeProps` re-set dance (loadProps is destructive — see the
memory), curve evaluation, symmetry reflection, bpy RNA reads. The dab-loop
design measures that slice at **~0.2–0.33 ms/dab, ~20–28 ms/stroke**
([cpp-dab-loop.md §1](cpp-dab-loop.md)). All of it contends for the GIL with
the main thread's own Python — including the modal handler this design is
trying to keep fast. A Python worker would hand back a slower main thread than
it started with.

**Therefore: the consumer loop must be C++, and this design is gated on
[design/cpp-dab-loop.md](cpp-dab-loop.md) landing first.** Its Variant A
(`StrokeRunner`, one ctypes call per pointer event) is already almost this
design's worker — it just runs synchronously. Off-threading it is then "run the
runner on its own thread and give it a ring instead of a call", which is a much
smaller change than building both at once. Variant B (batched dab calls, math
stays host-side) is *not* sufficient here: it leaves the spacing walk and
per-point bookkeeping in Python.

Open: `litestl::task::parallel_for` is invoked from inside the dab apply. Is
the litestl task pool safe to invoke from a non-main thread, and does it
oversubscribe when its worker count already assumes it owns the machine?
(P-a in §11.)

### 6.3 Abort, and what "modally locked" means

Blender is *already* logically locked while a modal operator runs — the modal
handler owns the event stream and other handlers do not see it. What is missing
is only that the handler returns fast. So (G2) is satisfied by the queue alone;
nothing needs to be added to enforce the lock.

Two semantics to get right:

- **Release does not finish.** On `LEFTMOUSE`/`RELEASE`, set a pen-up flag and
  keep returning `RUNNING_MODAL` until the ring drains and the worker
  quiesces, *then* run `_finish` (`stroke.py:1292`) on the main thread. Its
  contents — `stroke_end`, `draw_refresh`/`flush`, `undo.push`,
  `_publish_pivot` — all cross back into Blender and must not move.
- **ESC aborts at dab granularity.** An atomic cancel flag the worker checks
  between dabs; the worker stops, the main thread joins, and `_finish(...,
  'CANCELLED')` runs the existing rollback. The delta-undo step still lands for
  whatever applied, which is already `_finish`'s documented behavior.

The trailing-spline flush at `stroke.py:1297` (`self._spacer.flush`) becomes a
"pen-up" message pushed into the ring rather than a direct call, so it stays
ordered behind the samples it follows.

### 6.4 Interaction with the grab/anchored class

`_dab_at`'s `self._grab_class` branch (`stroke.py:946`) anchors on a raycast at
stroke start and thereafter projects onto a plane, re-deriving `cursor` from
the *current* mouse each event with `accum_add` symmetry. It is stateful across
events in a way the spaced-dab path is not, and its dabs are cheap. Keep grab
on the synchronous path in v1; route only the spaced-dab class through the
queue. The `_grab_class` test is already the branch point.

## 7. The path preview (G3)

A `bpy.types.SpaceView3D.draw_handler_add(..., 'POST_PIXEL')` handler drawing a
polyline through the samples that are in the ring but not yet consumed —
region coordinates, already known main-thread-side, no engine involvement.

Two reasons it earns its place beyond the visual affordance:

- It is the debug view for whether the queue is keeping up. A path that stays
  short means the worker is ahead; a lengthening tail is the backlog made
  visible, without instrumentation.
- Under §9 it is where a fitted spline would be drawn, making the fit
  inspectable.

Draw it as a lead line (applied geometry behind, pending path ahead). Do not
attempt to fade or animate it in v1 — it is diagnostic before it is decorative.

## 8. What the main thread does per event, exactly

The target `modal()` body for a spaced-dab stroke, in order:

1. Accept `MOUSEMOVE` **and** `INBETWEEN_MOUSEMOVE`.
2. Read `event.mouse_region_x/y`, `event.pressure`, tilt, `event.ctrl`.
3. Snapshot the view: `rv3d.perspective_matrix`, `ob.matrix_world`, eye,
   region size, `clip_start` (what `stroke_driver.push_view` reads today).
4. Read the brush parameters that change per event —
   `mapping.pixel_radius`, spacing, strength, `_overlap`.
5. Push one POD sample. Ring-full policy: **block briefly, do not drop.**
   Dropping re-creates the bug this design exists to remove; a full ring means
   the worker is >N samples behind, which is a backpressure signal the path
   preview should already be showing.
6. `region.tag_redraw()` on `MOUSEMOVE` only (skip on inbetween, per §3.3).
7. Return `RUNNING_MODAL`.

Steps 2–4 are bpy RNA reads, measured at ~9 ms/stroke across ~84–151 samples in
the dab-loop profiling — sub-0.1 ms per event. That is the whole main-thread
budget per sample.

## 9. Relationship to G2-continuous stroke reconstruction

The user framed clothoid/G2 spline reconstruction as *the alternative*. It is
not an alternative; it is a different axis, and it is already partly built.

The engine's `BrushStrokeDriver` already owns a spline, an arc-length walk and
per-dab pressure interpolation — `stroke_driver.py:25-33` records that this is
"the whole of what is adopted", the driver running as a pure spacer with
host-side re-raycast. Upgrading its curve from the current Catmull-Rom-ish
basis (`crToBezier`, which the parity harness already found a NaN in) to a
curvature-continuous fit is a change inside one engine class, behind the
existing `sculptcore_cpp_stroke_driver` scene bool.

The division of labor:

- **Fitting improves the shape you infer from the samples you have.** It cannot
  invent pen-down timing, cannot reduce latency, and cannot recover a corner
  the hand made between two surviving samples.
- **The queue improves how many samples you have, and when.**

And the dependency runs one way: the single largest improvement available to
any fit is being handed the `INBETWEEN_MOUSEMOVE` samples currently discarded
(§3.3). Fitting a G2 spline through the stall-decimated sample set is fairing a
curve that has already lost the evidence of what the hand did. **S0 first,
fitting after, threading independently.**

## 10. Staging

Each stage is separately shippable and separately revertible.

- **S0 — consume `INBETWEEN_MOUSEMOVE`** (§3.3). **DONE 2026-08-16.** Passed
  the viewport half of its gate (A/B on a flick: the stroke follows the hand).
  The `bench_multires_sc.py` half — no stroke-time regression on the backlog
  model — was **never run**, so the §3.3 feedback-loop caveat (more samples
  consumed → longer frame → bigger next backlog) is unmeasured, not disproven.
  Run it if strokes ever start feeling like they lag rather than skip.
- **S1–S4 below are SHELVED** (2026-08-16, user call after S0). Kept as the
  costed option, not a queued plan.
- **S1 — measure the actual stall.** Memory has Clay at ~165–171 ms busy across
  ~71–74 frames — ≈2.3 ms/frame, which is *not* a stalling main thread. Find
  and record the configuration that genuinely stalls (which brush, which
  subdivision level, which dab count/frame) before building for it. If S0 plus
  the dab loop closes the gap at that configuration, S2–S4 may not be worth
  building.
- **S2 — the sample queue, still synchronous.** Introduce the POD sample, the
  ring, and the view-in-the-sample discipline, with the consumer drained
  inline at the end of `modal()`. Zero thread-safety risk; delivers the path
  preview (§7) and forces every `context` dependency out of the consumer path,
  which is the migration's real work.
- **S3 — the extdraw snapshot** (§6.1): double buffer + generation counter,
  ABI bump, still single-threaded. Independently verifiable — the provider
  reading generation N while the engine builds N+1 is testable without a
  worker.
- **S4 — move the consumer to a worker thread.** Non-dyntopo sessions only,
  behind a scene bool (`sculptcore_async_stroke`, default off), with the
  synchronous drain retained as the fallback path. Requires
  [cpp-dab-loop.md](cpp-dab-loop.md) Variant A (§6.2).

## 11. Open questions

- **(P-a)** Is `litestl::task::parallel_for` safe to call from a non-main
  thread, and what happens to its worker count if the caller is itself one of
  N threads? (`brush_executor.h:816`, `grid_executor.h:927`.) A wrong answer
  here does not kill the design but changes where the thread boundary goes.
- **(P-b) — RESOLVED 2026-08-16: yes, S0 alone closed it.** §3's argument held:
  on a pen under Windows the samples were all arriving, and the perceived
  "compaction" was entirely the addon dropping them. User verdict on a viewport
  A/B after S0 landed: *"that looks better"*, and the off-main-thread plan was
  shelved on the strength of it. So S2–S4 are now a **latency** project, not a
  fidelity one, and must be justified on latency numbers from S1 — not on the
  sampling argument that motivated this document.
- **(P-c)** What is the ring-full policy's real behavior under a flick? §8 says
  block-don't-drop; that converts a worker backlog into main-thread stall,
  i.e. back to today's behavior. Acceptable as a floor, but the depth needs a
  number and the path preview needs to make the state legible.
- **(P-d)** Mouse users still lose OS-level samples (§3.1). Is
  `GetMouseMovePointsEx` worth a fork-side GHOST addition, or is the pen the
  only input this needs to be right for? This is the *only* part of the whole
  design that would touch the fork.
- **(P-e)** Symmetry with `accum_add` and the multires grids path both assume
  a specific ordering of dab application. Confirm the worker preserves it —
  the ring is FIFO, but the batch variants may reorder within a batch.

## 12. What this design explicitly does not do

- It does not make sculpting faster (§1). The dab work is already parallel.
- It does not touch the Blender fork (except possibly P-d).
- It does not collect events off the main thread (§2) — the phrase "our own
  event queue" survives, but the queue sits *downstream* of Blender's WM, not
  in place of it.
- It does not cover dyntopo (§6.1) or grab/anchored strokes (§6.4) in v1.
