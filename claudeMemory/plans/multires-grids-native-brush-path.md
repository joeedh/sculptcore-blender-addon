# Plan: a direct grids editing path for multires ("grids-native brush path")

**Status: plan, nothing implemented.** Written 2026-08-04, immediately after the
multires stroke optimization work
([research/multires-stroke-performance.md](../research/multires-stroke-performance.md)),
whose conclusion this plan executes: after a ~17× optimization pass (87.8 s →
5.0 s on the 1 M-vert level-4 bench), the residual ~6× gap to native sculpt is
architectural — SculptCore materializes a multires level as a full `mesh::Mesh`
plus a triangle BVH and per-element gated undo capture, where native Blender
sculpts flat CCG grid arrays in place. No remaining hot spot closes that; this
path does.

All work is in the **engine submodule** except where marked. Blender addon
wiring is **explicitly out of scope** (a later plan); the path is built,
validated and benchmarked engine-side (tests + debug app). GPU brush execution
**is** in scope.

## Goals and non-goals

Goals:

- Run sculpt strokes on a multires level directly over flat dense buffers +
  the grids' implicit lattice topology — no materialized `mesh::Mesh`, no
  triangle BVH, no meshlog attribute machinery on the hot path.
- Undo capture as per-grid block snapshots, O(touched grids) per stroke.
- Writeback restricted to the stroke's touched set, O(region) not O(level).
- The same `.sbrush` kernels, single-source: the CPU lowering and the existing
  WGSL lowering both execute against the grids domain. GPU dispatch reuses
  `IBrushComputeDispatch` (wgpu-native + Vulkan backends) unchanged.
- The materialized-mesh path survives as the fallback for whatever the grids
  path doesn't cover yet, and both coexist safely in one session.

Non-goals (deliberately unchanged):

- The store format (`GridsStore`, `kGridsFormatVersion`), the frame model
  (`base + frame·d`), sculpt layers, propagateDown/downPropDebt semantics.
- The parametric-frames switch-over (orthogonal; see
  [design/multires-parametric-frame.md](../design/multires-parametric-frame.md)).
- Blender addon / fork wiring: extdraw-from-grids, session undo integration,
  `stroke.py` dispatch. Phase G5 designs the seams so they're ready, but
  nothing outside the engine is modified by this plan.
- Dyntopo (meaningless on multires) and true parity for every last brush on
  day one — unsupported brushes fall back to the materialized path.

## Where the 5.0 s goes today (recap)

From the research doc's attribution (shares, not absolutes — taken at the ~4 s
intermediate point): kernel 351 ms, `capturePre` 323 ms, `_refresh_queries`
(BVH bounds/normals) 332 ms, undo store blob ~560 ms, `Multires::writeback`
~275 ms, `draw_refresh` ~354 ms — plus `enter_mode_ms` 15.6 s one-time and a
190 MB undo footprint. Native: ~857 ms, 160 ms enter, 10.6 MB undo. Every one
of those rows is a consequence of the materialized mesh; every one is
addressed below.

## The central representation decision

Two candidate layouts for the editable level state:

