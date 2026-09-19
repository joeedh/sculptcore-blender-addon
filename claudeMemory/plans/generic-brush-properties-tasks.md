# Generic brush properties: remaining work

Updated 2026-09-19. This is the single active task list. The original eight-plan
history is condensed in [history](../codebase/generic-brush-history.md); current
implementation details and known defects are in [the reference](../codebase/generic-brush-properties.md).
Read the [contract](../design/generic-brush-contract-v1.md) for ownership/numeric
semantics and [test guide](../codebase/generic-brush-testing.md) for focused checks.
Historical review requirements were waived by the user for the remaining task list.

## Completed foundations (historical gates)

- [x] Plan 1: contracts, migration inventory and frozen compatibility inputs.
- [x] Plan 2: owner-aware CurveMapping storage, RNA, editor and lifecycle.
  Brush authoring undo was reopened and subsequently covered by explicit scopes.
- [x] Plan 3: typed device dynamics, checked declarations/bindings and input delivery.
- [x] Plan 4: generic records, independent resolution, native adapters and authoring undo.
- [x] Plan 5: generated/custom responses and bounded revision-aware caching.

These passes do not certify the unfinished stroke/UI/migration integration.
Do not enable the new path by default until the remaining gates pass.

## Plan 6: stroke and command integration — complete

Implemented behind the Scene opt-in switch: immutable effective-owner snapshots,
native typed semantic evaluation, per-dab/batch transfer, mesh/grid/program routes,
preview/grab/dyntopo/attribute/cage/layer integration, and view-normal/backface
settings. Actual generic gesture tests require native semantic and checked calls.
Acceptance checks:

- [x] Correct ordinary brush spatial support. The user requires bounded reads
  and a hard zero outside the falloff boundary, even with nonzero curve endpoints.
  Whole-mesh reads require an explicit declaration (for example Kelvinlet).
  Remove implicit all-node policies for falloff kinds/shapes and normal anchored
  grab. Preserve moved pinned grab regions; audit CPU and generated backends,
  mesh/grid/program/batch/preview/cage selection and clipping.
- [x] Replace the earlier all-node falloff test oracle with independent boundary
  expectations and bounded-read assertions. Preserve frozen legacy fixtures as
  evidence; document the user-authorized correction to old leaf-dependent spill.
- [x] Finish auditing every consumer: stroke setup, spacing/dyntopo cadence,
  smooth decomposition, autosmooth including zero-base dynamic enable, accumulate,
  cursor/projection/offscreen fallback, texture projection and family adapters.
  No double dynamics or double attenuation; no raw fallback disguised as support.
- [x] Verify independent command radii/stacks, larger later commands, bounded
  union selection and explicitly unbounded commands on multileaf geometry.
  Preflight all property/topology/attribute requirements before mutation; retain
  per-command cavity/ENHANCE first-contact caches and correct override restoration.
- [x] Verify actual draw, smooth, grab, snake hook, paint/mask, dyntopo, multires
  and main-plus-smooth strokes through per-dab and batch paths, including symmetry,
  preview cancel, Blender undo/redo, and Brush/Scene changes between strokes.
- [x] Compare unchanged basic/legacy-pressure geometry with frozen inputs; use
  independent expectations for the already specified sampler/world-size fixes
  and the newly clarified hard clip. Exercise float/int/bool and missing inputs.
- [x] Finish cache/session rebuilding, capability diagnostics, binding/layout
  audit and matching staged package checks. Record one concise final result.

**Gate:** all consumers use resolved ownership and typed semantics; command
regions include every permitted contribution and exclude unbounded reads for
ordinary brushes. Actual generic execution, rollback and undo are demonstrated.
Historical broad test counts and previously passed all-node references are not
substitutes for this gate.

