# A sculpt-stroke world model — prior art and what its training data would be

**Date:** 2026-08-06. **Status:** research only; nothing implemented, nothing
proposed for implementation. Speculative.
**Question:** has anyone built an AI world model suitable for driving a 3D DCC
app, and — since nobody has built one at *stroke* granularity — what would the
training data for one even look like?

**Provenance note:** Part 1 is from a web survey on 2026-08-03 and is reported at
the confidence of vendor blogs and paper abstracts; none of it was run or
source-read. Part 6 is grounded in this repo and carries file:line citations.
Everything between the two is design reasoning, not a finding.

## Verdict up front

- **Agents that *operate* a DCC app using a world model exist and are funded.**
  They work at scene-assembly altitude — place objects, generate an asset,
  validate physics. The closest hit is Moonlake AI, which does computer-use
  inside Blender.
- **Generative world models are learning to emit editable geometry** rather than
  pixels (HY-World 2.0, World Tracing, WorldMesh). Still scene-level.
- **Nobody works at the granularity this engine does.** No published model
  predicts what a dab with a given radius, falloff and pressure does to a
  specific vertex set. The training signal for that does not exist as a public
  corpus, and the state space does not tokenize the way pixels or scene graphs
  do.
- **If one were built here, the framing that makes it worth anything is a
  *differentiable* sculpt operator**, not a faster one. Speed is already solved
  by the GPU kernels; differentiability buys inverse problems that are currently
  unreachable.
- **The single hardest constraint is not data volume.** It is that dyntopo
  changes the vertex set, which destroys the displacement-field formulation that
  makes the problem learnable at all.

## Part 1 — prior art (surveyed 2026-08-03)

### Agents driving a DCC app

