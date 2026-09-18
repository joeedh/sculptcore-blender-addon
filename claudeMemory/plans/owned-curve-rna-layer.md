# Plan 2: owned CurveMapping RNA layer

Status: reviewed, implementation underway, 2026-09-15.
Depends on the completed [native runtime core](owned-curve-runtime-core.md).
This is the next implementation layer; the editor and complete asset gate remain
mandatory before Plan 2 can be marked complete.

## Representation and lifetime

Keep the existing CurveMapping, CurveMap and CurveMapPoint RNA types. Add an
optional shared runtime handle to PointerRNA. Its interface validates/refreshes
a pointer and derives a child handle. Ordinary pointers retain an empty handle.
Owned handles retain a native deep-copy view of an immutable BKE snapshot, the
record, declaration tokens, kind/index and captured revision. Mapping/channel
handles refresh their view before operations; point handles and iterators fail
after an evaluation revision change. The full old view remains retained, so a
missed validation cannot free its point array. No saved parent IDProperty or
custom StructRNA pointers are kept in an owned pointer's ancestors: all owned
pointers are discrete. Refresh replaces only that PointerRNA's immutable handle;
it never frees a view still referenced by another copy of the old handle.

Integrate handle propagation into rna_pointer_create_with_ancestors and parent
extraction. Integrate validation into Python struct/property/function and
iterator validity paths, including mathutils callbacks. Native RNA entry points
that inspect owned curve data explicitly validate before dereferencing it.
Collection iteration pins its generation; next/skip cannot refresh into a new
generation. Reject owned foreach_get/set before raw-array extraction/fallback.
Never expose a mutable BKE snapshot pointer; the RNA view is a separate copy.

## Declaration and backing dispatch

Add an internal owned-curve property flag and a runtime factory in RNA_define.
Add bpy.props.CurveMappingProperty(name, description, update), following existing
deferred property registration and callback ownership. RNA pointer type remains
CurveMapping, storage is the ordinary tagged group in system_properties.
Dispatch owned pointer get/never-create-get, presence, assignment and unset
before generic idproperty validation. Unknown versions/types remain untouched
and report errors. Unset reads return None and do not allocate parent groups.
Direct mapping assignment is rejected; mutation uses the owned methods.

Declaration lifetime tokens are registered for the curve property and its
dynamic pointer/collection ancestors. Invalidate tokens before property teardown
in RNA_def_property_free_pointers (runtime build only). Tokens retain no Python
callable. Re-resolve the declaring parent for callbacks by walking the current
owner RNA system-property tree with nonallocating pointer reads and collection
iteration, matching the stable definition identity and declaration token.
Collection movement therefore changes callback parent location safely. Use the
same walk at initial binding to capture ancestor declaration tokens; never keep
raw dynamic StructRNA ancestors after the operation.

## Transactions and errors

Add a scoped native RNA error collector for void accessors. Python pointer
conversion, field/array writes and mathutils mutation inspect the result and
raise ReferenceError for stale handles, ValueError for invalid definitions and
PermissionError for unsupported read-only owners. Native C++ callers can use
the same scoped collector; no Python exception APIs enter BKE/RNA internals.
No unconsumed thread-global error may leak into a later operation.

Owned field setters edit a deep transaction copy and commit through BKE with
the expected revision. Add explicit setters for generated point/clip/enum
fields and owned-aware branches to existing custom setters. Presentation-only
selection/view changes stay in the RNA view without revision/dirty changes.
Mapping update refreshes the current record (preserving normal point-write then
mapping.update usage). Invalid edits preserve storage, view and revision.
Point insertion/removal use a transaction copy and membership validation before
calling BKE routines; point-count limits are checked before native insertion.

Convert curve functions to FUNC_SELF_AS_RNA and full PointerRNA parameters and
results where needed: evaluate, update, initialize, reset_view, points.new/remove.
Validate owned/native and record/generation membership before evaluating or
removing a point. Return a newly guarded point from insertion. Scalar wrapping,
tone and level restrictions come from the codec and raise on invalid edits.

Add owner.curve_mapping_initialize and curve_mapping_sync methods, callable on
ID and PropertyGroup. Initialization creates a complete validated definition
before attaching it; existing initialized values are returned without mutation.
Add a root-ID property-path variant for entirely absent nested parents. Build
missing parent groups off-tree before attaching, reject absent collection items,
and avoid materializing unrelated ancestors. Unset checks editability before
removing a definition. Sync validates and notifies even when its first runtime
record was only acquired after the raw edit.

## Owner notification and callbacks

After successful authored changes, tag the actual Brush/Scene first. Then
resolve the current declaring parent and invoke its callback once. Protect the
callback's Python reference during invocation: existing bpy_prop_update_fn uses
a borrowed reference that can be removed by unregister inside the callback.
Do not dereference PropertyRNA or parent pointers after invoking Python.
Use a per-record recursion guard; cross-curve callbacks remain allowed.
Owned curve field updates bypass native parent notification callbacks so an edit
does not notify twice. Suppressed/failed/unchanged commits do not notify; explicit
sync is the exception above. Same-curve callback mutation invalidates older view
generations, including a future editor session, rather than authorizing overwrite.

