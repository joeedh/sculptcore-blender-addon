# Plan 3: bounded prepared programs

Status: bounded program gate complete, 2026-09-16. Reviewed before implementation
by fresh `review_prepared_program_state` and `review_prepared_program_execution`;
corrections and passing fixture/addon-only evidence are recorded below.

## Scope

Add internal, unreflected `applyResolvedProgram(BrushProgram *, center, normal)`
entries to the mesh and grid executors. Keep the standalone bounded capability
policies, scratch-factory provenance and lifecycle contracts. Program/batch addon
routing, public typed command bindings, preview, broader capabilities and device
event delivery remain subsequent work. Existing legacy float programs retain
their source policy and geometry baselines.

## Typed overrides and preparation

- Add an internal typed scalar override roster to BrushCommandEntry, carrying
  name, exact FLOAT32/INT32/BOOL type and double transport. Provide an unreflected
  checked native setter; no binding signatures change in this slice. The existing
  float override and invert methods remain accepted by the new entry. Legacy
  execution explicitly rejects entries with typed overrides until adopted.
- Canonicalize each command's float/common-ID, typed-name and invert overrides.
  Unknown/invalid IDs, names, types, nonfinite values, fractional integers, boolean
  values other than 0/1 and duplicate canonical targets reject the entire program.
  Keep existing float setters unchanged; they may produce duplicates, which only
  the new checked entry rejects. Overrides must name a common property or a scalar
  in that command's manifest. Attribute overrides reject in the bounded entry.
- Use a fresh scratch command per entry. Gather and validate the union of scalar
  declarations without publication. Shared declarations must remain compatible.
  Prepare every command before any spatial query, scalar write, sample, capture,
  topology operation or geometry change. A later invalid command preserves all
  earlier state. Diagnostics identify the command index and failed field.
- Extend scalar preparation with an internal typed base-value overlay and program
  declaration scope. Apply overrides before typed dynamics, without touching
  authored properties. Validate type/schema/local-source/owner policy and every
  configured stack, including disabled/pending and unsupported numeric types.
  A stack used by another program command is permitted and validated there;
  unrelated stacks still reject. No getter, owner assignment or curve-table copy.
  An override replaces the effective base value; dormant overridden scalar values
  need not be finite/in range, but their schema, source ownership and stacks must
  remain valid. Missing common properties still reject.

## Working-state scope

- Programs do not publish declarations, authored properties or generated defaults
  into the caller. Candidate values already include required defaults and schema
  preflight. This preserves absent property/metadata distinctions. Standalone
  publication remains unchanged and explicit manifest queries can still register.
- Split private working-cache application from standalone publication. Only the
  executors can apply a fully checked candidate synchronously. The exact scratch
  command supplying the manifest executes after its candidate is applied.
- Snapshot the union of written native members and typed extra slots once, with
  exact scalar bytes, initialized flags and original store lengths. Restore them
  through an internal RAII scope on every exit. Use sparse slot snapshots and
  private store restoration/truncation, not Brush/StructDef copies or copies of
  whole working stores. Do not mutate authored values, metadata, readonly flags,
  owners, response tables, per-device caches or configuration generations.
- All recoverable errors precede the first write. Allocation failure follows the
  engine's existing fatal contract. No callbacks/yields/raw writes may intervene
  between preparation and execution.

## Regions and execution

- All commands share the center/normal. Preflight each evaluated radius and finite
  reciprocal; zero-radius stages do not execute. Query once at the maximum of
  positive command radii. The union is conservative for the admitted spherical
  bounded policy; selected leaves/nodes remain fixed through the logical dab as
  with existing programs. Kernels still apply their own falloff.
- Empty programs succeed as empty dabs after validating executor/frame;
  null program rejects. Empty/zero-region valid programs clear last-dab result
  sets and advance normal success counters/first-dab state, but leave working
  caches exactly as on entry and do not push a sample or capture.
- Nonempty execution pushes one stroke sample, makes the shared frame/context,
  then runs ordered commands with scoped working values. Mesh topology policy is
  the union of admitted command requirements; capture slots retain command index.
  Grid stages share one dab generation, moved-set union and finishDab, preserving
  Jacobi refresh and deferred normals. Refresh spatial bounds once at completion.

## Acceptance

- DRAW + SMOOTH on mesh/grid matches an independently configured raw program
  reference for unchanged inputs. Include both mesh neighbor modes and deferred
  grid normals. At least one command radius exceeds both the raw and first-command
  radius; prove movement in owners omitted by the smaller region.
- Typed extra stages execute exact large integers, floats and boolean thresholds,
  with differing overrides and configured local device stacks. Empty/absent extra
  slots, initialized zero/false slots, native static fields, invert and authored
  readonly owners/cache addresses remain exact after success and failure.
- A late invalid value/type/schema/stack/unsupported command rejects before the
  first stage's geometry, topology, sample, capture, state or slot publication.
  Include first/empty/nonfirst calls, raw edits, repaired calls, duplicate mixed
  aliases, invalid common IDs and typed overrides sent to the legacy entry.
- Verify exact undo/redo for actual mesh/grid program geometry. Retain standalone
  and legacy program baselines. Run fixture and addon-only native/Python gates,
  record binary hashes, update the task list and restore addon-only outputs.

