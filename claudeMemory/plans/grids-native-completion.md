# Grids-native completion: colorsmooth, layerdraw, mask, and the switch audit

Status: **COMPLETE 2026-08-20.** All workstreams landed and gated — CS
(cage-smooth colorsmooth), MK (mask single truth + seed/edit split), LD1–LD3
(layerdraw grids-native + layer c-api + addon layer UI), SW0–SW4 (the switch
audit: mixMode fix, generated GPU uniform packs, `@gpu` kernel map, the
`brush_hooks` hook table, debug-app reflection), and the DOC pass. ctest
137/137. By-eye items listed in the session close-out remain with the user.
Originally: Rev 1 (2026-08-19) was
pressure-tested by five fresh-context adversarial agents (one lens each:
CS buildability, LD semantics, MK semantics, SW feasibility, cross-cutting
seams). Three kill-class findings and twelve majors survived verification and
are folded in below; §0 records the casualties. I re-verified the two findings
that redesign whole workstreams against the code myself before folding.

Successor to [grid-domain-attributes.md](./grid-domain-attributes.md), whose §9
is fully landed. Four workstreams from the user's request — colorsmooth
cage-topology neighbour reads (CS), layerdraw grids-native (LD), proper mask
support (MK), the switch audit (SW) — closed by a consolidated documentation
pass (DOC), including the CLAUDE.md files and grid-domain-attributes §12 Q4.

House rules apply throughout: engine commits first, then the parent gitlink
bump, as one logical change; every engine phase gates on
`node make.mjs build native -j 6` + a clean ctest sweep (baseline **135/135**);
every addon phase gates on `node tools/build-blender-dist.mjs --skip-blender`
plus the named verify scripts run standalone; anything that renders gets a
by-eye check too.

---

## 0. What the pressure test killed (rev 1 → rev 2)

1. **LD's premise was false.** `grid_attr_bind.h`'s "the grids domain runs no
   compositor" comment is stale: the grids domain **already runs a full
   sculpt-layer subsystem** — `Multires::compositeMix` (multires.cc:731)
   weights every enabled cage settings-row layer channel into every position
   decode (`applyDisp`: `pos = base + frame·(disp + Σ wᵢ·layerᵢ)`,
   multires.cc:900-930), `writebackChannel()` (:1195) attributes a stroke's
   residual displacement into the active edit-target layer's own channel,
   `layerAdd/Remove/SetWeight/SetEnabled/SetFrozen/setEditTarget`
   (:1806-1945) carry full weight/frozen semantics, channels are
   `persist=true`, **`GridLevelRule::Delta`, frame-space** ("Delta, like
   disp"), undo already captures the writeback (grid_executor.h:135), and it
   is gated (test_grid_stroke.cc:865-920). Rev 1's design — a new session
   channel plus a new executor fold — would have applied the delta **twice, in
   mismatched spaces**. §2 is redesigned to ride the existing machinery, and
   its old level-rule question is answered by the code: Delta/frame-space.
2. **MK1's contract would have destroyed detail.** The store's seed/edit split
   is load-bearing: the whole-domain mask flush *deliberately* skips
   `noteAttrEdit` (grid_domain.cc:299-304 spells out why — a seed propagated
   as an edit overwrites levels the user actually painted). No upward on-edit
   propagation exists anywhere (`seedLevelFromBelow` runs only at `addLevel`,
   grids.cc:92/119); "restrict down" conflated the 9-point full-weighting
   *filter* (`restrictChannelDown`, multires.cc:1621-1652) with the exact
   *injection* today's import uses (multires.py:308); and rev 1 named the
   wrong provider (`gridsWriteback` is the **position** fold, multires.cc:1206
   — mask never touches it). §3.2 restates the contract with the split intact.
3. **MK's rev-1 ordering was a data-loss window.** With MK2 (grids-native mask
   strokes) landed before MK4 (exchange rebase), the *existing* machinery
   destroys the stroke: `export_mask` reads the stale slot column at every
   level switch and save flush (convert.py:2092/2152), exports a zero delta,
   re-imports the stale mask, sets `grid_mask_dirty`, and the next stroke's
   slot→store sync (`GridStroke_syncMask`, stroke.py:255-258) overwrites the
   store truth. The blob-fallback undo restore has the same clobber chain
   (convert.py:1957-1961). MK4 now lands with or before MK2's holdback
   removal, and the one-directional dirty/sync protocol is retired in the same
   phase.
