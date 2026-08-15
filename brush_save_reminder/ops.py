# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The quit dialog and the actions its buttons run."""

import bpy
from bpy.types import Operator

from . import changes

# Name of the text datablock the report is written into.  Reused (and
# overwritten) rather than accumulating one block per press.
TEXT_NAME = "brush_changes.txt"


def _set_dialog_open(value):
    """Tell the quit handler whether the dialog is currently on screen."""
    import sys

    # By `__package__`, not by name: an addon can be loaded under a prefixed
    # module name (as an extension) and must still find its own state.
    sys.modules[__package__].dialog_open = value


def _save_all(op):
    """Save every dirty brush asset.  True if none are left dirty afterwards.

    The work is `brush.asset_save_all`, a fork addition: every other brush-asset
    operator saves the *active* brush only, and there is no RNA to make another
    brush active without changing what the user is painting with.
    """
    if not hasattr(bpy.ops.brush, "asset_save_all"):
        op.report({'ERROR'},
                  "This Blender has no brush.asset_save_all operator; brush assets were not saved")
        return False

    try:
        bpy.ops.brush.asset_save_all()
    except RuntimeError as ex:
        op.report({'ERROR'}, "Saving brush assets failed: {!s}".format(ex))
        return False

    remaining = changes.unsaved_brushes()
    if remaining:
        op.report({'WARNING'},
                  "{:d} brush asset(s) could not be saved: {:s}"
                  .format(len(remaining), ", ".join(brush.name for brush in remaining)))
        return False
    return True


def _report_text():
    """The report text datablock, created or refreshed in place."""
    text = bpy.data.texts.get(TEXT_NAME)
    if text is None:
        text = bpy.data.texts.new(TEXT_NAME)
    text.clear()
    text.write(changes.summary_text())
    text.cursor_set(0)
    return text


def _existing_text_area(context):
    """An already-open text editor, anywhere across the open windows."""
    for window in context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'TEXT_EDITOR':
                return window, screen, area
    return None


def _source_area(context):
    """An area `screen.area_dupli` can be run from.

    Its poll rejects global areas (the top bar / status bar) and temporary
    screens, which is what a full-screen area or a render window is.
    """
    windows = list(context.window_manager.windows)
    if context.window is not None:
        windows.sort(key=lambda window: window != context.window)
    for window in windows:
        screen = window.screen
        if screen is None or screen.is_temporary:
            continue
        for area in screen.areas:
            if area.spaces.active is not None:
                return window, screen, area
    return None


def _show_text(context, text):
    """Put `text` in front of the user, in a floating editor if need be."""
    found = _existing_text_area(context)
    if found is not None:
        window, screen, area = found
        area.spaces.active.text = text
        area.tag_redraw()
        return True

    source = _source_area(context)
    if source is None:
        return False

    window, screen, area = source
    windows_before = set(context.window_manager.windows)
    with context.temp_override(window=window, screen=screen, area=area):
        # Duplicates the area into a floating single-area window; it comes up as
        # a copy of `area`, so the type is switched afterwards.
        bpy.ops.screen.area_dupli('INVOKE_DEFAULT')

    new_windows = [win for win in context.window_manager.windows if win not in windows_before]
    if not new_windows:
        return False

    new_area = new_windows[-1].screen.areas[0]
    new_area.type = 'TEXT_EDITOR'
    space = new_area.spaces.active
    space.text = text
    space.show_line_numbers = False
    space.show_syntax_highlight = False
    space.show_word_wrap = False
    return True


class BRUSHSAVE_OT_show_changes(Operator):
    """Write a summary of the changed brush assets to a text block and open it"""
    bl_idname = "brushsave.show_changes"
    bl_label = "Show Me What Changed"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        text = _report_text()
        if not _show_text(context, text):
            self.report({'WARNING'},
                        'No editor could be opened; the report is in the text block "{:s}"'
                        .format(text.name))
        return {'FINISHED'}


class BRUSHSAVE_OT_save_all_and_quit(Operator):
    """Save every changed brush asset, then quit"""
    bl_idname = "brushsave.save_all_and_quit"
    bl_label = "Save All"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from . import request_quit

        _set_dialog_open(False)
        if not _save_all(self):
            # Something is still unsaved, which is the one thing this addon
            # exists to prevent quitting on top of.  Stay put and let the
            # reports explain.
            return {'CANCELLED'}
        request_quit()
        return {'FINISHED'}


class BRUSHSAVE_OT_quit_without_saving(Operator):
    """Quit Blender, discarding the changes to the brush assets"""
    bl_idname = "brushsave.quit_without_saving"
    bl_label = "Quit Without Saving"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from . import request_quit

        _set_dialog_open(False)
        request_quit()
        return {'FINISHED'}


class BRUSHSAVE_OT_quit_dialog(Operator):
    """Warn about brush assets with unsaved changes before quitting"""
    bl_idname = "brushsave.quit_dialog"
    bl_label = "Unsaved Brush Assets"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        # Snapshot the report now: the dialog's draw runs on every redraw, and
        # describing the brushes touches the asset libraries.
        self._entries = changes.describe_all()
        self._copy_target = changes.copy_target_library()
        _set_dialog_open(True)
        return context.window_manager.invoke_props_dialog(
            self, width=460, title="Unsaved Brush Assets", confirm_text="Save All",
            cancel_default=True,
        )

    def draw(self, context):
        layout = self.layout
        entries = getattr(self, "_entries", [])
        num_copies = sum(1 for entry in entries if entry["disposition"] == changes.SAVE_AS_COPY)

        column = layout.column(align=True)
        column.label(text="{:d} brush asset(s) have unsaved changes.".format(len(entries)),
                     icon='BRUSH_DATA')
        column.label(text="Quitting now discards them — they live outside this .blend file.")

        box = layout.box()
        column = box.column(align=True)
        for entry in entries[:8]:
            row = column.row()
            row.label(text=entry["name"])
            if entry["disposition"] == changes.SAVE_AS_COPY:
                row.label(text="{:s} — saved as a copy".format(entry["source"]))
            else:
                row.label(text=entry["source"])
        if len(entries) > 8:
            column.label(text="... and {:d} more".format(len(entries) - 8))

        if num_copies:
            column = layout.column(align=True)
            if self._copy_target is not None:
                column.label(text="{:d} came from a read-only library and will be duplicated into "
                                  '"{:s}".'.format(num_copies, self._copy_target.name),
                             icon='INFO')
            else:
                column.label(text="{:d} came from a read-only library and cannot be saved: no "
                                  "user asset library is configured.".format(num_copies),
                             icon='ERROR')

        layout.separator()
        row = layout.row(align=True)
        row.operator(BRUSHSAVE_OT_show_changes.bl_idname, icon='TEXT')
        row.operator(BRUSHSAVE_OT_quit_without_saving.bl_idname, icon='QUIT')

    def execute(self, context):
        # The dialog's confirm button: save everything, then resume the quit.
        from . import request_quit

        _set_dialog_open(False)
        if not _save_all(self):
            return {'CANCELLED'}
        request_quit()
        return {'FINISHED'}

    def cancel(self, context):
        # Nothing to undo — the quit was already vetoed by the handler, so
        # letting the dialog close is itself "don't exit".
        _set_dialog_open(False)
