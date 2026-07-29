# claudeMemory — SculptCore Blender Addon

Working notes Claude maintains for this repository. See the top-level
[CLAUDE.md](../CLAUDE.md) for the project overview and the three-repo topology.

## Structure

- `plans/` — implementation plans for addon work.
- `research/` — investigation notes (engine seams, Blender API behavior).
- `codebase/` — validated reference docs for this repo and the Blender fork's
  custom-mode API the addon depends on.
- `design/` — design documents.

## Index

- [research/gpu-brush-evaluation-in-blender.md](research/gpu-brush-evaluation-in-blender.md)
  — how the engine's GPU brush stack could drive strokes under the addon: the
  existing marshal/dispatch seams, engine-owned wgpu vs. compute on Blender's
  device, and what per-dab work can and cannot be deferred to stroke end.
