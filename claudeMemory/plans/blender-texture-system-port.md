# Port Blender's legacy texture system (procedurals + texture nodes) to `.stex`

> **Revision 2 — 2026-08-14.** Rev 1 was pressure-tested by five adversarial
> agents reading engine/fork source, two of them checking empirically against a
> headless Blender 5.3 build of the fork. It did not survive intact: the
> validation oracle it specified returns **constant 0.0** for 9 of its 10 target
> types, one target type is not a function of position at all, the transcendental
> intrinsics it adds cannot link in the JIT, and its single largest line item
> (WGSL twins) is unreachable from the addon. This revision applies those
> findings, re-scopes, and records what was rejected so it is not re-derived.
> Rev 1's own citations were ~85% accurate; the corrected ones are inline below,
> and §6 lists what the pressure test *confirmed* so those questions stay closed.

## Context

The addon already routes 3D-mapped brush textures through a runtime `.stex`
texture-script program instead of a 128×128 bake (`sculptcore_addon/texture.py`,
precedent `sculptcore_addon/stex/clouds.stex`), approximating Blender's Clouds
texture with the engine's `vnoise` builtin — visually similar, not bit-identical.

The goal is to extend that coverage to the remaining legacy procedural types.
**The fidelity target is no longer bit-exactness** (see §5.1) and **the legacy
texture-node compiler is cut** (see §5.2). What survives is a smaller, testable
plan: fix the mapping bugs that affect every texture type today, build a *real*
parity oracle, then port the types that need no new native noise code.

---

## Part 0 — Prerequisites (do these first; they are not optional)

These are bugs in shipped code. Porting more types on top of them multiplies
them by 9, and the parity harness cannot be written correctly until the oracle
question below is settled.

### 0.1 The oracle: `evaluate()[3]`, not `[0]`

`rna_texture_api.cc:29-38` returns `(trgba[0], trgba[1], trgba[2], tin)` —
**intensity is index 3**. Every intensity-only procedural (`blend`, `wood`,
`marble`, `stucci`, all three musgrave wrappers, `mg_distNoiseTex`, grayscale
`clouds`) writes only `texres->tin` and never touches `trgba`, which stays
zero-initialized. Measured headless on this fork:

```
BLEND    [0]=0.000000 [3]=0.565000     WOOD     [0]=0.000000 [3]=0.984945
MARBLE   [0]=0.000000 [3]=0.921574     STUCCI   [0]=0.000000 [3]=0.778649
MUSGRAVE [0]=0.000000 [3]=0.548766     VORONOI  [0]=0.000000 [3]=0.619662
DISTORTED_NOISE [0]=0.000000 [3]=-0.095817
MAGIC    [0]=0.011155 [3]=0.433201   <- the only type where [0] is meaningful
```

`_bake_procedural` (`texture.py:132-154`) already encodes this correctly and
documents why. **Reuse that branch; do not invent a new one.**

The brush's actual path is `RE_texture_evaluate` (`texture_procedural.cc:1040-1108`),
not `multitex_ext`, and it differs in two ways the harness must replicate:

- `:1096-1098` — when the texture returned RGB, `tin` is **overwritten** with
  `IMB_colormanagement_get_luminance(trgba)`. `evaluate()` applies no such
  collapse and hands back the *pre-collapse* `tin` in slot 3.
- `:1061-1080` — applies `mtex->size`/`ofs` and the `projx/y/z` swizzle before
  `multitex`. `evaluate()` passes `mtex = nullptr` and applies none of it.

So the oracle is an explicit Python reimplementation of `RE_texture_evaluate`'s
tail: `intensity = luminance(rgb) if type_returns_rgb else evaluate(p)[3]`, with
the harness forcing `slot.scale=(1,1,1)`, `slot.offset=(0,0,0)` and default
projection so the placement transform is identity.

### 0.2 Fix `use_rgb`'s classification (`texture.py:141`) — **done 2026-08-14**

Landed as `_returns_rgb(tex)`, which also covers a case this section missed:
**every node-tree texture**, since `ntreeTexExecTree` ends with an
unconditional `retval |= TEX_RGB` (`node_texture_tree.cc:351`) — the Output
node's own `tin = (r+g+b)/3` is computed and then thrown away by the luminance
collapse. A node-tree texture was baking flat black.

`use_rgb = tex.use_color_ramp or tex.type == 'MAGIC'` misses two RGB-returning
cases, both of which populate `trgba` and are currently read as `v[3]`:

- `CLOUDS` with `cloud_type == 'COLOR'` (`texture_procedural.cc:129-147`)
- `VORONOI` with `color_mode != 'INTENSITY'` (`:507-548`)

Measured: `clouds COLOR: [0]=0.647259 [1]=0.606553 [2]=0.809351`,
`voronoi POS: [0]=0.683875 …`. Fix this **before** the harness encodes the
current classification as expected behaviour.

### 0.3 Two live bugs in `clouds.stex` — the file every port is templated on — **done 2026-08-14**

Both fixed; the recompile was verified against `engine/build/python`
(`setTextureScript` returns true, `no_clamp` lands at param slab index 5).
One correction: **the projection swizzle is a non-issue.** `MTex` defaults to
`PROJ_X/Y/Z` (`DNA_texture_types.h:315`) and `TextureSlot` RNA exposes no way
to change it, so a brush slot never permutes axes — bullet 1 is purely about
the offset/scale order. Recorded in the `.stex` comment so no later port
re-adds a swizzle.

Also gated: **Clouds in `COLOR` mode now falls back to the bake**
(`_script_supports()`), rather than the script silently ignoring the setting.
Color mode is three turbulence fields on swizzled coordinates folded through
`BRICONTRGB` and then luminance; a texture block admits exactly one `eval` and
**no helper functions** (`parser.cc:536-560`), so it would be three inline
turbulence loops at ~3× the per-dab cost. Not worth it unbidden — the bake
evaluates the real thing, just tiled.

1. **Placement order.** Blender computes `texvec[i] = size[i] * (vec[proj-1] + ofs[i])`
   — offset **before** scale, with a projection swizzle. `clouds.stex:34-36`
   computes `(p.x * sx + ox) * scale` — offset **after** scale, and ignores
   `projx/projy/projz` entirely.
2. **Unconditional clamp.** New textures get `TEX_NO_CLAMP` set by default
   (`DNA_texture_types.h:396`), and `BRICONT` (`texture_common.h:15-25`) clamps
   only when that flag is *clear*. `clouds.stex:53` clamps unconditionally.
   Blender's `tin` legitimately leaves `[0,1]`: DistortedNoise returns
   `-0.199972` at defaults. Add a `no_clamp` param from `not tex.use_clamp` and
   gate the clamp; wire it in `_script_params`.

Also note `BRICONT` is the scalar fold; RGB types take `BRICONTRGB`
(`texture_common.h:27`), which round-trips through HSV for `tex->saturation`.
And **Magic computes `tin` *before* `BRICONTRGB`** (`texture_procedural.cc:355-357`),
so bright/contrast do not affect it at all — a shared epilogue diverges on
what §3 makes the first landing. Per-type epilogue, not one shared tail.

