# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate typed extra shaders and both compiler-mode semantic rejection gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from run_blender_native_tests import decoded, suppress_error_dialogs


def main():
    root = Path(__file__).resolve().parents[2]
    engine = root / "engine"
    output = root / "claudeMemory/tests/typed-extra-compiler"
    output.mkdir(exist_ok=True)
    compiler = engine / "build/native/source/brush/compiler/sbrushc.exe"
    tint = Path("C:/dev/tint/tint.exe")
    spirv = Path("C:/VulkanSDK/1.4.350.0/Bin/spirv-val.exe")
    results = []

    def run(args, succeeds=True, diagnostic=None):
        args = [str(arg) for arg in args]
        with suppress_error_dialogs():
            p = subprocess.run(args, cwd=engine, capture_output=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        stdout, stderr = decoded(p.stdout), decoded(p.stderr)
        passed = (p.returncode == 0) if succeeds else (p.returncode == 1)
        if diagnostic:
            passed &= diagnostic in stdout + stderr
        results.append(dict(command=args, returncode=p.returncode, passed=passed, stdout=stdout, stderr=stderr))
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        if not passed:
            raise AssertionError(results[-1])

    fixture = engine / "tests/assets/typed_extras/typed_probe.sbrush"
    shader = output / "typed_probe.wgsl"
    binary = output / "typed_probe.spv"
    run([compiler, "--backend=wgsl", "--in=" + str(fixture), "--out=" + str(shader)])
    source = shader.read_text(encoding="utf-8")
    for required in ("typed_enabled: u32", "typed_static: u32", "typed_gate: u32",
                     "brush_u.typed_enabled != 0u", "ctx_u.typed_gate != 0u", "brush_u.invert != 0u",
                     "16777217", "16777218", "bool"):
        assert required in source, required
    assert "skipped" not in source.lower()
    run([tint, str(shader), "--format", "wgsl", "-o", str(output / "typed_probe.validated.wgsl")])
    run([tint, str(shader), "--format", "spirv", "-o", str(binary)])
    run([spirv, str(binary)])

    cases = (
        ("ctx int state @dynamic;", "semantics do not allow"),
        ("uniform float invert;", "does not match native"),
        ("uniform float nonaccum;", "reserved execution"),
        ("ctx int state = 2147483648;", "invalid scalar"),
        ("ctx bool state = 0.5;", "invalid scalar"),
        ("uniform int count; uniform int count;", "duplicate field"),
        ("uniform int count; ctx bool count;", "duplicate field"),
        ("uniform float3 state @dynamic;", "semantics do not allow"),
    )
    for index, (fields, diagnostic) in enumerate(cases):
        source = output / ("invalid_{}.sbrush".format(index))
        source.write_text('@brush("invalid") brush Invalid { ' + fields +
                          " vertex void apply(inout Vertex v) {} }\n", encoding="utf-8")
        run([compiler, "--backend=cpp", "--extras", "--in=" + str(source),
             "--out=" + str(output / "rejected.h")], succeeds=False, diagnostic=diagnostic)
        run([compiler, "--registry", "--in=" + str(source), "--out-dir=" + str(output)],
            succeeds=False, diagnostic=diagnostic)
    peer = output / "typed_peer.sbrush"
    peer_source = fixture.read_text(encoding="utf-8").replace('"typedProbe"', '"typedPeer"').replace(
        "brush TypedProbe", "brush TypedPeer")
    peer.write_text(peer_source, encoding="utf-8")
    run([compiler, "--registry", "--in=" + str(fixture), "--in=" + str(peer), "--out-dir=" + str(output)])
    registry = (output / "sculptcore_extra_brushes.gen.h").read_text(encoding="utf-8")
    for expected in ("extraNamedFloatCount = 1;", "extraNamedIntCount = 5;", "extraNamedBoolCount = 3;",
                     "kExtraSlot_typed_count = 0;", "kExtraSlot_typed_enabled = 0;", "createTypedpeerBrush"):
        assert expected in registry, expected
    for old, new in (("uniform int typed_count", "uniform float typed_count"),
                     ("typed_count = 16777217", "typed_count = 16777218"),
                     ("typed_enabled = true @dynamic", "typed_enabled = true @static")):
        peer.write_text(peer_source.replace(old, new), encoding="utf-8")
        run([compiler, "--registry", "--in=" + str(fixture), "--in=" + str(peer), "--out-dir=" + str(output)],
            succeeds=False, diagnostic="conflicting scalar declarations")
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (compiler, tint, spirv, shader, binary)}
    (output / "hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print("Typed fixture WGSL/SPIR-V validated; {} semantic CLI rejections, typed registry sharing/conflicts passed".format(
        2 * len(cases)))


if __name__ == "__main__":
    main()
