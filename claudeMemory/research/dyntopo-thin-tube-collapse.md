# Dyntopo: thin tubes that survive as "strings"

Problem: smoothing with dyntopo on shrinks a locally tube-shaped region radially. Blender's
dyntopo eventually removes the tube. SculptCore's keeps it as a thin string that cannot be
collapsed away.

## Why SculptCore keeps the string

- The link condition in `engine/source/mesh/utils/edge_collapse.h:160-188` refuses a collapse
  when the one-rings of the two endpoints share more vertices than the edge has faces
  (`common > faceCount`).
- A 4-vertex ring edge passes (common = 2), so a 4-around tube collapses to 3 around.
- On a 3-around tube (triangular-prism cross-section), each ring edge `(a,b)` has the two face
  apexes plus the third ring vertex `c` in common. That gives common = 3 > 2, so the collapse is
  refused. The ring `a,b,c` is a separating triangle that is not a face.
- Longitudinal edges would pass the link condition but stay longer than `l_min`, so they are
  never candidates.
- The refused ring edges are re-emitted every round, which feeds the `max_stall_rounds` early-out
  (`dyntopo.h:194`).
- Nothing in the engine deletes faces or components. There is no flap cull, no small-component
  cull and no thin-feature detection.
- SMOOTH (`smooth.sbrush`) is plain Laplacian and shrinks tubes. BSMOOTH's `projection`
  (`brush.smoothProj`) removes the normal component of the step and resists shrinking.

## What Blender does

Source: `source/blender/blenkernel/intern/pbvh_bmesh.cc`, `pbvh_bmesh_collapse_edge` (:1480) and
`pbvh_bmesh_collapse_short_edges` (:1674).

- It has no link condition. Every queued edge shorter than `min_edge_len` is collapsed.
- For each face around `v_del`, it checks whether the remapped triangle already exists
  (`bm_face_exists_tri_from_loop_vert`, :1551). If it does, it deletes both the old face and the
  existing one instead of creating a duplicate. The code calls these pairs "flaps".
- After deleting faces it kills edges that became wire (:1621) and vertices left without edges
  (:1629).
- On a tube, collapsing a 3-ring edge folds the ring into coincident face pairs. The flap rule
  deletes them, so the tube is severed and its thin part disappears pair by pair.
- BMesh tolerates the non-manifold intermediate states this passes through. The outcome is not
  guaranteed to be closed: holes and non-manifold edges near the severed ends are possible.

## Options

1. **Blender-style collapse-through with flap culling.** Drop the link condition for this case,
   let the collapse fold the ring, then delete coincident face pairs, wire edges and orphan
   vertices.
   - Matches Blender behaviour most closely.
   - Passes through non-manifold states. The engine's radial cycles, spatial ownership, meshlog
     and `validateAndRepair` all assume manifold-ish input, so every consumer needs auditing.
   - Can leave holes. Most invasive of the options.
2. **Pinch-off surgery at the separating triangle (recommended).** When the link condition refuses
   a collapse because of exactly one extra common vertex `c`, and the triangle `a,b,c` is not a
   face and all three edges are below `l_min`, cut the tube there. Duplicate `a,b,c`, reattach one
   side's faces to the copies, and cap each side with a triangle of opposite winding.
   - Both sides stay closed and manifold. Every step is a kill or add that `MeshCallbacks`
     already carries for splits and collapses, so the meshlog and spatial tree need nothing new.
   - The detection hook costs nothing extra: it runs only on the refusal path that fires today.
   - Each cap is a small cone tip. Its edges are short and collapse normally afterwards.
   - A string cut at both ends becomes a small closed component, which option 3 removes.
3. **Cull tiny closed components.** After a dab, delete components in the region whose bounding
   box is below roughly `l_min` or whose face count is at most a small number. A tetrahedron
   (4 faces) is the minimal closed result of repeated pinch-offs.
   - Needs a connected-component walk seeded only from the collapse region to stay O(region).
   - Also required by option 2, and cheap on its own.
4. **Prevent the shrink instead.** Default smoothing to a volume-preserving form: BSMOOTH with
   `projection` > 0, a Taubin λ/μ pair, or HC (Vollmer) smoothing.
   - Keeps tubes thick rather than removing them. That is desirable for sculpted strands but does
     not help a user who is smoothing a strand away.
   - Worth offering as a brush option. It complements options 2-3 and does not replace them.

## Related gap found on the way

- `collapseEdge` checks rebuilt faces only against each other (`rebuiltKeys`, `edge_collapse.h:509`),
  never against existing faces that touch only `v_keep`.
- A closed tetrahedron passes the count-based link condition (common = 2 = faceCount). Collapsing
  one of its edges rebuilds a face that duplicates an existing one with opposite winding. Only the
  geometry-dependent inversion guards can stop it.
- `engine/documentation/dynamic-topology.md:209-212` states the link condition as "exactly the two
  opposite vertices". The code compares counts only.
- Any fix for tubes produces tets and other tiny closed pieces, so this gap should be closed in the
  same change. Either refuse the collapse or route it to the component cull.
