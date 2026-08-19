# Grid-element attribute domains + de-gating the brush rosters

**Status:** plan, rev 2 — **P0a–P3 landed** (engine `080d0ac` / `182dc4e` /
`0a18195` / `e5ffc03` / `513ed34` + P3, addon `a7389b6` / `a36aae8` + P3,
2026-08-17/18); P4 next. Every brush roster in the engine is gone: what
runs on grids is now decided by each kernel's own def (no face stage, every
declared attr layer bindable), so P1–P5 widen a predicate rather than editing a
switch. Engine work in `engine/source/{subdiv,brush}`, addon work in
`sculptcore_addon/`. No Blender-fork change required (verified, §11).

**Goal, in the user's words:** *"the goal is to eliminate any switch statements
that gates specific brushes. There are brushes that will be invalid due to host
restrictions (e.g. for blender vertex paint and poly/face-set group). If that
happens these brushes should edit the base mesh attributes instead (as blender
currently does for face sets)."*

## 0. Revision note — what rev 1 got wrong

Rev 1 was pressure-tested by four independent adversarial reviewers (engine
internals, codegen, draw/host, sequencing). Its **diagnosis** (§1) survived
verbatim. Its **mechanism and sequencing did not**. The claims that died, because
the rest of this document is shaped by their absence:

| rev 1 claim | why it is false |
|---|---|
| "hand kernels an `AttrRef` pointing at store-channel memory" | `AttrRef::data` is an `AttrDataBase *` — a **paged container**, `pages[i>>SHIFT].data[i&MASK]` over per-page heap allocs (`mesh/attribute.h:215-218, 326`). Store levels are `Vector<Vector<float>>` chunks. Not aliasable. |
| "the metadata is already there; capability is just the join" | The manifest's `write` bit **does not mean writes**. `bsmooth.brush.gen.h:107` emits `vclass` with `write == true`; `grid_executor.h:806-808` says "the manifest write flag only means ensure-materialized". BSMOOTH — i.e. every autosmooth stroke — would route to the cage. (§4.1 now infers a real `kernelWrites` from the kernel body; this stays the plan's first blocker.) |
| "undo is a `GridBlock` sizing tweak" | `GridCapturePolicy` hard-asserts `field != CaptureField::Attr` (rev 2 cited `grid_executor.h:1139`; that assert never existed — see §5.6); the fold captures two hardcoded channels (`:124-135`); `captureGrids` is a stroke-**end** snapshot, so in-place dab writes would make undo a silent no-op. |
| "delete `supportsBrush` in P0" | `makeFaceIter` is `abort()` (`grid_executor.h:443-447`). P0 would send POLYGROUP down the grids path and hard-abort Blender. In `Release` the vclass assert is compiled out, so COLOR/COLORSMOOTH/LAYERDRAW dereference an unmatched handle instead. |
| "one emitted dispatcher already serves any executor" | `emit_registry.cc:400-405` emits the neighbor sources as **literals** (`CsrNbr`/`LiveDiskNbr`), both mesh-only. Grids needs `GridCsrNbr` (`grid_executor.h:67-77`). No extra kernel has ever run on grids. |
| "generate the `SculptBrushes` enum" | Ids are not positional: `CLAY = 2`, `TEXDRAW = 9`, `SCRAPE = 10`, `FILL = 11` (`brushes/types.h`). One `plane.sbrush` serves 2/10/11. No file-order rule reproduces that. |
| "four hand-maintained rosters" | At least fourteen (§8.3). `gpu_marshal.cc:33-56` is an entire second tool→kernel roster; six per-tool **pre-pass** conditionals survive untouched. |
| "cage fallback: undo is a gate, not an assumption" | There is no path at all. `convert.py:2033-2037` early-returns multires into `_flush_multires`, which writes **only** mask + CD_MDISPS; `_seed_cage_draw_attrs` (`:354-391`) is one-way; `undo.py`'s `_ATTR_KINDS` all target `session.mesh_ptr`, never `cage_ptr`. |
| "face attrs: average across grids at seams" | Grid id **is** the cage corner, so every face-set boundary lies exactly on a grid seam, and the indexed layout duplicates seam verts on purpose to keep them crisp (`grid_draw_source.cc:151-161`). Averaging across seams blurs 100% of them, in the default path. |
| "a per-request exact/interpolated flag" | `ScExternalDrawAttrRequest` is `{attrs_num, attr_names}`, no flags, ABI pinned at 3; the host hardcodes four slot names (`draw_external.cc:472`). `indexed_` is read once in the ctor (`grid_draw_source.cc:23-24`). |
| "V1 whole-layer invalidate is simple and correct" | `invalidate()` bumps `generation_` → `grid_draw_source.cc:262-274` calls `markAllData()` → full refill **and** GPU re-upload of every node, every dab. ~10⁶ verts at level 4. |
| "bilinear scatter = the transpose of the subdivision operator" | `quad_weights_from_uv` does not exist (weights are inline at `grid_attrs.cc:533-536`); n-gons pull in a face average over **all** corners; UV-likes use face-varying CC + limit masks. Blender itself does not scatter — it writes whole base faces, binary (`sculpt_face_set.cc:328-339`). |
| gates: "126/126 ctest", "enum ids unchanged", "no soup with the flag off" | No 126 baseline exists; nothing pins an enum id (the addon resolves by name everywhere); `indexed_ = true` is already unconditional. All three gates are unfailable. |

Two rev-1 gate errors also stand corrected: stock Blender's multires is **not** a
valid parity oracle here (standing instruction, `feedback-blender-multires-not-baseline`),
and `test_multires_stroke.cc` only builds under `WITH_VULKAN`
(`tests/CMakeLists.txt:131`) — new multires-stroke gates go in
`test_grid_stroke.cc` (CPU, deterministic).

## 1. Diagnosis (HISTORICAL — the pre-plan state, superseded by P0a-P4b)

**Read this section in the past tense.** Rev 2's heading said "unchanged, and
verified three times over", which reads as present tense; every citation below now
lands on different code. `supportsBrush` is at `grid_executor.h:684-697` and
iterates `def.attrs` through `attrBindable`; `createCommandSwitch` (`:655-668`)
lists **no** tools, having been replaced by the generated
`createBuiltinBrush`/`createExtraBrush` in P0b; `execStage` is at `:1012` and
calls `ensureAttrBindings` (`:1024`), with no non-`vclass` assert left. The
diagnosis was correct when written and is what P0a-P4b dismantled.

`GridBrushExecutor::supportsBrush` (`grid_executor.h:504`) was:

```cpp
brush_command def;
return createCommandSwitch<AccumLive>(brushType, def);
```

**The factory roster *is* the capability rule.** `createCommandSwitch` (`:464-499`)
lists 11 tools; the mesh executor's (`brush_executor.h:361-444`) lists 23. A kernel
is "unsupported on grids" precisely when nobody typed its `case` — which is why
snake hook, whose `@grabmode` sibling GRAB is already on the roster and whose dab
query is a plain sphere (`:769`), was excluded for no reason at all.

The one real capability boundary is `execStage` (`grid_executor.h:806-817`):
every non-`vclass` handle asserts. Everything else — `color`, `polygroup`,
`layerdraw`, `enhance`, `featurealign` — is unbindable because grids have no
storage for a named, typed, domained layer.

## 2. What is actually missing

Rev 1 assumed one gap. There are five, and each is phase-sized. **Status:** items
1, 2, 3 and 5 all landed (P0a-P4b, §9); item 4's framing is the switch/cage
conflation §6 now corrects. Read the present tense below as of rev 2.

1. **A binding mechanism** that reaches kernels at all (§3).
2. **Metadata that distinguishes reads from writes** (§4) — does not exist today.
3. **Grid-element storage** with domain and type (§5).
4. **A cage write-back path** through the addon to `ob.data` (§6) — does not
   exist today, and is the default path for every user.
5. **A face execution path** on grids (§5.4) — `makeFaceIter` is `abort()`.

## 3. Mechanism: dense mirrors, not zero-copy refs

Kernels index the **dense level-vert id** (`grid_executor.h:259-270`:
`d->pos()[v]`). Store channels are `(grid, u, v)` with boundary verts replicated
per incident grid. Derived layers are `gridCount·(S+1)²·comps` in lattice order.
Three different index spaces, and `AttrData<T>` is a paged container besides.