### 0.4 The map-mode defects (`design/blender-brush-textures.md` §6)

Recorded 2026-08-02, re-verified 2026-08-12, still live. They break **four of
six map modes for every texture type**. This work reaches more users than the
whole of the rest of this plan, which targets `map_mode == '3D'` only. **Land
it first.**

Rev 2 asserted all four were "addon-only, and need no rebuild". Two are; two
are not — corrected below, and **done 2026-08-14** to the extent the addon can
reach:

- ✅ `apply_render_matrix` pushes bare `rv3d.perspective_matrix`
  (`texture.py:456-458`), missing `@ ob.matrix_world` — every `TILED`/`STENCIL`
  texture on a transformed object is mis-projected. *Fixed:* composes
  `rv3d.perspective_matrix @ ob.matrix_world`, the same product `gestures.py:38`
  uses, since engine coordinates are object space.
- ✅ `RANDOM` is missing from `_COORD_SPACE` (`texture.py:44-50`), so the texture
  is dropped and `ui.py:80-81` prints "Texture mapping not supported". *Fixed:*
  mapped to `Projected` (4). The per-dab randomization it names is still absent
  — reported by `mapping_note()` rather than silently approximated.
- ❌ **Engine work, not addon work:** `texture_slot.angle` is bound to Ctrl-F
  (`keymap.py:47`, `:92-93`) and read nowhere in the addon — a shipped no-op
  interaction. The rotation *cannot* be folded into the pushed `renderMatrix`:
  `ViewRepeat` post-applies `fract(uv.x·viewAspect()·repeat, uv.y·repeat)`
  **after** `sampleViewUv`'s `·0.5 + 0.5`, and `viewAspect()` is itself derived
  from the pushed matrix (`|row1| / |row0|`), so the composition is not an
  affine carrier for a rotation. Nor can `TILED` be re-expressed as a plain
  `ViewPlane` matrix carrying the rotation: `sampleTexBilinear` is
  clamp-to-edge only, so tiling would be lost. Needs engine `tex_extend`
  (design doc §4.2). Meanwhile a non-zero `angle` / `use_rake` / `use_random`
  raises a `mapping_note()` in the N panel.
- ❌ **Engine work, not addon work:** the matrix is pushed once per stroke
  (`stroke.py:747-749`); `VIEW`/`RANDOM`/`AREA` need it per dab. The C++ dab
  batch (`_apply_batch`, 7 floats/dab) has been the default stroke path since
  2026-08-10, so per-dab matrices are an ABI extension — design doc §6 defect 3,
  phased to P2.

The two addon fixes shipped alongside `mapping_note()` / `_MAPPING_NOTES`
(`texture.py`, surfaced by `ui.py`), which states in one line what a given
brush's mapping approximates, so the remaining gaps are visible instead of
silent.

---

## Part 1 — Infrastructure

### 1.1 Standalone single-point eval API (engine + addon)

No Python-reachable way exists to evaluate a compiled `TextureProgram` outside a
stroke. Add a reflected `Brush` method next to `setTextureRampAt`
(`engine/source/brush/brush.h:879`, bound at `:475`), following `sampleBrushTex`
(`engine/source/brush/brush_command.h:359-374`):

```cpp
float evalTextureAt(float px, float py, float pz, float nx, float ny, float nz)
{
  if (!texture_program) return 0.0f;
  const float P[3] = {px, py, pz};
  const float N[3] = {nx, ny, nz};
  const float *params = texture_params.size() > 0 ? texture_params.data() : nullptr;
  return texture_program->eval(P, N, params, nullptr);   // see note
}
```

**Correction to rev 1:** it proposed `TexEvalCtx tctx{}` with the comment
"identity". `TexEvalCtx` is `{float map_matrix[16]}` (`texture_eval.h:24-27`) and
value-init **zeroes** it, so `texMapPoint` collapses every point to the origin —
the exact opposite of identity, and silently, since the branch only runs when
the script *does* call `mapPoint()`. Pass `nullptr`: `texMapPoint` returns `p`
unchanged for a null context (`texture_eval.h:35-37`). Assert `!usesMap` in the
harness rather than fabricating a matrix — a script that maps points needs the
real `renderMatrix` and must be tested through the stroke path.

`BIND_STRUCT_METHOD(st, evalTextureAt, MARGS("px","py","pz","nx","ny","nz"));`
Scalar floats only, matching every other bound `Brush` method. Verified: the
`MethodBuilder` is fully variadic with no arity cap (`binding_method.h:109-195`),
and reflected methods reach Python **fully dynamically** — `Manager._load()`
reads the descriptor registry at import and synthesizes methods
(`_classgen.py:249-267`), so no binding regeneration and no `engine.py` change.
The `types/*.pyi` stubs are pyright-only; stale ones cost nothing at runtime.

Compilation is **eager** — `setTextureScriptSource` calls `compileTextureScript`
inline (`brush.h:811-824`) and seeds `texture_params` from the program defaults
— so `evalTextureAt` sees a live program with working defaults immediately after
`setTextureScript`, with no stroke-time bind step skipped.

Addon wrapper in `texture.py`:
```python
def eval_texture_at(sc_brush, p, n):
    return sc_brush.evalTextureAt(p[0], p[1], p[2], n[0], n[1], n[2])
```

### 1.2 ~~`blender_tex` DSL-visible host sampler~~ — CUT

Rev 1 proposed registering a host sampler that calls back into Python to invoke
`Texture.evaluate()`, as an "inverse-direction oracle". Cut: **both sides of the
comparison are already reachable from Python** — `Texture.evaluate()` directly
and `evalTextureAt` via §1.1 — so this adds a C-to-Python-callback component
that must itself be debugged in order to debug the thing under test, and buys
nothing the harness cannot do in two lines. It also inherited the `[0]`-vs-`[3]`
bug of §0.1 in its body.

### 1.3 DSL intrinsic gaps — a **four**-site edit, not two

Rev 1 called this "two tables ... a hard gate". It is four sites, and it missed
the two that decide whether the JIT links at all. The emitted texture TU is
**freestanding**: `emit_c.cc:735-746` declares exactly five externs, and
`texture_program.cc:212-218` runs `tcc_set_options(s, "-nostdlib")` and hand-binds
exactly `sinf`, `cosf`, `sqrtf`, `floorf`, `fabsf` (verified). `powf`/`atan2f`/
`expf`/`logf` are neither declared nor bound: a script using them compiles in the
DSL, emits valid C, and dies at `tcc_relocate` with an unresolved symbol —
`compileTextureScript` returns null and `setTextureScript` returns false.

| # | Site | What to add |
|---|---|---|
| 1 | `emit_c.cc:53` `kCIntrinsics[]` | the lowering entries (verified: 15 entries, none of the new names present — no conflicts) |
| 2 | `emit_c.cc:742-746` `emitPrelude()` | `extern float powf(float,float); atan2f; expf; logf;` |
| 3 | `kernels/ir/intrinsics.cc:39-127` `sIntrinsicsRaw[]` | keep in sync per that file's convention |
| 4 | `texture_program.cc:88-107`, `:214-218` | `jitPowf`/`jitAtan2f`/`jitExpf`/`jitLogf` wrappers + `tcc_add_symbol` lines |

