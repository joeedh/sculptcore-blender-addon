# Plan 3: generated declaration registration

Status: complete for this bounded gate, 2026-09-16. Plan 3 remains open.

Connect the now-tested ScalarDeclaration batch API to generated kernels.
BrushUniformManifestEntry gains exact double defaults/ranges, explicit Prop
storage type and default presence; retain isFloat and positional compatibility
for existing manually authored manifest fixtures. Generated scalar metadata uses
exact double literals, with BOOL/INT32 eligibility requiring @dynamic and native
semantic approval. Typed extra stores remain a later step; unsupported extra
types continue to fail compilation until their working stores exist.

Replace the generated void registration callback with a checked result, using
immutable scalar declarations for the complete scalar uniform batch (including
static scalar metadata). New properties are unbound and existing values survive.
Generate typed native loads for FLOAT32/BOOL/INT32 where eligible. Regenerate all
checked-in outputs using the engine dispatcher before building consumers.

Existing registration call sites must handle failure: manifest query returns -1
and records diagnostics; mesh/grid programs validate registration for the whole
program before their per-dab mutations and skip geometry on failure. Combine
program scalar manifests into one registration batch to avoid partial creation.
Remove per-command re-registration after overrides. Preserve standalone raw-field
paths; full prepared execution, early region selection and typed extra/program
configuration remain in later reviewed integration steps.

Gate: generated built-in registry, original float dynamics/uniform validation,
actual failed query and mesh/grid program registration with unchanged geometry,
precise typed metadata/literals and conflict rejection, full native rebuild.
Record callback/error propagation scope and remaining execution limitations.

## Review corrections before implementation

- Use checked BrushCommandDef methods derived from uniforms, eliminating the
  duplicate generated callback rather than adding another declaration container.
  Alias/accumulation factories already clear uniforms, so metadata cannot stack.
- Registration-only program preparation runs on each public/direct invocation,
  before mesh dyntopo/filtering or grid stroke samples. Both batch entry points
  prepare before writeProps. Failure is retained in a diagnostic result and
  produces -1 at moved-count public boundaries; aggregators stop on failure.
  Manifest-query failure is explicit to the addon rather than an empty schema.
- Static scalar declarations are installed deliberately. Native static working
  members are never loaded from them. Revise the old storage-absence assertion
  and test the observable host-value preservation across static fields.
- Functional typed configuration remains deferred: existing configuration and
  execution validation gates still reject unsupported typed dynamics. This gate
  proves metadata/registration and generated native typed loads only.
- Emit double metadata literals; preserve typed storage literals. Add explicit
  props linkage to sbrushc_core for shared declaration validation (no implicit
  linker dependency), and prove the standalone codegen build. Boolean defaults
  accept true/false as well as validated 0/1.
- Extra registry generation still lacks complete metadata conflict validation;
  runtime combined registration rejects conflicts, with registry generation
  extended in the typed-store step. Command creation may initialize legacy
  working slots; atomicity here covers declarations/authored properties and
  execution mutations, not legacy cache allocation.
- Extend gates to common shared registration in both orders, accumulation
  variants, failed mixed programs/queries, empty first dab, changed programs and
  dyntopo. Check properties, overrides, samples and topology as well as positions.

Implementation review corrections: collect manifests with scratch Brushes so
extra-kernel default initialization cannot change live working slots on failure.
Registration status is separate from dynamics validation; the public combined
status checks both, and a subsequent successful registration clears its own
failure without erasing a dynamics error. Addon nonbatch mesh programs now
return -1 on native validation failure. Actual mesh/grid failed batch calls
check that authored common values remain unchanged before writeProps. Default
range validation respects hasDefault. The initial geometry assertions used
Vec's pointer conversion; final assertions compare exact component bytes.

## Completion evidence

- Dispatcher codegen and native rebuild passed. Final build:
  ../tests/typed-generated-registration-build-gate.log.
- All 13 suites passed via `run_typed_engine_gate.py --prefix
  typed-generated-registration --extended-registration`; commands, exit codes
  and binary hashes are in ../tests/typed-generated-registration-results.json.
- Five addon boundary tests passed in
  ../tests/typed-generated-registration-addon.log. They compile actual stroke
  function bodies with native calls replaced by fakes. Rejected scalar dabs stop
  symmetry; preview rejection follows rollback, including the initial dab.
  These are not a substitute for the later real modal-event acceptance gate.
- Initial 11/13 run is retained under the `typed-generated-registration-initial`
  prefix; the two failures were incorrect Vec pointer-equality assertions.

The Python DLL/bindings have not been regenerated or vendored for this gate.
The later [named-storage gate](generic-brush-named-storage.md) reran all suites
with NUDGE explicitly enabled and verified its extra-branch marker. The original
13-suite run had compiled that conditional branch out; use the later evidence
for extra working-slot preservation. It also checked the native DLL's metadata
transport through Python without vendoring the runtime.
Full prepared execution, typed configuration/stores and device acquisition are
still pending. In particular, addon node filtering and preview snapshotting
precede the native registration check; full early preparation is a later gate.
