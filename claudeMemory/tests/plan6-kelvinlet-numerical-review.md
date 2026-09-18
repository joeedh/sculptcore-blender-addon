**Verdict: do not admit the plan as written.** The dimensionless field is algebraically correct, but the supplied cutoff still fails at accepted radius scales, and the underflow assumptions need explicit tests and limits. This is a packet-only numerical review.

1. **Concrete blocker: moving the cutoff first does not make it numerically safe.**

   `brush_command.h:361–367` still computes distance using an unscaled length. Validating `R` and `0.2R` cannot prevent distance-square underflow or overflow.

   A particularly strong counterexample uses differing field/window centers:

   - `radius = 2^-80`, extent `1`;
   - vertex and `grabFrom` at zero;
   - `surfacePos = (2*radius, 0, 0)`;
   - `grabTo = (0, 1, 0)`, identity masks/texture.

   The correct window is zero. In float, the squared distance `2^-158` rounds to zero, so the supplied window returns **one**. The corrected field then applies approximately the full unit displacement at its origin.

   Conversely, `radius = 2^80`, extent `1`, and distance `radius/2` produce an overflowing squared distance: the window returns zero where it should be one. All cutoff scalar intermediates remain finite.

   **Minimal correction:** include a scaled cutoff-distance calculation in the obligation, with safe coordinate subtraction and explicit outside-window handling. Early exit must use that corrected window. If the parent plan already supplies this, admission must explicitly depend on it; its implementation is absent here.

2. **Concrete numerical gap: bounded normalized values can underflow before a later multiplication rescues the result.**

   Plan lines 19–28 protect against overflow in the norm, but do not preserve arbitrarily small `t`.

   Under gradual underflow, take:

   ```
   radius   = 2^-127
   co       = (2^24, 0, 0)
   grabFrom = (0, 0, 0)
   grabTo   = (0, 2^24, 0)
   mu = 1, nu = 0
   cutoff disabled
   ```

   This radius passes the supplied reciprocal check: its reciprocal is `2^127`. But `eps/scale = 2^-151` rounds to zero. The proposed displacement is zero, whereas the mathematical y displacement is approximately `0.6 * 2^-127`, a representable subnormal. Adding it to the zero y coordinate preserves it.

   This is **intermediate underflow, not unrepresentable output**. Whether these coordinate/stroke magnitudes qualify as “ordinary” is undefined in plan lines 41–46.

   **Minimal correction:** specify the accuracy contract for these tails and add this regression. If preservation is required, use an exponent-aware or wider-intermediate fallback; merely reordering the final multiplication cannot recover an already-zero `t`.

3. **Admission blocker: the origin proof depends on arithmetic semantics that the packet does not establish.**

   The claim that the reciprocal check excludes a zero half-radius is sound with gradual underflow. It is insufficient with flush-to-zero arithmetic: an accepted normal radius `2^-126` has a subnormal half. Flushing that half makes `scale` zero at the origin.

   Also, vector division must implement the intended division safely. If `r/scale` lowers to multiplication by `1/scale`, an origin case with `radius = 2^-127` creates the overflowing reciprocal `2^128`, despite the accepted radius reciprocal being finite.

   The packet does not include vector division implementation or relevant compiler modes, so these are **unresolved admission conditions**, not demonstrated backend failures.

   **Minimal correction:** test the minimum accepted radii at the origin under actual backend arithmetic modes, and inspect division lowering. Preserve the accepted radius domain rather than silently imposing a new floor.

The underlying algebra otherwise checks out. Writing `d = co−grabFrom`, `E = sqrt(dot(d,d)+radius²)`, the proposed quantities satisfy `q=d/E` and `t=radius/E` in exact arithmetic. Substitution reproduces the existing normalized field, including its normalizer clamp.

For prepared material bounds, let `k=b/a`. Then `k` lies approximately in `[0.25, 0.499002]`, so neither `a−b` nor `1.5a−b` suffers severe cancellation. The normalizer is at least approximately `0.00625`, comfortably above its floor. At the origin, `q=0`, `t=1`, and the displacement equals `grabTo` mathematically. Expect small rounding differences because the numerator and normalizer use different evaluation orders.

There is also a wording error at plan lines 21–22: each squared contribution is at most one, but their **sum** can reach four. The stated bound `1 ≤ e ≤ 2` is correct.

**Separate scope issue:** finite `grabTo` alone does not bound `dot(grabTo,q)` safely. With radius one, `d=(1,1,1)`, and each force component `0.75*FLT_MAX`, `q=(0.5,0.5,0.5)` and the dot overflows. For `nu=0`, the exact displacement components are only `0.31875*FLT_MAX`. This lies outside a reasonable “ordinary stroke delta” scope, but it cannot be dismissed as unrepresentable output. Either define that scope or scale the force before contraction. Arbitrary texture overflow and genuinely unrepresentable final coordinates remain existing engine limits.

Before admission, make the reference tests concrete:

- Evaluate the **original formula entirely in double**, promoting inputs before subtraction or multiplication. Binary32 endpoint powers here fit comfortably in double; do not copy the proposed normalization into the oracle.
- Independently evaluate the cutoff in double, including the two counterexamples above and distinct field/window centers.
- Cover accepted-radius boundaries, normal/subnormal transitions, all material corners, origin, and forces parallel/perpendicular to the offset.
- Check displacement and final coordinates separately; coordinate rounding can conceal displacement errors.
- Use a justified mixed error bound, with explicit subnormal-tail expectations. Require finiteness independently of approximate agreement.
- Verify zero-window execution bypasses texture evaluation, not merely that the final position happens to match.

Optional refinements include analytic symmetry/linearity checks and correcting the source comment at `kelvinlet.sbrush:38`: `4*(1−nu)` approaches **two**, not zero, as `nu` approaches `0.5`. Neither requires changing the material model.