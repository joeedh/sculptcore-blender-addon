# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run with background Blender (explicit pump) or headed Blender (real app timers)."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("debug_tool", ROOT / "tools/blender_debug.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
server = tool.load_server()
background = bpy.app.background
python = Path(sys.prefix) / ("bin/python.exe" if sys.platform == "win32" else "bin/python3")
scratch = tempfile.TemporaryDirectory(prefix="sculptcore-debug-test-")
connection_file = Path(scratch.name) / "connection.json"
info = server.start()
tool.publish_connection(connection_file, info)
outcome = []


def client_checks():
    # This thread uses no Blender API, including when constructing commands.
    try:
        reply = tool.request(info, "eval", "__import__('threading').current_thread() is "
                             "__import__('threading').main_thread()")
        assert reply["result"] == "True", reply
        reply = tool.request(info, "exec", "bpy.context.scene['debug_server_probe'] = 123\nsaved_number = 41")
        assert reply["ok"], reply
        reply = tool.request(info, "eval", "(bpy.context.scene['debug_server_probe'], saved_number + 1)")
        assert reply["result"] == "(123, 42)", reply
        reply = tool.request(info, "eval", "[(w.screen.name, [a.type for a in w.screen.areas]) "
                             "for w in bpy.context.window_manager.windows]")
        assert reply["ok"] and "VIEW_3D" in reply["result"], reply
        reply = tool.request(info, "exec", "w = bpy.context.window_manager.windows[0]\n"
                             "a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')\n"
                             "with bpy.context.temp_override(window=w, area=a):\n"
                             "    assert bpy.context.area.type == 'VIEW_3D'")
        assert reply["ok"], reply
        completed = subprocess.run([str(python), str(ROOT / "tools/blender_debug.py"),
                                    "--connection-file", str(connection_file), "--eval", "bpy.app.version_string"],
                                   capture_output=True, text=True, timeout=10)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["ok"], completed.stdout
        outcome.append(True)
    except BaseException:
        outcome.append(traceback.format_exc())


worker = threading.Thread(target=client_checks, daemon=True)
worker.start()
deadline = time.monotonic() + 45


def finalize():
    assert outcome == [True], outcome
    old = server._server
    # A file that reaches Blender's read path but cannot be decoded tests load_pre on failure.
    invalid = Path(scratch.name) / "invalid.blend"
    invalid.write_bytes(b"not a blend file")
    try:
        bpy.ops.wm.open_mainfile(filepath=str(invalid), load_ui=False)
    except RuntimeError:
        pass
    assert old.stopped and server._server is None, "failed load left the server running"
    assert not old.namespace
    info2 = server.start()
    assert info2["token"] != info["token"]
    valid = Path(scratch.name) / "valid.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(valid))
    bpy.ops.wm.open_mainfile(filepath=str(valid), load_ui=False)
    assert server._server is None, "successful load left server running"
    server.start()
    import addon_utils
    # Exercise the real addon unregister hook (including older staged-addon injection).
    def unregister_failed(_error):
        raise RuntimeError("addon unregister failed")

    addon_utils.disable("sculptcore_addon", handle_error=unregister_failed)
    assert server._server is None, "addon unregister left server running"
    assert not bpy.app.timers.is_registered(old.timer)
    scratch.cleanup()
    print("BLENDER_DEBUG_INTEGRATION_PASS {}".format("background" if background else "headed"), flush=True)


def tick():
    try:
        if time.monotonic() > deadline:
            raise TimeoutError("Remote debug test deadline exceeded")
        if not outcome:
            return 0.05
        finalize()
    except BaseException:
        server.stop()
        traceback.print_exc()
        print("BLENDER_DEBUG_INTEGRATION_FAIL", flush=True)
    if not background:
        bpy.ops.wm.quit_blender()
    return None


if background:
    while not outcome and time.monotonic() < deadline:
        server.pump()
        time.sleep(0.01)
    finalize()
else:
    bpy.app.timers.register(tick, first_interval=0.1)