4. **CS's recommended mechanism was unimplementable as written.**
   `float strength(float3 co)` has no vertex identity in scope
   (brush_command.h:305-329) — an id-indexed falloff span is unreachable from
   it; automasking consumes **no position at all** (cavity is a cache
   prefilled by a BFS over the node's own ring geometry,
   brush_executor.h:917-962, view-normal uses the live cage normal); and the
   kernel's `v.mask` gate reads the node tree-mesh's mask, which nothing seeds
   on a cage node. §1.2 replaces the span with a data-level substitution
   through the synthetic node's tree-mesh view, and the re-derive epilogue
   gains the three steps rev 1 omitted (slot stamp, cage-generation bump,
   draw-leaf flags) — each omission silently reverts the smooth.
5. **SW's derivation rules named mechanisms that don't exist.** "GPU artifact
   exists" discriminates nothing (WGSL is compiled for *every* kernel —
   make.mjs `emitBrushWgslTs`, brush/CMakeLists.txt:259-298); the pre-pass is
   not a def bit; brush factories are **generated** files, so "set by the
   factory" names no wiring; and the claimed CPU-side `brush->props`
   resolution doesn't exist for the named slots (`planeSide`, `activeGroup`,
   `brushColor`, `mixMode` are never props). §4's rows are re-derived.
6. **One production bug found incidentally:** `color.sbrush` declares
   `uniform int mixMode`; it lands in the WGSL uniform block (offset 96) but
   `packBrushUniforms` never writes it — **GPU colour strokes always run mix
   mode 0**. Fixed first, as its own commit, so SW1's bit-for-bit gate stays
   meaningful (§4 row 2).

Findings that were *attacked and survived* are cited inline where the design
leans on them.

---

## 1. Workstream CS — colorsmooth

### 1.1 Today

- The kernel exists and is complete (`engine/source/brush/kernels/colorsmooth.sbrush`):
  `for_neighbor` average of a float4 `color @use(color)` layer, `@relaxation`,
  `save vertex color`. It runs on the mesh executor already, and its only
  `v.co` read is `strength(v.co)` (verified in the generated
  colorsmooth.brush.gen.h:30).
- **The addon never selects it, on any mesh.** The Shift smooth toggle picks
  `BSMOOTH` unconditionally (`stroke.py:687`), including over a PAINT brush —
  where vanilla Blender runs a colour blur. So the first gap is plain-mesh
  parity, before multires enters the picture.
- On multires, colour is `Derived` (Blender declares only the mask as a host
  grid attr), so a colour stroke takes the cage route: kernel on the slot
  mesh, per-dab collapse onto the cage. §6.3 of the predecessor plan proves
  this collapse is *identical* to painting the cage for a pointwise kernel and
  **wrong** for a neighbour-reading one: grid-lattice neighbours of sample
  (0, 0) are mid-edge and face-centre samples, not the cage 1-ring.

### 1.2 The design: run the smooth on the cage itself

- **Visit set:** per dab, dab-region hits → grid → corner → cage vert, deduped
  per base vert. The region query is the **slot tree** (`dabGrids`,
  multires.cc:493) — the same index the existing colour scatter uses; the cage
  is written, never queried spatially.
- **Kernel inputs, substituted at the data level:** the cage dab builds one
  synthetic node whose tree-mesh view supplies the kernel's fine-surface
  inputs — `co` = the per-cage-vert **limit positions** (grid sample (0, 0),
  snapshotted at stroke start; a paint stroke moves nothing), `mask` = the
  grid-(0, 0) mask samples (the kernel gates on `ctx.masks(v.v, v.mask)`,
  brush_iterators.h:75-78 — leave it unseeded and shift-smooth paints through
  masks on multires only). `strength(v.co)` then evaluates at limit positions
  with **no codegen change and no new template instantiation** — the
  substitution is which spans the node's tree-mesh view points at, not a new
  type. `v.color`/`nb.color` bind to the cage columns; neighbours are the
  cage's own disk links (a full `mesh::Mesh` — no new adjacency). Fallbacks if
  the tree-mesh view resists pointer substitution (verify first in CS2):
  passing `v.v` into `strength()` (touches every generated kernel + the GPU
  intrinsic emission — rejected unless forced) or a bespoke cage entry that
  computes falloff outside `strength()`.
- **Automasking on the cage route grades cage geometry** — cavity's cache is
  prefilled from the node's own ring geometry and view-normal reads the live
  cage normal; no span can redirect either. V1: gate cavity automasking off
  for cage dabs (documented); accept view-normal against cage normals.
