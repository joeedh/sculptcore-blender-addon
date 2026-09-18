# Plan 3: prepared typed execution

Status: reviewed with corrections; nonmutating device evaluation, static
storage adapters, declaration preflight and scalar candidate gates complete,
plus bounded prepared mesh and grid execution, 2026-09-16. Fixture
and addon-only restoration gates pass. The subsequent
[bounded program gate](generic-brush-prepared-programs.md) also passes.
Full prepared execution remains open. The
checked configuration/binding gate is complete. This implements the remaining execution
requirements in [typed integration](generic-brush-typed-integration.md).

## Boundary and compatibility

- Add an explicit resolved-property execution entry point/policy for mesh and
  grid standalone dabs and programs. Existing raw member/working-slot callers
  retain their current source-of-values policy. Querying metadata must not
  silently opt a caller into a different execution policy.
- Both policies must reject invalid configured dynamics before dyntopo,
  freeze/thaw, hooks, undo capture, stroke sample mutation or spatial filtering.
  Revalidate at every invocation, including empty first dabs; raw public writes
  bypass configuration generations, so that counter alone is insufficient.
- Initially prepare CPU mesh/grid execution. Extra GPU dispatch remains absent
  and must reject explicitly. Independent command inheritance and configuration
  dependent hook/cavity caching remain Plan 6; reject unsupported new resolved
  combinations rather than execute a partial interpretation.

## Prepared values and errors

1. Build command metadata using scratch Brush factories. Register the complete
   declaration set atomically before execution. Do not initialize live extra
   working slots merely to discover that a later declaration is invalid.
2. Introduce an owned prepared scalar set carrying names, exact scalar types,
   evaluated values and the source/target identity needed by the internal apply
   step. Prepare all commands before the first command can run. Return a useful
   property/command error; do not use lookup fallback defaults as success.
3. Validate source type, retained schema, local ownership, finite authored
   values/ranges and every configured device stack (including disabled/pending
   entries). Reject stray dynamics for the active command. Evaluate with the
   current per-dab input context using the existing typed contract.
4. Keep authored properties and evaluated caches distinct. In resolved mode,
   dynamic uniforms and common properties read authored properties. Static native
   fields and static extra working slots retain authoritative working-state
   semantics. Audit checked scalar APIs for static properties: where they expose
   static values, ensure writes reach the same authoritative storage execution
   reads; do not introduce a second unsynchronized value. Generated defaults
   must preserve explicitly initialized working values.
5. Generate typed prepare/apply callbacks, or an equivalent typed accessor table,
   so prepared values can be committed to native members and named stores without
   repeating unchecked property lookup. Validate the whole candidate before
   applying any working cache. Keep float/int/bool exact and authored values
   unchanged by evaluation. Preserve raw-mode baselines explicitly in tests.

## Entry points and regions

6. Prepare standalone mesh/grid dabs before any mutation, then use the prepared
   radius/extents for spatial selection and for kernel execution. Account for
   unbounded fields and anchored grabs. The checked path owns node selection;
   raw caller-supplied node APIs keep an explicit coverage contract.
7. Programs prepare each command's sparse overrides and scalar state in advance.
   Extend the existing float override compatibility surface with typed values.
   Restore authored presence, values/stacks, native working fields, typed stores
   and invert on every return path. Compute a conservative command-region union
   before filtering; execution must use the same prepared values. Do not let a
   later invalid command follow an earlier geometry mutation.
8. Adopt preparation before filtering in mesh/grid batch C APIs. Propagate
   negative failures through existing addon scalar/batch/preview boundaries.
   Keep a bounded prepared result per dab; avoid allocating response tables in
   the per-dab path. Caching may follow once raw-write invalidation is sound.

## Acceptance gates

- Existing raw-field, float/program, registration, typed compiler, configuration
  and binding tests remain passing with the addon kernels enabled explicitly.
- Actual typed fixture geometry for standalone mesh/grid and program/batch paths,
  with exact large integer and boolean behavior and preserved authored values.
- Invalid type/schema/value, static or stray dynamics, duplicate/unsupported
  devices, invalid/pending curves and later-command failures leave geometry,
  topology/undo capture, working values and authored state unchanged. Include
  non-first dabs, empty first dabs, direct raw edits and repaired configurations.
- Radius dynamics and command overrides exercise geometry outside the raw/base
  radius. Include unbounded extent and caller-supplied node-policy cases.
- Static native/extra writes and reads agree with execution; copying/restoration
  preserves absent/default/initialized distinctions. Unsupported new command
  combinations return an explicit error.
- Rebuild through make.mjs, test exact binaries, regenerate affected kernels and
  binding declarations, then restore addon-only outputs. This gate does not
  claim timestamp acquisition or headed modal device delivery.

