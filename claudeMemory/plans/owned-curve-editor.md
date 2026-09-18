# Plan 2: owned scalar curve editor

Status: reviewed for implementation, 2026-09-15. Fresh adversarial reviews by
`review_owned_editor_ui` and `review_owned_editor_identity` are incorporated
below. RNA lifecycle and asset tests now pass;
the formatting rebuild is running. This completes the remaining editor layer,
not the generic addon UI in Plan 7.

## Editing interaction

Use Blender's native curve graph inside a transactional operator dialog. An
owned curve template shows an Edit Curve control. The dialog has the graph,
selected-point coordinates/handles/removal, clipping controls, extension,
zoom/reset-view, and scalar presets. Apply commits once and pushes one undo
step. Cancel, Escape, or dismissal discard the temporary edit. This is an
intentional owned-curve interaction: existing native CurveMapping templates
retain their current inline behavior.

An unset property shows Create Custom Curve. Its undoable operator initializes
one definition; undo restores absence. It does not open an edit transaction
before the owner has a stable definition identity. Add a root-ID/path template
entry so drawing missing PropertyGroup ancestors does not allocate them. The
existing template dispatches declared owned properties to this branch; its
caller has already obtained any explicit PropertyGroup argument.

## RNA transaction interface

Expose an internal editor transaction (not a Python type) in RNA_owned_curve:
begin from a validated owned mapping, retain its binding/declaration tokens and
expected evaluation revision, and return a deep native working mapping.
Commit validates the candidate and expected revision, tags the actual owner,
then invokes the optional declaring callback. Finish without reading the
owner/property afterward. A commit may invalidate the editor via its callback;
the dialog closes after Apply and does not authorize another write.

Add a read-only path inspection function for root-ID/path template use. Walk
metadata and existing raw groups/collection items without generic getters;
missing pointer ancestors remain absent. Reject missing collection items and
unsupported declarations/owners. Initialization uses the existing atomic path
operation. Capture declaration tokens for UI actions so re-registration does
not authorize an old button. Resolve a live owner through context Main using
captured owner address/session UID, never dereference a retained raw owner.

For an existing curve, dialog execution always targets the retained definition,
not a collection index/path looked up again. Movement remains valid; removal,
undo, reload, declaration replacement or external revision changes reject Apply.
For first initialization, a stale UI path must not initialize a replacement
collection item. Review must identify a concrete path/container-generation
guard for this case before implementation; do not assume content equality proves
identity when two empty collection items are identical.

## UI lifetime and staging

The operator owns a shared session through invoke/draw/execute/cancel. The graph
button retains the same session and native mapping address across redraws, so
ordinary active-button matching and transfer work. Every callback captures the
session, never an RNAUpdateCb containing a saved dynamic parent/property pointer.

Use a dedicated owned scalar layout, reusing the native graph button/handlers,
not the unsafe raw-coordinate controls in the native template. Numeric buttons
point at session-owned staging scalars. Their callbacks retain point indices,
selection and the local edit generation; an intervening insertion/removal/reset
rejects stale numeric writes. Recompute the working evaluator after valid edits.
Clipping controls are inline in the dialog, with one staged rectangle validated
before applying it to the working mapping. The graph never sees an invalid
rectangle. Invalid candidates remain uncommitted and show a useful error.

Presentation edits (selection, view, zoom) only affect the session. Keep cm[0]
selected for every preset; reject RGB/HSV/levels/tone template options.
Guard point insertion at the signed-short limit before native insertion.
Before native graph paste, validate a candidate against the scalar codec; reject
wrapping/RGB data without changing the working graph. The graph's native event
handler must only mutate the session; no saved owned state is exposed directly.

Disable undo flags for all dialog graph/numeric/preset controls. Do not call
native tool-menu callbacks that manually push undo. The operator's successful
execute commits before its single undo push; rejected edits return CANCELLED
without an undo entry. Review must check actual dialog repeat/redo/customdata
ownership and native graph paste/cancel paths, rather than inferring those
semantics from operator flags.

## Acceptance

Use headed event simulation and debug-server inspection to test actual pointer
drag, numeric edits, clipping, preset and copy/paste controls. Capture visual
evidence. Check Apply/Cancel/Escape/outside dismissal, undo/redo, and first
initialization undo. Open an editor while its item moves, grows, disappears,
its declaration is removed, its owner is deleted, or another edit changes its
revision. Never overwrite a newer curve or touch replacement storage.

