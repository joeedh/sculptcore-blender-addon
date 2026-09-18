# Plan 4 persistent authoring storage

Status: native owner safety, persistent scalars, generated stacks and saved
placements have passed their bounded gates, 2026-09-17.
The separately reviewed and implemented [atomic scalar plan](generic-brush-atomic-scalars.md)
supersedes the metadata records CollectionProperty proposal below: metadata uses
custom IDProperty groups with native atomic publication, while the future declared
curve bank remains separate. Scalar values, policies and UI metadata pass their
bounded gate. See also [generated stacks](generic-brush-persistent-stacks.md) and
[saved positions](generic-brush-persistent-positions.md). Curve-bank integration and Brush/native-Scene
authoring undo remain open; no new stroke/UI consumer is enabled.

The original proposal below is historical and **not approved for implementation**
as written. Its remaining array/curve details need revision and review before use.

## Accepted review findings and bounded implementation

- Registered ID PointerProperties use `ID.system_properties`, while Python
  `owner.get()` reads `ID.properties`. Ordinary RNA access can delete malformed
  backing properties. A nonallocating, nondestructive inspection boundary remains
  necessary; `is_property_set()` alone does not validate the backing type.
- Assigning an empty Python list creates an integer array, not a collection.
  Use absent layers/positions for canonical empty, or a typed native transaction.
- Python dictionary round trips lose opaque IDProperty types, UI metadata and
  flags. Lossless preservation needs a native clone/transaction design before
  whole-stack publication. Scalar values and UI metadata must publish together;
  prevalidating Python arguments alone does not provide rollback.
- FLOAT32 describes numeric precision; ordinary Python float IDProperties are
  physically doubles containing quantized float32 values. Do not claim otherwise.
- **Undo scope:** global undo can restore generic Scene records. Brush IDs carry
  `IDTYPE_FLAGS_NO_MEMFILE_UNDO`, and Scene undo preserves current ToolSettings.
  Brush authoring and native Scene settings therefore need a separately reviewed
  authoring-undo design before the full Plan 4 gate can pass.

Implement now, following review by `review_plan4_storage` and
`review_plan4_notifications`:

1. Add a shared, bpy-lazy owner guard. Register lifecycle handlers independently
   before engine-dependent registration. Snapshot an integer generation in every
   store identity. Invalidate both before and after undo/redo/load, including load
   failure, and on unregister. Registration/removal is idempotent. Post invalidation
   also rejects a store created by another pre-handler against the old database.
2. Check thread and generation before RNA access, then current session UID and
   exact Main membership. Deleted wrappers become `PropertyError`. Reads may use
   linked owners; writes require editable, non-evaluated, non-override Main IDs.
   Apply the guard to policy operations as well as native value operations.
3. Validate write eligibility and input before suppressing native no-op writes.
   Compare float32-quantized values and genuine boolean unified flags.
4. Correct the UnifiedPaintSettings callback to notify its actual Scene, retaining
   specialized color synchronization and overlay invalidation.
5. Run pure regressions, actual external-asset no-op/dirty/rejection/Save/Revert
   checks, fresh-process load invalidation, headed undo/redo invalidation and
   existing native curve notification/package regressions. Record precise scope.

The remaining sections describe pending storage work. Their broad gates remain
open, and their API details must be revised and reviewed before implementation.

## Fork prerequisite

The initially proposed `ID.tag_custom_properties_changed()` is deferred. The
next design must specify the full commit boundary, including lossless native
cloning, scalar UI metadata, atomic publication and essential owner notification.
A generic method cannot claim arbitrary custom-property evaluation using only
`ID_RECALC_SYNC_TO_EVAL`: parameters, drivers, pointer relations and notifier
semantics require explicit coverage. No unrelated native property self-assignment
may substitute for asset dirty tracking.

Correct `rna_UnifiedPaintSettings_update` to notify `ptr.owner_id` (the edited
Scene) instead of the context Scene and active Brush. Keep the color/overlay
side effects in their existing specialized callbacks. Build the current fork
install and test inactive-Brush and inactive-Scene ownership with real assets.

## Saved schema and mutation boundaries

- Register a versioned `Brush/Scene.sculptcore_properties` PointerProperty with
  a records collection. Each record has a stable identifier, scalar type, value
  presence, value inheritance mode, stack inheritance, unified flag and positions.
  The actual scalar uses a typed custom IDProperty `value`: absence is unset,
  float values are validated/quantized FLOAT32 stored in physical IDP_DOUBLE,
  integers remain exact INT32,
  booleans retain their own type. Never store a native-backed value here.
