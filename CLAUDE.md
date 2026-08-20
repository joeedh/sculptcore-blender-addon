# CLAUDE.md — SculptCore Blender Addon

Guidance for working in this repository.

## What this repo is

The **SculptCore sculpt mode** for Blender, shipped as an addon. It registers
a first-class object mode (`bpy.types.ObjectModeType`, `bl_idname
"sculptcore.sculpt"`) with real enter/exit lifecycle, wrapped undo, and an
external draw path — all on top of the custom-mode API that a companion
Blender fork provides. The sculpting itself runs in the native **SculptCore
engine**, loaded at runtime through a ctypes package that wraps
`sculptcore_capi.dll`.

### Three-repo topology

This addon is one of three coupled repositories:

- **Blender fork** — branch `custom-object-modes` (in the sibling Blender
  checkout, e.g. `C:\dev\blender\main`). Carries only the engine-agnostic core
  changes that make Python-registered custom object modes possible:
  `OB_MODE_CUSTOM`, the `bpy.types.ObjectModeType` RNA type, custom-mode undo,
  the external draw provider hooks, the multires reshape API,
  `Object.custom_mode_state` (a counter a custom mode bumps when it rebuilds
  its live state from the object's data, so it can tell an undo step whose
  data it already mirrors from one whose data it does not — see
  `sculptcore_addon/handlers.py::_resync_foreign_states`),
  `Object.multires_grid_vert_indices` (which grid sample is which subdivided
  vertex — the pairing every reshape walk computes internally and none exposed;
  see [claudeMemory/research/grid-correspondence.md](./claudeMemory/research/grid-correspondence.md)),
  and `Mesh.vertex_group_data_get`/`_set` (bulk CSR read/write of the whole
  `MDeformVert` table — the addon's vertex-group bridge would otherwise be a
  Python loop over every vertex and influence), the vetoable
  `bpy.app.handlers.quit_pre` callback (a handler returning true cancels the
  quit — the only hook that runs while a quit can still be stopped) and
  `bpy.ops.brush.asset_save_all()` (every other brush-asset operator saves the
  *active* brush only). It knows nothing about SculptCore. A stock Blender without these changes cannot load this addon's
  mode.
- **This repo** (`sculptcore-blender-addon`) — the addon Python
  (`sculptcore_addon/`) plus the engine as a submodule (`engine/`) and the
  build tooling that ties them to a Blender build.
- **Engine** (`engine/`, submodule → `joeedh/sculptcore.git`) — the C++
  sculpting engine. Built and documented on its own; see
  [engine/CLAUDE.md](./engine/CLAUDE.md).

## Layout

```
sculptcore_addon/        The addon package Blender loads (bl_info; registers the mode).
  __init__.py            SculptCoreMode(ObjectModeType) + register()/unregister().
  engine.py              Single load point for the `sculptcore` ctypes package + DLL.
  convert.py             Mesh <-> engine conversion (enter/exit/flush/refresh).
  stroke.py, ops.py ...  Stroke operator, brush mapping, gestures, undo, UI, keymap.
  texture.py             Brush-texture bridge: 2D bakes, runtime .stex programs, samplers.
  stex/                  Texture scripts the engine compiles at runtime (clouds.stex);
                         3D-mapped procedurals route here instead of the 2D bake.
                         See engine/documentation/textureScripts.md.
  lib/                   Vendored engine runtime (ctypes pkg + DLLs). Build product; gitignored.
brush_save_reminder/     A second, standalone addon (shares nothing with the above): warns on
                         quit about brush assets with unsaved changes, which neither the file
                         save nor Blender's own quit prompt covers. Needs two fork additions —
                         `bpy.app.handlers.quit_pre` and `bpy.ops.brush.asset_save_all()`.
                         See brush_save_reminder/README.md.
brushes/                 Addon-authored .sbrush kernels compiled into the DLL at build
                         time (engine "extra kernel dirs"); see brushes/README.md.
engine/                  SculptCore engine (git submodule). Builds sculptcore_capi.dll.
tools/                   build-blender-dist.mjs  build Blender locally, stage the addon (below).
                         fetch-blender-dist.mjs  the same, from CI artifacts instead of a build.
                         verify_addon.py         headless "did it come up enabled?" check.
                         smoke_test_package.py   headless "does its engine load?" check.
                         record-release.mjs      builds-repo manifest + RELEASES.md index.
.github/workflows/       Packaging CI (build-packages.yml) + the package smoke test
                         (smoke-test-packages.yml) — see below.
claudeMemory/            Claude's plans, research, and validated reference notes for THIS repo.
```

