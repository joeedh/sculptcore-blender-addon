# Plan — adopt the engine's C++ `BrushStrokeDriver` as the addon's sampler

Replace the addon's Python stroke sampler (`StrokeSpacer` + `stroke_math` +
per-dab raycasting) with the engine's `sculptcore::brush::BrushStrokeDriver`
(`engine/source/brush/stroke_driver.{h,cc}`, engine commit `9a22ee8`), keeping
every dispatcher-side concern in Python.

> **Revised 2026-08-04 after the grids-native wiring (W1/W2)** — see the
> "Grids-native interaction" section below; it changes how phase 1 must
> handle multires sessions, and re-scopes the expected perf win.

## Why

- One sampler instead of two. The C++ driver is a statement-for-statement port
  of the reference TS app's `stroke_driver.ts`, so the addon stops being a
  weaker reimplementation and inherits fixes made for the app.
- Double precision throughout the spline + arc-length carry (ours is Python
  float, which is fine, but the carry accumulates over a whole stroke).
- Per-dab pressure/tilt/twist interpolation across a segment, which we do not
  do today (every dab of a segment reuses the arriving event's pressure).
- Deletes ~250 lines of Python whose only purpose is to mirror engine behavior.
- **Perf expectation (measured 2026-08-04):** this is a correctness /
  maintenance plan, not the next big perf lever. The W1 headless profile at
  the 1 M multires bench puts the whole Python sampler side at ~0.05 ms/dab
  (`apply_dab_state` 0.016 + raycast 0.033) — the end-to-end multires gap is
  dominated by the 30 Hz draw-refresh cadence, the per-stroke store blob and
  the enter cost (see `research/grids-native-brush-path-results.md`, W1/W2
  addendum). Plain-mesh / dyntopo strokes were not re-measured and may
  benefit more.

## What is in scope

The driver's own docs are explicit: **the sampler only**. Symmetry, per-dab
brush policy, dyntopo cadence, preview rollback, undo and the GPU path stay
host-side. This plan does not move any of them.

## Grids-native interaction (added 2026-08-04, after W1)

The multires wiring changed the sampler's surroundings in ways phase 1 must
respect:

- **The driver raycasts the mesh `SpatialTree` it is constructed with**
  (`BrushStrokeDriver::rayCast` → `tree_->castRay`). On a grids-native stroke
  the addon no longer runs per-dab `updateQueries` — the ride-along mirror
  keeps the slot mesh's *positions* current but its tree *bounds* refresh at
  best at the 30 Hz draw cadence (never, headless). `stroke.raycast` therefore
  routes grids sessions through `GridTree_castRay` (domain bounds refresh per
  dab engine-side), gated on last-stroke-grids + level + domain liveness.
  Constructing the driver with `session.tree()` and letting it re-raycast
  control points would sample a stale-bounded tree mid-stroke — the exact
  failure `_refresh_queries` existed to prevent.
- **Resolution for phase 1:** for multires sessions, use the driver as a
  *pure spacer* and re-raycast each emitted `screenP` host-side through
  `stroke.raycast` (the fallback already described under "Known behavior
  change", promoted to *required* on grids sessions; it costs ~0.03 ms/dab).
  Plain-mesh sessions may use the driver's own raycast as planned. If the
  split reads badly, the alternative is an engine seam — a ray-source hook on
  `BrushStrokeDriver` (or a `GridTree` adapter with the `castRay` contract) —
  but that is engine work this plan should not start with.
- **The sampler seam itself is untouched by W1**: the grids dispatch happens
  inside `apply_dab`/`apply_grab_dab`, *below* `_apply_spaced_dab`, so
  phase 1's "only the spaced-dab branch changes" scoping still holds.
- **Validation additions:** the parity script's reference raycast is now the
  branchy `stroke.raycast` (grid tree on grids sessions); the in-viewport A/B
  list (1.4) must include a multires grids-native stroke of a roster kernel,
  checked against the per-dab raycast-currency behavior (snake hook / grab
  style "stroke dies mid-drag" is the failure mode to look for).

## Preconditions (already true, verify before starting)

- The driver is in the recorded submodule gitlink — **no submodule bump
  required**. (Originally verified at `engine @ 4b32dae` ⊇ `9a22ee8`; the
  gitlink has since advanced through the grids-native work to `68cdea8`+,
  which still contains it.)
- It is bound through litestl (`engine/source/brush/bindings.cc`), so the
  ctypes runtime builds the class automatically. `sampleAt(i)` returns a
  **non-owning** `DabSample` wrapper, or `None` for an out-of-range index
  (`engine/python/sculptcore/_classgen.py:294`).
- Work items: rebuild + re-vendor the DLL
  (`node tools/build-blender-dist.mjs`, which passes `--kernels-extra
  ../brushes` — a bundle without it makes the addon report `kernel 'NUDGE'
  missing`), and regenerate the stubs (`python -m sculptcore._gen`, cosmetic —
  typing only).

---

## Phase 1 — the PATH sampler

The only code path that changes is the `else` branch of
`SCULPTCORE_OT_brush_stroke._dab_at` (the spaced-dab branch) plus the trailing
flush in `_finish`. Grab-class and the ANCHORED/DRAG_DOT preview methods branch
away before the spacer today, so they are untouched.

### 1.1 New module `sculptcore_addon/stroke_driver.py`

Owns the engine driver and the Blender→driver view conversion. Nothing else in
the addon should know about `setViewRow` conventions.

- `make_driver(session)` — `mgr.get_struct("sculptcore::brush::BrushStrokeDriver")
  .find_constructor("main")` + `mgr.construct_with(ctor, session.tree())`, the
  same pattern `stroke._ensure_executor` uses for `CommandExecutor`.
  **Construct per stroke, in `invoke()`** — the driver caches the raw
  `SpatialTree*`, and `session.tree_ptr` is replaced by a resync or a topology
  rebuild. Dispose in `_finish`/`_finish_preview`.
- `push_view(driver, context)` — call once per event batch, before `push()`:
  - **Matrices are row-vector.** The driver's `Mat4` composes left-to-right, so
    feed transposes: `mt = rv3d.perspective_matrix.transposed()` →
    `setViewRow(0, r, *mt[r])`; `ot = ob.matrix_world.transposed()` →
    `setViewRow(1, r, *ot[r])`, with `hasObjectMatrix=True`.
  - **Camera position** = `rv3d.view_matrix.inverted().translation`.
  - **Ortho:** the driver derives every ray as
    `normalize(unproject(px) - cameraPos)` — one camera point, no ortho path.
    For `rv3d.is_perspective == False`, push a *virtual* eye far back along the
    view axis (`eye - forward * BIG`); the near-plane unprojection is still
    exact, so the ray error is `screen_extent / BIG × depth` and vanishes for
    `BIG ≈ 1e6 × scene scale`. Validate empirically (see 1.4) — Blender's
    numpad views are ortho and sculptors live in them, so this must be right
    before the toggle flips on by default.
  - `viewSize` / `glSize` = `(region.width, region.height)`; `camNear` =
    `context.space_data.clip_start`.
  - `spaceMode = SCREEN`, `strokeMethod = PATH`, `radiusIsWorld = False`.
- `push_event(driver, coord, ...)` — **y flips**: the driver's
  `project`/`unproject` are top-left-origin (web convention), Blender's
  `mouse_region_y` is bottom-left. Push `region.height - y`; flip `screenP`
  back on the way out.
- `poll_dabs(driver)` — generator yielding a small plain namedtuple per sample
  (`center`, `normal`, `screen`, `pressure`, `invert`, `hit`) read out of the
  `DabSample` wrapper. **Read before the next `poll()`**: `poll()` clears
  `out_`, so held wrappers dangle.

### 1.2 Spacing

`SCREEN` mode computes `spacingDist = spacing * 2 * radiusPx`. Feeding
`spacing = brush.spacing / 100.0` and `radius = pixel_radius` reproduces
vanilla's `radius * spacing / 50` (`#paint_space_stroke_spacing`) exactly — the
same interval `_dab_at` walks today. No compensation factor needed.

### 1.3 What stays in Python

- **World radius.** Ignore `DabSample.radius`: the driver's `worldRadiusAt` is
  a fov-agnostic `radiusPx / max(glSize) × |w|`, not Blender's
  `paint_calc_object_space_radius`. Keep `_world_radius(context, brush,
  position)` per dab, off the emitted center. (It is also wrong under ortho,
  where `w == 1` — another reason not to use it. It only feeds WORLD spacing
  and `radiusIsWorld` anchored radius, neither of which we enable.)
- **Dyntopo cadence.** `DabSample.strokeS` accumulates the *spacing fraction*,
  not pixels, while `_dyntopo_spacing` is `frac * 2 * pixel_radius` in pixels.
  Keep the host-side `self._stroke_s += self._last_spacing` accumulation
  unchanged rather than converting units.
- **Snake hook.** `_snake_hook_advance` needs a drag measured on the
  view-facing plane through the seed point; the driver has no equivalent for
  PATH mode. Keep `_coord_on_plane` and feed it the flipped `screenP`.
- Everything from `_apply_spaced_dab` down: mirrors, pressure LUTs, smooth
  multi-pass, `apply_dab_state`, preview, undo.

### 1.4 A/B toggle + validation

- Scene bool `sculptcore_cpp_stroke_driver` in `props.py` (same style as
  `sculptcore_dyntopo`), **default False**, surfaced in the dyntopo/dev panel
  in `ui.py`. `_dab_at` picks the sampler off it; both paths must live side by
  side until phase 1 is signed off.
- **Headless parity script** `claudeMemory/scripts/stroke_sampler_parity.py`:
  no `bpy` — build an engine mesh + tree, feed a canned pixel path and a canned
  view matrix to (a) `StrokeSpacer` + `stroke.raycast` and (b) the driver, and
  diff emitted centers. This is the cheap regression gate for the matrix /
  y-flip / spacing conversions, and it runs without a GUI.
- **In-viewport A/B** (the part the script cannot cover): perspective *and*
  ortho, a fast flick stroke, a stroke that leaves the mesh and returns, a
  stroke on a heavily deforming surface (clay at large radius), symmetry on,
  dyntopo on, snake hook, tablet pressure.

### 1.5 Deletions once the toggle flips

`stroke.StrokeSpacer`, `sculptcore_addon/stroke_math.py` (whole file),
`_ray_from_coord` / `_ray_from_event` if nothing else uses them, and the
now-dead spacer bookkeeping (`_last_spacing`, `_last_invert`,
`_last_pressure`) — plus the `stroke.py` module docstring paragraph that
describes the Python spacer.

---

## Phase 2 — ANCHORED / DRAG_DOT

`_dab_preview` currently hand-rolls what the driver has as
`StrokeMethod::Anchored` / `DragDot`:

- ANCHORED: `projectOntoAnchorPlane` is `_cursor_on_anchor_plane`;
  `DabSample.anchorVec` is the object-local drag vector; `liveAngle` is the
  cursor angle we do not expose yet; the drag-length radius replaces
  `_pixel_to_world_length(context, center, drag_px)` — but only with
  `radiusIsWorld`, which we are not using, so keep computing the radius
  host-side from the screen drag.
- DRAG_DOT: one dab per input at the live cursor, which is exactly the
  `else` branch.

The preview bracket (`beginPreviewDab` / `rollbackPreviewDab` /
`commitPreviewDab`) and the mirror grouping stay exactly as they are — the
driver emits samples, it does not know about preview.

Do this only after phase 1 is default-on, and reuse the same toggle.

## Phase 3 (optional) — grab-class

Grab could ride ANCHORED + `anchorVec` instead of `_cursor_on_anchor_plane` +
`_drag_origin`, but it goes through `mapping.drag_offset` (normal weighting,
strength scaling) which the driver knows nothing about, and the current path
works. Leave it unless phase 2 makes the seam obviously nicer.

---

## Known behavior change (decide during 1.4)

**Interpolated dabs are not re-projected onto the surface.** Today every spaced
point is raycast at apply time; the driver evaluates the Catmull-Rom between
control-point hits, so intermediate dabs chord-cut a curved surface and do not
track geometry deforming under the stroke. `stroke.py`'s module docstring
advertises the current behavior explicitly ("each spaced point is projected
onto the surface, so stroke density is independent of ... the surface deforming
under the stroke").

In practice mouse events usually outnumber dabs, so this only bites on fast
strokes at large radius — but it is the one difference that could look worse
rather than merely different. If it does, the fallback is a host-side
re-raycast of each emitted `screenP` (keeping the driver purely as the spacer),
which still deletes `stroke_math` and the spacer.

## Adjacent cleanup unlocked by the same engine commit

`9a22ee8` also fixes `SpatialTree::castRay`: the barycentric weights from
`rayTriIsect` were applied cyclically rotated, so **every** reported hit
position and normal was wrong. Two `stroke.py` comments cite that bug as their
rationale (line numbers drifted with the W1 wiring — anchor on the text):

- "castRay's reconstructed hit sits off the mouse ray" (near the grab
  anchoring in `_dab_at`, ~line 841 as of W1) — `_drag_origin` taken from a
  plane projection rather than the anchor.
- "castRay reconstructs the hit position imprecisely" (the symmetry comment
  in `_apply_spaced_dab`'s caller, ~line 1062 as of W1) — symmetry reflects
  the resolved hit rather than re-raycasting the mirrored ray.

Reflecting the resolved hit is still what vanilla sculpt does and should stay,
but **both comments are now stale** and the anchored-drag workaround may be
droppable. Fix the comments as part of phase 1; re-test the anchored drag
before removing anything. The memory note `sculptcore-castray-imprecise` needs
updating to record the fix.

## Risks

| Risk | Mitigation |
|---|---|
| Driver raycasts a stale-bounded mesh tree on grids strokes | Pure-spacer mode + host-side `stroke.raycast` for multires sessions (see "Grids-native interaction") |
| Ortho ray synthesis wrong | Parity script + explicit ortho pass in 1.4; the toggle stays off until it matches |
| Matrix convention / y-flip silently off by a transpose | Headless parity script diffs centers against the current sampler |
| Interpolated dabs read worse on deforming surfaces | Documented above; fallback is host-side re-raycast of `screenP` |
| ctypes cost per dab (a wrapper + ~8 member reads) | Measure in the A/B; read only the fields listed in 1.1, not all 31 |
| Stale `DabSample` wrappers after the next `poll()` | Copy out in `poll_dabs` before returning |
| Driver holds a dangling `SpatialTree*` after a rebuild | Construct per stroke in `invoke()`, never cache on the session |

## Rollback

Everything is behind `sculptcore_cpp_stroke_driver`. Until 1.5 runs, flipping
the scene bool restores the Python sampler with no code change.