## Bounded grid execution slice (2026-09-16)

Reviewed before implementation by fresh `review_resolved_grid_lifetime` and
`review_resolved_grid_dispatch`; their surviving corrections are folded below.

- Add an internal unreflected GridBrushExecutor::applyResolvedDab returning
  ScalarRegistrationResult, using a fresh GridCsrNbr/AccumLive scratch command.
  Prepare on every call, validate capabilities and evaluated radius, then use the
  existing private scalar publisher and execute that exact command through
  execStage/finishDab. Do not call legacy applyDab, loaders or live factories.
- Match the mesh slice's bounded Smoothstep/Linear spherical policy, zero-radius
  no-op and finite reciprocal check. Reject nonaccumulation, anchored grab,
  unbounded fields, unsafe generated code, host hooks/stages, cavity, original
  normal requirements, face/attribute/color/mask writes and cached attribute
  mirrors. Initially require base edit target (editTarget == -1 and writeback
  channel zero); layer/mask/attribute preflight remains a later extension.
- Keep the existing live-domain lifetime contract: attach after any Multires
  operation that invalidates the domain; never dereference stale domain pointers.
  Record attachment pointer identities and reject public domain/tree replacement
  without attach. Validate matching log domain and an open executor step before
  publication. Validation must not call ensureTree or another mutating domain API.
- Failed calls preserve authored/declaration/slot state, working caches, stats,
  first-dab flag, sample history, moved/touched sets, positions, normals, mask,
  bounds and undo bytes; only lastRegistration changes. Successful empty/zero
  calls publish valid scalars, clear last-dab result sets, increment dab count and
  advance first-dab state without pushing samples/capture. Accepted nonempty calls
  use evaluated radius, update frame/sample, execStage and finishDab, retaining
  existing deferred-normal cadence. Stroke end folds through the existing grid
  store/log path; test exact store and position undo/redo.
- Tests: actual DRAW across several grid leaves, moved owners excluded by raw
  radius, late raw invalid/pending stacks and repair, readonly source/cache
  preservation, zero/empty results, layer/mask/host/unsafe capability failures,
  attachment/log mismatch, default publication and typed float/int/bool geometry.
  Translate fixture geometry beyond old leaf bounds and hit it next dab; compare
  resolved SMOOTH to an independent raw configured grid reference, including
  deferred normals. Keep all prior mesh/grid baselines, run fixture and addon-only
  gates through existing dialog-safe infrastructure, and record exact binaries.
- Grid/program/batch/preview addon adoption and every-dab legacy validation remain
  subsequent parts of the overall execution gate. This slice does not change
  production addon routing, reflected bindings or the Blender fork.

Review corrections:

- Cache the live Multires pointer and domainGeneration at attach. Check generation
  before dereferencing cached domain/tree/log pointers; pointer equality alone
  misses allocator address reuse. Multires must outlive the executor. Rebaseline
  generation after executor-owned endStep when attachment was current before its
  fold: that fold retains this level but may invalidate resident finer domains.
  External generation changes conservatively require reattachment. Test stale
  drop/rebuild rejection and consecutive strokes with a resident finer domain.
- Bind the log pointer and a monotonic open-step serial at beginStep; reject log
  replacement, attach, close/reopen or closed steps before publication. Attach
  clears executor step eligibility. Domain/tree partition, edit target and log
  transaction must stay stable through endStep; calling endStep with an externally
  invalidated domain/transaction is outside the existing lifecycle contract.
  An endStep after attach with no new begin is a no-op.
- Grant the grid executor private publication access. Reject all command attrs,
  including read-only ones, and all cached mirrors in this bounded entry.
- Scalar-safe generated code can move every vertex in selected leaves, including
  seam vertices outside the query sphere. Refresh bounds over all occurrence
  leaves of moved vertices, and apply the same closure during log undo/redo.
  Use a reusable GridTree scratch set and a partial-region unconditional safe
  translation fixture; whole-domain translation does not cover this failure.
- Verify deferred successful dab -> failure -> zero/empty success -> flush/end
  preserves pending normals and touched sets. Compare every normal, store bytes,
  propagation debt, history count and subsequent spatial queries across undo/redo.

Implementation audits by both reviewers found no remaining blocking defects
within this bounded contract. The dispatch audit requested explicit full-normal
recomputation comparisons after undo/redo; these were added before the test gate.

## Bounded mesh publication and execution slice (2026-09-16)

Reviewed before implementation by fresh `review_resolved_mesh_state` and independent
dispatch reviewer `review_scalar_candidates_codegen`. The platform rejected a second
fresh agent with `agent thread limit reached`; the completed codegen reviewer was
reused with the new on-disk plan and a separate dispatch lens.

