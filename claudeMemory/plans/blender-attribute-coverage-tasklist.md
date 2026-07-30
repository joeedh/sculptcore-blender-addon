# Blender attribute coverage — what the bridge still drops

A tasklist of Blender mesh data the addon does **not** currently hand to the
engine, and what each one would take. Written after the `AttrType::WEIGHTS`
work landed (see
[vertex-group-weights-attribute.md](vertex-group-weights-attribute.md)), which
is the worked example every "needs its own storage type" item below points at.

Verified against `sculptcore_addon/convert.py`,
`engine/source/mesh/attribute_enums.h` and the fork's
`rna_enum_attribute_type_items` as of 2026-07-29. Nothing here is scheduled —
it is the backlog, ordered roughly by "how likely is a user to lose data".

## Why any of this matters

The bridge only exists because of the **topology-rebuild path**. While the
sculpt session is on the fast path, Blender's CustomData is untouched and every
one of these gaps is invisible. The moment dyntopo (or any remesh/undo that
changes the vertex count) fires, `_flush_topology_rebuild` calls
`mesh.clear_geometry()` and rebuilds — and anything the engine was not holding
is **gone**, silently, with no undo step that brings it back.

So the question for each item is not "does the engine support this type" but
"what does a user lose the first time they touch dyntopo".

## What is bridged today

| Path | Covers |
| --- | --- |
| Dedicated | positions, `.sculpt_mask`, `.sculpt_face_set`, active POINT/`FLOAT_COLOR` color, active UV map, `uv_seam`/`sharp_edge` (keyed by vertex pair), multires displacement, vertex groups |
| Generic (`_ATTR_TYPE_MAP`) | `FLOAT`, `FLOAT2`, `FLOAT_VECTOR`, `FLOAT_COLOR`, `BYTE_COLOR`, `INT`, `INT32_2D`, `BOOLEAN`, `QUATERNION` — on the `POINT`, `CORNER` and `FACE` domains only |
| Skipped by policy | `position`, every `.`-prefixed layer |

Engine side, for reference: `AttrType` has `FLOAT FLOAT2 FLOAT3 FLOAT4 BOOL INT
INT2 INT3 INT4 BYTE SHORT WEIGHTS`; `BYTE` is `uint8_t`, `SHORT` is `short`,
and there is **no** `SHORT2`/`BYTE2` or any matrix type. `ElemType` does have
`EDGE`.

## Engine-side tasklist

The whole of what the engine is missing, pulled to the front because it is
short and because most of the tiers below turn out to need none of it — see
*What of this is actually engine work* below for what was checked and found
already present. Each item names the tier item that wants it.

- [ ] **E1. `AttrType::SHORT2`** — a two-component 16-bit type. Wanted by
  **1.1** (`custom_normal` is `CD_PROP_INT16_2D`). Four files: the
  enumerator in `attribute_enums.h`, the
  `T`→type mapping in `attribute_base.h`, `type_dispatch` in `attribute.h`, and
  the `mesh_serialize.cc` switch. A `GPUType` too, but only if a shader ever
  reads it.
- [ ] **E2. A signed byte type** — `BYTE` is `uint8_t` and Blender's `INT8` is
  signed, so the direct mapping corrupts negatives. Wanted by **2.3**. Same
  four files as E1; only worth doing if the enum is already open for E1, since
  the host can otherwise widen to `INT`.
- [ ] **E3. A quaternion slerp `AttrMergeFn`** — wanted by **3.2**.
  Component-wise averaging of two quaternions is unnormalized and passes
  through zero when they are antipodal;
  the handler needs the `dot < 0` sign flip. `AttrMerge::CUSTOM`,
  `AttrRef::merge_fn` and `AttrMergeCtx` all exist already, with `mergeWeights`
  as the worked example.
- [ ] **E4. An encoded-normal `AttrMergeFn`** — decode, slerp, re-encode.
  Wanted by **1.1**, and **not optional alongside E1**: shipping the storage
  without the interpolator converts a
  visible "normals were dropped" into a silent "normals are wrong". Same
  handler shape as E3, so they likely land together.
