# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Mouse-driven attribute strokes with prepared execution and Blender undo/redo."""
import hashlib
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
from sculptcore_addon import convert, engine, stroke

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
region = next(item for item in area.regions if item.type == 'WINDOW')
cases = list(product(('PAINT', 'DRAW_FACE_SETS'), (False, True)))
case = phase = 0
active = False
calls, statuses, results = [], [], []
draws = [0]
started = time.monotonic()
baseline = final = None
manager = engine.manager()
for name in ('MeshStroke_dabResolved', 'MeshStroke_dabProgramResolved'):
    native = getattr(engine.capi().lib, name)

    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        if active:
            calls.append(dict(api=_name, count=result, center=list(args[2:5])))
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
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        coordinates = data.numpy().copy()
    colors = np.zeros(convert.mesh_vert_num(session.mesh_ptr) * 4, dtype=np.float32)
    groups = np.zeros(convert.mesh_face_num(session.mesh_ptr), dtype=np.int32)
    assert engine.capi().lib.Mesh_readVertFloat4Attr(session.mesh_ptr, convert._SC_COLOR, colors)
    assert engine.capi().lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, groups)
    return coordinates, colors, groups


def equal(a, b):
    return all(np.array_equal(x, y) for x, y in zip(a, b))


def push(index, kind='MOUSEMOVE', value='NOTHING'):
    x, y = ((.40, .45), (.46, .48), (.52, .45), (.56, .48))[index]
    window.event_simulate_input(type=kind, value=value,
                               x=region.x + int(region.width * x), y=region.y + int(region.height * y),
                               time=1000 + index * .2, tablet=True, pressure=(.2, .5, .9, .7)[index],
                               tilt_x=0, tilt_y=0)


def tick():
    global case, phase, active, baseline, final
    try:
        assert time.monotonic() - started < 170, (case, phase)
        tool, cancel = cases[case]
        if phase == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            obj = bpy.context.object
            colors = obj.data.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
            values = np.empty(len(obj.data.vertices) * 4, dtype=np.float32)
            for i in range(len(obj.data.vertices)):
                values[i * 4:i * 4 + 4] = (.1 + .02 * (i % 7), .2, .3, 1)
            colors.data.foreach_set('color', values)
            obj.data.color_attributes.active_color_index = 0
            groups = obj.data.attributes.new('.sculpt_face_set', 'INT', 'FACE')
            groups.data.foreach_set('value', np.ones(len(obj.data.polygons), dtype=np.int32))
            obj.data.use_mirror_x = True
            obj.data.use_mirror_y = obj.data.use_mirror_z = False
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            scene = bpy.context.scene
            scene.sculptcore_dyntopo = False
            scene.sculptcore_cpp_dab_loop = False
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
            brush.mesh_automasking_settings.use_automasking_cavity = False
            brush.mesh_automasking_settings.cavity_factor = 0
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .40), y=region.y + int(region.height * .45) + 100)
        elif phase == 2:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='Attribute gesture baseline')
            baseline = state()
            calls.clear()
            statuses.clear()
            active = True
            push(0, 'LEFTMOUSE', 'PRESS')
        elif phase in (3, 4, 5):
            push(phase - 2)
        elif phase == 6:
            push(3, 'ESC' if cancel else 'LEFTMOUSE', 'PRESS' if cancel else 'RELEASE')
        elif phase == 7:
            expected = 'CANCELLED' if cancel else 'FINISHED'
            assert statuses == [(expected, [expected], False, False)], (statuses, calls)
            assert calls and all(item['count'] >= 0 for item in calls), calls
            assert any(item['count'] > 0 for item in calls), calls
            final = state()
            assert not equal(final, baseline)
            if cancel:
                push(3, 'LEFTMOUSE', 'RELEASE')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo()
        elif phase == 8:
            assert equal(state(), baseline), (case, 'undo')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.redo()
        elif phase == 9:
            assert equal(state(), final), (case, 'redo')
            results.append(dict(tool=tool, cancel=cancel, calls=list(calls)))
            print('PLAN6_ATTRIBUTES_MODAL_CASE_PASS', tool, cancel, flush=True)
            active = False
            case += 1
            if case == len(cases):
                dll = Path(manager.capi.lib._name).resolve()
                result = dict(passed=True, cases=results, dll=str(dll),
                              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
                target = Path(__file__).resolve().parents[1] / 'tests/plan6-attributes-modal.json'
                target.write_text(json.dumps(result, indent=2))
                print('PLAN6_ATTRIBUTES_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('PLAN6_ATTRIBUTES_MODAL_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
