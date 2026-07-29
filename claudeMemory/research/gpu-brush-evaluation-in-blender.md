# GPU brush evaluation in Blender — options and cost model

**Date:** 2026-07-29. **Status:** research only; nothing implemented.
**Question:** how could SculptCore's GPU brush evaluation work under the Blender
addon, given that the engine's GPU path was built for a host that owns the GPU
device (the web app's TS dispatcher / the native debug app)?

## Verdict up front

Two viable paths, and they are a sequence, not a fork in the road.

- **Path A — engine-owned wgpu-native device, results crossing to Blender on the
  CPU.** Almost entirely built already: the marshaling C-API, the dispatcher,
  and even the `wgpu_native` DLL are shipping inside the addon today, unused.
  The remaining work is build wiring, hoisting one file out of `source/debug/`,
  and a ctypes seam. No Blender-fork changes at all.
- **Path B — compute on *Blender's* device, so the results never leave the GPU
  for display.** Needs a GLSL emitter in `sbrushc`, an SSBO surface in Blender's
  Python GPU module (fork), and an extdraw ABI change. Larger, but it is what
  removes the per-frame VBO upload, and it is the only version that scales to
  Vulkan + Metal + OpenGL without hand-writing three backends.

Path A is the measurement that tells you whether Path B is worth its price.

## What already exists in the engine

The GPU brush stack was deliberately split so the **host owns the device** and
the engine only produces bytes:

| Piece | Where | Role |
|---|---|---|
| Marshaling C-API | `source/brush/c-api/gpu_brush_c_api.cc`, `gpu_brush_session.h` | `GpuBrush_beginStroke/marshalDab/dataPtr/applyCo/endStroke`. Packs co/no/mask, neighbor CSR, cavity automask, per-dab uniforms, node meta, scatter tables; appends undo snapshots into the caller's open MeshLog step. Exported for WASM and N-API. |
| Dispatch interface | `source/brush/compute_dispatch.h` | `IBrushComputeDispatch` — `loadKernel` / `beginStroke` / `dab` / `setNeighbors` / `setAutomask` / `endStroke` / `readbackVerts` (+ `setAttr`/`readbackAttr`, Vulkan-only by default). |
| Vulkan backend | `source/vulkan/vk_compute.{h,cc}` | Plus the GPU-resident live extras (`prepareDab`/`recordDab`/`coBuffer`) that scatter into render VBOs — deliberately *not* on the shared interface, because they need cross-API buffer sharing. |
| WebGPU backend | `source/webgpu/wgpu_compute.{h,cc}` | wgpu-native. Upload once → dab → readback. No buffer sharing possible (separate device). |
| Orchestration | `source/debug/gpu_stroke.{h,cc}` | `GpuStrokeSession` — the only code that pairs marshal → dispatch → readback → dirty-flag. Gated on `SBRUSH_GPU_DISPATCH` and coupled to the debug app's `Scene`. |

**The useful accident:** `sculptcore_capi` already links the `webgpu` lib
(`CMakeLists.txt:306`), `wgpu_compute.cc` compiles into it unconditionally, and
`make.mjs bundle` already stages `wgpu_native.dll` beside `sculptcore_capi.dll`
in the addon's `lib/`. The DLL Blender loads today physically contains a working
WebGPU compute dispatcher that nothing calls.

Verification harnesses that come for free: `make.mjs sbrush-verify` (cpp vs wgsl
A/B, tolerant-numeric against goldens), `make.mjs webgpu-verify` (replay through
Dawn, bit-exact), and `GPUBRUSH_DATA_LIVE_CO`, which exists specifically to
shadow-diff a GPU readback against the CPU-authoritative result.

## Two corrections to prior assumptions

**There is no Metal/MSL emitter in `sbrushc`.** `BackendKind` (`compiler/ir.h`)
is cpp / wgsl / spirv / cuda / hip / opencl, and nothing under `source/brush`
mentions MSL. Metal can only arrive through someone else's abstraction:
wgpu-native (targets Metal, Vulkan, D3D12, GL) or Blender's own GLSL→MSL
generator (`source/blender/gpu/metal/mtl_shader_generate.cc`).

**Blender's *Python* GPU module already supports compute.**
`gpu.compute.dispatch(shader, x, y, z)` exists (`gpu_py_compute.cc`), and
`GPUShaderCreateInfo` exposes `compute_source()`, `local_group_size()`,
`push_constant()`, `uniform_buf()`, `image()`, `sampler()`. The one thing
missing is **`storage_buf()` and a `GPUStorageBuf` type** — there is no SSBO
surface anywhere in `source/blender/python/gpu/`. Since bindings 0–13 (+24) of
every sbrush kernel are storage buffers, that single gap is the entire blocker
for Python-driven compute.

## Path A — engine-owned wgpu device

Four work items:

1. **Ship the kernels.** `buildPythonCapi` calls
   `configureTarget('python', {kernelsExtra})` with no `backends`, so
   `SBRUSH_BACKEND_WGSL` stays OFF and no `.wgsl` is emitted for the addon
   build. Turn it on for the `python` target, then either stage the `.wgsl`
   into `lib/sculptcore/kernels/` or bake the text into generated headers and
   add `loadKernelSource(const char *)` beside `loadKernel(path)`.
2. **Hoist the orchestrator.** `GpuStrokeSession` needs a `Scene`-free version
   under `source/brush/` (or a new module), then a ctypes-callable C API in the
   same opaque-handle style as `GpuBrush_*`:
   `ScGpuStroke_begin(mesh, tree, brush, log, tool)` / `_dab(...)` / `_flush()`
   / `_end()`.
3. **Addon side.** `stroke.py` builds a `CommandExecutor` and drives it per dab
   (`_ensure_executor`, `stroke.py:101`). Add a branch: GPU stroke when the tool
   has a GPU kernel and the stroke is static-topology; otherwise fall through
   unchanged. The cadence you want already exists —
   `enableInteractiveReadback()` / `flushInteractiveReadback()` reads back only
   moved verts, once per frame for a whole burst of dabs.
4. **Draw is unchanged.** Dirty nodes → `sc_external_draw_update` → Blender's
   per-node GPU cache re-uploads, exactly as today.

Pre-existing limits to plan around:

- **Dyntopo is out.** `GpuBrush_beginStroke` thaws topology and the CSR/scatter
  tables assume it stays static for the stroke.
- **Addon extra kernels are CPU-only.** Per the extra-kernel-dir contract
  (`brush_compute.md`), `brushes/*.sbrush` (nudge) compile through the cpp
  backend only. Lifting that means running `sbrushc --backend=wgsl` over the
  extra dirs and shipping those outputs too.
- **Attribute kernels stay CPU.** `setAttr`/`readbackAttr` default to no-ops on
  the WebGPU dispatcher, so color / bsmooth / polygroup need them implemented
  there first.

## Path B — compute on Blender's device

Nobody hand-writes Vulkan + Metal + OpenGL here. Both plans lean on an existing
abstraction; the choice is whose:

| | wgpu-native (Path A) | Blender's GPU module (Path B) |
|---|---|---|
| Covers | Vulkan / Metal / D3D12 / GL | Vulkan / Metal / OpenGL — all three live and user-selectable (`gpu_backend` pref) |
| Kernel language | WGSL — already emitted | Blender-dialect GLSL — needs `emit_glsl.cc` |
| Metal handled by | wgpu | Blender (`mtl_shader_generate.cc`) |
| Fork work | none | `storage_buf` + `GPUStorageBuf` in the Python GPU module |
| Shares buffers with the viewport | impossible (separate device) | yes — the point of the path |

The GLSL emitter is the least risky part: `brush_compute.md` §"Adding a backend"
is a four-step recipe, the intrinsic table is indexed by `BackendKind` so a new
slot is mechanical, and GLSL is WGSL's nearest sibling (`emit_wgsl.cc` is the
file to copy). `sbrush-validate` (compile every kernel with `glslang`) and
`sbrush-verify` (cpp-vs-glsl A/B) are per-backend generic and come along free.

