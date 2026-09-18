# Generic brush Plan 1 completion evidence

2026-09-15. Contract: [v1](../design/generic-brush-contract-v1.md).
Owned scalar format: [v1](../design/owned-curve-storage-v1.md).
Inventory: [882 annotated RNA rows](../design/generic-brush-inventory-v1.json),
19 operator arguments, plus explicit dynamic graph/image and layer exclusions.
Each RNA row carries owner, type/default/range/unit snapshot, source references,
classification, migration disposition, kernel/pressure/unified metadata and
stable adapter IDs where supported. Unsupported native data remains preserved.

## Frozen inputs and independent expectations

[Fixture directory](../tests/generic-brush-v0) contains the pre-migration .blend,
external brush library, ten saved position arrays, generated manifest/default
snapshot, runtime identities and logs. `baseline.json` is immutable after capture;
the harness refuses replacement. `fixture-geometry.json` records execution path
and hashes for eight representative saved-fixture cases. Native scalar/curve
expectations are authored literals in the harness, independent of the mapping
implementation. Geometry is an explicitly recorded old-runtime oracle; future
tests compare new results against these arrays rather than regenerating them.

* Local/scene strength .25/.75, pixel diameter 80/160; effective radius 80 px.
* Local/scene cavity factor 1.75/.625, blur 3/1, endpoint .375/.875.
* Native and shadow pressure flags deliberately differ; native strength/size
  response endpoints .625/.875; custom distance-falloff endpoint .125.
* Generated `mu` is explicitly non-default; `nu` and `projection` explicitly
  default; `nudgeProjection` and `planeSide` unset. planeSide resolves to 1,
  despite the DSL default 0. Frozen manifest fan-out is CLAY/FILL/SCRAPE for
  planeSide, BSMOOTH for projection, KELVINLET for mu/nu, NUDGE for named slot.
  Slots are diagnostic only. RNA union declarations, including hard/soft
  ranges, are frozen separately in registered-rna.json. Sorted declaration
  winning provenance is CLAY:planeSide, BSMOOTH:projection, KELVINLET:mu/nu,
  NUDGE:nudgeProjection; none of these snapshots depends on a future DLL.
* Three explicit dabs at x=-.2,0,.2, radius=.35, pressure absent or constant .5.
  Saved-fixture geometry uses a convex quadratic surface; default DRAW uses
  a flat grid. DRAW/CLAY/FILL/NUDGE exercise saved unified strength, custom
  falloff/pressure, cavity and shared/named generated handoff. Each capture is
  run twice and required to be bit-identical before saving the oracle.
* Corrected variable-pressure interpolation and SCENE-size behavior use the
  independent examples in the contract; old sampling/world-size bugs are not
  baseline expectations for the corrected path.

## Commands actually run

Executable: C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe.
All background scripts used `--background --factory-startup --python-exit-code 1`.
Paths below are relative to this repository; append `-- PHASE
claudeMemory/tests/generic-brush-v0` for phased harnesses.

| Harness / phase | Result / retained evidence |
| --- | --- |
| claudeMemory/scripts/generic_brush_baseline.py capture, verify | PASS; fresh .blend and external asset readback, all native/scene/generated assertions; verify.log |
| same, inventory | PASS; inventory.log, inventory.json, registered-rna.json, runtime.json |
| same, geometry-capture, geometry-verify | PASS; eight fixture cases reproducible and fresh-process bit-exact; geometry-*.log |
| claudeMemory/scripts/generic_brush_inventory.py (bundled Python) | PASS; 882 rows, 19 operator arguments; owner/disposition uniqueness assertions |
| claudeMemory/scripts/generic_brush_asset_baseline.py capture, verify | PASS; saved .375, unsaved .75, Revert .375; fresh-process .375, independent Brush.copy; asset-*.log/json |
| claudeMemory/scripts/test_batch_parity.py | PASS; mesh bit-exact; grids max difference 1.1920928955078125e-7 <= 1e-6; batch-parity.log |
| claudeMemory/scripts/test_stroke_cancel.py (headed) | PASS; actual modal strokes, ESC retains sculpted delta, next stroke succeeds, window-close cancellation; headed-cancel.log/stderr.log |

Headed flags: `--factory-startup --enable-event-simulate --no-window-focus
-p 0 0 1280 800 --python-exit-code 1 --python SCRIPT`. Host starts a test-owned
process, waits at most 60 seconds and terminates only that PID on timeout.
Explicit success marker found; no Python traceback in either headed log.
No layout changed in Plan 1, so this headed gate scores geometry/lifecycle,
not a screenshot comparison. Plan 7 still requires visual evidence.

Runtime identities: addon eac6d456632c9dce3881baffa3bc6b0188399568;
engine 536fafa949594839b567f51d495cc58e5328b88c;
fork 4f49f4a04f3ae0f859489e86e2e6380777f96649.
Blender reports 5.3.0 Alpha / Unknown build hash; runtime.json records the
actual DLL SHA256 and paths. Staged mapping/engine_props/stroke SHA256 matches
the source snapshot in baseline.json. Existing unrelated dirty files were not
used as justification to change or revert them.

## Review and scope

Three fresh-context adversarial agents reviewed fork lifecycle/buildability,
engine execution, and migration/ownership. Their surviving findings were folded
into the contract before downstream implementation: RNA discriminator and
non-destructive verification; unset transactions; wrapper/widget lifetimes;
explicit raw sync; native cavity owner notifications; coupled size cancel;
legacy alias read/unset/animation; native pressure authority; input-presence
mask; command-specific cavity caches/hooks; arc-fraction/current-event sampling.
A migration recheck caught and corrected incomplete fixture geometry/assertions,
texture support overclaims, PINCH local-strength behavior and shared size IDs.

Plan 1 is a contract/fixture gate, not proof of the future owned-curve API,
typed dynamics, alias migration or UI. Those remain their respective gates.
The preservation choice for deprecated scene-wide unified flags is the
documented conservative rollout assumption pending user preference; no native
per-brush flags are rewritten. Optional asset-index cache writes were denied
by the environment; actual workspace asset writes/readbacks passed.

Initial lifecycle attempts exposed background asset-list invalidation after
Save As/Save. The final harness explicitly reactivates the scratch asset to
use the fork's background blocking fetch before dependent Save/Revert operators.
Initial geometry used a concave surface outside CLAY's positive plane-side
support; the final convex fixture requires actual displacement for every case.
