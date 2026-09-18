# Plan 2 runtime implementation refinement

Status: initial draft rejected by adversarial review, 2026-09-15. This elaborates Plan 2;
it does not waive its acceptance gate or introduce a production addon switch.

## Existing foundation

`BKE_curvemapping_idprop.hh` encodes/decodes validated scalar definitions using
ordinary IDProperty types. No runtime pointers or owner references are saved.
Native tests and old-reader file/asset round trips are in progress.

## Lifetime model to pressure-test before implementing

The proposal below is retained as the reviewed input, not permission to implement
it unchanged. See the mandatory corrections after the validation sequence.

1. Add a runtime registry for materialized owned curve definitions. Key by the
   heap-allocated definition group's identity, never a collection item address
   or its index. A group stored inside a PropertyGroup is a separately allocated
   list child, even when an ancestor IDP_IDPARRAY moves its inline items.
   A free-content hook in IDProperty invalidates a registered definition before
   freeing its children. Deep copies have fresh identities. Do not add a saved
   DNA type or persist registry keys.
2. Registry entries have an owner ID, monotonically increasing revision,
   canonical definition, and a materialized CurveMapping. Validate an entry's
   current attachment by walking the live owner's system property tree before
   an operation; resolve the current parent and declaration by identity. Do not
   dereference saved ancestor pointers after collection movement. Parent removal,
   property removal, owner deletion, undo, load and asset Revert invalidate or
   rebuild the entry. Registration replacement invalidates the declaration
   generation; no callback address or Python class survives unregister.
3. Extend PointerRNA with an optional shared lifetime/validity guard, inherited
   by child pointers and retained by Python wrappers and UI callbacks. Ordinary
   RNA pointers pay only an empty guard. Guard validity must be checked before
   dereference, including Python attribute/function/collection/iterator access.
   Curve-specific entry points reject invalid guards even in native callers.
   A stale owned pointer raises ReferenceError in Python instead of accessing
   a freed or replacement item.
4. Owned mapping/channel wrappers retain a materialization. Owned point
   wrappers and iterators retain snapshots of the point data and the expected
   revision, so native reallocation never leaves their data dangling. Mutation
   resolves back to the live definition only if revision and attachment match.
   Insertion/removal/reset may invalidate all old point wrappers; the contract
   permits a safe exception instead of following points across reallocation.
   A point field write commits the edited snapshot transactionally; other old
   point snapshots may then become invalid. Native curves retain existing RNA
   behavior except for explicitly tested owner-notification fixes.
5. The owned UI path uses a block-owned editable materialization snapshot with
   an expected revision. All raw button data and popup callbacks retain that
   snapshot, including clipping, selected-point coordinates, zoom and presets.
   External edits cannot free its memory. A callback checks attachment and
   revision before committing; stale UI edits are discarded with a redraw and
   never target a replacement item. Widget commits advance its expected
   revision so a drag can continue. Inspect current UI block/callback ownership
   rather than assuming a closure on the main curve button retains every popup.
6. Add an internal owned-storage discriminator to PointerPropertyRNA. Dispatch
   before the generic IDP_GROUP pointer cast and destructive type validation.
   Invalid/version-unknown payloads remain untouched and report an error.
   Read is null when unset, including template draw. An explicit Initialize
   button/operator creates the curve transactionally; ordinary property_unset
   removes it through the owner path. Nested unallocated parents must not be
   created as a side effect of draw.
7. Declare bpy.props.CurveMappingProperty with the frozen scalar API arguments.
   Add owner.curve_mapping_initialize/unset/sync operations. Access and edits
   use the standard system-property root and nested PropertyGroup storage.
   Commit validates into temporary storage before replacing the definition;
   invalid numeric edits leave saved data intact. Raw IDProperty writes require
   explicit sync; synchronization rejects invalid definitions non-destructively.
8. Notify the actual owner regardless of optional declaration update callbacks.
   Brush updates tag its unsaved asset state; Scene updates tag its file/tool
   settings state. Re-resolve declaring callbacks after essential notification,
   guard against recursive update, and do not retain Python callback references.
   Presentation-only edits do not serialize, increment revision, or dirty assets.

## Validation sequence

* Native registry/lifetime tests: independent copies, free/reallocation, invalid
  definitions, transactional commits and revisions.
* Python declaration, nonallocating reads, initialize/unset, two callbacks on
  the same owner, point edits and invalid old point/iterator references.
* Parent collection growth/move/remove, copied owner, delete/undo/load/revert,
  unregister/re-register and raw sync. Include retained wrappers and popups.
* True native API file/external asset round trips through stock and prior fork
  readers, and fresh-process evaluation readback.
* Headed editor first customization/undo, point edit/undo/redo, clipping and
  presets, asset Save/Revert .375/.75/.375 and correct dirty owner.

## Questions for adversarial review

