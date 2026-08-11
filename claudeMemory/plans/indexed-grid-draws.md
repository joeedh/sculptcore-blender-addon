# Indexed draw buffers for multires grids (external-draw path) — PLAN

## Implementation notes (2026-08-10, Stages 1–2)

- **Amendment 2 landed with a different mechanism than its literal wording.**
  The prescribed smoke-test assertion `mode.bl_draw_provider != "0"` is
  unimplementable instance-free: RNA string getters need a live `PointerRNA`
  (class-attribute access on `bpy.types.*` does not go through RNA —
  `pyrna_struct_getattro` consults RNA properties only on instances,
  `bpy_rna.cc:4826-4856`), no RNA collection exposes registered
  ObjectModeTypes, and entering the mode on a bare CI runner risks
  GPU-dependent failure. The equivalent *failing* check built instead:
  - The engine provider struct leads with `int abi_version`, readable via
    ctypes from the `sc_external_draw_provider()` address.
  - The fork gained a new read-only RNA property
    `ObjectModeType.bl_draw_provider_abi_version` whose **default** carries
    `BKE_EXTERNAL_DRAW_ABI_VERSION` and is readable instance-free via
    `bl_rna.properties[...].default`.
  - `smoke_test_package.py` fails on: null provider, missing property (fork
    predates the bump), or version mismatch. The addon's `register()` does
    the same comparison up front (console warning, skips handing over a
    skewed provider), and `enter()` does a one-time `bl_draw_provider`
    readback (instance reads do hit the RNA getter) as belt-and-braces
    against silent rejection on forks predating the property.
- Stage 2 followed §3 as written; the per-span local base is recomputed
  during the fill walk (the OPEN question's "recompute" option). The
  kill-switch env is read once in the ctor; the updated `test_grid_stroke`
  extdraw block is mode-agnostic, so the whole suite passes under
  `SC_GRIDS_INDEXED=0` too.

## Stage-3 results (2026-08-10) — all gates passed

Interleaved RenderDoc A/B (two rounds of native→sculptcore, 12 frames/arm,
1M faces at L4, OpenGL, paced stroke):

- **Call type**: the grid nodes draw as `glDrawElementsIndirect` with
  RenderDoc's `Indexed` action flag set (verified per-drawcall from a raw
  capture dump, not from `top_actions` — the indexed grid draws are cheap
  enough that they mostly *drop out* of the analyzer's per-frame top-15,
  which is dominated by unrelated `glDrawArrays*` overlay/scene draws; the
  aggregate "draw vertices" column also cannot distinguish the modes, since
  an indexed node's index count equals the old soup's corner count).
- **GPU frame (median)**: sculptcore **4.10 / 4.04 ms** vs native
  **4.75 / 4.78 ms** across the two rounds (drawcall GPU 3.16 vs 3.86/3.77) —
  the sculptcore arm now *beats* native by ~0.7 ms, versus the pre-plan +1 ms
  deficit. The ≲0.3 ms gate is passed with the sign flipped; the <0.5 ms
  keep-on-memory-grounds decision point is moot.
- **peak_z**: bit-identical between the soup DLL and the indexed DLL under
  the identical headless-driven bench (`0.013884586282074451` =
  `0x1.c6f85a0000000p-7`, 1018081 verts, 5 strokes).
