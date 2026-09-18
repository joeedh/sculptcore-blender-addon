# Generic brush properties — Plan 2 progress and evidence

2026-09-16 historical completion; **Brush authoring undo coverage reopened and
closed on 2026-09-17**. Earlier undo tests proved Scene-owned curve behavior,
not Brush memfile undo (which Blender skips). The explicit authoring API now
passes actual Brush widget Create/Edit undo/redo, collection/native restoration,
real custom sculpt undo interleave, owner replacement and history limits. See
[the final correction evidence](generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
The chronological notes below retain intermediate limitations.
Plan 1's [completion evidence](generic-brush-plan1-evidence.md) remains separate.

## Implemented native slices

Companion fork `C:/dev/blender/main`:

* `source/blender/blenkernel/BKE_curvemapping_idprop.hh` and
  `intern/curvemapping_idprop.cc`: scalar CurveMapping definition codec,
  non-destructive validation, independent materialization, and preservation
  of compatible unknown top-level fields. Existing IDProperty types only.
* `intern/curvemapping_idprop_test.cc` and CMake source registration:
  round-trip evaluation/copy, handles/clipping/extrapolation, malformed and
  version-unknown data, ID-free ownership, unsupported scalar settings and
  non-finite native evaluator rejection.
* `makesrna/intern/rna_sculpt_paint.cc`: automasking updates notify their
  actual Brush/Scene owner and tag Brush asset dirty state, rather than
  retrieving a possibly unrelated active brush or scene.
* `makesrna/intern/rna_color.cc`: native curve point/handle edits, insert/remove,
  clipping/extension/level changes and explicit update notify the actual owner.
  Selection, view reset and initialization remain presentation/read operations.
  Native point edits still need `CurveMapping.update()` to refresh evaluation.
* `build_files/cmake/platform/platform_win32.cmake`: retain generic imported
  tool locations as the last Windows configuration fallback. Without this,
  CMake 4.3 rejects `Git::Git` during generation. An isolated failing/passing
  reproduction is under `tests/cmake-git-import/` with corresponding logs.

The addon production property/mapping/stroke/UI modules and engine source have
not been migrated. No declaration of `bpy.props.CurveMappingProperty` exists yet.
Draft codec copies under `claudeMemory/implementation/` mirror the fork source;
the fork files are authoritative.

## Old-reader preservation — passed for the serialized format

All runs use `--background --factory-startup --python-exit-code 1 --python`.
Producer/prior-fork reader is the original staged Blender 5.3 binary recorded
in Plan 1. Stock reader is Blender 5.0.1, hash `a3db93c5b259`.
Actual executable hashes are in
`tests/owned-curve-compat-binaries.json`.

`scripts/owned_curve_storage_compat.py -- create|resave|verify DIR` tests nested
ordinary custom properties on Brush and Scene, normal files and external brush
libraries, absent declarations, unknown root fields and independent Brush.copy.
Typed assertions check integer flags/version and double coordinates/clip arrays.

* `tests/owned-curve-compat-v1`: stock 5.0.1 resave, producer readback passed.
* `tests/owned-curve-compat-prefork-v1`: prior-fork resave/readback passed.

`scripts/owned_curve_system_storage_compat.py` additionally uses real declared
PropertyGroups and CollectionProperty entries, therefore exercising Blender's
separate **system-property root**. It unregisters the declarations before the
producer save, and the old reader resaves without registering anything. The
producer re-registers ordinary groups and verifies nested data after readback.

* `tests/owned-curve-system-compat-v1`: stock resave/readback passed.
* `tests/owned-curve-system-compat-prefork-v1`: prior-fork resave/readback passed.

Stock Blender reports that the file was written by newer Blender 503.17.
The tested owned definitions survive despite that general warning. This is
evidence for these exact binaries and existing-type payloads, not a blanket
compatibility claim for arbitrary future Blender versions or other scene data.

These tests do **not** pass the full API compatibility gate: declaration,
materialization through the new RNA API, evaluation after old-reader resave,
real owned editor behavior and its asset Revert still need implementation.

## Native build and notification regression

Build directory: `C:/dev/blender/build_windows_x64_clang_RelWithDebInfo`.
Focused target: `blenkernel_curvemapping_idprop_test`.
`WITH_GTESTS=ON`, `WITH_TESTS_SINGLE_BINARY=OFF` were temporary test settings;
the original OFF/ON values were restored and configuration completed cleanly.
Restoration is recorded in
`tests/owned-curve-restore-config.log`.

Initial compilation caught a C-array Span constructor and missing
`BLI_listbase.hh` include; both were corrected. Enabling GTests rebuilds a
large set of Blender dependencies. A stale Freestyle precompiled header also
used a different MSVC patch version. Regenerating its owning object with
`SCCACHE_RECACHE=1` fixed that build artifact; Freestyle source was unchanged.
The focused native target and then `--target blender` both built successfully.
The latter updates the executable in the existing staged runtime. The broad
install target was interrupted before compiling unrelated standalone tests.

| Check | Result | Evidence under `claudeMemory/tests/` |
| --- | --- | --- |
| Registered CTest `blenkernel_curvemapping_idprop` | 6/6 native cases passed | `owned-curve-native-ctest.log`, `owned-curve-native-tests.log` |
| Native notification/asset script | 16 checks passed | `native-curve-notifications-test.log`, `native-curve-notifications-v1/results.json` |
| Fresh-process saved native endpoint | .375 passed | `native-curve-notifications-verify.log` |
| Frozen DRAW/CLAY/FILL/NUDGE geometry | All eight cases passed | `owned-curve-geometry-regression.log` |
| Mesh/grid batch parity | Mesh exact; grid max delta 1.1920928955078125e-7 | `owned-curve-batch-parity.log` |
| Headed actual modal/cancel | ESC retained dabs; second stroke worked; close cancel clean | `owned-curve-headed-cancel.log`, `.stderr.log` |

The headed run used `--factory-startup --enable-event-simulate
--no-window-focus -p 0 0 1280 800 --python-exit-code 1 --python
claudeMemory/scripts/test_stroke_cancel.py`, an explicit success marker and
stderr/traceback checks. Background checks used the flags above. No user
preferences were saved. Optional writes to the global asset-index cache were
denied; scratch workspace asset saves and readbacks passed.

Validated executable SHA256:
`43dcadcc9969c5a3ada8d86b42fa614b001e9fb5ea46ea4b1d14d776588c0735`.
Full identities are in `owned-curve-validation-runtime.json`. The build cache
is actually Release despite the historical RelWithDebInfo directory name.
This binary was built while GTests were enabled; restoring cache switches does
not rebuild it. The source and exercised behavior are the versions described
here. No engine source, DLL or production addon migration was changed.

`scripts/test_native_curve_notifications.py -- test DIR`, then `-- verify DIR`
uses two scratch external brush assets. One stays active while the other is
edited. Each mutation starts from a reverted definition; setup explicitly
restores a three-point curve and a .625 endpoint on every run. Checks include
actual dirty owner, rejected foreign point removal, inactive Scene value
isolation and clean brushes, presentation-only operations, and external
Save .375 / edit .75 / Revert .375 followed by fresh-process readback.

The original binary fails at the first assertion as expected:
`point location did not dirty its owner`.
Evidence: `tests/native-curve-notifications-baseline.log`.
This confirms the regression reproducer before using the rebuilt binary.
The Python Scene check does not inspect the native notifier queue; exact
notifier recipient is source-reviewed. Headed curve-widget mutation is a
separate outstanding gate.

## Adversarial review and remaining gate

Two reviews of the codec/storage test slice caught native evaluator NaNs from
otherwise finite coordinates, unsupported nested ID references, silently lost
point extensions, and unsupported RGB state. All were addressed in codec and
tests. Typed old-reader assertions and binary identities were added.

Two further fresh-context reviews rejected the first runtime/editor draft;
their concrete findings are recorded in
[the runtime implementation refinement](../plans/owned-curve-runtime-implementation.md).
Runtime implementation did not use the rejected model. The reviewed native
core is now implemented and validated below. In particular,
free hooks alone miss in-place property content replacement; generated RNA,
function results, bulk access and mathutils need explicit lifetime handling;
the curve UI needs persistent edit sessions and stable numeric staging fields;
native preset/paste paths bypass scalar restrictions; declaration callbacks
and nested nonallocating draw need dedicated handling.

The narrow native notification diff was separately reviewed with no surviving
code defect; test blind spots were either corrected or explicitly recorded.

Still required before checking Plan 2 complete: owned RNA declaration and
non-destructive dispatch, guarded runtime handles/iterators, transactional
initialize/unset/sync, read-only and callback behavior, persistent editor
sessions, undo/load/deletion/re-registration, full API old-reader readback,
and real owned-curve asset .375/.75/.375 Revert with dirty state.
Plans 3–8 remain behind the dependency gates in the task list.

## Native runtime core — completed subgate, 2026-09-15

Actual fork sources: `BKE_curvemapping_owned.hh`,
`intern/curvemapping_owned.cc`, `intern/curvemapping_owned_test.cc`; lifecycle
hooks in `idprop.cc`, `lib_id.cc`, `lib_id_delete.cc`; range-before-integer-index
conversion in `colortools.cc`. The addon `implementation/` directory contains
mirrors, not a separately executed substitute. Installation helper:
`scripts/install_owned_curve_core.py`.

The main-thread registry retains records keyed by stable definition-group
addresses. Exact frees use keyed lookup; subtree invalidation visits each node
once. Matching registered-owner destruction must be main-thread; unregistered
temporary/COW frees may run on workers. Removed records are released outside
map mutations/locks, and shutdown disables recursive hooks before draining.
Snapshots expose evaluation and deep-copy operations without writable native
pointers. Workers can evaluate retained snapshots after owner deletion.

Commit and sync validate before publication, preserve opaque root fields and
root flags, and reject stale/invalid/read-only changes without altering the
cached revision or snapshot. Library overrides are conservatively read-only
until declaration-aware RNA handling; editable linked brush assets are allowed.
Groups compare by key, strings by full bytes/subtype, numeric payloads by bits.
Flags/UI state are outside evaluator identity. Raw changes require explicit sync.

| Check | Result | Evidence under `tests/` |
| --- | --- | --- |
| Native compile and Blender relink | Passed | `owned-curve-core-final-build.log`, `owned-curve-core-test-rebuild.log` |
| Registered codec + runtime CTest | 6 + 8 cases passed | `owned-curve-core-ctest.log`, `owned-curve-core-native-tests.log` |
| Frozen geometry | Eight fixtures passed | `owned-curve-core-geometry.log` |
| Mesh/grid batch parity | Exact mesh; grid delta 1.1920928955078125e-7 | `owned-curve-core-batch.log` |
| Native notifications/assets | 16 checks passed | `owned-curve-core-notifications.log` |
| Fresh-process asset readback | .375 passed | `owned-curve-core-notifications-verify.log` |
| Headed modal cancel | Success marker; ESC/new stroke/close-cancel passed, no Python exception | `owned-curve-core-headed.log`, `.stderr.log` |

Native runtime cases exercise immutable-copy isolation; finite-authored invalid
evaluator rollback; valid raw conflict → sync → retry; invalid raw conflict
without repair; ordinary linked/editable asset/override policy; detach/reinsert;
ancestor content replacement; system collection growth/move/shrink; independent
owner copies; actual ID swap/free hooks; worker evaluation and temporary free;
registry-only retained records; opaque NaN payloads, signed zero, reordered keys,
embedded-NUL byte strings/subtypes; non-finite and extreme finite queries.

The first run found two harness mistakes, retained in
`owned-curve-core-ctest-first-run.log`: IDP_NewString does not preserve a NUL in
its input as a byte-string constructor would, and native sampled horizontal
endpoint evaluation differs slightly from authored 1.0. The corrected tests
construct actual byte payloads and use the established 1e-6 native tolerance.
These were fixture changes, not weakened transaction/lifetime assertions.

Validated Blender SHA256:
`ec0662e57bc8d39d91a4aa05b50fab318eb14b97fbf568c839eb14b8de7c898a`.
Runtime test executable SHA256:
`0036bfab0b454393bc6afa5f6286ee2feaaf69a3df9360c41763655f7d240170`.
The final test-only rebuild did not change Blender or production source.
Machine-readable identities: `tests/owned-curve-core-runtime.json`. The original
cache switches (`WITH_GTESTS=OFF`, `WITH_TESTS_SINGLE_BINARY=ON`) were restored
after validation; this does not replace the tested executable. Restore log:
`tests/owned-curve-core-restore-cache.log`.

This completes only the native core slice. No `bpy.props.CurveMappingProperty`
capability is advertised yet. Native notifications in the regression matrix
exercise existing curves; Python owned wrappers, declaration generations,
transactional initialize/unset, UI sessions, callbacks, undo/load and complete
owned-API asset/old-reader gates remain required before Plan 2 is complete.

## Owned RNA — functional subgate, 2026-09-15

Implemented the real `bpy.props.CurveMappingProperty` declaration, guarded
native CurveMapping/CurveMap/point wrappers, transactional initialize/unset/sync,
declaration generations, finite-number validation before clamping, retained
function/mathutils/iterator validation, and actual-owner callbacks/dirty state.
Atomic root-path initialization stages missing pointer ancestors off-tree.
Unknown versions and malformed siblings survive ordinary reads unchanged.

Callbacks may delete their owner or unregister themselves. Same-curve recursive
callbacks are suppressed; a callback which removes its curve/item/ancestor may
not recreate an absent instance of that declaration on the same owner until it
returns. This correction was reviewed independently by both RNA reviewers.

| Actual check | Result | Evidence under `tests/` |
| --- | --- | --- |
| Full native build | Passed | `owned-curve-rna-build.log` |
| RNA lifecycle, mutation, conversion and callback suite | 25 checks passed | `owned-curve-rna/test.json`, `owned-curve-rna-test.log` |
| Saved owned curve, fresh process | Passed | `owned-curve-rna/read.json`, `owned-curve-rna-read.log` |
| External owned brush Save As/Save/Revert .375/.75/.375 | Passed | `owned-curve-assets/test.json`, `owned-curve-assets-test.log` |
| External owned asset, fresh process | Passed | `owned-curve-assets-read.log` |
| Stock 5.0.1 and prior-fork resaved fixtures, real new API | Passed | `owned-curve-rna/old-reader-api.json`, `owned-curve-rna-old-reader.log` |
| Headed edit/init undo, redo, wrapper invalidation, nonallocating draw | Passed | `owned-curve-rna/headed.json`, `owned-curve-rna-headed.log` |
| Existing native curves/dirty notifications | 16 checks passed | `owned-curve-rna-native.log` |
| Existing native asset, fresh process | Passed | `owned-curve-rna-native-read.log` |

Tested pre-format binary SHA256:
`54b83d6b7a8a8b07d52c9ea05cbcdd78005fb444ee08b31396ed5da828a38934`

The formatting rebuild passed. Its binary SHA256 is
`ccb01cd9618433c4093cea4b6e1563c60bbae405c3fba57d7c87f78f3d6c8b84`.
The 25-case RNA suite, owned external-asset suite, and fresh-process RNA, asset
and both old-reader checks passed again (`owned-curve-rna-formatted-test.log`,
`owned-curve-rna-formatted-assets.log`, `owned-curve-formatted-*-read.log`).
These results do not claim the editor gate: the
headed test records `editor_drag_tested: false`, and the template still displays
a temporary integration guard. The reviewed editor implementation is tracked
in [owned-curve-editor.md](../plans/owned-curve-editor.md).

The first full suite retained native allocations on shutdown. Isolated phase
probes traced this to the Python `libraries.load` context dictionaries retaining
the dynamic test classes/namespace. Explicitly releasing those test-only
dictionaries made the full suite exit cleanly; ordinary owned handle/function/
iterator probes also exit cleanly. No production lifetime policy was weakened.
The exact CPython reference cycle remains an inference, not a proved native
leak diagnosis. Debugging details and probe entry points are in debugging.md.

Remaining Plan 2 gates: actual graph transactions and pointer events, capability
and revision API/documentation, final formatted binary regression matrix, and
the complete editor lifecycle/asset gate. Plans 3–8 remain incomplete.

## Editor support slice — compiled and native guards tested

Added independent path-watch tokens to reject stale first-initialization UI
targets. Array relocation invalidates every watched inline descendant without
detaching existing curve records. Owner tokens exist even for absent property
storage. Group membership/replacement, array resize/set-index, actual RNA move,
and existing free/swap hooks invalidate the appropriate watches. These fixes
were reviewed against identical empty items and pointer reuse, including
temporary frees on worker threads.

The RNA editor interface inspects absent pointer ancestors through metadata
without allocating saved groups. Existing-curve transactions pin their original
revision and commit once; callbacks may delete owners/declarations. Compiled
successfully in `owned-curve-editor-support-build.log`.

Actual native tests: **11 runtime cases and 6 codec cases passed**, including
new group mutation/lifetime, array identity/relocation, content replacement,
unrelated temporary allocation, and owner/all-watch invalidation assertions.
Evidence: `owned-curve-editor-support-native-build.log`,
`owned-curve-editor-support-native-tests.log`,
`owned-curve-editor-support-codec-tests.log`. Original GTest/cache switches
restored in `owned-curve-editor-support-restore-cache.log`.

The dialog and native graph hooks are now implemented but their build and
headed interaction gates are pending. Do not count the native guard tests as
proof of actual button movement, drag, cancellation or first-initialization
undo behavior.

## Actual editor and cache API — 2026-09-15/16

The dialog is implemented and built. Initial headed binary SHA256
`db9754853a267732387290dffde2cfec3cd28e5ab19c7bb1c98fb5b56f482a2a`
passed nonallocating drawing, explicit creation, graph dragging, numeric Apply,
single edit/init undo and redo, Escape during a held drag, stale revision Apply,
embedded NodeTree creation, stale empty collection buttons, original-item edits
after move/growth, removed-item rejection, and invalid clip rejection. Evidence:
`tests/owned-curve-editor/` screenshots, action log and partial result JSON.
Some early driver assertions failed because events had not reached the event
loop; subsequent spaced-event checks and screenshots establish the listed cases.

The cache API binary SHA256 is
`9e68ce53d752076933f64119c5fddf414e6f188a4ad7ad85782c264c07b33983`.
It exposes `bpy.props.owned_curve_mapping_api_version = 1` and guarded exact
integer `(record_identity, revision)` cache keys. Unchanged raw sync no longer
notifies or calls Python. API version means availability, not a passed gate.

Actual checks on this binary:

| Check | Result / evidence under `tests/` |
| --- | --- |
| Cache lifetime, raw sync, GC, declaration replacement, copy, deletion, load and worker rejection | 13 passed; `owned-curve-cache-api-test.log`, `owned-curve-cache/test.json` |
| Existing RNA suite and fresh read | 25 passed; `owned-curve-cache-rna-regression.log`, `owned-curve-cache-rna-read.log` |
| External assets and fresh read; unchanged sync leaves callback/dirty state unchanged | Passed; `owned-curve-cache-assets.log`, `owned-curve-cache-assets-read.log` |
| Headed RNA/cache undo/redo, captured-method rejection | Passed; `owned-curve-cache-headed.log`, `owned-curve-rna/headed.json` |
| Generated API methods/factory/constant plus indexed guide | Passed RST generation; `owned-curve-cache-docs.log`, `owned-curve-guide-docs.log`, respective `*-docs/sphinx-in/` |
| Scene and Brush collection deep copies; real Object library override rejects mutations | 3 passed; `owned-curve-copy-policy.log` |

Final headed session (`owned-curve-editor-final/controls.jsonl` and screenshots)
additionally verified staged clipping/extension, right-click/outside cancellation,
scalar clipboard no-op/commit, incompatible RGB paste (source independently
verified through native paste), Apply callbacks deleting owner/declaration,
two windows editing one curve with stale second Apply, insertion and Vector
handle editing. Actual external brush dialog editing passed .375/.75/.375
Save/Revert with only its actual owner dirty and one callback; separate process
read both assets at .375 (`owned-curve-editor-asset-fresh-read.log`).

The session was stopped after its 32767-point raw construction/sync exceeded
the request deadline and continued consuming CPU. It was test-owned PID 30392;
successful earlier checks remain recorded, but no full-session PASS is claimed.
The reviewed [array-watch correction](../plans/owned-curve-array-watch-performance.md)
addresses full-array scans on every SetIndex/append. Selected-point removal has
an unresolved headed assertion and must be diagnosed/retested. Driver failures
from asynchronous asset loading, popup dimensions, no-op presets and class
lookup are retained in the action log; none are claimed as passing gates.

Plan 2 remains open pending this correction, point boundary/removal checks and
the final regression matrix, including the existing headed stroke cancellation.

The array correction passed **14 runtime and six codec native tests**.
Encoding with an unrelated live watch took 0.002510 s for 2048 points,
0.015627 s for 8192 and 0.073129 s for 32767. Tests distinguish in-capacity
growth/shrink, reallocating growth/shrink, equal-content slot replacement,
untouched siblings and nested watches. Logs: `owned-curve-array-watch-native-tests.log`
and `owned-curve-array-watch-codec-tests.log`. The corrected installed Blender
and headed retest are still pending; timings are for the actual native codec.


## Completion gate — 2026-09-16

Installed Blender SHA256:
`5d444c284ee157403f8c9437b9e98c4ac287e6ba84623781070902433c550224`.
The final source cleanup only removes three duplicate comment headers.

The point-removal failure was a driver error: hiding the selected-point rows
moved Apply upward by 62 pixels. Screenshots before/after Remove showed the
working point actually removed; clicking the old Apply position canceled the
popup. The corrected driver passed insertion, Vector handle and removal, each
with exactly one commit callback. No production guard was weakened.

Both graph insertion paths reject 32767-point curves without a revision or
callback change. In the actual headed process, raw construction/sync took:

| Points | Raw construction | Explicit sync |
| --- | --- | --- |
| 2048 | 0.00220 s | 0.00339 s |
| 8192 | 0.01346 s | 0.01258 s |
| 32767 | 0.06445 s | 0.04822 s |

Evidence: `tests/owned-curve-editor-array/controls.jsonl`, screenshots and
`test.json`. The JSON labels this individual session partial because earlier
sessions cover the rest of the editor matrix. Combined recorded sessions cover
the complete Plan 2 gate; no single session is claimed to cover every case.

Final installed-binary regressions all passed:

| Coverage | Evidence under tests/ |
| --- | --- |
| 25-case RNA lifecycle and fresh file read | owned-curve-final-rna.log, owned-curve-final-rna-read.log |
| 13 cache API cases | owned-curve-final-cache.log |
| 3 copy/override policy cases | owned-curve-final-copy.log |
| Owned external asset Save/Revert and fresh read | owned-curve-final-assets.log, owned-curve-final-assets-read.log |
| Stock/prior-fork preserved fixtures materialized through real API | owned-curve-final-old-readers.log |
| 16 native curve notification cases and fresh asset read | owned-curve-final-native.log, owned-curve-final-native-read.log |
| Headed RNA/cache undo/redo and template | owned-curve-final-headed.log |
| Headed ESC and window-close stroke cancellation | owned-curve-final-stroke-cancel.log |
| Eight frozen geometry cases, bit exact | owned-curve-final-geometry.log |

The headed logs contain no traceback or failed assertion; stderr records the
existing sandbox denial reading Blender's user recents.toml. Native codec/runtime
results (6 + 14), actual GUI Save/Revert (.375/.75/.375), transaction lifecycle,
multi-window rejection and generated RST API documentation are recorded above.
Library overrides are explicitly read-only in v1; rejected edits preserve data.
Old-reader compatibility is limited to the actual tested binaries/payloads.

Plan 3 remains open. Engine typed evaluation is being implemented separately;
Plan 2 completion does not advertise migrated addon properties or device inputs.
