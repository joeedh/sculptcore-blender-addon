# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Undo full Brush generic authoring through the engine-independent native boundary."""
import json
from pathlib import Path
import traceback
import bpy
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.curves import declaration_name
from sculptcore_addon.brush_properties.edits import authoring_edit
from sculptcore_addon.brush_properties.registry import DeviceLayer, Position, PropertyError

identifier = 'sculptcore.kernel.kelvinlet.mu'
definition = authoring.registry.get(identifier)
state = dict(phase=0, checks=[])
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True


def owner():
    return bpy.data.brushes['Collection Authoring']


def store():
    return authoring.store(owner())


def step():
    try:
        phase = state['phase']
        if phase == 0:
            b = bpy.data.brushes.new('Collection Authoring', mode='SCULPT')
            b.use_fake_user = True
            bpy.ops.ed.undo_push(message='Collection baseline')
        elif phase == 1:
            target = store()
            with authoring_edit(target, 'Create generic brush authoring', native_settings=False):
                target.write_value(definition, .375)
                target.write_positions(definition, (Position('TEST', -3), Position('OTHER', 5)))
                reference = authoring.curve_bank.initialize(target, definition, 'SPEED')
                mapping = authoring.curve_bank.mapping(target, definition, reference)
                mapping.curves[0].points[-1].location.y = .625
                reference = authoring.curve_bank.reference(target, definition, 'SPEED')
                target.write_stack(definition, (DeviceLayer('SPEED', False, curve=reference),))
            state['old'] = target
        elif phase == 2:
            target = store()
            with authoring_edit(target, 'Remove custom curve', native_settings=False):
                target.write_stack(definition, ())
                authoring.curve_bank.remove(target, definition, 'SPEED')
                target.write_positions(definition, ())
                target.write_value(definition, .875)
        elif phase == 3:
            bpy.ops.ed.undo()
            target = store()
            assert target.read_value(definition).value == .375
            assert target.read_positions(definition) == (Position('TEST', -3), Position('OTHER', 5))
            assert target.read_stack(definition)[0].enabled is False
            assert getattr(owner(), declaration_name(identifier, 'SPEED')).curves[0].points[-1].location.y == .625
            state['checks'].append('Brush undo restores scalar, positions, disabled selection and custom payload')
            try:
                state['old'].read_stack(definition)
            except PropertyError:
                pass
            else:
                raise AssertionError('retained store survived undo')
        elif phase == 4:
            bpy.ops.ed.undo()
            target = store()
            assert not target.read_value(definition).present
            assert getattr(owner(), declaration_name(identifier, 'SPEED')) is None
            assert target.read_positions(definition) == definition.positions
            state['checks'].append('second Brush undo restores complete absence')
        elif phase == 5:
            bpy.ops.ed.redo()
            assert store().read_stack(definition)[0].enabled is False
            bpy.ops.ed.redo()
            assert store().read_value(definition).value == .875
            assert store().read_stack(definition) == () and store().read_positions(definition) == ()
            assert getattr(owner(), declaration_name(identifier, 'SPEED')) is None
            state['checks'].append('redo restores creation followed by removal and explicit empty positions')
        elif phase == 6:
            # Native restoration uses no authoring Python or engine callbacks.
            import addon_utils
            import sculptcore_addon
            assert sculptcore_addon.SculptCoreMode.__bases__[0] is bpy.types.ObjectModeType
            addon_utils.disable('sculptcore_addon', default_set=False)
            bpy.ops.ed.undo()
            assert owner().get('sculptcore_properties') is not None
            addon_utils.enable('sculptcore_addon', default_set=False)
            assert addon_utils.check('sculptcore_addon')[1]
            assert store().read_value(definition).value == .375
            assert store().read_stack(definition)[0].enabled is False
            assert store().read_positions(definition) == (Position('TEST', -3), Position('OTHER', 5))
            assert getattr(owner(), declaration_name(identifier, 'SPEED')).curves[0].points[-1].location.y == .625
            state['checks'].append('native undo works with addon unregistered and mapping declarations absent')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-collections.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_COLLECTIONS_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .4
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
