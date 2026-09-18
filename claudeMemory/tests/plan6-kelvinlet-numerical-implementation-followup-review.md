**One concrete numerical bug remains: anisotropic addition can still overflow a representable field.** Review is limited to the supplied packet; no tools or execution.

1. **P1 — Normalized contraction can round above one.**  
   In `kelvinlet.sbrush:86–89`, stabilizing `isotropic` does not protect the subsequent addition.

   Reproducer with cutoff disabled and unit mask/texture:
   ```text
   radius   = 1
   mu       = 1
   nu       = 0.49f
   p        = (0, 0, 0)
   grabFrom = -(4, 3, 2) * 2^-14
   grabTo   = (FLT_MAX, FLT_MAX, FLT_MAX)
   ```

   Under the stated native arithmetic:
   - `dot(scaledR, scaledR) = 29 * 2^-28`.
   - Adding one rounds to `1 + 2^-23`; its square root rounds to `1`.
   - Consequently, `t = 1`, `isotropic = 1`, and normalized force is `(1,1,1)`.
   - The positive anisotropic x contribution is approximately `6.51e-8`, exceeding half an ulp above one.
   - The combined x component rounds to `1 + 2^-23`; restoring `FLT_MAX` produces infinity.

   The original mathematical x displacement is approximately `(1 − 4.24e-8) * FLT_MAX`; all final coordinates are representable. This is an intermediate numerical failure, not an excluded output-range case.

   **Minimal fix:** clamp each component of the combined **normalized** displacement to `[-1,1]` before restoring `forceScale`, then regenerate the native header. This bound is mathematically valid over the declared material domain: the field’s maximum absolute row sum is at most one. It enforces a field bound rather than saturating geometry. Add this reproducer, sign/axis permutations, and neighboring offsets to the finiteness and full-vector oracle checks.

2. **P2 — The overflow regression misses the remaining failure mechanism.**  
   `prepared_unbounded_cases.h:120–147` exercises only a single transverse force component, so the anisotropic contribution vanishes. The main matrix uses at most `FLT_MAX/2`, leaving enough headroom to conceal this overflow.

   **Minimal fix:** include multi-component `FLT_MAX` forces at near-origin, non-axis-aligned offsets. Keep finiteness separate from the error tolerance; a generous absolute tolerance cannot justify infinity.

3. **P2 — Acceptance evidence remains narrower than the plan.**  
   The supplied tests do not establish:
   - Compatibility against the previous float expression at normal working scales.
   - The force-relative displacement tolerance through the actual executor: `:461–462` instead checks final positions against a fixed `3e-6` tolerance.
   - Backend compilation, GPU cutoff behavior, or installed-Blender denormal behavior; those implementations/results are absent.

   **Minimal fix:** add the normal-scale comparison, retain the zero-position probe for measuring displacement accuracy, and explicitly leave backend/DLL acceptance pending until corresponding evidence exists. Do not infer those results from native probe coverage.

The **native cutoff correction looks sound** for validated positive finite cutoffs and finite coordinates: promotion precedes subtraction, and double precision safely accommodates the distances and transition arithmetic.

The **double oracle is independent and algebraically faithful** to the original formula. Its intermediates fit comfortably in binary64 across the accepted binary32 inputs.

Remaining normalization underflow can erase tiny tails, but that is explicitly permitted by the revised absolute-error contract. I found no additional underflow violation of that contract in the supplied code.