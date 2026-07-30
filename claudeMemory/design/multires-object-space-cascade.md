# Multires: object-space displacement with an automatic downward cascade

**Status: design only. Nothing here is implemented.** Decisions recorded from a
design discussion on 2026-07-30; the "Decided" items are the repo owner's calls,
the "Open" items are not settled. Everything under *What exists today* is
validated against the tree at that date and cited. Fresh-context audited
2026-07-30; the corrections are folded in, and the one claim that did not survive
is recorded under *What this does to the export* so it does not get re-proposed.

The short version: the current store keeps each level's displacement in a
tangent frame and lands an entire edit in one level, which guarantees large
per-level displacement — the worst case for tangent-frame conditioning. The
target model edits each level's vertices directly, cascades downward into the
coarser levels **and the cage** by construction, keeps finer levels as
object-space displacement, and converts to tangent space exactly once, at the
Blender seam.

The payoff is **engine-internal**: no absolute tangent frame on the composition
path means no lever arm and no cross-field ambiguity, whatever the residual
happens to be. The export improves only to the extent the *cage* moves — see
*What this does to the export* for why redistributing among levels does nothing
for Blender's side.

## What exists today (validated)

**Storage is hierarchical and frame-relative.** `GridsStore` keeps a per-level
array per channel, indexed `elem(level, channel, grid, u, v)` (`grids.h`), with
`addLevel()` / `dropTopLevel()` growing and shrinking the stack. Channel 0 is
the float3 "disp", expressed in the level's tangent frame. Positions compose
coarse→fine: `base_L = stencil_L(pos_{L-1})`, `pos_L = base_L + frame·disp_L`
(`multires.h:9-12`), walked by `ensureChain` (`multires.cc:264`).

**The frame is genuinely orthonormal**, which matters for what follows.
`frames.cc:332-343` is a final orthonormalization pass: every tangent is
projected ⊥ its smoothed normal and normalized, with a deterministic fallback
for degenerate verts. So `(t, b = n×t, n)` is orthonormal and the encode
(`multires.cc:502-505`, `d = (dp·t, dp·b, dp·n)`) and decode
(`multires.cc:252-257`, `p = base + t·D₀ + b·D₁ + n·D₂`) are an exact orthogonal
pair up to float rounding. The provider is also transcendental-free by design
(`frames.cc:117-122`, only `+ - * / sqrt`) so identical bases give bit-identical
frames across backends.

**Drift is bounded today by not re-encoding.** `writeback` masks to changed
verts and skips verts bit-identical to the materialized baseline, so untouched
regions are never re-encoded. Gated: `test_multires.cc:317-320` asserts an
edit-free writeback leaves the store byte-identical; edited verts and
`downRefit`'s fine-surface preservation are gated at 1e-5.

**All edit energy lands in one level.** `storeDispFromPositions`
(`multires.cc:451`) writes the whole displacement into the active level's
channel — every frequency together. `setActiveLevel` (`multires.cc:1253`) is
writeback-then-materialize.

**The downward direction is a separate, partial, unwired pass.** `downRefit`
(`multires.h:92`) least-squares-fits level−1 to the level-`L` surface and
re-expresses `L` against the new base. It **requires `level >= 2`** —
`downRefit(1)` returns 0 (`test_multires.cc:562`), so the cage can never absorb
anything. It is exported as `Multires_downRefit` (`subdiv_c_api.cc:78`) and
**nothing in the addon calls it**.

**The Blender seam speaks absolute positions, top level only.** `export_bake`
(`multires.py:182`) reads the engine's top-level positions and calls
`ob.multires_reshape_from_vert_positions`. Blender's side is flat by
construction: `MDisps` is one `float (*disps)[3]` of `totdisp` samples per loop
(`DNA_meshdata_types.h:215`), a single top-level grid, with lower-level edits
handled by propagation — "propagated up from this level to top.level"
(`multires_reshape.hh:58`).

**And Blender's tangent basis is a different animal from ours.** It comes from
limit-surface derivatives `dPdu`/`dPdv`
(`multires_reshape_util.cc:535-553`) — *parametric*, not orthonormal, and with no
cross field anywhere in it, so it never had the ±90° ambiguity described below.
Its conditioning is governed by parametrization skew, which nothing in this
design touches. Critically, the displacement it stores is measured against the
**base mesh's** limit surface: `D = pos - P` with `P` sampled from the base cage
(`multires_reshape_util.cc:730-750`). That single line is why the export claim
had to be walked back.

