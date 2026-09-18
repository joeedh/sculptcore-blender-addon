# Plan 6: command-specific ENHANCE preparation

Status: completed 2026-09-18; [verified gate](../tests/plan6-enhance-gate.json).
The nonanchored unbounded gate passed.
The user waived CLAUDE.md's review requirement for the remaining task list on
2026-09-18. No further review dispatch or source export is needed.

## Problem

Prepared execution currently rejects every per-dab host hook and every read-only
attribute except the boundary class. ENHANCE needs a host-generated displacement
field. Its raw hook reads enhance_rings and enhance_inner from Brush, then caches
one vector per vertex under strokeGen alone. Two commands with different settings
therefore cannot share that cache. Deduplicating hook function pointers also loses
command-specific execution order and settings.

## Implementation proposal

1. Add authoritative static INT32 snapshots for enhance_rings and enhance_inner,
   using the existing executor-setting machinery and native descriptors. Permit
   command scalar overrides but no device stack until dynamic eligibility is
   explicitly defined. Preserve the kernel's existing normalization:
   outer = max(rings, 1), inner = clamp(inner, 0, outer). Validate any arithmetic
   bounds required to avoid signed overflow; do not invent an artist-facing cap.
   The source comments incorrectly say inner must be strictly less than outer;
   actual native behavior allows equality and yields zero detail.
2. Classify prepared hooks as invariant preparation or command-specific per-dab
   preparation. Continue deduplicating only the invariant boundary refresh.
   Invoke ENHANCE preparation after applying that command's prepared values and
   immediately before its kernel, with the program's live-topology requirement
   computed across all commands before mutation. Preserve raw execution policy.
3. Add an executor-owned prepared ENHANCE cache keyed by normalized outer/inner,
   mesh identity and topology generation, reset at stroke boundaries. Store
   first-contact vectors per key and vertex plus a reusable active column.
   Each stage claims vertices inside its own effective support, even when a
   larger/unbounded stage widens the shared node list. With nonaccumulating
   kernels, use the same base-coordinate support convention as prepared cavity.
   Compute the vector from the live geometry/normal at that first contact, using
   the original difference-of-smooths formula and reusable BFS scratch.
4. Before each ENHANCE kernel, install that configuration's active values into
   the existing temporary displacement attribute or an equivalent scoped binding.
   Admit exactly its vertex/FLOAT3/read-only/no-extra-use metadata together with
   the corresponding classified hook. Preserve rejection of arbitrary attributes
   and unsupported grid bindings. Native grid dispatch already routes ENHANCE to
   the materialized mesh because its read-only field has no grid source; retain
   that geometric-domain fallback rather than accepting a zero field.
5. Validate all scalars, metadata, command membership, hook requirements and
   transaction identity before allocating attributes, changing topology state,
   building caches or capturing undo. Restore command working settings on every
   exit. Keep FEATURE_ALIGN, general authored attributes, anchored/preview and
   dyntopo admission guarded until their own implementation gates pass.

## Acceptance

Implementation choices (2026-09-18): the generated ENHANCE manifest declares both
native INT32 members without defaults or narrowed ranges. Their native executor
descriptors supply full INT32 domains and static authority. Candidate preparation
includes them only when the command's manifest declares them; unrelated command
overrides therefore fail. Prepared execution binds an executor-owned `AttrData`
column directly rather than allocating `.brush.enhance.*` mesh attributes.
The binding is established before capture, populated after displacement-base
initialization, and remains stable during kernel execution. Stored mesh normals
are read at contact; the existing executor refreshes queries/normals after the
program, not between its stages. The independent oracle follows that timing.

- Native preparation verifies authoritative settings, independent command values,
  static-stack rejection, exact types, range normalization and failure atomicity.
- Multi-leaf live/CSR-configured mesh tests run two ENHANCE commands with different
  rings/inner in both orders, intervening DRAW, repeated dabs, zero/missed first
  dabs, changed pressure on strength, growth of support and nonaccumulation.
  Compare with an independent original-formula oracle and separately configured
  raw single-command references where their first-contact regions coincide.
- Prove distinct command cache keys, reusable unchanged keys, correct first-contact
  values after geometry changes, and no premature capture caused by a larger later
  command. Include an unbounded later command to force all-leaf selection.
- Exercise topology generation changes, stroke reset, undo/redo, absent temporary
  attribute allocation, failed late commands, validate-only and zero-count batches.
  Reuse the existing transaction/owner lifetime validation without weakening it.
- Actual Python/DLL and installed headed tests must require prepared execution on
  the selected mesh domain, including materialized multires fallback. Verify the
  fallback selects the correct domain before mutation and still uses prepared
  properties; raw fallback cannot stand in for generic property support.
- Regenerate bindings, run applicable native suites and package provenance checks.
  Record source reviews, corrections, commands and artifact identities before
  checking this capability off in the Plan 6 task list.

## Review questions

The reviews must resolve whether writing the active values into the existing TEMP
attribute preserves attribute binding and lifetime rules, whether raw first-contact
semantics require a different support/cache policy, and how the mesh fallback for
multires interacts with the existing prepared owner/transaction validation. These
are implementation questions; no user approval is required for routine corrections.

## Semantics review dispositions — 2026-09-18

The [fresh semantics review](../tests/plan6-enhance-semantics-review.md) requires
the following corrections, retained during implementation.

Review dispatch: the user authorized CLI use for remaining reviews. The semantics
CLI review completed. Automatic approval review rejected the integration invocation
because it required explicit authorization for sending the source-file packet to
OpenAI, beyond CLI authorization. The user subsequently waived the review rule;
the blocked review is abandoned, and no export approval is needed to continue locally.

- Insert prepared ENHANCE preparation inside `exec()`, after the current command
  initializes `ctx.dispVec`, `ctx.dispGen` and `ctx.strokeGen`, beside the existing
  prepared cavity phase and before parallel execution. A hook before `exec()`
  cannot use the nonaccumulating base reliably.
- Contact means positive-radius geometric support, independent of strength,
  masks, textures and automasking. Zero strength captures; zero radius and misses
  do not. This deliberately corrects raw leaf-wide capture, which depends on
  tree partitioning. Raw parity is claimed only with equal capture times and
  geometry. Add zero-strength contact followed by DRAW and a positive revisit,
  separately from zero-radius followed by DRAW and first contact.
- Hooks execute per command. Identical normalized `(outer, inner)` settings
  intentionally share first-contact history across command slots, matching the
  configuration-keyed cavity policy. Test `[A, DRAW, A]`, `[A, DRAW, B]`, A/B/A
  revisits, and differently authored pairs that normalize to the same key.
- Size reusable BFS stamps and active columns by vertex capacity, not live
  count. Clear stamps on token wrap and restart at a nonzero token. Test sparse
  vertex IDs and forced wrap against fresh scratch. Use an overflow-safe depth
  loop without restricting valid INT32 inputs.
- Snapshot/restoration coverage and override eligibility are separate. Add the
  ENHANCE static settings only to eligible command candidates; reject those
  overrides on DRAW and other commands. Accept negative INT32 authored values
  and normalize according to the native formula, instead of rejecting them with
  invented descriptor limits. Static device stacks remain rejected.
- The independent oracle uses graph distances from explicit adjacency, with
  each center included once, and snapshots actual stored coordinates/normals at
  each configuration's first contact. It must not call `computeEnhanceDisp()`.
  Normal-refresh timing must follow the executor's established stage semantics.
- Late invalid commands and validate-only calls must preserve geometry,
  topology state, TEMP attributes, caches, active values, undo capture and all
  working settings. Add leaf-partition invariance coverage for contact selection.
