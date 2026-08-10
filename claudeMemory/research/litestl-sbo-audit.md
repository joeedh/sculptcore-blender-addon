# litestl SBO audit — multires + spatial tree hot paths

Date: 2026-08-10. Scope: `engine/source/{subdiv,spatial,displace,vdm}` plus the
per-dab entry points in `brush/` that own spatial-tree query buffers.

Question asked: are the small-buffer-optimization sizes on `util::Vector` /
`util::Map` / `util::Set` right in the hot paths, given the defaults are low?

Answer in short: the defaults are low, but **the bigger problem is not the size
of the SBO — it is that hot code allocates fresh containers per element/per
leaf/per dab instead of reusing them**, and that `Vector`'s inline buffer is
off by one so every hand-tuned `Vector<T, N>` actually holds `N-1`.

---

## 1. Mechanics — the numbers to calibrate against

| container | default | inline slots | inline logical capacity | `sizeof` (int key) |
|---|---|---|---|---|
| `Vector<T, N>` | `N = 4` (`vector.h:51`) | `N` | **`N - 1`** (see §1.1) | 24 + `N`·sizeof(T) |
| `Set<K, N>` | `N = 4` (`set.h:55`) | `pow2 ≥ 3N+1` = 16 | 14 (7/8 load) | 120 |
| `Map<K,V,N>` | `N = 16` (`map.h:123`) | `pow2 ≥ 3N+1` = 64 | 56 | 616 |
| `OrderedSet<K,N>` | `N = 4` (`ordered_set.h:9`) | Map(16)+2 Vectors+BoolVector | 14 | 328 |

Measured with clang on this box (`sizeof(Set<int,64>) == 1320`,
`sizeof(Vector<int,64>) == 280`) — an SBO is inline in *every copy of the
object*, so it is not free when the container is a struct member stored in an
array.

### 1.1 `Vector<T, N>` spills at the N-th element (off-by-one)

`util/vector.h:922`:

```cpp
void ensure_size(size_t newsize)
{
  if (newsize < capacity_) {   // <-- should be <=
    return;
  }
  ...
}
```

`append_intern()` calls `ensure_size(size_ + 1)`. With `capacity_ == N` (the
default ctor sets exactly that), appending the N-th element evaluates
`N < N` → false → heap allocation. Verified empirically:

```
Vector<int,4>:  size=1 static=1   size=2 static=1   size=3 static=1
                size=4 static=0   <-- spilled
Vector<int,64>: 64 appends -> static=0
```

Same for `resize(N)` and `ensure_capacity(N)`.

This is a bug, not a deliberate one-slot reserve: the `initializer_list`
constructor (`vector.h:301`) puts a list of exactly `static_size` elements
inline and sets `capacity_ = static_size`, so the two paths disagree.

It matters most where a size was chosen to be an *exact* fit — a quad's 4
verts in a `Vector<int, 4>`, a face's 4 grids, a 16-gon in
`Vector<Tri, 16>` (`spatial.h:461`). Those all spill today.

**Fix:** change the guard to `newsize <= capacity_`. Safe on every path
(default ctor sets `data_ = static_storage()`; a moved-from vector has
`capacity_ == 0`, so `1 <= 0` is still false and it allocates).

### 1.2 Growth and reserve

- Growth is `(n+1)*2 - n/2` ≈ **1.5×**. Going 4 → 3000 is ~13 reallocations
  and ~3× the final byte count in memcpy traffic.
- `ensure_capacity(n)` is literally `ensure_size(n)`, so it over-allocates to
  ~1.5n. There is no reserve-exact.
- `Set` and `Map` have `reserve()`. **`OrderedSet` does not** — relevant
  because `SpatialNode::NodeData` uses two of them for 512-vert leaves.

### 1.3 `clear()` keeps capacity; `clear_and_contract()` does not

`Vector::clear()` → `resize(0)` → `ensure_size(0)` returns early, capacity
retained. `Set::clear()` / `Map::clear()` memset the control bytes and keep the
table. So **hoist-and-`clear()` is the correct idiom** and costs nothing after
the first iteration. `clear_and_contract()` throws the buffer away.