- **A dedicated cage executor instance,** not the session's slot executor —
  reuse would leak per-mesh state (`movedStamp_`, coPrev) and capture cage
  attrs into the *slot's* meshlog. Null-meshLog capture is safe
  (capture_policy.h:31); undo is the addon's cage-column snapshot instead.
- **Column ensure:** white-flood-ensure the cage colour column before the
  first cage dab. `_seed_cage_draw_attrs` seeds it only when the Blender mesh
  already has a colour layer (convert.py:385-390); a bind-time zero-init is
  black, while the scatter path deliberately white-floods (multires.cc:557-564).
- **The post-dab epilogue is four steps, not one** — the existing scatter
  epilogue (multires.cc:626-628, subdiv_c_api.cc:650-658) is the template:
  1. prolongate the touched verts' grids from the cage (`refreshFromCage`,
     grid_attrs.cc:730-803 — bilinear with sample (0, 0) = cage value, so
     collapse∘derive = identity) + `markGrids`;
  2. **`stampSlotVertFloat4`** — re-stamp the resident slot column; without it
     the *next* paint dab's collapse (which reads slot corners,
     multires.cc:581) reverts the smooth, and so does the trailing release-dab
     scatter hard-wired into `undo.push` (`_push_cage_columns`,
     undo.py:166-168) — stamping makes that unconditional scatter idempotent;
  3. **`noteCageAttrEdit`** / cageGeneration bump (multires.cc:396-408) — else
     other levels never re-derive on materialize;
  4. **slot-tree leaf `Spatial_UpdateGPU` flags** — during a mesh-path stroke
     the draw provider is the SLOT (§6.1 deviation 1); without the flags the
     viewport shows nothing until another stroke touches the nodes.
  `generation_` stays untouched throughout.
- **Undo:** unchanged — `undo.snapshot_cage_columns` covers colour once
  `last_stroke_color` is set (undo.py:100-175).

### 1.3 Phases

- **CS1 — plain-mesh wiring (addon only).** Shift smooth over a PAINT brush
  picks `COLORSMOOTH` (`stroke.py:687`) — **gated to non-multires sessions**:
  a multires session keeps BSMOOTH until CS3, because flipping it early ships
  §6.3's wrong grid-lattice smear for the whole CS1→CS3 window. Factor the
  toggle-kernel pick into a plain function: the verify harness drives
  `stroke_begin`/`apply_dab` directly and bypasses the modal invoke code
  (verify_multires_color.py:179-205), so an inline pick is untestable.
  Iteration strengths apply; undo needs nothing (`save vertex color` routes
  the meshlog capture). *Gate:* headless colorsmooth stroke on a plain mesh —
  movement toward the neighbourhood mean + undo restore; by-eye on a painted
  sphere.
- **CS2 — engine cage-dab entry.** The design above, exposed through the
  c-api. First task: verify the tree-mesh view accepts data-level span
  substitution; fall back per §1.2 if not. *Gate:* `gateCageColorSmooth` —
  needs the executor harness imported (test_multires_attrs.cc has none
  today); paint a cage, run a covering smooth dab, assert movement toward the
  **cage 1-ring** mean on a topology where it differs from the grid-lattice
  mean, falloff graded against sample-(0, 0) positions, mask respected, all
  four epilogue steps observable (slot column stamped — assert a trailing
  scatter is a no-op), `generation_` unchanged.
