# Plan 4: explicit authoring undo boundary

Implemented and verified, 2026-09-17. The original candidate below is superseded
where indicated by the scoped reviews. [Final evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
This closes the reopened
Plan 2 Brush undo gate as well as Plan 4 native owner undo. No global change to
Brush NO_MEMFILE_UNDO or Scene tool-settings preservation.

## Native scope and transaction

Add an engine-agnostic explicit `ID.authoring_edit_begin()` / commit / cancel
boundary for editable original Brush and Scene IDs. Use an opaque native token,
main thread only, tied to owner session UID, current Main/lifecycle and original
declaration/record lifetime when entered by an owned curve widget. Tokens are
single-use, cannot be shared across owners, and cannot span load/undo/redo or
external asset replacement. Nested scopes on the same ID are rejected. Python
tokens have deterministic free cleanup; no auto-commit on GC.

The initial Brush snapshot uses existing `BKE_id_copy_ex` into a no-Main,
no-user-refcount copy. It already deep-copies all native Brush curves, cavity
settings, custom properties and system properties. Capture authoring payload,
not the original ID header (name/session UID/library/asset metadata identity).
Restoration clones the saved snapshot and uses `BKE_lib_id_swap` (partial ID),
which already retires owned-curve runtime handles. Preserve original ID identity
and current asset identity; notify and dirty the actual owner. Exact native
pixel/world size pairs restore via raw snapshot data, avoiding rescaling setters.

Scene snapshots cover only custom/system IDProperties and sculpt Paint's
UnifiedPaintSettings plus MeshAutomaskingSettings (deep-copy their mappings).
Do not snapshot/swap the entire Scene, active Brush pointers, mode/session data,
objects, other paint modes or unrelated ToolSettings. Preserve absent sculpt/
automasking state without allocating on capture; restoring an originally absent
block needs an explicit implementation rule that does not destroy live Paint
state. Prefer rejecting unsupported absent native blocks while still allowing
generic Scene authoring; keep this capability visible.

Snapshot copies never hold untracked raw ID references. Enumerate all ID links
(Brush native links and IDProperties) into stable UndoRefID records using the
normal library foreach-ID machinery; copy flags avoid user refcount mutation.
Before restore, remap copied links from current UndoRefIDs; clone into actual
owner data with balanced reference counts. Snapshot free uses no-refcount free.
Owner and referenced IDs go through undo's foreach_ID_ref. Deleted owners must
not be resurrected by this API; missing targets fail closed. Test texture/ID
references explicitly rather than assuming all generic payloads are scalars.

Commit captures after state and publishes one before/after undo step. Cancel
restores before state without pushing; invalid/stale tokens never restore.
Record only semantic changes, excluding cache pointers/selection/runtime tables
and snapshot allocation differences. Snapshot memory accounting must include all
deep-owned data so undo memory limits work. Keep captured data bounded or use
existing ID memory-size accounting; do not silently report sizeof(Brush).

## Undo-system integration

New explicit-only UndoType (`poll=nullptr`) uses
UNDOTYPE_FLAG_DECODE_ACTIVE_STEP and direction/is_final/is_applied semantics
analogous to delta undo. Store before/after snapshots, owner UndoRefID and full
reference remapping. It must unapply the step left when crossing to a memfile
or another undo type, and reapply when entering on redo. Ordinary global pushes
remain unchanged. Ensure a valid initial memfile baseline before first push;
never overwrite an existing pending step. Tests determine precise hidden-memfile
interleave flags against actual BKE undo control flow before accepting the type.

Lifetime invalidation must also cover the explicit cancel/restore path, so addon
OwnerGuards and native mapping wrappers cannot survive swapped data accidentally.
No Python callback is used to restore native snapshots. Undo remains safe after
addon unregister or missing DLL.

## Addon and curve-editor integration

An addon context manager wraps effective-owner authoring edits, groups a modal
gesture, cancels on exceptions and exposes exact restoration for size. Direct
low-level setters keep their current explicit no-auto-undo contract; UI/operator
consumers use the authoring boundary. Automatic background migration never pushes
interactive undo. New row/widget consumers arrive in Plan 7.

Owned curve template edits already have their own native edit transaction.
Capture the appropriate owner authoring state at interaction start and publish
the explicit authoring undo step on commit (including first initialization,
points, reset/view actions where semantic). Avoid a duplicate memfile step from
the generic button path. UI view-only changes remain non-authoring. An edit
rejected by stale owner/declaration/revision commits neither snapshot nor undo.
Keep native stock curve widgets unchanged unless they explicitly opt into this
boundary through addon UI later.

## Gate

Headed actual undo/redo on Brush generic scalar, stack metadata, positions,
custom curve creation/edit/removal; native strength/pressure flags/curve; exact
paired size + mode; and Scene UPS/cavity plus generic metadata. Verify dormant
data, inactive actual-owner dirty state, two owners/windows/scenes, no-op and
cancel grouping, rejected stale token, and unknown IDProperty/ID-link payloads.
Interleave authoring with object memfile and custom sculpt undo, rename/delete,
asset switch/Revert, redo branch truncation, history limits, addon unregister
and missing engine. Confirm ordinary sculpt/asset lifecycle behavior unchanged.
No completion claim based solely on Scene memfile tests or pure mocks.

## Review corrections and bounded implementation refinement

The fresh native-lifetime and undo-system reviews found the full-Brush snapshot
too broad for this property API: existing Brush copy aliases gradient storage,
includes preview/dirty/runtime state, and expands equality/accounting into every
unrelated Brush subsystem. The implementation will instead capture explicit
property-authoring scopes; this supersedes the full-Brush copy/swap candidate:

- Always capture custom/system IDProperty trees, preserving unknown entries,
  order, flags, UI metadata and ID references. Bound depth/count/bytes before
  copying. Use detached no-user-count clones; record ID leaf targets by session
  UID, type and null/non-null state. Set detached pointers null. Resolve every
  reference into temporary clones before touching live trees; missing non-null
  refs reject an explicit cancel/commit restore and skip an undo restore with a
  diagnostic. Never accept a same-name replacement. Restore balances actual ID
  reference user counts; snapshot disposal changes no users.
- `native_settings=False` captures only those trees on either Brush/Scene.
  Opt-in native scope captures a finite engine-agnostic native brush-settings
  block (size pair/mode, strength, spacing, plane offset, crease pinch, hardness,
  autosmooth, color/cursor color, Brush type/direction/stroke/falloff policies and
  pressure/native unified flags) and its strength/size/distance mappings plus
  cavity block. Scene native scope captures sculpt UPS and cavity only. This is
  an explicit v1 scope; textures, paint curves, gradients, other modes and Brush
  identity are untouched. It is not general arbitrary Brush/operator undo.
- Raw size pairs and cavity flags restore directly, without rescaling or
  mutually-exclusive RNA setter side effects. Native cavity curve copies use
  BKE_curvemapping_copy. Reject a requested missing native Paint/cavity block at
  begin; generic-only scope still works. No snapshot creates a native block.
- Canonical equality compares scalar block fields individually; curve clip,
  tone, black/white, eval flags, per-channel handle defaults and point x/y/handle
  bits (ignoring selection, view, timestamps and tables). IDProperty equality is
  explicit recursive ordered comparison including full UI metadata and flags,
  ID identities, recursive property/group arrays and raw bytes. Do not use
  IDP_EqualsProperties alone. Memory accounting walks all actual cloned
  allocations including UI defaults/enums and CurveMapping points/tables; add
  sidecar/vector storage and enforce a bounded total snapshot size.
- Tokens remain completely outside UndoStack until changed commit; no-op/cancel
  cannot truncate redo or erase pending step_init. Preflight commit before push,
  reject active pending undo initialization, and preserve no-op redo history.
- Each changed authoring step sets `use_memfile_step=true`: its explicit native
  step is skipped and a post-state memfile is the visible history entry. This
  gives every authoring step a complete accumulated Scene generic state. Native
  step decode always restores BEFORE on STEP_UNDO and AFTER on STEP_REDO,
  independent of is_final/is_applied. Post memfile handles ordinary Scene data;
  native step handles Brush and preserved Scene settings. Test history jumps
  and two different Scene owners between foreign memfile steps explicitly.
- UndoRefID remains a compatibility enumeration hook, not authority. Resolve
  owner/references by captured session UID via BKE_libblock_find_session_uid;
  missing/deleted/Reverted owner is skipped rather than redirected by name.
- Remove OPTYPE_UNDO from UI_OT_owned_curve_edit when it commits the explicit
  authoring step; its buttons already clear BUT_UNDO. Keep first-init/edit/reset
  behavior grouped once. View-only operations never push.
- Main/load/undo lifetime guards plus captured owner UID reject stale tokens.
  Explicit restore increments a process-local per-owner authoring revision and
  retires native owned-curve handles. OwnerGuard checks this revision in addition
  to existing pre/post handler generation. No Python callbacks restore snapshots.

This refinement requires another fresh review before implementation. Required
gates now assert excluded gradient/texture/preview state stays unchanged rather
than claiming to snapshot it. ID references inside the captured IDProperty trees
remain fully supported and tested.

### Scoped review disposition (2026-09-17)

Fresh native-lifetime and undo-traversal reviewers accepted the bounded design
with the following corrections, now required for implementation:

- Capture selected UPS fields, never the whole struct: exclude weight, input
  samples, color jitter and its three owned mappings. UPS flag mask is only
  UNIFIED_PAINT_BRUSH_LOCK_SIZE plus legacy SIZE/ALPHA/COLOR enable bits used by
  the agreed LEGACY_SCENE policy. Brush unified mask covers SIZE/ALPHA/COLOR.
- Brush flag mask covers ALPHA_PRESSURE, SIZE_PRESSURE, SPACING_PRESSURE,
  DIR_IN, ACCUMULATE, OFFSET_PRESSURE, SPACE_ATTEN, LOCK_SIZE, SMOOTH_PRESSURE.
  Cavity mask covers CAVITY_NORMAL/INVERTED/USE_CURVE. Merge each mask into the
  current flag word; excluded settings must survive cancel and undo.
- Count group lookup objects and children.size_in_bytes() in addition to
  property nodes, data buffers, UI metadata and snapshot sidecars. Conservative
  double-counting inline capacity is acceptable; undercounting is not.
- An empty undo stack gets its baseline at begin, before any mutation. Existing
  history is untouched by begin/no-op/cancel. Reject pending initialization,
  disabled global undo, incompatible contexts, and nested undo-enabled operators
  before beginning an interactive undo transaction.
- Every operator adopting explicit commit must omit UNDO and UNDO_GROUPED,
  including future addon operators. The native curve operator does so now.
- Keep rollback-only transactions available without interactive undo (explicit
  undo=False), for background atomic multi-setting adapters. Such transactions
  never initialize/push the undo stack. This shares snapshot/lifetime rules.

The paired hidden native + visible post-memfile traversal was verified against
undo_system.cc by both fresh reviews. Runtime gates remain mandatory.