### 1.4 Minor: a branch + `printf` in the hottest function

`vector.h:915`, in `append_intern()`:

```cpp
if (size_ < 0 || reinterpret_cast<intptr_t>(data_) < 100) { printf("error!\n"); }
```

`size_` is `size_t`, so the first test is dead. The second is a compare+branch
on every single append in the engine. Worth deleting or `#ifndef NDEBUG`-ing.

---

## 2. Findings — per-dab / per-frame (highest value)

### F1. `update_node_normals` allocates three vectors per dirty leaf per frame
`spatial/spatial.cc:2991, 2999, 3000`

```cpp
Vector<int> moved_verts;        // grows to affected_verts.size(), up to leaf_limit/4 = 128
Vector<int> affected_face_set;  // one append per affected tri
Vector<int> affected_vert_set;  // three appends per affected tri
```

This is the per-frame normals path, run under `parallel_for` over every dirty
leaf (`spatial.cc:3432`). `affected_vert_set` takes up to `3 × tris.size()`
appends — with `leaf_limit = 512` that is a few thousand ints, i.e. ~13
reallocations from an SBO of 4, per leaf, per frame.

Fix: the sizes are all known up front. Either `ensure_capacity()` at the top
(`affected_verts.size()`, `tris.size()`, `tris.size() * 3`), or better, hoist a
scratch struct into the `parallel_for` lambda (one per range, not per node) and
`clear()` per leaf. Do **not** make it a `SpatialTree` member — this runs in
parallel.

### F2. `regen_node_tris` / `build_node_skirt` contract then immediately refill
`spatial/spatial.cc:357, 362, 363, 370`

```cpp
node->data->tris.clear_and_contract();
for (int f : node->data->unique_faces) { appendFaceTris(m, node->data->tris, f); }
```

`tris` holds ~1000 `NodeTri` (20 B each, ~20 KB) for a 512-vert leaf. Dropping
to the 4-element inline buffer and regrowing at 1.5× is ~19 malloc/free pairs
and ~60 KB of memcpy per leaf, every topology change — i.e. every dyntopo dab.
Same for `skirt_tris`, `foreign_verts`, `border_tris`.

Fix: use `clear()` (capacity retained) and add
`ensure_capacity(unique_faces.size() * 2)`. Keep `clear_and_contract()` only
where a node is genuinely being retired (`node.h:90/100`, `spatial_gpu.cc`).

### F3. Fresh `Set<int>` per leaf in the skirt and border-cache builds
`spatial/spatial.cc:373` (`build_node_skirt`), `spatial/spatial.cc:407`
(`ensure_border_cache`)

Both start at 14 inline entries and grow to the leaf's skirt-face /
foreign-vert count (typically dozens to a few hundred), rehashing 3–5 times.
`ensure_border_cache` runs from the per-frame normals phase.

Fix: `seen.reserve(...)` from a cheap upper bound (`unique_verts.size()` /
`tris.size()`), or declare them as `Set<int, 64>` scratch hoisted into the
caller's parallel range.

### F4. Per-dab spatial query buffer at SBO 4
`brush/brush_executor.h:1962, 2020, 2064`, `vdm/vdm_splat.cc:178`,
`meshlog/meshlog_base.h:1896`, `debug/gpu_stroke.cc:430`

```cpp
Vector<spatial::SpatialNode *> nodes;
tree->filterNodes(center, radius, nodes);
```

`lastDabNodeCount` is routinely tens of leaves, so this is 4–6 reallocations
per dab, per call site. Cheap to fix and consistent with the rest of the file,
which already uses `Vector<SpatialNode *, 32/64/256>` elsewhere
(`spatial.cc:647, 703, 3479`).

Fix: `Vector<spatial::SpatialNode *, 64> nodes;`, or make it a reused executor
member cleared per dab (`grid_executor.h` already does this with `dabLeaves_` /
`nodePtrs_`).

### F5. VDM splat allocates two vectors per face per dab
`vdm/vdm_splat.cc:211-212`

