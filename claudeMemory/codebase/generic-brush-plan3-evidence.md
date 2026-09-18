# Generic brush properties — Plan 3 evidence

2026-09-16. Plan 3 remains in progress. The typed-core slice is complete;
generated declaration registration and typed named working stores are also
complete. Typed extra emission, fixture execution and shader gates are complete.
Checked configuration/bindings and addon-only restoration are complete.
Full prepared execution and input delivery remain open.

## Prepared execution prerequisite

Two fresh reviews are folded into [the prepared-execution plan](../plans/generic-brush-prepared-execution.md).
Its first prerequisite now passes: checked device evaluation reads an explicit
input context without changing cached samples or copying response tables.
Both cached/context paths share the typed arithmetic. The new regression cases
cover exact integer interpolation, float/int/bool parity, duplicate/nonfinite
and absent inputs, signed zero and cache/output preservation on errors.

The addon-only build, [16 native suites](../tests/prepared-context-results.json)
and [exact-DLL Python smoke](../tests/prepared-context-python.log) passed.
Current native DLL SHA256:
defb0e6a8b752036520bb135f7b3a6193a5bc96649d9ac898b311ec25dbdbfc0.
Static native/extra storage coherence and full early preparation remain open.
The property accessor still assigns its owner pointer and can invoke a getter;
the nonmutating guarantee here concerns device evaluation. No runtime vendoring.

## Checked configuration and binding gate

[Reviewed plan](../plans/generic-brush-checked-configuration.md). The Brush API
now checks exact FLOAT32/INT32/BOOL writes and ordered device stacks. Bulk
replacement validates all arrays before committing; configure preserves table,
position and disabled state. Sequential resized curve imports keep the old
table intact and reject evaluation until every sample arrives. Clear or bulk
replacement cancels staging. Failed operations preserve values and generations.

CommandExecutor exposes positive process-unique int32 query tokens, private
canonical index mappings and owned metadata/result snapshots. Wrong executor,
changed Brush/StructDef, stale index generations and failed requeries reject.
Legacy indexed setters retain signatures and use the same canonical mapping.
The Python CommonProperties and UniformProperties adapters validate Python
types and fixed-width selectors before marshalling.

Final fixture-enabled validation (2026-09-16):

- `node make.mjs build native --kernels-extra '../brushes;tests/assets/typed_extras' -j 8`
  passed; [build log](../tests/checked-bindings-build-final.log).
- `python claudeMemory/scripts/run_typed_engine_gate.py --prefix checked-bindings-final
  --extended-registration --named-storage --typed-extras --configuration`:
  16/16 suites passed; [results and executable hashes](../tests/checked-bindings-final-results.json).
- [Actual Python binding gate](../scripts/test_checked_brush_bindings.py) passed:
  exact large integers, int32 endpoints, bool thresholds, ordered mixes, caller
  array preservation, atomic failures, pending uploads, query lifetime and every
  common-property stack operation. [Result](../tests/checked-bindings-python-final.log).
- [Declaration generator](../scripts/generate_checked_brush_bindings.py) produced
  15 Python and 74 TypeScript files with the checked methods and owned result
  descriptors. [Artifact hashes](../tests/checked-bindings-generated-final/results.json).

Both binding commands assert the absolute loaded DLL in fresh processes.
Fixture DLL SHA256:
12a5f9b6845d6bf39211427d884fc2136b307d0a54ec616321f793cadf02584b.
Reflection protocol ABI remains 1; reflected object sizes/offsets are discovered
at runtime. TypeScript declarations were generated, not runtime-tested.

The first binding build exposed unqualified Vector names and the Binder's
unsupported const-vector references. Read-only native implementations now have
non-const reflected wrappers, with caller-array preservation asserted in Python.
The first Python attempt reused a fixture declaring invert static for the common
fallback test; a fresh Brush correctly exercises that fallback. Failure logs
remain alongside passing reruns. Task-file whitespace checks pass; unrelated
engine/TODO.md whitespace is preserved. No runtime is vendored into Blender.

