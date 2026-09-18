# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Undo follows Brush identity across rename and never targets a same-name replacement."""
import json
from pathlib import Path
import traceback
import bpy

state = dict(phase=0, checks=[])
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True


def owner():
    return bpy.data.brushes[state['name']]


def tick():
    try:
        phase = state['phase']
        if phase == 0:
            b = bpy.data.brushes.new('Original Authoring Owner', mode='SCULPT')
            b.use_fake_user = True
            b['v'] = 1
            state.update(name=b.name, uid=b.session_uid)
            bpy.ops.ed.undo_push(message='Identity baseline')
            token = b.authoring_edit_begin()
            b['v'] = 7
            b.authoring_edit_commit(token, 'Identity authoring')
            b.name = 'Renamed Authoring Owner'
            state['name'] = b.name
        elif phase == 1:
            bpy.ops.ed.undo()
            assert owner()['v'] == 1 and owner().session_uid == state['uid']
            state['checks'].append('undo follows session identity after rename')
        elif phase == 2:
            bpy.ops.ed.redo()
            assert owner()['v'] == 7 and owner().session_uid == state['uid']
            state['checks'].append('redo preserves renamed owner identity')
            state['token'] = owner().authoring_edit_begin(undo=False)
            bpy.data.brushes.remove(owner())
            b = bpy.data.brushes.new(state['name'], mode='SCULPT')
            b.use_fake_user = True
            b['v'] = 99
            state['replacement'] = b.session_uid
            try:
                b.authoring_edit_cancel(state.pop('token'))
            except ValueError:
                state['checks'].append('deleted-owner token rejects same-name replacement')
            else:
                raise AssertionError('deleted token accepted')
            bpy.context.scene['foreign_identity_edit'] = True
            bpy.ops.ed.undo_push(message='Foreign identity step')
        elif phase == 3:
            bpy.ops.ed.undo()
            assert owner()['v'] == 99 and owner().session_uid == state['replacement']
        elif phase == 4:
            bpy.ops.ed.undo()
            assert owner()['v'] == 99 and owner().session_uid == state['replacement']
            assert all(b.session_uid != state['uid'] for b in bpy.data.brushes)
            state['checks'].append('native undo skips deleted owner without resurrection or name redirect')
        elif phase == 5:
            bpy.ops.ed.redo()
            assert owner()['v'] == 99 and owner().session_uid == state['replacement']
            state['checks'].append('native redo skips deleted owner')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-owner-identity.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_OWNER_IDENTITY_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .4
    except Exception:
        traceback.print_exc()
        print('AUTHORING_IDENTITY_FAILED_PHASE', state['phase'], flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
