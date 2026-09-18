# Plan 3 completion: event inputs and execution adoption

Status: completed 2026-09-17; original gate passed. Reviewed by fresh review_plan3_events and review_plan3_execution;
their corrections below are mandatory, 2026-09-16. Do not mark Plan 3 complete
until every remaining task and its original acceptance gate passes. Begin Plan 4
only after that gate. Preserve the existing bounded execution gates and unrelated
working-tree changes in all three repositories.

## A. Generic event acquisition API

- Add a double acquisition time in seconds and an explicit time-presence bit to
  wmEvent. Populate from the already delivered GHOST millisecond event time;
  preserve it when queued moves become INBETWEEN_MOUSEMOVE. Internally generated
  events without a source time must not inherit a stale valid timestamp.
- Add independent pressure/tilt-X/tilt-Y presence bits to GHOST_TabletData and
  wmTabletData. Initialize every platform/default path. Windows Pointer API uses
  its per-packet penMask; Wintab uses established device axis capabilities.
  Other backends advertise channels only when their acquisition path establishes
  validity. Missing channels do not become zero samples. Mouse pressure is 1.
- Expose Event.time, time availability and input validity through RNA without
  rounding the time to float. Extend Window.event_simulate with optional explicit
  time and tablet samples/presence; validate finite ranges before queue mutation.
  Old simulation calls remain valid and have no acquisition time.
- Test real queued synthetic events, INBETWEEN delivery, time precision, zero
  tilt versus absent tilt, missing time, invalid parameters and unchanged defaults.
  Build the existing fork install tree and run background/headed checks through
  the established dialog-safe infrastructure.

## B. Per-dab sampling in the actual modal path

- Use an immutable input sample containing pressure, normalized tilt axes, speed,
  time and channel presence. Speed follows contract v1 acquisition-time semantics
  and positive configurable reference (default 1000 screen pixels/second).
- Extend the existing StrokeSpacer/arc walker to associate each emitted point
  with its source segment and traveled-arc fraction. Keep position-only helpers
  compatible. Interpolate inputs from the two segment endpoints, not the latest
  event or cubic parameter. Preserve lookahead, constant-pressure geometry,
  residual release flushing, INBETWEEN events and stroke resets.
- Feed fresh samples on every Python, raw/grab/preview and batch dab; symmetry
  copies device samples unchanged. Clear absent channels every dab. Expose only
  pressure, tilt and speed where available; twist/angle/curvature stay unavailable.
- Add versioned/additive batch entry points with per-dab sample arrays; existing
  constant-pressure batch entry points keep their ABI. Compact sample rows using
  the same hit indices as compacted geometry. Validate buffers before writes.

## C. Checked execution adoption

- Expose the bounded prepared mesh/grid standalone and program entries through
  additive native/Python APIs and typed command setters. Add resolved batch entry
  points using the same preparation, region selection and error contracts.
- Keep raw legacy source semantics explicit. Validate configured stacks on every
  invocation, including nonfirst/empty dabs and programs before dyntopo, hooks,
  topology, capture and filtering owned by the entry. Unsupported resolved modes
  fail explicitly; no fallback may silently drop dynamics. Preserve raw baselines.
- Adopt the checked path where its capabilities permit and propagate failures
  through addon scalar, batch and preview boundaries. Complete remaining
  capability work required by Plan 3; independent per-command inheritance,
  custom host hooks dependent on command configurations and general resolved
  collection adoption remain Plan 6 as the original plans specify.
- Test actual typed float/int/bool kernel geometry through standalone/program
  mesh/grid/batch APIs, invalid late/nonfirst state, expanded regions, working
  restoration, errors, undo, and legacy constant-pressure parity. Regenerate
  affected binding declarations and use exact-DLL Python checks.

## D. Original completion gate and Plan 4 transition

- Deterministic straight and curved uneven-knot tests pin arc interpolation,
  missing-channel handling, timestamp reset and release behavior. Delayed handler
  delivery and different batch grouping must produce the same samples/geometry.
