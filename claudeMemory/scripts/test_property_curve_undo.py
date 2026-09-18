# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headed preset customization undo, redo, save/load and dead-owner cache gate."""
import json
from pathlib import Path
import sys
import traceback
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle, sampling
from generic_property_test_package.curves import CurveBank, declaration_name
from generic_property_test_package.customize import customize
from generic_property_test_package.registry import Definition, DeviceLayer, PropertyError, Registry, ResponseCurve
from generic_property_test_package.storage import PersistentOwnerStore

lifecycle.register()
registry = Registry()
definition = registry.register(Definition('test.plan5.undo', 'Response', 'FLOAT32', 1, 0, 10, 0, 1))
bank = CurveBank(registry)
bank.register()
name = declaration_name(definition.identifier, 'PRESSURE')
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
brush = bpy.data.brushes.new('Plan5Undo', mode='SCULPT')
brush.use_fake_user = True
def store(owner):
    return PersistentOwnerStore(owner, registry, curve_bank=bank)
for owner in (brush, bpy.context.scene):
    store(owner).write_stack(definition, (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
state = {'phase': 0, 'checks': []}
directory = Path(__file__).resolve().parents[1] / 'tests'
def check(name, condition):
    assert condition, name
    state['checks'].append(name)
def step():
    try:
        phase = state['phase']
        brush = bpy.data.brushes['Plan5Undo']
        if phase == 0:
            bpy.ops.ed.undo_push(message='Preset baseline')
        elif phase == 1:
            customize(store(brush), definition, 'PRESSURE')
            ref = store(brush).read_stack(definition)[0].curve
            state['active'] = sampling.resolved_response(store(brush), definition, ref)
            state['epoch'] = sampling.epoch
        elif phase == 2:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            brush = bpy.data.brushes['Plan5Undo']
            check('one undo removes Brush seeded mapping', getattr(brush, name) is None
                  and store(brush).read_stack(definition)[0].curve == ResponseCurve('SQUARE'))
            check('undo clears curve cache', not sampling.cache.contents and sampling.epoch > state['epoch'])
        elif phase == 3:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            brush = bpy.data.brushes['Plan5Undo']
            check('redo restores Brush mapping and selection', len(getattr(brush, name).curves[0].points) == 256)
            ref = store(brush).read_stack(definition)[0].curve
            check('redo sampled response agrees', sampling.resolved_response(store(brush), definition, ref)
                  == state['active'])
        elif phase == 4:
            customize(store(bpy.context.scene), definition, 'PRESSURE')
        elif phase == 5:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            check('one undo removes Scene seeded mapping', getattr(bpy.context.scene, name) is None)
        elif phase == 6:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            check('redo restores Scene mapping', len(getattr(bpy.context.scene, name).curves[0].points) == 256)
            bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'plan5-customized.blend'))
            state['epoch'] = sampling.epoch
        elif phase == 7:
            bpy.ops.wm.open_mainfile(filepath=str(directory / 'plan5-customized.blend'))
            check('load clears all cache state', sampling.epoch > state['epoch'] and not sampling.cache.contents)
        elif phase == 8:
            brush = bpy.data.brushes['Plan5Undo']
            for owner in (brush, bpy.context.scene):
                local = store(owner)
                check('saved mapping ' + owner.bl_rna.identifier,
                      sampling.resolved_response(local, definition, local.read_stack(definition)[0].curve)
                      == state['active'])
            copied = brush.copy()
            local = store(copied)
            ref = local.read_stack(definition)[0].curve
            sampling.resolved_response(local, definition, ref)
            bpy.data.brushes.remove(copied)
            try:
                sampling.resolved_response(local, definition, ref)
            except PropertyError:
                check('removed owner rejects cached access', True)
            else:
                raise AssertionError('removed owner survived cache lookup')
            bank.unregister()
            bank.register()
            local = store(brush)
            check('re-registration reconstructs valid references',
                  sampling.resolved_response(local, definition, local.read_stack(definition)[0].curve)
                  == state['active'])
        else:
            (directory / 'plan5-curve-undo.checks.json').write_text(json.dumps(state['checks'], indent=2) + '\n')
            print('PLAN5_CURVE_UNDO_PASS', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .4
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None
bpy.app.timers.register(step, first_interval=1, persistent=True)
