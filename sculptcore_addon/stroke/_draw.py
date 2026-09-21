# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Viewport-frame counting for the mid-stroke refresh cadence, plus the
pointer-move event set the operator's ``modal`` reads.

Shared module state: callers outside this file must read ``_frames_presented``
through attribute access on this module (``_draw._frames_presented``), not via
``from ._draw import _frames_presented`` — the latter binds the int's value at
import time and never sees this module's later increments.
"""

import bpy

# Frames presented in any 3D viewport, counted by a draw handler that lives
# only while a stroke runs (see _draw_counter_push/_pop). The mid-stroke
# refresh cadence gates on it: a refresh whose predecessor no frame has
# consumed yet is pure waste — the provider re-fills the same dirty nodes and
# only the fill current at draw time is ever uploaded. Wall-clock (30 Hz)
# alone over-refreshes exactly when it hurts: event floods and frame-bound
# heavy scenes.
_frames_presented = 0
_draw_counter_handle = None
_draw_counter_strokes = 0

# Pointer motion the stroke acts on. INBETWEEN_MOUSEMOVE is a backlog sample
# that the window manager demoted rather than discarded, so it carries a real
# position, pressure and tilt (see the modal handler).
_MOVE_EVENT_TYPES = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}


def _on_viewport_draw():
    global _frames_presented
    _frames_presented += 1


def _draw_counter_push():
    global _draw_counter_handle, _draw_counter_strokes
    _draw_counter_strokes += 1
    if _draw_counter_handle is None:
        _draw_counter_handle = bpy.types.SpaceView3D.draw_handler_add(
            _on_viewport_draw, (), 'WINDOW', 'POST_PIXEL')


def _draw_counter_pop():
    global _draw_counter_handle, _draw_counter_strokes
    _draw_counter_strokes = max(0, _draw_counter_strokes - 1)
    if _draw_counter_strokes == 0 and _draw_counter_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_counter_handle, 'WINDOW')
        _draw_counter_handle = None


def _tag_redraw_all_views(context):
    """Redraw the drawing region of every 3D viewport in every window (the
    stroke's own area included). Region, not area, for the same reason
    ``_mid_redraw`` gives: an area redraw also re-uploads the asset shelf's
    preview icons."""
    wm = context.window_manager
    if wm is None:  # cancel() teardown on window close
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    region.tag_redraw()
