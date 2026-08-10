# Attribution of the non-operator stroke wall (P-b) — RESOLVED, not a lever

Date: 2026-08-10. Question (user-directed, blocking the dab-loop
implementation): the postvbo batch showed sculptcore `sculpt_phase` wall at
~96.4 ms/stroke but stroke-operator busy (`stroke_ms`) at only ~67.7 —
**~28.7 ms/stroke sat outside the operator, unattributed**, the same
magnitude as the dab-loop design's whole expected win. Where does it go?

## Verdict

**It is not a lever.** Steady-state non-operator wall is ~15–18 ms/stroke
and is the **single vsync-blocked present** each stroke pays — native pays
the same ~15–16 ms. The rest of the 28.7 mean is a one-time warm-up
transient in strokes 1–2 (~100–180 ms/run) plus ~1 ms/stroke of view3d
draw. Nothing SC-specific hides outside the operator; the dab-loop move
(operator busy) is the only remaining stroke-path lever.

## Instrument

`bench_multires_sc.py --wall-trace` (added this session) records a span
timeline for the sculpt phase: `push` (stroke event burst queued), `step`
(bench timer body), `op:invoke`/`op:modal` (each operator call, SC only),
`draw` (PRE_VIEW→POST_PIXEL), `dgeval` (depsgraph_update_pre→post bracket =
C-side eval + all post handlers), `dg` (the addon's own handler body).
`analyze_walltrace.mjs` sweeps the timeline, assigns every elementary
segment to the highest-priority covering span (op > dg > dgeval > draw >
step > GAP), and prints phase totals, a per-stroke table, and one stroke's
raw ordered timeline. Runs: `bench-sc/walltrace/wt-{native,sculptcore}-r{1,2}.json`
(interleaved, same binary, 60 Hz confirmed by idle_frame median 16.7).

## What the timeline shows (sc, steady-state stroke)

```
push (bench timer, pass k)
  ~15 ms GAP                <- vsync-blocked present of the PREVIOUS pass
  draw 0.7 ms               <- previous stroke's edit reaches the screen
op:invoke + 21 op:modal     <- pass k+1: the whole event burst, back-to-back,
  62–67 ms total               inter-call gaps ~0 (WM dispatch is free)
dgeval 0.15 / dg 0.09       <- depsgraph eval + addon handler: noise
step -> next push immediately (no tail wait)
```

Key numbers (r1/r2 agree):

| per stroke | sc | native |
|---|---|---|
| op busy | 66.6 / 67.4 ms (probe) | ~13 (inferred: GAP − present) |
| GAP mean over 20 | 26.9 / 23.3 ms | 30.6 / 29.0 ms (includes its C++ op) |
| GAP steady-state (strokes 3+) | ~14–22 ms | ~26–30 ms |
| draw | 0.76 / 0.74 ms | 1.14 / 1.17 ms |
| dg + dgeval + step | ~0.3 ms | ~0.5 ms |
| strokes 1–2 GAP excess | ~180 / ~100 ms total | ~30 ms total |

Validation of the vsync model: sc stroke 3 (r1) op busy 67.3 ms ends past
vblank 4×16.7=66.8, so the present lands at 83.5 → observed stroke wall
84.3 ms. Stroke windows are op-busy rounded up to the vblank grid plus ε.

## Corrections to earlier claims

- `cycle_ms` never measured stroke handling: the event burst pushed during
  pass k's timer is handled in pass **k+1**, after pass k's draw+present.
  `cycle_ms` (~15–19) = push → previous content's vsynced present. The
  docstring's "handled in a single pass" is right, but it's the *next* pass.
- `sculpt_frames` in the JSONs is cumulative from process start (~102 =
  warmup ~20 + idle ~61 + sculpt ~21). The sculpt phase itself presents
  **one frame per stroke**, both arms. "Both arms present the same 102
  frames" was a misreading of that counter (the equality still holds).
- The "28.7 ms/stroke unattributed, same-size lever" framing in
  `design/cpp-dab-loop.md` §1 is corrected in place.

## Consequences for the dab loop (task #3)

Unblocked; nothing reshapes the design. Honest steady-state model per
stroke: sc 78–91 ms = 67 busy + ~16 present; native ~30 = ~13 busy + ~16
present. Post-move projection: sc busy ≈ 32 (engine dabs, survives by
construction) + ~13 `_finish` (undo push + draw refresh + pivot, kept) +
begin/invoke ≈ ~48 busy → wall ~64 vs native ~30, consistent with the
design's 2.0–2.3× realistic / 1.8× floor. Two small non-blocking observations:
`_finish`'s ~13 ms release-event modal is the biggest single surviving op
slice after the move (worth a look later), and the strokes-1-2 warm-up
transient (~150 ms once per mode entry) is real but one-time.
