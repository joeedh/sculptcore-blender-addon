# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run standalone Blender GTests with their runtime environment and durable evidence."""

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


@contextmanager
def suppress_error_dialogs():
    """Child processes inherit this process error mode, unlike DLL directory handles."""
    if os.name != "nt":
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetErrorMode.argtypes = []
    kernel.GetErrorMode.restype = ctypes.c_uint
    kernel.SetErrorMode.argtypes = [ctypes.c_uint]
    kernel.SetErrorMode.restype = ctypes.c_uint
    previous = kernel.GetErrorMode()
    kernel.SetErrorMode(previous | 0x0001 | 0x0002 | 0x8000)
    try:
        yield
    finally:
        kernel.SetErrorMode(previous)


def child_environment(blender_bin):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GTEST_")}
    env["PATH"] = os.pathsep.join((str(blender_bin / "blender.shared"), str(blender_bin), env.get("PATH", "")))
    return env


def decoded(output):
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


def run_test(command, *, cwd, env, output_dir, label, expected_count, timeout):
    """Always persist a result, including launch errors and partial timeout output."""
    result = {
        "command": command, "cwd": str(cwd), "expected_count": expected_count,
        "timeout_seconds": timeout, "binary_sha256": None, "returncode": None,
        "status_hex": None, "stdout": "", "stderr": "", "passed": False,
        "error": None, "runtime_search_path": env.get("PATH", "").split(os.pathsep)[:2],
    }
    started = time.monotonic()
    try:
        with Path(command[0]).open("rb") as binary:
            result["binary_sha256"] = hashlib.file_digest(binary, "sha256").hexdigest()
        with suppress_error_dialogs():
            process = subprocess.run(
                command, cwd=cwd, env=env, capture_output=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        result.update(returncode=process.returncode, status_hex="0x{:08x}".format(process.returncode & 0xffffffff),
                      stdout=decoded(process.stdout), stderr=decoded(process.stderr))
        completed = re.findall(r"^\[\s*=+\s*\]\s+(\d+) tests? from .* ran\.", result["stdout"], re.MULTILINE)
        passed = re.findall(r"^\[\s*PASSED\s*\]\s+(\d+) tests?\.", result["stdout"], re.MULTILINE)
        result["completed_counts"] = [int(count) for count in completed]
        result["passed_counts"] = [int(count) for count in passed]
        result["passed"] = (process.returncode == 0 and expected_count > 0 and
                            result["completed_counts"] == result["passed_counts"] == [expected_count])
        if not result["passed"]:
            result["error"] = "Nonzero exit or missing/mismatched completed GTest counts"
    except subprocess.TimeoutExpired as error:
        # subprocess.run kills and reaps its owned child before raising.
        result.update(error="Timeout", stdout=decoded(error.stdout), stderr=decoded(error.stderr))
    except OSError as error:
        result["error"] = "{}: {}".format(type(error).__name__, error)
    result["elapsed_seconds"] = time.monotonic() - started
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output_dir / (label + ".log")).write_text(
        json.dumps({key: value for key, value in result.items() if key not in {"stdout", "stderr"}}, indent=2)
        + "\n\nSTDOUT:\n" + result["stdout"] + "\nSTDERR:\n" + result["stderr"], encoding="utf-8")
    return result


def selection(value):
    match = re.fullmatch(r"([A-Za-z0-9_-]+)=(\d+)", value)
    if not match or int(match[2]) <= 0:
        raise argparse.ArgumentTypeError("Use an executable basename without extension and positive count: NAME=COUNT")
    return match[1], int(match[2])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender-bin", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--test", action="append", type=selection, required=True, help="NAME=EXPECTED_COUNT")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float("inf"):
        parser.error("timeout must be finite and positive")
    for name in ("blender_bin", "assets_dir", "release_dir", "output_dir"):
        setattr(args, name, getattr(args, name).resolve())
    for directory in (args.blender_bin, args.blender_bin / "tests", args.assets_dir, args.release_dir):
        if not directory.is_dir():
            parser.error("Missing input directory: {}".format(directory))
    env = child_environment(args.blender_bin)
    results = []
    for name, count in args.test:
        binary = (args.blender_bin / "tests" / (name + (".exe" if os.name == "nt" else ""))).resolve()
        if binary.parent != (args.blender_bin / "tests").resolve():
            parser.error("Executable must resolve directly inside bin/tests")
        command = [str(binary), "--test-assets-dir", str(args.assets_dir),
                   "--test-release-dir", str(args.release_dir), "--gtest_color=no"]
        result = run_test(command, cwd=args.blender_bin, env=env, output_dir=args.output_dir,
                          label=name, expected_count=count, timeout=args.timeout)
        results.append(result)
        print("{}: {} (status {}, counts {})".format(
            name, "PASS" if result["passed"] else "FAIL", result["status_hex"], result.get("passed_counts")))
    (args.output_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