## The instability mechanism

`pos = base + R(base)·d`, so `∂pos/∂(frame rotation) ≈ |d|`. **The frame is a
lever arm.** Every source of frame perturbation is amplified by the displacement
magnitude:

- a coarse edit moving the base, which recomputes the finer level's frames;
- normal smoothing (`frames.cc:242-265`);
- the cross field's ±90° ambiguity. The tangent is a 4-RoSy representative;
  `FRAME_TANGENT_ATTR` is NOINTERP precisely because averaging two cross
  directions can cancel (`frames.h:31-32`), and the diffusion rotates each
  neighbour to the nearest 90° image (`frames.cc:294-330`).

The third is the sharp one. Frames are recomputed from geometry alone, so
nothing pins a level's frame *choice* across rematerializations. If a frame
lands on a different 90° image than it had before, unchanged stored disp decodes
**rotated by 90°** — not 1e-7 accumulating over a thousand strokes, but a
visible detail flip in one step, near features and field singularities.

Both problems scale with `|d|`, and the current design guarantees `|d|` is large:
sculpt a broad shape at level 4 and all of that low-frequency content sits in
level 4's disp with the coarse levels flat.

That gives two independent fixes, and the design uses both — but they are not
equally strong. **Removing the absolute frame from the composition path removes
the ±90° flip outright**, at any `|d|`; shrinking the per-level residual only
scales the remaining continuous error down. So the frame change is the fix and the
cascade is the amplifier reduction. Worth keeping straight, because it is what
survives if the cascade turns out to redistribute less than hoped.

## Target model

### Decided

1. **The cage moves.** Coarse levels *and* the base mesh absorb their share of
   an edit.
2. **Levels ≤ active are edited directly**, with the downward fit keeping the
   cage and coarser levels consistent by construction, per stroke — not as a
   separate pass a user has to invoke.
3. **Levels > active hold object-space displacement** and are not re-encoded
   against a new absolute frame when a coarser level moves. (They are still
   *touched* if the delta rotation lands — see the trade-off below.)
4. **"A stroke touches one level" is abandoned as an invariant.** It was never
   the right framing.
5. **Object-space displacement is the uniform storage model at every level.**
   Coarse levels holding *real positions* instead is a candidate optimization,
   not part of the design: admissible only if it can be shown to improve
   performance without sacrificing quality. Until measured, every level stores
   `D` and composes `pos = base + D`.

Item 5 is a correction. An earlier draft recorded "levels ≤ active hold real
positions" as decided, which contradicts uniform object-space displacement
everywhere else in this document and would quietly change what `dispNonZero` /
`posIsBase` mean and what `addLevel`'s zero-displacement contract expresses
(today: "smooth subdivision, no detail yet"). Two representations in one stack is
a real cost; it needs to buy something measurable.

### Why object space is the working *and* persistent form

- **The decomposition is linear in object space and nonlinear in tangent
  space.** Stencils are linear operators and the fit is least squares, but level
  `L`'s frames depend on level `L−1`'s positions — so encoding per level makes
  the analysis a coupled nonlinear system. Solve the pyramid in object space,
  land it, encode once.
- **Redistribution becomes cheap.** This is the stronger argument. Today's drift
  guard is "skip bit-identical verts, never re-encode untouched regions". A
  cascade re-touches coarser levels on every stroke, including verts never
  sculpted at those levels — with tangent-space *storage* those levels start
  paying a frame encode/decode per stroke. Object space replaces that with an
  add and a subtract (~1 ulp per round trip). Not free: the least-squares fit
  remains a genuinely lossy step, and it is the one that dominates.
- **`invalidateAbove` survives unchanged in spirit.** Re-derive becomes "base
  moved, re-apply stored object-space disp" — a cheap add instead of a frame
  decode.

### The rotation trade-off

**Object-space displacement translates with the base but does not rotate with
it.** Rotate a limb at level 1 and tangent-space detail follows the limb;
object-space detail keeps its original world orientation and slides off the
surface. This is the thing tangent space was buying, and it shows up immediately
on any rotational edit.

Three options, and the comparison has to include what the delta *costs*:

