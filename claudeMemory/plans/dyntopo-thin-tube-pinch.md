# Plan: dyntopo pinches off thin tubes

- Status: pressure-tested once, with three adversarial lenses (operator buildability, topology
  semantics, cross-cutting seams and gates). Every surviving finding is folded in below.
- Implemented (uncommitted, 2026-09-22): Phases 0 to 4. 3-around tubes are cut and culled. Necks that
  start wider mostly stall first; see the Contingency section.
- Research: [../research/dyntopo-thin-tube-collapse.md](../research/dyntopo-thin-tube-collapse.md).

## Goal

- When smoothing shrinks a tube below the detail size, dyntopo cuts through the tube at its thin
  cross-sections instead of leaving an uncollapsible 3-vertex "string".
- Every intermediate and final state is a closed, oriented 2-manifold. Nothing passes through the
  non-manifold states Blender's flap rule relies on.
- Pieces the cuts produce that are no bigger than a few edges are deleted.
- Pieces bigger than the cull limits stay behind as separate floating components. Blender behaves the
  same way. Two examples:
  - a mushroom head on a stalk that thinned out;
  - a dangling strand whose far end lies outside the dab.
- With the feature off, output is identical to today's. The one exception is the Phase 0 tet guard,
  which changes behaviour only on isolated tetrahedron components.

## Definitions

- **Stuck ring.** An edge `(a,b)` is a collapse candidate, `collapseEdge` refuses it at the link
  condition with `faceCount == 2` and triangle apexes, and a shared neighbour `c` is not an apex.
  Then `a,b,c` is a 3-cycle that is not a face.
  - An edge can have more than one such `c`. In the Boerdijk-Coxeter (helix) triangulation of a
    3-around tube, edge `(i,i+1)` has two, and each of them gives a separating ring. So detection
    reports every extra neighbour and tries each one.
- **Thin.** Each ring edge is shorter than `pinch_ring_factor × its own tmin`. Default factor 1.0.
  - `tmin` is the graded threshold computed for that edge, including `size_attr` or `grade`. See
    "Band scale" in Phase 2.
  - A closed loop of three sub-`l_min` edges is a cross-section that dyntopo cannot represent.
- **Trivial side.** One side of the ring is a single vertex `v` of valence 3, joined to `a`, `b` and
  `c` by the three faces `vab`, `vbc` and `vca`.
  - The opposite triangle of every valence-3 vertex on an ordinary surface is a stuck ring. Today
    the link condition refuses to collapse its edges.
  - Pinching such a ring would cut `v` off as a tet and delete it. That drops `v`'s position, mask
    and displacement instead of blending them, and it would erase any spike on a small base.
  - So a ring with a trivial side is not pinched. It is handled as described in Phase 2 under
    "Trivial side".
- **Pinch.** Duplicate `a,b,c` into `a',b',c'`, move one side's faces onto the copies, and cap each
  side with one triangle.

## Topology of the cut

These were verified by the semantics review.

- Orient the cycle `a→b→c→a`. `F_L(xy)` is the face that holds the directed edge `x→y`, and
  `F_R(xy)` is the face that holds `y→x`.
- At each ring vertex, the two ring edges split its fan into two arcs.
  - Neither arc is empty: consecutive ring edges would share the face `abc`, which does not exist.
  - The arcs are disjoint, and every face that holds two ring vertices is the `F_L` or the `F_R` of
    a ring edge.
- Walk the arcs like this: at each ring vertex, start from the incoming ring edge's `F_L` and walk
  the fan until the outgoing ring edge. At `a` that means walking from `F_L(ca)` to `F_L(ab)`.
  - On an oriented manifold the three arcs always meet consistently. The check that they do is
    really a check of local orientation, and it rejects bad input.
- Side R is the set of faces in the complementary arcs. Those faces are rewired onto `a',b',c'`.
  Rewiring substitutes vertices in place, so each face keeps its orientation.
