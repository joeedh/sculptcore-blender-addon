# Plan 6: prepared unbounded support and proven scalar preludes

Status: completed 2026-09-18. The [verified gate](../tests/plan6-unbounded-gate.json)
records 17 native and 17 fixture suites, shader validation, installed background
and headed checks, and package provenance. The command automasking gate is complete.
This slice handles nonanchored unbounded commands;
anchored grab, preview, dyntopo, general attributes and other host hooks remain
explicit subsequent dependencies of the full Plan 6 gate.

## Current implementation constraints

- Kelvinlet is both unbounded and grab-capable. Anchored mode chooses
  AccumOrigGrab and requires first-touch image arbitration; this slice keeps the
  anchored guard. Nonanchored Kelvinlet still has a generated host clamp and a
  scalar reduce prelude, so merely removing the unbounded guard is insufficient.
- The compiler marks every host/reduce stage unsafe. Its assignment checker only
  admits lexical value locals and direct vertex geometry writes. Kelvinlet's
  host writes mu/nu, whose exact declared domains already guarantee those clamps
  are no-ops after successful prepared scalar validation. Its reduce computes
  two scalar outputs from those values without touching shared state.
- An unbounded field has an optional cutoff at radius * unboundedExtent. Extent
  <= 0 disables the cutoff. A conservative all-leaf query is correct for both;
  a radius-only query truncates later unbounded stages. Cavity first contact must
  cover the field's actual support, rather than the regular brush sphere.

## Implementation

1. Add conservative compiler proofs for two narrowly defined preludes.
   A host body qualifies only when it contains canonical scalar-uniform range
   clamps: `if (field > declared_max) field = declared_max` or the corresponding
   lower-bound form, with no else, extra writes, unknown calls, loops or context
   access. Restrict the initial proof to FLOAT32 fields with explicit finite
   ranges, matching comparison/assignment constants exactly. Normalize domains
   with the same representable-bound rules used at preparation. All other host
   stages remain ineligible. Preserve original host code for raw execution and
   retain its call during prepared execution, where the proof guarantees no change.
2. A reduce prelude qualifies only for straight-line scalar local/output
   assignments from literals, current scalar uniforms, already initialized locals
   or earlier initialized outputs, using pure arithmetic expressions. Require
   every output initialized before use and before completion. Reject shared writes,
   input-parameter writes, unknown calls, loops, neighbor/geometry/context reads
   and ambiguous shadowing. Keep general compiler behavior unchanged; this proof
   controls prepared eligibility only. Combine these proofs with the existing
   assignment/call audit; never allow a safe prelude to hide unsafe vertex writes.
   Emit default-false command metadata for proven no-op host stages and include
   proven reduce stages in preparedScalarSafe. Do not whitelist a tool name.
3. Snapshot unboundedExtent independently for every prepared stage, including
   stages whose kernel does not declare it, so an earlier declaring command cannot
   leak its working value. If the current manifest declares it, use its prepared
   typed value. Otherwise inherit the authoritative Brush member without adding
   a persistent property or allowing an undeclared scalar override. Apply the
   stage snapshot and restore the original working member with existing scopes.
4. After full scalar/metadata validation, validate each positive-radius unbounded
   stage's finite extent and finite positive cutoff arithmetic when enabled.
   Keep zero-radius stages skipped. A program with any executing unbounded stage
   selects all nonempty mesh/grid leaves; bounded-only programs retain the existing
   maximum-radius query. Do not mutate query lists, publish, capture, change
   topology or allocate persistent attributes on a rejected candidate.
5. Admit proven safe nonanchored unbounded commands in both prepared executors.
   Execute the already-prepared command and prelude without legacy loadProps or
   a second dynamics evaluation. Cavity contact for an unbounded stage is strictly
   inside its positive cutoff, or every visited vertex when cutoff is disabled.
   Bounded stage contact remains its own spherical support even in an all-leaf
   shared program. Keep the stage column valid outside contact as before.

## Acceptance

- Compiler positive/negative fixtures cover each permitted syntax, nearby unsafe
  variants, shadowing, assignments hidden in index expressions/calls, output
  initialization, mixed safe/unsafe stages and built-in Kelvinlet generation.
  Existing compiler/backend checks must continue to pass; regenerate native/TS
  declarations and generated kernels through the dispatcher.
- Mesh live/CSR and grid immediate/deferred tests compare nonanchored standalone
  and program Kelvinlet with independent raw execution over all leaves. Include
  DRAW followed by a larger unbounded field, changed pressure and material stacks,
  zero/missed first dabs, cutoff disabled, exact boundary, growing support, and
  subsequent bounded strokes. Use multiple leaves and vertices outside the main
  brush's original region. Demonstrate actual movement there.
