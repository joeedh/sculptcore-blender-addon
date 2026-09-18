# Plan 4: DLL-independent frozen authoring and legacy reads

Fresh registration and semantics reviews folded in, 2026-09-17.

Scope: production registration, immutable frozen legacy definitions, nonmutating
legacy import views and a saved default-off rollout switch. Native adapters and
authoring undo retain their own completion gates. Do not enable generic stroke/UI.

## Frozen source and definition catalogue

Generate a production Python data module from the Plan 1 `baseline.json`
manifests and `registered-rna.json`; embed provenance hashes. The frozen union
declaration, not the currently loaded DLL, supplies historical type/default/
hard and soft ranges/description/unit. Fan each legacy name out to every frozen
kernel association. Stable IDs preserve uniform case. Do not copy ephemeral
slots. Include a deterministic generation check and assert all associations.

A production authoring module owns a Registry and CurveBank. Initial catalogue
includes frozen engine definitions and native definitions as their adapters land.
Register it before `engine_props.register()` and provider work. Registering the
bank is engine-independent. Failed bank registration cleans its partial leases;
production registration failure unwinds its own additions. Unregister the bank
before lifecycle shutdown. Repeated registration is idempotent.

Engine manifest refresh is a separate explicit API accepting validated metadata
from the caller. It computes transient availability/diagnostics and does not
rewrite catalogue definitions, defaults, slots, saved records or unknown IDs.
Only matching stable ID/type contracts are executable in a later consumer;
missing/conflicting kernels remain authorable with execution unavailable. New
IDs require explicit definition registration rather than slot/name reinterpretation.
Legacy `engine_props` remains the active path until Plan 6; its registration is
not used as a prerequisite for the new catalogue. Its compatibility replacement
and public alias migration are Plan 8.

## Read-only legacy view

For frozen engine definitions with no generic value, Brush reads use a separate
read-only adapter. Read the raw existing `Brush.sculptcore` backing group without
accessing a missing PointerProperty (which could allocate). Reconcile declared
system-IDProperty vs custom-IDProperty namespaces against the actual fork before
implementation. If needed use a bounded engine-agnostic nonallocating native
getter; do not assume `Brush.get('sculptcore')` sees system storage.

An authored known name validates its exact scalar type and frozen limits and
returns `ValueSource(..., present=True, source='LEGACY')`. Missing name returns
the frozen default with `present=False`, distinguishable from an authored value
equal to that default. Unknown names stay opaque. One-name/many-kernel reads
share the old authored source without materializing generic records. Scene has
no legacy engine values and uses frozen defaults. Generic explicit values take
precedence; migration/alias/animation overlays are Plan 8 and must be called out.
Malformed legacy values fail closed rather than mutating or silently clamping.
Read-only linked data is readable. Merely reading never initializes a curve or
marks an asset dirty. Explicit generic writes materialize only the selected ID.

## Rollout switch

Use saved Scene authoring metadata under a distinct known field of the existing
generic root, default false, exact bool. Read absent without allocation. Setter
uses native atomic scalar publication and validates schema, preserving unknown
fields/records. Explicitly label as readiness/testing switch; Plan 6 is the first
consumer. Do not silently change current strokes when toggled now.

## Gate

Unit-check generation/provenance and frozen fanout. Actual Blender tests register
production catalogue with all engine import/load/manifest access forced to fail;
prove definition/curve authoring, copied/reloaded data and unknown preservation.
Baseline `.blend` unset/set-to-default cases resolve identically with changed or
missing manifests. Capture values and asset dirtiness before/after repeated reads.
Test repeated register/unregister, manifest refresh type conflicts, missing IDs,
feature flag absent/true/false/future schema and clean read-only assets. Measure
declaration count and registration time. Full Plan 4 remains open until native
adapter and authoring undo gates pass.

## Reviewed corrections (supersede candidate wording above)

- Freeze exactly five names -> seven IDs, excluding inherited `name`. Supplement
  fixtures with reviewed eligibility and kernel source hashes: only KELVINLET
  mu/nu are dynamic; projection, planeSide and nudgeProjection are static.
- Authoring registration must unwind if later addon registration fails too.
  Whole-addon duplicate registration remains unsupported; authoring is idempotent.
- System storage is mandatory: `get` sees custom storage and RNA's `never_create`
  getter can delete malformed fields. Add `ID.system_property_scalar(path_tuple)`
  returning copied `(present, type, value)`. Exact tuple, 1..32 exact UTF-8 keys,
  each 1..63 bytes without NUL. Main-thread, GIL-held GC guard, original ID in
  current Main; linked/read-only reads allowed. Traverse raw system_properties
  without getters/repair/declarations/owner allocation. Absent or GHOST ancestor/
  leaf returns `(False, None, None)`; present non-group ancestor/unsupported leaf
  raises. Support INT/FLOAT/DOUBLE/BOOLEAN and bounded UTF-8 STRING (one MiB).
  Return type names, never borrowed wrappers, IDs, arrays or groups.
- Missing legacy returns `ValueSource(source='LEGACY')` (None, present=False);
  resolver supplies frozen definition.default. Authored default stays present.
  Fallback depends on missing generic value leaf, not missing record. Metadata-
  only generic records still see legacy. Explicit overrides affect one ID only.
- Shared generic root validation treats missing records as empty, but rejects a
  present non-group. This supports flag-first roots without fake value records.
- Tests add static stack/declaration rejection, metadata-only legacy fallback,
  planeSide fanout divergence, raw legacy edits, GHOST defaults, malformed raw
  system data preservation, and flag-first property authoring. Engine execution
  remains disabled pending Plan 6 even for a manifest ID/type/dynamic match.
