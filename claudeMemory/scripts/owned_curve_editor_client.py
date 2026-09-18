# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Drive only the test-owned headed curve instance and record request results."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import time

repository = Path(__file__).resolve().parents[2]
output = repository / "claudeMemory" / "tests" / os.environ.get("OWNED_CURVE_EDITOR_OUTPUT", "owned-curve-editor-final")
spec = importlib.util.spec_from_file_location("owned_editor_debug_client", repository / "tools" / "blender_debug.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
action, *args = sys.argv[1:]
prefix = "t=bpy.app.driver_namespace['owned_editor_test']; "
operation = "exec"
if action == "state":
    operation = "eval"
    code = "bpy.app.driver_namespace['owned_editor_test']['describe']()"
elif action == "screenshot":
    operation = "eval"
    code = "bpy.app.driver_namespace['owned_editor_test']['screenshot']({!r})".format(args[0])
elif action == "click":
    code = prefix + "t['click']({}, {})".format(int(args[0]), int(args[1]))
elif action == "event":
    extra = dict(json.loads(args[4])) if len(args) > 4 else {}
    code = prefix + "t['event']({!r}, {!r}, {}, {}, **{!r})".format(
        args[0], args[1], int(args[2]), int(args[3]), extra)
elif action == "key":
    code = prefix + "t['event']({0!r}, 'PRESS'); t['event']({0!r}, 'RELEASE')".format(args[0])
elif action == "text":
    names = {str(i): name for i, name in enumerate(
        ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"))}
    names.update({".": "PERIOD", "-": "MINUS"})
    code = prefix + "t['event']('A', 'PRESS', ctrl=True); t['event']('A', 'RELEASE', ctrl=True); "
    for char in args[0]:
        code += "t['event']({0!r}, 'PRESS', unicode={1!r}); t['event']({0!r}, 'RELEASE'); ".format(
            names[char], char)
elif action == "file":
    code = Path(args[0]).read_text(encoding="utf-8")
elif action == "eval":
    operation = "eval"
    code = args[0]
elif action == "expect":
    label, expected = args[:2]
    code = prefix + "data=t['owner'](); "
    if expected == "unset":
        code += "assert not data.is_property_set('owned_editor_root'); "
    else:
        value = float(expected)
        code += "assert data.is_property_set('owned_editor_root'); root=data.owned_editor_root; "
        code += "assert root.is_property_set('item'); assert root.item.curve is not None; "
        code += "actual=root.item.curve.curves[0].points[-1].location.y; "
        code += "assert abs(actual - {!r}) < 0.0001, actual; ".format(value)
    if len(args) > 2:
        code += "assert t['state']['callbacks'] == {}, t['state']['callbacks']; ".format(int(args[2]))
    code += "t['state'].setdefault('checks', []).append({!r}); print({!r})".format(label, label)
elif action == "set":
    code = prefix + "t['owner']().owned_editor_root.item.curve.curves[0].points[-1].location.y = {!r}".format(float(args[0]))
elif action == "owner":
    code = prefix + "t['state']['owner']={!r}; t['redraw']()".format(args[0])
elif action == "path":
    code = prefix + "t['state']['path']={!r}; t['redraw']()".format(args[0])
elif action == "collection":
    operation_name = args[0]
    code = prefix + "t['state']['owner']='SCENE'; data=t['owner'](); items=data.owned_editor_items; "
    if operation_name in {"empty", "existing"}:
        code += "items.clear(); items.add(); items.add(); t['state']['path']='owned_editor_items[0].curve'; "
        if operation_name == "existing":
            code += "curve=data.curve_mapping_initialize(t['state']['path']); curve.curves[0].points[-1].location.y=0.375; "
    elif operation_name == "move":
        code += "items.move(0,1); "
    elif operation_name == "grow":
        code += "[items.add() for _ in range(300)]; "
    elif operation_name == "remove":
        code += "items.remove(1); "
    elif operation_name == "expect_empty":
        code += "assert all(item.curve is None for item in items); t['state'].setdefault('checks',[]).append('stale_empty_collection_button'); "
    elif operation_name == "expect_moved":
        code += "assert items[0].curve is None; assert abs(items[1].curve.curves[0].points[-1].location.y-1.0)<0.0001; t['state'].setdefault('checks',[]).append('edit_original_after_collection_move_and_growth'); "
    else:
        raise ValueError(operation_name)
    code += "t['redraw']()"
elif action == "finish":
    code = prefix + "import hashlib,json; from pathlib import Path; "
    code += "result=dict(t['state']); result['binary_sha256']=hashlib.sha256(Path(bpy.app.binary_path).read_bytes()).hexdigest(); "
    code += "result['scope']='Partial headed editor regression; full Plan 2 gate remains open'; "
    code += "Path({!r}).write_text(json.dumps(result,indent=2)+'\\n'); ".format(str(output / "test.json"))
    code += "print('OWNED_CURVE_EDITOR_PARTIAL_PASS'); bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.5)"
else:
    raise ValueError("Unknown action: " + action)

connection = json.loads((output / "connection.json").read_text())
if action == "click":
    for kind, value in (("MOUSEMOVE", "NOTHING"), ("LEFTMOUSE", "PRESS"), ("LEFTMOUSE", "RELEASE")):
        step = prefix + "t['event']({!r}, {!r}, {}, {})".format(kind, value, int(args[0]), int(args[1]))
        reply = helper.request(connection, "exec", step)
        if not reply.get("ok", False):
            break
        time.sleep(0.15)
else:
    reply = helper.request(connection, operation, code)
if action in {"click", "event", "key", "text"}:
    time.sleep(0.2)
with (output / "actions.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"time": time.time(), "action": action, "arguments": args, "reply": reply}) + "\n")
print(json.dumps(reply, indent=2))
if not reply.get("ok", False):
    raise SystemExit(1)
