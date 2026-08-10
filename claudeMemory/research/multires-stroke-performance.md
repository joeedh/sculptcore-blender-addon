# Why SculptCore multires strokes are slower than native sculpt

Investigation of the report that *"sculptcore's multires on moderately
high-poly meshes (>300k faces, >4 subdivision levels) is slower than native
sculpt mode's — on optimized builds only."* Confirmed, quantified, and
partially fixed. This note records the measurement rig, the full cost
breakdown, what was fixed, and what is left.

**No optimization flags were disabled anywhere.** Both builds are
RelWithDebInfo (`-O2 -DNDEBUG -g`); no `optnone` attribute was used at any
point, so every number below is an optimized-vs-optimized comparison.

## The rig

`claudeMemory/scripts/bench_multires_sc.py`, headed, run against the fork build:

```
blender.exe --factory-startup --no-window-focus -p 0 0 1280 800 \
  --enable-event-simulate --python-exit-code 1 \
  --python claudeMemory/scripts/bench_multires_sc.py -- \
  --out <path> --label X --engine sculptcore|native \
  --grid 64 --level 4 --mode multires [--profile] [--engine-trace]
```

Both engines are driven by the *same* synthesized event stream
(`Window.event_simulate`), so the drive mechanism cannot bias the comparison.
Grid 64 / level 4 = **1,016,064 faces, 1,018,081 verts**. Draw brush, size 50,
spacing 10, strength 0.1. 19 finished strokes over 102 frames.

The metric is **`sculpt_phase_ms`** — wall time for the whole sculpt phase,
reported identically by both engines. `cycle_ms` saturates at the vsync quantum
and hides per-dab cost; don't use it.

### The bench is not deterministic

Run-to-run spread on `sculpt_phase_ms` is roughly **±150 ms**. `surface_after.peak_z`
varies by ~4e-6 between runs, so **it is not a usable correctness canary**.
Any single-run delta under ~150 ms is unresolvable — read the `[phase]` /
`func_trace` aggregates instead, which are far less noisy.

All final numbers are taken on a tree with every piece of temporary
instrumentation removed from both the engine and the fork. The instrumented fork
measured native at 970 ms, so the earlier native reference was ~65 ms pessimistic.

### Correction: the 4030 ms figure was partly a bug

An intermediate sculptcore reading of 3889 / 4022 / 4181 ms was reported before
the full test suite had been run against the tree. It was not real. Dropping the
AABB reset in `regen_node_bounds` (see *Two regressions the full suite caught*)
was worth ~1300 ms of it, by letting leaf bounds accumulate instead of being
recomputed. Measured directly, same tree, only that hunk differing:

| `regen_node_bounds` reset | `sculpt_phase_ms` |
|---|---|
| removed (wrong, fails `test_dyntopo_collapse_crash`) | 3756 / 3731 |
| present (correct, baseline behaviour) | 5168 / 5027 |

The honest post-optimization number is therefore **~5.0 s**, not ~4.0 s.

## The gap

Measured end to end, all on the same machine and the same 102-frame / 19-stroke
bench. The **baseline** column is the untouched tree — every change in this work
stashed across all three repos (engine `source/` + `python/`, the litestl
submodule, and `sculptcore_addon/`):

| | native | sculptcore (baseline) | sculptcore (now) |
|---|---|---|---|
| `sculpt_phase_ms` | **~857 ms** | **~87,800 ms** | **~5,000 ms** |
| vs native | 1× | ~102× | ~5.9× |

Baseline samples: 91,394 / 87,633 / 84,364. Final samples on the shipped tree
(both regressions fixed, full ctest green): 5,190 / 5,020 / 4,935. So the work is
a **~17× speedup**,
and it closes most of the distance to native without changing the architecture —
but it does not close the gap, and the remaining ~6× is structural (below).

The per-dab breakdown below was taken at the ~4 s intermediate point, so read its
absolute figures as ~25% optimistic; the *proportions* and the attribution still
hold, and native's side of the table is unaffected:

