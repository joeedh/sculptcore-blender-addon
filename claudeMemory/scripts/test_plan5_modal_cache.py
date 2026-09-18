# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real headed strokes: mesh/grid, Python/batch, queued/delayed input delivery."""
import bpy
import json
from mathutils import Quaternion, Vector
from pathlib import Path
import time
import traceback

from sculptcore_addon import engine, stroke
from sculptcore_addon.brush_properties import sampling

bpy.context.preferences.view.show_splash = False
window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
region = next(region for region in area.regions if region.type == 'WINDOW')
context = dict(window=window, area=area, region=region)
cases = [(False, True, False)] * 5
records, inputs, statuses, batches = [], [], [], []
draws = [0]
active = False
case = 0
phase = 0
move = 0
started = time.monotonic()
results = []

cls = stroke.SCULPTCORE_OT_brush_stroke
original_spaced, original_batch, original_read, original_finish = cls._apply_spaced_dab, cls._apply_batch, cls._read_input, cls._finish


def record(point, sample):
    records.append((list(point), list(sample.channels), sample.time, sample.invert))


def spaced(self, context, point, sample):
    if active:
        record(point, sample)
    return original_spaced(self, context, point, sample)


def batch(self, context, points):
    if active:
        batches.append(len(points))
        for point, sample in points:
            record(point, sample)
    return original_batch(self, context, points)


def read(self, event):
    sample = original_read(self, event)
    if active and sample is not None:
        inputs.append((event.type, sample.time, sample.pressure, sample.tilt_x, sample.tilt_y, sample.speed))
    return sample


def finish(self, context, status):
    result = original_finish(self, context, status)
    if active:
        statuses.append((status, sorted(result), self._engine_dead, self.session.last_stroke_grids))
    return result


cls._apply_spaced_dab, cls._apply_batch, cls._read_input, cls._finish = spaced, batch, read, finish
bpy.types.SpaceView3D.draw_handler_add(lambda: draws.__setitem__(0, draws[0] + 1), (), 'WINDOW', 'POST_PIXEL')


def points():
    return [(region.x + int(region.width * x), region.y + int(region.height * y))
            for x, y in ((.35, .45), (.45, .45), (.55, .48), (.65, .45), (.65, .45))]


def push(index, kind='MOUSEMOVE', value='NOTHING'):
    x, y = points()[index]
    kwargs = dict(time=1000.0 + .1 * index, tablet=True, pressure=(.2, .4, .7, 1.0, 1.0)[index],
                  tilt_x=(-1, -.5, 0, .5, 1)[index])
    if index != 2:
        kwargs['tilt_y'] = 0
    window.event_simulate_input(type=kind, value=value, x=x, y=y, **kwargs)


def height():
    session = engine.sessions[bpy.context.object.name]
    positions = []
    for x in (-.7, -.4, 0, .4, .7):
        for y in (-.3, 0, .3):
            hit = stroke.raycast(session, (x, y, 3), (0, 0, -1))
            if hit:
                positions.append(float(hit[0][2]))
    return max(abs(z) for z in positions)


before, clock = [], [0]


def counters():
    memo = engine.sessions[bpy.context.object.name].curve_cache
    uploads = memo.get('pressure_uploads')
    return (sampling.cache.bakes, uploads.uploads if uploads else 0,
            memo.get('table_uploads', 0), memo.get('overlap_bakes', 0))