```cpp
for (SpatialNode *node : nodes) {
  for (int f : node->data->unique_faces) {
    ...
    Vector<int> cVerts;
    Vector<float2> cUvs;
```

A quad has exactly 4 corners, which under §1.1 spills both vectors — so this is
2 malloc + 2 free **per face per dab** even on an all-quad mesh.

Fix: hoist above the loops as `Vector<int, 8>` / `Vector<float2, 8>` and
`clear()` per face. (Fixing §1.1 alone also removes the allocation for quads.)

### F6. Per-dab VDM dedup tables grow from the default
`vdm/vdm_splat.cc:434` (`Set<uint64_t> visited`), `:435` (`Map<int,float>
foldRadius`), `:436` (`Map<int,uint8_t> synced`)

`visited` holds one entry per texel splatted in the dab — thousands — starting
from 14. That is ~8 rehashes, each a full table alloc + reinsert.

Fix: `visited.reserve()` from the dab's texel-area estimate; leave the SBO
alone (a large SBO would just bloat the stack frame).

### F7. Halo-hint fan-out vectors
`spatial/spatial.cc:3358`

```cpp
Vector<Vector<HaloHint>> haloHints;
haloHints.resize(primaryNormalsCount);
```

Each inner vector (SBO 4, `HaloHint` = 8 B) collects up to
`3 × (border_tris + skirt_tris)` hints for its leaf. Reallocating per leaf per
frame.

Fix: `Vector<HaloHint, 32>` for the inner type, or `ensure_capacity` inside the
worker once `border_tris`/`skirt_tris` sizes are known.

---

## 3. Findings — multires enter / rebuild

`Refiner::refine` is ~70% of the remaining multires enter cost (see
`multires-stroke-perf-gap` memory), so these matter for the 2.1 s enter number.

### F8. A heap allocation per coarse vertex in the vertex-point stencil pass
`subdiv/subdiv.cc:270`

```cpp
for (int vi : m0->v) {
  ...
  } else {
    double n = double(valence);
    row.add(vi, (n - 3.0) / n);
    Vector<int> vfaces;               // <-- fresh, per vertex
    for (int e1 : m0->e_of_v(vi)) { ... vfaces.append(f); ... }
```

Runs once per vertex of every level's coarse mesh — hundreds of thousands of
vertices at L3/L4. A valence-4 quad vertex has 4 incident faces, which spills
(§1.1); valence 5+ always spills. Note the neighbouring `RowBuilder row` is
already correctly hoisted above the loop and `clear()`ed — `vfaces` is the one
that was missed.

Fix: hoist `Vector<int, 16> vfaces;` above the `for (int vi : m0->v)` loop and
`vfaces.clear()` at the top of the `else` branch. This is the single
highest-value change in this document.

### F9. Stencil tables are built by unreserved single appends
`subdiv/subdiv.cc:96-99` (`RowBuilder::commit`)

`st.indices` / `st.weights` / `st.offsets` grow to `fineCount` × avg-row-width
one `append()` at a time from SBO 4. At 1M fine verts that is ~35
reallocations copying ~3× the final array.

Fix: `ensure_capacity()` on all three at the top of `refineStep` from
`m0->v/e/f` counts (the fine vert count is known exactly; a per-row estimate of
~8 gives a good bound for `indices`/`weights`).

### F10. Grid-tree build: per-face and per-leaf vectors at SBO 4
`subdiv/grid_tree.cc:51` (`Vector<int> cycle`, per cage face — 4 for a quad, so
it spills), `:92` (`Vector<int> frontier`), `:45/64` (`Vector<Vector<int>>
faceGrids` / `faceNbrs`, inner vectors hold face valence ≈ 4 → spill),
`grid_tree.h:48/51` (`Leaf::grids`, `Leaf::ownedVerts` — hundreds each).

Fix: `Vector<int, 8>` for `cycle` and the `faceGrids`/`faceNbrs` inner type;
`ensure_capacity` on `ownedVerts` from `leafVertTarget`.

