# Plan 6: resolved stroke and command integration

Reviewed by fresh native-execution and host-inheritance adversarial agents,
2026-09-17; findings below are incorporated before implementation. Preserve all earlier gates
and keep the new path opt-in until Plan 8. No fork change is currently anticipated.

## A. Independent command stacks and host command resolution

The existing prepared mesh/grid program path already stages typed values and the
union of evaluated radii without editing authored properties. Extend it with
explicit per-command whole-stack overrides: absence inherits the brush stack,
an explicit empty stack disables dynamics, and a present stack replaces it.
Store each override by canonical engine name plus scalar type and a validated
Dynamics value. Copy/reset-input behavior must match normal brush stacks.

Factor the Plan 5 parallel-vector response decoder into a reusable candidate
builder (no mutation before full validation). Add checked BrushProgram methods
for replacing/removing a named stack override, preserving existing entries on
failure. Bind the new methods with mutable vector-reference signatures required
by reflection; callers' vectors remain unchanged. Python uses the same validated
bulk marshalling as Common/Uniform stacks, retaining analytic double parameters.
The actual DLL probe exposed unsupported by-value String marshalling in Python
reflection. Add UTF-8 C API wrappers for named replace/remove, matching the existing
typed scalar bridge; they borrow the same validated vector buffers and call the same
checked implementation. Export through the normal WASM symbol list. No ABI input
record layout changes are required.

Pass command stacks into prepareBrushScalars and evaluate the selected stack
against the typed base override and the current dab input before selecting the
region. Validate canonical names, duplicates, property membership, exact types,
dynamic eligibility and malformed/pending layers. Unknown/unowned properties
remain errors; don't weaken existing corruption checks on authored brush state.
Preparation never temporarily replaces live brush stacks. Working-field scopes
already restore prepared values; verify stacks/authored values are unchanged on
success, failed late commands, cancellation and subsequent standalone strokes.
Legacy/raw program paths must explicitly reject stack overrides so unsupported
resolved capabilities cannot silently discard them.

Review corrections: evaluate a command stack even when its uniform has no authored
property yet. Extract decoding alone, without brush target lookup or publication.
Preserve the independent audit of authored stacks even when an empty replacement
masks their evaluation. Extend mesh/grid `preflightRawProgram` AND public
`prepareProgramDeclarations` rejection guards. Exercise direct/batch raw, automatic
fallback, zero-dab and miss paths. Preserve the existing batch ABI: accepted host
dab radius/strength/invert overlays remain committed, command scopes restore to
that overlay, and a rejected dab restores its prior overlay. Command execution
must never change authored stacks; this does not promise rollback of earlier
accepted dabs in a batch.

Add an immutable host command model and resolver. Names identify commands;
execution order is independent of ancestry. Parent may be the resolved brush,
another explicitly named command, or none (registry defaults). Sparse typed
value overrides and independently local/inherited whole stacks resolve into
complete immutable values/stacks with no inheritance flags. Reject cycles,
missing parents, duplicate command names, unknown properties and invalid static
stacks before native writes. Resolved curves use Plan 5 immutable responses.

Host boundary: use target-specific stable-ID definition universes, never engine
spellings for ancestry. A parent lacking a target ID supplies that target's registry
default and empty stack. Reject overrides outside the target universe. An explicit
tag distinguishes brush/named-command/default parents; omitted stack override means
inherit, while an explicit tuple (including empty) means replace. Unavailable stacks
are errors, not empty. Execution layers contain PreparedResponse and primitives,
sampled using stack_owner before flattening; snapshots retain no RNA/store/curve
references. Capture effective numeric domains separately from semantic definitions
(especially pixel size); Gate B normalizes them to engine execution domains before
this command resolver. Emit explicit complete stack state, including empties, for
every eligible target property. Build a new native program and publish it only after
all uploads succeed; never incrementally mutate an active program. Test forward and
disconnected cycles, independent order/ancestry, cross-kernel spelling collisions,
duplicate inputs before map construction, stale owner rejection before upload, and
snapshot independence from brush edits/cache eviction. Typed future definitions must
not reinterpret frozen legacy FLOAT32 IDs. Capability activation stays gated in B/C.

Gate A: pure host DAG/type/stack tests; native preparation and actual mesh/grid
program geometry with radius ADD exceeding the base, different main/smooth
stacks, explicit empty stacks, float/int/bool analytic and table responses,
changing/absent inputs and exact restoration. Test multi-leaf support and failed
late-command atomicity. Actual DLL tests validate Python transport and reject
malformed vectors/indices/types without changing command state. Raw paths reject.