So a bound attribute is an **executor-owned dense column**, exactly as the mask
and the vclass shim already work:

- The vclass shim allocates an `AttrData<int>` sized to `domain->vertCount()` and
  points the `AttrRef` at it. This is the pattern; it generalizes. (Rev 2 named it
  `ensureVclassBinding` at `grid_executor.h:1049-1064`; **no such function has ever
  existed** — the generalization landed as `ensureAttrBindings`,
  `grid_executor.h:1309`. The prediction was right, the citation was invented.)
- The mask is the round-trip precedent: dense mirror on the domain, flushed
  through the occurrence table (`grid_domain.h:98-107`, `grid_domain.cc:286-308`).

Per bound attribute, per stroke: allocate a dense `AttrData<T>` at
`vertCount()` (vertex domain) or `faceCount()` (face domain); **gather** from the
channel or derived layer at stroke start; **scatter** back through
`occurrences()` at the fold. Budget one mirror per binding — this is a real
memory cost and belongs in the §12 measurement, not hand-waved.

`boundAttr`'s narrow property does survive: `brush_command.h:239-244` is
`attrBindings → AttrRef → static_cast`, with no `Mesh`, no `AttrGroup`, no
`type_dispatch`. The coupling is to `mesh::AttrData<T>`, which a dense mirror
satisfies.

## 4. Capability metadata

### 4.1 The blocker: `write` does not mean writes

`BrushAttrManifestEntry::write` is set for anything the mesh executor must
*ensure-materialize*, not for anything the kernel stores to. `bsmooth` reads
`vclass` and only reads it, yet `write == true`. Any predicate keyed on that bit
routes BSMOOTH — and therefore every autosmooth-bearing program, i.e. the Clay
default that `program-grids-routing` landed and benched — off the grids path.
(Rev 2 wrote "into the cage path" here. Wrong: an unbindable attr routes a brush
to the **materialized-mesh** path, `grid_attr_bind.h:20`. BSMOOTH has no cage
destination at all — `.boundary.vert.class` is engine-derived, and is the one
layer `gridAttrZeroDefault` binds a zero column for, `grid_attr_bind.h:92-95`.)

**This is P0 work, not a §4 detail.** Nothing else in this plan is implementable
until the manifest distinguishes the two.

**The fix is a rename plus one inferred bit, not a new annotation.** Keep the
existing field's *meaning* and give it its honest name — `write` → `materialize`
(the executor must ensure the layer exists, which is true for every attr entry
including host-pre-pass-filled ones) — and add `kernelWrites`, **inferred from
the kernel body**. No DSL surface changes; nothing to author, nothing to keep in
sync, and an out-of-repo extra kernel gets the right answer for free.

The analysis already exists. `ir.cc:120-146` walks stage bodies for assignments
to a named member and is used at `emit_cpp.cc:2133` to emit `def.writesMask`:

```cpp
static bool stmtWritesMember(const Stmt *s, const char *field)
{
  if (s->kind == StmtKind::Assign && exprIsMemberNamed(s->lvalue.get(), field))
    return true;
  // recurses stmts / thenBranch / elseBranch / forInit / forStep
}
bool brushWritesMember(const Brush &brush, const char *field);
```

Attrs are referenced in bodies as ordinary member access (`v.vclass`, `nb.color`,
`f.group`), so the same walk keyed on each `attr` field's declared name is the
whole implementation. Over the seven attr-carrying kernels it yields:

| kernel | attr | body | inferred |
|---|---|---|---|
| bsmooth | `vclass` | `int vc = v.vclass`, `nb.vclass` | read |
| featurealign | `vclass`, `field` | reads only | read |
| enhance | `edisp` | `v.co += v.edisp * s` | read |
| color | `color` | `v.color = base + …` | write |
| colorsmooth | `color` | `v.color = v.color + …` | write |
| layerdraw | `slayer` | `v.slayer = v.slayer + …` | write |
| polygroup | `group` | `f.group = activeGroup` | write |

Which is exactly the split §4.3 needs: the three read-only attrs are all
host-pre-pass scratch that never wants a cage or a session channel, the four
writes are precisely the ones §6 must route, and BSMOOTH stays native.

**Why the analysis is sound for the language as it stands** (each verified, and
each a thing that would silently break it if it changed):

- Compound assignment is the same `StmtKind::Assign` with an `assignOp`
  (`parser.cc:866-871`), so `v.color += x` is caught.
- **The DSL has no user-defined functions.** `ExprKind::Call` (`ir.h:69-78`)
  reaches builtins only, and both `ParamDir` parse sites (`parser.cc:576-578`,
  `:775-777`) are stage / texture-`eval` *signatures*. So there is no call site
  at which an attr member could escape as an `out` argument — the classic hole in
  this kind of analysis is structurally absent.
- No kernel writes a swizzle or index lvalue on an attr (`v.color.x = …`), which
  `exprIsMemberNamed` would miss since it tests the top-level name.