## Editor seam and publication

Until the persistent editor session is implemented, template_curve_mapping must
recognize owned pointers and draw a clear unavailable control instead of entering
the native raw-pointer widget. This temporary guard is removed by the next layer;
it is not a completed editor feature. Public factory availability does not mark
the Plan 2 gate complete or switch the addon to the new system.

The editor layer must retain stable session/button state, use staged numeric
values, handle popup cancel and external changes, commit before undo push, and
provide root-ID/path nonallocating drawing and undoable first initialization.
These previously reviewed requirements remain in force.

## Acceptance for this layer

Build the actual fork and run Python tests for declaration/deferred registration,
unset/nonallocating reads, initialize/unset/sync, native type compatibility,
field/array/mathutils edits, evaluate/new/remove, invalid transactions, unrelated
active owner, optional callbacks, self-unregister and cross-curve callbacks.
Hold mapping/channel/point/iterator/mathutils handles across commits, collection
growth/move/delete, owner copy/delete, undo/load and declaration replacement;
assert correct current values or safe errors. Test read-only/editable asset policy
and untouched unknown versions. Ensure native curve regressions remain intact.
Record actual evidence and leave the full Plan 2 editor/asset gate unchecked.

## Accepted adversarial corrections

Fresh reviewers `review_rna_handles_v3` and `review_rna_transactions_v3`
inspected the actual fork and identified the following required changes:

* Preserve stable Python equality/hash using record/kind identity (point identity
  also includes revision/index). Refresh must not change dictionary key hashes.
* Handle CurveMapPoints, the collection-method alias of CurveMap, explicitly.
  Use full PointerRNA function return storage (PARM_RNAPTR + PROP_THICK_WRAP).
* Cover PYRNA_STRUCT_IS_VALID (repr/str), retained function vectorcall, iterator
  fast paths, mathutils errors before update, and native generated access via
  actual checks at the common RNA entry points, not debug-only assertions.
* Reject off-main-thread access before BKE or declaration traversal. Reject
  non-finite/float32-overflow Python numeric inputs before RNA parameter/array
  clamping can conceal them.
* Bypass the entire generic update pipeline for owned changes. Its post-callback
  property/owner accesses are unsafe after self-unregister or deletion. Essential
  tagging precedes callback execution; no property/owner access follows Python.
* Capture unset's notification context before detach. Use a read-only raw storage
  walk restricted to declared system-backed PropertyGroup pointers/collections;
  never call generic getters that may destroy malformed unrelated siblings.
* Centralize the owned discriminator in rna_property_rna_or_id_get and guard
  pointer_add/remove, reset and unset as well as get/set. No path may create an
  empty tagged group or delete an unsupported payload on read.

Scalar setters can use central owned dispatch in RNA_access rather than adding
many duplicate generated accessor bodies. The common entry points must validate
before any native generated getter/collection callback. Iteration retains a
pinned generation; mapping/channel ordinary reads refresh independently.

Implementation review corrections (same fresh reviewers, 2026-09-15):

* Direct generated native accessors also need manual guards; generic RNA access
  alone leaves direct field setters outside the transaction path. Custom
  collection getters return full PointerRNA, including the owned child handle.
* Numeric conversion can execute Python. Revalidate after float/sequence/bool
  coercion and each function argument, before dispatch or error formatting.
  Restrict finite-number marshalling policy to the owned function arguments,
  ending it before callbacks can edit unrelated native properties.
* Validate ID/PropertyGroup declaration type and actual ID-rooted ancestry,
  original rather than evaluated ownership, and total ancestor depth before
  attaching any initialized definition. Bone-owned PropertyGroups have separate
  storage roots and are unsupported by this API.
* Pending optional notification belongs to the binding, so refreshing a mapping
  between a native setter and its update call cannot drop that notification.
* Mathutils methods must propagate failed write callbacks rather than returning
  success while a Python exception is pending.
* Explicit unset is a deliberate deletion request and may discard an unknown
  version or malformed payload. Reads, sync, and ordinary edits preserve it.

Callback removal policy, additionally reviewed by both RNA reviewers: active
callbacks retain the native record, declaration token, and captured owner
address/session UID in RAII scopes. Nested unset of that record suppresses its
callback. While a callback's curve has been removed (including via item/ancestor
deletion), initialization of any absent instance of the same declaration on that
owner is rejected until the callback returns. Existing instances can still be
read/edited, and other declarations/owners are unaffected. The check happens
before definition allocation/attachment; staged missing ancestors are discarded
on rejection. This prevents unset/reinitialize recursion without pretending an
erased, movable collection item still has stable identity. Ordinary unset
callbacks enter with the removed flag already set. Attachment validity is
checked separately from raw-definition synchronization.
