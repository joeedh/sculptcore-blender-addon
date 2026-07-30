# Multires: object-space displacement with an automatic downward cascade

**Status: SUPERSEDED — rejected 2026-07-30, never implemented.** Killed by an
adversarial pressure test on the day it was written. Superseded by
[multires-parametric-frame.md](./multires-parametric-frame.md), which addresses
the same defect at a small fraction of the cost.

This page is kept as a postmortem, not a plan. It exists so the ideas below do
not get re-proposed, and because the *diagnosis* that motivated it was correct
and is still load-bearing for the successor.

---

## What was right, and is carried forward

**The defect is real and, if anything, was understated.** Multires displacement
is stored in a tangent frame whose tangent comes from a curvature-derived 4-RoSy
cross field (`frames.cc:294-330`), and `buildLevelTopo` (`multires.cc:54-78`)
hands the frame provider a *bare quad mesh* with no sharp/seam/group attrs — so
`use_features` degenerates to open borders only and the tangent is pure
`estimatePrincipalDir` curvature. On a nearly-flat subdivided base that is
umbilic noise.

**The lever arm.** `pos = base + R(base)·d`, so `∂pos/∂(frame rotation) ≈ |d|`.
Frame perturbation is amplified by displacement magnitude, from three sources: a
coarse edit moving the base; normal smoothing (`frames.cc:242-265`); and the
cross field's ±90° ambiguity.

**The third is the sharp one, and it is a discrete failure, not drift.** Frames
are recomputed from geometry alone, so nothing pins a level's frame *choice*
across rematerializations. A frame landing on a different 90° image decodes
unchanged stored disp **rotated by 90°** — a visible detail flip in one step,
near features and field singularities, not 1e-7 accumulating over a thousand
strokes.

**Everything under the old *What exists today* section was validated and still
holds.** Storage is hierarchical and frame-relative (`grids.h`,
`multires.h:9-12`, `ensureChain` at `multires.cc:264`). The frame is genuinely
orthonormal (`frames.cc:332-343`) and the encode (`multires.cc:502-505`) / decode
(`multires.cc:252-257`) are an exact orthogonal pair. The provider is
transcendental-free by design (`frames.cc:117-122`) for cross-backend bit
parity. All edit energy lands in one level (`storeDispFromPositions`,
`multires.cc:451`). `downRefit` requires `level >= 2`, so the cage can never
absorb anything (`test_multires.cc:562`), and nothing in the addon calls it.
The Blender seam speaks absolute positions, top level only (`multires.py:182`),
against a flat `MDisps` (`DNA_meshdata_types.h:215`).

---

## Why it was rejected

Four independent kills. Any one of them is disqualifying.

### 1. The delta rotation cannot work, and the correct version reintroduces a frame

The design proposed abolishing the absolute frame and restoring rotation
following with an incremental rotation built from cross/dot products only (to
preserve the transcendental-free bit-parity property).

The only such construction is the minimal, twist-free rotation `n_old → n_new`,
which equals the true surface rotation **only when the normal is perpendicular
to the rotation axis**. Measured error in where detail lands:

| rigid rotation | normal ⊥ axis | 30° off | 60° off | normal ∥ axis |
|---|---|---|---|---|
| 45° | 0.00° | 23.40° | 39.47° | **45°** |
| 90° | 0.00° | 53.13° | 81.79° | **90°** |

This is the generic case, not a corner: bend a limb and detail on the flanks
whose normals point along the axis does not rotate at all while the top and
bottom do — a shear discontinuity along a line, at full stroke amplitude. It also
returns NaN at exactly 180° (`1+c = 0`), with `‖RᵀR−I‖` growing as `1/(1+c)`
approaching it.

The construction that *is* correct — polar decomposition of a deformation
gradient fitted to the 1-ring — recovers the rotation to 5e-16 even at 179° and
is transcendental-free. But a surface 1-ring is **rank 2**: it becomes rank 3
only when the normal is added, and pinning the remaining twist needs a second
in-plane reference, i.e. a tangent.

**So the design's central premise is unachievable.** You cannot simultaneously
remove the frame from the composition path and follow rotation. You can only
choose *which* frame ambiguity you have — which is exactly what the successor
does, deliberately.