That last one is the only real fragility, and it is worth closing by
construction rather than by convention: if an assignment's lvalue **contains** an
attr-named `Member` anywhere in its subtree but is not a top-level `Member`, the
compiler should **hard-error** ("write through a swizzle/index of attr `color` is
not supported"). That makes the analysis fail loud instead of fail silent, which
is the property that matters for a bit this load-bearing.

Base-agnosticism is the safe direction: a local struct field colliding with an
attr name over-reports a write, which costs a needless cage route, not
corruption. If it ever bites, check that the base resolves to the stage's `inout`
param.

**Free cross-check, same phase.** The `save` list is an independent signal:
`color.sbrush` saves `color`, `layerdraw` saves `slayer`, `polygroup` saves
`group` (its comment: *"without naming `group` here the painted ids are never
captured and the stroke won't undo"*), and no read-only attr is saved. Every
body-written attr is saved and vice versa, across all seven. Emit a **warning**
on disagreement — a saved-but-never-written attr is dead capture, a
written-but-never-saved attr is an undo bug — but not an error, since a
host-pre-pass-written attr that needs capture would be a legitimate exception
(there is none today).

*Gate:* `queriedAttrEntry(BSMOOTH, "vclass").kernelWrites == false` and
`(COLOR, "color").kernelWrites == true`; the seven-row table above pinned as a
golden; the swizzle hard-error covered by a negative compile test.

Two further defects in the reflection surface, same phase:

- `queryAttrManifest` / `queriedAttrEntry` are **non-static members** holding
  result state on the instance (`brush_executor.h:2179-2218`) — the rev-1 call
  form is ill-formed and the shared buffer is unsafe under interleaving.
- `buildBrushDef` passes `brushOrNull = nullptr` (`:2135-2140`), and the extras
  branch requires a live `Brush` (`:447`), so the manifest is **empty for every
  extra kernel** — precisely the out-of-repo painting kernels this plan exists to
  serve. Give `buildBrushDef` a scratch `Brush`; make the queries static with
  caller-owned output.

### 4.2 Ownership

- **Host owns the inputs.** `MultiresAttrs::declareHostAttr(name, type)` /
  `clearHostAttrs()` (`grid_attrs.h:118`) — today the addon declares the scalar
  mask, nothing else. Plus the kill switch — there is one host input,
  `Scene.sculptcore_grid_attrs` (`props.py:157`), drawn in the dev-only
  `SCULPTCORE_PT_experimental`. Rev 2's "the checkbox and the kill switch" implies
  two; every later "the checkbox" in this doc means that one dev switch.
- **Engine owns the derivation.** A host-side join would be a host conditional
  over brush behaviour, which `engine/CLAUDE.md` § *Brush* rules out.

Two host inputs rev 1 missed, both fork-side draw gates rather than storage:
slot 0 is dropped unless the **Blender** mesh has an active `POINT`/`FLOAT_COLOR`
attribute (`draw_external.cc:88-108`, gated at `:255`), and the sculpt overlay
skips a batch carrying neither mask nor face set
(`overlay_sculpt.hh:174-182`). `mask@2`/`fset@3` are exempt (`:249-254`) — so a
session colour channel silently does not render on an object with no colour
layer, while face sets are fine.

### 4.3 The predicate

Per manifest entry, once §4.1 lands:

```cpp
enum class GridAttrPlanKind { BindDerived, BindChannel, CageScatter };

GridAttrPlanKind planForEntry(const BrushAttrManifestEntry &e, bool sessionWrites) const
{
  if (e.domain == AttrElemDomain::Corner) return CageScatter;  // no corner domain
  if (!e.kernelWrites) return BindDerived;                     // §4.1's inferred bit
  switch (storageFor(name, e.type, flagsFor(name), e.domain)) {
    case Host: case Temp: case Session: return BindChannel;
    default: return sessionWrites ? BindChannel : CageScatter;
  }
}
```

`Temp` is `BindChannel`, not cage — `AttrFlag::TEMP` is engine scratch the host
never sees, so `enhance`'s `.brush.enhance.disp` and `featurealign`'s
`.boundary.vert.class` stay native regardless of the checkbox.

**Reads do not always resolve**, contrary to rev 1: `attrComps(INT) == 0`
(`grid_attrs.cc:69-83`) makes `samples()` skip int cage attributes entirely
(`:383-397`), while `storageFor`'s guard deliberately admits INT to `Derived`
with nothing behind it (`:308`). `polygroup`'s read binding would be null. Fix:
`storageFor` returns `None` for INT until an int derived layer exists.

**What actually landed differs, and §9 did not record it.** The enum has no cage
arm: `enum class GridAttrPlanKind { Unbindable, DefaultColumn, SessionChannel }`
(`grid_attr_bind.h:66-70`), and switch-off is
`if (!sessionChannels) return Unbindable;` (`:117-119`). So the aggregate is
`supportsBrush`, which loops `def.attrs` and returns **false** on any unbindable
entry (`grid_executor.h:684-697`) — it answers exactly *whether grids runs*, the
opposite of what rev 2 asserted here ("It answers *where writes land*, never
*whether grids runs*"). The cage is not an arm of this predicate at all; it is a
destination orthogonal to it (§6.2, and `convert.sync_cage_face_attrs`, which
reads whichever of the two routes a stroke actually wrote). The face-stage gate
rev 2 expected to survive did not: P4b built the iterator (§5.4, §5.8).

## 5. Storage and domains

### 5.1 The storage line

Unchanged from [multires-attribute-subdivision](multires-attribute-subdivision.md)
§82-106: derived/recomputable → `MultiresAttrs`; authored → `GridsStore`. Plus a
fourth class, **`Session`** — authored, engine-owned, never re-subdivided (so a
cage edit or a `uv_smooth` change cannot silently destroy direct paint).

### 5.2 Channel extension

```cpp
enum class GridElemDomain : int { Vertex, Face };
struct Channel {
  string name; int floatsPerElem = 1;
  GridElemDomain domain = Vertex;
  mesh::AttrType type = FLOAT;    // metadata only — see the invariant below
  bool persist = true;
  Vector<LevelData> levels;
};
```

Elements per grid: Vertex → `(S+1)²`, Face → `S²`.

**Landed as single-sourced, and rev 2 undercounted the sites.** `GridsStore::elemWidth`
/ `elemsPerGrid` (`grids.h:97-111`, "The single home of…") is now the only home:
`allocLevel`/`fillChunks` call `elemsPerGrid` (`grids.cc:33, 44`), and
`captureGridBlock`/`applySwap` call `channelElemsPerGrid`
(`grid_stroke_log.cc:80-81, 176-177`). Rev 2 listed **four** duplication sites;
there were **five** — the row stride was also inline in `elemIn`
(`e5ffc03~1:source/subdiv/grids.cc:90-92`), a site that had to move for the Face
domain exactly as much as the sizing sites did, and did (`grids.cc:155`).

Storage is `float` throughout — `type` enforces nothing. State the invariant
explicitly: **no float math on a typed channel**, asserted at the interpolating
consumers (`gridsWriteback`, the §7 averaging).

### 5.3 Lifetime hazards (rev 2: "all live today"; two are now FIXED — see the tags)

- **Undo blocks are keyed by channel *index*.** `applySwap` dereferences
  `store.elem(level, b.channel, …)` unchecked (`grid_stroke_log.cc:184`), and
  `removeChannel` shifts every later index down (`grids.h:124-136`, live via
  `multires.cc:1387`). Key `GridBlock` by **name**, resolve at swap time, drop
  blocks whose channel is gone, add the missing range check.
  **FIXED in P1** (`e5ffc03`): `GridBlock.channel` is a `string`
  (`grid_stroke_log.h:93-96`), `applySwap` resolves by name and `continue`s when
  `findChannel < 0` (`grid_stroke_log.cc:176-188`), `removeChannel` gained a range
  guard (`grids.h:175-177`).
- **`addChannel` allocates every level eagerly and resident** (`grids.cc:49-60`),
  and eviction state is per `(channel, level)` (`:281-338`) — a channel created
  while a level is evicted lands resident under an "evicted" level. So §12 Q2's
  rev-1 answer ("eviction covers it") is false. Lazy per-level allocation for
  `persist == false`, and `evictLevel` must sweep late-added channels.
  **FIXED in P1**: `allocLevel` skips `fillChunks` for `!ch.persist`
  (`grids.cc:50-53`), and `addChannel` evicts the new level when that level is
  non-resident (`grids.cc:68-74`).
- **Level changes destroy session data.** `addLevel` zero-fills the new finest
  level for every channel (`multires.cc:1294`), `dropTopLevel` discards it, and
  `buildFromCage` does `channels_.clear()` re-adding only `disp`
  (`grids.cc:121-127`). "Never re-subdivided" protects against cage edits, not
  against Add Level. Seed new levels from the level below; document cage rebuild
  as destructive.
  **HALF FIXED in P1**: `addLevel` seeds session channels via `seedLevelFromBelow`
  (`grids.cc:80-87`); `buildFromCage`'s `channels_.clear()` is still destructive
  (`grids.cc:195`, documented at `grids.h:69-72`). No warning text was written,
  and none is owed while the switch is dev-only (§9, P5).
- **Skipping the serializer is not a safety property.** `Multires_serializeStore`
  has exactly one production consumer and it is *undo*, not save
  (`convert.py:1804`, `undo.py:324-335`); the .blend is written by
  `_flush_multires`, which never touches the store. Excluding session channels
  from the serializer therefore makes every blob-fallback undo restore an empty
  channel. **Include** them in the serializer; exclude at the *flush* boundary.
- `captureGridBlock`'s dedup stamp is a `uint32_t` bitmask, degrading to a linear
  scan past 32 channels (`grid_stroke_log.cc:62-76`).
- Channels are reconstructed **positionally** on load (`grids.cc:591-613`).

### 5.4 The face domain

§4.3's structural argument stands and was not refutable: `GridTree::Leaf` is
`{grids, ownedVerts, aabb}` (`grid_tree.h:47-53`), so a leaf owns all S² cells of
each of its grids — no canonical-corner rule, no double-visit. Cell id is
`v*S + u`; global face id `g*S*S + v*S + u` bridges to the slot mesh.

But there is **no face execution path**: `makeFaceIter` is `abort()`
(`grid_executor.h:443-447`), `face_iter` is a mesh iterator present only to
satisfy the concept (`:324-326`), and `GridCapturePolicy` discards every
non-vertex domain (`:1124-1126`). A grid face iterator — per-cell centre/normal,
per-cell affected set, per-cell capture — is its own phase. **Built in P4b; see
§5.8.**

### 5.5 Edges

Numbering only. Prefix-sum over ring1 CSR pairs with `nb > v`; seam-correct
because boundary verts exist exactly once. No storage, no kernels. Cage edge
attributes keep reaching grids as subdivided values.

### 5.6 Attribute undo on grids

Does not exist. Three independent breaks: the capture path asserts on
`CaptureField::Attr` (rev 2 cited `grid_executor.h:1139`; **no such assert exists
or existed** — `GridCapturePolicy::capture` is at `:1435-1463` and handles attr
saves by documented omission, `:1454-1457`) — which is exactly what
`color.sbrush`'s `save vertex color` codegens to; the fold captures two hardcoded
channels gated on `strokeWroteCo_`/`strokeWroteMask_`, so a colour stroke is
booked as a position stroke (`:124-135`, `:819-827`); and `captureGrids` is a
stroke-end snapshot, correct only because the store is untouched until the fold
(`grid_stroke_log.h:44-49`).

With §3's mirror this becomes tractable: capture the pre-value at **first touch
per dab** (as `pos`/`mask` already do, `grid_stroke_log.cc:118-131`), accumulate a
*set* of written channels instead of two booleans, and capture before the mirror
flush.

### 5.7 What P4a actually landed (2026-08-18)

The vertex half of P4: a session channel a colour stroke paints now *reaches the
viewport*, live, and survives the round trip through undo.

The gap it closes is a layering one. The grids draw path never reads the store —
it reads `MultiresAttrs`' derived samples, subdivided from the cage — and the
store only learns of a stroke at the fold. So before this, a grids-native colour
stroke was invisible until mouse-up, and invisible again after any rebuild of the
derived layer. Four seams, all in the engine:

- **`GridsStore::channelLevelAllocated(level, ch)`** — "does this level hold
  anything authored". False only for a session channel nobody has touched at that
  level (persistent channels are allocated up front; an evicted level rehydrates
  on the next `elem()`), which is exactly the question the seed and the overlay
  both need to ask.
- **Seed, once per level** (`MultiresAttrs::seedSessionChannel`, called from
  `gridAttrEnsureChannel`, which now takes the level). `addChannel` zero-fills;
  without a seed the first rebuild would overlay black over the whole level and
  paint would blend up from black instead of from the surface.
- **Overlay on build** (`overlaySessionChannel`, on both `buildLayer` branches):
  where a session channel of the same name holds data, it *wins* over the
  subdivided cage — the layer is no longer a pure function of the cage, because
  authored paint is not something the cage can reproduce.
- **Publish per dab** (`gridAttrMirrorToSamples`, from `GridBrushExecutor::finishDab`,
  through every occurrence so a seam sample stays identical in each grid). This
  runs single-threaded after the parallel kernel section, alongside the
  `markVerts` the draw source already gets, so the existing partial refill
  carries the colour with no extra invalidation.

Plus the undo return route: `applySwap` collects the blocks whose channel is a
session channel and re-overlays just those grids
(`MultiresAttrs::refreshSamplesFromChannel` + `markGrids`). It deliberately leaves
`generation_` alone, for the same reason `refreshFaceSetColors` does (§6.1
deviation 1) — a generation change sends `GridDrawSource::update()` through
`markAllData()` and re-uploads every node.

Gates: `test_grid_stroke`'s P4 block (published-per-dab count, then samples
bit-exact through `invalidateAll()` → undo → redo — the rebuild leg is what proves
the seed, since without it the untouched samples would come back zeroed), and
`tools/verify_multires_color.py` (headless: the kill switch decides the
route; the cage carries the `color` layer; a grids dab paints and leaves the cage,
the slot and `ob.data` byte-identical; the undo step seeks the grid log itself;
and the same dab with the switch off *does* land on the slot, which is what makes
"nothing moved" a routing result rather than a dab that missed). Wired into
`smoke-test-packages.yml`. Whether it *renders* was checked by eye and **passes**
(2026-08-19): with the checkbox on, colour appears live during the stroke on a
multires object carrying an active POINT/FLOAT_COLOR attribute, and undo/redo
behave.

**Known limitation: seeding is per level and one-shot.** Nothing propagates
between levels, so painting at level 3 and then switching to level 4 seeds level 4
from the *cage*, not from level 3's paint. (`addLevel` seeds from the level below;
a level *switch* does not.) Acceptable while colour is session-only — the paint is
not persisted anyway — but it is the first thing to revisit if colour ever gains a
flush route.

**Not in scope, and not a regression:** a session channel is excluded at the flush
boundary, so multires colour paint reaches neither `ob.data` nor the .blend. That
matches §5.1/§5.3 and matches the mesh path's behaviour today, where
`_flush_multires` writes mask + CD_MDISPS only.

### 5.8 What P4b actually landed (2026-08-18)

The face half of P4, and with it the last kernel the grids domain declined for
anything but a missing attr layer. POLYGROUP now instantiates and runs
grids-native: `supportsFaceStages` is gone as a `false`, `makeFaceIter` is a real
iterator, and POLYGROUP's last decline reason (`group attr layer`) goes with this
change. **Correction:** rev 2 wrote that the roster golden "lists exactly one
declined kernel, for exactly one reason". It does not.
`test_grid_stroke.cc:132-153` declines **six** of 23 with the flag off (COLOR,
POLYGROUP, COLORSMOOTH, FEATURE_ALIGN, LAYERDRAW, ENHANCE) and **three** with it
on (FEATURE_ALIGN, LAYERDRAW, ENHANCE), for three *different* reasons — see §9's
P5 entry. What is true is narrower: no kernel is declined for a *face stage* any
more.

Five seams, engine-side:

- **`GridFaceIter`** over a leaf's grids (`grid_executor.h`). A leaf owns whole
  grids, so face-leaf granularity *is* grid granularity and every cell is visited
  exactly once — no canonical-corner rule was needed. Cell centre/normal come from
  the four lattice samples that bound the cell.
- **Face-domain channels end to end**: `gridAttrPlan` accepts a Face-domain
  layer, `gridAttrEnsureChannel` allocates with `GridElemDomain::Face`
  (`elemWidth = S`, not `S+1`), and `gridAttrGatherFace` / `gridAttrScatterFace`
  move the dense mirror in and out. The seed is `seedFaceSessionChannel` — the
  cage's per-face value copied into every cell of its grid — because a face
  channel has no derived sample layer to copy from. A cage that never carried
  face sets gets `ensureFaceGroups()` first: it still has an *implicit* group
  (the host's default), and seeding zeros instead would make the scatter push
  "no group" onto every face the stroke missed.
- **Per-sample face-set draw.** `MultiresAttrs::faceSetSampleColors(level)` is a
  new derived layer: gridCount × (S+1)² float3, each sample averaged over its
  incident cells *within its own grid*. It wins over the per-grid
  `gridFaceSetColors()` in `GridDrawSource::fillNode` (a new `fsetSampleSrc_`),
  which is what lets a face-set boundary land *inside* a grid instead of snapping
  to a grid seam. It exists only once a grids-native polygroup stroke has
  allocated the Face channel; without one the per-grid colour is still the truth.
  Published per dab from `gridAttrMirrorFaceToSamples`, which builds the cache
  first — a per-grid refresh is a no-op before it exists, and the lazy build would
  otherwise source the (not-yet-folded) store and show nothing.
- **Undo.** Face saves are ignored by `GridCapturePolicy` on purpose: a face
  kernel's cells are a store channel, and every channel is captured at the fold,
  which is where the store is first written — a per-dab snapshot would capture
  nothing. The return route out of a seek is the same as P4a's: `applySwap`
  re-derives the touched grids, here through `refreshFaceSetSampleColors`.
- **`Multires::scatterFaceIntToCage` reads the store first.** A grids-native face
  stroke never materializes a slot mesh, so the old slot-only read saw nothing at
  all. It now prefers a non-persistent, elem-size-1, Face-domain channel of that
  name at that level and falls back to the slot column. One grid's cells are
  contiguous, so the store side is a base pointer per grid.

Addon side, `undo.push`'s grids branch now runs that scatter when the stroke was
a face-set stroke, and carries both sides of the cage column in the `_GRID_TAG`
tuple (now ten elements: `…, level, cage_before, cage_after`); both `_decode_grid`
paths restore it. Without this the paint would be gone at the next mode exit —
the Face channel is engine-owned session state and the cage is the only copy that
persists.

**Per-cell detail collapses to per-base-face at push time**, and the scatter
re-stamps its own source so the next push is idempotent. That is Blender's own
multires face-set rule and exactly what the mesh path already does; the gate is a
second `scatterFaceIntToCage` returning 0.

**Deliberate wart, left at mesh-path parity:** the scatter runs at *push* time,
after the grid log step closed, so a redo replays the un-collapsed per-cell state
while the cage holds the collapsed value. The mesh path has the identical
asymmetry (it re-stamps the slot after the meshlog snapshot). Matching it beat
inventing a third rule; fixing both is a separate change.

Gates: `test_grid_stroke`'s P4b block (a POLYGROUP dab publishes non-uniform
per-sample colours *before* `endStep`; the fold writes cells; undo restores every
cell and redo is blob-bit-exact; the cage adopts the group and a second scatter
returns 0) and four gates appended to `tools/verify_multires_face_sets.py`, next
to P3's own (the kill switch decides the route; a face dab reports touched *grids*
since it moves no vertex; the cage stays untouched until `undo.push` scatters it,
and undo/redo restore the column; and the object starts with *no* face-set column,
so the missed faces landing on the default group is what proves the seed invented
it rather than seeding zeros).

