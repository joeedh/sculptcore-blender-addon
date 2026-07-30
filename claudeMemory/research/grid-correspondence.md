# Multires grid correspondence: engine ↔ Blender

Validated reference for how SculptCore's `subdiv::Multires` grids line up with
Blender's `CD_MDISPS` grids, and why the exchange is exact. Referenced from
`sculptcore_addon/multires.py`.

## The two samplings

Both sides decompose a base face into one **grid per face corner** (a ptex
patch), so a mesh with `L` loops has `L` grids on either side, and grid `g` is
corner/loop `g` on both. Neither side interpolates: at level `n` each grid holds
a `w × w` lattice with

```
w = 2^(n-1) + 1          # grid_size_from_level(n) in Blender
```

Adjacent grids **replicate** their shared boundary samples — a subdivided vertex
on a base edge appears in two grids, one at a base vertex appears in every grid
around it. So the sample count exceeds the subdivided-mesh vertex count, and any
per-vertex channel converted to grid order has repeated entries that must agree.

## The lattice differs by a transpose, nothing else

With `S = w - 1`:

* **Engine.** `(0,0)` is the corner vertex; `+u` runs along the corner's own
  edge, `+v` along the previous corner's edge; `(S,S)` is the face center.
* **Blender.** `(0,0)` is the face center and `(S,S)` the corner vertex, with the
  axes swapped relative to the engine — `ptex_face_uv_to_grid_uv()` in
  `subdiv_inline.hh` is exactly `grid_u = 1 - ptex_v; grid_v = 1 - ptex_u`.

Composing those, engine `(u,v)` is Blender `(S-v, S-u)`. Flattened row-major
(`v*w + u` engine, `y*w + x` Blender):

```
engine[v*w + u]  ==  blender[(S-u)*w + (S-v)]
```

That map is an **involution** — apply it to a Blender index and you get the
engine one back — so a single permutation table converts either direction.
`multires._lattice_permutation()` builds it; `build_map` applies it once, at map
build time, so nothing downstream has to know the two lattices differ.

Verified exact (max error 0.0) on plane / open cube / creased cube / cube /
cylinder / icosphere / Suzanne at levels 1–4, for positions and for the paint
mask, using a high-frequency displacement so a one-sample mispairing would show
as a full-amplitude error rather than hiding under a smooth gradient.

## Why grid ↔ subdivided-vertex needs a fork primitive

Knowing the lattice transpose pairs *engine samples with Blender samples*. What
the exchange actually needs is engine sample ↔ **Blender subdivided vertex**,
because Blender's usable reshape/mask entry points
(`multiresModifier_reshapeFromVertPositions`, `..._maskFromVertValues`) speak
per-subdivided-vertex arrays, and the subdivided-mesh vertex order is a
different thing again (shared boundary vertices present once, ordering set by
`foreach_subdiv_geometry`).

That correspondence exists inside Blender — every reshape walk computes it on
the fly — but was not exposed. The fork now exports it as data:

```python
vert_indices, grid_size = ob.multires_grid_vert_indices(depsgraph)
```

`vert_indices[g * grid_size**2 + y * grid_size + x]` is the subdivided-vertex
index coinciding with that grid sample, in `CD_MDISPS` order; `-1` marks a
sample the walk never reached. Implemented in
`multires_reshape_vertcos.cc` (`multires_reshape_read_grid_vert_indices`) by
reusing the vertcos foreach walk — including its **seam-replica propagation**,
which is what makes boundary samples come out filled:

* `(u==0 && v==0)` — scatter to every corner grid of the face;
* `u==0` — also the previous corner's grid at `(v, 0)`;
* `v==0` — also the next corner's grid at `(0, u)`.

Blender-side chain: `Object.multires_grid_vert_indices` (RNA,
`rna_object_api.cc`) → `multiresModifier_gridVertIndices` (`multires_reshape.cc`,
forces a top-level `MultiresModifierData` copy) →
`multires_reshape_read_grid_vert_indices`.

### Vertices no grid sample names

A subdivided vertex outside every ptex face — from a loose edge or a wire vertex
— is named by no grid sample (Suzanne has 10 at level 1). Such a vertex carries
no `MDISPS` or mask element and is not part of the multires domain at all, so
`build_map` leaves its reverse-table slot at zero rather than treating it as an
error: both exchanges are driven by the grid samples, which never read it.

## What this replaced, and the bug it explains

`build_map` used to pair samples by **nearest neighbour** (a `mathutils` KD-tree)
between the engine's undisplaced base samples and those of a throwaway object
carrying a fresh multires. Proximity is not identity: sample spacing halves with
every level, so anywhere the engine's discrete Catmull-Clark base disagreed with
Blender's CC limit surface — creases, extraordinary vertices, n-gons —
neighbouring samples swapped. A swapped sample takes its neighbour's
displacement, which reads as grid borders pulled back toward the base at level
≥ 3. Suzanne at level 1 was the reproducible case: 10 mispaired vertices,
`0.019` position error and `0.74` mask error landing on exactly those 10.

The combinatorial map removes the whole failure class — no geometry is compared,
so there is nothing for a base-surface discrepancy to perturb.

## Absolute positions, not tangent frames

Both directions exchange **absolute object-space positions** at the top level,
never tangent-space displacement. The engine's base is discrete Catmull-Clark
and Blender's is the CC limit surface; those disagree, and the absolute-position
exchange absorbs the difference — Blender re-derives its own frames when baking
into `CD_MDISPS`.

This is why the engine's choice of frame is entirely internal. Nothing about
which basis the engine stores displacement in crosses this seam, so changing it
(see [design/multires-parametric-frame.md](../design/multires-parametric-frame.md))
needs no addon change, no fork change, and raises no file-compatibility
question — the engine store is session-scoped and Blender's tangent-space
`CD_MDISPS` is the persistent truth.

Residual on a **creased** cage: ~1e-4, border samples only. That is Blender's
own reshape being non-idempotent there, not the map — feeding Blender its own
evaluated surface straight back through
`multires_reshape_from_vert_positions` produces the same error at the same
samples (the `control` row in `diag_multires.py`). Every other topology tested
round-trips at exactly 0.

## Level-count changes

`Multires_addLevel` / `Multires_removeTopLevel` (c-api wrappers over the engine
methods) mirror the modifier's Subdivide and Delete Higher. They preserve the
surviving levels' displacement, so the engine keeps its per-level decomposition
instead of re-deriving everything from freshly subdivided `CD_MDISPS` — which
would leave the coarse levels smooth and lose what level switching shows.
`convert.sync_multires_total_levels()` drives them from
`handlers._sync_multires_levels`, rebuilds the sample map at the new `grid_size`,
and re-seeds the paint mask from `CD_GRID_PAINT_MASK` (the level meshes that held
it are dropped by the restack; every stroke end has already baked it out, so only
an in-stroke mask edit is lost).
