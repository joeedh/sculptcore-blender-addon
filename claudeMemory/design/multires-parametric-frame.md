# Multires: derive the tangent frame from the grid parametrization

**Status: partially implemented — Phase 1 landed 2026-07-30.** The frame
computation and its test gates exist in the engine
(`Multires::parametricFrames`, `multires.h:239`); the production
materialization path still runs the F3 cross-field provider, so nothing has
changed behaviourally yet. Written 2026-07-30,
replacing [multires-object-space-cascade.md](./multires-object-space-cascade.md)
after that design was killed in pressure testing. Everything under *What exists
today* is validated against the tree at that date and cited; the rest is
proposed. The phased implementation plan is
[plans/multires-parametric-frame.md](../plans/multires-parametric-frame.md),
which records the scope corrections a re-validation against engine `7979406`
turned up and the Phase 1 result.

**The change in one sentence:** multires stops asking the curvature cross field
for its tangent and computes one from the grid's own `(u,v)` lattice instead —
the same source Blender uses — which removes the ±90° ambiguity outright while
leaving storage, composition, the cage, undo, the seam and the file format
untouched.

## The defect

Recorded in full in the predecessor's postmortem; the short version:

`pos = base + R(base)·d`, so the frame is a lever arm and every perturbation of
it is amplified by `|d|`. The dangerous perturbation is discrete, not
continuous: the tangent is a 4-RoSy cross-field representative
(`frames.cc:294-330`), frames are recomputed from geometry alone with nothing
pinning a level's frame *choice* across rematerializations, so a frame landing on
a different image of the 4-fold symmetry decodes unchanged stored disp
**rotated by a multiple of 90°** — a visible detail flip in one step.

It is worse than the abstract description suggests. `buildLevelTopo`
(`multires.cc:54-78`) hands the frame provider a bare quad mesh carrying no
sharp/seam/group attributes, so feature detection degenerates to open borders and
the tangent is pure `estimatePrincipalDir` curvature — which on a nearly-flat
subdivided base is umbilic noise.

**Measured, Phase 1 (2026-07-30).** `gateFrameStability` on `createCube(2)` at
level 3, nudging one cage vertex by `(0.01, 0.007, 0.013)`: the worst provider
tangent dot before/after is **−0.999962** — a full **180° reversal**, not the
90° image predicted above. Same class of failure with the same consequence
(`b = n × t` reverses with `t`, so unchanged stored disp decodes with both
tangential components negated), but on the plainest possible cage and worse
than described. The parametric frame over the same perturbation: **0.999970**.

**The fix for a bad frame provider is a better frame provider.** The predecessor
tried to abolish the frame instead, and could not: rotation following provably
requires one.

## Why the grid parametrization has no ambiguity

A cross field must *choose* a direction from a 4-fold-symmetric curvature
tensor, and nothing makes that choice stable frame-to-frame. A grid lattice makes
no choice at all: `+u` is fixed by the refiner's grid enumeration (cage face id
order, loop order within a face — `grids.h:1-6`), which is fixed by cage
topology. There is no field to diffuse, no representative to pick, no ±90°
image to land on.

This is not a novel idea — it is what Blender does. `eval_displacement`
(`subdiv_displacement_multires.cc:329-359`) builds its tangent matrix from the
limit-surface derivatives `dPdu`/`dPdv` via
`BKE_multires_construct_tangent_matrix` (`multires_inline.hh:18-40`), which is
pure axis selection and sign flipping by quad corner. The predecessor document
already contained the observation and failed to act on it: *"Blender's parametric
basis never had the ±90° ambiguity."*

The engine is, if anything, better placed than Blender to do this. It does not
need limit-surface derivatives: it has the lattice in hand at every use site.

## What exists today (validated)

**Both frame consumers on the multires path are one line each.** `applyDisp`
calls `displace::updateFramesAll(*baseMesh, params)` and then reads
`FRAME_NORMAL_ATTR` / `FRAME_TANGENT_ATTR` per vertex (`multires.cc:225-233`);
`ensureBaseAndFrames` builds a throwaway `mesh::Mesh`, sets its `co` from
`lp.base`, calls `recalc_normals()` and `updateFramesAll`, then copies the two
attributes into `lp.frameNo` / `lp.frameTa` via `extractFrameAttrs` and deletes
the mesh (`multires.cc:316-354`, `:191-209`).

