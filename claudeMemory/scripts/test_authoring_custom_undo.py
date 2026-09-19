# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Interleave real engine mask/custom undo with Brush authoring and addon lifetime."""
import json
import sys
from itertools import product
from pathlib import Path
import traceback
import bpy
import addon_utils
from sculptcore_addon import engine, ops, undo
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve

bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])
shortcut_cases = tuple(product(('UNIFIED', 'ALWAYS', 'NEVER'), (False, True), ('VIEW', 'SCENE')))
variant = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
radial_test = variant == ['radial']
legacy_test = variant == ['radial-legacy']
rows_test = variant == ['rows']
rows_ui_test = variant == ['rows-ui']
stacks_test = variant == ['stacks']
stacks_ui_test = variant == ['stacks-ui']
placements_test = variant == ['placements']
panels_test = variant == ['panels']
stack_actions = (
    ('stack_action', dict(action='ADD', device='TILT_X')),
    ('stack_action', dict(action='ADD', device='SPEED')),
    ('stack_action', dict(action='ADD', device='TILT_Y')),
    ('stack_layer', dict(device='SPEED', operation='ADD', factor=.25, preset='TWO_STEP', threshold=.3, low=.2, high=.9)),
    ('stack_action', dict(action='UP', device='SPEED')),
    ('stack_action', dict(action='TOGGLE', device='TILT_X')),
    ('stack_action', dict(action='REMOVE', device='TILT_Y')),
    ('stack_action', dict(action='CUSTOM', device='SPEED')),
    ('stack_layer', dict(device='SPEED', operation='ADD', factor=.25, preset='SQUARE')),
    ('stack_action', dict(action='RESEED', device='SPEED')),
    ('stack_layer', dict(device='SPEED', operation='ADD', factor=.25, preset='LINEAR')),
    ('stack_action', dict(action='CUSTOM', device='SPEED')),
    ('stack_action', dict(action='CUSTOM', device='PRESSURE')),
)
row_cases = tuple(product((STRENGTH, 'sculptcore.brush.spacing', 'sculptcore.brush.accumulate'),
                          ('UNIFIED', 'ALWAYS', 'NEVER'), (False, True)))
policy_cases = (('MODE', 'ALWAYS'), ('MODE', 'NEVER'), ('MODE', 'UNIFIED'),
                ('UNIFIED', 'UNIFIED'), ('STACK_INHERIT', 'NEVER'))
radial_cases = tuple((SIZE, *case) for case in shortcut_cases) + tuple(
    (STRENGTH, mode, flag, 'VIEW') for mode, flag in product(('UNIFIED', 'ALWAYS', 'NEVER'), (False, True)))


def size_state():
    active = bpy.context.tool_settings.sculpt.brush
    unified = bpy.context.tool_settings.sculpt.unified_paint_settings
    return tuple((owner.size, owner.unprojected_size, owner.use_locked_size, owner.strength)
                 for owner in (active, unified))


def row_state(identifier):
    definition = authoring.registry.get(identifier)
    stores = (authoring.store(bpy.context.tool_settings.sculpt.brush), authoring.store(bpy.context.scene))
    return tuple((store.read_value(definition).value, store._stack_descriptions(definition)) for store in stores)


def stack_state():
    from sculptcore_addon.brush_properties.curves import declaration_name
    from sculptcore_addon.brush_properties.registry import DEVICE_TYPES
    result = []
    for owner in (bpy.context.tool_settings.sculpt.brush, bpy.context.scene):
        curves = []
        for device in DEVICE_TYPES:
            name = declaration_name(STRENGTH, device)
            mapping = getattr(owner, name, None)
            curves.append(None if mapping is None else tuple(
                (tuple(point.location), point.handle_type) for point in mapping.curves[0].points))
        native = owner.authoring_native_curve_key('curve_strength') if isinstance(owner, bpy.types.Brush) else None
        store = authoring.store(owner)
        result.append((store.read_value(authoring.registry.get(STRENGTH)).value,
                       store._stack_descriptions(authoring.registry.get(STRENGTH)), tuple(curves), native))
    return tuple(result)