## How the engine reaches the addon

The addon does **not** compile into `blender.exe`. A change to the C++ engine
(`engine/source/**`) reaches Blender by **rebuilding the DLL and re-vendoring**
it into `sculptcore_addon/lib/`; a change to the addon Python needs nothing
rebuilt. Build the DLL with the engine's own dispatcher (run inside `engine/`):

```
cd engine
node make.mjs build python     # builds sculptcore_capi.dll + wgpu_native.dll under engine/build/python/
```

Then the runtime (the `sculptcore` ctypes package + those DLLs) is vendored
into `sculptcore_addon/lib/sculptcore/`. The build/install helper (below)
performs this vendoring against a Blender install tree; see
`engine/CLAUDE.md` for the engine's own `make.mjs bundle` target.

**Discovery** (see `sculptcore_addon/engine.py` and the package's `_capi.py`):
- The `sculptcore` package is found via, in order: an already-importable
  `sculptcore`; `$SCULPTCORE_PYTHON_PATH` (a dev checkout, which wins); or the
  vendored `sculptcore_addon/lib/sculptcore/`.
- The DLL is found via, in order: `$SCULPTCORE_CAPI_PATH`; a copy beside the
  package (the vendored case; `wgpu_native.dll` resolves via
  `add_dll_directory` on that directory); or `engine/build/python/`.

To iterate on the engine without touching the vendored copy:

```
$env:SCULPTCORE_PYTHON_PATH = "C:\dev\blender\sculptcore-blender-addon\engine\python"
$env:PATH = "C:\dev\blender\sculptcore-blender-addon\engine\build\python;$env:PATH"
```

`engine.py`'s `init()` refuses an ABI-mismatched DLL; on any load failure the
addon reports it to the system console (Window → Toggle System Console).

## The build/install helper (`tools/build-blender-dist.mjs`)

One command assembles a runnable Blender with the sculpt mode bundled and
**enabled by default**:

```
node tools/build-blender-dist.mjs [--build-dir DIR] [--dist DIR] [--config CFG]
                                  [--skip-blender] [--skip-engine] [--run]
```

The chain (`node tools/build-blender-dist.mjs --help` for the full option list):

1. Build the Blender fork's `install` target (its Windows `bin/` tree is a
   portable Blender). Skipped with `--skip-blender`. The build tree is
   autodetected as `../build_*_<config>` beside the fork (`../main`), or passed
   with `--build-dir`.
2. Pick the install folder: a clean mirror at `--dist DIR`, or the build's
   `bin/` in place (default, fast for dev).
3. Copy `sculptcore_addon/` and `brush_save_reminder/` into
   `<install>/<ver>/scripts/addons_core/` (fresh; `lib/` excluded). Blender 5.x only scans `scripts/addons_core` in an install
   tree, not the legacy `scripts/addons`.
4. Vendor the engine runtime into the addon's `lib/` via the engine's own
   `node make.mjs bundle <lib> ` (builds the DLL too; `--skip-engine` restages
   existing outputs only).
