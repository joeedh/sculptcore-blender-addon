**Admission verdict: revise before implementation.** The capability change is appropriately bounded, and full program preflight already exists. The concrete gap is the promise that missed/zero mask stages cannot create storage: entering `execStage` does not establish that the mask stage hit anything.

1. **Blocker: a program-wide region hit is not a mask-stage hit.**  
   `prepareProgramScalars` selects the maximum command radius (`brush_program_preparation.cc:199`). Grid execution queries once with that radius, then runs every positive-radius stage over those leaves (`grid_executor.cc:276–286`).

   Counterexample: a large-radius DRAW hits; a smaller-radius MASK misses. The proposed unconditional `ensureMaskChannel()` in `execStage` creates storage anyway. Even standalone execution establishes only a leaf-query hit (`grid_executor.h:1045–1065`), not an affected mask vertex.

   **Minimal correction:** define “accepted region hit” precisely. If it means the existing broad-phase leaf selection, explicitly permit channel creation for an ineffective positive-radius mask stage, including one selected by another command’s radius. If it means a hit within the mask stage’s own effective region, require that check before channel creation. Add the large-DRAW/small-missing-MASK case; testing only a growing secondary radius misses this failure.

2. **Blocker in the stated contract: “zero” and “atomic” need narrower definitions.**  
   Positive radius with zero effective strength still reaches `execStage`; the kernel skips work only afterward (`mask.sbrush:12–13`). Channel creation and `execPre` capture precede that evaluation (`grid_executor.h:1090–1115`). Thus “zero dabs must not create storage” is unsupported if zero includes zero strength or pressure producing zero strength.

   Also, successful zero-radius/missed dabs already consume bookkeeping: standalone grid execution publishes scalars, increments `stats.dabs`, clears sets and clears first-of-step state (`grid_executor.cc:202–218`). Empty programs likewise change counters and first-of-step state (`:233–244`). Mesh execution also publishes before selection and clears first-of-step afterward (`brush_executor.cc:193–227`).

   **Minimal correction:** distinguish rejected calls, successful zero-radius/empty calls, and positive-radius calls with no effective mask writes. Preserve existing successful-call bookkeeping unless changing it is intentional. Reserve complete state preservation for rejection. If zero effective strength must prevent allocation/capture, the plan needs an additional mechanism; moving `ensureMaskChannel()` alone cannot satisfy that requirement.

3. **Required implementation invariant, already correctly requested—not another missing feature: validate mask metadata throughout admission.**  
   `ensureMaskChannel()` only checks the name (`grid_domain.cc:274–284`); it does not validate shape, domain or type. Checking only there would be too late for programs: an earlier DRAW could already have executed.

   Put the read-only check in the shared capability/preflight path used by supports, standalone execution and **every** program entry, before publication or execution. Require exact `FLOAT`, size one, vertex domain using the accessors supplied in `grids.h:315–342`; “interpolatable” alone accepts vector types. Existing loops already support complete preflight (`grid_executor.cc:249–270`, `brush_executor.cc:259–283`). Validate even a zero-radius mask command rather than letting execution skipping bypass admission.

**Acceptance refinements, not additional scope gates:**

- Exercise malformed type, component count and domain separately, through supports, `validateOnly`, standalone and later program entries. Snapshot rejection state after opening the step: `GridStrokeLog::beginStep` itself discards redo history (`grid_stroke_log.cc:44–51`).
- Require both DRAW→MASK and MASK→DRAW, plus first miss and first non-mask dab followed by MASK. The per-field snapshot upgrade supports mixed order (`grid_stroke_log.cc:109–133`); the first-dab-only channel creation is a real defect.
- Score actual mask deltas independently of positions. Require unchanged positions for pure MASK and exact mask/store undo/redo. The supplied capture and fold paths support this design, but generated affected-vertex reporting and complete cross-level undo behavior are not shown.
- Require route evidence paired with results: prepared entry executed, no raw fallback accounting for success, mask values changed as expected, and loaded package/DLL provenance. The packet contains acceptance intentions, not that evidence.

No supplied evidence justifies expanding this slice to separately gated attributes, cavity, faces, layers or host commands.