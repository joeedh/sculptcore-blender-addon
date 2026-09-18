# Plan 5 completion evidence — 2026-09-17

Plan 5 is complete. The [verified manifest](../tests/plan5-completion-gate.json)
records commands, runtime hashes, installed source equality and individual gates.
The [implementation plan](../plans/generic-brush-curve-evaluation.md) received
two fresh adversarial reviews before implementation: engine transport/evaluation
and Blender sampling/ownership. Their surviving findings are recorded there.

## Implemented behavior

- `brush_properties/responses.py` implements all ten frozen presets. Continuous
  responses become immutable float32 tables. CONSTANT and TWO_STEP retain exact
  finite double parameters as analytic descriptors. The engine compares promoted
  float input against the original double threshold, including thresholds between
  adjacent float values, before converting the selected level.
- `sampling.py` shares immutable content with bounded 256-entry content and
  source indices. Owned references validate owner, declaration and record revision
  before reuse. Changed owned definitions use complete visible evaluation fields;
  native definitions use the fork's canonical bytes, including hidden flags.
  Owned v1 forbids wrapping and fixes unsupported fields. Default insertion
  handles affect future points; existing point handles determine current samples.
  Full equality authorizes reuse, independently of hash collisions. Cache keys
  contain values, never Blender IDs/RNA wrappers. Load, undo/redo and unregister
  clear samples and advance the upload epoch. Dead owners reject access.
- `customize.py` seeds a first owned CUSTOM mapping with 256 vector-handle points.
  Returning to CUSTOM preserves dormant data; reseeding is explicit. Brush native
  pressure mappings remain authoritative and are preserved unless explicitly
  reseeded. Float32 coordinates validate before mutation, overshoot disables
  clipping, and TWO_STEP customization reports its editable approximation.
  The grouped authoring scope rolls back failures, including failed commit.
- `uploads.py` separates installation state from shared samples. Reuse requires
  the same live engine wrapper, command, configuration generation and lifecycle
  epoch. Uniform query validity is checked even on a warm hit. Memos publish only
  after all requested stack writes succeed. Command A/B/A and replacement targets
  reinstall. This supplies the cache boundary; command execution adoption is Plan 6.
- Engine DynamicDevice validation, equality, copies, typed evaluation and staged
  table replacement understand analytic responses. New checked Common/Uniform
  whole-stack calls accept kinds and double parameters. Legacy table APIs switch
  back to table mode only when a complete valid table is published.
- The Python bridge validates primitive arrays, resizes owning vectors and assigns
  through their contiguous NumPy views. It disposes them deterministically and
  copies layer inputs into immutable tuples. Checked 256-entry falloff/cavity
  methods reject malformed requests before changing the native arrays.
- Actual `mapping.py`/`stroke.py` consumers now cache pressure, falloff, cavity and
  spacing compensation. Direction, hardness, clipping and geometry remain
  compatible. Pressure upload generations are recorded after checked authored
  scalar writes; unchanged scalar synchronization avoids redundant writes.
  Native fingerprinting, sampling and table hashing occur at stroke start, never
  per dab. Legacy falloff/cavity memos are scoped to the session target and epoch;
  an external raw table writer must invalidate that consumer's memo/epoch.

No additional Blender fork edit was required in this plan. The staged fork is
the Plan 4 build with the owner-aware mapping and native-authoring APIs.

## Completion gates

