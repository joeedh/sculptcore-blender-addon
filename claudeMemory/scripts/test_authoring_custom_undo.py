# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Interleave real engine mask/custom undo with Brush authoring and addon lifetime."""
import json
from pathlib import Path
import traceback
import bpy
import addon_utils
from sculptcore_addon import engine, ops, undo

bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])


def brush():
    return bpy.data.brushes['Custom Undo Authoring']


def mask():
    return ops._mask_state(engine.sessions[bpy.context.object.name])[0]


def check(label, condition):
    assert condition, label
    state['checks'].append(label)


def step():
    try:
        phase = state['phase']
        if phase == 0:
            b = bpy.data.brushes.new('Custom Undo Authoring', mode='SCULPT')
            b.use_fake_user = True
            b['value'] = 1
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            check('actual engine custom mode entered', bpy.context.object.mode == 'CUSTOM'
                  and bpy.context.object.name in engine.sessions)
            bpy.ops.ed.undo_push(message='Custom sculpt baseline')
        elif phase == 1:
            assert bpy.ops.sculptcore.mask_flood_fill(value=.25) == {'FINISHED'}
            check('actual mask custom undo step pushed', bool(undo._pending) and (mask() == .25).all())
            state['old_keys'] = tuple(undo._pending)
        elif phase == 2:
            token = brush().authoring_edit_begin(native_settings=True)
            brush()['value'] = 2
            brush().strength = .75
            brush().authoring_edit_commit(token, 'Author brush among sculpt steps')
        elif phase == 3:
            assert bpy.ops.sculptcore.mask_flood_fill(value=.75) == {'FINISHED'}
        elif phase == 4:
            bpy.ops.ed.undo()
            check('custom undo preserves preceding authoring', (mask() == .25).all() and brush()['value'] == 2)
        elif phase == 5:
            bpy.ops.ed.undo()
            check('authoring undo preserves prior engine mask', brush()['value'] == 1 and (mask() == .25).all())
        elif phase == 6:
            bpy.ops.ed.undo()
            check('prior custom undo restores unmasked engine', (mask() == 0).all() and brush()['value'] == 1)
        elif phase == 7:
            bpy.ops.ed.redo()
            check('prior custom redo', (mask() == .25).all())
        elif phase == 8:
            bpy.ops.ed.redo()
            check('authoring redo among custom steps', brush()['value'] == 2 and brush().strength == .75
                  and (mask() == .25).all())
        elif phase == 9:
            bpy.ops.ed.redo()
            check('subsequent custom redo', (mask() == .75).all())
        elif phase == 10:
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            check('actual engine custom mode exit', bpy.context.object.mode == 'OBJECT' and not engine.sessions)
            state['next_key'] = undo._next_key
            addon_utils.disable('sculptcore_addon', default_set=False)
            check('disable clears pending payloads without recycling keys', not undo._pending
                  and undo._next_key == state['next_key'])
            addon_utils.enable('sculptcore_addon', default_set=False)
            assert addon_utils.check('sculptcore_addon')[1]
        elif phase == 11:
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            assert bpy.ops.sculptcore.mask_flood_fill(value=.5) == {'FINISHED'}
            keys = tuple(undo._pending)
            check('re-enabled custom mode assigns fresh undo keys', keys and min(keys) >= state['next_key'])
            for key in state['old_keys']:
                undo.free(key)
            check('old step cleanup leaves new payload intact', tuple(undo._pending) == keys)
        elif phase == 12:
            bpy.ops.ed.undo()
            check('new custom undo remains valid after old cleanup', (mask() == .75).all())
        elif phase == 13:
            bpy.ops.ed.redo()
            check('new custom redo remains valid after old cleanup', (mask() == .5).all())
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-custom-undo.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_CUSTOM_UNDO_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .5
    except Exception:
        traceback.print_exc()
        print('CUSTOM_UNDO_FAILED_PHASE', state['phase'], flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