## Folded review corrections

- Put typed-override rejection in both legacy prepareProgramDeclarations helpers,
  before registerScalars. Existing batch wrappers reach those helpers before
  writing brush/device state; the mesh wrapper reaches it before dyntopo.
- Program stack validation covers local configured stacks. Active inherited
  sources reject; unrelated dormant parent fields are not traversed. Preserve
  source-specific ownership checks: static noncommon values ignore dormant
  authored getters/NaNs, while common/dynamic getter-backed sources still reject
  without invocation even if overridden. An effective override can replace an
  invalid dormant base value, but cannot repair invalid schema/default metadata.
- Sparse restoration must restore slot bytes and initialized flags, then truncate
  both backing vectors to original lengths. Resolve slot addresses again after
  growth. Cover untouched holes, initialized zero/false, and static slots absent
  before execution; public evaluated setters alone cannot restore those states.
- Build the raw reference with an independently computed union radius. Explicitly
  query that radius on mesh; reset the grid reference's raw radius before every
  dab while giving stages their real radius overrides. Legacy working caches
  retain the last stage's values and must not truncate later reference queries.
- Require every fixture tool and a program-execution marker in the fixture gate;
  a successful compiler-only skip is not typed runtime evidence. Include mixed
  zero/positive/zero stages, later empty/all-zero programs, capture slots using
  original command indices, one sample per nonempty logical dab, and preserved
  pending normals/touched sets and working-state restoration.

Implementation audit corrections: resolve the empty-list wording in favor of
successful empty-dab bookkeeping (clear results and advance counters/first state,
no samples/capture/publication). Snapshot and restore existing extra-slot bytes
directly through private storage, preserving noncanonical floating-point payloads
without a typed copy; add a payload regression.

Final test audit corrections: defer inactive program-owned stack validation to
the owning command so mixed-manifest failures report that command's index.
Exercise DRAW followed by the typed fixture, pending later-command stacks and
unrelated local stacks. Test touched unset slots inside existing store lengths,
and getter refusal with an explicit base override. Start a fresh undo step before
the zero/positive/zero capture-index check; stale stamps from an earlier program
cannot establish which slot the new call used. Refresh raw mesh reference bounds
after each dab, and compare grid normals as well as positions with the raw oracle.
Snapshot those normals before undo/redo or full-normal recomputation can repair
the state under test. The first native run exposed an inadequate coarse mesh
fixture: its small query already included every moving owner. Increase only the
mesh fixture resolution and retain the strict outside-owner movement assertion.

## Bounded program execution evidence

Fixture and restored addon-only gates passed 2026-09-16.

- `applyResolvedProgram` uses fresh generated mesh/grid commands and prepares all
  stages before filtering or mutation. Typed float/int/bool overrides precede
  dynamics. The working-state scope restores native and extra values without
  publishing properties, declarations or defaults.
- DRAW/SMOOTH matches independently configured raw programs through three dabs,
  both mesh neighbor modes and immediate/deferred grid normals. There are 57 mesh
  and 416 grid moved vertices outside owners selected by the first stage's smaller
  radius. Exact position/store undo/redo, zero/empty stages, original capture
  indices and repaired rejection paths pass.
- Typed fixture programs pass exact large integers, boolean thresholds, static
  booleans, invert, readonly owners, absent stores, touched unset holes,
  noncanonical NaN cache payloads, mixed manifests and pending later-command
  diagnostics. Failed programs preserve geometry, samples and working state.
- Both original adversarial reviewers audited the implementation/test corrections.
  The state reviewer found no remaining blocker; the execution review's normal
  snapshot correction was applied before the final passing test.
- Fixture DLL SHA256:
  `45ff4ab3fdf6012e44f0e44ab69d84e61bc3a431b88060f3f920f4968c097f6e`.
- [Fixture native results](../tests/resolved-programs-final-results.json): 17/17.
  [Python binding results](../tests/resolved-programs-python.log): 11/11 against
  the exact DLL. [Engine build](../tests/resolved-programs-build-tested.log) and
  [final fixture-test build](../tests/resolved-programs-region-final-build.log)
  completed successfully.
- Restored addon-only DLL SHA256:
  `1768ac070f36088cc25626233f99420bfe76eacc305cedfb3643dfa21c170516`.
  [Addon-only build](../tests/resolved-programs-addon-build.log) and
  [Python smoke](../tests/resolved-programs-addon-python.log) passed.
  [Addon-only native results](../tests/resolved-programs-addon-results.json):
  17/17 after [rebuilding the cleaned test](../tests/resolved-programs-addon-final-test-build.log).
  Temporary region-count tracing was removed after the fixture run; the same
  strict movement assertions remain and pass in the final addon-only run.

The first compile found incorrect return types in test getter callbacks; fixed.
The first native gate found the coarse-mesh region fixture issue described above;
its failure is retained in resolved-programs-results.json. A transient wrong
fixture edit failed compilation and was corrected before the final passing build.
No bindings, addon routing or vendored runtime change in this slice. No headed
execution or full Plan 3 completion is claimed by this internal native gate.
