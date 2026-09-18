# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Check legacy float calls and exact manifest transport against the native DLL."""

import hashlib
import json
from pathlib import Path
import sys

from run_blender_native_tests import suppress_error_dialogs

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "engine/python"))
import sculptcore
from sculptcore._descriptors import read_litestl_string
from sculptcore.brush_properties import CommonProperties, DeviceLayer

dll = root / "engine/build/native/sculptcore_capi.dll"
with suppress_error_dialogs():
    manager = sculptcore.init(str(dll))
    assert Path(manager.capi.lib._name).resolve() == dll.resolve()
    with manager.construct("sculptcore::brush::BrushUniformManifestEntry") as entry:
        setattr(entry, "def", 16777217.0)
        entry.rangeMin = -2147483648.0
        entry.rangeMax = 2147483647.0
        entry.hasDefault = False
        entry.scalarType = 4
        assert getattr(entry, "def") == 16777217.0
        assert entry.rangeMin == -2147483648.0 and entry.rangeMax == 2147483647.0
        assert not entry.hasDefault and int(entry.scalarType) == 4

    with manager.construct("sculptcore::brush::Brush") as brush:
        brush.setNamedFloat(100, 0.75)
        assert brush.getNamedFloat(100) == 0.75
        common = CommonProperties(manager, brush)
        common.write(0, 0.75)
        common.replace_stack(0, [DeviceLayer(0, samples=(0.5, 0.5))])
        brush.pushDeviceInput(0, 0.9)
        assert common.read(0) == 0.75 and common.read(0, evaluate=True) == 0.375
        common.clear_stack(0)
        common.write(5, True)
        common.configure(5, 0)
        brush.pushDeviceInput(0, 0.1)
        assert common.read(5) is True and common.read(5, evaluate=True) is False
        common.clear_stack(5)
        ctor = manager.get_struct("sculptcore::brush::CommandExecutor").find_constructor("main")
        with manager.construct_with(ctor, None, brush) as executor:
            items = manager.get("sculptcore::brush::SculptBrushes").items
            count = executor.queryUniformManifest(int(items["KELVINLET"]))
            assert count > 0 and executor.lastUniformValidationOk()
            manifests = {}
            for index in range(count):
                entry = executor.queriedUniformEntry(index)
                manifests[read_litestl_string(entry.name.ptr)] = {
                    "type": int(entry.scalarType), "default": getattr(entry, "def"),
                    "has_default": entry.hasDefault, "max": entry.rangeMax,
                }
            assert manifests["nu"]["default"] == 0.4 and manifests["nu"]["max"] == 0.499
            assert not manifests["radius"]["has_default"]
            assert executor.queryUniformManifest(int(items["NUDGE"])) > 0
            assert brush.getNamedFloat(100) == 0.75

with dll.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
print(json.dumps({"passed": True, "dll": str(dll), "sha256": digest,
                  "scope": "Legacy float calls, common checked bindings and exact manifest transport",
                  "manifest": manifests}, indent=2))
