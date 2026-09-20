# Plane-brush frame parity (sculpt_plane, area normal/center, original toggles)

Status: pressure-tested 2026-09-20 (three adversarial lenses: engine
buildability, Blender semantics, host seams/gates); every surviving finding is
folded in below. Not started.

## Problem

- The plane kernel (`engine/source/brush/kernels/plane.sbrush`, `@tool CLAY,
  SCRAPE, FILL`, `@gpu`) projects onto the plane through `surfacePos` along
  `surfaceNo`; both are whatever the host passes per dab.
- The addon passes the raycast hit (`stroke/raycast.py`: barycentric vertex
  normal at the hit, `spatial.h:266`) against the *live* surface, every dab,
  on the per-dab and the batch path (`operator_apply.py:302-307`,
  `_apply_batch`).
- Blender (`mesh/sculpt.cc::calc_brush_plane`, `:3118`) resolves the frame
  from `Brush.sculpt_plane` and related settings none of which our mode reads
  or draws (all six are catalogued `preserved_excluded` in
  `claudeMemory/design/generic-brush-native-coverage-v1.json`):
  - `AREA` (every essentials plane brush): smoothstep-weighted average of
    vertex normals within `radius × normal_radius_factor` (front-facing
    bucket), plus a weighted area *center* within `radius ×
    area_radius_factor` (PLANE type, when the factor is > 0;
    `normal_radius_factor` otherwise, `sculpt.cc:1384-1399`).
  - `VIEW`, `X`, `Y`, `Z`: fixed normal; center = unstabilised area center
    (`calc_area_center`, `:3165-3168`).
  - Data vintage follows `cache->accum` (`:5666-5685`): live positions and
    normals when accumulating; stroke-start originals (positions, normals,
    node bounds, and the cursor raycast itself, `:4863`) when not. `accum` is
    false only for `stroke_method == ANCHORED` or a type in
    `supports_accumulate` (CLAY, CLAY_STRIPS, CLAY_THUMB, PLANE;
    `brush.cc:1920`) with the flag off. **MULTIPLANE_SCRAPE is never
    non-accumulating**, whatever its flag says.
  - `use_original_normal` / `use_original_plane`: after step 1, reuse the
    stroke's first main-pass normal / center (`:3171-3183`); mirror, radial
    and tile passes always take the reflected main-pass frame, toggles or
    not (`:3138`, `:3185-3197`). Both toggles are ignored for the PLANE type
    (`:3130-3133`), which instead runs `calc_stabilized_plane`
    (`:2043-2120`): a rolling average over up to `1 + w × 19` frames of the
    normal (`stabilize_normal`) and the center projected onto the previous
    plane (`stabilize_plane`).
  - Which point the plane passes through, and where the falloff is centered,
    is per brush: Clay = cursor (`clay.cc:182`, area center discarded);
    Clay Strips and Plane = displaced area center, falloff frame located
    there (`clay_strips.cc:394,435`, `plane.cc:390,394`), Plane re-gathering
    its nodes around it (`plane.cc:505-516`); Multiplane Scrape and Clay
    Thumb = cursor, and both force `AREA` and ignore the original toggles
    (`multiplane_scrape.cc:571-576,655-659`, `clay_thumb.cc:158-162,203`).
- Shipped essentials (measured from the bundled asset .blend):

  | brush | type | accum | plane | nrf | arf | stabilize n/p | notes |
  |---|---|---|---|---|---|---|---|
  | Clay | CLAY | on | AREA | 0.75 | 0.50 | 0/0 | plane_offset 0.40 |
  | Clay Strips | CLAY_STRIPS | on | AREA | 1.20 | 0.50 | 0/0 | cube tip (tip_roundness 0.15), plane_offset 0.15 |
  | Scrape/Fill, Flatten/Contrast, Fill/Deepen | PLANE | on | AREA | 0.5–1.0 | 0.5–1.0 | 0/0 | |
  | Trim | PLANE | on | AREA | 0.50 | 0.60 | 1.0/0 | |
  | Plateau | PLANE | off | AREA | 0.30 | 1.00 | 1.0/1.0 | |
  | Clay Thumb | CLAY_THUMB | off | AREA | 1.00 | 0.50 | — | not mapped to an engine kernel |
  | Scrape Multiplane | MULTIPLANE_SCRAPE | (always live) | AREA | 0.50 | 0.50 | — | dynamic mode |

  All SPHERE falloff, no `use_offset_pressure`, no original toggles.
