# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Interleave real engine mask/custom undo with Brush authoring and addon lifetime."""
import json
from itertools import product
from pathlib import Path
import traceback
import bpy
import addon_utils
from sculptcore_addon import engine, ops, undo
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve

bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])
shortcut_cases = tuple(product(('UNIFIED', 'ALWAYS', 'NEVER'), (False, True), ('VIEW', 'SCENE')))


def size_state():
    active = bpy.context.tool_settings.sculpt.brush
    unified = bpy.context.tool_settings.sculpt.unified_paint_settings
    return tuple((owner.size, owner.unprojected_size, owner.use_locked_size) for owner in (active, unified))


def shortcut_step(index, phase):
    active = bpy.context.tool_settings.sculpt.brush
    scene = bpy.context.scene
    unified = scene.tool_settings.sculpt.unified_paint_settings
    mode, flag, size_mode = shortcut_cases[index]
    factor = 1.0 / .9 if flag else .9
    if phase == 0:
        scene.sculptcore_generic_properties = True
        for owner, pixels, world in ((active, 100, .4), (unified, 200, .8)):
            owner.size, owner.unprojected_size, owner.use_locked_size = pixels, world, size_mode
        unified.use_unified_size = flag
        local, parent = authoring.store(active), authoring.store(scene)
        local.write_mode(SIZE, mode)
        local.write_stack_inheritance(SIZE, not flag)
        for store, preset in ((local, 'SQUARE'), (parent, 'LINEAR')):
            store.write_stack(authoring.registry.get(SIZE), (DeviceLayer('PRESSURE', curve=ResponseCurve(preset)),))
        state['stacks'] = local.read_stack(authoring.registry.get(SIZE)), parent.read_stack(authoring.registry.get(SIZE))
        state['size_before'] = size_state()
        bpy.ops.ed.undo_push(message='Size shortcut baseline')
        window = bpy.context.window
        area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
        region = next(item for item in area.regions if item.type == 'WINDOW')
        x, y = region.x + region.width // 2, region.y + region.height // 2
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        key = 'RIGHT_BRACKET' if flag else 'LEFT_BRACKET'
        window.event_simulate(type=key, value='PRESS', x=x, y=y)
        window.event_simulate(type=key, value='RELEASE', x=x, y=y)
    elif phase == 1:
        current, before = size_state(), state['size_before']
        target = int(mode == 'ALWAYS' or (mode == 'UNIFIED' and flag))
        field = 0 if size_mode == 'VIEW' else 1
        expected = before[target][field] * factor
        if field == 0:
            expected = int(expected + .5)
        check('bracket edits effective owner {}'.format(shortcut_cases[index]),
              abs(current[target][field] - expected) < 1e-6 and current[1 - target] == before[1 - target])
        current_stacks = tuple(authoring.store(owner).read_stack(authoring.registry.get(SIZE))
                               for owner in (active, scene))
        check('bracket preserves independent stacks {}'.format(index), current_stacks == state['stacks'])
        state['size_after'] = current
        bpy.ops.ed.undo()
    elif phase == 2:
        check('bracket undo restores coupled sizes {}'.format(index), size_state() == state['size_before'])
        bpy.ops.ed.redo()
    else:
        check('bracket redo restores coupled sizes {}'.format(index), size_state() == state['size_after'])


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
        elif phase == 14:
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
        elif phase < 15 + 4 * len(shortcut_cases):
            shortcut_step((phase - 15) // 4, (phase - 15) % 4)
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
