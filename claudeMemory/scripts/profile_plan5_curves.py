# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure actual installed Blender/native curve synchronization costs."""
import json
from pathlib import Path
import statistics
import time
import bpy
from sculptcore_addon import engine, mapping
from sculptcore_addon.brush_properties import sampling

brush = bpy.data.brushes.new('CurveProfile', mode='SCULPT')
brush.curve_distance_falloff_preset = 'CUSTOM'
settings = brush.mesh_automasking_settings
settings.use_automasking_cavity = True
settings.use_automasking_custom_cavity_curve = True
settings.cavity_curve.curves[0].points[-1].location.y = .7
memo = {}
results = {}
with engine.manager().construct('sculptcore::brush::Brush') as target:
    operations = {
        'pressure': lambda: mapping.apply_pressure_dynamics(brush, target, use_strength=True, use_size=True, cache=memo),
        'falloff': lambda: mapping._bake_falloff(brush, target, memo),
        'cavity': lambda: mapping._apply_cavity(settings, target, memo),
    }
    for name, operation in operations.items():
        cold, warm = [], []
        for _ in range(5):
            sampling.clear()
            memo.clear()
            start = time.perf_counter()
            operation()
            cold.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            operation()
            warm.append((time.perf_counter() - start) * 1000)
        results[name] = dict(cold_ms=statistics.median(cold), warm_ms=statistics.median(warm))
print(json.dumps(results), flush=True)
path = Path(__file__).resolve().parents[1] / 'tests/plan5-curve-profile.checks.json'
path.write_text(json.dumps(results, indent=2) + '\n')
print('PLAN5_PROFILE_PASS', flush=True)
