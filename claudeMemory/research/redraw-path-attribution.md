# Redraw-path attribution and the mid-stroke frame gate (2026-08-10)

The post-dab-loop stroke profile put ~14 ms/stroke in "redraw machinery"
(`draw_refresh` ~8.6 + `_mid_redraw` ~5.7, 1M faces / L4). This note records
what that time actually is and the fix that landed.

## Attribution (instrumented headed bench, 19 strokes)

Temporary timers split the slice per component:

| component | total | per stroke | per call |
|---|---|---|---|
| `GridStroke_flushNormals` (deferred normal resolve + mirror-to-slot) | 103 ms | 5.4 ms | 2.9 ms |
| `sc_external_draw_update` (`GridDrawSource::update` — dirty draw-node soup refill) | 159 ms | 8.4 ms | 2.9 ms |
| `ob.update_tag(refresh={'SHADING'})` | 2.5 ms | 0.13 ms | 45 µs |
| `context.area.tag_redraw()` | 1.7 ms | ~0 | ~4 µs |

Two conclusions:

- **~96 % of the slice is engine-side CPU work** (normal resolution + eager
  triangle-soup refill of dirty draw nodes: pos/no/mask, 42 floats per cell,
  `fillNode` refills a whole node when any of its rows is dirty). The
  Blender-side tagging (`update_tag`, `tag_redraw`) is noise — optimizing it
  is a dead end.
- **The refresh cadence, not the refresh cost, was the bug.** The bench
  presents exactly one frame per stroke, but the 30 Hz wall-clock throttle in
  `_mid_redraw` fired ~2.9 refreshes per stroke. A refresh is display-only
  (queries use the spatial tree's `updateQueries`, undo reads positions), so
  every refresh not followed by a presented frame is pure waste — the next
  pass refills the same overlapping dirty nodes and only the fill current at
  draw time is ever uploaded.

## The fix: gate on frame consumption

`_mid_redraw` now flushes only when the wall-clock throttle passes AND a
viewport frame has presented since the last flush (`_frames_presented`,
counted by a `POST_PIXEL` draw handler that lives only while a stroke runs —
push in `invoke`, pop in `_finish`/`_finish_preview` and the post-push
anchored-refusal return). The gate starts closed at stroke start; the first
refresh waits ≤ one frame period for the frame `invoke`'s own `tag_redraw`
requests.

**Above 30 fps the gate is provably inert**: the frame period (≤33 ms) is
shorter than the throttle interval, so a frame always presents between two
throttle passes and behavior is bit-identical to before. It engages only when
events outrun frames — synthetic event floods (the bench) and frame-bound
heavy scenes, where the waste hurts most.

## Measured (interleaved A/B, 4 pairs, 1M/L4, medians of per-run medians)

| metric | wall-clock only | + frame gate | delta |
|---|---|---|---|
| `stroke_ms` median | 65.0 | 55.3 | **−14.9 %** |
| `stroke_ms` mean | 65.0 | 54.9 | −15.5 % |
| `sculpt_phase_ms` | 1810 | 1552 | −14.3 % |
| `sculpt_frames` | 102 | 102 | identical |
| per-run medians spread | 59.9–77.0 | 54.7–56.9 | — |

`peak_z` identical (0.059032) in all 8 runs — display-only, as designed. The
treatment arm's far tighter spread is expected: whether a wall-clock pass
lands inside a stroke was timing luck; the gate removes that nondeterminism
(this also makes future stroke_ms A/Bs cleaner).

Validation: headed `test_stroke_cancel.py` green after the change (the
draw-counter push/pop must balance through ESC and window-close `cancel()`).

## What remains of the redraw slice

With the gate, the bench pays ~1 refresh per stroke (~5.8 ms: one
`flushNormals` + one `GridDrawSource::update` at stroke end feeding the
frame). Cutting deeper means cutting per-call cost, ranked:

- `fillNode` refills pos+no+mask and recomputes the AABB for the whole node
  even when one row band is dirty; mask is untouched by geometry brushes.
- `flushNormals` re-resolves the same overlapping verts each pass (inherent
  to closely-spaced dabs; already minimized by the lower cadence).

Neither is worth touching until the bigger post-gate buckets (engine dab
execution ~21 ms, `stroke_end` ~7 ms, per-hit Python helpers ~6–8 ms) are
addressed — see `multires-stroke-performance.md` for the standing tree.