The wrappers matter: the existing `jitSinf` comment (`:86-87`) exists because
routing through `std::pow` keeps the JIT and the precompiled cpp path in
agreement. Check whether `texture_jit.cc:24` (also `-nostdlib`) needs the same.

Mapping (C99 / WGSL). `mod` must **not** use WGSL's truncated `%`:

```
pow(a,b)          -> powf(a,b)                        | pow(a,b)
atan2(a,b)        -> atan2f(a,b)                       | atan2(a,b)
exp(a)            -> expf(a)                           | exp(a)
log(a)            -> logf(a)                           | log(a)
mod(a,b)          -> (a - b*floorf(a/b))               | (a - b*floor(a/b))
step(edge,x)      -> (x < edge ? 0.0f : 1.0f)          | step(edge,x)
smoothstep(a,b,x) -> inline clamp+t*t*(3-2t) expand    | smoothstep(a,b,x)
```

`sIntrinsicsRaw`'s macro is `INTR_CWGO(NAME, RET, ARITY, ARGS, CPP, WGSL, GPU, OCL)`
(`intrinsics.cc:31-32`) — four backend spellings, not two; fill the C++ slot
(`std::pow`) or accept a "no emit pattern" error if a precompiled `.sbrush` ever
uses it inline. Note the two tables are **not** symmetric gates: `emit_wgsl.cc:657-666`
falls through unknown call names to WGSL's own resolver, so the WGSL side fails
late at Tint rather than at emit.

**Also**: `emit_c.cc:588-596` holds a *third* table, `kDualIntrinsics[]`, gating
what may appear in a differentiated body (backed by the `sbd_*` prelude at
`:818-835`). It is not a compile gate — `emitTextureFnDual` silently rolls the
dual body back (`:1027-1034`) — but any ported type using `pow`/`exp`/`log`
silently loses `TextureProgram::evalDual`. Add `sbd_pow`/`sbd_exp`/`sbd_log` if
that matters; otherwise record the loss.

**DSL constraints to design around** (verified): `BinOp` (`ir.h:45-50`) has
`BitAnd`/`BitOr`/`BitXor` but **no shifts and no modulo**; runtime `int` params
are rejected outright (`parser.cc:495` — "int params must be @const"); `float4`
has a `TypeKind` and passes `isVectorType`, but `cTypeName` has no case for it
so a declared `float4` local fails at emit, and `.w` is rejected at
`emit_c.cc:335-337`. Runtime `if`/`else if`/`for` on a non-`@const` `param float`
**is** legal on both emitters (`emit_c.cc:681-701`, `emit_wgsl.cc:884-928`) —
`clouds.stex:42-56` already does exactly this, so a runtime basis switch is
sound. `@const` params inline as literals with **no dead-branch elimination**, so
every branch's samplers still land in `samplerDeps`.

**Do not use `continue` in a ported `.stex`**: `emit_wgsl.cc:971-973` lowers it
to `return;`, which is invalid inside an `f32`-returning eval. CPU emits it
correctly, so this fails only at Tint validation.

### 1.4 The parity harness (`tools/verify_texture_parity.py`) — **done 2026-08-14**

Headless, following the `tools/verify_addon.py` / `smoke_test_package.py`
convention (bare `assert` + `sys.exit(1)`, `--python-exit-code 1`, no pytest).
Per type: build a `bpy.data.textures.new(type=...)` with seeded-random settings,
compile the matching `.stex`, push params, sample N points, and compare
`eval_texture_at` against the §0.1 oracle.

**Harness invariants** (each one is a bug rev 1 would have shipped):

- Force `slot.scale=(1,1,1)`, `slot.offset=(0,0,0)`, default projection, and
  assert it — the `.stex` bakes placement into `eval()` (`clouds.stex:34-36`)
  while `evaluate()` applies none, so without this every type fails for reasons
  unrelated to the ported math.
- Use the §0.1 intensity rule, not `[0]`.
- Assert `!usesMap`.
- Exclude `TEX_NOISE` entirely (§5.3).

**Tolerances are measured, not asserted.** Rev 1's table was invented. A ULP
sweep on this box put DistortedNoise at 2.43e-4 and Musgrave(fbm, 8 octaves,
CRACKLE) at 1.89e-4 against a proposed 1e-3 bucket — under 5× headroom before
ordinary reassociation noise reads as failure. Worse, cell noise is piecewise
constant: a 1e-6 *relative* coordinate shift produced a **0.1588** jump (1 point
in ~4000 over 1e-2), because the port crosses cell borders at slightly different
coordinates than the reference. Voronoi order-ties behave the same way. So:

- derive each bucket from a per-type ULP sweep, re-measured per target platform;
- use relative tolerance where `|v| > 1` (Musgrave is unbounded, and `use_clamp`
  is off by default);
- for the discontinuous bases, allow a documented bounded outlier count instead
  of a hard max-error gate;
- record observed max error per type in the output so changes are visible.

**As built, the harness gates three things, not one** — because for a
noise-based type a pointwise diff is meaningless by construction. `clouds.stex`
samples the engine's builtin `vnoise`, deliberately substituted for `BLI_noise`
for the 8× speedup (see the `texture-scripts-progress` memory), so the two
bases *cannot* agree pointwise and CLOUDS failed at up to 1.009 relative error
on a naive diff. Each type therefore declares a `mode`:

- **epilogue** (all types): with the basis divided out — reference settings, one
  fixed point — `BRICONT` and the clamp must match to ~1e-6. This is shared code
  the port must not diverge on.
- **placement**: the reference config is fed `placed(p) - basis_offset`, so the
  script's own coordinate transform is compared against the model in isolation.
- **field** (`mode='field'`, noise types) vs **point** (`mode='point'`,
  everything with zero `BLI_noise` calls — Magic, Blend): a field type is gated
  on the mean and standard deviation of the two fields over a large box; a point
  type still gets a hard pointwise max-error gate.

Two findings worth keeping:

- The placement check earned its keep immediately: it caught a real port defect
  the pointwise diff had buried under basis noise. `BLI_noise_generic_turbulence`
  adds `x,y,z += 1` for `noisebasis == 0` (`noise_c.cc:1244-1258`) *before* the
  `1/noisesize` divide, and `clouds.stex` had omitted it. The Musgrave path has
  no such offset, so it belongs at the DSL call site, not in the sampler — hence
  the per-type `basis_offset`.
- The field statistic's error floor is set by **how many noise cells the box
  covers**, not by sample count. Stratifying the samples barely moved a marginal
  0.0285 mean error; widening the box to `FIELD_EXTENT = 16` scaled by
  `noise_scale` (~32 cells/axis) fixed it. Sample count only buys the last
  fraction after the box is big enough.

Budgets were measured over five seeds and the measurement recorded in the
`budget` comment, per the rule above. CLOUDS sits at roughly 2× headroom on all
four.

### 1.5 Kill switch and per-type gating — **done 2026-08-14**

