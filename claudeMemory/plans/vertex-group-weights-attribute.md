# Plan — vertex-group weights as a custom engine attribute type

Give the SculptCore engine first-class ownership of Blender vertex-group
weights, as a **sparse attribute column** (`AttrType::WEIGHTS`: a 32-bit index
into a mesh-owned, interned, refcounted pool of struct-of-arrays weight runs)
with a **`AttrMerge::CUSTOM` interpolator**, plus the Blender-fork bulk
accessor and addon bridging needed to round-trip it.

## Why

1. **It fixes silent data loss.** `convert.py`'s topology-rebuild flush calls
   `mesh.clear_geometry()` (`sculptcore_addon/convert.py:658`), which destroys
   both the weights and — on Blender 4.x+, where the names live on the mesh
   (`DNA_mesh_types.h:196 vertex_group_names`) — the group names themselves.
   Dyntopo is a user-facing toggle, so any stroke on a rigged mesh currently
   throws away its skinning. Weights the engine owns survive the rebuild.
2. **It is the engine's first genuinely non-POD attribute**, so it exercises
   `AttrMerge::CUSTOM`, the meshlog's value-copy path, serialization and the
   type-dispatch surface in a way no existing column does.

## Locked decisions

These were settled before the plan and are not open questions:

- **Indices, not pointers.** Three subsystems treat a column as opaque POD:
  `mesh_serialize.cc` (writes `count*elemSize` raw bytes and byte-swaps on
  load), `meshlog_base.h` (`memcpy(..., elemSize)` at lines 217 and 280–282),
  and the GPU/`get_data<T>()` path. A pointer column is unserializable and
  undo-unsafe. A 32-bit index is bit-identical to an `int` under all three.
- **No dense float-per-group baseline.** Not built, not shipped, not used as a
  staging step. Tests compute expected weights arithmetically instead.
- **Thread-safe from the start.** Dyntopo is single-threaded per dab today but
  is explicitly written to anticipate a parallel caller (`dyntopo.h:251`), and
  the meshlog's `parallel_capture.h` already fills rows from multiple threads
  (`meshlog_base.h:238-248`). The pool ships with its concurrency story done.
- **A new `AttrType`, not a repurposed `INT`.** `1 << 11` is free in the enum
  (`attribute_enums.h`). Reusing `INT` makes every generic site — mesh copy,
  mesh join, c-api typed accessors, `state_dump`, the kernel compiler — silently
  succeed while doing the wrong thing (duplicating indices without retaining
  pool slots). A distinct type turns each into an explicit case that is either
  implemented or refuses loudly. That is the whole point of the type.
- **A bulk accessor lands in the Blender fork.** Per-vertex Python over
  `me.vertices[i].groups` is not viable at sculpt densities.

## Ownership model (the crux)

Pool slots are **immutable, interned, and refcounted**. Every index stored in a
mesh attribute column *or* a meshlog column counts as exactly one reference.

Why immutability wins here: sculpt brushes never edit weights in place — the
only writer is split/collapse interpolation, which produces a new value anyway.
So immutability costs nothing in the real workload, and it buys three things:

| operation | with immutable slots |
| --- | --- |
| `MeshLog::cpyFrom` (capture; duplicates an index) | retain — plain atomic increment, safe because the source holds a live reference |
| `MeshLog::swapWith` (undo/redo; exchanges indices) | **no refcount change at all** — the existing raw `memcpy` stays correct verbatim |
| identical weight sets across a region | interned to one slot, so most splits allocate nothing |

Interning also makes the meshlog's memory accounting honest: a captured row
costs 4 bytes plus, usually, zero (a shared slot). Novel slots are accounted in
the pool, reported separately from `elemSize * size_`
(`meshlog_base.h:328`).

**The invariant this rests on: every write to a `WEIGHTS` column goes through a
funnel that releases the old index and retains the new one.** The writers are
enumerable and small: the CUSTOM merge handler, the c-api setter, the
serializer's load path, and the meshlog. Everything else must be structurally
unable to write — which is exactly what the new `AttrType` guarantees, provided
we never hand out `get_data<int>()` for it and `detail::type_dispatch`
(`attribute.h:408`) has no generic fallthrough that reaches it.

### Concurrency

- Sharded intern table (~64 shards, keyed by the hash of the `(group_id,
  weight)` run), each with its own mutex. No lock-free research project.
- Retain from a known-live reference: plain `atomic fetch_add`, no lock.
- **Any transition that can reach zero, and every intern lookup, takes the
  shard lock.** This is what closes the resurrection race (thread A dropping a
  count to 0 while thread B interns the same key).
