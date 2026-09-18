# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run an existing gesture fixture with generic evaluation required for each stroke."""
from pathlib import Path
import runpy
import sys
import bpy
from sculptcore_addon import stroke
from sculptcore_addon.brush_properties.native_evaluation import NativeEvaluation

bpy.context.scene.sculptcore_generic_properties = True
seen = set()
original_evaluate = NativeEvaluation.evaluate

def evaluated(self, samples, radii):
    result = original_evaluate(self, samples, radii)
    seen.add(id(self))
    return result

NativeEvaluation.evaluate = evaluated
for name in ('_finish', '_finish_preview'):
    original = getattr(stroke.SCULPTCORE_OT_brush_stroke, name)
    def finished(self, *args, _original=original, **kwargs):
        assert self._generic is not None, 'generic stroke runtime missing'
        assert id(self._generic.native) in seen, 'native semantic collection not evaluated'
        result = _original(self, *args, **kwargs)
        print('PLAN6_GENERIC_ROUTE_USED', flush=True)
        return result
    setattr(stroke.SCULPTCORE_OT_brush_stroke, name, finished)

route = sys.argv[sys.argv.index('--') + 1]
assert route in ('preview', 'dyntopo', 'cage', 'layer', 'attributes')
source = Path(__file__).with_name('test_brush_' + route + '_gestures.py')
code = source.read_text(encoding='utf-8').replace('tests/plan6-' + route + '-modal.json',
                                                'tests/plan6-generic-' + route + '-modal.json')
exec(compile(code, str(source), 'exec'), dict(__name__='__main__', __file__=str(source)))
