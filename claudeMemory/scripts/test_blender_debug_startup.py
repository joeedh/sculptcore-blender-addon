# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Test the documented background startup/CLI commands. Pass the Blender executable as argv[1]."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
tool = ROOT / "tools/blender_debug.py"

with tempfile.TemporaryDirectory(prefix="sculptcore-debug-startup-") as directory:
    connection = Path(directory) / "connection.json"
    log_path = Path(directory) / "blender.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.argv[1], "--background", "--factory-startup", "--python-exit-code", "1",
                                    "--python", str(tool), "--", "--connection-file", str(connection),
                                    "--background-seconds", "4"], stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 40
        while not connection.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert connection.exists(), log_path.read_text(encoding="utf-8")
        for arguments in (("--ping",), ("--exec", "remote_value = 123"), ("--eval", "remote_value")):
            completed = subprocess.run([sys.executable, str(tool), "--connection-file", str(connection), *arguments],
                                       capture_output=True, text=True, timeout=5)
            assert completed.returncode == 0, (completed.stdout, completed.stderr)
            reply = json.loads(completed.stdout)
            assert reply["ok"], reply
            if arguments[0] == "--eval":
                assert reply["result"] == "123", reply
        assert process.wait(timeout=10) == 0, log_path.read_text(encoding="utf-8")
        assert "Traceback" not in log_path.read_text(encoding="utf-8")
        print("BLENDER_DEBUG_STARTUP_PASS")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
