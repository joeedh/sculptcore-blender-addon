# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual generic gestures across host routes, native semantics, cancel and undo/redo."""
import hashlib
import math
import sys
from itertools import product
import json
from pathlib import Path
import time
import traceback

import bmesh
import bpy
from mathutils import Quaternion, Vector
import numpy as np
import sculptcore
from sculptcore_addon import convert, engine, layers, stroke
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve
from sculptcore_addon.brush_properties.native_evaluation import NativeEvaluation
requested_tool = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'DRAW'
semantic_rows = []
view_rows = []
original_evaluate = NativeEvaluation.evaluate

def evaluated(self, samples, radii):
    result = original_evaluate(self, samples, radii)
    if active:
        semantic_rows.append(len(samples))
        pressure = np.asarray(samples)[:, 0]
        expected = .25 * pressure if second_stroke else .45 * pressure ** 2
        np.testing.assert_allclose(result[:, self.identifiers.index(STRENGTH)], expected, atol=2e-6)
        if requested_tool == 'PROGRAM':
            np.testing.assert_allclose(result[:, self.identifiers.index('sculptcore.brush.autosmooth')], .15,
                                       atol=1e-7)
    return result

NativeEvaluation.evaluate = evaluated

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
region = next(item for item in area.regions if item.type == 'WINDOW')
cases = list(product((False, True), (False, True), (False, True)))
case = phase = 0
active = False
second_stroke = False
calls, statuses, results = [], [], []
draws = [0]
started = time.monotonic()
baseline = final = None
manager = engine.manager()
for name in ('GridStroke_dabResolved', 'GridStroke_dabBatchInputs',
             'MeshStroke_dabResolved', 'MeshStroke_dabBatchInputs',
             'GridStroke_dabResolvedImage', 'MeshStroke_dabResolvedImage',
             'GridStroke_dabProgramResolved', 'MeshStroke_dabProgramResolved',
             'GridStroke_dabBatchProgramInputs', 'MeshStroke_dabBatchProgramInputs'):
    native = getattr(engine.capi().lib, name)

    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        if active:
            calls.append(dict(api=_name, count=result))
            if requested_tool == 'VIEW':
                session = engine.sessions[bpy.context.object.name]
                view_rows.append(tuple(session.brush_obj.viewDir.vec))
        return result

    setattr(engine.capi().lib, name, checked)
original_finish = stroke.SCULPTCORE_OT_brush_stroke._finish


def finish(self, context, status):
    result = original_finish(self, context, status)
    if active:
        statuses.append((status, sorted(result), self._engine_dead, self.session.last_stroke_grids))
    return result


stroke.SCULPTCORE_OT_brush_stroke._finish = finish
bpy.types.SpaceView3D.draw_handler_add(lambda: draws.__setitem__(0, draws[0] + 1), (), 'WINDOW', 'POST_PIXEL')


def state():
    session = engine.sessions[bpy.context.object.name]
    convert.ensure_multires_slot(session)
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        coordinates = data.numpy().copy()
    colors = np.zeros(convert.mesh_vert_num(session.mesh_ptr) * 4, dtype=np.float32)
    groups = np.zeros(convert.mesh_face_num(session.mesh_ptr), dtype=np.int32)
    assert engine.capi().lib.Mesh_readVertFloat4Attr(session.mesh_ptr, convert._SC_COLOR, colors)
    assert engine.capi().lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)
    convert.sync_slot_mask(session)
    masks = np.zeros(convert.mesh_vert_num(session.mesh_ptr), dtype=np.float32)
    assert engine.capi().lib.Mesh_readVertFloatAttr(session.mesh_ptr, convert._SC_MASK, masks)
    return coordinates, colors, groups, masks


def equal(a, b):
    return all(np.array_equal(x, y) for x, y in zip(a, b))


