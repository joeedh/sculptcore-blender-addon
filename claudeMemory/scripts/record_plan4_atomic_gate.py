# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the persistent scalar gate against the installed binary and addon."""
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
tests = root / "claudeMemory/tests"
install = Path("C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin")
staged = install / "5.3/scripts/addons_core/sculptcore_addon"
fork = Path("C:/dev/blender/main")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


binary = digest(install / "blender.exe")
launchers = (
    "plan4-atomic", "plan4-atomic-assets", "plan4-atomic-assets-fresh",
    "plan4-atomic-headed", "plan4-atomic-without-authoring", "plan4-atomic-fresh",
    "plan4-atomic-owner-regression", "plan4-atomic-cache", "plan4-atomic-smoke",
)
for name in launchers:
    result = json.loads((tests / (name + ".json")).read_text())
    assert result["passed"] and result["returncode"] == 0 and result["sha256"] == binary, name
counts = {}
for name, expected in (
    ("plan4-atomic/test-results", 64), ("plan4-atomic/verify-results", 5),
    ("plan4-atomic-assets/test-results", 14), ("plan4-atomic-assets/verify-results", 2),
    ("plan4-atomic-headed-results", 4), ("plan4-owner-assets/test-results", 43),
):
    result = json.loads((tests / (name + ".json")).read_text())
    counts[name] = len(result["checks"])
    assert result["passed"] and counts[name] == expected, name
absent = json.loads((tests / "plan4-atomic/without-authoring-results.json").read_text())
assert absent["passed"] and absent["addon_disabled"] and absent["authoring_imports_blocked"]
assert absent["preserved_records"] == 6
pure = (tests / "plan4-atomic-foundation.log").read_text()
assert "Ran 11 tests" in pure and "\nOK" in pure
assert "OWNED_CACHE_PASS 13" in (tests / "plan4-atomic-cache.log").read_text()
assert "property not found" not in (tests / "plan4-atomic-headed.log").read_text().lower()
package = re.sub(r"\x1b\[[0-9;]*m", "", (tests / "plan4-atomic-package.log").read_text())
assert "done. install ready" in package and "enabled by default (no userpref)" in package
sources = {}
paths = [root / "sculptcore_addon/__init__.py"]
paths.extend(sorted((root / "sculptcore_addon/brush_properties").glob("*.py")))
for path in paths:
    name = path.relative_to(root / "sculptcore_addon").as_posix()
    sources[name] = digest(path)
    assert sources[name] == digest(staged / name), "Staged source differs: " + name
fork_sources = {
    name: digest(fork / name) for name in (
        "source/blender/python/intern/bpy_rna_idprops.cc",
        "source/blender/python/intern/bpy_rna_idprops.hh",
        "source/blender/python/intern/bpy_rna_types_capi.cc",
        "source/blender/python/intern/CMakeLists.txt",
        "source/blender/python/generic/idprop_py_ui_api.cc",
        "source/blender/python/generic/idprop_py_ui_api.hh",
        "doc/python_api/rst/info_atomic_id_properties.rst",
    )
}
report = dict(
    passed=True, scope="Persistent scalar values/policies and atomic scalar UI metadata",
    blender_sha256=binary,
    engine_sha256=digest(staged / "lib/sculptcore/sculptcore_capi.dll"),
    addon_sources=sources, fork_sources=fork_sources, launchers=launchers, counts=counts,
    pure_tests=11, owned_cache_checks=13, without_authoring=absent,
    limitations=[
        "Persistent stacks, saved positions, custom curve bank and further native adapters remain open",
        "Headed undo covers generic Scene data; Brush/native Scene authoring undo remains open",
        "No new stroke/UI consumer or feature switch is enabled",
        "Headless package smoke does not map wgpu_native and is not a clean-machine GPU test",
    ],
)
(tests / "plan4-atomic-gate.json").write_text(json.dumps(report, indent=2) + "\n")
print("PLAN4_ATOMIC_GATE_PASS")
