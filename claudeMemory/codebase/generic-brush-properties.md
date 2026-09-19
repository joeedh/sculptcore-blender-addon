# Generic brush properties: implementation reference

Updated 2026-09-18. This describes the implementation and its limits, not a
release approval. The generic stroke path is opt-in. Plans 1–5 passed their
historical gates; stroke integration, UI and migration remain unfinished.
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
| `resolver.py`, `adapters.py`, `bindings.py` | Effective value/stack owners and authoritative native RNA |
| `lifecycle.py`, `edits.py` | Operation-scoped owner validity and explicit grouped undo |
| `curves.py`, `customize.py` | Owner-aware custom mappings and explicit preset customization |
| `responses.py`, `sampling.py`, `uploads.py` | Analytic responses, bounded immutable tables and upload identity |
| `snapshots.py`, `commands.py` | Owner-free immutable inputs and command ancestry resolution |
| `evaluation.py`, `native_evaluation.py` | Typed semantic evaluation before unit conversion |
| `stroke_settings.py`, `stroke_runtime.py` | Stroke synchronization, projection and checked native transfer |

`interaction.py` and `placement.py` are unfinished, unintegrated UI groundwork.
Their existence does not mean the generic UI is available.

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

Retain the PINCH local-strength extra-field exception, existing AIRBRUSH/LINE/
CURVE spacing behavior and documented texture limitations until separately
changed. Correct SCENE-size projection and varying-input interpolation have
independent expectations; they are not reasons to rewrite unrelated baselines.
The generic UI, radial/bracket ownership, automasking panel consolidation,
versioned migration and packaged default rollout remain unapproved by tests.
