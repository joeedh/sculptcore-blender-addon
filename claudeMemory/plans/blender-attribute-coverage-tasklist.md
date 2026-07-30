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
into three, and added five tier items.

**Pressure-tested 2026-07-30** by four adversarial passes (engine track, addon
quick-wins, integration/lifecycle, prioritisation), each briefed to find the
reason an item should *not* be built. That pass was much harsher than the audit:
an audit checks whether the page says true things about the code, and nearly
every citation held. The pressure test attacked the *plan* and broke three
engine items, four Tier-1 items, one fork item, and the suggested order. It also
invalidated one item this page had already marked **done**. Corrections are
folded in below; *Corrections from the audit* and *Corrections from the pressure
test* at the end record what changed and why, so a claim that was wrong once
does not come back.

Nothing here is currently scheduled. **E3 and E4 were queued and are now
withdrawn as written** — see their entries. The rest is backlog, ordered by "how
likely is a user to lose data".

Two framing corrections that touch every item, recorded here because reading a
single entry without them is misleading:

- **The read point is wrong.** Almost every "restore" on this page was written
  as *snapshot at `enter()`, reapply after the rebuild*. There is no second read
  point in the session (`refresh` is disabled for custom-undo modes,
  `ed_undo.cc:222-231`; `resync_if_diverged` only tests vertex count), so an
  enter-time snapshot is stale the moment the user changes anything, and
  reapplying it silently reverts their edit — permanently, on every subsequent
  flush. The correct shape is **read immediately before `mesh.clear_geometry()`**
  inside `_flush_topology_rebuild`. That is smaller than what was proposed and it
  dissolves **1.7**, **1.9**, **3.5**, **1.10** and 1.4's block metadata at once.
  **1.8 is not an item, it is this rule**; see its entry.
- **Everything here is plain-Mesh only.** `_enter_multires` (`convert.py:185-252`)
  bridges displacement and grid mask and *nothing else* — no face sets, colors,
  UVs, edge flags, vertex groups or generic attributes, and `session.bridged_attrs`
  is empty for multires sessions (`session.py:82`). `flush()` also returns at
  `convert.py:1039-1041` before the whole rebuild path. So `clear_geometry()` is
  never reached on a multires object, the premise of this page does not apply
  there, and multires has its own losses that are *not* listed. See
  *Multires scope* below.

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

Each item names the tier item that wants it.

**E3 and E4 were queued; both are withdrawn as written.** The pressure test
broke this section harder than any other. In order:

- **E4 is unbuildable as specified.** Keying the merge policy on `AttrUse`
  cannot work — see its entry.
- **E3 has no consumer left.** It was justified by E6 and E7. E6 is now struck
  (1.6's redesign carries custom normals as a plain corner `FLOAT3`, whose
  default lerp is adequate), and E7 turns out to
  be vertex-domain, which E3 explicitly is not about. Nothing on this page needs
  corner-domain CUSTOM dispatch today. Keep the analysis; drop the queue slot.
- **E7 is the item that should have been first.** Its stated defect does not
  exist, but there is a *different*, real one-line bug underneath it.

The old framing — "nothing moves on the engine side until E3 and E4 land" — was
the single most expensive claim on this page: it blocked the only engine item
that is both real and cheap behind two that are not.

- [ ] **E7. `collapseEdge` skips attribute merging entirely at the default
  blend.** **Do this first.** *Rewritten — the original premise was wrong and
  the real bug is smaller and worse.*

  The original claim was that a passenger float3 column drifts from `position`
  because the survivor is placed at `merged_co`, which is not the lerp of the
  endpoints. Under dyntopo that is false: `collapseEdge`'s only caller passes no
  `merged_co` at all, and the default midpoint *is* the `t=0.5` lerp, so the
  passenger column and `position` agree exactly.

  The actual defect is the gate one line up (`edge_collapse.h:328-337`):

  ```cpp
  collapseEdge(Mesh &m, int edge,
               std::optional<litestl::math::float3> merged_co = std::nullopt,
               float blend = 0.0f, ...)
  ...
  if (blend > 0.0f) {
    const litestl::math::float3 *mco = merged_co.has_value() ? &merged_co.value() : nullptr;
    interpAttrs(m.v.attrs, v_keep, v_keep, v_kill, blend, &m, mco);
  }
  ```

  `blend` defaults to `0.0f`, so on the default path `interpAttrs` is **never
  called** — no lerp, no CUSTOM handler, no `mergeWeights`, no
  `mergeSculptLayerRest`. The survivor keeps `v_keep`'s values verbatim while
  its *position* is relocated to the midpoint unconditionally. So every vertex
  attribute in the engine — masks, colours, weights, sculpt layers, and any
  passenger column 1.4 would add — is nearest-copy-from-one-side across a
  collapse, and which side wins is whichever the topology code happened to name
  `v_keep`.

  That is a live correctness bug in shipped behaviour, not a prerequisite for a
  backlog item. Fixing it is roughly five lines (call `interpAttrs`
  unconditionally, with the blend the caller asked for, defaulting to the same
  0.5 the position uses). It needs **neither E3 nor E4**.

  Do this before anything else on the engine track, and re-check 1.4's
  requirements afterwards — with the gate fixed, shape keys as passenger
  `FLOAT3` columns are plausibly correct under the *default* policy, which is
  what the original 1.4 write-up assumed and could not justify.

