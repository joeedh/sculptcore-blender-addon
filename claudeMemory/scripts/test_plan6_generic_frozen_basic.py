# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare generic native execution with the frozen pre-migration geometry."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import bpy
import numpy as np
from sculptcore_addon import convert, engine, handlers, mapping, stroke
from sculptcore_addon.brush_properties import authoring
from sculptcore_addon.brush_properties.adapters import SIZE, STRENGTH
from sculptcore_addon.brush_properties.registry import DeviceLayer, ResponseCurve
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke
from sculptcore_addon.brush_properties.stroke_runtime import StrokeRuntime
from sculptcore_addon.stroke_input import InputSample

root = Path(__file__).resolve().parents[2]
directory = root / 'claudeMemory/tests/generic-brush-v0'

if handlers._on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
    bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)
brush = bpy.data.brushes.new('DeterministicBaseline', mode='SCULPT')
brush.strength = .5
bpy.context.scene.tool_settings.sculpt.unified_paint_settings.use_unified_strength = False
checks = []
for tool in ('DRAW',):
    brush.sculpt_brush_type = tool
    for pressure in (False, True):
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=32, y_subdivisions=32, size=2)
        obj = bpy.context.object
        obj.data.update()
        session = convert.enter(obj)
        native = stroke._ensure_brush(session)
        kernel = mapping.kernel_enum(engine.manager(), brush)
        paint = bpy.context.tool_settings.sculpt
        mapping.apply_brush_settings(brush, paint.unified_paint_settings, native, paint=paint)
        # The frozen harness supplies a fixed radius and explicit pressure switch,
        # bypassing screen projection and spacing compensation for both routes.
        brush.use_pressure_strength = brush.sculptcore_use_pressure_strength = pressure
        brush.use_pressure_size = brush.sculptcore_use_pressure_size = False
        settings = capture_stroke(brush, bpy.context.scene)
        settings = replace(settings, properties=tuple(
            replace(item, value=False) if item.definition.identifier == 'sculptcore.brush.spacing_attenuation'
            else item for item in settings.properties))
        runtime = StrokeRuntime(settings, session, kernel)
        session.generic_runtime = runtime
        stroke.stroke_begin(session, anchored_grab=False)
        for x in (-.2, 0, .2):
            if tool == 'NUDGE':
                native.strokeDirHostSet = True
                vector = native.strokeDir.vec
                vector[0], vector[1], vector[2] = .7071068, 0, -.7071068
            sample = InputSample(pressure=.5)
            runtime.publish(runtime.prepare(runtime.evaluate([sample], [.35])[0], sample))
            sample.upload(native)
            assert stroke.apply_dab(session, kernel, (x, 0, 0), (0, 0, 1), .35) >= 0
        stroke.stroke_end(session)
        actual = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
        key = 'pressure' if pressure else 'plain'
        expected = np.load(directory / (key + '.npy'))
        error = float(np.max(abs(actual - expected)))
        assert np.allclose(actual, expected, atol=2e-6, rtol=0), (key, error)
        checks.append(dict(case=key, max_error=error, exact=bool(np.array_equal(actual, expected))))
        runtime.close()
        session.generic_runtime = None
        convert.exit_(obj)
        bpy.data.objects.remove(obj, do_unlink=True)
dll = Path(engine.capi().lib._name)
(root / 'claudeMemory/tests/plan6-generic-frozen-basic.json').write_text(json.dumps(
    dict(passed=True, checks=checks, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest()), indent=2))
print('PLAN6_GENERIC_FROZEN_BASIC_PASS', checks, flush=True)
