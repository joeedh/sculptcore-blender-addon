# `collapseEdge`'s `blend` gate — there is no bug to fix

Written 2026-07-30, after the attribute-coverage pressure test filed **E7** as a
live correctness bug ("no vertex attribute is merged on a dyntopo collapse").
**That finding is wrong.** This note records why, what is actually there, and
the one small thing that is genuinely worth doing.

## The claim

`collapseEdge` (`engine/source/mesh/utils/edge_collapse.h:128-135`) declares:

```cpp
collapseEdge(Mesh &m,
             int edge,
             std::optional<litestl::math::float3> merged_co = std::nullopt,
             float blend = 0.0f,
             EdgeCollapseResult *out = nullptr,
             MeshCallbacks *cb = nullptr,
             bool prevent_inversion = false)
```

and gates the attribute merge on `blend` (`:331-337`):

```cpp
if (blend > 0.0f) {
  const litestl::math::float3 *mco = merged_co.has_value() ? &merged_co.value() : nullptr;
  interpAttrs(m.v.attrs, v_keep, v_keep, v_kill, blend, &m, mco);
}
```

Read in isolation this looks damning: `blend` defaults to `0.0f`, so the default
call merges nothing, and every vertex attribute — masks, colours, weights,
sculpt layers — would be nearest-copy-from-`v_keep` across a collapse.

## Why it is wrong

**There is exactly one non-test caller, and it passes both arguments
explicitly.** `dyntopo.h:1031-1043`:

```cpp
math::float3 mid = detail::edgeMid(m, c.edge);
/* No base shift here: collapseEdge already merges `.brush.disp.vec` over
 * both endpoints (blend=0.5), so the derived base `co - disp` lands on
 * the stroke-start surface's own midpoint. ... */
mesh::EdgeCollapseResult res;
if (mesh::collapseEdge(m, c.edge, mid, /*blend=*/0.5f, &res, cb,
                       /*prevent_inversion=*/true))
```

`blend = 0.5f`, `merged_co = mid`. The production dyntopo path merges every
vertex attribute at the midpoint, and the comment above the call shows the
author reasoned about it deliberately — the surrounding base-shift logic depends
on the merge happening.

The full caller inventory (`grep 'collapseEdge\s*('` across `engine/`):

| Site | `merged_co` | `blend` |
| --- | --- | --- |
| `source/dyntopo/dyntopo.h:1037` — **the only production caller** | `mid` | `0.5f` |
| `tests/test_attr_merge.cc:236` | `mid` | `0.5f` |
| `tests/test_attr_merge.cc:268` | `placed` | `0.5f` |
| `tests/test_collapse_fuzz.cc:121` | `mid` | `0.5f` |
| `tests/test_collapse_repro.cc:236` | `target` | `0.5f` |
| `tests/test_dyntopo_undo.cc:265` | `nullopt` | `0.5f` |
| `tests/test_edge_collapse.cc:595` | `nullopt` | `0.5f` |
| `tests/test_edge_collapse.cc:441`, `:572`, `:649` | `nullopt` | default / `0.0f` |

The only calls that exercise the defaults are three topology tests in
`test_edge_collapse.cc`, which are testing topology and deliberately want no
attribute motion.

And the merge, when it runs, is fully wired: `interpAttrs`
(`utils/attr_interp.h:228-259`) populates `src_co`/`src_no` and sets
`have_live = true` for the vertex group, then dispatches
`NONE` / `COPY_SRC0` / `CUSTOM` / `DEFAULT` per attribute, falling through to
`defaultMerge`. `mergeWeights` and `mergeSculptLayerRest` are reached normally.

**Nothing is broken. Do not open a worktree for this.**

## Where the false finding came from

Two compounding errors, worth recording because both are cheap to repeat:

1. **The pressure-test agent read the callee and inferred the caller.** A
   defaulted parameter tells you what happens when a caller stays silent; it
   tells you nothing about whether any caller does. Establishing "this default
   is live" requires the caller inventory, and the inventory here is one line
   long.