Gate A completed 2026-09-17: [recorded evidence](../codebase/generic-brush-plan6-evidence.md)
and [verified manifest](../tests/plan6-command-gate.json). Native addon-only and
effective fixture gates each pass 17 suites; 24 pure tests, actual DLL transport,
four Blender launches and eight real headed modal cases pass. Full Plan 6 remains
open. The bounded [snapshot prerequisite](generic-brush-plan6-snapshots.md) is
complete with both independent reviews and its recorded Blender gate. The next
[typed domain slice](generic-brush-execution-domains.md) defines evaluation and
unit-conversion order before consumer adoption.

## B. Flattened brush execution model

Build immutable stroke snapshots from Plan 4 effective value and stack owners,
sample curves at synchronization time, and translate stable IDs to exact current
kernel manifests. Use the frozen legacy catalogue and native numeric inventory;
never infer engine types/defaults from a previous brush. Preserve absent/default
semantics and native authority. Add engine-owned view-normal/backface definitions
using the compatibility table's defaults/radian units. Expand frozen registration
only for supported inventory entries; retain specialized nonnumeric widgets/data.

Audit unit/order seams explicitly: semantic native diameter vs engine radius,
pixel projection vs world size, native integer spacing vs engine fraction,
snake pinch remap, SHARP compensation, PINCH local-strength exception, and
smooth multi-pass behavior. Define whether dynamics apply before/after each
translation from the frozen contract; preserve typed final conversion. Capture
the effective owner and paired size mode at resolution time. Scalar/stack
capabilities advertise execution only after their adapters are complete.

Gate B: effective-owner and independent stack inheritance matrix, native and
legacy unset fixtures, typed manifest changes, no persistent allocations on
reads, same explicit-dab geometry or independently specified corrections.

## C. Adopt every consumer behind the explicit opt-in

Use snapshots at stroke start; only projection, current device samples, Ctrl
inversion and documented live settings vary per dab. Wire mapping, modal Python,
C++ batches, mesh/grid, anchored/grab/snake, smooth/autosmooth, dyntopo, texture,
cursor and filters according to the inventory. Remove double pressure application
and shared evaluated-value feedback. Feed object-space view direction including
symmetry to view-normal/backface automasking. Preserve legacy execution when the
opt-in is off; gate tests assert the resolved path actually ran.

Finish capability gaps instead of quietly using raw execution for generic stacks.
Preflight all program topology/host requirements and union regions, using all
nodes for unbounded commands. Classify preparation hooks: only invariant hooks
may deduplicate; ENHANCE and other command-dependent hooks run with each stage's
resolved values. Separate cavity caches by complete command configuration and
geometry epoch, covering later-command enable. Keep scoped restoration on every
exit. No new command UI is needed in this plan.

Gate C: real multi-leaf mesh/grid/batch/program tests, second larger/unbounded
command, differently configured ENHANCE, cavity/view-normal/backface effects,
undo/cancel and engine rebuild. Check dyntopo capture/pinning and host requirements
before mutation. Audit any C API layout changes and regenerate bindings.

## D. Completion

Run frozen explicit-dab baselines plus corrected Plan 3 input tests, actual headed
draw/smooth/grab/snake/paint/mask/dyntopo/multires/autosmooth cases, changing scene
and brush between strokes, no pressure compounding, and Plan 4/5 authoring/cache
regressions. Build using the dispatcher, stage matching runtime/declarations and
verify package provenance. Record evidence for each bounded gate as it passes;
only mark Plan 6 tasks complete when their full acceptance scope is satisfied.

## Next capability work after the preview/dyntopo gates

The remaining declared attribute kernels are COLOR/COLORSMOOTH (vertex color),
POLYGROUP (face groups), LAYERDRAW (sculpt-layer displacement), and FEATURE_ALIGN
(cross-field preparation plus boundary classes). Prepared execution currently
admits only boundary-class reads and the command-owned ENHANCE field.

Before admitting writes, preflight all selected attribute targets for the whole
program without allocating columns. Validate types, domains, write/capture
requirements and explicit layer indices. The raw executor silently falls back
from an invalid layer index to its default name; a checked path must reject that
before any earlier command mutates data. Default index overrides are shared
across kernels, so their scope needs care in mixed-manifest programs.

POLYGROUP needs its post-stage boundary-dirty hook. FEATURE_ALIGN needs its
per-stage cross-field preparation. Prepared execution currently calls neither
generic per-dab hook phase; admitting their manifests alone is insufficient.
Mesh/materialized-multires writeback, cage-only color smoothing and sculpt-layer
composition each need their own acceptance cases. Native grid color/group
storage remains unsupported by its existing domain contract.

These findings define the next implementation work; no new attribute capability
is claimed by the completed preview or dyntopo gates. Further reviews remain
waived by the user.

## Remaining cage host path (implementation, review waived)