- Caps:
  - L's cap is `(a,c,b)`. It supplies `b→a`, `c→b` and `a→c`, the reverse of L's `a→b`, `b→c` and
    `c→a`.
  - R's cap is `(a',b',c')`.
- Euler: V +3; E +3 (three twin ring edges, while the rewired spokes net 0); F +2. So χ rises by 2.
  - The cut either separates a component or removes one handle.
  - A sub-`tmin` 3-cycle that does not separate can only run round a thin handle, and cutting it
    lowers the genus by one.

## Phase 0: tet guard, refusal report, baseline

### 0a. Record the baseline

Do this first, before any engine edit.

- Build the dumbbell fixture from Phase 3 and the flat decimated patch.
- Record op counts and a hash of the positions from the current build as a committed golden. This
  is the only way to test "off = unchanged" once the change lands.

### 0b. `collapseEdge` changes

File: engine/source/mesh/utils/edge_collapse.h.

- **Tet guard.** When `faceCount == 2`, both faces are triangles and the apexes are `c,d`, refuse
  the collapse if faces `(a,c,d)` and `(b,c,d)` both exist.
  - Together with the count test, this is the full link condition for closed triangle meshes.
  - On a manifold mesh it fires only on an isolated tet component, so it cannot newly refuse any
    collapse the engine needs.
  - Keep it off the hot path. Test `valence(a) == 3 && valence(b) == 3` first, and only then confirm
    the two faces through `c`'s disk and the radial faces of `cd`. There is no face-by-vertices
    helper, and `find_edge` is O(deg·deg).
- **Refusal report.** `EdgeCollapseResult` gains:
  - `CollapseRefusal refusal`, one of `None`, `Invalid`, `Link`, `Tet` or `Inversion`. Set it on
    every `false` path: the invalid edge (:140), the link test, the tet guard, the face flip (:254)
    and the fold pair (:315).
  - `Vector<int, 4> link_extra`, the shared neighbours that are not apexes, when `faceCount == 2` and
    both incident faces are triangles.
    - Take the apexes from `c.next[c.next[cc]]` of the two radial corners.
    - Collect the shared neighbours in the existing loop. That loop skips `v_keep` at :177, so a
      single stuck ring shows as `common == 3`.
- **Docs.** Fix engine/documentation/dynamic-topology.md:208-212. It claims an exact link test;
  describe the count test plus the tet guard.

## Phase 1: the pinch operator

New file: engine/source/mesh/utils/pinch_off.h. It is a mesh-level Euler op with `MeshCallbacks`,
independent of spatial and dyntopo, in the pattern of edge_split.h.

### Signature

- `bool pinchSeparatingTriangle(Mesh &m, int a, int b, int c, PinchResult *out, MeshCallbacks *cb)`.
- `PinchResult` holds `a',b',c'`, the two cap faces, the created edges and a `refusal` reason.
- The operator knows nothing about features or the trivial-side rule. The dyntopo caller applies
  both before calling it. Keeping them out makes the op reusable, and it fixes what the refusal tests
  cover.

### Refusals

Every check finishes before the first `make_*` or `clear_*`, because `make_vertex` fires
`onVertCreate` immediately (mesh.cc:1100). A refusal leaves the mesh untouched. The op refuses when:

- `abc` is a face, or one of the three ring edges does not exist;
- a ring vertex is on a boundary, touches a non-manifold edge or a non-triangle face, or has an open
  fan;
- the arcs are inconsistent.

### Steps

1. Gather the R faces. This step only reads.
   - The gather has to run at apply time, not request time: a split applied earlier in the same round
     can have grown `c`'s fan.
2. Create `a',b',c'` with `make_vertex(co, cb, hint = original)`. Copy each vertex's attributes with
   `interpAttrs(m.v.attrs, dst, src, src, 0.0f, &m)`.
   - Never use the raw `snapshotAttrRow`/`restoreAttrRow` pair for vertex rows.
     - It memcpys `WeightSlot` cells without taking a reference, so the DeformPool double-releases
       when a culled copy dies.
     - It also skips the NOCOPY stroke displacement.
   - `interpAttrs` copies the vertex groups (`mergeWeights` reassigns an equal slot), the mask, the
     displacement field and the size attribute exactly.
   - It skips TOPO, NOINTERP and the `.spatial.*` ownership columns. It clears the dab, automask and
     enhance generation stamps. It renormalizes `.brush.orig.no`.
   - Split vertices get exactly the same treatment, so this is the accepted behaviour, not a bug.
   - Optionally, copy the NOINTERP data layers (the cross field and the displace frames) by hand,
     excluding `.spatial.*`. A duplicate at the same position should keep its cross field.
