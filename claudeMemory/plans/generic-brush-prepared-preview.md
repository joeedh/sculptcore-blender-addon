# Plan 6: prepared preview rollback

Status: completed on 2026-09-18. [Verified gate](../tests/plan6-preview-gate.json).
The user waived further adversarial reviews for this task list.

## Contract

Anchored and Drag Dot gestures keep one provisional group of primary/mirror dabs.
Replacing that group must restore its geometry before executing the replacement.
Only the committed group contributes to stroke history and first-contact caches.
Invalid settings must leave the previous valid preview intact.

Multires previews continue using the materialized mesh route; the native grid
executor has no preview transaction. Dyntopo remains outside preview admission.

## Implementation

1. Let the mesh log capture explicit selected nodes in an existing preview.
   Prepared execution adds its complete evaluated command-region union after
   preflight and before mutation. This covers independent later-command radii
   and all-leaf anchored/unbounded regions even when the host's initial radius
   underestimated them. Preserve deduplication across symmetry images.
2. Admit prepared preview only for a dedicated preview stroke beginning before
   any accepted ordinary dab. Do not silently mix a partially completed ordinary
   stroke with a preview-only cache lifetime.
3. On rollback of a prepared preview, invalidate displacement/dab generation
   stamps for captured vertices and leaf base-stamp shortcuts. Reset first-contact
   caches, previous-coordinate snapshots, stroke-path history and queued UV
   reprojection. A replacement preview recomputes those from restored geometry.
   Keep step-wide undo capture: it owns the stroke's original state.
4. Use checked prepared preflight in the host before rolling back the previous
   group. Preserve the raw route for capabilities still outside this admission.
   The snapshot bracket stays shared across the primary and mirrors.
5. Test bounded, nonaccumulating, anchored, unbounded, MASK, BSMOOTH, cavity and
   ENHANCE commands with repeated growth/shrink and replacement, including a
   larger second command and mirrored regions. Compare committed geometry with
   a fresh execution of only the final group. Check cancellation, exact undo/redo,
   late rejection, next-stroke isolation and the legacy preview suite.
6. Run native regression and installed background/headed gesture tests, then
   record hashes and evidence before marking this deliverable complete.

## Source observations

The current mesh-log snapshot skips NOCOPY values, restores captured NOCOPY cells
as zero, and does not restore newly appended columns. Prepared rollback must
therefore invalidate transient brush stamps explicitly. Restoring positions alone
leaves displacement bases and leaf shortcuts stale. The existing host validates
raw program overrides before rollback, which rejects the new typed command
overrides even when prepared execution supports them.

The first native matrix also exposed reads/writes of unmaterialized frozen
connectivity columns in preview row snapshots. Preview data rows now omit TOPO
columns: topology chunks already own connectivity rollback. Ordinary topology
chunk rows retain their full layouts. The legacy topology-changing preview tests
remain part of the acceptance gate for this shared mesh-log correction.

The headed matrix exposed an executor created before the lazy multires slot.
Materialization now binds its tree, and mesh-path stroke startup materializes
without depending on a draw provider. Grid and cage-only paths stay lazy.

## Acceptance evidence

- All 20 native suites pass, including the legacy topology-preview tests.
  Prepared replacement groups match fresh final groups across seven kernels,
  both neighbor modes, nonaccumulation, programs, symmetry and varying radii.
  Cancellation, invalid later commands and exact undo/redo pass.
- All 64 installed host cases pass in both background and headed Blender.
  These cover DRAW, GRAB, KELVINLET and ENHANCE on mesh/materialized multires,
  independent larger smooth commands, cavity, replacement and cancellation.
- Eight real headed gestures pass: Anchored/Drag Dot on mesh/multires, commit
  and cancel, with mirror execution and Blender undo/redo assertions.
- Bindings, TypeScript checking, package smoke and staged Python source equality
  pass. The gate records the exact DLL, executable and source hashes.

Dyntopo, other guarded command capabilities and generic consumer adoption remain
Plan 6 work. This gate does not enable the generic system by default.