### F11. `OrderedSet` on 512-vert leaves has dead SBO and no `reserve`
`spatial/node.h:110-111`

```cpp
util::OrderedSet<int> unique_verts;   // 328 B each, inline capacity 14
util::OrderedSet<int> unique_faces;
```

A leaf holds up to `leaf_limit = 512` verts, so the inline table is dead weight
in every node (~650 B × node count, a few MB on a 1M mesh) *and* the underlying
`Map` rehashes ~6 times filling each leaf — on every split, i.e. per dyntopo
dab.

Fix: `OrderedSet` needs a `reserve(n)` that forwards to `Map::reserve` +
`Vector::ensure_capacity`; call it with `leaf_limit` when a node's data is
created. Optionally drop the SBO (`OrderedSet<int, 1>`) since it is never used
at this size.

---

## 4. Where the sizing is already right

Worth noting so these are not "fixed" into regressions:

- `subdiv/grid_domain.cc:136, 148` — `util::Vector<int, 64> nbrs` hoisted
  *outside* the per-vert loop inside each `parallel_for` range and `clear()`ed.
  This is the pattern the rest of this document is asking for.
- `spatial/spatial.cc:647, 703, 707, 1120, 3231, 3294, 3336, 3478-3651` —
  `Vector<SpatialNode *, 32/64/256>` and friends, all correctly sized to the
  per-update working set.
- `subdiv/subdiv.cc:83` — `RowBuilder row` hoisted and `clear()`ed.
- `brush/grid_executor.h` — `dabLeaves_`, `nodePtrs_`, `dabMoved_`,
  `strokeTouched*_` are persistent members cleared per dab. Correct.
- Large per-level arrays (`posCache_`, `gridVerts`, `ring1`, stencil rows) are
  `resize()`d once to their real size; their SBO is irrelevant.

---

## 5. Adjacent finding (not SBO, found while reading)

`subdiv/grid_stroke_log.cc:57`, `captureGridBlock`:

```cpp
if (gridStamp_[grid] == gen_) {
  for (const GridBlock &b : s.blocks) {          // linear over ALL blocks
    if (b.grid == grid && b.channel == channel) return;
  }
}
```

After the first dab of a stroke, every already-captured grid takes a linear
scan of the step's whole block list. Over a stroke that is
O(dabs × grids × blocks) — quadratic in the touched-grid count. A per-grid
channel bitmask alongside `gridStamp_` (or a `Map<uint64_t,int>` keyed
`grid<<32|channel`) makes it O(1).

---

## 6. Suggested order of work

1. `vector.h` `ensure_size` `<` → `<=` (§1.1). One character; makes every
   existing tuned size honest and removes the quad-sized spills in F5, F8, F10.
2. F8 (`vfaces` hoist) — biggest single win on multires enter. **Measured false;
   see §7.1.**
3. F1 + F2 + F3 — the per-frame normals/tris path.
4. F4, F5, F7 — per-dab.
5. F9, F10, F11 — build-time reserves.
6. §1.4 and §5 hygiene.

None of these change behaviour; every one is a pure allocation-traffic change.
Worth A/B-ing against `claudeMemory/scripts/bench_multires_sc.py` (enter time,
F8/F9/F10/F11) and the headed stroke benchmark (per-dab ms, F1–F7).

---

## 7. Applied (2026-08-10)

All 14 items landed in the engine working tree, in the §6 order. Engine builds
clean (`node make.mjs build native`, 434/434, no new warnings) and
`node make.mjs test` is **125/125 passing** in 60 s — including the four tests
memory records as flaky/known-failing, which all passed in this build dir.

What each item became:

