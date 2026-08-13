# Blender brush textures in SculptCore

**Status:** design, not implemented. Written 2026-08-02 against addon `e04cd57`,
the engine submodule as vendored, and the fork's `custom-object-modes` branch.
Re-verified 2026-08-12 against addon `9cf9225` / engine `007d0bd`: every code
claim below still holds (line numbers refreshed), with **one architectural
change under it** — the default stroke path is now a per-event C++ dab batch,
not a Python per-dab loop, which moves the per-dab matrix push for
`VIEW`/`RANDOM`/`AREA` from "addon only" into engine work. See the dated notes
in §3, §6 and §8.

**Headline.** The transport is already built and mostly correct: the addon bakes
a Blender `Texture` to a grayscale tile, the engine carries it as a brush
uniform, and four kernels sample it. What is missing is the *mapping* — the
affine transform Blender applies between a sample point and a texture
coordinate. Nothing in the addon computes it, so `texture_slot.angle`,
`scale`, `offset`, rake, random, and the stencil's placement are all inert, and
the two mappings that do run are geometrically unlike Blender's.

The useful discovery is that **every non-3D map mode Blender offers is an affine
transform**, and the engine's existing `ctx.renderMatrix` hook — a full `mat4`
that only the texture path reads — can carry all of it. So five of the six map
modes are reachable with **no engine change at all**, by composing a matrix in
Python and pushing it per dab. What genuinely needs engine work is a much
shorter list than it first appears.

---

## 1. What exists today

### Addon

| Where | What |
|---|---|
| `sculptcore_addon/texture.py:58` | `_bake()` — `Texture.evaluate()` over a 128² grid on `[-1,1]²` at `z = 0`, taking `evaluate()[3]` (the intensity channel). Cached by `tex.name`. |
| `sculptcore_addon/texture.py:87` | `apply_texture()` — pushes the tile via `Brush::setTexture`, sets `coord_space` from a `map_mode` lookup, sets `tex_repeat = 1.0`. |
| `sculptcore_addon/texture.py:108` | `apply_render_matrix()` — pushes `rv3d.perspective_matrix` into `CommandExecutor::setRenderMatrix`. |
| `sculptcore_addon/handlers.py:89` | Depsgraph invalidation of the bake cache. |
| `sculptcore_addon/stroke.py:747` | Bind point — once per stroke. |
| `sculptcore_addon/ui.py:81` | Reports "Texture mapping not supported by the engine" for unmapped modes. |
| `sculptcore_addon/keymap.py:92` | Ctrl-F radial control bound to `texture_slot.angle`; `brush.stencil_control` on RMB. |

### Engine

| Where | What |
|---|---|
| `brush/brush.h:78` | `TexCoordSpace` — `Global`, `ViewPlane`, `ViewRepeat`, `StrokeCurved`, `Projected`. |
| `brush/brush.h:217` | `tex_width` / `tex_height` / `tex_pixels` / `coord_space` / `tex_repeat` on `Brush`. |
| `brush/brush.h:725` | `sampleTexBilinear` — bilinear, **clamp-to-edge**, returns `1.0` with nothing bound. |
| `brush/brush_command.h:349` | `sampleBrushTex(co, no)` — the coord-space switch. |
| `brush/brush_command.h:394` | `sampleViewUv` — `uv = (renderMatrix · co).xy / w · 0.5 + 0.5`. |
| `brush/kernels/ir/intrinsics.cc:76` | The `sampleBrushTex` DSL intrinsic; lowered by four backends. |
| `brush/compute_layout.h:59`, `gpu_marshal.cc:189` | `render_matrix` in the per-dab ctx uniform block. |

Sampling kernels: `draw`, `sharp`, `layerdraw` (engine) and `nudge` (this repo's
`brushes/`). Every other kernel ignores the texture entirely.

`renderMatrix` has exactly one consumer — `sampleViewUv`. Nothing else in the
engine reads it (checked across `source/`, excluding the emitters and the debug
app, which only thread it through; re-checked 2026-08-12 — still true after the
C++ stroke-driver and dab-batch work, neither of which touches it). **That
makes it free to repurpose as a general texture-mapping matrix.**

### The bake is faithful

