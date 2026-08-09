# Autotuning the multires acceleration granularities

Multires levels built three structures from **fixed constants**, whatever the
level's size:

| structure | constant | what it controls |
| --- | --- | --- |
| `GridTree` (grids-native brush path) | `kDefaultLeafVertTarget = 512` | leaf size → per-dab query + region |
| `GridDrawSource` (external-draw path) | `kNodeTriTarget = 2048` | draw node = one host draw call + one GPU batch |
| slot `SpatialTree` (materialized level mesh) | `leaf_limit 512`, `depth_limit 10`, `gpu_tri_target 2048` | mesh-path tools only |

The addon never overrode them: `multires.py:build_engine` passes
`Multires_new(cage, level, 0, 0, 0)` and `convert.py` passes
`Mesh_buildSpatialTree(mesh, 0, 0, 0)`, and 0 meant "keep the compiled-in
default". `SpatialTree::autoTuneLimits()` existed but was only ever called from
`debug/scene.cc`.

Both fixed targets make a *count* grow linearly with the level: leaves, and
therefore the flat AABB scan every `GridTree::query` pays, and draw nodes,
and therefore per-frame per-node host work in `external_batches_get` (a hashmap
lookup, an upload probe and a frustum cull per node — **per draw pass**).
That was the hypothesis going in. It held for the draw nodes and *not* for the
leaves; the results below say why.

`source/subdiv/multires_tuning.{h,cc}` now derives all three from the level's
size. Every field has an env override for sweeps, and `SC_MR_AUTOTUNE=0`
restores the old constants as an A/B baseline.

## Rig

