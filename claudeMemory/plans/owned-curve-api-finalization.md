# Plan 2: owned CurveMapping API finalization

Status: reviewed for implementation, 2026-09-15. Fresh reviewers
`review_owned_api_cache` and `review_owned_api_boundary` inspected actual code;
their surviving findings are folded into the corrections below.

The owned declaration/runtime/editor are implemented. This bounded final slice
publishes cache invalidation and capability metadata, then documents the actual
API. It does not complete the outstanding editor/lifecycle regression gates.

## Proposed API

- `bpy.props.owned_curve_mapping_api_version == 1` identifies the complete v1
  owned property API. Stock/earlier forks lack the constant. The saved schema
  remains the existing tagged IDProperty group, independent of this capability.
- `mapping.curve_mapping_cache_key()` returns two exact Python integers:
  `(runtime_record_identity, definition_revision)`. Implement through the existing
  bpy_struct C-method machinery and a guarded RNA helper. Reject ordinary
  native mappings, nonmapping structs, worker threads, invalidated declarations,
  deleted owners, stale raw unsynchronized data and obsolete pinned handles.
- Normal unpinned owned mapping handles may refresh to the current snapshot
  before reporting its revision, matching their existing getters. Presentation
  edits leave revision unchanged; valid evaluation changes and successful raw
  sync advance it; unchanged writes/rejected edits do not. Copy/reload/undo may
  create a fresh record beginning at 1. A revision is not persistent identity.
- Call the key method before reusing an evaluator: stale/invalid handles must
  not authorize cached data. Cache the immutable integer tuple, not a Python RNA
  wrapper. Re-registration creates new bindings but may retain the record/key;
  old wrappers reject access. Identity is process-local and never persisted.
- Native adapters continue reading authoritative native CurveMappings. This
  owned-only method does not promise complete revision tracking for native
  mappings; their cache strategy belongs to Plan 5.

## Implementation and gates

1. Fresh reviewers inspect actual bpy_struct method dispatch, error/owner
   guards, hash/equality and binding lifetime, and module constant registration.
   Fold concrete findings into this document before implementation.
2. Add the guarded native helper, exact Python integer wrapper and module
   capability constant. Document factory arguments, scalar restrictions,
   initialization/sync/unset, root-path template, transactional dialog,
   callbacks, read-only policy, copy/persistence and old-reader behavior.
3. Add meaningful real-Blender checks for revision changes/no-ops/presentation,
   raw conflicts/sync, copy/undo/reload/declaration replacement and invalid owner
   behavior. Run the existing suites against the resulting binary. No mock
   revision or header-only gate.
4. Complete remaining headed editor controls/clipboard/clipping, deletion and
   callbacks, concurrent views, external assets, and existing SculptCore
   cancellation regressions before checking the parent Plan 2 gate.

## Review corrections

- Assign a monotonic process-local uint64 identity only when creating a native
  record. The strong registry preserves it across temporary wrapper/binding
  destruction. Never reset the counter on undo/load/invalidation. A new record
  after copy/unset/reload has a different identity even if its revision is 1.
- RNA wrapper hashes are unsafe as durable dictionary keys in Python-safety
  builds: invalidation clears the owned handle. This did not reproduce in the
  current executable, but integer tuples avoid that build-dependent behavior.
- Revision means committed definition revision, not a guarantee that evaluated
  output changed. Opaque raw extensions can advance it. Unchanged sync must
  return before owner notifications/callbacks; the existing unconditional RNA
  sync notification is corrected in this slice.
- Check Python wrapper validity with PYRNA_STRUCT_CHECK_OBJ even for a captured
  bound method. Validate RNA first, then reacquire its possibly refreshed owned
  handle; never read an older handle's revision. Normal lookup/captured methods
  both reject invalid access through the existing ReferenceError guard.
- Build the tuple with checked PyLong_FromUnsignedLongLong allocations and
  correct PyTuple_Pack reference management. Audit exact unsigned conversion;
  do not introduce a public counter setter solely to manufacture huge revisions.
- Add real Sphinx function/method directives to the current factory and
  initialize/sync docstrings as well as the new method. Document capability
  semantics separately: version 1 means the documented API is available, not
  that the release/testing gates have passed.
- Tests cover wrapper GC/reacquisition, re-registration, copies/new records,
  presentation/no-ops, captured methods after invalidation and worker access,
  immutable-key eviction after owner deletion, and materialized-record no-op
  sync preserving callback count/dirty state.