- Add an internal, unreflected `CommandExecutor::applyResolvedDab` taking a tool,
  center and normal, returning `ScalarRegistrationResult`. It owns selection and
  uses a fresh scratch factory command with the executor's actual neighbor mode.
  That exact command supplies both metadata and execution; no live factory runs.
- Initially support topology-stable, accumulating CPU mesh dabs, spherical bounded
  Smoothstep/Linear falloff, no anchored grab, command attributes, attribute
  overrides, generated host stages, external hooks, cavity automasking or active preview. Reject unsupported capabilities
  explicitly before publication or filtering. No legacy caller opts in implicitly.
  Preview is unavailable through this internal entry; a future public preview API
  must prepare before capture. Reject missing tree/mesh/root, nonfinite center/normal
  and negative/nonfinite evaluated radius before publication. Zero radius is a
  successful empty dab (pressure may produce zero).
- Prepare fresh scalars on every invocation, including empty regions and nonfirst
  dabs. Do not trust configuration generations or expose reusable apply tokens.
  Add private candidate publication, accessible only to the executor: synchronous
  preparation, capability/radius checks, publication and execution have no user
  callbacks or yield points between them. Register the validated declarations,
  install extra defaults, then write native addresses and working-only typed
  stores. Never use authoring setters or re-run legacy loaders. Registration's
  existing validation failure is the final recoverable failure before mutation;
  allocation failure remains the engine's existing fatal allocation contract.
- Filter with evaluated radius; execute via the existing mesh capture/kernel
  pipeline after topology setup, context/frame and stroke sample initialization.
  Empty successful dabs publish the valid configuration and advance first-dab
  state consistently with applyDab, without geometry/sample/capture work. Failure
  preserves first-dab flag, node counts, sample history, working caches, authored
  presence, slot presence, topology, capture and geometry (apart from diagnostic
  status). Repair succeeds on the next call without restarting the stroke.
  Refresh spatial queries after successful nonempty execution so the next call
  can select vertices displaced outside their previous leaf bounds. The caller
  must supply a built, current tree initially and after external mesh edits.
- Test native DRAW geometry with raw radius deliberately smaller than evaluated
  radius, unsupported capability rejection, empty/nonfirst invalid stacks,
  publication absence on failure, readonly sources and undo capture. Fixture
  geometry must consume exact int/bool/float values with authored values/cache
  tables unchanged. Retain legacy mesh/grid program baselines. Run fixture and
  addon-only gates and record exact binaries. Grid, program, batch and bindings
  adoption remain subsequent slices of the overall execution gate.

Review corrections: Gaussian and arbitrary curve LUTs do not guarantee zero
outside the sphere. Generated host stages can change prepared scalars/center after
filtering, so they reject; use a separate host-free typed fixture with a real
distance cutoff and exactly matching shared declarations. Identify fixtures by
tool name, not the first manifest containing typed_count. The radius regression
must span multiple leaves and prove movement/undo in a leaf missed by raw-radius
selection. Test LiveDisk and CSR for admitted neighbor kernels. Preserve a
one-to-one scratch command/manifest/execution identity without legacy memo/loaders.

Implementation-review corrections: reject positive radii whose reciprocal is
nonfinite (a vertex exactly at the center otherwise becomes NaN). The root is
private; use SpatialTree::getRoot. A host-free kernel can still assign uniforms
in vertex stages. Add a conservative generated, unreflected preparedScalarSafe
capability, default false: permit only assignments rooted in lexical locals or
stage parameters; unwrap member/index/parenthesis lvalues. Host/reduce stages and
unknown free-function calls are ineligible. Preserve legacy code generation and
execution. Compiler tests cover unsafe native/extra/ctx/member/index assignments,
local shadowing, safe vertex writes and unknown calls; an unsafe extra fixture
must reject before publication. This is a bounded execution eligibility check,
not a change to the DSL's general mutation semantics.
The write whitelist excludes neighbor bundles and arbitrary Vertex member chains
(Vertex exposes executor/context references): only direct co/no/mask plus numeric
components qualify. Locals/texture parameters must be scalar/vector value types.
Numeric constructors/casts are allowed in the unknown-call branch; other unknown
calls reject. Both escape cases have compiler regressions from the dispatch review.
Runtime tests corrected one review assumption: the source parser already rejects
literal `.ctx` member syntax as a reserved keyword. Parser rejection and the
emitter's general nested-chain exclusion are tested separately.

## Review lenses

Fresh reviews must challenge buildability/code generation and actual execution
seams independently. Resolve concrete blockers against current code before
implementation, especially authoritative static state, command restoration,
early mutation ordering, host hooks and conservative spatial coverage.

## Folded execution review corrections

