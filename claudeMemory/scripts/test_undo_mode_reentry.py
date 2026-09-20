# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Undo across edit mode back into a memfile step written in the mode, then draw.

Memfile undo keeps OB_MODE_CUSTOM on the restored object and runs no enter
callback, while the earlier undo that took the object out of the mode freed
its session. Before 2026-09-19 that left the object in the mode with no
session and a freed tree still registered with the external-draw provider:
the next viewport draw crashed in extdraw_nodes_get. Run headed:

  python claudeMemory/scripts/run_blender_test.py --headed       --script claudeMemory/scripts/test_undo_mode_reentry.py       --prefix undo-mode-reentry --marker UNDO_MODE_OK
"""
import bpy
from sculptcore_addon import engine

bpy.context.preferences.view.show_splash = False
state = dict(phase=0)


def in_mode():
    ob = bpy.context.object
    return ob.mode == 'CUSTOM' and ob.custom_mode == 'sculptcore.sculpt'


def step():
    window = bpy.context.window
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        return _step()


def _step():
    phase = state['phase']
    ob = bpy.context.object
    print('PHASE', phase, ob.mode, ob.name in engine.sessions, flush=True)
    if phase == 0:
        bpy.ops.mesh.primitive_uv_sphere_add('EXEC_DEFAULT', True, segments=32, ring_count=16)
        bpy.ops.object.custom_mode_toggle('EXEC_DEFAULT', True, mode_id='sculptcore.sculpt')
        assert in_mode() and bpy.context.object.name in engine.sessions
    elif phase == 1:
        bpy.ops.object.editmode_toggle('EXEC_DEFAULT', True)
        assert bpy.context.object.mode == 'EDIT'
    elif phase == 2:
        bpy.ops.object.editmode_toggle('EXEC_DEFAULT', True)
    elif phase == 3:
        bpy.ops.object.custom_mode_toggle('EXEC_DEFAULT', True, mode_id='sculptcore.sculpt')
        assert in_mode()
    elif phase in (4, 5, 6):
        bpy.ops.ed.undo()
    elif phase == 7:
        ob = bpy.context.object
        print('AFTER_UNDO', ob.mode, ob.custom_mode, ob.name in engine.sessions, flush=True)
        assert in_mode(), 'expected the undo to land on an in-mode step'
        assert ob.name in engine.sessions, 'object is in the mode without an engine session'
        for area in bpy.context.screen.areas:
            area.tag_redraw()
    elif phase == 8:
        # Survived a full draw of the restored in-mode object.
        bpy.ops.ed.redo()
    elif phase == 9:
        ob = bpy.context.object
        print('AFTER_REDO', ob.mode, ob.name in engine.sessions, flush=True)
        for area in bpy.context.screen.areas:
            area.tag_redraw()
    elif phase == 10:
        print('UNDO_MODE_OK', flush=True)
        bpy.ops.wm.quit_blender()
        return None
    state['phase'] += 1
    return .4


bpy.app.timers.register(step, first_interval=1)
