# Plan 6: prepared attribute-backed brushes

Status: mesh/materialized attribute gate completed 2026-09-18; cage-only smoothing is a separate remaining host path. The user waived remaining adversarial reviews.

## Implementation contract

- Extend the compiler's preservation proof to writes to declared vertex/face
  attributes only when the same attribute appears in that domain's save set.
  Keep rejection of shared uniform/context writes, neighbor writes, unknown calls,
  mixed vertex/face execution, and uncertified host/reduce stages.
- Preflight the complete program's attribute domains, types and explicit targets
  without creating columns. Reject invalid indices, duplicate selections,
  incompatible named columns, and writes to topology/non-copyable storage before
  any geometry, topology or attribute mutation. Explicit selections never fall
  back to another layer. Keep raw execution's compatibility behavior unchanged.
- Bind each command's selected layers and capture those actual layers. Preserve
  initialized absent-column defaults and the existing column-presence undo policy.
  Materialized multires still uses its established cage/store writeback paths.
- Run FEATURE_ALIGN preparation per stage after applying that stage's settings.
  Run POLYGROUP's boundary-dirty hook after its stage. ENHANCE retains its dedicated
  command-owned cache. Only invariant pre-freeze hooks may deduplicate.
- Test color/smoothing, groups, sculpt layers and feature alignment on multiple
  leaves: larger later radius, independent selected layers, rejection without
  allocation, prepared/raw parity, preview/cancel, dyntopo and exact undo/redo.
  Native grid color/group storage remains outside its existing domain contract;
  test the materialized/cage routes actually used by the addon.

## Undo correction found during implementation

Legacy capture flags identify categories, so two selected color or sculpt layers
can alias the same flag. Prepared attribute-writing stages use separate data
chunks for their actual save sets. Each stage captures its touched region before
writing, and preview rollback removes those chunks in execution order alongside
topology chunks. This also restores face attributes and newly created columns,
which the older vertex-only preview snapshot cannot cover. The initial policy
uses memory proportional to touched elements per attribute-writing dab; existing
undo memory accounting includes these chunks. Geometry-only stages retain their
existing first-touch capture optimization. Optimizing these chunks requires an
attribute-identity-aware gate and must preserve mixed-stage and topology ordering.

## Completion gate

Native execution/compiler/attribute regressions, generated backend checks,
installed background/headed host tests, real paint/face-set gestures and package
provenance must pass before marking this deliverable complete. Generic collection
adoption, UI and migration remain later tasks in the eight-plan list.

Passed evidence: [verified manifest](../tests/plan6-attributes-gate.json) and
[gate record](../codebase/generic-brush-plan6-evidence.md#prepared-mesh-attributes--2026-09-18).