| | native | sculptcore |
|---|---|---|
| per stroke | ~18–20 ms | ~158 ms |
| dabs per stroke | 82 | 42–43 |
| per dab (whole dab path) | 0.24 ms | 1.84 ms |
| region verts per dab | 38,880 (16,807 in radius) | 34,130 |
| `enter_mode_ms` (one-time) | 160 ms | 15,576 ms |
| `idle_view_ms` (draw only) | 0.79 ms | 2.24 ms |
| `undo_memory` | 10.6 MB | 190 MB |

So the per-dab cost is **~7.7× native at a comparable or smaller region**.
SculptCore does about half as many dabs per stroke (a spacing-parity
difference — vanilla's spacing uses `brush.size/2` as the pixel size where
sculptcore uses `brush.size`), which *flatters* sculptcore here: matching
vanilla's dab count would roughly double its stroke cost.

## Full attribution

From `--engine-trace` (nesting shown by indent; a parent's total includes its
children):

```
_dab_at                          2212.0 ms   380 calls   5.821/call   (modal per-move handler)
  _apply_spaced_dab              1823.5 ms  1444 calls   1.263/call
    raycast                       174.1 ms  1444 calls   0.121/call
    _apply_one_image             1485.4 ms   800 calls   1.857/call
      apply_dab                  1472.8 ms   800 calls   1.841/call
        _refresh_queries          332.5 ms   800 calls   0.416/call
    (spaced-dab python)           164   ms                            residual
  _mid_redraw                     314.7 ms   380 calls   0.828/call
_finish                           809.0 ms    19 calls  42.579/call
  undo.push                       748.1 ms    19 calls  39.371/call
    convert.multires_store_blob   730.6 ms    19 calls  38.454/call
draw_refresh                      354.2 ms    83 calls   4.268/call
cursor.draw                        26.7 ms    19 calls   1.405/call
mapping.apply_dab_state            24.9 ms   800 calls   0.031/call
```

Top-level sum ≈ 3402 ms of 3952 ms; the remaining **~550 ms** is Blender's own
event loop, viewport draw and depsgraph flush.

### Inside the dab (engine `ExecPhaseTimers`, aggregated over 800 dabs)

| phase | ms/dab | total |
|---|---|---|
| kernel | 0.4388 | 351.1 |
| capturePre | 0.4043 | 323.5 |
| stampBase | 0.0876 | 66.4 |
| border | 0.0849 | 64.3 |
| createCmd | 0.0024 | 1.9 |
| ebPrologue | 0.3193 | 255.5 — but 251.67 of that is one one-time `ebFreeze` |
| **dabTotal** | **1.3590** | 1087.1 |

Steady-state per dab ≈ **1.02 ms**, of which **kernel + capturePre = 0.84 (82%)**.
Add `_refresh_queries` (0.42) and the Python wrapper and you get the observed
1.84 ms.

`kernel` at 0.4388 ms for 34,130 verts across 12 worker threads is ~156 ns of
CPU per vertex — roughly 10× what a Draw brush's arithmetic costs. The cost is
iteration and indirection, not math.

### Inside the undo snapshot (`[blobsplit]` / `[gridser]`, per stroke)

| step | ms |
|---|---|
| `Multires_writeback` | 12.9 |
| `Multires_serializeStore` | 27.5 |
| &nbsp;&nbsp;rehydrate (`ensureLevelResident` ×4) | 0.00 (already resident) |
| &nbsp;&nbsp;metadata (`std::stringstream`, 63,504 links + 89 chunks) | 3.9 |
| &nbsp;&nbsp;assemble (memcpy 22.1 MB payload) | 7.0 |
| &nbsp;&nbsp;compress (12 × 2 MB parallel lz4 → 9.2 MB) | 7.5 |
| &nbsp;&nbsp;out (memcpy 9.2 MB) | 3.3 |
| &nbsp;&nbsp;residual (an extra full 9.2 MB alloc+memcpy) | ~5 |
| ctypes `string_at` copy | 2.3 |
| **total** | **~40 ms/stroke, 760 ms over the bench** |

The metadata and residual rows are the two that were subsequently fixed (see the
table below), taking this to roughly **31 ms/stroke**.

`Multires::writeback(level)` is O(*whole level*) — a `parallel_for` over all
1,018,081 verts copying `lm.v.co[i]` and `memcmp`ing against a baseline to build
a `changed` mask — not O(edited region). It is already parallel, so it is
bandwidth-bound.

