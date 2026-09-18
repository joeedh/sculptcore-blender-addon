# Plan 6B prerequisite: immutable effective-property snapshots

Completed bounded prerequisite, 2026-09-17. This slice preserves effective owners
and native semantic domains before adding engine translations or adopting consumers.
It does not enable the generic execution switch or complete Gate B.

Implementation: `brush_properties/snapshots.py`, `engine_catalogue.py`, and
production authoring registration. [Verified gate](../tests/plan6-snapshot-gate.json)
records three background Blender runs (98 new checks and 77 frozen-authoring
regression checks), 24 pure tests, installed source equality and runtime hashes.
[Evidence and limitations](../codebase/generic-brush-plan6-evidence.md#immutable-authoring-snapshot-prerequisite--2026-09-17).

Review status: catalogue/defaults and owner/domain reviews completed.
The built-in reviewer slots are exhausted. The user explicitly approved the
external read-only OpenAI CLI owner review on 2026-09-17. Its sandbox blocked
local file reads, so the approved review used a fixed source bundle supplied
through standard input, with no tool execution. The owner/domain review found
no blocking contradictions; its acceptance refinements below are required.
Completed review: [catalogue findings](../tests/plan6-snapshot-catalogue-review.md).
Independent review: [owner/domain findings](../tests/plan6-snapshot-owner-review.md).

## Deliverables

1. Add a DLL-independent immutable snapshot module. Capture an explicit ordered
   set of stable IDs through the existing resolver at one main-thread synchronization
   boundary. Reject duplicates/unknown IDs and unavailable dynamic stacks. Preserve
   the effective scalar domain (native ValueDomain or immutable Definition), actual
   typed value, source/presence, capability diagnostics, and prepared owner-free
   ExecutionLayers. No store, RNA, CustomCurveReference or NativeCurveReference is
   retained. Static definitions without a stack capability carry an empty stack;
   they remain execution-unavailable when the resolver reports that capability.
2. Capture the native semantic SIZE block from its already-resolved value owner:
   pixel diameter, world diameter and locked-size mode together. Validate all
   fields, including the dormant representation, and store primitives only. Keep
   this separate from engine radius; projection and applying the shared SIZE stack
   once after projection remain the next integration step. Never infer pixel/world
   mode from another owner, nor reinterpret pixel INT32 as semantic FLOAT32 during
   capture. No sampling, hashing, or inheritance traversal will happen in a dab.
3. Add four engine-owned static definitions for automask_view_normal (false),
   view_normal_limit (pi/2 radians), view_normal_falloff (25*pi/180 radians), and
   cull_backfaces (false), under stable `sculptcore.brush.*` IDs. These use generic
   storage on Brush/Scene, never native Blender fields with different defaults or
   semantics. Register independently of the DLL with execution still pending.
   Keep existing cavity adapters unchanged and preserve frozen legacy definitions.
4. Test persistent native/legacy/unset values, all independent value/stack owner
   combinations, custom/native prepared curves, paired size mode from both owners,
   pixel INT32/world FLOAT32 types, no persistent allocation on reads, stale owners
   or curves, and snapshots surviving owner edits/removal/cache clear. Test new
   engine defaults, saved overrides/inheritance, DLL-off registration, and no extra
   custom-curve declarations for static fields. Update existing bounded production
   registry-count assertion deliberately. Record actual background Blender evidence.

Owner/domain review acceptance refinements (folded before implementation):

- Exercise opposite Brush/Scene SIZE modes with unequal paired values, both
  effective value owners and both stack owners. Assert strict Python scalar types.
- Warm native-curve caches before editing the curve or switching the native/shadow
  pressure capability; preparing an old resolution must reject it.
- Capture must resolve fresh from stores, never accept an old Resolved as evidence
  of freshness. Reject invalidated/deleted stores even for empty/generated stacks;
  completed snapshots must remain usable after these changes.

## Remaining integration boundary

Catalogue review corrections to the deliverables: static-unavailable snapshots must
retain `stack_available=False` separately from their empty tuple. Validate each
dormant size field against its own native pixel/world ValueDomain, with strict
primitive types, allowed mode, and agreement of the active field with the resolved
value. Register engine definitions through a separate catalogue; preserve the legacy
`DEFINITIONS` alias and manifest diagnostic loop. Production counts become 27
definitions and still 62 curve declarations. Test repeated DLL-off registration.
Both angle definitions use `ROTATION`, hard/soft bounds [0, FLOAT32(pi)], and
FLOAT32 defaults equal to the existing engine constants 1.5707964f/0.43633232f;
booleans use bounds [0, 1] and False defaults. Test exact float32 values, since
mathematical angle endpoints and their rounded storage values can differ.

The snapshot is immutable authoring input, not a claim that every native property
already has an execution adapter. Target-specific manifest validation, normalization
and typed unit conversion precede commands.resolve_commands. In particular integer
spacing cannot silently become FLOAT32 dynamics just because the engine's spacing
field stores a fraction; snake pinch and strength compensation also need explicit
ordering. Size stack semantics are fixed by the contract. Per-adapter capability
activation, all host consumers and command capability gaps remain Plan 6B/C work.