- Consequences today: plane brushes wobble on detailed surfaces (point
  normal), Fill/Scrape flatten to the local height rather than the region
  mean, Plateau/Trim get no stabilisation, and non-accumulating brushes drift
  with their own edits.

## Design

Resolve the frame **inside the engine's CPU executor, per dab, at apply
time**. Host-side is out: the batch path applies several dabs per pointer
event and an accumulating brush's dab *k* must see dab *k−1*; and the
stroke-start data the non-accumulating case needs already lives in the
executor (`.brush.disp.vec/.gen`, `.brush.orig.no`,
`brush_executor.h:700-795`).

Divergences from Blender that the design accepts and documents (not bugs to
chase later): node-granular gather differences (Blender only sees verts in
nodes intersecting the dab sphere — `r` for Clay/Plane, `r√2` for Clay
Strips; ours is a proper sphere query, more inclusive); non-accum "original"
= `co − disp`, which includes `@relaxation` autosmooth drift (Blender reads
undo originals); Blender raycasts the original surface when non-accumulating
(ours is live; needs original tree bounds); plane offset semantics (Clay uses
`initial_radius × plane_offset` with `cache->scale`, sign from strength;
Clay Strips `radius × offset` on the area center; Plane sign from the
stroke-start Ctrl state; Multiplane drops it; `use_offset_pressure`) — the
engine keeps its per-dab `planeoff × radius` for all; Clay Strips' box
falloff and first-dab skip (cube tip needs `grab_delta`), Multiplane's
two-plane / dynamic mode, `plane_trim`, `plane_height/depth`, tilt
(`tilt_apply_to_normal`, post-frame, composes if ever added), projected
(TUBE) falloff (distance metric, cylinder gather, and normal flattening —
no essentials use it), `use_pressure_area_radius` (per-dab factor needs a
batch-row field and is off the registry's pressure convention; stays
`preserved_excluded`). The stroke frame (`updateStrokeFrame`,
`pushStrokeSample`) keeps the cursor even with `center = AREA`.

### Engine

1. **`PlaneFramePolicy`** (`brush/plane_frame.h`, engine-owned, applied by
   the CPU executors only — the WGSL path marshals the hit frame directly,
   `gpu_marshal.cc:111-116`; document that a GPU host gets nothing):
   - `normal ∈ {SURFACE, AREA, VIEW, X, Y, Z}`, `center ∈ {CURSOR, AREA}`,
     `originalNormal`, `originalPlane`, `normalRadiusFactor`,
     `areaRadiusFactor`, `stabilizeNormal`, `stabilizePlane`, `viewAxis`
     (object-space camera axis, surface→eye, per stroke).
   - Default `{SURFACE, CURSOR, …}` = today's behaviour; sbrush-verify
     goldens unchanged.
   - **Sticky**, like `nonAccum`/`anchoredGrab` (`brush_executor.h:296-318`,
     `grid_executor.h:483`): never reset by the executor (there is no
     `beginStroke`; `beginStep` runs *after* the grids push and *before* the
     mesh push, `session.py:132/138` vs `:178/192`), so the host pushes it
     **every stroke**, including the default for non-plane brushes.
   - Setters: mesh via a reflected bound method `executor.setPlaneFrame(...)`
     (the `setNonAccum` convention) or a `MeshStroke_setPlaneFrame(exec, …)`
     c-api; grids `GridStroke_setPlaneFrame(session, …)` (void, like the
     other `GridStroke_set*`). Every new c-api symbol goes into
     `wasm_add_symbols(...)` in `engine/source/brush/CMakeLists.txt:100-155`
     (it generates the native export `.def`) and its argtypes into
     `sculptcore_addon/engine.py::_CApi.__init__`.
