# Plan 6: Kelvinlet numerical correction for prepared unbounded execution

Status: completed 2026-09-18, including initial, implementation/follow-up and
host floating-mode review corrections. Expanded native/DLL acceptance and installed
runtime checks passed in the [unbounded gate](../tests/plan6-unbounded-gate.json).

## Review dispositions — 2026-09-18

Both [numerical](../tests/plan6-kelvinlet-numerical-review.md) and
[compatibility](../tests/plan6-kelvinlet-compatibility-review.md) reviews are received.
The following corrections supersede shorthand in the proposal below:

- Correct the cutoff itself. Native CPU computes distance with double
  intermediates (promote before subtraction), then the window against the
  validated float cutoff. GPU helpers need a scaled norm and actual backend
  validation. Explicitly include the 2^-80 outside-window and 2^80 inside-window
  counterexamples with differing field/window centers.
- Force normalization precedes contraction: divide grabTo by its largest
  absolute component, contract that bounded vector, then multiply the result by
  the force scale. A zero force skips execution. This closes representable-output
  overflow for large finite deltas; it does not saturate genuinely unrepresentable
  final positions.
- Use nested two-argument max calls, as required by the DSL. The sum of the four
  squared normalized components is at most four, so e remains in [1,2].
- Use the existing vertex-stage `continue`; this intentionally omits affected
  bookkeeping and coordinate writeback for zero cutoff or zero radius/force.
  Test mixed/excluded nodes and undo, and bypass texture evaluation on exclusion.
- Preserve the host/reduce bodies. Test identical effective inputs in their
  declared domain; do not claim parity for already-differing out-of-domain raw
  CPU/GPU material sanitization.
- Accuracy is a displacement norm tolerance of 4e-6 times the largest force
  component, plus 8 binary32 denormal units. Finiteness is a separate requirement.
  Subnormal tails that underflow during normalization may become zero within
  that absolute error bound; explicitly test the review's 2^-127 radius / 2^24
  transverse force example. This is not an exact-subnormal-tail guarantee.
- Actual native vector division is component-wise scalar division
  (`litestl/math/vector.h`, VEC_OP_DEF), and the native clang toolchain disables
  FMA contraction without enabling fast math. Test the minimum accepted radius,
  2^-126 and 2^-127 at the origin in native and installed Blender execution.
  Handle the exact field origin without dividing by a possibly flushed half-
  radius. GPU denormal behavior remains an explicit backend accuracy limit;
  test finite output instead of promising native bitwise equality there.
- To avoid introducing a half-radius underflow for ordinary offsets, initially
  subtract unscaled positions and halve/recompute only when the maximum offset
  exceeds 1e30 (including a temporary overflow to infinity). Exact zero offset
  returns the force directly. The recomputed offset is finite for all finite
  endpoints; tiny normalized far tails retain the absolute accuracy contract.
- Prepared admission still depends on parent-plan vector checks, independent
  extent snapshots and product/transition preflight before validateOnly/mutation.
  The correction does not expand the shared-state certificate into a general
  arbitrary-kernel numerical proof.

## Problem and intended correction

The implementation review found an additional rounding overflow at nearly zero
offset with transverse FLT_MAX force, mu = 1 - 6 * 2^-24, and nu = 0. Computing
the isotropic coefficient by summing the original numerator rounded it above
one. Use `t * (originGain - (0.5*a/norm)*(1-t*t))`, with
`originGain = (1.5*a-b)/norm`. This retains the raw normalizer floor and has an
exact unit coefficient at the accepted field origin. Add the reported case,
axis permutations, neighboring distances and full-vector error checks. Also
test the smallest accepted radius, opposing FLT_MAX endpoints, cutoff transition
neighbors and texture-evaluation counters on skipped vertices.

The follow-up numerical review found that the anisotropic addition can also
round above one for multi-component FLT_MAX forces. Bound the normalized result
component-wise before restoring force scale. For unit direction n, the maximum
absolute row sum of n*n^T is (1 + sqrt(3))/2. With beta = b/a in [0.25, 0.5),
the field's row sum is bounded by t * (1 + C*(1-t*t)), where
C = (beta*(1+sqrt(3))/2 - 0.5)/(1.5-beta) < 0.184 < 0.5. This bound is at most
one for t in [0,1]. Enforcing it corrects rounding excursions without clipping
mathematically larger displacements in the declared material domain.

### Host denormal observation and reviewed disposition