2. **I propagated it without checking that inventory**, and then wrote a second
   claim on top of it — that "the position is relocated to the midpoint
   unconditionally while the attributes stay put" — which is also wrong. The
   position write is itself conditional (`:455-458`):

   ```cpp
   /* 5. Optional: update kept vertex position. */
   if (merged_co.has_value()) {
     m.v.co[v_keep] = merged_co.value();
   }
   ```

   With both defaults, position *and* attributes stay at `v_keep`. That is
   self-consistent, not divergent — the "drift" the finding described cannot
   occur on the default path either.

## What is actually there: a latent API footgun

The two conditionals are guarded by **different** parameters, so they can
disagree — just not in any way a current caller triggers:

| `merged_co` | `blend` | Position | Attributes | Consistent? |
| --- | --- | --- | --- | --- |
| `nullopt` | `0.0f` | stays at `v_keep` | stay at `v_keep` | yes |
| `mid` | `0.5f` | → `mid` | merged at 0.5 | yes — the production path |
| **`some_co`** | **`0.0f`** | **→ `some_co`** | **stay at `v_keep`** | **no** |
| `nullopt` | `0.5f` | stays at `v_keep` | merged at 0.5 | arguably not |

Row 3 is the trap: `collapseEdge(m, e, target)` reads as a complete, sensible
call, compiles, and silently relocates the survivor without merging anything
onto it. Nobody writes that today. Somebody eventually will.

Proportionate responses, in order of how little they cost:

- **Nothing.** Defensible. It is a private-ish utility with one caller.
- **A `BLI_assert`-equivalent** (`litestl` has `debugBreak`; the codebase's own
  assert idiom is the right pick) for `merged_co.has_value() && blend == 0.0f`,
  so row 3 fails loudly in a debug build.
- **Fold the two into one decision** — make `blend` default to `0.5f`, or derive
  it from whether `merged_co` was supplied. This changes behaviour for the three
  default-using tests in `test_edge_collapse.cc`, so it is not free, and those
  tests want the current semantics.
- **A doc-comment line** on the signature saying the two travel together. The
  existing comment at `:328-330` documents `blend` correctly in isolation
  ("0 = keep v_keep unchanged"); what is missing is that `merged_co` moves the
  vertex regardless.

My recommendation is the assert plus the comment line. It is a few minutes, it
cannot regress the tests, and it converts a silent inconsistency into a loud one.
It is **not** worth a worktree.

## Knock-on: what this does to the tasklist

[`../plans/blender-attribute-coverage-tasklist.md`](../plans/blender-attribute-coverage-tasklist.md)
has been corrected. E7 is withdrawn entirely — both its original form (the
`merged_co`-vs-lerp drift, which the audit invented) and its rewritten form (the
gate, which the pressure test invented). Consequences:

- **E7 no longer leads the suggested order.** It was item 1 on the strength of
  being a live shipped bug. It is now a footgun note.
- **1.4 (shape keys) loses its argument for the default merge policy.** The
  rewritten 1.4 said "with E7 fixed, the default policy is correct here". The
  correct statement is simpler: the default policy is *already* correct there,
  because the production collapse already merges at `blend=0.5` with
  `merged_co == mid`, and a passenger `FLOAT3` column lerped at 0.5 lands
  exactly where `position` does. **1.4 needs no CUSTOM handler and no engine
  work for its merge policy** — which is what the item's *first* write-up
  claimed, before the audit talked it out of that. The audit was wrong; the
  original was right.
- **1.4's real blocker is unaffected** — the `Mesh.key` resize gap
  (`key.cc:1665` asserts then `memcpy`s regardless of `totelem` mismatch) is
  independent of any of this and remains the gate.
- **The "engine work" section's claim about collapses is corrected.** Vertex
  attributes *are* interpolated on a collapse; only edge, face and corner
  attributes go through row copy.

## Method note

Both the audit and the pressure test produced a confident, well-cited, wrong
claim about this one function, in opposite directions, and neither was caught by
the other. The common failure was reasoning about a call from its declaration.
For any finding that turns on a defaulted parameter, an unexercised branch, or a
"nothing calls this correctly" claim, **enumerate the call sites before
believing it** — it is one grep, and here it would have killed both findings
immediately.