- [ ] **E3. Corner-domain merge dispatch.** *No consumer — analysis retained,
  do not schedule.* Today a CUSTOM handler
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
  *Withdrawn as written — the proposed mechanism cannot work. The problem is
  real; the solution was not.* `resolveMergePolicy` (`attr_merge.cc:319`) returns `{}` for any
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

  **The `AttrUse` route does not work.** Two independent reasons, either of
  which is fatal on its own:

  - **Ordering.** The policy is stamped inside `AttrGroup::ensure`
    (`attribute.h:771-775`), which resolves it from `(type, name)` and assigns
    `attr.merge`/`attr.merge_fn` *while constructing the `AttrRef`* — before any
    caller has a reference to set `use` on. `Mesh_writeAttr` sets `ref.use`
    strictly afterwards, on the returned ref. So at the only point where the
    policy is chosen, `use` does not yet exist. Passing `use` down into
    `ensure()` is possible but is a signature change across every call site,
    which is a different (and larger) task than the one this item describes.
  - **`AttrUse` is a bitmask, not an enum.** `attribute_enums.h:104-114`
    declares `_AttrUse` with `1<<0 … 1<<6` and wraps it in
    `MAKE_FLAGS_CLASS(AttrUse, _AttrUse, int)`. A layer can legitimately carry
    several bits at once, so "select the handler by `AttrUse`" has no defined
    answer for a combined value, and adding `NORMAL_ENCODED`/`SHAPE_KEY` bits
    does not fix that — it makes it more likely.

  The honest alternatives, neither of which has been costed:

  - **Thread `use` into `ensure()`** and resolve the policy from
    `(type, name, use)`. Requires deciding the bitmask-dispatch question above
    (probably: a precedence order over the bits, documented).
  - **Extend the name table past its dot gate.** `resolveMergePolicy` returns
    early for any name not starting with `.` (`attr_merge.cc:319-330`); an
    explicit allowlist of host-created names, checked before that early return,
    is much smaller than either of the above and is enough for
    `custom_normal`-style fixed names. It is not enough for user-chosen names,
    which is what 3.2's `rotation` layer actually is.
  - **A merge-policy setter on the c-api** — most general, most rope, and
    pushes the decision to the addon.

  A **dedicated `AttrType`** is the fourth route, and it is the one with a
  working precedent: `resolveMergePolicy` bypasses the dot gate for
  `AttrType::WEIGHTS` specifically because it is type-keyed
  (`attr_merge.cc:319-325`, and the comment there says exactly this). It reaches
  a host-created, user-named layer with no ordering problem and no bitmask
  ambiguity. It costs an enum value plus the four-file type addition per
  semantic — worth it where the semantic is genuinely distinct, not worth it as
  a general mechanism. **1.6 considered and did not need it**; 3.2's quaternion
  layer is the remaining candidate, since `QUATERNION` is otherwise
  indistinguishable from a colour.

  **E9 is not promoted by this item** — the `AttrUse` keying that would have
  promoted it does not work. E9 stands on its own original merit.

- [ ] ~~**E1. `AttrType::SHORT2`**~~ — **struck.** Wanted only by **1.6**, whose
  redesign (see its entry) carries custom normals through the engine as an
  existing `FLOAT3` and re-encodes host-side. Nothing else on this page asks for
  a two-component 16-bit type.

  Two findings from it are worth keeping, because they apply to *any* future
  `AttrType` addition (**E2** included):

  - **The serialize switch is not exhaustive.** `type_dispatch`
    (`attribute.h:411-453`) has no `default:`, so `-Wswitch` will catch a
    missing case there. `scalarSize` (`mesh_serialize.cc:142-152`) ends
    `default: return 4;` — a new type compiles clean and gets a silently wrong
    byte-swap width. Add the case by hand.
  - **The reflection binding table is already wrong.** `attribute_enums.h:177,179`
    register `"Float" → AttrType::NONE` and `"Vec2" → AttrType::FLOAT`. Fix the
    shift the next time the table is open rather than appending to a broken one.

- [ ] **E10. `type_dispatch`'s missing `default:` is a silent-success hole in
  the c-api.** Related to the above but a separate bug. Because `type_dispatch`
  (`attribute.h:411-453`) has no `default:` label, an `AttrType` value that is
  out of range — an addon passing a stale or wrong integer through
  `Mesh_writeAttr` — falls straight through the switch without invoking the
  callback. The function then returns success having written nothing. Add a
  `default:` that fails loudly. Small, and it converts a whole class of
  bridge bugs from silent data loss into an error message.

- [ ] **E2. A signed byte type** — `BYTE` is `uint8_t` and Blender's `INT8` is
  signed, so the direct mapping corrupts negatives. Wanted by **2.3**. A
  four-file type addition (see the traps under the struck E1). With E1 gone
  there is no enum change to ride on, so this is only worth doing if 2.3 is
  worth doing — and 2.3's host-side widening to `INT` is the cheaper answer.

- [ ] **E5. A quaternion slerp merge handler** — wanted by **3.2**.
  Component-wise averaging of two quaternions is unnormalized and passes
  through zero when they are antipodal; the handler needs the `dot < 0` sign
  flip. The handler itself is small and `mergeWeights` is the worked example.
  **Blocked on E4** — a user layer called `rotation` has no way to ask for it
  today, and E4 has no agreed mechanism. Of E4's surviving routes, the
  **dedicated `AttrType`** one is the only one that reaches a user-*named*
  layer, so this item and E4's resolution are the same decision.

- [ ] ~~**E6. An encoded-normal merge handler**~~ — **struck.** It existed to
  decode/slerp/re-encode the short2 corner form inside the engine. **1.6**'s
  redesign never puts the encoded form in the engine at all: the addon decodes
  on read and re-encodes on flush, so the engine sees an ordinary corner
  `FLOAT3` and the default lerp of two unit directions (renormalized at encode
  time) is adequate. This item was the last named consumer of **E3**.

- [ ] **E7** — *moved to the top of this section and rewritten.* The original
  entry described a `merged_co`-vs-lerp drift for passenger coordinate columns.
  That drift does not occur under dyntopo, and the real bug is that no merge
  runs at all. See the entry above.

- [ ] **E11. A welded edge drops one side's non-bool values.** On a collapse,
  edges that weld into the survivor are combined with `unionBoolAttrRow`
  (`edge_collapse.h:551-554`), which is correct for `uv_seam` and `sharp_edge`
  and does nothing at all for anything else — so of two welding edges carrying
  different `crease_edge` or `bevel_weight_edge` values, one is silently
  discarded. Today this is invisible because **1.2** means those layers never
  reach the engine. It becomes a real defect the moment 1.2 lands, and it is
  the same question as **E8** for the edge domain: max, first, or average.
  Listed here so 1.2 does not land on top of it unnoticed.

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

  Reprice: this is **not** "a decision, not code". The edge half of it is
  `unionBoolAttrRow`'s gap (**E11**) and the corner half needs the row-handler
  work in E3 before any answer other than the current one can be written. Call
  it a decision *plus* whichever of E3/E11 the answer implies.

