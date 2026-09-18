# Generic brush implementation history

This is historical context, not instructions or current acceptance evidence.
Current behavior and defects are in [the implementation reference](generic-brush-properties.md).
The [remaining task list](../plans/generic-brush-properties-tasks.md) is authoritative
for unfinished work. Superseded proposals must not be used to infer approval.

## September 15–18, 2026

| Work | Result and qualification |
| --- | --- |
| Contracts/inventory | Froze native/generated defaults, owner policies, numeric semantics, input provenance and baseline files/assets. |
| Owned CurveMapping | Implemented tagged storage, safe RNA handles, transactional editor, copy/save/revert and owner notifications in the fork. Initial Scene undo evidence did not prove Brush undo; that gate was reopened and closed with explicit authoring undo. |
| Typed dynamics/input | Added checked float/int/bool declarations, named storage, compiler/binding transport, event timestamps/presence and interpolated input delivery. |
| Generic authoring | Added atomic records, native adapters, independent owners, stack/position persistence, custom curves, frozen legacy reads and explicit Brush/Scene undo. |
| Presets/cache | Added analytic constant/step responses, generated/custom sampling, bounded content/revision caches and upload identity. |
| Execution | Expanded checked preparation through commands, masks, automasking, nonaccumulation, grab, previews, dyntopo, attributes, cage smoothing and layers. Generic consumers are implemented behind opt-in. Full integration is incomplete. |
| UI/migration | Not completed. Two UI groundwork modules are not integrated. No default rollout. |
| Test infrastructure | Added an opt-in loopback debug server and dialog-safe native launcher. Main-thread execution, bounded requests, uncertain-running timeouts, lifecycle shutdown and child-only DLL search paths are documented in the debug-server reference and regression guide. |

The implementation over-expanded the execution work and accumulated hundreds of
scripts, repeated gate reports and generated artifacts. Tests often proved a
narrow slice rather than completion of the user-facing system. New cleanup
commits retain executable regression coverage and frozen inputs while removing
chronological evidence from the active documentation surface.

## Decisions extracted from retired plans

| Retired plan family | Durable information now maintained |
| --- | --- |
| owned-curve runtime/core/RNA/editor/API/array-watch | Tagged format and independent copy; immutable runtime records, declaration/path/point lifetime checks; staged widget editing; exact cache keys; invalidate relocation without quadratic append scans. See implementation reference and fork API docs. |
| atomic-scalars, authoring-undo, undo-reregistration | Atomic custom-root publication; explicit bounded authoring scope; Brush memfile limitation; identity-based ID restoration; no-op redo preservation; stable ObjectModeType Python base. |
| foundation/storage/stacks/positions/native-adapters/frozen-authoring | Independent value/stack ownership, native authority, compound size/cavity policies, unique devices, unknown-schema preservation, frozen defaults and legacy fan-out. See contract and schemas. |
| typed-core/registration/generated-registration/typed-extras/named-storage/checked-configuration | Exact typed declarations/transport, atomic registration, manifest query lifetime, static eligibility, typed stores and shared compiler validation. See native APIs and implementation reference. |
| curve-evaluation/execution-domains/snapshots | Analytic discontinuities, revision/content cache boundaries, semantic evaluation before unit conversion, immutable owner-free stroke snapshots. |
| prepared-execution/programs/command-automasking/enhance | Whole-program preflight, independent command settings, support union and per-configuration first-contact caches; command-dependent hooks cannot be deduplicated by address. |
| prepared-mask/mask-finer-undo/nonaccum/boundary-smooth | Exact multilevel mask restoration, incarnation/debt identity, original-position semantics and live boundary-neighbor requirements. |
| prepared-grab/preview/dyntopo/attributes/cage/layer | From-base grab, preview cache reset, pre-remesh rejection, post-remesh regions, actual attribute target capture, lazy executor binding and pinned layer state. The all-node grab policy is not accepted. |
| prepared-unbounded/kelvinlet-numerics | Explicit extended support only, independent command extents, finite cutoff/force math and checked rejection under host FTZ/DAZ. |
| plan3/plan4 completion and plan6 integration | Historical run orchestration, not additional product requirements. Remaining acceptance criteria are retained in the single task list. |