**The lattice is already at both use sites.** The decode
(`multires.cc:240-260`) and encode (`multires.cc:481-508`) loops are both
`for g / for v / for u` with `const int *gv = &lvl.gridVerts[g*w*w]` in hand, so
`gv[v*w + u±1]` and `gv[(v±1)*w + u]` — the `±u` and `±v` neighbours — are
already addressable. Neither loop needs restructuring.

**The parametrization is already first-class.** `assignGridUVs`
(`multires.cc:80-137`) computes the exact grid-local param
`(lu, lv) = ((u+du)/S, (v+dv)/S)` per corner and stores it as `.ptex.c.grid` /
`.ptex.c.uv` alongside the packed chart uv.

**The frame attributes have other consumers, all outside multires.**
`FRAME_NORMAL_ATTR` / `FRAME_TANGENT_ATTR` are read by `vdm_bake.cc:54-56`,
`vdm_promote.cc:52-54` and `vdm_splat.cc:84-86`, plus brush use. Nothing in
`displace/frames.cc` needs to change, and it keeps its transcendental-free
guarantee (`frames.cc:117-122`) for those consumers.

**`seamMates` (`grids.cc:242`) has no callers in `source/`.** Border-replica
reconciliation is an available primitive, not an active mechanism — worth knowing
before designing around it.

**The engine store is session-scoped.** `_enter_multires` re-seeds the whole
stack from Blender's top-level positions on every enter
(`multires.py:168-179`, `convert.py:212`), `flush` bakes back to MDisps, and the
only serialized store blob is the in-memory undo payload (`undo.py:96-101`).
Blender's tangent-space MDisps is the persistent truth.

## The change

### Replace the tangent source, keep everything else

Per level, for each grid vertex, derive an orthonormal frame from the level's
`base` positions and the grid lattice:

```
du = base[gv[v*w + u+1]] - base[gv[v*w + u-1]]     (one-sided at u = 0, S)
dv = base[gv[(v+1)*w + u]] - base[gv[(v-1)*w + u]] (one-sided at v = 0, S)
n  = normalize(du × dv)
t  = normalize(du - n * (du·n))                     (Gram-Schmidt)
b  = n × t
```

Only `+ - * / sqrt` — the cross-backend bit-parity property is preserved by
construction, without depending on `frames.cc` to preserve it.

`applyDisp` and `ensureBaseAndFrames` then stop calling `updateFramesAll`
entirely, `extractFrameAttrs` becomes dead, and `ensureBaseAndFrames` no longer
needs to build, populate, normal-recalc and destroy a temporary `mesh::Mesh` per
level — it computes `lp.frameNo` / `lp.frameTa` directly from `lp.base`. **The
frame path gets both simpler and cheaper**; the cross-field diffusion
(`frames.cc:294-330`) is the single most expensive thing it currently does.

### The one real complication: border vertices

A vertex on a grid boundary belongs to 2 grids (edge) or N grids (cage vertex, N
= valence), and its `+u` direction differs in each — by ~2π/N at a cage vertex.
`frameNo`/`frameTa` are per-vertex-id today, so a value has to be chosen.

**Choose canonically: the owning grid with the lowest index.** Build a per-vid
`(grid, u, v)` table in one pass over `gridVerts` (first writer wins), and derive
each vertex's frame from that grid alone.

The reason this is correct rather than a compromise is worth stating explicitly,
because it is the load-bearing insight of this design:

> **The frame does not need to be geometrically meaningful. It needs to be
> deterministic, free of discrete ambiguity, and to rotate with the surface.**

Encode and decode both read the same per-vid frame and both operate on the same
per-vid `dp = pos[vid] - base[vid]`, so *any* frame satisfying those three
properties round-trips exactly. A canonical-grid tangent satisfies all three: it
is a pure function of cage topology and current base positions, it involves no
choice among symmetric alternatives, and being a finite difference of live
positions it rotates with the surface automatically.

Two consequences follow, both good:

- **Replicas stay bit-identical.** Every replica of a border vertex uses the same
  per-vid frame and the same per-vid `dp`, so `storeDispFromPositions` writes the
  same three floats into each grid's slot — preserving today's invariant and the
  `test_multires.cc:317-320` byte-identical gate. Per-grid frames would also be
  correct (each replica's `d` expressed in its own frame still decodes to the
  same position) but would break that invariant for no gain.
