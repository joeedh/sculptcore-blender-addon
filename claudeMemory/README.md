# claudeMemory — SculptCore Blender Addon

Working notes Claude maintains for this repository. See the top-level
[CLAUDE.md](../CLAUDE.md) for the project overview and the three-repo topology.

## Structure

- `plans/` — implementation plans for addon work.
- `research/` — investigation notes (engine seams, Blender API behavior).
- `codebase/` — validated reference docs for this repo and the Blender fork's
  custom-mode API the addon depends on.
- `design/` — design documents.
- `scripts/` — headless harnesses and benchmarks (run with Blender's Python or
  a plain interpreter, depending on the script). Not indexed individually
  below; the plan or research note that introduced one names it.
  `stroke_sampler_parity.py` is the bpy-free Python-vs-C++ stroke-sampler
  parity gate for the plan below.

## Index

- [plans/program-grids-routing.md](plans/program-grids-routing.md)
  — routing brush programs (Clay's `[main, BSMOOTH]` autosmooth, and programs
  in general) onto the grids path and the C++ batch driver: BSMOOTH-on-grids
  via a zero-filled vclass binding (exact parity — multires sessions carry no
  boundary flags), `applyProgram` with store-level override rollback,
  region-restricted co_prev refresh, per-arm symbol-gated batch variants,
  kill switch `sculptcore_grids_programs`. Pressure-tested 2026-08-11 by
  three adversarial lenses (2 KILLs repaired: unsatisfiable vclass oracle,
  batch-gate staging contradiction; §9 has the log). Not yet implemented.
- [plans/indexed-grid-draws.md](plans/indexed-grid-draws.md)
  — indexed draw buffers for multires grids in the external-draw path: shared
  lattice-row vertex streams + a per-node index buffer generated once at
  partition build, ABI v2→3 (null indices = soup fallback and rollback lever),
  fork-side IBO in the node cache. Pressure-tested 2026-08-10: **BUILD WITH
  AMENDMENTS** — `GPU_indexbuf_build_from_memory` takes the *primitive* count
  (passing indices_num reads 3× out of bounds), and the smoke test must assert
  `bl_draw_provider != "0"` in Stage 1 (a version-skewed engine/fork pair
  currently ships silently drawing the base cage). Not yet implemented.
- [plans/cpp-stroke-driver-adoption.md](plans/cpp-stroke-driver-adoption.md)
  — replacing the addon's Python stroke sampler (`StrokeSpacer` + `stroke_math`
  + per-dab raycasting) with the engine's C++ `BrushStrokeDriver`: phased by
  stroke method, the Blender→driver view-snapshot conversion (row-vector
  matrices, y-flip, ortho), what stays host-side, and the castRay fix the same
  engine commit brings. **Revised after the grids-native wiring**: on multires
  sessions the driver must run as a pure spacer with host-side re-raycast (its
  own raycast would sample the deliberately stale-bounded mesh tree), and the
  measured sampler cost (~0.05 ms/dab) re-scopes it as a correctness /
  maintenance win rather than a perf lever. **Phase 1 implemented 2026-08-06**
  behind the (default-off) `sculptcore_cpp_stroke_driver` scene bool — see the
  implementation notes at the end of the plan: the driver runs as a pure spacer
  on *every* session (not just grids), the parity harness found and got fixed a
  NaN in the engine's `crToBezier`, and the in-viewport A/B checklist is still
  the sign-off gate.
- [design/cpp-dab-loop.md](design/cpp-dab-loop.md)
  — **Pressure-tested and revised 2026-08-10; not yet implemented.** Moving
  the per-dab loop into the engine (`StrokeRunner` + flat `StrokeRun_*`
  c-api), superseding the adoption plan's "sampler only" scope. The
  four-lens adversarial pass reshaped it: the v1 "0.85 ms/dab removable"
  headline was a stale pre-VBO-fix quotient (honest slice 0.2–0.33 ms/dab,
  16–28 ms/stroke; ratio 2.7× → ~2.0–2.3×, floor ~1.8×), the ray section was rewritten to a
  verbatim `view3d_utils` port (the shipped ortho ray *is* far-pushed; the
  view matrix must ride the payload), two mid-stroke domain-fold UAFs got
  generation guards, cancel/error contracts were added (never `_end` on
  cancel; never mid-stroke Python fallback), the toggle is a NEW property
  (old one deleted, not repurposed), and a cheaper variant B (numpy math +
  batched capi calls, ~100 lines, 70–85% of the win) is recommended first.
  §12 has the full finding table.
