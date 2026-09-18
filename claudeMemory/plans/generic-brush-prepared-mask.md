# Plan 6: prepared mask execution

Reviewed by independent admission/preflight and storage/undo CLI reviewers on
2026-09-18; scope/acceptance corrections below resolve their findings. Mesh MASK
already fits the prepared scalar path; grids currently reject `writesMask`.
This slice admits the existing built-in mask storage policy without enabling
general attribute mirrors, face kernels, layer writes or host-stage commands.

## Implementation

1. Keep every existing capability restriction except the grid writesMask blanket
   rejection. Before admitting a mask-writing command, require an existing named
   mask channel (if any) to be one FLOAT component in the vertex domain. Do not create it
   during supports queries, validateOnly or rejected program preflight.
2. Ensure the mask channel inside execStage for every accepted nonempty mask
   stage, before capture. `ensureMaskChannel()` is an idempotent lookup. Its old
   first-dab-only condition fails after an earlier zero/missed dab or after a
   preceding non-mask dab consumed first-of-step state. Retain normal raw behavior
   except this correctness fix. Rejected calls, zero-radius mask stages and calls
   with no selected program leaves must not create storage. A positive-radius
   stage in an accepted broad-phase union may create a neutral channel and capture
   leaves even if its own influence/strength is zero. This preserves existing
   broad-phase capture semantics; it does not promise write-sensitive allocation.
   Accepted zero-radius/missed calls retain their existing counters/first-dab
   bookkeeping. Only rejected preflight preserves all state except diagnostics.
3. Use the existing GridCapturePolicy mask snapshots, moved-vertex union and
   stroke-end grid-block capture/flush. Prepared scalar evaluation and maximum
   command-radius selection already occur before this stage. Programs retain
   full preflight and working-state restoration. No native API or schema change.
4. Preserve existing undo semantics: undo restores mask values and store blocks;
   a lazily created neutral mask channel may remain, as in the current raw path.
   Test channel presence independently of mask data and never claim byte-identical
   whole-store serialization across first-ever channel creation.
5. Apply the same malformed-channel check in raw preflight as well. Automatic
   policy can fall back after supportsResolved rejects; raw fallback must not
   bypass validation and write a malformed channel. This rejects corrupt storage
   before mutation without changing valid raw strokes.

## Acceptance

- Multi-leaf mesh/grid MASK and DRAW+MASK prepared versus independent raw
  reference; inherited/explicit-empty strength stacks, varying pressure/tilt,
  larger growing secondary radius, inversion, zero and absent input.
- Exact mask, geometry and preexisting store-block undo/redo; new channel created
  only after accepted broad-phase region hit. Zero-radius/miss first dab then real hit; non-mask first
  dab then mask. Later invalid command leaves channel inventory, masks, positions,
  undo state, counters and first-dab state unchanged before any creation.
  Exercise DRAW→MASK and MASK→DRAW, a large DRAW with ineffective smaller MASK,
  zero effective strength, and accepted empty-call bookkeeping separately.
  Test preexisting nonuniform mask values at edited and finer resident levels,
  their store blocks, domain mirrors and attribute debt through undo/redo.
- Reject malformed existing mask channel shape/domain before capture/publication.
  Do not relax other attribute/mirror/face/layer/host restrictions.
  Check supports, validateOnly, standalone, later program entries and raw/automatic
  fallback, including zero-radius commands. Snapshot after beginStep since opening
  a step itself discards redo history.
- Dispatcher native/Python builds; applicable 17-suite regression, actual DLL
  input batches, safe headed Alt-mask mesh/grid Python/batch queued/delayed matrix.
  Require prepared calls and score actual mask values (not geometry movement).
  Stage matching package and record provenance smoke plus completion evidence.

## Completion — 2026-09-18

The [verified gate](../tests/plan6-mask-gate.json) passes 17 native suites, 12 exact
installed-DLL mask comparisons, 42 preflight checks, eight installed headed cases
with 124 prepared calls and package provenance smoke. The gate required the
separately reviewed [finer-level undo fix](generic-brush-mask-finer-undo.md).
See [evidence](../codebase/generic-brush-plan6-evidence.md#prepared-mask-and-finer-undo-gate--2026-09-18).
