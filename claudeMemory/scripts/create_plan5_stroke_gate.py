# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Derive cache instrumentation from the proven modal input gate."""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
text = (root / 'claudeMemory/scripts/test_modal_inputs.py').read_text()
text = text.replace('from sculptcore_addon import engine, stroke',
                    'from sculptcore_addon import engine, stroke\nfrom sculptcore_addon.brush_properties import sampling')
text = text.replace('cases = [(grid, batch, queued) for grid in (False, True) for batch in (False, True) for queued in (False, True)]',
                    'cases = [(False, True, False)] * 5')
text = text.replace('        if phase == 0:\n', '        if phase == 0 and case == 0:\n')
text = text.replace("            brush.stroke_method = 'SPACE'", """            brush.stroke_method = 'SPACE'
            if case == 0:
                brush.curve_distance_falloff_preset = 'CUSTOM'
                brush.use_space_attenuation = True
                brush.mesh_automasking_settings.use_automasking_cavity = True
                brush.mesh_automasking_settings.use_automasking_custom_cavity_curve = True
                brush.mesh_automasking_settings.cavity_curve.curves[0].points[-1].location.y = .81
                brush.curve_distance_falloff.curves[0].points[-1].location.y = .13
            if case:
                phase += 1
                return .2""")
text = text.replace('            active = True\n            push', """            active = True
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
            push""")
start = text.index('            if results:\n')
end = text.index('            results.append(', start)
text = text[:start] + """            delta = [a - b for a, b in zip(counters(), before)]
            expected = [(3, 2, 2, 1), (0, 0, 0, 0), (1, 2, 0, 0), (0, 2, 0, 0), (3, 2, 2, 1)][case]
            assert tuple(delta) == expected, (case, delta, expected)
            print('PLAN5_WARM_COUNTS', case, delta, flush=True)
""" + text[end:]
text = text.replace('samples=list(records), source_inputs=list(inputs), height=height(), batches=list(batches)))',
                    'samples=list(records), height=height(), counters=delta, seconds=time.perf_counter() - clock[0]))')
text = text.replace("'tests/plan3-modal-samples.json'", "'tests/plan5-modal-cache.checks.json'")
text = text.replace('PLAN3_MODAL_CASE_PASS', 'PLAN5_MODAL_CASE_PASS').replace('PLAN3_MODAL_INPUTS_PASS', 'PLAN5_MODAL_CACHE_PASS')
text = text.replace('PLAN3_MODAL_INPUTS_FAIL', 'PLAN5_MODAL_CACHE_FAIL')
text = text.replace('def tick():', """before, clock = [], [0]


def counters():
    memo = engine.sessions[bpy.context.object.name].curve_cache
    uploads = memo.get('pressure_uploads')
    return (sampling.cache.bakes, uploads.uploads if uploads else 0,
            memo.get('table_uploads', 0), memo.get('overlap_bakes', 0))


def tick():""")
(root / 'claudeMemory/scripts/test_plan5_modal_cache.py').write_text(text)
print('PLAN5_MODAL_GATE_CREATED')
