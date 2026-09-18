# Plan 5: curve evaluation and revision-aware caching

Reviewed by two fresh adversarial agents, 2026-09-17. Preserve Plan 4 authoring
and default-off generic consumers. Implement against real APIs; do not count
warm mocks as proof that actual strokes avoid baking or upload.

## Model and sampling

Add a pure response module implementing all ten frozen ResponseCurve presets.
Canonical x is clamped [0,1]; constants and TWO_STEP preserve finite double
parameters. TWO_STEP must remain an analytic descriptor at the engine boundary,
never an interpolated LUT. Continuous generated/custom curves use immutable
float32 tuples at explicit resolution (default 256), with domain/direction and
clamp/hardness configuration in their keys. Invalid/nonfinite output rejects.

Add a 256-table LRU for immutable response data and a bounded lookup from owned
runtime revision/native canonical bytes to content. Cache holds no Blender IDs,
RNA wrappers or engine objects. For owned mappings, validate the current record
key before every lookup; only changed revisions inspect canonical definition or
sample. Native mappings use the fork canonical key at synchronization boundaries.
Cache content uses complete tuple equality, including points, handles, clipping,
extension and other evaluation-affecting settings. Identical immutable samples
can be interned, but fingerprints that only happen to hash equal never alias.
Eviction cannot invalidate immutable tables held by a running stroke.

Provide explicit preset -> CUSTOM selection/reseed through the existing authoring
transaction. First customize seeds 256 vector-handle points from the chosen
preset; preserve a dormant mapping when returning to CUSTOM unless explicitly
reseeded. Native pressure stays native; Scene/non-pressure mappings stay owned.
Discontinuous seeding returns an approximation diagnostic for UI. Build and
validate samples before mutation; grouped rollback covers mapping and metadata.

## Engine transport and upload lifetime

Current DynamicDevice has only LUT/identity response storage despite the Plan 1
analytic step contract. Add a bounded native analytic response tag for CONSTANT
and TWO_STEP, finite double parameters, validation/equality/copy/evaluation, and
an atomic checked whole-stack upload accepting response tags/parameters. Preserve
the existing table APIs by delegating or explicitly switching back to table mode.
Respect FLOAT32/INT32/BOOL final conversion, disabled layers and missing input.
Reuse the existing checked bulk-vector bridge for LUTs, not per-sample ctypes.

Track installed configurations separately per engine Brush wrapper/session and
command configuration. Include actual configurationGeneration plus explicit
consumer epoch in reuse checks; clear/rebuild/external checked writes invalidate
upload state. Do not trust a recycled pointer. Publish memo only after successful
atomic upload. Command override execution remains Plan 6; Plan 5 provides cache
isolation by command key and tests it against real engine brushes.

For existing stroke paths, replace repeated native pressure/falloff/cavity bakes
with the revision/content sample service. Keep native falloff input reversal,
hardness remap, clipping and existing brush feel. Use engine generation for
pressure installation reuse; legacy falloff/cavity upload identity includes
target Brush identity and an explicit lifecycle epoch. Measure actual cold
marshalling and add native bulk falloff/cavity upload only if material. Native
settings remain authoritative; no owned mappings allocate during reads/strokes.
Lifecycle load/undo/unregister clears cache and upload state; owner removal is
validated on access, with no retained owner pointers and bounded dead keys.

## Gates

Independent preset formulas/endpoints, float32 nextafter at both sides of step
threshold including 0/1, actual engine float/int/bool evaluation, invalid atomic
requests preserving data/generation, table<->analytic switching and disabled
layer behavior. Actual Blender owned/native edits, no-op/selection, clipping,
extension, copied owners, undo/load/re-registration and stale references.
Customize/reseed/dormant preservation, native pressure authority, readonly assets
and rollback. Two identical presets share immutable tables without mappings;
LRU and revision/content indices remain bounded across >256 owners/edits.
Profile cold versus warm real headed strokes: unchanged warm strokes produce
zero new bakes/uploads; changed curve causes one update, rebuilt/cleared engine
receives required data. Retain Plan 3 geometry baselines and Plan 4 regression
gates. Stage matching package and record reproducible commands/hashes. Update
Plan 5 tasks only for gates actually passed.

## Accepted review corrections

- No native analytic device response exists. Use TABLE=0, CONSTANT=1, TWO_STEP=2
  with canonical double threshold/low/high triplets. Compare promoted float input
  to the original double threshold before narrowing output to evaluation Real.
  Preserve existing float mixing and widened int/bool arithmetic/fallback.
- Extend valid/equality/copy and both table upload paths. Pending sample uploads
  switch away from analytic mode only on full publication. Atomic vectors add
  kinds and Vector<double> parameters; Common and token-checked Uniform wrappers
  remain authoritative. Vector<double> is already bound by the runtime.
- construct_from_items performs per-element ctypes writes. Use a narrow validated
  primitive-vector helper: empty construction, resize, numpy contiguous assignment
  and deterministic disposal. Double parameters must not pass through float32.
- Brush configuration generation is global, includes scalar writes, and excludes
  raw fields/falloff/cavity setters. Publish combined stack memos after all writes;
  command A/B/A must reinstall. Wrappers lack arbitrary slots and weakrefs; keep
  explicit per-session memo state and identity references.
- Brush/Scene owner.get(name) accesses custom properties, not the bank's system
  namespace. Use visible evaluated owned RNA plus validated revision, never that
  raw access. Native fingerprints take an explicit actual owner/path.
- Prevalidate finite float32 seed coordinates, disable clipping for levels beyond
  [0,1], reacquire point wrappers after each mutation. This gives rollback and one
  undo entry, not one notification. Catch commit failures and attempt cancel while
  valid; stale-context failures remain explicit and fail closed.
- Generic resolutions are 2..65536; legacy fixed tables exactly 256. Bound both
  revision indices and content LRU at 256 entries. Indices hold content keys, not
  evicted tuples; active stroke callers can retain immutable results independently.
- Cache overlap_attenuation separately by native falloff fingerprint and spacing,
  preserving its no-hardness semantics. Include it in warm evaluation counters.
