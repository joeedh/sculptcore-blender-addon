# Grids-native brush path: addon-facing seams (G5)

**Status: design only — no Blender-side code.** Written 2026-08-04 at the end
of the engine phases of
[plans/multires-grids-native-brush-path.md](../plans/multires-grids-native-brush-path.md)
(G1–G4 landed in the engine; see the plan's gates and
[research/grids-native-brush-path-results.md](../research/grids-native-brush-path-results.md)
for what was measured). This document designs the seams the addon wiring plan
will implement, reviewed against `sculptcore_addon/stroke.py`, `session.py`,
`undo.py`, and `multires.py` as of this commit.

## What the engine now provides

- `Multires::gridDomain(level)` — the dense editable level view
  (`GridLevelDomain`), owned by the Multires stack and dropped at every fold
  point (mesh-path writeback, down-fit, VDM capture, level add/remove, cache
  invalidation). Building it also materializes the level's base+frames, so the
  first grids edit on a zero-disp level is safe.
- `GridTree` — whole-grid leaf clustering, owned-vert partition, sphere query,
  `castRay`. Static per level (no splits/merges, ever) → **leaf ids are stable
  for the level's lifetime**.
- `GridBrushExecutor` (CPU) and `GridGpuStrokeSession` (GPU, via
  `IBrushComputeDispatch`) — run the ordinary generated kernels over the
  domain. Roster: draw, grab, smooth, inflate, kelvinlet, pinch, sharp,
  clay/scrape/fill, mask. `supportsBrush()` is the engine-owned dispatch rule.
- `GridStrokeLog` — per-stroke block undo (owned-vert positions + write-target
  store blocks of exactly the touched grids), swap-based bit-exact undo/redo.
- `Multires::gridsWriteback(level, changed, grids)` — the O(region) stroke-end
  fold (no per-stroke `Multires_serializeStore` blob needed for grids strokes).
- The `GridStroke_*` / `GridTree_castRay` c-api (below).

## 1. The c-api surface the addon calls

Already exported from the capi DLL (`brush/c-api/grid_stroke_c_api.cc`,
`wasm_add_symbols` in `source/brush/CMakeLists.txt`):

```c
GridStrokeSession *GridStroke_new(Multires *mr, int level, Brush *brush);
void  GridStroke_free(GridStrokeSession *s);
int   GridStroke_supported(int tool);              // SculptBrushes id
int   GridStroke_sync(GridStrokeSession *s);       // re-bind after fold points
int   GridStroke_begin(GridStrokeSession *s);      // calls sync internally
int   GridStroke_dab(GridStrokeSession *s, int tool,
                     float ox, oy, oz, nx, ny, nz, int grabAdd);
void  GridStroke_end(GridStrokeSession *s);
int   GridStroke_canUndo/canRedo/undo/redo(GridStrokeSession *s);
double GridStroke_undoBytes(GridStrokeSession *s);
int   GridTree_castRay(Multires *mr, int level, float o[3], d[3],
                       float out10[10], int *nearestVert);
```

**Addon mapping** (`stroke.py` / `session.py`):

- `Session` gains `grid_session_ptr` (one per multires session, created lazily
  on the first grids-capable stroke at the active level, freed in
  `Session.free()` before `Multires_free`, and **recreated on level switch**
  — the session is bound to one level).
- `stroke.py`'s dab dispatch: when `session.multires_ptr` is set and
  `GridStroke_supported(brush_type)`, route `apply_dab`/`apply_grab_dab`
  through `GridStroke_begin/dab/end` instead of
  `tree.filterNodes + executor.execBrush`. Everything else (autosmooth
  programs, dyntopo — meaningless on multires anyway, unsupported tools)
  falls through to the existing materialized path unchanged; the two paths
  interleave safely because every fold point drops and rebuilds the domain
  (`GridStroke_sync` re-binds; the engine test covers the interleaving).
- Symmetry images map to `grabAdd`: 0 on the primary image (advances the
  per-dab first-touch generation), 1 on mirror images of the same dab —
  the same protocol `executor.setGrabAccumAdd` uses today.
- `raycast()`: for grids sessions call `GridTree_castRay` (dense-id
  `nearestVert`, cell/grid identity in `out10[7..9]`). Per the castRay
  memory, hosts mirror the *resolved hit* — same rule applies.
- Brush state: the session reuses the addon's per-session engine `Brush`
  (`_ensure_brush`); the loadProps-destructive rule is unchanged (re-set
  strength/radius before every per-dab write, then the grids path's
  `loadCommonProps` round-trips through props like the mesh path).

**Not yet exported (wire when needed):** per-stroke touched-vert/leaf lists
(for the provider's dirty ranges — see §2's `GridStroke_touched*` additions),
`GridStroke_setNonAccum`, and a `GridStroke_stats` readout. These are
one-liner additions to the existing session object.

## 2. External draw from grids (end state)

Interim (works today with zero fork changes): the engine-side "ride-along
mirror" — after each grids stroke/undo, copy the touched verts' `pos/no` into
the resident slot mesh and dirty the owning `SpatialNode`s (the debug app's
`gridMirrorSync` is the reference implementation). The existing extdraw
provider then redraws correctly. Cost: O(touched) copies + the slot mesh must
stay materialized (see §4). This is the recommended **first wiring step** —
it makes the perf win real (per-dab kernel/capture/undo savings) while
changing nothing in the draw stack.

End state (kills the materialized mesh + the 15.6 s enter):

