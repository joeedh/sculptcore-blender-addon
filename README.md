# SculptCore Blender Addon

A full sculpt mode for Blender, built on the [SculptCore](https://github.com/joeedh/sculptcore)
engine and shipped as an addon. It registers a first-class object mode with a
real enter/exit lifecycle, wrapped undo, and an external draw path.

## Requirements

This addon relies on a **custom-mode API** that stock Blender does not yet
have. It must run against a Blender build from the companion fork's
`custom-object-modes` branch (which adds `OB_MODE_CUSTOM`,
`bpy.types.ObjectModeType`, custom-mode undo, and external-draw hooks). Stock
Blender cannot load this addon's mode.

## Repository layout

- `sculptcore_addon/` — the addon package Blender loads.
- `engine/` — the SculptCore C++ engine (git submodule). Builds
  `sculptcore_capi.dll`. See [engine/CLAUDE.md](./engine/CLAUDE.md).
- `tools/` — build/install helper (assembles a Blender install tree with the
  addon bundled and enabled).

Clone with submodules:

```
git clone --recurse-submodules https://github.com/joeedh/sculptcore-blender-addon.git
```

## Building

See [CLAUDE.md](./CLAUDE.md) for the engine build, runtime discovery, and the
planned `dist` build helper.

## License

GPL-2.0-or-later.
