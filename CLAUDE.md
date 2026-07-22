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
  the external draw provider hooks, and the multires reshape API. It knows
  nothing about SculptCore. A stock Blender without these changes cannot load
  this addon's mode.
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
  lib/                   Vendored engine runtime (ctypes pkg + DLLs). Build product; gitignored.
engine/                  SculptCore engine (git submodule). Builds sculptcore_capi.dll.
tools/                   Build/install helper (build-blender-dist.*) — see below.
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

## The build/install helper (`tools/`) — PLANNED, not yet wired

The intended one-command chain (`tools/build-blender-dist.*`):

1. Build the Blender fork (`custom-object-modes`) and `cmake --install` it into
   a portable `dist/` tree.
2. Build the engine DLL (`node make.mjs build python` in `engine/`).
3. Vendor `sculptcore_addon/` + the `sculptcore` package + DLLs into
   `dist/<version>/scripts/addons/sculptcore_addon/`.
4. Run `dist/.../blender --background --python` to enable the addon and save a
   portable `dist/<version>/config/userpref.blend`, so the addon is **enabled
   by default** in the resulting install. (The fork stays sculptcore-agnostic;
   the userpref is a build product, never committed.)

Until this lands, iterate with the env-var flow above pointed at a Blender
fork build.

## Working conventions for Claude (this repo)

- Put everything Claude generates under `claudeMemory/` (plans → `plans/`,
  research → `research/`, validated reference docs → `codebase/`, designs →
  `design/`). Index in [claudeMemory/README.md](./claudeMemory/README.md).
- Prefix scaffolding/helper comments with `CLAUDENOTE:` so they are greppable;
  strip them before a task is considered done, then audit every comment you
  touched for accuracy.

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
