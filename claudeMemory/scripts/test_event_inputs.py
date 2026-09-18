# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headed acquisition metadata and shared queue conversion regression."""
import bpy
import math
import time
import traceback

received = []
started = time.monotonic()


class InputProbe(bpy.types.Operator):
    bl_idname = 'wm.sculptcore_input_probe'
    bl_label = "Input Probe"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
            received.append((event.type, event.has_time, event.time, event.is_input_sample,
                             event.has_pressure, event.pressure, event.has_tilt_x, event.has_tilt_y,
                             tuple(event.tilt), event.is_tablet))
        if event.type == 'ESC':
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


bpy.utils.register_class(InputProbe)
window = bpy.context.window
bpy.context.preferences.view.show_splash = False
phase = 0
expected_time = 12345678.123456789


def tick():
    global phase
    try:
        assert time.monotonic() - started < 30
        if phase == 0:
            bpy.ops.wm.sculptcore_input_probe('INVOKE_DEFAULT')
        elif phase == 1:
            event = window.event_simulate_input(type='MOUSEMOVE', value='NOTHING', x=450, y=400,
                                                time=expected_time, tablet=True, pressure=0, tilt_x=0)
            assert event.time == expected_time and event.has_time
            assert event.has_pressure and event.pressure == 0
            assert event.has_tilt_x and not event.has_tilt_y and event.tilt[0] == 0
            event = window.event_simulate_input(type='MOUSEMOVE', value='NOTHING', x=451, y=400,
                                                time=expected_time + .001, tablet=True, tilt_y=-1)
            assert not event.has_pressure and event.has_tilt_y and not event.has_tilt_x
            # Failed validation must not enqueue an event or retype the preceding move.
            for invalid in ({'time': float('nan')}, {'time': -1}, {'pressure': .4},
                            {'tablet': True, 'tilt_x': 2}, {'time': True}, {'tablet': 1}):
                try:
                    window.event_simulate_input(type='MOUSEMOVE', value='NOTHING', x=452, y=400, **invalid)
                except (TypeError, ValueError):
                    pass
                else:
                    raise AssertionError("invalid input accepted: " + repr(invalid))
            assert event.type == 'MOUSEMOVE'
            old = window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=453, y=400)
            assert not old.has_time and old.time == 0 and old.has_pressure and not old.is_tablet
            assert not old.has_tilt_x and not old.has_tilt_y
        elif phase == 2:
            timed = [sample for sample in received if sample[1]]
            assert len(timed) == 2, received
            assert timed[0][0] == 'INBETWEEN_MOUSEMOVE', timed
            assert timed[1][0] == 'MOUSEMOVE', timed
            assert timed[0][2] == expected_time and timed[1][2] == expected_time + .001
            assert all(sample[3] for sample in timed)
            assert timed[0][4:8] == (True, 0, True, False)
            assert timed[1][4] is False and timed[1][7] is True
            assert any(not sample[1] and not sample[9] for sample in received)
            window.event_simulate(type='ESC', value='PRESS')
            print("PLAN3_EVENT_INPUTS_PASS: precision, presence, validation, queued INBETWEEN delivery", flush=True)
        else:
            bpy.ops.wm.quit_blender()
            return None
        phase += 1
        return .4
    except Exception:
        traceback.print_exc()
        print("PLAN3_EVENT_INPUTS_FAIL", flush=True)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(tick, first_interval=2)