| Gate | Evidence |
| --- | --- |
| Pure formulas, endpoints, step boundaries, collisions, bounded LRU and failed commit cancellation | `plan5-response-cache.log`: 6 tests; foundation regression: 11 tests |
| Actual Blender custom/native revisions, first customization/reseed, dormant state, failure rollback, 270 edits and 270 owner switches, linked read-only rejection | `plan5-curves.checks.json`: 30 checks |
| One-step Brush/Scene undo/redo, save/load, dead owner and re-registration | `plan5-curve-undo.checks.json`: 11 headed checks |
| Actual typed DLL transport, integer precision, nextafter thresholds, invalid requests, table switching, bulk copies, command/target/query invalidation | `plan5-checked-bindings.json`: 15 check groups |
| Final addon-only native regression matrix | `plan5-restored-gate-results.json`: 17/17 suites |
| Fixture mesh/grid/typed execution | 16 fixture suites passed; the configuration harness initially kept its local Brush alive through the leak check. Its lifetime was corrected and the same configuration tests passed in the final addon-only matrix. This failure was in the test harness, not the upload API. |
| Actual unchanged warm stroke | `plan5-modal-cache.checks.json`: zero bakes, pressure uploads, fixed-table uploads and overlap bakes |
| Curve edit and engine/lifecycle invalidation | Same headed gate: one pressure edit causes one bake; engine-stack clear reinstalls without baking; lifecycle clear refreshes all required data |
| Mesh/grid, Python/batch, queued/delayed modal regression | `plan5-modal-inputs.json`: all eight cases pass |
| Frozen geometry | `plan5-geometry.json`: original fixture geometry comparisons pass |
| Native authority and asset cleanliness | 150 native adapter checks; 5 external asset Save/Revert checks with cold/warm sampling; 6 fresh-process asset checks including sampling a linked read-only mapping |
| Matched package | `plan5-package-smoke.json` verifies vendored dependency provenance; `plan5-packaged-api.checks.json` exercises new APIs on two engine targets and excludes fixture kernels |
| Generated declarations | 15 Python and 74 TypeScript files generated from the final native DLL; standard formatter and TypeScript check pass |

The final manifest verifies **11 Blender runs, 17 native suites and 17 pure tests**.
It also verifies installed addon/Python bridge/stub bytes and the packaged DLL
against the build output. The fixture DLL has its own recorded hash.

### Real stroke counters

Columns are new sampled tables, pressure stack calls, fixed-table uploads and
overlap evaluations. Pressure installs cover strength and radius as one memo.

| Scenario | Counters |
| --- | --- |
| Cold | 3, 2, 2, 1 |
| Unchanged warm | 0, 0, 0, 0 |
| Pressure point edited | 1, 2, 0, 0 |
| Native pressure stack cleared | 0, 2, 0, 0 |
| Lifecycle invalidated | 3, 2, 2, 1 |

The replacement-engine package test additionally proves cached falloff/cavity
tables upload to a new engine Brush while subsequent warm calls do not upload.

### Cold/warm synchronization profile

Five repetitions per operation in actual packaged Blender, median milliseconds.
This is a local diagnostic measurement, not a cross-machine performance promise.

| Operation | Cold before fixed-table bulk | Cold final | Warm final |
| --- | ---: | ---: | ---: |
| Pressure (already bulk) | 2.251 | 1.555 | 0.055 |
| Falloff | 2.453 | 0.626 | 0.023 |
| Cavity | 2.774 | 0.629 | 0.027 |

Recorded in `plan5-curve-profile-before-bulk.checks.json` and
`plan5-curve-profile.checks.json`. Warm pressure timing includes native fingerprints
and installation validation. No missing-DLL dialogs occurred in these launches;
all explicit Blender tests used the dialog-safe launcher.

## Reproduction

Use Blender's bundled Python at
`C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/python/bin/python.exe`.
Launcher arguments and markers are recorded verbatim in the manifest. Key tools:

```text
node make.mjs build native --kernels-extra "../brushes;tests/assets/typed_extras" -j 8
python claudeMemory/scripts/test_checked_brush_bindings.py
node make.mjs build native --kernels-extra ../brushes -j 8
node make.mjs build python --kernels-extra ../brushes -j 4
python claudeMemory/scripts/run_typed_engine_gate.py --prefix plan5-restored-gate --extended-registration --named-storage --compiler-boundaries --configuration --prepared-execution
python claudeMemory/scripts/generate_checked_brush_bindings.py --prefix plan5-generated-bindings --write-source
node claudeMemory/scripts/format_checked_typescript.mjs plan5-generated-bindings
node tools/build-blender-dist.mjs --skip-blender --skip-engine --build-dir C:/dev/blender/build_windows_x64_clang_RelWithDebInfo --config Release
python claudeMemory/scripts/record_plan5_completion.py
```

Engine dispatcher commands run inside `engine/`; addon scripts run at the addon
root. Run build configurations sequentially. The native fixture build is restored
to addon-only before final binding generation. Complete Blender test processes
before replacing their loaded staged runtime.

## Remaining work

Generic property consumers remain default-off. Plan 6 must adopt resolved values
and independent command stacks throughout all stroke paths. Plan 7 owns the
generic UI and automasking consolidation. Plan 8 owns migration, compatibility
and the default switch. TypeScript declarations are checked; TypeScript runtime
transport is not claimed by this Python/Blender gate.