Add a checked CageSmooth entry that prepares typed settings once before selecting
incident grids with the evaluated radius. Execute the certified COLOR/COLORSMOOTH
scratch command directly over the existing synthetic cage node and limit-position
snapshot. Resolve and validate the actual color layer without allocation. Preserve
host-owned cage undo, masked samples, grid derivation and the existing disabled
cavity/UV policy. Reject invalid frames, target layers and stale level/derived
storage before edits. Keep the legacy API available for existing callers.

Gate: native cage-neighbor/limit-position/mask expectations, radius ADD growth,
validation-only and rejected-call atomicity; installed host lifecycle with raw
parity, no raw fallback, undo/redo, derived-grid consistency and real smooth
mouse gestures. Run matching bindings, typecheck and package provenance checks.

## Remaining falloff support (implementation, review waived)

The kernel's Gaussian response and nonzero custom edge keep influence outside a
sphere; linear shape is a slab, and cube/oriented box exceed the same-radius
sphere. Checked execution will validate each supported shape/curve and use a
conservative all-node region for these policies. Spherical zero-edge curves retain
the bounded query. This intentionally fixes raw execution's spatial truncation;
parity is against the unchanged kernel evaluated over an independently widened
region, not the old incorrectly clipped result. Validate finite directions,
positive finite box extents, curve samples and box normals before mutation.
Apply the policy to mesh/grid standalone/program paths and cage selection.

Gate: multileaf mesh/grid comparison against all-node raw kernels, nonzero-edge,
cube/box/slab/Gaussian cases, larger later commands, exact undo/redo, bad-config
atomicity and installed host calls. No shape formula or curve values change.

## Grid sculpt-layer target (implementation, review waived)

Admit prepared LayerScratch bindings only for the existing live grid edit target.
Validate an enabled, unfrozen layer pinned at weight one with the existing
three-float vertex displacement channel. Keep rejecting arbitrary session-channel
mirrors and unsupported attribute domains. Pin target/channel at beginStep and
reject target changes before dab mutation; the documented transaction contract
requires the host to keep them stable through endStep. Preserve the existing
per-stage scratch fold and stroke-end layer writeback/undo capture.

Gate: LAYERDRAW plus larger later DRAW, radius dynamics, standalone/program,
raw kernel parity and exact positions/store undo/redo. Test stale target rejection
and actual installed Layer strokes with both per-dab and C++ batch routing.

## Consumer synchronization boundary (implementation, review waived)

Introduce one immutable stroke-settings model that captures effective scalar and
stack owners, the size pair/mode, falloff and cavity tables, direction, and the
PINCH local-strength exception. It holds no RNA or owner-store references.
Prepare tables once at capture, including scene-owned hardness/cavity settings.
Projection and current device channels remain per-dab inputs. Host evaluation
serves spacing, smooth passes, cursor and translated values; native-compatible
stacks remain available in the snapshot for checked engine installation.

The first gate isolates this boundary with real Brush/Scene owners and the actual
DLL. It must prove dormant state preservation, scene/local independence, no
persistent allocation on capture, snapshot stability after edits, SCENE diameter
conversion, integer spacing, nonlinear transforms after dynamics, immutable
curve tables, and checked transfer. This prerequisite does not activate the
modal path or advertise execution capability until every consumer is connected.

### Native evaluation of semantic domains

Kernel uniforms cannot directly represent every native authoring domain: spacing
is an integer percentage while the kernel consumes a float fraction, snake pinch
uses a reversed affine transform, and strength compensation follows final native
range clamping. Installing these stacks on the translated kernel value changes
ADD/REPLACE behavior and integer rounding.

Add an engine-owned semantic scalar collection containing typed bounds, bases and
immutable device stacks. Reuse the existing checked Dynamics evaluator and response
decoder. Evaluate a batch of explicit input rows without touching authored values;
accept a projected-radius override for semantic size. Publish output only after the
whole candidate validates. Python performs unit/brush-family transforms on evaluated
scalars and supplies explicit empty kernel stacks to prevent repeated evaluation.
The original stacks remain in the native semantic collection for the entire stroke.

For C++ dab batches, evaluate all scalar rows in one native call. Group consecutive
rows with equal converted uniforms/program settings and submit each group through
the existing checked batch API. Variable settings can yield one-row batches; order,
symmetry and input provenance remain unchanged. This is a documented performance
tradeoff until the executor accepts semantic collections directly. Never switch to
raw execution or discard stacks to preserve batching. Python smooth/cursor/spacing
consumers use the independently verified host evaluator over the same snapshot.

Gate this transfer with actual float/int/bool stack parity, final domain clamps,
noncommuting unit transforms, changing/absent inputs, batch equivalence, no repeated
bakes/uploads, failure atomicity and disposal. Then connect and test every modal
route before activating the opt-in capability.
