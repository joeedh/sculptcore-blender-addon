# Plan 3 first slice: typed dynamics evaluation

Status: bounded core complete, 2026-09-16. Fresh numeric and integration
reviewers inspected actual code; surviving findings are folded in below.
Native build and all four required suites passed; see
[completion evidence](../codebase/generic-brush-plan3-evidence.md).

Plan 3 depends on completed Plan 1 and can proceed independently of Plan 2.
The frozen contract remains authoritative. This slice implements and tests the
numeric evaluator and property lookup; it does not advertise complete kernel,
binding or device-delivery capability before later Plan 3 integration passes.

## Existing seams

- `engine/source/props/prop_dynamics.h` supports float-only mixing, leaves old
  samples in layers absent from a new context, and permits duplicate inputs.
- `prop_struct.cc::lookupValue` applies dynamics only for floating requests;
  typed properties already contain a Dynamics member through NumBase.
- `prop_types.h::NumBase` leaves min/max/step uninitialized; its copy constructor
  omits authored internal value, range and dynamics. Fix the relevant state
  initialization/copy without changing unrelated vector semantics.
- Brush configuration and generated uniform loaders are separate follow-up
  seams. Existing lookup/coercion must dispatch by actual stored property type,
  not turn an INT32 into float merely because the caller requests float.

## Proposed implementation

1. Add a shared scalar dynamics evaluator for FLOAT32, INT32 and BOOL. Float
   mixing and response interpolation use float32; integer/bool working values
   and interpolation use float64. Skip disabled/missing/nonfinite device samples.
   Preserve the previous finite layer result after nonfinite arithmetic. Apply
   declared bounds intersected with storage bounds once after the ordered stack;
   int rounds ties away from zero then saturates before casting; bool uses >=.5.
   Preserve valid authored bases for empty/entirely skipped stacks.
2. Give every layer explicit current-sample validity. Reset it before feeding
   a new context; duplicate delivered input types explicitly replace their prior
   sample rather than accumulating ambiguous entries. Configuration-layer
   duplicate rejection/replacement is exposed by a validated Dynamics helper,
   ready for the later Brush/command binding boundary. Canonical inputs here are
   normalized [0,1]; host pressure/tilt/time conversion is a later slice.
3. Validate layer configuration: supported device types pressure/tilt X/Y/speed,
   supported mix modes, finite factor in [0,1], finite response samples, unique
   layer type. Retain disabled layers and table data. Keep clear/update operations
   explicit. Preserve old float caller source compatibility where necessary;
   new typed callers use the shared evaluator. Do not claim low-level publicly
   writable structs are an authoritative serialized configuration boundary.
4. Initialize scalar property bounds/step and copy their complete authored state.
   Route lookup through the stored Float32/Int32/Bool type before destination
   coercion; preserve getters and bound owner handling. Values remain authored
   in properties; computed results populate caller caches only. Unsupported
   storage types receive no new dynamics capability. Avoid widening the existing
   unrelated coercion implementation beyond paths required by this slice.
5. Add native tests through the existing engine dispatcher for independently
   computed contract examples: +/-3*.5, conversion only after multiple layers,
   int32 extrema/saturation, bool .49/.5, all modes and factors, declared ranges,
   skipped/disabled/absent samples across dabs, nonfinite fallback, rejected
   duplicate/config inputs, typed lookup and deep property copying. Run existing
   float dynamics/uniform validation tests and report any deliberate contract
   change; do not bless new results by mechanically copying implementation output.

## Follow-up slices and gate boundary

Subsequent work adds typed Brush/command setters and stacks, DSL metadata and
generated registration/loaders, preflight failures, actual Python bindings,
acquisition timestamps/presence masks, modal interpolation and every executor.
Static uniforms/enums/masks/IDs stay ineligible. The parent Plan 3 remains open
until real float/int/bool kernels pass mesh/grid/program/single/batch paths and
headed device delivery, including queued-event speed and curved arc fractions.

