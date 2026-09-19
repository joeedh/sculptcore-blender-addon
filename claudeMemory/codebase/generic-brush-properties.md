# Generic brush properties: implementation reference

Updated 2026-09-19. This describes the implementation and its limits, not a
release approval. The generic stroke path is opt-in. Plans 1–7 passed their
gates. Migration/default rollout remains Plan 8.
See the [remaining work](../plans/generic-brush-properties-tasks.md),
[contract](../design/generic-brush-contract-v1.md),
[test guide](generic-brush-testing.md) and [history](generic-brush-history.md).

## Spatial support

The user clarified the spatial contract after the implementation tests:
ordinary brushes have bounded reads and hard-zero influence outside their
falloff boundary, even for a nonzero custom endpoint or Gaussian response.
Whole-mesh reads require an explicit brush declaration, such as Kelvinlet's
`@unbounded`. Falloff shape or endpoint alone never grants that capability.

Prepared executors now query finite regions for ordinary mesh/grid/program and
cage paths. Sphere support uses the radius; cube and oriented-box support use
enclosing spheres. Linear directional falloff is restricted to the radius sphere
because its directional metric alone describes an infinite slab. Strength is
zero outside the shape boundary; an authored nonzero endpoint is retained at the
boundary itself. Ordinary grab retains reached leaves across radius growth and
symmetry changes without selecting the drag-swept mesh.

