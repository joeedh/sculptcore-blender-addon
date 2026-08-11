# Design: the C++ dab loop (`StrokeRun`)

Status: **REVISED after adversarial pressure-test** (2026-08-10, four lenses:
engine buildability, behavior parity, perf payoff, lifecycle/ABI). The v1
draft's architecture survived; its perf claim did not, two memory-safety
fatals were found and closed, and the ray-synthesis section was rewritten
after both code-facing lenses proved it misdescribed what Blender ships.
§12 records the verdict. Supersedes the scope limit in
[plans/cpp-stroke-driver-adoption.md](../plans/cpp-stroke-driver-adoption.md)
("the sampler only") at the user's direction: *"let's move the dab loop into
C++ next."*

## 1. Problem and honest target (revised)

At 1M faces / multires level 4, the SculptCore sculpt phase is ~2.7× native
(interleaved same-batch ratio, 2026-08-10, postvbo batch). The v1 draft
cited "~0.85 ms/dab of removable Python driver cost" — **that figure is
stale and mis-composed**. It was derived from the pre-VBO-fix batch
(~105 ms/stroke) and bundles ~0.4 ms/dab of PCIe stall the VBO fix already
removed. Against the post-fix batch this design itself cites, the numbers
are:

- stroke operator busy time: **67.7 ms/stroke** mean; dabs/stroke
  **median 84** (the diameter fix doubled the old ~63 figure — don't cite it).
- engine dab (`GridStroke_dab`): 0.38 ms → 84 × 0.38 = **31.9 ms/stroke**
  survives by construction.
- total non-engine-dab cost: (67.7 − 31.9)/84 = **0.43 ms/dab**, of which
  mid-redraw (~7 ms/stroke, measured), the engine-side raycast time itself,
  per-event modal dispatch + bpy reads, and stroke begin/end are all *kept*
  by this design.
- **honestly removable Python slice: ~0.2–0.33 ms/dab ≈ 16–28 ms/stroke.**
- **The ~28.7 ms/stroke of sculptcore wall time outside the operator is
  ATTRIBUTED and is NOT a lever** (P-b resolved 2026-08-10; see
  [research/non-operator-wall-attribution.md](../research/non-operator-wall-attribution.md)).
  A span-timeline instrument (`bench_multires_sc.py --wall-trace` +
  `analyze_walltrace.mjs`) buckets every ms of the sculpt phase: steady-state
  non-operator wall is **~15–18 ms/stroke and is the single vsync-blocked
  present each stroke pays** — native pays the same ~15–16 ms (its ~29 ms
  GAP = its own C++ operator busy ~13 ms + the same present wait). The rest
  of the 28.7 mean is a one-time ~100–180 ms warm-up transient in strokes
  1–2 plus ~1 ms/stroke of view3d draw. WM event dispatch between modal
  calls measures ~0 (operator span ≈ operator busy sum); depsgraph
  eval + handlers are ~0.25 ms/stroke. There is no hidden SC-side cost.

Consequences: the v1 "ratio ≈ 1" end state is arithmetically unreachable —
a zero-cost runner floors at ~1.8× (engine dabs alone equal native's whole
per-stroke budget, plus the shared present quantum). **Honest expected
outcome: sculpt-phase ratio ~2.0–2.3× from 2.7×** — a real ~300–500 ms/bench
win. Steady-state model, per stroke: sc wall ≈ 67 op busy + ~16 present;
native ≈ 13 busy + ~16 present. Post-dab-loop: sc op busy ≈ 32 (engine dabs)
+ ~13 (`_finish`: undo push, draw refresh, pivot — kept) + invoke/begin ≈
~48, wall ≈ ~64 vs native ~30.

- **(P-a)** ~~re-profile the per-dab Python slice post-VBO-fix~~ — **DONE
  2026-08-10** (`--engine-trace --profile` run,
  `bench-sc/walltrace/wt-sc-trace-r1.json`): removable slice lands at
  **~20–28 ms/stroke**, the upper half of the bound. Structure per stroke:
  `apply_dab` 26 ms of which ~21 is the engine dab (kept); bpy RNA reads
  ~9 ms; raycast ~6 ms over 151 spaced samples (44% miss — batch casting
  covers misses too); curve eval ~4 ms; `_apply_spaced_dab`/dab-state
  bodies ~8 ms. Kept work confirmed kept: `stroke_end` 7.3,
  `draw_refresh` 8.4, `_mid_redraw` ~5, undo ~1 ms/stroke.
- **(P-b)** ~~attribute the 28.7 ms/stroke non-operator wall~~ — **DONE
  2026-08-10, not a lever** (vsync present shared with native + warm-up
  transient). Dab-loop implementation is unblocked.

## 2. Two variants

The pressure test surfaced a cheaper sibling. Both move the per-dab cycle
into C++; they differ in where ray/radius math lives.

**Variant A — full `StrokeRunner`** (the v1 architecture, amended below):
engine owns spacing (via `BrushStrokeDriver` as spacer), ray synthesis,
raycast, world radius, prop cycle, symmetry, apply. One ctypes call per
pointer event. ~500–700 lines C++; one genuinely new algorithmic surface
(the verbatim `view3d_utils` port, §5). Strategic value: D2 (smooth
multi-pass, dyntopo, programs) builds on it, and Python leaves the per-dab
path entirely.

**Variant B — batched dab calls, math stays host-side**: per event, Python
computes ray origins/dirs and world radii for all spaced points **with
numpy, vectorized** (the identical shipping math, batched), then makes ~2–3
flat capi calls: `StrokeRun_castBatch(N rays → hits)` and
`StrokeRun_dabBatch(N × {pos, normal, radius, strength, invert, pressure})`
which runs the writeProps→apply→symmetry cycle per entry engine-side.
~100 lines C++, no new algorithmic surface, no §5 parity burden, fallback
matrix untouched. Captures an estimated 70–85% of A's win. Weakness: the
spacing walk and per-point Python bookkeeping stay; D2 paths stay host-side.

**Recommendation: B first, then decide.** B is a strict stepping stone —
its engine-side batch-apply cycle (prop cycle + symmetry + apply + the §7
lifetime guards) is a component A needs anyway, and it can land and be
A/B-measured inside a day. If the post-B residual per-dab cost still
matters after (P-a)/(P-b), A's remaining delta (driver-as-spacer + the
§5 ray port) is an incremental step, not a rewrite. Everything in
§4–§11 below is written for A but applies to B's shared parts verbatim
(§5–§6 stay Python under B).