Two supporting facts found along the way: `litestl/math/quat.h` is abandoned,
uncompilable scaffolding (`var a = ...`, `T vec_[4]` with no `T` in scope,
`return this;`) and is `#include`d by nothing; and the only working 3×3 type is
Eigen-backed (`matrix.h:3-4`, `:147-152`), which would put architecture-dependent
association order on the composition path — the precise thing
`frames.cc:117-122` exists to avoid.

### 2. The cascade relocates the displacement instead of shrinking it, and rings the cage

A per-level least-squares fit is a **deconvolution, not a low-pass split**. The
subdivision operator has `σ_min = 0.5`, so `A⁺` overshoots by up to 2× per level
and the overshoot compounds downward.

Simulating the exact pyramid the engine builds (1-D regular Catmull-Clark ==
cubic B-spline, 4 levels, cage 32 → 512, `A` from the same (1,4,6,4,1)/8 mask,
greedy `L→L-1→…→cage` as `downRefit` implements it), against a joint solve
minimising `Σ‖D_l‖²` under the same surface constraint. Cage spacing = 16 fine
verts:

| edit width | max‖D‖ before | greedy: cage / max‖D‖ / Σ‖D‖² | joint: cage / max‖D‖ / Σ‖D‖² |
|---|---|---|---|
| 2 | 1.00 at L4 | 0.727 / **0.750 at L1** / 2.763 | 0.693 / 0.289 / **0.417** |
| 8 | 1.00 at L4 | **1.536** / 0.107 / 0.0376 | 1.527 / 0.021 / **0.0085** |
| 32 | 1.00 at L4 | 1.045 / 0.0009 / ~0 | 1.045 / 0.0002 / ~0 |

Read the `w=2` row: the pyramid's largest displacement goes from 1.00 at level 4
to 0.750 at level 1. **It moved; it did not shrink** — at 6.6× the achievable
minimum energy. The `w=8` row is an ordinary detail stroke covering half a cage
edge, and it **moves the cage by 1.54× the edit amplitude**.

The "floor set by cage resolution" the document claimed does not exist: 98.8% of
a bump one-eighth of a cage edge wide drains downward, as an alternating-sign
ripple. A unit fine spike produces cage values
`[0.008, −0.015, 0.029, −0.059, 0.142, −0.059, 0.029, …]`.

**Root cause: the design never stated an objective for the pyramid.** The
constraint `pos_L = stencil(pos_{L-1}) + D_L` is satisfiable by `D_L` alone, so
the decomposition is underdetermined and needs a regularizer (`Σλ_l‖D_l‖²`) or a
genuine frequency split to be well-posed *as a redistribution*. Greedy per-level
LS is a particular heuristic, and it is the worst-behaved one for exactly the
content the design claimed it would leave alone.

The consequence lands on the export, not just internally: a rippled,
locally self-intersecting cage is a *worse* input to Blender's reshape than a
flat cage with large `|D|`, since the cage is what MDisps measures against.

*Caveat honestly stated:* the simulation is 1-D and regular, so the constants do
not transfer. The direction does — `σ_min` near an extraordinary vertex is
*smaller*, so the overshoot is larger. To settle it in-engine: run `downRefit(2)`
plus a hand-added `downRefit(1)` on a subdivided cube after a narrow level-3
edit and dump cage positions; the alternating sign should be directly visible.

### 3. Undo structurally cannot carry a cascade stroke

The primary undo path is a **meshlog seek over the active level mesh only**
(`undo.py:199-214`); the store-blob path runs only on generation mismatch
(`:185-188`). The meshlog is built against `Multires_activeTree`, one level's
slot mesh (`stroke.py:106-108`, `convert.py:822-823`), and `Multires::writeback`
likewise touches one level (`multires.cc:607-625`).

A cascade stroke spans the cage, every level ≤ active, and (with delta rotation)
every level > active. **None of that is in the meshlog.** Sculpt at level 4 and
press Ctrl-Z: the level-4 slot reverts while the cage and levels 1–3 keep the
post-stroke state. Repeat, and the cage ratchets monotonically while the surface
appears to return.

