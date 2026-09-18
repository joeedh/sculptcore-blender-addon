# Plan 4: complete authoritative native adapters

Implemented after fresh adversarial reviews, 2026-09-17; see
[completion evidence](../codebase/generic-brush-plan4-evidence.md#completion-gate--2026-09-17).
Depends on scoped native
authoring snapshots for exact size restoration and mixed native/metadata edits.
No generic stroke consumer or replacement UI is enabled here.

## Scalar registry and inventory

Freeze numeric native metadata from the reviewed inventory, with provenance.
Add authoritative Brush adapters for spacing (INT32 percent), plane_offset,
snake_pinch (raw crease_pinch_factor), hardness, autosmooth, accumulate and
spacing_attenuation. Scene fallback uses generic storage where it has no native
counterpart; never mirror Brush fields. Native size/strength use Scene sculpt
UPS and LEGACY_SCENE native unified flags. All writes validate both registered
definition and current native hard limits, quantize once and skip native no-ops.
Native/shadow pressure aliases and native definitions are reserved contracts.

Definition dynamic eligibility is explicit: only supported engine per-dab inputs
are dynamic (strength, size, spacing, plane offset, pinch, autosmooth as supported
by existing typed engine metadata); hardness/accumulation/spacing attenuation and
cavity parameters remain static. Execution capability stays false until Plan 6.

Non-scalar native settings (kernel, direction, stroke method, falloff preset/shape,
color/cursor color, texture/mapping resources and native falloff/cavity curves)
have specialized owner-aware bindings returning current RNA parent/property for
their retained widgets. They are not numeric dynamic Definitions. Validate
their enums/vectors/references using actual RNA, reject unsupported generic
stack writes, preserve all native storage and report unsupported execution
approximations from the inventory. Texture graph/stencil/secondary-texture paths
remain with the existing texture adapter. Emit a coverage artifact mapping every
supported stable inventory ID and all exclusions to its concrete adapter.

## Coupled size

Register numeric pixel/world representations with their stable inventory IDs,
but share one value policy at `sculptcore.brush.size`. Size mode uses the same
block. Expose an immutable SizeBlock(pixels, world, mode, actual owner). Native
setters retain Blender's paired rescaling behavior for ordinary size edits.
Cancel/undo uses scoped native snapshots to restore both values and mode exactly.

The common size Definition owns the single device stack. Its numeric value is
the effective native diameter in the selected mode (pixels or world); its value
metadata/bounds come from that mode's native RNA. Pixel writes require integral
values; world writes float32. Pixel/world representation aliases are value-only
and cannot create separate stacks. Their inheritance APIs route to the common
size policy. Multiple positions remain local to each displayed definition.
Scene/world conversion is a pure semantic function returning diameter/2; pixel
unprojection/object transforms stay in Plan 6 stroke geometry. Test exact unequal
pairs, mode changes and off-screen/world conversion against independent values.

## Native pressure and response curves

Brush strength/size always read their current native-or-shadow enable flag based
on sculpt capabilities, including after richer generic stack metadata exists.
Absent metadata exposes one virtual PRESSURE entry using the native curve and
current enable flag. Explicit empty stack disables native pressure and retains
its curve. Ordinary native/script flag edits remain visible: if enabled with an
explicit order omitting PRESSURE, expose a virtual pressure entry at the front;
on the next stack write normalize it into the order. Never duplicate a device.

Store only extra curve preset/order/mix/factor metadata. Native enabled is not a
second authoritative copy. Native CUSTOM uses a NativeCurveReference with full
OwnerGuard identity, stable property/device/path and canonical current native
evaluation data; no native evaluation key is invented from pointer addresses.
Generated preset choice preserves the native custom mapping dormant. Brush type
switches choose the appropriate flag without copying either flag. Other devices
use the owner-aware bank. Scene pressure has only generic metadata and owned
mapping storage; no native Brush curve is touched for inherited Scene stacks.

NativeCurveReference validation checks owner, selected native RNA path, current
canonical curve data and device before selecting it. Fingerprint covers clipping,
extension/wrapping/tone/black-white, channel handle defaults and point coordinates/
handles; excludes UI selection and tables. No sampling occurs in resolution.
Plan 5 owns shared evaluation caching. Actual native getters do not allocate
saved data. Selecting generated presets cannot reset or rebuild native curves.

Native enabled + metadata writes occur within the scoped authoring transaction:
prevalidate all layers/schema/capability/owner first, publish the atomic generic
batch and update the native flag, restore the captured state on any failure.
Low-level setters do not automatically push user undo; outer UI contexts choose
one grouped commit. Dirty state for no-op/failed requests is covered explicitly.

## Cavity block and semantics

Retain NATIVE_CAVITY as the absent block policy. One block policy controls normal/
inverted enable, factor, blur, custom toggle and curve; all numeric rows resolve
through it. Native precedence is Brush if either local flag, else Scene if either
Scene flag, else disabled with Brush edit target. Explicit UNIFIED/ALWAYS/NEVER
policies preserve both native blocks. Keep NATIVE_CAVITY limited to this adapter;
do not silently allow it for arbitrary scalar definitions. Missing native blocks
report unavailable and do not allocate during reads. Cavity rows are static.

Central pure semantic helpers preserve spacing percent/100, strength multiplier
for DRAW_SHARP, forced accumulation, direction, local-source PINCH strength and
snake pinch `2*(.5-factor)`. Source values remain authored-native; geometric/per-dab
math is not mixed into the adapters. Retained unsupported modes carry explicit
diagnostics. Plan 6 binds these resolved values to execution.

## Gate

All twelve value/stack owner combinations, script edits and type changes;
inactive assets and Scene edits dirty only actual owners; native/shadow toggle
truth table and dormant curves through presets, disable/reorder/clear and copy;
Scene-owned native-semantic stacks never edit Brush curves. Exact size pair/mode
cancel/undo, independent world/pixel conversion examples. Full cavity enable
truth table, script edits, normal/inverted precedence, generic policy switching,
read-only targets and missing blocks. Validate every inventory coverage row.
Package and fresh-process tests run after native authoring undo is integrated.

## Fresh adversarial review corrections

Both semantic and coverage reviewers found the following required seams. These
refinements are part of the implementation contract:

- Common size remains one stable FLOAT32 Definition (positive native diameter
  domain), never mutated/re-registered when mode changes. Effective-owner
  `validate_value` and `value_domain` provide operation-scoped RNA limits/type;
  resolver calls these after owner resolution. Pixel/world aliases use their
  fixed domains and share only value policy; they reject stack operations.
- Preserve the fork's actual asymmetric rescaling: pixel writes scale world
  size; world writes currently preserve pixels. Predict and validate the entire
  resulting pair, rejecting overflow or out-of-range world values before setter
  invocation. Fixing BKE_brush_scale_size is outside this adapter change.
- Native curve keys need a read-only fork API, because wrapping and default
  channel handles are not exposed by existing RNA. The authoring snapshot
  canonical serializer supplies `ID.authoring_native_curve_key(path)` without
  saved allocation, sampling or pointer-based identity.
- DeviceLayer accepts and revalidates NativeCurveReference. CurveBank excludes
  only Brush strength/size PRESSURE; all other devices keep owned declarations.
- Native PRESSURE codec ignores any old schema-1 saved enabled field, preserving
  it as dormant unknown metadata; new writes omit enabled for this one variant.
  Non-pressure devices and every Scene entry retain ordinary enabled storage.
  Persist explicit empty headers even when metadata was absent, and disable the
  current native flag. Script re-enable exposes one virtual pressure layer.
- Cavity edit resolves/pins one destination for its entire transaction. Coupled
  enable edits accept one explicit mode OFF/NORMAL/INVERTED, rather than applying
  two true booleans in unspecified order. Disabling local cavity may reveal Scene
  cavity only on the next resolution; undo restores the captured local block.
- Coverage keys are inventory owner + RNA path (not only repeated stable IDs),
  including texture-slot children, native/shadow pressure and Scene counterparts.