Addon-only restoration passed with `node make.mjs build native --kernels-extra
../brushes -j 8`; [build log](../tests/checked-bindings-addon-build.log).
The restored [16-suite gate](../tests/checked-bindings-addon-results.json) covers
the compiler boundary branch without the runtime fixture. The enhanced legacy
[Python smoke](../tests/checked-bindings-addon-python.log) checks common float
and bool scalar/stack operations as well as existing named floats and metadata.
Restored DLL SHA256:
0261ba6c7c8cb053907f22d74440a9b4de552f3244732f406f22944c514895eb.

Shipping Python/TS declarations were regenerated from that restored library.
[Raw and formatted artifact hashes](../tests/checked-bindings-addon-generated/results.json).
[Formatting helper](../scripts/format_checked_typescript.mjs) follows
engine/tools/genTS.ts's header, Prettier options and native line-ending rules;
it leaves unrelated hand-written files and generated shaders intact. Its first
sandboxed launch could not resolve pnpm's linked dependency; the authorized
run used the installed dependency successfully. `pnpm --dir engine/typescript
exec tsgo --noEmit` passed, and all generated Python declarations parse. This
adds declaration checking, not TypeScript runtime transport acceptance.

The configuration test target was moved outside the Vulkan-only test block; it
links brush/spatial/mesh and needs no debug renderer. The dispatcher rebuild and
focused rerun passed with no binary changes: checked-configuration-test-wiring
build/results logs. A separate Vulkan-disabled build was not run.

Gate scope: authored property configuration, checked evaluation and binding
transport. Prepared execution must still adopt static/native working state,
reject invalid settings before any geometry/undo mutation, and evaluate region
parameters before spatial selection. Configuration counters do not detect raw
field/vector edits. Headed modal acquisition and per-dab delivery remain open.

## Typed extra compiler and execution gate

[Reviewed plan and detailed evidence](../plans/generic-brush-typed-extras.md).
FLOAT32/INT32/BOOL extras now generate typed slots/defaults, evaluated loads and
host writes. Shared C++/registry validation rejects duplicate declarations and
native/context semantic mismatches. Boolean wire values use uint32 0/1, with
WGSL conversion at reads; integer defaults and packed bytes preserve 16777217.

The fixture-enabled native build passed and all 15 suites passed, including
actual mesh/grid program geometry for float/int/bool device dynamics, authored
value preservation, host assignments and packed byte/canary checks. The global
registry branch is required by the runner. [Results and executable hashes](../tests/typed-extras-results.json).
DLL SHA256: 5957c22e614614fc36f1465f44a6c066ad0292b4dc0ce5e320c1174a4d72bde5.

The explicit fixture WGSL/SPIR-V validation and 16 semantic CLI rejection cases
passed, plus cross-kernel compatible sharing/conflicts. [Compiler commands and
outputs](../tests/typed-extra-compiler/results.json), [tool/artifact hashes](../tests/typed-extra-compiler/hashes.json).

Scope: direct native typed-core configuration and actual generated program
consumers. Legacy typed configuration, complete preflight, GPU extra runtime
dispatch/context marshalling and headed modal delivery remain open. No runtime
was vendored into Blender. The addon-only native rebuild passed and its restored
15-suite gate passed (14 regressions plus compiler boundary checks, without the
typed runtime fixture). The exact-DLL legacy Python smoke passed too.
[Restored gate results](../tests/typed-extras-addon-results.json),
[Python smoke](../tests/typed-extras-addon-bindings.log).
Restored DLL SHA256: a0ef50a2a74aadb2ae1669d35e53243f32b48ac0eb30b7a96acb060616eb0ee3.

## Typed named working stores

Completed [the reviewed storage gate](../plans/generic-brush-named-storage.md).
Brush now has separate FLOAT32, INT32 and BOOL working stores with explicit
initialized presence. High-slot writes preserve lower-slot default installation.
Public checked writes validate before changing authored properties or working
values; inherited, read-only, wrong-type, range and schema failures preserve both.
Static/context slots retain working-only semantics. Generated evaluation and host
assignments use internal working setters. Registry generation validates full
scalar declaration compatibility and supplies immutable slot descriptors.

Final commands:

- `node make.mjs codegen`: passed; ../tests/typed-named-storage-codegen.log.
- `node make.mjs build native --kernels-extra ../brushes -j 8`: passed;
  ../tests/typed-named-storage-build-verified.log.