**The blob is a fallback that is almost never read.** `undo.decode()` only uses
it when `generation != session.generation or session.meshlog is None` — i.e.
after a level switch or an earlier blob restore reset the meshlog. Normal undo
replays the meshlog. It is nonetheless load-bearing for correctness across a
level switch, so it cannot simply be dropped.

## Root cause

SculptCore materializes multires level 4 as a **full `mesh::Mesh`** — 1,018,081
verts, 1,016,064 faces, ~4 M corners, complete topology (disk/radial cycles), a
spatial tree over it, per-element attribute columns, and per-element undo capture
through a stamp gate — then writes the result back into the grid store.

Native Blender sculpts the **CCG grids in place**: flat contiguous per-grid
position arrays, no mesh topology, no attribute-layer indirection, per-grid-block
undo (a memcpy of contiguous floats), and per-grid bounding boxes instead of a
BVH over a million triangles.

That difference is the dominant term. It explains the kernel's per-vertex cost
(iterator + attribute indirection vs a `float3*` walk), `capturePre` (a per-vertex
gated row copy vs a block memcpy), `_refresh_queries` (BVH bound/normal refresh vs
per-grid BBs), the 15.6 s mode enter, the 190 MB undo footprint, and the 2.8×
idle draw cost. **The individually-identified 100–400 ms items cannot close a
~4200 ms gap on their own.**

## What was fixed

Landed and kept (all validated against the engine test suite):

| change | where | effect |
|---|---|---|
| Call-plan marshaller (`_CallPlan`, pooled per method) replacing per-call `memAlloc`/`memRelease` pairs | `engine/python/sculptcore/_marshal.py`, `_classgen.py` | ~38k native allocations per bench removed |
| Thread pool: batched `publish()` for a whole `parallel_for` fan-out + bounded spin before parking, spin-then-park join | `engine/source/litestl/util/task.h` | empty `parallel_for` of the kernel's shape: 54 µs → 36 µs |
| `parallelCapture` phase 1: one flat claim buffer + per-node start offsets instead of `Vector<Vector<int>>` | `engine/source/meshlog/parallel_capture.h` | ~70 heap alloc/free pairs per dab removed |
| Border/base-stamp caching, `ensure_border_cache`, gated cross-boundary halo | `engine/source/spatial/*` | (earlier session) |
| `kFastCompressLevel` for the undo blob, 2 MB parallel lz4 blocks | `engine/source/litestl/io/compress.*`, `subdiv/grids.*` | (earlier session) |
| `Vector::steal_data()` — `Multires_serializeStore` hands its heap block to the caller instead of a second full alloc+memcpy | `litestl/util/vector.h`, `subdiv/c-api/subdiv_c_api.cc` | ~5 ms/stroke (~95 ms) |
| `BinFile::writeUint32Array()` — the 63,504-entry link table blits once instead of 127,008 stream-sentry writes | `litestl/io/binfile.h`, `subdiv/grids.cc` | ~3.9 ms/stroke (~75 ms) |

Individually these are each below the ±150 ms noise floor of a single bench run;
they were verified through the phase timers and allocator counters instead.

### Two regressions the full suite caught (both fixed)

Neither showed up in `test_multires` / `test_multires_stroke` — the two gates
this work was being run against. Only the full 122-test ctest sweep found them,
which is the argument for running it before believing a perf change is free.

- **`test_task` hung** (ctest Timeout). The pool's new idle spin polled
  `pending > 0 || stop_` and `continue`d on either, but the loop's exit check
  lives *below* the `cv.wait` — so a worker that happened to be spinning when
  `stop_` was set busy-looped forever and never joined. It reproduced as a
  process that ran its work correctly and then hung at teardown, which in a
  Blender session would be a hang at DLL unload. Fixed by breaking out of the
  spin on `stop_` (falling through to the wait, whose predicate is already true,
  and then to the exit check) and retrying only on `pending > 0`.
