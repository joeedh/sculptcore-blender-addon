# Generic brush properties: implementation and migration tasks

Status: Plans 1–5 complete, 2026-09-17. Plan 4 also closes the reopened Plan 2
Brush authoring undo gate. See the [Plan 4 completion evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
Plans 6–8 remain; Plan 6 is in progress. The generic stroke/UI path is not enabled by default.
User direction, 2026-09-18: ignore CLAUDE.md's adversarial review requirement for
the remainder of this task list. Continue implementation and acceptance testing
without further external review dispatches. Existing review findings remain useful.
Plan 3's public typed execution, input acquisition/sampling, modal delivery,
legacy preflight and packaged runtime gates pass. See the
[final evidence](../codebase/generic-brush-plan3-evidence.md#completion-gate--2026-09-17)
and [input API](../codebase/brush-input-delivery.md). Plan 4 begins with its
[reviewed implementation sequence](generic-brush-plan4-foundation.md).
Native launch audit (2026-09-16): corrected the standalone Blender GTest DLL
environment and suppressed loader dialogs; reran 14 runtime + 6 codec tests and
directly audited all eight engine suites successfully. See the
[launcher correction gate](blender-native-test-launcher.md).
Created: 2026-09-15.

This document divides the work into eight implementation plans. Each plan has
its own tasks, dependencies, and completion gate. Check a plan off only when
its gate passes; documentation and interfaces alone do not constitute completion.

Requirements: [genericBrushProps.md](../../genericBrushProps.md).
Storage evidence: [CurveMapping asset investigation](../research/curve-mapping-brush-assets.md).

## Accepted decisions

* Implement a generic, owner-aware CurveMapping property in the Blender fork's
  Python add-on API. Custom editable curves are owned data of the Brush/Scene,
  including when nested in PropertyGroups and collections. Hidden node trees
  are not the persistent backing store.
* Property definitions, saved values/overrides, and resolved execution settings
  are separate concepts. Native adapters read/write native settings directly.
* Value inheritance has Unified, Always inherit, and Never inherit modes.
  Rows edit the effective owner and retain dormant local values.
* Device stacks inherit independently of values, as whole ordered stacks.
  There is at most one entry per device type; disabled entries retain settings.
* The engine must support float, integer, and boolean property dynamics.
* Generated response presets avoid allocating custom mappings. Cache immutable
  samples; track engine uploads independently of curve storage.
* A property has multiple UI positions. UI placement does not inherit alongside
  values. Resolve all property inheritance before crossing into the engine.
* Scene-inherited curves stay scene-owned. Saving a brush must preserve its
  local defaults without capturing the current scene's effective settings.
* Remove the duplicate, limited automasking panel. Update the surviving full
  automasking UI to SculptCore's actual settings and semantics, which differ
  from Blender's. Native UI reuse must not imply unsupported engine behavior.

## Task list and dependencies

| Complete | Plan | Primary repository | Depends on | Result |
| --- | --- | --- | --- | --- |
| [x] | [1. Contracts and migration inventory](#plan-1-contracts-and-migration-inventory) | Add-on, with fork/engine inspection | None | Explicit semantics, inventory, baseline fixtures |
| [x] | [2. Owner-aware CurveMapping API](#plan-2-owner-aware-curvemapping-api) | Blender fork | 1 | API/storage and explicit Brush authoring undo gates pass |
| [x] | [3. Typed device dynamics and input delivery](#plan-3-typed-device-dynamics-and-input-delivery) | Engine + add-on; conditional fork timestamp API | 1 | Float/int/bool stacks and supported device samples end to end |
| [x] | [4. Generic collections, resolution, native adapters](#plan-4-generic-collections-resolution-native-adapters) | Add-on + scoped fork authoring API | 1; 2 for real custom-curve storage | Persistent effective-owner authoring, native authority and undo gates pass |
| [x] | [5. Curve presets and caching](#plan-5-curve-presets-and-caching) | Add-on + bounded engine upload API | 2, 3, 4 | Correct custom/preset curves without repeat sampling/uploads |
| [ ] | [6. Stroke and command integration](#plan-6-stroke-and-command-integration) | Add-on + engine | 3, 4, 5 | Every supported execution path consumes resolved settings |
| [ ] | [7. Generic UI and placement](#plan-7-generic-ui-and-placement) | Add-on | 4, 5; 6 for end-to-end gate | Effective-owner editing across existing UI locations |
| [ ] | [8. Migration, compatibility, release](#plan-8-migration-compatibility-release) | All three + packaging | 2–7 | Existing files/assets work; new system becomes the default |

Plans 2 and 3 can proceed independently after Plan 1. Plan 4's non-curve model
can proceed against the agreed API contract while Plan 2 is implemented, but
cannot pass its gate on a mock. Plan 7 layout work can overlap Plan 6; final
verification must use real strokes. Migration fixtures begin in Plan 1, not at
the end of Plan 8.

Paths below are relative to the repository named in each section. Proposed API
and new module names are design targets, not existing capabilities.

## Existing Blender test infrastructure

Use both background and headed automated tests. Headed gates in this document
are work for the implementing agent using the existing infrastructure, not
automatically a request for the user to perform manual testing. Capture visual
evidence where layout/drawing matters and report any remaining manual-only gaps.

| Coverage | Existing entry points | Use in these plans |
| --- | --- | --- |
| Background add-on and package checks | `tools/verify_addon.py`, `tools/smoke_test_package.py`, `tools/verify_sculpt_layers.py`, other `tools/verify_*.py` | Registration, bindings, state assertions, migration, fresh-process files/assets |
| Live Blender Python inspection | [debug server guide](../codebase/blender-debug-server.md), `tools/blender_debug.py` | Opt-in main-thread API access, state assertions and UI context overrides; tested with background pumping and headed timers |
| Owned-curve asset regression seed | [probe_curve_asset_storage.py](../scripts/probe_curve_asset_storage.py) | Adapt the saved-versus-edited curve and Revert scenarios to the new property |
| Headed stroke and viewport benchmark | [bench_multires_sc.py](../scripts/bench_multires_sc.py), [run_stroke_bench.mjs](../scripts/run_stroke_bench.mjs), [run_tuning_headed.mjs](../scripts/run_tuning_headed.mjs) | Real modal event handling, backlog/INBETWEEN events, draw cadence and performance |
| Headed cancellation regression | [test_stroke_cancel.py](../scripts/test_stroke_cancel.py) | Existing timer/event-loop setup and modal ESC/window-close coverage |
| Fork UI simulation framework | `tests/python/ui_simulate/run.py`, `run_blender_setup.py`, `modules/easy_keys.py`, `modules/ui_test_utils.py` | Extend button input, undo, sculpt, drag and multi-window tests for curves, inheritance, shortcuts and panels |
| Fork operator event replay | `tests/utils/bl_run_operators_event_simulate.py` | Repeatable modal/operator interactions |
| Fork screenshot tests | `tests/python/ui_screenshot_tests.py` | Panel/popover layouts and visual regressions; its comparison runner requires `oiiotool` |

Verified local build location:
`C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe`.
Prefer the matching staged test build when the fork/engine API changes.

Background invocation pattern:

```text
blender.exe --background --factory-startup --python-exit-code 1 --python TEST_SCRIPT
```

Headed invocation pattern (used by the existing add-on scripts):

```text
blender.exe --factory-startup --enable-event-simulate --no-window-focus -p 0 0 1280 800 --python-exit-code 1 --python TEST_SCRIPT
```

* Headed runs omit `--background`; wait for viewport draw and asynchronous brush
  activation before injecting events. Reuse the timer/state-machine patterns
  rather than executing an entire UI scenario before the event loop can run.
* Score assertions and explicit completion markers, enforce a timeout, retain
  logs and screenshots, and check for tracebacks. In particular, the existing
  cancel harness notes that teardown exceptions need not change process exit
  status. Review each harness's expected cancel semantics before reusing it.
* Synthetic events exercise Blender's event loop, not OS/hardware acquisition.
  They must carry the planned pressure/tilt/timestamps to verify those inputs;
  replaying mouse movement alone is not a device-dynamics test.
* Use isolated fixtures and scratch asset libraries without saving user
  preferences. Launch test-owned instances and close only those instances.
* The fork's `tests/utils/blender_headless.py` is a graphical-session wrapper
  currently using Wayland/Weston. It is distinct from `--background` and is not
  the Windows headed runner.

## Plan 1: Contracts and migration inventory

**Goal:** remove ambiguities that otherwise create incompatible native, engine,
storage, and UI implementations. Produce a versioned contract and fixtures.

### Tasks

- [x] Inventory every native/add-on property read by mapping, strokes, cursors,
  textures, operators, and UI. Classify as generic brush setting, scene-only
  setting, transient state, or operator argument; explicitly retain exclusions
  such as transient layer mirrors. Record defaults, units, type, native owner,
  unified flag, pressure behavior, kernel applicability, and existing RNA paths.
- [x] Inventory conditional/grouped native precedence as well as individual
  fields. Cavity currently chooses an entire brush or Paint settings block from
  its enable flags. Decide whether to retain a specialized block adapter or
  introduce independent inheritance, and write an explicit migration truth
  table using different local/scene factors, blur settings, and custom curves.
- [x] Make an automasking compatibility table covering Blender controls,
  SculptCore engine settings, current bridge coverage, defaults, units, and
  semantic differences. Include cavity and custom cavity curves, view-normal
  limit/falloff, backface culling, and per-dab view direction. Classify other
  native controls as equivalent, translated, or unsupported; similar labels
  alone are not evidence that the behavior matches.
- [x] Define stable property IDs independently of labels, array positions,
  manifest indices, and per-build named-float slots. Separate intentionally
  shared properties from unrelated same-name kernel uniforms.
- [x] Freeze a versioned legacy RNA-name/default table independent of the new
  engine DLL. Legacy generated defaults come from live Brush fields, not always
  DSL defaults (`planeSide` is a known example), and one legacy property name
  can serve multiple kernels. Define fan-out/disambiguation when new stable IDs
  split such a name; distinguish unset from explicitly set-to-default values.
- [x] Specify independent stack inheritance (simple local/inherited flag or
  three modes), default modes, missing-parent behavior, missing local value
  behavior, and future-cycle rejection. Preserve current native unified-value
  and brush-local pressure behavior as the migration baseline.
- [x] Specify the row write target, stack-control write target, dormant-value
  preservation, and toggling behavior with concrete brush/scene examples.
- [x] Fix typed dynamics semantics: arithmetic precision, integer rounding and
  overflow, bool threshold and mixing interpretation, when conversion/clamping
  occurs, non-finite inputs, disabled layers, and empty-stack identity. Define
  supported numeric types explicitly; do not treat integer enums as freely
  interpolatable values without an explicit policy.
- [x] Define device domains and missing-input behavior: pressure, each tilt
  axis, stroke speed, and any further advertised inputs. Define speed units,
  normalization, timestamps, first-dab behavior, resampling, and reset on a new
  stroke. Unsupported inputs remain unavailable, never silently zero-driven.
- [x] Resolve the event-time source for speed: the current Blender wmEvent/RNA
  Event path does not expose acquisition timestamps. Accurate event-time speed
  needs a generic fork timestamp extension; handler-time speed must instead be
  named/documented as such and tested under queued events/render stalls. This
  additional fork scope is a decision to settle in Plan 1, not an implicit part
  of the already selected CurveMapping API work.
- [x] Define curve directions/domains and preset formulas, especially two-step
  discontinuities, sphere response, out-of-range input, and editable preset
  conversion. Specify whether switching back to a preset preserves a dormant
  custom curve; default to preserving user edits.
  The engine's current uniformly sampled, linearly interpolated tables cannot
  represent an exact step. Choose analytic/step-aware evaluation or an explicitly
  bounded approximation; sample equality alone cannot establish step correctness.
- [x] Select the owned-curve persistence representation and API contract for
  Plan 2, including how data survives add-on unregistration and which Blender
  versions can safely read it. Decide save/versioning compatibility before
  writing a new DNA/IDProperty payload format.
  Existing readers replace unknown IDProperty types with integer zero; a
  Python capability check is too late, and the fork shares version numbers
  with stock Blender. Choose existing-type serialized definitions that old
  readers preserve or prove an enforceable file compatibility boundary.
- [x] Define unset reads and first customization: null plus explicit initialization
  or a nonpersistent default view with copy-on-first-write. Specify supported
  mutation surfaces (widget, RNA, underlying storage) and behavior while the
  declaring add-on is unregistered; do not assume all edits invoke callbacks.
- [x] Define command inheritance: ordered commands do not automatically inherit
  from the preceding command. Choose explicit parent links/overrides, resolve
  them on the host, and define independent per-command stack behavior. Keep a
  full command-authoring UI out of this migration; preserve existing programs.
- [x] Capture representative pre-migration .blend files and external brush
  assets in isolated test libraries: native unified settings, shadow pressure
  toggles, generated engine fields, custom curves, and non-default scene tuning.
  Record effective values and representative deterministic stroke outputs.
  Separate unchanged input/evaluation baselines from intended sampler fixes:
  constant-pressure strokes should retain behavior, while varying-pressure
  interpolation needs explicit corrected-input expectations because the old
  sampler applies a later event's pressure to a whole delayed segment.

**Gate:** the contracts answer the above cases without implementation-dependent
guesswork; each inventory row has an owner and migration disposition, and fixtures
have independent expected results. Defaults proposed during implementation are
recorded as decisions, not silently treated as user requirements.

**Touchpoints:** add-on `props.py`, `engine_props.py`, `mapping.py`, `stroke.py`,
`tools.py`, `cursor.py`, `texture.py`, `vanilla_panels.py`, `ui.py`, `menus.py`;
engine `source/props/`, `source/brush/brush_program.h` and uniform manifests.

## Plan 2: Owner-aware CurveMapping API

**Goal:** an add-on can declare an owned curve on a Brush, Scene, or nested
PropertyGroup and use Blender's existing curve editor/evaluator. Tentative
declaration: `bpy.props.CurveMappingProperty(...)`; finalize the spelling and
arguments in Plan 1. Exposing a constructor or a raw pointer is insufficient.

### Tasks

- [x] Implement owned storage, allocation/initialization, deep copy, freeing,
  property removal, and .blend read/write using the representation selected in
  Plan 1. Store definitions, not owner pointers, evaluated tables, or Python
  callback addresses. Support lazy allocation for unused custom curves.
  - [x] Native scalar definition codec, independent materialization and
    non-destructive validation; six focused C++ tests passed.
  - [x] Native runtime core: immutable retained snapshots, expected-revision
    commits, explicit raw sync, read-only rejection, detach/copy/delete/swap
    invalidation and collection relocation. Eight runtime C++ cases passed;
    rebuilt Blender background/headed regressions passed. See
    [core plan](owned-curve-runtime-core.md) and
    [evidence](../codebase/generic-brush-plan2-evidence.md).
  - [x] Existing-type payload preservation through stock 5.0.1 and prior-fork
    readers for custom and system-property roots, normal files and brush assets.
    Actual new-RNA readback/evaluation also passed for both old-reader fixtures.
  - [x] Editor path-watch core: group/array/owner lifetime and relocation guards;
    11 native runtime cases and six codec cases passed. Existing curve records
    remain valid across collection movement.
- [x] Integrate Python property declaration/registration and RNA lookup with
  the standard property machinery. Resolve the owner ID through nested groups
  and collection items; preserve identity under collection reorder and make
  stale wrappers fail safely after item deletion, owner deletion, undo, or load.
  Include point-array reallocation on insert/remove/reset and inline parent
  IDProperty relocation on collection growth/movement. Runtime identities must
  protect curve/point wrappers and the declaring-property callback target.
  - [x] Reviewed [RNA layer](owned-curve-rna-layer.md): declaration,
    transactional fields/functions, guarded retained wrappers, staged root-path
    initialization, raw sync and callback ownership. Actual fork build, 25-case
    lifecycle suite, fresh-process readback and headed explicit undo/redo passed.
    Interactive lifecycle checks passed; see the final completion evidence.
- [x] Expose compatible CurveMapping/CurveMap/point access, initialize/update,
  evaluation, reset/copy operations, and `template_curve_mapping` editing.
  Define read access without allocating or dirtying data during panel drawing.
  The existing template calls allocating pointer accessors; implement an explicit
  unset/first-edit path rather than assuming widget reuse provides laziness.
- [x] Route nested point edits, insertion/removal, handle changes, clipping,
  extension, presets, resets, and script edits to the actual owner's update
  path. Brush asset changes must set its unsaved flag; Scene changes must
  participate in normal file updates. Do not dirty an unrelated active brush.
  - [x] Correct existing native curve/automasking owner notifications; 16
    regression checks and fresh-process native asset readback passed.
  - [x] Owned-property script callbacks and external assets: actual-owner dirty
    state, exactly-once callback, .375/.75/.375 Save/Revert and fresh read passed.
    Dialog-driven actual-owner notifications and asset Revert also passed.
- [x] Integrate undo/redo for interactive curve editing and operators; scripting
  follows Blender's normal explicit undo conventions. Handle callbacks without
  recursion, update storms, or keeping dead Python classes alive.
  - [x] Generic Scene owned-curve RNA/editor undo and wrapper invalidation pass.
  - [x] **Coverage correction closed, 2026-09-17:** Brush IDs opt out of memfile undo.
    Existing Scene tests did not establish Brush authoring undo. This part of
    Plan 2's historical completion was reopened. The explicit native authoring
    boundary now passes actual Brush widget Create/Edit undo/redo, generic
    collection restoration and custom sculpt undo interleave. Asset Revert stays
    independently verified. See the
    [completion evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
- [x] Separate essential owner notifications from optional declaring-property
  Python callbacks. Define raw-storage mutation synchronization or disallow it
  explicitly; cache revisions cannot assume raw IDProperty edits notify RNA.
  Data must survive unregister without retaining a dead callback, and two
  curves on one owner must invoke their respective declaring callbacks.
- [x] Add a runtime revision or equivalent reliable invalidation hook if it
  can cover all supported mutations. Document evaluation-affecting versus
  presentation-only edits; generation numbers are not persisted cache identity.
  Exact immutable `(record_identity, revision)` keys passed 13 real-Blender
  cases plus headed undo/redo. See the [API slice](owned-curve-api-finalization.md)
  and [evidence](../codebase/generic-brush-plan2-evidence.md).
- [x] Verify regular .blend persistence and fresh-process external asset Save,
  Save As, load, and Revert with the add-on enabled and with declarations absent.
  New ownership must fix the node-tree revert reproducer, not recreate it as a
  separate-ID curve container.
- [x] Verify Brush.copy(), Scene.copy(), nested collection copying, asset local
  Save As, external Save As, linked/editable/read-only data, supported library
  overrides, registration reload, and owner deletion. Independent copies cannot
  share mutable curves; scene inheritance must not duplicate curve storage.
- [x] Publish the Python API documentation and capability/version signal.
  Define unsupported-old-build behavior so loading files cannot corrupt data.
  Verify unsupported stock and prior fork readers opening/resaving fixture
  files and external assets, then reopen them with the new fork. Prove either
  preserved definitions or the chosen safe refusal before data is rewritten;
  disabling the add-on on the new fork is not this compatibility test.

**Gate:** focused native/Python lifecycle tests plus an interactive editor/undo
check pass. A saved endpoint of 0.375, edited to 0.75, must return to 0.375 after
asset Revert, with correct dirty state and fresh-process readback. No hidden tree
or self-assignment of unrelated native brush properties is required.
Retain several curve/point wrappers across ordinary point insertion/removal/reset
and parent collection growth/reorder/removal: access must stay attached to the
same logical object or raise safely, never edit a replacement. Exercise an open
curve popup while its item moves/disappears. Repeated drawing of unset nested
curves leaves serialized property presence and dirty state unchanged; first
customization creates storage once and undo restores the unset state. Verify
widget/RNA/raw-storage notifications according to the declared mutation policy.

**Touchpoints (fork):** `source/blender/python/intern/bpy_props.cc`, RNA property
definitions/access and `rna_color.cc`, IDProperty storage/copy/read/write,
`BKE_colortools` implementation, curve UI templates, owner update paths,
`tests/python/` and relevant BKE tests. Existing `brush.cc` curve lifecycle code
is a reference, not a reason to hardcode SculptCore properties into Brush DNA.

Historical completion: 2026-09-16. [Final gate evidence](../codebase/generic-brush-plan2-evidence.md#completion-gate--2026-09-16) records the installed binary, native tests, actual headed interactions, assets and regression matrix. The Brush authoring undo correction was reopened and then completed on 2026-09-17 with Plan 4; other verified results remain valid.

## Plan 3: Typed device dynamics and input delivery

**Goal:** a property stack behaves the same through bindings and every supported
executor. This is more than adding bool/int casts to the float evaluator.

### Tasks

- [x] Implement Plan 1's float/int/bool evaluation contract in engine property
  lookup, coercion, and dynamics configuration. Preserve authored base values
  separately from evaluated per-dab values.
  - [x] [Typed core](generic-brush-typed-core.md): implementation includes checked
    source-type evaluation, safe destination conversion, sample freshness,
    duplicate policies and complete property copying. Native build, new typed
    tests and three existing suites passed; [evidence](../codebase/generic-brush-plan3-evidence.md).
  - [x] Checked scalar access: exact-type finite transport, local-only writes,
    explicit evaluation failure and rejection of unresolved inherited owners.
    Native and actual Python binding gates passed; public execution adoption passes the final gate.
- [x] Enforce one entry per device type at authoring/configuration boundaries;
  define explicit replacement/update behavior and reject ambiguous serialized
  duplicates. Preserve stack order, mixing factors, curves, and disabled state.
  Checked bulk/configure/enable/move/clear methods enforce this in the engine;
  16 native suites and actual Python stack tests passed.
- [x] Extend uniform type/capability metadata, DSL/code generation, generated
  registration/load code, and validation beyond `isFloat`. Keep static uniforms
  ineligible and reject unsupported bindings before geometry mutation.
  - [x] Native member type/semantic descriptors and compiler validation: wrong
    scalar/array types, enum/ID dynamics, conflicting annotations and reserved
    execution names reject. Eight foundation/regression suites passed; see
    [Plan 3 evidence](../codebase/generic-brush-plan3-evidence.md).
- [x] Bounded scalar declaration and generated registration gates: exact type,
  default presence and double metadata, atomic declaration batches, typed native
  loads and registration-only mesh/grid program preflight. Thirteen native
  suites and five addon failure-boundary tests passed; see
  [generated registration](generic-brush-generated-registration.md).
- [x] Cover both built-in brush fields and extra-kernel stored uniforms with
  typed read/write/configuration APIs. Do not convert bool/int storage into
  float named slots and assume type semantics survive.
  - [x] [Typed named stores](generic-brush-named-storage.md): separate float/int/bool
    working values and initialized presence; checked authored/cache writes,
    immutable registry descriptors, generated evaluated/host writes. Fourteen
    native suites and the legacy float/manifest Python smoke passed.
  - [x] [Typed extra emission](generic-brush-typed-extras.md): per-type slots,
    exact defaults, typed loaders/host writes, bool GPU packing and shared field
    validation. Fifteen native suites passed with actual mesh/grid fixture
    execution; shader validation and addon-only restoration also passed.
  - [x] Complete checked configuration: float/int/bool authored operations,
    atomic stacks and staged curve uploads, canonical query mappings and owned
    snapshots. Native/Python gates and addon-only restoration passed; see
    [checked configuration](generic-brush-checked-configuration.md).
  - [x] Static storage coherence: checked scalar reads/writes reach authoritative
    native members or typed extra slots; common properties retain authored
    storage. Exact integers, absent/default preservation, invalid writes, actual
    mesh/grid static-bool geometry, Python transport and addon-only restoration
    pass; see [static adapter evidence](generic-brush-prepared-execution.md#static-storage-adapter-evidence).
  - [x] Declaration preflight without publication: validation preserves property
    and metadata presence, inherited state, owner pointers and stacks. Publication
    revalidates later raw edits. Addon-only native/Python gates pass; see
    [preflight evidence](generic-brush-prepared-execution.md#declaration-preflight-evidence).
  - [x] Prepared scalar candidates: float/int/bool evaluation, authoritative static
    sources, staged defaults/declarations, canonical property identity and readonly
    output views. Success/failure preserve live state; fixture and restored
    addon-only native/Python gates pass;
    see [candidate evidence](generic-brush-prepared-execution.md#prepared-scalar-candidate-evidence).
  - [x] Bounded prepared mesh execution: private declaration/default publication,
    typed working-only apply, generated shared-write capability guard, evaluated
    radius filtering, repaired/nonfirst/empty-dab validation and spatial refresh.
    Actual typed fixture geometry, expanded-region undo/redo and both neighbor
    modes pass. Fixture and restored addon-only 17-suite/native Python gates pass;
    see [mesh evidence](generic-brush-prepared-execution.md#bounded-mesh-execution-evidence).
    Initially internal; public entry points and addon adoption pass the final gate.
  - [x] Bounded prepared grid execution: evaluated-radius selection, atomic scalar
    publication, domain-generation/log-transaction guards, and occurrence-leaf
    bounds refresh through execution and undo/redo. Typed fixture geometry,
    expanded-region movement, exact store/position undo, deferred normals and
    repaired/nonfirst/empty failures pass. Fresh plan reviews and implementation
    audits are folded in; fixture and restored addon-only 17-suite native/Python
    gates pass. See [grid evidence](generic-brush-prepared-execution.md#bounded-grid-execution-evidence).
    Initially internal; public execution/input delivery passes the final gate.
  - [x] Bounded prepared mesh/grid programs: typed overrides before dynamics,
    full-program preflight, maximum evaluated-radius selection and exact sparse
    working-state restoration. Expanded-region raw-reference parity, exact undo,
    mixed manifests, late rejection and zero-stage capture indices pass. Fixture
    native 17/17 and Python 11/11 plus restored addon-only native 17/17/Python
    smoke passed. Public execution/input adoption passes the final gate. See
    [program evidence](generic-brush-prepared-programs.md#bounded-program-execution-evidence).
- [x] Provide callable Python binding paths for typed values and stacks; prefer
  stable identifiers mapped to runtime indices, with additive compatibility
  where possible. Update binding descriptors, exports, ABI checks and generated
  declarations through existing tooling. Consider batched sample upload here.
  CommonProperties/UniformProperties validate Python inputs; bulk arrays, exact
  double transport and stale tokens are tested against the explicit native DLL.
  Python/TS declarations are regenerated; TS type checking passes. TS runtime
  transport is not claimed. Public per-dab adoption and the broader built-in/extra
  integration task pass the final completion gate.
- [x] Carry pressure and tilt through event acquisition, interpolation, dab
  records, Python fallback and C++ batch paths. The current interactive operator
  uses its local `StrokeSpacer`, not `stroke_driver.py`, and currently passes
  the event pressure to all emitted dabs. Wire the actual modal/INBETWEEN input
  path and preserve each dab's samples within a batch. Existing `poll_dabs`
  returns screen/pressure/invert only; its accepted tilt arguments do not prove
  delivery or adoption by the interactive operator.
- [x] Implement stroke-speed input with the agreed timestamp/normalization
  contract; handle pauses, first/last samples, replay, and stroke reset. Advertise
  twist/angle/curvature only once their acquisition/computation is implemented.
  If Plan 1 selects acquisition-time speed, carry GHOST event timestamps through
  wmEvent, queue/coalescing/INBETWEEN handling, and RNA before implementing the
  add-on sampler. Specify units, monotonicity, and synthetic/replay timestamps.
  Do not infer acquisition time from Python callback arrival time.
- [x] Keep per-dab samples fresh when inputs are absent or disabled; no stale
  device values from a previous stroke. Define symmetry behavior for directional
  inputs and ensure identical samples in mesh and multires execution.

**Gate:** typed boundary tests, duplicate-device tests, actual Python-binding
configuration tests, and deterministic sample/replay comparisons pass. Test
float/int/bool brush-level values/stacks on an actual kernel via mesh, grid,
existing program, and relevant batch execution. Independent per-command state
is Plan 6's gate, not a prerequisite here. Include a real modal-event harness
with changing pressure/tilt within a multi-dab event batch; testing a dormant
stroke-driver helper alone cannot pass. Legacy float pressure behavior stays
unchanged for identical explicit dab inputs and constant-pressure end-to-end
fixtures. Use independent corrected-input expectations for varying-pressure
interpolation and release flushing, not wider parity tolerances. Run the
engine's relevant codegen/backend checks for generated-code changes.
Speed tests must compare equivalent motion delivered with different handler
delays/event batching against the chosen time-source contract.

**Touchpoints:** engine `source/props/prop_types.h`, `prop_struct.h`,
`prop_dynamics.h`, `source/brush/brush.h`, `brush_command.h`, compiler emitters,
mesh/grid executors, stroke driver, C APIs, Python bindings; add-on `stroke.py`
and `stroke_driver.py`.
Conditional fork touchpoints for acquisition timestamps: GHOST event delivery,
`WM_types.hh`, window-manager event queuing, and `rna_wm.cc`.

Completion: 2026-09-17. The final gate supersedes the historical bounded-slice limitations above. Independent command state and full generic collection adoption remain Plan 6.

## Plan 4: Generic collections, resolution, native adapters

**Goal:** a versioned, persistent authoring model with one deterministic resolver
and explicit owner-aware setters. Registration must not depend on a live DLL.

### Tasks

- [x] Implement the definition registry and typed storage for Brush/Scene
  collections, local values, inheritance metadata, device stacks, curves, and
  plural positions. Separate saved authoring data from transient resolved/cache
  state. Define behavior for unknown IDs and unavailable engine kernels.
  - [x] DLL-independent registry and resolver foundation: strict typed immutable
    definitions, plural positions, separate value/stack capabilities and owners,
    effective setters, dormant preservation and explicit repair. Native strength
    reads/writes authoritative RNA through injected transient policies. Two fresh
    plan reviews and implementation audits are folded in. See
    [foundation evidence](../codebase/generic-brush-plan4-evidence.md).
    Curve-bank integration and native pressure subsequently passed the final
    gate; this foundation does not enable the new UI or stroke path.
  - [x] Native owner-safety prerequisite: lifecycle guards retire stores before
    and after undo/redo/load (including failed load), reject invalid write owners,
    and suppress quantized native no-ops. Native strength also enforces native
    bounds when a caller supplies a widened definition. Unified settings notify
    their owning Scene. Two fresh adversarial reviews and implementation audits
    are folded in; actual assets and headed tests pass. See
    [storage review](generic-brush-plan4-storage.md) and
    [evidence](../codebase/generic-brush-plan4-evidence.md#native-owner-safety-prerequisite--2026-09-17).
  - [x] Persistent typed scalar values and inheritance policies, with atomic
    publication of scalar/UI metadata through a bounded native API. Custom
    metadata groups preserve unknown payloads losslessly; the future declared
    curve bank remains separate. Native strength values/unified flags stay
    authoritative. All twelve policy combinations, real assets, fresh-process
    save without authoring modules, and headed Scene undo pass. Two fresh plan
    reviews and implementation audits are folded in. See the
    [atomic plan](generic-brush-atomic-scalars.md) and
    [completion evidence](../codebase/generic-brush-plan4-evidence.md#persistent-atomic-scalar-records--2026-09-17).
  - [x] Persistent unique ordered generated-response device stacks for generic
    float/int/bool definitions. Independent effective-owner edits preserve dormant
    values/stacks; one native atomic batch publishes order and settings. Disabled
    entries and unknown/dormant payloads survive. Two fresh reviews and audits
    are folded in; real assets, Scene undo and fresh-process gates pass. See the
    [stack plan](generic-brush-persistent-stacks.md) and
    [evidence](../codebase/generic-brush-plan4-evidence.md#persistent-generated-device-stacks--2026-09-17).
  - [x] Persistent plural positions with local owner targeting, distinct default/
    explicit-empty/reset states, stable location keys and atomic publication.
    Definition defaults and saved data share location/int32/count validation.
    Two fresh reviews and implementation audits are folded in; actual assets,
    generic Scene undo and fresh-process persistence pass. See the
    [placement plan](generic-brush-persistent-positions.md) and
    [evidence](../codebase/generic-brush-plan4-evidence.md#saved-plural-positions--2026-09-17).
  - [x] Declared custom-curve bank integrated with persistent generic stacks.
    Explicit initialization, shared declaration leases, native declaration tokens,
    stale/owner/revision checks and dormant preservation pass storage, actual asset,
    headed Scene undo and fresh-process gates. See the reviewed
    [completion sequence](generic-brush-plan4-completion.md) and
    [evidence](../codebase/generic-brush-plan4-evidence.md).
  - [x] Production DLL-independent frozen authoring catalogue, nonmutating legacy
    scalar views, manifest diagnostics and default-off saved readiness switch.
    Seven frozen IDs retain five-name legacy fanout and unset/default distinction;
    missing engine, registration failure, independent copy and fresh reload pass.
    See [reviewed registration plan](generic-brush-frozen-authoring.md).
  - [x] Native pressure stacks and Brush/native-Scene authoring undo. Ordinary
    global undo preserves their current native state. The explicit authoring undo
    boundary is implemented under the reviewed [undo plan](generic-brush-authoring-undo.md).
- [x] Preserve definition-specific ranges, tooltips, units and capabilities in
  RNA/UI. Resolve how heterogeneous collection values expose per-property limits
  without a single generic float field silently losing metadata.
- [x] Implement read resolution returning value, value owner, stack, stack
  owner, source/capability information, and cache invalidation inputs. Never
  mutate or copy inherited authoring data merely to read it.
- [x] Implement setters for effective values and stacks, inheritance toggles,
  local restoration, and unique device entries. Match the Plan 1 truth tables
  for all combinations of scene-unified and local inheritance state.
- [x] Implement native adapters for agreed inventory entries: native unified
  size/strength, brush values, shadow pressure toggles, native response curves,
  kernel-specific conversions, and remaining mapped properties. Native fields
  remain authoritative; ordinary access must see script/native UI changes.
- [x] Preserve diameter/radius conversions, scene/world size behavior, percent
  spacing, brush-family policies and direction handling. Separate semantic
  conversion from geometric/per-dab calculations.
- [x] Define how a scene-owned stack uses add-on-owned curves when there is no
  native scene equivalent. Native adapters must not overwrite a dormant brush
  curve to represent a scene override or an unsupported mix mode.
- [x] Separate registration from engine metadata refresh. Store user values
  even if a kernel is missing; reconcile manifests without erasing unknown
  values or reinterpreting persisted IDs using per-build slots.
  Use Plan 1's frozen legacy default/name translation table rather than deriving
  historical values from the currently loaded DLL.
- [x] Add read-only legacy access/import adapters for staged migration and an
  explicit new-path feature switch. Keep baseline behavior available until the
  integration gates pass; avoid two competing authoritative copies.

**Gate:** resolver/setter table tests and Blender integration tests pass for
multiple brushes/scenes, native edits, asset switches, disabled engine, missing
definitions, ownership changes, and undo/reload. Native dormant values and
stacks survive every inheritance toggle and independent brush copy.
Exercise compound cavity precedence with both enable flags and deliberately
different brush/scene values; include absent kernels and unset legacy uniforms.

**Touchpoints:** add-on `props.py`, `engine_props.py`, `mapping.py`, registration,
handlers/session code; introduce focused registry/storage/resolver/adapter
modules rather than expanding one monolithic module.

## Plan 5: Curve presets and caching

**Goal:** custom and generated response curves share an evaluation contract and
avoid redundant allocation, sampling, and boundary crossings.

### Tasks

- [x] Implement constant, two-step, linear, sqrt, square, smoothstep,
  higher-degree smoothstep, sphere, and agreed additional presets as compact
  definitions. Reuse validated formulas from `mapping.py` with explicit input
  direction/domain rather than assuming falloff and pressure are identical.
  Implement the selected step-aware engine representation or approximation
  policy; test real engine evaluation immediately on both sides of the threshold.
- [x] Wire custom curves to Plan 2 owned properties and native curve adapters.
  Allocate mappings only when customization requires them; preserve dormant
  custom data on preset changes according to Plan 1.
- [x] Implement definition fingerprints and generation invalidation. Include
  effective owner changes, all evaluation-affecting curve settings, parameters,
  domain and sampling resolution. Use full-key equality, not hash equality alone.
- [x] Share immutable sampled tables by content; bound cache growth and clear
  dead owner references on load, undo/redo, unregister and owner removal.
  Use native fingerprint checks at synchronization boundaries if native curves
  lack a complete mutation revision.
- [x] Track engine-installed stacks separately per engine brush/session and
  command configuration. A cleared stack or rebuilt engine invalidates upload
  state even when the same sampled table is cached.
- [x] Add batch upload support if profiling shows sample-by-sample marshalling
  remains material; handle buffers and ownership explicitly across bindings.
  No curve sampling, inheritance walk, or cache-content hashing per dab.

**Gate:** preset endpoints/discontinuities and custom curve samples match the
agreed reference; two identical presets reuse samples without custom allocation;
native edits and owner changes invalidate correctly. Instrumented warm strokes
perform no unchanged curve bake/upload, while a rebuilt engine receives all
needed data. Memory remains bounded across repeated asset switching.

**Completion:** 2026-09-17. [Evidence](../codebase/generic-brush-plan5-evidence.md) and [verified manifest](../tests/plan5-completion-gate.json): 11 Blender runs, 17 native suites, 15 exact-DLL check groups and 17 pure tests. Actual warm strokes perform zero unchanged bakes/uploads; analytic typed responses, customization undo/persistence, asset cleanliness and matched package gates pass.

## Plan 6: Stroke and command integration

**Goal:** all existing sculpt paths consume one resolved authoring model without
double-applying pressure, compounding evaluated values, or changing brush feel.

### Tasks

- [ ] Resolve settings at stroke start; define deliberate per-event/per-dab
  exceptions for radius projection, input samples, Ctrl inversion and required
  live settings. Supply a flattened collection with no inheritance flags.
  - [x] Immutable authoring snapshot prerequisite: effective native domains,
    independently owned prepared stacks, paired SIZE validation, source/presence
    and pending capabilities. Four engine-owned static automasking definitions
    register without the DLL. Three background runs pass 98 new and 77 legacy
    checks, plus 24 pure tests. [Verified gate](../tests/plan6-snapshot-gate.json)
    and [reviewed slice](generic-brush-plan6-snapshots.md). Execution translation
    and actual stroke-consumer adoption remain open.
  - [x] Typed semantic evaluator prerequisite: FLOAT32/native-exact arithmetic,
    FLOAT64 integer/boolean stacks, representable range endpoints and explicit
    spacing/snake/strength/SIZE conversion order. Passed 543 actual DLL comparisons,
    six pure tests and six real Blender check groups including 800 warm evaluations.
    [Reviewed slice](generic-brush-execution-domains.md),
    [verified gate](../tests/plan6-domains-gate.json). Consumer adoption remains open.
- [ ] Replace direct legacy reads in every consuming path, including cursors,
  smooth special handling, grab/anchored/snake-hook policies, dyntopo cadence,
  texture setup and relevant filters. Follow the Plan 1 inventory for scope.
- [ ] Wire the automasking compatibility table into execution before exposing
  its controls. Current add-on mapping handles cavity; engine view-normal and
  backface controls need explicit adapters plus valid object-space per-dab
  `viewDir`, including symmetry and mesh/grid/batch paths. Preserve differing
  defaults and angle units rather than blindly forwarding native values.
- [ ] Replace the float-only generated-field handoff and fixed pressure setup
  with typed configuration. Clear old stacks when changing brush/kernel; keep
  authored base values separate from `loadProps` evaluated field values.
- [ ] Preserve separate base and evaluated radius semantics for hit testing,
  node selection, spacing, and cursor display. Pressure must not be applied
  both by host smoothing code and by engine dynamics.
- [ ] Implement the agreed host-side command-property resolution and typed
  per-command values/stacks. Current `BrushProgram` sparse float overrides are
  insufficient for independent command stacks: extend the program/bindings and
  both executors with scoped state restoration, including error/cancel paths.
  - [x] Bounded command integration: immutable stable-ID DAG resolution,
    owner-free prepared curves, checked native per-command stacks and bulk Python
    C APIs, candidate publication, growing multi-leaf mesh/grid regions, exact
    restoration and raw/legacy rejection. Final addon-only 17-suite gate, effective
    fixture 17-suite gate, 24 pure tests, four Blender launches and eight headed
    modal cases pass. See [Plan 6 evidence](../codebase/generic-brush-plan6-evidence.md)
    and [verified manifest](../tests/plan6-command-gate.json). Full generic stroke
    adoption and unsupported command capabilities remain open.
- [ ] Fix command region selection for independent radius values/stacks. Current
  program executors select nodes before applying command overrides. Preflight
  each command's evaluated radius/extent before selection or mutation, choose
  a conservative shared query/pinning/undo region (or correct per-command
  queries), and reuse the evaluated settings during execution. Include
  unbounded/grab policies, dyntopo and mask/undo capture so main-brush spatial
  support cannot truncate later commands.
- [ ] Keep existing main-plus-smooth programs correct. Verify one command's
  stack/typed value cannot leak into another command or the next stroke; use
  explicit resolved parents, not implicit previous-command inheritance.
  - [x] Actual BSMOOTH prepared execution: classified pre-freeze boundary refresh,
    strict read-only attribute binding, mesh live/CSR and grid zero-column parity,
    larger independent radius, marked boundaries, missed/zero first dab, late
    rejection and exact undo/redo. Passed 17 native suites, eight headed autosmooth
    cases with 124 required prepared calls, eight existing modal cases and package
    smoke. [Reviewed slice](generic-brush-prepared-boundary-smooth.md) and
    [verified gate](../tests/plan6-bsmooth-gate.json). Other capability gaps remain.
  - [x] Prepared non-accumulating commands: isolated AccumOrig factory selection,
    live relaxation stages, displacement-derived base preservation, newly reached
    leaves/capture slots, late rejection and second-stroke undo/redo. Passed 17
    native suites, 16 installed headed draw/autosmooth cases with 248 required
    prepared calls, and package smoke. [Reviewed slice](generic-brush-prepared-nonaccum.md)
    and [verified gate](../tests/plan6-nonaccum-gate.json).
  - [x] Prepared MASK and exact finer-level mask undo: strict grid channel
    preflight, correct first accepted mask capture, identity-qualified snapshots,
    preserved absent allocations/debt and indexed capture/seek grouping. Passed
    17 native suites, 12 exact DLL raw-reference comparisons, 42 preflight checks,
    eight installed headed cases with 124 required prepared calls and provenance
    smoke. [Reviewed mask plan](generic-brush-prepared-mask.md),
    [reviewed undo correction](generic-brush-mask-finer-undo.md), and
    [verified gate](../tests/plan6-mask-gate.json). Full Plan 6 remains open.
  - [x] Command-owned automasking: authoritative static bool/int/float settings,
    copied/inherited LUTs, configuration-specific first-contact cavity caches,
    mesh transaction checks and pre-freeze adjacency preparation. Passed 17 native
    suites, eight exact installed DLL comparisons, eight headed cavity cases
    (124 required prepared calls) plus eight controls, and package provenance.
    [Reviewed slice](generic-brush-command-automasking.md) and
    [verified gate](../tests/plan6-automask-gate.json). Generic host adoption,
    geometric viewDir symmetry and other guarded capabilities remain open.
  - [x] Compiler prerequisite for host/reduce commands: no-op range-clamp proof,
    FLOAT32 output initialization and command-level coverage, monotonic unsafe
    audit, generated-name diagnostics and compiled mesh/grid fixture. All 17
    [native suites passed](../tests/plan6-prelude-native-results.json).
  - [x] Nonanchored unbounded execution: independent declared/inherited extents,
    all-leaf selection, stage-specific cavity support and reflected prepared batch
    frames. Kelvinlet has independent numerical oracles and checked rejection of
    unsupported tiny-float transport under host FTZ/DAZ. Passed 17 addon-only and
    17 fixture suites, WGSL/SPIR-V validation, 16 installed batch comparisons in
    background and headed Blender, eight headed modal controls and package smoke.
    [Reviewed slice](generic-brush-prepared-unbounded.md),
    [numerical correction](generic-brush-kelvinlet-numerics.md) and
    [verified gate](../tests/plan6-unbounded-gate.json). Generic consumer adoption,
    anchored/preview, dyntopo, general attributes and command-specific hooks remain.
  - [x] Command-specific ENHANCE: native static INT32 authority, per-command
    configuration snapshots, executor-owned first-contact fields and strict
    attribute admission. Independent geometry/support oracles, radius growth,
    command order, unbounded unions, pressure, sparse IDs, token wrap and exact
    undo pass. All 17 native suites, shader checks, generated bindings, 16 installed
    prepared host cases and four exact raw controls pass in background and headed
    Blender, including materialized multires routing. [Plan](generic-brush-prepared-enhance.md)
    and [verified gate](../tests/plan6-enhance-gate.json). Generic modal adoption
    and the other guarded capabilities remain open; further reviews were waived.
  - [x] Prepared anchored grab: isolated from-base factories, conservative shared
    regions, independent command radii and primary/mirror dab identity. Independent
    GRAB and anchored-Kelvinlet oracles pass, along with all 17 native suites,
    48 installed cases in both background and headed Blender, bindings/typecheck
    and package smoke. [Implementation and region-cost decision](generic-brush-prepared-grab.md)
    and [verified gate](../tests/plan6-grab-gate.json). Preview, dyntopo and generic
    consumer adoption remain open.
  - [x] Prepared preview rollback: evaluated region capture, preview-only cache
    lifetime, checked preflight and lazy multires executor binding. All 20 native
    suites, 64 installed cases in background and headed Blender, eight actual
    Anchored/Drag Dot gestures with cancel/undo/redo, bindings and package smoke pass.
    [Implementation](generic-brush-prepared-preview.md) and
    [verified gate](../tests/plan6-preview-gate.json).
  - [x] Prepared dyntopo: checked pre-remesh validation, post-remesh command
    regions, live topology and per-dab undo sealing. All 26 native suites,
    eight installed cases plus four exact legacy controls in background/headed
    Blender, four real headed gestures, bindings and package smoke pass.
    [Implementation](generic-brush-prepared-dyntopo.md) and
    [verified gate](../tests/plan6-dyntopo-gate.json). General attributes/remaining
    host stages and generic consumer adoption remain open.
  - [x] Prepared mesh/materialized attributes: saved-field compiler certification,
    atomic target validation, per-stage hooks and selected-layer undo. All 34
    native suites, 32 installed host cases in both launch modes and four real
    paint/face-set gestures pass. [Verified gate](../tests/plan6-attributes-gate.json)
    and [undo memory policy](generic-brush-prepared-attributes.md). Cage-only
    smoothing remains a separate host-path deliverable.
  - [x] Checked cage color smoothing: evaluated-radius grid selection, selected
    color target validation and certified direct execution preserve cage neighbors,
    mask and limit-position semantics. All 34 native suites, installed lifecycle
    in both launch modes and two actual Shift-smooth gestures pass, including
    undo/redo and save/reload. [Verified gate](../tests/plan6-cage-gate.json).
  - [x] Prepared falloff and grid-layer policies: conservative regions for
    cube/box/slab, Gaussian and nonzero curve edges; validated pinned layer targets.
    All 34 native suites, 50 installed host cases in both launch modes and four
    actual Layer gestures pass. [Verified gate](../tests/plan6-host-policies-gate.json).
    The expanded regression found a sparse-vertex-ID cavity scratch bug after
    dyntopo collapse; capacity-sized storage passes exact per-dab comparison and
    eight consecutive native runs. Generic consumer adoption remains open.
- [x] Wire the opt-in generic runtime through mesh/grid dabs, batches, anchored
  grab, preview, dyntopo and cage smoothing. Capture effective owners once;
  native semantic evaluation preserves integer rounding before conversion.
  Actual Draw/program/Grab/Snake Hook/Smooth/Mask gestures exercise checked
  paths and exact Blender undo/redo. Full integration gate remains open below.
- [x] Transfer view-normal/backface settings from the effective owner and supply
  object-space view rays, reflected per symmetry image. Twenty installed host
  cases prove enabled/disabled, front/back/edge-facing behavior on mesh/grid
  standalone/program paths. Headed projection coverage is still being verified.
- [ ] Integrate Python dab, C++ batch, mesh, grid/multires, and program paths;
  align undo/cancel replay and session rebuilding. Audit C API struct layouts
  and bindings if typed/sample payloads change.

**Gate:** compare recorded baseline and new-path outputs with dynamics disabled
and legacy pressure enabled using identical explicit dab samples, then test new
input/type combinations. Use separate corrected sampler expectations from Plan 3
for varying-pressure event streams. Cover draw,
smooth, grab, snake hook, paint/mask, dyntopo, multires, and main-plus-smooth
programs; verify undo/cancel and changing brush/scene between strokes. No tests
may silently pass by falling back to the legacy path. A command whose radius
exceeds the main brush must match separate-command execution outside the main
brush's original node set.
Use geometry spanning multiple spatial leaves; single-leaf tests cannot detect
truncation. Include radius ADD dynamics exceeding the base, growth across dabs,
a second unbounded command, symmetry, mesh/grid and batch execution.

## Plan 7: Generic UI and placement

**Goal:** one reusable property row across supported locations with correct
effective-owner editing and discoverable metadata.

### Tasks

- [ ] Implement a common renderer for value, pressure shortcut, unified control,
  effective-owner indicator, and metadata expander. Show the separate stack
  owner when it differs from the value owner.
- [ ] Implement stack controls: one row per unique device type, enable/disable,
  ordering, mix operation/factor, preset selection and owned/native curve editor.
  Show float/int/bool behavior and restrict unavailable inputs/static uniforms.
- [ ] Implement value and stack inheritance controls, honoring Always/Never
  modes without a misleading unified toggle. Edit the resolved owner through
  Plan 4 setters, including custom CurveMapping widgets.
- [ ] Implement `positions[]` with stable location identifiers, sorting and
  applicability. Render one setting in header, panel, and context menu without
  duplicating its data. Scope saved placement separately from transient UI state.
- [ ] Match current useful layouts by default and add a searchable All Properties
  panel in the Properties editor. Preserve native asset selection, texture and
  specialized widgets where the inventory explicitly retains them.
- [ ] Consolidate automasking: remove `SCULPTCORE_PT_automasking` from `ui.py`
  and its registration list once the surviving full UI is ready. Replace the
  native automasking content reached through the cloned advanced brush settings
  with SculptCore's controls. Audit `draw_mesh_automasking_settings` reuse and
  the `VIEW3D_PT_mesh_paint_automasking` header popover so all SculptCore entry
  points use the same definitions, owner resolution and supported settings.
  Scope these changes to SculptCore mode; do not alter native sculpt behavior.
- [ ] Apply the automasking compatibility table to labels, defaults, ranges,
  enable logic, inheritance and active-state icons. Omit unsupported native
  controls, expose supported engine settings with their actual semantics, and
  verify that each exposed control reaches the engine. The retained panel must
  replace the limited duplicate, not leave both registered under new names.
- [ ] Replace relevant vanilla panel clones and hardcoded header/menu rows only
  when their generic equivalent passes; prevent duplicate controls and stale
  polling callbacks on register/unregister.
- [ ] Verify keyboard/numeric entry, context menus, undo grouping, multiple
  windows/scenes, read-only assets and insufficient-width layouts. Drawing must
  neither allocate persistent curves nor mark assets dirty.
- [ ] Rebind F/Shift-F radial controls and bracket-size operators to the generic
  owner-aware adapters. Their current native-unified flag/`brush.scale_size`
  routing cannot represent Always/Never inherit. Resolve the right owner at
  invocation and preserve cancel/undo behavior without editing dormant values.

**Gate:** interactive checklists demonstrate that each visible row changes the
right owner and affects real sculpt behavior; saved layout survives reload.
Pressure enable/disable retains its curve, and no duplicate input types can be
created through UI or scripts. Native curve widget edits dirty the correct asset.
F/Shift-F and bracket controls agree with displayed values and row writes in all
inheritance modes, including cancel and undo with separate value/stack owners.
Exactly one canonical automasking panel implementation remains for SculptCore,
reused as needed across intended UI locations. Verify no duplicate limited
panel, no unsupported working-looking controls, and correct cavity/view-normal/
backface effects and owner selection in real strokes. Native sculpt UI remains
unchanged when switching modes.

**Touchpoints:** add-on `ui.py`, `tools.py`, `menus.py`, `vanilla_panels.py`,
keymaps where operator/context targets change, and property storage/renderer.

## Plan 8: Migration, compatibility, release

**Goal:** preserve existing user data and behavior while retiring competing
property paths and shipping matching fork, engine and add-on versions.

### Tasks

- [ ] Implement versioned, idempotent migration using the Plan 1 inventory and
  fixtures. Preserve set-versus-unset distinctions, defaults, custom curves,
  shadow pressure flags, native unified flags, and generated engine settings.
  Apply the frozen legacy default table and explicit one-name-to-many-ID rules;
  test a changed/missing DLL so new defaults cannot rewrite historical intent.
- [ ] Keep native-backed values in their native storage. Migrate add-on metadata
  and unmapped values only; do not overwrite dormant local state with resolved
  scene settings. Handle unknown/newer schema data without destructive downgrade.
- [ ] Handle assets loaded or activated after startup, not just file-load or
  mode-entry events. For editable legacy assets, define lazy in-memory migration
  and explicit persistence on asset save; never automatically rewrite an entire
  external library. Define read-only/essentials behavior and Save As requirements.
- [ ] Maintain old public RNA paths where practical using adapters or aliases.
  Specify behavior for scripts, keymaps, drivers/animation and old `.blend`
  data referencing renamed properties. Retain legacy serialized data until the
  migration and rollback policy is proven; do not delete it merely on access.
- [ ] Verify brush asset dirty detection and the save-reminder add-on see generic
  changes, including nested custom curves. Update change reporting where needed
  without silently coupling the standalone reminder to SculptCore internals.
- [ ] Run the fresh-process matrix: old/new files, old/new external assets,
  custom presets/mappings, duplicate/copy, save/revert, disabled add-on then
  re-enable, missing kernel, and supported linked/read-only workflows. Include
  background checks and interactive global/custom-mode undo checks.
- [ ] Add package capability checks for the owned-curve API and typed engine
  support. Update `tools/verify_addon.py` and `tools/smoke_test_package.py` so they
  instantiate and round-trip new settings and stop requiring retired interfaces
  only after a tested compatibility replacement exists.
- [ ] Build the fork and engine using their documented tooling, re-vendor the
  matching DLL/Python runtime, and stage a test package. Include ABI/capability
  mismatch diagnostics, minimum version documentation, and clean-machine smoke
  coverage. Package verification must prove the new path was actually used.
- [ ] Switch the default only after Plans 2–7 gates and migration fixtures pass.
  Retire old readers/UI/cache code in a separate cleanup change with parity
  checks; preserve promised compatibility aliases and serialized rollback data.

**Gate:** old fixtures preserve their authored/effective settings and baseline
stroke results for unchanged dab inputs; documented sampler corrections use the
independent Plan 3 expectations. New assets round-trip with independent custom
curves and correct save/revert/undo. Tested staged packages contain compatible fork/engine/add-on
versions. No unsolicited external asset writes or missing-data fallbacks occur.

## Review and completion record

- [x] Independent fork buildability/lifecycle review completed and findings folded in.
- [x] Independent engine/execution semantics review completed and findings folded in.
- [x] Independent migration/ownership/UI review completed and findings folded in.
- [ ] All eight implementation gates passed (future work).

The 2026-09-15 review used three fresh-context, read-only agents against the
actual fork/engine/add-on source. Surviving findings were incorporated:

| Review lens | Amendments |
| --- | --- |
| Fork buildability/lifecycle | Unsupported-reader round trips and unknown-IDProperty loss; curve/point/parent reallocation identity; non-allocating draw/first-edit behavior; raw-storage and unregister notification policy |
| Engine/execution | Actual modal event path and per-dab samples; timestamp scope decision; evaluator parity versus corrected interpolation; command spatial preflight; step-curve representation; Plan 3/6 gate boundary |
| Migration/ownership/UI | Effective-owner radial/bracket controls; compound cavity precedence; historical generated defaults and legacy-name splitting |

There is no known unresolved structural dependency cycle. Contract choices
explicitly assigned to Plan 1 remain implementation prerequisites, not findings
silently waived by this review.

As work lands, record each plan's implementing changes, test commands/results,
remaining limitations and cross-repository version requirements here.
Re-pressure-test any
materially revised plan before its implementation starts.

### Plan 4 completed — 2026-09-17

[Completion evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17)
and [verified manifest](../tests/plan4-completion-gate.json) record 25 successful
Blender runs, 11 pure tests, 150 native adapter checks, all 407 supported inventory
paths, real external assets, custom sculpt undo interleave and actual Brush curve
widget undo/redo. Installed source equality and fork/engine hashes are verified.
The explicit native authoring API also closes Plan 2's reopened Brush undo gate.
The native adapter, scoped undo and persistent ObjectModeType base corrections
received fresh adversarial reviews before implementation.

The persistent catalogue has 23 definitions and 62 owned-curve declarations;
native values remain authoritative and dormant local state survives independent
value/stack inheritance. Native setter asymmetry and the PINCH local-strength
exception remain explicit compatibility behavior. Plans 5–8 retain curve caching,
stroke integration, generic UI/automasking consolidation and release migration.

### Plan 1 completed — 2026-09-15

[Versioned contract](../design/generic-brush-contract-v1.md),
[owned-curve format](../design/owned-curve-storage-v1.md),
[annotated inventory](../design/generic-brush-inventory-v1.json), and
[commands/results/runtime identities](../codebase/generic-brush-plan1-evidence.md).
The evidence records fresh-process files/assets, ten deterministic geometry
oracles, native curve Save/Revert/copy, mesh/grid batch parity and actual headed
modal/cancel execution. Three adversarial reviews and a migration recheck were
folded into the contract. Existing unrelated addon/engine/fork changes remain.

Material downstream amendments from contract review:

* Plan 2: existing-type tagged IDProperty storage; owned-curve RNA discriminator,
  non-destructive validation, transactional initialize/unset/sync, validated
  runtime handles including widgets/iterators, and native cavity owner dirty
  notifications. Raw writes require explicit sync. Coupled size restoration
  needs an atomic native operation for Plan 7 cancel behavior.
* Plan 3: acquisition timestamps plus per-channel input-presence mask through
  GHOST/wmEvent/RNA/simulation and every dab payload. Arc-length interpolation;
  current-event device inputs for anchored/raw methods. INT32/BOOL conversion
  and analytic TWO_STEP follow the frozen contract.
* Plan 6: configuration-keyed cavity caches; union of command host/topology
  requirements; command-dependent hook preparation cannot be deduplicated by
  function pointer alone. Preserve documented PINCH/spacer/texture limitations;
  SCENE-size and variable-pressure corrections have independent expectations.
* Plans 4/8: native pressure authority after stack customization, legacy alias
  read/unset/animation overlay, and shared semantic size-stack ID. Preserve
  legacy scene-wide unified behavior by default pending user preference; native
  per-brush flags remain intact.

### Plan 2 completed — 2026-09-16

The completed runtime/editor lifecycle, actual headed widgets and undo,
Save/Revert/copy and old-reader preservation gates are recorded in
[Plan 2 evidence](../codebase/generic-brush-plan2-evidence.md#completion-gate--2026-09-16).
The early rejected runtime draft and accepted corrections remain historical
review evidence. No hidden node-tree backing store was introduced.

### Plan 3 completed — 2026-09-17

[Completion gate](../codebase/generic-brush-plan3-evidence.md#completion-gate--2026-09-17)
records the fixture/addon-only native matrices, exact-DLL Python and generated
bindings, frozen geometry baselines, actual headed modal/event/cancel tests,
shader checks, staged package and runtime hashes. The
[reviewed completion plan](generic-brush-plan3-completion.md) includes the
accepted execution and event review corrections.