3. Snapshot the R faces' corner rows, keyed by vertex, as `splitEdge` does (edge_split.h:133-140).
4. Clear each R face with `clear_face_contents`. Every spoke from a ring vertex into R is now wire,
   and each ring edge keeps only its L face.
5. Re-point each such spoke with `relink_edge_verts(e, a', x)`.
   - This is `splitEdge`'s pattern (edge_split.h:163-172).
   - The edge keeps its id and attributes, including seam and sharp flags, so no edge snapshot or
     restore is needed.
   - The meshlog records a Change rather than a kill-and-create pair.
6. `make_edge` the three twins `a'b'`, `b'c'` and `c'a'`. Copy each ring edge's attribute row onto
   its twin.
   - This has to happen before any `reinit_face`: `reinit_face` never creates edges and needs every
     edge in its span to exist (mesh.cc:1483-1557).
   - Edge rows contain no refcounted types, so `snapshotAttrRow`/`restoreAttrRow` is safe for them.
7. Rebuild each R face with `reinit_face` onto the primed vertices, then restore its corner rows,
   mapping `a'` back to `a` for the lookup (edge_split.h:230-245).
   - Face attributes survive, because the face id is kept.
   - `reinit_face` fires `onFaceChange`, and `touch_face` then claims the unowned `a'`, `b'` and `c'`
     into that leaf (spatial.h:600-612).
8. Make the two caps. This has to come after step 7.
   - Once the primed vertices are owned, the caps anchor through `find_anchor_leaf`.
   - If they are made earlier, `add_face` falls back to a descent by centroid. That path drops faces
     with area below 1e-7 (spatial.h:489-492), which sub-`l_min` caps can be.
   - Each cap copies its face row from `F_L(ab)` (or `F_R(ab)`).
   - Each cap corner copies its corner row from a corner on the same vertex on the same side.
9. Flag the leaves that own `a,b,c` and `a',b',c'` for a normal update, in the way
   `flag_face_owner_normals` does. Nothing moved, so otherwise their normals keep the old average
   over the whole fan.

## Phase 2: dyntopo round loop

File: engine/source/dyntopo/dyntopo.h.

### Params and stats

- Add these fields to `DynTopoParams`. Bind them in dyntopo/bindings.cc, and validate them in the
  brush_executor.cc:298-307 block (finite and ≥ 0).
  - `bool pinch_thin = false`. The engine default stays off, so preremesh.cc, remesh_app,
    script_bench and every existing test are unchanged. The addon turns it on (Phase 4).
  - `float pinch_ring_factor = 1.0f`.
  - `int cull_max_faces = 64`.
  - `float cull_size = 2.0f`, a multiple of the local `tmax`.
  - `int max_pinches = 0`, a per-dab cap like `max_splits`. 0 means unlimited.
- `DynTopoStats` gains `pinches`, `culled_faces` and `trivial_dissolves`.
- No ABI bump is needed. The structs are bound by reflection from the DLL and passed by pointer;
  `ABI_VERSION` covers the c-api only. Regenerate the TS bindings and the .pyi stubs, and leave them
  out of the commit message as engine/CLAUDE.md asks.

### Band scale

- Add `tmin` and `tmax` to `Cand`, filled from the arguments that `emitCollapse` and `emitSplit`
  already receive.
- Do not recompute them "the way `consider` does". The graded seed path emits collapses with an
  unscaled `l_min` (dyntopo.h:1239-1240), while `consider` applies `sizeField` and `grade`.
- Each of the ring edges `bc` and `ca` is tested against its own tmin, computed with the same rule as
  the candidate path that emitted `ab`.
- The cull box is `cull_size × tmax` of the seed candidate.

### Apply loop (:1442-1481)

- When `collapseEdge` returns false:
  - With `refusal == Link` and a non-empty `link_extra`, push `(a, b, extras, tmin, tmax)` onto the
    round's `pinchReqs`.
  - With `refusal == Tet`, push the tet as a direct cull seed. The refusal proves it is an isolated
    tet. Without this, a small piece that shrinks to a tet through ordinary collapses (octahedron,
    then triangular bipyramid, then tet) would float forever.

### Pinch pass

It runs after the collapse loop and before the flip sweep.

