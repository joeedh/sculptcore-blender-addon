# Plan — multires tangent frames from the grid parametrization

Implements [design/multires-parametric-frame.md](../design/multires-parametric-frame.md).
Written 2026-07-30 against engine `7979406` ("multires c-api: expose level-count
mutation"). **Phase 1 has landed** (uncommitted in the engine submodule as of
2026-07-30); Phases 2–4 are not started. The production materialization path
still runs the F3 cross-field provider — Phase 1 is dead code plus the gates
that measure the defect.

**The change:** multires stops calling the curvature cross-field frame provider
and derives its per-vertex tangent frame from the grid's own `(u,v)` lattice, so
the ±90° detail flip cannot happen. All work is in the **engine submodule**,
almost entirely in `source/subdiv/multires.cc`. No addon change, no fork change,
no c-api change, no store-format change.

## What was re-validated before planning

Everything the design cites still holds at `7979406`. Four corrections and
additions the design's scope table did not have:

1. **There are three frame-population sites, not two.** The design lists
   `applyDisp` (`multires.cc:225`) and `ensureBaseAndFrames` (`:349`).
   `materialize()` is a third (`:412-420`): on a zero-disp materialization it
   runs `updateFramesAll` on the level mesh and seeds `lp.frameNo`/`lp.frameTa`
   through `extractFrameAttrs` so the level's first writeback pays nothing. It
   must be converted with the other two or the cache holds mixed-space frames.
   `captureDetailToVdm` (`:595-596`) is a fourth `updateFramesAll` call, but it
   refreshes the *slot mesh's* provider attrs for VDM consumers and stays.

2. **The canonical-owning-grid table already exists in the tree.**
   `levelVertGridCoordsOut` (`:1179-1204`) is exactly the design's proposed
   pass: `{grid, latticeU, latticeV}` per fine vert, first writer wins, `-1`
   for a vert in no grid. It is public, bound, and feeds the X3 GPU finalize
   kernel's VDM sampling coordinate. So the ~15 new lines are **zero new lines**
   plus a refactor — and factoring it into a shared private helper buys a real
   property: the CPU frame and the GPU kernel's sampling coordinate derive from
   the same canonical grid *by construction* rather than by two independent
   loops that happen to agree.

3. **Dropping the provider from `ensureChain` removes a whole temp mesh, not
   just a call.** `ensureChain` builds `buildLevelTopo(l)` (`:290`) — G·S²
   `make_face` calls — sets `co`, runs `recalc_normals()`, and deletes it
   (`:302`), *solely* to have something to run the frame provider on. With
   parametric frames that mesh has no reason to exist. The saving is larger than
   the design's "net simpler" estimate.

4. **`test_multires.cc:317-320` is the edit-free-writeback byte-identity gate**
   (materialize → `writeback` returns 0 → `storeBlob` unchanged), not a
   dedicated replica test. It is still the right gate to cite: it is what breaks
   first if replicas of a border vertex stop receiving identical values. There
   is no separate replica test today; Phase 1 adds one.

Also confirmed: no brush kernel reads `FRAME_*_ATTR` (the VDM trio and
`debug/script.cc:1012` are the only non-multires consumers); nothing in the
addon touches frames; `captureDetailToVdm` has **no test coverage** and exactly
one caller (`subdiv_c_api.cc:212`).

## Locked decisions

- **Canonical grid, per vertex id — not per grid, not averaged.** The frame need
  only be deterministic, ambiguity-free, and rotating with the surface; it does
  not need to be geometrically meaningful. Per-grid frames would also be correct
  but would break replica bit-equality for no gain, and averaging tangent
  directions cancels at a valence-4 vertex.
- **Reuse the existing first-writer-wins rule** (`levelVertGridCoordsOut`)
  rather than inventing a second canonical-grid convention.
- **Arithmetic stays `+ - * / sqrt`,** written out explicitly with the same
  `float3` ops already on the composition path (`applyDisp` `:252-257`). No
  Eigen, no `litestl/math/quat.h` (abandoned scaffolding — see the predecessor's
  postmortem). This preserves cross-backend bit parity without depending on
  `frames.cc:117-122` to preserve it.
- **`frames.cc` is not touched.** It keeps serving VDM and brush consumers
  unchanged.
- **Keep the `lp.frameNo`/`lp.frameTa` cache** for now (design open question 4).
  Recomputing on demand is attractive once frames are this cheap, but it changes
  the `storeDispFromPositions` contract and is a separable follow-up; measure
  in Phase 4, decide after.