5. Write `<install>/<ver>/scripts/addons_core/.always_enable` (one module name
   per line — both addons) so the mode is on at startup, then verify it headlessly
   (`--background --factory-startup --python tools/verify_addon.py`).

   **Enabled-by-default without owning the user config.** The fork's
   `scripts/modules/addon_utils.py` reads `.always_enable` from each add-on
   directory in `_initialize_once()` and folds those names into
   `_addons_hidden_core`, which is enabled with `default_set=False` (never
   written to `preferences.addons`, so no `userpref.blend` is touched) and
   `persistent=True` (`check()` then reports it as enabled-by-default, so
   `reset_all()` will not unload it on a preferences reload). Timing matters:
   this runs in `load_scripts_extensions()`, *outside* the `RestrictBlend` block
   that `scripts/startup` modules register under — the addon's
   `keymap.register()` needs a live `bpy.context.window_manager`. Being
   hidden-core also means the addon does not appear in the Add-ons list and is
   exempt from per-workspace add-on filtering. It is enabled under
   `--factory-startup` too, which is what makes the verify pass meaningful.

   The install therefore ships **no user config**: it reads and writes the
   machine's global Blender config like any other install. Do not create a
   directory named `portable` beside the executable — Blender 5.x treats that
   alone as the portable marker (`get_path_user_ex()` in `appdir.cc`) and
   redirects *all* user resources under `<base>/portable/<folder>`, which is
   exactly what this no longer wants. `build-blender-dist.mjs` deletes a stale
   one left by earlier revisions when staging in place.

The fork's side of this is engine-agnostic (it names no add-on); the
`.always_enable` marker and the vendored `lib/` are build products, never
committed. For tight engine iteration without a full restage, use the env-var
flow above pointed at a Blender fork build.

Prerequisites for step 4 are the engine's own (Node + CMake + toolchain; see
`engine/CLAUDE.md`). The script has no npm dependencies.

## Packaging CI (`.github/workflows/build-packages.yml`)

The shippable, downloadable builds. Manual dispatch only. One matrix job per
target OS (ubuntu / macos-arm64 / windows), and each job **is** the target OS,
so `tools/fetch-blender-dist.mjs` takes its host path — extract, stage, mark
always-enabled, and verify by actually running Blender — and the final
tar.gz/zip is packed natively, preserving exec bits and symlinks.

**It is the second of two workflows.** The fork's own `build.yml` (manual
dispatch on `custom-object-modes`, ~2.5 h) builds all three platforms and uploads
`blender-install-<OS>`; on Linux/macOS that is a single *uncompressed* tar,
because the artifact store re-zips everything and a zip carries no exec bits or
symlinks. Run it first whenever the fork moved, then dispatch packaging with
`blender_run` set to that run id — left blank it takes the latest successful run
on `blender_branch`, which may predate the fork change being packaged. A fork
build without the `.always_enable` support fails packaging at the verify step
rather than shipping a Blender whose sculpt mode never turns on. The other
dispatch inputs are `config` (engine build config), `tag` (default
`build-<UTC date>-<short sha>`) and `prerelease`.

Per job:

1. Build the engine libs here, with `node make.mjs bundle ci-staging
   --kernels-extra ../brushes`. This is why packaging can't live in the engine
   repo: only this repo has the addon's `.sbrush` kernels, and libs built
   without them make the addon report `kernel 'NUDGE' missing from engine enum`.

   `--publish-deps-to staged-deps` also exports any *freshly compiled* native
   deps combo (OpenBLAS + SuiteSparse/CHOLMOD) as a `deps-<label>-<config>`
   artifact — a cold deps cache dominates this job's runtime, so the combo is
   worth keeping. Nothing is pushed from the runner: feed the artifact to the
   engine's `tools/publish-deps-from-package.mjs --commit --push` to land it in
   `joeedh/sculptcore-deps` (the libs go through git-LFS, so publish from a
   machine that has it). Combos are keyed
   `{platform}/clang-<major>-<arch>/{config}` and only hit on a matching
   toolchain — a runner image that bumps clang's major version misses and
   re-exports. Worth doing promptly: a warm cache is the difference between a
   ~2 h job and a ~7 min one.