The fork patch is small and **engine-agnostic** — "expose SSBOs to the Python
GPU module" stands on its own merits and fits the `custom-object-modes` charter,
which forbids anything naming sculptcore.

The third piece is the extdraw ABI. `ScExternalDrawNode`
(`source/spatial/c-api/external_draw.h`, ABI v2) hands Blender **CPU pointers**
(`const float (*positions)[3]`). Scattering compute results straight into the
node VBOs means the provider must instead expose GPU buffer handles — an ABI v3,
touching both repos.

## The cost model — what can be deferred to stroke end, and what can't

This is the crux, and the engine's Vulkan live path already answers it
(`source/debug/gpu_stroke.cc:543`):

> Live path: the dab/normals/scatter above already deformed the render VBOs on
> the GPU this frame. Read back only this dab's moved verts into the CPU mesh so
> ray-pick + node bounds stay correct for the next dab. Touched leaves get
> RegenBounds only — never UpdateGPU/UpdateNormals: the scatter owns the VBOs
> and the normals until stroke end.

- **Display sync *is* deferred to stroke end.** Touched leaves never get
  `UpdateGPU`/`UpdateNormals` mid-stroke; the GPU scatter owns VBOs and normals
  until `finishLive()`.
- **A small per-dab readback cannot be deferred.** Dab N+1 depends on CPU
  coordinates from dab N in three places: the ray-pick producing the next dab's
  origin, node bounds (`RegenBounds`) which `GpuBrush_marshalDab` filters
  against to choose the next node set, and the undo snapshot — `snapshotNode`
  must fire *before* the readback overwrites `m->v.co` (`gpu_stroke.cc:396`).
- **That readback is O(verts moved this dab)**, not O(mesh) — negligible on a
  multi-million-vert mesh *when the device is shared*. On a separate device it
  degenerates into a full-buffer copy + device drain, which is exactly why the
  WebGPU path batches per frame instead (`gpu_stroke.cc:565` — the burst of
  catch-up dabs after a slow frame turns per-dab readback into N drains, the
  periodic hitch).

**So the zero-copy win for Blender is on the upload side.** Today every dab
dirties nodes and Blender re-uploads each dirty node's whole VBO through the
extdraw provider, every frame of the stroke. A shared device deletes that
traffic entirely, and simultaneously downgrades the surviving readback from
"full-buffer copy + drain" to "scoped copy of the moved verts" — which is what
makes per-dab CPU currency affordable in the first place.

## Recommended sequencing

1. Path A, behind a flag, with `GPUBRUSH_DATA_LIVE_CO` shadow-verification on.
   Cheap, no fork changes, and it measures the real question.
2. Expect it to be readback-bound in the same way the engine's own WebGPU
   interactive path is. That result is evidence *for* Path B, not against it.
3. Start Path B with the two independently useful pieces — `emit_glsl.cc` and
   the `storage_buf` fork patch — before committing to the extdraw ABI v3.

## Open questions worth measuring, not guessing

- At what mesh size does GPU dispatch beat `CommandExecutor` on the CPU, given
  that dyntopo already hits 5 M tris at ≥25 fps entirely on the CPU?
- How much of a stroke's frame time is currently the extdraw re-upload of dirty
  nodes? That number is the size of Path B's prize.
- Does wgpu-native device creation inside a running Blender interact badly with
  Blender's own GPU context on any of the three backends (particularly the GL
  backend on Windows)?