The proposed mitigation ("a new serialized channel plus a new field in the addon
step") was the wrong fix. The actual requirement is that *every* multires decode
take the blob path, retiring the P6 Tier-2 delta-undo design for multires
sessions. Note that Blender wraps its own `multires_base_apply` in a **full mesh
undo push** (`object_multires_modifier.cc:398-402`) — its authors judged cage
mutation unrepresentable in a delta step, which is precisely what was attempted.

### 4. The prescribed bake-ordering fix cannot be built on the API it names

The document prescribed: write cage positions into `ob.data`, tag, re-evaluate,
then reshape from top-level positions. The reshape context is built from **two
different meshes**: `base_positions`, topology and creases from `ob.data`
(`multires_reshape_util.cc:196-203`), but `subdiv` — which supplies `P` in
`D = pos - P` — from `mesh_get_eval_deform` (`:47-51`). Today both refer to the
same unchanged cage, so the split is invisible. Write the cage and
`foreach_grid_coordinate` walks new-cage topology while `P` samples the **old**
cage's limit surface: MDisps absorbs the entire cage delta, which is exactly the
failure the reorder existed to prevent. `depsgraph.update()` does not fix it.

Blender's own cage-mutation path proves the shape of the real fix:
`multiresModifier_base_apply` (`multires_reshape.cc:391-437`) calls
`apply_base_refine_from_base` *before* mutating and `..._from_deform` *after*,
inside the same context, re-running leading deform modifiers
(`multires_reshape_apply_base.cc:149-167`). All three helpers are internal to
`intern/multires_reshape.hh` with no RNA wrapper. **This is a fork change**, and
the scope table had no row for the fork at all.

---

## Secondary findings that also had to be answered

Not individually fatal, but none had a mitigation in the plan.

- **Nothing the cascade builds survives the seam except the cage.**
  `_enter_multires` seeds the entire stack from top-level positions only
  (`multires.py:168-179`, `convert.py:212`), and `refresh` frees and re-enters
  (`convert.py:1093-1109`), reachable from any foreign undo. Exit/re-enter and
  levels 1..N−1 are flat again with all energy back at level N. Phases 1–4 bought
  a within-session property only.
- **Phase 1's "accept the rotation regression here" was not available.**
  `md.sculpt_levels` is one slider drag (`handlers.py:74-77` →
  `convert.py:977-999`), and the sheared result bakes with no original-grid
  preservation: `reshapeFromVertPositions` forces `sculptlvl = totlvl`
  (`multires_reshape.cc:291-294`), so the details-preserving smooth early-outs
  (`multires_reshape_smooth.cc:1320-1324`) and the top grid is overwritten
  wholesale. Block out at level 1, drag to 4, save — the pre-stroke MDisps is
  gone.
- **Cage-wavelength content in the cage silently redefines Delete Higher**
  (`OBJECT_OT_multires_higher_levels_delete`): it no longer deletes what was
  sculpted at level 4. Blender ships cage mutation as an explicit, opt-in
  operator; the design made it implicit, per stroke.
- **Cage divergence is undetectable and the cage is not flushed per stroke.**
  With the draw provider active — always, for multires — stroke end calls
  `draw_refresh`, not `flush` (`stroke.py:911-914`). Both divergence detectors
  are vertex-count-only (`convert.py:1124-1130`, `:932`).
- **The scope table structurally could not see the layer stack.** Sculpt layers
  live in `source/displace/compositor.cc` (248 lines) plus the Mesh-side table
  (`mesh/mesh.h:374-421`), *outside* `source/subdiv/`; `source/vdm/` is ~2.9
  kLOC; and `downRefit` has a live caller at `source/debug/script.cc:1949`.
- **The proposed per-vert residual gate is not implied by least squares**, which
  bounds only global L2 — which is why the existing gate is a global
  `stencilResidual` ratio (`test_multires.cc:527-538`). And the cascade would
  permanently kill the `posIsBase` / `dispNonZero` fast paths
  (`multires.cc:169-187`, `:303-310`) and the untouched-region invariant.

---

## Claims made in the draft that were wrong

Recorded so they are not re-derived.

- **"No lever arm" was false and self-contradicting.** `pos = base + R_delta·D`
  gives `∂pos/∂R_delta ≈ |D|` — the same amplification, relocated from frame
  perturbation to delta perturbation. If the lever arm survives, the cascade is
  the load-bearing half and the phase order (frame flip first, cascade last) was
  backwards.
- **The drift gate targeted the wrong quantity by 4–6 orders of magnitude.**
  Measured float32 composed-delta drift at N=10⁴: reversible 1.64e-5, correlated
  full turn 4.37e-6, magnitude 4.8e-7. The `≈N·ε` worry was noise next to the
  *systematic* twist error, which is degrees. Worse, the proposed rotate-and-
  invert gate is structurally the case where consecutive errors cancel: it passes
  at 1.6e-5 while the same construction is wrong by 53° in the non-reversible
  case.
- **"Object space is the persistent form" was never true.** The persistent form
  is Blender's tangent-space MDisps; the engine store is session-scoped and the
  only serialized blob is the in-memory undo payload (`undo.py:96-101`). The
  version-field discussion protected nothing. Persisting object space is in fact
  *unrecoverable*, since Blender re-evaluates MDisps against the current cage
  every depsgraph tick (`subdiv_displacement_multires.cc:329-359`) with no hook
  for the addon to apply a delta.
- **The export-conditioning payoff** (already corrected once before the pressure
  test) does not exist for intra-level redistribution: `D = pos - P` with `P`
  from the base cage (`multires_reshape_util.cc:730-750`), and `pos` is what the
  cascade preserves.

---

## What the pressure test settled *positively*

Genuine results, worth keeping regardless of this design's fate.

- **The unmasked cascade is exactly path-independent and idempotent** — settling
  the old open question 1 in the affirmative. `A_l` is injective (the vertex
  symbol `(6+2cos ω)/8` never vanishes; `σ_min = 0.5`), so `AᵀA` is SPD, the
  minimizer is unique, and the cage is a function of `pos_L` alone. Verified at
  0.00e+00 across differing stroke orders and active-level histories; a second
  pass changes nothing. No oscillation, no overshoot-in-iteration.
- **`cond(AᵀA) = 8`, independent of mesh size**, so `solveStencilLeastSquares`'s
  Jacobi-CG converges in ~10 iterations at any resolution. The solver was never
  the weak link.
- **Influence decay through `(AᵀA)⁻¹` is 0.4465 per coarse vertex**, from the
  palindromic roots of its symbol `(70 + 56cos ω + 2cos 2ω)/64`, confirmed
  numerically to 4 digits. So masking accuracy is computable: 6 rings → 1e-2,
  9 → 1e-3, 12 → 1e-4, 14 → 1e-6. This also kills masking as a *saving*: 12 rings
  per level in 2-D is the whole level at levels 1–2, exactly where a cascade would
  need to reach.
- **Masked cascades are path-dependent at the decay tail** — two stroke orders
  reaching an identical surface leave cage differences of 6.16e-2 at radius 3,
  5.83e-3 at 6, 4.46e-5 at 12, i.e. `0.4465^r`.
- **Surface preservation is exact by construction**, and seam replication is a
  non-issue for the fit: the solve and `storeDispFromPositions` work in dense
  vert-id space (`multires.cc:481-508`), so both replicas of a seam vert derive
  from the same `pos[vid]`/`base[vid]` and receive bit-identical values.
- **Object-space storage does not break Blender's animation path** — the
  hypothesis was tested and held, because MDisps stays tangent-space and the
  engine store is session-scoped.

---

## Do not re-propose

1. **Object-space displacement as the stored form**, on the grounds that it
   removes frame ambiguity. It relocates the ambiguity into the delta rotation,
   which cannot be made correct without a frame (kill 1).
2. **A delta/incremental rotation from cross and dot products.** It is the
   twist-free minimal rotation and is wrong by up to the full rotation angle.
3. **Greedy per-level least-squares as a redistribution mechanism.** It is a
   deconvolution and rings. Any future redistribution needs a stated objective
   with a per-level penalty, or a real frequency split — a different solver, not
   a masked `solveStencilLeastSquares`.
4. **Automatic per-stroke cage mutation.** It is unrepresentable in the delta
   undo path, redefines Delete Higher, and needs a fork-side reshape entry point
   that does not exist.
5. **Masking the stencil solver as a performance measure.** The dilation width
   required for path independence is the width at which masking stops saving
   anything.

**Still open as a possible future, with no urgency:** a properly regularized
*joint* multilevel solve (all levels at once, `Σλ_l‖D_l‖²`) is a coherent way to
improve conditioning, and the joint-solve column above shows it beats greedy by
4–7×. It is a separate and much harder project, and once the discrete failure is
gone (see the successor) there is no pressing reason to attempt it.