One c-api consequence: `GridStroke_dab`/`applyDab` (and `applyProgram`) fall back
to the touched-grid count when no vertex moved. Callers read the return only as
"did the dab land", and a face stage that returned 0 read as "the brush missed".

## 6. The cage-write fallback — the product, not the fallback

This is what the user asked for. **Two corrections to rev 2's framing, both
load-bearing:**

1. It is **not** "the path every user takes with the checkbox off". The switch
   selects grids-native vs the **materialized-mesh** path (`grid_attr_bind.h:20`,
   `grid_executor.h:677-678`). The cage write-back is a *destination* orthogonal to
   the switch, reached from **both** routes — `convert.sync_cage_face_attrs` reads
   "whichever of the two a stroke actually wrote" (`convert.py:1719-1733`), and
   `undo.push`'s grids branch runs the same scatter (`undo.py:214-225`). Face sets
   reach it from both sides; colour from neither.
2. "None of its plumbing exists" was true at rev 2 and is now false — P3 built it
   (§6.1). The three bullets below are **historical**; each is superseded:
   - `_flush_multires` (now `convert.py:2047`) calls `sync_cage_face_attrs` then
     `_flush_face_sets(ob.data, session.cage_ptr)` (`:2071-2074`). Only the
     `_flush_color` half of the claim still holds.
   - `_seed_cage_draw_attrs`'s `group` layer **is** read back, by
     `cage_face_group_bytes` (`convert.py:1740-1756`).
   - `session.cage_ptr` is now all over `undo.py`: the `CAGE_FACE_I32`
     `_ATTR_KINDS` kind (`:89-92`), `_restore_cage_groups` (`:317-331`), both
     `push` branches.

