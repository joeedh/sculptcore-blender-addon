**Compiler verdict: revise before implementation.** The direction is viable, but the plan leaves three eligibility-proof obligations unresolved. These are pre-implementation blockers, not claims that an unsubmitted patch is broken. Review limited to the supplied packet and compiler lens; no tools used.

1. **A body-local reduce proof does not prove initialization at the generated call site.**

   The emitter declares every non-Vertex vertex parameter without initialization, then passes matching locals to every reduce stage in source order. Matching checks name and type, not initialization. See [emit_cpp.cc:2301–2347](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2301).

   A reduce with an unused `in float a` and an initialized `out float b` can satisfy the proposed body restrictions, yet its generated call reads uninitialized `a` when passing it by value. Likewise, proving every *declared reduce output* initialized does not establish that every additional vertex parameter has a producer.

   **Minimal correction:** add command-level definite-initialization analysis over the actual generated reduce-call sequence. Require matching types, initialized by-value arguments, and initialized vertex inputs before the vertex loop. For this initial slice, an even smaller policy is to accept only scalar `out` reduce parameters and require coverage of every additional vertex parameter. Keep unsupported arrangements raw-only rather than introducing new general compiler errors.

   **Acceptance:** unused uninitialized `in` argument; vertex input without a producer; consumer before producer; valid producer before consumer if supported.

2. **The existing sticky assignment audit rejects precisely the writes the new proofs must admit.**

   `preparedAssignmentSafe` admits lexical value locals and selected vertex geometry targets. It does not generally admit host-uniform assignments or reduce-output assignments. Every rejected assignment sets the shared `preparedStateUnsafe` flag. See [emit_cpp.cc:243–285](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:243) and [emit_cpp.cc:1050–1053](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:1050).

   Consequently, removing the factory’s blanket host/reduce exclusion still leaves Kelvinlet unsafe. Clearing the flag after recognizing a safe prelude is also unsound: textures are emitted before hosts and reduces, so clearing it can erase an earlier unsafe finding. See [emission order at 2221–2252](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2221) and [factory predicate at 2436–2440](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2436).

   “Combine these proofs with the existing assignment/call audit” needs an explicit implementation rule.

   **Minimal correction:** preserve monotonic command-level unsafety. Either exempt only the exact assignments certified by a stage proof, or maintain isolated stage results and combine them with all other audit results. Never reset previously accumulated unsafety. Traverse all evaluated expression children, including assignment-target indices and call arguments; a permitted destination alone is insufficient.

   **Acceptance:** safe host/reduce plus unsafe texture or vertex write; unsafe host before and after a safe host; safe reduce followed by an unsafe reduce. Assert emitted metadata, not merely successful parsing.

3. **“Pure arithmetic” is not a sufficient scalar safety policy.**

   The proposed rule does not restrict reduce scalars to FLOAT32. The IR includes `Int`, arithmetic division, unary negation, and compound assignment. See [ir.h:19–32](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/ir.h:19), [ir.h:45–74](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/ir.h:45), and [parameter directions at 185–197](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/ir.h:185).

   An initialized integer output computed using division by zero or signed overflow is syntactically pure but can invoke C++ undefined behavior. Also, `out += expression` reads the output before writing it; it cannot establish initialization. Floating arithmetic can produce nonfinite outputs from valid finite uniforms, so “pure” must not silently become a promise of numerical validity.

   **Minimal correction:** initially restrict reduce parameters, locals, and intermediate arithmetic to FLOAT32 with simple `=` assignments, and explicitly define the proof as a shared-state/initialization guarantee. If integer arithmetic or numeric conversions are admitted, specify their separate safety obligations. If finite reduce outputs are required, that needs an additional proof or validation policy.

   **Acceptance:** compound assignment before initialization; integer division/overflow; unsafe conversion; floating zero denominator with an explicitly documented expected eligibility result.

Two additional requirements should be made concrete before implementation, although the packet does **not** establish existing bugs in them:

- **Range proof must use emitted comparison semantics.** Kelvinlet’s host compares float-suffixed constants, while its manifest stores double bounds: [generated host at 32–39](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/kernels/generated/kelvinlet.brush.gen.h:32), [manifest at 101–103](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/kernels/generated/kelvinlet.brush.gen.h:101). Preparation calls `normalizeScalarDeclaration`, whose implementation is absent from the packet: [brush_preparation.cc:190–195](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_preparation.cc:190). Require the accepted typed domain to make each emitted strict comparison false: upper bound ≤ emitted upper threshold; lower bound ≥ emitted lower threshold. Source-double equality alone is insufficient. Specify a compiler-buildable normalization mechanism and boundary fixtures; this packet cannot verify helper linkage or normalization behavior.

- **Specify the complete metadata contract.** Both executors independently reject any `execHost`, irrespective of `preparedScalarSafe`: [mesh capability](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/brush_executor.cc:17), [grid capability](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/grid_executor.cc:55). Require a default-false host certificate covering **every** host in the composed callback, retain the whole-command scalar certificate, and gate a present callback on both. Preserve raw host execution. Test generated mesh/grid factory instantiations and a stale or hand-authored factory with an uncertified callback.

**Optional refinements:** emit reasons for prepared ineligibility; share the restricted expression walker between proofs; add empty-host and harmless-parentheses fixtures. These improve maintainability but need not expand the initial accepted language.