2. **Image identity.** The executor today never learns symmetry signs or
   whether a dab is a mirror image (per-dab path: Python reflects and calls
   `MeshStroke_dabResolved` per image; batch path: `DabFrameOverlay` reflects
   `grabFrom/grabTo/viewDir` on the Brush only, `dab_inputs.h:10-32`). Add
   an executor image frame `setImageSign(sx, sy, sz, isMirror)` on
   `CommandExecutor` and `GridBrushExecutor`, exposed as
   `MeshStroke_setImageSign(exec, …)` / `GridStroke_setImageSign(s, …)`;
   `DabFrameOverlay` sets/restores it on the batch path (raw batch fallback
   included), the host calls it per image on the per-dab paths
   (`_apply_one_image` already receives `view_sign`,
   `operator_apply.py:177`; `_preview_apply_image`,
   `operator_preview.py:23`; dyntopo dabs). Do not overload `grabAdd`.
3. **Kernel opt-in** `@planeFrame` → `BrushCommandDef::usesPlaneFrame`. There
   is no precedent to copy (`needsOrigNormals` has no parser/emit chain,
   `emit_cpp.cc:2505-2540`); the new chain is `compiler/parser.cc:187-236`
   (keyword + the valid-attribute error string), `compiler/ir.h:360-395`,
   `compiler/emit_cpp.cc:~2520`, `brush_command.h:481-540`,
   `documentation/brush_dsl.md:51-52`. Set it on `plane.sbrush` only.
   **Regenerate and commit `kernels/generated/plane.brush.gen.h`**
   (`node make.mjs codegen`; the python capi build uses the checked-in
   headers, `make.mjs:594-599`) or the vendored DLL ships the flag off.
   `brush_policy.py` reads flags by name and ignores extras; regenerate
   `typescript/sculptcore/brush/BrushDefFlags.ts` only if the flag is also
   exposed there.