- **Parametric normal, not the provider's smoothed normal** (design open
  question 1) — `n = normalize(du × dv)`. This is what makes the path fully
  self-contained and lets `updateFramesAll` leave multires entirely. It is a
  quality question, not a correctness one; Phase 4 measures it.

## The frame

Per level, per grid vertex, from that level's `base` positions and the vertex's
canonical `(g, u, v)`:

```
du = base[gv[v*w + u+1]] - base[gv[v*w + u-1]]      (one-sided at u = 0 or S)
dv = base[gv[(v+1)*w + u]] - base[gv[(v-1)*w + u]]  (one-sided at v = 0 or S)
n  = normalize(du × dv)
t  = normalize(du - n * (du·n))
b  = n × t                                          (as today, at the use site)
```

Central differences interior, one-sided on the two lattice borders. The design's
open question 2 (one-sided everywhere for uniformity) is answered **no**: the
border case is needed regardless, and central differences are better
conditioned where they are available.

### Degenerate ladder

Must be a pure function of the inputs — no iteration-order or
previous-value dependence. In order:

1. `du × dv` below `EPS` (collapsed cell): retry with the diagonal differences
   `base[gv[(v+1)*w+u+1]] - base[gv[(v-1)*w+u-1]]` and the anti-diagonal,
   clamped to the lattice the same way.
2. Still degenerate: take `n` from the Newell normal of the canonical grid's
   incident cell corners.
3. `t` degenerate after Gram-Schmidt (`du ∥ n`): mirror `frames.cc:338-341`
   exactly — `X = |n[0]| < 0.9 ? (1,0,0) : (0,1,0)`, then project onto the
   tangent plane and normalize.

Step 3 is the only rung that stops rotating with the surface, and it is reached
only when the lattice itself is degenerate at that point.

## Phases

Each phase leaves the tree correct and shippable.

### Phase 1 — the helper and the gates, no behaviour change — **DONE**

Landed 2026-07-30. **The rest of this section is the plan as written** — what
actually landed differs in three named places, all recorded under *Phase 1
outcome* below. Phase 2 onward refer to the landed names, not these.

Add, all private in `multires.cc` / `multires.h`:

- `void levelVertGridCoords(int level, Vector<int> &out)` — the loop currently
  inlined in `levelVertGridCoordsOut` (`:1179-1204`), which becomes a one-line
  forwarder. Nothing else changes about the bound method or its output.
- `struct GridFrame { float3 n, t; }` and
  `GridFrame gridFrame(const SubdivLevel &lvl, const Vector<float3> &base, const int *gv, int g, int u, int v)`
  — the finite differences, Gram-Schmidt and the degenerate ladder above.
- `void computeParametricFrames(int level, const Vector<float3> &base, Vector<float3> &no, Vector<float3> &ta)`
  — the canonical table plus a pass calling `gridFrame`, filling the same dense
  per-vert-id layout `extractFrameAttrs` produces today.

New gates in `tests/test_multires.cc`, each a `gate*()` called from `main()`:

- **`gateFrameStability`** — the regression test for the defect. Materialize a
  fine level, snapshot the parametric tangents, move one cage vertex by a small
  delta, rebuild, and assert every tangent's dot product with its predecessor
  stays above a threshold (no 90° jump). **Assert the same test fails on the
  provider frames** so the gate is demonstrably measuring the right thing —
  compute both in this phase and compare; this is the A/B the design asks for.
- **`gateFrameDeterminism`** — build the same level's frames twice from the same
  base; bit-identical (`sameBits`, `test_multires.cc:56`).
- **`gateFrameReplicas`** — for every vert appearing in more than one grid,
  assert one frame value is used (trivially true given per-vid storage, but it
  pins the invariant against a later per-grid "optimization"), and that
  `test_multires.cc:317-320`'s byte-identity still holds.
- **`gateFrameRoundTrip`** — `d = frameᵀ·dp` then `dp' = frame·d` to float
  tolerance, exercised at interior, edge-border and extraordinary (`gateFan`'s
  cage) vertices.
- **`gateFrameDegenerate`** — a cage collapsed so a grid cell is zero-area:
  no NaN, and the same fallback on repeat.

Exit: new gates pass; every existing gate untouched and passing; no production
code path changed.

### Phase 1 outcome

**The defect reproduces, and harder than the design predicted.** On
`createCube(2)` at level 3, nudging one cage vertex by `(0.01, 0.007, 0.013)`:

| frame source | worst tangent dot before/after |
|---|---|
| parametric | **0.999970** |
| F3 cross-field provider | **−0.999962** |

