# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real headed strokes: mesh/grid, Python/batch, queued/delayed input delivery."""
import bpy
import json
from mathutils import Quaternion, Vector
from pathlib import Path
import time
import traceback
import sys

from sculptcore_addon import engine, stroke

autosmooth = '--autosmooth' in sys.argv
nonaccum = '--nonaccum' in sys.argv
mask_mode = '--mask' in sys.argv
cavity_mode = '--cavity' in sys.argv
prepared_calls = []
begin_modes = []
original_begin = stroke.stroke_begin


def begin(session, **kwargs):
    if active and nonaccum:
        assert kwargs['accumulate'] is False, kwargs
        begin_modes.append(kwargs['accumulate'])
    return original_begin(session, **kwargs)


stroke.stroke_begin = begin
if autosmooth or nonaccum or mask_mode or cavity_mode:
    lib = engine.capi().lib
    for domain_name in ('Mesh', 'Grid'):
        suffix = 'dabProgramResolved' if autosmooth else 'dabResolved'
        name = domain_name + 'Stroke_' + suffix
        native = getattr(lib, name)

        def prepared(*args, _native=native, _name=name):
            result = _native(*args)
            if active:
                prepared_calls.append((_name, result))
            return result

        setattr(lib, name, prepared)
        suffix = 'dabBatchProgramInputs' if autosmooth else 'dabBatchInputs'
        name = domain_name + 'Stroke_' + suffix
        native = getattr(lib, name)

        def prepared_batch(*args, _native=native, _name=name):
            assert args[-1] == 2
            result = _native(*args[:-1], 1)  # Require prepared execution; reject fallback.
            if active:
                prepared_calls.append((_name, result))
            return result

        setattr(lib, name, prepared_batch)

bpy.context.preferences.view.show_splash = False
window = bpy.context.window
area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
region = next(region for region in area.regions if region.type == 'WINDOW')
context = dict(window=window, area=area, region=region)
cases = [(grid, batch, queued) for grid in (False, True) for batch in (False, True) for queued in (False, True)]
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
                  tilt_x=(-1, -.5, 0, .5, 1)[index], alt=mask_mode)
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


def mask_values():
    import numpy as np
    from sculptcore_addon.convert import _SC_MASK

    session = engine.sessions[bpy.context.object.name]
    lib = engine.capi().lib
    if session.multires_ptr:
        level = session.multires_active_level
        count = lib.Multires_levelVertCount(session.multires_ptr, level)
        values = np.empty(count, dtype=np.float32)
        assert lib.Multires_readDomainMask(session.multires_ptr, level, values, count)
    else:
        values = np.empty(session.verts_num, dtype=np.float32)
        assert lib.Mesh_readVertFloatAttr(session.mesh_ptr, _SC_MASK, values)
    return values


def tick():
    global case, phase, move, active
    try:
        assert time.monotonic() - started < 170, (case, phase)
        grid, use_batch, queued = cases[case]
        if phase == 0:
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
            brush.use_accumulate = not nonaccum
            brush.auto_smooth_factor = .25 if autosmooth else 0
            brush.mesh_automasking_settings.use_automasking_cavity = cavity_mode
            brush.mesh_automasking_settings.use_automasking_cavity_inverted = False
            if cavity_mode:
                brush.mesh_automasking_settings.cavity_factor = 0
                brush.mesh_automasking_settings.use_automasking_custom_cavity_curve = False
            brush.stroke_method = 'SPACE'
            # Warm the viewport focus without placing a dab on the scored path.
            x, y = points()[0]
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value, x=x, y=y + 100, alt=mask_mode)
        elif phase == 2:
            records.clear(); inputs.clear(); statuses.clear(); batches.clear()
            prepared_calls.clear()
            begin_modes.clear()
            active = True
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
            if nonaccum:
                assert begin_modes == [False], begin_modes
            if autosmooth or nonaccum or mask_mode or cavity_mode:
                assert prepared_calls and all(result >= 0 for _, result in prepared_calls), prepared_calls
                expected = ('Grid' if grid else 'Mesh') + 'Stroke_'
                assert all(name.startswith(expected) for name, _ in prepared_calls)
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
            if mask_mode:
                assert float(mask_values().max()) > 1e-4
                assert height() < 1e-6, height()
            else:
                assert height() > 1e-4, height()
            if results:
                reference = results[0]['samples']
                assert len(reference) == len(records), (len(reference), len(records))
                for a, b in zip(reference, records):
                    assert a == b, (a, b)
            results.append(dict(grid=grid, batch=use_batch, queued=queued,
                                samples=list(records), source_inputs=list(inputs), height=height(), batches=list(batches),
                                prepared_calls=list(prepared_calls), autosmooth=autosmooth, nonaccum=nonaccum,
                                accumulate_modes=list(begin_modes)))
            if mask_mode:
                results[-1]['mask_max'] = float(mask_values().max())
                results[-1]['mask_mode'] = True
            print('PLAN3_MODAL_CASE_PASS', grid, use_batch, queued, len(records), flush=True)
            active = False
            case += 1
            if case == len(cases):
                filename = 'plan6-bsmooth-modal-samples.json' if autosmooth else 'plan3-modal-samples.json'
                if nonaccum:
                    filename = 'plan6-nonaccum-' + ('auto' if autosmooth else 'draw') + '-samples.json'
                if mask_mode:
                    filename = 'plan6-mask-modal-samples.json'
                if cavity_mode:
                    filename = 'plan6-automask-modal-samples.json'
                destination = Path(__file__).resolve().parents[1] / 'tests' / filename
                destination.write_text(json.dumps(results, indent=2))
                print('PLAN3_MODAL_INPUTS_PASS', flush=True)
                if autosmooth:
                    print('PLAN6_BSMOOTH_MODAL_PASS', flush=True)
                if nonaccum:
                    print('PLAN6_NONACCUM_MODAL_PASS', flush=True)
                if mask_mode:
                    print('PLAN6_MASK_MODAL_PASS', flush=True)
                if cavity_mode:
                    print('PLAN6_AUTOMASK_MODAL_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
            phase = -1
        phase += 1
        return .2
    except Exception:
        traceback.print_exc()
        print('PLAN3_MODAL_INPUTS_FAIL', case, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
