# Dyntopo region gating: Blender's recursive graded queue vs SculptCore's hard sphere clip

Read 2026-09-22 against `C:\dev\blender\main` (`custom-object-modes`) and
`engine/source/dyntopo/dyntopo.h`. The comparison below is code-level. Blender's
rule was then ported as a second region mode the same day; the measured results
are in the last section, which supersedes the predictions made above.

## The one-line difference

- **Blender** seeds candidates from *faces* whose closest point is inside the
  brush sphere, then **recurses outward across the mesh** with a goal length that
  grows 1.6x per hop. Refinement density decays geometrically outside the brush
  instead of cliffing at the rim.
- **SculptCore** gates every candidate on *edge midpoint inside the sphere*, with
  no outward propagation at any stage. Splits, flips and smoothing are all
  clipped at the same hard sphere.

## Blender: how the gradation is produced

`source/blender/blenkernel/intern/pbvh_bmesh.cc`

- Seed (`long_edge_queue_face_add`, :895): for each face in a topology-marked
  leaf, test `edge_queue_tri_in_sphere` (:683) — closest point *on the triangle*
  to the brush center within `radius`. The test is on the **face**, so a huge
  triangle straddling the brush qualifies even though all three of its edge
  midpoints are far outside.
- Every edge of a qualifying face longer than `limit_len` enters
  `long_edge_queue_edge_add_recursive` (:835) — which **has no sphere test at
  all**. Propagation is purely by mesh adjacency and length.
- Per recursion hop (:862-880):
  - `even_generation_scale = 1.6` — goal length multiplies by 1.6 each hop, so a
    hop-k edge must exceed `l_max * 1.6^k` to be queued. This is the density
    gradation.
  - `even_edgelen_threshold = 1.2` — the neighbour must also be 1.2x longer than
    the edge that recursed into it, which stops a merely-skinny triangle from
    dragging in its neighbours.
  - Walks the full radial fan of the edge, recursing through each incident face's
    other two edges.
- Priority is `-len^2` (:807) — longest edge first, globally, across the whole
  recursively-gathered set.
- Re-seeding during the split loop: `pbvh_bmesh_split_edge` calls
  `long_edge_queue_face_add` on **both** new faces (:1149, :1162), so the
  recursive walk re-runs from the refreshed geometry as the pass proceeds. A new
  face outside the sphere fails the tri test and adds nothing, so outward work
  decays rather than runs away.
- **Explicit valence relief** (:1172-1179): after each split, if the apex
  `v_opp` ends up with more than 8 incident edges, *all* of its edges are pushed
  with `long_edge_queue_edge_add` — at the **unscaled** `limit_len`, not the
  hop-scaled one. This is the direct answer to "one big triangle fanned from a
  single apex".
- Collapse is **not** graded: `short_edge_queue_face_add` (:917) adds every edge
  of an in-range face, no recursion. The outward grading is subdivide-only.
- Ordering bias exists on collapse only: `short_edge_queue_priority` (:812)
  deprioritizes boundary (x1.5) and boundary-adjacent (x1.25) edges.

### Why this avoids high-valence hubs

The 1-triangle -> 2 split scheme connects the new midpoint to the apex opposite
the split edge. Split the same edge of a large triangle n times without touching
its other two edges and that apex gains n spokes. Blender prevents this two ways:
the recursion subdivides the large triangle's *other* edges too (so the work is
distributed rather than fanned), and the >8 valence check force-queues the hub's
edges when it happens anyway.

## SculptCore: the hard clip

`engine/source/dyntopo/dyntopo.h`

- `consider()` (:857) computes `d2 = |edgeMid(e) - center|^2` and returns
  immediately if `d2 > r2` (:862). That is the **only** region test, and it is
  per-edge, not per-face.
- No recursive/outward candidate add exists anywhere in the file. The `frontier`
  set (:812, :1163) re-examines endpoints of the previous round's candidates and
  created edges, but every re-examination still goes through `consider()` and so
  through the same sphere gate. The frontier makes rounds *local*, it does not
  make them *spread*.