- [ ] **E5. Decide whether the edge and face domains ever need real
  interpolation.** Every `interpAttrs` call site passes `m.v.attrs` or
  `m.c.attrs` — never `e` or `f`, which get row copy/union instead. That is
  correct for seam, sharp, material and face set, and defensible for crease and
  bevel weight, but an edge collapse welding two edges with different creases
  takes the first rather than the max. This is a decision to record, not
  necessarily code to write; the point is that the limit should stop being
  accidental.
- [ ] **E6. (optional) `AttrUse` tags for shape keys and custom normals**, so
  the semantics survive a round trip the way `UV` and `COLOR` do.

Nothing else on this page is engine work. In particular **1.2** (the edge
domain) and **1.4** (shape keys) are pure addon work against types and domains
the engine already carries.

## Fork-side tasklist — what Blender's Python API is missing

The third leg. `Mesh.vertex_group_data_get`/`_set` (fork commit `9a098f3`) is
the precedent for all of these: engine-agnostic, useful to any exporter or
rigging script, and added because the Python-loop alternative was untenable.

**F3, F2 and F4 are queued, in that order** — listed first below and mirrored
into the session task list. F5 and F6 are not.

- [ ] **F3. Any Python access at all to `CD_GRID_PAINT_MASK`.** There is
  none — the string does not appear anywhere in `makesrna`. So the multires
  sculpt mask (**3.4**) is not merely unbridged, it is *unreachable*: unlike
  every other item on this page there is no addon-side workaround, and the fork
  has to move first. That is why it leads: nothing else here blocks anyone but
  us. `CD_MDISPS` was in exactly this position, which is why the fork already
  carries the multires reshape API — this is the same gap, one layer over.
