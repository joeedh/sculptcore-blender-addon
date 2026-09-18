# Plan 3 second slice: typed configuration and generated uniforms

Status: reviewed, with corrections and bounded order below, 2026-09-16.
Fresh codegen and execution reviewers inspected actual code. The typed-core
native gate passed. Later subgates remain open until their actual tests pass.
Checked local access and native member validation now pass eight native suites;
see [evidence](../codebase/generic-brush-plan3-evidence.md). Atomic descriptor
registration and generated metadata/load emission now pass the 13-suite native
gate. Typed named stores now pass 14 native suites with NUDGE enabled and an
exact-DLL legacy float/manifest smoke. Typed extra emission now passes the
15-suite native gate with mesh/grid execution and WGSL/SPIR-V validation;
see [typed extras](generic-brush-typed-extras.md). Checked configuration/bindings
now pass 16 native suites, actual typed/common Python tests, addon-only
restoration and generated declaration checks; see
[configuration](generic-brush-checked-configuration.md). Prepared execution and
the remaining input-delivery steps are still open.

## Scope and current seams

The core evaluator and generated declarations implement FLOAT32/INT32/BOOL;
manifest defaults/ranges use exact doubles. Checked Brush configuration accepts
all three types; working stores preserve FLOAT32/INT32/BOOL separately. Extra
kernel code generation now supports all three scalar stores. Existing command
preflight validates only a subset of configuration errors. This slice completes
typed configuration and generated kernel execution; event acquisition/modal
delivery remains the next slice.

## Implementation

1. Add explicit scalar type metadata to `BrushUniformManifestEntry`, retaining
   `isFloat` for old consumers. Preserve existing enum numeric values and float
   APIs. Defaults/ranges gain precise double fields (or change the generated
   bound fields with an ABI bump); choose one coherent representation after
   checking binding generation. BOOL/INT32 dynamics require explicit DSL
   `@dynamic`; ordinary float uniforms keep existing eligibility. This avoids
   making enums, masks and IDs dynamic merely because their storage is integer.
   `@static` remains ineligible. Common property eligibility is explicit too.
2. Extend parser/IR and C++ registration/load emission to eligible scalar types.
   Register typed properties with authored defaults and declared bounds. Reject
   invalid/nonfinite/reversed ranges and invalid typed defaults at compilation;
   integer ranges intersect storage bounds and must contain a representable
   integer. Emit exact integer/bool literals, not float intermediates. Existing
   shared-name registration must reject conflicting types/ranges rather than
   reuse a mismatched property. Preserve native member types and static loads.
3. Add native named INT32/BOOL stores alongside existing FLOAT32 storage. Extend
   extra registry entries/deduplication to include type and default. Generate
   typed slot defaults, access, and GPU packing. Reject same-name conflicting
   types/defaults across extras. Keep existing float slot ordering when only
   existing float extras are present. Slots remain per-build implementation
   details; addon stable IDs map through queried metadata.
4. Brush typed property setters/getters and checked configuration operate by
   registered property name, with index wrappers where the binding runtime
   requires them. Add typed int/bool access without float slots. Existing float
   methods remain callable. Configure updates preserve order/table/disabled
   state; whole-stack replacement validates before changing live state. Expose
   explicit clear/move/enable and bounded bulk table replacement. Single-sample
   compatibility upload rejects invalid indices/counts/nonfinite values and
   initializes resized tables deterministically; incomplete imports cannot pass
   preflight. Avoid allocating tables per dab.
5. Extend actual mesh/grid/program preflight to check eligible stored type,
   authored finite value/range, unique supported input types, mix/factor/table
   validity and static/unavailable targets before geometry or undo mutation.
   Keep diagnostics useful to callers. BOOL `invert` loading must receive the
   same context if included in the explicit common eligibility list. Existing
   command float overrides remain compatible; add typed command overrides and
   copy complete stacks without leaking per-dab cached results between commands.
6. Regenerate binding descriptors, Python/TS declarations and ABI version using
   established tooling. Rebuild the Python DLL; point tests at that exact DLL
   before vendoring. Metadata exposes scalar type and dynamic eligibility.
   Unsupported configuration must return a checked failure, not silently fail.

## Acceptance evidence

- Preserve existing float dynamics/uniform validation/codegen/backend tests.
- Add actual typed extra-kernel fixtures using an integer above 2^24 and a bool
  branch, each explicitly dynamic. Independently assert computed geometry for
  mesh and grid, single and relevant batch/program paths; prove invalid static,
  unsupported, duplicate and nonfinite configurations leave geometry unchanged.
- Test integer/bool defaults and ranges in emitted source and queried metadata,
  typed stores, duplicate-extra conflict diagnostics, and GPU pack bytes.
- Configure/read/evaluate float/int/bool values and stacks through actual Python
  bindings, including bulk samples, exact large ints and failed atomic updates.
- Build through `make.mjs`; run codegen/validation targets relevant to emitter
  changes. Record actual commands and regenerated artifacts. The parent Plan 3
  remains open until timestamped input acquisition and headed modal delivery pass.

## Review questions

Review actual binder scalar support/ABI update workflow, registry slot naming,
GPU packing, generated default/range propagation, command preflight placement,
and all executable load paths. Identify missing seams and incompatible API
choices before implementation. Preserve engine TODO.md and dirty litestl work.

## Review corrections and fixed decisions

### Typed descriptors and storage

- Native member recognition needs actual scalar type and semantic eligibility,
  replacing name-only capability checks. Wrong-type declarations and explicit
  dynamics on enum/ID members (mixMode, activeGroup) fail. Reserved prelude names
  also validate against real storage. Track explicit annotations separately and
  reject contradictory @static/@dynamic declarations.