| | cost per edit | correct under rotation | discrete ambiguity | error growth over N edits | writes fine levels |
|---|---|---|---|---|---|
| Truly left alone | zero | **no** | none | none | no |
| Delta-rotated | one rotation apply per fine vert in the dilated support | yes | none | **≈ N·ε, composing** | **yes** |
| Absolute frame (today) | frame rebuild + encode/decode | yes | **±90° flip** | none — re-derived from geometry | yes |

**Recommended: delta-rotated**, with both of its costs stated plainly.

The win is the discrete one. The delta is near-identity for a stroke-sized edit,
so error scales with `|d|·|ε_delta|` with `ε_delta` small; the rotation between
two known base configurations is unique modulo twist; and **no absolute tangent
encode ever happens**, so the 90°-flip failure mode is *removed*, not mitigated.

The two costs an earlier draft omitted:

- **Stored orientation becomes path-dependent.** Deltas compose: the stored
  direction is the product of every delta ever applied, so error accumulates
  ≈ N·ε over N edits, and two edit sequences reaching the same base configuration
  need not leave the same stored disp. An absolute frame has the opposite
  profile — it re-derives exactly from current geometry and accumulates *nothing*.
  This is a straight trade of a bounded-but-accumulating error for the removal of
  an unbounded discrete one, and it is only obviously the right trade because the
  discrete failure is visible and the accumulation is not. It wants a drift gate
  (see *Test gates*).
- **It writes every level above the active one.** Applying a delta mutates stored
  disp throughout the dilated support at every finer level, which is why Decided 3
  says "not re-encoded against a new absolute frame" rather than "left alone".
  Option 1 is the only one that genuinely touches nothing.

Twist pinning is open (see below).

### What this does to the export

The tangent-space conversion happens **once, at the Blender seam, for the top
level only** — because MDisps is top-level only anyway. Our own frame provider
leaves the composition path entirely.

**But the export does not get better-conditioned by redistributing among levels,
and an earlier draft claimed it did.** Blender measures MDisps against the *base
mesh's* limit surface — `D = pos - P`, `P` sampled from the base cage
(`multires_reshape_util.cc:730-750`) — and `pos` is exactly the quantity the
cascade preserves. So draining low frequency out of level 4 into level 2 changes
Blender's `|D|` by **zero**. The only lever on the seam is the cage itself.

Two consequences:

- **The export benefit arrives in phase 5, not phase 4.** Phases 1-4 buy
  engine-internal stability and nothing at the seam.
- **The cage bounds how much can be absorbed.** A cage vertex can only absorb
  content at or above cage-edge wavelength; an edit broader than the mesh but
  finer than the cage's spacing has nowhere to go. So the residual-magnitude gate
  below has a floor set by cage resolution, and cannot be written as an absolute
  bound.

The stated payoff of this design is therefore engine-internal — removing the
lever arm and the cross-field ambiguity from the composition path — with a
bounded seam improvement as a phase-5 consequence.

## Consequences for existing code

**The bake ordering is load-bearing — this is the trap.** `export_bake` pushes
only top-level positions, and Blender's reshape re-expresses them against
*Blender's* cage. If our cage moved and Blender's did not, reshape silently
absorbs our cage motion back into MDisps displacement, re-inflating `|d|` on
Blender's side and undoing exactly the redistribution the cascade exists for.
The bake must write cage positions into `ob.data` first, tag, re-evaluate, *then*
reshape from top-level positions. Cage motion is a second channel across the
seam.

**Store format, and the version bump does less than it looks like.** Channel 0's
semantics change from frame-space to object-space → `kGridsFormatVersion` bump
(`grids.h:35`), and `grids.h:8-11`'s doc comment ("expressed in the level's
tangent frame") changes with it. But an earlier draft claimed the mismatch was
already handled, and that was wrong in three separate ways:

- **The read path accepts the old version.** `grids.cc:477` is
  `if (version == 0 || version > kGridsFormatVersion) return false;` — bumping to
  2 leaves a v1 blob *passing* the gate and being reinterpreted as object space.
  Rejecting or migrating v1 has to be written; the bump alone does nothing.
- **The desync latch is not a version check.** `_multires_desync`
  (`convert.py:883-892`) is a once-per-session `print`, and its two call sites
  (`:933` cage vert-count change, `:953` level-stack stall) never see a blob or a
  version number.