- Failure atomicity is per logical dab/program, not rollback of already accepted
  earlier dabs in a batch. Batch preparation uses an input overlay; it must not
  call writeProps on evaluated caches. Check every scalar/mirror result before
  accumulation. Tests cover spacing/planeoff/autosmooth without authored decay.
- Preview capture currently precedes addon apply_dab. Prepare before capture and
  use the same region at capture and execution, or reject new resolved previews
  before capture. Include second-command expanded regions and rollback tests.
- Preflight dispatch and domain capability as well as scalars. Grid programs
  must check actual MultiresAttrs, edit targets, grab restrictions and attribute
  overrides before the first command. Replace failure assertions on checked
  paths with explicit errors.
- Region plans include pinned ownership, radius growth, symmetry and ordinary
  command regions. Initially reject resolved mixed anchored/nonanchored programs.
  Cover cube corners and elongated boxes conservatively; linear slabs require
  all-domain selection or explicit rejection. Sphere-only filtering is inadequate.
- Canonicalize override ID/name aliases. Legacy float duplicates are last-write
  wins; snapshot each unique source once and restore with a scope guard. Typed
  conflicts reject before mutation. Preserve absent/local/inherited state and
  authored invert separately from its evaluated native cache.
- Audit reflected standalone mesh, grid scalar, both batch forms, preview and
  tree-less cage smooth callers. Void legacy entries expose validation status;
  new checked entries return explicit status. No failure may turn into a positive
  accumulated node/moved count.
- Reject unsupported configuration-dependent hook/cavity behavior in new resolved
  execution, including standalone mid-stroke ENHANCE parameter changes. Per-dab
  scalar preparation alone cannot invalidate its stroke-stamped cache.

## First prerequisite: nonmutating evaluation

The existing StructProp::evaluateScalar fills live device input caches. Prepared
evaluation cannot use it unchanged, and copying Dynamics allocates response
tables. Factor DynamicDevice evaluation to accept an explicit sample; add a
const-context Dynamics overload sharing the existing arithmetic. The last
matching input wins, missing/nonfinite inputs are inactive, and disabled/pending
stacks still validate. FLOAT32 keeps float arithmetic; INT32/BOOL keep double.
The checked StructProp path uses this overload without writing input caches.
Tests compare cached/context outputs and preserve cache values/table addresses
on success and failure. This prerequisite does not itself close execution gates.

Static-storage access follows through native scalar member accessors and extra
name/type/slot lookup behind brush.cc. Keep the generated registry out of brush.h:
standalone sbrushc includes that header, extras generation depends on sbrushc,
and brush compilation depends on generated extras. Do not create a build cycle.

## Remaining codegen/state review corrections

- Stage missing declarations/defaults until the complete prepared command set
  validates, or implement exact rollback of properties and retained declarations.
  A successful live registration followed by failed evaluation otherwise changes
  authored presence. All-extra default installation belongs behind this barrier.
- Never copy Brush or StructDef for isolation: self-pointers and owned raw property
  pointers make ordinary copies unsafe. Default-constructed scratch brushes are
  only for factories; use explicit owned scalar candidates and snapshots for state.
- Generated apply uses typed internal working setters, never public setNamedScalar
  (which writes authored dynamic properties). Pin accessor/manifest index identity
  across repeated AccumMode factories and validate names/types/store slots.

Both fresh reviews are folded above. Safe implementation order: nonmutating
evaluator, static accessor coherence, then supported standalone CPU preparation,
batch overlays, and fully preflighted typed programs/regions. Preview and other
unsupported resolved combinations remain explicit rejections until their gates pass.

## Nonmutating device-evaluation evidence

Implemented explicit-sample DynamicDevice overloads and a const-context Dynamics
overload sharing the existing checked arithmetic. Checked StructProp evaluation
uses it; legacy lookup's cached-input policy is unchanged. The dynamics overload
does not allocate/copy response tables. Code inspection supports the allocation
claim; unchanged table pointers alone would not prove absence of transient allocations.

The new contextEvaluation test covers exact 16777217 interpolation (4529849),
float/int/bool parity with cached evaluation, clamped samples, last duplicate
input precedence, final nonfinite input, missing input and signed zero. Cached
sample/presence state stays unchanged on success and failed disabled/pending
curve evaluation; failed checked StructProp reads preserve the output argument.
The implementation reviewer found no blocking issue.

`node make.mjs build native --kernels-extra ../brushes -j 8` passed;
[build log](../tests/prepared-context-build.log). The addon-only [16-suite gate](../tests/prepared-context-results.json)
and [exact-DLL Python smoke](../tests/prepared-context-python.log) passed. Current
native DLL SHA256: defb0e6a8b752036520bb135f7b3a6193a5bc96649d9ac898b311ec25dbdbfc0.
The typed compiler boundary suite ran without the runtime-only fixture; typed
context behavior is covered by native property/configuration tests here. No
reflected signature or generated declaration changed in this prerequisite.