- `python claudeMemory/scripts/run_typed_engine_gate.py --prefix
  typed-named-storage --extended-registration --named-storage`: 14/14 passed;
  [results and hashes](../tests/typed-named-storage-results.json).
- `python claudeMemory/scripts/test_named_storage_binding_smoke.py`: passed;
  [exact native DLL and metadata](../tests/typed-named-storage-bindings.log).
  DLL SHA256: 947fab064364abfc3a8399fe9b37cf6bba1049442a2f11b878232a22e7bdd9d1.

The 14-suite run includes the confirmed extra-kernel registration branch; the
earlier generated-registration run had compiled that branch out. This run
supersedes the earlier evidence for extra working-slot preservation.

The fixture executes a generated dynamic float loader, host simple/compound
assignments and float uniform packing. Its isolated slots do not belong to the
shipping registry; typed authored/cache updates use the same descriptor-aware
helper as Brush. Integer 16777217/extrema, bool true/false presence, invalid
transport and failed property writes are native checks. The Python smoke proves
existing float calls and exact metadata transport, not new typed configuration
bindings. No engine runtime was vendored or installed for this gate.

Next: typed extra emission supplies real INT32/BOOL kernels for the reviewed
[checked-configuration gate](../plans/generic-brush-checked-configuration.md).

## Generated registration gate

The reviewed [generated registration plan](../plans/generic-brush-generated-registration.md)
is complete. Scalar manifests retain default presence and exact double metadata.
Native FLOAT32/INT32/BOOL loads use their actual types. Program declaration
registration is atomic across commands, runs on every invocation, and gathers
metadata with a scratch Brush so rejected programs do not allocate live extra
slots. Failure propagates through mesh/grid batches and addon scalar/preview
calls. Static native values retain their existing authoritative working fields.

Commands (2026-09-16):

- `node make.mjs codegen`: passed; ../tests/typed-generated-registration-codegen.log.
- `node make.mjs build native -j 8`: passed;
  ../tests/typed-generated-registration-build-gate.log.
- `python claudeMemory/scripts/run_typed_engine_gate.py --prefix
  typed-generated-registration --extended-registration`: 13/13 passed;
  [commands and executable hashes](../tests/typed-generated-registration-results.json).
- `python claudeMemory/scripts/test_stroke_registration_errors.py`: 5/5 passed;
  ../tests/typed-generated-registration-addon.log. Actual function bodies execute
  with fake native boundaries, checking cancellation and preview rollback.

The native gate includes wrong-type registration at real mesh/grid program and
batch entry points, both command orders, empty-first-dab/changed-program cases,
dyntopo enabled, exact position bytes, topology/undo state, common authored
values, and live extra-slot allocation. All built-ins register in both orders
and accumulation variants. Integer metadata above 2^24 and omitted defaults
have separate regressions. The initial two failing geometry assertions compared
Vec addresses; corrected byte comparisons passed with the same tested behavior.

Limits: this gate does not deliver a new Python DLL, typed extra execution or
complete early preparation. Addon node filtering/preview snapshots still precede
native checks. Full configuration validation and real modal input delivery
remain required before Plan 3 closes. Native tests use the popup-suppressed
launcher established after the earlier DLL-loader failures.

## Typed core

Implemented in engine source/props:

- FLOAT32 mixes/interpolates in float32; INT32/BOOL use float64 and convert
  after the whole ordered stack. Declared bounds apply only after the stack.
- Checked failure for nonfinite bases/configuration or invalid ranges; finite
  arithmetic overflow skips that layer. Integer rounding uses ties away from
  zero and saturates before casting; bool uses >= .5.
- Every input context clears sample validity. Last delivered samples win,
  including nonfinite samples and mixed direct-vector/push delivery.
- Authoring configuration updates existing devices in place; imported duplicate
  stacks reject atomically. Disabled layers preserve their tables/settings.
- Lookup evaluates the stored type before destination coercion, guards integer
  destination overflow, and returns the caller default on checked failure.
- Numeric properties initialize bounds/step and copy authored values, metadata,
  callbacks and independent dynamics tables. Copies discard transient samples
  and reacquire owner bindings at lookup.