- **There are no persisted blobs to invalidate.** Store blobs live only in the
  in-memory undo step (`undo.py:97`), so within the addon the compatibility
  question is moot today. It matters for any future on-disk path, which is what
  the version field is for.

**Sculpt layers must move too — and they gate phase 1.** Channels 1..N are
frame-space, composited `disp_total = ch0 + Σ wᵢ·enabledᵢ·chᵢ`
(`multires.h:170-177`), which only means something if all channels share a space.
Flipping channel 0 alone puts two spaces in one additive sum. Object-space layers
also inherit the rotation problem, once per layer.

**Cage motion has no undo channel, and that is a phase-5 prerequisite.**
`GridsStore::write`/`read` (`grids.cc:440-500`) serializes channels over grid
verts and carries no cage positions; the addon's undo step is (meshlog id + store
blob) and the meshlog tracks the *materialized level mesh*, not the cage; and
`Multires_restoreStore` calls `invalidateAll()`, which re-derives from whatever
cage is current rather than restoring one. Once the cage carries sculpt energy,
undoing a stroke has to restore cage positions — a new serialized channel on the
engine side plus a new field in the addon's step. This is comparable in size to
the cage step itself and was missing from the scope table.

**`downRefit` changes shape.** It has to become region-restricted (the edited
support, dilated down through each stencil — stencils are CSR and local, so this
is tractable) and extended to the level 1 → cage step it currently refuses.
Cascading 4→3→2→1→cage per stroke end is a solve per level per stroke; unmasked
whole-level solves will not pay for themselves.

**The fit objective may want to be conditioning-aware.** Plain L2 residual
spreads error by mean, and a large *tangential* displacement is where frame
ambiguity bites hardest, so weighting tangential components above the normal one
is worth measuring. Note what this costs: weighted least squares still reduces to
normal equations and reuses the Jacobi-CG machinery, but a *true* max-norm
objective does not — minimax is non-smooth and needs a different algorithm
entirely (IRLS as an approximation, or an LP). Anything past reweighting is a new
solver, not a new objective. Descoped for v1 either way.

**The addon bridge gets simpler**, not harder: it already round-trips absolute
positions in both directions, so it stops being an impedance mismatch.

## Engine-side scope

Scoped by reading `source/subdiv/` at 2026-07-30, **not** by attempting the
change — the line counts are calibration, not estimates.

| Area | Lines today | Change |
|---|---|---|
| `grids.{h,cc}` | 757 | version bump + a v1 **reject/migrate** path |
| `subdiv.{h,cc}` (Refiner, stencils) | 542 | none |
| composition + writeback in `multires.cc` | ~250 of 1282 | rewrite, net **simpler** |
| the cascade in `multires.cc` | ~120 of 1282 | rewrite + genuinely new |
| delta rotation | 0 | new, ~100–150 |
| cage positions in store serialization + addon undo step | 0 | new, engine + addon |
| `captureDetailToVdm` | 95 | breaks; convert or gate |
| c-api + bindings + wasm/napi/TS bridge | 254 + ~35 | ~50 new, in **four** places |
| `test_multires.cc` | 1012 | fewer assertions than expected — see below |

The c-api line is easy to under-count. A new entry point has to be added to
`subdiv_c_api.cc`, `Multires::defineBindings` (`multires.cc:1219`), the
`wasm_add_symbols` list in `source/subdiv/CMakeLists.txt:26`, `napi_runtime.cc`
(`:97-107`), and `typescript/api/{wasm.ts,nativeManager.ts}`. The
`wasm_add_symbols` omission is the dangerous one: a missing entry links cleanly
and is invisible until the symbol is called at runtime.

**Most of the module is untouched.** `grids.h:8-11` already states the store is
frame-agnostic and means it: storage is float3-per-grid-vert regardless of the
space, so chunking, lz4 eviction, `seamMates`, `neighbor`, links and
serialization all survive as-is (the doc comment's description of the space does
not). So do the Refiner and stencil tables, the LRU and slot management,
`materialize`'s tree adoption, `assignGridUVs`, the layer table save/restore, and
every `*Out` export. `displace/frames.cc` (422 lines) stays — still needed for
brush use and for the VDM paths; it just stops being on the composition path.

**Where it gets simpler.** `applyDisp` (`multires.cc:215-262`) loses the
frame-provider call and the `n/t/b` basis → `pos = base + D`.
`storeDispFromPositions` (`:451-509`) loses the projection → `d = dp - rest`.