- [ ] **F2. `Mesh`-level vertex group names.** The `vertex_group_names`
  ListBase lives on `Mesh` — `mesh_clear_geometry` frees it — but RNA exposes
  the names only through `Object.vertex_groups`; `rna_mesh.cc` has no
  vertex-group property at all. Three costs, all of which the landed bridge
  pays: restoring names needs the *Object*, so `_flush_vertex_groups` hangs off
  `flush(ob)` instead of the mesh rebuild that actually dropped them;
  `ob.vertex_groups.clear()` + `.new()` invalidates live Python `VertexGroup`
  handles (this is a real trap — it broke the bridge's own test); and there is
  no bulk set, so it is one `.new()` per group. A `vertex_group_names_get`/
  `_set` pair is the same shape and roughly the same size as F1 — it is F1's
  missing other half. Landing it simplifies `_flush_vertex_groups` and retires
  the stale-handle workaround in its test.
- [ ] **F4. A bulk topology setter.** The rebuild is `clear_geometry()` +
  three `add()` calls + four `foreach_set` calls + `update(calc_edges=True)`
  (`convert.py:726-734`). `add()` preserves attribute layers but only *grows*;
  dyntopo also removes, which is why `clear_geometry()` is unavoidable, which
  is why this whole page exists. A `Mesh.set_topology(positions, corner_verts,
  face_offsets)` would be one call instead of eight, and could keep the layer
  *declarations* (name/type/domain/active flags) across the rebuild even though
  the per-element data is meaningless after a dyntopo pass — the addon would
  write values instead of recreating layers. It could also take edges directly
  rather than making Blender re-derive what the engine already knows. Biggest
  lever here, and the biggest ask.
- [ ] **F5. `Mesh.mselect`.** No RNA. Minor; wanted by **3.5**.
- [ ] **F6. (optional) Bulk shape-key data get/set on `Mesh`.** Nothing is
  strictly *missing* for **1.4** — `Object.shape_key_add` and
  `KeyBlock.data.foreach_get("co")` both work — but it is Object-level and
  per-block, so it has F2's shape. Worth doing only if 1.4's block-by-block
  restore turns out to be slow or awkward in practice.

**Checked and found present** — recorded so these do not get proposed:

- Every Blender attribute type has an RNA value struct, including
  `Short2AttributeValue` (which is what `custom_normal` is),
  `Float4x4AttributeValue`, `Float4AttributeValue` and `ByteIntAttributeValue`.
  All are reachable with `foreach_get`.
- `foreach_get`/`foreach_set` handle `PROP_RAW_SHORT` and `PROP_RAW_INT8` with
  a matching buffer format (`foreach_compat_buffer`, `bpy_rna.cc:6022`), so
  16-bit and 8-bit attributes take the fast raw path given an `int16`/`int8`
  numpy array. **1.1 and 2.3 are therefore engine-and-addon gaps, not RNA
  gaps** — the host can already read the data.
- Active color, default color, active UV and active attribute indices are all
  exposed, so restoring the attribute *metadata* after `clear_geometry` needs
  nothing new.

---

## Tier 1 — data a normal user can lose today

### [ ] 1.1 `INT16_2D` — this is `custom_normal`

Custom split normals are a plain `custom_normal` corner attribute of type
`CD_PROP_INT16_2D` in 5.x (`mesh_custom_normals_to_generic`,
`mesh_legacy_convert.cc:2494`). Not dot-prefixed, so the bridge reaches it,
sees no `_ATTR_TYPE_MAP` entry, logs *"is unsupported and will be dropped on
topology change"*, and drops it. Anyone who sculpts on a hard-surface mesh with
baked normals loses them at the first dyntopo dab.

Two pieces of work, and the first is the cheap one:

- Engine needs a two-component 16-bit type (`SHORT2`), or the bridge widens to
  `INT2` and narrows on the way back. Widening is a smaller change and the
  memory cost is per-corner; measure before assuming it matters.
- The values are **spherically encoded**, not a vector — component-wise lerp of
  two encoded normals is meaningless near the poles. This wants
  `AttrMerge::CUSTOM`: decode both, slerp, re-encode. That is the same shape as
  `mergeWeights`, minus the pool.

Shipping the type without the interpolator is worse than useless: it turns
"normals are lost" into "normals are quietly wrong", which is harder to notice.
Do both or neither.

### [ ] 1.2 The whole `EDGE` domain

`_DOMAIN_TO_ENGINE` is `{'POINT': 1, 'CORNER': 4, 'FACE': 16}`. An edge-domain
attribute is skipped **silently** — it does not even get the "unsupported" log
line that an unsupported *type* gets, because the domain check comes first
(`convert.py:524`).

Concretely dropped: `crease_edge`, `bevel_weight_edge`, `freestyle_edge`, and
every user-authored edge attribute. Subdivision creases surviving a sculpt is
the one most likely to be noticed.

The engine has `ElemType::EDGE`, so the blocker is not storage — it is
**identity**. The engine derives its own edges, so edge *indices* do not
correspond across the boundary in either direction. The addon already solved
this once, for the two boundary bool flags: `_load_edge_flags` /
`_flush_edge_flags` key edges by vertex pair. Generalizing that into the
attribute bridge is the task; the per-attribute cost is a hash lookup per edge,
which is why it was worth doing by hand for two flags and needs measuring
before doing it for N.

First step regardless of the rest: **log the skip**, so an edge attribute is at
least as visible as an unsupported type.

### [ ] 1.3 Selection and hide state

`.select_vert` / `.select_edge` / `.select_poly` and `.hide_vert` /
`.hide_edge` / `.hide_poly` are dot-prefixed, so the blanket "never bridge a
dot-prefixed layer" rule drops them. Leaving sculpt mode after a topology
change therefore hands the user a mesh with their edit-mode selection and their
hidden geometry reset.

Hide is the sharper half: a user who hid part of a mesh, sculpted, and came
back to find it all visible has lost work state, not just a selection.

The engine already has `AttrUse::SELECT` for the box-modeling case, so the
receiving end exists. The task is to carve named exceptions out of
`_SKIP_ATTR_NAMES`'s dot rule rather than to loosen the rule — the rule is
right for topology links.

### [ ] 1.4 Shape keys — one `FLOAT3` point attribute per key block

Currently a hard refusal at `enter()` (`convert.py:97`), which means the addon
cannot be used on any rigged or corrective-shape asset — most production
geometry.

**The storage needs nothing new.** A `KeyBlock` is per-vertex coordinates, so
each block maps to an ordinary `AttrType::FLOAT3` attribute on the point
domain, and the default merge policy is already the right one — the values are
coordinates, exactly like `position`, so a split's midpoint is their midpoint.
This holds for relative keys too: a `KeyBlock` stores absolute coordinates and
the delta against `relative_key` is taken at evaluation time, so there is
nothing delta-shaped to interpolate carefully. Every new dyntopo vertex gets a
sensible coordinate in every block for free.

No fork change either, unlike vertex groups: `ShapeKeyPoint.co` for a mesh key
is a plain array property (`rna_key.cc:872`, no custom get/set), so
`key_blocks[i].data.foreach_get("co", buf)` already takes the raw fast path in
both directions.

What is actually left is host-side bookkeeping:

- **Naming and round trip.** One engine attribute per block, on a reserved
  prefix so a user attribute cannot collide with it. Blender's block *order*
  matters (`relative_key` is a reference to another block), so the flush has to
  recreate blocks in order and re-point the references by name.
- **Per-block metadata is not per-element** and so does not belong in an
  attribute: `value`, `slider_min`/`max`, `vgroup`, `relative_key`, `mute`,
  `interpolation`. Snapshot them on enter, reapply after the rebuild — the same
  shape as `_flush_vertex_groups` reading its name table back, and like that
  one it needs the *object*, since `shape_key_add` is an Object method.
- **The active key vs. live positions** is the only genuinely awkward part.
  Vanilla sculpt mode edits the active shape key while displaying the mixed
  result; SculptCore's positions are the mesh's. The cheap first version is to
  carry shape keys as *passengers* — interpolate and restore them, but keep
  refusing to sculpt when a non-basis key is active. That preserves the data
  (which is the whole point of this tier) without taking on the display
  coupling, and it is a much smaller change than the refusal it replaces.

---

## Tier 2 — types with no engine equivalent

These only bite users who author them deliberately, but they are also the ones
where "we log and drop it" is a defensible permanent answer.

### [ ] 2.1 `FLOAT4X4`

Sixteen floats per element, no engine type. Geometry-nodes output, essentially
never authored by hand on a sculpt mesh.

The interpolation question is the real one: lerping matrix components is wrong
for anything with rotation in it, and doing it properly means
decompose/slerp/recompose. `AttrMerge::COPY_SRC0` is an honest answer here and
much cheaper than pretending.

### [ ] 2.2 `STRING`

`CD_PROP_STRING` is a fixed 255-byte `MStringProperty` per element. No engine
type, and a per-element 255-byte column is the wrong storage regardless — this
is the case the `DeformPool`'s interning pattern actually fits best, since
string attributes in practice hold a handful of distinct values repeated across
the mesh.

Merge policy is `COPY_SRC0` and there is nothing to argue about.

Very low priority; a string attribute on a mesh being sculpted is close to
hypothetical.

### [ ] 2.3 `INT8`

Blender's `INT8` is **signed** (-128..127); the engine's `BYTE` is `uint8_t`.
Mapping one to the other directly corrupts negatives.

Cheapest correct fix is to map `INT8` → engine `INT` and narrow on the way
back — 4× the memory for a type nobody uses at scale. A signed `SBYTE` engine
type is the tidier fix if `SHORT2` (1.1) is being added anyway and the enum is
open.

---

## Tier 3 — bridged, but the round trip is worth auditing

Not "missing support" — these already flow, and the question is whether what
comes back is what went in.

### [ ] 3.1 `FLOAT4` is missing purely by omission

Blender has `CD_PROP_FLOAT4`. The engine has `AttrType::FLOAT4`. It is used by
`FLOAT_COLOR`, `BYTE_COLOR` and `QUATERNION` in `_ATTR_TYPE_MAP` — but there is
no plain `'FLOAT4'` entry, so a raw float4 attribute is logged and dropped.

This is a one-line map addition with an existing engine type behind it. Do it
first, if only to shrink the list.

### [ ] 3.2 `QUATERNION` lerps component-wise

Mapped to `FLOAT4` with the default merge policy, so a split's midpoint is the
component-wise average of two quaternions: unnormalized, and wrong outright
when the two are antipodal (`dot < 0`), where it can pass through zero.

Wants `AttrMerge::CUSTOM` doing a proper slerp with a sign flip — the same
handler shape as 1.1, and probably the same commit.

### [ ] 3.3 `BYTE_COLOR` widens to float and comes back

`BYTE_COLOR` is read through the `"color"` RNA property (which converts to
float), carried as `FLOAT4`, and recreated as `BYTE_COLOR` on flush.

Two things to actually verify rather than assume: whether the round trip is
value-preserving for untouched elements, and what color space the lerp happens
in — Blender byte colors are sRGB-encoded and float colors are linear, so if
the widening does not decode, interpolated corners are being blended in the
wrong space. Write a round-trip test before changing anything; it may already
be correct.

### [ ] 3.4 `CD_GRID_PAINT_MASK`

The per-grid sculpt mask on a multires mesh, parallel to `CD_MDISPS`. The
addon converts displacement (`multires.py`) but not this. A multires user who
masks, sculpts, and leaves loses the mask.

Scoped to the multires path, so it belongs with that code rather than with the
attribute bridge.

### [ ] 3.5 `Mesh.mselect` (selection history)

Edit-mode's active-element history. Not CustomData, tiny, and dropped by
`clear_geometry` like everything else. Listed for completeness — the cost of
losing it is that the next edit-mode operator that reads "active vertex" picks
differently. Almost certainly not worth engine storage; the plausible fix is to
save and restore it around the rebuild, host-side.

---

## What of this is actually engine work

Almost none of it, which is worth stating plainly because the list above reads
like an engine backlog and mostly is not one. Verified by reading the call
sites, not the headers.

**Already there, no work needed:**

- **All four domains have attribute groups.** `Mesh` carries `v/e/c/f.attrs`,
  `attrGroupForDomainFlag` maps the `ElemType` bits onto them, and the C API's
  `mesh_elem_domain` (`mesh_c_api.cc:372`) already accepts `EDGE`. So
  `Mesh_writeAttr(m, 2, …)` works today — item 1.2 is entirely addon-side.
- **Edge and face attributes already survive topology operators.** Not by
  interpolation, by row copy: `edge_split.h:89/172` snapshots the parent edge's
  row and restores it onto the child; `edge_collapse.h:551-554` restores onto
  the survivor and `unionBoolAttrRow`s the rows of edges that welded into it;
  `subdivide.h` and `split.h` do the equivalent for faces and corners.
- **The meshlog logs all four domains** (`meshlog_base.h:379-391`), so anything
  stored is already undoable.
- **Adding an `AttrType` is a four-file change.** The only exhaustive switches
  on it are `attribute.h`'s `type_dispatch` and `mesh_serialize.cc`; add the
  enumerator in `attribute_enums.h` and the `T`→type mapping in
  `attribute_base.h` and every generic path — including the GPU upload, which
  goes through `type_dispatch` (`spatial_gpu.cc:201`) — picks it up. A
  `GPUType` is only needed if a shader ever reads it.

**Genuinely missing** — the six items are the
*Engine-side tasklist* at the top of this page; they are
not repeated here.

**Shape keys (1.4) need nothing at all.** `FLOAT3` on the point domain with
the default lerp. The only engine-side question is cost, not capability: N
extra float3 vertex columns grow the meshlog row linearly, so undo memory
scales with the key count. `AttrUse::SCULPT_LAYER` is already exactly this
shape (a float3 vertex passenger column) and is the precedent to measure
against.

## Suggested order

3.1 (one line) → 1.2's logging half (one line, makes the silent case visible) →
1.1 with **E1 + E4** (the real user-facing loss, and the only place engine work
gates addon work) → 3.2 with **E3** (rides along with E4's handler) → 1.3 →
everything else on demand.

**E5** is a decision, not code, and can be recorded at any point. **E2** and
**E6** only make sense as riders on E1.

The fork work runs on its own track, since it lands in a different repo and
gates different things: **F3** first (it unblocks 3.4, which nothing else can),
then **F2** (retires the Object-level detour and the stale-handle trap the
landed bridge lives with), then **F4** (the largest, and the one that would
shrink this whole page rather than tick one line off it). **F5** and **F6** are
not queued.

1.4 (shape keys) is the item with the largest payoff — it is what decides
whether the addon can be pointed at a production asset at all — and its
passenger-only form is mostly marshalling against types the engine already
has. Worth doing early on that basis, not late on the basis of the refusal it
replaces.