Reviewers must inspect actual property lifetime/coercion/getter and numeric
default semantics, existing direct Dynamics callers, toolchain fast-math flags,
and test/build routing. Seek cases where this bounded implementation would force
incompatible follow-up APIs or change baseline float geometry unexpectedly.
Engine TODO.md and its dirty litestl submodule are unrelated and preserved.

## Review corrections and routine decisions

- Fix the narrow PropBaseType name/UI-name constructor omission along with
  NumBase copy. Test cloneProperty metadata, callbacks, value, bounds and table
  independence; copied sample validity resets. Owner binding is reacquired by
  lookup rather than carrying a previous owner's transient sample state.
- FLOAT32 default bounds are lowest()/max(), INT32 uses full storage bounds,
  BOOL false/true. Default step is initialized. Unsupported vector metadata is
  initialized without adding vector dynamics. Reject reversed/nonfinite bounds
  and empty intersections; preserve valid empty-stack negative zero bitwise.
- Provide checked evaluation with explicit failure for invalid bases/config or
  bounds. Typed lookup uses its existing caller-supplied default on failure;
  never cast NaN or silently substitute zero. Keep the exact float operation
  sequence, including factor 1; FLT_MAX REPLACE -FLT_MAX overflows the delta
  and must retain the prior finite value. Test interpolation overflow separately.
- Delivered samples use last value, including last nonfinite making the input
  unavailable; cover direct duplicates in the public input vector as well as
  push. Authoring updates preserve order and unspecified table/disabled fields.
  Imported complete stacks reject duplicates atomically. These are separate
  operations. Zero response samples means identity, one is invalid, >=2 samples
  interpolate; match existing command preflight rather than its inconsistent
  low-level single-sample fallback.
- Evaluate the source type before coercion: INT32 16777217 * .5 requested as
  float yields integer 8388609 then converts; BOOL REPLACE .49 requested as
  float yields 0. FLOAT32 .49 requested as bool uses normal destination numeric
  coercion after float evaluation, not the BOOL dynamics threshold.
- Integer fixtures use Int32Prop::Default/set; do not expand StructProp setters
  solely to write the tests. Include getter-backed and bound-owner lookups and
  prove no setter/authored-value mutation during evaluation.
- Unsupported FLOAT64 retains its existing ordinary coercion path without
  dynamics; remove the legacy float-only dynamics branch under the frozen v1
  eligibility decision. Do not claim the pre-existing unsupported numeric
  coercion paths are repaired. Later configuration/preflight work must reject
  such stacks before geometry execution; this slice is not a release gate.
- Generated registration currently omits manifest Min/Max. Core tests explicitly
  configure bounds; later codegen/range propagation is a required integration
  gate, not evidence supplied by these core tests.
- Native clang already uses -ffp-contract=off. Record actual flags; no broad
  compiler changes. Build through `node make.mjs build native` before running
  `test_props`, the new typed test, `test_brush_dynamics` and
  `test_brush_uniform_validate`; the test command alone does not rebuild.

### Implementation review corrections

- Mixed direct-vector samples and `push` obey the same last-delivered rule:
  `push` updates the last matching entry, which evaluation consumes last.
- Source-first evaluation can produce finite floats outside an integer caller's
  range. Check destination representability before integral narrowing and use
  the supplied default on overflow; preserve ordinary in-range truncation.
- Add discriminating fixtures: `3*.5+.6 => 2`, BOOL `true*.49+.02 => true`,
  and an ADD-then-SUBTRACT excursion outside the declared range. These fail
  premature conversion/clamping. INT32 16777217 with table `{.2f,.9f}` at
  input `.1f` must produce 4529849, distinguishing float64 interpolation.
- Fresh numeric and seam reviewers checked the actual implementation. Their
  surviving findings above were fixed before the native gate is recorded.