- A slot reaching zero is *not* freed immediately — it goes on a per-shard dead
  list and can be resurrected by an interning lookup under the same shard lock.
  Reclamation is a **single-threaded sweep at dab end** (a natural safepoint),
  which also evicts the dead entries from the intern table. A slot referenced
  by a live undo step has count ≥ 1 and is therefore never on a dead list.

## Engine work

### E0 — the type and its refusals

`source/mesh/attribute_enums.h`, `attribute_base.h`, `attribute.h`.

- Add `AttrType::WEIGHTS = 1 << 11`, `elemSize` 4. Audit for any all-types mask
  constant that needs widening, and for the `litestl::binding::Binder<AttrType>`
  specialization in the same header.
- `type_to_attrtype<T>()` (`attribute_base.h`) and `detail::type_dispatch`
  (`attribute.h:408`) get an explicit case.
- Flags: **never `TOPO`** — it looks like a topology index but the serializer
  would remap it against the vert/edge/face tables. Never `NOINTERP` (that
  bypasses the merge handler, `attr_interp.h:240`). `AttrUse::DEFORM_WEIGHTS`
  added as the semantic tag.
- Make the sites that cannot handle it refuse *explicitly*, not silently.
  **Landed** — but the survey found only one site that needed new code, because
  most of the paths already refuse everything they don't recognize:
  - `source/mesh/c-api/mesh_c_api.cc` — **the one real hole, and it is fixed.**
    `Mesh_writeAttr` is the generic "seed every user layer" entry the addon
    calls per layer; on a WEIGHTS column it would have stored caller-supplied
    pool indices with no reference taken, so the pool would free runs the column
    still names. `Mesh_readAttr` would have exported indices that mean nothing
    outside the mesh. Both now return 0 for WEIGHTS; E6's `sc_mesh_weights_*`
    is the only way in or out. `Mesh::addAttr` is deliberately *not* refused —
    a WEIGHTS column with no group names is inert (every element is slot 0).
  - `SpatialTree::fill_leaf_attr` (`spatial_gpu.cc:201`) already gathers only
    the float family and default-fills anything else, `external_draw.cc` names
    its two `srcType`s literally, and `mesh_drawbatch.cc` never enumerates
    types — so the GPU path refuses WEIGHTS with no change. A weight overlay,
    if ever wanted, is a `DERIVED` FLOAT column for the active group; still out
    of scope.
  - `sbrushc` needs no reject: `emit_cpp.cc:905-923` maps only the DSL's own
    types (float, vec2/3/4, int, bool), so an `attr` declaration *cannot name*
    this type. Structural, not enforced — worth re-checking if the DSL ever
    grows a type-passthrough.
  - `source/debug/state_dump.cc` ends its attr-fingerprint switches in
    `default: continue`, so WEIGHTS is skipped and no golden churns. Printing
    the resolved run belongs with E7's `assert_weights` verb, not here.
- `mesh_serialize.cc`'s `scalarSize()` already returns 4 by default, which is
  right for a 32-bit slot index.

### E1 — the pool

New: `source/mesh/deform_pool.{h,cc}`. **Landed**, with the storage layout
settled differently than sketched here:

- Storage is an **AoS arena of `DeformWeight {int group; float weight;}`** per
  shard, not the parallel `Vector<int>`/`Vector<float>` pair. A run is read as a
  contiguous span and hashed as one byte range; splitting it across two arenas
  would double the indexing and buy nothing, since a run is 8–32 bytes and is
  always touched whole.
- A slot is `(start, count, refs, hash, next_hash)`; slot 0 is the canonical
  empty run, immortal, so an unset vertex is index 0 rather than a sentinel.
- **No size-class free lists.** Reclamation is `sweep()` compacting each dirty
  shard's arena in slot order — which is O(live) with no fragmentation at all,
  where size classes would have been O(1) with some. Slot *table* entries are
  reused (a swept slot becomes an empty reusable row); only arena offsets move,
  so local slot indices are stable and columns never learn about a sweep.
- Concurrency: 64 shards keyed by `slot_index & 63`, one `std::mutex` each,
  every read and write under it. Refcounts are plain `uint32_t`, not atomics —
  `util::Vector` reallocates, so a lock-free read is unsafe anyway, and
  `std::atomic` is not movable so it cannot live in a `Vector` element. The
  header documents the upgrade path (chunked never-reallocating storage +
  atomic refcounts) for when a shard lock shows up in a profile.
