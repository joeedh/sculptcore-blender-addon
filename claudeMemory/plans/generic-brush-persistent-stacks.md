# Plan 4 persistent generated device stacks

Status: implemented and bounded completion gate passed, 2026-09-17. Fresh
`review_stack_storage` and `review_stack_semantics` plan reviews and subsequent
implementation audits are folded in. See
[completion evidence](../codebase/generic-brush-plan4-evidence.md#persistent-generated-device-stacks--2026-09-17).

## Review corrections

- A present stack version must be a genuine integer 1 on both read and write.
  Missing version with any stack fields is malformed on read; explicit whole
  replacement may repair the missing version. Do not repair present mistyped or
  future versions. Keep this validation out of scalar/policy access and capability:
  those operations preserve an unknown stack sub-schema opaquely.
- Reads require a genuine string order (at most 64 characters and four entries),
  and a group `layers` if present, even for empty order. Nonempty order requires
  layers. No recognized stack fields is the only absent-stack encoding.
- Native atomic storage also rejects scalar retyping when a stored leaf has
  IDP_FLAG_STATIC_TYPE. Whole-stack repair must reject/preserve those mismatches
  as well as non-scalar leaves/ancestors. Test late-failure rollback explicitly.
- Share immutable device and preset-arity tables with registry validation. Keep
  native dispatch first: even an empty direct native stack write must reject.
  Static generic definitions can represent empty stacks but reject nonempty data
  on both direct store access and resolver paths. No execution capability is added.
- Descriptor levels remain finite doubles, including negative and greater-than-one
  values beyond FLOAT32 range; only factor and TWO_STEP threshold use [0,1]. Test
  threshold endpoints, integer-input normalization and invalid disabled entries.
  Implementation audits added static stored-data rejection, value-write/stack
  isolation, partial headers and malformed dormant data to the runtime gates.

## Bounded scope

Implement persistent ordered generated-response stacks for generic FLOAT32,
INT32 and BOOL definitions using the existing atomic scalar fork API. Native
strength stack capability remains unavailable until its native pressure adapter
is implemented. Execution remains unavailable until curve preparation/integration.
Custom CurveMapping bank, saved positions and authoring undo beyond generic Scene
remain later work. No fork or engine changes are needed for this slice.

## Encoding and transaction

Within each existing property record, add `stack_version=1`, `layer_order` (a
comma-separated string of the fixed v1 device names; empty string means empty),
and `layers` group keyed by device. Each keyed entry contains `enabled` bool,
`operation` string, `factor` double, `preset` string and `parameter_0` through
`parameter_2` double fields. Store all three parameter slots, unused slots zero.
Read only the preset's arity, requiring unused slots zero. This deliberately
uses scalar leaves, never dictionary replacement or RNA collection arrays.

No stack fields means empty, without allocation. Empty write to absent stack is
a no-op. Nonempty writes atomically publish version/order/all active known fields
plus record identity. Clear sets the order empty, retaining keyed payloads as
dormant data; re-add explicitly replaces known fields from the supplied layer.
Unknown sibling fields and dormant entries survive native cloning. A future
curve bank can use the same stable property/device keys independently of order.
Stored active order must be unique and contain supported device names; every
active payload is fully validated, even when disabled. Unknown version/order/
preset is preserved and rejected on read. Future stack versions reject on write.

Complete stack replacement validates all incoming layers first and can repair
malformed scalar fields/order or missing fields. It cannot replace malformed
group/array/ID ancestors/leaves through the scalar-only native API: reject with
no mutation. It does not silently downgrade future stack versions. Existing
property schema/identity/policy validation still precedes writes.

Reads return immutable DeviceLayer/ResponseCurve tuples with finite doubles and
genuine bool/string types. Writes normalize numeric factor/parameters to double.
Static definitions reject nonempty stacks on direct writes and reads, as well
as through the resolver. The generic store reports stack capability true and
execution false; the native adapter retains its current capabilities.

## Gates

1. Pure foundation/import regression. Actual Blender round trips all device,
   operation and preset descriptors; float/int/bool definitions; disabled state,
   reorder, clear/re-add, exact types, duplicate rejection and malformed reads.
2. All twelve value-mode/unified/stack-inheritance combinations with persistent
   stores. Effective stack edits target their independent owner and preserve the
   dormant stack/value; adding an existing device updates in place.
3. Native stack rejection, static rejection, future version preservation, explicit
   scalar repair, failed multi-field rollback, opaque/unknown sibling preservation,
   no-allocation/no-op and independent Brush/Scene copies.
4. Real external assets: inactive owner dirty isolation, no-op cleanliness,
   Save/Revert and fresh-process load. Generic Scene stack undo/redo with lifetime
   invalidation. Save/load with authoring modules blocked.
5. Restage addon, package verification/smoke, update task list/evidence with exact
   bounded scope. Keep full Plan 4 and Brush/native-Scene undo open.