- The flip sweep is gated the same way (:1077, `edgeMid ... > r2` -> skip) and
  tangential smoothing on vertex position (:1119).
- The seed for round 0 (`brush_executor.h` ~:1974) is the vert set of the
  spatial leaves overlapping the sphere — a superset, but `consider()` still
  clips it back to the sphere.
- `grade` (:72, applied :875-879) is the nearest analogue, and it is not the same
  mechanism: it relaxes the target *inside* the radius as
  `l_max * (1 + grade * d/radius)`, i.e. it makes the brush centre finer than the
  brush rim. It still stops dead at `d == radius`. **The addon never sets it** —
  `sculptcore_addon/stroke/dyntopo.py::build_dyntopo_params` writes only `l_max`
  and `l_min`, so `grade` is 0.0 (uniform) in every shipped stroke. `size_attr`
  (the Tier-9 curvature field) is likewise never set by the addon.
- No valence criterion anywhere. It was considered and **deliberately rejected**
  (:94 comment) because a valence-driven flip can lengthen an edge and therefore
  create work, breaking the monotonicity that makes the round loop terminate.
  SculptCore's substitute is the geometric flip sweep (M7.2): `flipShortens`
  requires the opposite diagonal to be strictly shorter (0.998 slack) and the
  quad convex. The design doc credits it with dropping cascade max valence from
  ~60-97 to ~9-10 — but that is the *interior* cascade, and the sweep cannot
  touch a spoke whose midpoint lies outside the sphere.

## Consequences of the difference

1. **A large triangle is invisible to a small brush.** Blender's face-in-sphere
   test catches a triangle the brush sits inside; SculptCore's edge-midpoint test
   does not, because all three midpoints are outside `radius`. Inferred from the
   code path, not yet reproduced in a build — worth an actual test: place a
   small-radius dab in the interior of one large triangle and check
   `DynTopoStats::splits`. Expect 0.
2. **Rim discontinuity.** Where Blender leaves a geometric 1.6^k falloff,
   SculptCore leaves a step from `l_max` to whatever the base mesh was, at a
   boundary defined by edge midpoints (so the visible boundary is ragged at
   roughly half the local edge length).
3. **The rim is where hubs are least relieved.** A spoke created by an in-sphere
   split can easily have its midpoint outside the sphere; that spoke is then
   ineligible for the flip sweep (:1077), which is precisely the geometry
   SculptCore relies on to keep valence bounded.
4. Both systems use the same brush radius, and both derive `l_max` from the same
   Blender detail settings (`stroke/dyntopo.py::dyntopo_max_edge` ports
   `constant_to_detail_size` / `brush_to_detail_size` / `relative_to_detail_size`
   and `EDGE_LENGTH_MIN_FACTOR = 0.4`), so the targets are comparable and the
   region rule is the real variable.

## If SculptCore were to adopt it

- The mechanism ports cleanly onto `consider()`: pass a hop-scaled `tmax` instead
  of returning on `d2 > r2`, i.e. keep a per-edge goal that grows with graph
  distance from the in-sphere seed set rather than clipping on Euclidean
  distance. The existing round/MIS/budget structure is unaffected — this only
  changes which edges enter `cands`.
- Two things must move with it or the port regresses:
  - the region test for the **flip sweep** (:1077) and the smooth (:1119), which
    would otherwise refuse to clean up the very geometry the new outward splits
    create;
  - the **split budget** (`max_splits`), since outward propagation strictly
    enlarges the candidate set — the budget is already the intended valve, but
    the cap is calibrated against the clipped set.
- Blender's `> 8 valence` relief has no SculptCore equivalent and should not be
  ported as a flip criterion (the rejection at :94 is sound); the Blender form is
  a *split* trigger, not a flip, so it is monotone and does not have that problem.

---

## Ported as a second mode (2026-09-22)

