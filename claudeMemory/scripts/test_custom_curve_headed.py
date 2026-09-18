# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene custom mapping plus selection undo/redo in the headed event loop."""
import json
from pathlib import Path
import sys
import traceback
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.curves import CurveBank
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT

lifecycle.register()
registry = Registry()
definition = registry.register(Definition('test.undo.custom', 'Custom', 'INT32', 4, 0, 100, 0, 100))
bank = CurveBank(registry)
bank.register()
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])


def store():
    return PersistentOwnerStore(bpy.context.scene, registry, curve_bank=bank)


def point():
    target = store()
    return bank.mapping(target, definition, bank.reference(target, definition, 'PRESSURE')).curves[0].points[-1]


def step():
    try:
        phase = state['phase']
        if phase == 0:
            bpy.ops.ed.undo_push(message='Custom unset')
        elif phase == 1:
            target = store()
            ref = bank.initialize(target, definition, 'PRESSURE')
            target.write_stack(definition, (DeviceLayer('PRESSURE', False, curve=ref),))
            point().location.y = .25
            bpy.ops.ed.undo_push(message='Custom create')
        elif phase == 2:
            target = store()
            target.write_stack(definition, ())
            point().location.y = .75
            state['old'] = target
            bpy.ops.ed.undo_push(message='Custom edit and deselect')
        elif phase == 3:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            try:
                state['old'].read_stack(definition)
            except PropertyError:
                pass
            else:
                raise AssertionError('Retained store survived undo')
            assert store().read_stack(definition)[0].enabled is False and point().location.y == .25
            state['checks'].append('undo restores disabled CUSTOM selection and mapping content')
        elif phase == 4:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert ROOT not in bpy.context.scene and store().read_stack(definition) == ()
            try:
                bank.reference(store(), definition, 'PRESSURE')
            except PropertyError:
                pass
            else:
                raise AssertionError('Mapping survived unset undo')
            state['checks'].append('undo restores absent mapping and metadata')
        elif phase == 5:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert store().read_stack(definition)[0].enabled is False and point().location.y == .25
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert store().read_stack(definition) == () and point().location.y == .75
            state['checks'].append('redo restores selection and dormant edited mapping')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-custom-headed.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('CUSTOM_HEADED_OK', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .5
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
