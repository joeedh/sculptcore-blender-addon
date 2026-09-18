# Plan 6C: prepared boundary-aware smooth

Reviewed by independent mesh-hook and grid/acceptance CLI reviews on 2026-09-18.
Both found no blockers; evidence is in `tests/plan6-bsmooth-{mesh,grid}-review.md`.
Completed 2026-09-18: [verified gate](../tests/plan6-bsmooth-gate.json), 17 native
suites, eight headed autosmooth cases/124 required prepared calls, eight legacy
modal cases and matched package smoke. Remaining Plan 6 tasks stay open.
This bounded engine slice enables the actual BSMOOTH command used by SculptCore,
including main-plus-smooth programs with independently evaluated radius/stacks.
It does not claim general attribute, cavity, unbounded, dyntopo or host-stage support.

## Implementation

1. Add explicit hook metadata for a prepared-safe, scalar-independent pre-freeze
   phase and for the equivalent phase being unnecessary on grids. Only the
   boundary-class refresh is currently classified this way. Do not infer safety
   from callback pointer identity or permit ENHANCE/FEATURE_ALIGN/POLYGROUP hooks.
   Existing raw hook behavior is unchanged.
2. Replace the blanket prepared attribute rejection with a narrow metadata check:
   read-only vertex INT bound to `.boundary.vert.class`, with no retargeting/use
   category or attribute overrides. Reject all other attribute bindings and every
   write. Mesh binding continues through existing exec; grids require the existing
   DefaultColumn routing and its documented zero/interior semantics. Keep every
   other capability guard, including attribute mirrors and active layer restrictions.
3. Mesh prepared single/program entrypoints validate every command/scalar/radius
   before any hook/materialization/mutation. For an accepted nonempty region,
   run the classified pre-freeze hook before deciding topology freeze/thaw, and
   before any program geometry stage. Calling the boundary refresh on each
   accepted region is safe: it internally returns immediately unless boundaryDirty.
   This also handles an earlier empty dab without incorrectly skipping the first
   actual boundary refresh. Run at most once per identical invariant hook within
   that program; do not broaden raw runProgramHooks or deduplicate command-dependent
   hooks. Preserve each prepared stage's working scalar scope and common node union.
4. Grid prepared execution binds the existing zero read-only column through
   execStage, after complete preflight. It runs no mesh-only hook. No new authored
   grid channels or attribute mirrors are created for the read-only boundary class.

## Gate

- Multi-leaf mesh: compare prepared BSMOOTH and DRAW+BSMOOTH against independently
  evaluated wide-region raw references, including marked sharp/seam boundaries,
  live-disk and CSR neighbor modes, larger dynamic secondary radius, explicit
  empty vs inherited strength, varying inputs and projection values.
- Exact undo/redo and authored/working scalar restoration. Verify read-only
  boundary attributes are not overwritten by prepared stage values.
  Programs restore working values; standalone calls retain their existing publish
  contract. Exact undo means geometry/store data; derived boundary inventory is
  checked for correct subsequent smoothing, not promised bytewise restoration.
- Dirty boundary state with initially frozen topology and an earlier zero/miss
  dab: first actual smooth refresh must happen safely before freeze; no dropped
  topology pages are accessed. Failed later-command preflight leaves boundary
  dirty state, attribute inventory, geometry, logs and first-dab state unchanged.
  The missed-first-dab reference explicitly refreshes its boundary classes: the
  old raw first-dab hook alone is not an oracle for this corrected behavior.
- Multi-leaf grids: prepared BSMOOTH/program vs existing raw BSMOOTH references,
  immediate/deferred normals, independent stacks/radii, undo/redo and no added
  authored channels/mirrors. Zero class is intentionally the existing grid policy,
  not a claim of cage-boundary preservation parity with mesh BSMOOTH.
- Keep unsupported attribute/hook tests rejecting, including ENHANCE,
  FEATURE_ALIGN, POLYGROUP, wrong-type/domain/written attributes and overrides.
- Build native and Python via dispatcher, regenerate declarations if affected,
  run applicable native suites and exact-DLL Python/batch tests, stage package,
  then run the existing headed modal matrix plus actual autosmooth coverage.
  Record this bounded gate; remaining Plan 6 capabilities/consumers stay open.