- Use one descriptor compatibility policy covering type, default presence/value,
  bounds and eligibility. Validate the complete registration batch before any
  mutation. Reverse registration order must yield identical results. Missing
  native DSL defaults preserve existing host-authored values.
- Properties hold authored dynamic values; typed member/slot caches hold evaluated
  values. Public legacy slot writes must update authored state once registered;
  internal evaluated writes must not. Static writes retain their semantics.
  Track initialized/authored presence separately from vector length so an early
  high-slot write does not erase lower nonzero/true defaults.
- BOOL wire values occupy four bytes as uint32 0/1. WGSL uniform buffers store
  u32 and convert at reads; never memcpy four bytes from native bool. Test fixed
  invert and appended bool offsets plus the following field. CPU-only bool extras
  must compile even though their generated header includes a pack function.
- GPU extra-kernel runtime dispatch does not exist. This slice supports typed
  extras on CPU mesh/grid and validates their shader/pack artifacts separately.
  Advertise no GPU extra execution; reject it before mutation. Invoke actual
  shader validators on typed fixtures because current backend globs omit extras.

### Checked access and bindings

- Exact-type authored writes address local properties only; inherited reads do
  not grant permission to modify a parent. A missing local write fails unless an
  explicit registration/override operation creates it. Preserve presence.
- Checked numeric transport uses a finite double plus explicit scalar type at
  the new reflected boundary. INT32 requires an integral representable value;
  BOOL requires exactly 0 or 1. This avoids ctypes int32 wrapping or bool truth
  coercion before C++ validation. Python adapters additionally validate intended
  user types. Native exact-type APIs remain typed. Wrong-type writes fail safely.
- Expose manifest-index wrappers; plain Python/TS strings do not automatically
  marshal to by-value reflected util::string. Re-query mapping after manifests
  change and reject stale indexed targets using configuration identity.
- Existing reflected BOOL/INT32/FLOAT64 transport is supported. Adding reflected
  fields does not itself change dispatcher ABI; do not edit dirty litestl merely
  to bump its ABI. Regenerate checked-in kernels before Python DLL compilation,
  then regenerate stubs with `python -m sculptcore._gen` against that exact DLL.

### Execution preparation

- Standalone mesh/grid paths currently omit generated uniform loading. New
  resolved execution explicitly registers, validates and loads authored state.
  Keep an explicit compatibility path for existing raw-member/named-slot callers;
  adding loaders unconditionally would overwrite their values with defaults.
- A reusable preparation result validates before dyntopo, pinning, undo capture,
  node selection or hooks. Grid needs the same check. Key preparation validity
  by configuration generation, never only isFirstOfStep; an empty first dab must
  not bypass validation. Checked evaluation failure propagates as failure,
  rather than treating lookup's compatibility default as valid execution.
- Evaluate radius/extents before region selection and batch filtering. Select
  the conservative union for prepared commands, including unbounded policies,
  and execute those exact values. Existing caller-supplied node lists need an
  explicit prepared-node contract; do not silently assume adequate coverage.
- Program preparation must reject the entire new typed program before its
  first command executes. Shared-brush stray checks cannot validate independent
  command manifests. Per-command state and scoped restoration cover authored
  presence, values/stacks, working members/slots, invert and failure exits.
- Full independent command inheritance and configuration-dependent hooks/cache
  identity remain Plan 6 gates, as the parent task list specifies. The new path
  must explicitly reject combinations it cannot yet prepare, while retaining
  existing legacy programs. Later-command cavity and differently configured
  ENHANCE require Plan 6 tests; do not claim them from typed core/config tests.

## Bounded implementation order

1. Checked exact-type local authored access and explicit evaluation errors;
   typed member/semantic descriptors and complete registration validation.
2. Checked configuration/typed stores with initialized presence, atomic stacks,
   bulk tables and binding transport; native and actual binding tests.
3. Generated exact defaults/ranges and typed working loads, shader bool packing
   and typed extra fixtures. Preserve raw-field caller baselines.
4. Standalone mesh/grid prepared execution and region selection, then batches.
5. Typed program preparation/restoration and program batches; explicitly gate
   deferred Plan 6 combinations and retain their required later tests.
6. Exact-DLL regeneration, codegen/backend fixtures, kernel geometry matrix.

Each step records its own evidence. All are prerequisites for claiming this
slice complete; timestamp acquisition and real modal delivery follow separately.

The checked-configuration review identified a fixture dependency: land typed
extra emission before its Python acceptance gate, so the gate uses actual typed
kernels. See [the folded review](generic-brush-checked-configuration.md). This
changes only the internal order of steps 2–3, not the parent plan dependencies.

### Foundation implementation review

- The checked API rejects inherited bound/getter-backed values with
  ERROR_INVALID_OWNER until a resolved property carries its declaring owner.
  It must not reuse a mutable Property.owner cache or assign the child owner.
  Unbound inherited defaults remain supported and legacy APIs are unchanged.
- The complete reserved shader-name set includes nonaccum and grab_dab_gen.
  Negative fixtures cover both; a positive nondynamic planeSide fixture checks
  emitted metadata plus omission from dynamic loading. Static scalar metadata
  now registers too, as recorded in the generated-registration gate.
- Native member descriptors derive storage types from decltype rather than a
  second handwritten type table. Semantic eligibility remains explicit. Existing
  built-in declarations and the NUDGE extra were inspected for compatibility.
