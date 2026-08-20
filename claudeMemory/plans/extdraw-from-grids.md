# External draw from grids — v2 LANDED 2026-08-06; lazy slot landed since

**Status: v2 implemented and landed 2026-08-06** (engine `1d6f58e`, addon
`b62be69`) after the pressure test below killed v1; steps (1) writeback
authority (engine `219f5af`) and (2) the provider are done, with (3) mask
authority partially handled (refresh_grids_mask), (4) provider flips done
(two-way freeing: grids buffers free on flip; slot GpuData still persists).
**(5) the lazy slot has since landed** (2026-08-19 status): a grids-native
session skips the materialized slot entirely — `activeMesh`/`activeTree` are
null while it is lazy and `convert.ensure_multires_slot` builds one on first
mesh-path need. See the results doc's provider-v2 addendum for measurements.

**Original verdict (kept for the record):** The v1 plan (this file's git history)
was pressure-tested by three adversarial reviews (staleness / host-ABI /
engine-perf lenses) before implementation, per the repo's design convention.
All three returned kills. This file records the verdict, the findings worth
keeping, and the prerequisites any v2 must satisfy. No code was written.

## Why it was killed

### 1. The per-stroke perf case was stale (cost/benefit kill)

The v1 rationale ("removes the 30 Hz `SpatialTree::update` walk") re-opened a
hypothesis this repo had **already disproven**: the W3 addendum of
[research/grids-native-brush-path-results.md](../research/grids-native-brush-path-results.md)
measured `tree.update(gpu)` at 0.4–0.5 ms/call (~4 ms/stroke). What the
provider actually removes is that plus the mirror leg inside the 34 ms dab
cost — **≤5–8 ms of the ~105 ms stroke**. The results doc's own ranked list
already put blob demotion (17–25 ms/stroke + most of undo memory) first.
The provider's real prize is the §4 lazy-slot **enter** win and the memory/
architecture cleanup — it should be scoped and justified as that, not as a
stroke-perf item.

### 2. The slot-staleness invariant sits at the wrong altitude (correctness kill)

v1 turned off the ride-along mirror and tracked "slot vs store+domain: who is
ahead" in Python (`session.slot_stale`), gating `Multires_writeback`. That is
unenforceable:

- `Multires::writeback()` is an engine-internal side effect of
  `setActiveLevel` (multires.cc:1604), `addLevel`/`removeTopLevel`
  (:1144/:1175), and `Multires_levelPositionsOut` → `setActiveLevel`
  (subdiv_c_api.cc:134). None are spelled "writeback" addon-side; two fire
  from a **depsgraph handler** (level sliders), one from the fork's save
  flush (`mt->flush` from `ED_editors_flush_edits`).
- Writeback diffs the slot against `posCache_[level-1].pos` — **the array the
  domain edits in place** (grid_domain.cc:39, multires.cc:844). A stale slot
  therefore looks like a legitimate edit of every grids-moved vert: writeback
  folds the *pre-stroke* positions into the store as new truth and drops the
  domain holding the real data. Silent, unrecoverable, and it persists into
  the .blend on save below top level (`_flush_multires`'s level dance).
  Today's mirror is the only reason those calls are safe (`nChanged == 0`
  early-out, multires.cc:865).
- The undo store-heal (undo.py:314) is genuinely conflicted under any
  addon-side rule: skip → meshlog undo resurrected by the next domain
  rebuild; mirror-then-run → erases the seek; run stale → destroys strokes.

**The fix altitude:** `Multires` must own the authority bit. `writeback()`
refuses (or folds **from the domain**) when a live domain at that level is
ahead; `setActiveLevel`/`addLevel`/`removeTopLevel` route through it. Then
the addon's flag becomes a cache hint, and findings A/B/C of the staleness
review collapse. This engine work is a prerequisite for §4 lazy-slot
regardless of the draw provider.

### 3. The draw path can trigger multi-second engine work (perf kill)

`update()` re-fetching `gridDomain(level)` after fold points = a 2.6 s domain
rebuild inside a draw refresh (the codebase already fences exactly this for
raycast via `hasGridDomain`, grid_stroke_c_api.cc:237). v2 rule: **a draw
poll must never build a domain** — the node buffers are engine-owned copies
that survive domain drops; report them with NONE flags until an addon-driven
update with a live domain refills.

### 4. Draw-node granularity inverts at deep stacks (perf kill)

A GridTree leaf has a hard floor of one cage face (grid_tree.cc:86–119 always
consumes the seed face), so tris/leaf = 1024 (L4) / 2048 (L5) / **8192 (L6) /
32768 (L7)**. "Aggregate leaves to 2048 tris" is unreachable at the classic
multires shape (coarse cage, deep level) — one touched vert refills 0.7–2.8 MB.
v2 needs **sub-leaf draw nodes** (row-bands within a grid, id-packed
`0x40000000 | leaf<<k | band`), with geometric dirty marking. The 1M/L4 bench
cannot see this; any v2 bench must include a ≤500-face cage at level 6.

## Findings worth keeping (fix-shaped, from the ABI/engine lenses)

- **Dirty closure:** draw nodes render seam-replicated tris whose corners are
  verts owned by *neighboring* leaves; `strokeTouchedLeaves_` (owned-verts,
  first-touch-per-stroke, grid_executor.h:729) is the wrong accumulator twice
  over — mid-stroke drains would freeze leaves, and boundaries would crack.
  Mark geometrically per dab (sphere vs node AABB — the `dabLeaves_` query
  logic) and per undo swap (leaf AABB overlap), drained per tick.
- **No generation counter exists on Multires** — pointer-equality re-attach
  detection is an ABA bug (free-then-alloc same block). Add `domainGen_`
  bumped in `dropDomains`/`gridDomain`; fix `GridStroke_sync`'s pointer
  compare while there.
- **Host cache survival:** `external_draw_cache_free` has no callers in the
  fork; deterministic grids ids + fixed verts_num would resurrect session-1
  batches on re-enter. Every node must be **born TOPOLOGY-dirty**; never
  report 0 nodes while registered (host's prune is skipped on the 0-node
  early return, draw_external.cc:431).
- **Provider flip cost:** flipping to the slot tree on a mesh-path tool
  builds the full ~312 MB slot GpuData cold, synchronously, and it never
  frees — the v1 memory claim inverted after one mask gesture. v2 must free
  the inactive side's buffers on flip (both directions).
- **Regressions v1 hid:** color/UV viewport display would silently disappear
  on multires (host gates on `attrs[0]/[1]` non-null; grids store has no
  color/uv channels); mask brush is mesh-path (slot column) while draw-mask
  would come from the domain → three-way divergence, with the grids stroke's
  `flushMaskToStore` then destroying the painted mask in the store. Mask
  authority must be unified (domain-first mask writes, or a slot→domain sync
  trigger on mask-column edits) before the provider ships.
- **Slot tree bounds:** today healed once per frame by the provider's
  `SpatialTree::update`; with that call gone, `ensure_multires_slot` must
  also `updateQueries()` or the first mesh-path raycast after a big grids
  stroke works off pre-stroke AABBs.
- **Misc contract:** assert `SpatialNode::id < 0x40000000` at the c-api;
  never emit zero-vert nodes; size the attr block to a hard-coded 4 with the
  shared-scratch `ensure_capacity` pattern; `GridStroke_end` must flush
  deferred normals; `GridStroke_mirrorSlot` must sync the domain first and
  fail loudly on a non-resident slot; `_rebind_multires_views`' pointer
  early-return skips re-registration when a level switch lands on an
  already-materialized slot (draws the old level).
- Pre-existing, out of scope, worth fork follow-ups: memfile undo orphans the
  per-object GPU cache (~200 MB/step at this scale) because the host cache is
  keyed by `Object*` while the registry key (`session_uid`) survives;
  `material_index` hard-coded 0 collapses EEVEE's per-material path; EEVEE
  culling uses base-cage bounds.

## v2 shape (when picked up)

Order of work: (1) Multires-owned authority (`writeback` refuses/folds-from-
domain + `domainGen_`) — standalone engine PR, de-risks today's mirror path
too; (2) sub-leaf draw partition + geometric dirty marking + never-build-on-
poll provider, benched on BOTH shapes (1M/L4 and 500-face/L6); (3) mask
authority unification; (4) addon registration flips with two-way buffer
freeing; (5) §4 lazy slot, which is the actual payoff and now has its
prerequisites named. Re-rank against blob demotion at each step — as of
2026-08-06 blob demotion is unambiguously the better next perf item.