Rev 1 had none; every comparable plan in this repo ships one. `_SCRIPT_TYPES`
(`texture.py:224`) **is** the switch — it is currently `{'CLOUDS': "clouds.stex"}`.
Rule: land the `.stex`, land its harness case, and add the type to
`_SCRIPT_TYPES` only once that case is green. Add one scene bool that empties
the dict wholesale. `_apply_script` currently falls back to the bake only on
*compile* failure (`texture.py:294-299`) — a port that compiles and is wrong has
no other backstop.

Landed as `Scene.sculptcore_texture_scripts` (`props.py`), read through
`texture._scripts_enabled(context)` in `apply_texture`'s 3D-map branch; absent a
context or the property (pre-register) scripts stay on.

Related trap for any generated/param work: `setTextureParamAt` **silently
returns false** for `@const` params (offset `-1`) and **silently clamps** to a
param's `@range` (`brush.h:864-875`); `_apply_script:309` ignores the return.

---

## Part 2 — Type ports

### 2.1 The cheap tier — do this, on the existing `vnoise` builtin

Five types at **visual-equivalence** fidelity, no new native samplers, no
tables, no WGSL:

1. **Magic**, **Blend** — verified to contain zero `BLI_noise` calls
   (`texture_procedural.cc:290-360`, `:55-110`), so they shake out the harness
   and the intrinsic tables before anything harder is on the critical path.
   Blend's `TEX_RAD` needs `atan2`; Magic needs the §0.3 per-type epilogue.
   — **done 2026-08-14**
2. **Wood**, **Marble**, **Stucci** — turbulence over `vnoise`, structurally the
   same shape `clouds.stex` already ships. — **done 2026-08-14**

Each lands with its harness case, then enters `_SCRIPT_TYPES`.

**Magic and Blend, as landed.** Both are `mode='point'` in the harness — no
noise means no substituted basis, so they are graded against Blender pointwise
rather than statistically, and both are far tighter than visual equivalence:
over five seeds Blend is **bit-identical** at every drawn setting (epilogue 0,
point 0) and Magic matches to ~6e-8. That is a stronger result than §5.1
promised, and it is a property of these two types only — it does not transfer to
the turbulence tier, where the `vnoise` substitution makes pointwise parity
structurally impossible.

Three things the two ports taught, in the order they cost time:

- **A `mode='point'` type needs no epilogue *model*.** `check_epilogue`
  originally fitted both sides to the shared scalar `BRICONT`, which Magic
  simply does not obey: it reports `TEX_RGB`, so the brush path runs
  `BRICONTRGB` and collapses to luminance, and
  `luma(BRICONTRGB(c)) = contrast·Σ Lᵢfᵢ(cᵢ−0.5) + (bright−0.5)·Σ Lᵢfᵢ` — equal
  to `BRICONT` only when `Σ Lᵢfᵢ = 1`, i.e. all three channel factors are 1.
  The lower-only clamp and the saturation step do not commute with the collapse
  either. Rather than carry a per-type analytic model, `check_epilogue` now just
  diffs the two sides at the drawn settings when the pattern itself matches —
  model-free and strictly stronger, and it grades the per-type epilogue whole.
- **BRICONTRGB's HSV round-trip is three lerps.** A `texture` block admits
  exactly one `eval` and no helper functions (`parser.cc:536-560`), so
  `rgb_to_hsv`/`hsv_to_rgb` around a saturation scale is not something
  `magic.stex` can call. It does not need to: scaling S by k at fixed H and V is
  exactly `c → V + k·(c − V)` with `V = max(r,g,b)`. It fixes the max channel,
  sends min to `V − k(V−min)`, and preserves `(mid−min)/(max−min)`, which is all
  hue is. At `k == 1` it is the identity, so the macro's `sat != 1` branch
  disappears too.
- **The placement budget is loose for Magic on purpose, and still catches the
  bug it is for.** The check hands the engine a coordinate *this script*
  computed in double and rounded to float, instead of one the engine composed;
  Magic's cascade then amplifies that last-bit difference by up to `(turb)^10`
  through ten nested `cos`, landing at 7.8e-4 worst over five seeds against a
  3e-3 budget. `point = 6e-8` under identity placement is what proves the
  pattern; a genuinely wrong composition — scale before offset, a stray basis
  offset — moves the pattern rather than its last bits and shows up at O(1).

Cost, measured through `eval_texture_at` (20k samples, worst-case settings):
Blend 17.0 µs, Magic 17.9 µs, Clouds 18.0 µs per sample. The ~17 µs floor is
the per-call Python/ctypes overhead, which is all this can resolve — but it
bounds the thing §4 asks about: Magic's full ten-deep cascade costs no more than
the 5-octave Clouds already shipping at 2.7 ms/dab, and Blend costs less than
both. Neither is a perf regression against the bake it replaces.

**Wood, Marble and Stucci, as landed.** All three substitute `vnoise` for
`BLI_noise`, so §5.1 visual equivalence is the ceiling — but three of the nine
harness cases still grade *pointwise*, which turned out to be where the actual
bugs were. Two levers make that possible:

- **Wood's Bands and Rings call no noise at all** (`wood_int` only reaches
  `BLI_noise_generic_noise` for Band/Ring Noise), so those two wood types are
  graded like Blend — and come out **bit-identical**, epilogue 0 and point 0
  over four seeds.
- **A "quiet" variant**, `turbulence` pinned to its RNA minimum of 1e-4, bounds
  the whole noise contribution by 1e-4 whatever the basis. That grades every
  part of the noisy arms *except* the noise amplitude, which is then all the
  field case has left to carry. Wood/quiet-noise lands at 4.6e-5 pointwise,
  Marble/quiet at 7.6e-4 (see below).

So a type's harness descriptor is now either one spec or a **list** of them:
one `mode` per type could not say that half of Wood deserves the strictly
stronger grade. Field results are ordinary: mean ≤ 0.012, sd ≤ 0.0067 across
Wood/noise, Marble/veined and Stucci — the same range clouds.stex sits in.

Four things these three taught:

- **`noise_scale` does not scale the pattern.** `wood_int` and `marble_int`
  hand the *raw placed coordinate* to the waveform; only
  `BLI_noise_generic_noise`/`_turbulence` divide by `noisesize`
  (`noise_c.cc:1198-1203`, `:1247-1253`). Turning `noise_scale` re-grains the
  perturbation and leaves the bands where they are. Stucci is the same, plus
  its z-offset is added ahead of the divide. All three therefore take
  `scale_attr: None` in the harness — a spec that scaled the reference
  coordinate would have "corrected" a placement the port had right.
- **`tex_saw` has to be transcribed operation for operation.** It reduces `a`
  modulo 2π *first* (`n = int(a/b); a -= n*b; if (a<0) a += b`) and divides
  after, and `int()` truncates toward zero. Wood drives `|a|` into the
  hundreds, where reducing modulo 2π cancels ~4 bits — and the residue is the
  entire answer. `fract(a/2π)` drifts ~1e-5; the tidier
  `(a − floor(a/2π)·2π)/2π` still drifts ~3e-6, because floor and trunc round
  negative quotients differently. Only the literal transcription is exact.
  `tex_tri` (`:178`) genuinely does scale by 1/2π first, so it needs none of
  this — the two are not symmetric and cannot share a spelling.
