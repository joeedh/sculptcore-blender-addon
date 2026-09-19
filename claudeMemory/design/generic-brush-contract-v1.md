# Generic brush contract, version 1

Status: Plan 1 fixture gate passed (2026-09-15); downstream implementation in progress.
These are implementation decisions unless explicitly attributed to the user.
The current status and corrections are in [the implementation reference](../codebase/generic-brush-properties.md).
The automasking table below records the initial inventory; view-normal/backface
execution and the generic UI are now implemented.
The eight gates in [the task list](../plans/generic-brush-properties-tasks.md)
remain mandatory. This contract does not enable the new path.

## Identity and migration

Saved schema version is 1. Definitions, authored records and immutable resolved
records are distinct. IDs are explicit registry strings; labels, collection
indices, manifest order, named-float slots and memory addresses are never IDs.
Common native settings use `sculptcore.brush.<semantic_name>`; kernel uniforms
use `sculptcore.kernel.<kernel_name_lowercase>.<uniform_name>` preserving the
uniform's case. Kernel names become permanent registry namespaces: renaming a
kernel requires an explicit alias. Only the common native adapter table shares
IDs across kernels. For example, `strength` is shared; each kernel's `projection`
has a separate ID even if today's C++ storage happens to be the same field.

Freeze the old generated RNA declarations and every kernel/name association
from the baseline runtime, including registered defaults/ranges and live Brush
defaults. Migration uses that frozen data without querying a new DLL. For each
legacy `Brush.sculptcore[name]`, fan the authored value out to every frozen
kernel ID associated with that name. Do this even for inactive kernels, so
changing brush type later retains the old shared setting. If unset, resolve
the frozen *registered RNA default* for all those IDs, not a new DSL default.
Keep `authored=false` distinct from explicit set-to-default. Preserve the raw
legacy group for rollback; never delete it on read. Unknown names and newer
schema records are retained opaquely and cannot be downgraded. Missing kernels
disable execution of their records without rewriting values or IDs.

Native values and curves remain authoritative in their native RNA. Migration
adds metadata and unmapped storage only. Legacy assets are migrated lazily in
memory after activation; persistence requires explicit asset save. Read-only
assets expose resolved reads and require Save As for changes. No library scan
rewrites assets. Existing native RNA paths stay intact; generated legacy paths
have aliases with fan-out writes. Driver variables on other IDs can read these
paths, including the active kernel's independent value.

Legacy alias reads select the active kernel's ID when it owns the name;
otherwise return the preserved legacy value/default. Unset clears all fan-out
authoring flags and restores their frozen defaults. Raw legacy writes are
detected by comparing value/presence at synchronization; pending changes also
have a non-mutating read overlay so display and execution agree before the next
synchronization. **September 19 correction:** the fork marks Brush with
`IDTYPE_FLAGS_NO_ANIMDATA`; Brush has no animation_data and rejects both
driver_add and keyframe_insert. The originally planned evaluated-animation
overlay therefore has no supported legacy Brush data to preserve. Keep that
native limitation instead of introducing Brush animation as part of migration.
Scene animation and driver variables referencing Brush paths remain native;
the actual driver-variable read/update case is covered by the frozen fixture.
Freeze union-declaration winning provenance, hard/soft ranges and DLL/source
identity alongside manifest associations.

## Ownership and resolution

Value modes: `UNIFIED` (default), `ALWAYS`, `NEVER`. Scene per-property unified
defaults to false, except native size/strength use the current native flag.
Scene is the root. A scene's own value never inherits. Stacks have the simpler
`inherit_stack` boolean, default false for every brush. This preserves native
unified values with brush-local native or shadow pressure controls.

Compatibility policy for the initial rollout is `LEGACY_SCENE`: preserve the
deprecated UnifiedPaintSettings flags read by today's SculptCore. The fork's
new Brush.use_unified_* flags are retained but do not silently replace this
policy. Generic controls show the effective policy. Conversion to per-brush
native-unified behavior is explicit, with a preview of differing values;
the user has been asked whether immediate conversion is preferred. Keep the
two flags independent until that compatibility choice is settled.

