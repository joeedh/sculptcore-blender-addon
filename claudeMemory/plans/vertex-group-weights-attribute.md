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
- **Pool ownership**: one lazily-created `DeformPool` per mesh, owned by
  `MeshBase` through a `DeformPoolOwner` member and reached by
  `MeshBase::deformPool()` / `deformPoolOrNull()`. `deformPool()` stamps a
  non-owning `AttrGroup::deform_pool` back-pointer onto all five element
  groups. The owner is a *member* rather than a raw pointer plus a `~MeshBase`
  body because a base destructor body runs *before* its base members are
  destroyed — the pool would have died before the `AttrGroup`s that release
  into it. It is declared first, so it destructs last.
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

`source/meshlog/meshlog_base.h`, `parallel_capture.h`.

- `cpyFrom` (line 217): retain after the memcpy for `WEIGHTS` columns. The
  existing memcpy is otherwise unchanged.
- `swapWith` (line 250): **no change** — swapping is refcount-neutral, and
  `char buf[64]` is ample for a 4-byte element.
- Row-store destruction / step drop: release every index in each `WEIGHTS`
  column.
- Memory accounting (line 328): report pool bytes as a separate term rather
  than folding them into `elemSize * size_`.
- Confirm the retain path is safe from `parallel_capture`'s worker threads (it
  is a plain atomic increment from a live reference, but assert it).
- **Verify undo state is not serialized.** If it is, save-time pool compaction
  (E5) has to consider log columns too.

### E4 — the merge handler

`source/mesh/attr_merge.cc`, registered in `resolveMergePolicy` (line 225) by
layer name, exactly like `mergeOrigNormal` / `mergeSculptLayerRest`.

Signature is `void(AttrRef &, const AttrMergeCtx &)`. `AttrMergeCtx` already
carries `Mesh *mesh` (`attr_interp.h:220-234`), so the handler reaches the pool
with no ABI change to the context.

Behavior: union the two sparse runs, `lerp(w0, w1, ctx.t)` treating a group
absent from one side as weight 0, drop sub-epsilon entries, cap the influence
count, then intern. Do **not** auto-normalize — Blender does not, and a sculpt
operation silently renormalizing a rigged mesh would be a worse bug than the one
this fixes. `COPY_SRC0` semantics for the degenerate cases, matching
`defaultMerge` (`attr_merge.cc:48`).

This is the engine's **first merge handler that allocates**, which is why E1's
concurrency work is a precondition rather than a follow-up.

### E5 — serialization

`source/mesh/mesh_serialize.cc`.

- Compact the pool at save time — order slots by first referencing vertex — so
  the on-disk indices are dense and the "remap" is just the compaction map.
- Write the pool (runs + slot table) and `group_names` as a companion blob
  alongside the column, byte-swapped like everything else.
- On load: rebuild the pool, re-intern, restore refcounts from the column.
  Merge policy and `AttrUse` are re-derived by name on load already, so nothing
  new is serialized for those.

### E6 — c-api

`source/mesh/c-api/mesh_c_api.cc`. The generic typed accessors cannot serve
this type, so it needs its own, and the shape should match what the addon
actually moves — **CSR, in bulk**:

```
sc_mesh_weights_element_count(mesh) -> int
sc_mesh_weights_get(mesh, int *offsets, int *group_ids, float *weights)
sc_mesh_weights_set(mesh, const int *offsets, const int *group_ids, const float *weights)
sc_mesh_weight_groups_get / _set   (the name table)
```

`offsets` has `vert_count + 1` entries. No per-vertex call ever crosses the
ctypes boundary.

### E7 — tests

`engine/tests/test_deform_attr.cc`, plus debug-app verbs.

- Intern/dedup correctness; refcount audit clean after churn.
- Merge correctness against values computed arithmetically in the test.
- Split/collapse round trips: weights on a uniformly-weighted region must be
  bit-identical after remeshing, and must be a correct lerp across a boundary.
- **Threading stress**: N threads interpolating and capturing concurrently, run
  under TSan. Assert the audit afterward.
- Serialize round trip, including a mesh whose pool has holes before saving.
- `save_weights` / `assert_weights` debug-app verbs mirroring the existing
  `save_pos` / `assert_pos` undo-fidelity pair (`engine/CLAUDE.md` § Debug app),
  so `save_weights … stroke … undo … assert_weights` is a scriptable regression.

## Blender fork work

### F1 — bulk vertex-group accessor

Branch `custom-object-modes`, in `source/blender/makesrna/intern/rna_mesh_api.cc`.
Engine-agnostic and generally useful, so it fits the branch's charter (and is
plausibly upstreamable).

```python
mesh.vertex_group_element_count() -> int
mesh.vertex_group_data_get(offsets, group_indices, weights)
mesh.vertex_group_data_set(offsets, group_indices, weights)
```

- CSR again: `offsets` is `len(vertices) + 1` ints; the other two are
  `element_count` long. Caller preallocates, matching `foreach_get`'s protocol,
  so a `numpy`/`array.array` buffer transfers at memcpy speed.
- Use the `PROP_DYNAMIC` + `PARM_REQUIRED`/`PARM_OUTPUT` precedent already in
  that file (lines 334, 347, 359 — `normals_split_custom_set`).
- Implementation reads `mesh->deform_verts()` / writes
  `deform_verts_for_write()` (`DNA_mesh_types.h:427-429`) and uses
  `BKE_defvert_*` (`BKE_deform.hh`) for the per-vertex edit rather than
  hand-rolling `MDeformWeight` allocation.
- The two-call protocol (count, then fill) is deliberate: the total is not
  derivable from the vertex count.
- Group **names** are not part of this API — they are a short list and
  `object.vertex_groups` already reads and creates them cheaply.

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
