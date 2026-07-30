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
  and why it is ordered where it is. Fresh-context audited 2026-07-29; the two
  engine prerequisites it uncovered (**E3** corner-domain merge dispatch, **E4**
  merge-policy binding for host-created layers) are queued, and the corrections
  are recorded at the end of the page so they do not get re-proposed.
- [research/grid-correspondence.md](research/grid-correspondence.md)
  — how the engine's multires grids line up with Blender's `CD_MDISPS`: the
  exact lattice transpose (an involution, so one table serves both directions),
  the fork's `Object.multires_grid_vert_indices` primitive that supplies grid
  sample → subdivided vertex, why the exchange is in absolute positions, and the
  KD-tree nearest-neighbour pairing this replaced — the cause of the "grid
  borders snap to zero at level ≥ 3" bug.
- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
  — how the engine's GPU brush stack could drive strokes under the addon: the
  existing marshal/dispatch seams, engine-owned wgpu vs. compute on Blender's
  device, and what per-dab work can and cannot be deferred to stroke end.
