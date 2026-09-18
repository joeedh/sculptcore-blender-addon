# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headed undo/redo lifetime test with explicit native-state undo limitations."""
import json
from pathlib import Path
import sys
import traceback

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package

_, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import PropertyError

lifecycle.register()
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
bpy.ops.object.mode_set(mode='SCULPT')
bpy.ops.object.mode_set(mode='OBJECT')
brush = bpy.data.brushes.new('Plan4UndoNative', mode='SCULPT')
brush.use_fake_user = True
state = dict(phase=0, pre_stores=[], checks=[])


def store(owner):
    return native.NativeStrengthOwner(owner, epoch=1)


def capture_pre(_):
    state['pre_stores'].append(store(bpy.data.brushes['Plan4UndoNative']))


bpy.app.handlers.undo_pre.append(capture_pre)
bpy.app.handlers.redo_pre.append(capture_pre)


def rejected(value):
    try:
        value.value_mode(native.STRENGTH)
    except PropertyError:
        return
    raise AssertionError('Stale store survived undo/redo')


def step():
    try:
        phase = state['phase']
        scene = bpy.context.scene
        if phase == 0:
            scene['plan4_undo_marker'] = 1
            brush.strength = .375
            ups = scene.tool_settings.sculpt.unified_paint_settings
            ups.strength = .375
            ups.use_unified_strength = False
            bpy.ops.ed.undo_push(message='Plan4 owner baseline')
        elif phase == 1:
            scene['plan4_undo_marker'] = 2
            brush.strength = .75
            ups = scene.tool_settings.sculpt.unified_paint_settings
            ups.strength = .75
            ups.use_unified_strength = True
            bpy.ops.ed.undo_push(message='Plan4 owner edit')
            state['before_undo'] = (store(brush), store(scene))
        elif phase == 2:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            for value in (*state['before_undo'], state['pre_stores'][-1]):
                rejected(value)
            scene = bpy.context.scene
            assert scene['plan4_undo_marker'] == 1
            # These assertions document the actual native limitation, not undo support.
            assert store(bpy.data.brushes['Plan4UndoNative']).read_value(native.STRENGTH_DEFINITION).value == .75
            parent = store(scene)
            assert parent.read_value(native.STRENGTH_DEFINITION).value == .75 and parent.unified(native.STRENGTH)
            state['checks'].append('undo restores Scene IDProperties; Brush and native Scene settings retain current state')
            state['checks'].append('undo invalidates both owners and a store created in another pre-handler')
            state['before_redo'] = parent
        elif phase == 3:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            rejected(state['before_redo'])
            rejected(state['pre_stores'][-1])
            assert bpy.context.scene['plan4_undo_marker'] == 2
            state['checks'].append('redo invalidates existing and pre-handler stores; fresh store works')
            assert store(bpy.context.scene).read_value(native.STRENGTH_DEFINITION).value == .75
        else:
            root = Path(__file__).resolve().parents[1] / 'tests'
            (root / 'plan4-owner-headed-results.json').write_text(json.dumps(dict(
                passed=True, checks=state['checks'],
                undo_scope='Scene custom-property sentinel only; generic brush storage unimplemented'), indent=2) + '\n')
            bpy.app.handlers.undo_pre.remove(capture_pre)
            bpy.app.handlers.redo_pre.remove(capture_pre)
            lifecycle.unregister()
            print('PLAN4_OWNER_HEADED_PASS', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .4
    except Exception:
        traceback.print_exc()
        print('PLAN4_OWNER_HEADED_FAIL', flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