- Releasing to zero does **not** free: the slot stays interned on the shard's
  dead list, and `intern()` of an equal run resurrects it in place. Both
  transitions hold the same shard lock, which is what closes the
  resurrection race.
- `copyRun()` returns a copy into the caller's buffer, never a span — interning
  may reallocate a shard arena, so no pointer into one may outlive the call.
- `Vector<string> group_names` on the pool: a slot's `group` indexes it, and
  it is ordered to match Blender's `mesh->vertex_group_names` so the mapping is
  identity while the lists agree. Reconciliation by name is the addon's job.
- **Refcount audit** (`auditRefcounts(roots)`): recompute every refcount from a
  caller-supplied list of every reference held, report the count that disagree.
  This is the test that catches a missed funnel; E2/E3 supply the roots by
  walking the mesh and meshlog columns.
- `tests/test_deform_attr.cc` covers canonicalization (unsorted / duplicated /
  zero-padded spellings all intern to one slot), the immortal empty slot,
  undersized `copyRun`, refcount lifetime and resurrection, sweep leaving slot
  indices intact and the intern table still deduping, the audit failing when a
  root is missing, pool copy/assign preserving indices, and two threaded
  stresses (8-way concurrent intern of overlapping runs, and intern racing
  release-to-zero on the same run).

### E2 — attribute integration

New: `source/mesh/attr_weights.{h,cc}`. **Landed**, and the sketch below it was
wrong in three places — the corrected shape:

- **No `AttrDataBase` subclass.** The column is a plain
  `AttrData<WeightSlot>`, because a subclass could never have been invoked:
  `AttrGroup`'s generic paths `static_cast<AttrData<T> *>(attr.data)` and then
  call *non-virtual* members (`set_default`, `resize`, `operator[]`). Reference
  discipline therefore lives at `AttrGroup` level, keyed on
  `attr.type == AttrType::WEIGHTS`. Keeping the column dumb is also what lets
  reorder, swap, resize, serialization and the meshlog's raw byte copies keep
  working untouched.
- **Pool ownership**: one lazily-created `DeformPool` per mesh, held by
  `MeshBase` through a member reference and reached by `MeshBase::deformPool()`
  / `deformPoolOrNull()`. `deformPool()` stamps a non-owning
  `AttrGroup::deform_pool` back-pointer onto all five element groups. It is a
  *member* rather than a raw pointer plus a `~MeshBase` body because a base
  destructor body runs *before* its base members are destroyed — the pool would
  have died before the `AttrGroup`s that release into it. It is declared first,
  so it destructs last. (E2 landed this as a sole-owner `DeformPoolOwner`; E3
  replaced it with the shared `DeformPoolUser` below, for reasons E2 had no way
  to see.)
- **The four dropping paths**, each now releasing (and zeroing, so nothing can
  be released twice) via `detail::weightsReleaseElem` / `weightsReleaseFrom`
  (declared in `attribute.h`, defined in `attr_weights.cc` so that
  `attribute.h` — included everywhere — never has to see `DeformPool`):
  `~AttrGroup`, `remove_attr`, `set_default` and `shrink_capacity`.
  `set_default` is the subtle one: `ElemData::release(elem)` does not touch
  attrs, so a freed element's column entry keeps its slot *and its reference*
  until the element is reallocated. No double release, no leak.
- **`AttrGroup::ensure` did need a change** — a `util::Assert` that a WEIGHTS
  column is not created before the group has a `deform_pool`.
- **The write funnel** is `WeightsRef` (`attr_weights.h`), constructed from
  `(AttrGroup &, AttrRef &)` and obtained via `ensureVertWeights(mesh, name)` /
  `findVertWeights(mesh, name)`. `setSlot` materializes then goes through
  `DeformPool::reassign` (retain new, release old); `setRun` interns, stores,
  and drops `intern`'s reference. Reads copy out (`getRun`), never span into a
  shard arena. `collectRoots` walks every materialized page — free elements
  included — to feed `auditRefcounts`.
- **`resolveMergePolicy` also needed a change**, which the sketch missed
  entirely: its name-keyed path early-returns for names without a dot prefix,
  so a user-facing `"weights"` layer would have fallen through to
  `defaultMerge`, whose final `else` plainly copies src0's *slot index* into
  dst with no retain — an under-count, which is fatal once `sweep()` runs. The
  branch is now type-keyed (`type == AttrType::WEIGHTS` → `{CUSTOM,
  mergeWeights}`) ahead of everything else. `mergeWeights` is interim: it
  carries src0's run forward *with* a reference. E4 replaces the value rule;
  the registration is already correct.