- **Stucci runs no epilogue.** `stucci()` returns straight after
  `max(tin, 0)` with no `BRICONT`, and nothing downstream adds one, so
  `intensity`/`contrast`/`use_clamp` are inert in Blender too. `stucci.stex`
  therefore declares no such params, and the harness gained an
  `epilogue: 'none'` model that keeps those settings randomized and grades the
  identity — asserting the inertness on both sides rather than declining to
  check it. `_push_script_params` had to be inverted to iterate what the
  *script* declares rather than what the params dict holds; it still raises on
  a param declared and unsupplied, which is the typo check worth keeping.
- **Two of these maps have unbounded slope, so the worst case needs
  trimming.** The saw and triangle waveforms jump a full unit once per period,
  and Marble's Sharper takes `v^(1/4)`, whose derivative blows up as `v → 0`.
  A single drawn sample landing on a jump or a zero reads O(1) while every
  other reads 1e-6 — Marble/quiet's pointwise worst swung 1.9e-4 to 7.6e-4
  across four seeds on that alone. Every worst-case statistic now discards the
  four largest errors (`TRIM_OUTLIERS`). This is not slack: a wrong placement
  or a wrong epilogue moves the *pattern*, misplacing every sample at once,
  which no amount of trimming can hide.

Cost, on the same `eval_texture_at` harness and each type worst-cased (Ring
Noise + Saw + hard noise; Sharper + depth 5 + Saw + hard noise; Wall In + hard
noise): Blend 10.9, Magic 11.4, Marble 11.7, Wood 11.7, Stucci 12.3, **Clouds
12.4** µs/sample. The ~11 µs floor is per-call Python/ctypes overhead, so this
resolves ordering and not much else — but ordering is what §4.4 asks for, and
the answer is that the already-shipping Clouds is the *most* expensive of the
six. Nothing ported here is slower than the program the addon already runs at
2.7 ms/dab, and their structure says the same: Wood's Bands/Rings call no
sampler at all, its noisy arms and Stucci call one and two respectively, and
Marble's octave loop is Clouds' own.

### 2.2 The expensive tail — deferred, with the real cost written down

**Musgrave ×5, Voronoi, DistortedNoise.** Deferred, not cancelled. What rev 1
got wrong about them:

- **The basis table names the wrong variants for 4 of 5 rows.** Clouds, Wood,
  Marble and Stucci go through `BLI_noise_generic_noise`/`_turbulence`
  (`noise_c.cc:1155`, `:1212`), which dispatch the **unsigned** set
  (`orgPerlinNoiseU`, `newPerlinU`, `voronoi_F1`…`voronoi_Cr`, `BLI_cellNoiseU`).
  Only the Musgrave family (`:1281-1314`) dispatches the signed names rev 1
  listed. Cheap fix: `S = 2·U − 1`, one sampler per basis plus a DSL wrap — but
  the table must say so. Also, the generic path does `x,y,z += 1` before
  `orgBlenderNoise` and the Musgrave path does not, so the `+1` belongs at the
  DSL call site, not inside the sampler.
- **The Voronoi "resolution" solved the wrong half.** Rev 1's premise — that no
  extra runtime params can cross the sampler boundary, hence 28 named entries
  closing over static `VoronoiParams` — is **false**. The ABI is
  `float(float3)` *or* `float(float3, float3)` (`parser.cc:662-669`, verified),
  and the second vector passes through uninterpreted on both backends
  (`emit_c.cc:451-463`, `emit_wgsl.cc:581-593`). So
  `bl_voronoi_f1(p, float3(metric, order, mexp))` carries exactly the three
  runtime floats needed, from **one** sampler, with the metric staying a mutable
  `param float` — no 28 entries, no `@const`, no recompile on a dropdown, and
  FD-grad-safe since the wrapper perturbs only `p`. What rev 1 *called* solved
  and isn't: `voronoiTex` consumes all four of `da[0..3]` from a **single**
  27-cell search (`texture_procedural.cc:491-552`) plus `pa[12]` for the colour
  modes. A scalar-return sampler recomputes the search per distance — 4× — and
  inside a Musgrave octave loop that is 8 × 4 × 27 = 864 cell evaluations per
  vertex under a JIT that does no optimization. Needs a `user`-owned scratch
  struct read back by a second trivial sampler, or it is not shippable.
- **No perf budget existed.** Documented datum (`textureScripts.md:108-112`,
  commit `6f8f2c2`): clouds at depth 2 costs **2.66 ms/dab vs ~1.3–1.7 ms for
  the bitmap bake**, scaling ~0.375 ms/dab per octave. Musgrave/DistortedNoise
  at 8–10 octaves is ~3–4 ms of octave loop alone, plus a 3-to-9-way basis
  branch *inside* the loop. Set a per-dab budget before starting, and measure
  against the bake it replaces.

**Porting requirements when this is picked up** (all verified, all silent if
missed): `noise_c.cc` has **no `double`** anywhere, so float32 is not a blocker;
but `g_perlin_data_ub` is declared `static const char` and indexed as
`p[i + by0]` (`:458`, `:766-779`), which is only correct because Blender compiles
with `/J` / `-funsigned-char` globally (`platform_win32.cmake:207-208`,
`platform_unix.cmake:895`, `platform_apple.cmake:161`) — **declare the port's
tables `uint8_t` explicitly**. Those same files pin `-ffp-contract=off`. The
`SETUP` macro (`:754-762`) adds `10000.0f` before flooring, quantizing the
intra-cell fraction to ~2^-10 — a "clean" `floorf` port will not match. Cell
noise relies on uint32 wraparound and a mandatory `(x + 0.000001f) * 1.00001f`
nudge (`:1116-1125`). Table inventory is **two** unique 256-entry tables plus
`hashpntf[768]` — rev 1 said three families; `g_perlin_data_ub[:512]` equals
`BLI_noise_hash_uchar_512` and `g_perlin_data_v3[:768]` equals `hashvectf`,
verified by comparison. `BLI_noise_generic_distorted` does not exist; the
DistortedNoise entry point is `BLI_noise_mg_variable_lacunarity` (`:1608`).

### 2.3 WGSL twins — descoped

Rev 1's largest single line item ("budget real time for this, it's mechanical
but bulky" — ~4100 table literals plus basis bodies). It is unreachable:

- `gpu_brush_c_api.cc:77-79` (verified): `if (b->texture_program) { return nullptr; }`
  — a brush carrying a texture program **cannot construct a GpuBrush at all**.
- The addon has zero `GpuBrush` references; there is no GPU stroke path in
  `sculptcore_addon/**` today under any configuration.
- `gpuAvailable` is `wgsl.size() != 0` (`texture_program.cc:298-319`, verified) —
  the string is **never parsed**, and `test_texture_program.cc` validates WGSL
  with `strstr` only. A typo in 4100 hand-transcribed literals would set
  `gpuAvailable = true`, pass every existing test, and fail at the first GPU
  stroke, with no CPU/GPU numerical comparison anywhere in the tree to catch it.