- **`test_dyntopo_collapse_crash` failed** its `maxRedoVsForward < 1e-5f` gate
  (0.671421 against a baseline 1.33e-07). Cause: dropping the
  `min = FLT_MAX / max = FLT_MIN` reset at the top of `regen_node_bounds`'s leaf
  branch. `FLT_MIN` is the smallest *positive* float, so the original reset is
  itself wrong for any leaf lying at negative coordinates — but removing it
  outright is worse, because leaf AABBs then only ever accumulate. Bounds feed
  `split_node`'s axis/midpoint choice, so leaf composition became
  path-dependent, and a forward dyntopo stroke and its redo ended up with
  *different* leaves holding stale normals. Restored verbatim; it bought no
  measurable time. Bisected by reverting one hunk at a time — the border cache
  and the `affected_verts.size() * 4` incremental/full threshold were both
  suspected first and both exonerated by test.

## What is left, ranked

The ms figures are from the `--engine-trace` aggregates taken at the ~4 s
intermediate point; treat them as shares of the total rather than as absolutes.

1. **A grids-native brush path** (the real fix, ~2000 ms). Run the kernel,
   the undo capture and the bounds refresh over the grid store's flat
   per-grid float arrays instead of materializing a `mesh::Mesh`. This is the
   architectural change that makes the other items moot.
2. **Undo snapshot, ~560 ms** (was ~730; the two cheap fixes above are done).
   In order of increasing risk:
   - cache compressed bytes **per chunk** with a dirty flag set in the
     non-const `GridsStore::elem()`, so a stroke recompresses the ~3% of
     chunks it touched instead of all 22.1 MB (~270 ms). Needs
     `kGridsFormatVersion` → 3 and a matching `read()`; the risk is a missed
     dirty flag silently restoring stale grid data on undo, so gate it on
     `test_multires` / `test_multires_stroke`.
   - delta blobs (biggest win, also fixes the 190 MB footprint; must preserve
     the `multires_last_blob` chain and the `_decode_multires_blob` fallback).
3. **`Multires::writeback`, ~275 ms.** Restrict the scan to the stroke's dirty
   node/vert set instead of the whole level. Also drop the `pos` copy by passing
   a span of `lm.v.co` directly (3 call sites: `multires.cc:746, 972, 986`).
4. **`draw_refresh`, ~354 ms (4.27 ms/call).** The engine half
   (`sc_external_draw_update`) measures 0.4–1.4 ms, so **~3 ms/call is
   `ob.update_tag(refresh={'SHADING'})`** flushing the depsgraph through the
   multires modifier. Worth checking whether a narrower tag exists.
5. **One-time costs**: `enter_mode_ms` 15.6 s (native 160 ms) and the single
   251.67 ms `ebFreeze` in the first dab's prologue.

### Parity notes (not performance bugs)

- Sculptcore's dab spacing uses `pixel_size = brush.size` where vanilla uses
  `size/2`, giving 42–43 dabs/stroke against vanilla's 82. Fixing it would make
  sculptcore *slower*, so it is recorded here rather than changed as part of
  this work.
- The object-space dab radius is recomputed per dab; vanilla latches
  `cache.initial_radius` at stroke start.

## The instrumentation (all of it removed)

The engine-side numbers above came from throwaway scaffolding that no longer
exists in the tree; rebuilding it is the first step of any follow-up:

- `ExecPhaseTimers` + `SC_PHASE_BEGIN/END` around each stage of
  `CommandExecutor::exec` / `applyDab` / `endStep` in `brush/brush_executor.h`,
  dumped once per stroke by a `dumpPhaseTimers()` called from `endStep()`.
- `CaptureTimers` in `meshlog/parallel_capture.h` for the claim/reserve/fill split.
- `[gridser]` / `[gridser2]` in `subdiv/grids.cc` (serialize breakdown),
  `[extdraw]` in `spatial/c-api/external_draw.cc`, `[gpuupd]` in `spatial/spatial.cc`,
  `[blobsplit]` in the addon's `convert.multires_store_blob`.
- On the native side, two fork-only blocks: a dab counter/timer in
  `editors/sculpt_paint/paint_stroke.cc` and a per-dab region-size print in
  `editors/sculpt_paint/mesh/sculpt.cc`. Both are reverted; note that they cost
  native ~65 ms over the bench, so a fork carrying them under-reports the gap.

The Python-side `FuncTrace` / `EngineTrace` in `bench_multires_sc.py` **is**
kept — it is gated behind `--engine-trace` and is what produced the attribution
tree.