Find concrete unsafe or unbuildable seams in this model against the current
fork. In particular: coverage of IDProperty content-free paths and undo reuse;
PointerRNA direct-data callers and generated RNA access; nonallocating nested
parent draw; UI block/popup lifetime; and whether snapshots can preserve native
curve editor behavior without introducing incorrect callback/undo semantics.
Suggest a simpler safe implementation where possible, not a raw pointer proxy.

## Adversarial findings accepted

The native core has since been implemented using the separately reviewed
[runtime core plan](owned-curve-runtime-core.md). RNA/editor integration remains
pending; the rejected assumptions below were not used as implementation approval.

Two fresh-context reviewers inspected actual RNA generation, IDProperty copy
and undo, Python function results/bulk access, UI redraw transfer and popups.
Their surviving findings are mandatory constraints on the next implementation:

* A definition-group identity survives ancestor array movement, but a free hook
  alone misses `IDP_CopyPropertyContent`: it swaps destination contents with a
  temporary before freeing that temporary. Explicitly invalidate destination
  identity before content replacement, and audit all transfer operations.
* Undo swaps ID contents while retaining the owner's address. Validate current
  attachment, not just address liveness. Never rebind an old token to new data.
  Owned wrappers must not retain movable PropertyGroup ancestors or dead
  custom StructRNA types; construct a discrete native owned-curve root and
  resolve current paths through the registry.
* The generic PointerRNA guard is insufficient on its own. Generated RNA
  directly casts data; function arguments/results strip guards; retained
  mathutils vectors and iterator next have separate access paths. Owned-aware
  functions need `FUNC_SELF_AS_RNA` and `PARM_RNAPTR` parameters/results.
  Point removal must resolve membership in the retained generation, not compare
  an independently copied point with the live array address.
  `BKE_curvemap_remove_point` also replaces its array when a foreign point
  makes it return false; run it on a transaction copy after membership checks,
  never on live owned storage whose handles should survive a rejected edit.
* Prefer a retained full materialization per generation over independent point
  copies. Define whether mapping/channel handles refresh to a new generation
  before operations, while point/iterator handles fail after structural edits.
  Preserve the normal `curve.points[...]` edit followed by `curve.update()`
  usage; do not silently require users to reacquire every mapping after every
  field edit. Resolve this explicitly before implementing runtime wrappers.
* Owned `foreach_get/set` cannot use raw-array extraction. The fast path writes
  with memcpy and even ends the iterator before returning its raw pointer.
  Implement a single validated bulk transaction or explicitly reject owned
  bulk access; per-point fallback is unsafe if its first write invalidates
  the remaining iterator. This restriction does not change native curves.
* Rejected property setters need a scoped mutation-result/error channel at
  RNA/Python/UI dispatch: ordinary native setters return void, so silently
  refusing the edit does not implement the promised Python exception. Generic
  BKE code must not directly manipulate Python exception state.
* Use persistent editor sessions across redraw/drag/popup, with stable button
  identity and explicit active-state transfer. A new snapshot per draw fails
  native active-button matching/transfer and leaves stale drag state.
* Numeric controls need stable staging scalars. Keeping the mapping alive does
  not keep point-field addresses alive after insert/remove/reset or duplicate
  removal. Every popup owns its session and explicit commit/cancel handling.
* Scalar preset buttons must maintain channel zero; the current generic preset
  row sets `cur=3`. Validate paste before mutation because it can copy wrapping
  and RGB state without invoking scalar setters. Reject incompatible template
  options such as RGB levels/tone for owned scalar curves.
* Existing `RNAUpdateCb` retains a parent pointer and raw PropertyRNA pointer.
  Owned callbacks instead retain owner/session identity plus declaration name
  and generation. Finish essential notifications before optional Python code;
  temporarily own the callable, revalidate after it returns, and never access
  a declaration it may have unregistered. Recursion guards are per definition,
  allowing curve A's callback to edit curve B. Same-curve callback changes
  invalidate the editor session instead of authorizing it to overwrite them.
* Nonallocation must cover absent ancestors. Passing `brush.settings` to a
  template already allocates that group. Add a root-ID/property-path draw and
  initialization route (or a clearly documented guarded equivalent) that
  resolves without creation and initializes the full chain atomically.
* Commit before the relevant undo push. Rejected/stale edits must not produce
  successful-looking undo entries; test clipping Escape/outside dismissal and
  external revision changes during an open popup.

The separate, narrow native notification fix was also reviewed: actual-owner
tags, callback signatures and failure paths have no surviving code defect.
Its Python tests do not substitute for headed owned-editor/lifetime checks.

Source anchors: `idprop.cc::IDP_CopyPropertyContent`,
`readfile.cc::read_libblock_undo_restore_at_old_address`,
`bpy_rna.cc` function result conversion and collection iterator/bulk paths,
`rna_access.cc::RNA_property_collection_raw_array`, `makesrna.cc` generated
accessors, `interface.cc` active-button matching/transfer,
`interface_template_curve_mapping.cc` preset/numeric/clipping controls, and
`interface_handlers.cc` CurveMapping paste and popup completion.
