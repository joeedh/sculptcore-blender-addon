# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Mouse-driven dyntopo strokes, cadence, mirror images and Blender undo/redo."""
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
cases = list(product((False, True), repeat=2))
case = phase = 0
active = False
calls, statuses, results = [], [], []
draws = [0]
started = time.monotonic()
baseline = final = None
manager = engine.manager()
native = engine.capi().lib.MeshStroke_dabProgramResolvedDyntopo


def checked(*args):
    result = native(*args)
    if active:
        calls.append(dict(remesh=bool(args[-2]), count=result, center=list(args[2:5])))
    return result


engine.capi().lib.MeshStroke_dabProgramResolvedDyntopo = checked
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
        return data.numpy().copy(), convert._mesh_counts(session.mesh_ptr)[:3]


def equal(a, b):
    return np.array_equal(a[0], b[0]) and a[1] == b[1]


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
        nonaccum, cancel = cases[case]
        if phase == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            obj = bpy.context.object
            edit = bmesh.new()
            edit.from_mesh(obj.data)
            bmesh.ops.triangulate(edit, faces=list(edit.faces))
            edit.to_mesh(obj.data)
            edit.free()
            obj.data.use_mirror_x = True
            obj.data.use_mirror_y = obj.data.use_mirror_z = False
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            scene = bpy.context.scene
            scene.sculptcore_dyntopo = True
            scene.sculptcore_dyntopo_spacing = .5
            scene.sculptcore_dyntopo_max_rounds = 4
            scene.sculptcore_dyntopo_split_budget = 40
            paint = bpy.context.tool_settings.sculpt
            paint.detail_type_method = 'CONSTANT'
            paint.constant_detail_resolution = 12.5
            paint.detail_refine_method = 'SUBDIVIDE'
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
            brush.use_accumulate = not nonaccum
            brush.auto_smooth_factor = .15
            brush.stroke_method = 'SPACE'
            brush.mesh_automasking_settings.use_automasking_cavity = nonaccum
            brush.mesh_automasking_settings.cavity_factor = 0
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .40), y=region.y + int(region.height * .45) + 100)
        elif phase == 2:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='Dyntopo gesture baseline')
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
            assert any(not item['remesh'] for item in calls), calls
            final = state()
            assert final[1][0] > baseline[1][0]
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
            results.append(dict(nonaccum=nonaccum, cancel=cancel, calls=list(calls),
                                vertices=[baseline[1][0], final[1][0]]))
            print('PLAN6_DYNTOPO_MODAL_CASE_PASS', nonaccum, cancel, flush=True)
            active = False
            case += 1
            if case == len(cases):
                dll = Path(manager.capi.lib._name).resolve()
                result = dict(passed=True, cases=results, dll=str(dll),
                              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
                target = Path(__file__).resolve().parents[1] / 'tests/plan6-dyntopo-modal.json'
                target.write_text(json.dumps(result, indent=2))
                print('PLAN6_DYNTOPO_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('PLAN6_DYNTOPO_MODAL_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
