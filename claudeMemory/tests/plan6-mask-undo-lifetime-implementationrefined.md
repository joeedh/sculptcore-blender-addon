**The packet does not establish a production lifetime blocker in the shared-fold path. It does expose one concrete transaction-lifetime defect and several missing acceptance checks. I would not mark the lifetime gate complete.** This is source-only review; no tests were run.

1. **Concrete defect: closing a finer-only transaction silently destroys its undo state.**  
   `captureFinerMask()` can create block snapshots or an owning absent-level snapshot, but `endStep()` discards the step whenever both `leaves` and coarse `blocks` are empty. It never considers `finerMask`. A caller can capture finer storage, change it, close the step, and lose both undo eligibility and the retained snapshot. See `grid_stroke_log.cc:105–148, 204–213`.

   Minimal correction: include `s.finerMask.isEmpty()` in the empty-step predicate, or explicitly prohibit finer-only transactions in the API and enforce that contract. Add a direct capture/mutate/end/undo/redo test, including an originally absent level with debt.

   **Classification:** a definite public-API defect, but **not a demonstrated blocker for the current shared fold**, which always captures coarse blocks first (`grid_executor.h:139–145`).

2. **Acceptance gap: restored absence is never tested through rebuilding and reading a finer domain.**  
   The zero-delta fixture caches a fine domain before channel creation and checks allocation after undo, but does not reacquire that domain after undo. Thus it does not establish that rebuilding and reading the restored absent level preserves absence. See `test_brush_prepared_execution.cc:1533–1550`.

   This matters because undo deliberately destroys finer domains before swapping storage (`grid_stroke_log.cc:288–305`; `multires.cc:47–55`). The nonallocating behavior in `syncMaskFromStore()` is promising, but the packet does not include domain construction (`grid_domain.cc:258–270`).

   Minimal acceptance addition: after undo, reacquire each absent finer domain, assert every mask value is zero, and assert allocation and debt remain unchanged **after** construction and synchronization. After redo, reacquire and compare against the post-stroke mirror.

   **Classification:** acceptance refinement, not evidence that rebuilding currently allocates.

3. **Acceptance gap: compressed owning state is destroyed, but never restored by redo.**  
   The compressed case is exclusively `cleanup == 1`: level 3 is evicted, undo transfers its compressed allocation into history, then `attach(nullptr)` destroys that history. The redo-after-history-movement case is `cleanup == 2`, which does not evict the level. See `test_brush_prepared_execution.cc:1625–1650`.

   Consequently, compressed ownership cleanup has coverage, but compressed ownership **swap-back and subsequent rehydration** do not.

   Minimal acceptance addition: evict → undo → redo → read/rebuild finer domain → compare values and debt → undo again → truncate or detach. Exercise this after `dropOldest()` moves the remaining owning snapshot too.

   **Classification:** acceptance refinement.

4. **Acceptance gap: the mixed-level fold fixture does not validate edited-domain mask undo.**  
   It directly changes `d->mask[0]`, folds, and checks serialized store restoration without calling `captureLeaf()` or checking the edited mirror afterward (`test_brush_prepared_execution.cc:1599–1601, 1629–1636`). The visible edited-mask restoration path depends on a captured `LeafSnap` (`grid_stroke_log.cc:253–265`).

   This fixture therefore cannot establish the plan’s live-mirror acceptance claim. The prepared regression checks a rebuilt finer mirror after undo, but checks only store serialization after redo (`test_brush_prepared_execution.cc:1432–1438`).

   Minimal acceptance addition: use the intended leaf-capture lifecycle in the mixed-level fixture; assert edited and finer mirrors after stroke, undo, and redo. Reacquire finer pointers after every seek because invalidation deletes them.

   **Classification:** acceptance refinement; the packet does not establish that folding alone promises leaf capture.

5. **Acceptance gap: identity construction and debt restoration are only partially demonstrated.**  
   Name-plus-channel/level-token resolution protects captured storage and mask leaves (`grid_stroke_log.cc:63–74, 261–269, 289–304`). However, the required deserialization identity behavior cannot be audited: `read()` is declared, but its implementation is absent (`grids.h:424–425`). Tests also exercise finer-level replacement, not edited-level replacement or deserialization with retained history.

   Minimal correction to acceptance: specify which operations invalidate the bound log versus support safe skipping. Add explicit debt assertions before/after both seek directions; serialized equality cannot substitute for debt checks without the serializer implementation.

   **Classification:** missing evidence and contract clarification, not proven token corruption.

The owning-swap design itself survives this review: it copies actual empty metadata, swaps allocation and debt together, and deletes finer cached domains before restoring absence (`grid_stroke_log.cc:133–138, 288–305`). I would retain that design and tighten the transaction contract and acceptance coverage above.