# Generic brush regression guide

Use a small number of suites selected by the changed boundary. Do not reproduce
the historical sequence of plan gates. Native engine tests remain in
`engine/tests/`; fork API tests remain with their canonical native sources.
The addon scripts exercise Python/RNA, installed-runtime and interactive seams
that those native tests cannot cover.

## Routine entry point

Run `claudeMemory/scripts/run_brush_tests.py --list` for the exact current cases.
Use the bundled Blender Python (or a Python with the required dependencies):

```powershell
$brushPython = 'C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/python/bin/python.exe'
& $brushPython claudeMemory/scripts/run_brush_tests.py --suite unit
& $brushPython claudeMemory/scripts/run_brush_tests.py --suite authoring
& $brushPython claudeMemory/scripts/run_brush_tests.py --suite runtime
& $brushPython claudeMemory/scripts/run_brush_tests.py --suite gestures --case draw
```

| Suite | Select when changing | Coverage |
| --- | --- | --- |
| unit | Resolver, arithmetic, presets, input sampler or error propagation | Independent ownership/type/curve/command/input expectations without Blender |
| authoring | Saved records or native adapters | Actual RNA, atomic records, independent stacks, positions, curves and fresh-process persistence |
| runtime | Snapshot, conversion, cache or native transfer | Native semantic parity, effective owners, mesh/grid execution, automasking and unchanged basic geometry |
| gestures | Modal path, cancellation or undo | One parameterized mesh/grid × per-dab/batch × release/cancel matrix; route fixtures for preview, dyntopo, paint, cage and layers |
| native | Native engine semantics | Existing dispatcher suites; outputs are local, not committed |
| known-falloff | Investigating historical footprint differences | Frozen-footprint diagnostic includes old leaf-dependent spill; it is not the oracle for the corrected hard boundary |

The default is `unit`, not the full matrix. `--case` narrows a suite.
Fresh-process authoring cases automatically include their create and addon-disabled
resave prerequisites. Earlier runners relied on existing `without-authoring.blend`
output; deleting the artifacts exposed that missing dependency. These files must
be generated during the run, never treated as committed expected results.

Run one
headed process at a time. The dialog-safe launcher suppresses Windows loader
popups and requires a success marker plus clean exit. Use `--blender` to select
a staged install; the launcher records the actual executable hash. Stage changed
addon Python with `stage_test_addon.py`; rebuild/vendor the DLL only for engine
changes. Unit checks use checkout source; installed checks need a matching stage.

`gestures/cache` runs the existing cache driver in generic mode. Draw also checks
a second stroke after independent owner changes; Program starts with zero base
autosmooth and enables it through dynamics. These extend the existing fixtures.

The standalone checked-binding drivers require probe kernels. Build them with
`node make.mjs build native --kernels-extra ../brushes --kernels-extra tests/assets/typed_extras`
inside `engine/` before running `test_checked_brush_bindings.py` or
`test_property_command_bindings.py`. The production DLL lacks those test kernels.
Keep the production `build/python` DLL in staged packages; clear
`SCULPTCORE_PYTHON_PATH` and `SCULPTCORE_CAPI_PATH` when verifying vendored provenance.

## Less frequent coverage

For standalone fork GTests use `run_blender_native_tests.py` with explicit
`--blender-bin`, `--assets-dir`, `--release-dir`, `--output-dir` and
`--test executable=expected_count`. Use the current executable's expected count,
not a historical count copied from a gate report. The launcher prepends the
install's `blender.shared` and `bin` directories to the child PATH, preserves
and restores Windows error-mode flags, clears inherited GTEST filters/shards,
and requires matching positive completed/pass counts. A zero exit with no tests
is a failure. Timeouts reap children and preserve partial local output. No DLL
copying or global PATH changes are needed. The dedicated negative harness covers
actual suppressed loader failure, missing executables, timeout and false passes.

Retained asset and editor drivers are specialist regression tools, not mandatory
steps after every edit. They create scratch data under the ignored output root.
Run asset lifecycle checks for persistence/migration changes; run authoring
collections/custom-mode/identity/history and native widget tests for undo or
editor changes. Their fresh-process and actual widget behavior cannot be replaced
by checking setter return values. Debug-server protocol and native-launcher
tests are independent infrastructure tests.