- [ ] **E9. `AttrUse` tags for encoded normals and shape keys.** Stays
  optional. E4 does *not* promote it — the `AttrUse` keying that would have is
  withdrawn (see E4). What it still does is what it was originally listed for:
  keep the semantics across a round trip the way `UV` and `COLOR` do.

- [ ] **E12. `_bridge_use` mis-tags every corner `FLOAT2` as a UV map.** Addon
  side, filed here because it corrupts the engine's `AttrUse` channel that E9
  and E4 both lean on: any `FLOAT2` attribute on the corner domain is tagged
  `AttrUse::UV` regardless of what it is. A user's per-corner float2 — a flow
  field, a packed pair — is then treated as a UV map by anything downstream that
  trusts the tag, including the collapse wedge blending added in P11. One
  predicate change; worth doing before E9 adds more meaning to the channel.

**1.5**, **1.6**'s host half, **1.7**, **1.8** and **1.9** are pure addon work
against types and domains the engine already carries. **1.2 is not** — see its
entry; the c-api has no edge-identity export, so the edge domain needs engine
work first. **3.4 is no longer done** — see its entry.

## Fork-side tasklist — what Blender's Python API is missing

The third leg. `Mesh.vertex_group_data_get`/`_set` (fork commit `9a098f3`) is
the precedent for both of these: engine-agnostic, useful to any exporter or
rigging script, and added because the Python-loop alternative was untenable.

**F2 and F4 are queued, in that order — but see the note under F2: F4 deletes
F2's reason to exist, so the order is backwards.** F5 is not queued. *(F3 was
queued and has been withdrawn — it was already implemented; see* Checked and
found present *below. F6 is struck for the same reason.)*

- [ ] **F2. `Mesh`-level vertex group names.** *Order note: F4 subsumes this.*
  If `set_topology` preserves the layer declarations and the name table across
  the rebuild, the names are never lost, and a `vertex_group_names_get`/`_set`
  pair has nothing left to restore. Doing F2 first means writing a bulk
  save/restore path whose only caller F4 then deletes. Either do F4 first, or
  do F2 knowing it is interim. The rest of the entry stands on its own merits
  (it is still F1's missing other half, and it still retires the stale-handle
  trap) — it is the *queue position* that is wrong.

  The `vertex_group_names`
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
- [ ] **F7. An encode entry point for corner-fan custom normals.** New; wanted
  by **1.6**, which is the only reason it exists. The addon can already *read*
  custom normals in either storage form through `Mesh.corner_normals`
  (decoded float3, raw `foreach_get` fast path). It cannot write the short2
  form back: `bke::mesh::corner_space_custom_normal_to_data`
  (`mesh_normals.cc:763`) is the per-corner encoder and is not exposed, and the
  only RNA-reachable route, `mesh_set_custom_normals`, is the wrong shape — see
  1.6.

  What is wanted is a `Mesh` method taking a corner-length float3 array and
  writing the `custom_normal` `Int16_2D` layer: run `normals_calc_corners`
  **once** against the mesh's *current* sharpness to build the
  `CornerNormalSpace` per corner, then encode each input direction into it. No
  `sharp_edge` write, no fan-divergence scan, no second normals pass — roughly
  half the work of `mesh_set_custom_normals` and none of its side effects.
  Engine-agnostic and useful to any importer that already knows its own
  sharpness, which is the same argument that landed
  `Mesh.vertex_group_data_get`/`_set`.
- [ ] ~~**F6. Bulk shape-key data get/set on `Mesh`.**~~ **Struck — this is a
  second F3.** It was proposed because `KeyBlock.data.foreach_get("co")` is
  per-block and Object-level. The bulk path already exists: `ShapeKey.points`
  (`rna_key.cc:1058`) is the flat collection over the whole block, and the
  *Checked and found present* entry below already establishes that
  `ShapeKeyPoint.co` takes the raw `foreach_get` fast path. As with F3, this was
  concluded missing from a grep that looked at the wrong sibling property.

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
- **`ShapeKey.points`** (`rna_key.cc:1058`) is the flat per-block collection,
  i.e. the bulk path F6 was proposed to add. F6 is struck on this.
- **`Mesh.corner_normals`** (`rna_mesh.cc:3029-3045`) is a
  `MeshNormalValue` collection over `rna_iterator_array_get`, so
  `foreach_get("vector", buf)` takes the raw fast path. It yields the mesh's
  *resolved* corner normals — custom normals decoded and folded in, whichever
  storage form they were in. **1.6's read half needs no fork change**, and it
  needs no format detection either.
- The six layer designations of **1.7** are all reachable, but *not* as six
  strings, which is what that item originally assumed:
  `active_color_attribute` and `default_color_attribute` are direct settable
  string properties (`rna_attribute.cc:1297-1299`); the four UV designations
  are reached through layer proxies instead — `uv_layers[i].active` /
  `.active_render` for active and default, and `Mesh.uv_layer_clone` /
  `uv_layer_stencil` (plus their `_index` siblings, `rna_mesh.cc:889-966`,
  `1064-1094`) for clone and stencil. So 1.7 stays addon work, with a different
  shape. The RNA being present is not the same as anything using it — which is
  exactly the trap 1.7 records.

---

## Tier 1 — data a normal user can lose today

Numbered in the order they were written, **not** in priority order — see
*Suggested order*. By the tier's own metric (how many users, how often) the
ranking is roughly **1.8 → 1.7 → 1.3 → 1.6 → 1.5 → 1.2 → 1.4 → 1.9 → 1.10**.

*(The old ranking led with 1.6. The pressure test moved 1.8 to the front: it is
the only item that can produce a layer the user explicitly deleted, and — once
restated as "read at the destruction point" rather than "rescan at flush" — it
is also the mechanism that closes 1.7, 1.9, 3.5 and 1.10. Everything else in
this tier is a special case of it.)*

**Every item below is plain-Mesh only.** See *Multires scope* at the end of the
tier for what a multires session loses instead; it is a different and shorter
list, and none of these fixes touch it.

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

