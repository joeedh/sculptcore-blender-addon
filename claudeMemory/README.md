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
- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
  — how the engine's GPU brush stack could drive strokes under the addon: the
  existing marshal/dispatch seams, engine-owned wgpu vs. compute on Blender's
  device, and what per-dab work can and cannot be deferred to stroke end.