Rev 2's original text, for the record:

- `convert.py:2033-2037` early-returns multires into `_flush_multires`
  (`:1994-2022`), which writes `export_mask` + `export_bake` (CD_MDISPS) and
  nothing else. `_flush_face_sets` (`:414-425`) and `_flush_color` never run.
- `_seed_cage_draw_attrs` (`:354-391`) pushes uv/color/group onto `cage_ptr` at
  enter and is **never read back**.
- Every `_ATTR_KINDS` entry writes through `session.mesh_ptr` (`undo.py:69-80`);
  `session.cage_ptr` appears nowhere in `undo.py`.

So the work is: a cage-attr readback c-api, a new branch in `_flush_multires`
(the map is trivial — cage vert *i* == base vert *i*, cage face *i* == base face
*i*), a cage-targeted `_ATTR_KINDS` kind so `push_attr` can snapshot the cage
column, and the engine-side scatter. Blender's own face-set path pushes a
dedicated `undo::Type::FaceSet` node (`sculpt_face_set.cc:322, 386`) — rev 1
cited the precedent and copied only half of it.

**Face domain, V1:** grid → cage corner → cage face is exact and cheap
(`grid_attrs.cc:49-67`, grid id *is* the cage corner index). Write the whole base
face, binary, no area weighting — matching what Blender actually does
(`sculpt_face_set.cc:328-339, 392-404`), not rev 1's invented "largest covered
area".

**Vertex domain: cut from V1.** The bilinear "transpose" is not the adjoint of
the real forward operator — weights are inline at `grid_attrs.cc:533-536` (no
`quad_weights_from_uv` exists), n-gons gather a face average over *all* corners
so a transposed write sprays the whole n-gon, the forward weights are not a
per-source-vertex partition of unity, and UV-likes use face-varying Catmull-Clark
with limit masks (`buildFaceVarying:696`, `applyLimitMask:197` — rev 2's
`:550-692` range is inside `buildBilinear`, `:585-694`) where a
bilinear transpose is simply wrong. Colour-on-multires with the checkbox off is
therefore **out of V1**; say so plainly rather than shipping a smeared
approximation. **This objection is narrower than it reads -- it kills the
transpose, not the cage route; see §6.2.**

**Refresh cadence is a correctness-adjacent gate, not a follow-up.**
`invalidate()` bumps `generation_` (`grid_attrs.cc:337-346`), which
`grid_draw_source.cc:262-274` turns into `markAllData()` — every node refilled
(`fillNode` rewrites pos/no/mask/color/uv/fset, `:136-206`) and re-uploaded
(`draw_external.cc:328-393`). A partial, touched-grid invalidate feeding
`markGrids` (`grid_draw_source.cc:232-240`) is part of this phase's definition of
done.

### 6.1 What P3 actually landed (2026-08-18)

Engine: `Multires::gridCageFaces` (the grid → cage-face table, the walk
`gridFaceInts` already describes) and `Multires::scatterFaceIntToCage`, exposed
as `Multires_scatterFaceIntToCage`. Addon: `convert.sync_cage_face_attrs` /
`cage_face_group_bytes` / `restamp_cage_face_attrs`, a `_flush_multires` branch
ahead of the readback, the `CAGE_FACE_I32` `_ATTR_KINDS` kind, `undo.push_face_sets`
for the two face-set operators, and a `cage_before`/`cage_after` pair carried in
the stroke step (gated on `session.last_stroke_face_sets`, so only face-set
strokes pay for the scan).

Gate: `tools/verify_multires_face_sets.py` (headless) — the per-face
rule, `ob.data` + save/reload, and both undo routes (attribute step and stroke
step). Engine gate: `gateCageScatter` in `tests/test_multires_attrs.cc`.

**Three deviations from §9's wording, each deliberate:**

1. *"per-dab draw refill touches only marked grids"* does not apply literally.
   During a mesh-path stroke on multires the provider is SLOT, not GRIDS, so the
   grids source is not refilling per dab at all. The requirement is met at the
   scatter instead: `refreshFaceSetColors` re-tints only the changed grids and
   deliberately leaves `generation_` alone (so `GridDrawSource::update()` cannot
   fall into `markAllData()`), the c-api calls `markGrids(touched)`, and only the
   slot tree's leaves are flagged for re-upload. `gateCageScatter` asserts the
   generation is unchanged across a scatter — that is the "assert, not eyeballs".
2. The painted region snaps to base-face granularity at **mouse-up**, not live;
   Blender flips whole base faces live. Accepted for V1: the live view is the
   slot's own per-cell column, which is finer, not wrong.
3. The face-set *operators* on multires are now coarsened to base-face
   granularity too. That is a behaviour change, and the correct one — before
   this their slot writes had no persistent home and evaporated at the next
   eviction.

**A prerequisite bug this uncovered.** A materialized slot never inherited the
cage's `default_group_id`; it defaulted to 0 while the host's is 1. So
`ensureFaceGroups()` on a level mesh filled it with zeros the cage disagreed
with, `newFaceGroupId()` handed back an id aliasing the host default, and the
first scatter read *every* base face as changed. Fixed in `assignDerivedAttrs`
(slots inherit at materialize) and in `Multires_setDefaultGroupId` (resident
slots follow a later change).

### 6.2 Correction: the vertex-domain objection is about the *transpose*, not the cage route

Rev 2's "Vertex domain: cut from V1" above rejects one specific construction --
transposing `buildBilinear`'s gather, i.e. spreading a fine-sample edit back
across every cage vert that fed it. That rejection stands, for the reasons given
(the n-gon face-average term sprays a whole n-gon, the forward weights are not a
per-source-vertex partition of unity, and face-varying layers carry limit masks).

It does **not** apply to the restriction route, which is a different operation:
paint only the samples that *are* cage verts, and write them through unweighted.
That route is exact, not approximate, and the code says so.