4. **`resolvePlaneFrame`** runs inside `exec()` (`brush_executor.h`), the one
   choke point for `execBrush`, `execProgram`, both `applyResolved*`, the
   batch lambdas and the dyntopo variant. Placement: **before** the
   stroke-start stamp block (`:700`) — the query needs originals only for
   verts earlier dabs stamped, and reads unstamped verts as live == original
   via `safe_get` (pages are lazily materialised, never `operator[]`) — and
   therefore before the prepared-cavity/enhance blocks that read the frame
   (`:801-856`). Only when `cmd.usesPlaneFrame` and the policy is not the
   default. Steps, per dab:
   - **Mirror image** (`isMirror`): no query. Take the stroke's last primary
     frame and reflect normal and center component-wise with the image
     signs (Blender: `symmetry_flip` of `sculpt_normal`/`last_center`). If
     no primary frame exists yet, fall through to the primary path.
   - **Primary, toggles active and not the first primary dab of the
     stroke** (`isFirstOfStep` identifies the first primary,
     `brush_executor.cc:266`): substitute the frozen normal and/or center;
     with only one toggle on, the other quantity is still recomputed.
   - **Primary query**: `rN = radius × normalRadiusFactor`, `rC = radius ×
     areaRadiusFactor` (host already applied the PLANE-only / `> 0`
     fallback rules). Candidate nodes: reuse the dab list when
     `max(rN, rC) ≤ brush->falloffSupportRadius(radius)` (the dab filter's
     radius, `brush_executor.cc:232`), else `tree.filterNodes(cursor,
     max(rN, rC), scratch_)` into an executor-owned scratch vector (not
     `dabNodes_`). Per vert of the candidates' `unique_verts`, skipping
     hidden verts (Blender skips hidden, not masked): position/normal =
     `co − dispVec.safe_get(v)` when `dispGen.safe_get(v) == strokeGen` and
     `nonAccum`, `origNo.safe_get(v)` when stamped and `nonAccum`; live
     otherwise. `d` = distance from the incoming cursor position (sphere
     metric). `w = clamp(3p² − 2p³, 0, 1)`, `p = 1 − d/r`. Normal sum over
     `d ≤ rN` with weight `w(rN)`; center sum over `d ≤ rC` of
     `cursor + (co − cursor)(1 − w(rC))` divided by count. Two buckets by
     `dot(viewAxis, n) > 0` (front) vs `≤ 0` (Blender's `<= 0` goes to the
     flipped bucket); use the front bucket if its normal normalises
     non-zero, else the flipped one. Both empty → center falls back to the
     cursor and the normal is zero → **skip the dab** (Blender's plane is
     degenerate / mask empty), reachable with `normal_radius_factor < 1`.
   - `normal` mode: AREA → the bucket normal; VIEW → `viewAxis`; X/Y/Z →
     unit axis. `center` mode: CURSOR → incoming `surfacePos`; AREA → the
     area center.
   - **Stabilise** (PLANE type, `stabilizeNormal/Plane > 0`): port
     `calc_stabilized_plane` verbatim — ring buffers of `1 + w × 19`
     entries per stroke, normal lerped toward the last stabilised normal,
     center projected onto the last stabilised plane, then the ring-average
     normal and the ring-mean signed-distance correction of the center.
     Exact no-op at 0/0. Runs only for `normal == AREA` (Blender skips it
     for VIEW/X/Y/Z).
   - Record the result as the stroke's primary frame (for mirrors and the
     toggles), write `ctx.surfaceNo` / `ctx.surfacePos`, and **restore the
     incoming frame after this command's kernel** so a later sub-command of
     the same program (`[CLAY, SMOOTH]`) sees the cursor frame on both the
     resolved path (ctx set once per dab, `brush_executor.cc:439-441`) and
     the raw path (per sub-command, `brush_executor.h:1558`).
   - **Re-gather when the center moved** (`center == AREA`): refilter the
     dab's node list around the resolved center with the support radius
     (Blender: `plane.cc:505-516`, #123768) into scratch and run the rest
     of `exec()` — stamp and kernel — on that list. Test with a slope, not
     a centered bump.
   - **Live normals are frame-stale**: `tree->updateQueries()` after a dab
     skips the normal phase (`spatial.cc:3196-3203`); the addon refreshes
     normals at ≤30 fps and stroke end. When `normal == AREA` and the stroke
     accumulates, call the tree's incremental normal update for dirty
     leaves in the hook before the query (cost lands in the perf gate), or
     the per-dab/batch parity and "accum follows" tests are timing-dependent.
5. **Original normals** (`nonAccum && usesPlaneFrame && normal == AREA`):
   set `command.needsOrigNormals = true` in **both** factories
   (`createPreparedCommand`, `brush_executor.cc:108-127`, and the raw
   `createCommand`, `brush_executor.h:1346/1547`) before the stroke's first
   `exec()` — the elision key re-walks leaves when the bit changes, but
   `stampBase` never re-stamps a vert, so a mid-stroke flip leaves stale
   normals. Skirt stamping already covers every vert the halo refresh can
   touch, independent of `normalRadiusFactor` (`:786-791`). **Mesh executor
   only**: `GridBrushExecutor::resolvedCapability` rejects
   `needsOrigNormals` (`grid_executor.cc:86`) and `execStage` asserts on it
   (`grid_executor.h:1162`).
6. **Grids** (`grid_executor.h`): same policy, same image-sign field, query
   via `tree->query(origin, r, dabLeaves_)` → `leaves[li].ownedVerts`,
   positions `d->pos()[v]`, normals `d->no[v]`, `baseFor(v)` for originals
   (`:255-262`, `:1062-1088`). Grid normals are deferred
   (`GridStroke_setDeferNormals(1)`, `session.py:120`; flushed from
   `_mid_redraw` only, so headless they stay at stroke-start until
   `endStep`): the hook must flush queued normals for the query's leaves
   before an accumulating AREA query. Non-accum grids: original positions,
   flushed live normals in the first cut — a documented gap; a grid
   orig-normal stamp (ownedVerts + the lattice 8-neighbourhood
   `refreshNormals` dirties, `grid_domain.cc:226-245`; no skirt concept)
   is a scoped follow-up, not part of this plan.
7. Scratch: candidate-node vector, ring buffers, and the frozen/primary
   frames live on the executor; no per-dab allocation.

### Host (addon)

8. **Registry, not raw props** (repo convention, `test_native_inventory_
   coverage.py`): `use_original_normal`, `use_original_plane`,
   `normal_radius_factor`, `area_radius_factor`, `stabilize_normal`,
   `stabilize_plane` become native rows (`dynamic=False`; add to
   `generate_native_authoring.py` paths, inventory `stable_ids`, coverage
   `supported`, regenerate both sha lines); `sculpt_plane` (ENUM, no
   registry kind) becomes a RETAINED binding `sculptcore.brush.sculpt_plane`
   (`bindings.py`). Flip the six coverage rows off `preserved_excluded`.
   `mapping.plane_frame(bl_brush, settings)` reads `settings.value(...)`
   when generic and raw Brush props otherwise (the `use_accumulate` pattern,
   `operator.py:366-372`).
9. **Policy by Blender type** (`mapping.py`, next to `_MAP`):
   - CLAY → `normal = sculpt_plane`, `center = CURSOR`, toggles honoured
     (`originalPlane` is moot), `rN/rC = normal_radius_factor`.
   - CLAY_STRIPS → `sculpt_plane`, `center = AREA`, toggles honoured,
     `rN/rC = normal_radius_factor`.
   - PLANE → `sculpt_plane`, `center = AREA`, toggles forced off,
     `rN = normal_radius_factor`, `rC = area_radius_factor if > 0 else
     normal_radius_factor`, stabilise factors passed.
   - MULTIPLANE_SCRAPE → `normal = AREA` (forced), `center = CURSOR`,
     toggles off, no stabilise.
   - Anything else → default policy.
   `viewAxis` = the ortho branch of `stroke_settings.view_direction`
   (`view_rotation @ (0,0,-1)` in object space), **negated** to surface→eye,
   regardless of `is_perspective` — Blender's `view_normal` is `viewinv`'s
   z axis, per stroke (`mesh_paint.cc:431-434`), not the per-dab eye ray the
   generic path writes to `Brush.viewDir`. Leave `viewDir` alone.
10. **Non-accumulate rule** aligned with Blender at the existing
    `setNonAccum` derivation: `nonAccum = anchored ||
    (type in {CLAY, CLAY_STRIPS, CLAY_THUMB, PLANE} && not use_accumulate)`;
    MULTIPLANE_SCRAPE is always live.
11. **Push sites**: exactly two, both every stroke — `session.py:132`
    (grids, program-grids included, before `GridStroke_begin`) and
    `session.py:192` (mesh, after `beginStep`); a grids-begin failure falls
    through to the mesh push. No mid-stroke executor switch exists
    (`last_stroke_grids`/`dyntopo_active` are fixed at begin; the batch
    stroke-dead sentinel tears down).
12. **Image sign** per image on the per-dab paths (`_apply_one_image`,
    `_preview_apply_image`, dyntopo) before each dab, primary first with
    `isMirror = false` (primary is always applied before its mirrors,
    `operator_apply.py:372-385`).
13. **UI**: `_draw_brush_settings` (`vanilla_panels.py:96-107`) draws
    `draw_location('BRUSH_SETTINGS')` + `direction` and returns before
    vanilla's `normal_radius_factor`/`area_radius_factor` blocks, and
    `_draw_advanced` (`:197`) is automasking only — so nothing is drawn
    today. Draw `sculpt_plane` (RETAINED, `layout.prop`, essentials are
    asset-editable so this works in memory) after `direction` when the
    brush maps to the plane family; give the new native rows a default
    `BRUSH_SETTINGS` placement so `draw_location` draws them, with the
    Original pair hidden for PLANE and the stabilise pair shown only for
    PLANE, `area_radius_factor` only for PLANE (vanilla's gates).
14. **Engine/addon coupling**: `_CApi.__init__` declares argtypes
    unconditionally, so the first addon commit naming a new symbol must be
    the same commit as the submodule bump, and phase-3 development runs on
    the env-var flow (`SCULPTCORE_PYTHON_PATH` + `engine/build/python` on
    PATH). ABI pin (`LSTL_AbiVersion`) is unaffected. Editing
    `plane.sbrush` changes its sha in `frozen_v0.py` — regenerate with
    `generate_frozen_authoring.py`.
15. Docs: `generic-brush-properties.md` gains a "Plane frame" section with
    the per-type table and the accepted divergences; `engine/documentation/
    strokeDriverGuide.md` §4.1 replaces "purely a host decision" with the
    executor policy; `brush.h:205` comment on `viewDir` stays accurate
    (it is still automask-only).

## Tests and gates

- Engine ctest `tests/test_plane_frame.cc` (register in
  `engine/tests/CMakeLists.txt`): (a) sphere → AREA normal radial within
  1e-4, center inside along it; (b) flat grid with a bump under the cursor →
  point normal tilts ≥ 20°, AREA normal within 1° of the plane, center
  height ≈ region mean; (c) slope with `center = AREA` → verts within radius
  of the resolved center but outside the cursor filter are deformed;
  (d) nonAccum: after dabs displace the region the query returns the
  pre-dab frame; accum: it follows (with the normal refresh in the hook);
  (e) VIEW/X/Y/Z; (f) toggles freeze the primary across dabs while the
  other quantity keeps updating; (g) mirror images with `setImageSign`
  reproduce the reflected primary frame on asymmetric geometry;
  (h) empty buckets → dab skipped, no deformation; (i) stabilise: 1.0/1.0
  over a jittered normal sequence converges to the ring mean, 0/0 is
  bit-identical to no stabilise; (j) `[CLAY, SMOOTH]` program: the SMOOTH
  stage sees the cursor frame on raw and resolved paths.
- Addon background test `claudeMemory/scripts/test_plane_frame.py` on the
  `test_brush_runtime.py` pattern (`stroke_begin` + `apply_dab` /
  `apply_dab_program`, mesh and grids): Plateau (non-accum, stabilised) —
  plane height across a 10-dab stroke within ε of the first dab; Clay
  (accum) — monotone build-up; Fill on a bumpy patch → region mean, not hit
  height; VIEW asserted via `viewAxis` directly (no region needed);
  per-dab vs batch parity by calling `MeshStroke_dabBatchInputs` /
  `GridStroke_dabBatchInputs` with synthetic rows and signs (the operator's
  batch path needs `region_data`; the c-api does not) — bit-exact for
  nonAccum, 1e-6 for accum after the normal refresh.
- Gestures suite: add a `clay` case (essentials Clay, AREA) to
  `run_brush_tests.py`'s tool list — the only harness driving the real modal
  batch + mirror path; `draw` is not plane coverage.
- Perf gate: `bench_multires_sc.py` **`stroke_ms`** median (operator busy
  time) — `stroke_frame_ms` is vsync-locked and blind to per-dab cost — or
  `--vsync off`; Clay (AREA, program-grids batch) is the right brush.
  Interleave two vendored DLL trees via `SCULPTCORE_CAPI_PATH` /
  `SCULPTCORE_PYTHON_PATH` per rep (runner extension: `--engines` cannot
  express two SculptCore builds today), ≥10 pairs, order reversed for half;
  budget 5 %.
- Regression: authoring fixture (`test_authoring_custom_undo.py`, no args),
  `test_native_inventory_coverage.py`, `generate_frozen_authoring.py
  --check`, package smoke (`KERNEL_BY_TYPE` and uniform manifests
  unchanged by an annotation-only flag).

## Phases

1. Engine, mesh: policy + image sign + `@planeFrame` chain + codegen regen +
   `resolvePlaneFrame` (query, buckets, modes, toggles, stabilise, re-gather,
   normal refresh, skip) + orig-normal factory override + c-api/exports +
   ctest (a)–(j) minus grids.
2. Engine, grids: policy/sign on `GridBrushExecutor`, query with deferred-
   normal flush, ctest grids variants of (a)–(e),(g),(h). Document the
   non-accum grids normal gap.
3. Addon on the env-var flow: registry rows + RETAINED enum + coverage regen,
   `mapping.plane_frame`, non-accum rule, two push sites, image signs on the
   per-dab paths, background test, gestures `clay` case, perf A/B. Exit:
   submodule bump and addon change in one commit.
4. UI + docs + frozen regen; rows-ui/gestures/authoring suites; commit.
