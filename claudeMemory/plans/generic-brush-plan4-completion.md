# Plan 4 completion sequence

Status: complete, 2026-09-17; [evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
The reviewed sequence below is retained. Do not stop at intermediate
gates or mark Plan 4 complete until every original task/gate is accounted for.
Each material subdesign gets fresh adversarial reviews before implementation.

1. Integrate declared owner-aware custom mappings with persistent generic stacks.
   Use direct stable per-property/device declarations as the initial reviewed
   candidate; validate owner identity, stale references, independent copies,
   registration without an engine, and real asset/Scene persistence and undo.
2. Complete authoritative native adapters and their inventory: coupled size,
   native/shadow pressure and native response curves, cavity block precedence,
   scalar/conversion adapters and explicitly retained unsupported native data.
   Implement read-only legacy views and frozen manifest/default registration;
   keep missing-kernel values intact. Add default-off saved new-path switch.
3. Resolve authoring undo for Brush/native Scene settings with a separately
   reviewed engine-agnostic native transaction/undo boundary. Ordinary memfile
   undo alone is insufficient. Do not change all brush/sculpt undo semantics as
   a shortcut or claim Scene tests as Brush coverage.
4. Run full persistent owner tables with native script edits, asset switching,
   DLL-disabled registration, missing definitions/kernels, native cavity truth
   table, exact size pair preservation, copy/undo/reload and packaged install.
   Map every Plan 4 checkbox to code and evidence; keep Plans 5–8 consumer/UI/
   release gates distinct. Close the reopened Plan 2 Brush undo only when proven.

## Custom mapping integration candidate

Add a pure immutable `CustomCurveReference` carrying owner identity (generation,
caller epoch, kind/session UID), stable property/device IDs, declaration generation and exact
native `(record_identity, definition_revision)` key. DeviceLayer accepts this or
a generated ResponseCurve. Saved layers store `preset='CUSTOM'` with zero unused
parameters; live references are reconstructed on read, never serialized. Custom
layer writes require a reference to the actual destination owner/property/device
and current mapping key. Copying an ID reconstructs references for the copy.

`CurveBank` registers one direct `CurveMappingProperty` on Brush/Scene per dynamic
definition/device, named `sc_curve_` plus 52 base32 hash characters of the full
property ID/device pair. No registered collection or hidden node tree is used.
Registration is explicit, main-thread, engine-independent and nonallocating for
owners. Global declaration bookkeeping rejects an existing conflicting RNA
property or hash identity. Separate registries share identical declarations;
unregistration retires its references and releases shared declaration leases.
Benchmark bounded registration growth on the frozen inventory.

Reviewed corrections (fresh lifetime and semantics agents, 2026-09-17):

- A native declaration token is required: the actual Blender probe reused a
  PropertyRNA address immediately. Add `bpy.props.curve_mapping_declaration_key`
  taking a Python RNA type and exact string; reject workers before RNA access,
  reject capsules, NUL and inherited lookup. Native process-wide nonzero uint64
  tokens never reset and fail on exhaustion. This allocates runtime bookkeeping
  only; it never allocates owner data. Removal retires the token before callbacks.
- Shared declarations use leases keyed by owner type/name, full immutable
  definition/device contract and native token. Each bank has its own generation.
  Preflight all collisions and capture the registry snapshot. New definitions
  require explicit re-registration; reads cannot register declarations.
- Journal acquisitions/creations. Failed registration releases only its leases;
  delete only current-token, zero-lease declarations created by that attempt.
  Preserve external replacements and other banks. Publish registration last.
- Initialize/remove validate schema, definition, eligibility and local stack
  metadata first. Removal parses selection metadata without resolving unrelated
  mappings, rejects disabled CUSTOM selections too, and validates the target
  payload before explicit unset. Unknown/malformed data is preserved.
- Test shared leases, injected partial failure, hash collisions, reused deferred
  declarations, registry growth, caller epoch, external replacement, malformed
  removal, inherited Scene references and independent dormant Brush copies.

The explicit initialize operation initializes a dormant LINEAR mapping using
the owned API, without modifying a stack. Selecting an existing custom reference
publishes metadata only. Preset seeding / combined UI selection is Plan 5/7 and
must not be represented as implemented here. Reads never initialize curves.
Mappings remain dormant through generated preset selection, disable/reorder and
stack clear. Removal is explicit and rejects while the local stack actively
references CUSTOM (including disabled entries); clearing/selecting a preset then
removing is the supported sequence. The store checks schema/definition/lifetime
and owner eligibility before each mutation. Native pressure uses its native
adapter later, never this bank on Brush.

Tests: generated regression, custom selection/read/edit/current revision,
cross-owner/stale/property/device rejection, copy, registration/re-registration,
unknown data preservation, nonallocating absent reads, inactive asset dirtiness,
Save/Revert/fresh-process no-authoring load, Scene undo and declaration growth.
