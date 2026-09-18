# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate and verify Python/TS declarations from one explicit native DLL."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import sys

from run_blender_native_tests import suppress_error_dialogs

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "engine/python"))
import sculptcore
from sculptcore import _capi, _gen

parser = argparse.ArgumentParser()
parser.add_argument("--prefix", required=True)
parser.add_argument("--write-source", action="store_true")
args = parser.parse_args()
dll = (root / "engine/build/native/sculptcore_capi.dll").resolve()
output = root / "claudeMemory/tests" / args.prefix
output.mkdir(parents=True, exist_ok=True)

with suppress_error_dialogs():
    manager = sculptcore.init(str(dll))
    lib = manager.capi.lib
    assert Path(lib._name).resolve() == dll
    python = _gen.generate_files(manager.capi)
    lib.LSTL_GenerateTypescript.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    lib.LSTL_GenerateTypescript.restype = ctypes.c_void_p
    lib.LSTL_FreeTypescriptString.argtypes = [ctypes.c_void_p]
    lib.LSTL_FreeTypescriptString.restype = None
    size = ctypes.c_int()
    pointer = lib.LSTL_GenerateTypescript(lib.getBindingManager(), ctypes.byref(size))
    try:
        data = ctypes.string_at(pointer, size.value)
    finally:
        lib.LSTL_FreeTypescriptString(pointer)
    typescript = {}
    offset = 0
    while offset < len(data):
        length, = struct.unpack_from("<i", data, offset)
        offset += 4
        name = data[offset:offset + length].decode("utf-8")
        offset += length
        length, = struct.unpack_from("<i", data, offset)
        offset += 4
        typescript[name] = data[offset:offset + length]
        offset += length
    assert offset == len(data)

hashes = {}
for language, files in (("python", python), ("typescript", typescript)):
    combined = b"\n".join(files.values())
    for required in (b"BrushScalarResult", b"readUniformScalarChecked", b"replaceUniformDynamicsChecked",
                     b"uniformSnapshotChecked", b"uniformQueryToken", b"writeCommonScalarChecked",
                     b"replaceCommonResponseDynamicsChecked", b"replaceUniformResponseDynamicsChecked"):
        assert required in combined, (language, required)
    for name, content in files.items():
        path = output / language / name
        assert path.resolve().is_relative_to(output.resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        hashes[language + "/" + name] = hashlib.sha256(content).hexdigest()
        if args.write_source and language == "typescript":
            target = root / "engine/typescript" / name
            assert target.resolve().is_relative_to((root / "engine/typescript").resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)
if args.write_source:
    _gen.write_stubs()

report = {"passed": True, "dll": str(dll), "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
          "reflection_abi": _capi.ABI_VERSION, "written_to_source": args.write_source,
          "scope": "Python/TS declaration generation; TypeScript runtime transport is not tested",
          "artifacts": hashes}
(output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "artifacts"}, indent=2))
print("{} Python and {} TypeScript files".format(len(python), len(typescript)))