- **Why it is deferred.** The round's independent set assumes each picked op touches only its locked
  one-rings, and a pinch rewires faces around `c`, whose neighbours are not locked.
- **Why the triples stay valid.** The refused collapse locked the one-rings of `a` and `b`, and `c`
  is in both. No collapse touches `c`'s neighbourhood, and splits cannot kill `a`, `b` or `c`.
- **Placement.** Run it before the `if (graded) regionVerts.add(touched)` block (dyntopo.h:1489).
  Otherwise the new vertices fall outside the graded region and the flip and smooth gates skip them.
- For each request, and for each candidate `c` in its extras:
  1. Re-derive the ring from the current mesh.
     - An earlier pinch this pass may have moved an edge `(x,c)` onto `c'`.
     - Look up the ring edges again. If `(a,c)` is gone, try `(a,c')`.
     - Drop the candidate only if no ring can be found.
  2. Apply the thin test to each edge against its own tmin.
  3. Refuse when `feat.active` and any ring vertex is a feature vertex. This is a conservative v1
     rule: a seam or crease along a strand keeps the strand.
  4. Check for a trivial side. If there is one, run the trivial-side handling below instead of
     pinching.
  5. Otherwise call `pinchSeparatingTriangle`. On success:
     - count `stats.pinches`;
     - add the new edges to `touched` and `nextFrontier` through `addCreated`;
     - mark the ring vertices and new edges boundary-dirty;
     - push both caps as cull seeds.
  6. Stop the pass when `max_pinches` is reached.
- **De-duplication.** Key requests on the sorted triple. The MIS allows at most one request per ring
  per round, so this is cheap insurance.

### Trivial side

- The ring bounds a single valence-3 vertex `v`.
- Collapse `v` into the ring vertex nearest to it by calling `collapseEdge` on `(ring vertex, v)`
  with the usual midpoint and blend.
  - The link test passes, because `common` is 2, the two faces flanking the spoke.
  - The collapse leaves the face `abc` on that side, and the ring stops being a stuck ring.
- This is the standard removal of a valence-3 vertex that remeshers use. It blends `v`'s attributes
  instead of discarding them.
- Only do it when `v`'s spoke is shorter than the local `tmax`.
  - A longer spoke is a spike on a small base, which is real sculpted shape. Leave it and the stuck
    ring as they are today.
- It also covers tip peeling. The tip of a dangling strand is a cone over a 3-ring, and its apex is
  exactly this case: the tip merges into the ring instead of being cut off as a tet.
- Count it in `stats.trivial_dissolves`.

### Cull pass

It runs right after the pinch pass.

- For each seed, skip it if the seed face has already been freed, because an earlier flood may have
  deleted it. Then flood-fill faces across manifold edges.
- Keep the piece, and stop the flood, when any of these holds:
  - the piece exceeds `cull_max_faces`;
  - the running bounding-box diagonal exceeds the cull box;
  - an edge does not have exactly two faces.
- Delete a piece that completes within the limits.
  - Kill its faces, then its wire edges, then its isolated vertices, all through `cb`.
  - Count the deleted faces in `stats.culled_faces`.
- The existing freemap guards on the `frontier`, `touched` and flip reads cover the killed
  vertices.
- The cost is bounded by `cull_max_faces` per seed. The body side of a cut hits that limit quickly
  and is kept.

### Loop accounting

- Pinches, trivial dissolves and cull deletions count toward `applied` so that the `applied == 0`
  break does not fire.
- They do not reset the stall run (`kStallOpMax`). Otherwise a large floating piece that keeps being
  pinched but never culled would spin to `max_rounds`. `max_pinches` backs this up.
- Set `m.boundaryDirty` when `stats.pinches`, `stats.trivial_dissolves` or `stats.culled_faces` is
  nonzero, as well as on the existing splits-and-collapses condition (dyntopo.h:1657).

### Expected dynamics

The Phase 3 gates check each of these.

- A long 3-around string gets cuts on several rings within a round or two. Cuts made in the same
  round sit at least three rings apart because of the MIS locks.
- Segments between cuts are culled once they are closed and small enough. Longer segments are re-cut
  in later rounds.