- **No averaging, so no cancellation.** Averaging tangent *directions* across
  grids at a valence-4 vertex cancels — the failure `FRAME_TANGENT_ATTR` is
  NOINTERP to avoid (`frames.h:31-32`). Note Blender does not average tangents
  either: it averages the resulting **object-space** displacement after
  conversion (`subdiv_displacement_multires.cc:255-303`), a different and safer
  operation.

The cost is a tangent field that is discontinuous across grid borders. The
decoded *surface* is continuous regardless (the stored `d` compensates), so this
affects only how smooth the stored `d` field is — which matters for compression
ratio and for anything that filters `d`, not for correctness. Worth measuring;
not worth pre-optimizing.

### Degenerate cases

- **`du × dv` near zero** (collapsed cell, or a grid corner where the one-sided
  differences are collinear): fall back deterministically, the way
  `frames.cc:332-343` already does for degenerate verts. This must be a pure
  function of the input, not of iteration order.
- **`du` parallel to `n`** after Gram-Schmidt: same fallback.
- **Extraordinary vertices** need no special handling — the canonical-grid rule
  makes them the same case as any other border vertex.

## What this does *not* change

Deliberately, and this is most of the value:

- **Storage.** Channel 0 stays a frame-relative float3; `kGridsFormatVersion`
  does not move. Values *change meaning* within a session, but the engine store
  is session-scoped and re-seeded from MDisps on every enter, so **there is no
  file-compatibility question at all** — the property the predecessor spent a
  version bump and a migration path failing to obtain.
- **Composition.** `ensureChain`, the stencils, `Refiner`, the LRU, slot
  management, `materialize`, `assignGridUVs`.
- **The cage.** Never written. Delete Higher, Apply Base, shape keys, vertex
  groups, the modifier stack and the armature rest pose are all untouched.
- **Undo.** The meshlog delta path stays valid, because a stroke still affects
  exactly one level's mesh.
- **The Blender seam.** `export_bake` still pushes absolute top-level positions;
  no fork change, no bake reordering, no reshape entry point.
- **`downRefit`.** Unchanged and still unwired. Its `level >= 2` restriction stops
  being interesting.
- **Sculpt layers.** Channels 1..N stay frame-space and stay consistent with
  channel 0, because both move to the new frame together — there is no
  mixed-space window.
- **The addon.** No Python change.

## What it does not fix

Stated plainly so it is not oversold.

**The lever arm survives.** `∂pos/∂(frame rotation) ≈ |d|` still holds, and a
coarse edit still moves the base and hence the frames of finer levels. What
changes is that the residual perturbation is now purely *continuous* — a small
rotation of a finite-difference direction under a small base motion — instead of
a continuous term plus a discrete 90° jump. Large `|d|` is still worse
conditioned than small `|d|`.

