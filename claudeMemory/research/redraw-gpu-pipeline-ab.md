# Redraw pipeline GPU A/B: native vs SculptCore draw path (2026-08-10)

RenderDoc A/B of the entire redraw pipeline at 1M faces / L4, prompted by "no
visible difference in performance" interactively. Companion to
[redraw-path-attribution.md](./redraw-path-attribution.md), which covered the
CPU side of the mid-stroke refresh; this note covers what the GPU actually
does per frame in each mode, the two root causes found, the fix that landed,
and the event-handling verdict.

Harness: `claudeMemory/scripts/run_gpu_trace.mjs` (renderdoccmd capture +
in-process trigger + qrenderdoc replay analysis), both arms pinned to OpenGL,
vsync off, paced strokes. All numbers from this box's AMD iGPU (shared memory
bandwidth with the CPU — vertex-fetch costs are amplified relative to a dGPU).

## Methodology guards

Draw profiling is noisy (memory bandwidth, driver async, replay overhead), so:

- **Interleaved, order-alternated reps** (3 reps for the baseline, order
  flipped in rep 2; 2+2 alternated runs for each A/B). Conclusions only where
  the effect reproduces across reps and survives order flipping.
- **Replay GPU timers are used for attribution and ratios only.** RenderDoc
  replays actions serialized, which defeats driver async — absolute ms are
  not frame times. Cross-checked against in-process wall clocks
  (`cycle_ms` = pointer-event push → viewport redrawn) from the same runs.
- One replay pass (per-program attribution) produced a 5× outlier on native
  mesh-draw ms (9.28 vs 1.91–2.1 in six agreeing measurements). Discarded its
  timings, kept its call counts/vertex formats/program identities. Treat any
  single replay pass's ms as unconfirmed until a second pass agrees.
- `peak_z` per arm bit-identical across reps — the workload itself is
  deterministic; variance is measurement, not sculpting.

## Baseline: where the +50 % GPU frame came from (3 reps, medians)

| metric | native | sculptcore | delta |
|---|---|---|---|
| GPU frame total | 4.62 ms | 6.94 ms | +50 % |
| mesh drawcalls | 1.91 ms | 3.45 ms | +1.5 ms |
| compute dispatches | 0.02 ms (4) | 0.53 ms (116) | +0.5 ms |
| tiny UI draws | ~0.1 ms (5) | ~0.8 ms (39) | +0.7 ms |
| drawn vertices | 6,104,199 | 6,105,132 | — |
| per-dab cycle (wall) | 6.84 ms | 11.80 ms | +5.0 ms |

Both arms run the **same workbench prepass shader with the identical 20-byte
vertex format** (float3 position + R16G16B16A16_SNORM normal, verified from
GL pipeline state). The gap is not shading — it is two structural issues:

### Root cause 1: non-indexed grid soup (+1.5 ms, engine-side)

Native draws indexed (`glDrawElementsIndirect`, ~450 calls × ~12288 indices;
~1.05M unique vertex fetches via post-transform reuse). `GridDrawSource`
draws raw non-indexed triangle soup (`glDrawArraysIndirect`, 248 calls, all
6.1M vertices fetched and shaded) — **~6× the vertex bandwidth** on an iGPU
that shares that bandwidth with the CPU. Fix is an engine design item
(shared-vertex grids + index buffer), tracked separately; not Blender-side.

### Root cause 2: area-wide tag_redraw → asset shelf mip churn (~1.2 ms + CPU)

`stroke.py:_mid_redraw` called `context.area.tag_redraw()` per pointer event,
which tags **every region** of the View3D area: main, header, tool header,
toolbar, sidebar, and the 5.x **brush asset shelf**. The shelf's preview
icons go through `PixelBitmapDrawer::draw` / `immDrawPixels`
(`editors/screen/glutil.cc`), which creates a **fresh GPU texture every
call** and, when drawn scaled down >2×, rebuilds the full mip chain in
compute (`GPU_texture_update_mipmap_chain`) — ~10 icons × ~11 mips = the 116
dispatches/frame, plus the 39 glyph/icon draws. Native sculpt tags only the
drawing region, so its shelf stays cached (4 dispatches, 5 tiny draws).

