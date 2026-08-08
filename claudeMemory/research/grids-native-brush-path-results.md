# Grids-native brush path: engine-phase results (G1–G4) + addon wiring (W1/W2)

> **Addendum 2026-08-04 (later): the addon wiring landed** — see the W1/W2
> section at the end for the end-to-end numbers.

Execution record for
[plans/multires-grids-native-brush-path.md](../plans/multires-grids-native-brush-path.md),
run 2026-08-04. All four engine phases landed in the engine submodule (four
commits, one per phase, each gated on the full ctest suite); G5's seam design
is [design/grids-native-addon-seams.md](../design/grids-native-addon-seams.md).
Blender-side wiring remains its own plan, per the plan's scope.

## What landed (engine submodule)

- **G1** `source/subdiv/grid_domain.{h,cc}`, `grid_tree.{h,cc}` +
  `Multires::gridDomain()/levelPositions()` ownership/invalidation.
  `tests/test_grid_domain.cc`.
- **G2** Emitter generalization (`TYPES::node_type` + `capture_policy`,
  `brush/capture_policy.h`, `TYPES::nbrNo`, executor `liveVertNoPtr`;
  behaviour-neutral by ctest + sbrush-verify signature comparison), then
  `brush/grid_executor.h` (CPU), `subdiv/grid_stroke_log.{h,cc}` (undo),
  `cavityRawT` source-generic cavity, `storeDispFromPositions` grid-list
  restriction + `Multires::gridsWriteback`. `tests/test_grid_stroke.cc`.
- **G3** `GridStroke_*`/`GridTree_castRay` c-api, `grid_stroke`/`grid_undo`/
  `grid_redo`/`grid_bench` debug verbs, Scene-owned session + interim
  ride-along mirror, executor phase stats, deferred store-block undo capture,
  the posIsBase fix (base+frames materialized at domain build).
- **G4** `brush/grid_gpu_session.h` (Scene-free, IBrushComputeDispatch),
  `GpuNormalTopology::buildFromArrays`, `gridsFoldStroke` shared fold,
  wgpu-native + Vulkan verb backends. `tests/test_grid_gpu.cc`.

## Correctness gates (all green)

- ring1 CSR == mesh topo-cache ring1 as sets; owned-vert partition exact;
  raycast parity (64/64 rays, same cell) vs the materialized SpatialTree.
- Touched-set normal refresh bit-equals a full refill (the halo is the exact
  cell-Newell dependency closure — the 8-neighborhood, not the edge ring).
- Per-kernel A/B vs the materialized path: draw/clay/pinch/sharp **bit-exact**
  (draw's store writeback too), smooth 6e-8, inflate 3.4e-2 (pure
  normal-source divergence: recalc_normals' per-edge-radial fan pick vs the
  domain's Newell cell fans — recalc even emits near-cancelled garbage
  normals on strongly non-planar quads, found while gating G1).
- Undo/redo: store blob + positions bit-exact two strokes deep; mask
  round-trip; layer-target stroke with channel 0 byte-identical; anchored
  grab; mesh-stroke interleave across the domain fold point; zero-disp level
  round trip (3e-8, frame-projection drift only).
- CPU-grids vs GPU-grids: draw + smooth worst-diff 0 on BOTH dispatchers
  (wgpu-native and Vulkan SPIR-V); undo through the GPU path bit-exact.
- Full ctest 125/125 at the end (the four historically flaky GPU/config
  tests passed on every run this session).

## Perf (grid_bench, 26-subdiv cube → level 4 = 960k verts, 19×57 draw dabs)

| metric | gate | grids path | materialized path (research doc) |
|---|---|---|---|
| per-dab core (kernel+capture+bounds) | ≤0.35 ms | **0.082 ms** | ~1.02 + 0.42 ms |
| stroke-end writeback | ≤3 ms | **2.3 ms** | 12.9 ms |
| undo footprint (19 strokes) | ≤20 MB | **19.9 MB** | ~190 MB |
| domain (enter-path analog) build | — | 2.6 s domain + 15 ms tree | 15.6 s enter |

Per-dab detail at 1M: query 0.026, capture 0.012, kernel 0.051, normals
0.139, bounds 0.019 ms. **Normals are the dominant per-dab cost** (0.14 ms at
1M, 3.05 ms at 4M) — the touched-set refresh runs per dab where the mesh path
amortizes per frame; per-frame batching of the normal refresh is the top
follow-up if the addon-phase numbers need it.