Blender's rule now ships alongside ours as `DynTopoParams::region`
(`DynTopoRegion::Sphere`, the unchanged default, vs `GradedRecursive`), so the
two can be measured against each other instead of argued about.

- **Engine**: `engine/source/dyntopo/dyntopo.h`. Face-in-sphere seeding
  (`triInSphere` + a ported `closestPointTri`), the outward walk with its
  `graded_generation_scale` / `graded_len_sq_factor` gates, and the valence
  relief. Knobs: `graded_generation_scale` (1.6), `graded_len_sq_factor` (1.2,
  squared-length as in Blender, so ~1.095x linear), `graded_max_hops` (12),
  `graded_valence_relief` (8, 0 = off). `DynTopoStats::graded_hops` reports the
  deepest hop reached.
- **Where it deviates from a literal transcription**, and why:
  - Blender's DFS dedups insertion only and re-walks every path. The port uses a
    min-limit memo per edge (`GenMinMap`). An edge's own length is
    path-independent, so the carried limit is the whole state and keeping its
    minimum gives the same candidate set for bounded work.
  - Blender fires the valence relief on the apex of a face it just split, inside
    the pass. The round loop has no equivalent moment, so the port runs it after
    the walk over the seed set, gated on the walk's own region. **The gate is
    load-bearing**: ungated, it is the only rule in the mode with no distance
    bound, and re-running it on the whole frontier every round walked the
    refinement steadily off across the mesh (reach 0.243 -> past 0.42 on the
    17-grid case).
  - The flip sweep and tangential smooth follow the walk's region under
    GradedRecursive rather than the dab sphere. Left on the sphere they refuse to
    clean up the geometry the grading just created.
  - Not ported: `use_frontface` / `use_projected`. Dyntopo here has no view
    normal.
- **Integration**: `test_spatial_dyntopo.cc` gained a graded case driven the way
  the brush executor drives it (round-0 seeds from the in-region leaves, edits
  through `getSpatialCallbacks`). Node ownership stays complete through the
  out-of-region edits and a second dab converges to 0 splits. Viewport staleness
  is a non-issue by construction: `add_face_at` sets
  `RegenTris | RegenBounds | RegenGPU` with no position gate, so a leaf touched
  beyond the dab is flagged like any other and the dirty-driven
  `updateQueries()` / `update(gpu)` pick it up.
- **Gate**: `engine/tests/test_dyntopo_graded.cc` (`node make.mjs test
  test_dyntopo_graded`). Full native ctest stayed at 151/151.
- **Reachable from**: the addon's Dyntopo panel (Scene.sculptcore_dyntopo_region,
  'SPHERE' / 'GRADED'), and the debug app's `dyntopo graded=0|1` /
  `bench_dyntopo graded=0|1`.

### What it measures

From the test's own output:

- **One large triangle, small dab at its centroid** — Sphere 0 splits (the
  triangle is untouchable), GradedRecursive 133 splits over 5 hops. This is the
  gap, confirmed rather than inferred.
- **17-grid (spacing 0.0625), r=0.1 dab, l_max=0.02, flips off** — Sphere reaches
  0.119 from center and leaves the mesh beyond the rim at its original 0.0591
  mean. GradedRecursive reaches 0.243 and grades: 0.0167 mean just outside the
  rim, 0.0685 in the next shell out. The walk terminates on its own well inside
  the grid.
- **Max valence, same grid, shipped config (flips on)** — Sphere 11,
  GradedRecursive 9. The relief knob made no difference on this case (9 either
  way), so its value is still unproven here; it is printed, not asserted.
- **Convergence** — a second graded dab on an already-graded region applies 0
  splits and never hits the round cap.

### Cost characteristic worth knowing before enabling it

The 1.6-per-hop growth only bounds the walk when `l_max` is not tiny relative to
the base mesh's edge length. At `l_max = 0.03` against 0.125 grid spacing the
hop-3 goal (0.123) still admits base edges, so the walk pulled in essentially the
whole connected coarse region in one dab. `max_splits` is the existing valve, but
its calibration assumes the clipped candidate set.