−1.0 is a full **180° reversal**, not the 90° image the design anticipated. Both
are discrete failures with the same consequence — `b = n × t` reverses with `t`,
so unchanged stored disp decodes with its two tangential components negated,
mirroring detail through the normal in one step. The design's diagnosis is
confirmed on the plainest possible cage.

What landed differs from the plan in three places:

- **Public `Multires::parametricFrames(level, base, no, ta)`**, not a private
  helper — Phase 1 is dead code plus tests, and the tests need an entry point.
  It stays public after Phase 2 (harmless, and it is the natural test seam).
- **`gridFrame` / `cellNewellNormal` / `buildVertGridCoords` are file-static**
  in `multires.cc`, so the header gained one declaration rather than four.
  `levelVertGridCoordsOut` now forwards to `buildVertGridCoords`, which is the
  shared-canonical-grid property the plan wanted.
- **Four gates, not five.** Determinism, orthonormality, the canonical-grid
  rule, and the encode/decode round trip are all per-base invariants, so they
  live in one `checkFrames()` helper that the other gates reuse — including
  `gateFrameDegenerate`, which is how "same fallback on repeat" is asserted
  without a second code path. Gates: `gateParametricFrames` (cube levels 1–3 +
  a fan cage for extraordinary verts), `gateFrameDegenerate` (fully collapsed
  base, then one pinched cell), `gateFrameStability` (the A/B above).

The stability gate asserts `parametricWorst > 0.9` on both tangent and normal,
and `providerWorst <= parametricWorst` — a *relative* assert, deliberately, so a
future improvement to `frames.cc` cannot fail the suite spuriously. The absolute
numbers are printed and recorded in the gate's comment.

Suite: `test_multires` fully green. Full ctest is **118/122**; the four failures
(`test_live_stroke`, `test_bsmooth`, `test_automask_gpu`,
`test_spatial_boundary_normals`) are all pre-existing — verified by stashing the
change, rebuilding, and reproducing `test_spatial_boundary_normals`' failure
with byte-identical output. That matches the recorded local baseline (the first
three are a WGSL-backend configure gap and a GPU numeric diff; the fourth is
upstream).

### Phase 2 — switch the frame source

The entry point is the one Phase 1 landed:
`Multires::parametricFrames(level, base, no, ta)` (`multires.h:239`). Line
numbers below are pre-Phase-1 and have shifted by roughly +150 in
`multires.cc`.

- `applyDisp` (`:215-262`): drop the `mesh::Mesh *baseMesh` parameter,
  `updateFramesAll`, and the two attr lookups. Take `const Vector<float3> &no,
  &ta` instead and read them as it reads `(*no)[vid]` today.
- `ensureChain` (`:287-302`): delete the `buildLevelTopo` / `co` fill /
  `recalc_normals` / `alloc::Delete` block. Compute `lp.frameNo`/`lp.frameTa`
  with `parametricFrames(l, base, ...)` **before** `applyDisp`, then call
  `applyDisp` with them. Set `lp.framesValid = true` as today.
- `ensureBaseAndFrames` (`:343-352`): same removal — temp mesh, `recalc_normals`,
  `updateFramesAll`, `extractFrameAttrs` all go; one
  `parametricFrames(level, lp.base, ...)` replaces them.
