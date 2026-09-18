**Hold the footprint gate.** The packet shows two implementation gaps and missing mandatory acceptance coverage. This is a source-only review; no tests were run. Citations refer to supplied file lines.

1. **Blocker — coarse channel membership is still a linear search.**  
   `captureGridBlock()` searches `s.captured` for every grid, and searches pre-debt records when adding a channel (`grid_stroke_log.cc:85–114`). Capturing G grids across C channels therefore costs O(G·C²) channel-membership work, despite grid membership itself using a set. This does not satisfy the explicit requirement for **indexed channel/grid membership** (`generic-brush-mask-finer-undo.md:82–84`). The index ≥32 test captures only one channel, so it cannot expose this (`test_brush_prepared_execution.cc:1454–1478`).

   **Minimal correction:** index captured channels by level incarnation; retain the per-channel grid set. Add an operation-count gate varying both captured channels and grids, including overlapping captures.

2. **Blocker — `bytes()` measures float/compressed payload, not the retained undo footprint it advertises.**  
   It counts leaf arrays, block arrays, owned chunks and compressed bytes (`grid_stroke_log.cc:399–419`), but omits the newly retained coarse and finer membership sets, identity strings, debt records and snapshot containers (`grid_stroke_log.h:95–138`). The sets remain attached to closed history steps. Consequently, memory retained for deduplication is invisible to undo trimming. This conflicts with the “total captured bytes” API description and honest-trimming requirement (`grid_stroke_log.h:91–92`; plan:49–50).

   **Minimal correction:** discard capture-only membership at step closure, and account for remaining owned allocations in the limiter’s footprint metric. If `bytes()` intentionally means payload only, name/document that distinction and supply a separate retained-memory measure. Keep the existing avoidance of double-counting `rawFloats`.

3. **Acceptance blocker — the mixed-allocation fixture bypasses the propagation whose footprint it claims to test.**  
   `maskUndoStorage()` manually changes two grids at every level (`test_brush_prepared_execution.cc:1481–1486`). It never exercises the critical combination:
   
   - absent levels seed **all grids** from the post-edit level below (`grids.cc:420–428`, `128–143`);
   - allocated levels receive delta additions only in touched grids (`grids.cc:431–459`);
   - subsequent allocated levels must still receive the delta across an absent intermediate level.

   Thus its allocated/absent/allocated chain tests snapshot swapping, not actual fold coverage or delta propagation. The prepared regression exercises only one allocated finer level (`test_brush_prepared_execution.cc:1407–1438`).

   **Minimal correction:** run the shared fold on a localized seam edit through an allocated/absent/allocated chain. Independently check post-edit interpolation, untouched allocated-grid sentinels, whole-level seeding, exact undo/redo and absence restoration. Snapshot round trips alone cannot detect an incorrect forward edit that is faithfully replayed.

4. **Acceptance blocker — the claimed cleanup and accounting gates do not reach the necessary states.**  
   The “truncate … while it owns the absent-level allocation” comment is inaccurate: the preceding redo returns that allocation to live storage; channel replacement then makes undo skip the finer snapshot (`test_brush_prepared_execution.cc:1498–1519`; `grid_stroke_log.cc:296–303`). Truncation therefore does not test releasing a held redo allocation. Both `attach(nullptr)` calls follow history cleanup, so neither tests attachment cleanup with populated history (`test_brush_prepared_execution.cc:1521–1522`, `1559–1561`).

   Nor do the directional byte assertions establish exact accounting: `bytes() > capturedBytes` would pass with substantial undercounting (`test_brush_prepared_execution.cc:1497`). Evicting the already allocated level before capture exercises rehydration into block snapshots, not a compressed owning snapshot.

   **Minimal correction:** undo an absent-level edit, verify the expected whole-level payload is held, then separately test redo truncation and attachment cleanup. Evict a stroke-created level before undo to exercise compressed owning storage; assert its byte contribution exactly. Add a snapshot/dedup scaling gate. These are already required by plan:83–89.

**Acceptance refinements, rather than additional demonstrated correctness blockers:**

- Use partially overlapping capture sets, such as `{0,1}` then `{1,2}` after intervening writes. Repeating the identical set only proves duplicate suppression (`test_brush_prepared_execution.cc:1477–1489`).
- Extend zero-delta coverage to an allocated, evicted finer level. Capture currently rehydrates and copies its blocks before flush discovers there are no deltas (`grid_stroke_log.cc:152–156`; `grid_domain.cc:323–340`; `grids.cc:359–360`). That is avoidable work, not demonstrated undo corruption.
- Require recorded results for the prepared-mask matrix and existing suites before completion. The packet supplies test bodies and invocation, not passing evidence for plan:61–62.

The core coverage choice is defensible: occurrence-grid capture covers allocated-level writes, and whole-level ownership covers absent-level seeding. The blockers above concern the implementation’s indexing/accounting promises and the missing evidence needed to accept that design.