### Data flow per stroke (variant A)

```
Python stroke_begin (unchanged: undo bracket, apply_brush_settings,
                     apply_pressure_dynamics, GridStroke_begin / beginStep)
  StrokeRun_new + bind — chosen strictly AFTER stroke_begin returns, keyed
    on session.last_stroke_grids (stroke_begin can silently fall through
    grids→mesh; binding from the pre-stroke predicate would put runner dabs
    in one undo system while the open step belongs to the other)
  StrokeRun_setStroke(strength base, invert base, overlap (see §4.3),
                      fallback world radius, mirror signs, flags)
per pointer event (modal loop):
  StrokeRun_setView(mats, viewport, near, persp)     # per event: orbit-safe
  n = StrokeRun_event(x, y, pressure, tilt, twist, invert,
                      pixel_radius, spacing_frac)     # THE hot call
  n < 0 → the stroke is dead: §8 error contract
  Python: 30 Hz mid-redraw as today (granularity is unchanged — today's
    _mid_redraw already runs once per event, after the whole dab batch)
on commit (release):
  StrokeRun_end()          # driver flush + trailing dabs
  StrokeRun_pivot(out[4]); StrokeRun_free()
on cancel (ESC/RMB) — matches today's "stop early, keep what landed":
  NO StrokeRun_end (the buffered trailing segment dies, exactly as the
    Python spacer's unflushed segment dies on CANCELLED today)
  StrokeRun_pivot(out[4])  # _publish_pivot runs unconditionally today
  StrokeRun_free()
Python stroke_end (unchanged on BOTH paths: GridStroke_end / endStep,
                   cursor bump, undo.push — cancel is not rollback)
```

The operator must also grow a `cancel(self, context)` method (it has none
today — window close / file load / forced mode exit currently leak an open
engine step even without this design) routing into the same teardown, and
the per-event body wraps `StrokeRun_event` + mid-redraw in try/except that
routes to `_finish(context, 'CANCELLED')` rather than letting an exception
escape. Teardown is idempotent (`StrokeRun_free` tolerates repeat/null) so
cancel-then-finish ordering cannot double-free.

### Inside `StrokeRun_event`, per polled sample (all C++)