The two fresh numeric/seam reviewers reviewed the plan and implementation.
Their destination-overflow, mixed-duplicate and discriminating-test findings
were folded into [the reviewed plan](../plans/generic-brush-typed-core.md).

## Commands and results

Run from engine/ with the required dispatcher:

| Command | Result / evidence under tests/ |
| --- | --- |
| `node make.mjs build native -j 8` | Passed; typed-core-build-final.log |
| Repeat build after final source edits | Up to date; typed-core-build-check.log |
| `node make.mjs test test_props_typed_dynamics` | Exit 0; typed-core-test_props_typed_dynamics.log |
| `node make.mjs test test_props` | Exit 0; typed-core-test_props.log |
| `node make.mjs test test_brush_dynamics` | Exit 0; typed-core-test_brush_dynamics.log |
| `node make.mjs test test_brush_uniform_validate` | Exit 0; typed-core-test_brush_uniform_validate.log |

The new suite covers all mix modes, declared ranges, signed ties, INT32 extrema,
bool thresholds, deferred conversion/clamping, missing/disabled/nonfinite
samples, negative-zero empty identity, input/config duplicates, rejected tables,
source-before-destination dispatch and getter-backed independent property copies.
The 16777217/{.2f,.9f}/.1f case yields 4529849, distinguishing float64 response
interpolation from float32's 4529848. Float overflow retains the prior value.
Actual native compile commands contain `-ffp-contract=off`.

The first compilation caught an ambiguous test-only litestl string comparison;
explicit string operands fixed it. Existing unrelated compiler warnings remain.
The sandbox initially could not read pnpm hardlinks, so authorized dispatcher
runs used existing dependency/cache access; no dependency install was needed.

No Python DLL was rebuilt or vendored for this core-only gate. Generated ranges,
typed Brush APIs, command preflight, complete kernel execution and modal input
delivery are not proven by these tests. The publicly writable Dynamics tables
are checked during evaluation; later validated upload work must address repeated
validation cost without assuming callers cannot mutate public data. Unsupported
FLOAT64 receives no new dynamics capability. Engine TODO.md and the dirty litestl
submodule were preserved; diff checks on task files pass.

## Checked authored-access foundation

The next reviewed integration slice now has exact-type local writes and checked
reads/evaluation in StructProp. The new methods accept only FLOAT32, INT32 and
BOOL; finite double transport is validated before integer/bool conversion.
Local-only writes cannot modify an inherited default. Read-only, missing,
wrong-type, out-of-range and nonfinite writes leave authored state unchanged.
Checked evaluation preserves its output argument on failure instead of silently
substituting a default. Legacy accessors remain separate compatibility paths.

`node make.mjs build native -j 8` passed (`typed-access-build.log`). The new
`test_props_checked_access` and the four typed-core/legacy suites all returned
exit 0, recorded in `typed-access-test_*.log`. Tests include exact 16777217,
both int32 overflows, fractional integers, nonfinite bool transport, parent
presence/value preservation, actual bound-owner setters and explicit dynamic
failure. These are native boundary tests; actual Python binding validation
remains an upcoming gate.

## Reviewed foundation completion — 2026-09-16

The final checked API rejects inherited bound/getter-backed values with
ERROR_INVALID_OWNER because StructDef does not carry the declaring owner.
Tests use distinct parent/child objects and verify no callback, owner-pointer,
value or output mutation on rejection. Ordinary unbound inherited defaults work.

Native Brush member descriptors now derive storage types from C++ declarations
and list semantic dynamics eligibility explicitly. C++ emission rejects wrong
types/array shapes, forbidden enum/ID dynamics and reserved execution uniforms.
Parser IR distinguishes explicit annotations and rejects contradictory
@static/@dynamic. Unannotated planeSide remains nondynamic. The reserved-name
fixtures include nonaccum/grab_dab_gen, found by the implementation reviewer.

Final build: `node make.mjs build native -j 8`, exit 0, retained in
`typed-foundation-build-final.log`. Then all eight dispatcher suites returned 0:

