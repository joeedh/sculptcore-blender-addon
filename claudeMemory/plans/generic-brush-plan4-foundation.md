# Plan 4: registry and owner-resolution foundation

Status: reviewed by fresh review_plan4_resolution and review_plan4_native agents,
2026-09-17; corrections below accepted before implementation. Plan 3 passed.
This document refines Plan 4;
it does not replace that plan's persistent-storage and integration gate.

First slice implemented and tested: 11 dependency-free tests and 22 real Blender
checks pass. See [evidence](../codebase/generic-brush-plan4-evidence.md).
Steps 2–4 remain open.

## Dependency order

1. Implement a DLL-independent definition registry, immutable resolution records,
   independent value/stack owner selection, and an authoritative native strength
   adapter. This bounded foundation is the first implementation slice.
2. Add versioned Brush/Scene RNA collections implementing the storage interface,
   owned custom curves, explicit owner notifications, and definition-specific
   editable RNA fields. Verify persistence, copying, dirty state and undo before
   exposing saved authoring controls. Native storage never receives a second
   authoritative value in the collections.
3. Complete size's coupled adapter, native/shadow pressure and native curves,
   compound cavity, remaining mapped settings, and frozen legacy defaults/import
   views. Separate live engine capabilities from stable definitions and values.
4. Run every original Plan 4 gate before enabling consumers in later plans.
   Strokes and existing UI continue using their current settings meanwhile.

## First slice: concrete scope

Create a focused `sculptcore_addon/brush_properties/` package with no bpy or
engine import in its registry and resolver. The package is not registered into
the UI or stroke path in this slice.

- Frozen definitions hold stable ID, label, scalar type, default, hard/soft
  limits, description, units, dynamic eligibility, owner capabilities and plural
  positions. Validate duplicate IDs, finite typed defaults and ranges. Do not
  derive identity or defaults from runtime manifest positions. Registry revision
  changes only on actual definition changes; conflict registration fails.
- Definitions are immutable. Keep persisted records and future RNA storage out
  of the registry. Unknown IDs raise an explicit unresolved-definition error;
  never delete their stored records. An unavailable kernel remains a separate
  execution capability, not a reason to replace its definition or saved value.
- A narrow storage protocol supplies owner capability, local authored value
  presence, value mode, scene unified flag, stack inheritance and immutable stack
  descriptions. Reads never ensure/create records. Tests implement this protocol
  with an in-memory fixture; that fixture is not production persistent storage.
- Resolve value and stack owners separately with the contract's UNIFIED/ALWAYS/
  NEVER truth table and independent stack flag. Missing records use the selected
  owner's definition default/empty stack without materializing. Missing parent
  capability falls back locally with `parent_unavailable`; missing local
  capability is an explicit error. The only hierarchy is Brush -> Scene.
- Return the definition, effective value, both owners, immutable stack,
  source diagnostics and a structural invalidation tuple. Include registry
  revision, authored presence, owner identity, policies, value and stack content.
  No long-lived RNA references or cache are introduced here.
- Setters resolve at invocation, validate type/range and owner editability, then
  call the selected store's write method. Inheritance setters change metadata
  only. Unique-device validation rejects duplicates before any write; replacing
  an entry preserves its index, and disabling preserves its other fields.
- Add a native strength adapter using Brush.strength and
  Scene.tool_settings.sculpt.unified_paint_settings.strength/its scene flag.
  Read current native values on every access. Capture native metadata explicitly
  from the frozen inventory (hard range 0..10; brush default 1, scene default .5).
  Keep the fork's per-brush unified flags untouched. Do not enable generic
  strength stack editing until the native pressure/curve adapter is implemented;
  report that capability explicitly rather than treating an empty stack as the
  native brush's effective pressure behavior.

## First-slice tests and completion evidence

- Dependency-free table tests cover every value mode x unified x stack flag,
  different local/scene values/stacks, effective writes, dormant restoration,
  missing records/parent capabilities, unknown IDs, immutable definitions,
  invalid types/ranges, duplicate devices, disabled data, independent owners,
  multiple positions and registry/capability changes.
- Real Blender background checks exercise the native strength adapter on two
  brushes and two scenes, inactive-owner edits, ordinary native script edits,
  scene unified policy and missing engine. The adapter imports without loading
  a DLL. Invalid writes must leave both owners unchanged.
- No generic persistent schema, custom curve allocation, asset-dirty guarantee,
  metadata renderer or full Plan 4 completion is claimed by this first slice.
  These remain explicit work in steps 2–4 and the original acceptance gate.

## Reviews

Both fresh read-only reviews accepted the bounded scope. Folded corrections:

- Separate value and stack capabilities and fallback diagnostics. An unavailable
  native pressure adapter is not an empty identity stack and cannot redirect a
  valid value write. Include capabilities and execution availability in keys.
- Policy edits always target the requesting Brush; unified edits target Scene.
  Scene is a root and never inherits. Read-only checks target the actual edit
  owner. Rejected writes preserve values, records and policies.
- Native DNA values are always present, independent of generic metadata. The
  native strength adapter supplies current RNA and owner-specific defaults.
- Validate genuine BOOL, signed INT32 excluding bool, and finite representable
  FLOAT32. Validate hard/soft ordering, deep immutable positions/layers and all
  disabled layers too. Duplicate imports fail without changing saved data.
- Pure tests load the actual subpackage with an isolated package loader, avoiding
  the bpy-dependent addon initializer. Native tests use the same route and block
  engine imports. This proves the adapter triggers no engine load; the staged
  process may already have loaded the addon engine during startup.
- Native adapter policy is explicitly injected transient metadata in this slice;
  its default is UNIFIED/local stack. No ad-hoc saved IDProperties or per-brush
  native unified flags are used. Production RNA storage replaces this interface
  in the next slice.
- Native UnifiedPaintSettings update currently notifies the context Scene and
  active Brush, even for an inactive Scene edit (rna_sculpt_paint.cc). Numerical
  writes are correct; notification ownership must be fixed/tested in step 2.
  The first-slice numerical tests do not certify notification or asset dirtiness.
- Implementation audits added explicit metadata owner restrictions, validated
  capability/presence records and whole-record repair without consuming invalid
  old content. Fresh Scenes can lack native Sculpt settings; that is unavailable
  parent capability, never a reason to allocate data during resolution.