The development Blender probe on 2026-09-18 found that its thread flushes
binary32 subnormals to zero even during Python struct unpacking and reflected
Brush writes. Constructing the input as a normal binary64 number distinguishes
that host conversion from kernel arithmetic: 2^-127 arrives in Brush.radius as
zero; 2^-126 and ordinary radii arrive intact and produce the correct origin
displacement. Native tests under the launcher's default IEEE environment pass
the smaller radius. Do not report the planned installed-denormal gate as passed
or silently change the host floating-point mode. Evidence:
../tests/plan6-kelvinlet-denormal-probe.json.

Fresh contract and compatibility reviews agree: preserve legacy reflected float
transport, but reject nonzero values lost within checked double transport or
prepared preflight. In particular a positive inherited subnormal extent must
never become disabled cutoff because a floating comparison treated it as zero.
Use binary32 representation checks before comparisons/promotion, and reject
subnormal scalar values when the caller flushes inputs or arithmetic results.
Checked conversion may retain ordinary IEEE rounding below half a denormal unit;
it must reject a representable nonzero result flushed to zero. Apply this to the
Brush checked write, program override conversion, prepared scalar bases and
unbounded radius/extent/frame validation. Preserve the caller's floating mode.
Test IEEE acceptance natively, explicit FTZ/DAZ rejection and atomicity natively,
and real Blender checked-double rejection and inherited-bit preflight. Reflected
values already delivered as zero retain zero-radius behavior; record that as a
transport limitation rather than claiming subnormal field execution.

The present expression computes radius squared and inverse distance cubed before
normalizing the result. Valid tiny/large radii overflow or underflow those
intermediates, including at the field origin. Selecting all leaves also evaluates
that expression outside the cutoff, where multiplying NaN by zero cannot help.

Keep the DSL as the single implementation for every backend and preserve the
mathematical field. Replace the intermediates with dimensionless ratios:

1. Compute cutoff first and continue on zero, before field or texture evaluation.
2. Initially subtract unscaled coordinates. Only when the largest offset exceeds
   1e30, use `r = 0.5 * co - 0.5 * grabFrom`, `eps = 0.5 * radius`.
   Halving before subtraction prevents overflow for opposite finite endpoints.
3. Set `scale = max(abs(r.x), abs(r.y), abs(r.z), eps)`, divide r and eps by
   scale, then `e = sqrt(dot(r_scaled,r_scaled) + eps_scaled*eps_scaled)`.
   For positive accepted radius, scale is positive and the largest input to
   the square root is 1; e is between 1 and 2. The existing finite reciprocal
   radius check excludes values whose half is zero. Zero radius skips execution.
4. `q = r_scaled/e`, `t = eps_scaled/e`, and
   `norm = max(1.5*a-b, 1e-6)` retain the original material coefficients.
   Compute `isotropic = t*(originGain-(0.5*a/norm)*(1-t*t))` and
   `anisotropic = b/norm*t`. Then
   normalize grabTo by its maximum absolute component before contraction, then
   restore that scale after combining the two terms.
   This is algebraically the existing normalized field with no radius square,
   inverse cube, or large/small radius multiplier at the end.
5. Multiply by the existing mask, cutoff and texture gain, and write the position.
   This correction retains existing mask/texture semantics and their numerical
   assumptions; a scalar eligibility certificate does not certify arbitrary DSL
   code, arbitrary procedural textures or corrupt input geometry as finite.
   Preflight grabFrom/grabTo finiteness in prepared unbounded execution, alongside
   extent/cutoff/transition-width validation. Do not invent an artist-facing
   radius restriction or saturate geometry.

## Numerical contract and tests

This fixes numerical failures caused by accepted scalar radius and mu/nu values,
on finite ordinary geometry and stroke deltas. It does not extend the engine's
existing coordinate/output representability contract: mathematically
unrepresentable output, malformed geometry, and overflowing user texture programs
remain outside that contract. Reviewers should distinguish those existing limits
from new intermediate overflow in the kernel itself.

- Independent double-precision reference for the original mathematical formula
  across logarithmic radius scales, material endpoints, origin/near-origin/far
  points and differing field/window centers. Test tiny/large accepted radii with
  disabled cutoff and positive cutoff; explicit zero window must bypass the field.
- Normal working-scale output matches the previous expression within justified
  float tolerance; no baseline overwrite. Record the expected rounding change.
- Compile every existing emitted backend and run applicable existing numerical
  shader/kernel gates. The prepared path remains native CPU; raw CPU/GPU share
  the corrected DSL expression.
- Retain command-wide atomic configuration rejection, zero-count validation,
  independent material dynamics, extent snapshots, cavity support and undo tests
  from the parent unbounded plan. No anchored completion claim.
