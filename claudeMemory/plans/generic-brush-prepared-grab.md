# Plan 6: prepared anchored grab

Status: completed 2026-09-18; [verified gate](../tests/plan6-grab-gate.json).
Further adversarial reviews were waived by the user for the remaining task list.

## Contract and implementation

1. Build isolated AccumOrigGrab commands when the stroke is anchored and the
   kernel declares grab capability. Preserve AccumLive relaxation commands and
   existing nonaccumulating selection for other commands.
2. Select all nonempty leaves for a positive-radius anchored stage. This is a
   conservative region shared with later commands: deformed live bounds cannot
   discard original-position support, growing radii or another symmetry image.
   It costs a whole-domain traversal and first-use base/undo storage. Keep this
   cost explicit; the generic consumer remains opt-in pending the full Plan 6
   gate. A future base-coordinate spatial index can reduce this cost without
   changing support. Do not reuse the raw grid path's single pinned footprint.
3. Advance the logical-dab stamp only after successful preparation; mirrors
   preserve it. Standalone and program entry points default to a primary image.
   Add explicit image C APIs for the addon's grab path, preserving existing ABI.
   Prepared batches pass their primary/mirror identity to the executor.
4. Use displacement-derived base coordinates for anchored cavity contact.
   Reject nonfinite grab frames before publication, including validation-only
   calls. Preserve command ordering and working-state restoration.
5. Preserve native kernel semantics: zero falloff/strength performs no write;
   vertices leaving support retain their earlier displacement. Multiple grab
   stages and symmetry images sum from-base deltas after the first writer has
   rebased a vertex in that logical dab. Relaxation still updates the base.
6. Keep preview, dyntopo and unrelated attribute capabilities guarded.

## Acceptance gate

- Independent GRAB displacement oracle across mesh live/CSR and native grids,
  multiple leaves, varying radius/strength, far drags, misses, zero radius,
  radius growth and shrink, overlapping symmetry and independently configured
  program stages. Verify actual movement outside the first footprint.
- Nonfinite frame and late-command errors preserve geometry, authored values,
  stamp, attributes and undo; exact undo/redo and a second stroke.
- Native regression suites, generated bindings/typecheck, installed background
  and headed Blender direct/batch/program comparisons and package provenance.
- Record actual evidence before checking off this slice or claiming completion.

## Recorded results

All 17 native suites pass. The independent GRAB oracle covers mesh live/CSR and
native grids, both accumulation settings, single/two-command programs, varying
radius/strength, pressure ADD radius, far drags, overlapping mirrors, misses,
zero radius, growth/shrink, rejected frames/late overrides, exact undo/redo and
fresh base coordinates in a second stroke.

Installed background and headed Blender each pass 24 GRAB cases and 24 anchored
Kelvinlet cases. These use actual addon stroke lifecycle and direct image/program
calls, compare required prepared batches, and cover native grids without forcing
a mesh slot to materialize. Kelvinlet additionally matches an independent
double-precision elasticity formula across every case. These are headed API
checks; generic modal consumer adoption remains a later Plan 6 deliverable.

Checked Python/TypeScript declarations, TypeScript checking and package provenance
smoke pass. No shader source changed in this slice. The two new image C APIs are
additive and listed in the native/WASM export inventory. Their omitted initial
exports were caught by the installed test and corrected before the passing gate.

The full-domain selection cost remains explicit. Preview and dyntopo stay guarded;
the full Plan 6 acceptance gate and Plans 7/8 are still open.