This is not a wholly read-only property accessor: readScalar still assigns the
property owner pointer and may invoke a custom getter. Static working-state
coherence was still pending at that gate. Publishing declarations/defaults only
after whole-command preparation and all execution adoption remain unimplemented.
No Blender runtime was vendored.

## Static storage adapter evidence

Checked scalar access now routes registered static uniforms through the same
native member or typed extra slot used by generated kernels. The native roster
provides typed addresses from a fixed descriptor table; compiler metadata still
uses that same roster. Extra name/type/slot lookup stays behind brush.cc. Static
property shadows remain dormant and do not override working values. Dynamic
uniforms continue to edit authored property storage.

Common properties are an explicit exception: loadCommonProps always loads their
authored values into native caches, including a static invert declaration. A
static declaration disables their device dynamics without changing this source.
Reads reject invalid native/slot values. Writes validate type, range, ownership,
schema and read-only state before changing storage or generation. Reading an
uninitialized static extra slot reports absence; invalid writes preserve absence,
and a valid write survives later generated default initialization.

The fixture-enabled build and all [16 native suites](../tests/static-storage-fixed-results.json)
passed, including actual mesh/grid program geometry: checked static boolean writes
disable and re-enable movement across six dabs alongside integer/boolean dynamics.
Native tests cover exact large integers, raw-field/raw-slot readback, dormant
shadows, readonly/nonfinite/range failures, common invert and absent slots. The
[11-check Python gate](../tests/static-storage-fixed-python.log) passed against
the exact DLL, including the real CLAY planeSide manifest and repeated fixture
queries preserving static slots. Fixture DLL SHA256:
418138e64d5b3dfca43c597bc0cdb9400e1639b2fd040a62e359aebcff411864.
[Build log](../tests/static-storage-fixed-build-final.log).

The initial descriptor vector passed value/geometry assertions but failed native
allocation accounting at test exit. It was replaced by a fixed array/span; the
final runs above include allocation checks. An initial sandboxed gate could not
resolve the existing external pnpm links; the successful dispatcher runs used
the established elevated environment. No dependency installation was needed.

The addon-only rebuild (`--kernels-extra ../brushes`) and its [16-suite gate](../tests/static-storage-addon-results.json)
passed, as did the [exact-DLL Python smoke](../tests/static-storage-addon-python.log).
[Restoration build log](../tests/static-storage-addon-build.log). Restoration DLL SHA256:
d0cef2b33e7372dee9bc8af647e9460ee28d333f18b16efe1e44c165c7c38c26.
The fixture-only runtime branch is excluded in this restored configuration; its
geometry evidence is the explicit fixture run above. No reflected signature,
binding declaration or Blender runtime installation changed in this slice.
Preparation and validation before geometry mutation remain open.

## Declaration preflight evidence

StructDef::validateScalarDeclarations now checks a complete declaration set
against existing properties, retained declarations and inheritance without
creating properties or retaining metadata. registerScalars reuses this check
immediately before publication; successful preflight does not reserve state or
permit a later raw schema edit to escape validation. This is declaration
compatibility only, not authored-value or device-stack evaluation.

The new preflightWithoutPublication regression preserves absent entries,
inherited/local presence, property identity, owner pointers, values and device
stacks without invoking a getter. A schema edit after successful preflight
causes publication to fail without creating an earlier pending entry. Restoring
the schema permits a different declaration, proving preflight retained no stale
metadata. Existing invalid-batch cases now compare preflight/publication errors.

The addon-only [build](../tests/prepared-declaration-build.log), [16 native suites](../tests/prepared-declaration-results.json)
and [exact-DLL Python smoke](../tests/prepared-declaration-python.log) passed.
Current DLL SHA256:
a85f03382a2f745eef87f9d9f0c81b3b67224517a3ba1ab6266fc350fe065968.
No reflected signatures or Blender runtime installation changed. Prepared scalar
candidates, delayed publication across evaluation, and execution adoption remain
the next work; this helper alone does not provide a complete execution transaction.

## Prepared scalar candidate implementation slice

Implement an internal prepareBrushScalars helper in brush_preparation.h/.cc. It
accepts a Brush, a command's owned uniform manifest, an explicit const input
context and an output candidate. The candidate owns typed double-transport
values, target names/slots and pending scalar declarations, plus source Brush
and StructDef identities. It has no apply method in this slice; consumers must
not treat a retained candidate as valid after raw source edits. Publish output
only after the entire candidate validates; preserve earlier output on failure.

