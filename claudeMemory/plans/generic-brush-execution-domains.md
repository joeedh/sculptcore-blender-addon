# Plan 6B: typed semantic evaluation and unit conversion

Reviewed independently for numerical correctness and integration seams, 2026-09-18.
The user approved CLI use for all remaining reviews. Both fixed-source reviews
completed and their shared typed-range blocker is resolved below before implementation.
[Numerical findings](../tests/plan6-domains-numerics-review.md),
[integration findings](../tests/plan6-domains-integration-review.md).
The immutable authoring snapshot prerequisite is complete. This slice supplies
the evaluated scalar boundary needed by host consumers and validates it against
the actual native evaluator before wiring modal consumers. It does not complete
Plan 6, activate authoring execution capabilities, or change the default path.

Bounded gate completed 2026-09-18:
[verified manifest](../tests/plan6-domains-gate.json). All 543 actual native
comparisons pass (FLOAT32 bitwise, INT32/BOOL exact), six independent pure tests
pass, and six Blender groups include 800 warm evaluations without new bakes.
The normal addon-only native configuration is restored. Installed Python source
matches the tested evaluator. Modal/batch/UI adoption remains open.

## Concrete implementation

1. Add a DLL-independent evaluator over immutable PropertySnapshot values and
   prepared ExecutionLayers. Input is four positional optional device channels
   in PRESSURE/TILT_X/TILT_Y/SPEED order. Quantize finite samples to FLOAT32 to
   match the native transport; absent/nonfinite samples are missing. Reject
   malformed channels, including bool. Clamp response inputs to [0,1].
2. Reproduce native ordered-stack arithmetic: FLOAT32 rounds each arithmetic
   operation; INT32/BOOL use FLOAT64 and convert only after all layers. Table
   interpolation uses the respective arithmetic width. Analytic thresholds
   remain double and compare against the transported FLOAT32 input. Disabled
   layers and missing inputs skip; a nonfinite response, combination or result
   retains the prior layer value. Preserve the native intermediate-overflow
   behavior (including factor-zero cases). Clamp to the effective native/declared
   domain and storage range, then ties-away INT32 or BOOL >= .5. Do not mutate
   authored values or cached tables. Never sample/hash curves during evaluation.
   Canonicalize the captured value_domain, not the semantic Definition: intersect
   storage bounds, INT32 ceil/floor endpoints, BOOL permitted 0/1 endpoints, and
   FLOAT32 endpoints rounded inward to representable values. Reject empty domains.
   This makes the contract's clamp-before-conversion operate on admissible stored
   values. Native domains already represented by RNA floats keep their exact limits.
3. Expose semantic evaluation separately from engine unit conversion. Native
   spacing evaluates as INT32 percent and rounds before division by 100. Snake
   pinch evaluates in its native FLOAT32 [0,1] domain before 2*(.5-value).
   Strength applies dynamics in its native domain before explicit family/overlap
   compensation; smoothing's pass decomposition follows the resulting value.
   PINCH's historical extra remains a separate local-source adapter, not the
   effective strength. These orderings must be explicit in tests and docs.
4. SIZE is the exception fixed by the contract: generic scalar evaluation of
   semantic SIZE rejects unless supplied an already-projected object-space
   radius. Evaluate its stack as FLOAT32 on that radius, with [0,FLOAT32_MAX]
   bounds; do not round to integer pixels or apply the native diameter bounds
   to object-space radius. Projection selects the immutable effective owner's
   mode/pair and happens in the consumer. This API must make double application
   difficult: the result is a primitive evaluated radius, with no stack attached.
5. Keep the existing curve cache/PreparedResponse.evaluate behavior unchanged;
   the new evaluator supplies width-aware interpolation for exact native parity.
   Do not use a second bpy-dependent authoring resolver in the per-dab path.

## Acceptance gate

- Pure independent expected results: all five operations, ordering, skipped
  channels/layers, clamp, integer half ties/sign/saturation, INT32 above 2^24,
  boolean threshold, analytic double thresholds between neighboring floats,
  intermediate overflow, explicit zero radius and immutable source survival.
  Add fractional INT32 ranges, nonrepresentable FLOAT32 maximum .1, singleton
  BOOL ranges, knot-adjacent interpolation, endpoint signed zero and subnormals.
  Finite inputs overflowing FLOAT32 transport become missing before clamping.
  Finite analytic 1e300 responses abandon FLOAT32 layers but remain FLOAT64
  arithmetic for INT32/BOOL. Check zero-factor intermediate overflow explicitly.
- Compare prepared float/int/bool stacks to actual native UniformProperties
  evaluation using the typed fixture DLL. Include deterministic randomized
  tables, negative/out-of-range normalized inputs, missing/nonfinite samples,
  exact integer/boolean results, and bitwise FLOAT32 results where the engine's
  build arithmetic permits. Investigate any mismatch rather than weaken tests.
  The native clang toolchain explicitly sets -ffp-contract=off. Require bitwise
  FLOAT32 parity for this build; any differing arithmetic policy needs a recorded
  decision and gate rerun, never an unexplained tolerance. Compare identical typed
  ranges: native fixture declared limits where available and independently clamped
  primitive native results for additional host-only narrower domains.
- Real Blender snapshot-to-evaluation: opposed owners/native curves, spacing
  integer quantization before translation, snake remap order, compensated strength,
  and size after projection with unequal native modes/values. Assert no bpy reads
  during evaluation, no persistent allocations, no new bakes or uploads on reuse.
- Read engine instructions/status before building. Use the dispatcher, restore
  addon-only native configuration after fixture testing, and retain binary hashes.
  Record evidence and update only the bounded subtask; modal/cursor/filter/texture,
  world projection, full command capability work and Plans 7/8 remain open.

The [current consumer audit](../codebase/generic-brush-consumer-audit.md) records
the existing single-strength-per-batch transport constraint. The evaluator is
not a substitute for a reviewed batch adapter: current per-row native inputs
must continue to drive the corresponding per-dab values. No raw fallback is
authorized for unsupported generic command configurations.