September 18 boundary correction: native falloff/prepared execution/grab/unbounded
and compiler suites passed; Blender passed 16 runtime cases (including independent
constant-edge geometry), two unchanged basic fixtures and 24 headed Draw/Grab/
preview gestures. See [verification and limits](../codebase/generic-brush-history.md#boundary-correction--september-18-2026).
Generated WGSL/SPIR-V compiled; CUDA/HIP/OpenCL emitters were updated but were not
validated on devices.

September 18 consumer gate: removed redundant legacy installation before generic
snapshots. The matching staged package passed 86 gesture cases and five repeated
cache strokes, including zero-base dynamic autosmooth, independent owner changes
between strokes, cancel and undo/redo. Typed probe execution/bindings, packed
layout, runtime/readiness/cache and unchanged basic baselines passed. Warm generic
strokes rebake/upload no curves. See [final verification](../codebase/generic-brush-history.md#stroke-consumer-gate--september-18-2026).
This closes the CPU addon integration gate; UI, migration, default rollout and
device-backend execution certification remain separate work.

## Plan 7: Generic UI and placement — complete

**Goal:** one reusable property row across supported locations with correct
effective-owner editing and discoverable metadata.

### Tasks

- [x] Implement a common renderer for value, pressure shortcut, unified control,
  effective-owner indicator, and metadata expander. Show the separate stack
  owner when it differs from the value owner.
  The existing headed fixture passed 172 typed/operator/policy checks and 24
  actual-widget checks. Numeric cancel/confirm, independent pressure ownership,
  dormant values, curve/order preservation, one-step undo/redo and non-mutating
  full-panel drawing passed on the staged addon (September 19).
- [x] Implement stack controls: one row per unique device type, enable/disable,
  ordering, mix operation/factor, preset selection and owned/native curve editor.
  Show float/int/bool behavior and restrict unavailable inputs/static uniforms.
  The existing headed fixture passed 130 stack-action checks across Brush and
  Scene owners, including preset/custom preservation, undo/redo, duplicate and
  static-input rejection, and stale-owner drafts (September 19).
- [x] Implement value and stack inheritance controls, honoring Always/Never
  modes without a misleading unified toggle. Edit the resolved owner through
  Plan 4 setters, including custom CurveMapping widgets.
  Actual native and inherited owned-curve widgets passed Apply/Cancel and
  one-step undo/redo checks; native edits roll back during addon disable.
  Drawing the stack popup leaves Brush and Scene unchanged. The wider
  multi-window/read-only interaction matrix remains a separate gate below.
  The 31-check widget gate uses rebuilt Blender `4980bc0c4694`, including fork
  fix `70ff11ce9b6` for a stale Python context after popup unregistration.
  Snapshot and fresh-process custom-curve persistence regressions also passed.
- [x] Implement `positions[]` with stable location identifiers, sorting and
  applicability. Render one setting in header, panel, and context menu without
  duplicating its data. Scope saved placement separately from transient UI state.
  The existing fixture passed 39 headed checks for actual surfaces, placement
  Apply/Cancel, undo/redo, sorting, reset/empty/unknown locations and stale drafts,
  plus owner-aware size units. A fresh process passed two checks on a saved copy
  of the edited Brush (September 19, Blender `4980bc0c4694`), including the fourth
  Automasking location. External asset persistence remains in Plan 8.
  The affected shared-row widget regression also passed its 24 checks.
- [x] Match current useful layouts by default and add a searchable All Properties
  panel in the Properties editor. Preserve native asset selection, texture and
  specialized widgets where the inventory explicitly retains them.
  The searchable All Brush Properties panel and shared tool-header rows are
  implemented. Basic Brush Settings and the context menu now use shared rows;
  native asset/type/color/texture/display controls remain. Stroke and falloff
  retain their native selectors with explicit existing-behavior limitations;
  unused stabilization and normal-falloff controls are hidden in generic mode.
- [x] Consolidate automasking: remove `SCULPTCORE_PT_automasking` from `ui.py`
  and its registration list once the surviving full UI is ready. Replace the
  native automasking content reached through the cloned advanced brush settings
  with SculptCore's controls. Audit `draw_mesh_automasking_settings` reuse and
  the `VIEW3D_PT_mesh_paint_automasking` header popover so all SculptCore entry
  points use the same definitions, owner resolution and supported settings.
  Scope these changes to SculptCore mode; do not alter native sculpt behavior.
- [x] Apply the automasking compatibility table to labels, defaults, ranges,
  enable logic, inheritance and active-state icons. Omit unsupported native
  controls, expose supported engine settings with their actual semantics, and
  verify that each exposed control reaches the engine. The retained panel must
  replace the limited duplicate, not leave both registered under new names.
- [x] Replace relevant vanilla panel clones and hardcoded header/menu rows only
  when their generic equivalent passes; prevent duplicate controls and stale
  polling callbacks on register/unregister.
- [x] Verify keyboard/numeric entry, context menus, undo grouping, multiple
  windows/scenes, read-only assets and insufficient-width layouts. Drawing must
  neither allocate persistent curves nor mark assets dirty.
- [x] Rebind bracket-size keys to the generic owner-aware adapter. The effective
  size owner/mode is resolved at invocation; one authoring undo entry preserves
  paired native sizes, dormant values and independent stacks. The existing
  custom-mode authoring fixture exercises real bracket keys across all 12
  inheritance/unified/size-mode combinations and undo/redo.
- [x] Rebind F/Shift-F radial controls to the generic owner-aware adapter. Pin
  the effective owner and size domain at invocation; preserve dormant values and
  independent stacks. The headed authoring fixture passed 176 checks across 18
  ownership/domain combinations, numeric entry, precision, cancel, undo/redo,
  owner changes and addon disable. Native fallback passed with generic disabled.

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

**Completion evidence (September 19):** Blender `4980bc0c4694`, unchanged production
engine DLL `839d1f5ad3e5a`. Maintained fixtures passed:

- `test_authoring_custom_undo.py --args panels`: 56 checks of canonical
  automasking, Brush/Scene cavity and Brush falloff widgets, Apply/Cancel/undo,
  dirty flags, independent main-window scenes, linked-owner guards, narrow
  non-mutating layouts, specialized popovers and switching to native sculpt.
- `--args rows-ui`: 24 actual numeric/search/widget checks; `--args stacks-ui`:
  31 native/owned curve and teardown checks. The earlier typed/operator and
  shortcut gates above remain applicable.
- `--args placements`: 39 checks across all four surfaces; fresh-process
  `--args placements-reload`: two persistence checks.
- `test_brush_automasking.py`: 40 mesh/grid × single/program cases passed both
  background and headed `--args ui`. UI-authored cavity factor/blur/custom flags
  and view-normal/cull/angle values reached the engine; custom zero/one curves
  proved suppression and inversion order, with geometry undo/redo.
- Unit suite: 42 tests. Screenshot review confirmed the consolidated panel,
  narrow owner controls, and readable stroke/falloff popovers. `git diff --check`
  passed. Logs/screenshots remain ignored under `claudeMemory/tests/` with
  `brush-plan7-*` and `brush-runtime-automask` prefixes.

No engine or fork edits were needed for this closing slice. Generic properties
remain opt-in; Plan 8 owns migration and default rollout.

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