- On the body side of each cut, the cap face `abc` is followed by normal ring collapses, and the
  stump shrinks.
  - The semantics review showed that the first cap-edge collapse passes both the link test and the
    fold guard.
  - It did not verify the later collapses on a sheared tube; the dumbbell gate has to.

## Phase 3: engine tests

New file: engine/tests/test_dyntopo_pinch.cc, registered as
`test(test_dyntopo_pinch.cc "meshlog;mesh;spatial")`, the same as test_dyntopo_undo.cc
(CMakeLists.txt:50). The fixtures are built in code.

### Operator gates

- **`gateTetRefused`**
  - `collapseEdge` on every edge of a closed tet returns false with `refusal == Tet`.
  - The mesh is unchanged.
- **`gatePinchPrism`**: a capped triangular-prism tube with five rings, pinched at the middle ring.
  - `validateAndRepair() == 0`.
  - The result is two closed components, each with χ = 2, and every face's winding is consistent.
  - A float vertex attribute, the mask and a vertex group are copied onto the duplicates.
  - The vertex-group refcounts balance after both components are deleted.
  - A seam flag on a ring edge is present on both twins, and seam flags on spokes survive the relink.
- **`gatePinchRefusals`**: `pinchSeparatingTriangle` returns false and leaves the mesh unchanged for:
  - a ring that is a face;
  - a ring through a boundary vertex;
  - a non-manifold ring.
- **`gatePinchHandle`**: a torus whose handle has thinned to a 3-ring. After the pinch there is still
  one component, χ goes from 0 to 2, and the mesh is valid.
- **`gateHelixRing`**: a Boerdijk-Coxeter tube with `link_extra` of size 2. At least one ring is
  pinched.

### Dyntopo gates

- **`gateTrivialSide`**: a flat or bumpy decimated patch containing valence-3 vertices, run with
  `pinch_thin` on.
  - No components are culled.
  - `stats.pinches == 0` and `trivial_dissolves > 0`.
  - A spike on a small base with long spokes survives unchanged.
- **`gateFeatureRefusal`**: a strand whose ring vertices carry a seam, run with `preserve_features`
  on. It is not pinched.
- **`gateTubeReachesThree`**: start from a 6-around and an 8-around tube and shrink them radially
  across dabs with `prevent_inversion` on.
  - Assert that the tube reaches 3-around and pinches.
  - This is the check on the unproven claim that the fold guard at edge_collapse.h:309-318 lets a
    4-around ring collapse to 3. A round 4-ring's flanking pair goes from about 90° to about 120°,
    which is on the knife-edge of the refusal.
  - If it fails, see Contingency.
- **`gateDumbbellString`**: two icospheres joined by a 3-around tube that is long compared with
  `l_max`, with `l_min` above the ring edges, in both Sphere and GradedRecursive modes. Check:
  - `pinches > 0` and `culled_faces > 0`;
  - the mesh is valid and every edge is two-faced;
  - no thin non-face 3-cycle is left inside the region;
  - the stumps shrink: the maximum distance from each icosphere's surface falls between the first
    and last dab;
  - `stalled == false`.
- **`gateTinyCollapseToTet`**: a small floating octahedron with collapses on. It ends deleted, not as
  a tet.
- **`gatePinchOffIdentity`**: with `pinch_thin` off, the dumbbell and the flat patch reproduce the
  0a golden exactly.
- **`gatePinchUndo`**: the dumbbell through the combined meshlog and spatial callbacks.
  - Pass the tree to `undo` and `redo`. The existing harness passes `nullptr`
    (test_dyntopo_undo.cc:263/308/364).
  - After the stroke, after undo and after redo, run a whole-tree ownership check. Move
    `validateOwnership` out of test_spatial_dyntopo.cc:52-110, where it is file-static, into a
    shared test header.
  - Undo restores positions and element counts, and the mesh is valid. Redo restores the
    post-stroke counts.
- **`gatePinchSpatial`**: after a pinching dab, `tree->update()` succeeds and every live face and
  vertex has an owner.

### Regression

- Run the existing `test_dyntopo*` and `test_spatial_dyntopo*` suites and the sbrush gates.

### debug_app

- Add `pinch=0/1` to the `dyntopo` verb (documentation/debugApp.md).

## Phase 2b: seam fixes the gates depend on