0. **Lifetime guard first, before any raycast** (§7).
1. Synthesize the ray for `screenP` (§5), cast it (§6). Miss → skip sample
   (today's behavior; 44% of casts).
2. World radius at the hit (§6a).
3. Prop cycle: `brush->strength = baseStrength * overlap` (the fold v1
   dropped — see §4.3), `brush->radius = worldRadius`,
   `brush->invert = sampleInvert ^ directionSubtract`,
   `brush->writeProps()`; if pressure dynamics active: `clearDeviceInputs()`
   + `pushDeviceInput(Pressure, rawPressure)` once per logical dab, shared
   by all mirror images. The destructive `loadCommonProps` write-back cycle
   becomes invisible — bracketed inside one C++ loop.
4. Pivot accumulate (primary hit only).
5. Apply the primary image, then one per mirror sign with the resolved hit
   position/normal reflected (never re-raycast per image):
   - grids: the full `GridStroke_dab` body on the bound session —
     `exec.setGrabAccumAdd(false)` → `exec.applyDab(tool, p, n)` → on
     moved>0 `mr->drawSource()->markVerts(lastDabMoved)` → if
     `session->mirror`: `gridsMirrorToSlot`. All four steps; undo capture
     rides the session's `GridStrokeLog` already wired into the executor.
   - mesh: `exec->setGrabAccumAdd(false)` (applyDab does NOT do it), then
     `CommandExecutor::applyDab(tool, p, n, radius, nullptr, seed)` —
     verified to exist with the tool-enum overload; it applies
     `fmax(radius, filterRadiusFloor)` and filters nodes internally and
     calls `clearIsFirstOfStep()` — then `tree->updateQueries()` per image
     (applyDab does not refresh queries).
6. `dabCount++` **per image, including mirrors** (matches `_apply_one_image`;
   v1's step 6 contradicted its own invariant 5 — per-image is correct).
   Seeds are vestigial in D1 (`params=nullptr`) but the parity harness
   asserts the sequence.

## 3. The c-api

Flat functions, `GridStroke_*` style, exported via `wasm_add_symbols` in
`source/brush/CMakeLists.txt` (which also feeds the native DLL export
list); the new `stroke_runner.{h,cc}` + c-api .cc must also join the
CMake `SRC` list.

```c
StrokeRunner *StrokeRun_new(void);
void StrokeRun_free(StrokeRunner *r);          /* idempotent, null-safe */

int StrokeRun_bindGrids(StrokeRunner *r, GridStrokeSession *s);
int StrokeRun_bindMesh(StrokeRunner *r, CommandExecutor *exec,
                       spatial::SpatialTree *tree, Brush *brush, int tool);

/* per event batch — 48 doubles: perspective_matrix + VIEW matrix + object
   matrix. v1's 32-double payload was insufficient: three of the four
   shipped ray quantities need the view matrix (persp origin = eye =
   viewinv.translation; ortho dir = -viewinv.col[2]; ortho far offset =
   persinv.col[2]) and the eye is not bit-recoverable from P·V. The runner
   owns the transposes and the y-flip. */
void StrokeRun_setView(StrokeRunner *r, const double mats[48],
                       double regionW, double regionH,
                       double clipNear, int isPersp);

void StrokeRun_setStroke(StrokeRunner *r, double baseStrength,
                         int invertBase, double overlap,
                         double fallbackWorldRadius,
                         const float *mirrorSigns, int mirrorCount, /* ≤7 */
                         int usePressureDynamics, int tool);

/* x,y in region coords (bottom-left origin); returns dabs applied this
   event (0 = all samples missed, NOT an error), <0 = stroke dead (§8) */
int StrokeRun_event(StrokeRunner *r, double x, double y, double pressure,
                    double tiltX, double tiltY, double twist,
                    int invert, double pixelRadius, double spacingFrac);

int  StrokeRun_end(StrokeRunner *r);        /* commit only; never on cancel */
void StrokeRun_pivot(StrokeRunner *r, double out[4]); /* Σxyz, count */
```

`pixelRadius` must be the **unscaled** `mapping.pixel_radius` — never
pre-multiplied by the size-pressure LUT. Size pressure reaches the dab
exclusively through the engine `PROP_RADIUS` device dynamic plus the raw
pressure push; pre-scaling would double-apply it. (Verified: the design's
split reproduces today's radius-pressure path exactly.)

**Buildability prerequisite (was FATAL):** `GridStrokeSession` is currently
a struct local to `grid_stroke_c_api.cc` — no header declares it, so
`StrokeRun_bindGrids` cannot compile from a new file. Either hoist the
struct into a small header (its member types — `GridBrushExecutor`,
`GridStrokeLog`, `Multires` — are all already public), or implement the
runner's grids arm inside `grid_stroke_c_api.cc`. The session carries
`mr` + `level`, so the bind needs nothing else.

Pointer identity is safe: bound-object `.ptr` **is** the C++ this-pointer
(`_classgen.py` reads members at `self.ptr + offset` and passes it as the
invoke self), and the addon holds `session.brush_obj` / `session.executor`
/ `session.tree_ptr` / `session.grid_ptr` stably — *within* one stroke,
subject to §7.

## 4. Per-dab semantics the runner must reproduce exactly

1. **Prop-cycle order**: strength/radius/invert → `writeProps()` → device
   refill → images. Matches `_apply_spaced_dab`. The refill is once per
   logical dab, shared by mirror images; non-compounding because
   `loadCommonProps` reads the prop store (baked by `writeProps`) and only
   the *fields* are destructively overwritten, which the per-sample rewrite
   resets.
2. **`filterRadiusFloor` ordering invariant**: the engine floor reads
   `brush->radius * unboundedExtent`, which equals the host's
   `field_radius` *only because* the prop cycle wrote
   `brush->radius = worldRadius` first. Reordering steps 3 and 5 silently
   mis-filters unbounded kernels (kelvinlet).
3. **Strength fold (was MAJOR)**: per-dab strength is
   `base × overlap_attenuation × STRENGTH_SCALE[type]` — DRAW_SHARP is
   ×2.0, and spacing<100% strokes carry the 1/peak normalization. Python
   folds all of it into the `overlap` passed at `setStroke`, exactly as
   `invoke` computes `self._overlap` today (kernel-toggle strokes skip the
   STRENGTH_SCALE fold, as today).
4. **Invert**: the driver latches the pushed event flag to the nearest
   control point; per dab the runner XORs with `direction=='SUBTRACT'`.
   Mid-stroke Ctrl rides the event.
5. **Miss handling**: skip the sample, nothing else (no synthesizeMiss
   adoption; behavior change is not this design's job).
6. **Tilt/twist**: forwarded but inert today (the Python driver path pushes
   zeros); pass zeros in parity fixtures or verify inertness first.

## 5. Ray synthesis — verbatim `view3d_utils` port (rewritten; was MAJOR ×2)

v1 claimed a "two-depth near-plane unprojection" model and "exact parity by
construction." Both code-facing lenses independently proved that wrong.
What Blender — and therefore this addon — actually ships
(`view3d_utils.region_2d_to_origin_3d` / `region_2d_to_vector_3d`, called
from `_ray_origin_dir`):

- **Perspective origin = the eye**, `viewinv.translation` — from the view
  matrix, not any unprojection.
- **Perspective dir** = unproject `(dx, dy, −0.5)` through
  `perspective_matrix.inverted()`, minus the eye, normalized.
- **Ortho origin** = the pixel's mid-plane unprojection **pushed back by
  the full far-clip-scaled offset** (`origin −= persinv.col[2].xyz`). The
  "synthetic far origin" v1 claimed to avoid is what ships today, and a
  near-plane origin would be a behavior change: geometry between the near
  plane and today's pushed-back origin hits differently.
- **Ortho dir** = `−viewinv.col[2].xyz`.

The runner ports these functions **verbatim, branch for branch**, including
the far-clip offset and the inverse-object transform with normalize *after*
the 3×3 multiply (as `_ray_origin_dir` does). That — and only that —
restores exact parity: the same float64 math producing the same float32
origin/dir at the `castRay` seam, so the parity fixtures can assert
bit-equal hits. If a near-plane ortho origin is ever wanted, it is a
separate, A/B'd change.

### 6a. World radius (corrected)

`_pixel_to_world_length` is **equal-Euclidean-distance**, not equal-depth:
`edge_world = ray_origin + ray_dir * |center_world − ray_origin|` for the
offset pixel's ray (a sphere about the origin, not a plane; off-center
these differ by a cos factor). Port `stroke.py:1372–1402` literally,
including both fallback triggers: `location_3d_to_region_2d` returning
None **and** a computed length of exactly 0.0 (`or`, not `is None`).

## 6. Raycast dispatch

Two-arm switch on the bind:

- grids → **the bound session's `exec.tree`, never a fresh
  `mr->gridDomain(level)` fetch** (was FATAL — see §7: `gridDomain()`
  lazily *rebuilds* a dropped domain, so casting through it silently
  resurrects a new domain while the bound executor still dangles on the
  freed one, converting a detectable abort into a UAF with a
  plausible-looking hit).
- mesh → `tree_->castRay` (what `BrushStrokeDriver` already calls).

## 7. Lifetime guards (was FATAL-1/FATAL-2/MAJOR-3)

v1's premise "the runner never survives a domain rebuild because a runner
lives strictly inside one stroke" is **false**: `_mid_redraw` tags the
object, so `_on_depsgraph_update` fires between modal events during every
stroke, and inside it `_sync_multires_levels` can call
`set_multires_level` (a fold: `dropDomains` frees the domain, allocator
routinely reuses the block) and `_reconcile` can `free()` whole sessions.
Today's Python loop survives because it re-reads `session.grid_ptr` per
dab and gates every cast on `Multires_hasGridDomain` + provider kind; the
runner removes those re-reads, so it must replace them:

- **Engine half**: `StrokeRun_bindGrids` records `mr->domainGeneration()`
  + level at bind. Every `StrokeRun_event` / `StrokeRun_end` checks
  `hasGridDomain(level) && gen == boundGen` **before the raycast** (after
  it is too late — see §6) and returns a distinct error code on mismatch.
  One integer compare per event.
- **Python half**: before each `StrokeRun_event`, verify the session
  object is the one bound (`session.generation` / `id(session.executor)`
  identity) and abort the stroke on mismatch. Both halves are needed: the
  engine check catches folds; the Python check catches session
  `free()`/re-enter, which invalidates the `GridStrokeSession*` itself.
- **Mesh half**: `_rebind_multires_views` disposes `session.executor` +
  `session.meshlog` and is reachable mid-stroke by the same path; the
  Python-side identity check covers it.

Node pointers need no guard: `applyDab` re-filters per dab into id-keyed
storage precisely because leaves can be freed/reused between dabs; the
runner caches no node pointers across dabs.

## 8. Error contract (was MAJOR — v1 was silent)

- `StrokeRun_event ≥ 0`: dabs applied; 0 = all samples missed, normal.
- `< 0`: the stroke is dead (distinct codes: unbound, domain-generation
  mismatch, disposed tree, internal). Python must then: `StrokeRun_pivot`,
  `StrokeRun_free`, run the normal **cancel** teardown — `stroke_end` +
  `undo.push`, so the dabs already applied land in one coherent undo step
  and the grid/meshlog cursors stay consistent — `self.report({'WARNING'})`,
  return `{'CANCELLED'}`.
- **Never fall back to the Python dab loop mid-stroke** (invariant). The
  driver owns the spline lookahead and spacing residual; the Python spacer
  never saw the stroke's earlier control points, so a mid-arc handoff
  double-fires or gaps dabs and restarts pressure interpolation wrong.
  Runner-vs-Python is a per-*stroke* choice made at invoke, only.

## 9. Scope: what moves, what stays, what never moves

**D1**: the plain spaced-dab path — every kernel that flows through
`_apply_spaced_dab` → `apply_dab_state` → `apply_dab` today, both grids
and mesh, with symmetry, pressure dynamics, per-event invert.

**Python fallback, unchanged, selected at invoke** (verified: the entire
qualification predicate is per-stroke today — grab-class/snake-hook from
keymap operator properties fixed at PRESS, smooth mode likewise, dyntopo
toggle read once at invoke, program/preview at invoke; `modal()` swallows
all events so no mid-stroke UI edits; only Ctrl-invert is per-event and it
rides the event):

- **Grab-class + anchored + drag-dot**: permanently out (one dab per event
  — no win to move).
- **Snake hook**: out of D1 (same argument). Note: today the spacer toggle
  *does* route snake hook through the C++ spacer; under the runner's
  predicate it reverts to the Python spacer — spacing parity means no
  behavior change, but record the perf non-claim.
- **Smooth multi-pass**: D2 (pass-strength computation + Python-side LUT
  folding move together).
- **Dyntopo + brush programs**: D2. Note for D2: today `_stroke_s`
  advances only on *hits* (the miss return precedes the cadence
  bookkeeping), so dyntopo cadence must not naively read the driver's
  `strokeS`, which advances on misses too.
- **Preview dabs**: stays host, unaffected.

**Toggle (was MAJOR — v1's repurposing rejected):** a **new** scene bool
`sculptcore_cpp_dab_loop` (default False, Experimental panel); the old
`sculptcore_cpp_stroke_driver` property is **deleted in the same commit**.
Deletion makes stale saved-`.blend` state inert (unknown IDProperty, never
read) — repurposing would have silently opted old files' users into the
new experimental hot path under a checkbox they ticked for a validated
wash. `bench_multires_sc.py --cpp-driver` gets consciously repointed (new
flag name) so pre/post-bump benchmarks can't be conflated.
`stroke_driver.py` (the Python wrapper) **stays** — the sampler parity
harness depends on it.

## 10. Validation plan (task #4)

- **Parity**: fixtures compare the runner against the **C++ driver path**,
  not the default Python spacer (their invert/pressure latching already
  diverges today; comparing against the spacer would report shipped
  divergence as runner bugs). Assert per-dab: hit positions (bit-equal —
  §5 makes this achievable), world radii, invert, seed sequence, dab
  count. Then headed: peak_z per stroke, undo blob sizes, mirrored-stroke
  symmetry, cancel-path dab counts (no trailing dabs on ESC).
- **Perf**: gate on `stroke_ms` medians and per-dab timers, **not**
  single-run `sculpt_phase` — the expected phase delta (~400 ms/bench) is
  only ~2.7× the ±150 ms single-run noise floor, so a real win and a wash
  are indistinguishable in two runs. Interleaved same-batch A/B at 1M/L4.
- **Regression**: full engine ctest sweep (baseline 125/125; known
  env-dependent failures matched by *name*), `verify_addon.py`, a
  non-multires mesh-session stroke check, and an ESC/window-close pass
  (the new `cancel()` path).
- **DLL round trip**: `node make.mjs build python` + re-vendor; submodule
  gitlink bump co-committed.

## 11. Cost/risk summary (revised)

- Variant A: ~500–700 lines C++; the one new algorithmic surface is the
  verbatim §5/§6a port, with exact-parity fixtures available. Variant B:
  ~100 lines C++, no new surface, most of the win.
- **The perf payoff is real but bounded**: 16–28 ms/stroke, ratio
  2.7× → ~2.0–2.3×, floor ~1.8×. Anyone expecting ratio ≈ 1 from this
  design is reading v1; that claim is dead. (P-b) resolved the
  non-operator wall as vsync present pacing shared with native — this
  design's removable Python slice is the only remaining stroke-path lever.
- Rollback = the (new) toggle. The Python loop stays live for excluded
  paths daily, so it cannot rot.

## 12. Pressure-test verdict (2026-08-10)

Four adversarial lenses, run per the repo's pressure-test-don't-audit
convention. Disposition of every FATAL/MAJOR:

| Lens | Finding | Disposition |
|---|---|---|
| buildability | `GridStrokeSession` TU-local → bind uncompilable | fixed §3 (hoist or co-locate) |
| buildability + parity | §4 ray model ≠ shipped `view3d_utils`; 32-double view payload can't carry the eye; "parity by construction" false | rewritten §5, 48-double payload |
| parity | overlap × STRENGTH_SCALE strength fold dropped (DRAW_SHARP halved) | fixed §4.3 |
| parity | no cancel path → trailing dabs applied on ESC | fixed §2 flow + `cancel()` |
| parity | §6a radius formula is equal-distance, not equal-depth | fixed §6a (literal port) |
| perf | 0.85 ms/dab stale (pre-VBO-fix); removable slice is 0.2–0.33 ms/dab; ratio ≈ 1 unreachable (floor 1.8×); 28.7 ms/stroke unattributed outside the operator | §1 rewritten; (P-a)/(P-b) added; variant B added §2 |
| lifecycle | mid-stroke domain folds reachable (depsgraph fires during strokes); bound pointers dangle; `gridDomain()` raycast masks the fold as a UAF | fixed §6 + §7 (gen guard before raycast, Python identity check) |
| lifecycle | `_rebind_multires_views` disposes bound executor mid-stroke | fixed §7 |
| lifecycle | grids-vs-mesh bind racing `stroke_begin`'s silent fallthrough → two undo systems in one stroke | fixed §2 (bind after `stroke_begin`, keyed on `last_stroke_grids`) |
| lifecycle | error contract unspecified; mid-stroke Python fallback must be forbidden | fixed §8 |
| lifecycle | toggle repurposing: saved-scene silent opt-in, bench-flag meaning drift | fixed §9 (new property, old deleted) |

Verified-and-held (no change needed): pointer identity (`.ptr` is the C++
this), driver's no-arg spacer mode, `applyDab(tool, …)` overload existence
+ internal filter policy, radius-pressure split (no double-application),
mid-redraw granularity (already per-event), per-stroke qualification
predicate, pressure-dynamics memoization across interleaved stroke kinds,
threading (no new reentrancy window), node-id (not pointer) filtering.

Minor notes carried: `applyDab` clears `isFirstOfStep` even on zero-node
dabs where Python doesn't (unreachable after a confirmed hit); Python's
per-dab live reads of `bl_brush.strength` are frozen at `setStroke`
(mutation mid-stroke only possible via timers/second window — accepted);
stale `_flush_multires` comment at `convert.py:1898` describes removed
fold behavior as current — fix when touching.

## 13. Validation results (2026-08-10, task #4 — variant B as landed)

Everything below ran against engine 8b8bc3a + addon b6bb0e8 staged into the
dev fork build (`build_windows_x64_clang_RelWithDebInfo`).

**Correctness**

- `test_batch_dab.py` (headless smoke, all four entry points direct): 17/17.
- `test_batch_parity.py` (batch vs shipping Python cycle, identical dab
  sequence, X-mirror on the mesh arm): mesh arm **bit-exact** (max |Δ| = 0.0);
  grids arm max |Δ| = 1.19e-07 — inside the grids executor's own
  run-to-run thread noise (two identical Python-arm runs differ by the same
  ~1 ULP; the mesh executor is run-deterministic, the grids one is not, so
  only the mesh arm may gate bit-exact).
- Engine ctest sweep: **125/125 passed** — including the four historically
  env-dependent names (`test_live_stroke`, `test_bsmooth`,
  `test_automask_gpu`, `test_spatial_boundary_normals`).
- `test_stroke_cancel.py` (headed, event-simulate): ESC mid-stroke keeps the
  applied dabs and the session survives (a follow-up stroke sculpts); quitting
  Blender with the modal live runs the new `cancel()` teardown without a
  traceback. Harness traps discovered: the splash *and* the first viewport
  click are each swallowed (the bench's `strokes_finished=19/20`,
  `dabs min=0` is the same loss), and an idle viewport stops drawing, so a
  draw-count warmup gate must `tag_redraw()` itself.

**Perf — interleaved headed A/B at 1M faces / L4** (4 alternating pairs,
`bench_multires_sc.py`, sculptcore engine both arms, toggle off vs on;
medians of per-run medians):

| metric | Python loop | C++ batch | delta |
|---|---|---|---|
| `stroke_ms` median | 67.6 | 59.6 | **−11.8 %** |
| `stroke_ms` mean | 65.1 | 57.2 | −12.2 % |
| `sculpt_phase_ms` | 1755 | 1590 | −9.4 % |
| `cycle_ms` median | 15.6 | 19.0 | +21 % (vsync-quantized leading edge, noise) |

`--engine-trace` confirms the removed traffic: the per-dab prop cycle
(`writeProps`/`pushDeviceInput`/`clearDeviceInputs`, 1605 calls/run ≈
1 ms/stroke of pure marshalling) drops to zero engine-side; the raw
`lib.*Batch` calls are invisible to that tracer. cProfile on the batch arm
puts `_apply_batch` at ~29 ms/stroke *tottime* — but that bucket contains the
two opaque ctypes batch calls, i.e. mostly the ~21 ms/stroke of engine dab
work §1 always said stays. True Python residue there (ray synthesis loop,
`_world_radius`, `_track_pivot`, numpy assembly) is ~6–8 ms/stroke.

**Reading vs §11's 16–28 ms prediction**: the measured win (~8 ms/stroke) is
the *bottom* of the predicted band minus the new per-event overhead the
prediction ignored. The remaining stroke time is engine dab execution
(~21 ms), redraw machinery (`draw_refresh` ~8.6 + `_mid_redraw` ~5.7 +
`stroke_end` ~7.2 ms), the spacer walk (~4 ms), and per-hit helpers still in
Python. None of that is per-dab ctypes driver cost: **the "~3× is per-dab
Python/ctypes driver cost" attribution in the perf-gap memory is now
falsified** — the next levers are the redraw path and per-hit helpers, not
deeper batching of the dab loop.
