# Plan 6 progress and evidence

Plan 6 remains in progress; the generic stroke/UI path remains disabled by default.
Implementation follows [the reviewed plan](../plans/generic-brush-plan6-integration.md).

## Independent command-stack boundary — 2026-09-17

Fresh native-execution and host-inheritance adversarial reviews identified cold
uniform evaluation, all four raw/declaration rejection guards, masked authored
corruption, batch overlay restoration, target-specific stable identities, explicit
empty stacks, owner-free responses and candidate program publication. All are
incorporated into the implementation and test scope.

Implemented:

- Native `BrushDynamicsOverride`, checked replace/remove, shared atomic parallel
  buffer decoding, independent stack selection before region preparation, and
  explicit rejection by both raw executors/declaration paths.
- Additive UTF-8 C APIs and Python bulk stack transport. Analytic parameters stay
  double. No per-dab buffer upload or input-record layout change.
- Host `commands.py`: immutable normalized execution values/layers, explicit
  brush/command/default parents, stable-ID ancestry independent of execution order,
  target defaults for absent parent IDs, cycle/type/duplicate validation, and a new
  native program candidate published only after its complete upload succeeds.
- Owner-aware `prepare_stack`: sample from stack_owner rather than value_owner;
  results retain only primitives and immutable PreparedResponse data.

Bounded command integration gate completed. [Verified manifest](../tests/plan6-command-gate.json).

Validation:

- Seven pure command resolver tests, eleven existing ownership tests and six
  response-cache tests pass (24 total).
- Actual DLL command transport: five check groups pass, including cold typed
  geometry, changing/missing input, exact analytic thresholds, failed replacement,
  candidate rollback and raw explicit-empty rejection.
  [DLL evidence](../tests/plan6-command-bindings.json).
- Fixture native gate: 16/17 passed initially. The typed suite's only failures
  were two hard-coded seven-dab assertions after three new accepted test dabs;
  corrected to ten. Both revised geometry suites pass, including multi-leaf mesh
  and grid programs with independently growing radii and exact undo/restoration.
  [Initial gate](../tests/plan6-command-fixture-results.json),
  [revised suites](../tests/plan6-command-fixture-final-results.json).
- Real Blender custom-curve ownership: three checks pass for opposed effective
  value/stack owners, stale-reference rejection and immutable snapshots surviving
  curve edits/cache retirement. [Assertions](../tests/plan6-stack-owners.checks.json),
  [safe launcher](../tests/plan6-stack-owners.json).
- Existing actual DLL Common/Uniform APIs pass after decoder extraction.
  [Log](../tests/plan6-checked-bindings.log).
- Headed real modal mesh/grid × Python/batch × queued/delayed input matrix passes
  all eight cases using the new fixture DLL.
  [Safe launcher](../tests/plan6-command-modal.json).

- Final addon-only build and all 17 applicable native suites pass, including
  independently growing command radii and explicit empty smooth strength against
  inherited main pressure. [Final native gate](../tests/plan6-command-addon-results.json).
- Python/TypeScript declarations regenerated from the addon-only DLL; standard
  formatting and TypeScript type checking pass. The matching Python runtime was
  rebuilt and staged, and registration/package provenance checks pass.
- Staged command APIs pass four check groups, including the actual legacy mesh/grid
  batch wrappers rejecting stack-only empty overrides on zero-dab and miss paths
  without altering the host overlay. [Package assertions](../tests/plan6-packaged-api.checks.json),
  [package smoke](../tests/plan6-command-package-smoke.json).

No fork edits were needed. The final native engine SHA-256 is
`c7b0af96bec602a29155c10447d9ec7b376c9df7b763246429b5aa4ea90f3fd2`;
staged Python DLL SHA-256 is
`1847947f3fc31a7bd9c1ead24112ef5364b065a06c1ef2fdf8393d0dc2370b32`.
The background package smoke does not map wgpu_native; GPU loading is not claimed
by that check. The headed modal matrix covers the existing actual sculpt path.

## Remaining Plan 6 work

Normalized command inputs are an internal boundary, not yet the full stroke
snapshot adapter. Gates B/C still need native/legacy translation and capabilities,
paired size/projection semantics, every host consumer, supported unbounded and
host-hook command paths, and command-specific automasking caches. Broad Plan 6
task boxes remain open until their complete scopes and headed gates pass.

The immutable authoring prerequisite is complete below. Semantic snapshots still
need execution translation and adoption by the actual stroke consumers.

## Immutable authoring snapshot prerequisite — 2026-09-17

The user explicitly approved the previously blocked read-only OpenAI CLI review.
The reviewer's sandbox rejected local file reads, so the review used an explicit
source bundle through standard input with no tool execution. The independent
[owner/domain review](../tests/plan6-snapshot-owner-review.md) found no blocking
contradictions. Its opposite-mode SIZE, warm native-cache stale-reference, and
empty/generated stale-store refinements were folded into the
[plan](../plans/generic-brush-plan6-snapshots.md) before implementation, alongside
the earlier [catalogue review](../tests/plan6-snapshot-catalogue-review.md).