What dies in `LevelPos` (`multires.h:275-295`) is the *frame* cache —
`frameNo`, `frameTa`, `framesValid` — a deletion touching `:283-309`, `:316-354`,
`:416`, `:463-464`, `:782-788`, with `extractFrameAttrs` dropping off this path.
**`base` is not dead** and an earlier draft wrongly implied it was: object space
still needs it on both sides (`pos = base + D`, `d = dp - rest`, `multires.cc:491`)
— which is why the deletion list starts at `:463` and excludes `:462`.
`ensureBaseAndFrames` (`:324-342`) survives as an `ensureBase`. `posIsBase` is an
independent memory optimization, unrelated to frames, and survives too (subject to
Decided 5).

**The one genuinely hard piece is masking the solver — and it is not just an
implementation problem.** `solveStencilLeastSquares` (`:686-748`) is Jacobi-CG
sized to the dense coarse vert count — `n = x.size()`, with a comment at
`:680-685` on why that dimension is load-bearing. Restricting the cascade to the
edited support means solving on a subset: index compaction or a masked operator,
with the Jacobi preconditioner *and* the convergence tolerance computed over the
active set.

The subtlety: `AᵀA` couples every coarse vertex reachable through the stencil, so
holding the complement fixed does not truncate the same iteration — **it changes
the minimizer.** A masked solve is a different problem with a different answer,
not an approximation that converges to the unmasked one. So "gate it against the
unmasked solve" is not well-posed as stated; the honest gate is a *tolerance* test
resting on an explicit assumption that influence decays fast enough outside the
dilated support, with the dilation width chosen to make that true. Getting this
wrong produces a solver that silently under-converges rather than one that
crashes. Everything else on the list is mechanical by comparison.

**Two items are new territory rather than new code.** `downRefit` reads the cage
only indirectly, via `ensureChain(level - 1)` (`:277`) — there is no
`gatherVertCo` call in it, as an earlier draft had it. Cascading into the cage
means mutating cage *positions*; `cage_` is already mutated today, but only for
`sculptLayers` / `activeEditLayer` (`:897`, `:917-919`, `:972`, `:987`), so the
"no precedent" point holds for positions specifically, as does the unexamined
interaction with `invalidateAll()` ("cage edited"). And the delta rotation needs a
helper `litestl/math/quat.h` does not have — no axis-angle, no from-two-vectors
constructor — which **must stay transcendental-free** to preserve the
cross-backend bit-parity property `frames.cc:117-122` deliberately buys
(Rodrigues from cross/dot only, no `acos`/`atan2`).

**Tests are a smaller chunk than expected.** An earlier draft claimed much of
`test_multires.cc` asserts frame-space stored values; it does not. Every
`store.elem` use is space-agnostic — value injection, bit-snapshots, zero probes,
eviction round-trips (`:87`, `:141`, `:261`, `:276`, `:434`, `:546`) — and the
substantive assertions are on composed *positions*, which this design preserves by
construction. Most of the 118 `test_assert`s survive unchanged. `test_grids_store.cc`
(250 lines) is space-agnostic and survives entirely. The work here is new gates
(below), not rewriting old ones.

**Total: ~600–900 lines changed or new under `source/subdiv/`** (calibration, not
an estimate — nothing here was attempted), one delicate piece, and three decisions
that must be made before coding: VDM capture, cage-mutation semantics, and how
cage state reaches undo. A substantial change to roughly a quarter of one module —
not a rewrite of the subdiv system. The audit moved the balance slightly: less
test churn than expected, more surface at the seams (four bridge sites, a v1
reject path, a cage undo channel).

### Descope for v1

**Keep the fit objective as plain L2.** The conditioning-aware objective
(max-norm, tangential weighting) turns the normal equations into IRLS or weighted
least squares, and whether it is needed is unknowable until the cascade is
actually draining low frequency. Measure first.

### Suggested phase order

Each step is independently testable, and the delicate piece is isolated:

0. **Decide the fate of the frame-space consumers.** Sculpt layers (channels
   1..N) and `captureDetailToVdm` both assume frame space, and phase 1 breaks
   both the moment it lands. Either convert the layers with channel 0 as one
   change, or disable layers behind a flag for the duration. This is a
   prerequisite, not a parallel track — an earlier draft called phase 1
   self-consistent while leaving channels 1..N in the other space and summing
   them together.
