# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run typed-property regression suites through the engine dispatcher with logs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from run_blender_native_tests import decoded, suppress_error_dialogs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="typed-declarations")
    parser.add_argument("--extended-registration", action="store_true")
    parser.add_argument("--named-storage", action="store_true")
    parser.add_argument("--typed-extras", action="store_true")
    parser.add_argument("--compiler-boundaries", action="store_true",
                        help="Include compiler boundary checks without requiring the typed runtime fixture")
    parser.add_argument("--configuration", action="store_true")
    parser.add_argument("--prepared-execution", action="store_true")
    parser.add_argument("--preview", action="store_true", help="Include legacy preview and nonaccumulation regressions")
    parser.add_argument("--dyntopo", action="store_true", help="Include topology, nonaccumulation and undo regressions")
    parser.add_argument("--attributes", action="store_true", help="Include paint, layer and attribute undo regressions")
    parser.add_argument("--semantic", action="store_true", help="Include typed semantic-domain batch evaluation")
    parser.add_argument("--suite", action="append", help="Run only a named suite from the selected gate")
    args = parser.parse_args()
    if not args.prefix.replace("-", "").replace("_", "").isalnum():
        parser.error("prefix must be a simple filename component")
    root = Path(__file__).resolve().parents[2]
    engine = root / "engine"
    output = root / "claudeMemory/tests"
    output.mkdir(exist_ok=True)
    suites = (
        "test_props_declarations", "test_props_checked_access", "test_props_typed_dynamics",
        "test_props", "test_sbrush_member_types", "test_brush_dynamics",
        "test_brush_uniform_validate", "test_sbrush_attr_writes", "test_gpu_uniform_pack",
    )
    if args.extended_registration:
        suites += ("test_brush_declarations", "test_brush_props", "test_brush_registry", "test_grid_stroke")
    if args.named_storage:
        suites += ("test_brush_named_storage",)
    if args.typed_extras or args.compiler_boundaries:
        suites += ("test_brush_typed_extras",)
    if args.configuration:
        suites += ("test_brush_configuration",)
    if args.semantic:
        suites += ("test_semantic_scalars",)
    if args.prepared_execution:
        suites += ("test_brush_prepared_execution",)
    if args.preview:
        suites += ("test_meshlog_preview_rollback", "test_meshlog_preview_unbound", "test_brush_nonaccum")
    if args.dyntopo:
        suites += ("test_dyntopo", "test_dyntopo_undo", "test_dyntopo_stroke_undo",
                   "test_dyntopo_nonaccum_collapse", "test_dyntopo_collapse_crash", "test_spatial_dyntopo")
    if args.attributes:
        suites += ("test_brush_attr", "test_attr_saver", "test_paint_undo", "test_layer_stroke_undo",
                   "test_sculpt_layers", "test_multires_attrs", "test_boundary", "test_meshlog_topo")
    if args.suite:
        if any(name not in suites for name in args.suite):
            parser.error("requested suite is not part of the selected gate")
        suites = tuple(name for name in suites if name in args.suite)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node dispatcher runtime not found")
    results = []
    for suite in suites:
        binary = engine / "build/native/tests" / (suite + ".cc_out" + (".exe" if os.name == "nt" else ""))
        command = [node, "make.mjs", "test", suite]
        result = {"suite": suite, "command": command, "binary": str(binary), "returncode": None, "passed": False}
        try:
            with binary.open("rb") as stream:
                result["binary_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            with suppress_error_dialogs():
                process = subprocess.run(
                    command, cwd=engine, capture_output=True, timeout=180,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            result.update(returncode=process.returncode, passed=process.returncode == 0,
                          stdout=decoded(process.stdout), stderr=decoded(process.stderr))
            if args.prepared_execution and suite == "test_brush_prepared_execution":
                marker = "resolved mesh/grid programs, widened raw reference and atomic rejection passed"
                if marker not in result["stdout"] + result["stderr"]:
                    result.update(passed=False, error="Missing required prepared-program execution marker")
            if args.named_storage and suite == "test_brush_declarations":
                marker = "extra-kernel failed registration preserves working slots"
                if marker not in result["stdout"] + result["stderr"]:
                    result.update(passed=False, error="The extra-kernel registration branch did not run")
            if args.typed_extras and suite == "test_brush_typed_extras":
                for domain in ("mesh", "grid"):
                    for execution in ("standalone", "program"):
                        for delivery in ("single", "batch"):
                            marker = f"public typed inputs {domain} {execution} {delivery} geometry and undo passed"
                            if marker not in result["stdout"] + result["stderr"]:
                                result.update(passed=False, error="Missing public input marker: " + marker)
                for marker in ("typed extra registry, authored/cache writes and packed bytes passed",
                               "typed extra candidate defaults and readonly evaluation passed",
                               "typed extra resolved mesh geometry and atomic publication passed",
                               "typed extra resolved grid geometry and atomic publication passed",
                               "resolved grid unqueried seam bounds and undo passed",
                               "typed extra resolved mesh program geometry and exact restoration passed",
                               "typed extra resolved grid program geometry and exact restoration passed",
                               "typed extra mesh program geometry passed", "typed extra grid program geometry passed"):
                    if marker not in result["stdout"] + result["stderr"]:
                        result.update(passed=False, error="Missing required fixture marker: " + marker)
        except subprocess.TimeoutExpired as error:
            result.update(error="Timeout", stdout=decoded(error.stdout), stderr=decoded(error.stderr))
        except OSError as error:
            result["error"] = str(error)
        results.append(result)
        (output / (args.prefix + "-" + suite + ".log")).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (output / (args.prefix + "-results.json")).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print("{}: {}".format(suite, "PASS" if result["passed"] else "FAIL"), flush=True)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