**Moonlake AI** ([3D Agent](https://moonlakeai.com/blog/3d-agent)) is the direct
hit. SF research lab, out of stealth October 2025 on a $28M seed (Threshold
Ventures, AIX Ventures, NVIDIA's NVentures; Jeff Dean and Ian Goodfellow among
the angels), explicitly self-described as a world-modeling lab. The 3D Agent does
computer-use *inside Blender*: given a prompt, image, point cloud, CAD data, a
scan or a floor plan it builds editable scenes with hundreds of objects, models
individual assets, and produces articulated ones (hinged doors, refrigerators,
filing cabinets). The claimed differentiator is a physics-validation loop —
geometry, structural validity, articulation, deformation, friction, mass,
constraints, collision — with code-based structural checks and automatic repair,
plus long-horizon iteration where the agent inspects its own output instead of
one-shotting. Target market is robotics simulation and digital twins, not
artists. Beta opened after a 10k waitlist.

Below that tier the ecosystem is **MCP plumbing, not world models**:
[Blender MCP](https://3d-agent.com/blender-mcp) and similar addons let an LLM
call Blender operators. That is an agent with tools. It has no learned model of
what its actions do to the scene, and it fails in exactly the way you would
expect — it cannot predict the result of an edit, so it can only try and look.

### Generative world models

**Genie 3** (DeepMind, introduced August 2025; access widened via Project Genie
in January 2026) is the reference point for interactive world models: navigable
worlds at ~24 fps / 720p, minutes-long consistency, promptable in-world edits
during play. It renders frame-by-frame and **deliberately trades away explicit
geometry**. There is no mesh to hand to a DCC app, which makes it irrelevant as a
document model however impressive it is as a demo.

The branch that actually converges on the question is structured-output world
models:

| Work | What it emits |
|---|---|
| [HY-World 2.0](https://huggingface.co/tencent/HY-World-2.0) (Tencent) | Meshes + Gaussian splats, importable into Unity / Unreal / Isaac |
| [World Tracing](https://haoz19.github.io/world-tracing-page/) | Textured meshes; every object a full 3D asset; insert/replace/remove propagates consistently |
| [WorldMesh](https://mschneider456.github.io/world-mesh/) | Mesh scaffold conditions diffusion, reconstructed to a navigable scene |
| World Labs' Marble | Gaussian splats + collision meshes from one model |

The trend is real: simulators are being pushed toward controllable, editable
output rather than pixels. But all of it is *assembly* — what objects exist,
where they sit, how they articulate.

### The gap

None of the above models the inside of a mesh edit. The regime where a learned
model would have to predict a deformation field over a specific vertex set — what
a stroke does to a topology, what a collapse does to attribute layers, how a
coarse level should follow a fine one — is untouched. That is the regime this
engine lives in, and it is likely to stay hand-written longer than the assembly
layer above it.

## Part 2 — three incompatible goals

The dataset design is fully determined by which of these you want, and they do
not share a corpus.

1. **A fast surrogate for the sculpt kernel.** Almost certainly pointless. The
   kernels already run on GPU (see
   [gpu-brush-evaluation-in-blender.md](gpu-brush-evaluation-in-blender.md)) and
   the grids-native path measures 0.082 ms/dab core cost
   ([grids-native-brush-path-results.md](grids-native-brush-path-results.md)). A
   network will not beat that and will be approximately correct where the kernel
   is exactly correct.
2. **A differentiable sculpt operator.** The one worth wanting. It buys inverse
   problems that are currently unreachable: *what stroke sequence takes this mesh
   to that reference*, gradient-based fitting of a sculpt to a scan,
   optimization through an edit rather than search over edits.
3. **A behavioral prior over what artists actually do.** Stroke autocomplete, or
   an agent that sculpts. This wants human sessions and *sequences*, and barely
   cares about per-dab physics — it needs to know that people block out with a
   large clay brush before they crease, not what the clay brush does to a
   triangle.

Goal 2 is the world model in the technical sense. Goal 3 is what people usually
mean by the phrase, and it needs Goal 2 as its simulator to be trainable by
rollout. Goal 1 is a distraction.

The rest of this document is about Goal 2.

## Part 3 — the sample unit

**Mesh → mesh is not a formulation.** There is no canonical vertex order, the
size is unbounded, and better than 99.9% of the mesh is untouched by any given
dab. Training on whole meshes spends all its capacity learning the identity
function.

The unit is a **local patch**: the brush's influence sphere plus a ring or two of
context, expressed in a brush-local frame — origin at the hit point, z along the
surface normal (or the view vector, for view-aligned brushes), and **every length
divided by the brush radius**.

That normalization is the whole trick. In radius units the displacement field is
dimensionless, and one model covers a 2 mm detail brush and a 2 m blockout brush
with the same weights. Without it you are training a separate model per scale and
it will never generalize off the radii you sampled.

The label is a per-vertex displacement in the same frame. So:

```
(patch graph, dab action) -> Δ per vertex
```

This is a well-posed regression on a graph, which is the only reason any of this
is plausible.

### Positions are not the state

A stroke's result depends on far more than geometry, and a model trained on
positions alone will be confidently wrong the first time someone masks half the
model. The patch needs per-vertex channels:

| Channel | Why |
|---|---|
| Position, normal | The geometry itself |
| Mask | Scales the effect per vertex; ignoring it is an immediate, visible failure |
| Curvature (or a local frame descriptor) | Cavity automasking and pinch-type brushes are curvature-driven |
| Face set — **relational** | Encode *same-set-as-hit-vertex / different*, never the id. Face-set ids are not canonical; a model that memorizes id 7 has learned nothing and will not transfer between two meshes. |
| Vertex-group weight | Where the weights attribute participates in the brush ([vertex-group-weights-attribute](../plans/vertex-group-weights-attribute.md)) |
| Boundary / seam flags | Boundary handling is discontinuous and cannot be inferred from the patch geometry alone |

Multires level is a *sample-level* attribute rather than a per-vertex one, but it
has to be present: the same dab on the same cage at level 2 and level 5 produces
different results.

## Part 4 — the action space

A dab is a much larger object than it looks:

- Position, surface normal, view direction, radius, strength, pressure, tilt
- Direction of travel, and **previous dab positions** — grab and smooth are
  path-dependent, so the action is *not* Markov in a single dab. Either the state
  carries stroke history or the sample unit is a short dab window.
- Brush type (categorical), inversion flag, symmetry configuration
- **Falloff, which is a curve, not a scalar.** You either freeze it for the whole
  corpus or embed it as sampled control points. Blender exposes it as an editable
  curve mapping and artists do edit it.
- Automasking flags, which change the operator rather than parameterize it

### A capture trap specific to this engine

`loadProps` writes strength × pressure back into the Brush fields — the
destructive-loadProps behaviour recorded in memory and worked around in
`stroke.py`. And `_apply_spaced_dab` (`sculptcore_addon/stroke.py:839`) already
folds the pressure LUTs into `strength` and `world_radius` before the engine
call:

```
stroke.py:887-890   strength     *= eval_pressure_lut(self._pressure_strength_lut, pressure)
                    world_radius *= eval_pressure_lut(self._pressure_size_lut,     pressure)
```

So a naive capture that logs the Brush struct records **post-multiplied values
that drift dab to dab**, and the labels silently encode the workaround rather
than the artist's intent. Capture has to happen at the call site and record both
the authored (pre-LUT) values and the resolved ones. This is the kind of detail
that would poison a corpus invisibly — the model would train fine and be wrong in
a way no loss curve shows.

## Part 5 — where the data comes from

Two real sources, buying different things. A third is a mirage.

### Engine self-play

Free and unlimited: **the engine is the simulator**. Script randomized strokes
across a corpus of base forms and dump triples. This is distillation of your own
kernel, which is only worth doing *because* of the differentiability payoff —
the network is a differentiable stand-in for a non-differentiable operator, and
its ground truth is exact by construction.

The failure mode is distributional. Random strokes on random meshes cover a
region of the space no artist ever visits, and the model spends capacity on
nonsense. Curriculum matters more than volume. A usable base-mesh corpus needs:

- Primitives and subdivided primitives (trivially available, low value)
- Scan-derived and blockout-derived forms (the realistic distribution)
- Deliberate pathologies: thin shells, near-degenerate triangles, high-curvature
  creases, non-manifold junctions, wildly non-uniform edge length

and the stroke paths should come from a prior fitted to real sessions rather than
being uniform-random.

### Human capture

The only source of the *interesting* distribution. Instrument the real app, log
every dab from real artists across real projects. This is what tells you which
(mesh state, action) pairs matter, and it is the only route to Goal 3.

Volume is a non-issue. A stroke is 50–500 dabs; a dab touches 10²–10³ vertices;
so one artist-hour is on the order of 10⁶ dab samples. The bottleneck is
diversity of base geometry and brush coverage, not raw count. Storage is modest
if you store patch deltas rather than states.

### Reconstruction from public content — a mirage

Sculpt timelapses, speedsculpt videos, before/after model pairs. There is no
ground-truth intermediate state, the frame rate is far below the dab rate, and
the camera moves. It cannot supervise a displacement field. At best it is a weak
prior on stroke *plans* for Goal 3.

## Part 6 — capture seams in this codebase

This is where the repo is unusually well positioned, and also where the obvious
plan has a gap.

**What exists.** The delta-undo path already computes before/after diffs through
the per-session `MeshLog`, and `undo.py` documents the model: *each stroke pushes
one step* (`sculptcore_addon/undo.py:7-9`), with a cursor seek model over applied
step counts (`undo.py:340-385`). Grids-native strokes push a `GridStrokeLog` step
instead, with no meshlog entry (`undo.py:172-176`).

**The gap.** That is **stroke** granularity, not **dab** granularity. One meshlog
step covers an entire stroke — 50–500 dabs of accumulated displacement against a
moving surface. As a training label it is the composition of hundreds of
applications of the operator you are trying to learn, which is exactly the signal
you cannot invert. The meshlog is therefore a corpus generator for Goal 3
(stroke-level behaviour) and **not** for Goal 2 without new capture.

**Where dab-granular capture would hook.** `apply_dab`
(`sculptcore_addon/stroke.py:322`) is the single funnel: it takes the object-space
center, normal, radius and brush type, dispatches either to
`GridStroke_dab` (grids-native, returns the moved-vert count) or to the
`filterNodes` → `execProgram` path (returns the touched-node count). Both return
values are the touched-set size, which is the thing a capture layer needs to know
how much to snapshot. `apply_dab_program` (`stroke.py:460`) is the same shape for
chained programs.

A dab-granular capture would be: snapshot the touched set before `execProgram`,
snapshot after, record the resolved action from `_apply_spaced_dab`'s locals.
Cost is proportional to the touched set, not the mesh — the same property that
makes the grids-native undo affordable.

**Unverified.** Whether the engine exposes a cheap enough per-dab touched-set
readback to make this affordable in a live session, and whether the C++ stroke
driver (`plans/cpp-stroke-driver-adoption.md`, Phase 1 landed behind
`sculptcore_cpp_stroke_driver`) moves this seam. Both would need checking before
anyone costed a capture implementation.

## Part 7 — the topology wall

This is where the ambition usually dies, and it should be stated plainly.

**Fixed-topology sculpting is learnable.** Multires, and static-mesh draw / grab
/ smooth / clay, are a clean regression: the output vertex set is the input
vertex set, so there is a displacement field to fit.

**Dyntopo is not.** Collapse and split change the vertex set. There is no field
to regress, because the output has vertices with no input counterpart. The
formulation that makes Part 3 work simply does not apply.

The only honest move is to **split the problem**: learn the displacement
operator, and treat remeshing as a separate, deterministic, non-learned operator
applied after. That is a real limitation, not a temporary one — an end-to-end
learned dyntopo world model would have to generate topology, and anyone claiming
to have done it is either emitting point clouds and calling them meshes, or has
not tried it at production density.

Attribute propagation across a collapse (the wedge blend — see
[collapse-blend-gate.md](collapse-blend-gate.md)) sits on the wrong side of this
wall too.

## Part 8 — loss and evaluation

Two traps, both fatal if missed.

**L2 on displacement is a bad proxy.** Sculpt quality is surface continuity,
absence of pinching, and no self-intersection. A model can win on L2 while
producing a surface no artist would accept. The loss wants curvature-domain and
Laplacian terms alongside the positional one, and the evaluation wants a
self-intersection check the loss cannot express.

**Single-dab accuracy is nearly irrelevant.** Three hundred dabs compound: a
model with 1% per-dab error produces mush by the end of a stroke. Autoregressive
drift, not per-sample accuracy, is what decides whether the thing works. Training
has to include **rollout** — predict N dabs ahead and backpropagate through the
chain, or use scheduled sampling — otherwise the model only works in the
teacher-forced regime it was evaluated in, which is not a regime that exists at
inference time.

The honest headline metric is: *starting from a real mesh, replay a real 200-dab
stroke through the model and measure Hausdorff and curvature-spectrum deviation
from the engine's own result.* Anything reported per-dab is marketing.

## Part 9 — the minimum viable experiment

If someone wanted to find out whether this is real, without committing to a
program:

1. **Fixed topology only.** No dyntopo. Static mesh, one level.
2. **One brush** (draw), **one falloff**, frozen. Radius-normalized patches.
3. **Mask channel included** — it is the cheapest way to prove the model learned
   the operator rather than a shape prior.
4. **Self-play corpus** over ~10³ diverse base meshes, with stroke paths drawn
   from a prior fitted to a handful of real captured sessions rather than
   uniform-random.
5. **Success criterion: invert a known stroke.** Given a before mesh and an
   after mesh produced by a single known dab, recover the dab parameters by
   gradient descent through the model. If that works, the differentiability is
   real and Goal 2 is on the table. If it does not, nothing downstream matters.

Note what this deliberately does not test: visual quality, artist acceptance,
speed, or anything about dyntopo. Those are all downstream of the inversion
result and none of them are informative before it.

## Do not re-propose

- **A learned replacement for the sculpt kernel on performance grounds.** The
  measured core cost is 0.082 ms/dab. There is no headroom to win and exactness
  to lose.
- **End-to-end learned dyntopo.** See Part 7. If this comes back it needs a
  concrete answer to "what is the regression target when the vertex set changes",
  and "a point cloud" is not one.
- **Training from public sculpt video.** No ground-truth intermediate state, no
  dab-rate sampling. See Part 5.
- **Using the meshlog as a Goal 2 corpus without new capture.** It is
  stroke-granular; the label is the composition of the operator with itself
  hundreds of times.

## Sources

- [Moonlake 3D Agent](https://moonlakeai.com/blog/3d-agent) ·
  [Moonlake on Latent Space](https://www.latent.space/p/moonlake) ·
  [Metaverse Post coverage](https://mpost.io/moonlake-ai-unveils-3d-world-building-agent-capable-of-reconstructing-complex-scenes-from-single-image-input/)
- [Genie (world model), Wikipedia](https://en.wikipedia.org/wiki/Genie_(world_model))
- [HY-World 2.0](https://huggingface.co/tencent/HY-World-2.0) ·
  [World Tracing](https://haoz19.github.io/world-tracing-page/) ·
  [WorldMesh](https://mschneider456.github.io/world-mesh/)
- [Blender MCP](https://3d-agent.com/blender-mcp) ·
  [State of AI 3D Generation 2026](https://www.3daistudio.com/state-of-ai-3d-generation-2026)
- [A Functional Taxonomy of World Models — Fei-Fei Li](https://drfeifei.substack.com/p/a-functional-taxonomy-of-world-models)
