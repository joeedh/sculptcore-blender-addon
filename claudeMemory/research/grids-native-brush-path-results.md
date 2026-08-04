# Grids-native brush path: engine-phase results (G1–G4)

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