Implemented:

- `snapshots.capture` resolves fresh at a main-thread boundary and returns only
  immutable scalar/domain/source/presence, capability diagnostics and prepared
  curve data. It retains neither stores/RNA nor inheritance/curve references.
  Unknown/duplicate IDs and unavailable dynamic stacks reject the candidate.
- Native SIZE captures the effective value owner's pixel diameter, world
  diameter and mode together. Both active and dormant values use their own RNA
  domains; strict primitive types and active-value/domain agreement are checked.
  Pixel size remains INT32 even though the semantic definition is FLOAT32.
- Stack sampling continues to use the independent effective stack owner. Static
  unavailable aliases retain that capability separately from their empty tuple.
  No execution capability is activated by capture.
- A separate DLL-independent engine catalogue adds four static view-normal and
  backface properties, using exact engine float32 defaults, radian angle metadata
  and generic Brush/Scene storage. Production now has 27 definitions and still
  62 curve declarations; the frozen legacy catalogue/manifest loop is unchanged.

[Verified manifest](../tests/plan6-snapshot-gate.json) is generated by
`claudeMemory/scripts/record_plan6_snapshot_gate.py`. Validation commands use
`run_plan3_blender.py --script <script> --prefix <prefix> --marker <marker> --timeout 150`:

| Script | Prefix / marker | Result |
| --- | --- | --- |
| `test_plan6_snapshots.py` | `plan6-snapshots` / `PLAN6_SNAPSHOTS_PASS` | 93 checks pass |
| `test_plan6_snapshots_fresh.py` | `plan6-snapshots-fresh` / `PLAN6_SNAPSHOTS_FRESH_PASS` | 5 groups pass |
| `test_frozen_authoring.py` | `plan6-snapshots-frozen` / `FROZEN_AUTHORING_OK` | 77 checks pass |

New checks exercise all four value/stack owner combinations, opposite Brush/Scene
size modes, malformed dormant values, native/custom curve ownership, warm-cache
staleness, empty/generated stale stores, no allocations on reads, owner deletion,
file restoration, saved inheritance and dormant locals, and repeated DLL-off
registration. Completed snapshots remain immutable after owner changes and cache
retirement. The three existing pure suites pass all 24 tests. The gate verifies
installed source equality and records Blender/engine hashes. No fork or engine
changes or native rebuild were needed for this slice.

Two fixture corrections preceded the final passing gate: native customization
preserves its dormant mapping unless reseeding is explicit, and direct addon
unregister/register tests must leave the addon registered for Blender shutdown.
The dialog-safe launcher correctly rejected the latter's teardown traceback
despite its process returning zero. Final logs have no tracebacks.

This is an authoring snapshot prerequisite, not Gate B or full Plan 6 completion.
Projection, typed unit-conversion ordering, execution capability activation,
consumer adoption and command-specific host/topology/automasking work remain.

## Typed semantic evaluator — 2026-09-18

The user approved CLI use for all remaining Plan 6–8 reviews. Independent
[numerical](../tests/plan6-domains-numerics-review.md) and
[integration](../tests/plan6-domains-integration-review.md) reviews identified
fractional/nonrepresentable range endpoints as a blocker. The
[plan](../plans/generic-brush-execution-domains.md) now canonicalizes INT32 bounds
inward with ceil/floor, FLOAT32 bounds to inward representable floats, and BOOL
bounds to admissible endpoints. This agrees with native scalar declaration
normalization in `engine/source/props/prop_declarations.cc`.

`brush_properties/evaluation.py` compiles immutable snapshots into host evaluators.
Native input narrowing, table interpolation, analytic thresholds, ordered mixing,
overflow retention and final typed conversion match the native evaluator. Native
spacing remains integer percent through evaluation; snake remapping and strength
compensation occur afterward. Semantic SIZE requires a projected object-space
radius and applies the shared stack in the radius domain. The module does not
activate execution capabilities or substitute for native command preflight.

[Verified manifest](../tests/plan6-domains-gate.json), generated by
`record_plan6_domains_gate.py`, records:

- `test_plan6_evaluation.py`: six independent expectation tests pass.
- `test_plan6_evaluation_native.py`: 543 actual `UniformProperties` comparisons
  pass, with FLOAT32 bitwise equality and exact INT32/BOOL values. Deterministic
  seed 9182026 covers randomized stacks plus signed zero, subnormals, neighboring
  step thresholds, overflow, disabled/missing samples and narrowed domains.
  Native clang explicitly disables floating-point contraction. Fixture DLL hash
  is recorded before the normal native configuration is restored.
