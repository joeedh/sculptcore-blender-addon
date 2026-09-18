**One confirmed kernel bug remains: finite, representable output can still become infinity.** The native tests also enforce a weaker accuracy condition than the plan specifies. This review uses only the supplied packet; nothing was executed.

1. **High — coefficient rounding defeats the force-normalization overflow fix.**  
   In `kelvinlet.sbrush:83–87`, the numerator `(a-b)+0.5*a*t*t` and denominator `1.5*a-b` round differently. Even when `t == 1`, `isotropic` can exceed one.

   A concrete native binary32 case, assuming the stated component-wise division and disabled FMA contraction:

   ```text
   u        = 2^-24
   mu       = 1 - 6*u
   nu       = 0
   radius   = 1
   p        = (0, 0, 0)
   grabFrom = (-2^-20, 0, 0)
   grabTo   = (0, FLT_MAX, 0)
   extent   = 0
   mask     = 0; texture gain = 1; automasks disabled
   ```

   The reduced coefficient is `a = 0.5 + 3*u`. The squared offset disappears when added to one, giving `e == t == 1`. Float evaluation then produces:

   ```text
   norm                = 0.625 + 3*u
   isotropic numerator = 0.625 + 4*u
   isotropic           = 1 + 2^-23
   ```

   The force is transverse, so the anisotropic contribution is zero. Restoring `forceScale` overflows the Y displacement to infinity. The original mathematical field attenuates this transverse force slightly below `FLT_MAX`; both displacement and final position are representable.

   **Minimal correction:** in the declared material domain, where the normalization floor is inactive, rewrite the isotropic coefficient around its exact origin identity:

   ```text
   isotropic = t * (1.0 - (0.5*a/norm) * (1.0 - t*t));
   ```

   Add this exact regression with a separate finiteness assertion. Also check nearby offsets and force orientations at `FLT_MAX` before claiming the rounded contraction is bounded. The existing `FLT_MAX * 0.5` tests leave enough headroom to hide this failure.

2. **Medium — the native numerical test does not enforce the promised displacement-norm tolerance.**  
   `prepared_unbounded_cases.h:107–112` allows each component an error of `T = 4e-6*forceScale + 8*denorm_min`. That permits Euclidean displacement error up to `sqrt(3)*T`, contrary to plan lines 30–34.

   **Minimal correction:** retain component finiteness checks, then compute the three errors in double and assert:

   ```text
   hypot(errorX, errorY, errorZ) <= T
   ```

   Keep this field-displacement check at zero position, as the probe currently intends. Final-coordinate rounding at nonzero positions needs a separately stated allowance.

3. **Medium — several explicitly required numerical boundaries remain untested.**  
   The supplied native matrix omits:

   - **Minimum accepted radius.** `2^-127` is not the minimum. Under gradual binary32 arithmetic, test `nextafter(2^-128, +infinity)` and rejection of `2^-128`.
   - **Overflowing initial subtraction.** All numerical probes use zero position, so they never exercise opposite finite endpoints whose initial difference overflows. Add `p.x = FLT_MAX`, `grabFrom.x = -FLT_MAX`, with a transverse force, and compare the transverse output with the oracle.
   - **Cutoff transition accuracy at extreme scales.** Distances `.5R`, `R`, and `2R` only exercise plateau/endpoints. Add `.9R` and representable neighbors around `.8R` and `R`, retaining different field/window centers.
   - **Zero-force/radius exclusion and texture bypass.** The generated `continue` placement is correct by inspection, but these branches lack direct probe coverage. Use a counting texture evaluator and assert no calls, writes, affected entries, or update flag.

   These are small additions to the existing probe, not a reason to broaden the executor review.

The **original-formula double oracle is suitably independent**: it promotes before subtraction and products, retains the original radius-squared/inverse-cube expression, and has sufficient exponent range for accepted binary32 inputs. The native cutoff likewise correctly promotes before subtraction and computes against the float cutoff product; I found no additional numerical defect there for finite centers and validated inputs.

The normalization underflow concession is also coherent with the stated **absolute** tolerance. The `2^-127` radius, `2^24` transverse-force example is present; losing that tiny tail is not itself a contract violation.

GPU cutoff implementations, generated GPU kernels, installed-Blender results, and backend execution evidence are absent from this packet. Their required validation remains unestablished, rather than demonstrated defective.