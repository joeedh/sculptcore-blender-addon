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

For each brush the report gives its identity and disposition — the library it
came from, the asset file, the catalog, the paint modes it applies to, and
whether saving updates it in place or copies it — followed by **the settings
that actually differ from the copy on disk**, old value on the left and the
value this session would save on the right.

Blender itself records only *that* a brush changed, so the diff comes from
reading the asset back and comparing it property by property (`diff.py`). The
read goes through **`bpy.data.temp_data()`**, a throwaway Main discarded when
the block exits: appending the original into `bpy.data` would work too, but it
adds datablocks and dirties the file at the exact moment the user is being asked
whether to quit. Details worth knowing:

- It walks the brush's RNA, following pointer properties (the texture slots,
  the per-mode settings structs, `sculptcore`) up to three levels down, with
  purpose-built comparisons for curve mappings (their points) and colour ramps
  (their stops), plus the asset metadata — description, author, license,
  copyright, catalog and tags.
- `size` and `unprojected_size` are one radius in two units that Blender keeps
  in step, so only the one the brush is driven by (per `use_locked_size`) is
  reported — unless it is the sole change, which would otherwise read as
  "nothing changed".
- Enums whose item list is built from the paint mode in context (the texture
  slot's mapping) read back as `""` when the stored value is not in that list,
  which says nothing about whether it changed; those are skipped rather than
  reported as a bogus change.
- If the asset file is gone, the brush was renamed out of it, or the read fails,
  that brush falls back to a snapshot of its current settings with the reason
  stated. A report is never worth failing a quit over.
- The diff runs when the button is pressed, not when the dialog is built, so
  putting the dialog up stays instant.

A brush can be flagged as changed with nothing differing — Blender tags on any
edit, including one later undone — and the report says so plainly.

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
| `diff.py` | the on-disk asset read-back and the property-by-property comparison |
| `ops.py` | the dialog and its four actions |
