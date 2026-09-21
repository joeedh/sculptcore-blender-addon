# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shift-smooth keeps respecting a face-set boundary after an edit-mode round
trip and after undo. A grid with a z cliff along a face-set boundary, no UV
layer (so nothing but the face-set write itself dirties the boundary overlay);
a Shift-smooth stroke down the boundary column must find it classified
(BC_POLYGROUP) on the fresh enter, after Tab in/out of edit mode and after an
undo, and must move the column less than an unconstrained smooth would.
Regression gate for the group-column dirtying in Mesh_writeFaceIntAttr and the
meshlog's face-row undo (engine)."""
import time
import traceback

import bpy
from mathutils import Quaternion, Vector
import numpy as np
import sculptcore
from sculptcore_addon import convert, engine

window = bpy.context.window
area = next(item for item in window.screen.areas if item.type == 'VIEW_3D')
region = next(item for item in area.regions if item.type == 'WINDOW')
draws = [0]
bpy.types.SpaceView3D.draw_handler_add(lambda: draws.__setitem__(0, draws[0] + 1), (), 'WINDOW', 'POST_PIXEL')
manager = engine.manager()
started = time.monotonic()
phase = 0
steps = ['fresh', 'after-edit-roundtrip', 'after-undo']
step = 0
results = {}
UNCONSTRAINED_Z = 0.095  # what a plain smooth does to the column (measured with the boundary unclassified)


def positions():
    session = engine.sessions[bpy.context.object.name]
    with sculptcore.construct_from_items(manager, manager.get('float'), []) as data:
        session.mesh().dumpVertCo(data)
        return data.numpy().copy().reshape(-1, 4)[:, 1:4]  # (index, x, y, z) rows


column = None


def boundary_report(tag):
    global column
    pos = positions()
    if column is None:
        column = np.abs(pos[:, 0]) < 1e-4  # the x=0 column of the pristine grid, fixed by index from then on
    zmax = float(np.max(np.abs(pos[column, 2])))
    xmax = float(np.max(np.abs(pos[column, 0])))
    print('FSET_SMOOTH', tag, 'boundary column |z| max =', zmax, '|x| max =', xmax, 'verts', int(column.sum()),
          flush=True)
    results[tag] = zmax


def classes():
    s = engine.sessions[bpy.context.object.name]
    n = convert.mesh_vert_num(s.mesh_ptr)
    out = np.zeros(n, dtype=np.int32)
    ok = engine.capi().lib.Mesh_readAttr(s.mesh_ptr, 1, b".boundary.vert.class", 32, out.ctypes.data)
    return ok, int(np.count_nonzero(out & 8))


def cliff():
    ob = bpy.context.object
    for vertex in ob.data.vertices:
        vertex.co.z = 0.3 if vertex.co.x > 1e-4 else 0.0


def push(index, kind='MOUSEMOVE', value='NOTHING'):
    # A stroke straight down the x=0 boundary column (ortho top view, centred).
    y = (.35, .42, .5, .58)[index]
    window.event_simulate_input(type=kind, value=value, shift=True,
                               x=region.x + int(region.width * .5), y=region.y + int(region.height * y),
                               time=1000 + index * .2, tablet=True, pressure=.8, tilt_x=0, tilt_y=0)


def tick():
    global phase, step
    try:
        assert time.monotonic() - started < 170, (step, phase)
        if phase == 0:
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=4)
            ob = bpy.context.object
            fs = ob.data.attributes.new('.sculpt_face_set', 'INT', 'FACE')
            fs.data.foreach_set('value', np.array([1 if p.center.x < 0 else 2 for p in ob.data.polygons],
                                                  dtype=np.int32))
            while ob.data.uv_layers:
                ob.data.uv_layers.remove(ob.data.uv_layers[0])
            cliff()
            ob.data.use_mirror_x = ob.data.use_mirror_y = ob.data.use_mirror_z = False
            view = area.spaces.active.region_3d
            view.view_rotation = Quaternion((1, 0, 0, 0))
            view.view_location = Vector((0, 0, 0))
            view.view_distance, view.view_perspective = 4, 'ORTHO'
            scene = bpy.context.scene
            scene.sculptcore_generic_properties = True
            scene.sculptcore_dyntopo = False
            bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
            draws[0] = 0
        elif phase == 1:
            brush = bpy.context.tool_settings.sculpt.brush
            if not brush or brush.name != 'Draw' or draws[0] < 8:
                area.tag_redraw()
                return .1
            brush.size, brush.strength, brush.spacing = 120, .5, 10
            brush.use_pressure_strength = brush.use_pressure_size = False
            brush.stroke_method = 'SPACE'
            for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
                window.event_simulate(type=kind, value=value,
                    x=region.x + int(region.width * .1), y=region.y + int(region.height * .9))
        elif phase == 2:
            print('FSET_SMOOTH', steps[step], 'classes', classes(), flush=True)
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.ed.undo_push(message='fset probe ' + steps[step])
            boundary_report(steps[step] + ':before')
            push(0, 'LEFTMOUSE', 'PRESS')
        elif phase in (3, 4):
            push(phase - 2)
        elif phase == 5:
            push(3, 'LEFTMOUSE', 'RELEASE')
        elif phase == 6:
            boundary_report(steps[step] + ':after')
            ok, polygroup = classes()
            print('FSET_SMOOTH', steps[step], 'classes after stroke', (ok, polygroup), flush=True)
            assert ok and polygroup == int(column.sum()), (steps[step], ok, polygroup)
            assert results[steps[step] + ':after'] < UNCONSTRAINED_Z * .8, (steps[step], results)
            step += 1
            if step == 1:
                # The user's flow: Tab into edit mode from the mode and back, re-enter.
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.object.mode_set(mode='OBJECT')
                cliff()
                bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
                phase = 1
            elif step == 2:
                # Undo the stroke just made, then stroke again on the restored cliff.
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.ed.undo()
                phase = 1
            else:
                print('FSET_SMOOTH_RESULTS', results, flush=True)
                print('FSET_BOUNDARY_SMOOTH_PASS', flush=True)
                bpy.ops.wm.quit_blender()
                return None
        phase += 1
        return .25
    except Exception:
        traceback.print_exc()
        print('FSET_SMOOTH_FAIL', step, phase, flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=1)