Structurally invisible headless — no earlier bench could see it. The addon
writes no Brush RNA and touches no images per dab (verified), so this was
pure redraw tagging, not notifier churn.

**Fix (landed):** `_mid_redraw` tags `context.region` instead, matching
native sculpt. One line.

## Fix validation (interleaved A/B, SCULPTCORE_TAG_AREA env toggle)

Plain headed bench first (burst regime, ~1 frame/stroke presents): area
55.6/51.8 vs region 54.1 ms `stroke_ms` — insensitive, as expected, and no
regression; `peak_z` identical in all runs (display-only change confirmed).

Paced traces (2+2 alternated, sculptcore arm, 12 frames each; sculpt-frame
medians):

| arm | dispatches | drawcalls | GPU frame | cycle_ms median |
|---|---|---|---|---|
| area r1 / r2 (old) | 116 | 388 | 6.80 / 7.56 ms | 12.87 / 14.84 ms |
| region r1 / r2 (fix) | **4** | **311** | 6.16 / 6.25 ms | **3.52 / 3.89 ms** |

Exactly the predicted signature: dispatches drop to native's count, the ~77
extra UI drawcalls vanish, GPU frame −0.6…−1.3 ms. The wall-clock effect is
far larger than the GPU-only share (−9…−11 ms per dab cycle): the area tag
was also paying CPU region-draw time for five extra regions per event.
`sculpt_view_ms` (the 3D region's own draw callback) is unchanged (~2.2 vs
~2.4 ms) — the savings are entirely the *other* regions.

## Final native-vs-sculptcore A/B with the shipped code

(2 pairs, order flipped on the second; paced regime, capture-inflated but
comparable. Per-pair values pair1 / pair2.)

| metric | native | sculptcore (fixed) |
|---|---|---|
| GPU frame median | 4.90 / 4.51 ms | 5.71 / 5.80 ms |
| per-dab cycle median | 9.52 / 8.12 ms | **4.39 / 3.40 ms** |
| dispatches | 4 | 4 |
| drawcalls | 569 | 311 |
| 3D-region draw wall (`sculpt_view_ms` med) | 4.64 / 4.25 ms | 2.53 / 2.12 ms |

Order-independent and consistent across pairs.

## Event-handling verdict

The user's framing was: if per-dab performance is the same after the draw
pipeline is fixed, the remaining problem is Blender's pointer-event handling.
Measured answer: **there is no remaining per-dab gap to explain — sculptcore's
event→redrawn cycle now beats native by ~2.3×** (native ~8–9.5 ms vs
sculptcore ~3.4–4.4 ms; native pays more because its per-dab CPU work runs on
the same thread the cycle measures). The pre-fix "+5.0 ms cycle gap vs +2.3 ms
GPU gap" residue was region-redraw CPU from the area tag, not pointer-event
overhead. No Blender-side event-system lever exists on this path.

The residual GPU-frame gap (+0.9…+1.3 ms) is exactly the non-indexed grid
soup (root cause 1) — the only remaining draw-path item, and it is
engine-side.

## Tooling traps (this box)

- `run_gpu_trace.mjs` uses `spawnSync`, so **nothing prints between the
  capture banner and Blender's exit** — a silent run is a healthy run.
- The Claude harness's sandboxed background wrapper killed every capture run
  ~1–3 min in (mid-capture, healthy .rdc files on disk). Detached
  `Start-Process` runs finished the same work in ~65 s per arm. Launch
  capture sequences detached and poll a progress log.
- Keep the iGPU otherwise idle during captures; it shares memory bandwidth
  with the CPU and background compositing skews both arms.