**Sample (0, 0) of every grid is its corner's cage vert, with weight exactly 1.**
Verified in `buildBilinear` (`grid_attrs.cc:585-693`), both branches:

- *Quad* (`size == 4`): `org = kQuadPtex[gr.index]`, one of the unit square's four
  corners (`:38`), and `ptex[j] = elemVal(j)` are the face's four verts in loop
  order. At `(u, v) = (0, 0)`, `(pu, pv) = org`, so `quad_weights_from_uv` is
  one-hot on ptex corner `gr.index` -- this grid's own cage vert.
- *N-gon*: `org = (0, 0)` and `ptex[0] = elemVal(k)` is the corner's own vert
  (`:653-668`), so the same `(0, 0)` lattice coord reads weight 1 on it. The
  face-average term lives at `ptex[2]`, which `(0, 0)` weights zero.

So grid -> cage corner -> cage vert (`buildGridRefs`, `:50-67`, plus
`cage.c.v[cc]`) is as exact for the vertex domain as `gridCageFaces` is for the
face domain. No adjoint is involved: the forward operator is already the identity
on this subdomain, so the inverse on it is too.

**The three things the restriction route does need**, none of them an adjoint:

1. *A per-base-vert visit set.* A cage vert of valence n is sample `(0, 0)` of n
   grids, one per incident corner. Forward they all agree; after a dab that
   touched only some of them they do not. Treat the base vert as the entity and
   dedupe, exactly as P4b dedupes base faces.
2. *A neighbour-reading rule.* Grid-lattice neighbours of `(0, 0)` are mid-edge
   and face-centre samples, not cage verts, so grid adjacency is the wrong
   topology for a smooth-class kernel. Run those against the cage's own topology
   -- the cage is a `mesh::Mesh`, so this is the existing mesh executor pointed at
   `cage_ptr`, not new machinery. A cage 1-ring can reach verts whose grids the
   query never returned; that is fine for a kernel that *reads* neighbours and
   writes the centre (the cage attr array is fully resident), and only a problem
   for one that writes neighbours.
3. *An accepted resolution collapse.* Only cage verts are paintable, so a dab
   smaller than a base face paints nothing. That is cage-resolution paint -- the
   honest, persistent counterpart to the session channel's full-resolution,
   non-persistent paint. They are different products and shipping both is
   reasonable.

**No second spatial tree, and no tree update.** The grid tree stays the spatial
index; grid -> corner -> vert turns its hit set into base verts for free, and the
cage is only ever written, never queried spatially. Attribute paint moves no
geometry, so nothing rebuilds -- only the draw refresh needs marking, which is
P3's partial-refresh machinery (`refreshFaceSetColors` + `markGrids`, deliberately
leaving `generation_` alone; §6.1 deviation 1).

**Scope of the identity claim:** `buildBilinear` layers only -- colour, groups,
generic float attrs. `buildLayer` routes `layer.uvRule` layers to
`buildFaceVarying` when `uvSmooth_ != None` (`:431-438`), and those carry
`applyLimitMask` (`:823`), whose limit value at a vert is *not* the cage value.
UV is therefore outside this, which costs nothing here since UV is not painted.

## 7. Draw: within-grid only

Face attributes must not force a vertex soup. They also must not blur.

Grid id *is* the cage corner, so **every face-set boundary lies exactly on a grid
seam**, and the indexed layout duplicates seam verts per grid on purpose —
`fillNode`'s own comment: *"a seam vert exists once in the domain but carries a
different UV in each grid"* (`grid_draw_source.cc:151-161`). Rev 1's cross-seam
averaging would blur 100% of face-set boundaries and break UV seams, by default,
with no opt-out.

**The rule:** average incident cells **within a grid only**, never across the
occurrence table. Indexed buffers and the `indices` array are untouched; seam
crispness is preserved exactly as today; `markGrids`' inability to cross seams
(`:232-240`) stops mattering.

This deletes rev 1's exact/interpolated request entirely — with per-sample values
at every cell, "exact" and "interpolated" coincide. Which is fortunate, because
that request cannot exist: `ScExternalDrawAttrRequest` is
`{attrs_num, attr_names}` with no flags (ABI pinned at 3, `external_draw.h:17,45-48`),
the host hardcodes the four names (`draw_external.cc:472-473`), and `indexed_` is
read once into the constructor (`grid_draw_source.cc:23-24`) and baked into every
node's vert counts *and* static index stream. **No ABI change, no fork change, no
soup path.**

A *fifth* channel later would be a fork change (`attr_names[4]`, four static
`GPUVertFormat`s, six named VBOs in `NodeCache`) — noted in §11.

## 8. Roster elimination

### 8.1 What must survive

`supportsBrush` **stays**, and so does the exported `GridStroke_supported`
(`CMakeLists.txt:88`, `grid_stroke_c_api.cc:76-80`, called by `stroke.py:185`
every stroke across an independently-versioned DLL boundary). Its *body* becomes
metadata-derived — `!brushHasFaceStage(id)` initially (`def.faceMode` is already
codegen-set, `brush_command.h:492`), widening as capability lands, returning
constant true only when nothing can answer no. **Roster deletion is the
consequence of the capability work, not its prerequisite.**

### 8.2 Generated dispatch

`emit_registry.cc:363-410` is the model, with three corrections:

- It emits neighbor sources as **literals** (`:400-405`), both mesh-only. It needs
  a third template parameter (or a per-executor `using NbrSource`), since grids
  uses `GridCsrNbr` (`grid_executor.h:67-77`).
- It only runs under `NOT BUILD_WASM AND SBRUSH_BACKEND_CPP AND
  SCULPTCORE_EXTRA_KERNEL_DIRS` (`brush/CMakeLists.txt:149`); WASM consumes
  checked-in `.gen.h`. So a built-in registry must be a **checked-in artifact
  regenerated by `node make.mjs codegen`**, unconditional, outside the extras
  `#ifdef`. No bootstrap cycle: `sbrushc_core` links only `util math`.
- Its validation inverts today — built-ins are *inputs* used to reject extras
  (`emit_registry.h:33-41`).

**The enum is not generated.** Ids are non-derivable (§0). Codegen emits the
`Binder` item list and the dispatchers; `types.h`'s enum stays hand-written, and
a golden `{name → id}` table test pins it (`tests/test_brush.cc` is a 25-line
stub). `SB_EXTRA_RESERVED` (`brush/CMakeLists.txt:159` — since P0b it reads
`brushes/tools.txt` via `file(STRINGS …)`, `:163-167`, so the "literal copy" half
of this is historical), a literal copy of all 23
names commented "keep in sync", is generated from the same table.

### 8.3 `@tool` and `@fulltopo`

Parser cost is small — `parser.cc:153-186` is a flat `while (match(TokKind::At))`
chain, ~4 lines for a bool and ~15 for a comma list.

```
@tool DRAW                 // draw.sbrush
@tool CLAY, SCRAPE, FILL   // plane.sbrush

// The cross field generator needs complete, unfrozen topology: its per-dab
// pre-pass walks the live vertex disks, so the stroke can neither drop the
// link pages nor read neighbors from a stroke-start CSR snapshot.
@fulltopo                  // featurealign.sbrush
```

`@fulltopo` is a **topology-lifetime declaration, not a pre-pass registry**.
`brushNeedsLiveLinks` (`brush_executor.h:1227-1240`) does collapse into
`fullTopo || hasFaceStage || (usesForNeighbor && mode != Csr)` — the face-stage
term is real (`def.faceMode`, POLYGROUP walks the face loop) and `usesForNeighbor`
is already generated (`emit_registry.cc:363`).

But rev 1 was **wrong about ENHANCE**: `enhance.sbrush` is three lines
(`v.co += v.edisp * s`) and walks nothing (`brush_executor.h:437-438` says so).
Its live-links need comes from `updateEnhanceRegion`'s ring BFS, dispatched **by
enum id** at `:1512` and `:1668`. That is one of six per-tool **pre-pass**
conditionals — `:1496` (BSMOOTH), `:1512`/`:1668` (ENHANCE), `:1550`/`:1744`
(POLYGROUP `markPolygroupDirty`), `:1608-1609`, `:1644` (FEATURE_ALIGN) — none of
which any annotation in this plan removes.