CPU geometry, bounded mesh selection, command growth, grab and undo have passed
independent/native and Blender checks. Generated strength helpers also clip;
WGSL/SPIR-V compiled, while CUDA/HIP/OpenCL device parity remains unverified.
The change is tested with the rebuilt development DLL; default rollout remains
pending. Frozen legacy results remain historical evidence, including accidental
leaf-dependent spill outside the boundary. Do not regenerate them to hide the
user-authorized correction. See [verification](generic-brush-history.md#boundary-correction--september-18-2026).

## Addon structure

Sources live in `sculptcore_addon/brush_properties/`.

| Module | Responsibility |
| --- | --- |
| `registry.py`, `authoring.py` | Immutable definitions, unique device types, production catalogue and manifest readiness |
| `storage.py`, `legacy.py`, `frozen_v0.py`, `native_v0.py` | Versioned saved records, frozen legacy reads and defaults |
| `migration.py` | Explicit atomic v0 import and synchronization of changed raw legacy names |
| `resolver.py`, `adapters.py`, `bindings.py` | Effective value/stack owners and authoritative native RNA |
| `lifecycle.py`, `edits.py` | Operation-scoped owner validity and explicit grouped undo |
| `curves.py`, `customize.py` | Owner-aware custom mappings and explicit preset customization |
| `responses.py`, `sampling.py`, `uploads.py` | Analytic responses, bounded immutable tables and upload identity |
| `snapshots.py`, `commands.py` | Owner-free immutable inputs and command ancestry resolution |
| `evaluation.py`, `native_evaluation.py` | Typed semantic evaluation before unit conversion |
| `stroke_settings.py`, `stroke_runtime.py` | Stroke synchronization, projection and checked native transfer |

`interaction.py` supplies pinned value edits to keyboard and numeric controls.
`ui.py` draws shared rows in the tool header and the searchable All Brush
Properties panel in Properties > Active Tool. `placement.py` filters applicable
definitions and reads saved/default positions; `placement_ui.py` edits their
Brush-local overrides.

## Property rows

With the generic path enabled, numeric rows open a typed editor. Confirmation
validates the current owner/domain and commits one explicit authoring undo step;
editing the dialog or cancelling it does not write to the brush. Boolean rows
toggle immediately through the same value adapter. The row shows the value-owner
icon and names the input-stack owner when different.

The pressure shortcut edits the effective stack's unique pressure entry,
preserving its curve, mix settings, order and other entries. Static settings have
no pressure shortcut. The unified button appears only in Unified inheritance
mode. The details popup changes value inheritance and independent stack
inheritance without copying dormant values. Native cavity policy remains an
explicit compatibility choice. Unavailable execution and read-only targets
disable their respective controls.

Search state lives in Python UI state, separate from saved Brush/Scene settings.
Drawing reads defaults and existing mappings; it does not create records or
curves. Narrow sidebars and Properties editors put the value and controls on
separate lines; a different input owner gets its own label. Main windows resolve
their own scenes, and open editors reject a changed Brush/Scene. A linked Brush
can inherit an editable Scene value but cannot edit its own layout or mappings.

The details popup's Edit Locations dialog stages Tool Header, Brush Settings,
Context Menu and Automasking selections and integer order values. Lower values sort first, with
stable property ID breaking ties. Confirmation writes only the Brush's layout,
even when values and input stacks belong to the Scene. Cancel writes nothing;
changed Brush identity or placement rejects a stale draft. Deselecting all four
saves an explicit empty layout; All Brush Properties still lists the property.
Unknown/other locations are retained. Use Default Locations removes the override
headers while preserving dormant location metadata.

Basic Brush Settings and the context menu now use the same rows as the header.
Native brush type, color, texture, asset selection and display widgets remain. Stroke settings
retain the native method enum, explain the existing spaced-stroke fallback for
AIRBRUSH/LINE/CURVE, and omit unconsumed jitter/dash/rate/stabilization settings
in generic mode. Falloff retains native presets, shape and a scoped custom-curve
editor with descending presets. PROJECTED explicitly reports its existing spherical
fallback. The unconsumed normal-falloff child is hidden in generic mode.
Kernel scalar controls no longer appear again in the legacy Engine child panel
when generic properties are enabled. Size units are available in Size's details
popup and edit the effective owner through the native adapter with grouped undo.
The generic-disabled branch retains native scalar/stroke/falloff rendering.

`stack_ui.py` provides the input-stack popup beside each dynamic property.
Only absent device types appear in Add; existing entries can be disabled,
reordered or removed. Response settings edit mix operation/factor and generated
presets, including constant and two-step parameters. Missing device inputs are
skipped; the popup explains integer rounding and boolean threshold behavior.
Static or unsupported dynamics have no editable stack.

Custom selects a saved mapping without replacing it. Replace Custom From Preset
explicitly reseeds that mapping; generated presets leave it dormant. Owned
curves use the fork's transactional editor on the resolved stack owner. Brush
size/strength pressure uses its authoritative native mapping inside a scoped
dialog: Apply commits one authoring step, Cancel restores the exact mapping.
The native editor closes its scope before load, undo/redo or addon shutdown.
Layer dialogs pin their owner and stack; a stale draft cannot overwrite a
changed stack.

### Automasking

`automasking_ui.py` is the canonical renderer in the surviving advanced settings
panel (labelled Automasking), tool-header popover and main-header shortcut. The
limited `SCULPTCORE_PT_automasking` panel is removed. The native header panel
delegates to this renderer only in SculptCore; its original native sculpt draw
callback is restored on unregister.

Cavity enable/invert/factor/blur/custom-curve fields share the compound cavity
owner. Value rows and the curve button edit that effective native block, preserving
the other block. Under Native policy, disabling Scene cavity can expose the Brush
fallback; use explicit Always/Never when that fallback is unwanted. Custom cavity
curves apply before inversion. The same transactional native editor handles cavity
and Brush falloff, with Apply/Cancel, one-step undo and teardown rollback.

View-normal masking uses SculptCore's four engine settings. Limit and falloff are
shown in radians: the mask reaches zero at the limit, with the transition before
it. Cull Backfaces belongs to view-normal masking. Dependent value controls are
disabled when their mask is off; inheritance metadata remains accessible. The
active icon reads effective cavity/view-normal state. Native topology, face-set,
boundary, start-normal and occlusion controls are omitted because the engine does
not consume them. With generic properties off, the same panel offers native cavity
only; unsupported engine settings are not exposed.

September 19 verification: the existing custom-mode authoring fixture passed
172 checks across typed value/pressure ownership combinations and policy changes,
then 24 checks using actual rendered numeric and inheritance widgets. It verifies
cancel/confirm, one-step undo/redo and unchanged owner data during full-panel
draws. Both runs used staged addon Python and Blender `1c93a65f4ed4`; no engine or
fork source changed for these rows. This closes the shared-row step, not Plan 7.

The stack extension passed 130 operator/ownership/undo checks and 31 actual
curve-widget checks on Blender `4980bc0c4694` with staged addon Python. Snapshot
authoring and custom-curve create, addon-disabled resave and fresh reload also
passed. Fork commit `70ff11ce9b6` restores Python context after RNA callbacks;
without it, unregistering an open Python curve popup from a timer could leave
`bpy.context` pointing to freed memory. The headed fixture retains that shutdown
regression. The production engine DLL was unchanged (`839d1f5ad3e5`).

## Ownership, storage and compatibility

- Saved custom root: `sculptcore_properties`, schema 1. Records use a digest key
  but retain and validate the complete stable ID and exact scalar type. Separate
  versions cover stacks and positions. Unknown/newer data must survive unchanged;
  malformed and absent data are different cases.
- Brush values use UNIFIED/ALWAYS/NEVER; Scene is the root. Stack inheritance is
  independent. Writes edit the resolved owner without copying dormant values.
  Placement belongs to the Brush and does not inherit. Reads/drawing allocate
  neither saved records nor custom mappings.
- Native values stay in native RNA. Missing native capability is an error, not
  permission to create a second authoritative value. Size's pixel/world pair
  and mode share one owner and one semantic device stack. Preserve native setter
  asymmetry; exact cancel restores both values through the native transaction.
- Initial unified compatibility uses legacy Scene flags. New per-brush native
  flags remain separate. Cavity initially uses its compound NATIVE_CAVITY policy:
  enabled Brush block wins, otherwise enabled Scene block, otherwise edit Brush.
- Native/shadow pressure enable follows current brush capabilities even after
  stack customization. CUSTOM on Brush size/strength uses the native mapping;
  generated presets preserve it dormant. Scene pressure uses owned mappings.
- Five legacy generated names fan out to seven stable kernel IDs. The frozen
  registered defaults, not a new DLL's defaults, determine historical intent.
  Raw system-property inspection avoids allocating `Brush.sculptcore` on reads.
  Alias writes/unset/animation overlays and lazy asset migration are still work
  for the release phase; read adapters are not a completed migration.
- `ID_IS_EDITABLE` is authoritative: some linked Brush assets are editable.
  Ordinary readonly links and unsupported overrides must fail before writes.

## Fork APIs and lifetime

The canonical fork API documentation is in the companion checkout:
`doc/python_api/rst/info_owned_curve_mapping.rst` and
`doc/python_api/rst/info_property_authoring.rst`. The
[owned storage format](../design/owned-curve-storage-v1.md) is retained here.
Do not rerun old source-install scripts; canonical native sources live in the fork.

`bpy.props.CurveMappingProperty` uses existing tagged IDProperty groups, not
NodeTrees or a new serialized IDProperty type. The capability constant is
`bpy.props.owned_curve_mapping_api_version`. Unset reads are null; creation,
unset and raw-storage synchronization are explicit. Native materialization
validates evaluator finiteness as well as authored points.

Runtime mapping/channel access reacquires immutable snapshots. Point/iterator
and editor handles reject stale generations. Owner session identity, declaration
identity and parent-path watches matter independently; pointer reuse is not
identity. Invalidate before array relocation/memmove, but avoid rescanning every
descendant for each within-capacity append. This distinction fixed quadratic
point-array construction. Native widgets edit a staged mapping and commit only
after validating owner, path, declaration and revision. Runtime graph selection
and view state do not dirty the asset.

`ID.id_properties_update_atomic` stages scalar leaves and UI metadata under a
custom root. Duplicate/ancestor-overlapping operations reject; semantic no-ops
do not allocate or notify. Bounds, exact types, UI enum metadata and unknown
siblings survive. This API does not edit system storage.

`ID.authoring_edit_begin/commit/cancel` supplies explicit Brush/Scene undo.
Brush edits cannot rely on ordinary memfile undo alone. Tokens are main-thread,
single-use, owner/lifecycle-bound and reject nesting on one ID. Operators using
this API omit UNDO/UNDO_GROUPED to avoid duplicate history. `undo=False` provides
background rollback without creating history. No-op/cancel preserves redo.

Snapshots cover custom/system IDProperty trees and a finite native settings
scope, not arbitrary Brush state. Native scope includes paired size, supported
brush scalars/policies/pressure flags and size/strength/falloff/cavity mappings;
Scene scope includes selected sculpt UPS/cavity fields. Textures, gradients,
other paint modes, runtime samples and Brush identity are outside that scope.
Restore masked flag bits and raw coupled values without setter side effects.
ID references resolve by session UID/type, never by name, and user counts remain
balanced. Restore increments authoring revision and retires handles even on
cancel. Bound snapshot memory including lookup tables and sidecars. Native undo
must work without the addon or DLL. Persistent ObjectModeType base identity
allows disable/undo/re-enable without invalidating Python subclass ancestry.

## Evaluation and synchronization

The [contract](../design/generic-brush-contract-v1.md) defines arithmetic,
missing-input behavior, response directions, rounding and command inheritance.
Use that document for formulas rather than historical test output.

- Float stacks evaluate in float32; integer/bool arithmetic uses double and
  converts once after the ordered stack. Clamp then round integer ties away
  from zero; boolean threshold is 0.5. Static/enumerated/ID fields reject dynamics.
- CONSTANT and TWO_STEP remain analytic in native transport; a sampled table
  cannot preserve a discontinuity. Customizing TWO_STEP into a mapping explicitly
  produces an approximation. Bulk stack replacement validates before publication.
- Cache keys use complete canonical content with equality, not hash alone.
  Owned revisions/native fingerprints are inspected at synchronization boundaries.
  Table LRU is bounded to 256 entries and retains no owners/RNA. Undo/load/session
  recreation invalidates owner/upload state. Upload identity is separate from
  shared sampled-table identity. A warm unchanged stroke should not rebake curves.
- Stroke snapshots capture effective owners once and retain no RNA references.
  Semantic evaluation precedes spacing percent conversion, strength compensation
  and snake-pinch transforms. Size dynamics evaluate on projected radius once.
  Host/native evaluators have independent numeric comparison tests.
- Current batch transport groups consecutive rows with equal converted settings.
  Changing properties may produce single-row batches. Preserve order and checked
  execution rather than silently dropping dynamics to keep a larger batch.
- Autosmooth uses typed overrides from program creation and its own native
  strength stack. Mixing legacy float and typed overrides for the same property
  causes a duplicate-override rejection. It is not a reason to fall back to raw.
- Per-dab view rays are object-space and reflected per symmetry image. Tablet
  tilt is an input channel and is not reflected. Culling belongs to view-normal
  masking; unsupported native automasking controls must not appear functional.

### Stroke consumer audit

Generic stroke startup installs the resolved snapshot directly; it does not first
upload legacy local pressure/cavity/falloff settings. Paint color remains a native
vector, outside the scalar catalogue. The legacy path remains available while the
Scene opt-in is off.

| Consumer | Policy |
| --- | --- |
| Spacing and dyntopo | Evaluate integer spacing before percent conversion. Spacing uses the projected base diameter; size dynamics apply once to each dab radius. Relative/brush remesh edge lengths use that evaluated radius; remesh cadence retains the stroke-start pixel diameter. |
| Smooth and autosmooth | Decompose evaluated strength once. An enabled autosmooth stack creates the chained command even when its base is zero; that command applies the captured strength stack to its own autosmooth base. |
| Accumulate and attenuation | Both switches are static declarations. Preserve family exemptions and exact legacy spacing compensation; apply compensation once after semantic strength evaluation. |
| Cursor and projection | Use the captured size owner during a stroke and freshly resolve it when idle. Project along object-space view-right, including nonuniform scale; failed VIEW projection uses the effective world diameter. |
| Texture | Tiled repeat uses captured size at stroke start. Other texture/vector/enum settings keep their native adapters. |
| Families and batches | Keep PINCH's local-strength exception, SHARP's zero pinch and SNAKEHOOK's post-dynamics remap. Group consecutive equal payloads without reordering; checked-call failure ends execution. |

The headed Draw fixture edits Brush/Scene values and swaps independent value/stack
owners between strokes in the same session after undo/redo. The cache fixture's
`generic` mode rejects entry into legacy installation and checks warm strokes,
native curve edits, cleared native stacks and lifecycle invalidation.

## Native execution invariants and fixes worth retaining

`engine/source/brush/brush_preparation.*`, `brush_program_preparation.*` and
`semantic_scalars.*` own checked candidates. Validate every command before any
publication, topology work, undo capture or geometry mutation. Exact manifests
and immutable query tokens prevent stale index/name use. Native settings and
typed named stores remain authoritative where declared. Restore shared working
state after commands; execution order alone does not define inheritance.

- Independent command radii/stacks require a conservative union of bounded
  regions; only explicitly unbounded commands justify whole-mesh selection.
- Cavity caches include full configuration, stroke/geometry/topology identity
  and per-stage first contact. ENHANCE also needs command-dependent host fields;
  deduplicating those hooks by function pointer alone is incorrect. Scratch
  indexes use vertex capacity, not live count, after dyntopo deletion; stamp wrap
  must clear visited state. A later larger command must not capture an earlier
  command's first-contact data outside its support.
- Preview rollback resets executor stamps and first-contact caches, not just
  coordinates. Materializing a multires slot must bind an existing lazy executor.
- Dyntopo preflight precedes remesh; final regions and live links follow the
  changed topology. COLORSMOOTH requires its live disk-neighbor policy.
- Attribute undo captures the selected layer, including initialized absent-column
  semantics. Grid layer targets are pinned, enabled, unfrozen and weight one.
  General arbitrary session-channel targets are not thereby supported.
- Grid mask undo covers finer levels and allocation/debt state. Channel and
  level incarnation tokens distinguish remove/re-add from the original. Capture
  scales with touched grids; absence does not allocate finer storage. Restoring
  top-level mask leaves must advance maskGeneration even with no finer snapshot,
  or a resident slot can overwrite the restored mask on flush.
- Kelvinlet has explicit extended support. Scaled offsets/forces avoid overflow;
  double cutoff distance avoids squared-length under/overflow on CPU. Its declared
  displacement error bound is `4e-6 * max(abs(force)) + 8 binary32 denormal units`,
  with finiteness checked separately. Exact-origin handling preserves force.
  The tested Blender thread flushes float subnormals: checked transport rejects
  nonzero values lost to zero; do not change the host floating mode silently.
  GPU denormal behavior is not promised bitwise equal to native CPU.

## Remaining compatibility limits

### Migration foundation

`migration.migrate(authoring.store(brush))` imports the seven frozen generated
IDs from five legacy names without querying the DLL. It writes one atomic
transaction under `sculptcore_properties`, with a versioned `legacy_migration`
source snapshot. Unset values remain absent and use the frozen defaults; an
explicit set-to-default remains authored. Initial import preserves pre-existing
generic values. A later call compares exact raw presence/type/value with that
snapshot and fans each changed name out to all its frozen local destinations.
Unsetting a name clears those authored values. Unchanged calls publish nothing.

Native settings/pressure/unified flags and custom curves remain authoritative
where they were stored; migration never copies effective Scene settings into a
Brush. Unknown fields and raw legacy data remain intact for rollback. Unsupported
schema versions and malformed known sources fail before publication. Linked and
override owners reject writes. Use an existing `authoring_edit` scope for grouped
undo or cancellation; background callers can use the atomic operation directly.

This operation currently has **no automatic activation or edit hook**. Legacy
public RNA aliases, resolver-time animation overlays and raw-write synchronization
still need integration before automatic migration is enabled. Until then, manual
callers must synchronize subsequent raw legacy changes explicitly; the current
resolver does not refresh already-imported generic values from those changes.
No external library is scanned or saved. External asset save/revert, save-reminder
integration, packaged capability checks and default rollout remain Plan 8 gates.

### Retained execution behavior

Retain the PINCH local-strength extra-field exception, existing AIRBRUSH/LINE/
CURVE spacing behavior and documented texture limitations until separately
changed. Correct SCENE-size projection and varying-input interpolation have
independent expectations; they are not reasons to rewrite unrelated baselines.
Bracket keys now resolve the effective size owner and active VIEW/SCENE domain,
using a grouped authoring edit to preserve coupled native values through undo.
With generic properties disabled they delegate to the existing native operator.
The existing custom-mode authoring fixture covers bracket events across all 12
inheritance/unified/size-mode combinations, independent stacks and undo/redo.
F/Shift-F also pin the effective size/strength owner. Horizontal movement and
numeric entry share the same adapter and one explicit authoring undo scope.
Pressing Shift during a gesture enables precision; the Shift-F invocation itself
does not. Size numbers are pixel diameters in VIEW and Blender units in SCENE.
Escape/right-click, owner/domain changes and addon shutdown restore coupled
native values and release the overlay/timer. Generic-disabled controls delegate
to Blender's native radial operator. The headed fixture passed 176 checks over
18 combinations plus owner-change/shutdown cases; native fallback passed all four
size/strength and unified-flag cases. The later row, layout and multiple-window
checks are recorded in the task list and test guide.
The same staged Blender build (`1c93a65f4ed4`) passed the maintained headed Draw
regression after sharing the cursor overlay; the unit suite also passed.
Versioned migration and packaged default rollout remain unapproved by tests.