- **Unverified and blocking if false**: no precedent exists in `engine/source/**`
  for dynamically indexing a module-scope WGSL `const` array — the exact shape
  every ported table needs. The only existing twin, `kVnoiseWgsl`
  (`host_sampler.cc:134-164`), is arithmetic-only. WGSL also has no `char`, so
  byte tables become `array<u32>` at 4× memory or reintroduce packing shifts.

Prerequisites before any twin is written: (a) lift `gpu_brush_c_api.cc:77`,
(b) add one naga/tint **compile** assertion to `test_texture_program.cc`, and
(c) confirm dynamic const-array indexing. Note also that bit-exactness is not
coherent on GPU regardless — WGSL permits FMA contraction and reassociation, and
`pow` is customarily lowered to `exp2(b*log2(a))`.

Related mechanism to know: `samplerDeps` is collected by textual call-site search
over the whole unit (`parser.cc:709-715`), `compileTextureScript` **hard-fails**
unless every dep is registered, and it concatenates **every** dep's WGSL plus a
synthesized FD-grad wrapper into `p->wgsl`. One missing `wgsl` string flips
`gpuAvailable` false for the whole program.

---

## Part 3 — What replaces the node-graph compiler

The `NTREE_TEXTURE` → `.stex` compiler (rev 1 Part 2, ~1500–2500 lines) is
**cut**. Reasons in §5.2. Two small fixes capture most of its correctness value:

### 3.1 The reduction formula in `_bake_procedural` is wrong for node trees

`ntreeTexExecTree` ends with an **unconditional** `retval |= TEX_RGB`
(`node_texture_tree.cc:351`), so every node tree reports RGB, and
`RE_texture_evaluate:1097` therefore takes `luminance(trgba)`. The Output node's
own `tin = (r+g+b)/3` (`node_texture_output.cc:44`) is computed and thrown away.
But `use_rgb` (`texture.py:141`) is False for a node-tree texture unless
`use_color_ramp`, so the bake currently takes `v[3]`. Fold this into §0.2's fix.

(Rev 1 §2.3 asserted in bold that the terminal reduction is the plain average and
that the luminance path must *not* be reused. That is backwards for the brush
path — and `Texture.evaluate()` hides it, since it returns the pre-collapse
`tin`, so the harness rev 1 specified would have confirmed the wrong formula.)

### 3.2 Node-tree edits are invisible to the cache — **done 2026-08-14**

`_fingerprint` (`texture.py:81`) is called only from `_bake` (`:112`) and
iterates `tex.bl_rna.properties` for `BOOLEAN/INT/FLOAT/ENUM` only — `node_tree`
is a POINTER, so **no graph edit is visible to it**. Combined with
`invalidate_from_depsgraph` (`:69-78`) matching only `Image`/`Texture`, a
node-tree brush texture plausibly bakes once and never updates. Hash node
topology (type, links, `custom1-4`) and per-node storage, recursing into groups
and `Tex` references.

`_node_tree_fingerprint` does that. **But the fingerprint alone fixes nothing**,
which the test caught: a correct re-bake still replayed the old graph, because
`Texture.evaluate()` on a `use_nodes` texture runs `ntreeTexExecTree`, which
lazily builds `ntree->runtime->execdata` on first use and then keeps it forever
("XXX hack: prevent exec data from being generated twice",
`node_texture_tree.cc:337-345`). Nothing frees it on a link edit, a socket
default, or an added node — only node *removal* (`node.cc:5074-5078`) and tree
free do. The interactive paint paths dodge this by bracketing their own
`ntreeTexBeginExecTree`/`EndExecTree` per stroke (`sculpt.cc:5242/6134`,
`paint_cursor.cc:319/338`); `evaluate()` has no bracket and RNA exposes none.

So `_bake_procedural` calls `_purge_node_execdata` first: add a throwaway
`TextureNodeCoordinates` and remove it. The tree ends structurally identical, so
the purge is fingerprint-neutral (asserted in the test) and the cache entry the
bake writes stays valid.

That purge also forced a **deletion**: the `NodeTree` branch this task first
added to `invalidate_from_depsgraph` had to come back out. Every bake now tags
the tree, so clearing the cache on a NodeTree update would invalidate the bake
the addon had just made and rebake on every stroke forever. The fingerprint is
the whole mechanism; the depsgraph hook stays `Image`-only.

Note separately that `_apply_script` has **no fingerprint at all** — its entire
cache key is `session.tex_script_type != tex.type` (`texture.py:285`, verified),
so two different textures of the same type share a compiled program within a
session. Worth fixing when a second type lands.

---

## 4 — Verification

1. **Engine**: `node make.mjs build native` then `node make.mjs test <name>` per
   addition (`make.mjs test` does not rebuild). Existing targets are real —
   `test_sbrush_textures`, `test_texture_c_jit`, `test_texture_program`,
   `test_texture_stroke` (`engine/tests/CMakeLists.txt:96-107`) — but **none of
   them compares numbers**; `test_texture_program.cc` is `strstr` assertions.
   The parity work needs a new `test_texture_parity` target; budget it.
   — **done: ctest 130/130 green** on the intrinsics work. The new
   `test_texture_parity` target was **not** built and is no longer needed: the
   numeric comparison it was for wants a *Blender* on the other side, and
   `tools/verify_texture_parity.py` is that comparison, run where a Blender
   exists. A C++ target could only re-check the engine against itself.
2. **Addon**: `tools/verify_texture_parity.py` headless per §1.4, gated into
   whichever CI job runs `verify_addon.py`/`smoke_test_package.py`. — **done**:
   a third step in `smoke-test-packages.yml`, after the enabled check and the
   engine smoke test. That job is the only one where a Blender and the engine
   coexist, and the copy it grades is the one users get — so it also catches a
   `.stex` that ships in the archive but no longer compiles against the
   vendored DLL, which neither of the other two steps can see.
3. **End-to-end**: bind each ported type to a real brush in the dev build
   (`node tools/build-blender-dist.mjs --run`, or the `SCULPTCORE_PYTHON_PATH`
   env flow) and sculpt a stroke. — **done, and headless**:
   `claudeMemory/scripts/test_texture_stroke.py`. Headless is sufficient here
   rather than a compromise, because 3D mapping is the only map mode that
   routes to a script and a 3D-mapped program reads the sculpt-space point
   directly — none of the six `.stex` sources calls `mapPoint()`, so there is
   no render matrix that has to come from a real 3D view. Per type, on
   identical dabs over a fresh 96² grid: `apply_texture` routes it (which is
   what exercises `_SCRIPT_TYPES` and the `map_mode == '3D'` gate the parity
   harness bypasses), the stroke moves verts, the per-vertex displacement
   ratio against an untextured control has real spread (0.084–0.36 — a script
   that compiled and returned a constant scales every vertex alike and lands
   at 0), and no two types produce the same field. 35 checks, all green.
4. **Perf**: measure ms/dab per ported type against the bake it replaces, on the
   `textureScripts.md:108-112` methodology. A type that is slower than its bake
   without being more correct does not enter `_SCRIPT_TYPES`. — **done**: see
   the cost paragraph at the end of §2.1. Every newly ported type is cheaper,
   worst-cased, than the Clouds program the addon already ships.

---

## 5 — Rejected, with reasons (do not re-derive)

### 5.1 Bit-exactness as the fidelity target — rejected