`Texture.evaluate` → `texture_evaluate` (`rna_texture_api.cc:29`) →
`multitex_ext`, which is the same evaluator `RE_texture_evaluate` calls from
`BKE_brush_sample_tex_3d`. Color ramps, brightness/contrast, image
interpolation and extension are all inside it. Baking is also not a shortcut but
a requirement: the GPU kernels need a resident tile and cannot call back into
Blender per vertex the way `BKE_brush_sample_tex_3d` does per thread.

Note the domain convention that makes the rest of this work: Blender's texture
coordinate runs `-1..1` across the tile (image textures do `fx = texvec[0]/2 +
0.5` internally), the addon bakes over `[-1,1]²`, and the engine's
`sampleViewUv` ends with `· 0.5 + 0.5`. All three agree. **The engine's uv is
Blender's texture coordinate remapped by exactly `0.5·c + 0.5`.**

---

## 2. What Blender actually does

The call chain for mesh sculpting:

```
sculpt_apply_texture()                      sculpt.cc:2478
  mtex = BKE_brush_mask_texture_get(brush, OB_MODE_SCULPT)   -> &brush->mtex
  point = brush_point - cache.plane_offset
  3D    -> BKE_brush_sample_tex_3d(point)          brush.cc:942
  else  -> undo radial symmetry, symmetry_flip(point)
           AREA  -> point · brush_local_mat, × mtex->size, + mtex->ofs,
                    paint_get_tex_pixel(), then *r_value -= texture_sample_bias
           other -> project to region pixels, BKE_brush_sample_tex_3d(point_2d)
```

`BKE_brush_mask_texture_get` returns `brush->mtex` for `OB_MODE_SCULPT`
(`brush.cc:926`) — i.e. **`brush.texture` / `brush.texture_slot`, which is the
slot the addon already reads.** `brush.mask_texture` is the *color* slot in
sculpt mode and is not sampled by mesh sculpting at all; it only feeds the
cursor's secondary overlay. One texture is enough.

Inside `BKE_brush_sample_tex_3d`, per mode:

| `map_mode` | Coordinate handed to `multitex_ext` |
|---|---|
| `3D` | the object-space point, **evaluated in 3D** |
| `VIEW` | `(px - tex_mouse) / pixel_radius`, rotated by `-mtex->rot - brush_rotation` |
| `TILED` | `px / start_pixel_radius`, rotated by `-mtex->rot` |
| `RANDOM` | `VIEW`, but `tex_mouse` is a per-dab random offset and `brush_rotation` carries a random angle |
| `STENCIL` | `(px - stencil_pos)` rotated by `-mtex->rot`, divided by `stencil_dimension`; **zero outside the rect** |
| `AREA` | `brush_local_mat · point`, then `× mtex->size`, `+ mtex->ofs` |

then `intensity += br->texture_sample_bias`.

Everything but `3D` is **translate + rotate + scale**. That is the whole design.

### Two details worth recording

**`brush_local_mat` (`sculpt.cc:2866`) is motion-aligned, not arbitrary.** Its
Y axis lies in the intersection of the tangent plane and the plane of motion; X
is `Y × sculpt_normal`; Z is the sculpt normal; the origin is the dab center and
the whole thing is scaled by the stroke radius. `angle = mtex->rot +
cache->special_rotation`, where `special_rotation` is the rake angle. The
engine's `Projected` mode instead builds a basis from `ref × surfaceNo` with
`ref` flipping on `|n.z| < 0.999` — deterministic, but unrelated to the stroke,
and it *spins* as the surface normal turns.

**The bias sign is inconsistent in Blender.** `BKE_brush_sample_tex_3d` does
`intensity += bias` (`brush.cc:1041`); the AREA branch of `sculpt_apply_texture`
does `*r_value -= bias` (`sculpt.cc:2530`). Mirror the quirk rather than
"fixing" it, or AREA will not match.

### The runtime state is not exposed to Python

`tex_mouse`, `pixel_radius`, `start_pixel_radius` and `brush_rotation` live in
`bke::PaintRuntime`, which RNA exposes only through `Paint.stroke_pivot`
(`rna_sculpt_paint.cc:298`). The addon owns its own stroke loop, so it has to
compute the equivalents itself. It already has all the inputs:

