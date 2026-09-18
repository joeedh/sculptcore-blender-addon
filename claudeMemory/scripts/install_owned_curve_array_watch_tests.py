# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install focused native array-watch lifetime and scaling regression cases."""
from pathlib import Path

target = Path("C:/dev/blender/main/source/blender/blenkernel/intern/curvemapping_owned_test.cc")
source = target.read_text(encoding="utf-8")
tests = (Path(__file__).resolve().parents[1] / "implementation/owned_curve_array_watch_tests.inc").read_text()
assert "LargeEncodingWithUnrelatedLivePathWatch" not in source
source = source.replace("#include <cstring>", "#include <chrono>\n#include <cstdio>\n#include <cstring>")
source = source.replace("}  // namespace blender::bke::tests", tests + "\n}  // namespace blender::bke::tests")
target.write_text(source, encoding="utf-8", newline="\n")
