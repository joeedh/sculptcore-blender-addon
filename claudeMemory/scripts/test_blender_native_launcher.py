# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise native launcher failure reporting, including a real Windows loader failure."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

from run_blender_native_tests import child_environment, run_test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.blender_bin = args.blender_bin.resolve()
    args.output_dir = args.output_dir.resolve()
    env = child_environment(args.blender_bin)
    prior_mode = ctypes.windll.kernel32.GetErrorMode() if os.name == "nt" else None
    cases = [
        ("nonzero", "print('partial', flush=True); raise SystemExit(7)", 10, 7),
        ("silent_zero", "pass", 10, 0),
        ("zero_tests", "print('[==========] 0 tests from 0 test suites ran.\\n[  PASSED  ] 0 tests.')", 10, 0),
        ("partial_suite", "print('[==========] 1 test from 1 test suite ran.\\n[  PASSED  ] 1 test.')", 10, 0),
        ("timeout", "import time; print('partial', flush=True); time.sleep(30)", 0.5, None),
    ]
    results = []
    for label, code, timeout, status in cases:
        result = run_test([sys.executable, "-c", code], cwd=args.blender_bin, env=env,
                          output_dir=args.output_dir, label=label, expected_count=2, timeout=timeout)
        assert not result["passed"] and result["returncode"] == status, result
        if label == "timeout":
            assert result["error"] == "Timeout" and "partial" in result["stdout"], result
        results.append(result)
    missing = run_test([str(args.output_dir / "missing-test.exe")], cwd=args.blender_bin, env=env,
                       output_dir=args.output_dir, label="missing", expected_count=1, timeout=5)
    assert not missing["passed"] and missing["returncode"] is None and "FileNotFoundError" in missing["error"]
    results.append(missing)
    if os.name == "nt":
        loader_env = dict(env)
        # Intentionally exclude Blender DLLs, while retaining Windows system DLLs.
        loader_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        result = run_test([str(args.blender_bin / "tests/blenkernel_curvemapping_owned_test.exe"),
                           "--gtest_list_tests"], cwd=args.output_dir, env=loader_env,
                          output_dir=args.output_dir, label="loader_failure", expected_count=14, timeout=10)
        assert not result["passed"] and result["status_hex"] == "0xc0000135", result
        assert ctypes.windll.kernel32.GetErrorMode() == prior_mode
        results.append(result)
    launcher = str(Path(__file__).with_name("run_blender_native_tests.py"))
    common = [sys.executable, launcher, "--blender-bin", str(args.blender_bin),
              "--assets-dir", str(args.blender_bin), "--release-dir", str(args.blender_bin),
              "--output-dir", str(args.output_dir / "cli")]
    for label, name, status in (("cli_missing", "missing-test=1", 1), ("cli_traversal", "../bad=1", 2)):
        child = subprocess.run(common + ["--test", name], capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert child.returncode == status, child
        results.append({"case": label, "returncode": child.returncode,
                        "stdout": child.stdout.decode(), "stderr": child.stderr.decode()})
    original_filter = os.environ.get("GTEST_FILTER")
    try:
        os.environ["GTEST_FILTER"] = "DoesNotExist"
        assert "GTEST_FILTER" not in child_environment(args.blender_bin)
    finally:
        if original_filter is None:
            del os.environ["GTEST_FILTER"]
        else:
            os.environ["GTEST_FILTER"] = original_filter
    (args.output_dir / "verification.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("PASS: {} failure cases; error mode restored; inherited GTest filter removed".format(len(results)))


if __name__ == "__main__":
    main()