- **CS3 — multires wiring (addon).** Flip the multires gate from CS1; route
  shift-smooth-over-PAINT to CS2's entry; skip the per-dab scatter for this
  stroke shape (the trailing `undo.push` scatter stays and is idempotent by
  CS2's slot stamp); set `last_stroke_color` on toggle strokes so cage
  snapshots run. *Gate:* `verify_multires_color.py` grows the case — paint at
  L5, shift-smooth, assert cage-resolution smoothing **after `undo.push`**
  (not after the last dab), save/reload, undo; by-eye at two levels.

---

## 2. Workstream LD — layerdraw grids-native

### 2.1 Today (corrected by the pressure test)

The grids domain **already has** the layer subsystem — compositor, writeback
attribution, weight/frozen/enable, edit targets, Delta/frame-space persistent
channels, undo coverage, and a gate (§0 item 1 for the map). What is actually
missing is exactly two things:

- **LAYERDRAW-the-kernel cannot run on grids**: its `slayer @use(sculpt_layer)`
  write is `Unbindable` (grid_attr_bind.h:119-124), behind a comment the
  pressure test proved stale. It is one of the roster golden's three declines
  (`test_grid_stroke.cc:245`).
- **The addon drives none of it**: Blender's LAYER brush sits in
  `mapping.UNSUPPORTED` (`mapping.py:141`), and the addon has no layer
  add/select UI. Mesh-path layerdraw is reachable only from the debug app and
  tests.

### 2.2 Design: ride the existing machinery — no new channel, no new fold

- Bind the kernel's `slayer` write to a **per-dab TEMP scratch**. After the
  kernel, the executor folds `co += w·Δslayer`, with `w` read from the cage
  settings row of the **active edit target** (`setEditTarget`). The existing
  `writebackChannel()` attribution then lands the stroke's displacement in
  that layer's Delta/frame-space channel — weight re-evaluation, frozen, and
  enable all keep working because `compositeMix` owns them, and undo is
  already atomic (`gridsFoldStroke` captures co store blocks + every dirty
  mirror channel into one `log->endStep`, grid_executor.h:95-171 — survived
  attack; LD2 is test-only on this front).
- **Grids LAYERDRAW requires an active edit target.** Without one the binding
  stays `Unbindable` — mirroring the mesh path, where `LayerEditScope` is
  inert without a settings row. `gridAttrPlan`'s SCULPT_LAYER branch therefore
  becomes a **conditional early return**, not a fall-through — falling through
  reaches the Derived-Unbindable branch (grid_attr_bind.h:125-136) and the
  flip silently does nothing. The stale "runs no compositor" comment and the
  header's "Only a Host- or Temp-class layer gets here" line die with it.
- **Level rule: resolved.** The engine's own layer channels are Delta,
  frame-space, "like disp" (multires.cc:1829-1837) — that is the rule under
  which `co = base + Σ w·d` survives a level switch. Rev 1's Authored
  object-space recommendation is dead.
- `strokeWroteCo_` needs no work — `execStage` already sets it for every
  non-face, non-mask kernel.

### 2.3 Phases

- **LD1 — the bracket + the conditional plan flip.** *Gate:* new
  `gateGridLayerDraw` in `test_grid_stroke.cc`: with `layerAdd` +
  `setEditTarget`, a layerdraw dab moves co by `w·Δ` and the residual lands in
  the target layer's channel with channel 0 byte-identical (the mirror of the
  existing :865 DRAW-with-edit-target gate); a post-stroke `layerSetWeight`
  re-composites; without an edit target, `supportsBrush` still declines.
- **LD2 — golden + parity + undo tests.** The flat golden at
  `attrs == nullptr` **stays `- 3`** — `supportsBrush(tool, nullptr)` skips
  the storage-class term (test_grid_stroke.cc:219) and cannot see conditional
  support; add a second assertion under a session with a live edit target
  where the count is `- 2` (unconditional decliners: FEATURE_ALIGN, ENHANCE —
  both decline on read-only non-zero-default attrs independent of `attrs`;
  verified). Parity dab vs the mesh path requires **both** sides configured —
  the mesh fold is inert without a settings row (`test_layer_stroke_undo.cc`'s
  `layer_add` + retarget machinery). Undo gate: grids stroke restores co + the
  layer channel atomically. Full ctest sweep.
- **LD3 — addon wiring (decision pending, §7 Q1).** Scope grew in rev 2: it
  is not just `LAYER → LAYERDRAW` in `mapping._MAP` — the addon must also
  manage layers (create-on-first-use or a layer list UI, `setEditTarget`
  plumbing, radius uniform; no `use_persistent` in V1). If not wired, LD ends
  at LD2 and `mapping.UNSUPPORTED` gets an updated reason string.

---

## 3. Workstream MK — mask, one truth

### 3.1 Today: three part-owners and two exclusions

Blender **does** store multires mask data (CD_GRID_PAINT_MASK), and the fork
already exposes both directions at `totlvl`
(`Object.multires_mask_to_vert_values` / `multires_mask_from_vert_values`,
multires_reshape.cc:200-253 — verified; **no fork change needed**). But on our
side the truth is split:

- The store has a Host-class `.spatial.v.mask` channel (declared at enter).
- While a slot mesh is resident, the **slot column** is authoritative
  (mesh-path MASK strokes write it; `export_mask` reads it first,
  multires.py:341-342).
