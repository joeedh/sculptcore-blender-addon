# Routing brush programs onto the grids path (and the batch driver)

Status: **LANDED 2026-08-11** (S1–S5; addon `4b82690` / `6a60937` + engine) —
amended before implementation per three adversarial reviews (§9). Clay's stroke
cost went 862–931 ms to 165–171 ms median, which closed the multires stroke
perf gap.
Date: 2026-08-11
Repos touched: engine (submodule), addon. No fork changes (verified §9).

## 0. Problem

Clay — the user's actual test brush — ships `auto_smooth_factor` 0.25, which
makes `stroke.py` build a `[main, BSMOOTH]` `BrushProgram`, and a non-None
`self._program` fails both fast-path gates:

- the C++ batch driver gate (`stroke.py:828-831`, requires `self._program is
  None`), and
- grids-native dispatch (`stroke.py:879-885`, "The program (autosmooth),
  preview and snake-hook flows stay mesh-path").

So a Clay stroke at 1M/L4 multires runs per-dab Python against the
materialized `mesh::Mesh` — the pre-grids-native cost profile. Measured
(realistic bench, 2026-08-11, interleaved, vsync on): sc operator busy
**862–931 ms median per 1.2 s stroke** (max 2.6 s) vs ~55 ms for Draw on the
grids path (~15×); frame median degrades to 29.8 ms (p90 47) while native
holds 16.8. This is the user-perceived gap.

Two adjacent misroutes ride along:

- **The plain Smooth brush (and Shift-smooth) are mesh-path on multires
  today**, excluded only incidentally: `mapping.py:54` maps Blender `'SMOOTH'`
  to the engine's boundary-aware **BSMOOTH**, and the grids roster carries
  SMOOTH but not BSMOOTH (`grid_executor.h:451-487`), so
  `GridStroke_supported(BSMOOTH) == 0` and `grids_capable` says no
  (`stroke.py:173`).
- Program strokes on multires also **flip the draw provider to SLOT** for the
  stroke's duration (`stroke.py:235-240`) — paying the slot GPU-buffer build —
  and fall off `GridTree_castRay` for cursor raycasts (`stroke.py:551-565`).

Goal: **any program whose stages are all grids-capable runs grids-native, and
programs run inside the C++ batch driver on both the mesh and grids arms.**
Routing becomes a capability predicate, not an autosmooth special case.

## 1. Facts the design rests on

From code reading 2026-08-11 (two independent sweeps + three adversarial
reviews; file:line verified):

1. **A program is one engine object.** `BrushProgram`
   (`brush_executor.h:82-157`) = `Vector<BrushCommandEntry>`; each entry is a
   kernel enum id plus *sparse* overrides (`floatOverrides`,
   `attrLayerOverrides`, `overrideInvert`) pushed onto the **one shared
   `Brush`** before the command runs and rolled back after
   (`brush_executor.h:65-68`). The addon builds `[main]` or `[main, BSMOOTH]`
   in `build_program` (`stroke.py:479-500`), overriding only strength
   (propId 0) and invert on the smooth stage.
   **The overridden strength IS pressure-scaled on today's mesh path**
   (correction, §9): the 0.25 lands in the strength *prop store*
   (`brush_executor.h:1822`) and the per-entry `loadCommonProps` then applies
   the registered strength pressure device to it (`prop_struct.cc:40-48`;
   the addon attaches PRESSURE to strength for autosmooth strokes whenever
   the main brush has `use_pressure_strength`, `mapping.py:376`,
   `stroke.py:716-719` excludes only smooth *strokes*). Grids must reproduce
   this, and one parity test must run with a pushed pressure sample — a
   constant-baked smooth strength would pass synthetic tests and diverge
   under a pen. No overlap attenuation on either path; preserving all of
   this semantics exactly is the contract, changing it is out of scope.
2. **Mesh-side execution exists** — `CommandExecutor::execProgram`
   (`brush_executor.h:1673-1869`): one node filter, one freeze/thaw decision,
   **one stroke sample** for the whole program (`:1804-1805`), per entry
   push-overrides → createCommand → load props → exec → rollback. Overrides
   are applied at the **prop-store level** — `props.setFloat` with a
   `lookupFloat` snapshot for rollback (`:1811-1827`, restore `:1862-1867`)
   — and `writeProps` is never called inside the program (see E2). The
   chained SMOOTH's `co_prev` snapshot is re-taken **after** the main pass so
   it smooths the deformed result (`:1670-1672`) — the defining property; a
   fused single-kernel autosmooth would smooth the pre-deform surface
   (neighbor reads are Jacobi `co_prev` on every backend) and is rejected.
3. **The grids executor takes the kernel per dab call**
   (`GridStroke_dab(s, tool, ...)` → `createCommand(brushType)` first thing,
   `grid_executor.h:550-552`; nothing kernel-specific cached at
   `beginStep`). Two roster kernels can already be interleaved within one
   stroke — the structural precondition for a two-stage dab.
4. **But there is no grids program entry point** — `GridBrushExecutor` has
   only the single-tool `applyDab` (`grid_executor.h:549-553`) and is
   deliberately minimal ("no dyntopo, no meshlog, no attr overrides, no
   preview machinery", `grid_executor.h:12-20`). The batch c-api takes one
   `tool` scalar for the whole batch (`grid_stroke_c_api.cc:264`).
5. **Grids undo is safe for multi-kernel dabs.** `GridStrokeLog::captureLeaf`
   dedups per (leaf, field-class, step) (`grid_stroke_log.cc:93-125`);
   stroke-end fold and writeback key off accumulated touched verts, kernel
   count independent (`grid_executor.h:92-139`). The capture-before-write
   invariant holds across stages: a leaf written by stage 1 was in stage 1's
   query set, so `execPre` captured it before the write (verified §9). No
   mesh-style capture-slot plumbing needed. There is also **no freeze/thaw
   analog to violate**: grids neighbors come from the topology-only lattice
   ring1 CSR (`grid_executor.h:66-76`), which position writes never
   invalidate, and tree bounds refresh per stage-call when anything moved
   (`:765`).
6. **Two per-dab caveats** in `GridBrushExecutor::applyDab`: it pushes a
   stroke sample per call (`grid_executor.h:562`; ring saturates at 64,
   `brush.h:790-798` — degrades, doesn't wrap) — a naive two-call dab
   double-pushes and halves the STROKE_CURVED window; and `isFirstOfStep`
   clears after the first call (`:769`), so stage 2 of dab 1 would see
   `false` (mesh `execProgram` holds it constant, `brush_executor.h:1846`).
   `applyProgram` hoists both: one `updateStrokeFrame` + one
   `pushStrokeSample` per logical dab, `isFirstOfStep` constant across
   stages.
7. **The co_prev cost cliff**: a smooth-family stage on grids snapshots
   `co_prev` for the **full domain, O(level)**, every call
   (`grid_executor.h:618-628`, parallel copy of all verts; known —
   `plans/multires-grids-native-brush-path.md:402`). At 1M verts × ~84
   dabs/stroke, full-domain copies alone would add **~85–170 ms per stroke**
   (~12 MB each) and erase the routing win — E3 is load-bearing, and no
   stage may route smooth-family strokes onto grids before it lands (§6).
   co_prev has exactly one reader (`AccumLive::neighborCo`,
   `accum_mode.h:43-46`) and no stroke-start restore path (nonAccum
   from-base semantics go through `dispVec_`; BSMOOTH is
   `relaxesBase = true` and stays AccumLive, `grid_executor.h:497-514`) —
   so a region-restricted refresh is exactly sufficient.
8. **BSMOOTH's `vclass` read needs a binding, not a mesh**: the generated
   kernel reads `ctx.boundAttr<int>("vclass")` (`bsmooth.brush.gen.h:34`),
   which resolves through `ctx.attrBindings` — a plain
   `Vector<BrushAttrBinding>` of {handle, `mesh::AttrRef`}
   (`brush_command.h:163-173, 239-244`) with **no Mesh in the read path**.
   The mesh coupling lives only in `CommandExecutor::exec`'s resolution loop
   (`brush_executor.h:774-835`), which grids doesn't share. The grids ctx
   leaves `attrBindings` null today, so BSMOOTH without a shim null-derefs —
   the shim is genuinely required, and it is **small** (~20 lines): the
   executor already owns freestanding `mesh::AttrData` sidecars
   (`dispVec_`, `grid_executor.h:401-405`); one `AttrData<int>` + one
   synthetic binding suffices. `createBsmoothBrush` is already fully
   domain-generic (`bsmooth.brush.gen.h:98-113`, same shape as the roster's
   `createSmoothBrush` instantiation); its FACE-domain `bsmoothPre` capture
   is already no-op'd by `GridCapturePolicy` (`grid_executor.h:913-914`) and
   its saves are Co/No only, so the attr-save assert (`:928`) never fires.
   The hand-instantiated-template fallback in earlier drafts is dead weight
   — struck.
9. **What vclass actually contains in an addon session: zeros.** Multires
   enter (`_enter_multires`, `convert.py:138→217+`) seeds no edge flags —
   `_load_edge_flags` runs only on the plain-mesh path (`convert.py:162`) —
   so the cage's `vertClass` is identically 0, and today's mesh-path BSMOOTH
   *also* runs with vclass 0 (the materialized level mesh is flagless;
   `refreshBoundaryClassForBSmooth` gates on `boundaryDirty`,
   `brush_executor.h:1366-1373`, which a flagless mesh never sets).
   Independently, subdiv refinement propagates **only `EDGE_SHARP`**
   (`subdiv.cc:320-334`; no seam/projected/group/UV interpolation exists in
   `refineStep`), so even a flagged cage yields a materialized mesh whose
   vertClass is nonzero only along sharp chains. Consequence: **a
   zero-filled sidecar is exact parity with today's mesh path**, and any
   lattice-derived sidecar carrying seam/group/UV classes would make grids
   *diverge* from the mesh path it must match. The lattice derivation is
   therefore future work (§8), not part of this plan's deliverable.
10. **BSMOOTH ≠ SMOOTH even at vclass 0**: bsmooth's interior case applies
    the volume-preserving `(1 - projection)` normal damping
    (`bsmooth.brush.gen.h:80-82`) that plain SMOOTH lacks
    (`smooth.brush.gen.h:49-52`). Mapping the autosmooth stage (or the
    Smooth brush) to SMOOTH on grids would shrink volume relative to today's
    mesh-path result — silent downgrade, unacceptable. Grids must gain
    BSMOOTH.
11. **Batch driver shape**: `GridStroke_dabBatch` entries are 7 floats
    (center, normal, radius); strength/invert/pressure/mirrors are per-event;
    the loop does a per-logical-dab `writeProps` + device-refill cycle, then
    the primary + mirror inner calls (`grid_stroke_c_api.cc:264-301`).
    Device inputs are **non-consuming** (`pushDeviceInput` appends,
    `inputDeviceDatas` copies into `curDeviceValue`, `lookupValue` evaluates
    non-destructively, `prop_dynamics.h:31-43, 112-121`,
    `prop_struct.cc:10-51`) — so all stages and all mirror images of one
    logical dab see the same pressure sample, same as mesh
    (`mesh_stroke_batch_c_api.cc:96-116`). The batch loop's own
    `writeProps`-per-dab exists to undo loadProps destructiveness *between*
    logical dabs — it must never run *inside* a program (see E2).
12. **BSMOOTH's `projection` uniform costs nothing**: it is `@static`, the
    generated `loadUniformProps` is empty (`bsmooth.brush.gen.h:109-112`),
    and the kernel reads the plain Brush member `ctx.brush.projection`
    (`brush.h:248-252` — the TS-side name is `smoothProj`, the C++ member is
    `projection`), which `engine_props.apply` already syncs at stroke start
    (`engine_props.py:55-60` via `mapping.apply_brush_settings`,
    `stroke.py:730`) and the grids roster already exercises this convention
    (`ctx.brush.pinch`). One pre-existing, parity-neutral quirk to note:
    during an autosmooth stroke under a non-Smooth brush,
    `engine_props.apply` applies only the *main* kernel's props
    (`engine_props.py:49`), so `projection` holds whatever the last Smooth
    stroke wrote — identical on both paths, not this plan's problem.
13. **The vclass sidecar slot is structurally safe**: the grid domain's
    dense-id layout means boundary verts exist exactly once
    (`grid_domain.h:9-12`) — no replica-stitching ambiguity — and the whole
    domain drops on fold/rebuild, matching the existing mask/normals/CSR
    sidecars' invalidation. (Engine-level hole for *future* flagged-cage
    work: mid-session `setEdgeFlag` on the cage dirties the cage but drops
    no domain — moot while the addon seeds no flags.)

## 2. Design

### E1 — BSMOOTH on grids: zero-filled vclass binding + roster entry (engine)

- `GridDomain` gains a dense `int vclass` sidecar (one per dense vert),
  **zero-filled** at domain build. Per fact 9 this is exact parity with
  today's mesh-path BSMOOTH in every addon session, and anything richer
  would *break* parity. The lattice derivation from cage flags is future
  work (§8) with its own gating decisions.
- The read-only attr-binding shim (fact 8): one owned `AttrData<int>`
  sidecar + one synthetic `BrushAttrBindings` entry, set on the grids ctx in
  `applyDab`/`applyProgram`. ~20 lines; no fallback path needed.
- Roster entry: `createBsmoothBrush<GridBrushExecutor, GridCsrNbr, AccMode>`
  next to SMOOTH's (`grid_executor.h:475-477`). `relaxesBase = true` means
  the nonAccum re-instantiation branch (`grid_executor.h:508-511`) never
  runs for it; `needsCoPrev` follows SMOOTH's existing handling.
- **Independent payoff**: `GridStroke_supported(BSMOOTH)` flips to 1, so the
  plain Smooth brush and Shift-smooth route grids-native through the
  *existing* addon gates (their multi-pass Python loop stays host-side;
  per-pass `strength_override` reaches grids via
  `mapping.apply_dab_state` → `writeProps` → `loadCommonProps`, verified;
  batching the loop is the separate D2 item, `design/cpp-dab-loop.md:369-372`).
  Engine test `test_grid_stroke.cc:838` asserts `== 0` today and must flip.
  **This flip rides the existing gates, so it must be covered by the kill
  switch** (A1) — otherwise the first user-visible routing change has no
  rollback short of an engine rebuild — and it must not land before E3
  (fact 7's cliff; §6 ordering).

### E2 — grids program execution (engine)

- `GridBrushExecutor::applyProgram(BrushProgram *prog, float3 origin,
  float3 normal)`, mirroring `execProgram` semantics:
  - push **one** stroke sample + one `updateStrokeFrame` per logical dab
    (stage calls skip the push); hold `isFirstOfStep` constant across
    stages, clear at dab end;
  - per entry: apply float/invert overrides at the **prop-store level** —
    `props.setFloat(name, ov.value)` with a `lookupFloat` snapshot, restored
    exactly after the entry (mesh `execProgram`'s pattern,
    `brush_executor.h:1811-1827, 1862-1867`). **Never `writeProps` inside
    the program**: `loadCommonProps` assigns post-dynamics values into the
    Brush members (`brush.h:621-629`), so a member+`writeProps` override
    sequence would bake stage 1's pressure-decayed radius into the store and
    stage 2's `loadCommonProps` would apply the radius pressure curve a
    second time (radius × curve(p)² with `use_pressure_size` on) — a real
    parity bug. Store-level rollback restores the caller-written values, so
    the batch driver's per-dab writes are undisturbed.
  - per entry, call `loadCommonProps` (parity with mesh `:1838-1841`; this
    is what pressure-scales the overridden smooth strength, fact 1);
  - dispatch through the existing roster `createCommand`;
  - **clear `dabMoved_` once per program, not per stage** — the c-api marks
    extdraw/slot verts from `lastDabMoved()` after the call
    (`grid_stroke_c_api.cc:195-205`), and stage 2's moved set is *not* a
    superset of stage 1's (BSMOOTH skips masked verts and pins sharp
    junctions): per-stage clearing makes CLAY-moved, BSMOOTH-pinned verts
    vanish from the viewport until stroke end. Union across stages is a
    correctness requirement, not an optimization.
  - for smooth-family stages, refresh `co_prev` per E3 after the main
    stage, preserving the smooth-the-result property.
- c-api: `GridStroke_dabProgram(s, void *program, ox,oy,oz, nx,ny,nz,
  grabAdd)`. `BrushProgram` is a reflected type; the addon passes
  `session.program.ptr`.
- Grab-class stages are out of scope for programs (autosmooth already
  excludes grab-class strokes, `stroke.py:779`); asserted in
  `applyProgram`.

### E3 — region-restricted co_prev refresh (engine, prerequisite for any smooth-family grids routing)

- Replace the full-domain smooth-family snapshot with a refresh over the
  **consuming stage's read set**: the stage's query-leaf set closed under
  the `GridCsrNbr` 1-ring adjacency (leaf closure through the CSR, not a
  geometric radius pad — Gaussian falloff has no compact support, so the
  kernel reads the full 1-ring of every owned vert of every query leaf).
  Deriving the region from the *producing* stage's touched set is wrong: a
  vert inside the smooth stage's query radius that the main stage didn't
  move, but a previous dab's smooth stage did, would be read stale.
- Refresh stamps are keyed **per `applyDab`/stage call — i.e. per mirror
  image**, not per logical dab: a seam leaf inside both the primary and
  mirror query sets, refreshed only for the primary, reads positions stale
  by the primary image's writes when the mirror runs.
- Acceptance: co_prev refresh cost scales with the brush region, not the
  level size (region copies are tens of kB–~0.5 MB per stage-call — noise;
  the full-domain alternative is ~85–170 ms per stroke at 1M, fact 7).

### E4 — batch-driver program variants (engine)

- `GridStroke_dabBatchProgram(s, void *program, n, dabs, strength, invert,
  pressure, usePressure, signs, mirrorCount)` — identical loop to
  `dabBatch` but `applyProgram` per (dab × mirror). Composes cleanly: the
  batch loop's per-logical-dab `writeProps` + device refill stays outside
  the program; store-level override rollback (E2) restores exactly the
  values the batch loop wrote; device inputs are non-consuming (fact 11).
  Marks from the per-image unioned moved set (E2's `dabMoved_` rule).
- `MeshStroke_dabBatchProgram(executor, tree, mesh, brush, void *program,
  n, dabs, ...)` — same shape over `execProgram` instead of `execBrush`
  (which substitutes cleanly since `execProgram` never calls `writeProps`).
  This routes **non-multires** autosmooth through the batch driver too
  ("programs in general", not just grids).

### A1 — addon routing changes (addon)

**Three changes, not two** (the third was missing from the draft and would
have produced invisible edits + corrupt undo — a program stroke reaching
mesh-only `apply_dab_program` against the slot mesh with no meshlog step
open, since the grids branch of `stroke_begin` returns at `:234` without
`executor.beginStep()`):

1. **Grids gate** (`stroke.py:879-885`): allow `self._program is not None`
   when `program_grids_capable`. Consequences that ride along: provider
   stays GRIDS (no SLOT flip), raycast stays on `GridTree_castRay`,
   `stroke_end` takes the grids branch, undo takes the grids-log branch —
   all key off `session.last_stroke_grids` already; every consumer walked
   and verified program-agnostic (§9), no new plumbing, but covered by
   tests.
2. **Dab dispatch**: the per-image dab path must branch — when
   `last_stroke_grids` and a program exists, call `GridStroke_dabProgram`
   instead of the mesh-only `apply_dab_program` (`stroke.py:503-527`).
3. **Batch gate** (`stroke.py:828-831`): drop `self._program is None`
   **per-arm, symbol-gated**: the grids arm requires
   `GridStroke_dabBatchProgram` on the loaded capi, the mesh arm requires
   `MeshStroke_dabBatchProgram`. (The draft relaxed both arms in one stage
   while the mesh symbol landed a stage later — with
   `sculptcore_cpp_dab_loop` default-on, that breaks every non-multires
   autosmooth stroke. Per-arm gating makes the stages independent.)

- New helper `program_grids_capable(session, program_kernels)`: every stage
  kernel passes `GridStroke_supported` AND the `GridStroke_dabProgram`
  symbol exists on the loaded capi (`getattr`-gated, the established
  pattern).
- **Kill switch** `sculptcore_grids_programs` (default on) gates **all of**:
  the three changes above **and** BSMOOTH's admission in `grids_capable`
  (`stroke.py:159-173`) — because the Smooth/Shift-smooth flip from E1
  otherwise rides the existing gates with no addon-side lever (the first
  user-visible change would need an engine revert to roll back). One flip
  restores today's routing in full; all engine changes are additive
  symbols.
- `build_program` unchanged (`[main, BSMOOTH]`, strength-by-propId,
  invert pinned). `mapping.py:54` `'SMOOTH' → BSMOOTH` unchanged.
- MASK stays held back from grids (unchanged; mask truth lives in the slot
  mesh column, `stroke.py:160-164`).

## 3. Correctness invariants

- **One stroke sample + one stroke-frame update per logical dab**
  (STROKE_CURVED window preserved).
- **Store-level override rollback** per stage, restoring caller-written
  values; no `writeProps` inside a program (E2).
- **Pressure parity**: the smooth stage's overridden strength is
  pressure-scaled identically to mesh (per-entry `loadCommonProps`); at
  least one parity case pushes a device pressure sample (fact 1's test
  blind spot).
- **Moved-set union**: `lastDabMoved()` after `applyProgram` covers every
  vert any stage moved.
- **Undo**: leaf/field-granular dedup makes two stages capture-once; grids
  undo byte counts for `[main, BSMOOTH]` ≈ a single-**BSMOOTH** stroke on
  the same dab sequence (the smooth stage's query set is the superset;
  baselining against single-CLAY would fail for a non-bug).
- **Parity, split gate**: mesh `execProgram` vs grids `applyProgram` on
  identical dab sequences — tangent-plane positions at the tight eps
  (2e-3, the SMOOTH precedent, `test_grid_stroke.cc:257`); the
  normal-direction component at the INFLATE-class eps (5e-2) because
  BSMOOTH reads `v.no` and the two paths derive normals differently by
  design (recalc_normals' fan pick vs Newell cell fans — the harness's own
  documented divergence). Threaded executor ⇒ eps, never bit-exact.
- **Routing must be parity-neutral vs today's mesh-path program result** —
  achieved *by construction* via the zero-filled vclass binding (fact 9).
  The separate Clay magnitude question (sc peak_z 0.053 vs native 0.008) is
  explicitly NOT this work.

## 4. Tests

- Engine (`test_grid_stroke.cc`): flip the `GridStroke_supported(BSMOOTH)`
  assertion; program dab mesh-vs-grids parity (split eps per §3, one case
  with a pushed pressure sample); undo-bytes vs single-BSMOOTH;
  `dabBatchProgram` ≡ loop of `dabProgram`; a mirror case with a leaf in
  both images' query sets (E3's per-image stamp); ctest **full sweep**, not
  just multires (two past regressions only the full sweep caught).
- Addon headless: autosmooth stroke on multires → undo/redo cycling, save
  round-trip; provider stays GRIDS during the stroke; kill switch off →
  today's routing byte-for-byte (including Smooth back to mesh-path).
- Headed: `test_stroke_cancel.py` (ESC/window-close teardown), realistic
  bench.

## 5. Bench targets (realistic bench, interleaved, 1M/L4, vsync on)

- Clay: `stroke_ms` 862–931 → **≤ ~90 ms** — *at-risk, not padded*:
  independent arithmetic (§9) lands the estimate at 85–100 ms
  (grids single-kernel ~55 ms; BSMOOTH stage ≈ 1.5–2× the draw kernel ⇒
  +34–42 ms; E3 region copies are noise). The target survives only if
  BSMOOTH-per-dab lands ≲1.6× draw — if it misses on that term alone,
  report the measured number rather than force it.
  `stroke_frame_ms` median back to ~16.7 (locked vsync); no
  INBETWEEN-starvation regression (`events.moves` back to ~native counts).
- Draw: unregressed within the noise floor.
- Smooth brush on multires: measure before/after the E1 flip (mesh-path →
  grids); no committed target (multi-pass loop still host-side).
- Attribution runs with `--vsync off` + `--engine-trace` if targets miss.

## 6. Staging

Reordered after the pressure test: **no smooth-family grids routing before
E3** (fact 7's cliff would ship a Smooth-brush regression), and the
Smooth-flip stage carries the kill switch with it.

- **S1**: E3 (region-restricted co_prev refresh) + engine parity tests over
  the existing SMOOTH grids kernel. Engine-only; no addon-reachable
  behavior change (nothing routes smooth-family to grids yet). Lands alone.
- **S2**: E1 (zero-filled vclass binding + shim + roster BSMOOTH) **+ the
  addon kill switch**, including BSMOOTH's gate in `grids_capable`.
  Smooth/Shift-smooth flip to grids — with a lever, and post-E3. Measure.
- **S3**: E2 (`applyProgram` + `GridStroke_dabProgram`) + addon changes 1
  and 2 (grids gate + dab dispatch). Per-dab Python driver but
  grids-native — this alone should collapse most of the 900 ms. Measure.
- **S4**: E4 grids batch variant + the batch gate's **grids arm**. Measure.
- **S5**: `MeshStroke_dabBatchProgram` + the batch gate's **mesh arm**
  (non-multires autosmooth batching). Optional, independently landable.

Each stage independently revertible; the kill switch spans S2–S5.

## 7. Risks / open questions

- Bench target headroom is ~zero (§5) — the go/no-go term is BSMOOTH's
  per-dab cost on grids.
- E3 region derivation must come from the consuming stage's query leaves;
  the CSR closure is exact but the leaf-set bookkeeping per (image, stage)
  is new state — the mirror-stamp test in §4 is the guard.
- Stage-2 bookkeeping doubles per-dab query/bounds/capture walks (the
  ~0.38 ms/dab metadata budget again at worst — inside the §5 estimate).
- Batch × program prop interleaving: store-level rollback (E2) composes
  with the batch loop's writes by construction, but the ordering is subtle
  enough that `dabBatchProgram ≡ loop of dabProgram` (§4) is the invariant
  test, run with pressure on.
- `nonAccum`/`anchoredGrab`/grab-pinning are stroke-level state shared by
  all stages — fine for `[main, BSMOOTH]` (both non-grab), asserted in
  `applyProgram`.
- The stale-`projection` quirk under non-Smooth brushes (fact 12) is
  parity-neutral but user-visible in principle; candidate one-line fix
  (sync `projection` for any program containing BSMOOTH) belongs to a
  follow-up, not this plan.

## 8. Out of scope / future work

- **Lattice-derived vclass sidecar** (was E1 in the draft; demoted by the
  pressure test): only meaningful after two gated decisions — (a) semantics:
  sharp-only (matching what subdiv refinement actually propagates,
  fact 9) vs extending `refineStep` flag propagation vs intentional
  grids-side seam awareness (a *divergence* from the mesh path, needs its
  own justification); and (b) the addon seeding cage edge flags in
  `_enter_multires` at all, without which any derivation defends
  unreachable behavior. The draft's propagation bit-rules survived review
  (chain interiors are plain feature-class verts; endpoint/junction only at
  base verts) and are recorded here for that future work, along with the
  dense-id safety argument (fact 13) and the sharp-only A/B oracle
  (materialized-mesh `vertClass` is a valid reference for SHARP only).
- Pressure-/overlap-scaling the autosmooth stage *beyond* what the mesh
  path already does (note: the mesh path DOES pressure-scale strength —
  fact 1; the thing out of scope is adding overlap attenuation or new
  dynamics).
- Batching the multi-pass smooth stroke loop (D2, `design/cpp-dab-loop.md`).
- MASK on grids; dyntopo programs (dyntopo is excluded on multires,
  `stroke.py:788-794`).
- Clay deformation-magnitude parity vs native (separate investigation).
- GPU dispatch of the vclass attr (CPU-only mesh-side today as well).

## 9. Pressure-test log (2026-08-11)

Three adversarial lenses, each instructed to kill the plan. Findings and
dispositions:

**vclass/DSL lens** — 1 KILL, 2 WOUNDs: the draft's vclass A/B oracle was
unsatisfiable (subdiv propagates only `EDGE_SHARP`; verified directly) and
the lattice derivation defended unreachable behavior (multires enter seeds
no edge flags; verified directly) → E1 rebuilt around a zero-filled
binding, derivation demoted to §8. `smoothProj` → `projection` naming
fixed; shim confirmed small; fallback template struck; bit-rules and
dense-id safety recorded for future work.

**Executor-semantics lens** — 0 KILL, 5 WOUNDs: member+`writeProps`
override sequencing double-applies pressure dynamics → E2 now mandates
store-level setFloat/lookupFloat rollback; co_prev region respecified to
the consuming stage's CSR leaf closure with per-image stamps (E3);
`dabMoved_` union made a correctness requirement (E2); parity eps split
(§3); bench target flagged at-risk with the 1.6× condition (§5); S1
kill-switch gap folded into A1. Confirmed: no freeze/thaw analog, device
inputs non-consuming, undo capture-before-write holds, E3 load-bearing.

**Addon routing/undo lens** — 1 KILL, 4 WOUNDs: the S3/S4 batch-gate
staging contradiction (mesh arm relaxed before its symbol existed) → gate
is now per-arm symbol-gated, mesh arm moved to S5; the missing third addon
change (grids dab dispatch; without it, slot-mesh writes through an
unopened meshlog step) → A1 change 2; "no pressure" fact falsified →
fact 1 corrected + pressure-sample parity test; Smooth-flip-before-E3
regression risk → staging reordered S1=E3; kill-switch scope widened to
cover the E1 flip. Confirmed: UV behavior unchanged on multires, every
`last_stroke_grids` consumer program-agnostic, no new fork surface.
