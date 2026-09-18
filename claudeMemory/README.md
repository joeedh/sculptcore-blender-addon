# SculptCore development notes

Start with [CLAUDE.md](../CLAUDE.md) for repository/build guidance.
Current reference documentation takes precedence over archived plans and logs.

## Generic brush properties

- [Implementation and known defects](codebase/generic-brush-properties.md)
- [Remaining work](plans/generic-brush-properties-tasks.md)
- [Ownership, numeric and migration contract](design/generic-brush-contract-v1.md)
- [Owned-curve saved format](design/owned-curve-storage-v1.md)
- [Focused regression suites and artifact policy](codebase/generic-brush-testing.md)
- [Condensed history and recovery from Git](codebase/generic-brush-history.md)

The JSON inventory/coverage catalogues in `design/` are machine inputs; query
specific rows instead of loading them as prose. Generated output under `tests/`
is ignored apart from explicitly retained frozen compatibility inputs.

## Other project references

- [codebase/blender-debug-server.md](codebase/blender-debug-server.md)
- [debugging.md](debugging.md)
- [research/curve-mapping-brush-assets.md](research/curve-mapping-brush-assets.md)
- [plans/program-grids-routing.md](plans/program-grids-routing.md)
- [plans/indexed-grid-draws.md](plans/indexed-grid-draws.md)
- [plans/cpp-stroke-driver-adoption.md](plans/cpp-stroke-driver-adoption.md)
- [design/cpp-dab-loop.md](design/cpp-dab-loop.md)
- [design/off-thread-stroke.md](design/off-thread-stroke.md)
- [research/non-operator-wall-attribution.md](research/non-operator-wall-attribution.md)
- [plans/vertex-group-weights-attribute.md](plans/vertex-group-weights-attribute.md)
- [plans/blender-attribute-coverage-tasklist.md](plans/blender-attribute-coverage-tasklist.md)
- [research/collapse-blend-gate.md](research/collapse-blend-gate.md)
- [plans/grids-native-completion.md](plans/grids-native-completion.md)
- [plans/grid-domain-attributes.md](plans/grid-domain-attributes.md)
- [plans/multires-attribute-subdivision.md](plans/multires-attribute-subdivision.md)
- [plans/multires-grids-native-brush-path.md](plans/multires-grids-native-brush-path.md)
- [plans/extdraw-from-grids.md](plans/extdraw-from-grids.md)
- [research/grids-native-brush-path-results.md](research/grids-native-brush-path-results.md)
- [design/grids-native-addon-seams.md](design/grids-native-addon-seams.md)
- [research/multires-stroke-performance.md](research/multires-stroke-performance.md)
- [research/redraw-path-attribution.md](research/redraw-path-attribution.md)
- [research/redraw-gpu-pipeline-ab.md](research/redraw-gpu-pipeline-ab.md)
- [research/multires-autotune.md](research/multires-autotune.md)
- [research/grid-correspondence.md](research/grid-correspondence.md)
- [plans/multires-parametric-frame.md](plans/multires-parametric-frame.md)
- [design/multires-parametric-frame.md](design/multires-parametric-frame.md)
- [design/multires-object-space-cascade.md](design/multires-object-space-cascade.md)
- [design/blender-brush-textures.md](design/blender-brush-textures.md)
- [plans/blender-texture-system-port.md](plans/blender-texture-system-port.md)
- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
- [research/sculpt-stroke-world-model.md](research/sculpt-stroke-world-model.md)
- [research/litestl-sbo-audit.md](research/litestl-sbo-audit.md)
- [research/tbb-vs-litestl-parallel-for.md](research/tbb-vs-litestl-parallel-for.md)
- [Safe native test launching](codebase/generic-brush-testing.md#less-frequent-coverage)
- [codebase/brush-input-delivery.md](codebase/brush-input-delivery.md)
