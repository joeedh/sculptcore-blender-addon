# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run cage color lifecycle gates with proof of checked native routing."""
import hashlib
import importlib.util
import json
from pathlib import Path
import bpy
from sculptcore_addon import engine

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cage_gate', root / 'tools/verify_multires_color.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
lib = engine.capi().lib
native = lib.CageSmooth_dabResolved
calls = []

def checked(*args):
    result = native(*args)
    calls.append(dict(tool=args[1], count=result))
    assert result >= 0
    return result

def raw_rejected(*args):
    raise AssertionError('Cage smoothing silently used the legacy loader')

lib.CageSmooth_dabResolved = checked
lib.CageSmooth_dabCurrentInputs = raw_rejected
lib.CageSmooth_dabBatch = raw_rejected
gate.VERBOSE = True
gate.run_cage_smooth()
assert not gate.FAILURES, gate.FAILURES
assert calls and all(item['count'] > 0 for item in calls)
dll = Path(lib._name).resolve()
result = dict(passed=True, calls=calls, dll=str(dll), sha256=hashlib.sha256(dll.read_bytes()).hexdigest())
(root / 'claudeMemory/tests/plan6-cage-host.json').write_text(json.dumps(result, indent=2))
print('PLAN6_CAGE_HOST_PASS', flush=True)
if not bpy.app.background:
    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None
    bpy.app.timers.register(quit_after_startup, first_interval=1)