- `tex_mouse` — the dab's region-space mouse position (`copy_v2_v2(tex_mouse,
  mouse)` per step, `paint_stroke.cc:264`), frozen to the anchor for anchored
  strokes and randomized for `RANDOM` (`BKE_brush_randomize_texture_coords`,
  `brush.cc:1453` — note it multiplies the random by `pixel_radius`).
- `pixel_radius` — brush radius × the size-pressure curve value; the addon
  already bakes that LUT (`stroke.py:736`).
- `brush_rotation` — rake: `atan2(dy, dx) + π/2`, updated only once the mouse
  has moved at least `paint_rake_rotation_spacing` (capped at 4 px before the
  stroke starts), otherwise held (`paint.cc:2007`). ~15 lines to reproduce.
  Plus `-random_angle/2 + random_angle·rand()` when `use_random`.

---

## 3. The core idea

The engine computes

```
uv = (M · p).xy / (M · p).w · 0.5 + 0.5
```

Take `M = S · P`, with `P` the object→clip projection and `S` a matrix whose
third row is `[0 0 1 0]` and fourth row `[0 0 0 1]`:

```
S row0 = [a b 0 c]   ->  x' = a·x + b·y + c·w
S row1 = [d e 0 f]   ->  y' = d·x + e·y + f·w
S row3 = [0 0 0 1]   ->  w' = w
```

so `x'/w' = a·(x/w) + b·(y/w) + c`. **A matrix applied in clip space, with the
`w` column carrying the translation, is an arbitrary 2D affine in NDC.** NDC↔
region pixels is itself affine, so any translate/rotate/scale Blender performs in
pixel space composes into one `mat4`.

For `AREA`, which has no perspective at all, set the fourth row to `[0 0 0 1]`
and leave the `w` component of the point at 1 — the divide becomes a no-op and
`M` is a plain object-space affine.

Because the engine's uv is Blender's texture coordinate under `0.5·c + 0.5`, the
rule to implement is a single sentence:

> **Push a `renderMatrix` whose `x, y` (after the `w` divide) *are* Blender's
> texture coordinate**, and select `TexCoordSpace::ViewPlane`.

`Global`, `ViewRepeat` and `Projected` then become unused for Blender parity.
`tex_repeat` folds into the matrix. `StrokeCurved` has no Blender equivalent and
stays as an engine-native extra.

### Per-mode recipes

Let `V = rv3d.perspective_matrix @ ob.matrix_world` (object → clip), `W, H` the
region size, `R(θ)` a 2D rotation, and `N⁻¹` the NDC→pixel affine
`px = ((ndc + 1)/2)·(W, H)`.

```
VIEW     M = R(-rot - brush_rotation) · scale(1/pixel_radius) ·
             translate(-tex_mouse) · N⁻¹ · V
TILED    M = R(-rot) · scale(1/start_pixel_radius) · N⁻¹ · V
RANDOM   VIEW, with a per-dab tex_mouse and a random angle folded into
             brush_rotation
STENCIL  M = scale(1/stencil_dimension) · R(-rot) ·
             translate(-stencil_pos) · N⁻¹ · V
AREA     M = translate(ofs.xy) · scale(size.xy) · brush_local_mat · Mobj
             (fourth row [0 0 0 1])