| Brush mode | Scene unified | Value owner | Edit strength .2 local / .8 scene to .6 |
| --- | --- | --- | --- |
| UNIFIED | false | Brush | local=.6, scene=.8 |
| UNIFIED | true | Scene | local=.2, scene=.6 |
| ALWAYS | either | Scene | local=.2, scene=.6 |
| NEVER | either | Brush | local=.6, scene=.8 |

Changing mode/flags never copies or resets values. With local=.2 and scene=.8,
ALWAYS then NEVER restores .2. Stack ownership resolves independently: with
ALWAYS and `inherit_stack=false`, rows edit scene values and brush pressure
curves; with NEVER and `inherit_stack=true`, they edit brush values and scene
stacks. Disabling pressure toggles its unique entry, preserving order, curve,
mix and factor. Adding an existing device updates it in place; explicit move
changes order. Imported duplicate types are a validation error, preserved for
repair rather than silently merged. Empty and fully disabled stacks are identity.

An absent value record uses the definition's default at the selected owner
without allocation. An absent stack record is an empty stack at that owner;
legacy native pressure adapters supply virtual entries without storing them.
If the requested parent lacks a *definition/capability*, resolve locally with
an explicit `parent_unavailable` diagnostic and local write target. Do not
invent parent records. Unknown local definitions cannot execute. Future parent
links must be validated as an acyclic graph before mutation; resolution also
detects cycles and fails before any stroke mutation.

Read resolution never allocates saved records or curves. Explicit setters
materialize only the selected owner, validate editability/type/range and notify
that owner. Radial controls and bracket sizing use these same setters, capture
the owner at invocation, and restore its old authored value on cancel. Owner
changes during a modal edit cancel it safely. Placement is brush metadata with
definition defaults; expansion is WindowManager runtime state. Neither inherits.
Positions have unique stable location IDs, each carrying one integer sort index;
ties sort by property ID. One property may occupy header, panel and context menu.

Size is a coupled adapter block: pixel diameter, world diameter and locked-size
mode share one value owner and inheritance policy. The current native pixel
setter rescales its world partner; the current world setter leaves pixels
unchanged (its scale helper divides the new value by itself). Preserve that
existing asymmetry in authoring adapters. Modal cancel snapshots/restores both values exactly through an
atomic native restoration operation (including authored presence where relevant).
The new path will honor SCENE size as world diameter/2, transformed to object
space, and honor the effective owner on off-screen fallback. These are explicit
corrections: the old stroke always pixel-unprojects and falls back to local
Brush.unprojected_size. Preserve pixel-mode baselines; test world-mode corrected
expectations independently with unequal object scale and paired non-round sizes.
The common stack ID is `sculptcore.brush.size`; pixel/world diameter fields
are two native representations of that semantic size. Apply its stack once
to the projected/effective radius; cursor uses the same evaluated size. Do not
attach separate pressure stacks to pixel and world representations.

For strength/size brush-owned pressure entries, enabled always reads the native
or shadow flag selected by current native capabilities, even after richer stack
metadata exists. CUSTOM always edits/evaluates the native curve; selecting a
generated preset preserves it dormant. A script edit to the dormant native
curve does not switch the preset; returning to CUSTOM reveals the edit.
Changing brush type reselects the native/shadow flag without copying either;
stack curve/mix/order metadata survives. Scene-owned pressure uses addon-owned
storage because there is no equivalent native scene curve/enable pair.
PINCH currently uses local Brush.strength for its `pinch` extra even while
unified strength drives the strength uniform. Retain that local-source family
adapter for legacy parity; expose the distinction in diagnostics. AIRBRUSH,
LINE and CURVE currently use the ordinary spacer; retain this behavior without
claiming native airbrush timing or line/curve authoring support. Texture angle,
rake/randomization, stencil placement and secondary mask texture are retained
native data with unsupported/approximate execution explicitly identified.

## Compound cavity adapter and automasking