- `materialize` (`:412-420`): replace the `updateFramesAll` +
  `extractFrameAttrs` pair with `parametricFrames(level, lp.pos, ...)`
  (`lp.pos == base` on this branch, which is the branch's precondition).
- Delete `extractFrameAttrs` (`:191-209`) — now unreferenced.
- **Gate `captureDetailToVdm` for the duration of this phase**: extend the
  existing `mix.size() > 1` refusal (`:518-527`) to an unconditional early
  `return 0` with a `CLAUDENOTE:` marker naming Phase 3. This is the one
  correction to the design's suggested order — it lists capture conversion
  *after* the switch, which leaves a window where multires `d` is parametric-
  frame while capture treats it as provider-frame. Refusing is a correct,
  visible no-op; producing wrong texels is not.
- Update the `multires.h:5-18` header comment and the `LevelPos` comment
  (`:279-285`), both of which name "the F3 frame provider".

Expect **no test diffs**: every `store.elem` assertion in `test_multires.cc` is
space-agnostic (`storeBlob` compares the store against itself across
operations, never against literals). If a gate fails here it is a real
regression, not a rebaseline.

Exit: full `test_multires` green; `test_frame_provider` untouched and green;
`gateFrameStability`'s A/B now shows the production path taking the stable
branch.

### Phase 3 — convert `captureDetailToVdm`

Capture moves multires `d` into Ptex texels that VDM consumers
(`vdm_bake.cc:54-56`, `vdm_promote.cc:52-54`, `vdm_splat.cc:84-86`) read back
through the *provider* frame. After Phase 2 those two frames differ, so capture
must convert.

Convert **at the lattice corners, before the bilinear blend** (`:559-567`):
for each of the four `store.elem` reads, decode with the parametric frame at
that vertex into object space and re-encode with the provider frame at the same
vertex, then bilerp exactly as today. Bilinear interpolation of frame-space
vectors is already an approximation on this path, so converting at corners
keeps the current accuracy class and changes nothing structurally.

Provider frames for the level's base are needed here, which means capture
rebuilds the temp level mesh + `updateFramesAll` that Phase 2 removed from the
hot paths. That is acceptable: capture is a rare, explicit operation, and the
code already reconstructs `base` at `:532-541`.

Remove the Phase 2 refusal and its `CLAUDENOTE:`. Add the first test coverage
this function has ever had: a `gateCapture` that captures a known displacement
and asserts the resulting VDM texels reproduce the pre-capture surface when
splatted back.

Exit: `gateCapture` passes; the refusal is gone.

### Phase 4 — measure, then decide the open questions

Nothing here is required to ship; all three are measurements the design asks for
and none should gate Phases 1–3.

- **Parametrization skew** on a production-shaped cage: the distribution of
  `|du·dv| / (|du||dv|)` per level. This is the failure mode conditioning moves
  *to*, and it is Blender's failure mode too — bounded and continuous, but it
  should be measured rather than assumed benign.
- **lz4 chunk ratio** before/after (design open question 3). The parametric
  tangent field is discontinuous across grid borders; if that measurably hurts
  the X5 eviction path's compression, per-grid frames become worth revisiting
  despite losing replica bit-equality.
- **Provider vs parametric normal** (open question 1) on coarse levels, and
  **whether to cache frames at all** (open question 4) now that they cost a
  subtract and a cross product. `bench()` (`test_multires.cc:885`) is the
  harness for the latter.

Record the results back into the design doc's open-questions section.

## Ordering and gates

| Phase | Files | Ships alone | Blocking gate |
|---|---|---|---|
| 1 ✅ | `multires.{cc,h}`, `tests/test_multires.cc` | yes (dead code + tests) | `gateFrameStability` fails on provider frames, passes on parametric |
| 2 | `multires.{cc,h}` | yes | full `test_multires` green with no rebaselining |
| 3 | `multires.cc`, `tests/test_multires.cc` | yes | `gateCapture` |
| 4 | none (measurement) | n/a | none |

Run with `node make.mjs test test_multires` from `engine/` (native build dir;
see `engine/CLAUDE.md`) — and `node make.mjs build native` **first**: `test`
runs the existing binaries and will happily re-run a stale one. The local full
ctest baseline is 118/122; the four expected failures are `test_live_stroke`,
`test_bsmooth`, `test_automask_gpu` and `test_spatial_boundary_normals`. Match
the names, not the count.

## Risks

- **The temp-mesh removal is the largest behavioural delta in Phase 2**, because
  `recalc_normals()` on that mesh was also the only thing normalizing the base
  before the provider saw it. Nothing downstream reads those normals — the mesh
  was deleted immediately — but `materialize`'s level mesh (`:409`) still calls
  `recalc_normals()` and must keep doing so; it feeds draw and spatial.
- **A stale `lp.framesValid`** is now cheaper to be wrong about, not safer.
  The invalidation rules (`invalidateAbove`, `invalidateAll`, `LevelPos::reset`)
  are unchanged and still load-bearing.
- **Phase 3's conversion is the only place two frame spaces coexist.** If it
  proves harder than it reads, the honest fallback is to leave capture refusing
  and file it — VDM capture is post-V2 territory and has no test coverage or
  addon caller today.
- **Skew could be worse than the cross field somewhere.** The design concedes
  this is unmeasured. It would not invalidate the change (a continuous failure
  beats a discrete one), but Phase 4 should run before anyone claims the frame
  is strictly better.

## Not in scope

Restated from the design so it does not drift: storage format and
`kGridsFormatVersion`, composition/`ensureChain` structure, the cage,
`downRefit`, undo, the Blender seam and `export_bake`, sculpt layers, and the
addon. The lever arm `∂pos/∂(frame rotation) ≈ |d|` survives this change; a
regularized joint multilevel solve remains a separate, non-urgent project.