- Reuse the declaration normalizer through a public normalized scalar-domain
  helper (min/max/initial). Existing validation and registration share its
  arithmetic. Preflight all manifest declarations without publication.
- Resolve native targets from the fixed typed roster, extra targets by exact
  name/type/slot/dynamics identity. Reject duplicate manifest names and malformed
  scalar metadata. Permit known static native nonscalar entries to remain raw;
  reject unsupported unknown bindings. Always include common scalar fields once.
- Read dynamic/common authored values locally without get(), owner assignment or
  device-cache writes. Reject custom getters and effective bound storage with a
  nonnull StructProp owner. Legacy local common properties with offset zero and
  null owner use their internal value as existing get() does. Reject inherited
  sources rather than guessing their owner. Preserve readonly authored values.
- Use normalized defaults for absent dynamic properties; use authoritative native
  fields or initialized extra slots for static uniforms. An absent static extra
  slot stages its generated manifest default without initializing it. Common
  fields continue to use authored properties even when declared static. Retained
  common declarations govern eligibility/bounds when omitted by the command.
- Validate every local configured scalar stack, rejecting stray and static
  dynamics, pending/invalid/duplicate devices, and invalid authored values. Read
  and evaluate float/int/bool with the const-context typed arithmetic; do not copy
  response tables. Candidate collection may allocate its own bounded vectors.
- Tests cover real builtin and typed-extra manifests, exact large integers,
  boolean thresholds, changing inputs, raw static values, normalized defaults,
  absent property/slot preservation, later failures preserving output and all
  live state, local owner/getter policy, inherited rejection, malformed target
  identities, readonly inputs, stray/static/disabled-pending stacks and repeats.

Build/run fixture and addon-only native gates plus exact-DLL Python regressions.
No geometry entry point or publication/apply phase changes here: spatial,
capability, hook and whole-program preflight remain required before adoption.

### Folded candidate review corrections

- Static property shadows are dormant: validate their schema and absence of
  dynamics, but do not read their value, inspect owner bindings or invoke/reject
  dormant getters. Read and validate the authoritative working value instead.
- Sweep every supported NumBase storage type for configured stacks, including
  FLOAT64 and vectors; unsupported types with stacks reject, even when disabled.