- While lazy, the **grid domain / store** is (`Multires_read/writeDomainMask`,
  level-parameterized — verified, subdiv_c_api.cc:135/154).
- The addon carries a numpy delta machine (`session.multires_mask_base`) that
  restricts by injection on import and prolongates the user's delta on export
  so finer-lattice detail survives a coarse-level edit.

Consequences, all user-visible: grids-native MASK strokes are held back
(`stroke.py:165-186`); mask flood fill, mask filter, and the box/lasso mask
gestures are excluded on multires entirely (`ops.py:11-30`, gestures via
`ops._session`).

### 3.2 Design: the store's Host channel is the single truth

Everything else becomes a cache with a freshness stamp. The contract, restated
with the pressure test's corrections:

- **The seed/edit split stays — edits propagate, seeds never do.** The two
  `flushMaskToStore` overloads already encode it (grid_domain.cc:289-319):
  whole-domain = host seeding a level (deliberately no `noteAttrEdit`),
  touched-verts = a user edit (notes the edit, down-debt fires). MK1 preserves
  this split in every new path it adds.
- **Two distinct restriction operators, chosen per direction.** Seeding
  restricts by **injection** (exact at coincident sites — reproduces today's
  import bit-for-bit); edit debt restricts by **full-weighting**
  (`restrictChannelDown`, matching disp). They are not interchangeable:
  prolongate∘full-weight is not the identity.
- **Upward on-edit propagation is new machinery.** Nothing in the store
  prolongates an edit to finer levels today (`seedLevelFromBelow` is
  addLevel-only). MK1 builds the store-side equivalent of the addon's numpy
  delta machine: on an edit at level L, delta-prolongate to finer levels
  (preserving their authored detail), full-weight-debt to coarser. This is
  the load-bearing phase; everything after consumes the guarantee.
- **The write entry points get an edit-flavored path.** `writeDomainMask`
  whole-domain is a *seed* by design and must stay one; mask ops are *edits*
  and need a touched/level write that notes the edit. `gridChannelWrite`
  writes the store but leaves the dense `GridLevelDomain::mask` mirror — which
  both the grids draw source (grid_draw_source.cc:177/201 uploads `d.mask`)
  and grids kernels actually read — stale; an edit write must refresh the
  mirror. (There is no standalone `markGrids` c-api — it only rides inside the
  write calls, subdiv_c_api.cc:611/651 — so the plan stops citing one.)

### 3.3 Phases

- **MK1 — store-side edit semantics.** The contract above. *Gate:*
  `test_multires_attrs.cc` — author fine-lattice mask detail at top, edit at
  L2 via the edit path, assert top carries edit + detail; seed a level and
  assert coarser levels untouched; level add/remove round trip.
- **MK4 — exchange rebase + protocol retirement** *(lands with or before MK2
  — the rev-1 order was a data-loss window, §0 item 3).*
  `import_mask`/`export_mask` move onto the store's top level via
  `grid_channel_c_api` (exact — the fork pair operates at `totlvl` both ways);
  the `multires_mask_base` delta machine dies (MK1 owns the semantics); the
  **one-directional `grid_mask_dirty` / `GridStroke_syncMask` slot→store
  protocol is retired** — it fires on unrelated events (attr-undo undo.py:365/
  440/469, level switch convert.py:2109, session create stroke.py:230) and
  would overwrite store truth from a stale slot column. Replacement: a store
  **mask-generation counter** (new — `generation_`/`cageGen_` track rebuilds,
  nothing tracks mask edits) with direction-aware sync. The blob-fallback undo
  restore **trusts the restored store channel** (GridsStore v3 serializes
  channels, grids.h:59) instead of re-importing from CD + flagging dirty
  (convert.py:1957-1961). Stale-column consumers to convert, enumerated:
  `gridsSyncMaskFromSlot`; mesh-path kernel mask gating + capture
  (capture_policy.h:63); `export_mask`'s slot-first read; slot-provider mask@2
  (external_draw.cc:290); ops.py reads. Delete `_level_lattice`/`_prolongate`
  when the last caller goes.
- **MK2 — grids-native MASK strokes.** Delete the `_mask_kernel_id` holdback.
  The engine side is genuinely complete behind it (survived attack:
  `strokeWroteMask_` → touched-verts `flushMaskToStore` + `noteAttrEdit` +
  GridStrokeLog mask capture, grid_executor.h:138-143/1028-1033; stroke draw
  reads `d.mask` directly). Resident slot columns re-sync store→slot on
  materialize and post-stroke, gated by MK4's generation counter. *Gate:*
  grids MASK stroke, then a mesh-path read AND a level switch + export see the
  stroke (the rev-1 gate could not see the clobber).
