# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headed Scene undo preserves default/explicit/empty/reset placement states."""
import json
from pathlib import Path
import sys
import traceback
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, Position, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

lifecycle.register()
registry = Registry()
defaults = (Position('HEADER', 10), Position('PANEL', 20))
definition = registry.register(Definition('test.undo', 'Undo', 'BOOL', True, 0, 1, 0, 1, positions=defaults))
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.edit.use_global_undo = True
state = dict(phase=0, checks=[])


def store():
    return PersistentOwnerStore(bpy.context.scene, registry)


def explicit():
    root = bpy.context.scene.get(ROOT)
    return root is not None and 'positions_version' in root['records'][record_key(definition.identifier)]


def step():
    try:
        phase = state['phase']
        if phase == 0:
            assert ROOT not in bpy.context.scene
            bpy.ops.ed.undo_push(message='Positions absent')
        elif phase == 1:
            store().write_positions(definition, defaults)
            bpy.ops.ed.undo_push(message='Positions explicit defaults')
        elif phase == 2:
            store().write_positions(definition, ())
            bpy.ops.ed.undo_push(message='Positions explicit empty')
        elif phase == 3:
            store().reset_positions(definition)
            state['old'] = store()
            bpy.ops.ed.undo_push(message='Positions reset')
        elif phase == 4:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert explicit() and store().read_positions(definition) == ()
            try:
                state['old'].read_positions(definition)
            except PropertyError:
                pass
            else:
                raise AssertionError('Old placement store survived undo')
            state['checks'].append('undo reset restores explicit empty and retires store')
        elif phase == 5:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert explicit() and store().read_positions(definition) == defaults
            state['checks'].append('undo empty restores explicitly authored defaults')
        elif phase == 6:
            assert bpy.ops.ed.undo() == {'FINISHED'}
            assert ROOT not in bpy.context.scene and store().read_positions(definition) == defaults
            state['checks'].append('undo creation restores absent override without allocation')
        elif phase == 7:
            for expected, present in ((defaults, True), ((), True), (defaults, False)):
                assert bpy.ops.ed.redo() == {'FINISHED'}
                assert store().read_positions(definition) == expected and explicit() == present
            state['checks'].append('redo traverses explicit defaults, empty, reset distinctly')
        else:
            path = Path(__file__).resolve().parents[1] / 'tests/plan4-positions-headed-results.json'
            path.write_text(json.dumps(dict(passed=True, checks=state['checks']), indent=2) + '\n')
            lifecycle.unregister()
            print('PERSISTENT_POSITIONS_HEADED_PASS', flush=True)
            bpy.ops.wm.quit_blender()
            return None
        state['phase'] += 1
        return .5
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=1)