- `test_plan6_evaluation_blender.py`, launched through `run_plan3_blender.py`
  with prefix `plan6-domains-blender` and marker `PLAN6_DOMAINS_BLENDER_PASS`:
  six groups pass. Actual Scene/Brush snapshots exercise native/custom curves,
  typed conversion order, dormant local values and paired size. Eight hundred
  warm evaluations survive owner deletion/cache retirement without new bakes or
  authoring access.
- Dispatcher fixture and addon-only builds pass. Normal addon-only configuration
  is restored; installed evaluator source equality and runtime hashes are checked.
  No native engine source or fork changes were needed.

This completes the evaluator prerequisite only. The explicit consumer audit and
all remaining Plan 6 integration/UI/migration gates are still open.

## Prepared BSMOOTH gate — 2026-09-18

Two independent CLI reviews found no blockers. Their acceptance refinements are
incorporated in the [bounded plan](../plans/generic-brush-prepared-boundary-smooth.md).
The [verified manifest](../tests/plan6-bsmooth-gate.json) records current test-binary
and packaged DLL hashes. No public ABI or generated binding declarations changed.

Mesh execution accepts only the classified invariant boundary hook and exact
read-only vertex INT boundary attribute. It refreshes dirty classes before
freeze, after complete scalar/command validation, even after an initial missed
or zero dab. Mesh attribute consumers without a preparation hook remain rejected.
Grid BSMOOTH uses the existing zero/interior column, with no channel/mirror creation.

- All 17 native suites pass. Added actual BSMOOTH standalone/program comparisons
  cover live/CSR mesh, sharp/seam flags, varying projection, independently larger
  secondary radius/stacks, grid immediate/deferred normals, exact geometry/store
  undo/redo, dirty frozen topology and atomic late rejection. A freshly refreshed
  reference supplies the missed-first-dab oracle independently of raw first-dab hooks.
- Dispatcher native and Python builds pass; the matching runtime is staged.
- `test_modal_inputs.py --autosmooth` passes all eight installed-package cases:
  mesh/grid, Python/batch and queued/delayed samples. Recorded 124 native prepared
  program calls. Batch calls force policy 1, so raw fallback fails acceptance.
- The existing eight-case headed modal matrix and packaged DLL provenance smoke
  pass. Safe Blender launcher used throughout; no missing-DLL popups were observed.

This enables actual autosmooth in the existing supported path. It does not yet
wire generic authoring snapshots into all consumers or close the remaining
non-accumulating, anchored, dyntopo, cavity, attribute and host-stage capabilities.

## Prepared non-accumulating gate — 2026-09-18

The mesh and grid CLI reviews found no blockers and clarified the existing
additive displacement semantics, growth coverage and executor-specific capture
policies. See the [reviewed plan](../plans/generic-brush-prepared-nonaccum.md)
and [verified manifest](../tests/plan6-nonaccum-gate.json).

Both prepared factories now instantiate AccumOrig for eligible non-accumulating
commands, using a scratch Brush and fresh command so manifests cannot duplicate
or publish defaults. Relaxation stages stay live; all other capability guards
remain. Native APIs and reflected struct layouts are unchanged.

- All 17 native suites pass, including the preceding BSMOOTH gate. Non-accumulating
  DRAW/BSMOOTH match independent raw references on mesh and grids. The reference
  with accumulation enabled demonstrably differs, so the test distinguishes
  the selected execution template.
- Tests inspect the displacement-derived base after DRAW, smooth and another
  DRAW, plus a second stroke. They cover newly entered leaves, both mesh capture
  slots, live/CSR neighbors, immediate/deferred grid normals, exact undo/redo,
  and invalid later commands before and after displacement pages exist.
- Native/Python dispatcher builds pass. The matching DLL is staged. Sixteen
  installed headed cases cover draw/autosmooth, mesh/grid, Python/batch and
  queued/delayed input. Each records actual accumulate-off stroke setup. The
  248 prepared calls and forced batch policy prohibit raw fallback.
- The package smoke passes with dependency/DLL provenance. No fork change.

Mesh stroke generation remains host-owned, as before; tests explicitly advance
it through setStrokeGen. Grid beginStep advances its own generation. Remaining
Plan 6 consumer integration and other command capabilities stay open.

## Prepared MASK and finer undo gate — 2026-09-18

[Verified manifest](../tests/plan6-mask-gate.json) records the final binaries,
installed runtime and launcher evidence. Both native and Python dispatcher builds
pass and the matching package is staged. No Blender fork edits or public C ABI
changes were needed for this slice.

- All 17 native suites pass. A new regression first reproduced coarse mask edits
  leaving authored finer masks changed after undo. The fix captures occurrence-grid
  blocks at allocated finer levels and owns the complete state of formerly absent
  levels. Bitwise store restoration, nonuniform masks, independent bilinear
  interpolation, seam replicas, allocated/absent/allocated chains, compressed
  storage, debt, rebuilds, replacement identities and cleanup now pass.
