# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Format the named-storage edits without reformatting unrelated code."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2] / "engine"
formatter = "C:/Program Files/Microsoft Visual Studio/18/Community/VC/Tools/Llvm/x64/bin/clang-format.exe"
for name in ("source/brush/brush.h", "source/brush/brushes/extra.h",
             "source/brush/compiler/emit_cpp.cc", "source/brush/compiler/emit_cpp.h",
             "source/brush/compiler/emit_wgsl.cc",
             "source/brush/compiler/emit_registry.cc", "source/brush/compiler/emit_registry.h",
             "source/brush/compiler/sbrushc_main.cc", "source/brush/brush_executor.h",
             "source/brush/brush_command.h", "source/props/prop_dynamics.h",
             "source/props/prop_enums.h", "tests/test_brush_uniform_validate.cc"):
    diff = subprocess.check_output(["git", "diff", "--unified=0", "--", name], cwd=root).decode("utf-8")
    ranges = []
    for start, count in re.findall(r"^@@ .* \+(\d+)(?:,(\d+))? @@", diff, re.MULTILINE):
        count = int(count or "1")
        if count:
            ranges.append("--lines={}:{}".format(start, int(start) + count - 1))
    if ranges:
        subprocess.run([formatter, "-i", *ranges, str(root / name)], check=True)
for name in ("source/brush/named_uniform_store.h", "source/brush/brush.cc", "tests/test_brush_named_storage.cc",
             "source/brush/brush_configuration.h", "source/brush/brush_configuration.cc",
             "source/brush/brush_executor.cc", "tests/test_brush_configuration.cc"):
    subprocess.run([formatter, "-i", str(root / name)], check=True)