The consumer is a brush mask multiplied into `strength()`, then into a
displacement scaled by radius, pressure, a falloff curve and autosmooth. A 1e-3
difference is not resolvable by eye at any brush size. Nothing about a texture is
persisted by the addon (session-scoped store, textures re-bind per stroke), so
there is no file-format exposure. The project already accepted visual
equivalence for CLOUDS and shipped it (`6f8f2c2`).

Bit-exactness is what forces every expensive item: verbatim tables, WGSL twins,
the Voronoi sampler explosion, replicating the `+10000.0f` quantization. It is
also *not achievable* on the GPU half (§2.3) and *not measurable* against the
discontinuous bases (§1.4).

The one argument it cannot dismiss: a user switching between native sculpt and
SculptCore mid-project sees a 3D-mapped pattern jump. Answer: target **exact
mapping** (placement order, projection, the `tin`-vs-luminance rule, the
bright/contrast fold) with **statistical/structural equivalence** on the noise
phase. That closes the user-visible wrongness — which lives in §0.3, not in the
noise lattice — at a fraction of the cost.

### 5.2 The `NTREE_TEXTURE` compiler — cut

Not for infeasibility. `NTREE_TEXTURE` is alive and healthy (§6), and rev 1's
design was mostly sound. It is cut on value:

- **Node-tree brush textures already work.** `multitex` branches to
  `ntreeTexExecTree` when `use_nodes && tex->use_nodes && tex->nodetree`
  (`texture_procedural.cc:718`), `multitex_ext` passes `use_nodes=true` (`:941`),
  and `evaluate()` calls `multitex_ext`. So `_bake_procedural`'s 128² loop
  already renders the real graph correctly for all five 2D map modes, with zero
  code. The addressable gap is **3D-mapped node trees only**.
- **Behind a hidden toggle.** There is no `use_nodes` button in Properties ▸
  Texture at all (`properties_texture.py:109-140`); the only way to enable it for
  a brush texture is the Texture Node Editor header (`space_node.py:127-141`)
  after switching an editor and setting `texture_type='BRUSH'`.
- **The graphs that most need infinite extent are the ones that can't have it.**
  Nested At/Rotate/Scale and ValToNor bump chains are exactly what pushes
  emission over the cost cliff back onto the bake.

If it is ever revived, these are the corrections it needs (all verified):

- Memoize on **`(output_socket, p_expr)`**, not `(node, color|value)`.
  `TexDelegate` is stored per output socket (`node_texture_util.cc:129-143`) and
  Separate Color installs four different `texfn`s (`node_texture_separate_color.cc:82-88`);
  the color/value split is a *consumer-side* coercion (`:100-105`), so the rev 1
  key both collapses distinct outputs and duplicates shared ones.
- **ValToNor forks four coordinates, not one** (`node_texture_valToNor.cc:23-45`)
  — three nested ones are 64× their subtree. The cap must be a pre-flight cost
  estimate over the context lattice, not a post-hoc statement count.
- **2000 statements is ~20× too many.** Extrapolating from clouds' 2.66 ms/dab
  over ~44 executed statements gives ~35 µs/statement/dab under tcc (which does
  no optimization, ~10× clang -O2 per op), i.e. ~50–90 ms/dab at 2000. Realistic
  ceiling is ~100–150, measured.
- **Image nodes must not use Python host samplers.** Three GIL-taking callbacks
  per node instance per vertex contradicts `texture.py:411-412` and
  `textureScripts.md:94-98` verbatim, and any Python-backed sampler registers
  empty WGSL, dropping the whole program off the GPU path. It is also
  unnecessary: `node_texture_image.cc:29-77` is nearest-neighbour, wrap-only,
  2D-only — precisely what the engine's existing bitmap path does.
- **Bricks needs far more than `Shl`/`Shr`.** `n * (n*n*60493 + 19990303)`
  (`node_texture_bricks.cc:41-47`) reaches ~2^31, which float32's 24-bit mantissa
  cannot represent — there is no float workaround. It needs a runtime i32 type
  across the parser and both emitters. **Checker** also needs integer modulo, so
  it cannot ship in a "no new intrinsics" first wave as rev 1 scheduled.
- **`tex_proc_*` and `Texture` nodes are not raw procedural math** — they call
  `multitex_nodes` on an embedded/referenced `Tex` (`node_texture_proc.cc:35-46`,
  `node_texture_texture.cc:29-58`), i.e. the whole per-type pipeline including
  its colour band and bright/contrast, then `ramp_blend` against the node's own
  Color1/Color2 subtrees.
- **`Curve Time` is dead work**: `multitex` hardcodes `const float cfra = 1.0f`
  (`texture_procedural.cc:719-721`) on both paths, so the scene frame never
  reaches a texture node tree. Emit the constant. And **RGB Curves is four
  curves, not three** — `cm[i](cm[3](x))` (`colortools.cc:1202-1212`); bake the
  composition into the per-channel LUTs.
- The byte-comparability regression guard (rev 1 Verification item 4) is **not
  implementable**: samplers are unit-scope and must be deduped
  (`parser.cc:672`, `:679-706`), and `tex_proc_*` scalar inputs are *sockets*,
  so `param float noisesize;` must become `float noisesize_n3 = <expr>;` the
  moment anyone links one. Replace it with a **numeric** guard — evaluate flat
  program vs. spliced instance at N points through `evalTextureAt`.
- Reroute and muted nodes (`node_exec.cc:232-235`) were never mentioned.
- Rev 1's "governing constraint" citation is wrong twice over: the one-`texture`-
  block limit is not `parser.cc:173` (that is `@brush` attribute parsing) but a
  **four-line runtime check** at `texture_program.cc:172-175` (verified) — a
  pillar that "settles the compilation strategy" but could be lifted in an
  afternoon.

### 5.3 Plain `Noise` (`TEX_NOISE`) — impossible, removed from scope

`texnoise` (`texture_procedural.cc:559-581`) takes **no `texvec` parameter**. It
draws from `BLI_rng_thread_rand(random_tex_array, thread)`, advancing global
state per call. Measured, same texture and same point, five consecutive calls:
`[0.074074, 0.0, 0.0, 0.666667, 0.0]`. It is not a function of position, cannot
be expressed as `float eval(float3 p, float3 n)`, and cannot be parity-tested
because the oracle is nondeterministic. Rev 1 listed it in §1.5 step 3 and gave
it a 1e-4 tolerance. Target count is **9**, not 10.

### 5.4 The signed-`char` Perlin table is *not* a bit-exactness blocker

One reviewer argued `g_perlin_data_ub` (`static const char`, 258 entries > 127,
indexed as `p[i + by0]`) makes `orgPerlinNoise` UB and bit-exactness undefined.
Refuted: Blender compiles with `/J` / `-funsigned-char` on all three platforms
(§2.2 cites), so the reference is well-defined. It is a *porting requirement*
(declare `uint8_t`), not a blocker.

### 5.5 `fd_step` gradients — a non-issue, drop from the risk list