**This is not addon-only work, and the "What of this is actually engine work"
section was wrong to say so.** That section reasoned from
`attrGroupForDomainFlag` and `mesh_elem_domain` accepting `EDGE` to the
conclusion that `Mesh_writeAttr(m, 2, …)` closes the item. It does not, because
the c-api's *entire* edge surface is three functions:

- `Mesh_edgeCount` (`mesh_c_api.cc:620`)
- `Mesh_writeEdgeFlagsByVerts` (`:636`) — bool payload only, keyed by vertex
  pair, which is precisely the special case the addon already uses
- `Mesh_readEdgeFlags` (`:665`) — sparse, returns only the *flagged* edges

There is no general edge read, and nothing exports engine edges in an order the
host can pair with its own. `Mesh_writeAttr`'s values array is in engine
live-iteration order, so writing an edge column works and reading it back means
nothing. The missing piece is an engine-side **edge identity channel** — the
vertex-pair export that `Mesh_readEdgeFlags` already does for its sparse case,
generalized. File that as engine work — and land **E11** with it, which is the
merge question the same change raises.

See also **1.5** — bridging edge attributes does not save loose edges, which
die for an unrelated reason.

First step regardless of the rest: **log the skip**, so an edge attribute is at
least as visible as an unsupported type. That half genuinely is one addon line.

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

**Cheapest item in this tier — for four of its six layers.** Three corrections
to the original write-up:

- **The `_edge` half is blocked on 1.2.** `.select_edge` and `.hide_edge` are
  edge-domain, so they hit the same wall everything else in 1.2 does. What is
  actually cheap is the vert and poly halves: `.select_vert`, `.select_poly`,
  `.hide_vert`, `.hide_poly` — all on domains already bridged. Do those; the
  edge pair rides on 1.2.
- **`AttrUse::SELECT` does not mean the engine acts on it.** It is a passenger
  tag; there is no hide concept in the engine at all, so hidden geometry is
  still fully sculptable during the session and comes back hidden but modified.
  That is better than losing the flag and it is not the same as respecting it —
  say so in the commit rather than implying hide is honoured.
- **Consider folding in the neighbouring pins while the exception list is
  open**: `.uv_select_vert` / `.uv_select_edge` / `.uv_select_pin` and the
  `.pn.<uv>` pin layers are dropped by the same rule and are lost work state in
  exactly the same way, on a mesh whose UVs are already being bridged.

### [ ] 1.4 Shape keys — one `FLOAT3` point attribute per key block

Currently a hard refusal at `enter()` (`convert.py:97`), which means the addon
cannot be used on any rigged or corrective-shape asset — most production
geometry.

**Read the blocker below before scheduling this. It is not the largest-payoff
early item the old *Suggested order* called it.**

**`clear_geometry()` deliberately does not free `Mesh.key`, and nothing
resizes it.** `mesh_clear_geometry`'s own doc comment
(`mesh.cc:1079-1090`) lists shape keys among the things it intentionally leaves
alone, so after a dyntopo rebuild the mesh has N′ vertices and every `KeyBlock`
still has `totelem == N`. `BKE_keyblock_update_from_mesh` (`key.cc:1665`) guards
that mismatch with a `BLI_assert` and then does a raw `memcpy` — an assert is a
no-op in a release build, so a shipped Blender writes N floats into an
N′-element allocation. **That is a heap overflow, not a data-loss bug**, and it
is reachable from the current `enter()` refusal being relaxed by one line.

So the refusal at `convert.py:97` is a **safety interlock**, not the policy stub
this item originally described. Relaxing it requires, before anything else, a
resize path for `Mesh.key` across the rebuild — which is fork work with no item
number yet, and which is the real gate on 1.4. Everything below assumes that is
solved.

**The storage needs nothing new.** A `KeyBlock` is per-vertex coordinates, so
each block maps to an ordinary `AttrType::FLOAT3` attribute on the point
domain. This holds for relative keys too: a `KeyBlock` stores absolute
coordinates and the delta against `relative_key` is taken at evaluation time,
so there is nothing delta-shaped to interpolate carefully.

**The merge policy needs E7, but not for the reason previously given.** The
audit's version of this paragraph said the default policy fails on a collapse
because the survivor is placed at `merged_co` rather than at the lerp of the
endpoints. That is not what happens under dyntopo — no caller passes
`merged_co`, and the default midpoint *is* the `t=0.5` lerp, so a passenger
float3 column and `position` would agree exactly. What actually breaks it is
E7's real bug: `interpAttrs` is not called at all on the default collapse path
(`edge_collapse.h:331`), so a passenger column is nearest-copy-from-one-side
while the position moves to the midpoint. **With E7 fixed, the default policy
is correct here** and 1.4 needs no CUSTOM handler — which is close to what the
first write-up claimed, arrived at by a different route.

No fork change *for the shape-key data itself*, unlike vertex groups: see
*Checked and found present*. The `Mesh.key` resize above is a separate fork
gap.

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
`mesh.update(calc_edges=True)` (`convert.py:740`). Any wire or loose edge — a
curve guide, a hair guide, a skin-modifier armature, a modeling scaffold — is
gone after the first rebuild whether or not its attributes were bridged.

**The mechanism is not what this item said.** It is not that `calc_edges`
"derives edges from faces" and therefore discards the loose ones:
`mesh_calc_edges` runs with `keep_existing_edges=true`, so it *preserves* any
edge already present, loose ones included. They die one step earlier —
`clear_geometry()` removed every edge, and the rebuild block calls
`verts.add()`, `loops.add()` and `polygons.add()` but never `edges.add()`, so
by the time `update()` runs there is nothing left to keep. The distinction
matters because it changes the fix: **re-adding the loose edges before
`update()` is sufficient**, and no change to `calc_edges` behaviour is needed.

`validate()` warns about loose geometry at enter (`convert.py:105-106`), so the
condition is already detected; nothing acts on it. Two possible answers: round
loose edges through the engine as real edges — which needs 1.2's edge identity
channel and is therefore engine work — or snapshot them immediately before
`clear_geometry()` and re-add them host-side, which needs nothing new and is
the cheap version. **F4** would make the first one natural by taking edges
directly instead of re-deriving them.

### [ ] 1.6 The encoded (`short2`) form of `custom_normal` — *design settled*

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