Retain the existing specialized cavity block adapter for migrated data. The
block's ownership policy is `NATIVE_CAVITY` until explicitly changed to generic
UNIFIED/ALWAYS/NEVER; changing policy never rewrites either native block.
All cavity rows share the block policy, including enables, inversion, factor,
blur, curve toggle and custom curve. Do not independently inherit those fields.
Native precedence is recomputed on each synchronization, including script edits.

Let B/S mean either cavity enable is true on Brush/Paint. Fixtures use local
factor=1.75, blur=3, curve endpoint=.375 and scene factor=.625, blur=1,
curve endpoint=.875, with custom curves enabled on both.

| B | S | Effective block | factor / blur / endpoint | inversion |
| --- | --- | --- | --- | --- |
| false | false | disabled; edit Brush | no cavity effect | false |
| false | true | Paint (Scene ID) | .625 / 1 / .875 | scene inverted flag |
| true | false | Brush | 1.75 / 3 / .375 | brush inverted flag |
| true | true | Brush | 1.75 / 3 / .375 | brush inverted flag |

If both normal and inverted flags are true, inverted wins as in today's bridge.
Ordinary native RNA setters mutually exclude these flags; the both-true case is
a defensive malformed/raw-legacy case tested through an independent adapter
stub, not manufactured by two ordinary RNA assignments.
Editing the effective scene enable off can reveal the brush fallback; subsequent
rows re-resolve. UI shows the block owner and offers explicit local override.

| Native control | Engine target / defaults | Current bridge | v1 disposition |
| --- | --- | --- | --- |
| cavity and inverted cavity | automask_cavity=false, cavity_inverted=false | wired block | equivalent enable and inversion |
| cavity factor | cavity_factor=1, dimensionless | wired | equivalent remap, retain native authored value |
| cavity blur steps | cavity_blur_steps=2, integer neighborhood radius | wired | translated mesh/grid neighborhood estimator; no claim of geometric parity |
| custom cavity toggle/curve | cavity_use_curve=false, identity table | wired, 256 samples | equivalent curve-before-invert order; native owned curve |
| view normal enable/limit/falloff | automask_view_normal=false; limit=pi/2, falloff=25*pi/180 | not wired | new engine-owned settings, radians; do not adopt native defaults |
| front-face / backface controls | cull_backfaces=false | not wired | engine culling is part of view-normal mask; expose with view-normal enable |
| view direction | viewDir, object-space eye-to-surface ray | not wired for mask | transient per-dab sample, reflected with symmetry, all mesh/grid/batch paths |
| topology, face sets, boundary edges/face sets, propagation steps | no matching bridge | unsupported | omit SculptCore controls; retain native data |
| start normal / occlusion / normal falloff | no matching bridge | unsupported | omit; do not relabel as engine view-normal |

Engine view-normal uses abs(dot) when culling is off, so back faces fade like
front faces. Factor reaches zero at limit, ramps over falloff radians before
limit, and uses a hard cutoff for falloff<=1e-6. Degenerate normals/rays give
identity. This differs from native controls; store its settings separately.
All additional native automasking RNA fields are unsupported unless this table
explicitly maps them. Cavity is stroke-cached; view-normal is evaluated per dab.
The full advanced panel and header popover will share SculptCore's renderer;
remove `SCULPTCORE_PT_automasking` only after that renderer reaches execution.
Plan 2 must also correct native MeshAutomaskingSettings notifications to use
ptr.owner_id and mark the owning Brush dirty. Its current callback notifies
the active brush and never tags the edited asset. Test inactive-Brush scalar
and native curve edits, plus Scene edits leaving all Brush assets clean.
Cavity parameters are stroke-static, not device-dynamic in v1. Independent
command cavity configurations require separate configuration-keyed caches
(stroke generation plus full blur/factor/inversion/curve identity); a vertex's
fully remapped factor must not be reused for a different command configuration.

## Typed dynamics