So the predecessor's conditioning motivation was not wrong, only its mechanism.
A properly regularized joint multilevel solve remains a coherent future project
(see the postmortem's closing note); it just stops being urgent once the failure
mode is continuous.

**Conditioning now depends on parametrization skew** instead of on cross-field
stability. Where grid cells are badly sheared, `du` and `dv` are far from
orthogonal and `t` after Gram-Schmidt is a poor representative of the surface
direction. This is Blender's failure mode too, and it is bounded and continuous —
but it should be measured rather than assumed benign.

## Scope

Sites, all in `source/subdiv/multires.cc` unless noted:

| Change | Est. |
|---|---|
| `gridFrame()` helper: finite differences, Gram-Schmidt, borders, degenerate fallback | ~60–80 new |
| per-vid canonical `(grid, u, v)` table, one pass over `gridVerts` | ~15 new |
| `ensureBaseAndFrames` (`:316-354`): drop temp mesh + `updateFramesAll` + `extractFrameAttrs` | ~25 net **simpler** |
| `applyDisp` (`:225-233`): drop `updateFramesAll` + attr lookups | ~10 net **simpler** |
| `extractFrameAttrs` (`:191-209`) | deleted |
| `captureDetailToVdm` (`:511-541`) | see below |
| new tests in `test_multires.cc` | ~100 new |

**~150–250 lines, one file, one module.** No c-api entry point, so none of the
four bridge sites (`subdiv_c_api.cc`, `defineBindings`, `wasm_add_symbols`,
napi/TS) are touched. *Actual for Phase 1: +151 in `multires.cc`, +13 in
`multires.h`, +229 in `test_multires.cc` — the estimate held for the code and
was low by ~2x on the tests.* No addon change, no fork change, no undo change,
no format change.

**`captureDetailToVdm` is the one integration point that needs a decision.** It
converts multires displacement into a VDM store, and the VDM consumers
(`vdm_bake.cc`, `vdm_promote.cc`, `vdm_splat.cc`) read the cross-field
`FRAME_*_ATTR`. After this change multires `d` is in a different frame than
those attrs describe, so the capture must either convert through object space
(decode with the parametric frame, re-encode with the provider frame — exact, and
the code already reconstructs the base at `:531-541`) or the mismatch must be
gated. Converting is preferable and is the smaller of the two.

**`source/debug/script.cc:1949`** calls `downRefit`, which is unaffected. Noted
only because the predecessor's scope work missed the caller.

## Open questions

1. **Normal source: parametric or provider?** `n = normalize(du × dv)` makes
   multires fully self-contained and drops `updateFramesAll` from the path
   entirely. Keeping the provider's *smoothed* normal (`frames.cc:242-265`) may
   decode better on coarse levels, at the cost of retaining the dependency and
   the smoothing's own base-motion sensitivity. The normal has no ±90° problem
   either way, so this is a quality/cost question, not a correctness one.
   Recommend parametric first, measure.
2. **Central vs one-sided differences throughout.** Central differences are
   better conditioned but need the border special case anyway; using one-sided
   everywhere is simpler and uniform. Probably not worth the uniformity.
3. **Does the discontinuous tangent field across grid borders measurably hurt
   lz4 chunk compression** (`grids.h:1-13`, X5 eviction)? If it does, per-grid
   frames become worth revisiting despite losing replica bit-equality.
4. **Whether a level's frames should be cached at all** once they are this cheap
   to compute. `lp.frameNo` / `lp.frameTa` are two float3 arrays per resident
   level; recomputing on demand would trade memory for arithmetic that is now
   just a subtract and a cross product.

## Test gates

The gate the predecessor called "moot" is the central one here, because there
*is* an absolute frame and its stability is now the claim being made.

- **Frame stability under a coarse edit.** Move one cage vertex by a small
  amount, rebuild a fine level's frames, and assert every tangent changed
  continuously — no dot product with its previous value below a threshold. This
  is the direct regression test for the ±90° flip and it fails today.
- **Frame determinism.** Build the same level twice from the same base; frames
  bit-identical. Also across backends, preserving the existing parity property.
- **Encode/decode exactness.** `d = frame⁻¹(dp)` then `dp' = frame(d)` round-trips
  to float tolerance, including at border vertices and extraordinary vertices.
- **Border replicas remain bit-identical**, i.e. `test_multires.cc:317-320`
  continues to pass unmodified — the canonical-grid rule's main structural claim.
- **Rotation following.** Rotate a limb at a coarse level; fine detail tracks it.
  Passes by construction (the tangent is a finite difference of live positions),
  so this is a guard against regressing back to a stored orientation.
- **Degenerate configurations.** Collapsed cell and collinear one-sided
  differences produce the deterministic fallback rather than NaN, and produce the
  *same* fallback on repeat.

## Suggested order

The plan is the authority on this; it corrects step 3's placement (see below).

1. ✅ **Done.** `gridFrame()` + the canonical-grid table, with the
   frame-stability and determinism gates. No behaviour change yet — compute both
   frames and compare.
2. Switch `ensureBaseAndFrames` and `applyDisp` over; delete `extractFrameAttrs`.
   Existing tests should pass unmodified except for stored `d` values, which are
   not asserted (every `store.elem` use in `test_multires.cc` is space-agnostic).
   `materialize()` is a third site this list missed.
3. Convert `captureDetailToVdm` — but **gate it to refuse during step 2**, or
   there is a window where multires `d` is parametric-frame while capture still
   reads it as provider-frame.
4. Measure: parametrization skew on a production-shaped cage, and lz4 chunk
   ratio before/after.

Steps 1–2 are independently shippable and each leaves the product in a correct
state — the property the predecessor's phase plan could not offer at any
boundary.
