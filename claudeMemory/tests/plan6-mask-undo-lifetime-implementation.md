**Do not accept the lifetime gate yet.** The packet exposes one concrete identity defect and significant gaps in the claimed lifetime acceptance coverage. This is a source-only review; no tests were run.

1. **Blocker: leaf-mask dedup survives channel replacement within an open step.**  
   `captureLeaf()` returns when the leaf already has a mask snapshot, without checking its current channel/level identity (`grid_stroke_log.cc:169–177`). Identity is established only when `hasMask` is false (`195–201`). Coarse and finer capture, however, distinguish replacement incarnations (`85–114`, `132–149`).

   Concrete sequence: capture and edit mask channel A; replace it with B while the step remains open; synchronize B’s domain mask, capture the same leaf, and edit B. B’s store blocks can be captured correctly, but its leaf snapshot is suppressed. Undo restores B’s store while skipping the leaf snapshot belonging to A (`269–272`), leaving B’s edited mask mirror inconsistent with storage.

   **Minimal correction:** qualify mask first-touch membership by channel and level incarnation, independently of position capture. Preserve the earliest mask values for each captured incarnation. Add an open-step replacement test checking both store values and the edited-domain mask after undo/redo. Existing replacement tests operate only after `endStep()` (`test_brush_prepared_execution.cc:1490–1518`).

2. **Acceptance blocker: the claimed owning-allocation cleanup test does not exercise owning-allocation cleanup.**  
   The comment at `test_brush_prepared_execution.cc:1519` says redo truncation occurs while the snapshot owns the absent-level allocation. In fact:
   - The preceding redo swaps that allocation back into live storage (`1507`; swap at `grid_stroke_log.cc:302–303`).
   - Removing the channel destroys that live allocation (`1508`; `grids.h:295–307`).
   - Undo against the replacement skips the old snapshot (`1515`; `grid_stroke_log.cc:297–299`).

   Consequently, truncation destroys an **empty** owning snapshot. `attach(nullptr)` also runs after history has already been emptied (`1520–1522`, `1559–1561`).

   **Minimal correction:** undo an absent-level stroke, assert the log now holds the allocation, then separately test redo truncation and attaching another/null domain directly from that state. Include eviction before undo so cleanup covers a held compressed allocation. These are explicit requirements in the plan (`85–89`), not optional additions.

3. **Acceptance blocker: cached-domain safety and absence preservation remain unproved.**  
   Owning storage is swapped at `grid_stroke_log.cc:301–303`, but finer domains are invalidated only at `357`, after draw/sample-refresh operations (`320–353`). The packet omits the implementations needed to establish whether those intervening operations access finer caches. Likewise, stroke flush unconditionally calls `refreshFinerMaskMirrors()` (`grid_domain.cc:342`), while the supplied mask synchronization reads through allocating `elem()` (`258–270`; `grids.h:394–397`).

   This does **not** establish a use-after-free, but it leaves the plan’s explicit “drop finer cached domains before any read could allocate restored absent storage” requirement unverified (`plan:79–81`). The absence/zero-delta fixture creates only the edited domain (`test_brush_prepared_execution.cc:1530–1546`); the resident-finer fixture begins with allocated finer masks (`1408–1414`).

   **Minimal correction:** add a finer domain cached *before the mask channel exists*, then exercise zero/nonzero folds and repeated seeks. Check allocation/debt immediately after each seek, before rebuilding any domain. Supply the invalidation and refresh implementations for review; move invalidation earlier if their reads require it.

Acceptance refinements:

- Assert edited-domain masks and rebuilt finer masks after **both** undo and redo. The prepared regression checks finer mirrors only after undo (`1432–1438`).
- Check debt explicitly across every captured level; the storage fixture explicitly verifies only level 3’s undo debt (`1493–1499`).
- Exercise a dropped level without recreation, leaf restoration after channel reindexing, and deserialization identity renewal. Existing storage tests capture no leaves, and the supplied code does not include deserialization.

The empty-state snapshot does preserve its original incarnation and debt (`grid_stroke_log.cc:145–149`), and the whole-state swap correctly avoids a competing separate debt swap (`302–311`). Those parts have no demonstrated defect in this packet.