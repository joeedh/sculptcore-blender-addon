**Execution verdict: revise before implementation.** The all-leaf approach addresses support truncation, but the plan leaves restoration and numerical safety gaps. This review uses only the packet; compiler proof construction is left to the other reviewer.

1. **Standalone extent restoration does not follow from the existing scopes.**

   Step 3 promises restoration of the original working `unboundedExtent`. Both standalone executors construct `ScopedBrushWorkingValues(..., true)`, whose constructor skips every value that is not an `executorSetting`. `unboundedExtent` is absent from that setting list. A declaring command can therefore publish its prepared extent and leave it behind for the next nondeclaring command. Programs use the full scope, so testing only programs misses this.

   Evidence: [mesh standalone scope](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:194), [grid standalone scope](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.cc:222), [scope filtering](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_program_preparation.cc:239), [executor settings](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:30).

   **Minimal correction:** explicitly save/restore extent in standalone and program scopes, including successful zero-radius and missed dabs. Keep an inherited extent snapshot separate from override eligibility: override validation currently treats membership in `candidate.values_` as authorization, so simply appending an undeclared extent there would admit the forbidden override. See [override validation](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:457).

2. **A finite positive cutoff product does not establish safe window arithmetic.**

   The window divides by `0.2f * R`. A finite positive subnormal `R` can pass the proposed check while that denominator rounds to zero. At the boundary, the expression becomes `0/0`; multiplying displacement by the resulting NaN does not produce zero support. The checks must use the actual execution precision, not just a double-precision product.

   Evidence: [window implementation](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_command.h:359); plan lines 52–54.

   **Minimal correction:** either validate the float product and its positive finite transition width, or change the window formulation to handle these values explicitly. Test product underflow, transition-width underflow, overflow, and exact boundary. Run this validation before every `validateOnly` return and mutation barrier.

3. **All-leaf execution evaluates Kelvinlet outside the cutoff; a zero window cannot contain invalid arithmetic.**

   Kelvinlet computes its entire field before multiplying by the window. For example, a sufficiently small positive radius at `grabFrom` can overflow `invE3`, making `dot(grabTo, r) * invE3` evaluate as `0 * Inf`. Large radii can overflow `radius * radius`. The existing radius checks establish only finiteness, nonnegativity, and a finite reciprocal; the proposed extent checks do not close these gaps.

   With all leaves selected, previously unvisited vertices also execute this arithmetic, even where the intended window is zero. The generated kernel then writes the result and records the vertex as affected.

   Evidence: [radius validation](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:185), [generated arithmetic and unconditional write](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/kernels/generated/kelvinlet.brush.gen.h:60).

   **Minimal correction:** establish a numerically safe Kelvinlet evaluation or an explicit validated numeric envelope. Short-circuit outside an enabled cutoff before evaluating the field; that alone does not repair inside-cutoff or no-cutoff cases. Add finite-coordinate assertions for extreme accepted inputs, including a vertex exactly at `grabFrom`. Reject unsupported candidates before capture; post-write NaN detection would violate atomic failure.

4. **“Independent raw execution over all leaves” needs a separate cavity contract.**

   The shown raw grid path stamps cavity for every visited owned vertex. Prepared execution stamps only first contact and writes a neutral active-column value elsewhere. Feeding all leaves to raw execution therefore freezes cavity outside the cutoff prematurely. When support grows after intervening deformation, raw and prepared results can legitimately differ. Raw parity with cavity enabled is consequently an invalid acceptance oracle unless corrected.

   Evidence: [prepared grid contact](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.h:1190), [raw grid stamping](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.h:1220).

   **Minimal correction:** specify cavity-disabled raw parity for field execution and a separate independent first-contact oracle for cavity. That oracle must use live stage-input coordinates, cutoff centered on `surfacePos`, strict boundary exclusion, and universal contact when cutoff is disabled. Kelvinlet’s field origin is separately `grabFrom`; tests should deliberately make the two centers differ. See [field origin](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/kernels/kelvinlet.sbrush:58) and [window center](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_command.h:365).

5. **Batch atomicity must be explicitly scoped to the rejected candidate.**

   Both input-batch APIs execute each dab and mirror immediately. A failure in a later dab returns `-1` after earlier geometry changes have already occurred. The packet shows no batch rollback. Extending “atomic failure” to the whole submitted batch would therefore require substantially more than this plan proposes.

   Evidence: [mesh batch execution](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/c-api/mesh_stroke_batch_c_api.cc:179), [grid batch execution](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/c-api/grid_stroke_c_api.cc:358).

   **Minimal correction:** state that rejection is atomic per prepared image/program candidate, while earlier successful batch work remains applied. Test a pressure-dependent invalid cutoff in a later dab and verify both preservation of earlier work and absence of rejected-candidate mutations. Separately test `n == 0`, required-prepared policy, and automatic policy; zero-count calls enter `validateOnly`, so late placement of support validation would silently bypass it.

Optional refinements:

- Keep the existing falloff eligibility restriction for this slice. Relaxing it for unbounded commands is a separate compatibility decision.
- Document that all-leaf Kelvinlet currently captures and reports affected vertices even when displacement is zero; movement assertions should inspect coordinates, not affected counts.
- Add stale grid-generation/open-step rejection and subsequent bounded-stroke tests. The existing [attachment checks](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.cc:31) are worth preserving explicitly; the packet does not demonstrate a new lifetime defect.
- Do not use the shown raw mesh batch API as the all-leaf reference: it still performs a radius query. Use an explicitly enumerated leaf set. See [raw batch query](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/c-api/mesh_stroke_batch_c_api.cc:165).