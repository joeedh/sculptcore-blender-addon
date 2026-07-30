# Blender attribute coverage — what the bridge still drops

A tasklist of Blender mesh data the addon does **not** currently hand to the
engine, and what each one would take. Written after the `AttrType::WEIGHTS`
work landed (see
[vertex-group-weights-attribute.md](vertex-group-weights-attribute.md)), which
is the worked example every "needs its own storage type" item below points at.

Verified against `sculptcore_addon/convert.py`,
`engine/source/mesh/attribute_enums.h` and the fork's
`rna_enum_attribute_type_items` as of 2026-07-29, then **audited from scratch
the same day** — the audit killed one queued fork task, split one engine task
into three, and added five tier items. Corrections are folded in below rather
than annotated; *Corrections from the audit* at the end records what changed and
why, so a claim that was wrong once does not come back.

Nothing here is scheduled except **E3** and **E4**, which are being
implemented. The rest is backlog, ordered by "how likely is a user to lose
data".

## Why any of this matters

The bridge only exists because of the **topology-rebuild path**. While the
sculpt session is on the fast path, Blender's CustomData is untouched and every
one of these gaps is invisible. The moment dyntopo (or any remesh/undo that
changes the vertex count) fires, `_flush_topology_rebuild` calls
`mesh.clear_geometry()` and rebuilds — and anything the engine was not holding
is **gone**, silently, with no undo step that brings it back.

`clear_geometry()` is more destructive than its name suggests. It is
`BKE_mesh_clear_geometry_and_metadata` **plus** `BKE_animdata_free`
(`rna_mesh_api.cc:370-378`), so it frees every CustomData domain, `mselect`,
the vertex-group name table, all six active/default layer *designations*
(`clear_attribute_names`, `mesh.cc:1114-1122`) and the mesh's animation data.

So the question for each item is not "does the engine support this type" but
"what does a user lose the first time they touch dyntopo".

## What is bridged today

| Path | Covers |
| --- | --- |
| Dedicated | positions, `.sculpt_mask`, `.sculpt_face_set`, active POINT/`FLOAT_COLOR` color, active UV map, `uv_seam`/`sharp_edge` (keyed by vertex pair), multires displacement, multires paint mask, vertex groups |
| Generic (`_ATTR_TYPE_MAP`) | `FLOAT`, `FLOAT2`, `FLOAT_VECTOR`, `FLOAT_COLOR`, `BYTE_COLOR`, `INT`, `INT32_2D`, `BOOLEAN`, `QUATERNION` — on the `POINT`, `CORNER` and `FACE` domains only |
| Skipped by policy | `position`, every `.`-prefixed layer |

Engine side, for reference: `AttrType` has `FLOAT FLOAT2 FLOAT3 FLOAT4 BOOL INT
INT2 INT3 INT4 BYTE SHORT WEIGHTS`; `BYTE` is `uint8_t`, `SHORT` is `short`,
and there is **no** `SHORT2`/`BYTE2` or any matrix type. `ElemType` does have
`EDGE`.

## Engine-side tasklist

Each item names the tier item that wants it. **E3 and E4 are queued** — they
are prerequisites for three of the items below, and until they land no CUSTOM
merge policy can reach a corner attribute or a host-created layer at all.