- test_props_checked_access
- test_sbrush_member_types
- test_props_typed_dynamics
- test_props
- test_brush_dynamics
- test_brush_uniform_validate
- test_sbrush_attr_writes
- test_gpu_uniform_pack

Logs use `typed-foundation-<suite>.log`; silent success is an exit-code gate.
The result manifest `typed-foundation-results.json` records executable hashes.
Task-file diff checks pass. Existing built-in declarations and NUDGE remain
compatible; no generated kernel output changed in this foundation.

This completes checked access and native declaration validation only. Complete
descriptor registration, precise manifest defaults/ranges, typed stores, bool
shader packing and actual typed generated execution remain in the reviewed
integration slice. Its corrections specify upstream preflight, explicit raw
caller compatibility, command state and region selection. Input timestamps and
modal delivery follow; independent command inheritance/hooks remain Plan 6.

## Atomic scalar declaration foundation — 2026-09-16

StructDef now owns immutable scalar declarations with exact double defaults,
presence flags, bounds and dynamics eligibility. Batch validation rejects all
conflicts before property/metadata creation. New FLOAT32/INT32/BOOL properties
are explicitly unbound; adoption preserves authored values, stacks and owners.
Checked access revalidates declarations against mutable storage and current
inheritance, rejecting incompatible raw range changes or property replacement.
Float bounds round inward and writes check converted values; integer/boolean
domains intersect storage bounds. New absent defaults require a valid zero.

Two fresh plan reviews and an implementation review are folded into
[registration plan](../plans/generic-brush-registration.md). Native build
`node make.mjs build native -j 8` passed. All nine suites passed through the
dispatcher: test_props_declarations plus the eight foundation suites above.
Evidence includes exact 16777217/int32 endpoints, bool/fractional domains,
nonfinite and empty ranges, float rounding/underflow, atomic failures, reverse
conflicts, descriptor ownership, owner sentinels, callbacks, inherited shadows
and parent replacement. The new suite uses normal engine allocation checks.

Build log: tests/typed-declarations-build-final.log. Result manifest with binary
hashes: tests/typed-declarations-results.json. Individual logs are
tests/typed-declarations-test_*.log. No Python DLL build or vendoring yet; generated
registration and complete typed storage/execution still remain open.

## Completion gate — 2026-09-17

Plan 3 is complete. The final implementation exposes checked prepared mesh/grid
standalone and program execution, typed command overrides, fresh per-dab batch
samples, and explicit raw validation for paths outside prepared capabilities.
Actual modal input uses acquisition timestamps, independent channel presence,
arc-length interpolation and release flushing. See [input API and limitations](brush-input-delivery.md).

Two fresh adversarial plan reviews and subsequent implementation audits found
batch failure state leakage, unchecked cage rejection, stale preview preflight,
missing diagnostics, empty-call validation and synthetic-move backlog loss.
All were corrected. Cage's current-input entry also retains Ctrl inversion;
its regression checks retained tilt and invalid-buffer rejection.

### Tests actually run

All commands used the existing bundled Python and dialog-safe launchers. Native
builds/tests use `node make.mjs`; shader checks use the existing compiler/Tint/SPIR-V
validator. No dependencies were installed and no user Blender process was closed.

