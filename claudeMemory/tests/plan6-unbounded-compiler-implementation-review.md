**One concrete issue: generated-name collisions can receive a safe certificate.**

`reduceCalls()` rejects collisions with fields, other inputs, and the vertex parameter, but does not reserve emitter-owned names ([prepared_preludes.h:188–194](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/prepared_preludes.h:188)). Consequently, this passes the shown proof:

```cpp
reduce void prep(out float any_moved) { any_moved = 1.0; }
vertex void apply(inout Vertex v, in float any_moved) {
  v.co.x += any_moved;
}
```

The emitter declares `bool any_moved = false;`, then declares every additional vertex parameter in that same scope. This produces a conflicting `float any_moved;` declaration and uncompilable generated C++ ([emit_cpp.cc:2285](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2285), [emit_cpp.cc:2313–2319](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2313)).

The same naming problem has a **runtime correctness consequence** with a vertex local:

```cpp
vertex void apply(inout Vertex v) {
  float any_moved = 0.0;
  v.co.x += 1.0;
}
```

The generated post-body `any_moved = true;` updates the user’s inner local. The outer flag remains false, so geometry changes skip `ctx.node.update(...)` ([emit_cpp.cc:2362–2388](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2362)). Nothing in the shown assignment audit or final certificate conjunction rejects this ([emit_cpp.cc:245–286](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:245), [emit_cpp.cc:2448–2452](C:/dev/blender/sculptcore-blender-addon/engine/source/brush/compiler/emit_cpp.cc:2448)).

**Fix:** generate collision-free internal identifiers and use them consistently, or diagnose reserved-name collisions across stage parameters and locals. Rejecting these names only in the prelude proof would leave the raw code-generation defect intact.

**Tests:** add both fixtures, compile their generated C++, and verify that the vertex-local case requests node updates after changing coordinates. The current prelude helper checks emitter errors and certificate strings only, so it cannot detect either generated compilation failures or incorrect update behavior ([test_sbrush_member_types.cc:48–69](C:/dev/blender/sculptcore-blender-addon/engine/tests/test_sbrush_member_types.cc:48)).

I found no additional definite prelude initialization or float-bound unsoundness in the supplied excerpts. Verification of general literal and identifier lowering remains limited because the relevant `emitExpr` cases were not included.