1. **Flip channel 0 (and the layer channels) to object space.** No cascade, no
   delta rotation; finer levels truly left alone. Composition and writeback both
   simplify. Rotation following regresses; accept it here, the model is coherent.
2. **Delta rotation**, restoring rotation following, with the drift gate that its
   accumulating error requires. Independent of the cascade.
3. **Masked solver**, in isolation, gated by a residual-tolerance test over the
   active set plus a dilation-width sweep showing the answer stops moving — *not*
   by convergence to the unmasked solve, which is a different minimizer.
4. **The cascade** — iterate `L → L-1 → … → 1` on the masked solver, still
   stopping above the cage. Nothing at the Blender seam improves yet.
5. **The cage step: cage mutation + cage undo channel + the addon's
   bake-ordering fix, as one landing.** Cage motion without the reordered bake is
   silently absorbed into MDisps (see *Consequences*) and looks like the cascade
   not working; cage motion without an undo channel loses sculpt energy on undo.
   This is where the export benefit finally appears.
6. **Conditioning-aware objective**, only if measurement says so, and only as far
   as reweighting.

## Open questions

1. **Exact-where-possible vs. always least-squares for the downward fit.** This
   decides whether a cage edit is uniquely determined by a fine-level stroke, and
   therefore whether two different strokes producing the same level-2 surface
   leave the same cage. If not, cage state is path-dependent — which matters a
   lot once undo serializes it.
2. **Cascade cadence.** Every stroke end, or cadenced/deferred? Every stroke end
   is the clean invariant; it is also a per-level solve on the hot path.
3. **Twist pinning for the delta rotation.** The rotation between two base
   configurations is unique only modulo twist about the normal; that has to be
   pinned from the surface, deterministically, or it becomes a new ambiguity in
   place of the one being removed.
4. **A cage edited outside the mode.** `invalidateAll()` handles "cage edited"
   today, but under this model the cage *carries sculpt energy* — an external
   cage edit is no longer cleanly separable from sculpted content.
5. **Whether coarse levels should hold positions rather than displacement**
   (Decided 5). A performance question, to be settled by measurement against the
   uniform object-space baseline, not by design preference.
6. **Whether the delta rotation's accumulating orientation error needs a
   periodic re-anchor.** Deltas compose without bound; if the drift gate in
   *Test gates* fails at realistic stroke counts, the fix is presumably an
   occasional re-derivation from geometry — which reintroduces exactly the
   absolute frame this design removes, for one frame in N. Unexamined.

## Test gates that would need to exist

The current gates assume single round trips and one-level strokes. New ones:

- **Cross-level redistribution.** The composed surface at the edited level is
  preserved to tolerance while energy redistributes downward. This replaces "a
  stroke touches one level"; the byte-identical edit-free-switch gate
  (`test_multires.cc:317-320`) still holds and should stay.
- **Residual magnitude.** After a broad edit at a fine level, assert the finest
  level's per-vert `|d|` drops relative to the no-cascade baseline. Note it cannot
  be an absolute bound: absorption is capped by cage-edge wavelength, so a
  relative-improvement assertion is the honest form.
- **Repeated redistribution.** N successive strokes over the same verts, with a
  drift bound. Today's assertions are single round trips at 1e-5.
- **Delta-rotation drift.** Distinct from the above, and the gate the trade-off
  table's `≈ N·ε` column demands: apply a coarse rotation and its inverse N times
  and assert stored disp returns to its start within a bound. Absolute frames pass
  this trivially; composed deltas are the reason it has to exist.
- **Rotation following.** Rotate a limb at a coarse level; assert fine detail
  tracks it (the delta-rotation contract, and the test that distinguishes the
  options in the table above).
- **Cage bake round trip.** Cage motion survives `export_bake` instead of being
  absorbed into MDisps — the ordering trap above, as a test.
- **Cage undo round trip.** A stroke that moves the cage, undone, restores the
  cage exactly — the channel that does not exist yet.
- **Store version rejection.** A v1 blob is refused (or migrated), not silently
  reinterpreted as object space. `grids.cc:477` passes it today.

A frame-90°-image-stability test would have been the right gate for the *current*
design; under this one there is no absolute frame to be unstable, so it is moot
rather than fixed.
