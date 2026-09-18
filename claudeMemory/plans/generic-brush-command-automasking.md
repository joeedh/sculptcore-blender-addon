# Plan 6: command-owned automasking preparation and cavity caches

Completed 2026-09-18. [Verified gate](../tests/plan6-automask-gate.json) and
[evidence](../codebase/generic-brush-plan6-evidence.md#command-automasking-gate--2026-09-18).

Reviewed by fresh preparation/transaction and cache/geometry CLI reviewers;
findings and dispositions below are incorporated before implementation.
The prepared MASK gate is complete; this closes the next native
capability dependency before generic host adoption.

## Current seams

- PreparedBrushScalars includes common properties and kernel uniforms only.
  Executor-owned cavity/view-normal settings are absent from both that set and
  Brush::builtinPropDescriptorSpan, although they are reflected native members.
- Mesh/grid prepared admission rejects brush.automask_cavity wholesale. Removing
  the guard alone would miss later-command enable, topology preparation and cache
  separation. Both raw executors cache one remapped factor per vertex/stroke.
- Mesh cavity needs ring1 ensured before freezing. Command overrides must be
  validated before any cache, attribute, topology, store or undo mutation.
- The frozen contract requires command-independent stroke-static cavity and
  reflected geometric viewDir on the future generic symmetry path. Existing raw
  view-normal policy pins a camera ray; retain it for legacy execution. This slice
  prepares the static settings; generic per-image viewDir adoption remains in the
  host consumer task and must use the frozen contract's independent expectations.

## Implementation

1. Add an explicit executor-owned static scalar catalogue for automask_cavity,
   cavity_factor, cavity_blur_steps, cavity_inverted, cavity_use_curve,
   automask_view_normal, cull_backfaces, view_normal_limit, view_normal_falloff.
   Add these authoritative native members to builtin descriptors with dynamics
   disabled. The catalogue is engine-owned, separate from DSL kernel manifests.
   Prepare this fixed set for every prepared command, using native member values
   unless the command supplies an exact typed override. Include matching values
   in scoped restoration, without publishing persistent property declarations or
   default slots merely for these executor settings. Reject device stacks on this
   static set, unknown IDs, type mismatch and nonfinite float values. Retain full
   finite FLOAT32 domains and signed INT32 transport; blur must be nonnegative and
   less than INT32_MAX to make the BFS depth increment defined. Validate before
   mutation, including a disabled cavity configuration with malformed parameters.
2. Add optional command-owned cavity LUT payload with exact 256 finite FLOAT32
   samples. Omitted payload inherits the Brush LUT; explicit identity LUT replaces
   it. Copy into the prepared command candidate, never retain caller pointers.
   Add checked public replacement/removal transport and generated bindings using
   established Vector<float> transport. A failed upload preserves the previous
   command. Include the LUT in working-state restoration on every exit. Raw paths
   explicitly reject command LUT overrides, including zero-dab automatic fallback.
3. Candidate preparation resolves each command's full cavity configuration before
   spatial selection. Union the requirement for enabled positive-radius commands.
   After complete preflight and a nonempty region, ensure mesh ring1 before freeze
   even when only a later command enables cavity. Do not change unrelated prepared
   guards (dyntopo, anchored/unbounded, general attributes, host stages, previews).
4. Prepared execution gets executor-owned transient cavity cache entries keyed by
   exact full configuration (blur, factor, inversion, use-curve and complete LUT),
   current mesh/domain identity, stroke transaction and topology generation.
   Hashes may accelerate lookup but cannot replace equality checks. Cache sparse
   per-vertex factors per entry, frozen at that configuration's first contact.
   BeginStep/attach/rebuild retires entries; mesh topology changes retire stale
   entries. Ordinary coordinate deformation does not invalidate first-contact
   values within a stroke: that preserves the existing cavity contract. Filling
   occurs serially before parallel kernels; references remain stable during the
   kernel. Identical configurations share work, different configurations never
   share a remapped factor. Cache no-op/miss/rejected commands cannot publish data.
5. Preserve legacy raw cavity execution and cache policy when the generic/prepared
   path is not used. Introduce a scoped prepared execution context to select the
   new cache inside shared exec/execStage without leaking into subsequent raw dabs.
   Keep live view-normal evaluation and camera data outside cavity cache identity.
   Cache growth is bounded by distinct static configurations in the stroke; tests
   cover reuse, reset and changed configurations. No persistent cache serialization.

## Acceptance

- Read-only candidate tests for authoritative static bool/int/float sources,
  independent command overrides, absent properties, invalid/stale inputs, static
  dynamics rejection and exact working/LUT restoration. Keep failed late commands
  atomic before ring1 preparation, allocation, undo capture and counters.
- Independent cavity oracle using cavityRawT/cavityRemap on the configuration's
  first-contact geometry; test different blur/factor/inversion/LUT, later-command
  enable, larger secondary radius, newly reached vertices, same-config reuse,
  changed stroke/topology/domain identity, and no accidental per-dab recomputation.
- Actual mesh live/CSR and grid immediate/deferred execution; standalone/program,
  Python transport, input batches, mask+draw+smooth, exact undo/cancel and subsequent
  raw/prepared strokes. Default-off cavity remains identical to prior gate outputs.
- Snapshot cache payload/evaluation counts in tests to prove configuration
  separation and warm reuse. Test failed LUT replacement/removal, caller mutation,
  inherited vs explicit identity, cold upload and required prepared policy.
- Extend the safe headed harness with actual cavity settings and demonstrate a
  measurable difference from cavity off. Native/Python builds, generated bindings,
  applicable regression matrix, installed package and provenance smoke.

This gate does not claim generic UI, owner resolution in the modal operator,
viewDir symmetry adoption or Plan 6 completion. Those remain explicit next tasks.

## Review corrections and decisions — 2026-09-18

- Dedicated catalogue pass: supply explicit temporary ScalarDeclaration domains
  to prepareValue, with dynamic=false, authoritative native addressing and no
  insertion into declarations_. Validate existing property identity/type/schema/
  stacks but ignore property value/getter/range for the static native value.
  Catalogue entries named by DSL manifests must exactly match type/static/range
  policy; reject conflicts and prepare the target once. Normal kernel processing
  must not republish a catalogue declaration.
- Typed command transport already exists outside the first review packet:
  BrushProgram_setScalarChecked in mesh_stroke_batch_c_api.cc and Python
  set_command_scalar in brush_properties.py. Retain/test that checked float64
  transport for BOOL, signed INT32 and FLOAT32; do not add a competing scalar API.
  Add bound LUT methods with an explicit native C seam if reflection proves unable
  to call them, as required by the prior command-stack transport experience.
- Resolve/copy all 256 LUT entries for every stage before execution, including
  inheritance and disabled configurations. Validate public raw mutations again
  at preparation. Apply each stage's complete LUT, even when it inherited, so a
  preceding override cannot leak. Removal resumes inheritance on next preparation.
- Standalone retains its existing common-scalar publication behavior (accepted
  misses/zero calls included). Protect only the new executor-owned settings/LUT
  with a dedicated scope before first working write; program scope additionally
  restores all prepared working values as before. Rejected candidates publish no
  declarations or persistent/executor/mesh allocation; scratch allocation is allowed.
- First contact means a vertex inside the executing command's spherical radius
  (strict normalized distance <1) immediately before that command's kernel. The
  larger shared program leaf union does not establish contact for a smaller
  command. BFS may read neighbors outside the support without caching them.
  Accepted positive-radius zero-strength/texture/mask-effect stages may cache
  those in-support vertices; there is no general promise to detect every no-op.
  Zero radius, no in-support vertices and rejected preflight cannot fill entries.
- For stale ring1 on an already frozen mesh, thaw after complete validation and
  nonempty selection, ensure ring1, then apply the program's freeze/live policy.
  A prepared cavity stage requires valid ring1 and never silently bypasses cavity.
- Reuse one executor-owned CavityScratch across entries. Warm hits do no BFS and
  no capacity-sized scratch initialization. Measure configuration-vertex payload
  and evaluation counts. No eviction/recomputation from changed geometry is allowed
  within a transaction. beginStep retires cache even if mesh strokeGen repeats.
- Oracle geometry is captured immediately before the cache fill: current co/no
  as supplied by the chosen immediate/deferred normal policy. Test A -> deform
  -> B -> A, newly entered support, each key field and in-place LUT mutation.
  Compare each policy against its own independent oracle, not assumed parity
  between policies with different normal refresh cadence.

Implementation seam checks: non-accumulating contact uses the same derived base
coordinate as its AccumOrig vertex iterator (cavity's BFS still samples live
geometry). Kernels evaluate automasks even when strength() returns zero, so every
visited vertex needs a valid factor address. Keep a reusable active factor column
for the current stage, set outside-support visited vertices to identity, and copy
cached in-support factors into it. Cache entries store only contacted vertex/value
pairs; the stage column's materialized pages are separate reusable scratch.

## Implementation review dispositions

- Require an open mesh executor step with unchanged tree, mesh, Brush and log
  ownership. If a log is present, validate its current unfinalized step ID before
  prepared mutation. Calls after endStep fail, matching grid admission.
  The addon's freshly constructed MeshLog legitimately has no active mesh until
  a legacy operation binds it. Permit that initial null binding; an existing
  binding must match the captured executor mesh. Keep log pointer/step-ID checks.
- Clear BFS visit stamps on uint32 token wrap and restart at one. Add a forced
  near-wrap oracle; ordinary warm hits still avoid BFS and scratch initialization.
- An omitted manifest range deliberately inherits the fixed native catalogue
  domain; only an explicit conflicting range is rejected. This clarifies the
  earlier exact-policy wording without admitting any new runtime values.
- Extend evidence with nonzero draw/mask/smooth effects, command LUT replacement
  followed by inheritance, Python transport, exact restoration, lifecycle rejection,
  first-contact oracles after deformation and frozen topology invalidation.
