# Plan 4 atomic scalar records

Status: implemented and bounded completion gate passed, 2026-09-17. Two fresh
adversarial plan reviews and subsequent implementation audits are folded in.
See [completion evidence](../codebase/generic-brush-plan4-evidence.md#persistent-atomic-scalar-records--2026-09-17).

## Review corrections

Both native and addon reviewers accept the architecture with these corrections:

- Honor ID_IS_EDITABLE, including editable linked Brush assets. Reject ordinary
  read-only links and unsupported overrides. Never equate linked with read-only.
- Parse exact outer/inner containers, operation tokens, paths and UI dictionary
  keys/values before fetching owner pointers. Use direct internal UI C helpers,
  not mutable Python attributes. Preserve static-type flags and reject retyping
  static leaves. Compare complete normalized UI state, not requested keywords.
- Preflight the whole existing root iteratively with a depth limit before native
  recursive cloning; operation depth alone cannot bound opaque unknown data.
- Register the method on RNA_ID using bpy_rna_types_capi and add its dedicated
  source/header to python/intern/CMakeLists. Include the node-tree shading notifier
  in the single post-publication notification phase. No-op means no owner-side
  allocation; detached normalization necessarily allocates staging.
- BOOL UI uses only default/subtype/description. INT32 hard bounds are ceil(min)
  and floor(max), soft bounds rounded then clamped into the integer interval.
  Reads require genuine bool/int/float and exact float32 quantization; they cannot
  silently narrow malformed stored doubles. Scalar writes may explicitly repair.
- Existing roots require a valid schema_version and records group. Existing known
  records require matching full identifier/type. Absent is distinct from malformed.
  Reserved native strength never falls back to generic storage when unavailable;
  validate schema before native writes and persist policies without transient
  native policy setters. Test a Scene with no Sculpt settings.
- A Blender probe confirms path_resolve of custom nested groups returns a generic
  PropertyGroup with id_properties_ui; reacquiring it after each commit provides
  metadata access without registered record declarations.
- A bounded GC-disable guard spans callback-free native parsing/staging/commit
  and restores the caller's prior GC state last. The GIL remains held, and direct
  internal C helpers avoid Python attribute dispatch. Equality examines detached
  UI data only. Two implementation-review reproductions additionally require
  preserving existing int enum choices and rejecting float-backed step overflow.

## Scope and schema correction

Implement persistent typed values and value/stack inheritance policies now.
Stack authoring, custom-curve bank, inventory migration and authoring undo remain
explicit later gates. All stack/execution capabilities stay unavailable in this
slice; native strength values and Scene unified flags stay authoritative RNA.

Use custom IDProperty groups, not a registered PointerProperty, for metadata:
`owner['sculptcore_properties'] = {schema_version: 1, records: {key: record}}`.
Record keys are `p_` plus lowercase unpadded base32 SHA256 of the stable ID
(54 ASCII bytes, below Blender's 63-byte key limit). Store the full stable ID and
type inside each record and check both on access; a collision rejects. Group
keys make uniqueness structural without imposing a length limit on stable IDs.
Record fields: identifier, scalar_type, optional value, value_mode (default
UNIFIED), inherit_stack (default false), unified (default false, generic Scene).
Physical floating storage is IDP_DOUBLE holding exact float32-quantized values;
int and bool remain distinct. No native value/unified-flag duplicate is stored.

The eventual declared CurveMapping bank is separate from metadata, attached to
the same ID. Metadata publication therefore never replaces known curve backing
storage. This supersedes the prior unimplemented records CollectionProperty
proposal; logical collections do not require RNA collection arrays. No feature
switch or new stroke/UI consumer is enabled yet.

## Native atomic scalar API

Add `ID.id_properties_update_atomic(root, operations)` as an engine-agnostic
Python method, implemented in a focused Python/RNA source file. It operates
only on a named custom-property root group, never ID.system_properties.

- Operations are exact tuple entries in an exact tuple/list: `('SET', path_tuple, scalar, ui_dict_or_None)`
  or `('DELETE', path_tuple)`. Paths are nonempty tuples of exact strings relative
  to root. SET creates missing intermediate groups. DELETE absent paths is a no-op.
  Validate UTF-8 key byte lengths, embedded NUL, depth and duplicate/overlapping
  paths. Root has the same key validation. Reject malformed ancestors; never
  silently replace a non-group parent. Limit depth to 32 and operations to 1024.
- Incoming values are exact builtin bool/int32/finite double/UTF-8 str. No user
  coercion protocols, mutable containers, ID pointers or Python callbacks.
  SET/DELETE may replace/remove scalar leaves only, never groups, arrays or IDs.
  Unknown siblings are preserved without conversion, including typed arrays,
  empty IDP_IDPARRAY, UI metadata, flags and ID references.
- Clone the named root natively with `LIB_ID_CREATE_NO_USER_REFCOUNT`. Apply all
  operations and UI updates to this detached clone; free staging with
  `IDP_FreeProperty_ex(..., false)`. No operation may change ID-pointer topology,
  so the published clone inherits the exact original references/user counts.
  Replacing the original likewise frees with `do_id_user=false`. Missing root
  creation and all ancestor allocation happen only in staging before publication.
- UI updates use Blender's existing IDPropertyUIManager on the staged scalar,
  with exact builtin-only keyword values validated before invoking the C method.
  Preserve old flags/UI on same-type replacement; a type change intentionally
  changes that known leaf's representation. Invalid UI data leaves owner content,
  presence, user counts and dirty state unchanged. Reject nested/enum UI payloads
  in v1; support scalar limits/default/description/subtype/step/precision only.
- Duplicate or ancestor-overlapping leaf operations reject, so semantic no-op
  detection can compare each staged leaf against its original once (type/value
  plus requested UI data). No-op commits return false without root allocation or
  notification. Successful semantic commit returns true and notifies once.
- Validate main-thread/write-context, current Main membership, editable original
  ID and unsupported override status before any staging, even for no-ops. No
  Python conversion callbacks are allowed while holding a live raw ID pointer.
  Retained wrappers into a replaced metadata root follow ordinary raw IDProperty
  wrapper limitations; addon code exposes only copied immutable values and
  reacquires groups after every commit. Owned curves live outside this root.
- Notify scalar custom-property changes using the existing RNA custom-property
  pattern: depsgraph transform/geometry/parameter and synchronization tags,
  window/ID notifier, plus actual Brush unsaved flag/Brush notifier or Scene
  tool-settings notifier. No pointer-relation rebuild is needed because this API
  cannot alter ID-reference topology. It does not create undo or invoke arbitrary
  declaring-property callbacks. Document this boundary explicitly.

## Addon store

`PersistentOwnerStore` uses OwnerGuard for every operation. Read custom roots via
`owner.get()` (correct for this revised namespace), validate known schema fields,
and copy only known scalar fields into immutable descriptions. Missing reads
allocate nothing. Future schema versions, bad record identity/type or malformed
known policy fields reject without repair. Unknown records/fields are untouched.
Explicit scalar replacement can repair a malformed scalar; it cannot replace a
group/array/ID stored as value through this bounded API.

Writes stage schema/version/record identity plus changed fields in one atomic
call. Native strength delegates value/Scene flag operations exclusively to its
adapter; persistent policy writes preserve native state and unrelated metadata.
Generic values carry per-definition UI metadata atomically. Unsupported units
reject before writes (initial support NONE, ROTATION/ANGLE, LENGTH/DISTANCE).
The store's metadata accessor supplies definitions without creating value data.
No DLL import is needed. No declaration registration is needed for these groups.
Fork capability absence makes this explicit API unavailable; legacy addon stays
enabled and existing stroke/UI behavior remains in use.

## Gates

1. Native boundary tests on actual Blender: exact scalar types, absent reads,
   successful/rejected/no-op batches, invalid later operation/UI rollback, malformed
   ancestors, embedded-NUL/long/deep/overlapping paths, read-only linked/override/evaluated/
   thread/write-context rejection. Verify ID-reference counts and opaque sibling
   types/UI metadata/flags remain unchanged, including failure.
2. Addon ownership truth table with persistent values/policies, dormant local
   restoration, native composition/no duplicate values, future-schema/unknown
   record preservation, copy independence and definition metadata.
3. Real inactive external Brush dirty state, no-op cleanliness, Save/Revert and
   fresh-process .blend readback with source modules absent during save/load.
4. Headed Scene generic scalar/policy undo/redo plus lifecycle invalidation;
   do not extrapolate this to Brush or native ToolSettings undo.
5. Pure foundation and owner-safety regressions; package installation/smoke on the
   rebuilt fork. Record evidence and keep broader Plan 4/Brush undo gates open.
