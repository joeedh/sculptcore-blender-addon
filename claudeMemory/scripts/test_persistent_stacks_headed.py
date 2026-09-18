# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generic Scene stack undo/redo using the actual headed event loop."""
import json
from pathlib import Path
import sys
import traceback
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.storage import PersistentOwnerStore, ROOT

lifecycle.register()
registry = Registry()
definition = registry.register(Definition('test.undo', 'Undo', 'INT32', 4, 0, 100, 0, 100))
original = (DeviceLayer('PRESSURE', False, curve=ResponseCurve('CONSTANT', (-3.,))),)
edited = (DeviceLayer('SPEED', operation='ADD'), DeviceLayer('TILT_Y'))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])


def store():
    return PersistentOwnerStore(bpy.context.scene, registry)


def step():
    try:
        phase = state['phase']
        if phase == 0:
            assert ROOT not in bpy.context.scene
            bpy.ops.ed.undo_push(message='Stack unset')
        elif phase == 1:
            store().write_stack(definition, original)
            bpy.ops.ed.undo_push(message='Stack create')
        elif phase == 2:
            store().write_stack(definition, edited)
            state['old'] = store()
            bpy.ops.ed.undo_push(message='Stack replace')
        elif phase == 3:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            try:
                state['old'].read_stack(definition)
            except PropertyError:
                pass
            else:
                raise AssertionError('Retained store survived undo')
            assert store().read_stack(definition) == original
            state['checks'].append('undo restores disabled entry/curve and retires old store')
        elif phase == 4:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert ROOT not in bpy.context.scene and store().read_stack(definition) == ()
            state['checks'].append('undo restores absent root without read allocation')
        elif phase == 5:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert store().read_stack(definition) == original
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert store().read_stack(definition) == edited
            state['checks'].append('redo restores both complete stack states')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-stacks-headed-results.json'
            path.write_text(json.dumps(dict(passed=True, checks=state['checks']), indent=2) + '\n')
            lifecycle.unregister()
            print('PERSISTENT_STACKS_HEADED_PASS', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .5
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