- [design/off-thread-stroke.md](design/off-thread-stroke.md)
  — **S0 shipped 2026-08-16 and closed the problem; §4 onward SHELVED**
  (declined, kept as the costed option — reviving it needs latency numbers,
  not this document's sampling argument). Was about moving the
  stroke consumer off the main thread so the main thread only collects
  pointer events, plus a viewport preview of the pending stroke path. Both
  headline answers invert the premise: events **cannot** be collected off
  the main thread (macOS forbids it; Win32 message queues are per-thread —
  `GHOST_SystemWin32.cc:440`), and the design needs **no fork change**,
  because on a pen under Windows the samples are already arriving intact
  (Wintab queues 500 packets, `GHOST_Wintab.cc:90`; Blender *demotes* backlog
  moves to `INBETWEEN_MOUSEMOVE` rather than discarding them,
  `wm_event_system.cc:5868`) and `stroke.py`'s `modal()` dropped every one of
  them — the ~15-line S0 fix has since landed (spaced-dab strokes only;
  preview and grab re-base per input so a backlog sample there is overwritten
  work). With fidelity now bought by S0, threading would buy only
  responsiveness — never throughput (the dab is already node-parallel) — which
  is why it was shelved. Gated on [design/cpp-dab-loop.md](design/cpp-dab-loop.md)
  Variant A: a Python worker would contend for the GIL with the very modal
  handler it is trying to keep fast. Bulk of the work is the extdraw
  double-buffer + generation counter (§6.1); dyntopo and grab excluded in v1.
- [research/non-operator-wall-attribution.md](research/non-operator-wall-attribution.md)
  — **P-b resolved 2026-08-10: the ~28.7 ms/stroke of sc wall outside the
  stroke operator is NOT a lever.** A span-timeline instrument
  (`scripts/bench_multires_sc.py --wall-trace` + `scripts/analyze_walltrace.mjs`)
  shows steady-state non-op wall is the single vsync-blocked present per
  stroke (~15–18 ms) that native pays identically, plus a one-time
  strokes-1–2 warm-up transient (~150 ms) and ~1 ms/stroke of draw. WM
  dispatch between modal calls is ~0; depsgraph eval+handlers ~0.25 ms.
  Also corrects two bench misreadings: `cycle_ms` spans push → the
  *previous* content's present (events are handled the pass after the
  push), and `sculpt_frames` is cumulative (the sculpt phase presents one
  frame per stroke). Dab-loop implementation unblocked.
- [plans/vertex-group-weights-attribute.md](plans/vertex-group-weights-attribute.md)
  — giving the engine ownership of Blender vertex-group weights as a sparse
  `AttrType::WEIGHTS` column (32-bit index into an interned, refcounted,
  thread-safe pool) with a `AttrMerge::CUSTOM` interpolator, plus the fork's
  bulk CSR accessor and the `convert.py` bridge. Fixes the `clear_geometry()`
  weight loss on the dyntopo flush path. **Landed** — every phase is marked up
  in the plan, with the two open follow-ups recorded under *Ordering and gates*.
