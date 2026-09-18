# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Finish comment placement and format only changed engine lines."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2] / "engine"
path = root / "source/brush/grid_executor.h"
source = path.read_text(encoding="utf-8")
begin = source.index("  /** One logical dab of a composite brush program")
end = source.index("  props::ScalarRegistrationResult lastRegistration;", begin)
comment = source[begin:end]
source = source[:begin] + source[end:]
at = source.index("  int applyProgram(BrushProgram *prog")
source = source[:at] + comment + source[at:]
path.write_text(source, encoding="utf-8", newline="\n")

path = root / "tests/test_brush_props.cc"
source = path.read_text(encoding="utf-8").replace(
    "uniform (plane `planeSide`) must NOT be registered or overwritten by load.",
    "uniform (plane `planeSide`) retains its host value after registration and load.")
source = source.replace("plane @static opt-out: planeSide is host-set, never a prop", "plane @static opt-out: planeSide retains its host value")
source = source.replace("planeoff is a dynamic uniform; planeSide is @static and must be excluded.", "planeoff is dynamic; planeSide has a nondynamic declaration.")
path.write_text(source, encoding="utf-8", newline="\n")

path = root / "source/brush/compiler/emit_cpp.cc"
source = path.read_text(encoding="utf-8").replace(
    "Format a double as a valid C++ float literal (mirrors the LitFloat case).",
    "Preserve exact parsed metadata independently of float working storage.")
path.write_text(source, encoding="utf-8", newline="\n")

formatter = "C:/Program Files/Microsoft Visual Studio/18/Community/VC/Tools/Llvm/x64/bin/clang-format.exe"
files = ["source/brush/brush_command.h", "source/brush/brush_executor.h", "source/brush/grid_executor.h",
         "source/brush/c-api/mesh_stroke_batch_c_api.cc", "source/brush/c-api/grid_stroke_c_api.cc",
         "source/brush/compiler/emit_cpp.cc", "source/brush/compiler/parser.cc", "source/props/prop_struct.h",
         "source/props/prop_struct.cc", "tests/test_brush_props.cc", "tests/test_grid_stroke.cc"]
for name in files:
    diff = subprocess.check_output(["git", "diff", "--unified=0", "--", name], cwd=root).decode("utf-8")
    ranges = []
    for start, count in re.findall(r"^@@ .* \+(\d+)(?:,(\d+))? @@", diff, re.MULTILINE):
        count = int(count or "1")
        if count:
            ranges.append("--lines={}:{}".format(start, int(start) + count - 1))
    if ranges:
        subprocess.run([formatter, "-i", *ranges, str(root / name)], check=True)
for name in ("source/props/prop_declarations.cc", "tests/test_brush_declarations.cc", "tests/test_sbrush_member_types.cc"):
    subprocess.run([formatter, "-i", str(root / name)], check=True)