- IDs and schema metadata use strings/integers rather than enum indices that
  could reinterpret unknown records. Reject unknown schema versions, duplicate
  record IDs, known-ID type mismatches and malformed known data without altering
  it. Unknown IDs and unknown extension fields survive ordinary writes, copies,
  save/reload and registration changes. Missing kernels affect execution only.
- Read system-property backing data through a nondestructive inspection API,
  still to be designed; ordinary `owner.get()` addresses the wrong namespace.
  Absent records return default/policy/empty stack without allocation. Stores
  capture the lifecycle epoch and ID session UID; no global owner cache exists.
- Persist stack metadata as the record's `layers` RNA collection, replacing its
  complete raw IDProperty array only after constructing and validating the full
  replacement. Use absent storage for empty collections. Preserve extension
  fields losslessly through native cloning, not Python dictionary conversion.
  At most one
  entry per device; explicit whole-stack replacement can repair malformed stacks.
- Keep owned curves in a separate per-record `responses` collection, keyed by
  device. Each response declares `CurveMappingProperty`. Metadata replacement,
  disable, ordering and preset changes do not touch this collection. Thus dormant
  curves survive even a stack clear; explicit curve removal is separate. Allocate
  only through an explicit initialize operation. Inheritance resolves references
  to the actual owner; Brush.copy/Scene.copy must deep-copy definitions.
- Add an immutable custom-curve reference to registry layer descriptions. It
  carries owner identity, stable property/device IDs and the owned API's exact
  runtime key, never a persisted pointer or sampled table. Validate it against
  the destination owner and live mapping before accepting stack publication.
  Cross-owner assignment rejects; independent ID copy is the supported copy
  operation in this slice. Preset seeding/evaluation remains Plan 5.
- Stage scalar values together with all UI metadata; failures preserve exact old
  presence, physical types, metadata, ancestors and dirty state. The transaction
  mechanism is unresolved. Complete layer/position replacement likewise stages
  before publication. Notify once after a semantic commit; unchanged operations
  do not mark assets dirty. Owned curve edits use the fork's native notification.
  Low-level raw edits require explicit owner notification and owned-curve sync;
  resolver validation rejects malformed raw data and never silently repairs it.

## Metadata, native composition and registration

- Attach definition-specific IDProperty UI data (hard/soft limits, default,
  description, subtype including unit-bearing subtype) to the stored value.
  Return metadata for absent/native fields without materializing storage. Reject
  unsupported metadata before writes; do not expose one generic unrestricted
  FloatProperty. UI rendering and operator ownership/cancel remain Plan 7.
- Implement the existing OwnerStore protocol with persistent policies and generic
  values/stacks. Compose the native strength adapter for actual values/scene flag;
  keep native strength stack capability explicitly unavailable until its pressure
  adapter arrives. Record policies without copying native values into the schema.
- Registration uses only bpy and frozen definitions, never engine manifests or
  a DLL. Call it before engine-dependent registration and cleanly unregister
  declarations while preserving data. Require fork capabilities; an older fork
  keeps the legacy addon path with an explicit unsupported-capability diagnostic.
- Add a default-off saved feature switch for later consumers; no new UI/stroke
  reader is enabled by this slice. Preserve unknown data when the switch is off.

## Gates

1. Pure registry/resolver regressions pass, including custom-reference validation.
2. Actual Blender checks cover all ownership combinations on persistent records,
   exact typed values/default presence, read-only rejection, unknown IDs/schema,
   duplicate repair, dormant curves, curve keys/reorder, independent Brush/Scene
   copies, unregister/re-register, metadata and missing-engine registration.
3. Fresh-process .blend save/read and external brush Save As/Save/Revert restore
   values/stacks/custom curves. Editing an inactive asset dirties only that asset;
   scene edits leave Brushes clean. No-op reads/writes leave clean assets clean.
4. Headed global undo/redo restores generic Scene scalar/policy/stack/curve state
   and invalidates old references safely. Brush and native Scene authoring need
   a separately reviewed undo mechanism; do not claim this gate for those owners
   using `ed.undo_push()`. Use current dialog-safe launchers and markers.
5. Re-run native-strength and owned-curve notification regressions plus package
   verification on the rebuilt fork. Record binaries and results in Plan 4
   evidence; update task checkboxes only to the scope actually completed.