def tick():
    global case, phase, move, active
    try:
        assert time.monotonic() - started < 170, (case, phase)
        grid, use_batch, queued = cases[case]
        if phase == 0 and case == 0:
            active = False
            if bpy.context.object and bpy.context.object.mode == 'CUSTOM':
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=32, y_subdivisions=32, size=4)
            obj = bpy.context.object
            obj.data.use_mirror_x = obj.data.use_mirror_y = obj.data.use_mirror_z = False
            if grid:
                obj.modifiers.new('Multires', 'MULTIRES')
                bpy.ops.object.multires_subdivide(modifier='Multires')
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance = 4
            view.view_perspective = 'ORTHO'
            bpy.context.scene.sculptcore_cpp_dab_loop = use_batch
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
            draws[0] = 0
        elif phase == 1:
            brush = bpy.context.tool_settings.sculpt.brush
            if not brush or brush.name != 'Draw' or draws[0] < 8:
                area.tag_redraw()
                return .1
            brush.size = 100
            brush.strength = .3
            brush.spacing = 12
            brush.use_pressure_strength = True
            brush.use_pressure_size = False
            brush.use_accumulate = True
            brush.auto_smooth_factor = 0
            brush.stroke_method = 'SPACE'
            if case == 0:
                brush.curve_distance_falloff_preset = 'CUSTOM'
                brush.use_space_attenuation = True
                brush.mesh_automasking_settings.use_automasking_cavity = True
                brush.mesh_automasking_settings.use_automasking_custom_cavity_curve = True
                brush.mesh_automasking_settings.cavity_curve.curves[0].points[-1].location.y = .81
                brush.curve_distance_falloff.curves[0].points[-1].location.y = .13
            if case:
                phase += 1
                return .2
            # Warm the viewport focus without placing a dab on the scored path.
            x, y = points()[0]
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value, x=x, y=y + 100)
        elif phase == 2:
            records.clear(); inputs.clear(); statuses.clear(); batches.clear()
            active = True
            memo = engine.sessions[bpy.context.object.name].curve_cache
            if case == 0:
                sampling.clear()
                memo.clear()
            elif case == 2:
                bpy.context.tool_settings.sculpt.brush.curve_strength.curves[0].points[-1].location.y = .61
            elif case == 3:
                engine.sessions[bpy.context.object.name].brush_obj.clearPropDynamics(0)
            elif case == 4:
                sampling.clear()
            before[:] = counters()
            clock[0] = time.perf_counter()
            push(0, 'LEFTMOUSE', 'PRESS')
            move = 1
        elif phase == 3:
            push(move)
            move += 1
            if queued:
                while move < 4:
                    push(move)
                    move += 1
            if move < 4:
                return .3
        elif phase == 4:
            push(4, 'LEFTMOUSE', 'RELEASE')
        elif phase == 5:
            assert statuses == [('FINISHED', ['FINISHED'], False, grid)], statuses
            assert len(records) > 10, records
            assert len(inputs) == 5, inputs
            assert inputs[0][1] == 1000.0 and abs(inputs[0][2] - .2) < 1e-6, inputs
            assert any(row[4] is None for row in inputs)
            assert any(row[1][2] is None for row in records)
            assert all(row[1][3] is not None for row in records)
            assert len({round(row[1][0], 5) for row in records}) > 8
            if queued:
                assert any(row[0] == 'INBETWEEN_MOUSEMOVE' for row in inputs), inputs
            if use_batch:
                assert max(batches) > 3, batches
            assert height() > 1e-4, height()
            delta = [a - b for a, b in zip(counters(), before)]
            expected = [(3, 2, 2, 1), (0, 0, 0, 0), (1, 2, 0, 0), (0, 2, 0, 0), (3, 2, 2, 1)][case]
            assert tuple(delta) == expected, (case, delta, expected)
            print('PLAN5_WARM_COUNTS', case, delta, flush=True)
            results.append(dict(grid=grid, batch=use_batch, queued=queued,
                                samples=list(records), height=height(), counters=delta, seconds=time.perf_counter() - clock[0]))
            print('PLAN5_MODAL_CASE_PASS', grid, use_batch, queued, len(records), flush=True)
            active = False
            case += 1
            if case == len(cases):
                destination = Path(__file__).resolve().parents[1] / 'tests/plan5-modal-cache.checks.json'
                destination.write_text(json.dumps(results, indent=2))
                print('PLAN5_MODAL_CACHE_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .2
    except Exception:
        traceback.print_exc()
        print('PLAN5_MODAL_CACHE_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