## Explicitly superseded conclusions

- A nonzero falloff endpoint, Gaussian response or nonspherical shape does not
  authorize unbounded reads. Ordinary brushes hard-clip at their falloff boundary.
  The all-node reference used by the earlier falloff gate encoded a wrong policy.
- Anchored grab likewise does not gain an unbounded declaration merely by being
  anchored. Bounded pinned-region handling must replace that shortcut.
- Passing a legacy/prepared route does not prove generic owner resolution ran.
  Current generic gesture tests instrument semantic evaluation and checked calls.
- Earlier documents saying pressure support, execution adapters or Brush undo
  are wholly absent describe intermediate states, not the current source.
- Hidden NodeTrees were investigated and rejected as custom-curve storage.
- Full arbitrary Brush copy/swap was rejected as the authoring undo design;
  the implementation uses a selected native property scope.

## Historical verification, not a fresh certification

Recorded runs included 35 native suites; 2,200 native semantic comparisons;
78 generic headed gestures across mesh/grid, per-dab/batch, release/cancel and
undo/redo; 20 view-normal/backface host cases; frozen plain/pressure basic
geometry; generated bindings/typecheck; and package provenance smoke.
Those counts describe runs before cleanup, not a requirement to rerun every
case for a documentation edit and not a guarantee that the falloff policy was
correct. The eight richer frozen geometry cases exposed the compatibility
failure. Keep that failure visible until corrected independent expectations
and bounded-read tests pass.

## Cleanup verification — September 18, 2026

Removed 4,988 generated artifact files, 44 subsidiary plans, duplicate native
source templates and 120 obsolete scripts/helpers. Retained 36 frozen inputs
unchanged, with SHA256 checksums in `tests/fixtures.json`; consolidated decisions
into the implementation reference, regression guide and single remaining task
list. This is a new commit, with no history rewrite or production-code changes.

Verification: 42 unit tests, all 18 authoring cases and all seven runtime cases
passed across the initial runs and focused corrective reruns. Draw and preview
passed 16 headed gestures, including cancellation and undo/redo. Removing cached
output exposed missing create/resave dependencies in reload tests and a curve
cache test's dependency on another test's scratch library; the runner now supplies
the prerequisites and the cache test creates its own input. A stale operator
mock was also updated to initialize its generic state. Assertions were preserved.

The installed Blender executable SHA256 was
`1c93a65f4ed4f53ca3a18bf34c1808c5802341e9a26356b46bdc3ca74b28ba84`.
Remaining Python scripts parsed, frozen-input hashes matched, generated outputs
were ignored, and staged whitespace checks passed. Native tests were not rerun
for this cleanup. The known spatial-policy failure and unfinished UI/migration
remain open; this verification does not close those implementation gates.

## Recovery without keeping artifacts in the working tree

The existing commits preserve the original material; cleanup does not rewrite
history or claim to reduce old Git object storage:

- Addon `dbbd225`: original plans, review transcripts, test scripts/results,
  baseline fixtures and duplicate source-install templates.
- Engine `ba915d14`: native implementation and regression tests.
- Blender fork `fd28e6d5510`: native API implementation and documentation.

For a specific historical question, inspect just the relevant file:

```powershell
git show dbbd225:claudeMemory/plans/generic-brush-authoring-undo.md
git show dbbd225:claudeMemory/tests/plan6-host-policies-gate.json
```

Do not restore entire evidence directories or feed old review transcripts into
ordinary development context. They include failed drafts, stale statuses and
superseded behavioral assumptions. Preserve a new failure artifact outside Git
only while diagnosing it; put the durable finding into maintained documentation.