**Design settled 2026-07-30. It replaces the E1+E6 plan entirely — both of
those are now struck.** The old plan bridged the *encoded* form: add a
`SHORT2` engine type to store it and an encoded-normal merge handler to
interpolate it, which dragged in E3 (corner-domain CUSTOM dispatch) and E4
(binding a policy to a host-created layer), neither of which is buildable
today. Carrying the encoding through the engine was the mistake — the engine
has no business holding a representation that is only meaningful relative to a
smooth-fan structure dyntopo is about to destroy.

Decode on read, carry directions, re-encode on write:

- **Read — no fork work.** `Mesh.corner_normals` (`rna_mesh.cc:3029-3045`)
  yields the mesh's resolved corner normals as float3 through
  `rna_iterator_array_get`, so `foreach_get("vector", buf)` is the raw fast
  path. It reports the same thing whichever storage form the file used, so the
  addon does not need to detect the form to read it.
- **Engine — no engine work.** Store as an ordinary `FLOAT3` on the corner
  domain, a type and domain already bridged. The default lerp of two unit
  directions is not a slerp, but it is a reasonable direction (it fails only
  for near-antipodal pairs, which adjacent corner normals are not), and the
  encode step renormalizes anyway. **No `SHORT2`, no CUSTOM handler, no E3, no
  E4.**
- **Addon — the one new piece of bookkeeping.** Record per layer, in the
  session, that `custom_normal` arrived as `Int16_2D`/`CORNER`, so the flush
  writes back the form the user's file had rather than silently converting it
  to float3. This is the round-trip-fidelity requirement, and it is *addon*
  state: the engine never needs to know.