- A headed harness drives the actual modal operator using explicit synthetic
  pressure/tilt/time, with multiple dabs from one event, Python and C++ batch
  execution, mesh/grid coverage and cancellation/undo. Record assertions, timeouts
  and completion markers; do not substitute a dormant helper test.
- Run applicable native, compiler/backend, exact-DLL Python and Blender gates,
  restore addon-only outputs and record hashes/evidence. Audit every remaining
  Plan 3 checkbox against the original task list before completion.
- Then implement Plan 4's registry/persistent Brush/Scene schema and resolver
  truth tables against the frozen inventory and real owned CurveMapping API,
  after its implementation choices receive adversarial review.

## Folded adversarial corrections

- RNA floats narrow to 32 bits. Event.time will be a C/Python double getset on
  RNA-backed Event, with ordinary RNA availability booleans. Additive
  Window.event_simulate_input validates new time/tablet/sample keywords before
  delegating legacy arguments and synchronously completing the queued event.
  Original event_simulate clears acquisition metadata. This is not a new double
  PropertyRNA type. The new simulation path must share the native motion queue's
  previous-move retyping, without changing old simulation semantics.
- Acquisition-time provenance travels with GHOST cursor/button data, defaults
  unavailable, and is enabled only for audited source timestamps. Windows mouse,
  Pointer and Wintab are the initial supported producers. Normalize 32-bit
  Wintab time onto the existing GHOST monotonic clock using wrap-safe deltas.
  Other platforms conservatively report unavailable acquisition time/channels
  until their device producers are audited; do not claim their device support.
  Shared defaults initialize presence. No synthetic cursor warp is acquisition.
- Acquisition metadata remains event-owned, outside flags cleared by INBETWEEN
  conversion and outside persistent eventstate. Clear generated head/tail moves;
  cross-window forwarding explicitly copies source metadata. Headed simulation
  tests must exercise the shared queue conversion, not just named INBETWEEN input.
- Untimed first samples have no speed. Missing real input time, duplicate and
  decreasing times reset the derivative anchor; a following valid sample starts
  at speed zero. Internally generated moves must be distinguishable and must not
  affect sampler/derivative history. Stationary real input retains its timestamp.
- The addon always maps falloff to a curve LUT. Admit and validate real mapped
  LUTs before claiming adoption; test their actual endpoint/support semantics.
  Typed authored handoff is required for adopted dynamic extras because the old
  engine_props mapper writes only raw float working storage.
- Raw preflight needs scratch factories, complete numeric-stack and canonical
  identity checks, union program scope and an explicit raw/authored source
  distinction. It precedes live factories, empty filtering, dyntopo and hooks.
  Repaired calls must recover; first-dab-only sticky validation is insufficient.
- Raw preview may remain explicitly raw, but validate before rollback/capture;
  reject unsupported resolved preview before capture. Status must propagate
  through standalone/grab/dyntopo/grid, symmetry and release flushing. A rejected
  later batch dab keeps earlier successful dabs in the stroke's undo transaction;
  report failure and never retry through another policy.
- Batch input shape, pointers, counts, finite values and presence bits validate
  before writes. Overlay only radius/strength/invert, never writeProps from
  previously evaluated caches. Preserve grid slot mirroring and draw marking.
- Prebatch raycasts observe a different surface from sequential evolving casts.
  Sampler output must be grouping-independent; geometry equality uses prescribed
  hits or a fixture where ray intersections do not change. Do not claim general
  geometry invariance for the existing prebatch raycast algorithm.
- Completion evidence includes actual public typed geometry on standalone and
  program/nonprogram mesh/grid batches, above-2^24 integers, bool thresholds,
  missing channels, nonfirst/empty/repaired failures, radius expansion and undo.
  Native event tests require explicit GTest configuration (existing install
  caches disable it); shared queue behavior may instead be covered by the real
  headed path with explicit assertions. Platform-specific gates remain honest.
