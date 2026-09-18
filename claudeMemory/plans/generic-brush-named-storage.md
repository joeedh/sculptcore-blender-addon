# Plan 3: typed named working stores

Status: complete for this bounded gate, 2026-09-16. Plan 3 remains open.

Implement a bounded storage gate before checked stack configuration and typed
extra-kernel emission. Preserve float API call shapes and existing float slot
order. Integer and boolean stores keep their actual native types.

## Proposed implementation

1. Add a small NamedUniformStore<T> used by Brush for float, int32 and bool
   working values. Keep initialized presence separately from vector length.
   Ensure a default only for an uninitialized slot; an early write to a high
   slot must not prevent lower nonzero/true defaults from being installed.
   Bounds-check reads and writes; negative slots fail without growing storage.
   Expose read-only indexing/size for generated reads; mutations use methods.
2. Keep setNamedFloat/getNamedFloat and add native int/bool counterparts.
   Add internal evaluated-write methods that never write authored properties.
   Read names/types/eligibility from immutable generated slot descriptors via
   an out-of-line lookup in brush.cc, with a no-extras fallback. No mutable
   binding API or new factory failure protocol is introduced.
   Public slot writes update an existing local registered property through
   exact-type checked access before changing working storage. Static slots
   retain direct working-value writes. Unregistered writes remain supported.
   On a checked authored-write error, preserve both values and return failure
   from a new checked scalar transport boundary (explicit type + double).
   Legacy void setters delegate to that boundary and report failures.
3. Generated float default installation calls Brush slot initialization with
   compile-validated slots/defaults. Generated evaluated float loads use the new
   internal working-write method. This immediately exercises storage through
   the existing NUDGE extra without enabling typed DSL extras prematurely.
   Repeated initialization preserves authored/working presence and values.
4. Add native tests for all three storage types: high-slot writes before default
   installation, exact 16777217 and INT32 extrema, true defaults, repeated
   initialization, invalid indices/types/numbers, checked local property writes,
   inherited write rejection, static raw semantics, and evaluated writes leaving
   authored state unchanged. Extend actual extra-registry/codegen regression
   tests and compile the generated existing extra with the native build.

This gate does not claim typed extra execution, complete registration/store
adoption transactions, or host bindings. Those remain in the reviewed typed
integration plan. Working caches populated before registration retain their
legacy values; later resolved execution loads the registered authored value.

## Gate

Fresh adversarial storage-semantics and generated-consumer reviews before edits.
Dispatcher codegen/native builds and the extended registration regressions,
plus dedicated typed-store tests. Record exact commands and limitations.

## Fresh review corrections (2026-09-16)

The storage-semantics and generated-consumer reviewers inspected actual code.
Both accepted the immutable descriptor correction above. Folded requirements:

- Slots are [0,65536); reject before allocation/property access. Checked numeric
  transport validates finite representability before modifying either store.
  A missing local property with an existing parent property rejects as an
  invalid owner; only absence throughout the chain permits an unregistered raw
  write. Static/context slots keep working-only writes.
- Registry StoreUniform carries a complete ScalarDeclaration and shares the
  emitter's eligibility helper. Validate declaration/count/compatibility before
  generation, including default presence and range. Context fields are never
  dynamically authored. Immutable generated lookup avoids bind conflicts and
  the existing factory's false-means-unknown/abort protocol.
- Storage values/flags stay private; expose read-only size/index/get. Defaults
  and internal evaluated writes set initialized presence, never authored state.
  Do not add hostWritten provenance or claim evaluated caches support adoption.
- Route emitted simple/compound store assignments through evaluated setters:
  the same identifier emitter currently serves reads and assignment targets.
- NUDGE is static. Add a compiled dynamic-float extra fixture with a host write
  and run its generated loader. Test typed authored-write policy through a
  descriptor-aware helper until typed extras exist. Preserve existing float
  GPU getter/packing behavior and bound float signatures. Build sbrushc alone
  to detect accidental linkage from its Brush descriptor dependency.

Implementation audit corrections: the combined property/store write now lives
in a descriptor-aware helper used by Brush itself and typed regression tests.
Cover read-only, range, wrong-type, schema drift and inherited failures with
both values unchanged. The new test executable calls `return test_end()` so
assertion failures and allocation leaks fail its process. Its dynamic generated
fixture uses test slots; it is not added to the shipping extra registry.

Build note: the initial no-extras build exposed an unguarded duplicate props.h
include and the old unused BrushCommand placeholder in brush.cc. Removing those
when making brush.cc own the real setters resolves the conflicts. The final
build explicitly uses `--kernels-extra ../brushes`; earlier registration logs
did not include the conditional extra branch and are superseded for that claim.

## Completion evidence

- `node make.mjs codegen`: standalone compiler link and generation passed;
  ../tests/typed-named-storage-codegen.log.
- `node make.mjs build native --kernels-extra ../brushes -j 8`: passed;
  ../tests/typed-named-storage-build-verified.log. Earlier failed build logs are
  retained. The fixture needed the emitter's normalized factory spelling and
  vector-coordinate assignment syntax; both compiled in the verified build.
- `python claudeMemory/scripts/run_typed_engine_gate.py --prefix
  typed-named-storage --extended-registration --named-storage`: all 14 suites
  passed; ../tests/typed-named-storage-results.json records commands and binary
  hashes. The runner requires the extra-registration branch marker.
- `python claudeMemory/scripts/test_named_storage_binding_smoke.py`: passed
  through the native DLL; ../tests/typed-named-storage-bindings.log records the
  exact path/hash and queried metadata. FLOAT64 manifest transport preserves
  16777217 and INT32 bounds; existing bound float methods remain callable.

The generated dynamic-float fixture uses isolated test slots; it runs its loader,
host assignments and float GPU pack. Descriptor-aware authored/cache atomicity
is tested through the exact helper used by Brush for all three scalar types.
It does not prove a configured typed extra kernel through every executor.
New int/bool/checked store methods are native APIs, not yet reflected bindings.
No new runtime has been vendored into the Blender install.
