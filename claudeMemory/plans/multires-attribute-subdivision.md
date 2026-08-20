# Multires attribute subdivision (UVs, colors, face sets) → the draw system

**Status: LANDED 2026-08-16** — all six work items, with the parity numbers in
*Measured parity* below. The storage policy this plan introduced later became
the routing rule for attribute *brushes* too; see
[plans/grid-domain-attributes.md](grid-domain-attributes.md).

**Problem.** On a multires object the viewport shows no UVs and no vertex
colors while the mode is active. Three independent reasons:

1. `_enter_multires` (convert.py) builds the cage with `Mesh_fromArrays` and
   seeds only `material_index` — the engine cage carries no `uv`, no `color`,
   no face-set `group`.
2. The grids draw source (`grid_draw_c_api.cc`) hard-nulls color@0, uv@1 and
   fset@3; only mask@2 is filled. The fork gates display on
   `node.attrs[0]/[1]` being non-null, so those channels simply do not exist.
3. Nothing subdivides a cage attribute onto grid samples. (The level slot mesh
   *does* carry a `uv` layer — `Multires::assignGridUVs` — but that is the X1
   VDM **atlas chart** parameterization, not the object's UV map. It must not
   be confused for one.)

## What Blender does (source-verified, `blenkernel/intern/subdiv_mesh.cc`)

Subdivided attribute values are evaluated **directly at the ptex `(u,v)` of the
sample** — there is no per-level iteration, so a sample shared by two levels
gets the same value and *attributes only need subdividing once per level's
sample set*.

* **Everything except UV maps** (point-domain and corner-domain alike):
  bilinear over four ptex-corner values, `quad_weights_from_uv(u, v)`
  (`subdiv_interpolate_corner_data`, `vert_interpolation_from_*`,
  `loop_interpolation_from_*`). The ptex corners are indexed
  `0→uv(0,0) 1→uv(1,0) 2→uv(1,1) 3→uv(0,1)` and are
  * **quad face** — the face's own 4 corner values, one ptex face over the
    whole quad (so the field is bilinear across the *whole face*, not
    per-quadrant);
  * **n-gon, corner c** — `[0]` = c's value, `[1]` = mid(c, next),
    `[2]` = the face average, `[3]` = mid(c, prev).
  This is exactly reproducible and the engine will reproduce it exactly.
* **UV maps** go through OpenSubdiv face-varying **limit** evaluation instead
  (`subdiv_eval_uv_layer` → `eval_face_varying`), with the fvar linear rule
  from the modifier's `uv_smooth` (multires default:
  `PRESERVE_BOUNDARIES` → `FVAR_LINEAR_BOUNDARIES`).

### Engine grid sample → ptex (u,v)

Engine grid `g` is cage corner `g`; lattice `(0,0)` is the corner vert, `+u`
runs toward the next corner, `+v` toward the previous, `(S,S)` is the face
centre. Blender's ptex corner layout above puts the next corner at ptex `(1,0)`
and the previous at `(0,1)`, which is the same handedness — so the mapping is
**`ptex = (u/S, v/S)` scaled into the corner's quadrant**, with no transpose:
for an n-gon the quadrant is the whole square; for a quad it is the quarter
anchored at that corner's ptex position, reaching the centre. (The vertex
lattice does carry a transpose against *Blender's grid storage order* — see
[research/grid-correspondence.md](../research/grid-correspondence.md) — but
that is a different pairing from the ptex parameterization, and the two must
not be conflated.)

## The UV rule (`fvar`)

Face-varying refinement is Catmull-Clark on the **UV cage** — the cage with its
vertices split wherever incident corners disagree on UV. That mesh has the same
faces in the same order, so `Refiner`'s grid enumeration is unchanged and the
refined lattice lines up sample-for-sample with the position lattice. UV seams
become *boundaries* of that mesh, which is precisely OSD's fvar topology, and
the refiner already treats a boundary edge as a crease.

`uv_smooth` then only selects how boundary curves refine:

