**Lifetime verdict: block pending three corrections.** This review uses only the supplied packet; it does not assess footprint.

1. **Name + metadata + level number do not establish identity.** Remove `"mask"`, re-add it with identical metadata, then seek: the planned lookup accepts the replacement and writes old snapshots into it. Likewise, dropping and recreating a finer level defeats a level-number/range check. An owning swap can replace the replacement level’s entire allocation. Channel removal actually destroys storage and shifts channels; no incarnation identifier appears in the supplied `Channel` or `LevelData`.
   
   **Minimal correction:** use runtime channel/level incarnation tokens, or invalidate the affected history on destructive identity changes. Preserve history across mere channel reindexing. Apply the identity check to debt restoration too.
   
   Citations: plan lines 25–26, 44–46, 56–57; `grids.h:295–307, 457–479`; `grid_stroke_log.cc:212–224`.

2. **The existing coarse “safe-skip” convention is insufficient for the promised compatibility gate.** Fixing only finer snapshots leaves coarse restoration accepting any same-name channel with the same float count. For example, replacing FLOAT/one-component/vertex mask with INT/one-component/vertex passes the size check and receives the old mask bytes. Separately, `applyAttrDebt()` resolves names without compatibility checks and clears debt on every current channel, including replacements. Finer guards therefore cannot establish the plan’s seek-wide safety claim.
   
   **Minimal correction:** extend compatibility/incarnation validation to the affected coarse blocks and edited-level debt records. Define how replacement channels’ debt is preserved when their snapshots are skipped.
   
   Citations: plan lines 40–46, 56–57; `grid_stroke_log.cc:175–187, 212–225, 278–299`; `grids.h:259–262`.

3. **A nonexistent mask channel has no specified capture path.** The shared fold looks up `"mask"` before flushing. If absent, existing coarse capture returns immediately; the flush then creates the channel, and nonzero deltas can allocate finer levels by seeding them. The plan specifies snapshots for unallocated *levels*, but does not say how to record those levels when their channel does not yet exist. Consequently, this supported source path can escape finer capture entirely.
   
   **Minimal correction:** explicitly handle missing-channel capture: record the finer levels’ prior absence and bind those records to the channel created by this fold, or establish and enforce an existing-channel precondition before capture. State whether undo also restores channel absence; do not silently claim exact whole-store serialization if the newly created channel remains.
   
   Citations: plan lines 20–31, 52–53; `grid_executor.h:139–143`; `grid_stroke_log.cc:137–142`; `grid_domain.cc:274–284, 310–340`; `grids.cc:411–419`.

**Acceptance refinements, not additional blockers:**

- **“Empty owning snapshot” must preserve the real empty state.** Allocation absence does not imply default metadata or false debt. Preserve `gridsPerChunk`, `rawFloats`, and `downPending`; use ownership-safe moves/swaps. Exercise redo truncation, `attach()`, and history eviction while snapshots own allocations. The nested-vector destruction warning makes these valuable lifetime tests, but does not prove owning swaps themselves are unsafe. Citations: `grids.h:225–232, 302–307, 457–488`; `grid_stroke_log.cc:18–29, 44–50, 304–314`.

- **Absent-safe mirror restoration needs a specific implementation route.** Calling existing `syncMaskFromStore()` after restoring absence recreates storage through `elem()`. Either discard finer domains before any such read or provide an allocation-aware refresh. Test allocation absence *after* cache handling. The plan already requires this; the packet does not supply `invalidateAbove()` or `refreshFinerMaskMirrors()` implementations, so it cannot establish a concrete dangling-pointer defect there. Citations: plan lines 40–43; `grid_domain.cc:258–270`; `grids.cc:461–467`.

- **Give finer debt one restoration authority.** Whole-state swaps already carry `downPending`; a separate debt restore must not overwrite the swapped value with a default or stale value. Include an absent level with debt set, which the public setter permits. Citations: plan lines 25, 44; `grids.h:225–232, 457–469`.