- Preserve current registration semantics: absent declarations with omitted
  defaults require zero inside the normalized range. Do not seed declarations
  from native working values to evade that check. Missing common properties
  reject; present common properties use their actual authored values (including
  a newly constructed Brush's authored zeros).
- Readonly values remain readable. A nonnull owner with an unbound offset of -1
  is acceptable. Only an effective bound authored source or custom getter rejects.
- Candidate output is privately owned with read-only views. Input manifests must
  come directly from scratch command factories, never mutable reflected query
  snapshots. Runtime slot descriptors authenticate storage identity, not the
  command-specific default/range metadata; factory provenance supplies that.
- Put fixture tests in the existing test_brush_typed_extras target, whose fixture
  macro is wired by CMake. Discover commands using createDeclarationCommand,
  not queryUniformManifest (which would already publish properties/defaults).
- Check owner pointers, schema/presence, initialized slots, authored values,
  device input caches/table addresses, generation and prior output after both
  successful preparation and later failures. No apply/commit entry exists yet.
- Dispatch evaluation at the actual scalar type before double transport. Compare
  candidate extra defaults against generated initialization on a separate Brush;
  require float-rounding-sensitive mixes, exact integer interpolation, boolean
  threshold transitions, integer extrema and normalized integer bounds.

Both fresh candidate reviews are folded above; implementation may proceed.

Implementation review correction: public property names can diverge from their
StructDef map keys. Validate the resolved property's name and require canonical
lookup identity when authorizing any configured stack; a renamed stray property
must not impersonate common radius/strength dynamics. Regressions cover both
renamed sources and renamed stray stacks while preserving prior output.

## Prepared scalar candidate evidence

Implemented the internal brush_preparation helper and readonly candidate views.
The shared ScalarDomain normalizer keeps candidate defaults/bounds identical to
registration. Candidates carry exact float/int/bool values and native-member or
typed-slot targets, pending declarations and source identities. Preparation
does not register properties, initialize slots, alter working values, invoke
getters, assign owners, copy response tables or change device input caches.
All values validate before replacing the caller's output.

Both fresh plan reviews and implementation audits are folded above. The audits
found and corrected mutable-name impersonation and a test reusing an accumulating
command manifest. Compilation also caught litestl's missing const data() overload;
readonly spans now use const element access without modifying litestl.

The fixture-enabled [build](../tests/prepared-candidates-build-final.log) and
[final test rebuild](../tests/prepared-candidates-build-tested.log) passed. All
[16 native suites](../tests/prepared-candidates-results.json) passed, including:

- Kelvinlet, Wingscrape, Polygroup and Color candidate manifests; native integer
  16777217, dormant static NaN/getter shadows, known nonscalar native entries,
  inherited/missing common rejection and readonly/effective-owner policy.
- FLOAT32 per-mix rounding at 16777216, exact integer interpolation to 4529849,
  boolean threshold transitions and changing device inputs.
- Typed fixture defaults compared against generated initialization on a separate
  Brush, integer extrema, normalized integer bounds and preserved absent slots.
- Late invalid static values, invalid authored values, malformed manifest identity,
  renamed sources/stray stacks, unsupported numeric/vector stacks and disabled
  pending uploads preserve earlier output and live state.
- Existing mesh/grid program geometry still passes; these are regression checks,
  not evidence of prepared execution adoption.

All [11 Python binding checks](../tests/prepared-candidates-python.log) passed
against fixture DLL SHA256:
e81d22f8e35fbb29914dbd0f8607d2d64ebe1ccd06fd4a608344fb278dec9840.
The addon-only [restoration build](../tests/prepared-candidates-addon-build.log),
[16 native suites](../tests/prepared-candidates-addon-results.json) and
[exact-DLL Python smoke](../tests/prepared-candidates-addon-python.log) passed.
Current addon-only DLL SHA256:
8b257f401c43a5cd583659c85d071e2385e72bf1bc4381b09824476131ad08a8.
No reflected signatures changed and no runtime was vendored into Blender.
At that gate publication/apply, spatial/capability preflight and geometry
entry-point adoption remained open. Candidates are snapshots, not execution
tokens, and must be rebuilt after source edits.

## Bounded mesh execution evidence

Completed 2026-09-16; fixture and addon-only restoration gates passed.

- Private `PreparedBrushScalars::publish` registers validated declarations,
  initializes untouched extra defaults and writes typed native/working caches.
  It is called synchronously after preparation and capability checks; it is not
  a public reusable token. Readonly authored values, owners and device caches
  remain unchanged by evaluation/application.
- Unreflected `CommandExecutor::applyResolvedDab` prepares every invocation before
  publication/filtering, uses evaluated radius, runs the same scratch command
  through mesh capture/execution, then refreshes spatial queries. Zero radius
  succeeds without kernel execution. Unsupported modes and invalid finite/range/
  dynamics state return a diagnostic error; repaired calls can proceed immediately.
- Generated `preparedScalarSafe` defaults false and excludes shared-state writes,
  unsafe member chains, neighbor writes, unknown calls and host/reduce/face stages.
  This changes checked-path eligibility only. C++ kernels were regenerated;
  no reflected signatures changed. Literal `.ctx` is already a parser error;
  emitter nested-member exclusions have separate tests.

Successful fixture [engine build](../tests/resolved-mesh-build-tested.log), followed
by the [final test rebuild](../tests/resolved-mesh-test-final-build.log):
`node make.mjs build native --kernels-extra '../brushes;tests/assets/typed_extras' -j 8`.
The [17-suite native gate](../tests/resolved-mesh-final-results.json) passed:

- DRAW moves 337 vertices owned by leaves omitted by raw-radius filtering, with
  exact undo/redo. Invalid first/empty/nonfirst dynamics preserve publication,
  caches, geometry and capture state. Readonly radius ownership/cache values,
  zero-radius no-op, reciprocal overflow rejection and capability failures pass.
- SMOOTH executes with LiveDisk and CSR neighbor factories and matching geometry.
- The host-free TYPEDRESOLVED fixture consumes float/int/bool values, exact large
  integers and the 0.5 boolean threshold. Late invalid static values and pending
  disabled uploads preserve state; successful defaults preserve initialized static
  slots. After a 20-unit translation the next dab finds and moves the mesh through
  refreshed bounds. TYPEDPROBE host execution and TYPEDUNSAFE uniform writes reject
  before publication in this path. Existing mesh/grid program baselines pass.
- Compiler tests cover native/extra/ctx/member/index writes, neighbor writes,
  unknown calls, local shadowing, direct vertex writes and numeric constructors.

All [11 existing Python checks](../tests/resolved-mesh-python.log) passed against
the same fixture DLL SHA256:
`702ce4e5edda9218b6655a520d589f9ddfbb0bbe267227fc43d58746fc5e7c8c`.
Earlier build/test logs retain corrected private-root access, ambiguous
`float3(0)` construction, test-owned vector lifetime at test_end, and parser-keyword
test failures. No engine failures remain in the final fixture gate.

The [addon-only restoration build](../tests/resolved-mesh-addon-build.log),
[17 native suites](../tests/resolved-mesh-addon-results.json), and
[exact-DLL Python smoke](../tests/resolved-mesh-addon-python.log) all passed.
Current addon-only DLL SHA256:
`0d80b055c328a360b9606e0ffc321cf692cacbd0cb494ed22592fd3dfc2a8c88`.
Scoped `git diff --check -- source/brush tests/CMakeLists.txt` passes; unrelated
pre-existing TODO.md whitespace remains untouched. The gate runner's new
`--prepared-execution` switch adds the native execution suite and the typed
fixture gate requires its resolved-geometry marker.

This internal mesh entry is not installed in Blender or exposed to addon callers.
Grid standalone, typed program/batch/preview adoption, broader region/host policies,
legacy every-dab validation and modal input delivery remain open. No headed gate
is claimed for this native-only slice.

## Bounded grid execution evidence

Completed 2026-09-16; fixture and addon-only restoration gates passed.

- Internal `GridBrushExecutor::applyResolvedDab` prepares every call from a fresh
  scratch command, rejects unsupported capabilities before publication, publishes
  exact scalar caches and selects leaves using evaluated radius. Invalid dabs
  preserve geometry, normals, mask, bounds, samples, first-dab state, stats,
  touched sets, undo bytes and property/slot presence. Zero/empty successes keep
  prior stroke touched sets and deferred normals while clearing last-dab results.
- Attachment checks compare the live owner's domainGeneration before touching
  cached domain/tree pointers. Step checks bind the log pointer and open-step
  serial, catching replacement, close/reopen and same-domain reattachment.
  EndStep rebaselines executor-owned finer-domain invalidation without clearing
  valid undo history. Multires must outlive the executor; external invalidation
  still requires reattachment. The domain/tree partition, edit target and log
  transaction must remain stable through endStep.
- GridTree refreshes bounds through moved vertices' occurrence grids, including
  incident leaves outside the original query. Both normal grid execution and log
  undo/redo use this closure. Scratch vectors are reused; no full-tree rebuild is
  introduced. A partial-region unconditional translation fixture exercises this
  seam, checks all bounds against a full refresh and verifies subsequent queries.

Both fresh plan reviews and implementation audits passed after their corrections
were folded in. The first build caught a test initializer mixing the enum wrapper
and underlying enum; it was corrected. The successful fixture
[engine build](../tests/resolved-grid-build-tested.log) and
[final test rebuild](../tests/resolved-grid-test-final-build.log) used:
`node make.mjs build native --kernels-extra '../brushes;tests/assets/typed_extras' -j 8`.

All [17 native suites](../tests/resolved-grid-results.json) passed:

- DRAW moves 593 vertices owned by leaves excluded at the raw radius. Deferred
  normals survive rejected and zero/empty dabs, then match full recomputation.
  Two strokes with an initially resident finer domain preserve log history;
  positions and store bytes restore bit-exact, propagation debt restores, and
  every normal matches full recomputation after undo/redo.
- Lifecycle tests cover missing/replaced attachments, invalidated and rebuilt
  domains, closed/replaced/reopened logs, null/log replacement, post-attach
  endStep, and repair. Unsupported falloff, nonaccumulation, host/unsafe/attribute/
  mask/layer/cached-mirror cases reject without publication or geometry changes.
- TYPEDRESOLVED executes exact integer 16777217, boolean 0.49/0.5 transitions and
  float response values on grids. Initialized static slots and readonly authored
  owner/cache state survive publication. Late invalid static values and disabled
  pending uploads reject atomically; repair and translated-region selection pass.
- SMOOTH matches an independent raw-configured grid reference across repeated
  dabs, with both immediate and deferred normal cadence. Existing legacy mesh/grid
  program and mask/layer/attribute tests continue to pass.

All [11 Python checks](../tests/resolved-grid-python.log) passed against fixture
DLL SHA256 `0909f0c03ea04faee4c5872cdc65c43064dc7ccc5439c33d644a8a7afaae88fe`.
No reflected signatures changed. The internal entry is not yet routed from the
addon or vendored into Blender; this gate makes no headed execution claim.

The [addon-only restoration build](../tests/resolved-grid-addon-build.log),
[17 native suites](../tests/resolved-grid-addon-results.json) and
[exact-DLL Python smoke](../tests/resolved-grid-addon-python.log) passed.
Current addon-only DLL SHA256:
`dd4cbed04d6264afda429e64eb9e60be78fb6275ea540bf665fdcd4f3522c21b`.
Scoped whitespace checks pass. The original build failure log is retained;
the corrected final gates have no failures. No unrelated work was reverted.

Prepared program/batch/preview integration, legacy every-dab validation, broader
capability policies and modal device-input delivery remain open in Plan 3.