The existing `test_authoring_custom_undo.py` driver covers real bracket events by
default. Pass `--args radial` to its dialog-safe headed launcher for F/Shift-F
owner/domain, numeric, precision, cancel, undo and teardown checks; use
`--args radial-legacy` for the generic-disabled native fallback. `--args rows`
checks typed row operators, independent pressure owners, inheritance and undo;
`--args rows-ui` drives the actual searchable panel/numeric widgets and checks
non-mutating draws. The widget case uses the launcher's fixed 1280×800 window.
`--args stacks` checks ordered stack operations, presets, dormant custom mappings
and undo/redo with opposite value/stack owners. `--args stacks-ui` exercises
native curve graph edits, Apply/Cancel, undo/redo and addon shutdown, plus the
inherited owned-curve widget. These extend the same fixture, not separate suites.
`--args placements` checks actual header/settings/context-menu/automasking draws, staged
placement widgets, sorting, unknown locations, reset/empty layouts, stale drafts,
undo/redo and owner-aware size units. Follow it with a background
`--args placements-reload` run to check a saved copy of the edited Brush and
unsaved transient search. External active assets are resolved lazily after file
load; that lifecycle belongs to the asset/migration gate.
`--args panels` checks the canonical automasking panel, native cavity/falloff
curve widgets on both owners, native sculpt dispatch, independent main-window
scenes, linked-owner guards and non-mutating narrow Properties drawing.
The runtime `automask` case covers 40 mesh/grid × single/program strokes with
view-normal/backface and cavity/custom/inverted settings. Launch its same script
headed with `--args ui` to author those settings through the actual property
operators before executing the strokes. The background variant writes through
the same resolved stores without UI undo.
The authoring `frozen-fresh` case also checks migration and RNA aliases: authored/unset
values, shared-name fan-out, preservation of native and unknown data, atomic
rejection, changed/missing DLL defaults, idempotence and fresh linked reads.
The custom-undo fixture's `--args migration` variant checks migration rollback,
single-step undo/redo and no undo entry for repetition in SculptCore and Object
mode, plus actual timer-driven late activation. `authoring/migration-fresh` runs
the production external-asset create/save/revert, disabled-addon resave and fresh
linked-read phases automatically. It checks the independent standalone reminder,
custom/generated curves, copies, placement, Essentials Save As and missing kernels.
The frozen fixture checks driver-variable reads and refresh, and verifies the
fork's existing rejection of Brush-owned drivers/keyframes.
For example:

```powershell
& $brushPython claudeMemory/scripts/run_blender_test.py --script claudeMemory/scripts/test_authoring_custom_undo.py --headed --prefix brush-radial --marker AUTHORING_CUSTOM_UNDO_OK --timeout 180 --args radial
```

Old slice-specific host drivers were retired where the current generic runtime,
parameterized gestures and native prepared-execution suite cover the same
boundary. Standalone scalar/stack/placement Scene undo demos were superseded by
the combined Brush collections/native/custom-mode undo tests. Early transient
strength-owner demos were superseded by persistent native adapter tests.
The historical falloff diagnostic is retained even though hard clipping can differ. No test was
removed merely to turn a failing gate green. Keep native edge cases, including
typed invalid input, program atomicity, radius union and multilevel undo.

## Retained inputs versus disposable output

`claudeMemory/tests/generic-brush-v0/` retains the legacy `.blend`, geometry `.npy`
files and frozen JSON inputs used by compatibility tests and catalogue generation.
Old-reader compatibility `.blend` inputs are also retained. These are inputs,
not fresh test results. Do not regenerate them with the new implementation to
make parity pass. The richer nonzero-edge fixtures document the old spill;
the corrected boundary is tested with independent expectations in the native
prepared-falloff cases and the Blender runtime suite's constant-edge Draw cases.

The reviewed inventory and coverage JSON in `design/` are machine catalogues.
Their formatting/hashes are preserved for reproducible frozen-data generation.
Do not load the full catalogues as conversational context; query relevant rows.

All other logs, result JSON, screenshots, temporary assets, copied bindings,
rendered API documentation and scratch builds under `claudeMemory/tests/` are
ignored. Ordinary documentation should link to source and reproducible commands,
not yesterday's generated result file. Record a brief result, relevant version
identity and a durable finding only when useful. CI may retain failure artifacts
with expiry; they do not belong in source control.

## Historical material

See [history and recovery](generic-brush-history.md). Removed plans/results and
one-time source patchers remain in commit `dbbd225`. Do not run those patchers
against today's source. Copied native implementation templates were retired;
the fork and engine own their actual implementation and API documentation.

This cleanup does not certify the unfinished UI/migration, and historical test
counts are not a substitute for the remaining acceptance gates.
