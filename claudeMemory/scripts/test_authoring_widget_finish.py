# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Drive the real Brush Create/Edit widget and its two undo/redo steps."""
import importlib.util
import json
from pathlib import Path
import time

root = Path(__file__).resolve().parents[2]
output = root / 'claudeMemory/tests/plan4-curve-widget'
spec = importlib.util.spec_from_file_location('widget_client', root / 'tools/blender_debug.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
connection = json.loads((output / 'connection.json').read_text())


def run(code):
    reply = helper.request(connection, 'exec', "t=bpy.app.driver_namespace['owned_editor_test']\n" + code)
    with (output / 'undo-actions.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(code=code, reply=reply)) + '\n')
    assert reply.get('ok'), reply
    time.sleep(.3)


def click(x, y):
    for kind, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')):
        run("t['event']({!r}, {!r}, {}, {})".format(kind, value, x, y))


run("t['state']['owner']='BRUSH'; t['redraw']()")
click(860, 162)
run("assert t['owner']().owned_editor_root.item.curve is not None; "
    "assert t['state']['callbacks']==1; t['state']['checks']=['brush_widget_create']; "
    "t['state']['linear_key']=t['owner']().owned_editor_root.item.curve.curve_mapping_cache_key()")
click(860, 162)
click(750, 480)
click(845, 448)
run("assert t['owner']().owned_editor_root.item.curve.curve_mapping_cache_key()==t['state']['linear_key']")
click(775, 32)
run("c=t['owner']().owned_editor_root.item.curve; assert len(c.curves[0].points)>2; "
    "assert t['state']['callbacks']==2; t['state']['smooth_points']=len(c.curves[0].points); "
    "t['screenshot']('brush_smooth_applied'); t['state']['checks'].append('staged_widget_edit_applies_once')")
run("bpy.ops.ed.undo()")
run("assert len(t['owner']().owned_editor_root.item.curve.curves[0].points)==2; "
    "t['state']['checks'].append('one_undo_restores_brush_widget_edit')")
run("bpy.ops.ed.undo()")
run("assert t['owner']().owned_editor_root.item.curve is None; "
    "t['state']['checks'].append('second_undo_removes_brush_widget_creation'); t['screenshot']('brush_create_undone')")
run("bpy.ops.ed.redo()")
run("assert len(t['owner']().owned_editor_root.item.curve.curves[0].points)==2")
run("bpy.ops.ed.redo()")
run("assert len(t['owner']().owned_editor_root.item.curve.curves[0].points)==t['state']['smooth_points']; "
    "t['state']['checks'].append('two_redos_restore_creation_and_edit'); "
    "t['screenshot']('brush_widget_redone'); import json; from pathlib import Path; "
    "Path({!r}).write_text(json.dumps(t['state']['checks'],indent=2)); "
    "bpy.app.timers.register(lambda: (print('AUTHORING_WIDGET_OK', flush=True), "
    "bpy.ops.wm.quit_blender()) and None, first_interval=.5)".format(
        str(output / 'checks.json')))