v1 dynamic storage types are FLOAT32, INT32 and BOOL. Integer enums, bit masks,
IDs, vectors, strings, FLOAT64 and other integer widths are not dynamic-capable.
Static uniforms are never eligible. Capability is the intersection of type,
kernel metadata, execution-path support and delivered inputs; unsupported
configuration fails preflight before geometry mutation.

Preserve the authored base; evaluate a separate working value each dab.
FLOAT32 uses IEEE float32 operations matching the existing float evaluator.
INT32/BOOL arithmetic uses float64 (all int32 bases are exact); convert once
after the ordered stack. BOOL begins as 0 or 1. Given value v, response r and
mix factor a in [0,1], compute c as r (REPLACE), v*r (MULTIPLY), v+r (ADD),
v-r (SUBTRACT), or abs(v-r) (DIFFERENCE), then v=v+(c-v)*a.
Disabled/missing-sample entries are skipped. No conversion between layers.

At the end clamp to the declared numeric range intersected with the storage
range. INT32 then rounds ties away from zero and saturates before casting;
BOOL converts with >=.5 true after clamping to [0,1]. FLOAT32 retains its
declared finite range. Empty stacks return the valid authored base exactly.
Non-finite bases, factors, parameters and curve samples are rejected at write
or upload. A non-finite/missing device sample skips that layer for this dab;
no old sample persists. Non-finite intermediate arithmetic abandons that
layer and retains its previous finite v. No fast-math reassociation at typed
conversion boundaries. CPU/grid/program/batch tests use the same contract.

Independent examples: INT32 base 3, multiply .5 => 2; base -3 => -2;
base 3, multiply .5 then add .4 => 2 (conversion only at end); BOOL base true,
multiply .49 => false, multiply .5 => true; base false, add .75 => true.
INT32 max plus 1 saturates at 2147483647. Disabled ADD yields the original base.

## Input acquisition and sampling

Pressure domain [0,1], mouse pressure=1. Missing tablet pressure skips pressure
for that dab. Tilt X/Y arrive signed [-1,1], normalized as (x+1)/2 for curves;
missing tilt skips the respective layer. Tilt is a screen/tablet input, so
symmetry copies it unchanged. viewDir is geometric and is reflected instead.
ANGLE, CURVATURE and TWIST stay unavailable in v1.

Choose acquisition-time speed, requiring a generic fork timestamp API in
Plan 3. `Event.time` is monotonic seconds (double), sourced from GHOST event
time through queued/coalesced/INBETWEEN events. Synthetic event APIs accept an
explicit time with the same units; absence makes speed unavailable, never
handler-time speed. No timestamp is persisted in a brush.
The fork extension also preserves an input-presence mask from the device API
through GHOST/wmEvent/RNA and synthetic events. Pressure, tilt X and tilt Y
have independent validity bits; zero tilt is a valid sample, not absence.
Platforms must advertise only channels whose availability they can establish.

Speed is screen pixels/second, normalized by an authored positive
`speed_reference` (default 1000 px/s), clamped to [0,1]. First sample speed=0.
Each positive-time segment uses distance/delta-time; duplicate or decreasing
times yield missing speed and reset the derivative anchor. A pause contributes
to the next segment's time, so subsequent movement is slower. New strokes reset
all sample history. Motion is measured in region pixels, before symmetry.

Dabs emitted at arc fractions interpolate pressure, tilt and time between
the segment's event endpoints; speed is constant on that segment. Missing input
at either endpoint skips that input for interpolated dabs. Release flush uses
the final event and emits only residual dabs required by the existing spacer;
it never reuses a later pressure across an earlier segment. Example: x=0..100,
t=0..1, pressure=.2..1: dabs at x=25,50,75 have pressure=.4,.6,.8 and speed=.1
with default normalization. Delaying handler delivery changes none of these.
Constant-pressure baselines must remain unchanged; old variable-pressure
geometry is not an oracle for the corrected sampler.
Dab interpolation uses traveled arc length divided by the full segment arc
length, not cubic parameter t. Preserve that fraction in the spacer output.
Raw, anchored and drag-dot dabs use current-event inputs and speed even when
their geometric center stays at the anchor. Test a curved uneven-knot segment
in addition to the straight example.