| `uv_smooth`                      | rule                                             |
| -------------------------------- | ------------------------------------------------ |
| `NONE` (`FVAR_LINEAR_ALL`)       | no fvar refinement at all — the generic ptex-bilinear path |
| `PRESERVE_BOUNDARIES` (default)  | boundary verts held, boundary edge points at the midpoint (linear polylines) |
| `PRESERVE_CORNERS*`, `SMOOTH_ALL` (`FVAR_LINEAR_NONE`) | smooth boundary curve (the refiner's existing 1/8–6/8–1/8 crease rule) |

`Refiner` gains one option (`linearBoundary`) for the middle row. The three
`PRESERVE_CORNERS*` variants differ only in which boundary *vertices* OSD
additionally sharpens (junctions / concave corners); they collapse onto the
smooth-boundary row here, which is a documented approximation.

**Fidelity limit, stated up front:** OSD evaluates the fvar *limit* surface,
this refines discretely. The parity script (below) is what decides whether a
limit-mask projection at the top level is needed to close the gap; near
extraordinary fvar vertices OSD uses Gregory patches and exact agreement is not
reachable without porting OpenSubdiv.

## Grid-element storage policy (the host-capability system)

`GridsStore` already carries named float channels per grid element, and that is
the natural home for per-grid-element attribute data. But a host can only
*persist* the channels its own file format has a slot for — Blender has exactly
one (`CD_GRID_PAINT_MASK`, a scalar per grid vertex). So each attribute gets a
storage class:

```
GridAttrStorage::Host     host persists it per grid element (Blender: "mask")
GridAttrStorage::Derived  engine-owned cache, resubdivided from the cage attr
GridAttrStorage::Temp     engine-owned scratch (AttrFlag::TEMP) — never persisted,
                          so brushes may always write it per grid element
```

Hosts declare their capability (`MultiresAttrs::declareHostAttr(name, type)`,
reached as `mr.gridAttrs()`; c-api `Multires_declareHostGridAttr`). Anything
undeclared and not TEMP is **Derived**: a brush must write the *cage*
attribute, and the grid-element data is a cache that gets resubdivided
(`MultiresAttrs::invalidate(name)`). Derived caches live outside `GridsStore` on
purpose — they must not enter the undo store blob or the serialized level data,
being recomputable by definition.

**Where the enforcement point ended up (2026-08-19).** When this was written the
only grids-path attribute write was the paint mask, and the sentence here
predicted the policy would be what a future grids-native colour brush routed
through rather than a per-tool conditional. That is what happened, in
[plans/grid-domain-attributes.md](grid-domain-attributes.md): `gridAttrPlan`
(`engine/source/brush/grid_attr_bind.h`) calls `storageFor` and returns
`Unbindable` for a writable `Derived` attribute, so on a Blender host colour and
face sets take the mesh path and each dab writes the cage
(`Multires::scatterVertFloat4ToCage` / `scatterFaceIntToCage`). No tool list is
consulted anywhere on that decision, and the scene-level override that briefly
sat in front of it was deleted once the storage class decided first.

## Work items

1. **engine `subdiv/grid_attrs.{h,cc}`** — `MultiresAttrs`: per-level derived
   grid-sample layers, the ptex-bilinear evaluator (point + corner domains),
   the fvar UV path, the storage-policy table, dirty/rebuild.
2. **engine `subdiv/subdiv.{h,cc}`** — `Refiner::linearBoundary`.
3. **engine `subdiv/grid_draw_source.{h,cc}`** — per-node `color`/`uv`/`fset`
   streams filled from (1); `grid_draw_c_api.cc` advertises the slots it has.
4. **engine c-api + `wasm_add_symbols`** — declare/query the policy, set
   `uv_smooth`, invalidate a cage attribute. Test: `test_multires_attrs`.
5. **addon `convert.py`** — seed the cage's `uv` / `color` / face-set `group`
   at multires enter, declare `mask` as the one host-persisted grid attribute,
   pass the modifier's `uv_smooth`.
6. **parity gate** — `tools/verify_multires_uv_parity.py`: compare engine grid
   UVs against Blender's own evaluated multires mesh, sample for sample,
   through the existing grid↔subdivided-vertex map.

## Measured parity (2026-08-16)

All landed; the gate runs 8 cases (plain grid L1/L2, UV-seamed grid, cube,
n-gon fan, across `PRESERVE_BOUNDARIES` / `SMOOTH_ALL` / `NONE`) and passes.

The fidelity limit above resolved better than feared: the discrete refinement
plus `applyLimitMask` agrees with OSD to **float epsilon (≤2.9e-6)** at every
sample except one class. The exception is the `(0,0)` sample of each grid — a
cage vertex — under `SMOOTH_ALL` only, where it reads **6.5e-4**: Blender
answers `0.166015625` for a UV-chart corner whose Catmull-Clark limit is
exactly `1/6`. That is OSD evaluating a patch after *bounded feature isolation*
around an extraordinary fvar vertex, not a different rule; the engine's value is
the closed-form limit. Both `PRESERVE_BOUNDARIES` (the multires default, which
holds fvar corners) and `NONE` are exact there.

The gate therefore grades on two budgets — `body` 5e-5 and `corner` 1e-3 — so
the tight one still covers 99% of samples and neither can hide a wrong rule,
which costs O(0.1). Do not "fix" the corner value toward Blender's: it would
trade an exact limit for an evaluator artifact.
