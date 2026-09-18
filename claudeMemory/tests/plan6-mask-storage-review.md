The plan’s capture ordering is sound for an admitted mask stage, but its lazy-creation promise is stronger than the proposed implementation. I would block approval on that mismatch and require tighter undo evidence before claiming completion.

**Blocker: entering `execStage` does not establish a mask hit or nonzero mask effect.**

Removing `isFirstOfStep` around `ensureMaskChannel()` fixes the identified first-miss/first-nonmask bug (`grid_executor.h:1090–1095`). However:

- Programs query leaves once using the **maximum** command radius, then execute every stage with a nonzero radius against that shared selection (`grid_executor.cc:276–286`). A large DRAW can hit while a smaller MASK misses; MASK still creates its channel.
- A positive-radius MASK with zero effective strength reaches channel creation and capture before the kernel skips every vertex (`grid_executor.h:1090–1115`; `mask.sbrush:12–13`).
- Even standalone admission establishes only a nonempty leaf query, not an actual affected mask vertex (`grid_executor.h:1045–1065`).

Thus plan lines 14–18 and 33–34 cannot simultaneously mean “ensure on stage entry” and “missed/zero mask dabs create nothing.”

Minimal correction: define “zero” and “region hit” precisely. If they mean zero radius and an empty *logical-dab* query, narrow the promise accordingly. If they mean no mask-stage contribution, channel creation needs an additional gate. One possible bounded approach is to capture domain masks before execution, then ensure the channel after confirmed mask writes but before stroke-end store capture. That requires verifying the omitted generated execution code does not need the store channel during the kernel. Add the decisive case: **large DRAW hits, small MASK misses, initially absent channel**.

**Blocker if “atomic” includes successful misses/zeros: the existing API explicitly mutates their bookkeeping.**

Standalone prepared grid execution publishes scalars, increments `stats.dabs`, clears dab selections, and clears first-of-step state even when radius is zero or the query misses (`grid_executor.cc:202–218`). Empty programs also increment counters and consume first-of-step state (`233–244`). Mesh execution likewise publishes before selection and clears first-of-step state afterward (`brush_executor.cc:193–227`).

Minimal correction: distinguish **rejected preflight**, which must preserve execution/storage state apart from diagnostics, from **accepted zero/miss**, which must avoid the specified storage effects but retain existing bookkeeping behavior. If complete no-op semantics are intended for accepted misses, the proposed change is insufficient and materially broader. The first-miss regression should explicitly expect consumed first-of-step state.

**Undo claim needs evidence beyond the supplied excerpt; this is an acceptance gap, not a proven undo defect.**

The local ordering supports the design:

- MASK declares mask-only capture (`mask.sbrush:6–7`).
- `GridCapturePolicy` forwards position and mask saves independently (`grid_executor.h:1551–1564`).
- `captureLeaf` can add a missing position or mask snapshot to an already captured leaf without replacing the earlier field (`grid_stroke_log.cc:101–133`). That supports DRAW→MASK and MASK→DRAW.
- Stroke-end folding captures each channel’s occurrence-grid blocks before writing that channel (`grid_executor.h:122–143`).

But mask flush also prolongates edits into finer levels, changes attribute debt, and refreshes finer mask mirrors (`grid_domain.cc:333–343`). The supplied `applySwap` ends before its remaining channel-restoration logic. It proves current-level mask/position/block swaps, **not complete reversal of those additional effects**.

Minimal correction: verify undo and redo with a preexisting, nonuniform mask at the edited and a finer resident level, checking their store values, mirrored masks and relevant debt. Do not label the missing tail defective without evidence.

The following are acceptance refinements within the existing scope:

- Put the read-only malformed-channel check in the common prepared capability path so support queries, validation and actual execution agree. Require exactly FLOAT, one component and Vertex; storage being physically float is insufficient (`grids.h:259–262,315–342`). The current whole-program loops already provide the right place to reject before any stage executes (`grid_executor.cc:249–270`). Test a valid earlier DRAW followed by malformed MASK.
- Test both mixed-program orders, overlapping and disjoint leaf coverage, plus first zero-radius/miss/nonmask dab followed by MASK in the same step. Check mask and position restoration independently.
- Keep the neutral-channel-on-undo exception. The supplied swap restores values, not channel inventory; whole-store identity across first creation is inappropriate.
- Require actual prepared-route evidence and direct mask-value assertions. MASK intentionally moves no geometry. A successful build, visible brush action, or DRAW movement cannot prove prepared MASK execution. The packet contains no DLL/Python route implementation or execution results, so plan lines 39–42 remain requirements, not evidence.

None of these findings requires opening separately gated attributes, cavity, face, layer or host execution.