- Channel and level tokens are runtime-only; name reuse cannot redirect old bytes
  or debt. Leaf mask capture handles replacement during an open step. Coarse
  capture indexes both channel and grid, leaf capture indexes position/mask
  membership, and seek groups authored-channel refreshes once. Capture-only
  indexes are released at close. Forty-channel overlapping-capture tests pass.
- GridStroke_undoBytes supplies retainedBytes to the existing undo.push consumer.
  It reserves stroke-created finer payload at push time, before undo moves that
  allocation into history. bytes remains the documented value-payload metric;
  retainedBytes includes records/strings and reserve, but excludes allocator slack.
- Twelve installed-DLL mesh/grid comparisons cover MASK and both DRAW/MASK orders,
  per-command pressure/tilt radius, independent/empty strength stacks, inversion,
  absent inputs, one-dab and batch delivery. All match independent raw settings
  exactly. Grid edited/finer masks undo and redo bit-exactly.
- Forty-two installed-DLL checks cover malformed type/component/domain metadata,
  prepared/raw/automatic policy, zero-dab validate-only, late rejection before
  channel creation, missed/zero/non-mask first dab and neutral zero-strength capture.
- Eight installed headed cases cover mesh/grid, Python/batch and queued/delayed
  events. All 124 recorded native calls require prepared execution; mask values
  change while geometry remains unchanged. Package provenance smoke passes.

The initial plan reviews and two implementation-review rounds are retained in
the manifest. Surviving findings were fixed and tested: incarnation identity,
first-channel capture, independent debt authority, absent-safe mirrors, indexed
capture/grouping, real propagation oracles, populated owning-state cleanup,
finer-only transactions and advance undo-budget charging. The reviews' request
for synthetic operation counters was resolved by direct hash-indexed code paths,
multi-channel/overlap tests and exact payload increments, avoiding instrumentation
that would duplicate the implementation. No timing-based complexity claim is made.

Remaining Plan 6 work includes generic consumer adoption and the guarded cavity,
anchored/unbounded, dyntopo, attribute and host-stage paths. Plans 7/8 remain open.

## Command automasking gate — 2026-09-18

[Verified manifest](../tests/plan6-automask-gate.json) closes
[the reviewed slice](../plans/generic-brush-command-automasking.md).

- Nine executor settings resolve authoritative native BOOL/INT32/FLOAT32 values
  without publishing persistent declarations. Command overrides and 256-sample
  cavity tables are copied, validated before mutation, and fully restored.
  Omitted tables inherit the original Brush table independently for each stage.
- Mesh/grid prepared cavity uses complete configuration equality, sparse
  first-contact factors and reusable BFS scratch. Contact uses each command's
  support, including AccumOrig base coordinates; BFS samples live geometry.
  BeginStep, attachment and topology changes retire stale factors. Counter wrap
  clears visit stamps. Warm cache hits perform no BFS; no broad timing or
  constant-time configuration-lookup claim is made.
- Later-command cavity enable ensures current ring1 before mesh freezing.
  Mesh admission requires an open step and stable executor/log ownership. A new
  unbound MeshLog is allowed, matching the real addon lifecycle; an existing
  active-mesh binding must match. Calls after endStep are rejected.
- All 17 native suites pass on current binary hashes. Tests cover authoritative
  sources, invalid disabled settings, owned/inherited tables, independent
  first-contact oracles after deformation, exact new-contact counts, frozen stale
  adjacency, forced token wrap, transaction reset, and full scalar/LUT restoration.
  Nonzero draw/mask/smooth programs match independently scaled-strength oracles
  through accumulating/nonaccumulating mesh and immediate/deferred grids, with
  exact position undo.