- **Write — one new fork entry point (F7).** The obvious candidate,
  `mesh_set_custom_normals` (`mesh_normals.cc:1652-1698`), is the wrong shape
  twice over. It does write the short2 form
  (`lookup_or_add_for_write_span<short2>("custom_normal", Corner)`, `:1657`) —
  but it also runs the fan-divergence scan at `:1463-1521`, which **adds sharp
  edges** wherever the requested normals disagree across a fan, and writes
  `sharp_edge` back (`:1662`). It also runs `normals_calc_corners` twice by
  design (`:1422-1427`: "this function *is not* performance-critical… just call
  it twice!"), which it is not, on every dyntopo flush.

  The `sharp_edge` write is **additive only** — `:1466-1467` says outright
  "this code *will never* unsharp edges!" — so it cannot clobber the addon's
  bridged sharpness. The failure mode is creep: each flush can add sharp edges
  and none removes them, so a long dyntopo session accumulates faceting the
  user never asked for. Clamp rather than accumulate.

  Hence **F7**: encode against the *current* sharpness with one
  `normals_calc_corners` pass and `corner_space_custom_normal_to_data`
  (`mesh_normals.cc:763`) per corner, no `sharp_edge` write, no divergence scan.

**Stated limitation, by design.** Bit-exact round-tripping the short2 form
through a topology change is impossible in principle: the encoding is a pair of
angles relative to a per-corner `CornerNormalSpace` derived from the smooth fan,
and dyntopo destroys the fan. Re-encoding into the *new* fan is the best
achievable, and the error is bounded by the encoder's own quantization on the
corners that survive unchanged. A session that never triggers a rebuild
round-trips exactly.

**Net effect on the rest of the page:** E1 struck, E6 struck, E3 loses its last
consumer, E4 loses one of its two justifications (3.2 keeps the other), F7
added.

### [ ] 1.7 Active/default color and UV-map designations

`clear_attribute_names` (`mesh.cc:1114-1122`) frees all six of
`active_color_attribute`, `default_color_attribute`, `active_uv_map_attribute`,
`default_uv_map_attribute`, `stencil_uv_map_attribute` and
`clone_uv_map_attribute`. `_flush_bridged_attrs` (`convert.py:559-587`) only
calls `attributes.new()` and restores none of them.

So after one dyntopo pass, *which* UV map renders and *which* color attribute
is the render default are reset. Every user, every rebuild.

This is the item that was previously mis-filed under "checked and found
present" because the RNA exists. The RNA existing answers "can it be restored",
not "is it restored". Three corrections:

- **It is five of six, not six.** `active_color_attribute` is already restored
  — `convert.py:322` writes it back after the rebuild. The other five are not.
- **The impact was under-sold.** "On a mesh with one of each this is invisible"
  is wrong for UVs. With no active UV designation,
  `draw_cache_impl_mesh.cc:236-243` skips UV extraction **entirely**, so a
  single-UV textured mesh renders untextured after the first dyntopo pass — not
  a wrong-map render on a multi-UV asset, a no-texture render on the common
  one. This is the most visible bug on the page.
- **Not six strings.** Only the two colour designations are settable strings
  (`rna_attribute.cc:1297-1299`). The four UV ones go through layer proxies:
  `uv_layers[i].active` / `.active_render` for active and default,
  `Mesh.uv_layer_clone` / `uv_layer_stencil` (or their `_index` siblings,
  `rna_mesh.cc:889-966`, `1064-1094`) for clone and stencil. Snapshot the
  *names*, resolve back to indices after the rebuild.

Two ordering hazards for whoever writes it:

- `attributes.new()` auto-assigns the active colour designation in several
  places (`rna_attribute.cc:828-829, 871`; `rna_mesh.cc:1873-1874`), so
  recreating layers mutates the very state being restored. Restore **after**
  all layers exist, not as each is created.
- The colour setter does no validation — it `MEM_SAFE_DELETE`s and
  `BLI_strdup`s whatever string it is handed. Writing back a name whose layer
  failed to recreate leaves a dangling designation rather than an error.

Still pure addon work. The correct read point is immediately before
`clear_geometry()`, per **1.8** — an enter-time snapshot reverts any change the
user made to these during the session.

### [ ] 1.8 Attributes created or deleted mid-session — **and the rule the rest of this tier follows**

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

**This is not item #6 in a list of ten. It is the rule the other nine follow,
and it was mis-scheduled as a peer.** Every "snapshot on enter, restore after
the rebuild" in this tier has the same defect this item describes: there is no
second read point in the session, so an enter-time snapshot is stale from the
first user edit onward, and reapplying it silently reverts that edit on every
subsequent flush — permanently, with no undo step. Specifically:

- `refresh` is never called for a custom-undo mode (`ed_undo.cc:222-231`
  short-circuits when `bl_use_custom_undo` is set), so the bridge has no
  periodic re-read.
- `resync_if_diverged` compares vertex counts only, so any change that keeps
  the count — renaming a layer, deleting and re-adding one, changing the active
  UV map — is invisible to it.

**The fix is a read point, not a rescan schedule**: read the host state
immediately *before* `mesh.clear_geometry()` inside `_flush_topology_rebuild`,
where it is guaranteed current and guaranteed about to be destroyed. That
single placement closes **1.7**, **1.9**, **3.5**, **1.10** and 1.4's per-block
metadata along with this item, and it is *smaller* than the per-item enter-time
snapshots they each proposed. Reconciling the attribute list itself is then a
set difference against the engine's name-keyed columns.

Two things worth knowing about when this fires. `_flush_topology_rebuild` runs
**zero** times during a stroke and is instead triggered by
`ED_editors_flush_edits_ex` — memfile-undo-pushing operators, saves, renders,
scene switches, exporters — so it can fire on operations that have nothing to
do with sculpting. During an undo *decode* it can run up to twice per step.
Neither changes the fix; both mean "on flush" is not "occasionally".

### [ ] 1.9 Animation data on the Mesh datablock

`rna_Mesh_clear_geometry` does not stop at the geometry — it calls
`BKE_animdata_free(&mesh->id, false)` immediately afterwards
(`rna_mesh_api.cc:373`). Drivers, actions and NLA strips on the *Mesh* ID are
destroyed on every topology flush.

Unlike everything else on this page there is no partial preservation, no
identity problem and no engine storage question: it is not per-element data at
all.

**But it is not the cheap save/restore this item claimed, and it is not addon
work.** `Object.animation_data` and `Mesh.animation_data` are both declared
`PROP_EDITABLE`-cleared with no setter (`rna_animation.cc:1616-1620`), so
Python cannot assign an `AnimData` to an ID at all — there is nothing to
"restore it after" with. Worse, `BKE_animdata_free` `MEM_delete`s the struct, so
a Python reference taken before the rebuild is dangling afterwards, not merely
stale; reading through it is undefined behaviour, not a failed restore.

Deep-copying the contents (drivers, F-curves, modifiers, NLA strips) through the
RNA that *is* writable is possible and is a substantial amount of code for a
narrow case. The realistic answers are both fork-side: **F4** (never destroy it)
or a `Mesh.animation_data` assignment/copy entry point. Re-filed out of the
addon-only list on that basis.

Narrower in practice than it sounds — shape-key drivers live on the `Key` ID,
not the Mesh — and now more expensive than it sounds too. Currently a silent
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

Cheaper interim: it is per-vertex and not per-element-*semantic*, so a snapshot
taken at the **1.8** read point plus a re-add after the rebuild preserves it for
the count-preserving case at a fraction of the cost of a bridged path.

### [ ] 1.11 Particle systems referencing vertex and face indices

Added by the pressure test; not previously listed. `ParticleData.num` and
`num_dmcache` are indices into the mesh's vertices and faces. A dyntopo rebuild
renumbers both, and nothing remaps them, so every particle on a hair or emitter
system is left pointing at whatever now occupies its old index — the system does
not fail, it silently relocates.

Not CustomData and not a mesh attribute, so like **1.10** the bridge
structurally cannot see it. Unlike 1.10 there is no correct remap available
either: the engine does not preserve vertex identity across dyntopo, so the
honest first version is to **detect and warn at enter** — the same shape as
`validate()`'s loose-geometry warning — rather than to promise a fix.

### Multires scope

Recorded because every item above silently assumes a plain-Mesh session and
none of them says so.

`_enter_multires` (`convert.py:185-252`) bridges **displacement and grid paint
mask, and nothing else** — no face sets, colours, UVs, edge flags, vertex
groups or generic attributes; `session.bridged_attrs` is left empty
(`session.py:82`). `flush()` returns at `convert.py:1039-1041` before the
topology-rebuild path is reached, so `clear_geometry()` never runs on a multires
object and the destruction this page is about does not happen there.

The consequence cuts both ways: **multires sessions lose nothing to
`clear_geometry()`, and gain nothing from any fix on this page.** Their losses
are a different, shorter list — attributes that are simply not bridged in the
first place, plus **3.4**'s level gating below. If multires attribute coverage
is wanted, it is a separate page.

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

### [ ] 3.4 `CD_GRID_PAINT_MASK` — **re-opened; the exchange is gated to the top level**

The per-grid sculpt mask on a multires mesh, parallel to `CD_MDISPS`. The
plumbing is bridged: `multires.py:228,249` (`import_mask`/`export_mask`) over
the fork's `Object.multires_mask_to_vert_values`/`_from_vert_values`, wired at
`convert.py:228, 945, 975, 997`. On that basis this was marked **done**. It is
not.

Every export is gated on being at the top subdivision level:

```python
# _flush_multires, convert.py:1021-1026
if session.multires_active_level == session.multires_level:
    multires.export_mask(ob, depsgraph, session.mesh_ptr, session.multires_map)
```

and `set_multires_level` (`convert.py:992-999`) likewise exports only on a
top→non-top transition and imports only on non-top→top. So **a mask painted at
a non-top level is never written back to `CD_GRID_PAINT_MASK` and dies with the
session.**

This is not an edge case. `_enter_multires` (`convert.py:246-248`) *descends* to
the modifier's `sculpt_levels` on entry:

```python
sculpt_level = min(max(md.sculpt_levels, 1), level)
if sculpt_level != level:
    set_multires_level(ob, sculpt_level)
```

so any asset whose `sculpt_levels` is below its `levels` — the ordinary
configuration for a heavy multires mesh — starts the session at a level where
mask painting is silently discarded. The original entry's claim that "a multires
user does not lose the mask" holds only for a user sitting at the top level.

The fix is either to export at whatever level is active (mapping through the
same grid correspondence the top-level path uses) or, if that is not sound, to
refuse mask painting below the top level rather than accepting strokes that go
nowhere. **Marking this done was the pressure test's most direct catch**: the
item was checked off against the existence of the plumbing, not against the
condition under which the plumbing runs.

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
  `Mesh_writeAttr(m, 2, …)` compiles and runs.

  **It does not follow that item 1.2 is addon-side, and the original version of
  this bullet said it did.** Storage existing is not the same as the data being
  addressable: the c-api's whole edge surface is `Mesh_edgeCount` (:620),
  `Mesh_writeEdgeFlagsByVerts` (:636, bool only) and `Mesh_readEdgeFlags`
  (:665, sparse). Nothing exports engine edges in an order the host can pair
  with its own, so a written edge column cannot be read back meaningfully. 1.2
  needs an engine-side edge identity channel first. See its entry.
- **Edge, face and corner attributes already survive topology operators.** Not
  by interpolation, by row copy — and note that **vertex attributes do not
  survive a collapse by interpolation either**, because `interpAttrs` is gated
  behind `blend > 0.0f` and the default caller passes 0 (**E7**). Row copy:
  `edge_split.h:89/172` snapshots the parent
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
  the audit's version of this page wanted was on the wrong side of both
  restrictions.

  The pressure test then removed most of the demand: 1.6 no longer needs a
  CUSTOM handler (it carries directions, not an encoding), and 1.4 no longer
  needs one either (E7's real fix makes the default policy correct). **3.2's
  quaternion slerp is the only remaining CUSTOM consumer on this page**, and of
  E4's surviving routes only a dedicated `AttrType` reaches it. The restriction
  is still real; what changed is that almost nothing is behind it.

**Genuinely missing** — the items in the *Engine-side tasklist* at the top of
this page; they are not repeated here.

## Suggested order

*Rewritten after the pressure test. The previous order led with engine items
that are unbuildable, scheduled `animation_data` as an addon quick win when
Python cannot write it, and put the governing lifecycle rule sixth.*

**First, because it is a live bug in shipped behaviour rather than a backlog
item:**

1. **E7** — remove the `blend > 0.0f` gate in `collapseEdge`. Today no vertex
   attribute is merged on a dyntopo collapse: masks, colours, weights and
   sculpt layers all take one endpoint's value verbatim while the position moves
   to the midpoint. ~5 lines, no dependencies. Re-check 1.4's requirements after.
2. **3.4** — either export the grid paint mask at the active level or refuse
   painting below the top one. Currently strokes at a non-top level are accepted
   and discarded, and entering at `sculpt_levels` puts users there by default.

**Then the addon quick wins, in ascending size:**

3. **3.1** — one line in `_ATTR_TYPE_MAP`. The only item on this page that
   survived the pressure test completely unchanged.
4. **1.2's logging half** — one line; makes the silent edge-domain skip visible.
   The rest of 1.2 is engine work.
5. **1.7** — restore the five unrestored layer designations at the **1.8** read
   point. The most visible bug here: with no active UV designation the draw
   cache skips UV extraction entirely, so an ordinary single-UV textured mesh
   renders untextured after one dyntopo pass.
6. **1.3's vert and poly halves** — a named-exception list before the dot rule.
   The edge halves ride on 1.2. Consider folding in the `.uv_select_*` pins.
7. **E12** — stop tagging every corner `FLOAT2` as a UV map. One predicate,
   and it should land before E9 puts more weight on that channel.
8. **E10** — a `default:` in `type_dispatch`, so a bad `AttrType` through the
   c-api errors instead of returning success having written nothing.

**Then the one structural change, which is what most of this tier actually
wants:**

9. **1.8, restated as a read point** — read host state immediately before
   `mesh.clear_geometry()` rather than snapshotting at `enter()`. This is not a
   peer of the items above it; it is the rule they follow, and doing it early
   makes 1.7, 3.5, 1.10 and 1.4's block metadata into small additions to one
   existing call site instead of five independent snapshot mechanisms. It also
   closes the resurrect-a-deleted-layer case, which nothing else does.

**Engine track, what is left of it:**

10. **1.2's engine half** — an edge identity channel (generalize
    `Mesh_readEdgeFlags`' vertex-pair export). Unblocks the edge domain, 1.3's
    edge halves, and makes 1.5's engine-side answer available. **E11** (welded
    edges drop one side's non-bool values) must land with it or the new columns
    arrive already lossy.
11. **E4** — decide the mechanism. Not the `AttrUse` keying this page proposed;
    of the four routes listed, the dedicated `AttrType` is the only one that
    reaches a user-named layer and it has a working precedent in `WEIGHTS`.
    Only **3.2/E5** are waiting on it, so this can wait too.
12. **E8/E3** — the corner interpolation contract, and the row-handler work if
    the answer needs it. No consumer today. **E2** is a rider on 2.3.

**Fork track, separate repo:**

13. **F7** — the custom-normal encode entry point. Small, self-contained, and
    it is the only thing standing between 1.6 and a complete round trip.
14. **F4** — the largest, and the one that would shrink this page rather than
    tick one line off it: it subsumes **1.7**, **1.8** and **1.9** outright,
    makes **1.5** natural, and **deletes F2's reason to exist**, which is why
    F2's queue slot ahead of it is backwards.
15. A **`Mesh.key` resize path** — no item number yet, and the actual gate on
    1.4. Without it, relaxing the `enter()` refusal is a release-build heap
    overflow (`key.cc:1665` asserts and then `memcpy`s regardless).

**1.4 (shape keys) is no longer "the largest payoff, do it early".** It is
still what decides whether the addon can be pointed at a production asset, but
the refusal at `convert.py:97` is a safety interlock over a memory-safety bug,
not a policy stub — see its entry. It moves behind item 15 and behind E7.

**1.9** is re-filed as fork work: `animation_data` is not Python-assignable and
the struct is freed, so there is nothing to restore it with.

**1.10**, **1.11** and everything in Tier 2 stay on demand.

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

## Corrections from the pressure test

Same convention as above, from the 2026-07-30 adversarial pass. The audit
checked whether the page described the code correctly and it largely did; this
pass attacked whether the *plan* would work, and most of what it broke had
survived the audit intact.

**Killed outright:**

- **1.9 is not addon work.** `animation_data` is `PROP_EDITABLE`-cleared with
  no setter (`rna_animation.cc:1616-1620`), so Python cannot assign it;
  `BKE_animdata_free` `MEM_delete`s the struct, so a pre-rebuild Python
  reference dangles rather than merely going stale. It was scheduled as an
  addon quick win.
- **E4 is unbuildable as specified.** `resolveMergePolicy` is called from inside
  `AttrGroup::ensure` (`attribute.h:771-775`) *while constructing the ref*,
  before any caller can set `use`; and `AttrUse` is a bitmask
  (`attribute_enums.h:104-114`, `MAKE_FLAGS_CLASS`), which has no defined
  single-handler dispatch. Both are fatal to the proposed mechanism
  independently.
- **E7's stated defect does not occur.** No dyntopo caller passes `merged_co`,
  and the default midpoint *is* the `t=0.5` lerp, so passenger columns and
  `position` agree. The real bug is one line up: `if (blend > 0.0f)`
  (`edge_collapse.h:331`) skips `interpAttrs` entirely on the default path, so
  **no vertex attribute is merged on a collapse at all**. Smaller than the
  proposed fix, worse in effect, and it needs neither E3 nor E4.
- **1.4 is not the largest-payoff early item.** `mesh_clear_geometry`
  deliberately does not free `Mesh.key` (`mesh.cc:1079-1090`) and nothing
  resizes `KeyBlock.totelem`; `BKE_keyblock_update_from_mesh` (`key.cc:1665`)
  is a `BLI_assert` followed by a raw `memcpy`, so in a release build relaxing
  the `enter()` refusal is a heap overflow. The refusal is an interlock, not a
  stub.
- **3.4 was marked done and is not.** Both mask exports are gated on
  `session.multires_active_level == session.multires_level`
  (`convert.py:1021-1026`, `992-999`), and `_enter_multires` descends to
  `md.sculpt_levels` on entry (`convert.py:246-248`), so the default
  configuration for a heavy multires asset is one where painted mask is
  silently discarded. Checked off against the plumbing existing rather than the
  condition under which it runs.
- **F6 is a second F3.** `ShapeKey.points` (`rna_key.cc:1058`) already is the
  flat bulk path; the item was concluded missing from the slower per-block
  `.data` sibling.
- **1.2 is not addon-only.** The c-api's entire edge surface is `Mesh_edgeCount`,
  `Mesh_writeEdgeFlagsByVerts` (bool, vertex-pair-keyed) and
  `Mesh_readEdgeFlags` (sparse). `Mesh_writeAttr(m, 2, …)` running is not the
  same as the data being addressable — nothing exports engine edges in a
  host-pairable order.

**Restructured:**

- **The read point was wrong across the whole tier.** `refresh` is disabled for
  custom-undo modes (`ed_undo.cc:222-231`) and `resync_if_diverged` tests only
  vertex count, so an enter-time snapshot is stale from the user's first edit
  and reapplying it silently reverts them. Read immediately before
  `clear_geometry()` instead. **1.8 is that rule, not an item beside it**, and
  it closes 1.7, 1.9, 3.5, 1.10 and 1.4's metadata at once.
- **1.6 was redesigned rather than corrected.** Carrying the *encoded* form
  through the engine required E1 + E6 + E3 + E4. Decoding on read
  (`Mesh.corner_normals` is already a raw-fast-path float3 collection),
  carrying `FLOAT3`, and re-encoding host-side needs **none** of them — one new
  fork entry point (**F7**) and a per-layer note of the arrival format. E1 and
  E6 are struck on this, and E3 loses its last consumer. `mesh_set_custom_normals`
  is the wrong write target: it also runs the fan-divergence scan
  (`mesh_normals.cc:1463-1521`), which adds sharp edges, and by its own comment
  (`:1422-1427`) is not performance-critical, which a per-flush path is.
- **The engine track's dependency claim was inverted.** "Nothing moves until E3
  and E4" put the one cheap, real engine fix (E7) behind two that cannot be
  built. E3 and E4 now have almost no consumers left; E7 leads.
- **F2 is scheduled ahead of the item that deletes it.** F4 preserving the layer
  declarations across the rebuild leaves `vertex_group_names_get`/`_set` with
  nothing to restore.
- **E8 is not "a decision, not code".** Its edge half is E11 and its corner half
  needs E3 before any new answer is writable.

**Under- or mis-stated:**

- **1.7's impact.** Not "invisible on a mesh with one UV map" — with no active
  UV designation, `draw_cache_impl_mesh.cc:236-243` skips UV extraction
  entirely, so a single-UV textured mesh renders **untextured**. Also five of
  six, not six: `active_color_attribute` is already restored
  (`convert.py:322`). And the four UV designations are layer proxies, not
  strings.
- **1.5's mechanism.** `mesh_calc_edges` runs with `keep_existing_edges=true`
  and preserves loose edges. They die because `clear_geometry()` removed them
  and the rebuild never calls `edges.add()` — so re-adding them before
  `update()` is a sufficient fix, with no change to `calc_edges`.
- **1.3's scope.** Two of its six layers are edge-domain and blocked on 1.2, and
  `AttrUse::SELECT` is a passenger tag — the engine has no hide concept, so
  hidden geometry stays sculptable during the session.
- **Multires was never in scope and the page never said so.** `_enter_multires`
  bridges displacement and grid mask only, `bridged_attrs` is empty, and
  `flush()` returns before the rebuild path (`convert.py:1039-1041`). No item
  here applies to a multires session; their losses are a separate list.

**Added:**

- **E10** — `type_dispatch` has no `default:`, so an out-of-range `AttrType`
  falls through the switch and `Mesh_writeAttr` returns success having written
  nothing.
- **E11** — welded edges are combined with `unionBoolAttrRow` only, so one
  side's `crease_edge`/`bevel_weight_edge` is dropped. Latent until 1.2 lands.
- **E12** — `_bridge_use` tags every corner `FLOAT2` as `AttrUse::UV`.
- **1.11** — particle `num`/`num_dmcache` indices are silently relocated by a
  rebuild, with no correct remap available.
- **A `Mesh.key` resize path** on the fork side, as 1.4's actual gate.

**Survived unchanged:** **3.1**. It is one line in `_ATTR_TYPE_MAP` over an
engine type that already exists, and nothing was found against it.