def push(index, kind='MOUSEMOVE', value='NOTHING'):
    x, y = ((.40, .45), (.46, .48), (.52, .45), (.56, .48))[index]
    window.event_simulate_input(type=kind, value=value,
                               x=region.x + int(region.width * x), y=region.y + int(region.height * y),
                               time=1000 + index * .2, tablet=True, pressure=(.2, .5, .9, .7)[index],
                               tilt_x=0, tilt_y=0)


def tick():
    global case, phase, active, baseline, final, second_stroke
    try:
        assert time.monotonic() - started < 170, (case, phase)
        grid, batched, cancel = cases[case]
        tool = 'DRAW' if requested_tool in ('PROGRAM', 'VIEW') else requested_tool
        if phase == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            obj = bpy.context.object
            for vertex in obj.data.vertices:
                vertex.co.z = .06 * math.cos(vertex.co.x * 7) * math.cos(vertex.co.y * 9)
            colors = obj.data.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
            values = np.empty(len(obj.data.vertices) * 4, dtype=np.float32)
            for i in range(len(obj.data.vertices)):
                values[i * 4:i * 4 + 4] = (.1 + .02 * (i % 7), .2, .3, 1)
            colors.data.foreach_set('color', values)
            obj.data.color_attributes.active_color_index = 0
            groups = obj.data.attributes.new('.sculpt_face_set', 'INT', 'FACE')
            groups.data.foreach_set('value', np.ones(len(obj.data.polygons), dtype=np.int32))
            if grid:
                obj.modifiers.new('Multires', 'MULTIRES')
                bpy.ops.object.multires_subdivide(modifier='Multires')
            obj.scale = (1.2, .8, 1.5)
            if requested_tool == 'VIEW':
                obj.rotation_euler = (.2, .15, .1)
            obj.data.use_mirror_x = True
            obj.data.use_mirror_y = obj.data.use_mirror_z = False
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            scene = bpy.context.scene
            scene.sculptcore_dyntopo = False
            scene.sculptcore_generic_properties = True
            scene.sculptcore_cpp_dab_loop = batched
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
            draws[0] = 0
        elif phase == 1:
            brush = bpy.context.tool_settings.sculpt.brush
            if not brush or brush.name != 'Draw' or draws[0] < 8:
                area.tag_redraw()
                return .1
            brush.size, brush.strength, brush.spacing = 100, .3, 12
            brush.use_pressure_strength, brush.use_pressure_size = True, False
            brush.use_accumulate = True
            brush.sculpt_brush_type = tool
            brush.color = (.8, .1, .5)
            brush.auto_smooth_factor = 0
            brush.stroke_method = 'SPACE'
            local, parent = authoring.store(brush), authoring.store(bpy.context.scene)
            if requested_tool == 'VIEW':
                for suffix, value in (('automask_view_normal', True), ('cull_backfaces', True),
                                      ('view_normal_limit', 1.2), ('view_normal_falloff', .3)):
                    identifier = 'sculptcore.brush.' + suffix
                    parent.write_value(authoring.registry.get(identifier), value)
                    local.write_mode(identifier, 'ALWAYS')
            local.write_mode(STRENGTH, 'ALWAYS')
            parent.write_value(authoring.registry.get(STRENGTH), .45)
            local.write_stack_inheritance(STRENGTH, False)
            local.write_stack(authoring.registry.get(STRENGTH), (
                DeviceLayer('PRESSURE', curve=ResponseCurve('SQUARE')),))
            local.write_mode(SIZE, 'NEVER')
            brush.use_locked_size = 'VIEW' if grid else 'SCENE'
            brush.unprojected_size = .7
            local.write_stack(authoring.registry.get(SIZE), (
                DeviceLayer('TILT_X', operation='ADD', curve=ResponseCurve('CONSTANT', (.03,))),))
            autosmooth = authoring.registry.get('sculptcore.brush.autosmooth')
            local.write_mode(autosmooth.identifier, 'NEVER')
            local.write_stack(autosmooth, (DeviceLayer('PRESSURE', operation='ADD',
                curve=ResponseCurve('CONSTANT', (.15,))),) if requested_tool == 'PROGRAM' else ())

            if requested_tool == 'CLAY':
                # The plane family's frame policy through the real modal path:
                # an AREA gather held from the first dab, on the mirror too.
                brush.sculpt_plane = 'AREA'
                brush.normal_radius_factor = .5
                brush.use_original_normal = True
            brush.mesh_automasking_settings.use_automasking_cavity = False
            brush.mesh_automasking_settings.cavity_factor = 0
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .40), y=region.y + int(region.height * .45) + 100)
        elif phase == 2:
            session = engine.sessions[bpy.context.object.name]
            convert.ensure_multires_slot(session)
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='Generic gesture baseline')
            baseline = state()
            calls.clear()
            semantic_rows.clear()
            view_rows.clear()
            statuses.clear()
            active = True
            push(0, 'LEFTMOUSE', 'PRESS')
        elif phase in (3, 4, 5):
            push(phase - 2)
        elif phase == 6:
            push(3, 'ESC' if cancel else 'LEFTMOUSE', 'PRESS' if cancel else 'RELEASE')
        elif phase == 7:
            expected = 'CANCELLED' if cancel else 'FINISHED'
            assert statuses == [(expected, [expected], False, grid)], (statuses, calls)
            assert semantic_rows, 'generic native evaluation did not run'
            if requested_tool == 'VIEW':
                assert view_rows and all(abs(row[0]) > .01 and abs(row[1]) > .01 for row in view_rows)
                if not batched:
                    assert min(row[0] for row in view_rows) < 0 < max(row[0] for row in view_rows)
            assert calls and all(item['count'] >= 0 for item in calls), calls
            assert any(item['count'] > 0 for item in calls), calls
            if requested_tool == 'PROGRAM':
                assert all('Program' in item['api'] for item in calls), calls
            final = state()
            assert not equal(final, baseline)
            if cancel:
                push(3, 'LEFTMOUSE', 'RELEASE')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo()
        elif phase == 8:
            current = state()
            if not equal(current, baseline):
                session = engine.sessions[bpy.context.object.name]
                print('GENERIC_UNDO_MISMATCH', [(a.shape, b.shape, float(np.max(abs(a-b))) if a.shape == b.shape else None)
                                            for a, b in zip(current, baseline)],
                      session.grid_cursor, session.grid_generation, session.meshlog_cursor,
                      engine.capi().lib.Multires_editTarget(session.multires_ptr), flush=True)
            assert equal(current, baseline), (case, 'undo')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.redo()
        elif phase == 9:
            assert equal(state(), final), (case, 'redo')
            results.append(dict(tool=tool, grid=grid, batched=batched, cancel=cancel,
                                second_stroke=second_stroke, calls=list(calls), semantic_rows=list(semantic_rows)))
            print('PLAN6_GENERIC_MODAL_CASE_PASS', tool, cancel, flush=True)
            active = False
            if requested_tool == 'DRAW' and not second_stroke:
                # Reuse the live session after undo/redo, changing both independent owners.
                brush = bpy.context.tool_settings.sculpt.brush
                local, parent = authoring.store(brush), authoring.store(bpy.context.scene)
                brush.strength = .25
                parent.write_value(authoring.registry.get(STRENGTH), .8)
                local.write_mode(STRENGTH, 'NEVER')
                local.write_stack_inheritance(STRENGTH, True)
                parent.write_stack(authoring.registry.get(STRENGTH), (DeviceLayer('PRESSURE'),))
                second_stroke = True
                phase = 2
                return .25
            second_stroke = False
            case += 1
            if case == len(cases):
                dll = Path(manager.capi.lib._name).resolve()
                result = dict(passed=True, cases=results, dll=str(dll),
                              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
                target = Path(__file__).resolve().parents[1] / ('tests/plan6-generic-' + requested_tool.lower() + '-modal.json')
                target.write_text(json.dumps(result, indent=2))
                print('PLAN6_GENERIC_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('PLAN6_GENERIC_MODAL_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