- [plans/blender-attribute-coverage-tasklist.md](plans/blender-attribute-coverage-tasklist.md)
  — the backlog of Blender mesh data the bridge still drops on a topology
  rebuild: everything `clear_geometry()` destroys beyond CustomData (animation
  data, the six active/default layer designations), the encoded `custom_normal`
  gap, the unbridged `EDGE` domain, loose edges, selection/hide state, shape
  keys, and the types with no engine equivalent — each with what it would take
  and why it is ordered where it is. Fresh-context audited 2026-07-29, then
  **adversarially pressure-tested 2026-07-30**, which broke considerably more
  than the audit did: the two queued engine prerequisites (**E3**, **E4**) are
  withdrawn, **1.6** was redesigned to need no new engine type or handler,
  **1.9** and **1.2** are re-filed out of addon-only work, **1.4** is gated
  behind a release-build heap overflow, and **3.4** is un-done. The pressure
  test's own **E7** finding was then checked and withdrawn as well — see
  [research/collapse-blend-gate.md](research/collapse-blend-gate.md).
  Corrections from all three passes are recorded at the end of the page so they
  do not get re-proposed.
- [research/collapse-blend-gate.md](research/collapse-blend-gate.md)
  — why `collapseEdge`'s `blend > 0.0f` gate is **not** a bug: the caller
  inventory (one production caller, passing `mid` and `blend=0.5f`), the
  latent API footgun that is actually there, and the method lesson — a finding
  that turns on a defaulted parameter needs the call sites enumerated before it
  is believed. Kills the tasklist's **E7** and restores **1.4**'s original
  merge-policy claim.
- [plans/multires-grids-native-brush-path.md](plans/multires-grids-native-brush-path.md)
  — **engine phases G1–G4 executed 2026-08-04** (see the results doc below);
  Blender wiring still open. The direct grids editing path that closes the
  residual ~6× multires gap: sculpt on the dense level-vert position buffer
  (`LevelPos::pos`) with lattice-CSR neighbors instead of a materialized
  `mesh::Mesh` — chosen over a Blender-style replicated CCG layout because the
  store's dense↔grid machinery already exists and seam replicas vanish by
  construction. Covers `GridLevelDomain`/`GridTree`/`GridStrokeLog`, the
  sbrushc TYPES generalization that makes the generated kernels domain-generic,
  GPU dispatch reuse (flat buffers + one shared CSR, orchestrator hoisted out
  of `debug/`), touched-set writeback, the ride-along mirror that keeps draw
  correct until an extdraw-from-grids provider exists, and five phases with
  parity/undo/perf gates. Blender wiring is explicitly out of scope.
- [research/grids-native-brush-path-results.md](research/grids-native-brush-path-results.md)
  — the G1–G4 execution record: what landed per phase, every gate result
  (draw/clay/pinch/sharp A/B bit-exact, undo bit-exact, CPU-vs-GPU grids
  worst-diff 0 on both dispatchers), the bench table (per-dab core 0.082 ms
  vs the 0.35 gate; writeback 2.3 ms; undo 19.9 MB), the GPU size-crossover
  measurement (dispatch crosses ~4 M, readback forces per-frame batching),
  and the deviations (no mesh-orchestrator hoist; store-block capture moved
  to stroke end).
- [design/grids-native-addon-seams.md](design/grids-native-addon-seams.md)
  — G5: the addon-facing seams, reviewed against `stroke.py`/`session.py`/
  `undo.py` — the `GridStroke_*` c-api mapping, extdraw-from-grids with
  `node_id` = stable leaf id (interim ride-along mirror first), grid-log undo
  steps replacing per-stroke store blobs (blob demoted to level switches),
  and the four-case lazy-mirror rule that eventually kills the 15.6 s enter.
