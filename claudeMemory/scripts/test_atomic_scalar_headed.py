# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual persistent generic Scene value/policy undo and draw-time write rejection."""
import json
from pathlib import Path
import sys
import traceback
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT

lifecycle.register()
registry = Registry()
definition = registry.register(Definition('test.undo', 'Undo', 'FLOAT32', .5, 0, 10, 0, 1))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, draw_rejections=0, checks=[])


def store():
    return PersistentOwnerStore(bpy.context.scene, registry)


class ATOMICSCALAR_PT_test(bpy.types.Panel):
    bl_label = 'Atomic scalar test'
    bl_idname = 'ATOMICSCALAR_PT_test'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    def draw(self, context):
        try:
            context.scene.id_properties_update_atomic('atomic_draw_rejected', ())
        except PermissionError:
            state['draw_rejections'] += 1
        else:
            raise AssertionError('Draw-time write context was not rejected')
        if ROOT in context.scene:
            path = store().value_path(definition.identifier)
            group = context.scene.path_resolve(path.rsplit('[', 1)[0], False)
            self.layout.prop(group, '["value"]', text='Actual scalar')
        else:
            self.layout.label(text='Unset')


bpy.utils.register_class(ATOMICSCALAR_PT_test)
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.show_region_ui = True


def stale(value):
    try:
        value.read_value(definition)
    except PropertyError:
        return
    raise AssertionError('Old store survived undo')


def step():
    try:
        phase = state['phase']
        if phase == 0:
            assert ROOT not in bpy.context.scene
            bpy.ops.ed.undo_push(message='Atomic unset')
        elif phase == 1:
            store().write_value(definition, .375)
            store().write_unified(definition.identifier, True)
            bpy.ops.ed.undo_push(message='Atomic create')
        elif phase == 2:
            store().write_value(definition, .75)
            store().write_unified(definition.identifier, False)
            state['old'] = store()
            bpy.ops.ed.undo_push(message='Atomic edit')
        elif phase == 3:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            stale(state['old'])
            assert store().read_value(definition).value == .375 and store().unified(definition.identifier)
            state['checks'].append('Scene scalar and unified policy undo with stale-store rejection')
        elif phase == 4:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert ROOT not in bpy.context.scene
            assert not store().read_value(definition).present
            state['checks'].append('Scene undo restores absent root')
        elif phase == 5:
            assert bpy.ops.ed.redo() == {'FINISHED'}
            assert store().read_value(definition).value == .375 and store().unified(definition.identifier)
            state['checks'].append('Scene redo restores actual persistent generic records')
        else:
            assert state['draw_rejections'] > 0 and 'atomic_draw_rejected' not in bpy.context.scene
            state['checks'].append('draw-time native write rejection and generic custom-property UI rendering')
            target = Path(__file__).resolve().parents[1] / 'tests/plan4-atomic-headed-results.json'
            target.write_text(json.dumps(dict(passed=True, checks=state['checks'],
                                             draw_rejections=state['draw_rejections']), indent=2) + '\n')
            bpy.utils.unregister_class(ATOMICSCALAR_PT_test)
            lifecycle.unregister()
            print('ATOMIC_SCALAR_HEADED_PASS', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        for area in bpy.context.screen.areas:
            area.tag_redraw()
        return .5
    except Exception:
        traceback.print_exc()
        print('ATOMIC_SCALAR_HEADED_FAIL', flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