- **MK3 — mask operators on multires.** Flood fill, filter, gestures take
  `allow_multires`. **Read side:** gestures project `session.mesh_ptr`
  positions (gestures.py:37) and the filter builds adjacency from
  `mesh_topo_arrays(mesh_ptr)` (ops.py:90/155) — both dead on a lazy slot
  (`mesh_ptr == 0`). V1: the ops **ensure the slot** (one-shot operators; the
  materialization cost is acceptable); a domain-lattice c-api is the recorded
  alternative, not chosen. **Write side:** the MK1 edit path at the active
  level, plus the resident slot column. **Undo:** a store-mask step kind —
  `_ATTR_KINDS`' shape is `(dtype, count(mesh), Mesh_write*, mesh_ptr)`
  (undo.py:70-98) and `_decode_attr` carries no level, so this is a new shape,
  not a fit: a **level-tagged** blob (undo can cross a level switch; guard on
  level-count mismatch) whose restore **re-fires edit propagation** — a raw
  level write-back leaves every other level carrying the undone edit.
  `CAGE_FACE_I32` is *not* the precedent (it is a mesh column on `cage_ptr`);
  `_CAGE_RESTAMP` (undo.py:103-106) is, for the resync half.
- **MK5 — the gate script.** New `tools/verify_multires_mask.py`: grids-native
  mask stroke at top and coarse levels; flood fill + filter on multires; the
  detail-preservation case; save/reload round trip through CD_GRID_PAINT_MASK;
  undo of both step kinds **with the restore at a different active level than
  the push**. The box-gesture case is scoped to write/undo plumbing with an
  injected projection — `execute()` cancels without `context.region_data` and
  projection scales by region width/height, which are dead under
  `--background` (gestures.py:34-48/211-214); selection geometry moves to the
  by-eye list (mask overlay while switching levels, masked sculpt stroke
  respecting the mask).

---

## 4. Workstream SW — the switch audit