### 8.4 The rosters this plan does *not* remove

Stated so the goal is not overclaimed. Beyond the six pre-passes:
`gpu_marshal.cc:33-56` (`kGpuKernels`, a second tool→kernel roster whose comment
notes ENHANCE/FEATURE_ALIGN are deliberately absent), `:136-169`
(`packBrushUniforms` per-tool packing on a `static_assert`ed slot alias),
`:97-102` and `:210-219` (host clamps); `grid_gpu_session.h:69, 100`;
`debug/script.cc:730-764, 1393-1407, 1622-1635`; `debug/ui.cc:160+`.

Also: `grid_executor.h:858` asserts `!cmd.needsOrigNormals` with the roster as its
stated premise. Rev 2 also claimed `ctx.renderMatrix` "is never set on the grids
path … a live bug the moment the addon's texture bridge follows them onto grids".
**Fixed in P0d** and no longer a bug: `GridBrushExecutor::setRenderMatrix` exists
(`grid_executor.h:540-554`), reached through `GridStroke_setRenderMatrix` +
`texture.apply_render_matrix_grids`.

And `_snake_hook` is **not** a name roster: `mapping.is_snake_hook`
(`mapping.py:160-169`) already derives from the engine's `@incremental` flag. The
grids exclusion rev 2 cited at `stroke.py:919` was **lifted in P0d**: the
grids-dispatch condition (`stroke.py:926-936`) carries no snake-hook term, since
"its per-dab state is written on the shared Brush, which both paths read". The
surviving `not self._snake_hook` at `stroke.py:874` gates the C++ dab loop, a
different thing. MASK is held back because host
mask ownership lives in the slot-mesh column (`convert.py:1719-1734`); BSMOOTH
rides the deliberate `sculptcore_grids_programs` kill switch. None become vacuous.

## 9. Phases

Reordered on one principle rev 1 inverted: **the cage path is the product; the
session channel is the optimization.**

**P0a — reflection repair (behaviour-neutral). DONE** (engine `080d0ac`).
`write` → `materialize` rename
plus the body-inferred `kernelWrites` bit and its swizzle hard-error (§4.1);
the `save`-list cross-check warning; static, caller-owned manifest queries;
`buildBrushDef` scratch `Brush` so extras report their manifest.
*Gates:* §4.1's golden seven-row table; the negative compile test; a test
asserting a sample extra kernel's manifest is non-empty; full ctest green.
Regenerating `kernels/generated/*.gen.h` must be a **pure rename diff** plus the
new field — any behavioural delta here means the inference disagreed with the
hand-maintained flags and must be resolved before P0b.

**P0b — generated dispatch, mesh-only instantiation. DONE** (engine `080d0ac`).
`@tool`; the emitter
extension with the `NbrSource` parameter; checked-in registry artifact; golden
`{name → id}` table test **landed before** anything touches `types.h`.
Per the precedent in `multires-grids-native-brush-path.md:315-319`: prove the
refactor is behaviour-neutral before a new domain exists.
*Gates:* a test asserting the generated dispatcher and the hand-written switch
agree for all 23 ids (this can fail, which is the point); `sbrush-verify`
unchanged; ctest green.
*As landed:* the ids live in `engine/source/brush/brushes/tools.txt`, an
append-only ordered table — they are persisted and not derivable from the
`@brush` names (`FEATURE_ALIGN` vs `"featurealign"`). `sbrushc
--builtin-registry` reads it and emits `brushes/generated/`
(`builtin_brushes_enum.inc`, included by `types.h`, plus
`builtin_brushes.gen.h`'s `createBuiltinBrush`); `SB_EXTRA_RESERVED` is now
derived from the same file rather than hand-copied into the CMake.
`tests/test_brush_registry.cc` keeps the old switch as its reference and
compares stages by the **address of the stored function pointer** — every
codegen'd stage is a plain function pointer, so `std::function::target_type()`
is `void(*)(Ctx&)` for all of them and a type comparison is vacuous (a
deliberate teeth-check assertion proved this before the address form went in).
The gate was demonstrated falsifiable by mis-mapping id 11 and watching it fail
across both `csr` values and both accum modes. `graddraw.sbrush` claims no
`@tool` and is deliberately absent from the registry. `sbrush-verify` is
unchanged, `pinch`'s pre-existing stale golden included; ctest 134/134.

**P0c — `@fulltopo` + `brushNeedsLiveLinks`. DONE** (engine `182dc4e`).
Separate because a wrong answer
drops link pages mid-stroke: a heap-layout-dependent UAF, the failure class whose
postmortem here reads *"the native suite and three probe scripts all passed while
the full test crashed deterministically"*. It has **zero** current coverage.
*Gates:* an old-vs-new truth table over all 23 ids, written **before** the
predicate changes; a dyntopo stroke A/B.
`tests/test_brush_live_links.cc` carries the truth table (`@fulltopo` = {19
FEATURE_ALIGN, 21 ENHANCE}, `usesForNeighbor` = {6 SMOOTH, 15 BSMOOTH, 18
COLORSMOOTH, 19 FEATURE_ALIGN}); the extras golden needed the same
NbrSource-parameterized `createExtraBrush` P0d later generalized, and the
bsmooth-segfault teeth-check confirmed the predicate is load-bearing.

**P0d — grids roster. DONE** (engine `0a18195`). Landed wider than written:
`supportsBrush` is not `!brushHasFaceStage(id)` but a conjunction of *def facts*
— the generated dispatch declines face-stage kernels structurally
(`if constexpr (!TYPES::supportsFaceStages)`), and a local `attrBindable`
declines every kernel whose declared attr layer has no grid storage. That second
term is exactly the hook P1/P2 widen, so no roster survives the change.
Newly grids-native: pose, texdraw, wingscrape, snakehook, texgrad. Still
declined: polygroup (face stage) plus color, colorsmooth, feature_align,
layerdraw, enhance (attr layers).
`wingscrape` **did** go native: `grid_executor.h` now calls `execHost` like the
mesh path, which was a latent correctness bug of its own — kelvinlet was already
routed here with its parameter clamp silently skipped.
*Gates met:* `test_grid_stroke`'s `gateGridsRoster` grades `supportsBrush`
against an independent 23-entry transcription; snakehook and wingscrape A/B
grids-vs-mesh at **0.00000000** (eps 1e-6), every pre-existing A/B number
unchanged; ctest 135/135 both with and without `--kernels-extra ../brushes`.
The wingscrape A/B first failed at 6.2e-3 and found a real engine bug:
`updateStrokeFrame` left the *previous* stroke's tangent in `strokeDir` on a
stroke's first dab, which wingscrape leans its wings along — fixed in both
executors.
Addon side: `GridStroke_setRenderMatrix` + `texture.apply_render_matrix_grids`
(§8.4 — texdraw/texgrad would otherwise map through the identity), and
`stroke.py`'s `not self._snake_hook` grids gate is lifted (the snake-hook state
is written on the shared `Brush`, which both paths read).

**P1 — domain infrastructure. DONE** (engine `e5ffc03`).
Channel domain/type/persist; face element counts;
the four `(S+1)²` sites; name-keyed `GridBlock` + range check; lazy session-level
allocation; level-change seeding; serializer includes session channels.
*Gates:* in `test_grids_store.cc` / `test_grid_stroke.cc` style — face channel
survives save/load/evict/rehydrate byte-exact; int channel bit-exact; undo blocks
survive a `removeChannel`; `addLevel` does not blank a session channel.

**P2 — binding + capability, behind the kill switch. DONE** (engine `513ed34`,
addon `a36aae8`). §3's dense mirrors; `planForEntry`/`routeForBrush`; §5.6's
stroke-end attr capture — all in the new `source/brush/grid_attr_bind.h`.
(§5.6 asked for *first-touch*; it landed as a **stroke-end** channel capture in
`gridsFoldStroke`, deliberately: "a per-dab snapshot here would capture nothing",
`grid_executor.h:1454-1457`. §5.8 states this correctly.)
`sculptcore_grid_attrs` scene bool, default **off**, spanning P2–P4; the engine
half is a process-global (`GridStroke_setGridAttrs`), because
`GridStroke_supported` answers before any session exists.
*Gates:* the BSMOOTH-on-grids A/B is unchanged (tangent 1.19e-07 / normal
3.06e-07 against the existing split eps); attr undo bit-exact on a COLOR stroke;
the roster golden is graded in both switch positions; full ctest 135/135.