- **Undo of a cull must re-own its faces.**
  - The `Existed && Dead` post-pass calls `tree->add_face(f)` (meshlog_topo.h:393-396).
  - A culled component has no owned vertex, so `add_face` falls back to the descent by centroid,
    which drops faces with area below 1e-7 (spatial.h:462-492).
  - Add a replay path that skips the area check, for example a `force` flag on `add_face` that goes
    straight to `add_face_intern`.
  - `gatePinchUndo` must fail without this fix.
- **Chain the tree's `onCornerKill` skirt hook into the executor's combined callbacks**
  (brush_executor.h:1935-1968), as script_vdm.cc:262 does.
  - A cull can otherwise leave stale `skirt_tris` pointing at freed corners.
  - Mirror the chaining in the test harness copy (test_dyntopo_undo.cc:605-630).

## Phase 4: addon

- Add a scene property `sculptcore_dyntopo_pinch`, "Remove Thin Strands", default True.
  - Its tooltip says that strands thinner than the detail size are cut, and that small pieces are
    deleted.
  - props.py: define it next to the remesher tuning props, and `del` it in `unregister()`
    (props.py:186-197).
  - ui.py: add it to the remesher block (:200).
- stroke/dyntopo.py:65: set `params.pinch_thin` behind the `hasattr(params, ...)` guard used for
  `region` (:60-64). Without the guard, a stale vendored DLL raises `AttributeError` on every
  dyntopo stroke.
- The cull limits and `max_pinches` stay engine defaults and are not exposed.
- Re-vendor the DLL, and restage the addon into the build tree before testing (memory note:
  sculptcore-addon-loaded-from-build-copy).
- Run claudeMemory/scripts/test_brush_dyntopo_gestures.py.
- Manual check in Blender:
  - smooth a strand thin between two masses: it cuts and the stumps shrink;
  - smooth a dangling strand: the part inside the dab disappears;
  - undo restores the strand, visible and brushable;
  - decimating a bumpy area with dyntopo leaves the bumps.
- Undecided: `applyDynTopoDab` and the c-api return only `splits + collapses`, and the addon only
  checks whether that is negative. Leave pinches out unless something needs them.

## Contingency: wide necks stall before 3-around

Status: triggered, not yet planned. Needs the user's decision.

- `gateTubeReachesThree` was replaced by `gateWideNeck`, which asserts only that the mesh stays a
  closed manifold and that at least one cut happens.
- Measured on the dumbbell with 8 dabs:
  - The 6-around neck gives 9 pinches, 84 culled faces and 3 components.
  - The 8-around neck gives 1 pinch, 0 culled faces and 2 components (the neck survives).
- The neck stalls at 4 to 6 around. Most collapses there are refused by the inversion (fold) guard
  in `collapseEdge`, not by the link test, so few separating 3-rings ever form.
- Candidate fix: generalize the cut to short chordless non-face cycles of thin edges (length 3 to
  8), triggered from both Link and Inversion refusals.
  - The operator generalizes: duplicate the n cycle vertices and fan-triangulate each cap.
  - It needs a side test so a flat small disk is not cut. Both sides must be tubes that continue
    past the cycle, rather than one side being a cap of a few faces.
  - Detection is a bounded search from the refused edge's endpoints over edges shorter than `tmin`.
- The generalization needs its own design and pressure test before it is built.

## Out of scope

- Option 1 (Blender's non-manifold flap rule) and option 4 (volume-preserving smoothing).
- Culling pieces that are not seeded by a pinch or a tet refusal.
- Pinching rings through feature vertices.
- Multires: `topoLocked` returns early at brush_executor.h:1895.

## Risks

- **Coincident caps.** They persist only when both sides survive, as with a handle or a large
  floating piece. They sit inside the cross-section, so an outside ray hits the wall first. Duplicate
  vertices at the same position are smoothed independently by the next dab. Low impact.
- **Flat ribbons.** A fin whose cross-section is a flat sub-`tmin` 3-ring is cut too. Blender does
  the same.
- **Symmetric strokes.** Mirrored dabs run dyntopo independently, so the topology can differ between
  the two sides. Positions are unchanged, so this is no worse than today's collapse asymmetry.
- **Collapse-only mode.** Spike spokes can exceed `tmax` there. The trivial-side rule then leaves the
  spike alone, which is the intended behaviour.
