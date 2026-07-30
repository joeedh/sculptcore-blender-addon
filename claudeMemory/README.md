# claudeMemory — SculptCore Blender Addon

Working notes Claude maintains for this repository. See the top-level
[CLAUDE.md](../CLAUDE.md) for the project overview and the three-repo topology.

## Structure

- `plans/` — implementation plans for addon work.
- `research/` — investigation notes (engine seams, Blender API behavior).
- `codebase/` — validated reference docs for this repo and the Blender fork's
  custom-mode API the addon depends on.
- `design/` — design documents.

## Index

- [plans/cpp-stroke-driver-adoption.md](plans/cpp-stroke-driver-adoption.md)
  — replacing the addon's Python stroke sampler (`StrokeSpacer` + `stroke_math`
  + per-dab raycasting) with the engine's C++ `BrushStrokeDriver`: phased by
  stroke method, the Blender→driver view-snapshot conversion (row-vector
  matrices, y-flip, ortho), what stays host-side, and the castRay fix the same
  engine commit brings.
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
  withdrawn, **E7** turned out to be a live bug (`collapseEdge` merges no vertex
  attribute at all on the default path) and now leads the order, **1.6** was
  redesigned to need no new engine type or handler, **1.9** and **1.2** are
  re-filed out of addon-only work, **1.4** is gated behind a release-build heap
  overflow, and **3.4** is un-done. Corrections from both passes are recorded at
  the end of the page so they do not get re-proposed.
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
- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
  — how the engine's GPU brush stack could drive strokes under the addon: the
  existing marshal/dispatch seams, engine-owned wgpu vs. compute on Blender's
  device, and what per-dab work can and cannot be deferred to stroke end.