2. `fetch-blender-dist.mjs --blender-repo joeedh/blender --engine-libs enginelibs`
   — the two CI-only flags. `--engine-libs` also bypasses the ABI pin, which is
   safe here because the libs were just built from the same submodule commit
   whose ctypes package gets vendored.

   Vendoring also **relinks the engine libs** (`fixLibLinkage()`). The prebuilt
   `wgpu_native` has no SONAME, so on Linux `libsculptcore_capi.so` records the
   build machine's *absolute path* to it as `DT_NEEDED` — unresolvable anywhere
   else, no matter that the lib is colocated. `patchelf` (hence its apt entry)
   sets a SONAME, rewrites the `NEEDED`, and sets `$ORIGIN` as the rpath. macOS
   is the same bug in milder form — the install name is already `@rpath`-relative
   but the only `LC_RPATH` is the runner's `extern/wgpu_native/lib` — fixed with
   `install_name_tool` (`-delete_rpath` / `-add_rpath @loader_path`) plus an
   ad-hoc `codesign`, since editing load commands voids the signature.

   Windows needs no *relinking* — PE resolves imports by bare name, and ctypes
   loads the capi with `LOAD_WITH_ALTERED_SEARCH_PATH`, so the DLL's own
   directory wins over System32 — but it does need the dependencies to be
   present. The engine is a clang build and imports `libomp140.x86_64.dll`,
   which ships with Visual Studio / LLVM and *not* with the VC++
   redistributable, so it resolved out of System32 on the builder and was
   missing from every package until `tools/lib/windows-deps.mjs` landed: it
   parses the PE import table (no `dumpbin` on a runner), copies in every
   non-system import — following the copies, which have imports of their own —
   and fails the build if one cannot be found. `build-blender-dist.mjs` runs it
   too, so a dev install is as self-contained as a package.

   None of this shows up on a dev box, where the recorded build paths and the
   toolchain runtimes exist — which is what the package smoke test (below) is
   for.
3. Pack, having first renamed `dist/<os>` to the package name, so the archive
   holds a single top-level `sculptblender-<tag>-<platform>/` directory —
   extracting one must not scatter ~1.5 GB across the user's current directory.

   The archive **file**, unlike that directory, carries no tag:
   `sculptblender-<platform>.(tar.gz|zip)`. GitHub's only stable-download URL is
   `/releases/latest/download/<asset name>`, which matches by exact name, so a
   tagged file name can never be linked to; the tag stays on the inner
   directory, where it still keeps two extracted builds from colliding and
   remains visible after unpacking. The same rule is why `prerelease` defaults
   to **false** — GitHub's "latest" skips pre-releases entirely, and while every
   release was one, `/releases/latest` 302'd to the plain releases list.
4. Upload straight into a draft release on `joeedh/sculptblender-builds`
   (created by the `prepare` job, un-drafted by `finalize`), so a ~1.5 GB
   package crosses the wire once instead of twice through the artifact store.

`finalize` also runs `tools/record-release.mjs` against a clone of the builds
repo: binaries stay release assets, and git gets only `releases/<tag>.json` plus
a regenerated `RELEASES.md`. The index orders on each manifest's `created_at`
timestamp — several builds land on one day, and ordering by date alone fell
through to the tag's sha suffix, i.e. alphabetical noise. `--reindex`
regenerates `RELEASES.md` from the manifests already on disk, which is how the
published index gets repaired without waiting for the next build.

`RELEASES.md` leads with a **Latest build** table of `/releases/latest/download/`
links, but only when a manifest on disk actually satisfies both halves of that
contract — not a pre-release, and carrying assets under the tag-free names.
Releases predating the rename fail the second test, so the section stays absent
rather than publishing links that 404.

## Package smoke test (`.github/workflows/smoke-test-packages.yml`)

Packaging verifies the tree it assembles **on the machine that just built the
engine libraries** — where every build path still exists, every toolchain
runtime is installed, and nothing has been through a pack/unpack round trip. So
it structurally cannot catch a mis-linked library, a lost exec bit, or a
dependency satisfied from the builder. This workflow closes that gap: it takes
the most recent published release from `joeedh/sculptblender-builds` (or a
dispatched `tag`), unpacks it on a clean runner of the target OS, and launches
Blender against `tools/verify_addon.py` (enabled?) and
`tools/smoke_test_package.py` (does the engine load, and from where?).