Repeated unset root-path drawing must leave all saved property presence and
dirty state unchanged. Test concurrent views of one mapping. Repeat the real
external asset .375/.75/.375 Save/Revert test after editor changes, plus native
curve regression and existing headed SculptCore stroke cancellation tests.
Only then remove the temporary owned-template guard and complete the Plan 2
editor gate. API capability/revision documentation and full lifecycle evidence
remain part of the parent gate.

## Review corrections and concrete implementation sequence

1. Add runtime path watch tokens, separate from definition records. Capture
   owner/session, all declaration tokens, each existing group/array on the
   path, and root-storage presence. Invalidate watches on property/tree/owner
   destruction, content replacement, array resize/set-index, RNA collection
   move, and parent group add/remove. An unset action conservatively rejects
   intervening structural changes; existing definition edits still tolerate
   collection movement. Temporary codec allocations must not expire unrelated
   watches. Test identical empty items, nested relocation and equal-content
   replacement, not merely different values.
2. Implement a separate read-only inspector that continues through declaration
   metadata when pointer ancestors are absent. Never call generic getters on
   null-data PropertyGroups; absent collection elements are still errors.
   Transactions retain the begin-time revision independently of refreshing RNA
   handles. Owner free/swap and definition invalidation reject edits; an
   unrelated undo preserving the same owner and definition need not reject.
3. Hand a captured session to operator invoke with a scoped, opaque, one-use
   ticket. Remove ticket registration when synchronous invoke returns. Repeat
   without a live session rejects, including first initialization; stored paths
   never reconstruct authorization. Poll only checks general context. Execute
   owns RAII cleanup on success and rejection; cancel also destroys customdata.
   Blender does not free that customdata for us. Standard dialog closes before
   execute, so invalid Apply reports an error after closure without committing.
4. Graph Escape/right-click during a drag explicitly cancels the owned session;
   the native handler currently swallows those events. Check both insertion
   paths before reaching the signed-short point count limit. Validate the
   clipboard source before native channel conversion; RGB source rejection
   cannot rely on validating its converted scalar result. Preserve a stable
   working mapping address, force channel zero and validate/reset view bounds.
5. Freeze staging and numeric selection/generation bindings throughout an
   active interaction. Active-button transfer replaces callbacks, so each
   redraw must not authorize a new target. Include sorting, duplicate removal,
   selection and paste in generation changes. Prefer stable per-interaction
   bindings or identity rejection across generation changes. All inner controls
   disable undo; only successful Apply/initialization gets an operator undo step.
6. Commit validates attachment/declarations, commits with the original revision,
   notifies, and invokes callback once. After callback, inspect only retained
   result/session data: owner, declaration or item may have been deleted.

The first implementation slice is the native path guards and RNA editor
transaction/inspection interface. The actual dialog and headed interaction
gate follow; no partial slice completes Plan 2.

### Implementation review corrections

- Array structural changes invalidate every descendant path watch before
  inline addresses move. Otherwise stale keys can alias unrelated worker-side
  temporary allocations. This does not invalidate existing definition records.
- Every captured path includes an owner watch, including absent storage roots.
  Validate tokens before touching the saved owner address. This also supports
  embedded IDs (Material node trees and Scene master collections), whose
  free/swap paths reach the common owner hooks but which do not appear in
  Main's ID lists. Nonembedded no-Main temporaries are rejected by the editor.
- Launch buttons own their captured target through copyable/freeable func_argN
  data and compare declaration/watch/binding authority across redraws. Allowing
  Blender's normal callback transfer to refresh a stale target would defeat
  the path guard. Both editor reviewers checked this correction.
- Owned graph Escape explicitly sets the containing popup's cancel result;
  ending a modal button and returning CONTINUE does not reprocess that event.
- Numeric edits keep their interaction binding across their own successful
  writes, updating index/generation and clamped coordinates. External selection
  or generation changes still reject stale writes. Point limits are finite
  float limits; clipping retains the schema/native RNA bounds [-100,100].
- Extrapolation uses CurveMapping.flag. Paste synchronizes staged clipping and
  toggle values. A rejected staged clipping rectangle blocks Apply.
- Dialog action buttons require explicit identities too, not only launch
  buttons. The native default matcher does not distinguish capturing lambdas
  or labels, so added/removed point rows can match unrelated actions. UI and
  identity reviewers checked the bounded correction: a typed func_argN payload
  with shared session/numeric target, canonical action kind/parameter, callable,
  typed copy/free and a named dispatcher. Compare that identity across redraws;
  queued handle/Remove actions also reject a replaced numeric target. This
  closes a concrete matching weakness; the headed removal failure still needs
  verification before attributing its cause to that weakness.