- [ ] **E3. Corner-domain merge dispatch.** *Queued.* Today a CUSTOM handler
  can only ever fire on the **vertex** domain. `merge_fn` is invoked from
  exactly one place, `interpAttrs` (`attr_interp.h:250-251`), and all six of its
  call sites pass `m.v.attrs` — `loopcut.h:60`, `subdivide.h:221,306`,
  `edge_split.h:152`, `edge_collapse.h:336`, `triage.cc:440`. Corners go
  through the row path instead, which refuses CUSTOM outright; its own comment
  says why (`attr_interp.h:160-161`): "Both sources are captured rows, not live
  elements, so a CUSTOM handler has nothing to inspect here — it falls back to
  the generic rule."

  That is the real obstacle, not an oversight. `AttrMergeCtx` (`attr_merge.h`)
  carries `mesh`, `grp`, live `src_co`/`src_no`, and `src0`/`src1` as *element
  indices* — but `interpAttrRows`' sources are elements that were already
  killed, so those indices are stale and the group cannot be read at them. The
  work is therefore:

  - A row-shaped handler variant whose sources are the two
    `AttrRowSnapshot::Cell`s rather than live indices. That is sufficient for
    every handler this page wants (**E6** decode/slerp/re-encode and **E7**
    both need only their own two cells' bytes), and it is honest about what is
    knowable at that point.
  - Sibling-column access from a snapshot, for handlers that need it. Cells are
    already index-aligned with `grp.attrs`, so a sibling is a cell lookup, not
    a group lookup — `siblingLayer()` needs a row-based twin.
  - A decision on the **collapse** side, which today does not interpolate
    corners at all: `edge_collapse.h:525` only `restoreAttrRow`s. The sole
    `interpAttrRows` calls in the tree are `edge_split.h:243,245`, the two
    midpoint corners of a split. See **E8**.

  Note `Cell.bytes` is 16 bytes, which fits everything on this page but not a
  `FLOAT4X4` (**2.1**).

- [ ] **E4. A route for binding a merge policy to a host-created layer.**
  *Queued.* `resolveMergePolicy` (`attr_merge.cc:319`) returns `{}` for any
  name that does not start with `.`, with exactly one type-keyed exception
  (`WEIGHTS`). Every entry in `builtin_policies` is a dot-prefixed internal
  layer. And `Mesh_writeAttr` (`mesh_c_api.cc:456`) sets `ref.use` but never
  `ref.merge`.

  So a layer the *host* creates — `custom_normal`, a `QUATERNION` named
  `rotation`, a shape-key column — can never receive `AttrMerge::CUSTOM` under
  any name it is allowed to have. The `WEIGHTS` escape hatch does not
  generalize either: type-keying works there because `WEIGHTS` is unique, while
  `QUATERNION` is mapped onto `_AT_FLOAT4` (`convert.py:489`) and is
  indistinguishable from a colour.

  The cheap and probably right answer is to key on **`AttrUse`**, which the
  c-api already carries end to end and which is exactly the "what this layer
  means" channel this needs: `Mesh_writeAttr` takes `use`, so
  `AttrUse::NORMAL_ENCODED` or `AttrUse::SHAPE_KEY` arriving from the addon
  would select the handler with no name convention and no new parameter. That
  makes **E9** a prerequisite rather than a nicety. A merge-policy setter on
  the c-api is the alternative; it is more general and more rope.

- [ ] **E1. `AttrType::SHORT2`** — a two-component 16-bit type. Wanted by
  **1.6** (the short2 form of `custom_normal`). Four files: the enumerator in
  `attribute_enums.h`, the `T`→type mapping in `attribute_base.h`,
  `type_dispatch` in `attribute.h`, and `mesh_serialize.cc`. `math::short2`
  already exists (`litestl/math/vector.h:439`, via `DEF_VECS(int16_t, short)`),
  so the type itself is free. A `GPUType` too, but only if a shader ever reads
  it.

  Two traps for whoever does it:

  - **The serialize switch is not exhaustive.** `type_dispatch`
    (`attribute.h:411-453`) has no `default:`, so `-Wswitch` will catch a
    missing case there. `scalarSize` (`mesh_serialize.cc:142-152`) ends
    `default: return 4;` — a new `SHORT2` compiles clean and gets a silently
    wrong byte-swap width. Add the case by hand.
  - **The reflection binding table is already wrong.** `attribute_enums.h:177,179`
    register `"Float" → AttrType::NONE` and `"Vec2" → AttrType::FLOAT`. Fix the
    shift while the table is open rather than appending to a broken one.

  **E1 does not depend on E6.** See the note under **1.6**.

- [ ] **E2. A signed byte type** — `BYTE` is `uint8_t` and Blender's `INT8` is
  signed, so the direct mapping corrupts negatives. Wanted by **2.3**. Same
  four files as E1; only worth doing if the enum is already open for E1, since
  the host can otherwise widen to `INT`.

- [ ] **E5. A quaternion slerp merge handler** — wanted by **3.2**.
  Component-wise averaging of two quaternions is unnormalized and passes
  through zero when they are antipodal; the handler needs the `dot < 0` sign
  flip. The handler itself is small and `mergeWeights` is the worked example —
  **the blocker is E4**, since a user layer called `rotation` has no way to ask
  for it today.

- [ ] **E6. An encoded-normal merge handler** — decode, slerp, re-encode.
  Wanted by **1.6**. Needs **E3** (it runs on corners) and **E4** (it runs on a
  host-created layer). Same handler shape as E5.

- [ ] **E7. A merge handler for passenger coordinate columns** — wanted by
  **1.4** (shape keys). On a *split* the default lerp is correct. On a
  **collapse** it is not: the survivor is placed at `merged_co`, which is
  deliberately not the lerp of the endpoints (`edge_collapse.h:336` passes it
  for exactly that reason), so `position` gets the real merged coordinate while
  a passenger float3 column gets `a(1-t) + bt` and the two drift apart. This is
  the same failure `mergeSculptLayerRest` exists to fix, and that one needed
  `AttrMerge::CUSTOM` — which is why **1.4 is not the zero-engine-work item it
  was first written up as**. Needs **E4**; on the vertex domain, so not E3.

- [ ] **E8. Decide the interpolation contract for the edge, face and *corner*
  domains.** No `interpAttrs` call site passes anything but `m.v.attrs`, so all
  three of the other domains get row copy/union, never interpolation. That is
  correct for seam, sharp, material and face set, and defensible for crease and
  bevel weight (an edge collapse welding two different creases takes the first
  rather than the max). **Corners are the case that actually matters**, because
  that is where UV maps live: a split interpolates only its two midpoint
  corners (`edge_split.h:243,245`) under the generic rule, and a collapse does
  not interpolate corners at all (`edge_collapse.h:525` restores). Whether a UV
  should blend across a dyntopo collapse is a live question, not a settled one.
  E3 makes the answer implementable; this item is deciding it.

- [ ] **E9. `AttrUse` tags for encoded normals and shape keys.** Was optional;
  **E4 promotes it to a prerequisite** if the policy is keyed on `AttrUse`. It
  also does what it was originally listed for — keeps the semantics across a
  round trip the way `UV` and `COLOR` do.

**1.2** (the edge domain), **1.5**, **1.6**'s host half, **1.7**, **1.8**,
**1.9** and **3.4** are pure addon work against types and domains the engine
already carries.

## Fork-side tasklist — what Blender's Python API is missing

The third leg. `Mesh.vertex_group_data_get`/`_set` (fork commit `9a098f3`) is
the precedent for both of these: engine-agnostic, useful to any exporter or
rigging script, and added because the Python-loop alternative was untenable.

**F2 and F4 are queued, in that order.** F5 and F6 are not. *(F3 was queued and
has been withdrawn — it was already implemented; see* Checked and found present
*below.)*

- [ ] **F2. `Mesh`-level vertex group names.** The `vertex_group_names`
  ListBase lives on `Mesh` and `clear_attribute_names` frees it
  (`mesh.cc:1115`) — but RNA exposes the names only through
  `Object.vertex_groups`; `rna_mesh.cc` has no vertex-group property at all.
  Three costs, all of which the landed bridge pays: restoring names needs the
  *Object*, so `_flush_vertex_groups` hangs off `flush(ob)` instead of the mesh
  rebuild that actually dropped them; `ob.vertex_groups.clear()` + `.new()`
  invalidates live Python `VertexGroup` handles (a real trap — it broke the
  bridge's own test); and there is no bulk set, so it is one `.new()` per
  group. A `vertex_group_names_get`/`_set` pair is the same shape and roughly
  the same size as F1 — it is F1's missing other half. Landing it simplifies
  `_flush_vertex_groups` and retires the stale-handle workaround in its test.
- [ ] **F4. A bulk topology setter.** The rebuild is `clear_geometry()` +
  three `add()` calls + four `foreach_set` calls + `update(calc_edges=True)`
  (`convert.py:732-740`). `add()` preserves attribute layers but only *grows*;
  dyntopo also removes, which is why `clear_geometry()` is unavoidable, which
  is why this whole page exists. A `Mesh.set_topology(positions, corner_verts,
  face_offsets)` would be one call instead of eight, and could keep the layer
  *declarations* (name/type/domain/active flags) and the metadata that
  `clear_attribute_names` currently frees across the rebuild — the addon would
  write values instead of recreating layers, and **1.7** would evaporate. It
  could also take edges directly rather than making Blender re-derive what the
  engine already knows, which is **1.5**. Biggest lever here, and the biggest
  ask: it is the only item that shrinks this page rather than ticking one line
  off it.
- [ ] **F5. `Mesh.mselect`.** No RNA. Freed by `mesh_clear_geometry`
  (`mesh.cc:1105`). Minor; wanted by **3.5**.
- [ ] **F6. (optional) Bulk shape-key data get/set on `Mesh`.** Nothing is
  strictly *missing* for **1.4** — `Object.shape_key_add` and
  `KeyBlock.data.foreach_get("co")` both work — but it is Object-level and
  per-block, so it has F2's shape. Worth doing only if 1.4's block-by-block
  restore turns out to be slow or awkward in practice.

**Checked and found present** — recorded so these do not get proposed:

- **`CD_GRID_PAINT_MASK` is already exposed, and the addon already uses it.**
  This was queued as F3 on the strength of "the string does not appear anywhere
  in `makesrna`", which was a false negative — the work is in BKE, not RNA
  boilerplate. The fork has `Object.multires_mask_to_vert_values` /
  `multires_mask_from_vert_values` (`rna_object_api.cc:465,484`) over
  `multiresModifier_maskToVertValues`/`_maskFromVertValues`
  (`multires_reshape.cc:200,230`), whose `reshape_context.grid_paint_masks`
  *is* the layer. `multires.py:228,249` calls both, wired from `convert.py:228,
  945, 975, 997`. **Search BKE before concluding a CustomData layer is
  unreachable** — `CD_MDISPS` has the same shape.
- Every Blender attribute type has an RNA value struct, including
  `Short2AttributeValue` (which is what the encoded `custom_normal` is),
  `Float4x4AttributeValue`, `Float4AttributeValue` and `ByteIntAttributeValue`.
  All are reachable with `foreach_get`.
- `foreach_get`/`foreach_set` handle `PROP_RAW_SHORT` and `PROP_RAW_INT8` with
  a matching buffer format (`foreach_compat_buffer`, `bpy_rna.cc:6022`), so
  16-bit and 8-bit attributes take the fast raw path given an `int16`/`int8`
  numpy array. **1.6 and 2.3 are therefore engine-and-addon gaps, not RNA
  gaps** — the host can already read the data.
- `ShapeKeyPoint.co` for a mesh key is a plain array property
  (`rna_key.cc:872`, no custom get/set, over an `rna_iterator_array_begin`
  collection at `rna_key.cc:585`), so `key_blocks[i].data.foreach_get("co",
  buf)` takes the raw fast path in both directions. **1.4 needs no fork
  change** — unlike vertex groups.
- Active color, default color, active UV and active attribute indices are all
  exposed, so **1.7** is addon work, not a fork gap. The RNA being present is
  not the same as anything using it — which is exactly the trap 1.7 records.

---

## Tier 1 — data a normal user can lose today

Numbered in the order they were written, **not** in priority order — see
*Suggested order*. By the tier's own metric (how many users, how often) the
ranking is roughly 1.6 → 1.7 → 1.3 → 1.8 → 1.2/1.5 → 1.4 → 1.1 → 1.9.

### [ ] 1.1 `custom_normal` — but only its encoded form

Superseded in scope by the audit; kept as the number the rest of the page
references. **See 1.6.** The short version: `custom_normal` has *two* storage
forms, the float3 forms are already bridged, and only the short2 corner form is
missing.

### [ ] 1.2 The whole `EDGE` domain

`_DOMAIN_TO_ENGINE` is `{'POINT': 1, 'CORNER': 4, 'FACE': 16}`. An edge-domain
attribute is skipped **silently** — it does not even get the "unsupported" log
line that an unsupported *type* gets, because the domain check
(`convert.py:530-532`) comes before the type check (`convert.py:533`).

Concretely dropped: `crease_edge`, `bevel_weight_edge`, `freestyle_edge`, and
every user-authored edge attribute. Subdivision creases surviving a sculpt is
the one most likely to be noticed.

The engine has `ElemType::EDGE`, so the blocker is not storage — it is
**identity**. The engine derives its own edges, so edge *indices* do not
correspond across the boundary in either direction. The addon already solved
this once, for the two boundary bool flags: `_load_edge_flags` /
`_flush_edge_flags` (`convert.py:359-403`) key edges by vertex pair. That is
not a per-edge hash lookup — it packs sorted vertex pairs into int64 keys and
uses `np.argsort` + `np.searchsorted`, and it builds the sorted key table
**once** and reuses it across attributes (`if bl_keys is None`, line 383). So
generalizing it is O(E log E) once plus O(E log E) per attribute, all in numpy.
The cost is not the reason to hesitate; measure rather than assume either way.

See also **1.5** — bridging edge attributes does not save loose edges, which
die for an unrelated reason.

First step regardless of the rest: **log the skip**, so an edge attribute is at
least as visible as an unsupported type.

### [ ] 1.3 Selection and hide state

`.select_vert` / `.select_edge` / `.select_poly` and `.hide_vert` /
`.hide_edge` / `.hide_poly` are dot-prefixed, so the blanket "never bridge a
dot-prefixed layer" rule (`attr.name.startswith(".")`, `convert.py:528`) drops
them. Leaving sculpt mode after a topology change therefore hands the user a
mesh with their edit-mode selection and their hidden geometry reset.

Hide is the sharper half: a user who hid part of a mesh, sculpted, and came
back to find it all visible has lost work state, not just a selection.

The engine already has `AttrUse::SELECT` for the box-modeling case, so the
receiving end exists. The task is a named-exception list checked *before* the
dot rule at `convert.py:528` — not a loosening of the rule, which is right for
topology links. Note this is a separate test from `_SKIP_ATTR_NAMES`, which is
just `{"position"}` (`convert.py:497`).

**Cheapest item in this tier**: no engine work, no fork work, no identity
problem, and the domains involved are already bridged.

### [ ] 1.4 Shape keys — one `FLOAT3` point attribute per key block

Currently a hard refusal at `enter()` (`convert.py:97`), which means the addon
cannot be used on any rigged or corrective-shape asset — most production
geometry.

**The storage needs nothing new.** A `KeyBlock` is per-vertex coordinates, so
each block maps to an ordinary `AttrType::FLOAT3` attribute on the point
domain. This holds for relative keys too: a `KeyBlock` stores absolute
coordinates and the delta against `relative_key` is taken at evaluation time,
so there is nothing delta-shaped to interpolate carefully.

**The merge policy does need something new — see E7.** The first write-up of
this item claimed the default policy was already correct because "the values
are coordinates, exactly like `position`". That holds for a split and fails for
a collapse, where the survivor is placed at `merged_co` rather than at the lerp
of the endpoints. `position` gets the real merged coordinate; a passenger
column gets the lerp; they disagree and the shape offset shifts. The precedent
cited in support of the claim — `AttrUse::SCULPT_LAYER`, a float3 vertex
passenger column — is precisely the case that needed a CUSTOM handler
(`mergeSculptLayerRest`) for this exact reason.

No fork change, unlike vertex groups: see *Checked and found present*.

What is left is host-side bookkeeping:

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

### [ ] 1.5 Loose edges do not survive at all

Independent of **1.2**, and not fixed by it. `_flush_topology_rebuild` ends at
`mesh.update(calc_edges=True)` (`convert.py:740`), which *derives* edges from
faces. Any wire or loose edge — a curve guide, a hair guide, a skin-modifier
armature, a modeling scaffold — is gone after the first rebuild whether or not
its attributes were bridged.

`validate()` warns about loose geometry at enter (`convert.py:105-106`), so the
condition is already detected; nothing acts on it. Two possible answers: round
loose edges through the engine as real edges, or snapshot and re-add them
host-side after the rebuild. **F4** would make the first one natural by taking
edges directly instead of re-deriving them.

### [ ] 1.6 The encoded (`short2`) form of `custom_normal`

`custom_normal` has two storage forms and the bridge's coverage differs between
them:

- **Free normals** — `FLOAT_VECTOR` on `POINT`, `FACE` or `CORNER`
  (`Mesh::normals_domain`, `mesh_normals.cc:301-322`). **Already bridged
  today** by `_ATTR_TYPE_MAP`'s `FLOAT_VECTOR` entry (`convert.py:483`), with
  the default lerp, which is roughly right for a vector and normalizes on use.
- **The corner-fan encoding** — `CD_PROP_INT16_2D` on `CORNER`, produced by
  `mesh_normals.cc:1657-1658` (the legacy converter at
  `mesh_legacy_convert.cc:2494` is versioning, not the live producer). Not
  dot-prefixed, so the bridge reaches it, finds no `_ATTR_TYPE_MAP` entry, logs
  *"is unsupported and will be dropped on topology change"*, and drops it.

So the loss is real but narrower than first written: it is the baked,
spherically-encoded case, which is what a hard-surface asset with baked normals
actually carries.

Two pieces of work, and **they are separable** — the original write-up said
"shipping the type without the interpolator is worse than useless… do both or
neither", which is wrong:

- **Storage** (**E1**, or widen to `INT2` host-side and narrow on the way
  back). Widening is smaller and the memory cost is per-corner; measure before
  assuming it matters.
- **Interpolation** (**E6**, which needs **E3** and **E4**). The values are
  spherically encoded, so a component-wise lerp of two of them is meaningless
  near the poles.

The separability matters because it decides the order. Both merge paths copy
`src0` for integer-vector types rather than lerping — `defaultMerge`'s
non-floating `Scalar` branch, and `interpAttrRows` at `attr_interp.h:186-197`.
A `SHORT2` (or `INT2`) column therefore gets **nearest-copy semantics for
free** and can never be lerped into garbage. E1 alone is safe and useful:
nearest-copy of a baked normal onto a new corner is a defensible answer, and it
is unambiguously better than dropping the layer. E6 upgrades it.

### [ ] 1.7 Active/default color and UV-map designations

`clear_attribute_names` (`mesh.cc:1114-1122`) frees all six of
`active_color_attribute`, `default_color_attribute`, `active_uv_map_attribute`,
`default_uv_map_attribute`, `stencil_uv_map_attribute` and
`clone_uv_map_attribute`. `_flush_bridged_attrs` (`convert.py:559-587`) only
calls `attributes.new()` and restores none of them.

So after one dyntopo pass, *which* UV map renders and *which* color attribute
is the render default are reset — on a mesh with one of each this is invisible,
and on a multi-UV asset it is a wrong render. Every user, every rebuild.

This is the item that was previously mis-filed under "checked and found
present" because the RNA exists. The RNA existing answers "can it be restored",
not "is it restored". Pure addon work: snapshot six strings on enter, write
them back after the rebuild.

### [ ] 1.8 Attributes created or deleted mid-session

`session.bridged_attrs` is built once, in `_load_bridged_attrs`
(`convert.py:526-556`), and `_flush_bridged_attrs` replays exactly that list.
Nothing refreshes it.

Two failures fall out. An attribute a user or an operator creates *during* the
session is not in the list, so it is silently dropped by the next topology
rebuild — even though its type is fully supported. An attribute deleted during
the session is still in the list, so the rebuild **resurrects it** with whatever
values the engine last held.

The whole framing of this page is "data the bridge never reaches"; this is data
the bridge reached at the wrong time, and it is the one item here that can
produce a layer the user explicitly removed.

Cheapest fix is to re-scan `mesh.attributes` against the recorded list at flush
time rather than trusting the snapshot. The engine columns are keyed by name,
so reconciling is a set difference.

### [ ] 1.9 Animation data on the Mesh datablock

`rna_Mesh_clear_geometry` does not stop at the geometry — it calls
`BKE_animdata_free(&mesh->id, false)` immediately afterwards
(`rna_mesh_api.cc:373`). Drivers, actions and NLA strips on the *Mesh* ID are
destroyed on every topology flush.

Unlike everything else on this page there is no partial preservation, no
identity problem and no engine storage question: it is not per-element data at
all. Snapshot `mesh.animation_data` before the rebuild and restore it after, or
push the whole rebuild behind **F4** so it never happens.

Narrower in practice than it sounds — shape-key drivers live on the `Key` ID,
not the Mesh — but it costs one save/restore to close and is currently a silent
total loss.

### [ ] 1.10 `Mesh.skin_vertices` (`CD_MVERT_SKIN`)

A per-vertex layer carrying skin radii and root/loose flags, with its own RNA
(`rna_mesh.cc:3159`, `rna_def_skin_vertices` at 2834, `MVertSkin` sdna at
2868). It is **not** a generic attribute, so `mesh.attributes` never yields it
and the bridge structurally cannot see it; `CustomData_free(&mesh.vert_data)`
(`mesh.cc:1093`) destroys it.

Any Skin-modifier asset loses every radius at the first rebuild. The data is
two floats and an int per vertex, all types the engine has — the work is a
dedicated path like the `uv_seam`/`sharp_edge` one, since there is no generic
route to it. Niche, but total when it bites.

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

Note also that `AttrRowSnapshot::Cell.bytes` is 16 bytes, so a 64-byte type
would need the row snapshot widened or spilled — a second reason this is not a
drive-by.

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
type (**E2**) is the tidier fix if `SHORT2` is being added anyway and the enum
is open.

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

Wants **E5**. Blocked on **E4** — the layer is host-created and user-named, and
`resolveMergePolicy` cannot reach it. Type-keying is not available as a
shortcut either: `QUATERNION` arrives as `_AT_FLOAT4`, identical to a colour.

### [ ] 3.3 `BYTE_COLOR`'s round trip is asymmetric

Read through the `"color"` RNA property, carried as `FLOAT4`, recreated as
`BYTE_COLOR` on flush. The colour-space question this item was opened with is
answered in the RNA, and the answer is the *opposite* of the original worry —
but there is a real bug next to it.

`rna_ByteColorAttributeValue_color_get` (`rna_attribute.cc:734-739`) does
`srgb_to_linearrgb_uchar4` **and** `IMB_colormanagement_rec709_to_scene_linear`,
so the widening decodes properly and the engine lerps in scene-linear. Correct.

The setter (`rna_attribute.cc:741-748`) computes a `rec709[]` array and then
**ignores it**, calling `linearrgb_to_srgb_uchar4(&mlcol->r, values)` on the
scene-linear values directly. The round trip is exact only when scene-linear
equals rec709 — the default config — and drifts under any other scene colour
space.

That is a fork-side bug in `rna_attribute.cc`, not an addon one, and it affects
anything that reads and writes byte colours through RNA. Worth a round-trip
test to pin the behaviour, then a one-line fix.

### [x] 3.4 `CD_GRID_PAINT_MASK` — done

The per-grid sculpt mask on a multires mesh, parallel to `CD_MDISPS`. Already
bridged: `multires.py:228,249` (`import_mask`/`export_mask`) over the fork's
`Object.multires_mask_to_vert_values`/`_from_vert_values`, wired at
`convert.py:228, 945, 975, 997`. The original entry claimed a multires user
loses the mask; they do not. See *Checked and found present*.

### [ ] 3.5 `Mesh.mselect` (selection history)

Edit-mode's active-element history. Not CustomData, tiny, freed by
`mesh_clear_geometry` (`mesh.cc:1105`) like everything else. Listed for
completeness — the cost of losing it is that the next edit-mode operator that
reads "active vertex" picks differently. Almost certainly not worth engine
storage; the plausible fix is to save and restore it around the rebuild,
host-side, which needs **F5**.

---

## What of this is actually engine work

Less than the list above reads like, but more than the first draft of this
section claimed. Verified by reading call sites, not headers.

**Already there, no work needed:**

- **All four domains have attribute groups.** `Mesh` carries `v/e/c/f.attrs`,
  `attrGroupForDomainFlag` maps the `ElemType` bits onto them, and the C API's
  `mesh_elem_domain` (`mesh_c_api.cc:372`) already accepts `EDGE`. So
  `Mesh_writeAttr(m, 2, …)` works today — item 1.2 is entirely addon-side.
- **Edge, face and corner attributes already survive topology operators.** Not
  by interpolation, by row copy: `edge_split.h:89/172` snapshots the parent
  edge's row and restores it onto the child; `edge_collapse.h:551-554` restores
  onto the survivor and `unionBoolAttrRow`s the rows of edges that welded into
  it; `edge_collapse.h:402-410/517-525`, `triangulate.h`, `symmetrize.h` and
  `edge_flip.h` do the equivalent for faces and corners.
- **The meshlog logs all four domains** (`meshlog_base.h:378-392`), so anything
  stored is already undoable.

**Present but weaker than it looks:**

- **Adding an `AttrType` is a four-file change, but only one of those switches
  is compiler-enforced.** `type_dispatch` (`attribute.h:411-453`) is genuinely
  exhaustive. `mesh_serialize.cc`'s `scalarSize` ends in `default: return 4;`.
  See the traps under **E1**.
- **`AttrMerge::CUSTOM`, `AttrRef::merge_fn` and `AttrMergeCtx` all exist** —
  but they are reachable only from the **vertex** domain (**E3**) and only for
  **dot-prefixed internal layers or `WEIGHTS`** (**E4**). Every CUSTOM handler
  this page wants is on the wrong side of both restrictions. This is the single
  biggest correction the audit produced: three tier items were written up as
  "needs a small handler, the machinery exists", and the machinery does not
  reach them.

**Genuinely missing** — the nine items in the *Engine-side tasklist* at the top
of this page; they are not repeated here.

## Suggested order

Addon-only, no dependencies, in ascending size — do these regardless of what
happens on the engine track:

1. **3.1** — one line in `_ATTR_TYPE_MAP`.
2. **1.2's logging half** — one line; makes the silent edge case visible.
3. **1.7** — snapshot six strings, write them back. Every user, every rebuild,
   currently a silent wrong render on any multi-UV asset.
4. **1.3** — a named-exception list before the dot rule. Cheapest Tier-1 item,
   no engine or fork work, and hidden geometry coming back visible is work
   state, not cosmetics.
5. **1.9** — save/restore `animation_data` around the rebuild.
6. **1.8** — reconcile `bridged_attrs` at flush instead of trusting the enter
   snapshot. The only item that can resurrect a layer the user deleted.

Engine track, in dependency order:

7. **E3 + E4** — queued. Nothing else on the engine side moves until a CUSTOM
   handler can reach a corner and a host-created layer. E4 probably wants
   **E9** (the `AttrUse` tags) as its keying mechanism, so scope that decision
   first.
8. **E1** — independent of the above, and safe alone: a `SHORT2` column gets
   nearest-copy semantics from both merge paths for free. Landing it turns
   **1.6** from "normals are dropped" into "normals are approximate", which is
   strictly better. Fix the `scalarSize` default and the reflection table while
   in there.
9. **E6** (finishes 1.6), **E5** (finishes 3.2), **E7** (unblocks 1.4) — all
   three are small once E3/E4 exist, and they are the same handler shape, so
   they likely land together.
10. **E8** is a decision, not code, and can be recorded at any point — but E3
    changes what answers are available, so record it after E3 rather than
    before. **E2** is a rider on E1.

Fork track, separate repo, gates different things:

11. **F2** — retires the Object-level detour and the stale-handle trap the
    landed vertex-group bridge lives with.
12. **F4** — the largest, and the one that would shrink this page rather than
    tick one line off it: it subsumes **1.7**, **1.8** and **1.9** outright and
    makes **1.5** natural. **F5** and **F6** are not queued.

**1.4 (shape keys) is still the item with the largest payoff** — it is what
decides whether the addon can be pointed at a production asset at all. It is no
longer a zero-engine-work item (it needs **E7**), but E7 is one small handler
and the rest is marshalling against types the engine already has. Worth doing
early on that basis, not late on the basis of the refusal it replaces.

**1.10** and everything in Tier 2 stay on demand.

## Corrections from the audit

Recorded so a claim that was wrong once does not come back. Each was checked
against source.

- **F3 was already implemented.** Concluding a CustomData layer is unreachable
  from `makesrna` grep results alone is unsound; `CD_GRID_PAINT_MASK` is
  exposed through BKE-backed `Object` methods the addon was already calling.
- **`interpAttrs` is never called with `m.c.attrs`.** All six call sites pass
  `m.v.attrs`. Corners are in the same row-copy bucket as edges and faces, and
  `interpAttrRows` explicitly declines CUSTOM. This invalidated the old E4 as
  written and produced **E3**.
- **No merge policy can bind to a host-created layer.** `resolveMergePolicy`
  short-circuits on names without a `.` prefix; `Mesh_writeAttr` never sets
  `ref.merge`. Produced **E4**; it also means the old E3 (quaternion slerp) was
  never implementable as described.
- **"Ship E1 without the interpolator and it is worse than useless" was
  wrong.** Integer-vector types copy `src0` in both merge paths, so there is no
  meaningless-lerp failure mode to guard against.
- **Shape keys are not zero engine work.** The collapse case needs **E7**; the
  `SCULPT_LAYER` precedent cited in support of "the default policy is already
  right" is itself a CUSTOM handler written for that exact failure.
- **`custom_normal` has two storage forms** and the float3 ones are already
  bridged. 1.1's original scope was too wide; 1.6 replaces it.
- **`mesh_serialize.cc`'s switch is not exhaustive**, so "the compiler will
  catch a missing case" held for only one of the two switches.
- **`clear_geometry()` destroys more than CustomData** — animation data
  (**1.9**) and six layer designations (**1.7**), neither previously listed.
- **Three items were missing entirely**: loose edges (**1.5**), mid-session
  attribute changes (**1.8**), `skin_vertices` (**1.10**).
- **3.3's colour-space question was answerable by reading**, and the real bug
  is in the setter, not the widening.
- **"Checked and found present" answered the wrong question for 1.7.** The RNA
  existing does not mean anything uses it. Entries in that section must state
  what was checked, not just that something exists.
- Line references corrected: the domain check is `convert.py:530-532` (524 is
  the colour-attribute assignment); the rebuild block is `convert.py:732-740`;
  `vertex_group_names` is freed by `clear_attribute_names` (`mesh.cc:1115`),
  not `mesh_clear_geometry`; the live producer of encoded normals is
  `mesh_normals.cc:1657-1658`, not the legacy converter; `_SKIP_ATTR_NAMES` is
  `{"position"}` and the dot rule is a separate test at `convert.py:528`.
