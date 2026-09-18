# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Interactive authoring context rejection, first-edit baseline and bounded history."""
import json
from pathlib import Path
import traceback
import bpy

state = dict(phase=0, checks=[], undos=0)
prefs = bpy.context.preferences.edit
bpy.context.preferences.view.show_splash = False
prefs.use_global_undo = True


def brush():
    return bpy.data.brushes['Authoring Limits']


def reject(label, operation):
    try:
        operation()
    except (ValueError, PermissionError):
        state['checks'].append(label)
    else:
        raise AssertionError(label)


class AUTHORING_OT_nested_probe(bpy.types.Operator):
    bl_idname = 'authoring.nested_probe'
    bl_label = 'Nested Probe'
    bl_options = {'UNDO'}

    def execute(self, context):
        reject('nested undo operator rejected before editing', lambda: brush().authoring_edit_begin())
        return {'CANCELLED'}


bpy.utils.register_class(AUTHORING_OT_nested_probe)


def step():
    try:
        phase = state['phase']
        if phase == 0:
            b = bpy.data.brushes.new('Authoring Limits', mode='SCULPT')
            b.use_fake_user = True
            b['v'] = 0
            token = b.authoring_edit_begin()
            b['v'] = 1
            b.authoring_edit_commit(token, 'First authoring edit without explicit baseline')
        elif phase == 1:
            bpy.ops.ed.undo()
            assert brush()['v'] == 0
            state['checks'].append('first edit undoes without caller-pushed baseline')
        elif phase == 2:
            bpy.ops.ed.redo()
            assert brush()['v'] == 1
            prefs.use_global_undo = False
            reject('disabled global undo rejected', lambda: brush().authoring_edit_begin())
            token = brush().authoring_edit_begin(undo=False)
            brush()['v'] = 2
            brush().authoring_edit_cancel(token)
            assert brush()['v'] == 1
            state['checks'].append('rollback-only scope works with global undo disabled')
            prefs.use_global_undo = True
            previous = prefs.undo_steps
            prefs.undo_steps = 0
            reject('zero history steps rejected', lambda: brush().authoring_edit_begin())
            prefs.undo_steps = previous
            assert bpy.ops.authoring.nested_probe() == {'CANCELLED'}
        elif phase == 3:
            state['token'] = brush().authoring_edit_begin()
            bpy.ops.ed.undo()
        elif phase == 4:
            reject('token cannot survive undo', lambda: brush().authoring_edit_cancel(state.pop('token')))
            assert brush()['v'] == 0
            prefs.undo_steps = 3
            prefs.undo_memory_limit = 8
            # Large captured trees exercise real snapshot memory accounting and eviction.
            brush()['payload'] = 'x' * (1024 * 1024)
            for index in range(1, 9):
                token = brush().authoring_edit_begin()
                brush()['v'] = index
                brush().authoring_edit_commit(token, 'Limited authoring {}'.format(index))
            state['expected'] = 8
        elif phase == 5:
            if bpy.ops.ed.undo.poll():
                result = bpy.ops.ed.undo()
                if result == {'FINISHED'} and brush()['v'] != state['expected']:
                    state['expected'] -= 1
                    state['undos'] += 1
                    assert brush()['v'] == state['expected'], (state['undos'], brush()['v'], state['expected'])
                    assert state['undos'] <= 3
                    return .2
                # Native poll includes hidden prev steps. ed_undo_step_direction discards
                # BKE's false return when limits removed the previous visible target.
                assert result in ({'FINISHED'}, {'CANCELLED'}) and brush()['v'] == state['expected']
                state['checks'].append('hidden history boundary leaves authoring unchanged')
            assert 1 <= state['undos'] <= 3
            state['checks'].append('bounded count/memory history restores retained steps exactly')
        elif phase == 6:
            if bpy.ops.ed.redo.poll():
                bpy.ops.ed.redo()
                state['expected'] += 1
                assert brush()['v'] == state['expected']
                return .2
            assert brush()['v'] == 8
            state['checks'].append('retained limited history redoes exactly')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-undo-limits.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_UNDO_LIMITS_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .3
    except Exception:
        traceback.print_exc()
        print('AUTHORING_LIMITS_FAILED_PHASE', state['phase'], flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