* Headless — `claudeMemory/scripts/bench_multires_tuning.py`: per config, an
  `enter` from a pristine base mesh (teardown skips `convert.flush`, so no
  config inherits the previous one's displacement), then 20 grids-native dabs,
  timing the dab and the `sc_external_draw_update` refill after it. One process
  sweeps every config — `multires_tuning.cc` re-reads its env vars per build.
* Headed — `claudeMemory/scripts/run_tuning_headed.mjs` drives
  `bench_multires_sc.py` (GUI, `Window.event_simulate` strokes) once per config
  for `idle_view_ms` / `sculpt_view_ms`. **Headless cannot see the draw-call
  side of the trade**: it measures the provider's CPU refill, which always
  prefers small nodes, and nothing that prefers large ones. Runs are
  interleaved (A B C, A B C) because this box's display pacing has flipped
  30↔60 Hz between batches.

Noise: the headless dab median moves ±0.2 ms run to run; read the shape of a
sweep, not a single pair.

## Results

### Leaf size — the optimum tracks the cage-face block, not the vert count

Headless dab medians (ms), 24 dabs, two repeats averaged. `leaf=N` is the
`SC_MR_LEAF_TARGET` verts-per-leaf target; `GridTree::build` clusters whole cage
faces, so the achievable minimum is one **block** = 4 grids of (S+1)² samples.

| scene | verts | S | block | 512 | 1024 | 2048 | 4096 | 8192 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| g128l3 | 1.0 M | 4 | 100 | **0.93** | 1.12 | 1.14 | 1.32 | 1.69 |
| g64l4 | 1.0 M | 8 | 324 | 0.86 | **0.75** | 0.89 | 1.07 | 1.31 |
| g32l5 | 1.0 M | 16 | 1156 | 0.69 | 0.60 | **0.61** | 0.65 | 0.90 |
| g64l5 | 4.0 M | 16 | 1156 | 2.77 | 2.70 | **2.46** | 3.03 | 2.95 |

The best target moves with S, not with vert count. That killed the v0 rule
(`vertCount / 1024`): at 4 M it asked for 4000 verts/leaf and was measurably
worse than 1024. The shipped rule is **two blocks per leaf**,
`clamp(2·4·(S+1)², 512, 4096)` — 512 at S=4, 648 at S=8, 2312 at S=16, and above
S≈22 it is inert anyway because the block alone exceeds the cap.

**Be honest about the size of this one.** At S=4 and S=8 the rule clusters
identically to the old fixed 512, so it changes nothing there. The only scenes
where it differs are S=16, and it is a wash: at 1 M it is ~0.06 ms/dab *worse*
than 512 (0.60 vs 0.54 median, sign confirmed by re-running the A/B with the
config order reversed — the earlier full sweep had them tied), and at 4 M it is
~0.3 ms better. The rule earns its place by scaling in the right direction and
by refusing to ask for leaves below the block floor, not by being faster today.

Enter time is flat across the whole leaf sweep (±5 %, all within noise): tree
build is not where mode-enter goes — `Refiner::refine` is.

### Draw-node size — the trade only appears headed

Headless says one thing and only one thing: refill cost is monotone in node
size, so smaller is always better (g64l4: 993 nodes → 0.33 ms/dab, 249 → 0.76,
63 → 1.92). The host side is invisible there. Headed, g64l4 (1 M verts, 2.03 M
tris), two interleaved repeats:

| tri target | nodes | idle_view ms | sculpt_view ms | sculpt_phase ms |
| --- | --- | --- | --- | --- |
| 2048 | 993 | 2.09 / 2.17 | 2.17 / 2.54 | 2258 / 2448 |
| 8192 | 249 | 1.03 / 0.99 | 1.05 / 1.00 | 2613 / 2684 |
| 32768 | 63 | 0.76 / 0.75 | 0.58 / 0.58 | 3039 / 3076 |

`idle_frame_ms` held at 16.7 ms across every run, so the pacing was stable and
the comparison is sound; the viewport cost is read from `idle_view_ms`.

Both halves of the trade are now visible and both are large. Quartering the node
count from 993 to 249 halves the per-frame viewport cost (2.1 → 1.0 ms) for
about +300 ms of sculpt phase — worth it. The next step down buys only 0.25 ms
more per frame and costs another ~400 ms of stroke, which is past the knee (the
sculpt-phase noise floor on this box is ±150 ms, so the 8192 → 32768 step is
real and the 2048 → 8192 step is borderline).

That knee — ~8192 tris per node at 2.03 M tris — is what the shipped rule is
anchored to. Because the two costs scale differently (host per *node*, refill
per node *size*), the rule takes their geometric mean:
`triTarget = clamp(sqrt(33·tris), 2048, 65536)`, i.e. node count and node size
both grow as √tris — 248 nodes at 2 M tris, ~497 at 8 M.

### auto vs fixed, headed (g64l4, 3 interleaved repeats)

The sign-off A/B, with the shipped constants built in — `auto` derives
648 verts/leaf and 8137 tris/node (1985 leaves, 249 draw nodes); `fixed`
(`SC_MR_AUTOTUNE=0`) is the old 512 / 2048 (1985 leaves, 993 nodes).

| | idle_view ms | sculpt_view ms | sculpt_phase ms | enter ms |
| --- | --- | --- | --- | --- |
| auto | 0.96 / 1.00 / 1.07 | 0.96 / 0.91 / 0.91 | 2522 / 2461 / 2498 | 2043 / 2025 / 2061 |
| fixed | 2.24 / 2.27 / 2.15 | 3.07 / 2.14 / 2.34 | 2716 / 2303 / 2287 | 2355 / 2037 / 2046 |

Viewport cost drops **2.2×** both idle and mid-stroke, and it is the cleanest
signal in this whole study — the three repeats of each config are tighter than
the gap between them, and `idle_frame_ms` never left 16.7 ms. Stroke and enter
are unchanged (every difference is inside the ±150 ms sculpt-phase noise floor);
the extra refill the bigger nodes cost headless does not surface as stroke time
here, because it overlaps work the frame was already doing.

### Slot tree

Untouched by these benchmarks: a lazy multires session never materializes the
slot `SpatialTree`, and only mesh-path tools build one. Its limits are derived
the same way `SpatialTree::autoTuneLimits` does and are left unvalidated here.


