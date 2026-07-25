# Addon-authored engine kernels (`*.sbrush`)

Developer-authored SculptCore brush kernels carried by this repo and compiled
into `sculptcore_capi.dll` alongside the engine's built-ins. These are
**build-time sources**, not runtime addon files — they live at the repo root
(not in `sculptcore_addon/`, which is copied verbatim into Blender installs)
and reach the DLL through the engine's "extra kernel dirs" build option:
`tools/build-blender-dist.mjs` passes `--kernels-extra <this dir>` to the
engine's `make.mjs bundle` whenever this directory contains `.sbrush` files.
For the language itself see the engine's `documentation/brush_dsl.md`; for the
build machinery, "Extra kernel dirs" in `documentation/brush_compute.md`.

Rules that matter when adding a kernel here:

- **Uniforms are member-backed or store-backed.** Names listed in
  `Brush::builtinPropNames` (`engine/source/brush/brush.h`) lower to the
  engine member `ctx.brush.<name>` — sharing whatever else writes that member.
  Any *other scalar float* uniform automatically gets its own slot in the
  `Brush.namedFloats` store (per-build slot, DSL default seeded, written by
  the addon via `setNamedFloat`) — so a kernel can own a new float tunable
  without touching the engine (`nudgeProjection` here is one). Non-float
  uniforms still need an engine-side member. Builtin `ctx` names
  (`surfaceNo`, `strokeDir`, `mousePos`, ...) come from the executor's
  `CommandCtx`.
- **Names must not collide with built-ins or each other**: file stem,
  `@brush("name")`, and the uppercased enum item (case-insensitive) are each
  checked by the registry step, which fails the build with a message.
- **Ids are per-build**: kernels register as `SculptBrushesBuiltinCount + i`
  (stems sorted bytewise). Nothing persists these ids — the addon resolves
  kernels by *name* through the reflected `SculptBrushes` enum, so a DLL
  without a given kernel simply reports it missing.
- **CPU/C++ only**: extras compile through the reference C++ backend; there is
  no WGSL/SPIR-V/CUDA output, and no executor pre-pass coupling
  (enhance/featurealign-style kernels can't be authored here).

Wiring a kernel to a Blender brush type happens in
`sculptcore_addon/mapping.py` (`_MAP`); its float uniforms show up
automatically in the engine-props UI via the reflected uniform manifest.