**No optimization flag was disabled and no `optnone` attribute was ever added**,
on either side, at any point in this work.

## Gotchas for anyone repeating this

- **The live addon is the staged copy** at
  `build_windows_x64_clang_RelWithDebInfo/bin/5.3/scripts/addons_core/sculptcore_addon/`.
  Editing the repo's Python (including `engine/python/sculptcore/*`) has no
  effect until it is copied over and `__pycache__` is cleared.
- **cProfile does not separately track ctypes `_FuncPtr` calls**, so native
  engine time lands in the *calling Python function's* `tottime`. `invoke_method`
  showing 1.486 s looked like marshaller overhead and was actually engine
  execution. Use `--engine-trace`, not `--profile`, for attribution.
- **Wrapping the operator's `modal` breaks the operator** — Blender binds it at
  registration, and the patched class attribute leaves the stroke doing nothing
  (`sculpt_phase_ms` collapses to ~400 ms with no dabs). Wrap the internal
  helpers (`_dab_at`, `_apply_spaced_dab`, …) instead. Same for
  `depsgraph_update_post` handlers, which capture the function object by
  reference at append time.
- **Read `[phase]` blocks aggregated, never the tail.** The last-stroke dump is
  wildly unrepresentative — `ebPrologue` reads as 0.0039 ms/call there and is
  0.3193 ms/call aggregated.

## Addendum 2026-08-10: GPU-side attribution (RenderDoc A/B)

Same scene (grid 64 / L4, 1,016,064 faces), the GPU-trace harness
(`claudeMemory/scripts/run_gpu_trace.mjs`, 12 captured frames per arm, GL
backend, vsync off). Per-frame medians from RenderDoc counter analysis.

**Fix 1 — mask-overlay double-draw, verified at draw-vertex parity.** The
engine always advertised mask@2 and the fork's external overlay branch drew
every batch unconditionally, so a maskless session drew the whole mesh twice.
After gating both sides (engine `grids_nodes_get` on
`Multires::maskChannelExists()`, fork `SculptBatch.has_mask/has_face_set` +
per-batch skip in `overlay_sculpt.hh`):

| per frame | native | sculptcore before | sculptcore after |
|---|---|---|---|
| draw_vertices | 6.104 M | 12.2 M | **6.105 M** (parity) |
| under-capture cycle_ms | ~7.3 | 27.7 | 18.3 |

**Finding 2 — residual per-drawcall gap at equal vertex count.** With the
double-draw gone, sculptcore still burned 30.1 ms GPU vs native 5.1 ms/frame:
~249 node draws of `glDrawArraysIndirect(<24528, 1>)` at 0.095–0.117 ms each
vs native's `glDrawArraysInstancedBaseInstance` at ~0.0066 ms avg — **~14×
per-drawcall**, uniform across nodes. Attribution: external-draw VBOs were
created `GPU_USAGE_DYNAMIC` (→ `GL_DYNAMIC_DRAW`, which this AMD driver keeps
host-visible: vertex fetch crosses PCIe every frame), while native's
`draw_pbvh` buffers are `GPU_USAGE_STATIC` (device-local; host copy freed on
upload, re-allocated per refill). Fixed in fork `draw_external.cc node_upload`:
static usage + `GPU_vertbuf_data_alloc` per refill (draw_pbvh's pattern), and
streams without a live source (neutral msk/fset, absent col/uv) are no longer
refilled on data-only uploads — the device copy persists.

**Verified** (same harness, `gpu-trace-results-staticvbo/`): sculptcore GPU
total 30.14 → **7.15 ms**/frame (native 4.75), drawcall GPU 29.5 → 6.00 ms,
per-drawcall ~14× → ~1.6× native, per-dab cycle 18.3 → 13.2 ms (native 7.4),
draw-vertex parity intact. Viewport draw wall time during sculpt is now
*faster* than native (2.15 vs 3.90 ms). The remaining cycle gap is the
CPU-side per-dab driver cost, not the GPU: at 6.1M verts/frame the external
draw path is no longer the bottleneck. Residual GPU deltas, small and
unchased: dispatch 0.57 vs 0.02 ms (116 vs 4 dispatches/frame) and ~2.3 ms
drawcall spread across ~250 node draws vs native's finer batches.