Full inventory, with verdicts revised where the pressure test broke them. The
principle stands: per-tool knowledge lives with the tool; call sites are
uniform. But **builtin factories are generated files** (`*.brush.gen.h`, "DO
NOT EDIT"), so "the factory sets it" names no mechanism — per-tool hooks and
clamps live in either a new `sbrushc` annotation or **one hand-written
tool-keyed hook table** (a single file beside gpu_marshal; pick per row).

| # | Site | What it is | Verdict (rev 2) |
| --- | --- | --- | --- |
| 1 | `gpu_marshal.cc:33-56` `kGpuKernels` | hand-written tool → GPU kernel-stem roster | **Generate — from an explicit `@gpu` annotation**, not artifact existence (WGSL is compiled for every kernel; "artifact exists" admits SNAKEHOOK/COLORSMOOTH/LAYERDRAW, all deliberately absent) and not a pre-pass def bit (none exists — the pre-passes are hand-written executor conditionals `sbrushc` never sees). The tool→stem half is already registry knowledge (survived: `@brush("plane")` + `@tool CLAY, SCRAPE, FILL`; `sbrushc --builtin-registry` consumes `@tool`). Emitted by `node make.mjs codegen` as a checked-in `.gen.h`. |
| 2 | `gpu_marshal.cc:136-169` `packBrushUniforms` | per-tool switch copying named Brush fields into aliased uniform slots, pinned by a FRAGILE offset-72 `static_assert` | **Table-drive via codegen-emitted Brush-*member* accessors** — the claimed `brush->props` name→value resolution does not exist (`props` registers only dynamic non-`@static` float uniforms; `planeSide`/`activeGroup`/`brushColor`/`mixMode` are never props; the CPU path resolves by compile-time member access in generated code, plane.brush.gen.h:72). Codegen must also implement WGSL uniform alignment (vec3/vec4 = 16) — offsets are emittable (uniforms append in declaration order after the fixed 72-byte prelude, emit_wgsl.cc:1098-1155). **Precursor commit: fix the mixMode bug** (§0 item 6) so the gate stays bit-for-bit. |
| 3 | `gpu_marshal.cc:97-102, 210-219` host clamps + ctx tail | kelvinlet clamp duplicated from its host stage; grab/kelvinlet/pose global ctx blocks | Clamp → the hook table (row 4's mechanism). Ctx tail: **keep for V1**, named as a grep-gate survivor. |
| 4 | `brush_executor.h:1455, 1471, 1509, 1567, 1603, 1627, 1703` | per-tool pre/post-pass conditionals | **Hook-table-drive, with a three-shape taxonomy**, not two: `stepPreFreeze` (BSMOOTH — must run *before* `freezeTopo()`), `dabPre` (ENHANCE/FEATURE_ALIGN region passes — after the thaw decision), `dabPost` (POLYGROUP dirty-mark — runs *after* `exec()`, :1509/:1703). FEATURE_ALIGN's passes exist **only in `execProgram`** (:1567/:1603), not `execBrush` — preserve the asymmetry or deliberately unify (§7 Q5). `execBrush` + `execProgram` are the whole surface (survived: the batch c-api delegates, mesh_stroke_batch_c_api.cc:152; grid executor has zero per-tool sites). |
| 5 | `grid_executor.h:1079` | orig-normals assert | **Already done** — it asserts on the def bit today, no roster premise. Row satisfied; no work. |
| 6 | `debug/script.cc:730-764` | name → tool switch | Replace with the generated name tables (`kBuiltinBrushNames`, builtin_brushes.gen.h:37). Reflection is a superset of today's list — benign (verified). |
| 7 | `debug/script.cc:1393-1407, 1622-1635` | two `gpuTool` OR-chains | **Not a drop-in predicate swap**: the chains differ from the map *and each other* (first lacks SCRAPE/FILL; second also GRAB — the GRAB omission looks deliberate). Per-site decision recorded in the commit, then the predicate. "Scripts still run" cannot catch a backend reroute — the gate is a per-verb backend assertion. |
| 8 | `debug/ui.cc:160+` | UI tool roster | Iterate the enum, filtered by the same capability predicates. |
| 9 | `types.h` `SculptBrushes` enum | hand-written ids | **Keep**, per grid-domain-attributes §8.2. |
| 10 | `mapping._MAP` / `COLOR_TYPES` / `FACE_SET_TYPES` (addon) | Blender-brush-type → kernel + host policy | **Keep**: host knowledge. Reason strings refreshed by LD3/this plan. |
| 11 | `grid_gpu_session.h:69-74` | `kernelFor` = `supportsBrush` ∧ GPU map | **Keep** (survived attack) — composes two predicates; correct by construction once row 1 is generated. |
| 12 | `props.py:142` / `stroke.py:188` / `ui.py:226` (addon) | `Scene.sculptcore_grids_programs` — the program-grids-routing kill switch, still UI-exposed | **Decide** (§7 Q4): the grid-attrs switch died by the "a kill switch is a dev tool — the routing ships by deleting the switch" precedent (`9286167`); this older sibling looks due for the same. Its docstring citations go stale with MK2 either way. |
| 13 | `debug/interactive.cc:353` | hardcoded `currentTool = SMOOTH` default | Trivial; fold into SW4. |

### Phases

- **SW0 — mixMode fix.** `packBrushUniforms` writes `mixMode`; own commit;
  gate: a GPU colour stroke with a non-zero mix mode differs from mode 0 and
  matches the CPU path.
- **SW1 — uniform descriptors.** Codegen emits per-kernel
  `{Brush member, slot offset}` rows (member accessors, WGSL alignment);
  `packBrushUniforms` becomes the loop; offset-72 assert deleted; clamp moves
  to the hook table. *Gate:* `test_grid_gpu.cc` + `test_automask_gpu.cc` +
  the GPU A/B debug verbs bit-for-bit on a fixed seed; ctest sweep.
- **SW2 — generated GPU kernel map.** `@gpu` annotation + registry emission;
  golden asserts the generated rows equal today's hand list. *Gate:* same GPU
  tests + the golden.
- **SW3 — hook table** (after workstream CS — same executor region). The
  three-shape hooks; the eight `brush_executor.h` sites become uniform
  invocations; FEATURE_ALIGN asymmetry per §7 Q5. *Gate:* ctest sweep (the
  enhance/featurealign/polygroup/bsmooth tests exercise every hook) + the
  grep acceptance, **restated**: the eight SW3 sites in `brush_executor.h` are
  gone; `grid_executor.h` stays at zero `SculptBrushes::` hits (it already
  is); `gpu_marshal.cc`'s survivors are exactly the row-3 keeps, each
  commented with its table row.
- **SW4 — debug app.** Rows 6/7/8/13. *Gate:* the A/B debug verbs still run
  with unchanged backends per row 7's per-verb decision; sweep green.
- Perf note: all stroke-setup cadence; no benchmark owed. Anything that lands
  in a per-dab path takes the interleaved-A/B rule.

---

## 5. Workstream DOC — the closing documentation pass

Each phase updates the docs its change invalidates as it lands; DOC is the
consolidated audit at the end:

- **`engine/CLAUDE.md`** — the "Attributes on the grid domain" subsection:
  mask's single-truth story (seed/edit split included), the grids layer
  subsystem + LAYERDRAW's edit-target condition, the cage neighbour route,
  the roster-golden pair (flat −3 / edit-target −2).
- **`engine/documentation/projectIndex.md`** — new/changed files.
- **`engine/documentation/debugApp.md`** — document `grid_stroke`,
  `grid_undo`, `grid_redo`, `grid_bench` (script.cc:2182/2310/2335), closing
  grid-domain-attributes **§12 Q4**.
- **`engine/documentation/sculpt-layers-design.md`** — the grids side: it
  exists already (compositeMix/writebackChannel); document it plus LD1.
- **`engine/documentation/addingSBrushUniforms.md`** — its offset-72 alias
  regime (lines 187-227) is exactly what SW1 deletes; rewrite for the
  descriptor tables. *(Missed by rev 1.)*
- **`engine/documentation/brush_compute.md` / `brush_dsl.md`** — `@gpu`, the
  descriptor tables, the hook table.
- **Source comments that are already wrong**, fixed by their phases:
  `grid_attr_bind.h`'s "runs no compositor" + its header's storage-class line
  (LD1); `grids_capable`'s docstring (MK2/Q4).
- **Repo `CLAUDE.md`** — audit; expect no edit.
- **`claudeMemory/plans/grid-domain-attributes.md`** — §11's colorsmooth /
  pre-pass / gpu_marshal bullets and §12 Q4 get "superseded → this plan"
  pointers (status lines only).
- **`claudeMemory/README.md`** — index entry updates as workstreams land.
- Strip every `CLAUDENOTE:`; audit each touched comment; SPDX on new files.

---

## 6. Order and dependencies

```
MK1 → MK4 → MK2 → MK3 → MK5     (MK4 with-or-before MK2 is a data-integrity
                                  constraint, not a preference — §0 item 3)
CS1 → CS2 → CS3                  (CS1's multires toggle stays gated off
                                  until CS3)
LD1 → LD2 → (LD3?)
SW0 → SW1 → SW2;  SW3 after CS;  SW4 last of SW
DOC last, after everything
```

The real cross-workstream textual collision (rev 1 named a false one): **MK2,
Q4's switch deletion, and CS3 all rewrite `grids_capable`
(stroke.py:165-198)** — land them in that order or as one coordinated series.
LD2's roster golden and SW2's map golden are independent files (LAYERDRAW has
no GPU kernel and never enters the map). Every engine phase co-commits its
gitlink bump.

## 7. Open questions — RESOLVED by the user, 2026-08-20

1. **LD3: wire it, with a layer list UI.** Full layer management panel
   (add/remove/select/weight) plus the mapping entry — the larger addon phase.
2. **MK1: default taken** — the store-side edit-propagation machinery replaces
   the addon's numpy delta machine.
3. **SW scope: default taken** — SW4 (debug-app cleanup) stays in scope.
4. **The `sculptcore_grids_programs` switch: delete it**, folded into MK2's
   `grids_capable` rewrite, per the `sculptcore_grid_attrs` precedent.
5. **FEATURE_ALIGN (SW3): unify both paths** — `execBrush` gains the region
   pre-passes too. A deliberate behaviour change in the debug app's
   single-tool path; SW3's gate must cover it explicitly.

## 8. Out of scope, restated

- A Blender container for persistent grid channels (fork change; unchanged
  from grid-domain-attributes §11). Note the layer channels already persist
  in the engine store — this item is about *Blender-side* persistence.
- Edge- and corner-domain grid attributes (unchanged).
- A fifth draw channel (fork change; unchanged).
- Vanilla LAYER-brush persistent-base semantics (`use_persistent`) — even if
  LD3 lands, V1 is the live layer only.
- §12 Q2 (session-channel memory measurement) — still open, still a
  measurement; not folded in here.
