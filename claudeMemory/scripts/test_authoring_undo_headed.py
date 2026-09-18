# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Paired authoring/native undo across owners, foreign memfiles and redo branches."""
import json
from pathlib import Path
import traceback
import bpy

bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])


def brush():
    return bpy.data.brushes['Authoring Undo Brush']


def scene():
    return bpy.data.scenes['Authoring Undo Scene']


def record(label, condition):
    assert condition, label
    state['checks'].append(label)


def brush_native():
    b = brush()
    cavity = b.mesh_automasking_settings
    return (b.use_pressure_strength, b.curve_strength.curves[0].points[-1].location.y,
            cavity.use_automasking_cavity, cavity.use_automasking_cavity_inverted,
            cavity.cavity_factor, cavity.cavity_curve.curves[0].points[-1].location.y)


def scene_native():
    s = bpy.context.scene.tool_settings.sculpt
    u, c = s.unified_paint_settings, s.mesh_automasking_settings
    return (u.size, u.unprojected_size, u.use_locked_size, u.use_unified_size, u.use_unified_strength,
            c.use_automasking_cavity, c.use_automasking_cavity_inverted, c.cavity_factor,
            c.cavity_curve.curves[0].points[-1].location.y)


def step():
    try:
        phase = state['phase']
        if phase == 0:
            b = bpy.data.brushes.new('Authoring Undo Brush', mode='SCULPT')
            b.use_fake_user = True
            b['v'] = 1
            s = bpy.data.scenes.new('Authoring Undo Scene')
            s['v'] = 10
            state['uid'] = b.session_uid
            bpy.ops.ed.undo_push(message='Authoring baseline')
        elif phase == 1:
            b = brush()
            token = b.authoring_edit_begin(native_settings=True)
            state['pair'] = (b.size, b.unprojected_size, b.use_locked_size)
            state['brush_native_before'] = brush_native()
            b['v'] = 2
            b.size = 200
            b.unprojected_size = .75
            b.use_locked_size = 'SCENE'
            b.strength = .625
            b.use_pressure_strength = not b.use_pressure_strength
            b.curve_strength.curves[0].points[-1].location.y = .375
            b.mesh_automasking_settings.use_automasking_cavity_inverted = True
            b.mesh_automasking_settings.cavity_factor = 1.75
            b.mesh_automasking_settings.cavity_curve.curves[0].points[-1].location.y = .625
            state['brush_native_after'] = brush_native()
            record('changed Brush commit', b.authoring_edit_commit(token, 'Brush authoring'))
        elif phase == 2:
            s = scene()
            token = s.authoring_edit_begin()
            s['v'] = 20
            s.authoring_edit_commit(token, 'Other Scene authoring')
        elif phase == 3:
            s = bpy.context.scene
            token = s.authoring_edit_begin(native_settings=True)
            state['scene_native_before'] = scene_native()
            s['authoring_v'] = 30
            s.tool_settings.sculpt.unified_paint_settings.strength = .8125
            u, c = s.tool_settings.sculpt.unified_paint_settings, s.tool_settings.sculpt.mesh_automasking_settings
            u.size, u.unprojected_size, u.use_locked_size = 333, .875, 'SCENE'
            u.use_unified_size = not u.use_unified_size
            u.use_unified_strength = not u.use_unified_strength
            c.use_automasking_cavity = True
            c.cavity_factor = 1.875
            c.cavity_curve.curves[0].points[-1].location.y = .375
            state['scene_native_after'] = scene_native()
            s.authoring_edit_commit(token, 'Active Scene authoring')
        elif phase == 4:
            bpy.context.scene['foreign'] = 1
            bpy.ops.ed.undo_push(message='Foreign memfile')
        elif phase == 5:
            bpy.ops.ed.undo()
            record('foreign undo preserves accumulated authoring', brush()['v'] == 2
                   and scene()['v'] == 20 and bpy.context.scene['authoring_v'] == 30)
        elif phase == 6:
            bpy.ops.ed.undo()
            record('Scene undo leaves other owners authored', 'authoring_v' not in bpy.context.scene
                   and scene()['v'] == 20 and brush()['v'] == 2)
            record('Scene undo restores native cavity, exact sizes and legacy unified flags',
                   scene_native() == state['scene_native_before'])
        elif phase == 7:
            bpy.ops.ed.undo()
            record('second Scene undo restores before', scene()['v'] == 10 and brush()['v'] == 2)
        elif phase == 8:
            bpy.ops.ed.undo()
            b = brush()
            record('Brush undo restores scalar and exact native pair', b['v'] == 1
                   and (b.size, b.unprojected_size, b.use_locked_size) == state['pair']
                   and b.session_uid == state['uid'])
            record('Brush undo restores pressure flag, native response and cavity mapping',
                   brush_native() == state['brush_native_before'])
            token = b.authoring_edit_begin()
            record('no-op preserves redo', not b.authoring_edit_commit(token, 'No-op'))
        elif phase == 9:
            bpy.ops.ed.redo()
            record('Brush redo after no-op', brush()['v'] == 2 and brush().size == 200
                   and brush().unprojected_size == .75 and brush().strength == .625)
            record('Brush redo restores pressure and cavity', brush_native() == state['brush_native_after'])
        elif phase == 10:
            bpy.ops.ed.redo()
            record('other Scene redo', scene()['v'] == 20)
        elif phase == 11:
            bpy.ops.ed.redo()
            record('active Scene redo restores preserved UPS', bpy.context.scene['authoring_v'] == 30
                   and bpy.context.scene.tool_settings.sculpt.unified_paint_settings.strength == .8125)
            record('Scene redo restores native cavity and exact sizes', scene_native() == state['scene_native_after'])
        elif phase == 12:
            token = brush().authoring_edit_begin()
            brush()['v'] = 99
            brush().authoring_edit_cancel(token)
            record('cancel restores Brush without losing foreign redo', brush()['v'] == 2)
            bpy.ops.ed.redo()
            record('foreign redo remains after cancel', bpy.context.scene['foreign'] == 1)
        elif phase == 13:
            bpy.ops.ed.undo()
            token = brush().authoring_edit_begin()
            brush()['v'] = 3
            brush().authoring_edit_commit(token, 'Replacement branch')
        elif phase == 14:
            record('changed commit truncates redo branch', not bpy.ops.ed.redo.poll())
            bpy.ops.ed.undo()
            record('new branch undo', brush()['v'] == 2)
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-undo-headed.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_UNDO_HEADED_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .35
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