- `tests/test_weights_attr.cc` covers pool ownership and idempotence, read /
  write / canonicalization, interning collapse across a whole mesh, overwrite
  releasing the old run (and a same-value write not double-counting),
  kill/make element reuse being reference-neutral, `remove_attr` dropping every
  reference, the CUSTOM handler surviving an `splitEdge`, and teardown ordering
  (which `test_end()`'s leak check enforces).

### E3 — meshlog integration

`source/meshlog/meshlog_base.h`, plus `mesh/deform_pool.{h,cc}` and
`mesh/mesh_types.{h,cc}`. **Landed.** The sketch below it assumed one row store
and plain mesh ownership of the pool; both were wrong.

- **The log holds a *user* of the pool, not a borrow.** `~Scene()`
  (`source/debug/scene.cc:51`) does `alloc::Delete(mesh)` in its destructor
  *body*, while `meshLog` is a member destroyed *after* that body. A
  mesh-owned pool would therefore be gone before the log chunks that release
  into it. `DeformPool` gained an intrusive `std::atomic<int> users_`
  (`addUser`/`removeUser`, acq_rel on the decrement so every prior `release()`
  on any thread happens-before the delete) and `DeformPoolUser` — a
  move-free, non-copyable strong reference whose `reset()` is idempotent. The
  mesh, each `ChunkElemData`, each `RowLayout`, and `MeshLog` itself each hold
  one; the last one out deletes. `deformPool()` installs its pointer directly
  rather than through `reset()`, since `New<>` already starts the count at one.
- **There are two independent row stores, not one**, and WEIGHTS flows through
  both:
  - `detail::ChunkElemData` — an `AttrGroup`-backed store (brush capture,
    declared attrs only). Its `AttrGroup` gets the mesh's pool via a new
    `bindPool()`, called from `ensureAttr(src, ref)`: `AttrGroup::ensure`
    asserts on the pool, and the copied rows are raw slot indices only
    resolvable against that one pool. Bound once — re-pointing would strand the
    references already-captured rows hold. Release comes free from `~AttrGroup`
    (E2), which is why `pool_user` is declared *first* in the struct: it
    destructs last, after the group that releases into it.
  - `detail::ChunkElemRow` + `detail::RowLayout` — a raw byte blob for
    `LogChunkTopo`, capturing **every** attribute of the group. It has no type
    information at row-destruction time, so `RowLayout` now carries
    `weight_cells` (byte offsets of the WEIGHTS cells, empty on the
    overwhelmingly common weightless mesh) and its own `DeformPoolUser`.
- **The verbs, by what they do to a cell:**
  - *duplicate* → retain: `ChunkElemData::cpyFrom` (reassigns into a
    materialized dst cell instead of memcpy'ing), `ChunkElemRow::captureFrom`
    (releases first — a pooled row still names the previous element's runs —
    then retains).
  - *overwrite* → reassign: `ChunkElemRow::writeTo` and `refreshDataColumns`.
  - *swap* → **nothing**, in both stores. Slots are interned and immutable, so
    the two sides exchange indices and each reference simply moves with it.
    `char buf[64]` is ample for a 4-byte element.
  - *drop* → release: `~ChunkElemRow` (covering both `dropRecord`'s
    release-to-pool and pool teardown, since `util::Pool::release` runs the
    destructor), and `~AttrGroup` for the other store.
- **Destruction order, again.** `~LogChunkTopo` deletes its `layouts_` in the
  body, but `bodies_pool` / `records_pool` are members destroyed *after* the
  body — a `~ChunkElemRow` reading `layout_->pool` would use-after-free. Both
  pools are now cleared explicitly at the top of that body.
- **Memory accounting**: `MeshLog::totalMemSize()` adds a single
  `deformPoolMemSize()` term rather than folding pool bytes into each chunk's
  `elemSize * rows` — a WEIGHTS cell is a 4-byte index into one shared table
  that every step and the mesh point into. `MeshLog::setActiveMesh` picks the
  pool up (`deformPoolOrNull` — never creates one, so a weightless mesh does
  not grow a pool because it was logged) and holds it so the size is still
  answerable after the mesh is gone.
- **Thread safety confirmed, not assumed**: `parallel_capture`'s workers reach
  `cpyFrom`, and `retain` / `release` / `reassign` all take the owning shard's
  mutex. Nothing new was needed.
- **Undo state is not serialized** — verified: `source/meshlog/` has runtime
  reflection bindings only (`defineBindings`, no `loadSTRUCT`/`saveSTRUCT`, no
  file writer), and no caller persists a `MeshLog`. So E5's save-time
  compaction only has to consider live mesh columns. Were that to change, the
  log's rows would need remapping too.
- `tests/test_weights_undo.cc` covers all four: a `ChunkElemData` row keeping a
  run alive across a `sweep()` after the mesh has overwritten it (and giving it
  back at teardown); a `LogChunkTopo` kill/undo/redo/undo round trip restoring
  the run *from the log* (the mesh's stale column entry is explicitly cleared
  first, so a passing assert cannot be reading it); dropping the log making the
  run reclaimable; and the lifetime case itself — `alloc::Delete` the mesh with
  a live `MeshLog`, then delete the log, with `test_end()`'s leak check proving
  the pool was freed exactly once.

### E4 — the merge handler

`source/mesh/attr_merge.cc`. **Landed**, replacing E2's interim carry-src0 rule;
the registration (type-keyed in `resolveMergePolicy`, not name-keyed — see E2)
was already correct and did not change.

`AttrMergeCtx` already carried everything needed (`grp->deform_pool`, `src0`,
`src1`, `t`), so there was no ABI change to the context.

- **Value rule**: union the two sparse runs — both are canonicalized
  group-ascending, so it is one merge walk — with `lerp(w0, w1, ctx.t)` and a
  group absent from one side weighing **0** there, not "unchanged". Then drop
  sub-epsilon entries, cap the influence count, intern, and `reassign` the
  result in (releasing `intern`'s own reference).
- **Not normalized**, deliberately. Blender does not renormalize on
  interpolation, and a sculpt operation silently rescaling a rigged mesh's
  weights would be a worse bug than the one this fixes. The
  `testMergeInterpolates` case sums to 1.5 precisely to pin that.
- **Endpoint fast paths**: `src0 == src1` (a collapse), `t <= 0` or `t >= 1`
  take the existing interned run whole and skip the intern entirely. This is
  both the common case and what makes a collapse exactly a copy.
- **Two growth bounds**, because interpolation is transitive — a dyntopo region
  resplit repeatedly feeds every merge its own output:
  - `WEIGHT_MERGE_EPSILON` (1e-5f, the smallest weight a 16-bit UI slider can
    express) drops noise entries, or a run accumulates groups it can never lose,
    one denormal at a time, until it starts evicting real influences.
  - the cap at `DEFORM_MAX_INFLUENCES` keeps the **strongest** entries, by
    magnitude rather than value (weights are not required to be positive). It
    sorts by magnitude and truncates without re-sorting, since `intern()`
    canonicalizes back to group order anyway.
- This is the engine's **first merge handler that allocates** — `intern()` takes
  a shard lock — which is why the pool being thread-safe from the start was a
  precondition rather than a follow-up.
- `tests/test_weights_attr.cc` gained `testMergeInterpolates` (union,
  absent-is-zero, no normalization), `testMergeEndpoints` (t=0, t=1, and the
  collapse case, each asserting the *slot* is shared, not merely equal) and
  `testMergeBounds` (epsilon drop; 32+32 disjoint groups capping to 32). Each
  ends in an `auditRefcounts` check, so a handler that leaks or under-counts
  fails on accounting even when its arithmetic is right.

### E5 — serialization

`source/mesh/mesh_serialize.{h,cc}`. **Landed**, at format version **6**
(`kMeshFormatVersion`, the one constant writer, reader, and fixture generator
all read).

A WEIGHTS cell is bit-identical to an int, so the existing `type_dispatch`
already gathers, byte-swaps and writes it correctly — and that is exactly the
problem: the bytes are *pool indices*, meaningless without the pool and
dangerous if restored without refcounts. So the column travels as-is and
everything else is new.

- **Compaction on write.** A `WeightRemap` (a `Map<int,int>` plus a dense→slot
  vector) assigns dense ids in the order the write pass meets slots — domains in
  file order, elements in dense order — so the saved pool has no holes whatever
  the live one looked like, and reloads with the mesh's own locality. Dense 0 is
  pinned to the empty run, matching the live pool's slot 0. `remapWeightColumn`
  rewrites each gathered column in place right after `gatherColumn`.
- **One section, appended last.** The pool is written after all five domains
  *and* the v3 sculpt-layer table — not beside its column — because `remap` is
  only complete once every domain has been gathered. Layout: `uint32 slotCount`,
  then per slot `uint32 runLen` and `(int32 group, float weight)` entries, then
  `uint32 groupNameCount` and the names. `slotCount == 0` means "no pool", which
  is distinct from a pool holding only the empty run. Everything goes through
  `BinFile`, so byte-swap is free; `scalarSize()` already returned 4 for WEIGHTS.
- **Pool before columns on read.** `AttrGroup::ensure` *asserts* the group has a
  `deform_pool` before it will create a WEIGHTS column, so `readMesh` calls
  `mesh.deformPool()` ahead of `buildDomain` whenever the file has a pool
  section or (`hasWeightColumn`) any WEIGHTS column at all.
- **`buildDomain` skips WEIGHTS entirely.** A raw copy would install dense ids
  as live slot indices and take no reference — a double-release at teardown,
  since `~AttrGroup`, `remove_attr`, `shrink_capacity` and `set_default` all
  release WEIGHTS references. The cells stay at the empty run until:
- **`restoreWeights`** interns each dense run once, then walks every WEIGHTS
  column writing cells through `reassign` (which retains), and finally releases
  each `intern()` reference exactly once. That ledger is what `auditRefcounts`
  checks in the test.
- **v5 → v6 migration** zeroes any WEIGHTS bytes it finds rather than
  reconstructing: a v5 file's indices point into a pool that was never written.
  No file with real weights predates v6 — E1–E4 landed while the version was
  still 5, and the pool section and the bump landed together. The existing
  `test_load_fixture("mesh_v5.bin")` exercises that path for free.
- Merge policy and `AttrUse` are re-derived by name on load already, so nothing
  new is serialized for those.
- **Tests.** `tests/test_mesh_serialize.cc::test_weights_roundtrip` builds a
  4×4 grid whose runs are position-derived across three shapes (so several verts
  sharing one slot is the common case), then deliberately creates *two* kinds of
  pool hole — a run named only by a killed vertex (its cell keeps the reference,
  so the slot is live but unreachable) and a run overwritten then swept — before
  saving. On the loaded mesh it asserts every run round-tripped, `group_names`
  survived, `liveSlotCount() == 3` (compaction dropped both holes), and
  `auditRefcounts(roots) == 0`. `fixtures/mesh_v6.bin` is checked in and loaded
  by `test_load_fixture`. Commenting out `restoreWeights` was confirmed to fail
  the test, so it is not vacuous. Payload budget unchanged (20528 / 22500).

### E6 — c-api

**Landed.** `source/mesh/c-api/mesh_c_api.cc`, the CSR shape this section
planned, with the two additions the marshalling actually needed:

```
int  sc_mesh_weights_element_count(Mesh *)
int  sc_mesh_weights_get(Mesh *, int *offsets, int *group_ids, float *weights)
int  sc_mesh_weights_set(Mesh *, const int *offsets, const int *group_ids, const float *weights)
int  sc_mesh_weight_group_count(Mesh *)
int  sc_mesh_weight_groups_get(Mesh *, char *buf, int buf_size)
void sc_mesh_weight_groups_set(Mesh *, const char *buf, int count)
```

- `offsets` has `vert_count + 1` entries, in the **live-vertex order**
  `Mesh_toArrays` exports — not engine index order. A mesh with a freelist gap
  is where the difference bites, which is what the new test block builds.
- `element_count` sizes the two payload arrays; it is `offsets[vert_count]`.
  Both readers return 0 without writing when there is no weights layer, so the
  addon's enter path can call them unconditionally.
- **Names cross as one NUL-separated block**, not a call per name:
  `_groups_get(m, nullptr, 0)` returns the byte count, so the caller sizes once
  and copies once. `sc_mesh_weight_group_count` exists because splitting the
  block to count is silly when the pool already knows.
- `_set` writes **every** live vertex, so an empty run clears rather than
  leaving the previous one — a half-write is not a state the bridge can
  produce. It creates the layer and the pool on first use (`ensureVertWeights`),
  and interning canonicalizes, so runs need not arrive sorted or deduplicated.
- **The layer name is fixed**, not a parameter: `mesh::VERT_WEIGHTS`
  (`".vertex_groups"`, new in `attr_weights.h`). Blender carries exactly one
  MDeformVert table per mesh, so a name argument would only ever take one value.

Two pieces of wiring beyond the c-api file itself, both of which a build would
not catch:

- `source/mesh/CMakeLists.txt`'s exported-symbol list. The native shared library
  exports by explicit list (`lt_native_export_symbols`), so an unlisted
  `extern "C"` function compiles, links, and is then invisible to `ctypes`.
- `sculptcore_addon/engine.py`'s `_CApi.__init__` — the addon's mesh c-api
  declarations live there, *not* in the engine's `python/sculptcore/_capi.py`
  `_DECLS` table (which covers the binding/alloc surface only). Without
  `restype`, ctypes truncates a returned pointer to `int`; these all return
  `int`, but the `argtypes` matter for the numpy `ndpointer` checks.

Tested in `tests/test_mesh_arrays.cc` (the c-api marshalling test), on a mesh
with three killed vertices: no-layer returns, the name-table size/copy round
trip, a CSR write whose first run is given out of group order (it comes back
group-ascending, values following their groups), the runs landing on verts
3/4/5 rather than the dead slots, and an all-empty write clearing. Rewriting
`_set`'s loop as `for (vi = 0; vi < m->v.count; vi++)` fails seven of those
assertions, so the live-order half is not vacuous. A ctypes smoke against the
built `sculptcore_capi.dll` confirmed the exports resolve on the path the addon
actually uses.

### E7 — tests

**Landed.** The unit coverage grew alongside each phase rather than as one pass
at the end, so it is spread over four files rather than the single
`test_deform_attr.cc` this section originally named:

- `tests/test_deform_attr.cc` (E1) — the pool alone: intern/dedup, refcounting,
  `reassign`, sweep-keeps-indices, the audit itself, plus
  `testConcurrentIntern` / `testConcurrentChurn` (8 threads, fan-in onto shared
  slots, and release-to-zero racing intern of the same run).
- `tests/test_weights_attr.cc` (E2/E4) — the column's reference discipline
  (overwrite, element reuse, layer removal, teardown) and the merge handler's
  value rules, each ending in an `auditRefcounts` check.
- `tests/test_weights_undo.cc` (E3) — meshlog capture/restore and the
  pool-outlives-mesh case.
- `tests/test_mesh_serialize.cc` (E5) — the round trip, including a pool with
  holes before saving.

What this phase added on top:

- **Threading stress** — `test_weights_attr.cc::testConcurrentMergeAndCapture`:
  8 threads, each owning a disjoint slice of verts and its own
  `ChunkElemData`, running the merge handler and a meshlog capture in a loop, so
  interns, retains and releases all overlap on one pool. `t` is drawn from a
  small shared set so the threads fan in onto the same runs. It asserts the
  final blend per vertex (recomputed, not read back), a clean audit before and
  after a sweep, and the exact live-slot count. The handler is called directly
  rather than through `interpAttrs`: no other column claims to be writable from
  several threads, and dragging them in would test a promise nothing makes.
  - **Gap: not run under TSan.** The build has no TSan configuration (only
    `WITH_ASAN`), and clang's TSan does not support Windows, which is this
    box. Running it needs a Linux/macOS build with `-fsanitize=thread`.
- **`set_weights` / `save_weights` / `assert_weights`** debug-app verbs
  (`source/debug/script.cc`), mirroring `save_pos` / `assert_pos` down to the
  `eps` / `soft` arguments and the non-zero exit. `set_weights` had to come
  with them — without a way to *put* weights on a mesh the pair has nothing to
  check — and its default is a z-gradient over the AABB, not a constant, since
  a constant survives any interpolator, correct or not. `assert_weights`
  compares whole runs, not slot indices (the pool interns by value, so an index
  is not comparable across a sweep), and reports `dead` / `reshaped` /
  `changed`. Documented in `documentation/debugApp.md` with the
  `save_weights … stroke … undo … assert_weights` example.
- **`dump_state` fingerprint** — a `weight_attrs` block per WEIGHTS layer:
  `entries` (an influence gained or dropped), `group_sum` (a run landing on the
  wrong group), `sum`/`sqsum` (the values), and the pool's live `slots` (which
  is how run growth under repeated interpolation would show). The existing
  vertex-attr block skips WEIGHTS, so meshes without one dump unchanged and
  every brush golden stays stable.

Still open, and better placed once dyntopo weights are exercised for real:
split/collapse round trips asserting a uniformly-weighted region comes back
bit-identical and a boundary comes back a correct lerp. `testMergeAcrossSplit`
covers the single-split case today.

## Blender fork work

### F1 — bulk vertex-group accessor

Branch `custom-object-modes`, in `source/blender/makesrna/intern/rna_mesh_api.cc`.
Engine-agnostic and generally useful, so it fits the branch's charter (and is
plausibly upstreamable).

**Landed** (fork commit `9a098f3`, `custom-object-modes`).

```python
mesh.vertex_group_element_count() -> int
mesh.vertex_group_data_get() -> (offsets, group_indices, weights)
mesh.vertex_group_data_set(offsets, group_indices, weights)
```

- CSR again: `offsets` is `len(vertices) + 1` ints; the other two are
  `element_count` long.
- **`_get` returns its arrays rather than filling caller-supplied buffers**,
  which is where this section was wrong. RNA function parameters have no
  caller-preallocated form: a `PARM_OUTPUT` + `PROP_DYNAMIC` array is allocated
  by the callee and converted to a Python list, and a `PARM_REQUIRED` array is
  copied into a temp buffer the callee cannot write back through. `foreach_get`
  is the only memcpy-speed path in the RNA layer and it is collection-property
  only, so it cannot serve a ragged table. The win is still the one that
  mattered — one call and one C-side loop instead of a Python loop over every
  vertex and influence — but A1 pays a list→buffer conversion on the way to
  the c-api.
- The `PROP_DYNAMIC` + `PARM_REQUIRED`/`PARM_OUTPUT` precedent
  (`normals_split_custom_set`, `calc_smooth_groups`) is what it follows. Output
  arrays are allocated with `MEM_new_array_uninitialized` — RNA frees them with
  `MEM_delete_void` in `RNA_parameter_list_free`.
- Reads `mesh->deform_verts()` / writes `deform_verts_for_write()`. `_set`
  clears each vertex with `BKE_defvert_clear` and then allocates its run **once**
  rather than calling `BKE_defvert_add_index_notest` per influence, which
  reallocates and memcpys every time; the allocation matches the one that call
  uses, so `BKE_defvert_clear` still frees it.
- The two-call protocol (count, then fill) is deliberate: the total is not
  derivable from the vertex count.
- **`_set` validates everything before it mutates**: offsets length, payload
  lengths agreeing with each other and with the terminator, offsets
  non-decreasing, and every group index naming an existing vertex group. A
  rejected call reports and leaves the mesh alone — a half-written weight table
  is not a state a caller can detect or recover from.
- Group **names** are not part of this API — they are a short list and
  `object.vertex_groups` already reads and creates them cheaply.

Verified headlessly against the rebuilt fork: a 4-vertex mesh with two groups
round-trips get→set→get, Blender's own `VertexGroup.weight()` view agrees with
what was written (so this is not a private side table), each of the five
rejection paths raises and leaves the data intact, and a mesh with no groups
reads as all-zero offsets rather than erroring.

## Addon work

### A1 — bridge it in `convert.py`

`sculptcore_addon/convert.py`.

- Vertex groups are invisible to `mesh.attributes`, so this is a dedicated path
  alongside `_load_bridged_attrs` (line 503) and `_flush_bridged_attrs`, not a
  new entry in `_ATTR_TYPE_MAP` (line 473).
- **Enter**: read names from `object.vertex_groups`, weights via F1's
  `vertex_group_data_get` into `array.array` buffers, hand both to E6's c-api.
- **Exit / flush**: the reverse. On the topology-rebuild path
  (`_flush_topology_rebuild`, line 634), `clear_geometry()` at line 658 wipes
  the group names too, so restore them with `object.vertex_groups.new(name=...)`
  in engine order *before* writing weights back.
- Do the transfer on enter/exit only. If profiling shows the fast flush path
  (line 871) needs it per-flush, that is a follow-up, not part of this plan.

### A2 — docs and memory

- Update the addon `CLAUDE.md` if the bridge grows a user-visible caveat.
- Add a memory recording that weights are engine-owned and why the fork gained
  a bulk accessor; link `[[sculptcore-delta-undo]]`.

## Ordering and gates

```
E0 ─ E1 ─ E2 ─ E3 ─ E4 ─┬─ E5 ─┐
                        └─ E7 ─┴─ E6 ─ A1
F1 ────────────────────────────────────┘
```

- E1's concurrency design gates E4 (the first allocating merge handler).
- E3 gates E7's threading stress test.
- F1 is independent of all engine work and can be done in parallel; it is the
  long pole for A1 because it needs a fork rebuild.
- **A1 must not land before E5**, or a save/load will drop weights the user can
  see, which is worse than today's behavior.

## Risks

- **A missed write funnel** leaks or corrupts slots and will not reproduce
  deterministically. The debug refcount audit (E1) is the mitigation and should
  be written before E2, not after.
- **`AttrType` is a bitmask** — anything that treats a set of types as a mask
  needs auditing for a hardcoded all-bits value.
- **Interning under a stroke that produces novel weights everywhere** (a
  boundary between many groups) degrades to one slot per split. That is the
  correct cost, but the dab-end sweep needs to keep up; measure with
  `bench_dyntopo`.
- **`group_id` ordering drift** between engine and Blender across an
  enter/edit/exit cycle where the user adds or removes a group in another mode.
  A1 reconciles by name and must be tested for it.
