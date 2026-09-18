# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Anchored/Drag Dot gestures, commit/cancel and Blender undo on mesh/multires."""
import hashlib
from itertools import product
import json
from pathlib import Path
import time
import traceback

import bpy
from mathutils import Quaternion, Vector
import numpy as np
import sculptcore
from sculptcore_addon import engine, stroke

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
region = next(item for item in area.regions if item.type == 'WINDOW')
cases = list(product((False, True), ('ANCHORED', 'DRAG_DOT'), (False, True)))
case = phase = 0
active = False
calls, statuses, results = [], [], []
draws = [0]
started = time.monotonic()
baseline = final = None
manager = engine.manager()
lib = engine.capi().lib
for suffix in ('dabResolved', 'dabResolvedImage', 'dabProgramResolved', 'dabProgramResolvedImage'):
    name = 'MeshStroke_' + suffix
    native = getattr(lib, name)

    def checked(*args, _native=native, _name=name):
        result = _native(*args)
        if active:
            calls.append((_name, result))
        return result

    setattr(lib, name, checked)

original_finish = stroke.SCULPTCORE_OT_brush_stroke._finish_preview


def finish(self, context, commit):
    result = original_finish(self, context, commit)
    if active:
        statuses.append((commit, sorted(result), self._engine_dead, self.session.last_stroke_grids))
    return result


stroke.SCULPTCORE_OT_brush_stroke._finish_preview = finish


bpy.types.SpaceView3D.draw_handler_add(lambda: draws.__setitem__(0, draws[0] + 1), (), 'WINDOW', 'POST_PIXEL')


def positions():
    session = engine.sessions[bpy.context.object.name]
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().reshape(-1, 4)[:, 1:].copy()


def push(index, kind='MOUSEMOVE', value='NOTHING'):
    x, y = ((.40, .45), (.52, .48), (.60, .45), (.56, .48))[index]
    window.event_simulate_input(type=kind, value=value,
                                x=region.x + int(region.width * x), y=region.y + int(region.height * y),
                                time=1000 + index * .2, tablet=True, pressure=(.2, .5, .9, .7)[index],
                                tilt_x=0, tilt_y=0)


def tick():
    global case, phase, active, baseline, final
    try:
        assert time.monotonic() - started < 170, (case, phase)
        multires, method, cancel = cases[case]
        if phase == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            obj = bpy.context.object
            obj.data.use_mirror_x = True
            obj.data.use_mirror_y = obj.data.use_mirror_z = False
            if multires:
                obj.modifiers.new('Multires', 'MULTIRES')
                bpy.ops.object.multires_subdivide(modifier='Multires')
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
            draws[0] = 0
        elif phase == 1:
            brush = bpy.context.tool_settings.sculpt.brush
            if not brush or brush.name != 'Draw' or draws[0] < 8:
                area.tag_redraw()
                return .1
            brush.size, brush.strength = 100, .3
            brush.use_pressure_strength, brush.use_pressure_size = True, False
            brush.use_accumulate = False
            brush.auto_smooth_factor = .15
            brush.stroke_method = method
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .40), y=region.y + int(region.height * .45) + 100)
        elif phase == 2:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='Preview gesture baseline')
            baseline = positions()
            calls.clear()
            statuses.clear()
            active = True
            push(0, 'LEFTMOUSE', 'PRESS')
        elif phase in (3, 4, 5):
            push(phase - 2)
        elif phase == 6:
            push(3, 'ESC' if cancel else 'LEFTMOUSE', 'PRESS' if cancel else 'RELEASE')
        elif phase == 7:
            assert statuses == [(not cancel, ['CANCELLED' if cancel else 'FINISHED'], False, False)], (statuses, calls)
            assert calls and all(status >= 0 for _, status in calls), calls
            assert any(name.endswith('ResolvedImage') for name, _ in calls), calls
            final = positions()
            if cancel:
                assert np.allclose(final, baseline, rtol=0, atol=2e-6)
                push(3, 'LEFTMOUSE', 'RELEASE')
            else:
                assert np.max(abs(final - baseline)) > 1e-5
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.ed.undo()
        elif phase == 8:
            if not cancel:
                assert np.allclose(positions(), baseline, rtol=0, atol=2e-6)
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.ed.redo()
        elif phase == 9:
            if not cancel:
                assert np.allclose(positions(), final, rtol=0, atol=2e-6)
            results.append(dict(multires=multires, method=method, cancel=cancel, calls=list(calls)))
            print('PLAN6_PREVIEW_MODAL_CASE_PASS', multires, method, cancel, flush=True)
            active = False
            case += 1
            if case == len(cases):
                dll = Path(manager.capi.lib._name).resolve()
                result = dict(passed=True, cases=results, dll=str(dll),
                              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
                (Path(__file__).resolve().parents[1] / 'tests/plan6-preview-modal.json').write_text(json.dumps(result, indent=2))
                print('PLAN6_PREVIEW_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('PLAN6_PREVIEW_MODAL_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
