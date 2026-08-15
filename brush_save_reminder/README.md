<!-- SPDX-FileCopyrightText: 2026 Blender Authors

     SPDX-License-Identifier: GPL-2.0-or-later -->

# Brush Save Reminder

Warns about brush assets with unsaved changes when Blender is quit.

Brush assets live in their own `.asset.blend` files inside an asset library —
*outside* the file being edited. Saving the .blend does not save them, and
Blender's own "Save changes?" quit prompt only looks at the file
(`wm_file_or_session_data_has_unsaved_changes`), so a session's worth of brush
tweaking is discarded on quit without a word. Blender does track the per-brush
dirty bit (`Brush.has_unsaved_changes`, set by `BKE_brush_tag_unsaved_changes`);
it just never asks about it.

On quit, if any brush asset is dirty, this addon takes the quit over and puts up
a dialog:

- **Save All** (the confirm button) — saves every dirty brush asset, then
  resumes the quit. Brushes from a read-only library (the bundled Essentials)
  cannot be written back, so those are **duplicated** into the first writable
  user asset library, exactly as Blender's own *Save As Asset* does.
- **Cancel** — stays in Blender.
- **Show Me What Changed** — writes a report into a `brush_changes.txt` text
  datablock and opens it: in an already-open text editor if there is one, else
  in a floating single-area window (`screen.area_dupli`, retyped to
  `TEXT_EDITOR`).
- **Quit Without Saving** — quits anyway. Not in the original spec; it is here
  because the other three leave no way out of the dialog that discards, and a
  warning you cannot dismiss is worse than no warning. Delete the operator and
  its button in `ops.py` to drop it.

The report is identity and disposition, not a diff: Blender records only *that*
a brush changed, so for each brush it lists the library it came from, the asset
file, the catalog, the paint modes it applies to, whether saving updates it in
place or copies it, and a snapshot of its current settings. (A true diff would
mean appending the on-disk asset with `bpy.data.libraries.load`, which adds
datablocks and dirties the file — at quit time, exactly the wrong trade.)

It is standalone: it shares no code with `sculptcore_addon` and works in a plain
sculpt/paint session.

## Fork dependencies

It does need two additions that this repo's Blender fork carries (branch
`custom-object-modes`); with a stock Blender it registers, prints a notice to
the console, and does nothing.

- **`bpy.app.handlers.quit_pre`** — a *vetoable* callback
  (`BKE_CB_EVT_QUIT_PRE`), fired from `wm_quit_with_optional_confirmation_prompt`
  before Blender's own file prompt, at the last point where the quit can still
  be stopped. A handler returning a true value cancels the quit
  (`BKE_callback_exec_vetoable` / `BKE_callback_veto`); only events for which
  `BKE_callback_evt_is_vetoable` holds read that return value, so every existing
  handler's return value keeps being ignored. Never fired in background mode.
  The stock `exit_pre` is no help here: it runs at the point of no return, and
  cannot cancel or show UI.
- **`bpy.ops.brush.asset_save_all()`** (`BRUSH_OT_asset_save_all`) — saves every
  dirty brush asset. Every other brush-asset operator saves the *active* brush
  only, and there is no RNA to make a brush active without changing what the
  user is painting with (`Paint.brush` is read-only; `brush.asset_activate`
  needs a loaded asset list and depends on the object mode). For read-only
  brushes it re-creates the catalog by *path* in the target library (catalog
  UUIDs are per-library) and saves a copy, then clears the dirty flag on the
  original too — Blender's own save-as leaves it tagged, which would make the
  quit warning unsatisfiable.

## Files

| File | |
|---|---|
| `__init__.py` | `bl_info`, the `quit_pre` handler, register/unregister, `request_quit()` |
| `changes.py` | which brushes are dirty, where saving them goes, the report text |
| `ops.py` | the dialog and its four actions |