Three deviations from the text above:

- *`storageFor` returns `None` for INT* moved to P3/P4. P2 needs no derived-read
  path — enumerating the six-entry attr manifest showed no read-only
  *retargetable* handle exists — and that fix lives in the in-tree multires
  attribute work, which P2 deliberately does not touch. P2 compiles at engine
  HEAD.
- *`!kernelWrites` → BindDerived* became **DefaultColumn or Unbindable**. A
  read-only handle needs a *source*, not storage; binding zeros to ENHANCE's
  held displacement or FEATURE_ALIGN's cross field (both filled by mesh-path
  pre-passes that are out of scope, §8.4) would make those brushes silent
  no-ops instead of falling back. The zero column binds only where zero is a
  documented default for the layer — today `.boundary.vert.class` (0 =
  interior = plain Laplacian), i.e. today's vclass shim re-expressed as a
  registry of layers rather than a `handle == "vclass"` test.
- **LAYERDRAW cannot widen in P2 either.** Its `slayer` write is a delta the
  mesh path's displace compositor folds into positions; the grids domain runs
  no compositor, so writing the layer alone would move nothing. Expressed
  metadata-only as `use & AttrUse::SCULPT_LAYER` → Unbindable. P2's widening is
  therefore COLOR + COLORSMOOTH only.

One known wart, documented not fixed: `execStage`'s
`if (cmd.writesMask) … else strokeWroteCo_ = true;` books a colour stroke as a
position stroke, so the fold also captures `disp` and runs `gridsWriteback`.
Harmless (writeback skips bit-identical verts) but wasteful; a `cmd.writesCo`
bit would fix it.

**P3 — cage write-back (its own sub-plan, §6). DONE** (2026-08-18; see §6.1
for what landed, the three gate deviations, and the `default_group_id`
inheritance bug it uncovered). Cage-attr readback c-api;
`_flush_multires` branch; cage `_ATTR_KINDS` undo kind; face-domain binary
per-face scatter; partial invalidate + `markGrids`.
*Gates:* face-set paint on a multires object with the checkbox off reaches
`ob.data`, survives save/reload, and undoes; per-dab draw refill touches only
marked grids (assert node count, not eyeballs); the resolution matches what the
per-face rule predicts — **not** a comparison against stock Blender's multires.

**P4 — session channels. DONE** (2026-08-18). Colour (vertex float4, P4a —
§5.7) and polygroup (face, P4b — §5.8) under the checkbox; draw prefers the
session channel. P4b built the grid face iterator (§5.4), which was most of the
phase, and with it POLYGROUP stopped being declined at all.
*Gates:* paint → undo/redo bit-exact via the grid log (`test_grid_stroke`'s P4 and
P4b blocks); `tools/verify_multires_color.py` and
`tools/verify_multires_face_sets.py` headless; colour *renders* — confirmed by eye
2026-08-19 (§5.7).

**P5 — cleanup.** Kill switch **removed**, making the routing unconditional. It
is a development tool and is never promoted to default on -- that is a deliberate
exception to the pattern its three siblings follow (`sculptcore_cpp_dab_loop`,
`sculptcore_grids_programs`, `sculptcore_texture_scripts` are all `default=True`
with the switch retained), so there is no default-on release in between.

`supportsBrush` does **not** become constant true, and §8.1's wording overstates
it: the predicate is already tool-list-free and metadata-derived, and with the
flag on three built-ins still decline for capabilities this domain lacks --
`FEATURE_ALIGN` (cross field) and `ENHANCE` (held per-vert displacement) want a
mesh-path pre-pass, `LAYERDRAW` wants the displace compositor. All three are §8.4
/ §11 out-of-scope items, and the roster golden (`test_grid_stroke.cc:132-153`)
is the ledger: 20 of 23 built-ins run grids-native with the flag on. So P5 keeps
the predicate and records those three as residual decliners with named reasons.

**Removal is the gate for the durability question, not a flip.** While the switch
exists, session-only colour is behind a dev tool; deleting it makes grids-native
what every user gets. So §11's "persisting session channels" item must be settled
before P5 lands -- either by §6.2's cage route or by accepting and documenting
that multires colour is session-only. Not a regression either way: the mesh path
does not persist multires colour either (`_flush_color` is unreachable from
`_flush_multires`, and the slot's colour column is re-derived by
`assignDerivedAttrs` inside every `materialize()`).

## 10. Rollback

`sculptcore_grid_attrs`, default off, introduced in P2, spanning P2–P4 — the same shape as
`sculptcore_grids_programs` (`props.py:139-147`) and `sculptcore_texture_scripts`
(`:167`), which exist because, per `program-grids-routing.md:318-325`, without
an addon lever "the first user-visible change would need an engine revert to roll
back". It differs from those two in the one way that matters for P5: they are
`default=True` with the switch retained, whereas this one stays a development tool
and is deleted rather than promoted (§9, P5). P0a–P0d are each independently
revertable because none of them changes
which brushes reach grids until P0d, and P0d's gate is an A/B.

## 11. Out of scope

- Persisting session channels into a .blend (no Blender container exists).
- Edge-domain storage or edge-attr kernels (numbering only).
- Corner-domain attributes on grids (cage route, permanently).
- Vertex-domain cage scatter — out of scope for §6.2's three reasons (per-base-vert
  dedupe, cage-topology neighbour reads, accepted resolution collapse). **Not** for
  a missing adjoint: rev 2 said "needs an operator-correct adjoint first", which
  §6.2 disproves (sample (0,0) is the corner's cage vert at weight 1).
- A fifth draw channel (that *is* a fork change: `attr_names[4]`, four static
  `GPUVertFormat`s, six `NodeCache` VBOs — and the repo's two-workflow packaging
  order applies).
- The six per-tool pre-pass conditionals and the `gpu_marshal.cc` rosters (§8.4).
- Dyntopo behaviour, unchanged throughout. The **slot path** is not: rev 2 said
  "Dyntopo/slot-path behaviour, unchanged throughout" and two things changed —
  the face-set operators on multires coarsened to base-face granularity (§6.1
  deviation 3, deliberate), and `assignDerivedAttrs` now has slots inherit the
  cage's `default_group_id` (`multires.cc:417-419`).

**No fork change is required for anything in scope** — verified: per-grid-element
storage never crosses the boundary (the provider hands over expanded per-node
arrays), custom-mode undo payloads are opaque byte counts to Blender, the
checkbox is ordinary addon RNA, the cage target is plain `Mesh.attributes` with
`_flush_face_sets` as precedent, and per-node soup/indexed mixing is already legal
in ABI v3.

## 12. Open questions

1. **Settled, was Q1.** The addon resolves brushes by *name* everywhere
   (`stroke.py:177`, `mapping.py:399`, `engine_props.py:89`), so no numeric id is
   persisted — but the enum still is not generated (§8.2), and the gate pins
   names, not ids.
2. **Session-channel memory** — genuinely a measurement, now with §5.3's eager
   all-levels allocation as the thing to fix first, plus §3's per-binding dense
   mirror. Measure in P4.
3. **Settled in P3, was Q3: blend vs replace on partial cage coverage.**
   Replace, binary, no weighting: a cage face takes the value of the
   lowest-indexed cell, across all of its grids, that disagrees with what the
   cage already holds; a face no cell disagrees with is untouched. Every cell of
   a changed face is then re-stamped to the adopted value — leaving one
   non-uniform would make the *next* scatter read its untouched cells as a fresh
   disagreement and propose reverting the face. `verify_multires_face_sets.py`
   gates that non-oscillation directly (a second write-back must return 0).
4. The `grid_stroke` / `grid_undo` / `grid_redo` / `grid_bench` debug verbs
   (`source/debug/script.cc:2182, 2310, 2335`) are undocumented in
   `documentation/debugApp.md`; the A/B gates above lean on them.
