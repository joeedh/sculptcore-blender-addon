# Plan 6: prepared non-accumulating commands

Reviewed by independent mesh/grid CLI reviewers on 2026-09-18; no blockers.
See `tests/plan6-nonaccum-{mesh,grid}-review.md`. This completes the
original-coordinate factory selection for bounded prepared draw/smooth programs.
Anchored grab, preview, dyntopo, general attributes, cavity and unbounded commands
remain separately gated; this slice does not weaken their guards.

Completed 2026-09-18: [verified gate](../tests/plan6-nonaccum-gate.json), 17 native
suites, 16 installed headed cases and 248 required prepared calls, matched DLL
provenance smoke. No C API or generated bindings changed.

## Implementation

1. Add a scratch-only prepared factory to each executor. Build the AccumLive
   manifest with a temporary Brush, then replace the command with a fresh
   AccumOrig instantiation when `nonAccum && accumulable && !relaxesBase`.
   Preserve neighbor dispatch. Do not invoke the live factory or publish extra
   defaults/declarations during capability queries or preflight. Do not append
   duplicate manifests when changing the execution template.
2. Use this factory consistently in supportsResolved, single prepared execution,
   and every prepared program stage. Remove only the blanket nonAccum rejection.
   Keep all other capability gates and complete scalar/program preflight.
3. Execute through the existing mesh/grid displacement, generation and capture
   paths. Non-accumulating DRAW uses the displacement-derived base; relaxation
   remains live and preserves its existing base adjustments. This additive policy
   does not impose a height cap. Preserve each executor's capture policy (mesh
   per-stage slots; grid first-touch snapshots) and union of evaluated radii. No changes
   to raw factory behavior, saved brush flags, authored values or stack storage.

## Acceptance

- Actual multi-leaf mesh and grids, prepared standalone DRAW and DRAW+BSMOOTH
  versus independent raw references. Compare accumulation on/off over repeated
  changing-pressure dabs so a mistakenly live template cannot pass by coincidence.
- Independently growing secondary radius, explicit empty/inherited strength,
  both mesh neighbor modes and grid immediate/deferred normals. Preserve exact
  undo/redo and working-state restoration, plus a fresh second stroke.
  Prove raw accumulation on/off differs for the fixture. Track the complete first
  leaf union and require later newly selected leaves to move. Inspect base/disp
  after DRAW, smooth and another DRAW, including smooth-only regions and second
  stroke first-contact reset. Record both mesh stage slots in newly reached leaves.
- Failed later-command preflight must not materialize displacement pages, alter
  generation stamps, capture undo, edit geometry or consume first-dab status.
  Check this before first contact and after a successful dab, then retry validly.
  Finish fresh replacement dispatch before taking manifest spans; propagate either
  factory failure and keep both dispatches isolated from the live Brush.
- Capability queries must not alter authored property presence, metadata or
  extra slots. Existing anchored/preview/dyntopo/cavity/attribute rejections stay.
- Rebuild native/Python through dispatcher; run the applicable 17-suite gate,
  stage the matching DLL, and run a headed non-accumulating draw/autosmooth matrix
  over mesh/grid and Python/batch. Instrument native calls and force prepared
  batch policy so fallback cannot establish acceptance.
