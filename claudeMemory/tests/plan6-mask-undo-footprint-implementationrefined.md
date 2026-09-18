**Do not close the footprint gate yet.** The packet shows two quadratic deduplication paths and leaves undo-budget integration unverified. This is a source-only review; I have not assumed any test passes.

1. **Blocker: repeated leaf capture scans the entire step.**  
   Once a leaf is stamped, `captureLeaf()` walks every saved leaf to determine whether its position and current mask incarnation were captured (`engine/source/subdiv/grid_stroke_log.cc:159–165`). Capture N distinct leaves, then revisit all N on another dab: that produces Θ(N²) comparisons, even when every revisit immediately returns without saving anything. A growing stroke therefore pays quadratic capture bookkeeping.

   **Minimal correction:** index capture membership by leaf, with separate position membership and mask-level-incarnation membership. Preserve the distinct snapshots needed for replacement within an open step.

   **Required acceptance:** capture many distinct leaves, revisit them in reverse order, and assert linear membership work and unchanged payload. The existing replacement test revisits only leaf 0, so it cannot expose this (`engine/tests/test_brush_prepared_execution.cc:1656–1685`). This matters to the plan’s incremental dedup-work gate (`claudeMemory/plans/generic-brush-mask-finer-undo.md:82–84`).

2. **Blocker: seek deduplication becomes quadratic with multiple authored channels.**  
   `applySwap()` collects one `swappedSession` entry per authored block, then searches all preceding entries by channel name (`engine/source/subdiv/grid_stroke_log.cc:281–285,325–343`).

   Concrete case: N captured blocks for authored channel A followed by N for authored channel B. Every B block searches past all N A entries before finding B’s first entry. That is Θ(N²) name comparisons. A combined stroke with mask and another authored attribute can create this ordering through the shared fold (`engine/source/brush/grid_executor.h:139–154`).

   **Minimal correction:** group swapped grids by resolved channel during the swap, then refresh each group once. This also removes the repeated full-list collection scan.

   **Required acceptance:** undo/redo a partial-footprint step containing two authored channels at increasing grid counts; count grouping work rather than relying on wall-clock timing. The supplied new tests exercise a single captured channel.

3. **Acceptance blocker: honest undo trimming is not demonstrated.**  
   The new `bytes()` correctly includes held finer block payload, owning chunks and compressed bytes, without charging `rawFloats` again (`engine/source/subdiv/grid_stroke_log.cc:392–412`). `retainedBytes()` additionally estimates records and identity strings (`415–440`).

   However, the packet contains **no undo-limiter consumer showing that trimming uses `retainedBytes()`**, although the plan explicitly assigns it that purpose (`claudeMemory/plans/generic-brush-mask-finer-undo.md:91–96`). The tests establish only that the estimate exceeds payload and eventually returns zero (`engine/tests/test_brush_prepared_execution.cc:1637,1652`). They do not establish budget enforcement, including after undo transfers an entire allocation into redo history.

   **Minimal correction:** supply the limiter integration and a budget test covering that ownership transfer. This is missing acceptance evidence, not proof that an unseen caller is wrong.

The affected-grid design itself survives this review. The fold enumerates every touched vertex’s occurrence grids before capture (`engine/source/brush/grid_executor.h:122–145`). Allocated finer levels receive delta writes only within those grids (`engine/source/subdiv/grids.cc:431–459`). Absent finer levels are the important exception: seeding walks **all** grids (`128–143`), but their whole-level snapshots cover that expanded footprint (`engine/source/subdiv/grid_stroke_log.cc:134–137,294–304`). The mixed-chain full-grid oracle is meaningful coverage of this distinction (`engine/tests/test_brush_prepared_execution.cc:1603–1622`).

Additional **acceptance refinements**, rather than demonstrated correctness blockers:

- **Overlapping capture:** the storage test repeats exactly `{0,1}` (`1477–1489`). Add `{0,1}` followed by `{1,2}` after intervening writes; verify earliest values for grid 1 and first-touch values for grid 2.
- **Payload scaling:** asserting unchanged bytes on duplicate capture does not prove proportionality to newly captured grids. Assert exact incremental block bytes across different touched-grid counts, including channel indices below and above 32.
- **Forward mirrors and redo:** check cached finer mirrors immediately after propagation, and rebuilt mirrors after redo. The prepared regression checks rebuilt fine values after undo but only serialization after redo (`1432–1438`).
- **Gate execution:** the tests are called from `main()` (`1691–1695`), but the packet supplies no results for them or the required existing suites/prepared-mask matrix. Keep plan completion conditional on those results (`claudeMemory/plans/generic-brush-mask-finer-undo.md:61–62`).