## Curves and cache contract

Canonical device input x is clamped to [0,1]. Generated responses are:
CONSTANT(c)=c (default 1); TWO_STEP(t,lo,hi)=lo for x<t and hi for x>=t
(defaults .5,0,1); LINEAR=x; ROOT=sqrt(x); SQUARE=x*x;
SMOOTHSTEP=x*x*(3-2*x); SMOOTHERSTEP=x^3*(6*x*x-15*x+10);
SPHERE=sqrt(max(0,2*x-x*x)); POW4=x^4; INVSQUARE=x*(2-x).
Nonconstant default responses have endpoints 0,1. Threshold t is in [0,1],
including explicit endpoint behavior. TWO_STEP uses an analytic engine tag,
never a linearly interpolated LUT. Native distance falloff evaluates at
distance d; generated falloff uses x=1-d, whereas native pressure/cavity uses x.
Preserve hardness remapping and existing native falloff clamping from mapping.py.
Pressure curves may exceed [0,1]; final property range, not a curve clamp,
limits the result. Generated constant/step levels must be finite.

Switching to CUSTOM explicitly initializes an editable approximation of the
current preset (256 samples); discontinuous presets warn that editable Bezier
curves approximate the jump. Returning to a preset keeps dormant custom data;
returning to CUSTOM restores it. Reset/reseed is an explicit action.

Cache immutable LUTs by complete canonical definition and sample/domain config;
use hashes only as lookup accelerators. Native/custom fingerprints include all
evaluation-affecting points, handles, clipping, extension and mapping fields.
Check fingerprints at stroke start. Runtime generations accelerate known edits;
undo/load/deletion invalidates owner references and all engine upload state.
Cache capacity is 256 tables, LRU; active resolved strokes own their immutable
tables until completion. Track uploads separately per engine brush and command;
clear/rebuild invalidates uploads even when definitions match. No sampling,
hashing, ownership resolution or ctypes table upload occurs per dab.

## Owned CurveMapping API selected for Plan 2

Declare `bpy.props.CurveMappingProperty(name="", description="", update=None)`.
v1 is a single scalar channel; no color-space variants. It is an RNA pointer
property whose unset read is None. Explicit
`owner.curve_mapping_initialize("property_name", preset='LINEAR')` allocates
once and returns the owned mapping; `owner.property_unset("property_name")`
removes it. Nesting in PropertyGroup and CollectionProperty resolves the true
Brush/Scene ID. `template_curve_mapping` draws an Initialize control for None
without allocation; its undoable first-edit operation initializes the property.

Persistence uses ONLY existing IDProperty GROUP/IDPARRAY/array/scalar/string
types: a tagged, versioned group under the declared property name. It contains
channel definitions, points/handles, clip/extension settings and required
evaluation metadata. No new IDProperty type, DNA payload, ID dependency, owner
pointer, sampled table or Python address is serialized. Old readers preserve
these ordinary properties even when the declaration is absent. Add an API
capability signal (`hasattr(bpy.props, 'CurveMappingProperty')`); old forks can
preserve data but cannot edit it with the widget. Unsupported stock readers
cannot run SculptCore mode; Plan 2 must prove curve-definition preservation
through open/resave independently of that mode capability.

The fork provides a runtime CurveMapping materialization of the saved group.
All widget/RNA mutations synchronize definitions and tag the actual owner;
Brush changes mark that brush's asset dirty, Scene changes tag Scene. Optional
Python callbacks run once after the complete mutation and are removed on
unregister. Essential notifications remain native and do not depend on callbacks.
No self-assignment of unrelated brush properties. Two declarations retain their
own callback identity. Read-only owners reject mutations before touching cache.

