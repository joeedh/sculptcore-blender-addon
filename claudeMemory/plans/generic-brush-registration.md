# Plan 3: atomic scalar declarations

Bounded implementation of the reviewed typed-integration registration step.
Add an immutable ScalarDeclaration record to the property definition layer:
name, FLOAT32/INT32/BOOL type, default presence/value (double), range
presence/bounds (double), and dynamics eligibility. StructDef retains accepted
declarations independently of mutable property values. Registration validates
the complete batch and existing declarations before creating any properties.
Conflicting type/default presence/value/range/eligibility fails, including in
reverse registration order. Duplicate identical declarations are idempotent.

Preserve existing native/common authored values when adopting an undeclared
property. Validate its type and effective numeric bounds; do not reseed it.
Inherited properties remain inherited and require matching declarations/bounds;
never register through a parent owner or change a parent's fields. Normalize
integer ranges by intersection with int32 storage and ceil/floor; validate
finite defaults and representability. Empty integer ranges fail. Boolean
defaults must be 0/1. Unsupported scalar types fail. Runtime checked writes
must use the resulting effective bounds. Schema checks precede all mutations.

Expose this primitive with direct native tests before wiring generated
registration and manifest metadata. Keep this gate explicitly foundational;
the existing generated callback remains until the follow-on emitter/manifest
step can propagate failures through its callers. No end-to-end typed execution
claim from this gate.

Gate: native registration tests for exact 16777217, int32 bounds, booleans,
nonfinite/reversed/empty ranges, atomic mixed batches, duplicate declarations,
reverse order conflicts, authored values/stacks preserved, common and inherited
properties, and checked writes against declared bounds. Rebuild through the
engine dispatcher and rerun property/brush regressions. Preserve dirty TODO.md
and litestl. Record the accepted review corrections and evidence.

## Adversarial review corrections (before implementation)

- Both reviewers identified the factory's offset-zero default: new declaration
  properties explicitly use binding_offset=-1. Registration never calls a
  getter/setter or changes owner pointers. Existing values are validated by the
  execution access gate, not by invoking owner-dependent code during adoption.
- Keep original doubles and presence bits for strict schema compatibility;
  separately derive effective bounds. FLOAT32 bounds intersect finite storage
  then round inward with nextafter; an interval containing no float fails.
  Defaults round to FLOAT32 (including normal underflow to zero) and must land
  within the effective bounds. Checked writes validate converted FLOAT32 values
  against effective bounds, allowing decimal boundary inputs that round inside.
  Integer/boolean bounds intersect storage and round inward to integer values;
  boolean domain is {0,1}. An absent default initializes a new prop to zero only
  if zero is allowed, otherwise registration fails; adopted values are preserved.
- StructDef owns copies of declarations. Metadata lookup follows actual property
  resolution and stops at a local shadow. Validate every retained declaration
  on the resolution path against the actual property type/bounds. Checked scalar
  reads/writes reject schema drift after raw bound mutation or replacement;
  identical re-registration also checks live compatibility. Parent changes are
  rechecked rather than cached. No shallow StructDef copy for transactions.
- Atomicity covers validation failures; allocator failure follows the engine's
  allocator policy. Add sentinel-owner, drift/replacement, temporary-input,
  default-presence, fractional/empty ranges, float boundary/underflow and
  pointer/value/stack/metadata preservation tests.

Implementation review found no blocker. Registration checks the receiving
definition and its ancestor resolution path; it does not maintain a reverse
index of descendants. If a parent is changed incompatibly after a child has
adopted a declaration, subsequent checked child access rejects the mismatch.
Order-independent conflict tests apply to batches and shared definitions.

## Completion gate — 2026-09-16

Complete: native build and nine regression suites pass, including the new
test_props_declarations suite. Final build log: tests/typed-declarations-build-final.log.
Commands, binary hashes, statuses and output: tests/typed-declarations-results.json
and tests/typed-declarations-test_*.log. The helper run_typed_engine_gate.py invokes
each suite through node make.mjs test with inherited loader dialogs suppressed.
Generated callback integration remains the next step, not part of this gate.