1. **Replicated grid-major (Blender's CCG):** one flat `(S+1)²` position array
   per grid, boundary verts duplicated in every grid that contains them.
   Pro: undo/iteration are pure contiguous block ops. Con: every seam vert has
   multiple live copies — a dab must not double-apply to replicas, smooth-type
   kernels see different neighborhoods per replica, and every write needs a
   stitching pass (Blender pays exactly this).
2. **Dense level-vert-id indexing:** one flat position array indexed by the
   refiner's dense level vert ids — boundary verts exist exactly once.

**This plan chooses (2), dense level-vert ids.** The deciding facts:

- `Multires` already maintains exactly this buffer: `LevelPos::pos`
  (`multires.h` — the cached position chain). The editable state *already
  exists in the right layout*; the mesh materialized from it is the thing
  we're deleting.
- All the dense↔grid machinery exists and is tested: `SubdivLevel::gridVerts`
  (lattice→vert id), `levelVertGridCoordsOut` (vert id→canonical owning grid),
  `seamMates`, and `storeDispFromPositions(level, pos, mask, toEditTarget)` —
  which already takes a per-vert mask, i.e. the restricted-writeback hook is
  already in the signature (`multires.cc:567`).
- Uniqueness by construction: no replica double-application, no stitch pass,
  no per-replica neighborhood divergence. This is a place we end up *simpler*
  than Blender, not just equal.
- Both kernel backends already speak flat vert-id-indexed buffers: the CPU
  kernels via iterator bundles + a CSR neighbor source, the WGSL kernels via
  `co/no/mask` storage buffers + a CSR at bindings 12/13
  (`compute_layout.h`). GPU marshal reuse is near-total.

What (2) gives up vs (1): per-grid undo becomes a gather (through the grid's
vert-id table) instead of a straight `memcpy`, and leaf iteration walks a
precomputed vert-id list instead of a contiguous range. Both are O(touched)
with good locality if the refiner's vert ids cluster by grid. **Contingency**
(only if profiling says the gather hurts): a level-local permutation to
grid-major-canonical order, applied to all domain buffers, with the
permutation folded in at the writeback/stencil boundaries. Not part of the
base plan.

## Architecture

Three new pieces, one codegen change, one hoist.

### 1. `GridLevelDomain` — the editable level state

Built per active level from `Multires` (owned by it, invalidated with the
posCache). Contents:

- `pos` — **is** `LevelPos::pos` (edited in place; the chain stays
  authoritative, so `invalidateAbove`/`ensureChain` semantics are untouched).
- `no` — dense vertex normals (new buffer): geometric normals from the grid
  quad fans. Full fill at build; per-dab refresh of touched verts + a 1-ring
  halo (the halo rule mirrors `GpuNormalTopology::dabWork`'s reasoning:
  boundary verts of the moved set need fresh face normals from outside it).
- `mask` — dense mirror of a `"mask"` grids-store channel (1 float,
  `GridsStore::addChannel`), synced at build/writeback. Mask-writing kernels
  edit the mirror; writeback lands it in the channel. (The addon's existing
  mask exchange already treats mask as engine state; the channel makes it
  survive level switches the same way disp does.)
- `ring1` — CSR 1-ring built once per level from the lattice
  (`GridsStore::neighbor` semantics: ±u/±v steps, seam-crossing via
  `GridLink` transposes, dedup'd to vert ids). Static for the level's
  lifetime — multires topology never changes. Serves the CPU `CsrNbr`-style
  source and GPU bindings 12/13 verbatim.
- Sidecar stroke state (dense `Vector`s, allocated lazily): `dispVec`/
  `dispGen` (from-base accumulation), `dabGen` (grab first-touch),
  `automaskCavity` + gen (cavity cache), `touchedStamp` (per-vert, per-stroke)
  and a touched-grid set. These replace the `.brush.*` TEMP mesh attrs
  one-for-one.

### 2. `GridTree` — spatial structure over grids

- **Leaf = a cluster of whole grids** (target ~`leaf_limit` verts per leaf,
  so ~4–16 grids at level 4; grids of the same cage face first, then merged
  by adjacency). Built once per level; **no splits, no merges, ever**.
- Each leaf: grid-id list, an **owned-vert list** (every level vert assigned
  to exactly one leaf via its canonical owning grid — the
  `levelVertGridCoordsOut` rule), and an AABB (+ the same padding rule the
  mesh tree uses).
- Query: brush-sphere → leaf list. Start with a flat SIMD-friendly scan over
  leaf AABBs (2–8 k leaves at level 4 — microseconds); keep a shallow static
  BVH as an option if coarser cages with more levels blow the leaf count up.
- `castRay`: leaf AABB test → per-grid → per-cell bilinear quad as two
  triangles (verts via `gridVerts`). Replaces the mesh-tree raycast for dab
  origins and view picking. (Per the castRay memory: hosts mirror the
  *resolved hit*, so matching the mesh tree's hit-reconstruction quirks is
  not required — but return the same `CastRayIsect` shape.)
- Bounds refresh after a dab: recompute AABBs of touched leaves from their
  owned verts. No structure maintenance, no `regen_node_bounds` subtleties.

### 3. `GridStrokeLog` — undo

- Per stroke step: first touch of a grid snapshots its owned verts'
  pre-positions (gather via the leaf/grid vert lists) — CCG-style block undo.
  Mask strokes snapshot the mask values likewise; a step records which
  buffers it captured.
- Undo/redo = swap blocks back in, refresh normals + bounds of the affected
  leaves, invalidate finer chain levels, set the level's writeback-pending
  state. Positions restore **bit-exact** (they're copies, not re-derivations).
- External semantics mirror the meshlog step/seek model
  (`DECODE_ACTIVE_STEP` + `is_final` — see the delta-undo memory) so the
  later addon wiring is a swap, not a redesign.
- The store-blob fallback for level switches stays exactly as is. End state
  (addon phase, not here): grid strokes stop paying the ~31 ms/stroke
  `Multires_serializeStore` blob entirely — the blob remains a level-*switch*
  artifact only. Expected undo footprint on the bench: a stroke touching
  ~1,900 grids ≈ 3.5 KB each ≈ **~7 MB vs today's 190 MB**, in native's
  ballpark (10.6 MB).

### 4. Codegen: domain-generic kernel lowering

The generated CPU kernels are *nearly* domain-agnostic already — the exec body
is templated on `TYPES` and touches only `ctx.node`, the iterator bundle
(`co/no/mask/v`), ctx helpers, `affected_verts.append`, `node.update(flags)`.
Two hard couplings remain, both fixed in the sbrushc C++ emitter (one emitter
change regenerates every kernel):

- `CommandCtx<TYPES>` and the generated `*Pre`/`*Post` signatures hard-code
  `spatial::SpatialNode` (`brush_command.h:263`,
  `kernels/generated/*.brush.gen.h`). Extend the `CommandTypes` concept with
  `TYPES::node_type` and emit against it.
- The `*Pre` undo capture is inlined meshlog code (AttrSaver +
  `parallelCapture` against `nodes[0]->data->m`). Replace the inline block
  with a call through a `TYPES::capture_policy` — the mesh executor's policy
  is today's code verbatim; the grid executor's policy is
  `GridStrokeLog::captureLeaves(...)`.

Then a **`GridBrushExecutor`** (new, small — deliberately *not* a
generalization of the 2,300-line `CommandExecutor`, which keeps dyntopo,
meshlog, attr-override and preview machinery the grids domain never needs)
instantiates the same kernel factories
(`command::create<X>Brush<GridBrushExecutor, GridCsrNbr, AccMode>`), with:

- `GridVertexIter`: walks a leaf's owned-vert list; `co` binds `pos[v]`
  (through the existing `CoProxy<AccMode>` so AccumOrig/AccumOrigGrab work),
  `no` → `no[v]`, `mask` → `mask[v]`.
- `GridCsrNbr`: the `CsrNbr` contract over the domain's `ring1`.
- Ctx helpers: `strength()`, `masks()`, `sampleBrushTex()`, the view-normal
  automask are pure math over `Brush` + dab state — hoist the shared bodies
  to a header both ctx types include (or a CRTP base). Cavity automask needs
  a span-CSR variant of `cavityRaw` (`automask.h:111` currently takes
  `mesh::Mesh*` only to reach `topo_cache.ring1` and `v.co/v.no` — take
  spans instead, mesh path passes its own).
- `co_prev` (Jacobi snapshot for `for_neighbor` kernels): same dense-buffer
  copy the mesh path does. Flag for later: both paths pay O(domain) per dab
  here; restricting it to touched+halo is a follow-up that helps mesh and
  grids alike.

**Kernel coverage, day one:** vertex-stage kernels reading/writing
`co/no/mask/disp` — draw, grab, smooth, inflate, kelvinlet, pinch/sharp, the
plane family (clay/scrape/fill), mask, nudge (the addon's extra kernel —
CPU-only there, CPU-only here). **Fallback to the materialized path:**
face-stage kernels (`GpuKernelInfo::faceMode` set), kernels binding mesh
attrs with no store-channel equivalent (color, colorsmooth, bsmooth's vclass),
and anything `queryBrushFlags` says needs live topology. The dispatch rule is
engine-owned metadata, not a host tool-name switch — consistent with the
existing `BrushMetadata` policy.

### 5. GPU brush execution

The GPU stack is already domain-agnostic below the marshal layer — WGSL
kernels see flat storage buffers and know nothing of `mesh::Mesh`. Work:

- **Hoist the orchestrator** out of `source/debug/gpu_stroke.{h,cc}` into a
  `Scene`-free session under `source/brush/` (this is item 2 of "Path A" in
  [research/gpu-brush-evaluation-in-blender.md](../research/gpu-brush-evaluation-in-blender.md)
  — shared work, both plans need it), parameterized over the domain.
- **Grid marshal** (`grid_gpu_marshal` beside `gpu_marshal.cc`): variants of
  `packGeometry` (trivial — `pos/no/mask` are already flat), `packAutomask`
  (over the span-CSR cavity), `packNeighborCSR` (the domain's `ring1`,
  verbatim), `chunkNodes` (leaf owned-vert lists → ≤64-wide chunks). Uniform/
  stroke-path/scatter packing is shared as-is.
- **Dispatchers unchanged:** `IBrushComputeDispatch` (wgpu-native first —
  engine-owned device, no host coupling; Vulkan for the debug app's live
  path). The `kDispBinding` from-base buffer, dab stamps, automask binding
  all carry over — GPU stroke topology is static, which multires satisfies
  trivially.
- **Normal pass:** `GpuNormalTopology` gets a build-from-arrays entry —
  `triVerts` from `levelTriIndicesOut` (already exists, built for exactly
  this kind of consumer), vert→tri CSR from the lattice. `dabWork` is already
  array-based and reused as-is.
- **Undo ordering contract:** snapshot touched grids into `GridStrokeLog`
  *before* the readback overwrites `pos` (the `gpu_stroke.cc:396` rule).
- **Readback cadence:** per-dab moved-verts readback for currency (raycast,
  bounds), batched per frame on the wgpu path exactly as the engine's
  interactive path does today (`enableInteractiveReadback` model) — the
  separate-device drain economics from the GPU research apply unchanged.
- **Verification:** extend `sbrush-verify`-style A/B to the grids domain —
  CPU-grids vs GPU-grids must match bit-modulo-fp (same CSR on both sides, so
  the neighbor-order caveat below does not apply here); plus a
  `GPUBRUSH_DATA_LIVE_CO`-style shadow diff mode in the session.

### 6. Writeback, draw, and coexistence with the mesh path

- **Writeback:** stroke end (and any fold point — level switch, serialize,
  layer ops) calls `storeDispFromPositions` with the touched-vert mask and
  iterates only the touched-grid set (the current implementation loops all
  grids; give it an optional grid-list parameter). `Multires::writeback`'s
  whole-level memcmp scan remains the path for mesh-materialized edits;
  grids strokes supply their touched set directly. This is "What is left"
  item 3 falling out for free, and it also shrinks `downPropPending_`
  bookkeeping not at all (semantics unchanged — a changed writeback still
  sets the debt).
- **Draw + legacy queries (interim — the "ride-along mirror"):** the slot
  mesh's vert ids **are** the dense level ids (`buildLevelTopo` — "dense vert
  ids matching the stencil rows"), so syncing is a direct indexed copy of
  touched `pos/no` into `m->v.co/v.no` plus dirtying the owning tree nodes
  (via `.spatial.v.node`), once per frame. O(touched), keeps extdraw and any
  un-migrated query byte-correct while the grids path does the real work.
  The mirror is write-only: the domain is authoritative; a mesh-path edit
  (fallback brush) writes back to the store and refreshes the domain from
  the chain before the next grids stroke — the fold points already exist.
- **Draw (end state, G5 design / addon-phase build):** an extdraw provider
  fed straight from `GridTree` leaves — positions/normals from the domain,
  triangle layout from `levelTriIndicesOut` restricted per leaf, stable
  `node_id` = leaf id (the ABI v2 contract). Only then does the mirror — and
  with it the materialized mesh + tree and the 15.6 s enter — become lazy
  (built only if a consumer actually asks).

## Phases

### G1 — `GridLevelDomain` + `GridTree` (no brushes)

Files: `source/subdiv/grid_domain.{h,cc}`, `grid_tree.{h,cc}` (subdiv module —
it owns the tables; the tree depends only on the domain, not on `spatial/`).

Work: lattice→CSR builder, normal fill + touched-refresh, leaf clustering +
owned-vert partition, AABB build/refresh, sphere query, raycast, mask-channel
mirror.

Gates (new `tests/test_grid_domain.cc`):
- CSR vs the materialized mesh's `topo_cache.ring1`: identical **as sets**
  per vert (order will differ — lattice vs edge-cycle enumeration).
- Owned-vert partition: every level vert in exactly one leaf; leaf grid lists
  cover all grids exactly once.
- Normals vs the mesh path's within tolerance.
- Raycast vs the mesh tree's `castRay` on the same level: same primitive
  region + hit distance within eps over a ray battery.
- Full ctest stays 118/122.

### G2 — CPU brush execution + undo + restricted writeback

Files: sbrushc emitter (`compiler/emit_cpp` side) + regenerated
`kernels/generated/*`, `source/brush/grid_executor.h`,
`source/subdiv/grid_stroke_log.{h,cc}`, the ctx-helper hoist, the
`cavityRaw` span variant, `storeDispFromPositions` grid-list parameter.

Order inside the phase: (a) emitter generalization with the **mesh** path as
the only instantiation — regenerate, `sbrush-verify`, full ctest green, i.e.
prove the refactor is behaviour-neutral before the new domain exists;
(b) `GridBrushExecutor` + draw kernel end-to-end; (c) the vertex-stage roster
+ from-base/grab modes + automask; (d) `GridStrokeLog` + undo seek;
(e) touched-set writeback.

Gates (new `tests/test_grid_stroke.cc` + extensions to
`test_multires_stroke`):
- Per-kernel A/B vs the materialized path: identical dab sequence on the same
  store, compare resulting store contents. **Tolerance-based, not bit-exact**
  — neighbor order differs, so `for_neighbor` accumulation and normal sums
  diverge in float. Position-only kernels (draw, grab, inflate) should be
  near-bit-exact; assert tight eps there, looser for smooth-class.
- Undo fidelity: store snapshot → stroke → undo → **bit-exact** store
  compare (the grids log restores copies). Redo → forward-result compare.
- Mask stroke round-trip through the channel.
- Layer interaction: stroke with an active edit target lands in the target's
  channel (the `storeDispFromPositions` residual rule is shared code, but
  gate it anyway).
- Full ctest — the whole suite, per the regression lesson in the research
  doc, before believing any perf number.

### G3 — session surface + engine-side benchmark

Files: `source/subdiv/c-api/` additions (`GridStroke_begin/dab/end`,
`GridTree_castRay`, undo seek), debug-app verbs (`script.cc` already has
multires verbs to extend), the ride-along mirror sync.

- Bench via the debug app on the bench-equivalent workload (1 M-vert level-4,
  draw brush, comparable dab count). Measure: per-dab total, capture, bounds
  refresh, writeback-per-stroke, undo bytes.
- **Perf gates:** per-dab (kernel + capture + bounds) ≤ **0.35 ms** at the
  bench workload (vs ~1.02 ms steady-state + 0.42 ms `_refresh_queries`
  today — i.e. ≥4× on the engine's share of the dab); stroke-end writeback
  ≤ 3 ms (vs 12.9); undo ≤ 20 MB on the 19-stroke bench. These are
  engine-side numbers; the end-to-end 5.0 s → target ~1.5–2 s claim can only
  be validated after addon wiring, and the plan makes no promise the Python
  half doesn't cap it — the fallback expectation is stated honestly in the
  research doc's ranked list.

### G4 — GPU path

Files: hoisted `source/brush/gpu_stroke_session.{h,cc}` (Scene-free),
`grid_gpu_marshal.{h,cc}`, `GpuNormalTopology` array entry, verification
plumbing.

- wgpu-native backend first (self-contained, testable headless), Vulkan
  second (debug-app live path, GPU-resident scatter excluded — that's tied
  to the engine's own renderer and irrelevant to the Blender future).
- Gates: `webgpu-verify`-style replay per kernel on the grids domain;
  CPU-grids vs GPU-grids bit-modulo-fp; undo fidelity through the GPU path
  (snapshot-before-readback ordering); full ctest.
- Measure dispatch+readback per dab vs the CPU grids path at 1 M and 4 M
  verts — the "at what size does GPU win" open question from the GPU
  research, now answerable on the domain where it matters.

### G5 — addon-facing seams (design + stubs only)

No Blender-side code. Deliverables: the extdraw-from-grids provider design
(ABI v2 `node_id` = leaf id; what SC_EXTERNAL_DRAW_UPDATE_* means per leaf),
the session-undo integration design (grid steps replace per-stroke blobs;
blob on level switch only; generation interplay with the existing
`_decode_multires_blob` fallback), the lazy-mirror rule (when a materialized
slot is actually required), and the c-api surface the addon will call —
reviewed against `sculptcore_addon/stroke.py` / `session.py` / `undo` as they
exist then. Wiring is its own plan.

## Risks

- **Codegen churn** touches every generated kernel and the live mesh path.
  Mitigation is the G2 ordering: regenerate with mesh-only instantiation
  first, gate on `sbrush-verify` + full ctest before any grids code exists.
- **Neighbor-order float divergence** vs the materialized path is inherent
  (lattice vs edge-cycle order). It only affects the *migration parity*
  gates (tolerance), never CPU-vs-GPU parity (both grids sides share one
  CSR). Flagged so nobody chases it as a bug later.
- **Two sources of truth during the mirror phase.** The rule is absolute:
  domain authoritative, mirror write-only, fallback strokes fold through the
  store. The G2/G3 tests must include an interleaving case (grids stroke →
  fallback mesh stroke → grids stroke).
- **Eviction reentrancy:** `GridsStore::elem()` rehydrates on touch and is
  not thread-safe under `parallel_for` — the domain must pin the active
  level resident for the stroke (the `storeDispFromPositions` comment
  already documents the hazard).
- **Chain-cache coupling:** editing `LevelPos::pos` in place must preserve
  `ensureBaseAndFrames`'s validity rules (base/frames depend only on the
  level below — safe) and `posIsBase` handling (first grids edit on a
  zero-disp level must materialize `base` first, same as `materialize()`
  does today at `multires.cc:527`).
- **Gather-based iteration underperforming.** If leaf owned-vert lists don't
  cluster well in the dense id space, the kernel walk loses locality. The
  grid-major permutation contingency exists; measure before building it.
- **`co_prev` stays O(level) per dab** for smooth-class kernels in this plan
  — a known, shared-with-mesh-path cost, listed as follow-up, not silently
  absorbed into the perf gates (the G3 gate is measured on draw).
- **Scope creep toward the addon.** The 15.6 s enter and the per-stroke blob
  cost do *not* fall in this plan — they fall when the addon adopts the
  provider and the grids undo. The G3 gates are engine-side on purpose.

## Prior art note

The perf model being matched is native Blender's `PBVH_GRIDS` (flat CCG
arrays, per-grid-block undo, per-grid bounds). Per the recorded feedback,
stock Blender's multires *reshape/propagation algorithms* are not a baseline
for correctness — nothing here touches SculptCore's own
propagation/writeback math; only the *storage/iteration* economics are
borrowed, and the dense-id choice deliberately diverges from CCG where
SculptCore's store machinery makes the simpler layout viable.