- Eight installed DLL geometry comparisons match exactly (maximum error zero).
  Python checked transport, failed replacement, inheritance restoration, raw and
  automatic-fallback rejection at zero/nonzero dab counts, batch/per-dab delivery
  and grid redo pass. Generated declarations and TypeScript checking pass (Node
  production types; the shared config's unavailable Jest types are excluded).
- Eight installed headed cavity cases make 124 required prepared native calls.
  Identical-input cavity-off controls pass; cavity-on heights are
  0.49998–0.50143 times control heights, consistent with the chosen neutral 0.5
  cavity factor. Package smoke and native/Python/installed provenance pass.

Both plan reviews and both implementation reviews are retained. Surviving
findings were fixed or resolved explicitly: native catalogue authority, complete
per-stage inherited LUT snapshots, first-contact support, reusable scratch,
transaction lifetime, token wrap, geometry oracles, raw fallback and restoration.
An omitted manifest range intentionally inherits the catalogue domain; conflicting
explicit bounds are rejected. AttrData::resize with unchanged capacity performs
no page initialization; cache tests verify unchanged BFS counts on warm hits.

The first installed headed run caught the initially unbound MeshLog lifecycle;
the corrected guard and its native unbound-log fixture pass the final gate.
Two buffer-sizing mistakes in the new DLL test export were corrected before the
passing runs. They were test harness errors, not evidence of an engine failure.

Plan 6 still needs generic consumer adoption, viewDir symmetry, anchored/unbounded,
dyntopo, general attributes and host-stage capabilities. Plans 7/8 remain open.

## Compiler prelude prerequisite — 2026-09-18

Implemented conservative no-op host-clamp and FLOAT32 reduce initialization
certificates, including command-level output coverage. Command unsafety remains
monotonic across stages. Generated factories carry a default-false host certificate.
The compiler diagnoses collisions with its internal variable names before emitting
C++; parenthesized named-store writes now use the normal checked working-store
lowering. The raw host callbacks are retained.

The reviewed [unbounded plan](../plans/generic-brush-prepared-unbounded.md) records
the two initial review dispositions. The independent
[compiler source review](../tests/plan6-unbounded-compiler-implementation-review.md)
found the internal-name collision, which is fixed and covered by negative fixtures.

`node make.mjs build native --kernels-extra ../brushes -j 8` passed.
`run_typed_engine_gate.py --prefix plan6-prelude-native --extended-registration
--named-storage --compiler-boundaries --configuration --prepared-execution`
passed **all 17 suites**, including actual generated mesh/grid factory compilation,
raw host no-op/clamp behavior and native reduce-driven geometry.
[Recorded results](../tests/plan6-prelude-native-results.json) include executable
hashes and output. This is the compiler prerequisite, not the full unbounded gate.

The new compiled fixture initially used an unsupported coordinate-component write
and then mismatched `delete` with the engine mesh allocator. Those test errors were
corrected before the passing matrix. The subsequent extent, cutoff, Kelvinlet and
unbounded executor changes require their own new build/test gate; the installed
Blender runtime still contains the last completed automasking gate.

## Nonanchored unbounded execution gate — 2026-09-18

[Verified manifest](../tests/plan6-unbounded-gate.json) closes the
[unbounded slice](../plans/generic-brush-prepared-unbounded.md) and its
[Kelvinlet correction](../plans/generic-brush-kelvinlet-numerics.md).

- Prepared mesh/grid commands snapshot declared or inherited native extent,
  validate numerical support before mutation, and select all leaves when an
  executing stage is unbounded. Program scopes restore dormant native state;
  undeclared extent does not become an eligible command override.
- Prepared batch symmetry reflects grab endpoints and view direction, restoring
  the original frame afterward. Raw and primary images preserve their existing
  frame-write behavior. Direct Python generic symmetry adoption remains open.
- Cavity first contact uses each stage's support and current post-stage geometry.
  Tests include nonconstant factors, strict boundaries, zero/missed first dabs,
  radius growth, DRAW crossing a subsequent unbounded stage's support, and
  configuration-specific reuse. Position undo/redo remains exact.
- Kelvinlet uses scaled arithmetic from the original field equation and a proven
  component bound before restoring large force magnitudes. An independent double
  oracle checks 1,485 scalar endpoint cases, plus extreme multi-component forces,
  opposing finite endpoints and cutoff neighborhoods. Zero radius, force and
  support avoid texture evaluation and geometry bookkeeping.
- Checked float conversion rejects nonzero loss under the caller's FTZ/DAZ mode,
  without changing that mode. Native tests exercise IEEE, FTZ, DAZ and both.
  Installed Blender tests distinguish an already-zero raw reflected value from
  checked double input or intact inherited float bits, which reject atomically.

Validation commands and evidence:

1. `node make.mjs build native --kernels-extra '../brushes;tests/assets/typed_extras' -j 8`
   plus the fixture gate passed all 17 suites. The typed extent fixture runs a
   declaring command before an undeclared Kelvinlet, with restoration and late
   failure checks. Results: `plan6-unbounded-fixture-results.json`.
2. Restored addon-only native build and gate passed all 17 suites. A final
   test-only correction selected a crossing cutoff from fixture geometry;
   `plan6-unbounded-final-case-results.json` reran the affected prepared suite.
   The merged `plan6-unbounded-native-results.json` verifies all current executable
   hashes and retains the actual rerun result.
3. `run_engine_backend_gate.py` passed WGSL and SPIR-V validation. Regenerated
   Python/TypeScript declarations and production TypeScript checking passed.
   Generated declarations are not a TypeScript runtime transport claim.
4. `node make.mjs build python --kernels-extra ../brushes -j 4` and
   `node tools/build-blender-dist.mjs --skip-blender --skip-engine --build-dir
   C:/dev/blender/build_windows_x64_clang_RelWithDebInfo --config Release` passed.
5. Dialog-safe `run_plan3_blender.py` runs passed for
   `test_plan6_unbounded_batches.py` in background and headed Blender (16 exact
   batch comparisons each, independent double field oracle and raw mesh checks),
   `probe_plan6_kelvinlet_denormals.py` (four cases),
   `test_modal_inputs.py --headed --args --cavity` (eight actual modal cases,
   124 required prepared calls), and `tools/smoke_test_package.py`.
6. `record_plan6_unbounded_gate.py` passed, verifying all artifacts and current
   native, installed Blender and staged Python DLL identities. The staged DLL is
   `76c0b7a363691b73fbf2ab58a363cfe4bbf7500dc184f3d3d5589cfd065a8acb`;
   the native test DLL is
   `1f8a38d8fe452226cc0c6351a66aab0f5e13bee3c31143ed17385c2087c37b55`.

The first headed API launcher timed out after all assertions passed because quit
ran during startup. Its evidence is retained under
`plan6-unbounded-installed-headed-startup-timeout.*`; the corrected timer-based
shutdown rerun passed. No production change was needed for that harness issue.

All ten associated review outputs are listed in the manifest. Corrections include
compiler name safety, extent authority, post-stage cavity contact, numerical
overflow bounds, and caller-mode float transport. GPU shader validation does not
claim CUDA/HIP/OpenCL runtime execution. Headed API tests do not claim modal
Kelvinlet adoption. Plan 6 still needs ENHANCE/other command hooks, anchored/preview,
dyntopo, general attributes and generic consumer adoption. Plans 7/8 remain open.

## Prepared ENHANCE gate — 2026-09-18

[Verified manifest](../tests/plan6-enhance-gate.json) closes
[the ENHANCE slice](../plans/generic-brush-prepared-enhance.md).

- The ENHANCE manifest names authoritative native INT32 rings/inner settings.
  Candidates accept full INT32 inputs and normalize with the established formula;
  static stacks and unrelated-command overrides reject. Command execution restores
  the native values. There are 35 builtin member descriptors after these additions.
- Prepared execution binds an executor-owned displacement column. Each normalized
  configuration shares its own first-contact history across command slots; it
  claims only that stage's geometric support after base initialization. It uses
  live stored geometry/normals when a vertex first enters. The prepared path creates
  no `.brush.enhance.*` mesh attributes. Raw behavior remains available.
- Native oracles derive graph distances from edge endpoints independently of the
  production CSR/BFS. They cover mesh live/CSR modes, nonaccumulation, pressure
  geometry, A/DRAW/B/revisit, command order, different leaf partitions, radius
  growth, a later unbounded union, zero/missed first dabs, zero strength, topology
  reset, sparse vertex IDs, counter wrap, failure atomicity and exact undo/redo.
- The native build and all 17 suites pass. The final support test result replaces
  only the prepared suite in the gate manifest; all executable hashes are verified.
  Evidence: `plan6-enhance-native-results.json` and
  `plan6-enhance-support-results.json`.
- `generate_checked_brush_bindings.py --prefix plan6-enhance-bindings --write-source`,
  generated TypeScript formatting, production TypeScript checking and explicit
  WGSL/SPIR-V validation pass. No TypeScript runtime or untested GPU-backend claim.
- Python runtime build, staging and package smoke pass. Background and headed
  `test_plan6_enhance_host.py` each pass 16 prepared cases plus four exact raw
  controls. This exercises real addon `stroke_begin`, standalone/program dispatch,
  required prepared batch execution, native read/write authority, normalization,
  stack rejection, late invalid zero-count preflight and restoration. Multires
  correctly uses its materialized mesh and SLOT provider because ENHANCE's field
  is not a native grid attribute. These are headed addon/API checks, not mouse-modal
  ENHANCE UI adoption.
- `record_plan6_enhance_gate.py` passes with staged DLL SHA-256
  `e50fb3424afba601074198c71221cace4bbfbe97ac1ad1ab8271d47ed3c87a4e`
  and native DLL SHA-256
  `ecf24f21ce39f14e039719e6008a7849137dcb8f043e8476d169d68076c0f3c7`.

The completed semantics review's findings were retained. The user waived all
remaining review requirements; no blocked external review was retried. New test
errors (edge/vector API spelling, omitted stroke generation and appended legacy
overrides) were corrected before the passing gates; temporary traces were removed.
The engine's mistakenly introduced GPL headers were removed in a separate
header-only correction recorded in `engine-header-correction.json`.

Plan 6 still needs anchored/preview behavior, dyntopo, general attributes/remaining
host stages and generic consumer adoption. Plans 7/8 remain open.

## Prepared anchored grab — 2026-09-18

[Verified gate](../tests/plan6-grab-gate.json) and
[implementation contract](../plans/generic-brush-prepared-grab.md).

- Isolated AccumOrigGrab factories now run in both prepared executors. Logical-dab
  stamps advance after successful preparation; mirrors preserve the stamp. The
  addon uses additive image APIs and prepared batches reflect the frame and carry
  mirror identity. Cavity contact uses the same original-position base.
- Positive-radius anchored stages conservatively select all nonempty leaves.
  This handles deformed bounds, radius growth and independent later commands,
  with a documented whole-domain traversal/storage cost.
- All 17 native suites pass. The GRAB oracle independently computes displacement
  on multi-leaf live/CSR meshes and native grids, including command-specific
  radius/strength, pressure radius, symmetry, shrink/growth, failure atomicity,
  exact undo/redo and a second stroke.
- Background and headed installed Blender each pass 24 GRAB cases and 24 anchored
  Kelvinlet cases. Direct calls match required prepared batches. Kelvinlet also
  matches an independent double-precision field oracle. Native grid samples are
  read directly without materializing the optional mesh slot. These are actual
  addon lifecycle/API tests, not a claim of generic modal/UI adoption.
- Generated declarations, TypeScript checking, final native/Python builds,
  staging and package provenance smoke pass. Staged DLL SHA-256:
  `4972891558957f53310c2b0963cd7bb72d2b4c10b50f605786919ff08fa6114b`.
  Native DLL SHA-256:
  `65208ab93c129b3cd499ad632ed79068b046322045289929f90280ff9cee2fc4`.
- Initial fixture/API issues were fixed: the mesh log requires explicit mesh/tree
  undo arguments; old capability assertions rejected now-supported Kelvinlet;
  new C functions need explicit exports; native-grid position checks cannot assume
  a materialized mesh slot. The final gate verifies the actual installed hashes.

Plan 6 still needs preview, dyntopo, general attributes/remaining host stages and
generic consumer adoption. Plans 7/8 remain open. Further reviews remain waived.

## Prepared preview rollback — 2026-09-18

[Verified gate](../tests/plan6-preview-gate.json) and
[implementation contract](../plans/generic-brush-prepared-preview.md).

Prepared execution extends preview capture to its evaluated command region.
Rollback clears provisional displacement/dab stamps, leaf shortcuts, first-contact
caches and stroke history. The host validates replacement settings before
rolling back the prior valid group. Mirror images share a group and dab identity.
Preview data rows omit frozen connectivity; topology chunks retain ownership of
connectivity restoration. Lazy multires materialization now binds an executor
created during modal settings setup before the slot existed.

All 20 native suites pass, including legacy topology-preview tests and the
seven-kernel replacement/fresh-group matrix. Background and headed Blender each
pass 64 installed host cases. Eight actual mouse-driven Anchored/Drag Dot cases
pass on mesh and multires, including mirror calls, commit, cancel and Blender
undo/redo. Generated bindings, TypeScript checks, staged source equality and
package provenance smoke pass. Final DLL SHA-256 values:

- Installed/Python: `e4026daad8deb50ccae11f44b9a8d09eb0506fdf08088fe6ea0c5c1ac4e383c7`.
- Native: `388e1a662cd3b44f81305e7c37854a07e3e83104bc8109e64e73e9b901d378c7`.

The first headed fixture lacked a scripted-scene undo baseline; corrected before
the passing run. That run then exposed the real null-tree multires binding bug,
which is covered by both modal and direct lifecycle regressions. No engine rebuild
was needed for this Python binding-lifecycle correction.

The existing eight-case modal input matrix also passes against the staged preview
addon after the lazy-slot fix (`plan6-preview-modal-regression.json`). This covers
the ordinary mesh/grid paths alongside the dedicated preview gestures.

Plan 6 still needs dyntopo, general attributes/remaining host stages and generic
consumer adoption. Plans 7/8 remain open; further reviews remain waived.

## Prepared dyntopo — 2026-09-18

[Verified gate](../tests/plan6-dyntopo-gate.json) and
[implementation contract](../plans/generic-brush-prepared-dyntopo.md).

Prepared programs validate the complete typed command list and topology settings
before remeshing. The host's detail radius/cadence is preserved; deformation uses
the evaluated command union queried after topology mutation. Links remain live,
existing spatial/mesh-log callbacks record topology, and each remeshed dab seals
its topology chunk. The additive checked C API is exported and used by the addon
for supported programs. Other attributes/host stages retain their capability guard.

- All 26 native suites pass, including existing topology/collapse/undo regressions.
  The new direct C API matrix includes splits and collapses, pressure radius ADD,
  independent larger later commands, off-cadence dabs, cavity and nonaccumulation,
  exact separate-pass parity, atomic rejection, and exact topology/position undo.
- Background and headed Blender each pass eight installed cases plus four legacy
  controls. Legacy control geometry/topology agrees exactly in both accumulation
  modes. Invalid later radius types and invalid topology settings preserve state.
- Four actual headed gestures pass with mirrored draw/autosmooth, varying pressure,
  cavity, remesh cadence, release/ESC, and Blender undo/redo. ESC keeps accepted
  ordinary dabs and pushes undo, consistent with the existing stroke policy.
- Bindings, TypeScript checks, staging/source equality and package smoke pass.
  Native DLL: `63de0479f8ae0fc0be1dc5f55f4f84f4ad9bcf74f70ac29b487debe446eadee8`.
  Installed/Python DLL: `b41fdcaf8485a5ac151d1abc9c59d52e776c9cd677cf905738ac4561372998a2`.

The initial dispatcher probe could not resolve pnpm dependencies in the sandbox;
it ran successfully with the already-authorized toolchain access. An expanded
fixture's C++ initialization syntax was corrected before the final build/gate.
Plan 6 remains open for general attributes/host stages and generic consumer
adoption. Plans 7/8 remain open; no generic default switch has occurred.

## Prepared mesh attributes � 2026-09-18

[Verified gate](../tests/plan6-attributes-gate.json) and
[implementation contract](../plans/generic-brush-prepared-attributes.md).

The compiler certifies writes to saved vertex/face attributes. The executor
validates every selected layer before mutating a program, runs feature-field and
face-group hooks at their proper stages, and captures the actual selected layers
in ordered per-stage undo chunks. Preview restores those chunks along with
topology. This fixes aliased legacy undo flags when commands target two layers.

All 34 native suites pass, including compiler proof, selected color/sculpt layers,
face groups, feature alignment, raw parity, preview, dyntopo and exact undo/redo.
Installed background and headed Blender each pass 32 host cases; four actual
paint/face-set gestures pass with symmetry, varying pressure, release/ESC and
Blender undo/redo. Generated bindings, TypeScript, staging/source equality and
package smoke pass. Native DLL: `bf6e4ffd3f9cbb8e55547801d7fbb7d18d065eeffc64c7eacfa488500cef3f8b`.
Installed/Python DLL: `6ce2eca1037f8d91474c85ff871193cf757db39679b5ad5f87222d719f859088`.

Testing exposed and corrected a capture deduplication error: OrderedSet.add does
not return insertion success; capture now uses Set. An expanded test fixture also
read released frozen edge links; its state snapshot now reads coordinates and
attributes only. All passing evidence uses the corrected implementation.

Cage-only smoothing, remaining host modes and generic consumer adoption still
keep Plan 6 open. Plans 7 and 8 remain open; no generic default switch occurred.

## Checked cage color smoothing � 2026-09-18

[Verified gate](../tests/plan6-cage-gate.json). The additive cage C API prepares
typed settings once, validates the actual selected color column, then selects
grids using the evaluated radius. The generated color kernel keeps the existing
limit-position snapshot, live cage neighbors, mask seeds and derived-grid refresh.
Cavity and UV reprojection retain the established cage policy. Invalid frames,
columns, tools and stale level/domain attachments reject before edits.

All 34 native suites pass. The cage test runs raw and checked expectations for
masked neighbors, limit-space falloff and grid freshness, including radius ADD
and validation-only/rejected-call preservation. Installed background and headed
lifecycle tests prove checked routing, exact cage/slot undo and redo, flush and
save/reload. Two actual mirrored Shift-smooth mouse gestures pass on multires,
including release/ESC and Blender undo/redo. Bindings, TypeScript, installed
source equality and package smoke pass; DLL hashes are recorded in the manifest.

An initial draft froze links needed by COLORSMOOTH; the checked path now uses
the executor's existing live-link policy. The older host fixture directly opened
an engine session while Blender remained in Object mode, allowing handlers to
retire it during undo flush. It now enters and exits the actual SculptCore mode.
The modal fixture explicitly materializes its slot before taking the baseline.

Plan 6 still needs remaining falloff/grid-layer policies and generic consumer
adoption. Plans 7/8 remain open. Review requirements remain waived by the user.

## Prepared falloff and grid-layer policies - 2026-09-18

[Verified gate](../tests/plan6-host-policies-gate.json) records 34 passing native
suites, 50 installed host cases in background and headed Blender, four actual
Layer gestures with release/cancel and undo/redo, generated bindings, TypeScript
and package provenance. Conservative all-node selection covers cube/box/slab,
Gaussian and nonzero custom edge influence without changing kernel formulas.
The reference evaluates the raw kernel over an independently widened region.
Grid LayerScratch execution validates and pins the active layer channel.

Repeated native testing exposed a cavity scratch error on sparse vertex IDs
after dyntopo collapse. BFS scratch and prepared output columns now size to vertex
capacity rather than live count. The regression compares states after every dab,
retains exact undo/redo and passed eight consecutive runs (plan6-dyntopo-fixed-0
through -7), followed by the full 34-suite gate. No tolerance was relaxed.

The new native semantic-domain collection retains typed bases/bounds and stacks,
accepts explicit per-row input presence/projected radius, and publishes batch
output atomically. Its native test passes; Blender compares 2,200 float/int/bool
evaluations with the independent host evaluator using development and installed
DLLs. Consumer wiring is in progress and is not part of the completed falloff/layer
gate. Generic execution remains disabled by default. Plans 6, 7 and 8 remain open.