def stack_step(index, phase):
    inherited, operation_index = divmod(index, len(stack_actions))
    target = inherited
    if phase == 0:
        if operation_index == 0:
            bpy.context.scene.sculptcore_generic_properties = True
            local = authoring.store(bpy.context.tool_settings.sculpt.brush)
            parent = authoring.store(bpy.context.scene)
            local.write_mode(STRENGTH, 'NEVER' if inherited else 'ALWAYS')
            local.write_stack_inheritance(STRENGTH, bool(inherited))
            for store in (local, parent):
                store.write_stack(authoring.registry.get(STRENGTH), (DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
            before = stack_state()
            try:
                bpy.ops.sculptcore.stack_action('EXEC_DEFAULT', True, identifier=STRENGTH,
                                                device='PRESSURE', action='ADD')
            except RuntimeError as error:
                check('duplicate input rejected {}'.format(inherited), 'already has an entry' in str(error))
            else:
                raise AssertionError('Duplicate input was accepted')
            check('duplicate input leaves both owners unchanged {}'.format(inherited), stack_state() == before)
            from sculptcore_addon.brush_properties.stack_ui import StackEdit
            from sculptcore_addon.brush_properties.registry import PropertyError
            try:
                StackEdit(bpy.context, 'sculptcore.brush.accumulate')
            except PropertyError:
                check('static property rejects a stack editor {}'.format(inherited), True)
            else:
                raise AssertionError('Static property exposed a stack editor')
            edit = StackEdit(bpy.context, STRENGTH)
            local.write_stack_inheritance(STRENGTH, not bool(inherited))
            try:
                edit.check(bpy.context)
            except PropertyError:
                check('stack draft rejects changed owner {}'.format(inherited), True)
            else:
                raise AssertionError('Stack draft accepted a changed owner')
            local.write_stack_inheritance(STRENGTH, bool(inherited))
            bpy.ops.ed.undo_push(message='Input stack baseline')
        state['stack_before'] = stack_state()
        op, arguments = stack_actions[operation_index]
        result = getattr(bpy.ops.sculptcore, op)('EXEC_DEFAULT', True, identifier=STRENGTH, **arguments)
        check('stack action commits {}'.format(index), result == {'FINISHED'})
        after, before = stack_state(), state['stack_before']
        check('stack action preserves other owner and both values {}'.format(index),
              after[1 - target] == before[1 - target] and after[target][0] == before[target][0])
        if operation_index == 6:
            layers = after[target][1]
            check('stack order, disable and mix semantics {}'.format(inherited),
                  tuple(layer[0] for layer in layers) == ('PRESSURE', 'SPEED', 'TILT_X')
                  and layers[1][2:4] == ('ADD', .25) and layers[1][4] == 'TWO_STEP' and not layers[2][1])
        if operation_index == 11:
            check('custom reselect preserves dormant mapping {}'.format(inherited), after[target][2] == before[target][2])
        state['stack_after'] = after
        bpy.ops.ed.undo()
    elif phase == 1:
        check('stack action undo {}'.format(index), stack_state() == state['stack_before'])
        bpy.ops.ed.redo()
    else:
        check('stack action redo {}'.format(index), stack_state() == state['stack_after'])


def stack_ui_step(phase):
    from sculptcore_addon.brush_properties import stack_ui
    active, scene = bpy.context.tool_settings.sculpt.brush, bpy.context.scene
    window = bpy.context.window

    def key(kind):
        window.event_simulate(type=kind, value='PRESS', x=350, y=140)
        window.event_simulate(type=kind, value='RELEASE', x=350, y=140)

    def click(x, y, *, ctrl=False):
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        bpy.app.timers.register(lambda: window.event_simulate(
            type='LEFTMOUSE', value='PRESS', ctrl=ctrl, x=x, y=y) and None, first_interval=.05)
        bpy.app.timers.register(lambda: window.event_simulate(
            type='LEFTMOUSE', value='RELEASE', ctrl=ctrl, x=x, y=y) and None, first_interval=.1)

    def open_native():
        assert bpy.ops.sculptcore.native_response('INVOKE_DEFAULT', True, identifier=STRENGTH) == {'RUNNING_MODAL'}

    if phase == 0:
        scene.sculptcore_generic_properties = True
        local = authoring.store(active)
        local.write_mode(STRENGTH, 'NEVER')
        local.write_stack_inheritance(STRENGTH, False)
        local.write_stack(authoring.registry.get(STRENGTH), (
            DeviceLayer('PRESSURE', curve=local._native.curve_reference(STRENGTH)), DeviceLayer('SPEED')))
        state['native_before'] = active.authoring_native_curve_key('curve_strength')
        bpy.ops.ed.undo_push(message='Native response widget baseline')
        try:
            bpy.ops.sculptcore.native_response('EXEC_DEFAULT', True, identifier=STRENGTH)
        except RuntimeError as error:
            check('native curve rejects execution without an active dialog', 'cancelled' in str(error))
        else:
            raise AssertionError('Native editor executed without a dialog')
        open_native()
    elif phase in (1, 4):
        click(350, 140, ctrl=True)
    elif phase == 13:
        # Reopening a mapping with a selected point focuses its X field. Leave
        # text entry before sending the separate graph insertion event.
        click(200, 325)
    elif phase == 14:
        click(450, 180, ctrl=True)
    elif phase == 2:
        check('native graph widget edits authoritative mapping', active.authoring_native_curve_key(
            'curve_strength') != state['native_before'])
        key('ESC')
    elif phase == 3:
        check('native graph cancel restores exact definition', active.authoring_native_curve_key(
            'curve_strength') == state['native_before'] and not stack_ui._native_editors)
        open_native()
    elif phase == 5:
        key('RET')
    elif phase == 6:
        state['native_after'] = active.authoring_native_curve_key('curve_strength')
        check('native graph Apply retires scope', not stack_ui._native_editors
              and state['native_after'] != state['native_before'])
        bpy.ops.ed.undo()
    elif phase == 7:
        check('native graph one-step undo', active.authoring_native_curve_key('curve_strength') == state['native_before'])
        bpy.ops.ed.redo()
    elif phase == 8:
        check('native graph redo', active.authoring_native_curve_key('curve_strength') == state['native_after'])
        bpy.ops.sculptcore.stack_action('EXEC_DEFAULT', True, identifier=STRENGTH, device='SPEED', action='CUSTOM')
    elif phase == 9:
        state['stack_draw_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                           for owner in (active, scene))
        bpy.ops.sculptcore.property_stack('INVOKE_DEFAULT', True, identifier=STRENGTH)
    elif phase == 10:
        for owner, token in zip((active, scene), state.pop('stack_draw_tokens')):
            check('input-stack drawing preserves ' + owner.bl_rna.identifier, not owner.authoring_edit_commit(token))
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-stack-ui.png'))
        key('ESC')
    elif phase == 11:
        state['native_teardown'] = active.authoring_native_curve_key('curve_strength')
    elif phase == 12:
        open_native()
    elif phase == 15:
        check('native teardown case actually edited curve', active.authoring_native_curve_key(
            'curve_strength') != state['native_teardown'])
        addon_utils.disable('sculptcore_addon', default_set=False)
        check('native curve addon disable rolls back scope', not stack_ui._native_editors
              and active.authoring_native_curve_key('curve_strength') == state['native_teardown'])
        addon_utils.enable('sculptcore_addon', default_set=False)
        key('ESC')
    elif phase == 16:
        check('native curve re-enable has no active editors', not stack_ui._native_editors)
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif phase == 17:
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
        local, parent = authoring.store(active), authoring.store(scene)
        local.write_mode(STRENGTH, 'NEVER')
        local.write_stack_inheritance(STRENGTH, True)
        parent.write_stack(authoring.registry.get(STRENGTH), (DeviceLayer('PRESSURE'), DeviceLayer('SPEED')))
        bpy.ops.sculptcore.stack_action('EXEC_DEFAULT', True, identifier=STRENGTH, device='SPEED', action='CUSTOM')
        state['owned_before'] = stack_state()
        bpy.ops.ed.undo_push(message='Inherited curve widget baseline')
        bpy.ops.sculptcore.property_stack('INVOKE_DEFAULT', True, identifier=STRENGTH)
    elif phase in (18, 24):
        click(740, 63)
    elif phase in (19, 25):
        click(600, 490)  # Leave the coordinate field before selecting a preset.
    elif phase in (20, 26):
        click(730, 447)  # Owned editor's Smooth preset.
    elif phase in (21, 27):
        check('owned curve widget stages edits {}'.format(phase), stack_state() == state['owned_before'])
        if phase == 21:
            key('ESC')
        else:
            click(650, 31)  # Apply.
    elif phase == 22:
        check('owned curve Cancel preserves both owners', stack_state() == state['owned_before'])
        key('ESC')  # Close the parent stack popup too.
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif phase == 23:
        bpy.ops.sculptcore.property_stack('INVOKE_DEFAULT', True, identifier=STRENGTH)
    elif phase == 28:
        state['owned_after'] = stack_state()
        check('owned curve Apply edits inherited Scene only', state['owned_after'][0] == state['owned_before'][0]
              and state['owned_after'][1] != state['owned_before'][1])
        bpy.ops.ed.undo()
    elif phase == 29:
        check('owned curve one-step undo', stack_state() == state['owned_before'])
        bpy.ops.ed.redo()
    elif phase == 30:
        check('owned curve redo', stack_state() == state['owned_after'])
        key('ESC')


def placement_step(phase):
    from sculptcore_addon.brush_properties import placement, ui as property_ui
    from sculptcore_addon.brush_properties.registry import Position, PropertyError
    from sculptcore_addon.brush_properties.placement_ui import PlacementEdit
    active, scene = bpy.context.tool_settings.sculpt.brush, bpy.context.scene
    local = authoring.store(active)
    definition = authoring.registry.get(STRENGTH)
    window = bpy.context.window

    def key(kind):
        window.event_simulate(type=kind, value='PRESS', x=350, y=140)
        window.event_simulate(type=kind, value='RELEASE', x=350, y=140)

    def saved():
        return placement.positions(authoring.store(bpy.context.tool_settings.sculpt.brush), definition)

    def draw_begin(panel):
        state['placement_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                          for owner in (active, scene))
        bpy.ops.wm.call_panel(name=panel)

    def draw_end(location):
        for owner, token in zip((active, scene), state.pop('placement_tokens')):
            check('placement draw preserves ' + location + owner.bl_rna.identifier,
                  not owner.authoring_edit_commit(token))
        check('real surface draws strength ' + location, STRENGTH in state['placement_draws'][location])
        key('ESC')

    if phase == 0:
        scene.sculptcore_generic_properties = True
        local.write_mode(STRENGTH, 'ALWAYS')
        local.write_stack_inheritance(STRENGTH, True)
        local.write_positions(definition, (Position('FUTURE_SURFACE', -7),))
        state['placement_before'], state['placement_values'] = saved(), stack_state()
        # Observe the real renderer, retaining its actual drawing behavior.
        state['placement_draws'] = {}
        state['draw_location_original'], state['draw_row_original'] = property_ui.draw_location, property_ui.draw_row
        def draw_location(layout, context, location):
            state['placement_location'] = location
            state['placement_draws'][location] = []
            try:
                state['draw_location_original'](layout, context, location)
            finally:
                state['placement_location'] = None
        def draw_row(layout, context, item):
            if state.get('placement_location'):
                state['placement_draws'][state['placement_location']].append(item.identifier)
            state['draw_row_original'](layout, context, item)
        property_ui.draw_location, property_ui.draw_row = draw_location, draw_row
        bpy.ops.ed.undo_push(message='Placement baseline')
    elif phase == 1:
        bpy.ops.sculptcore.property_placement('EXEC_DEFAULT', True, identifier=STRENGTH,
            header=True, header_order=-5, settings=True, settings_order=-4, menu=True, menu_order=-3,
            automasking=True, automasking_order=-2)
        state['placement_after'] = saved()
        check('placement edits local Brush with inherited value and stack', saved() == (
            Position('FUTURE_SURFACE', -7), Position('VIEW3D_HEADER', -5),
            Position('BRUSH_SETTINGS', -4), Position('CONTEXT_MENU', -3), Position('AUTOMASKING', -2))
            and stack_state() == state['placement_values'])
        bpy.ops.ed.undo()
    elif phase == 2:
        check('placement one-step undo', saved() == state['placement_before'])
        bpy.ops.ed.redo()
    elif phase == 3:
        check('placement redo', saved() == state['placement_after'])
        check('header ordering takes effect', state['placement_draws']['VIEW3D_HEADER'][0] == STRENGTH)
        draw_begin('SCULPTCORE_PT_tools_brush_settings')
    elif phase == 4:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-placement-settings.png'))
        draw_end('BRUSH_SETTINGS')
    elif phase == 5:
        draw_begin('SCULPTCORE_PT_sculpt_context_menu')
    elif phase == 6:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-placement-menu.png'))
        draw_end('CONTEXT_MENU')
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif phase in (7, 10):
        bpy.ops.sculptcore.property_placement('INVOKE_DEFAULT', True, identifier=STRENGTH)
    elif phase == 8:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-placement-ui.png'))
        key('ESC')
    elif phase == 9:
        check('placement dialog cancel preserves saved layout', saved() == state['placement_after'])
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif phase == 11:
        # Tool Header checkbox in the fixed-size placement dialog.
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=160, y=211)
        bpy.app.timers.register(lambda: window.event_simulate(
            type='LEFTMOUSE', value='PRESS', x=160, y=211) and None, first_interval=.05)
        bpy.app.timers.register(lambda: window.event_simulate(
            type='LEFTMOUSE', value='RELEASE', x=160, y=211) and None, first_interval=.1)
    elif phase == 12:
        check('placement dialog stages edits', saved() == state['placement_after'])
        key('RET')
    elif phase == 13:
        check('placement dialog confirms selected locations', saved() == tuple(
            item for item in state['placement_after'] if item.location != 'VIEW3D_HEADER'))
        state['placement_dialog_after'] = saved()
        bpy.ops.ed.undo()
    elif phase == 14:
        check('placement dialog undo', saved() == state['placement_after'])
        bpy.ops.ed.redo()
    elif phase == 15:
        check('placement dialog redo', saved() == state['placement_dialog_after'])
        bpy.ops.sculptcore.property_placement('EXEC_DEFAULT', True, identifier=STRENGTH, reset=True)
    elif phase == 16:
        check('placement reset restores defaults', saved() == (
            Position('VIEW3D_HEADER', 20), Position('BRUSH_SETTINGS', 20), Position('CONTEXT_MENU', 20)))
        bpy.ops.ed.undo()
    elif phase == 17:
        check('placement reset undo restores unknown location', saved() == state['placement_dialog_after'])
        edit = PlacementEdit(bpy.context, STRENGTH)
        local.write_positions(definition, (Position('BRUSH_SETTINGS', 45),))
        try:
            edit.write(bpy.context, ())
        except PropertyError:
            check('stale placement draft rejected', True)
        else:
            raise AssertionError('Stale placement draft was accepted')
        bpy.ops.sculptcore.property_placement('EXEC_DEFAULT', True, identifier=STRENGTH)
        check('deselecting all supported locations saves explicit empty', saved() == ())
    elif phase == 18:
        local.write_positions(definition, state['placement_after'])
        bpy.context.window_manager.sculptcore_property_search = 'temporary search'
        # External active assets are resolved lazily after file load. Persist an
        # explicit copy of the edited Brush to test its data without asset IO.
        persisted = active.copy()
        persisted.name = 'PlacementPersistenceBrush'
        persisted.use_fake_user = True
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-placements.blend'))
        local.write_mode(SIZE, 'ALWAYS')
        scene.tool_settings.sculpt.unified_paint_settings.use_locked_size = 'VIEW'
        state['units_before'] = size_state()
        bpy.ops.ed.undo_push(message='Size units baseline')
        bpy.ops.sculptcore.property_action('EXEC_DEFAULT', True, identifier=SIZE, action='SIZE_MODE', size_mode='SCENE')
        state['units_after'] = size_state()
        check('size units edit effective Scene only', state['units_after'][0] == state['units_before'][0]
              and state['units_after'][1][2] == 'SCENE' and state['units_before'][1][2] == 'VIEW')
        bpy.ops.ed.undo()
    elif phase == 19:
        check('size units undo restores coupled values', size_state() == state['units_before'])
        bpy.ops.ed.redo()
    elif phase == 20:
        check('size units redo', size_state() == state['units_after'])
    elif phase == 21:
        draw_begin('SCULPTCORE_PT_tools_brush_settings_advanced')
    else:
        draw_end('AUTOMASKING')
        property_ui.draw_location, property_ui.draw_row = state['draw_location_original'], state['draw_row_original']


def row_step(index, phase):
    identifier, mode, flag = row_cases[index]
    target = int(mode == 'ALWAYS' or (mode == 'UNIFIED' and flag))
    stack_target = int(not flag)
    definition = authoring.registry.get(identifier)
    if phase == 0:
        bpy.context.scene.sculptcore_generic_properties = True
        local, parent = authoring.store(bpy.context.tool_settings.sculpt.brush), authoring.store(bpy.context.scene)
        values = {'FLOAT32': (.25, .5, .75), 'INT32': (10, 20, 30), 'BOOL': (False, True, None)}[definition.scalar_type]
        for store, value, preset in ((local, values[0], 'SQUARE'), (parent, values[1], 'LINEAR')):
            store.write_value(definition, value)
            if definition.dynamic:
                store.write_stack(definition, (DeviceLayer('PRESSURE', False, curve=ResponseCurve(preset)),
                                               DeviceLayer('TILT_X', curve=ResponseCurve('ROOT'))))
        local.write_mode(identifier, mode)
        local.write_stack_inheritance(identifier, not flag)
        parent.write_unified(identifier, flag)
        state['row_before'] = row_state(identifier)
        bpy.ops.ed.undo_push(message='Property row baseline')
        if definition.scalar_type == 'BOOL':
            state['row_expected'] = not values[target]
            result = bpy.ops.sculptcore.property_action('EXEC_DEFAULT', True, identifier=identifier, action='BOOLEAN')
        else:
            state['row_expected'] = values[2]
            field = 'float_value' if definition.scalar_type == 'FLOAT32' else 'int_value'
            result = bpy.ops.sculptcore.property_value('EXEC_DEFAULT', True, identifier=identifier, **{field: values[2]})
        check('row value operator commits {}'.format(index), result == {'FINISHED'})
    elif phase == 1:
        current, before = row_state(identifier), state['row_before']
        check('row edits effective value and preserves dormant state {}'.format(index),
              current[target][0] == state['row_expected'] and current[1 - target] == before[1 - target]
              and current[target][1] == before[target][1])
        state['row_value'] = current
        if definition.dynamic:
            check('row pressure commits {}'.format(index), bpy.ops.sculptcore.property_action(
                'EXEC_DEFAULT', True, identifier=identifier, action='PRESSURE') == {'FINISHED'})
    elif phase == 2:
        current, before = row_state(identifier), state['row_value']
        if definition.dynamic:
            expected_layers = list(before[stack_target][1])
            expected_layers[0] = (expected_layers[0][0], True, *expected_layers[0][2:])
            check('row pressure edits independent owner preserving curves/order {}'.format(index),
                  current[stack_target] == (before[stack_target][0], tuple(expected_layers))
                  and current[1 - stack_target] == before[1 - stack_target])
        state['row_after'] = current
        bpy.ops.ed.undo()
    elif phase == 3:
        check('first row undo {}'.format(index), row_state(identifier) == state[
            'row_value' if definition.dynamic else 'row_before'])
        if definition.dynamic:
            bpy.ops.ed.undo()
    elif phase == 4:
        check('second undo restores value {}'.format(index), row_state(identifier) == state['row_before'])
        bpy.ops.ed.redo()
    else:
        check('row value redo {}'.format(index), row_state(identifier) == state['row_value'])
        if definition.dynamic:
            bpy.ops.ed.redo()
            check('row pressure redo {}'.format(index), row_state(identifier) == state['row_after'])
            bpy.ops.sculptcore.property_action('EXEC_DEFAULT', True, identifier=identifier, action='PRESSURE')
            check('pressure disable retains curve and order {}'.format(index), row_state(identifier) == state['row_value'])


def radial_event(kind, value='PRESS', *, shift=False, offset=0):
    window = bpy.context.window
    area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
    region = next(item for item in area.regions if item.type == 'WINDOW')
    window.event_simulate(type=kind, value=value, shift=shift,
                         x=region.x + region.width // 2 + offset, y=region.y + region.height // 2)


def row_policy_step(index, phase):
    action, mode = policy_cases[index]
    local, parent = authoring.store(bpy.context.tool_settings.sculpt.brush), authoring.store(bpy.context.scene)

    def policy():
        return local.value_mode(STRENGTH), parent.unified(STRENGTH), local.inherits_stack(STRENGTH)

    if phase == 0:
        local.write_mode(STRENGTH, 'UNIFIED' if action == 'UNIFIED' else 'ALWAYS' if mode == 'NEVER' else 'NEVER')
        parent.write_unified(STRENGTH, False)
        local.write_stack_inheritance(STRENGTH, False)
        state['policy_before'], state['policy_data'] = policy(), row_state(STRENGTH)
        bpy.ops.ed.undo_push(message='Property policy baseline')
        result = bpy.ops.sculptcore.property_action('EXEC_DEFAULT', True, identifier=STRENGTH, action=action, mode=mode)
        check('policy operator commits {}'.format(index), result == {'FINISHED'})
    elif phase == 1:
        expected = list(state['policy_before'])
        expected[{'MODE': 0, 'UNIFIED': 1, 'STACK_INHERIT': 2}[action]] = mode if action == 'MODE' else True
        check('policy changes preserve dormant values and stacks {}'.format(index),
              policy() == tuple(expected) and row_state(STRENGTH) == state['policy_data'])
        state['policy_after'] = policy()
        bpy.ops.ed.undo()
    elif phase == 2:
        check('policy undo {}'.format(index), policy() == state['policy_before']
              and row_state(STRENGTH) == state['policy_data'])
        bpy.ops.ed.redo()
    else:
        check('policy redo {}'.format(index), policy() == state['policy_after']
              and row_state(STRENGTH) == state['policy_data'])


def row_ui_step(phase):
    active, scene = bpy.context.tool_settings.sculpt.brush, bpy.context.scene
    window = bpy.context.window

    def click(x, y):
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        def press():
            window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
            return None
        def release():
            window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
            return None
        bpy.app.timers.register(press, first_interval=.05)
        bpy.app.timers.register(release, first_interval=.1)

    def number():
        click(420, 263)
        def type_value():
            window.event_simulate(type='A', value='PRESS', ctrl=True, x=420, y=263)
            for kind, char in (('ZERO', '0'), ('PERIOD', '.'), ('SEVEN', '7'), ('FIVE', '5')):
                window.event_simulate(type=kind, value='PRESS', unicode=char, x=420, y=263)
            window.event_simulate(type='RET', value='PRESS', x=420, y=263)
            window.event_simulate(type='RET', value='RELEASE', x=420, y=263)
            return None
        bpy.app.timers.register(type_value, first_interval=.2)

    if phase == 0:
        scene.sculptcore_generic_properties = True
        active.strength, scene.tool_settings.sculpt.unified_paint_settings.strength = .5, .25
        local = authoring.store(active)
        local.write_mode(STRENGTH, 'NEVER')
        local.write_stack_inheritance(STRENGTH, True)
        bpy.ops.ed.undo_push(message='Row widget baseline')
        area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
        area.type = 'PROPERTIES'
        area.spaces.active.context = 'TOOL'
        state['draw_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                     for owner in (active, scene))
    elif phase == 1:
        for owner, token in zip((active, scene), state.pop('draw_tokens')):
            check('all-properties drawing preserves ' + owner.bl_rna.identifier, not owner.authoring_edit_commit(token))
        window_manager = bpy.context.window_manager
        window_manager.sculptcore_property_search = 'strength'
    elif phase == 2:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-row-ui.png'))
        click(250, 303)
    elif phase in (3, 6):
        number()
    elif phase == 4:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-row-numeric.png'))
        check('numeric dialog does not write before confirmation', active.strength == .5)
        window.event_simulate(type='ESC', value='PRESS', x=390, y=195)
        window.event_simulate(type='ESC', value='RELEASE', x=390, y=195)
    elif phase == 5:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-row-cancelled.png'))
        check('numeric widget cancel preserves both owners', active.strength == .5
              and scene.tool_settings.sculpt.unified_paint_settings.strength == .25)
        click(250, 303)
    elif phase == 7:
        window.event_simulate(type='RET', value='PRESS', x=187, y=195)
        window.event_simulate(type='RET', value='RELEASE', x=187, y=195)
    elif phase == 8:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-row-confirmed.png'))
        check('actual numeric widget writes authoritative native owner', active.strength == .75
              and scene.tool_settings.sculpt.unified_paint_settings.strength == .25)
        bpy.ops.ed.undo()
    elif phase == 9:
        check('numeric widget creates one undo step', active.strength == .5)
        bpy.ops.ed.redo()
    elif phase == 10:
        check('numeric widget redo', active.strength == .75)
        click(1017, 303)
    elif phase == 11:
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-row-metadata.png'))
        click(1037, 167)
    elif phase == 12:
        check('metadata widget changes inheritance without copying values',
              authoring.store(active).value_mode(STRENGTH) == 'ALWAYS' and active.strength == .75
              and scene.tool_settings.sculpt.unified_paint_settings.strength == .25)
        bpy.ops.ed.undo()
    elif phase == 13:
        check('metadata widget undo', authoring.store(active).value_mode(STRENGTH) == 'NEVER'
              and active.strength == .75)
        bpy.ops.ed.redo()
    else:
        check('metadata widget redo', authoring.store(active).value_mode(STRENGTH) == 'ALWAYS'
              and active.strength == .75)


def radial_step(index, phase):
    from sculptcore_addon.brush_properties import radial
    active = bpy.context.tool_settings.sculpt.brush
    scene = bpy.context.scene
    unified = scene.tool_settings.sculpt.unified_paint_settings
    identifier, mode, flag, size_mode = radial_cases[index]
    target = int(mode == 'ALWAYS' or (mode == 'UNIFIED' and flag))
    field = (0 if size_mode == 'VIEW' else 1) if identifier == SIZE else 3
    if phase == 0:
        scene.sculptcore_generic_properties = True
        for owner, pixels, world, strength in ((active, 100, .4, .25), (unified, 200, .8, .5)):
            owner.size, owner.unprojected_size, owner.use_locked_size = pixels, world, size_mode
            owner.strength = strength
        unified.use_unified_size = unified.use_unified_strength = flag
        local, parent = authoring.store(active), authoring.store(scene)
        local.write_mode(identifier, mode)
        local.write_stack_inheritance(identifier, not flag)
        definition = authoring.registry.get(identifier)
        for store, preset in ((local, 'SQUARE'), (parent, 'LINEAR')):
            store.write_stack(definition, (DeviceLayer('PRESSURE', curve=ResponseCurve(preset)),))
        state['stacks'] = local.read_stack(definition), parent.read_stack(definition)
        state['size_before'] = size_state()
        bpy.ops.ed.undo_push(message='Radial baseline')
        radial_event('MOUSEMOVE', 'NOTHING')
        radial_event('F', shift=identifier == STRENGTH)
        radial_event('F', 'RELEASE')
    elif phase == 1:
        check('radial modal opened {}'.format(index), len(radial._active) == 1)
        radial_event('MOUSEMOVE', 'NOTHING', offset=10)
        radial_event('LEFT_SHIFT', offset=10)
        for offset in range(11, 21):
            radial_event('MOUSEMOVE', 'NOTHING', shift=True, offset=offset)
        radial_event('LEFT_SHIFT', 'RELEASE', offset=20)
    elif phase == 2:
        current = size_state()
        check('radial motion edits effective owner {}'.format(index),
              current[target][field] > state['size_before'][target][field]
              and current[1 - target] == state['size_before'][1 - target])
        if field in (0, 3):
            expected = state['size_before'][target][field] + (22 if field == 0 else .055)
            check('radial precision movement {}'.format(index), abs(current[target][field] - expected) < 1e-6)
        if index == 0:
            bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-radial.png'))
        radial_event('ESC' if flag else 'RIGHTMOUSE')
    elif phase == 3:
        check('radial cancel restores paired values {}'.format(index),
              size_state() == state['size_before'] and not radial._active)
        radial_event('MOUSEMOVE', 'NOTHING')
        radial_event('F', shift=identifier == STRENGTH)
        radial_event('F', 'RELEASE')
        radial_event('MINUS')
        radial_event('BACK_SPACE')
        text = '120' if field == 0 else '0.6' if field == 1 else '0.8'
        names = dict(zip('0123456789', ('ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE')))
        for char in text:
            radial_event('PERIOD' if char == '.' else names[char])
    elif phase == 4:
        current = size_state()
        expected = 120 if field == 0 else .6 if field == 1 else .8
        check('radial numeric entry edits effective owner {}'.format(index),
              abs(current[target][field] - expected) < 1e-6
              and current[1 - target] == state['size_before'][1 - target])
        stacks = tuple(authoring.store(owner).read_stack(authoring.registry.get(identifier))
                       for owner in (active, scene))
        check('radial preserves independent stacks {}'.format(index), stacks == state['stacks'])
        radial_event('RET')
    elif phase == 5:
        check('radial commit retires modal resources {}'.format(index), not radial._active)
        state['size_after'] = size_state()
        bpy.ops.ed.undo()
    elif phase == 6:
        check('radial undo restores coupled values {}'.format(index), size_state() == state['size_before'])
        bpy.ops.ed.redo()
    else:
        check('radial redo restores coupled values {}'.format(index), size_state() == state['size_after'])


def radial_lifetime_step(phase):
    from sculptcore_addon.brush_properties import radial
    active = bpy.context.tool_settings.sculpt.brush
    if phase in (0, 3):
        authoring.store(active).write_mode(SIZE, 'ALWAYS' if phase == 0 else 'NEVER')
        state['lifetime_before'] = size_state()
        radial_event('MOUSEMOVE', 'NOTHING')
        radial_event('F')
        radial_event('F', 'RELEASE')
        radial_event('MOUSEMOVE', 'NOTHING', offset=20)
    elif phase == 1:
        check('owner-change case has an active edit', len(radial._active) == 1 and size_state() != state['lifetime_before'])
        authoring.store(active).write_mode(SIZE, 'NEVER')
    elif phase == 2:
        check('owner change cancels pinned edit', not radial._active and size_state() == state['lifetime_before'])
        check('owner change preserves the other owner metadata', authoring.store(active).value_mode(SIZE) == 'NEVER')
    elif phase == 4:
        check('disable case has an active edit', len(radial._active) == 1 and size_state() != state['lifetime_before'])
        addon_utils.disable('sculptcore_addon', default_set=False)
        check('disable cancels authoring before unregister', not radial._active and size_state() == state['lifetime_before'])
        addon_utils.enable('sculptcore_addon', default_set=False)
        radial_event('MOUSEMOVE', 'NOTHING')
    else:
        check('re-enable leaves no modal resources', not radial._active and size_state() == state['lifetime_before'])


def radial_legacy_step(index, phase):
    from sculptcore_addon.brush_properties import radial
    identifier, flag = tuple(product((SIZE, STRENGTH), (False, True)))[index]
    field = 0 if identifier == SIZE else 3
    if phase == 0:
        bpy.context.scene.sculptcore_generic_properties = False
        active = bpy.context.tool_settings.sculpt.brush
        unified = bpy.context.tool_settings.sculpt.unified_paint_settings
        for owner, pixels, strength in ((active, 100, .25), (unified, 200, .5)):
            owner.size, owner.strength, owner.use_locked_size = pixels, strength, 'VIEW'
        unified.use_unified_size = unified.use_unified_strength = flag
        state['legacy_before'] = size_state()
        radial_event('MOUSEMOVE', 'NOTHING')
        radial_event('F', shift=identifier == STRENGTH)
        radial_event('F', 'RELEASE')
    elif phase == 1:
        check('legacy radial delegates to native {}'.format(index), not radial._active)
        radial_event('MOUSEMOVE', 'NOTHING', offset=20)
    elif phase == 2:
        current, before = size_state(), state['legacy_before']
        check('legacy radial edits native owner {}'.format(index),
              current[int(flag)][field] != before[int(flag)][field]
              and current[int(not flag)] == before[int(not flag)])
        radial_event('ESC')
    else:
        check('legacy radial cancel restores values {}'.format(index), size_state() == state['legacy_before'])


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


def panel_step(phase):
    from sculptcore_addon.brush_properties import automasking_ui, placement, stack_ui, ui as property_ui
    from sculptcore_addon.brush_properties.adapters import CAVITY
    from sculptcore_addon.brush_properties.interaction import ValueEdit
    from sculptcore_addon.brush_properties.registry import PropertyError
    from bl_ui.space_view3d import VIEW3D_PT_mesh_paint_automasking
    active, scene = bpy.context.tool_settings.sculpt.brush, bpy.context.scene
    window = bpy.context.window

    def key(kind):
        window.event_simulate(type=kind, value='PRESS', x=350, y=140)
        window.event_simulate(type=kind, value='RELEASE', x=350, y=140)

    def curve_state():
        return (active.authoring_native_curve_key('mesh_automasking_settings.cavity_curve'),
                scene.authoring_native_curve_key('tool_settings.sculpt.mesh_automasking_settings.cavity_curve'),
                active.authoring_native_curve_key('curve_distance_falloff'))

    if phase == 0:
        scene.sculptcore_generic_properties = True
        check('limited duplicate automasking panel removed', not hasattr(bpy.types, 'SCULPTCORE_PT_automasking'))
        check('all supported automasking settings occur once', tuple(item.identifier for item in
              placement.located(authoring.store(active), 'AUTOMASKING')) == automasking_ui.ORDER)
        check('disabled masks have inactive icon', not automasking_ui.active(bpy.context))
        state['panel_draw_original'] = property_ui.draw_row
        state['panel_draws'] = set()
        def observe(layout, context, definition):
            state['panel_draws'].add(definition.identifier)
            state['panel_draw_original'](layout, context, definition)
        property_ui.draw_row = observe
        state['panel_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                      for owner in (active, scene))
        bpy.ops.wm.call_panel(name='SCULPTCORE_PT_tools_brush_settings_advanced')
    elif phase == 1:
        check('actual canonical panel draws all supported settings', set(automasking_ui.ORDER) <= state['panel_draws'])
        for owner, token in zip((active, scene), state.pop('panel_tokens')):
            check('canonical draw preserves ' + owner.bl_rna.identifier, not owner.authoring_edit_commit(token))
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-automasking-ui.png'))
        key('ESC')
        property_ui.draw_row = state.pop('panel_draw_original')
    elif phase == 2:
        # The native header target delegates only in SculptCore mode.
        state['canonical_draw'] = automasking_ui.draw
        state['native_draw'] = automasking_ui._original_draw
        state['dispatch'] = []
        automasking_ui.draw = lambda layout, context: state['dispatch'].append('custom')
        automasking_ui._original_draw = lambda self, context: state['dispatch'].append('native')
        from types import SimpleNamespace
        panel = SimpleNamespace(layout=None)
        VIEW3D_PT_mesh_paint_automasking.draw(panel, bpy.context)
        VIEW3D_PT_mesh_paint_automasking.draw(panel, SimpleNamespace(active_object=SimpleNamespace(mode='SCULPT')))
        check('native header target preserves native mode dispatch', state['dispatch'] == ['custom', 'native'])
        automasking_ui.draw = state.pop('canonical_draw')
        automasking_ui._original_draw = state.pop('native_draw')
        automasking_ui.unregister()
        check('native draw callback restored exactly', VIEW3D_PT_mesh_paint_automasking.draw is not automasking_ui._native_draw)
        automasking_ui.register()
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif 3 <= phase < 30:
        case, part = divmod(phase - 3, 9)
        target = 'CAVITY' if case < 2 else 'FALLOFF'
        if part == 0:
            local = authoring.store(active)
            local.write_mode(CAVITY + '.cavity_factor', 'NEVER' if case == 0 else 'ALWAYS')
            if case < 2:
                cavity = (active if case == 0 else scene.tool_settings.sculpt).mesh_automasking_settings
                cavity.use_automasking_cavity = True
                cavity.use_automasking_custom_cavity_curve = True
                check('enabled effective cavity changes icon {}'.format(case), automasking_ui.active(bpy.context))
            state['curve_before'] = curve_state()
            bpy.ops.ed.undo_push(message='Native curve owner baseline')
            bpy.ops.sculptcore.native_response('INVOKE_DEFAULT', True, target=target)
        elif part in (1, 4):
            # Real curve widget: insert a point, then Apply or Cancel through keyboard.
            window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
            bpy.app.timers.register(lambda: window.event_simulate(
                type='LEFTMOUSE', value='PRESS', ctrl=True, x=350, y=140) and None, first_interval=.05)
            bpy.app.timers.register(lambda: window.event_simulate(
                type='LEFTMOUSE', value='RELEASE', ctrl=True, x=350, y=140) and None, first_interval=.1)
        elif part == 2:
            now = curve_state()
            check('native widget edits only effective curve {}'.format(case), now[case] != state['curve_before'][case]
                  and all(now[i] == state['curve_before'][i] for i in range(3) if i != case))
            key('ESC')
        elif part == 3:
            check('native widget cancel restores owners {}'.format(case), curve_state() == state['curve_before'])
            bpy.ops.sculptcore.native_response('INVOKE_DEFAULT', True, target=target)
        elif part == 5:
            key('RET')
        elif part == 6:
            state['curve_after'] = curve_state()
            check('native widget Apply commits {}'.format(case), not stack_ui._native_editors
                  and state['curve_after'][case] != state['curve_before'][case])
            if case != 1:
                check('native curve edit dirties Brush asset {}'.format(case), active.has_unsaved_changes)
            bpy.ops.ed.undo()
        elif part == 7:
            check('native widget undo {}'.format(case), curve_state() == state['curve_before'])
            bpy.ops.ed.redo()
        else:
            check('native widget redo {}'.format(case), curve_state() == state['curve_after'])
            window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=350, y=140)
    elif phase == 30:
        local = authoring.store(active)
        local.write_mode(STRENGTH, 'ALWAYS')
        state['first_window'] = window
        state['first_scene'] = scene
        state['pinned_edit'] = ValueEdit(bpy.context, STRENGTH)
        bpy.ops.wm.window_new_main()
    elif phase == 31:
        other = next(item for item in bpy.context.window_manager.windows if item != state['first_window'])
        state['second_window'] = other
        other.scene = scene.copy()
        check('windows retain independent scenes', state['first_window'].scene == state['first_scene']
              and other.scene != state['first_scene'])
        with bpy.context.temp_override(window=other):
            check('second window resolves its own Scene', ValueEdit(bpy.context, STRENGTH).owner.owner == other.scene)
            try:
                state['pinned_edit'].check(bpy.context)
            except PropertyError:
                check('open edit rejects a different window Scene', True)
            else:
                raise AssertionError('Edit accepted a different Scene')
            bpy.ops.sculptcore.property_value('EXEC_DEFAULT', True, identifier=STRENGTH, float_value=.37)
            check('second window edits only its Scene', abs(other.scene.tool_settings.sculpt.unified_paint_settings.strength
                  - .37) < 1e-6 and scene.tool_settings.sculpt.unified_paint_settings.strength != .37)
            bpy.ops.wm.window_close()
    elif phase == 32:
        path = str(Path(__file__).resolve().parents[1] / 'tests/brush-readonly.blend')
        saved = active.copy()
        saved.name = 'ReadOnly UI Brush'
        authoring.store(saved).write_mode(STRENGTH, 'ALWAYS')
        bpy.data.libraries.write(path, {saved})
        bpy.data.brushes.remove(saved)
        with bpy.data.libraries.load(path, link=True) as (source, destination):
            destination.brushes = ['ReadOnly UI Brush']
        linked = destination.brushes[0]
        # Use real linked RNA and a context whose sculpt brush is the linked ID.
        from types import SimpleNamespace
        context = SimpleNamespace(scene=scene, tool_settings=SimpleNamespace(sculpt=SimpleNamespace(brush=linked)))
        check('linked Brush inherits editable Scene', ValueEdit(context, STRENGTH).owner.owner == scene)
        try:
            stack_ui.NativeCurveEdit(context, 'FALLOFF')
        except PropertyError:
            check('linked native falloff fails closed', True)
        else:
            raise AssertionError('Linked Brush was editable')
        from sculptcore_addon.brush_properties.placement_ui import PlacementEdit
        try:
            PlacementEdit(context, STRENGTH)
        except PropertyError:
            check('linked Brush placement fails closed', True)
        else:
            raise AssertionError('Linked placement was editable')
        area = next(item for item in window.screen.areas if item.type == 'PROPERTIES')
        area.spaces.active.context = 'TOOL'
        state['panel_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                      for owner in (active, scene))
        state['narrow_regions'] = []
        state['panel_draw_original'] = property_ui.draw_row
        def observe(layout, context, definition):
            if context.area.type == 'PROPERTIES':
                state['narrow_regions'].append(context.region.width)
            state['panel_draw_original'](layout, context, definition)
        property_ui.draw_row = observe
        area.tag_redraw()
    elif phase == 33:
        check('real narrow Properties editor uses shared rows', state['narrow_regions'] and min(state['narrow_regions']) < 340)
        for owner, token in zip((active, scene), state.pop('panel_tokens')):
            check('narrow drawing preserves ' + owner.bl_rna.identifier, not owner.authoring_edit_commit(token))
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-narrow-ui.png'))
        property_ui.draw_row = state.pop('panel_draw_original')
    elif phase == 34:
        bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
        bpy.ops.object.mode_set(mode='SCULPT')
        state['native_draw'] = automasking_ui._original_draw
        state['native_draw_count'] = 0
        def observe_native(self, context):
            state['native_draw_count'] += 1
            state['native_draw'](self, context)
        automasking_ui._original_draw = observe_native
        bpy.ops.wm.call_panel(name='VIEW3D_PT_mesh_paint_automasking')
    elif phase == 35:
        check('switching to native sculpt draws original automasking', bpy.context.object.mode == 'SCULPT'
              and state['native_draw_count'] > 0)
        automasking_ui._original_draw = state.pop('native_draw')
        key('ESC')
    elif phase in (36, 38):
        if phase == 36:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            scene.sculptcore_generic_properties = True
            active = bpy.context.tool_settings.sculpt.brush
            active.curve_distance_falloff_preset = 'CUSTOM'
            active.falloff_shape = 'PROJECTED'
            active.stroke_method = 'AIRBRUSH'
        state['panel_tokens'] = tuple(owner.authoring_edit_begin(native_settings=True, undo=False)
                                      for owner in (active, scene))
        bpy.ops.wm.call_panel(name='SCULPTCORE_PT_tools_brush_' + ('falloff' if phase == 36 else 'stroke'))
    elif phase in (37, 39):
        for owner, token in zip((active, scene), state.pop('panel_tokens')):
            check('specialized drawing preserves {} {}'.format(phase, owner.bl_rna.identifier),
                  not owner.authoring_edit_commit(token))
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] /
            ('tests/brush-falloff-ui.png' if phase == 37 else 'tests/brush-stroke-ui.png')))
        key('ESC')


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
        elif radial_test and phase < 15 + 8 * len(radial_cases):
            radial_step((phase - 15) // 8, (phase - 15) % 8)
        elif radial_test and phase < 21 + 8 * len(radial_cases):
            radial_lifetime_step(phase - 15 - 8 * len(radial_cases))
        elif legacy_test and phase < 31:
            radial_legacy_step((phase - 15) // 4, (phase - 15) % 4)
        elif rows_test and phase < 15 + 6 * len(row_cases) + 4 * len(policy_cases):
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                offset = phase - 15
                if offset < 6 * len(row_cases):
                    row_step(offset // 6, offset % 6)
                else:
                    offset -= 6 * len(row_cases)
                    row_policy_step(offset // 4, offset % 4)
        elif rows_ui_test and phase < 30:
            row_ui_step(phase - 15)
        elif stacks_test and phase < 15 + 6 * len(stack_actions):
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                stack_step((phase - 15) // 3, (phase - 15) % 3)
        elif panels_test and phase < 55:
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                panel_step(phase - 15)
        elif (stacks_ui_test and phase < 46) or (placements_test and phase < 38):
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                (placement_step if placements_test else stack_ui_step)(phase - 15)
        elif not variant and phase < 15 + 4 * len(shortcut_cases):
            shortcut_step((phase - 15) // 4, (phase - 15) % 4)
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-custom-undo.checks.json'
            path.write_text(json.dumps(state['checks'], indent=2), encoding='utf-8')
            print('AUTHORING_CUSTOM_UNDO_OK', len(state['checks']), flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .8 if stacks_ui_test or placements_test or panels_test else .5
    except Exception:
        traceback.print_exc()
        print('CUSTOM_UNDO_FAILED_PHASE', state['phase'], flush=True)
        bpy.ops.screen.screenshot(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-authoring-failed.png'))
        bpy.ops.wm.quit_blender()
        return None


if variant == ['placements-reload']:
    from sculptcore_addon.brush_properties import placement
    from sculptcore_addon.brush_properties.registry import Position
    bpy.ops.wm.open_mainfile(filepath=str(Path(__file__).resolve().parents[1] / 'tests/brush-placements.blend'))
    actual = placement.positions(authoring.store(bpy.data.brushes['PlacementPersistenceBrush']),
                                 authoring.registry.get(STRENGTH))
    check('fresh process retains real edited placements', actual == (
        Position('FUTURE_SURFACE', -7), Position('VIEW3D_HEADER', -5),
        Position('BRUSH_SETTINGS', -4), Position('CONTEXT_MENU', -3), Position('AUTOMASKING', -2)))
    check('fresh process does not restore transient search', bpy.context.window_manager.sculptcore_property_search == '')
    print('AUTHORING_CUSTOM_UNDO_OK', len(state['checks']), flush=True)
else:
    bpy.app.timers.register(step, first_interval=1)