## GPU size question (the research doc's open item)

Per-dab, draw kernel, wgpu-native on this box:

| verts | CPU kernel | GPU dispatch | GPU readback (per-dab currency) |
|---|---|---|---|
| 960k (r=0.1) | 0.055 ms | 0.28 ms | 10.0 ms |
| 4.0M (r=0.2) | 0.46 ms | 0.35 ms | 44.4 ms |

Dispatch crosses over near ~4M verts / large dab regions, but per-dab
readback is 1–2 orders over budget either way — the separate-device drain
economics from the GPU research, now measured on the grids domain. Conclusion
unchanged from the plan: GPU wiring must batch readback per frame
(`enableInteractiveReadback` model), never per dab.

## Deviations from the plan (called out)

- The mesh GPU orchestrator (`debug/gpu_stroke.cc`) was **not** hoisted;
  G4 built the Scene-free grids session instead (the hoist's purpose). The
  mesh-path hoist remains open for the GPU-brushes-in-Blender plan.
- Undo store-block capture was moved from first-touch (per region leaf) to
  stroke end (touched grids only) — smaller and still correct because the
  store is untouched until the fold; this is what brought undo under the
  gate.
- `nudge` (the addon's extra kernel) is not wired grids-side in the engine
  phase — the extras registry is TYPES-generic, so the addon phase gets it by
  instantiating `createExtraBrush<GridBrushExecutor, …>` when extras are
  configured.

## Watch items for the addon phase

- The 19.9 MB undo result is knife-edge at this workload; the addon's undo
  limiter should meter on `GridStroke_undoBytes`.
- `SBRUSH_WEBGPU_COMPUTE=ON` was flipped in the local native build cache to
  validate the wgpu path (not a repo change).
- The pinch sbrush-verify golden mismatch pre-exists this work (verified on
  the unmodified tree) and is untouched.

## W1/W2 addendum: addon wiring + end-to-end bench (same day)

**What landed** (addon repo + engine `GridStroke_*` extensions): stroke.py
dispatches roster kernels through the grids session (`grids_kernel` at
stroke begin; program/preview/snake-hook/MASK stay mesh-path), engine-side
per-dab ride-along mirror + full mirror on undo/redo, domain raycast (gated
on last-stroke-grids + level + domain liveness), grid-tagged undo steps
(grid-log seek primary, per-stroke store blob kept as the fallback chain),
flag-driven mask sync from the slot column, per-step undo-size delta
accounting, and the meshlog-undo store heal (a meshlog seek reverts slot-mesh
edits the store still carries — re-encode at decode so a later grids domain
rebuild can't resurrect them). Headless gate:
`claudeMemory/scripts/test_grids_native.py` (18 checks); per-phase profile:
`profile_grids_stroke.py`.

**End-to-end** (`bench_multires_sc.py`, grid 64 / level 4 ≈ 1M verts, 19
strokes, same rig/noise floor as the baseline):

| | native | pre-grids baseline | grids-wired (W1) |
|---|---|---|---|
| sculpt_phase_ms | ~857 | ~5,050 | **~3,656** |
| stroke_ms mean | — | ~240 (derived) | 149 |
| undo memory | 10.6 MB | ~190 MB | **144 MB → mostly blobs** |
| peak_z | — | 0.11412 | 0.11412 (bit-identical surface) |

Steady-state per-stroke (headless profile at the same workload): dabs 11 ms
(0.26 ms/dab through Python+engine), stroke-end fold 2.5 ms, store blob
24 ms, raycasts 1.3 ms. The wiring pass also fixed two hot mistakes found by
measurement: the mirror originally set `Spatial_RegenTris` (leaf
re-triangulation + GPU partition recompute per draw refresh — ~600 ms of the
bench) and `GridStroke_begin` originally re-pulled the mask column per stroke
(~20 ms → flag-driven).

**Where the remaining 3.66 s − 0.86 s lives** (the ranked follow-ups):
1. draw refresh ~100 ms/stroke at 30 Hz mid-stroke cadence — the
   extdraw-from-grids provider (seams design §2 end state) is the fix;
2. the per-stroke store blob (~24 ms + ~8 MB/step) — blob demotion to level
   switches (seams design §3), needs `GridStrokeLog` eviction first;
3. residual modal Python per-move overhead — the cpp-stroke-driver plan;
4. `enter_mode_ms` ~12.8 s — the lazy-mirror rule (seams design §4).

## W3 addendum: per-stroke cost attribution + two wins (same day, later)

Headed per-phase instrumentation (temporary, removed after measurement)
finally attributed the post-W1 stroke_ms 149 ms: **~70 ms was the engine dabs
themselves at production radius** — dominated by the per-dab normal refresh,
which recomputes ~90 %-overlapping fans dab after dab (spacing is 10 % of the
brush diameter) — plus 23 ms undo push (17 ms blob serialize + a redundant
O(1M) writeback scan) and ~5 ms draw refresh. The draw-refresh hypothesis
from W2 was **wrong**: `tree.update(gpu)` costs 0.4–0.5 ms/call (~4 ms/stroke
at the 30 Hz cadence), measured by registering the provider headlessly.

Fixes:

1. **Deferred normal refresh** (`GridBrushExecutor::deferNormals` +
   `GridStroke_setDeferNormals/flushNormals`): dabs accumulate moved verts;
   the refresh runs deduped at the host frame cadence (`_mid_redraw`, before
   the provider re-upload) and at stroke end. This is the mesh path's / native
   sculpt's per-frame normal cadence; kernels and raycast normals read
   ≤1-frame-stale values, and the bench surface moved only in the 5th decimal
   (stale dab normals steer dabs microscopically differently). Off by
   default engine-side — the per-dab A/B tests keep exact semantics; the
   addon opts in. `images` 70 → 34 ms/stroke.
2. **Blob push skips the writeback scan** (`multires_store_blob(...,
   skip_writeback=True)` from the grid-step push): the grids fold already ran
   at stroke end and the mirror makes the scan compare a million
   bit-identical verts. ~7 ms/stroke.

| | native | pre-grids | W1 | **W3** |
|---|---|---|---|---|
| sculpt_phase_ms | ~857 | ~5,050 | ~3,656 | **~2,811** |
| stroke_ms mean | — | ~240 | 149 | **105** |

Remaining per-stroke (headed): engine dabs 34 ms, undo push ~25 ms (17 ms
blob serialize — demotion still the designed fix), normals+provider refresh
~12 ms at frame cadence, sampler ~7 ms, ~25 ms modal dispatch/misc. Next
levers in value order: blob demotion (§3 of the seams design), the
extdraw-from-grids provider (mirror + slice fills), enter (~13 s, lazy
mirror).

## W4 addendum: fast enter (same day, later)

cProfile on `convert.enter` at 1M attributed **11.0 of the 13.1 s to
`Multires_fromLevelPositions`**: it materialized the level (topo mesh + tree
+ normals), scattered the seed into the slot mesh, ran a full writeback,
eagerly cascaded `propagateDown` through every level, then invalidated and
materialized AGAIN — with the addon's own `setActiveLevel` that's ~3 slot
builds of a 1M mesh plus a cascade the user may never look at.

Fix: `Multires::seedLevelPositions` (+ c-api) — seed through the CHAIN:
ensure base+frames first (one throwaway topo mesh for the frame provider —
the posIsBase hazard again), write the samples into `LevelPos::pos` in
place, one `storeDispFromPositions` over the level, set the down-prop DEBT
instead of cascading (the first downward switch settles it — `sculpt_levels
< top` enters pay it immediately, same as before), drop resident slots.
The addon then materializes exactly once.

Gates: seeded-level surface vs the old path 3e-8 (float re-derivation);
the settled coarse level after a downward switch **bit-identical** to the
old eager cascade; all headless suites green.

**Enter: 13.1 s → ~6.2 s headed** (6.1 s headless), with `sculpt_phase`
unchanged (~2.82 s across repeat runs; a 3.27 s outlier run was variance —
single-run phase deltas at this scale swing more than the native rig's
±150 ms floor, so bracket with a repeat before believing a change). The
remaining ~6 s of enter is the refiner init ~1.4 s, chain+frames ~2 s, and
the one real materialization — the lazy-mirror end state is still the fix
for most of that.

**Watch item:** `test_grids_native.py`'s raycast-lands-on-surface check
flaked ~1-in-4 in one build, then passed 7+ consecutive runs; the check now
prints the full hit on failure. Positions/moved-counts were bit-identical
across those runs, so if it recurs the printed hit will say whether the
raycast (tie on the center seam?) or the branch selection moved.

## Blob-demotion addendum (2026-08-06)

Per-stroke store blobs are demoted to **boundaries** (seams design §3): a
grids step's undo payload is the GridStrokeLog alone; the events that kill a
log (level switch/restack, mesh-path writeback, blob restore, the meshlog
store heal, the below-top save dance) first retro-attach blobs to its
blob-less steps via `undo.materialize_grid_blobs` — the log's undo/redo swap
store blocks bit-exactly, so seeking the live history reproduces each step's
store state, one serialize per step, once per boundary. The undo limiter now
also truncates the engine log (`GridStrokeLog::dropOldest`, evicting the
front applied step only) when it frees the oldest grid step.

Bench (1M/L4, 19 strokes, vs the same-rig control of 2026-08-06):

| | control | blob demotion |
|---|---|---|
| sculpt_phase_ms | 3244/3308/3410 | **2091/2209/2819** |
| stroke_ms median | ~128 | **~72** |
| undo memory | 99.7 MB | **0.7 MB** |
| peak_z | 0.077474–6 | 0.077474–5 |

The ~55 ms/stroke win exceeds the 17 ms serialize because the push also paid
an ~8 MB `ctypes.string_at` copy + Python bytes retention per stroke. A
pure-grids run now pushes zero blobs; histories that cross a boundary pay
blobs for the pre-boundary steps only.

**The crash the wiring test caught was not demotion** — it was a latent ABA
bug the extdraw pressure-test predicted (its Finding 6): `GridStroke_sync`
compared domain *pointers*, and a mesh-fold's drop + rebuild routinely
reuses the same allocation, so the session kept a freed `GridTree *`. Any
sculpt-after-fold could read freed memory (heap-layout-dependent, which is
why the native suite and three probe scripts all passed while the full test
crashed deterministically). Fixed with `Multires::domainGen_` — bumped on
every domain build/drop, compared by sync; regression-gated in
`test_grid_stroke.cc`.

## Provider v2 addendum (2026-08-06, same day)

The grids-fed extdraw source landed (engine `1d6f58e`, addon `b62be69`),
rebuilt per the pressure-test findings: row-band partition (~2048 tris/node,
sub-grid granularity at deep levels), exact occurrence-table dirty marking
(±2 cell rows = the cell-Newell closure; covers seams and grab by
construction), never-build-a-domain-on-a-draw-poll, born-TOPOLOGY nodes, a
type-erased custom-source vtable in external_draw.cc (spatial cannot depend
on subdiv), and per-stroke-class provider flips addon-side (mesh-path tools
draw the slot tree; the ride-along mirror stays on, so no heal is needed).

Measured (1M/L4, same binary): sculpt_phase ~2.0–2.1 s (vs ~2.1–2.2 blob-
demotion baseline — no regression), stroke_ms median ~73, peak_z parity,
engine-side registration ~200 ms at enter. An apparent +2.5 s enter
regression dissolved under a same-binary A/B: the slot provider entered at
~8.8 s in the same environment — display pacing had shifted 30→60 Hz
between run batches (idle_frame 33.3→16.7 ms is exactly the vsync
interval). Cross-batch numbers on this machine are not comparable; A/B
within a batch.

Visual note: the grids source supplies smooth per-vert normals (native
multires' shading); the slot path hard-codes flat. Color/uv/fset overlays
fall back to the slot provider via the mesh-path flip.

**Remaining for the §4 end state (designed, not yet implemented):** the
lazy slot — enter still materializes the level mesh + tree (~2.5 s of the
~6 s baseline enter) purely for mesh-path readers. With the writeback
authority guard landed, turning the mirror off is data-safe; the remaining
work is session-surface: nullable slot pointers (or an ensureSlot() seam)
across convert/stroke/multires readers, mask exchange ported to domain
reads, and Multires_levelPositionsOut reading the chain instead of
materializing. See plans/extdraw-from-grids.md.

## Lazy-slot addendum (2026-08-06, same day)

The §4 end state landed (engine `d4e8cf9`, addon `a469108`): a multires
enter materializes NOTHING — chain seed, grids draw source, domain-direct
mask import. `convert.ensure_multires_slot` is the single materialization
seam (mesh-path strokes and the slot-provider flip call it; the build reads
the chain so positions are current by construction, and the mask column
seeds from the domain). `Multires_levelPositionsOut` reads the chain, so
saves below top no longer materialize the top slot or settle debt; level
switches and blob restores preserve residency (lazy stays lazy). The
writeback-authority guard is what makes all of it data-safe.

Bench (1M/L4, all in one environment): enter ~9.0 → **~7.3 s**, sculpt_phase
~2.1 → **~1.9 s**, stroke_ms ~73 → **~64** — the second win because the
ride-along mirror no-ops while no slot exists, removing the last mirror leg
from pure-grids sessions. Undo 0.7 MB, parity to 1e-6, ctest 125/125,
wiring test covers slot-less sculpt/raycast/save.

Day total at 1M/L4 (same-day control → now): sculpt_phase 3.3 → 1.9 s,
stroke 128 → 64 ms, undo 99.7 → 0.7 MB, and enter carries no slot cost.
Remaining enter is refiner + chain + domain fill (~200 ms of it the
provider); further wins are domain-build parallelization territory.

## Lattice-frame addendum (2026-08-08): enter 4.4 s → 2.1 s

The "~200 ms of it the provider" estimate above was **wrong by an order of
magnitude** — it was inferred, not measured. Measured headless at HEAD, enter
was 4723 ms (first run) / 4389 ms, and env-gated engine timers put **2433 ms of
that in `ensureBaseAndFrames`** — nearly all of it the F3 frame provider.
Lesson: re-measure before trusting an inherited breakdown, and never quote a
phase cost that was reasoned about rather than timed.

Why it cost that much: `ensureBaseAndFrames` (and `ensureChain`'s disp branch,
and `materialize`) each built a **throwaway `mesh::Mesh` of the whole level**
purely so `displace::updateFramesAll` had something to run on, then read the
`FRAME_*_ATTR` back into dense vectors and deleted the mesh. And
`updateFramesRegion` is **deliberately serial** — Gauss-Seidel 1-ring normal
smoothing plus the "4-fold-aware diffusion … the backend-parity anchor" — so
parallelizing it was off the table: it would change results and break the
documented cross-backend parity.

Fix: switch the multires frame space to `Multires::parametricFrames()`, which
the engine already had implemented and gated by `test_multires` (and which
`displacementAndSubSurf.md` risk #2 already named as "the answer for
multires"). It derives normal + tangent from the grid's own `(u,v)` lattice by
central differences on the smoothed base — no mesh, only `+ - * / sqrt`, and
embarrassingly parallel (now under `task::parallel_for`).

**Encode and decode had to move together.** `storeDispFromPositions` already
consumed the cached `frameNo/frameTa`, but `applyDisp` re-ran the provider
internally off a mesh it was handed; switching one alone would have broken the
round trip. `applyDisp` now takes the frame vectors instead of a `mesh::Mesh`,
so both sides read one field by construction. `extractFrameAttrs` is gone (all
three call sites with it).

This is a **correctness fix that happens to be the perf fix**. The cross field
must choose a representative from a 4-fold-symmetric tensor with nothing
pinning that choice across rematerializations; `gateFrameStability` measures a
provider tangent *reversing* (dot −0.999962) from a 0.01 cage nudge where the
lattice frame holds at 0.999970. That defect is now off the production path.

Results (1M/L4 headless, clean build):

| phase | before | after |
| --- | --- | --- |
| `convert.enter` total | 4389 ms | **2104–2208 ms** |
| `ensureBaseAndFrames` | 2433 ms | **26 ms** |

Gates: ctest **125/125**; `test_grids_native.py`, plus the material-seed and
slot-material headless checks, all 0 failures.

Remaining enter is now dominated by `multires.py:build_engine` at **1470 ms**
(≈70%), which is `Multires::init` → `Refiner::refine`. That one is not a quick
win: `refineStep` builds a `mesh::Mesh` per level via `make_vertex`/`make_face`
under dense-ordering asserts, so it is inherently sequential — parallelizing it
is a redesign, not a tweak.

**Open, flagged, deliberately not fixed:** `captureDetailToVdm` now straddles
two frame spaces — it writes texels in the lattice frame while `vdm_bake` /
`_promote` / `_splat` decode against the provider's `FRAME_*_ATTR`. The two
agreed only while multires also used F3. It is dormant (no test, no addon
caller, X4 stage 2 is work-in-progress), so it was **documented in the header
rather than silently disabled** — quietly turning off a feature the user may be
building on is the worse failure mode. Capture must convert, or the VDM path
must adopt the lattice frame, before it is wired to a host.
