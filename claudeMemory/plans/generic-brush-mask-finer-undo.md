# Plan 6 mask gate: exact finer-level undo

Reviewed by independent CLI storage/lifetime and footprint reviewers; findings
in tests/plan6-mask-undo-lifetime-review.md and tests/plan6-mask-undo-footprint-review.md
are incorporated below before implementation.
The new prepared MASK probe reproduces a preexisting bug: edited-level values
undo, while authored finer-level mask values retain the prolonged stroke delta.
Evidence: `tests/plan6-mask-finer-probe-results.json`, failures in maskFinerUndo.
This blocks the prepared mask completion gate; the staged package remains the
previously passed non-accumulation build.

## Cause

`grid_domain.cc::flushMaskToStore(verts)` prolongates the coarse edit upward
and refreshes resident finer mask mirrors. GridStrokeLog captures/swaps only
edited-level blocks. Invalidating finer domains cannot restore their authored
store values. Arithmetic inverse propagation would introduce float-rounding
drift and cannot restore newly allocated versus absent finer-level storage.

## Fix

1. Add mask-specific finer-level capture to GridStrokeLog, invoked from the shared
   gridsFoldStroke immediately before mask flush, alongside coarse block capture.
   Capture all occurrence grids selected for that fold: prolongateChannelEditUp
   never crosses grids, and occurrence enumeration already includes seam replicas.
2. For each previously allocated finer mask level, snapshot only these grids'
   blocks, plus the level's debt bit. Store channel name, exact FLOAT/one-component/
   vertex metadata and level; resolve current names on seek. Evicted levels may
   rehydrate for capture, as the subsequent edit already requires. Do not copy
   unrelated grids or other channels.
3. For an unallocated finer level, preserve an empty owning LevelData snapshot
   without allocating/seeding or changing the live store. Undo/redo swap that
   owning level state with live storage, restoring absence exactly and retaining
   the stroke-created allocation only for redo. This avoids materializing a full
   zero level at capture. Add narrow friendship from GridsStore to GridStrokeLog
   for this internal owning swap; do not expose a public mutable storage API.
4. Keep finer snapshots separate from existing coarse stamps/blocks. Capture each
   (channel, level, grid) once; no quadratic duplicate scans across grid count.
   Shared fold currently captures once, but repeated calls in the same open step
   must preserve the earliest values. For originally absent levels, retain the
   original empty snapshot and let its whole-state swap cover later edits.
5. Seek swaps coarse blocks, then finer mask snapshots, then refreshes/invalidates
   cached domains in the existing order. Refresh surviving finer mask mirrors
   from restored storage without creating formerly absent levels; existing
   invalidateAbove can drop finer domains. Preserve edited-level attribute debt
   and restore each captured finer level's debt. Channel removal/reindexing must
   not redirect bytes; reject/skip incompatible metadata or removed levels using
   the log's existing safe-skip convention.
6. Include finer held blocks and owning redo allocations/compressed buffers in
   bytes() so undo trimming remains honest. No file schema or public C ABI change.

## Gate

- Reproducing edited+finer nonuniform-mask fixture must undo/redo exactly, including
  store serialization, live/rebuilt mirrors and per-level debt.
- Cover finer resident/evicted/unallocated levels, multiple finer levels, seams,
  partial grid footprints, repeated capture in one step and repeated undo/redo.
- Channel removal/reindex/re-add and dropped levels must not overwrite another
  channel or access freed storage. Capture scales with touched grids on allocated
  levels; an absent finer level adds no allocated float buffer until the edit.
- Existing GridStrokeLog, multires attributes and prepared-mask/17-suite gates
  pass. Finish the prepared mask acceptance matrix before staging/marking complete.

## Review corrections (implementation requirements)

- Assign runtime-only, process-unique incarnation tokens to each channel and each
  channel level at construction (including deserialization). Preserve tokens on
  moves/reindexing, but recreate them on remove/re-add and drop/recreate. Snapshot
  name plus both tokens. Validate identity for coarse blocks, finer blocks/owning
  swaps, leaf-mask restoration and edited/finer debt. A same-name replacement
  must retain its values and debt. Tokens do not change the file format or C ABI.
- Replace name-only edited-level debt sets with identity-qualified boolean
  records. Apply only matching records; never clear every current channel.
  Capture a newly created channel's pre-write debt when it first joins a step.
- Ensure the mask channel exists before shared-fold capture, without allocating
  finer levels. Leaf-mask capture also establishes that identity. Undo may retain
  this neutral channel; exact serialized-store comparisons require a preexisting
  channel. Finer allocation absence must still restore exactly.
- An absent-level snapshot copies its actual empty LevelData metadata, including
  debt; its owning swap is the sole debt authority. Drop finer cached domains
  before any read could allocate restored absent storage.
- Use indexed channel/grid membership for coarse capture at every channel index,
  and per-finer-level grid membership. The scaling gate measures incremental
  snapshot payload and dedup work, not existing whole-domain fold bookkeeping.
- Extend tests to channel/level replacement, channel reindexing, index >=32,
  overlapping capture, zero delta, absent level with debt, allocated/absent/
  allocated chains, and history cleanup (redo truncation, attach, eviction).
  Measure held payload directionally through capture/undo/redo and cleanup;
  count chunks and compressed buffers without charging rawFloats twice.

Implementation review follow-up: mask leaf capture must distinguish incarnations
within an open step too. Index channel membership as well as grid membership,
and release capture-only indexes at step close. Preserve the existing bytes()
payload metric (used by parity fixtures), document that scope and add a separate
retainedBytes() estimate for undo trimming that includes snapshot records and
identity strings. Exact allocator capacity is outside that estimate. Test cleanup
directly from an undone state holding newly allocated/compressed storage, rather
than after replacement has destroyed it. Make mask mirror synchronization read
an unallocated level as logical zero without allocating it; invalidate finer
domains before restoring their storage. Exercise actual fold propagation through
mixed allocated/absent levels and cached-before-channel fine domains.

The follow-up review also identified existing leaf/seek grouping scans; use
indexed membership/grouping there. Keep finer-only transactions in endStep.
Blender receives a fixed memory charge at push through GridStroke_undoBytes;
reserve the uncompressed mask payload of a stroke-created finer allocation in
retainedBytes before undo moves it into history. This avoids undercharging the
later ownership transfer. Include the C API and undo.py consumer in evidence.

## Completion — 2026-09-18

Implemented and tested under [the mask gate](../tests/plan6-mask-gate.json).
The final tests include the original failing finer-mask fixture, independent
full-grid bilinear oracle, absent and compressed owning state, live mirror
replacement during an open step, cached-before-channel/rebuilt absent mirrors,
debt, history truncation/attachment/eviction, 40-channel overlapping indexed
capture, exact payload growth and finer-only transaction lifetime. Existing
grid-stroke regressions and the full 17-suite matrix pass. See the consolidated
[evidence and review dispositions](../codebase/generic-brush-plan6-evidence.md#prepared-mask-and-finer-undo-gate--2026-09-18).
