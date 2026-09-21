# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shift-smooth strokes through the real modal path: the Shift-smooth settings
pick the kernel (BSMOOTH / FEATURE_ALIGN), the strength ceiling, the kernel
scalars and whether dyntopo runs; a feature-align (Slide Relax) brush stroke
publishes its own rake. Every stroke must move geometry and undo cleanly."""
import hashlib
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
from sculptcore_addon.brush_properties import authoring, shift_smooth
from sculptcore_addon.brush_properties.stroke_runtime import StrokeRuntime

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
region = next(item for item in area.regions if item.type == 'WINDOW')
# (shift, feature_align, dyntopo): four Shift-smooth strokes over a Draw brush,
# then a plain Slide Relax (TOPOLOGY -> FEATURE_ALIGN) stroke.
cases = [(True, False, False), (True, True, False), (True, False, True), (True, True, True), (False, False, False)]
case = phase = 0
active = False
calls, statuses, results, publishes = [], [], [], []
draws = [0]
started = time.monotonic()
baseline = final = None
manager = engine.manager()
native = engine.capi().lib.MeshStroke_dabProgramResolvedDyntopo


def checked(*args):
    result = native(*args)
    if active:
        calls.append(dict(remesh=bool(args[-2]), count=result))
    return result


engine.capi().lib.MeshStroke_dabProgramResolvedDyntopo = checked
original_publish = StrokeRuntime.publish


def publish(self, payload, **kw):
    if active:
        publishes.append((dict(payload[1]), kw.get('strength_override')))
    return original_publish(self, payload, **kw)


StrokeRuntime.publish = publish
original_finish = stroke.SCULPTCORE_OT_brush_stroke._finish


def finish(self, context, status):
    result = original_finish(self, context, status)
    if active:
        kernel_name = next(name for name, value in manager.get("sculptcore::brush::SculptBrushes").items.items()
                           if int(value) == self.kernel)
        statuses.append(dict(status=status, result=sorted(result), dead=self._engine_dead, kernel=kernel_name,
                             shift=self._shift_smooth, ceiling=self._smooth_strength_max,
                             extras=self._toggle_extras, dyntopo=self._dyntopo is not None))
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


def close(extras, expected):
    """Name-for-name equal (uniform, value) pairs; the values are float32."""
    extras, expected = tuple(extras), tuple(expected)
    return (len(extras) == len(expected)
            and all(a[0] == b[0] and abs(a[1] - b[1]) < 1e-6 for a, b in zip(extras, expected)))


def push(index, kind='MOUSEMOVE', value='NOTHING', shift=False):
    x, y = ((.40, .45), (.46, .48), (.52, .45), (.56, .48))[index]
    window.event_simulate_input(type=kind, value=value, shift=shift,
                               x=region.x + int(region.width * x), y=region.y + int(region.height * y),
                               time=1000 + index * .2, tablet=True, pressure=(.2, .5, .9, .7)[index],
                               tilt_x=0, tilt_y=0)


def tick():
    global case, phase, active, baseline, final
    try:
        assert time.monotonic() - started < 170, (case, phase)
        shift, feature_align, dyntopo = cases[case]
        if phase == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            obj = bpy.context.object
            for vertex in obj.data.vertices:
                vertex.co.z = .05 * ((vertex.index * 7919) % 13) / 13.0
            edit = bmesh.new()
            edit.from_mesh(obj.data)
            bmesh.ops.triangulate(edit, faces=list(edit.faces))
            edit.to_mesh(obj.data)
            edit.free()
            obj.data.use_mirror_x = obj.data.use_mirror_y = obj.data.use_mirror_z = False
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            scene = bpy.context.scene
            scene.sculptcore_generic_properties = True
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
            brush.use_pressure_strength, brush.use_pressure_size = False, False
            brush.use_accumulate = True
            brush.auto_smooth_factor = 0
            brush.stroke_method = 'SPACE'
            brush.sculpt_brush_type = 'DRAW' if shift else 'TOPOLOGY'
            brush.mesh_automasking_settings.use_automasking_cavity = False
            parent = authoring.store(bpy.context.scene)
            parent.write_value(authoring.registry.get(shift_smooth.STRENGTH), 2.5)
            parent.write_value(authoring.registry.get(shift_smooth.FEATURE_ALIGN), feature_align)
            parent.write_value(authoring.registry.get(shift_smooth.DYNTOPO), dyntopo)
            parent.write_value(authoring.registry.get(shift_smooth.RAKE_SHIFT), .35)
            parent.write_value(authoring.registry.get(shift_smooth.PROJECTION), .25)
            authoring.store(brush).write_value(authoring.registry.get(shift_smooth.RAKE), .65)
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .40), y=region.y + int(region.height * .45) + 100)
        elif phase == 2:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='Shift-smooth gesture baseline')
            baseline = state()
            calls.clear()
            statuses.clear()
            publishes.clear()
            active = True
            push(0, 'LEFTMOUSE', 'PRESS', shift=shift)
        elif phase in (3, 4, 5):
            push(phase - 2, shift=shift)
        elif phase == 6:
            push(3, 'LEFTMOUSE', 'RELEASE', shift=shift)
        elif phase == 7:
            assert len(statuses) == 1, statuses
            status = statuses[0]
            assert status['status'] == 'FINISHED' and not status['dead'], status
            if shift:
                expected_kernel = 'FEATURE_ALIGN' if feature_align else 'BSMOOTH'
                expected_extras = ((('rake', .35), ('projection', .25)) if feature_align
                                   else (('projection', .25),))
                assert status['kernel'] == expected_kernel, status
                assert status['shift'] and status['ceiling'] == shift_smooth.STRENGTH_MAX, status
                assert close(status['extras'], expected_extras), status
                assert status['dyntopo'] == dyntopo, status
                # Strength 2.5 -> ten full passes per dab, none clamped to 1.0.
                overrides = [item[1] for item in publishes]
                assert overrides and max(overrides) <= 1.0 and overrides.count(1.0) >= 10, overrides[:16]
                assert all(close(item[0].items(), expected_extras) for item in publishes), publishes[:3]
            else:
                assert status['kernel'] == 'FEATURE_ALIGN' and not status['shift'], status
                assert status['ceiling'] == 1.0 and status['extras'] is None, status
                assert status['dyntopo'], status  # the brush's own dyntopo path
                assert all(abs(item[0]['rake'] - .65) < 1e-6 for item in publishes), publishes[:3]
                assert all(item[1] is not None for item in publishes), publishes[:3]
            final = state()
            assert not np.array_equal(final[0], baseline[0]), 'stroke moved nothing'
            if status['dyntopo']:
                assert calls and any(item['count'] > 0 for item in calls), calls
                assert any(item['remesh'] for item in calls), calls
                assert final[1][0] > baseline[1][0], (final[1], baseline[1])
            else:
                assert not calls, calls
                assert final[1] == baseline[1], (final[1], baseline[1])
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo()
        elif phase == 8:
            assert equal(state(), baseline), (case, 'undo')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.redo()
        elif phase == 9:
            assert equal(state(), final), (case, 'redo')
            results.append(dict(shift=shift, feature_align=feature_align, dyntopo=dyntopo,
                                status=statuses[0], passes=len(publishes),
                                vertices=[baseline[1][0], final[1][0]]))
            print('SHIFT_SMOOTH_CASE_PASS', shift, feature_align, dyntopo, flush=True)
            active = False
            case += 1
            if case == len(cases):
                dll = Path(manager.capi.lib._name).resolve()
                result = dict(passed=True, cases=results, dll=str(dll),
                              sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
                target = Path(__file__).resolve().parents[1] / 'tests/shift-smooth-modal.json'
                target.write_text(json.dumps(result, indent=2))
                print('SHIFT_SMOOTH_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('SHIFT_SMOOTH_MODAL_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