A third step, `tools/verify_texture_parity.py`, grades the shipped `.stex`
texture programs against Blender's own texture evaluation — the only job where a
Blender and the engine coexist, and the copy it grades is the one users get. It
also covers what the other two cannot see: a `.stex` that ships in the archive
but no longer compiles against the vendored DLL.

Triggered manually, and automatically on a successful **Build packages** run
(`workflow_run`) — packaging un-drafts the release in its `finalize` job, so by
then the assets are the "most recent".

**It installs nothing an ordinary user would not already have**, and that
constraint is the point: a compiler, patchelf, git-lfs or an OpenMP runtime on
the test machine would let a package that only loads on a build machine pass.
The one exception is the standard X11/GL runtime any Linux desktop carries
(Blender links it even under `--background`); a bare CI container has *less*
than a user's machine, not more. Unpacking uses only OS-provided tools —
including Windows' own `System32\tar.exe`, since the Git bash on PATH there
ships GNU tar, which cannot read a zip.

`smoke_test_package.py` asserts provenance, not just success: the `sculptcore`
ctypes package and every engine shared library the *process actually mapped*
(read from `/proc/self/maps`, `_dyld_get_image_name`, or `EnumProcessModules`)
must resolve inside the add-on's vendored `lib/sculptcore/`. A system copy
quietly satisfying the load fails the job instead of hiding in it. It also
requires `Brush.sculptcore` to exist (proving the engine was live during the
add-on's own registration — `engine_props.register()`'s failure path is a
`print`, not an exception), every kernel in `mapping.KERNEL_BY_TYPE` to be in
the engine enum (how libs built without `--kernels-extra ../brushes` show up),
and a one-triangle mesh to round-trip through the c-api. Both scripts are
launched with `--python-exit-code 1`: without it Blender prints an unhandled
exception and still exits 0.

The builds repo's `Readme.MD` is the user-facing install doc (nothing regenerates
it) — it describes the archive layout, the always-enabled add-on and the global
config, so a change to any of those means editing it by hand.

Needs the repo secret **`BUILDS_TOKEN`** — a PAT with `actions:read` on
`joeedh/blender` (the default `GITHUB_TOKEN` is repo-scoped and cannot download
the fork's artifacts) and `contents:write` on `joeedh/sculptblender-builds`.

## Working conventions for Claude (this repo)

- Put everything Claude generates under `claudeMemory/` (plans → `plans/`,
  research → `research/`, validated reference docs → `codebase/`, designs →
  `design/`). Index in [claudeMemory/README.md](./claudeMemory/README.md).
- Prefix scaffolding/helper comments with `CLAUDENOTE:` so they are greppable;
  strip them before a task is considered done, then audit every comment you
  touched for accuracy.
- **Pressure-test every plan after formulation.** Launch multiple adversarial
  agents with fresh contexts (one lens each — per-workstream buildability,
  semantics/correctness, cross-cutting seams and gates) whose brief is to
  *kill* the plan against the actual code, then fold every surviving finding
  back into the plan before any phase starts. A citation audit is not a
  substitute: it verifies references, not buildability.

## Coding style

- **Python** follows Blender's guidelines: PEP 8, 4-space indent, 120-column
  lines, `underscore_case` (CamelCase for classes), single quotes for enum
  literals (`ob.type == 'MESH'`) and double quotes elsewhere. Prefer
  `str.format()` over f-strings in code that may be translated. Imports inside
  function bodies are fine (and preferred for startup-cost-sensitive paths).
- **Engine (C++)** follows the engine repo's own conventions — see
  `engine/CLAUDE.md` / `engine/AGENTS.MD`.
- Every new source file needs an SPDX header
  (`GPL-2.0-or-later`, `2026 Blender Authors`), matching the addon's existing
  files.