Raw writes to the backing IDProperty group are NOT a supported edit API.
After raw writes, callers must explicitly call
`owner.curve_mapping_sync("property_name")` before save/dirty-state inspection.
Sync validates the complete definition, rebuilds runtime state and notifies the
owner; invalid definitions raise without deleting or replacing saved data.
Access/evaluation can detect changes opportunistically, but raw writes alone
do not promise dirty propagation or save-reminder detection. File serializers
preserve raw data as ordinary IDProperties without callbacks or mutation.
When declarations are absent, raw definitions are opaque preserved properties;
re-register validates before use. Raw writes follow Blender's explicit undo
conventions. Runtime revisions are monotonic within a lifetime only.

Retained curve/point wrappers must carry runtime lifetime/identity tokens,
independent of movable arrays or IDProperty addresses. On point removal/reset,
owner removal, undo/load or unregister, invalidate wrappers with ReferenceError.
Insertion/reorder may preserve logical identity or invalidate safely. Open
widgets must re-resolve through an owner/record identity and close safely after
deletion. Do not ship raw pointers into point arrays as retained handles.
Copying owners deep-copies ordinary IDProperties and creates new runtime
identities. Revert reloads owned definitions with the Brush itself.

Implementation requires an owned-curve RNA property discriminator ahead of
generic IDProperty verification/pointer dispatch, which otherwise deletes
wrong-type storage or returns an IDProperty pointer as CurveMapping data.
Get/never-create-get, presence and unset must use this dispatch. Initialization,
unset and sync are native transactions: check editability, validate, invalidate
old handles, mutate storage, tag owner and run the declaring callback. Unknown
schema versions raise on edit/access but remain preserved on save.

Use heap-stable runtime owner records with lifetime generations checked at
RNA/Python access boundaries. Invalidate all affected owner-record wrappers,
collections, iterators and widget handles on any structural parent/point change;
v1 need not preserve their identity across such changes. No retained parent
IDProperty addresses. UI popup callbacks hold validated handles and reacquire
native pointers only for their immediate operation. One native commit path
handles RNA setters, methods and widget edits; callback once per RNA operation
or interactive widget update, with the enclosing drag forming one undo step.
Nested unset PropertyGroup lookup also needs a non-allocating path. Freeze the
exact tagged-group serialization schema before native code is written; its
supported compatibility matrix begins with the current pre-change fork and a
stock Blender 5.x reader, whose actual binary identity is recorded by tests.
The exact payload is specified in [owned-curve-storage-v1.md](owned-curve-storage-v1.md).

## Commands and integration

Commands have explicit parent links to the resolved brush by default, optional
links to a named command, or no parent. Order is execution order only. Validate
cycles and missing parents before a stroke. Each command has sparse typed value
overrides and independently local/inherited whole stacks (default inherited).
Resolve all links on the host and upload complete typed command state without
inheritance flags. Existing main-plus-smooth programs retain their explicit
strength/invert behavior. A command without a parent uses registry defaults.

Evaluate command radius/extents before node selection, pinning, undo capture or
mutation. Use conservative union regions (all nodes only for explicitly declared unbounded commands),
then execute with exactly the preflighted values. Restore authored brush and
command state on success, errors and cancellation. No previous-command leakage.
Preflight the union of topology/host-preparation requirements too. Classify
hooks as configuration-invariant or command-dependent; only invariant hooks
may be deduplicated by function pointer. Dependent hooks execute with resolved
command state and configuration-specific cache identity (including ENHANCE
rings/inner values). Test later-command cavity enable and differently configured
ENHANCE commands; shared-brush hook execution cannot satisfy this contract.
New per-command UI is outside this migration. New path remains opt-in until
all eight gates pass; gate tests assert which path actually executed.

## Spatial support clarification from the user (2026-09-18)

Ordinary brushes never acquire unbounded reads from their falloff kind, shape or
nonzero endpoint. They hard-clip to zero outside the falloff boundary. Whole-mesh
reads require an explicit declaration, such as Kelvinlet's `@unbounded`.
This supersedes the earlier prepared-falloff all-node policy and its parity oracle.
Correct bounded selection and pointwise clipping together; test independence from
spatial leaf partitioning. Frozen fixtures showing spill outside the boundary
remain historical evidence, not the desired corrected result.