- [research/multires-stroke-performance.md](research/multires-stroke-performance.md)
  — why a sculptcore multires stroke cost ~87 s where native costs ~0.86 s on a
  1 M-vert level-4 cage, and how it got to ~5.0 s (~17×): the headed A/B rig and
  its ±150 ms noise floor, the full attribution tree down to engine phase timers,
  the root cause of the residual ~6× (a materialized `mesh::Mesh` + BVH +
  per-element undo capture vs native's in-place CCG grids), what was fixed, the
  two regressions only the full ctest sweep caught, and the ranked remainder — a
  grids-native brush path is the only item that closes the gap.
- [research/redraw-path-attribution.md](research/redraw-path-attribution.md)
  — what the ~14 ms/stroke "redraw machinery" slice actually is (~96 % engine
  CPU: deferred normals + draw-node soup refill), and the frame-consumption
  gate on `_mid_redraw` that cut `stroke_ms` −15 % by refusing refreshes no
  frame will ever present.
- [research/redraw-gpu-pipeline-ab.md](research/redraw-gpu-pipeline-ab.md)
  — RenderDoc A/B of the full redraw pipeline, native vs SculptCore (1M/L4):
  the +50 % GPU frame split into non-indexed grid soup (+1.5 ms, engine item)
  and the `area.tag_redraw()` → brush-asset-shelf mip churn (~1.2 ms GPU +
  region-draw CPU; fixed to `region.tag_redraw()`), the interleaved-replay
  methodology, and the per-dab cycle numbers before/after.
- [research/multires-autotune.md](research/multires-autotune.md)
  — deriving a multires level's three acceleration granularities from its size
  instead of fixed constants (`engine/source/subdiv/multires_tuning.{h,cc}`,
  reached by the `0` the addon already passed). The headless sweep rig, the
  headed rig that exists because **the draw-node trade is invisible headless**
  (refill cost is monotone in node size; the host's per-node-per-pass cost is
  not measurable there), and the measured knees: leaf size tracks the cage-face
  block and not the vert count (and is a wash either way), while quartering the
  draw-node count halves viewport cost — 2.2 → 1.0 ms/frame at 1 M verts.
- [research/grid-correspondence.md](research/grid-correspondence.md)
  — how the engine's multires grids line up with Blender's `CD_MDISPS`: the
  exact lattice transpose (an involution, so one table serves both directions),
  the fork's `Object.multires_grid_vert_indices` primitive that supplies grid
  sample → subdivided vertex, why the exchange is in absolute positions, and the
  KD-tree nearest-neighbour pairing this replaced — the cause of the "grid
  borders snap to zero at level ≥ 3" bug.
- [plans/multires-parametric-frame.md](plans/multires-parametric-frame.md)
  — the implementation plan for the design below: four phases, all in the engine
  submodule (`source/subdiv/multires.cc`), each independently shippable.
  **Phase 1 landed 2026-07-30** (frame computation + gates, no behaviour
  change); its outcome section carries the A/B that reproduces the defect — the
  provider tangent *reverses* (dot −0.999962) on a nudged cube cage where the
  parametric one holds at 0.999970. Records what re-validation against engine
  `7979406` corrected in the design's scope — a third frame-population site in
  `materialize()`, the canonical-owning-grid table that already exists as
  `levelVertGridCoordsOut`, a whole temp level mesh that disappears from
  `ensureChain`, and the capture-refusal that closes the mixed-frame-space
  window the design's suggested order left open.
- [design/multires-parametric-frame.md](design/multires-parametric-frame.md)
  — **Phase 1 implemented; the production path is unchanged.** The live
  multires design: derive the tangent frame from the grid's own `(u,v)` lattice
  instead of the curvature cross field, which removes the discrete detail-flip
  outright (a symmetry image, measured at a full 180° reversal) because a
  lattice makes no choice among symmetric alternatives. Covers why the frame
  need only be deterministic, ambiguity-free and rotating-with-the-surface (not
  geometrically meaningful), the canonical-owning-grid rule that keeps border
  replicas bit-identical without averaging tangents, what it deliberately leaves
  alone
  (storage, cage, undo, the seam, the file format — the engine store is
  session-scoped, so there is no compatibility question), and what it does *not*
  fix (the lever arm survives; conditioning moves to parametrization skew).
  ~150–250 lines in one file. The frame-stability gate it asks for now exists
  and is what measured the reversal.
- [design/multires-object-space-cascade.md](design/multires-object-space-cascade.md)
  — **SUPERSEDED, rejected 2026-07-30, never implemented.** Postmortem of the
  above's predecessor: object-space storage plus an automatic downward cascade
  into the coarse levels and the cage. Killed by adversarial pressure testing on
  four independent counts — the delta rotation is wrong by up to the full
  rotation angle and its correct form needs a frame anyway; greedy per-level
  least squares is a deconvolution that *relocates* displacement and rings the
  cage; the meshlog undo path structurally cannot carry a cage stroke; and the
  prescribed bake reorder cannot be built on Blender's reshape API. Keeps the
  diagnosis (which was right and is carried forward), a **do not re-propose**
  list, and the results the test settled positively — the unmasked cascade is
  provably path-independent, `cond(AᵀA) = 8`, and influence decays 0.4465 per
  coarse vertex.
- [design/blender-brush-textures.md](design/blender-brush-textures.md)
  — **design, not implemented.** How Blender brush textures reach the engine:
  the transport already exists (bake → `setTexture` → four kernels), what is
  missing is the *mapping*. Every non-3D `map_mode` Blender offers is an affine
  transform, and `ctx.renderMatrix` — a `mat4` with exactly one consumer — can
  carry all of it, so five of six modes are addon-only work (per-dab matrix
  composition in Python; per-mode recipes included). Engine work reduces to
  folding the texture into the `strength()` intrinsic so it reaches more than
  four kernels, and a wrap/clip mode for TILED and STENCIL. True 3D mapping is
  **deferred** (2026-08-02): not a volume bake — the interim escape hatch is a
  host-sampler callback, and the canonical answer for DCC integration is host
  procedural textures implemented in the brush DSL, so they lower to CPU and GPU
  alike (the `texture` block already prototypes this) — ending in a **runtime
  procedural-texture compiler** emitting WGSL/SPIR-V, with the CPU side JITed or
  interpreting SPIR-V, which would make hand-maintained CPU/GPU parity
  unnecessary for what it covers. Records three live defects — `apply_render_matrix` omits
  `matrix_world`, `texture_slot.angle` is bound to Ctrl-F but never read, and
  the matrix is pushed per stroke where three modes need it per dab — plus the
  Blender-side quirks parity has to mirror (AREA's inverted bias sign, sculpt
  reading `mtex` not `mask_mtex`, `PaintRuntime` being invisible to RNA).
- [plans/blender-texture-system-port.md](plans/blender-texture-system-port.md)
  — **rev 2 (2026-08-14) after an adversarial pressure test; Parts 0-3 now
  implemented.** Porting Blender's legacy procedural textures to `.stex`. Rev 1 did
  not survive review and rev 2 records why, so the dead ends stay dead: the
  oracle it specified (`Texture.evaluate(p)[0]`) returns **constant 0.0** for 9
  of 10 types — intensity is `[3]`, which `_bake_procedural` already knew — and
  the brush's real path (`RE_texture_evaluate`) overwrites `tin` with luminance
  for RGB types; `TEX_NOISE` is a thread-RNG draw that ignores its coordinate
  entirely, so it cannot be ported *or* parity-tested; the new transcendental
  intrinsics need **four** edit sites, not two, because the texture JIT is
  `-nostdlib` with five hand-bound libm symbols; and the WGSL twins (the
  largest line item) are unreachable — `gpu_brush_c_api.cc:77` refuses any
  brush carrying a texture program, and `gpuAvailable` never parses the string.
  Bit-exactness is **rejected** as the target (§5.1) and the `NTREE_TEXTURE`
  compiler is **cut** (§5.2 — node trees already bake correctly through
  Blender's own evaluator for all 2D map modes; the gap is 3D-only behind a
  toggle absent from the Texture properties UI), leaving two ~20-line fixes.
  **Landed:** the `clouds.stex` placement-order and unconditional-clamp fixes,
  the map-mode defects from `design/blender-brush-textures.md` §6, the
  `evalTextureAt` parity harness (`tools/verify_texture_parity.py`, now a third
  step in `smoke-test-packages.yml`), the end-to-end stroke check
  (`scripts/test_texture_stroke.py`), and Magic/Blend/Wood/Marble/Stucci — six
  of ten types now route to a `.stex` instead of a 2D bake. §2.1's two "as landed" blocks are the ones to read
  before adding a seventh: what a `mode='point'` case can and cannot grade, why
  `noise_scale` does not scale Wood/Marble/Stucci's pattern, why `tex_saw`
  needs an operation-for-operation transcription, and why the worst-case
  statistic trims outliers. **Deferred:** §2.2's Musgrave/Voronoi/
  DistortedNoise and §2.3's WGSL twins, both against stated demand only.
  §6 lists what the pressure test confirmed (all 10 types and
  MUSGRAVE survive; `NTREE_TEXTURE` has 34 node types and is not deprecated;
  `noise_c.cc` has no `double`, so float32 is not a blocker).
- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
  — how the engine's GPU brush stack could drive strokes under the addon: the
  existing marshal/dispatch seams, engine-owned wgpu vs. compute on Blender's
  device, and what per-dab work can and cannot be deferred to stroke end.
- [research/sculpt-stroke-world-model.md](research/sculpt-stroke-world-model.md)
  — **speculative; nothing proposed for implementation.** Prior art on AI world
  models for DCC apps (Moonlake's Blender computer-use agent; the
  structured-output branch — HY-World 2.0 / World Tracing / WorldMesh — versus
  pixel-space Genie 3) and the gap: nothing published works at *stroke*
  granularity. Then what a corpus for one would be — the local-patch,
  radius-normalized displacement-field formulation, the per-vertex channels a
  positions-only model gets wrong (mask, relational face sets), the dab action
  space including falloff-as-a-curve, and the `loadProps`/pressure-LUT capture
  trap that would poison labels invisibly (`stroke.py:887-890`). Records that the
  meshlog is **stroke**-granular (`undo.py:7-9`) and so is *not* a corpus for the
  differentiable-operator goal without new per-dab capture at `apply_dab`
  (`stroke.py:322`); that dyntopo's changing vertex set structurally breaks the
  formulation; and that rollout, not per-dab accuracy, is the metric. Ends with a
  five-point minimum viable experiment whose only success criterion is inverting
  a known stroke, and a **do not re-propose** list.
- [research/litestl-sbo-audit.md](research/litestl-sbo-audit.md)
  — small-buffer-optimization audit of `util::Vector`/`Map`/`Set`/`OrderedSet`
  across the multires and spatial-tree hot paths. The headline is not the
  default sizes: `Vector<T, N>`'s inline buffer is **off by one**
  (`ensure_size`'s guard is `<` where it should be `<=`, verified empirically),
  so every tuned size holds `N-1` and every exact fit — a quad's 4 corners, a
  face's 4 grids — spills. Beyond that, the real cost is fresh containers per
  element rather than small ones: a heap allocation per coarse vertex in
  `Refiner::refine` (`subdiv.cc:270`), three unreserved vectors per dirty leaf
  per frame in `update_node_normals`, `clear_and_contract()` on ~20 KB tri lists
  that are refilled immediately, and per-dab `filterNodes` buffers at SBO 4.
  Tables of measured `sizeof`/inline capacities, eleven ranked findings with
  file:line, the places already sized correctly (so they are not "fixed" into
  regressions), and one adjacent quadratic scan in the grid undo log.
  **All of it is applied** (§7), and §7.1 walks back the audit's own claim that
  F8 was the biggest multires-enter win: an interleaved A/B puts it at ~1.6%,
  inside the noise — plus the batching trap that first made it look like 1.9x.
- [research/tbb-vs-litestl-parallel-for.md](research/tbb-vs-litestl-parallel-for.md)
  — litestl's `task::parallel_for` (static band equipartition over its own
  work-stealing pool) versus Blender's (a façade over `tbb::parallel_for` with
  recursive splitting, `TaskSizeHints` and lazy threading), then an actual A/B: a
  temporary `LITESTL_WITH_TBB` backend, gated by 125/125 native ctest and
  measured 3v3 on the multires benchmark. **TBB lost** — ~4% on sculpt phase, ~5%
  per stroke, a dead heat on enter-mode, and ~20× the run-to-run variance. The
  scaffolding was reverted; the note records the exact patch, the caveats (shared
  Blender arena, nesting sites left hand-flattened), and the one untested case
  where TBB should still win.