- Test invalid extent/product/late-stage candidates before topology, undo,
  counters, properties and query-state mutation. Command extent inheritance and
  scoped restoration must survive success, miss, zero radius and rejection.
- Cavity-on unbounded stages must match independent cutoff-support oracles and
  keep first-contact values for subsequent dabs. Different scalar material values
  must not create accidental cavity configuration changes.
- Exercise required-prepared C API/Python calls and input batches with the current
  nonanchored geometric context. Test native undo/redo and installed package
  provenance. Do not claim anchored modal adoption from this bounded slice.

The all-leaf query is a deliberate correctness-first choice for unbounded stages.
It avoids support truncation without extending today's pinned-grab lifetime
rules. A later measured optimization may use a finite validated extent query.

The existing raw grid query cannot serve as an all-leaf reference with cutoff
disabled: it still selects a bounded region from the brush radius. Grid acceptance
therefore uses the independent original-formula double oracle over the whole
domain. Mesh acceptance additionally compares against raw execution with an
explicitly widened all-leaf region. Do not change the legacy raw grid query just
to make it usable as an oracle for the new prepared path.

## Implementation review corrections — 2026-09-18

The execution source review requires reflected `grabFrom`, `grabTo`, and `viewDir`
for each prepared batch image. A scoped image frame restores the primary frame
on success and failure; signs are already restricted to exactly -1 or +1 by
batch input validation. Raw batch behavior retains its existing frame policy.
Compare mirrored batches against explicitly reflected single calls in the DLL.

Strengthen native coverage with both mesh neighbor modes, nonconstant cavity
factors independently computed at first contact, exact cutoff exclusion, changing
material settings without changing cache identity, and all finite-product/vector
rejection classes before geometry, topology, query, or cavity-cache mutation.
Add actual late-stage extent isolation and zero/miss/subsequent bounded execution
before claiming the complete unbounded gate. Snapshot-only tests do not satisfy
the executing extent-isolation requirement.

The reported `ctx` parameter collision is already rejected by the lexer because
`ctx` and `brush` are reserved tokens. The emitter also rejects those names
defensively for programmatically constructed IR; generated internal names remain
covered by compiler tests. This does not require expanding eligible prelude syntax.

## Review dispositions — 2026-09-18

The [compiler review](../tests/plan6-unbounded-compiler-review.md) and
[execution review](../tests/plan6-unbounded-execution-review.md) require these
corrections before the corresponding implementation:

- Reduce proofs initially accept only FLOAT32 `out` parameters and initialized
  FLOAT32 locals, simple assignments, float literals and float arithmetic. All
  non-Vertex inputs to the generated vertex loop must have matching producers.
  Reject input/inout reduce parameters, ambiguous names, nested local scopes,
  conversions, calls, integer operations and compound assignments. Float divide
  by zero remains eligible for the *shared-state/initialization* certificate;
  this certificate does not promise finite geometry from arbitrary kernel math.
- Exempt assignments only while emitting a fully certified stage. Command-level
  unsafety remains monotonic, including textures and vertex expressions. Emit a
  default-false `preparedHostNoop` certificate covering all composed hosts.
  Executors require this together with `preparedScalarSafe` for a host callback.
- Host proofs use `normalizeScalarDeclaration` (already linked through props)
  and the emitter's actual float-literal representation. Accepted typed lower/
  upper bounds must make the emitted strict predicate false. Preserve raw code.
- Snapshot inherited extent outside the override-eligible value list. Explicitly
  save and restore it in standalone executor-only and full program scopes.
- Validate the actual float cutoff product AND its `0.2f * R` transition width
  before validateOnly or any mutation. Test underflow, overflow and boundaries.
- Kelvinlet admission additionally requires reviewed safe arithmetic or a proven
  preflight numerical envelope, including inside-cutoff and disabled-cutoff
  cases. Merely short-circuiting outside support is insufficient. Keep the
  unbounded executor guard until this obligation and its tests are satisfied.
- Compare field execution against cavity-disabled raw all-leaf references.
  Separately test cavity's first contact with an independent live stage-input
  coordinate oracle, centered on surfacePos (deliberately unlike grabFrom),
  strict cutoff exclusion and universal contact when cutoff is disabled.
- Rejection is atomic per image/program candidate; earlier accepted batch dabs
  remain applied. Test later-dab rejection, zero-count validation, required and
  automatic policy. Preserve falloff restrictions and lifetime checks. Measure
  actual coordinates rather than affected counts, which include zero movement.