```

`plane_offset` is a pre-translation on all of them. Symmetry is a
post-multiplied mirror: Blender flips the *sample point* back to primary space
(`sculpt.cc:2506`), so `M_pass = M_primary · symm_rot_inv · flip`. The addon
executes each mirror image as its own dab (`symmetry.py`), so on the Python
per-dab path each pass simply pushes its own matrix.

**2026-08-12:** that per-pass push only exists on the Python path. The default
stroke path is now the C++ dab batch (`stroke.py:1209` `_apply_batch`, scene
toggle `sculptcore_cpp_dab_loop`, default on since 2026-08-10), where symmetry
mirrors are applied *inside* the engine batch call from `_mirror_flat` — Python
never sees the mirror passes. The mirror matrix therefore has to be composed
engine-side there (the engine knows the mirror signs; `symm_rot_inv · flip` is
the same per-sign composition Python would do). See §6 defect 3 for the per-dab
half of the same problem.

Everything above is `mathutils` arithmetic on data the addon already has.

---

## 4. What genuinely needs engine work

### 4.1 The texture reaches only four kernels

> **Implemented (engine, 2026-08-12).** The multiply is folded into all four
> `strength()` helpers (C++ `CommandCtx::strength`, WGSL/CUDA-HIP/OpenCL
> `brush_strength`); `draw`/`layerdraw`/`sharp` dropped their explicit calls,
> and `kelvinlet` (the only `@unbounded` kernel today — pose is not) gained an
> explicit `sampleBrushTex` multiply beside `unbounded_window()`.

Blender applies the texture through `SCULPT_brush_strength_factor`, which nearly
every brush calls. SculptCore has the same choke point: the `strength()`
intrinsic (`intrinsics.cc:44`), which lowers to `ctx.strength()` in C++
(`brush_command.h:295`) and a `brush_strength()` helper in each of WGSL, CUDA and
OpenCL. Folding the texture multiply into those four helpers gives every kernel
texture support at once, and is bit-identical when nothing is bound
(`sampleTexBilinear` returns `1.0`).

Two care points:

- The four kernels that call `sampleBrushTex` explicitly must drop the call, or
  they double-multiply. `texdraw.sbrush` uses its own inline `texture` block and
  is unaffected.
- Kernels with unbounded support are *not* allowed to call `strength()`
  (`intrinsics.cc:42` — the field is its own falloff; sema now enforces that an
  `@unbounded` kernel calls `unbounded_window()` instead, `intrinsics.cc:61`).
  Those — kelvinlet, pose, and anything else `@unbounded` — need an explicit
  `sampleBrushTex` call to stay in parity. Note also the `masks()` /
  `automasks()` split beside `strength()` (`intrinsics.cc:47`): the texture
  multiply belongs in `strength()` (it is spatial), not in the mask helpers.

This is the single change that buys the most.

### 4.2 Wrap mode

`sampleTexBilinear` is clamp-to-edge only.

- `TILED` needs **repeat**. Blender gets tiling for free because the coordinate
  grows without bound and `multitex_ext` applies the image's own `extension`
  setting.
- `STENCIL` needs **zero outside**. This one can be faked addon-side by baking a
  one-texel zero guard ring, since clamp-to-edge against zero border texels *is*
  a clip; but a real border-zero mode is cleaner and costs the same.

A `tex_extend` enum on `Brush` (clamp / repeat / clip) plus the branch in
`sampleTexBilinear` and its three emitted mirrors.

Honest limit: a *procedural* texture under `TILED` is defined over all of ℝ² and
a finite bake cannot represent it. Repeating the `[-1,1]` tile is an
approximation there. It is exact for image textures with `extension = REPEAT`,
which is the common case.

### 4.3 3D map mode — deferred

**Decision (2026-08-02, user): defer true 3D support.** Grey the mode out in
`ui.py` rather than shipping the current z = 0 slice, which is simply wrong for
3D noise.

The volume bake sketched in earlier drafts of this document (`tex_depth` on
`Brush`, a trilinear sample, a 64³ bake over the object's padded bounding box)
is *not* the intended answer and should not be built as one. It is recorded here
only so the option is not re-derived: it costs an engine uniform and a second
sampler for a result that is still a resampled approximation of a function the
host can evaluate exactly.

The two real answers are in §4.4.

### 4.4 Where procedural textures should actually live

Baking is a transport for *tiles*. It is the right answer for image textures and
an acceptable one for a 2D-mapped procedural, because the mapping is affine and
the domain is bounded (§3). It is the wrong answer for a procedural evaluated in
3D, where the function is unbounded and any bake is a resample of something the
host can evaluate exactly. Two routes out, in the order they are likely to be
taken:

**Stopgap — expose the host's texture sampler to SculptCore as a callback.**
The engine takes a function pointer (`float sample(const float3 &p)`, plus an
opaque user pointer) and the addon services it with `Texture.evaluate` /
`RE_texture_evaluate`. Exact by construction, zero bake, no fidelity argument to
have. Its cost is that it is **CPU-only and re-entrant into Python**: it puts a
host call on the per-vertex path, which kills the GPU backends for any textured
brush and is a poor fit for the ctypes boundary. Viable as a correctness
fallback for modes the tile path cannot express; not viable as the default.

**Canonical — implement the host's procedural textures inside the brush DSL.**
This is the long-term answer for DCC integration generally, not just for
Blender: a texture written in the `.sbrush` DSL lowers to a free function on
every backend, so the same definition runs on CPU and GPU and produces
bit-identical results. The vehicle already exists in prototype: the `texture`
block (`compiler/parser.cc:420`, demonstrated by
`kernels/texdraw.sbrush` — `Rings.eval(p, n)` lowering to `texRingsEval` in C++
and `tex_rings_eval` in WGSL, using only its own params plus intrinsics, which
is exactly the property that makes the two backends agree). Reimplementing
Blender's `TEX_CLOUDS` / `TEX_MUSGRAVE` / `TEX_VORONOI` / `TEX_WOOD` / … as DSL
texture functions is then mechanical, and each one is testable against
`Texture.evaluate` numerically.

**The endpoint is a runtime procedural-texture compiler** (user, 2026-08-02;
long-term goal). Today's DSL compiles ahead of time — `sbrushc`
(`compiler/sbrushc_main.cc`) is the only caller of the emitters, and its C++
output is the checked-in `kernels/generated/*.brush.gen.h` — while a host
texture is picked at runtime with arbitrary parameters. The planned resolution
is not to work around that but to remove it: a compiler that runs in-session and
**emits WGSL or SPIR-V directly**, with the CPU side served either by a small
embedded x86/ARM transpiler or by interpreting the SPIR-V.

That shape has a consequence worth stating, because it inverts how this codebase
currently keeps backends honest. Parity today is *maintained by hand* — `emit_cpp`
and `emit_wgsl` are kept in lockstep, and the comments in `brush.h` /
`brush_command.h` repeatedly note that a C++ branch and its WGSL mirror must key
off the same value "bit-for-bit in structure". A runtime compiler with a
SPIR-V interpreter (or a JIT over the same IR) makes CPU and GPU **the same
program**, so that class of drift stops being possible for anything it covers.

It also lands well against the backends that already exist. `vulkan/vk_compute.h`
loads SPIR-V today (currently derived from the sbrush WGSL offline), so a
SPIR-V-emitting compiler feeds it natively; wgpu wants WGSL, which the same
front end can emit. The CUDA and OpenCL emitters are the awkward ones — OpenCL
ingests SPIR-V, CUDA does not.

Two things the route still has to solve, neither a blocker:

- **Interim shape.** Until the runtime compiler exists, DSL texture nodes mean a
  *fixed library* selected by uniform (a dispatch switch over texture-type ids).
  That is a stepping stone, not a design to entrench — the node implementations
  carry over to the compiled path; the dispatch switch does not.
- **Parameter transport.** Each texture type carries its own parameter set
  (noise basis, depth, distortion, turbulence, a color ramp). That is a uniform
  block, sized for the union or carried as a small float array, plus a baked
  ramp LUT — the same shape as the existing falloff-curve bake. A runtime
  compiler can instead specialize the constants into the emitted code, which is
  the better answer once it exists.

Neither §4.3's volume bake nor the callback should be built as if it were the
destination. The callback is a stopgap with a known ceiling; the compiler is
where this ends up.

**2026-08-12: this section now has a concrete engine-side plan** —
`engine/documentation/plans/texture-scripts.md` (standalone `.stex` texture
units, milestones T1–T5). It keeps this section's structure (DSL textures
canonical, host sampler as the stopgap — T4 registers a `blender_tex` ctypes
sampler) but supersedes two mechanisms sketched above: the runtime CPU side is
a **C99 emitter JIT'd with embedded libtcc**, not a SPIR-V
interpreter/transpiler (and only textures compile at runtime — brushes stay
compile-time, so emitter parity stays gate-verified rather than
by-construction); and the "fixed library selected by uniform" stepping stone is
dropped for a name-keyed precompiled registry plus a `Brush::texture_program`
checked first inside `sampleBrushTex` (the seam demanded below, honored
exactly). It adds two requirements this section missed: `grad()` must
propagate through texture scripts and host samplers (chain rule / synthesized
central differences, T2), and the ctypes sampler is per-thread-unsafe against
the multithreaded CPU executor (flagged there for the T4 addon slice).

The seam this note previously left open — scripts getting raw object-space
`p` with no access to the §3 mapping — is now resolved in that plan's
"Map-mode seam" section: a texture-scope `mapPoint(p)` intrinsic returning
`(M·p).xyz / (M·p).w`, i.e. Blender's texture coordinate directly (the
bitmap path's `0.5·c + 0.5` remap stays internal to `sampleViewUv`), with
the matrix threaded as a pure argument (`TexEvalCtx`) rather than ctx
access, an exact quotient-rule autodiff dual, and `renderMatrix` shared as
the single mapping source for both consumers. The §3 per-mode recipes apply
to scripts unchanged; `TILED` repeat and `STENCIL` clip become script logic
(`fract()` / bounds check), leaving §4.2's `tex_extend` bitmap-path-only.
Per-dab/per-mirror matrix composition remains P2 work and feeds both
consumers through the same matrix.

**What this asks of the work in §8 today:** nothing, except that the texture
lookup stay behind the `sampleBrushTex` intrinsic seam so a compiled sampler can
replace the tile fetch without touching a single kernel. It already does — which
is also the argument for §4.1 (fold the multiply into `strength()`) being worth
doing now: it puts every brush behind that one seam ahead of time.

### 4.5 Cost note

Every new `Brush` uniform costs five edits — `brush.h`, `emit_wgsl.cc`,
`emit_cuda.cc`, `emit_opencl.cc` and `gpu_marshal.cc` (plus `compute_layout.h`
if it joins the ctx block). Land `tex_extend`, `tex_depth` and any bias field as
one change rather than three.

---

## 5. Bake fidelity and caching

- **128² is coarse.** Raise procedurals to 256². For `tex.type == 'IMAGE'`, skip
  `evaluate()` entirely and pull `image.pixels` with `foreach_get` at native
  resolution — orders of magnitude faster than per-texel RNA calls, and it
  removes the resample. Watch the cases `evaluate()` handles that a raw pixel
  read does not: color ramp, brightness/contrast, `use_alpha`, crop. Fall back
  to `evaluate()` when any of those are set.
- **The cache key is wrong.** `tex.name` collides across libraries and breaks on
  rename. Key on `id.session_uid`. Image edits that do not raise a depsgraph
  update (reload, external edit) need `image.is_dirty` or a
  `bpy.app.handlers.load_post`-style catch.
- **Bake the bias in.** `texture_sample_bias` is a post-eval add (and a subtract
  in AREA), so it can live in the pixels — but it belongs to the *brush*, not
  the texture, so it must join the cache key.
- **Bake cost is per stroke start.** A 256² procedural is ~65k `evaluate()`
  calls; measure before shipping, and consider baking on first use rather than
  on every `apply_texture`.

---

## 6. Defects in the current implementation

Independent of the design above, three things are wrong today:

1. **`apply_render_matrix` pushes the wrong matrix** (`texture.py:117`). Engine
   coordinates are *object* space — `stroke.py:1527` converts world → object on
   the way in — but the pushed matrix is the bare `rv3d.perspective_matrix`. It
   needs `rv3d.perspective_matrix @ ob.matrix_world`, the composition
   `gestures.py:38` already gets right. Any object with a non-identity transform
   gets a mis-projected texture in `TILED` / `STENCIL` today.
2. **`texture_slot.angle` is bound but never read.** `keymap.py:92` gives it a
   Ctrl-F radial control; nothing consumes it, so the interaction is a no-op.
3. **The matrix is pushed once per stroke** (`stroke.py:749`). `VIEW`, `AREA`
   and `RANDOM` all change per dab (`tex_mouse`, `brush_local_mat`, the random
   angle), and each symmetry image needs its own. It has to move to the dab
   path.

   **2026-08-12 — "the dab path" is no longer a Python loop.** As written this
   defect assumed one Python round-trip per dab, where pushing 16 floats
   through the bound-vector marshal is cheap and trivial. Since 2026-08-10 the
   default path for plain spaced strokes is the C++ dab batch: `_apply_batch`
   (`stroke.py:1209`) resolves a whole pointer event in one
   `MeshStroke_dabBatch` / `GridStroke_dabBatch` (or `*_dabBatchProgram` for
   autosmooth program strokes, S4/S5) call, over a 7-float-per-dab record
   (hit pos, hit normal, world radius), with symmetry expanded engine-side.
   Python round-trips per dab only on what the batch cannot express — grab
   anchoring, preview dabs, snake hook, multi-pass smooth, dyntopo
   (`stroke.py:852`) — and the toggle comment (`props.py:129`) says the Python
   path is slated for retirement, so the design must target the batch. That
   means: stroke-constant matrices (`TILED`, `STENCIL`) stay a single
   pre-batch push and remain addon-only; per-dab matrices (`VIEW`, `RANDOM`,
   `AREA` rake / random / motion-aligned `brush_local_mat`) need the batch
   record extended (e.g. +16 floats per dab, or the few scalars — `tex_mouse`,
   angle — the engine composes into a matrix itself), and the per-mirror
   composition of §3 done engine-side. That is engine work, moving those
   modes out of P1 (§8).

Also worth a second look: the existing `VIEW_PLANE → Projected` and
`STENCIL → ViewPlane` choices in `_COORD_SPACE` are not the modes' Blender
semantics (`VIEW` is a screen-space disc that does not foreshorten; `STENCIL` is
a placed, clipped rectangle). Both are superseded by §3.

---

## 7. Out of scope here

- **Color textures.** `tex_pixels` is grayscale; a paint brush that wants RGB
  needs a second channel set. Blender's sculpt path only ever uses intensity, so
  this is a SculptCore-native feature, not parity work.
- **The cursor overlay.** `use_primary_overlay` / `texture_overlay_alpha` draw
  the texture under the cursor disc. The addon's external-draw cursor
  (`cursor.py`) draws nothing of the sort. Purely visual, but its absence makes
  a textured brush hard to aim.
- **`calc_vertex_displacement`** (`sculpt.cc:2545`) — Blender divides a textured
  draw brush's displacement by `mtex->size²` and rotates it through
  `brush_local_mat_inv`, making the displacement direction anisotropic with the
  texture. A refinement to consider after the mapping is right.
- **`StrokeCurved`** — an engine mode with no Blender counterpart. Leave it.

---

## 8. Suggested phasing

**P1 — addon only, no engine rebuild.** Fix the object-matrix bug; build the
stroke-constant matrix for `TILED` / `STENCIL` including angle, scale, offset,
stencil placement and bias; zero guard ring on the bake for `STENCIL`; image
fast path and the `session_uid` cache key.

*(2026-08-12: P1 originally also covered the per-dab modes — "move the push to
the dab path" — because the dab path was a Python loop. With the C++ dab batch
now the default (§6 defect 3), per-dab matrices for `VIEW` / `RANDOM` / `AREA`
plus rake, random and per-mirror composition require the batch ABI to carry
them, so they move to P2. What stays in P1 is exactly what is constant across
a stroke.)*

**P2 — engine.** Per-dab mapping through the dab batch: extend the batch
record (or pass the scalars the engine composes itself) for `VIEW` / `RANDOM` /
`AREA`, with the §3 mirror composition done engine-side. Texture folded into
`strength()` (plus explicit calls in the `@unbounded` kernels), `tex_extend`.
One submodule change, four emitters, a DLL rebuild and re-vendor.

**P3 — optional.** Cursor overlay; RGB textures.

**Not scheduled.** 3D map mode (§4.3), and behind it the procedural-texture
question (§4.4). When it is taken up, it is taken up as DSL texture nodes, not
as a volume bake — with a host-sampler callback as an interim correctness escape
hatch if one is needed sooner. *(2026-08-12: the engine-side plan for exactly
that now exists — `engine/documentation/plans/texture-scripts.md`; see the note
in §4.4 for what it supersedes here and the map-mode seam it leaves open.)*

### Validating it

Parity here is numeric, so check it numerically rather than by eye: for a fixed
brush, texture, view and dab, sample Blender's own
`BKE_brush_sample_tex_3d` path against the engine's at a set of surface points
and diff. The headless-convert-test harness already knows how to stand a session
up without the GUI. A GUI A/B — the same stroke in vanilla sculpt and in the
mode, on a rotated, non-uniformly scaled object — catches the matrix-composition
errors that a face-on identity-transform test cannot.
