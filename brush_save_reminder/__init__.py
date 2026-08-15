# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Brush Save Reminder — warn about unsaved brush assets when Blender is quit.

Brush assets live in their own blend files inside an asset library, *outside*
the current file, so neither saving the file nor Blender's own "Save changes?"
prompt covers them: a session's worth of brush tweaking is silently thrown away
on quit.  Blender does track the per-brush dirty bit (``Brush.has_unsaved_
changes``), it just never asks about it.

This addon asks.  On quit, if any brush asset has unsaved changes, it takes the
quit over and offers to save them all, to look at what changed, or to stay.

Standalone: it shares nothing with the SculptCore addon it ships beside, and
works in a plain sculpt/paint session.  It does need the two fork additions this
repo's Blender carries (see README.md): the ``bpy.app.handlers.quit_pre``
handler list, which is the only hook that runs while a quit can still be
stopped, and ``bpy.ops.brush.asset_save_all()``, which saves brushes other than
the active one (every other brush-asset operator is active-brush only).
"""

bl_info = {
    "name": "Brush Save Reminder",
    "author": "Blender Authors",
    "version": (1, 0, 0),
    "blender": (5, 3, 0),
    "location": "On quit",
    "description": "Warn about brush assets with unsaved changes when quitting Blender",
    "category": "Paint",
}

import bpy

from . import changes, ops

_CLASSES = (
    ops.BRUSHSAVE_OT_quit_dialog,
    ops.BRUSHSAVE_OT_show_changes,
    ops.BRUSHSAVE_OT_save_all_and_quit,
    ops.BRUSHSAVE_OT_quit_without_saving,
)

# Set while this addon is itself asking Blender to quit, so the handler below
# lets that quit through instead of putting the dialog up a second time.
_quitting = False

# Set while the dialog is on screen.  Quit requests keep arriving while it is up
# (the window's close button is still there, and closing the *last* window is a
# quit request too); each must be refused, not answered with another dialog.
dialog_open = False


def request_quit():
    """Quit Blender, without the dialog re-triggering on the way out.

    Deferred to a timer: this is called from inside the dialog's own execute(),
    and the quit path opens further popups (Blender's "Save changes?" prompt) —
    which the closing dialog must be out of the way for.
    """
    def _quit():
        global _quitting
        _quitting = True
        try:
            bpy.ops.wm.quit_blender('INVOKE_DEFAULT')
        finally:
            # Cleared unconditionally: if the quit is stopped further down the
            # line (the file prompt's Cancel), the next quit must warn again.
            _quitting = False
        return None

    bpy.app.timers.register(_quit, first_interval=0.0)


@bpy.app.handlers.persistent
def _on_quit_pre(*_args):
    """``quit_pre`` handler: True means "I took the quit over, don't quit".

    Anything unexpected here has to fall through to a normal quit — a bug in an
    addon must not be able to make Blender unquittable.
    """
    if _quitting:
        return False
    if dialog_open:
        return True
    try:
        if not changes.unsaved_brushes():
            return False
        bpy.ops.brushsave.quit_dialog('INVOKE_DEFAULT')
    except Exception as ex:  # noqa: BLE001 - reported, never fatal
        print("brush_save_reminder: not warning about unsaved brushes: {!r}".format(ex))
        return False
    return True


def register():
    global dialog_open
    dialog_open = False

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    if not hasattr(bpy.app.handlers, "quit_pre"):
        print("brush_save_reminder: this Blender has no bpy.app.handlers.quit_pre; "
              "unsaved brush assets will not be reported on quit")
        return
    if _on_quit_pre not in bpy.app.handlers.quit_pre:
        bpy.app.handlers.quit_pre.append(_on_quit_pre)


def unregister():
    if hasattr(bpy.app.handlers, "quit_pre"):
        if _on_quit_pre in bpy.app.handlers.quit_pre:
            bpy.app.handlers.quit_pre.remove(_on_quit_pre)

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
