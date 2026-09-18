# Plan 2: native owned-curve runtime core

Status: native core subgate passed, 2026-09-15. Eight runtime and six codec
tests passed through registered CTest; rebuilt Blender background/headed
regressions passed. See [evidence](../codebase/generic-brush-plan2-evidence.md).
This replaces the unsafe registry/snapshot assumptions in the earlier draft.
RNA and editor integration follow this core; no Python capability is advertised
until the guarded API is implemented.

## Concrete implementation

* Add `BKE_curvemapping_owned.hh` / `intern/curvemapping_owned.cc`. A registry
  maps heap-stable definition-group addresses to shared runtime records. A
  definition must be a list child of a group in the owner's current custom or
  system-property tree; reject root groups and inline IDP_IDPARRAY elements.
  Attachment search descends arrays without retaining their movable addresses.
* Records retain owner/definition identity, revision starting at one, a canonical
  definition copy and a fully evaluated immutable CurveMapping snapshot. A
  snapshot owns its full mapping and point arrays independently of the record.
  Old snapshots can be evaluated after edits or owner deletion, but cannot be
  used to commit through an invalid record. Native mapping pointers remain private:
  even a const CurveMapping exposes writable point arrays. Expose guarded evaluation
  and an explicit deep-copy method for editors.
* Use exact structural definition comparison (including string/array subtype
  and floating-point bits, excluding presentation/UI metadata). Do not rely on
  IDP_EqualsProperties for this: scalar NaNs in opaque extensions compare unequal
  to themselves and its string comparison ignores subtype. Groups compare by key,
  arrays by position, strings by full bytes including embedded NUL. Exclude links,
  allocation capacity, children maps, flags and UI metadata from evaluator identity.
* Lookup, attachment checks, sync and commit are main-thread operations. Immutable
  snapshot evaluation is independent of owner storage and may run on workers.
  Registered original owners may only be mutated, detached, swapped or freed on
  the main thread (assert in matching hooks); reject evaluated/COW acquisition.
  Any-thread hooks support unregistered temporary/COW frees. They do not purport
  to serialize concurrent destruction of registered originals. Registry removal
  retains records locally and releases them after map mutations and unlocking.
  A shutdown-disabled registry pointer prevents destructor reentry into its map.
* Invalidate a definition at entry to `idp_free_property_content_recurse`, and
  invalidate the destination before `IDP_CopyPropertyContent` swaps contents.
  Invalidate removed subtrees before `IDP_RemoveFromGroup`, including detach and
  reattach without an intervening read. Invalidate all records for an ID at `BKE_libblock_free_data` entry and both
  IDs at `id_swap` entry. Expose explicit all-record invalidation for later
  read/undo/declaration teardown integration. Invalid records clear raw owner
  and definition pointers and never become valid again.
* Every record operation first checks attachment while owner identity is still
  live. Read detects changed raw definitions and asks for explicit sync instead
  of returning a stale evaluator. Sync fully validates current raw storage,
  then publishes a new snapshot/revision only if definitions differ. Invalid
  raw data is left unchanged and cannot be overwritten by a stale edit. Sync and
  commit require ID_IS_EDITABLE and reject all library overrides until the RNA
  declaration-aware override policy exists; editable linked assets remain allowed.
* Commit accepts an expected revision and a candidate native mapping. Check
  attachment, editability, revision and unchanged raw backing data first.
  Encode/validate/materialize all temporary data before touching saved storage.
  Preserve unknown root extensions and root flags. Identical definitions return
  Unchanged without revision advancement. On success, temporarily remove the
  root from the registry, replace contents at its existing address, then publish
  the prepared snapshot and reinsert the same record. Only this internal atomic
  commit suppresses root invalidation; freeing replaced children still runs all
  ordinary invalidation hooks. No callbacks run while registry state is hidden.
* Return Changed, Unchanged, Stale, Invalid or ReadOnly with an error string.
  Essential owner/declaration notifications belong in the RNA transaction layer
  after Changed (and after successful explicit sync, whose raw edits may predate
  first acquisition); this core never calls Python or chooses an active brush.
  Rejected changes preserve saved data, snapshot identity and revision.
* Snapshot evaluation rejects non-finite inputs/results. Move the native table
  index integer conversion after its range check so finite extreme extrapolation
  cannot cause an overflowing integer conversion. Match native RNA's unclipped
  scalar evaluation; downstream property conversion owns its final value clamp.

## Adversarial review disposition

Two fresh-context reviewers, `review_runtime_core_lifecycle_v2` and
`review_runtime_core_transactions_v2`, inspected native implementations. Accepted
all findings: main-thread lifetime restriction, opaque snapshots, detach hooks,
two-phase registry teardown, sync editability, guarded evaluation and fully
specified structural comparison. Tests include immutable-copy isolation, extreme
queries, reordered keys/opaque bit patterns, detach/reinsert, cache identity and
payload preservation for rejected transactions. Core support deliberately rejects
overrides until declaration-specific RNA checks are available.

Implementation review also caught quadratic free/tree hook overhead and a
duplicate native index declaration from the installation helper. Exact frees
now use keyed lookup; subtree invalidation traverses once. The duplicate was
removed before the successful build. The reviews found no other concrete core
lifetime/transaction defect under the main-thread owner restriction.

## RNA/editor integration decisions carried forward

Mapping/channel handles must resolve the current record snapshot at operation
entry so `point.location = ...; mapping.update()` remains valid. Point/iterator
handles retain a full generation and raise on generation mismatch; native
arrays never reallocate underneath them. Explicit owned RNA callbacks,
full PointerRNA function parameters/results, mathutils and bulk guards remain
required. Bulk owned writes will initially raise rather than using raw-array
fallback. Persistent editor sessions retain separate editable mapping copies
and stable scalar staging fields; they commit with an expected revision.
Root-ID/path initialization and drawing handle entirely absent parent groups.
These integration changes remain subject to the full Plan 2 lifecycle gate.

## Native acceptance tests for this slice

* Two owners/copies have independent records and snapshots; rejected mismatched
  owner and inline definition attachment does not create a record.
* Commit publishes a new evaluator while a retained old snapshot stays intact;
  mapping record identity stays stable and revision advances exactly once.
  Equal candidate, invalid finite-evaluator candidate, stale revision, read-only
  owner and raw-storage conflicts leave saved data and revision unchanged.
* Explicit sync publishes valid raw changes, rejects invalid ones without data
  deletion, handles opaque NaN extension values and string subtype differences.
* Collection growth and item move preserve attachment, while item deletion,
  content copy/reset, owner swap, owner deletion and explicit invalidation make
  old records permanently invalid. Reacquiring reused addresses creates fresh
  records. Evaluate retained snapshots after every destructive case.
* Run registered CTest against the real native implementation, then rebuild
  Blender and rerun existing background/headed regressions. This is a core
  subgate, not permission to check Plan 2 complete.