- Provider geometry source: `GridTree` leaves. Positions/normals from the
  domain (`pos()[v]`, `no[v]`), triangle layout from
  `Multires::levelTriIndicesOut(level)` restricted to each leaf's grids
  (grid-major cell order — each leaf's tri range is contiguous per grid, so
  a leaf's index buffer is a concatenation of per-grid slices).
- **`node_id` = leaf index** (stable for the level's lifetime — GridTree
  never splits or merges). This satisfies the ABI v2 contract (stable
  node_id keys Blender's per-node GPU cache; the positional-pairing
  dyntopo bug cannot recur because the id space is static).
  Level switches change the leaf set wholesale → report all previous ids
  removed + new ids added (same as a rebuild today).
- Update semantics per leaf:
  - `SC_EXTERNAL_DRAW_UPDATE_GEOMETRY`: any owned vert of the leaf touched
    this frame (positions/normals re-upload; topology unchanged).
  - `SC_EXTERNAL_DRAW_UPDATE_TOPOLOGY`: only on level switch / stack
    rebuild (grids topology is static per level).
  - Overlay slots (color@0/uv@1/mask@2/fset@3): mask comes from the
    domain's dense `mask` mirror; color/UV/fset have no grids-domain
    representation yet — the provider falls back to the materialized slot
    for those overlays (i.e. enabling those overlays forces the mirror
    path; acceptable, they're off in the perf-critical sculpt loop).
- Dirty tracking: the stroke session accumulates touched leaves
  (`strokeTouchedLeaves()` exists on the executor; export as
  `GridStroke_touchedLeaves(session, int *out, int cap)` + a per-frame
  drain, mirroring the update-cadence the current provider uses).

## 3. Session-undo integration

Today (`undo.py`): every multires stroke pushes a meshlog step **plus** a full
store blob (`multires_store_blob`, ~31 ms + tens of MB per stroke); level
switches and meshlog resets fall back to `_decode_multires_blob`.

Grids strokes replace both halves:

- Each grids stroke is one `GridStrokeLog` step (`GridStroke_end` closes it).
  `push()` grows a third step flavor in `_pending`: a `("grid",)`-tagged
  entry `(object_name, generation, level, log_cursor_target)` — **no blob**.
  `decode()` seeks the grid log exactly like the meshlog seek loop
  (`GridStroke_undo/redo` until the cursor matches; the
  `DECODE_ACTIVE_STEP` + `is_final` rules map 1:1 — undo leaving a step
  seeks to `target - 1`, landing/redo seeks to `target`). `free()` — the
  grid log is a linear history; freeing a non-newest step is refused today,
  matching the meshlog's model (eviction truncates from the oldest end —
  add `GridStrokeLog::dropOldest()` when wiring the undo-limiter).
- **The store blob becomes a level-*switch* artifact only.** The blob chain
  (`multires_last_blob`) is still rooted at every state the user can land
  on across a level switch: push a blob-carrying step only when the stroke
  is the first after a level switch (or a mesh-path stroke). A pure-grids
  run of strokes at one level pushes zero blobs — that is the remaining
  ~31 ms/stroke + ~10 MB/step of the research doc's ranked list.
- Cross-level undo keeps today's semantics: the grid log dies with the
  domain at a level switch (`GridStroke_sync` reports the rebuild →
  `generation` mismatch in `_pending`) and decode falls back to
  `_decode_multires_blob`, which restores the store at the recorded level
  — bit-exact because grids strokes write back at stroke end, exactly like
  the mesh path's push-time writeback.
- The `downPropDebt` header stays with the blob path (unchanged); the grid
  log carries the debt flag per step internally (`preDebt/postDebt`), so
  within-level seeks restore it without a blob.

## 4. The lazy-mirror rule

The materialized slot (mesh + SpatialTree + the 15.6 s enter at 1 M verts)
becomes demand-driven. A slot is required iff one of:

1. a stroke uses a **non-grids-capable tool** (`GridStroke_supported` false:
   color, bsmooth, polygroup, texdraw-with-attrs, enhance, pose, snakehook,
   wingscrape, featurealign, layerdraw);
2. the extdraw provider still runs mesh-fed (interim §2 state), or a
   color/uv/fset overlay is enabled;
3. an addon feature reads the level mesh directly (mask flood-fill export,
   `Mesh_toArrays` flushes, vertex-group bridge, UV reprojection);
4. `Multires` internals need it (`writeback()` of mesh-path edits — only
   after case 1 actually edited it).

Wiring order: keep eager materialization until §2's end-state provider and
the case-3 readers are ported to domain reads (`levelPositions` + the
occurrence table give everything `multires_map` provides today, without the
mesh). Then `setActiveLevel` stops materializing and `findSlot`-style
accessors go through a `ensureSlot()` that materializes on first use — the
enter cost falls to the domain build (~2.6 s at 1 M today, itself
parallelizable later) plus tree build (~15 ms).

## 5. Open items for the wiring plan

- `GridStroke_touchedLeaves/Verts` exports (provider dirty ranges, mask
  delta export).
- `GridStrokeLog::dropOldest()` for the undo limiter; byte accounting via
  `GridStroke_undoBytes` feeds the existing `size=` argument of
  `custom_mode_undo_push`.
- Mask flood-fill (`push_attr`) on grids sessions should write the domain
  mirror + `flushMaskToStore` instead of the mesh column, so it composes
  with grids mask strokes.
- GPU-in-Blender: `GridGpuStrokeSession` is Scene-free and dispatcher-
  agnostic; the wgpu-native backend needs no host device. Per-dab readback
  measured at ~10 ms (1 M) / ~44 ms (4 M) on this box — the addon wiring
  must use the batched per-frame readback cadence
  (`enableInteractiveReadback` model), not per-dab.
- The mesh-path GPU orchestrator (`debug/gpu_stroke.cc`) was NOT hoisted;
  the grids GPU session is the Scene-free session instead. The hoist
  remains open work for the GPU-brushes-in-Blender plan.
