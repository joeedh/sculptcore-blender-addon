**Verdict: revise before implementation.** The configuration-keyed cache is viable, but the plan leaves several observable semantics unresolved and has two concrete hazards if it reuses the supplied implementation unchanged. This review covers the semantics lens using only the supplied text; no tools were used.

1. **P1 — “Immediately before its kernel” needs a precise insertion point inside `exec()`.**

   Applying stage values and calling the hook immediately before `exec()` is insufficient for nonaccumulation. `exec()` resets and initializes `ctx.dispVec`, `ctx.dispGen` and `ctx.strokeGen` internally. A hook outside it can see null or previous-command state. The existing prepared cavity pass deliberately runs after that setup and tests support using `co - disp` only for the current generation. See [brush_executor.h:929–1035](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.h:929) and [brush_executor.h:1049–1067](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.h:1049).

   **Minimal correction:** specify a prepared-only command preparation phase after current-command base initialization, before the parallel kernel loop. Use base coordinates solely for contact selection; feed live `m->v.co` and `m->v.no` to the difference-of-smooths calculation. Wire both standalone and program prepared execution through that phase. Current program stage application is at [brush_executor.cc:370–376](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:370).

2. **P1 — Prepared first contact deliberately differs from raw first contact; define that difference and the zero-strength rule.**

   Raw ENHANCE captures every unique vertex in selected leaves, without testing radius, strength, masks or pressure. Its hook also precedes common-property evaluation. See [brush_hooks.cc:18–24](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_hooks.cc:18), [brush_hooks.cc:37–44](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_hooks.cc:37) and [brush_executor.h:1824–1834](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.h:1824).

   Thus “effective support” cannot remain ambiguous between geometric inclusion and nonzero final influence. Prepared cavity uses geometric inclusion; its tests intentionally capture contacts at zero strength. See [prepared_cavity.h:14–27](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/prepared_cavity.h:14) and [prepared_cavity_cases.h:99–133](C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_cavity_cases.h:99).

   **Minimal correction:** explicitly adopt geometric contact: positive evaluated radius and the stage’s support predicate, regardless of strength, painted mask, texture or automasking. Zero radius and misses claim nothing; zero strength inside support still claims. Pressure on strength changes application, not cached displacement. Test zero-strength contact → intervening DRAW → positive-strength revisit, separately from zero-radius → DRAW → first positive-radius contact. Raw parity requires matching **capture times and captured geometry**, not merely overlapping regions.

3. **P1 — Configuration identity is not command identity; lock down intentional sharing.**

   The proposed key shares first-contact history between two commands with identical normalized settings. In `[ENHANCE A, DRAW, ENHANCE A]`, the second ENHANCE reuses the first vector at previously claimed vertices, despite intervening geometry changes. With a distinct configuration B, it computes from the later geometry. That follows directly from [plan:30–37](C:/dev/blender/sculptcore-blender-addon/claudeMemory/plans/generic-brush-prepared-enhance.md:30), but “independent command values” and “distinct command cache keys” do not establish whether this sharing is intended.

   **Minimal correction:** state that hooks execute independently per command, while identical normalized configurations share contact history across command slots. Add `[A, DRAW, A]`, `[A, DRAW, B]`, and A→B→A revisit tests. Include distinct authored pairs that normalize identically, such as `(0,-1)` and `(1,0)`. If independent per-command histories are actually required, add stable command identity to the key instead.

4. **P1 — Reusing `EnhanceScratch` unchanged introduces wraparound errors and retains unsafe raw-ID sizing.**

   `computeEnhanceDisp()` sizes visit stamps with `m->v.count`, then indexes them using raw vertex IDs and CSR neighbor IDs. The executor explicitly documents that live IDs may exceed the live count after deletions. See [enhance.h:85–118](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/enhance.h:85) and [brush_executor.h:685–698](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.h:685). Disallowing dyntopo during this stroke does not make an already sparse mesh dense.

   The token also increments without handling wraparound. With reusable scratch, a wrapped token can match stale stamps and incorrectly skip neighbors. [enhance.h:85–87](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/enhance.h:85).

   **Minimal correction:** size scratch and active columns by vertex capacity; clear stamps and restart at a nonzero token on wrap. Add a sparse-ID mesh test and a forced-wrap test against fresh scratch. These are required for the proposed reuse, not optional performance work.

5. **P1 — Adding global executor settings does not enforce ENHANCE command membership.**

   Every executor setting is appended to every prepared stage, regardless of its manifest. Override validation then accepts any name present in that stage. Simply adding the two fields therefore admits `enhance_rings` overrides on DRAW and other commands. See [brush_preparation.cc:443–450](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:443) and [brush_preparation.cc:467–473](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:467).

   **Minimal correction:** distinguish global snapshot/restoration coverage from command override eligibility. Reject ENHANCE-specific overrides on non-ENHANCE commands during whole-program preflight. Preserve native-field authority and static-stack rejection. Declaration ranges must admit negative input values that the formula normalizes; the existing preparer rejects out-of-range values before any such normalization. See [brush_preparation.cc:262–266](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:262) and [enhance.h:79–83](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/enhance.h:79).

6. **P1 — Acceptance needs explicit independent temporal and failure oracles.**

   Reusing `computeEnhanceDisp()` to calculate expected vectors would duplicate the implementation’s traversal, normalization and scratch bugs. The supplied cavity tests use their production formula helpers, so copying that test structure is insufficient for the promised independent ENHANCE oracle. See [prepared_cavity_cases.h:124–145](C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_cavity_cases.h:124).

   **Minimal correction:** compute graph-distance neighborhoods independently from a small explicit adjacency fixture, including the center once, and snapshot positions/normals at each expected configuration’s first contact. Specify whether “live normal” means the current stored normal or a normal refreshed after preceding commands; the formula reads stored `m->v.no`, and the supplied code does not establish generated `execPost` normal-refresh behavior. See [enhance.h:92–100](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/enhance.h:92) and [brush_executor.h:1149](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.h:1149).

   For a malformed late command and `validateOnly`, assert unchanged geometry, topology state, TEMP attributes, cache entries/active values, undo capture and working settings—not just unchanged evaluation counts. Preserve the existing whole-program validation barrier before hooks or execution at [brush_executor.cc:278–315](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:278).

**Optional improvements:** expose configuration/contact/evaluation counters for diagnostics, and add a leaf-partition invariance test to detect accidental return to raw leaf-wide capture. Neither requires changing the preceding unbounded numerical design.