| Gate | Result and evidence in claudeMemory/tests |
| --- | --- |
| Native fixture build, addon + typed fixture kernels | PASS; plan3-fixture-build-final.log |
| Fixture native gate, all 17 suites | PASS; plan3-completion-fixture-results.json; requires all eight public typed input geometry/undo markers |
| Restored addon-only native build/gate, all 17 suites | PASS; plan3-addon-only-build.log, plan3-cage-build-final.log, plan3-completion-addon-results.json |
| Cage/multires attributes | PASS; plan3-final-multires-attrs.log, including current-input inversion/tilt and invalid mirror pointer |
| Exact fixture DLL Python configuration | 11 checks PASS; plan3-final-python-bindings.log |
| Public typed batch-program Python geometry | PASS; plan3-public-inputs-python.json/.log; exact 16777217, bool .49/.5 and missing-after-present samples |
| Restored addon-only Python smoke | PASS; plan3-addon-python-smoke.log |
| Generated Python/TypeScript declarations and TS checking | PASS; plan3-final-bindings/results.json, plan3-final-binding-generation.log, plan3-final-typescript.log |
| WGSL/SPIR-V and compiler rejection gates | PASS; typed-extra-compiler/results.json and plan3-final-compiler.log |
| Actual spacer/sampler | 7/7 PASS; plan3-stroke-inputs.log |
| Addon rejection boundaries | 5/5 PASS; plan3-addon-rejections.log |
| Actual headed Event acquisition/RNA/simulation | PASS; plan3-event-inputs.json/.log; double precision, independent presence, invalid input atomicity and shared INBETWEEN conversion |
| Actual headed modal delivery in staged runtime | 8/8 PASS; plan3-final-modal-inputs.json/.log and plan3-modal-samples.json; 27 identical samples per case across mesh/grid, Python/batch and queued/delayed handlers |
| Headed cancellation/next stroke/window close | PASS; plan3-modal-cancel.json/.log |
| Frozen file/external asset settings and ten geometry oracles | Bit-exact PASS; plan3-baseline-verify.json/.log and plan3-geometry-verify.json/.log; original arrays were not regenerated |
| Existing mesh/grid explicit-dab batch parity | PASS; plan3-batch-parity.json/.log; original mesh exact/grid 1e-6 gate retained |
| Python runtime build, stage and enabled-by-default verification | PASS; plan3-runtime-build.log, plan3-runtime-stage.log |
| Packaged self-contained runtime smoke | PASS; plan3-package-smoke.json/.log |

Native public geometry coverage is mesh/grid x standalone/program x single/batch
using a real generated float/int/bool kernel. It includes exact large integers,
bool thresholds, zero-edge mapped falloff, missing channels, invalid batches,
nonfirst and empty rejection, repair, expanded spatial regions and undo/redo.
Independent per-command stacks remain Plan 6. Unsupported host/kernel modes
reject configured dynamics they cannot consume; there is no retry after failure.

Reproduction commands for the principal gates:

```
# In engine, build fixture then run the gate from the addon root:
node make.mjs build native --kernels-extra "../brushes;tests/assets/typed_extras" -j 8
python claudeMemory/scripts/run_typed_engine_gate.py --prefix plan3-completion-fixture --extended-registration --named-storage --typed-extras --configuration --prepared-execution
# Restore native addon-only and repeat with --compiler-boundaries replacing --typed-extras.
node make.mjs build native --kernels-extra ../brushes -j 8
node make.mjs build python --kernels-extra ../brushes -j 8
# In addon root:
node tools/build-blender-dist.mjs --skip-blender --skip-engine --build-dir C:/dev/blender/build_windows_x64_clang_RelWithDebInfo --config Release
python claudeMemory/scripts/run_plan3_blender.py --script claudeMemory/scripts/test_modal_inputs.py --prefix plan3-final-modal-inputs --marker PLAN3_MODAL_INPUTS_PASS --headed --timeout 110
```

### Runtime identities and limits

[Completion manifest](../tests/plan3-completion.json) asserts all final gate
manifests and equal built/installed/workspace runtime hashes:

- Blender: cd15fa6c69b5a17a408a534c260f918a085e7efe792b542545c6319016153673
- Fixture DLL: 4589006e4e6c860ba658a8a5b9de959eafa490470ba1d4690cb05f1e6d3f136c
- Restored native DLL: 26af66125c314935a50cc3b6a31737050a6f3a47fa613b2922df086b7c9331c7
- Packaged Python DLL: 4e5961047db841289d9d52c6fd1b48eef689fd1e60c0c1b09204646199441a4e

The matching runtime is vendored in both the workspace and existing Blender
installation. The test-only typed kernels are absent from that restored runtime.
The installed fork requires this task's event API and Plan 2 owned-curve changes.
Windows acquisition producers are audited and built; other platforms retain
conservative unavailable time/tablet channels. Cocoa/Wayland synthetic-warp fixes
were source-reviewed, not compiled on those platforms. TS declaration checking
is not a claim of TS runtime transport testing. Prebatch raycasts are still an
independent algorithm; sample grouping is invariant, but general evolving-surface
raycast geometry equivalence is not claimed. Unrelated working-tree edits remain.