- **stroke_ms**: no regression — median 48.2 → 46.0 ms, per-dab cycle
  16.2 → 12.4 ms (same bench pair; small n, direction confirmed by the
  interleaved trace's per-dab cycle 7.3 native vs 3.2–3.5 sculptcore).

`SC_GRIDS_INDEXED=0` remains the rollback lever.

**Stage 4 ran and closed with no change**: interleaved headed sweep
(`run_tuning_headed.mjs`, 1M/L4, 2 reps) of `auto` vs `tris=32768` vs
`tris=131072` under the indexed fill — `auto` wins or ties everywhere
(stroke 48.5/48.9 ms vs 49.4–54.9; the larger nodes trade ~0.15 ms of
sculpt_view for more per-stroke dirty-node refill). The 2.2×-viewport
draw-node target survives the indexed cost model; keep the autotune as is.
Raw table: scratchpad `stage4-tune/results/summary.json` (2026-08-10 run).

**Status: all stages complete (2026-08-10); indexed draws are on by default,
draw-node autotune unchanged.** Written 2026-08-10 from code reading of
engine `GridDrawSource`, the extdraw ABI on both sides of the repo seam, the
fork's `draw_external.cc` upload path, and native `draw_pbvh.cc`'s grid index
buffers. Everything cited was read in source at the given lines; the few
things that could not be verified are tagged OPEN/UNVERIFIED inline.

## 1. Goal and motivating measurement

[research/redraw-gpu-pipeline-ab.md](../research/redraw-gpu-pipeline-ab.md)
(RenderDoc A/B, 1M faces / L4, OpenGL, workbench prepass, dev-box AMD iGPU):
native sculpt draws **indexed** (`glDrawElementsIndirect`, ~450 calls × ~12288
indices, ~1.05M unique vertex fetches via post-transform reuse) while
`GridDrawSource` emits **non-indexed triangle soup** (`glDrawArraysIndirect`,
248 calls × 24528 verts, all 6.1M verts fetched and shaded) — ~6× the vertex
bandwidth, +1.5 ms mesh-drawcall time, and after the region-tag fix it is the
**only remaining GPU-frame gap vs native** (~+1 ms, 5.7 vs 4.7 ms). Both arms
already use the identical 20-byte vertex format (float3 pos +
R16G16B16A16_SNORM normal) and the same prepass shader, so the whole gap is
vertex fetch. Do not re-derive these numbers; that doc is the baseline.

The fix: keep the node partition, node ids, and dirty tracking exactly as they
are, and change *what a node's buffers contain* — a shared-vertex lattice
layout plus a per-node index buffer that is a **pure function of the level
topology** (static per level, generated once), carried across the extdraw ABI
so the fork can build a `gpu::IndexBuf` and an indexed batch.

## 2. Current state (what the code actually does)

### Engine: soup fill

- `GridDrawSource` partitions cell **rows of whole grids** into nodes of
  ~`drawNodeTriTarget` tris (`buildPartition`,
  `engine/source/subdiv/grid_draw_source.cc:36-86`). `rowNode_` maps
  `grid*S + cellRow -> node`; spans within a node merge when contiguous
  (:62-66). Node ids are `kIdBase + ordinal`, stable for the level's lifetime
  (`grid_draw_source.h:49,102-105`); every node is born
  `Update_Data|Update_Topo` (:74).
- `fillNode` (`grid_draw_source.cc:101-131`) is the "42 floats per cell"
  pattern: per cell, 6 corners × (float3 pos + float3 no + float mask) = 42
  floats, gathered through `gridVerts()` lattice lookups, split `(a,b,c) +
  (a,c,e)` (:114-119). `n.verts = rows * 2S * 3` soup corners (:52).
- Dirty tracking is exact and row-granular: `markVerts` maps each moved vert
  through the occurrence table to cell rows `lv-2..lv+1` (the cell-Newell
  normal closure, :133-155); `update()` refills marked nodes in parallel and
  sets `Update_Data` (:174-202). Feeds: per-dab moved set
  (`engine/source/brush/c-api/grid_stroke_c_api.cc:196-199`), deferred-normals
  flush (`GridStroke_flushNormals` → `markVerts`, :119-133), stroke end
  (:311-314), undo swaps, and `markAllData` on mask sync (:161-168).
- The domain gives everything needed for a shared layout:
  `GridLevelDomain::gridVerts(g)` is the `(S+1)^2` lattice→dense-vert table
  (`engine/source/subdiv/grid_domain.h:73-75`), `no`/`mask` are dense sidecars
  (:117-120), and boundary verts are dense ids shared across grids (:8-12) —
  seam consistency is by construction, not stitching.

### The ABI (both sides, mirrored by layout)

- Engine: `ScExternalDrawNode` carries only vertex streams — `positions`,
  `normals`, 4-slot `attrs` (color@0/uv@1/mask@2/fset@3), `verts_num`
  ("multiple of 3"), `material_index`, `update_flags`, stable `node_id`,
  AABB (`engine/source/spatial/c-api/external_draw.h:25-37`);
  `SC_EXTERNAL_DRAW_ABI_VERSION 2` (:17). No index stream exists — an
  engine-only stage cannot produce the GPU win.
- Fork mirror: `ExternalDrawNode` / `BKE_EXTERNAL_DRAW_ABI_VERSION 2`
  (`C:\dev\blender\main\source\blender\blenkernel\BKE_object_draw_provider.hh:41,60-87`).
  `BKE_object_mode_draw_provider_set` **rejects** a version mismatch and
  leaves `mt->draw_provider` null
  (`blenkernel/intern/object_modes_custom.cc:73-79`) — the mode then draws the
  evaluated mesh (no crash, but no engine geometry either).
- Both engine fill sites zero-init the node (`ScExternalDrawNode dn = {};`,
  `spatial/c-api/external_draw.cc:131`, `subdiv/c-api/grid_draw_c_api.cc:66`),
  so **appended struct fields default to null/0** — the mesh/spatial-tree path
  stays soup with no code change beyond the struct.

### Fork: upload and batch

- `node_upload` (`draw/intern/draw_external.cc:235-409`): reallocs when batch
  missing, `verts_num` changed, the attr-stream set flipped, or TOPOLOGY is
  flagged (:252-255); STATIC usage + `GPU_vertbuf_data_alloc` per refill +
  `GPU_vertbuf_tag_dirty`/`GPU_vertbuf_use` (the 2026-08-10 usage-hint fix,
  :268-269, :365-390); batch is `GPU_batch_create(GPU_PRIM_TRIS, nullptr,
  nullptr)` + vertbuf adds — **no index buffer anywhere** (:392-408). Caches
  are keyed by `node_id` in a per-object map (:202-224). There is a
  soup-order flat-normal fallback when `normals == nullptr` (:317-327).
- Native reference: `draw_pbvh.cc` grids nodes hold each grid's `gridsize²`
  verts contiguously (`verts_per_grid`, :548) and index them per grid with a
  node-local offset — `create_tri_index_grids` (:1200-1237) emits 2 tris/quad
  as `uint3`s into a `GPUIndexBufBuilder`
  (`create_tri_index_grids` wrapper, :1547-1589). That is where "~12288-index
  nodes" comes from: ~2048 quads × 6 indices. The de-indexed "flat layout" is
  used **only** for nodes containing sharp faces (`calc_use_flat_layout`,
  :1461-1500) — the engine's grids path has no sharp-face or hidden-face
  support (no hide state anywhere under `engine/source/subdiv/`), so the
  indexed layout applies to every grids node unconditionally.
- Handy fork API: `GPU_indexbuf_build_from_memory(GPU_PRIM_TRIS, data,
  data_len, index_min, index_max, false)` builds an IBO straight from a
  contiguous uint32 array (`gpu/GPU_index_buffer.hh:222-227`); the GPU module
  squeezes to 16-bit indices itself when the range fits
  (`squeeze_indices_short`, :118).

## 3. Design: per-node shared-vertex layout + static index buffer

### Vertex layout (engine)

Node vertex streams become the **lattice rows** of the node's spans instead of
de-indexed cell corners. For span `{grid, row0, rows}`: lattice rows
`row0 .. row0+rows` (that's `rows+1` rows) × `(S+1)` verts each, row-major,
gathered through `gridVerts(grid)`. Spans concatenate; each span records its
local base offset.

- `n.verts = Σ_spans (rows+1)·(S+1)` — no longer a multiple of 3.
- Per-vert fill is 7 floats (pos3 + no3 + mask1) with a contiguous row walk
  instead of today's 42 floats per cell through 6 lattice lookups — ~1/6 the
  writes and a friendlier access pattern.
- Duplication happens only (a) across node boundaries (a band-split grid's
  boundary lattice row is written by both nodes) and (b) across grids (two
  grids sharing dense seam verts each write their own lattice copy — same as
  native, and it keeps a future per-grid attribute (Ptex-style UV, per-grid
  fset) representable without a layout change). At 1M/L4 total unique verts
  ≈ 4096 grids × 17² ≈ 1.18M + band duplicates — right at native's ~1.05M
  fetch count, ~5.3× below the 6.1M soup.

### Index buffer (engine)

Per node, built **once at partition build** (indices are a pure function of
`spans` + `S`, which are fixed for the source's lifetime — same stability
argument as node ids, `grid_draw_source.h:14-20`):

```
for span (local vert base B):
  for cell (r in row0..row0+rows-1, u in 0..S-1):
    a = B + (r-row0)*(S+1) + u;  b = a+1;  c = a+(S+1)+1;  e = a+(S+1)
    emit (a,b,c), (a,c,e)     // exactly today's winding, fillNode :114-119
```

`indices_num = Σ_spans rows·S·6`. Stored as `Vector<uint32_t> indices` on
`Node`. A **data** refill never touches it; only construction (born
`Update_Topo`) ever generates it. All node-local — no cross-node index
sharing, so the fork's per-node cache model is untouched.

### What changes, what doesn't

| invariant | status |
| --- | --- |
| partition, `rowNode_`, span merging | unchanged (`buildPartition` byte-for-byte) |
| node ids (`kIdBase + ordinal`), born-dirty, consume-on-read | unchanged |
| `markVerts` ±2-row closure | unchanged, and still correct: a lattice-row-`lv` vert is in a node's stream iff the node owns a cell row in `[lv-1, lv]`, which `lv-2..lv+1` covers |
| `GridStroke_flushNormals` / dab / end / undo dirty feeds | unchanged (they call `markVerts`/`markGrids`; only `fillNode`'s body changes) |
| mask@2 gating on `maskChannelExists()` (`grid_draw_c_api.cc:53-59`) | unchanged; the mask stream is per-vertex and indexes identically |
| color/uv/fset slots on the grids path | still null (nothing to index) |
| AABB | identical point set (cell corners == lattice verts) |
| shading | bit-identical: soup already wrote the same shared `d.no[v]` per corner; indexed shares them exactly |
| `n.verts % 3 == 0` | **gone** — `verts_num` is unique-vert count when indices are present |

### Engine files/functions to touch

- `engine/source/subdiv/grid_draw_source.h` — `Node` gains
  `Vector<uint32_t> indices;` (+ per-span local base if not recomputed);
  header comment rewrite (it currently promises "de-indexed triangle soup",
  :6-7).
- `engine/source/subdiv/grid_draw_source.cc` — `buildPartition` additionally
  computes `n.verts` (unique) and builds `n.indices`; `fillNode` becomes the
  row-walk vertex fill. Env kill-switch `SC_GRIDS_INDEXED=0` (read in the
  ctor, like `multires_tuning.cc`'s env overrides) restores the soup fill and
  leaves `indices` empty.
- `engine/source/subdiv/c-api/grid_draw_c_api.cc` — `grids_nodes_get` sets
  `dn.indices = n.indices.data()` / `dn.indices_num` **on every sync** (the
  host may realloc on any sync — e.g. the mask-stream flip, :50-56 — and
  needs index data then; the arrays are engine-owned and static, so this is
  free).
- `engine/source/spatial/c-api/external_draw.h` — struct + version (below).
- `engine/tests/test_grid_stroke.cc:637-777` — the coverage walk sums soup
  corners and asserts `verts_num % 3 == 0` (:686,691-695); change it to walk
  `indices` (sum `positions[indices[k]]` — the expected sum at :660-677 is
  already corner-based and stays valid), assert every index `< verts_num`,
  `indices_num == 6 × Σ cells`, and both fill modes (env off → soup) agree on
  the corner sum.

## 4. The ABI change (v2 → v3) and the compatibility story

Append to `ScExternalDrawNode` / `ExternalDrawNode` (identical order both
sides — they mirror by layout):

```c
/** Optional node-local triangle index stream: 3 indices per triangle into
 * this node's vertex streams. Null -> non-indexed soup (verts_num is then a
 * multiple of 3, every 3 verts a triangle). When set, normals must be
 * provided (the flat-normal soup fallback does not apply). */
const uint32_t *indices;
int indices_num;
```

Bump `SC_EXTERNAL_DRAW_ABI_VERSION` (`external_draw.h:17`) and
`BKE_EXTERNAL_DRAW_ABI_VERSION` (`BKE_object_draw_provider.hh:41`) to **3**,
in the same lockstep engine+fork change. This is unavoidable: the struct is
read as an array (`ExternalDrawNode *nodes` + count), so appended fields
change the element stride — there is no "optional tail" trick.

Compatibility story:

- **Mismatch behavior is refusal, not corruption**: the fork's
  `BKE_object_mode_draw_provider_set` returns false and the provider stays
  null (`object_modes_custom.cc:75-77`) → `BKE_object_use_external_draw` is
  false → the object draws its evaluated mesh. With the addon's multires
  `show_viewport` suppression that means the **base cage**, silently. Cheap
  hardening (recommended, addon-side): after registration
  (`sculptcore_addon/__init__.py:81` sets `bl_draw_provider`), read the
  property back — the fork's getter returns the accepted pointer or `"0"`
  (`rna_object_mode.cc:241-252`) — and print a loud console warning naming
  the fork/engine version skew on `"0"`.
- The addon's own DLL ABI gate (`engine/python/sculptcore/_capi.py:19-20,
  274-278`, `LSTL_AbiVersion`) is a **separate, orthogonal** check; the
  extdraw bump does not touch it (UNVERIFIED whether the litestl ABI version
  also *should* bump — it guards the binding thunk ABI, not extdraw, so no).
- Cross-repo choreography is the existing one (dispatch the fork's
  `build.yml` first, pin `build-packages.yml` to that run — see the packaging
  section of the root CLAUDE.md). A fork build
  predating the bump packaged with a bumped engine yields the base-cage
  symptom above; the package smoke test does **not** catch it (it checks the
  engine loads, not that the provider registered) — one more reason for the
  addon-side readback warning, which `verify_addon.py`'s console output would
  then surface. OPEN: whether to make `smoke_test_package.py` assert
  `mode.bl_draw_provider != "0"` — cheap and worth doing while in there.

## 5. Fork changes (`draw_external.cc` — stays engine-agnostic)

The fork consumes a generic uint32 index array; nothing engine-specific
enters. All in `C:\dev\blender\main\source\blender\draw\intern\draw_external.cc`:

- `NodeCache` (:136-200): add `gpu::IndexBufPtr ibo;` + `int indices_num = 0;`
  (move ctor/assign updated — note the existing raw-`batch` move hazard
  comment :158-160).
- `node_upload` (:235):
  - `have_indices = node.indices != nullptr && node.indices_num > 0`.
  - Realloc condition (:252-255) additionally triggers on
    `cache.indices_num != node.indices_num` or index presence flipping.
  - On realloc: `cache.ibo = gpu::IndexBufPtr(GPU_indexbuf_build_from_memory(
    GPU_PRIM_TRIS, node.indices, node.indices_num, 0, node.verts_num - 1,
    false))` (`GPU_index_buffer.hh:222-227`; the min/max lets the GPU module
    squeeze to u16 when a node's vert count fits — at the autotuned ~4.6k
    verts/node it always will). On DATA-only uploads the IBO is untouched —
    indices are static per level.
  - Batch creation (:392-393) becomes `GPU_batch_create(GPU_PRIM_TRIS,
    nullptr, cache.ibo.get())` when indexed (non-owning; `IndexBufPtr` owns),
    unchanged otherwise.
  - Flat-normal fallback (:317-327) is soup-only; for an indexed node with
    null normals, keep it defined: fill zeros + debug assert (the ABI doc
    says indexed ⇒ normals present; the grids source always sends them).
- Doc comment on `ExternalDrawNode` (:60-63 "de-indexed triangle soup")
  updated alongside the struct.
- Downstream passes need nothing: `SculptBatch` just carries the
  `gpu::Batch *` (:504-510), and every consumer (workbench prepass, overlays,
  EEVEE per-material via `external_batches_per_material_get` :531-537)
  already draws native PBVH batches that are indexed — an indexed external
  batch is indistinguishable at that layer. The mask/fset overlay streams
  (:286-289) are per-vertex VBOs in the same batch and index identically.

## 6. Staging

**Engine-only first is not possible** for the GPU win — the ABI carries no
index stream (v2 structs, §2), and the IBO must be built by Blender's GPU
module (provider contract: CPU arrays only,
`BKE_object_draw_provider.hh:19-22`). The smallest safely landable first unit
is the ABI+fork pair; the engine's layout change is second and independently
testable.

1. **Stage 1 — ABI v3 + fork indexed support (no behavior change).**
   Engine: append fields + bump `SC_EXTERNAL_DRAW_ABI_VERSION`; both fill
   sites keep emitting soup (zero-init covers the new fields). Fork: bump +
   `node_upload` indexed path (dormant). Addon: `bl_draw_provider` readback
   warning. Land as the usual lockstep pair; validate *no change*: RenderDoc
   still shows `glDrawArrays*`, `peak_z` identical, ctest green, fork build
   green.
2. **Stage 2 — engine indexed fill.** `GridDrawSource` shared-vertex layout +
   static per-node indices, default on, `SC_GRIDS_INDEXED=0` kill-switch.
   Update `test_grid_stroke.cc` as §3. Engine-only commit + DLL re-vendor; no
   addon Python changes.
3. **Stage 3 — measure.** `run_gpu_trace.mjs` A/B (§9) + headless refill
   bench. Sign-off gate: GPU frame gap vs native closes to ≲0.3 ms at 1M/L4,
   `peak_z` bit-identical, no stroke_ms regression.
4. **Stage 4 — retune the draw-node knob** (optional, after 3): the autotune
   knee (`multiresAutoTune`, `engine/source/subdiv/multires_tuning.h:32-44`)
   balanced host per-node cost against refill-per-size cost
   ([research/multires-autotune.md](../research/multires-autotune.md), the
   `sqrt(33·tris)` rule / 2.2× viewport win). Indexed refill writes ~1/6 the
   data, so the knee should move toward **larger nodes / fewer draw calls**;
   re-run the headed sweep (`run_tuning_headed.mjs`) before touching the
   constant. Do not fold this into Stage 2 — one variable at a time.

## 7. Scope boundaries — what stays soup, and why that's fine

**Multires grids path only.** The mesh/dyntopo path
(`spatial/c-api/external_draw.cc` over `SpatialTree` GpuData) keeps its soup:

- Dyntopo churns topology per dab — per-node index buffers would rebuild
  every dab, exactly the cost class indexing is supposed to avoid. (And that
  path's history bites: the disappearing-geometry bug was fixed by stable
  `node_id` keying — ABI v2; nothing here may reintroduce positional pairing.
  This plan never touches node identity.)
- Its dynamic attr layout carries **corner-domain** streams (uv@1 is corner
  float2, `external_draw.h:83-87`), which need split verts — the same reason
  native keeps the *mesh* PBVH path de-indexed (`draw_pbvh.cc:1466-1467`).
- The residual GPU gap is measured to be entirely the grids soup; the mesh
  path has no established measurement motivating the work.

The grids path has no sharp-face or hidden-face state (§2), so it needs no
per-node soup/indexed heterogeneity — but the ABI keeps `indices == null`
meaning soup per node forever, which is both the mesh path's contract and the
rollback lever.

## 8. Win ceiling, cost, memory (1M/L4, autotuned ~249 nodes / ~8.1k tris)

Per node today: ~24.4k soup verts. Indexed: ~254 band rows → ~4.6k unique
verts + ~24.4k uint32 indices (u16 after squeeze).

- **GPU frame**: fetches 6.1M → ~1.15M (≈ native's 1.05M). Expect to recover
  most of the +1.5 ms mesh-drawcall delta / ~+1 ms residual frame gap on the
  iGPU; proportionally more at deeper levels (soup grows 4× per level, unique
  verts too, but bandwidth per fetched vert is the multiplier being removed).
  Ceiling honesty: the remaining call-count and cull structure are already
  equal-or-better than native, so ~1 ms/frame at this scene is the realistic
  prize — this is a polish item, not a stroke_ms lever (vsync present is the
  shared wall).
- **Refill CPU**: writes drop ~6× (7 floats/vert × 1/6 the verts, contiguous
  rows instead of per-corner gathers); index generation moves to
  construction. Expect the measured ~2.9 ms full-pass `GridDrawSource` refill
  (task baseline; same rig) to land well under 1 ms. Fork upload cost
  (memcpy + `normal_float_to_short` per vert, `draw_external.cc:304-327`)
  drops by the same factor. UNVERIFIED until Stage 3's bench — the row walk
  adds `(rows+1)` boundary-row writes and span bookkeeping, but nothing
  plausibly cancels a 6× write reduction.
- **Memory**: engine-side node buffers 6.1M×28B ≈ 171 MB → ~1.2M×28B + 24 MB
  indices ≈ **56 MB**; fork GPU side (pos+nor+msk+fset ≈ 36B/vert)
  ~220 MB → ~43 MB + 12–24 MB IBO ≈ **~60 MB**. (Estimates; the always-alloc
  msk/fset streams :288-289 are included.)
- **Enter cost**: initial fill shrinks with refill; index build is O(cells)
  once — noise next to `Refiner::refine` (~70% of enter).

## 9. Rollback and validation

**Rollback**: `SC_GRIDS_INDEXED=0` (engine env, no rebuild) → soup fill,
null indices, fork takes today's path. The fork keeps the soup branch
permanently (mesh path), so rollback needs no fork change. A full Stage-1
revert is the ordinary lockstep-pair revert.

**Validation**:

- Engine ctest (`node make.mjs test`): updated `test_grid_stroke` coverage
  (index-walk sum == independent lattice walk, bounds, both env modes), plus
  the existing `test_multires` / `test_multires_stroke` gates untouched.
  (Known-failure list per memory: match the four names, not the count.)
- **Bit-identical `peak_z`**: this is a display-only change; any drift in the
  headless/headed benches' `peak_z` is a bug, full stop.
- RenderDoc rig: `claudeMemory/scripts/run_gpu_trace.mjs`, interleaved
  order-flipped pairs per the harness's own methodology (never batched
  A-then-B runs on this box) — expect `glDrawElements*` calls in the
  sculptcore arm, fetched-vertex count ~1.1M, GPU frame → ~4.7-5.0 ms.
  UNVERIFIED: whether the replay's "drawn vertices" counter reports indices
  or unique fetches for indexed draws — read call types + GPU ms as primary,
  the vertex counter only after confirming its semantics on the native arm.
  Launch detached (the sandbox wrapper kills capture runs; silent is
  healthy).
- Headless refill bench (`bench_multires_tuning.py` rig) for the CPU claim;
  headed `run_tuning_headed.mjs` only if Stage 4 proceeds.
- Fork side: normal fork build + `build-blender-dist.mjs` verify chain;
  visual spot-check of mask overlay + multi-material objects (per-node
  `material_index` path) + a level switch (source teardown/rebuild) + undo
  (markGrids refill) in the GUI.

## 10. Open questions

- OPEN: pack per-span local bases into `Node` vs recompute in fill — trivial
  either way; decide at implementation.
- OPEN: `GPU_indexbuf_build_from_memory` currently still makes a local copy
  (its own `\todo`, `GPU_index_buffer.hh:220`) — one extra memcpy per node
  per *topology* build only; ignore unless profiling says otherwise.
- OPEN: add `mode.bl_draw_provider != "0"` to `smoke_test_package.py` (§4) —
  recommended, tiny, but touches CI test scope.
- OPEN: should Stage 4 retune also revisit `kNodeTriTarget`'s test default
  (tests pass explicit small targets, so probably inert)?
- UNVERIFIED: EEVEE/Vulkan-backend behavior with indexed external batches was
  argued by construction (native PBVH batches are indexed through the same
  consumers), not run. The GUI spot-check in §9 covers workbench + overlays;
  do one EEVEE viewport sanity pass before sign-off.

## Pressure-test verdict (2026-08-10)

Adversarial review against source on both sides of the seam (engine
`grid_draw_source.{h,cc}` / `grid_draw_c_api.cc` / `grid_stroke_c_api.cc` /
`grid_stroke_log.cc` / `grid_domain.h`; fork `draw_external.cc` /
`BKE_object_draw_provider.hh` / `object_modes_custom.cc` / `rna_object_mode.cc`
/ `gpu_index_buffer.cc` / overlay consumers; addon `convert.py` / `stroke.py` /
`__init__.py` / `_capi.py`). Goal was to kill the plan; it survives, with two
must-fix amendments.

**VERDICT: BUILD WITH AMENDMENTS** (ranked below).

### Amendments (ranked)

1. **MUST-FIX — the §5 `GPU_indexbuf_build_from_memory` call is wrong as
   written.** `data_len` is the **primitive count**, not the index count: the
   implementation computes `indices_num = data_len *
   indices_per_primitive(prim_type)` and copies that many uint32s
   (`gpu/intern/gpu_index_buffer.cc:483-500`;
   `GPU_index_buffer.hh:125-136` — `GPU_PRIM_TRIS` → 3). Passing
   `node.indices_num` as `data_len` allocates and reads 3× the engine array
   (out-of-bounds read of engine-owned memory, then 3× the triangles drawn
   from garbage indices). Pass `node.indices_num / 3` (and
   `BLI_assert(node.indices_num % 3 == 0)`). Everything else about the call
   checks out: it does go through `IndexBuf::init`, which squeezes to u16 when
   `max-min+1 <= 0xFFFF` (`gpu_index_buffer.cc:334-348`), and it does make a
   full CPU copy per build (the header's own `\todo`, topology-time only).

2. **MUST-FIX — the skew-pair failure mode currently has *no failing check
   anywhere in the deployment chain*; promote §4's OPEN item to a Stage-1
   requirement.** Verified: refusal is real and bidirectional
   (`object_modes_custom.cc` `BKE_object_mode_draw_provider_set` rejects any
   `abi_version != BKE_EXTERNAL_DRAW_ABI_VERSION`, leaving the provider null
   — reading `abi_version` from a differently-sized struct is safe since it
   is the first field), the RNA getter really does return `"0"` on refusal
   (`rna_object_mode.cc` `rna_ObjectModeType_draw_provider_get`, and the RNA
   *setter* discards `BKE_object_mode_draw_provider_set`'s return, so the
   addon's class registration at `sculptcore_addon/__init__.py:81` gets no
   error), `smoke_test_package.py` contains zero provider checks (grepped),
   and the addon's `_capi.py` LSTL gate is orthogonal as claimed
   (`ABI_VERSION = 1` guards `LSTL_AbiVersion()` only, `_capi.py:19-20,
   274-280`). With fork builds at ~2.5 h and packaging pinned by run id, a
   skewed pair shipping a silent base-cage package is a *likely* event, not a
   tail risk. Stage 1 must land with (a) the addon readback warning and (b)
   the `smoke_test_package.py` assertion `mode.bl_draw_provider != "0"` in
   the same change — a console print alone fails nothing.

3. **RISK (accepted, gated) — the ~1 ms attribution is partly inferential.**
   The 5.7 vs 4.7 ms A/B is measured (research doc §measurements confirm the
   plan's numbers), but "~1.05M unique fetches" is *derived* (450 × 12288 =
   5.5M indices; ~4096 grids × 17² ≈ 1.18M VBO-resident verts), not a counter
   read, and actual vertex-reuse efficiency on this RDNA iGPU is assumed. The
   two arms also differ in call structure (248 big calls vs ~450 smaller), so
   attributing 100% of the residual to vertex fetch is a hypothesis the fix
   itself will test. Keep Stage 3's ≲0.3 ms gate as the go/no-go — and add
   the miss path now: if the measured win lands under ~0.5 ms, the decision
   to keep it must be re-argued on the memory savings (~171→56 MB engine +
   ~220→~60 MB GPU at 1M/L4, real and load-bearing on an iGPU with shared
   memory) rather than silently shipped as a perf win that didn't happen.

4. **NIT** — indexed-node-with-null-normals zero-fill (§5) is fine;
   `grid_draw_c_api.cc:68` sets `dn.normals` unconditionally, so the branch is
   genuinely unreachable from the grids source. Keep the debug assert.

### Kill-lenses that did NOT fire (verified in code)

- **Dirty closure under the lattice layout is exactly sufficient.** The
  refill is *node-granular* (`update()` refills whole marked nodes,
  `grid_draw_source.cc:194-201`), so the "dirty row changes the refill
  region" concern is moot: a node's lattice-vertex set (rows
  `row0..row0+rows`) equals its soup corner set — identical data-dependency
  set, identical marking requirements. A lattice-row-`lv` vert is in exactly
  the nodes owning a cell row in `[lv-1, lv]`; changed data spans rows
  `lv-1..lv+1` (the `refreshNormals` closure, `grid_domain.h:93-96`); nodes
  owning `[lv-2, lv+1]` are marked (`grid_draw_source.cc:146-148`). Exact
  cover, zero slack — same as soup.
- **Cross-grid seam copies stay consistent** for the same reason they do
  today: all copies read the same dense sidecars (`grid_domain.h:8-12,
  117-120`), moved verts are marked through *all* their occurrences
  (`grid_domain.h:83-89`, `grid_draw_source.cc:140-153`), and deferred
  normals feed the *reshaded* set — not just moved verts — through
  `markVerts` (`grid_stroke_c_api.cc:119-127`), so a seam vert whose normal
  changed marks the neighbor grid's nodes via its own occurrences. Undo swaps
  feed owned verts per leaf the same way (`grid_stroke_log.cc:195-206`).
- **Winding is safe by construction**: the index generation replicates
  `fillNode`'s emission order per cell (`grid_draw_source.cc:114-119`), no
  per-grid flip exists anywhere in the fill, so indexed output is
  triangle-for-triangle identical to today's soup. (Native's CW quad
  disposition in `create_tri_index_grids` differs from the engine's split —
  irrelevant, the engine is self-consistent.)
- **Indices really are static per source lifetime**: level switches tear down
  and rebuild the source (`sc_external_draw_register_grids` replaces +
  destroys, `grid_draw_c_api.cc:126-141`; the addon rebinds the provider on
  any level change, `convert.py:1664-1671`), domain drop/revive is data-only
  (`boundGen_` → `markAllData`, `grid_draw_source.cc:180-184`; `side_` is a
  pure function of level), and no hide/sharp state exists under
  `engine/source/subdiv/` (grepped). Nodes with coincidentally equal counts
  after a rebuild are covered by born `Update_Topo` → fork realloc → IBO
  rebuild (`draw_external.cc:252-255` + §5's realloc rule).
- **Slot↔grids provider flips** (`stroke.py:233-240`,
  `convert.py:1666-1671`) cannot alias an indexed cache entry with a soup
  node: id namespaces are disjoint (`external_draw.h:60-62`, kIdBase
  0x40000000) and `external_batches_get` prunes unseen ids per sync
  (`draw_external.cc:517`). The §5 presence-flip realloc condition is
  belt-and-braces, keep it.
- **Both fill sites zero-init** (`external_draw.cc:131`,
  `grid_draw_c_api.cc:66`) — the Stage-1 "soup with null indices" claim
  holds; mesh/dyntopo path untouched.
- **Hidden consumers are clean**: every consumer draws the shared cached
  batch whole — workbench (`workbench_engine.cc:374`), EEVEE per-material
  (`eevee_sync.cc:280-300`), overlay facing/fade/mode-transfer/outline/
  prepass-depth/sculpt-mask (all `external_batches_get` callers grepped) —
  and the wireframe overlay explicitly *skips* external draw
  (`overlay_wireframe.hh:191-194`, "v1 deferral"), so no lines-batch consumer
  exists to break. Mask@2 is a per-vertex dense sidecar
  (`grid_domain.h:119-120`) and every attr stream uploads with the same
  `verts_num` (`draw_external.cc:304-363`) — lockstep conversion is
  structural. The `verts_num % 3` contract has exactly two consumers: the
  BKE doc comment and `test_grid_stroke.cc:687` — both already in the plan's
  touch list.

### Could not verify (unchanged from the plan's own flags, plus one)

- EEVEE/Vulkan runtime behavior with indexed external batches (argued by
  construction; plan already requires a sign-off pass).
- RenderDoc "drawn vertices" counter semantics for indexed draws (plan
  already demotes it to secondary evidence).
- The refill-CPU ~6× claim and the ~2.9 ms full-pass baseline — no bench was
  run for this review; the write pattern argument holds up in code
  (destination writes become contiguous; gathers drop ~6×; nothing scatters),
  so this stays a Stage-3 measurement, not a design risk.
- Actual post-transform reuse efficiency of the dev-box iGPU (amendment 3).

### Go/no-go gates

- **Stage 1 gate**: fork+engine bump lands only with the smoke-test provider
  assertion + addon readback warning (amendment 2); RenderDoc still shows
  `glDrawArrays*`; ctest + fork build green.
- **Stage 2 gate**: updated `test_grid_stroke` coverage green in both
  `SC_GRIDS_INDEXED` modes; `peak_z` bit-identical headless.
- **Stage 3 gate**: interleaved (never batched) A/B shows `glDrawElements*`
  in the sculptcore arm and GPU frame within ~0.3 ms of native at 1M/L4, no
  stroke_ms regression; a win under ~0.5 ms triggers the explicit
  keep-on-memory-grounds decision (amendment 3), not a silent pass.
- **Sign-off**: EEVEE viewport sanity pass + GUI spot-checks per §9.