`sb_hs_grad`'s 6-tap central differences (`host_sampler.cc:244-272`) are reached
only via `grad()`, used only by `graddraw.sbrush`/`texgrad.sbrush`. `TEXGRAD`
appears once (`brush_executor.h:441`) and is **absent from
`sculptcore_addon/mapping.py`** — no addon brush maps to it. Finite-differencing
high-frequency noise at 1e-3 would indeed be garbage; nothing in the addon
consumes it.

---

## 6 — Confirmed by the pressure test (questions now closed)

- **All 10 legacy procedural types still exist** — `DNA_texture_types.h:64-76`
  (`TEX_CLOUDS`=1 … `TEX_DISTNOISE`=13), RNA items at `rna_texture.cc:30-73`, all
  dispatch arms live at `texture_procedural.cc:728-792`. **MUSGRAVE survives as
  a legacy `Tex` datablock** with all five subtypes despite the 4.1 shader-node
  removal, and every setting the port reads is still exposed (`musgrave_type`,
  `noise_basis`, `noise_basis_2`, `distance_metric`, `minkovsky_exponent`). All
  10 constructible via `bpy.data.textures.new` (verified live).
- **`NTREE_TEXTURE` is alive and not deprecated** — `DNA_node_types.h:281`, no
  `DNA_DEPRECATED`, **34** registered node types (`node_texture_register.cc:15-49`,
  rev 1 said "~30"), nothing `#if 0`'d, no removal versioning. Only
  Compose/Decompose are gone (versioned to Combine/SeparateColor,
  `versioning_500.cc:453-471`). A user can create one and a brush can use it.
- **Float32 is not a blocker** — `noise_c.cc` contains no `double` on any path.
- **`evalTextureAt` is genuinely thin** — eager compile, params seeded from
  defaults, no skipped bind step; 6-float binding fine; reflected methods reach
  Python with no codegen regeneration.
- **§1.5 step 2's warm-up choice was right** — `magic()` and `blend()` contain
  zero `BLI_noise` calls.
- **The `1/noisesize` pre-scale claim was right** — applied for Musgrave
  (`:758-759`), Voronoi (`:779-780`), DistortedNoise (`:787-788`) only.
- **`multitex` → `ntreeTexExecTree`** at `texture_procedural.cc:718` is literally
  correct, and `evaluate()` does reach it (verified live: a Checker→Output tree
  gives `evaluate((0.3,0.3,0)) = (1.0, 1.0, 1.0, 1.0)`).

Minor citation corrections to rev 1: sampler-arity enforcement is
`parser.cc:662-669` (not `:628`); `vnoise` spans `host_sampler.cc:79-165` (not
`:79-182`); `HostSampler::user` carries no doc comment at `:21` (it is documented
for lifetime in the c-api block at `:66-69`); `IntrinsicDef::arity`
(`intrinsics.h:44`) is stored but never checked — mis-arity renders
`/*bad-arg*/` (`emit_c.cc:492`).

---

## 7 — Ordering

1. **Part 0** — map-mode fixes (§0.4), `use_rgb` (§0.2), `clouds.stex` placement
   + clamp (§0.3). Addon-only, no rebuild, helps every texture type. — **done**
2. **§1.1** `evalTextureAt` + **§1.3** intrinsics (four sites) + **§1.4** harness
   with the corrected oracle. First thing the harness should find is §0.3's
   placement bug — fix before porting anything. — **done** (and it did)
3. **§2.1** Magic, Blend, then Wood, Marble, Stucci — each gated into
   `_SCRIPT_TYPES` only on a green parity case (§1.5). — **done 2026-08-14**
4. **§3.1/§3.2** node-tree reduction + fingerprint fixes (~40 lines total).
   — **done**
5. **Stop and measure.** Musgrave/Voronoi/DistortedNoise (§2.2) and the WGSL
   twins (§2.3) proceed only against a stated demand and, for the twins, the
   three prerequisites in §2.3. — **this is where the plan now sits.**

**Where it landed.** `_SCRIPT_TYPES` is
`{CLOUDS, BLEND, MAGIC, WOOD, MARBLE, STUCCI}` — six of the ten legacy
procedurals now evaluate as a runtime `.stex` at the true sculpt-space point
instead of a tiled 128² bake, with Clouds in Color mode the one supported type
that still falls back (`_script_supports`). `tools/verify_texture_parity.py` grades
them as **9 cases over 6 types**, all within budget on four seeds; three of the
nine are pointwise, and two of those three (Blend, Wood's Bands/Rings) are
bit-identical. Every budget in the file is a rounded-up measurement with the
observed worst in a comment beside it, except Marble/quiet's `point`, which
documents why it keeps an order of headroom instead.

The four procedurals left out are each left out for a recorded reason:
`TEX_NOISE` (§5.3 — a thread-RNG draw that ignores its coordinate, so it can be
neither ported nor parity-tested) and Musgrave, Voronoi and DistortedNoise
(§2.2 — they need new native samplers, and §2.2 prices them). `TEX_IMAGE` is
not a procedural and keeps going through the bake, which is the right path for
it.

## Critical files

- `sculptcore_addon/texture.py` — `apply_texture`, `_bake_procedural` (§0.1/§0.2),
  `_apply_script`, `_script_params`, `_ramp_lut`, `_fingerprint`, `_SCRIPT_TYPES`
  (§1.5), `apply_render_matrix` (§0.4).
- `sculptcore_addon/stex/clouds.stex` — template for every port; **fix §0.3
  before copying it**.
- `engine/source/brush/brush.h` — `evalTextureAt` (~`:475`/`:879`),
  `setTextureScript`/`setTextureParamAt`/`setTextureRampAt`/
  `queriedTextureParamEntry` (`:864-875` for the silent-clamp trap).
- `engine/source/brush/texture_program.cc` — the one-texture gate (`:172-175`),
  the tcc symbol table (`:212-218`), `gpuAvailable` (`:298-319`).
- `engine/source/brush/compiler/emit_c.cc` — `kCIntrinsics[]` (`:53`),
  `emitPrelude()` (`:735-746`), `kDualIntrinsics[]` (`:588-596`).
- `engine/source/brush/kernels/ir/intrinsics.cc` — `sIntrinsicsRaw[]` (`:39-127`).
- `engine/source/brush/host_sampler.cc`/`.h` — registry, `vnoise` (`:79-165`),
  the two-`float3` sampler ABI.
- `engine/source/brush/c-api/gpu_brush_c_api.cc:77-79` — the GPU texture gate.
- `C:\dev\blender\main\source\blender\blenlib\intern\noise_c.cc` + `BLI_noise_c.hh`
  — noise algorithms/tables (**not** `noise.cc`, a different modern namespace).
- `C:\dev\blender\main\source\blender\render\intern\texture_procedural.cc` —
  `multitex()`, `RE_texture_evaluate` (`:1040-1108`), the 9 per-type bodies.
- `C:\dev\blender\main\source\blender\makesrna\intern\rna_texture_api.cc:29-38`
  — what `Texture.evaluate()` actually returns.
- `claudeMemory/design/blender-brush-textures.md` — §6's map-mode defects (§0.4).
- `engine/documentation/textureScripts.md` — update as intrinsics, samplers and
  the point-eval API land; the perf datum at `:108-112` is the budget baseline.
</content>
