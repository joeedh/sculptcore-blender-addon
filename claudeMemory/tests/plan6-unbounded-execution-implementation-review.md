Two concrete defects and four acceptance gaps stand out. This is a packet-only source review; I did not run tests.

1. **P1 — Batch symmetry does not transform the unbounded field.** Both batch implementations mirror only the dab center and normal. `grabFrom` and `grabTo` remain unchanged, although Kelvinlet reads both directly from `Brush`. Consequently, a mirrored image moves the cutoff center but retains the primary image’s force origin and direction. With cutoff disabled, images apply the same field repeatedly.

   **Minimal correction:** Preserve the primary grab frame, transform both vectors by each image’s signs within a restoring scope, and validate that image’s resulting frame before execution. Add mesh/grid, standalone/program tests comparing mirrored batches with separately configured image executions, including disabled cutoff.

   Citations: [mesh batch image loop](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/c-api/mesh_stroke_batch_c_api.cc:180), [grid batch image loop](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/c-api/grid_stroke_c_api.cc:359), [generated field reads](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/kernels/generated/kelvinlet.brush.gen.h:67).

2. **P2 — Certified reduce syntax can collide with the generated `ctx` parameter.** For example:
   ```cpp
   reduce void prep(out float a) { float ctx = 1.0; a = ctx; }
   vertex void apply(inout Vertex v, in float a) {}
   ```
   The proof accepts this initialized FLOAT32 local. Generated-name validation does not reserve `ctx`, but the emitted reduce function already has a `CommandCtx<TYPES> &ctx` parameter. The resulting C++ redeclares that parameter. An `out float ctx` parameter has the same problem. Certificate-string assertions alone will miss the compilation failure.

   **Minimal correction:** Reject bindings that collide with generated parameters, or rename generated parameters into the already-reserved namespace. Add these fixtures and compile an accepted generated prelude fixture.

   Citations: [reduce-local proof](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/prepared_preludes.h:155), [reserved-name check](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:182), [generated reduce signature](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:1499), [certificate-only assertions](/C:/dev/blender/sculptcore-blender-addon/engine/tests/test_sbrush_member_types.cc:56).

3. **P2 — Cavity tests cannot establish preservation of actual first-contact values.** The execution matrix sets `cavity_factor = 0` and uses a constant `0.5` oracle. Evaluation counts check reuse, but incorrect stored values, incorrect geometry used for the initial evaluation, or stale stage-input sampling can remain invisible. The matrix also does not deliberately place a vertex exactly on the cavity cutoff; the separate window test is not a cavity-cache test.

   **Minimal correction:** Use nonconstant cavity factors on asymmetric geometry. Independently calculate each vertex’s factor from geometry at its first contact, deform that geometry, and verify the cached value on later dabs. Include exact-cutoff exclusion, disabled-cutoff universal contact, and DRAW moving a vertex across the later stage’s contact boundary. Assert one configuration despite changing `mu`/`nu`.

   Citations: [constant cavity setup](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:217), [constant-value oracle and count assertion](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:289), [first-contact storage](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/prepared_cavity.h:87).

4. **P2 — Extent restoration is tested without exercising the leak it must prevent.** The helper test prepares declared and inherited snapshots, but the execution matrix uses only inherited extent: Kelvinlet does not declare it. Its restoration assertion therefore checks that an unchanged extent remains unchanged. There is no executing sequence where a declaring stage installs one extent and a later undeclaring stage must recover the authoritative inherited extent.

   **Minimal correction:** Add a declaring test command followed by an undeclaring unbounded command, with distinct extents and observable support differences. Exercise standalone executor-only restoration and full program restoration after success, zero radius, missed support, and rejection.

   Citations: [snapshot helper test](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:147), [execution restoration assertions](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:313), [explicit scope save/restore](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_program_preparation.cc:233).

5. **P2 — Rejection tests do not establish the complete pre-mutation contract.** Executor tests inject only infinite inherited extent and check positions, stroke-path count, and an unspecified `gridState`. Overflow, cutoff underflow, transition-width underflow, and invalid grab vectors are mostly helper-level checks. No supplied assertions establish unchanged mesh query lists, topology/cache state, undo capture, property declarations, or persistent attributes for these executor failures.

   **Minimal correction:** Run those invalid cases through both executors, standalone and as a late program stage, with execution and `validateOnly`. Snapshot the named state explicitly. Include every component of both vectors, NaN and infinity, positive-cutoff acceptance boundaries, and zero-radius skipping.

   Citations: [helper rejection cases](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:168), [executor rejection assertions](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:274), [validation implementation](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:515).

6. **P2 — Several required integration and lifetime cases lack packet evidence.** The supplied matrix does not explicitly select both mesh live/CSR modes, execute an independent raw all-leaf reference, begin with zero/missed support, or follow unbounded execution with a bounded stroke. It contains no required/automatic-policy batch tests, zero-count batch validation, later-dab rejection preserving earlier accepted dabs, Python calls, or installed-package provenance.

   Lifetime verification is also incomplete: mesh `preparedStepValid()` and grid attachment setup/invalidation are absent. The shown grid check establishes some generation and step checks, but cannot alone establish owner lifetime or safe correspondence between current leaves and `nodes_`.

   **Minimal correction:** Supply the omitted lifetime implementation and focused regressions for these cases; retain the existing coordinate and undo/redo assertions.

   Citations: [matrix dimensions](/C:/dev/blender/sculptcore-blender-addon/engine/tests/prepared_unbounded_cases.h:347), [mesh lifetime gate](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:153), [grid lifetime gate](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.cc:27), [grid leaf-to-node indexing](/C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.h:1063).

The shown extent snapshot/application and explicit restoration paths look consistent. Both executors validate positive-radius unbounded support before `validateOnly` returns or query mutation, select all nonempty leaves, and require both scalar safety and host no-op certification. Cavity contact uses `surfacePos`, strict positive-cutoff exclusion, and universal disabled-cutoff contact. Grab vectors are **live reads**, not snapshot members; their validity depends on the documented synchronous, non-reusable preparation lifetime. The packet does not fully show certificate aggregation or every intervening execution helper, so those broader guarantees remain unverified.