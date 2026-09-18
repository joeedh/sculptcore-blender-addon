# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare native and dispatcher exit codes with Windows loader dialogs disabled."""
import ctypes
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
engine = root / "engine"
ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
results = []
names = ["test_props_checked_access", "test_sbrush_member_types", "test_props_typed_dynamics",
         "test_props", "test_brush_dynamics", "test_brush_uniform_validate",
         "test_sbrush_attr_writes", "test_gpu_uniform_pack"]
commands = [[str(engine / "build/native/tests" / (name + ".cc_out.exe"))] for name in names]
blender_bin = Path("C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin")
commands += [[str(blender_bin / "tests" / name), "--gtest_list_tests"] for name in (
    "blenkernel_curvemapping_owned_test.exe", "blenkernel_curvemapping_idprop_test.exe")]
for command in commands:
    run = subprocess.run(command, cwd=engine, capture_output=True, text=True, timeout=30)
    results.append({"command": command, "returncode": run.returncode,
                    "hex": hex(run.returncode & 0xffffffff),
                    "stdout": run.stdout, "stderr": run.stderr})
path = root / "claudeMemory/tests/native-loader-probe.json"
path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results, indent=2))