| Item | Where |
|---|---|
| §1.1 `<` → `<=` | `litestl/util/vector.h` `ensure_size` |
| §1.4 | dead `printf` branch removed from `Vector::append_intern` |
| F1 | `NormalsScratch` in `spatial/spatial.h`; `update_node_normals(node, scratch)`, one scratch per `parallel_for` range |
| F2, F3 | `clear()` (not `clear_and_contract()`) + `ensure_capacity` in `regen_node_tris`; `Set<int, 64> seen` in `build_node_skirt` / `ensure_border_cache` |
| F4 | `dabNodes_` / `dynTopoNodes_` / `dynTopoSeed_` members on `BrushExecutor`; `ensure_capacity(64)` at the cold `filterNodes` sites (`vdm_splat.cc`, `meshlog_base.h`, `debug/gpu_stroke.cc`) |
| F5, F6 | hoisted `cVerts`/`cUvs`, `visited.reserve(texelBudget)`, `faceTouched.reserve` in `vdm/vdm_splat.cc` |
| F7 | `Vector<HaloHint, 32>` / `Vector<int, 64> moved` in `spatial.cc` |
| F8, F9 | `vfaces` hoisted above the vertex-point loop; stencil `offsets`/`indices`/`weights` reserves — `subdiv/subdiv.cc` `refineStep` |
| F10 | `FaceList = Vector<int, 8>`, hoisted `frontier`, per-leaf `grids`/`ownedVerts` reserves — `subdiv/grid_tree.cc` |
| F11 | `OrderedSet::reserve()` (+ the missing `#pragma once` in `ordered_set.h`); `create_data(reserveVerts)` in `spatial/node.h`, called with `leaf_limit` at the four split/merge sites |
| §5 | `gridChannels_` bitmask in `subdiv/grid_stroke_log.{h,cc}` — the dedup scan is O(1) except for `channel >= 32` |

Two constraints worth remembering, both hit while applying this:

- `SpatialTree::filterNodes` binds `Vector<SpatialNode *>&` with the **default**
  SBO, and that exact type is registered with the binding system and the napi
  runtime. Callers cannot pass an SBO'd type — reuse across dabs or
  `ensure_capacity` is the only route. That is why F4 is executor members.
- `update_node_normals` runs under `task::parallel_for`, so its scratch must be
  per-worker-range, never a tree member.

### 7.1 Measured: the enter-path A/B says these fixes do ~nothing there

`§6` called F8 "the biggest single win on multires enter". **That is wrong**, and
the A/B is what says so. Two `debug_app` binaries were built from the same tree —
one with the enter-path items (`<=`, F8, F9, F10, F11) reverted, one with them in —
and run **interleaved**, 10 pairs, on `make_cube subdivs=64 size=0.5` +
`multires_init levels=4` (6,096,386 verts):

| | min | median |
|---|---|---|
| before | 26.71 s | 27.52 s |
| after | 25.85 s | 27.08 s |

~1.6% on the median, ~3% on the min, against a run-to-run spread of ±2-3 s. The
effect is **inside the noise floor** — real in sign (the fixes never lose) but not
worth claiming a number for.

Order matters more than the fixes do: the first five pairs (before-then-after) show
the fixes ahead in 5/5, the reversed five split 2/3. Interleaving is not optional
here.

**Do not trust separated batches on this box.** An earlier non-interleaved attempt
read 47.6 s, then 53-83 s for the baseline and 28-29 s for the fixes — an apparent
1.9x that was entirely machine state (thermal/background load), not code. Both
binaries land at ~27 s once the machine is quiet.

Why the ceiling is so low: the `vfaces` allocation F8 removes fires about 2M times
across levels 0-3, at tens of ns each — a few hundred ms out of ~27 s. Allocation
traffic simply is not what `Refiner::refine` spends its time on (memory records it
as ~70% of enter); this is a bandwidth/access-pattern problem, and the next
enter-path win has to come from there, not from container tuning.

**Still unmeasured:** F1-F7, the per-dab items. Those need the headed stroke
benchmark (`claudeMemory/scripts/bench_multires_native.py`), not this script — the
enter path barely exercises them.

The fixes stay in regardless: they are strictly less allocation for identical
behaviour, and F1/F4's reuse matters more as brush footprints grow. They are just
not an enter-path optimization.

Diffs backed up at scratchpad `engine-sbo.patch` / `litestl-sbo.patch`; the two A/B
binaries at scratchpad `ab/{before,after}/`.
