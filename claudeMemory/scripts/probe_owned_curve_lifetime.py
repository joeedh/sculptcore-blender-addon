# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolate retained native allocations at process shutdown."""
import gc
import sys
import bpy

bpy.types.Brush.owned_probe = bpy.props.CurveMappingProperty()
mode = sys.argv[sys.argv.index("--") + 1]
brush = bpy.data.brushes.new("LifetimeProbe", mode='SCULPT')
curve = brush.curve_mapping_initialize("owned_probe")
if mode == "edit":
    for i in range(10):
        curve.curves[0].points[-1].location = (1, 0.1 * i)
elif mode == "function":
    for i in range(10):
        curve.curves[0].points.new(0.05 * i, 0.5)
elif mode == "iterator":
    for i in range(10):
        iterator = iter(curve.curves[0].points)
        next(iterator)
        curve.clip_max_x = 2 + i
        try:
            next(iterator)
        except ReferenceError:
            pass
    del iterator
if mode != "leave":
    del curve
    bpy.data.brushes.remove(brush)
    del brush
    del bpy.types.Brush.owned_probe
    gc.collect()
print("OWNED_LIFETIME_PROBE " + mode, flush=True)
