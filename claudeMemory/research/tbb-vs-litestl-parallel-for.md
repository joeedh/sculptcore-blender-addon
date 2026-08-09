# TBB vs. litestl's pool for `task::parallel_for`

**Date:** 2026-08-09 · **Verdict:** keep the litestl pool; TBB is ~4% slower and
much less predictable. The experimental backend was measured, then reverted —
nothing from it is in the tree.

Raw JSON for all six runs is in
[`../scripts/bench-tbb/`](../scripts/bench-tbb/).

## Why the question came up

`litestl::task::parallel_for` (`engine/source/litestl/util/task.h`) and Blender's
`blender::threading::parallel_for` (`BLI_task.hh` + `intern/task_range.cc`) solve
the same problem differently, and the difference is structural rather than
cosmetic.

**Blender's is a façade over Intel TBB.** It does an empty-range early-out and a
`use_single_thread()` check, then hands off to
`tbb::parallel_for(tbb::blocked_range<int64_t>(...))`. Without `WITH_TBB` it
degrades to a serial `function(range)`. There is no Blender-owned worker pool on
this path.

**litestl's is a complete scheduler**: per-worker LIFO queues, work stealing,
cache-line-aligned workers, lazy thread spawn, spin-then-park on a shared cv.

The algorithmic gap is **static bands vs. recursive splitting**:

- litestl partitions once, up front —
  `submission_count = min(worker_count, ceil(size/grain))` (`task.h:340`). Bands
  are fixed, the caller runs the last one inline, `cb` is invoked exactly once
  per band. Stealing balances *across* submissions, never *within* one
  `parallel_for`. A band that turns out 5× more expensive than its neighbours is
  a straggler nothing can subdivide.
- TBB keeps halving `blocked_range` while the auto-partitioner thinks it is
  worthwhile, so a thread that finishes early steals *and re-splits*. Subrange
  count is dynamic.

Blender layers more on top: `TaskSizeHints` (`BLI_task_size_hints.hh`) lets a
caller declare relative per-task cost, and `lazy_threading` keeps work
single-threaded until a task announces mid-execution that it will run long.
litestl has neither — `grain_size` is one uniform-cost scalar.

The hypothesis worth testing was therefore: **does the engine's real workload
have enough per-index cost irregularity for recursive splitting to pay?**

## The experiment

A temporary `LITESTL_WITH_TBB` backend inside `parallel_for`, linked against the
TBB bundled in the Blender fork's `lib/windows_x64/tbb` — the same `tbb12.dll`
Blender itself loads, so inside Blender the engine joined Blender's existing
arena instead of oversubscribing against it.

Correctness gate: **125/125 native ctest passed** under the TBB backend. No
caller depends on band count, `worker_count()`, or a per-band buffer, so the
once-per-band → many-per-thread change in `cb` invocation was safe.

Benchmark: `claudeMemory/scripts/bench_multires_sc.py --engine sculptcore
--grid 64 --level 4` (1,016,064 faces / 1,018,081 verts), headed, three repeats
per configuration, rebuilt and restaged between configurations.

## Results (3 runs each, mean and range)

| metric | TBB | litestl pool | delta |
|---|---:|---:|---:|
| `enter_mode_ms` | 1994.7 (1950–2030) | 1992.3 (1974–2012) | +0.1% |
| `sculpt_phase_ms` | 2390.5 (2312–2545) | 2301.2 (2296–2307) | **+3.9%** |
| `stroke_ms` mean | 80.4 (78.3–84.4) | 76.3 (75.7–77.0) | +5.3% |
| `stroke_ms` median | 80.9 (80.2–81.9) | 78.0 (76.8–79.0) | +3.8% |
| `stroke_ms` p90 | 99.2 (90.7–111.5) | 97.1 (92.3–101.4) | +2.1% |
| `cycle_ms` median | 27.2 | 27.7 | −1.7% |
| `idle_view_ms` median | 2.2 | 2.2 | +2.2% |

Every run finished 19/20 strokes with `peak_z` 0.114154–0.114155, so the work
was identical; the residual fp difference is summation order.

**The most robust signal is variance, not the mean.** TBB's `sculpt_phase_ms`
spans 233 ms (10%); the pool's spans 11.6 ms (0.5%). A static partition does the
same thing every dab, where TBB's partitioner makes scheduling decisions that
differ run to run. For interactive sculpting that predictability is worth more
than the 4% mean, and it is the stronger argument for keeping the pool.

`cycle_ms` is vsync-quantized (~16.7 ms floor, see
[[native-sculpt-headed-benchmark]]) and cannot resolve a few percent of CPU, which
is why the difference is invisible interactively — confirmed by hand before the
numbers were taken.

## What this says about the workload

The engine's `parallel_for` call sites are mostly flat sweeps over vertex, grid
and node arrays with near-uniform per-element cost — exactly the case a static
equipartition handles optimally, and exactly the case where recursive splitting
charges dispatch overhead for splits that buy nothing. The irregularity TBB is
built to absorb is not present in this path at this size.

## Methodology note

The first TBB run alone showed +10.6% on `sculpt_phase_ms` and +20.8% on p90,
and that was briefly reported as decisive because the *control's* spread was
0.5%. That was wrong: TBB's own variance is 10%, so a single TBB run could not
support the claim no matter how tight the control was. n=3 per configuration cut
the sculpt-phase delta to +3.9% and the p90 delta to +2.1%. **Measure the
variance of the arm you are making the claim about, not the other one.**

## Not tested — the one case TBB should win

Some call sites are hand-flattened around the litestl pool's nesting hazard
(`spatial.cc:1522`: "Nested parallel_for is avoided"), because a worker blocked
in `Joiner` waits on the cv rather than stealing, so nested waits can starve a
bounded pool. TBB's blocking waits participate in the task graph and cannot
deadlock that way. Those sites stayed flattened for the A/B, so TBB never got to
exploit its one structural advantage. Unflattening one and re-measuring is the
obvious follow-up if this is revisited.

Two further conditions favoured TBB and it still lost: it shared Blender's arena
(no oversubscription penalty), and `enter_mode` — the most allocation-heavy
phase — was a dead heat.

## If this is ever redone

The backend was four edits, all marked `CLAUDENOTE:` and all reverted:

- `engine/source/litestl/util/task.h` — `#ifdef LITESTL_WITH_TBB` branch in
  `parallel_for` wrapping `tbb::parallel_for(tbb::blocked_range<int>(...))`,
  sharing the existing small-range early-out. Native pool untouched.
- `engine/source/litestl/util/CMakeLists.txt` — `PUBLIC LITESTL_WITH_TBB` +
  `SYSTEM PUBLIC` include on the `util` target.
- `engine/CMakeLists.txt` — `option(WITH_LITESTL_TBB)`, TBB located under
  `BLENDER_LIB_DIR`, `tbb12.dll` registered with `sculptcore_add_runtime_dll`,
  cache vars unset on the OFF pass so the toggle is clean both ways.
- `engine/make.mjs` — `SCULPTCORE_LITESTL_TBB=1` env → `-DWITH_LITESTL_TBB=ON`;
  `bundle` carries `tbb12.dll` into the vendored `lib/sculptcore/`.

Restaging between arms is `node make.mjs configure python` then
`node tools/build-blender-dist.mjs --skip-blender`, and no Blender may be running
(it holds the vendored DLL open).
