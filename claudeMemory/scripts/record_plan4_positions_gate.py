# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the saved-placement completion gate against staged source and binaries."""
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
tests = root / "claudeMemory/tests"
install = Path("C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin")
staged = install / "5.3/scripts/addons_core/sculptcore_addon"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


binary = digest(install / "blender.exe")
launchers = (
    "plan4-positions", "plan4-positions-assets", "plan4-positions-assets-fresh", "plan4-positions-headed",
    "plan4-positions-without-authoring", "plan4-positions-fresh", "plan4-positions-stack-regression",
    "plan4-positions-scalar-regression", "plan4-positions-smoke",
)
for name in launchers:
    result = json.loads((tests / (name + ".json")).read_text())
    assert result["passed"] and result["returncode"] == 0 and result["sha256"] == binary, name
counts = {}
for name, expected in (
    ("plan4-positions/test-results", 64), ("plan4-positions/verify-results", 3),
    ("plan4-positions-assets/test-results", 9), ("plan4-positions-assets/verify-results", 1),
    ("plan4-positions-headed-results", 4), ("plan4-atomic/test-results", 64),
    ("plan4-stacks/test-results", 77),
):
    result = json.loads((tests / (name + ".json")).read_text())
    counts[name] = len(result["checks"])
    assert result["passed"] and counts[name] == expected, name
absent = json.loads((tests / "plan4-positions/without-authoring-results.json").read_text())
assert absent["passed"] and absent["addon_disabled"] and absent["authoring_imports_blocked"]
assert absent["preserved_records"] == 2
pure = (tests / "plan4-positions-foundation.log").read_text()
assert "Ran 11 tests" in pure and "\nOK" in pure
package = re.sub(r"\x1b\[[0-9;]*m", "", (tests / "plan4-positions-package.log").read_text())
assert "done. install ready" in package and "enabled by default (no userpref)" in package
sources = {}
for path in sorted((root / "sculptcore_addon/brush_properties").glob("*.py")):
    name = path.relative_to(root / "sculptcore_addon").as_posix()
    sources[name] = digest(path)
    assert sources[name] == digest(staged / name), "Staged source differs: " + name
report = dict(
    passed=True, scope="Saved local plural positions with explicit defaults/empty/reset semantics",
    blender_sha256=binary, engine_sha256=digest(staged / "lib/sculptcore/sculptcore_capi.dll"),
    addon_sources=sources, launchers=launchers, counts=counts, pure_tests=11, without_authoring=absent,
    limitations=[
        "Product placement renderer and new UI/stroke consumers remain disabled",
        "Custom curve integration and native adapters remain open",
        "Generic Scene undo verified; Brush/native-Scene authoring undo remains open",
        "Headless smoke does not exercise wgpu_native GPU dependency loading",
    ],
)
(tests / "plan4-positions-gate.json").write_text(json.dumps(report, indent=2) + "\n")
print("PLAN4_POSITIONS_GATE_PASS")
