# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run final background authoring regressions through the dialog-safe launcher."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
launcher = root / 'claudeMemory/scripts/run_plan3_blender.py'
cases = [
    ('authoring_snapshot', 'AUTHORING_SNAPSHOT_OK', ()),
    ('native_adapters', 'NATIVE_ADAPTERS_OK', ()),
    ('native_adapters_fresh', 'NATIVE_ADAPTERS_FRESH_OK', ()),
    ('native_inventory_coverage', 'NATIVE_INVENTORY_COVERAGE_OK', ()),
    ('atomic_scalar_storage', 'ATOMIC_SCALAR_STORAGE_PASS', ()),
    ('atomic_scalar_storage', 'ATOMIC_SCALAR_STORAGE_PASS', ('verify',)),
    ('persistent_stacks', 'PERSISTENT_STACKS_PASS', ()),
    ('persistent_stacks', 'PERSISTENT_STACKS_PASS', ('verify',)),
    ('persistent_positions', 'PERSISTENT_POSITIONS_PASS', ()),
    ('persistent_positions', 'PERSISTENT_POSITIONS_PASS', ('verify',)),
    ('custom_curve_storage', 'CUSTOM_STORAGE_OK', ()),
    ('frozen_authoring', 'FROZEN_AUTHORING_OK', ()),
    ('frozen_authoring_fresh', 'FROZEN_FRESH_OK', ()),
]
failed = []
for name, marker, args in cases:
    command = [sys.executable, str(launcher), '--script', str(launcher.parent / ('test_' + name + '.py')),
               '--prefix', 'plan4-final-' + name + ('-' + args[0] if args else ''), '--marker', marker]
    if args:
        command += ['--args', *args]
    result = subprocess.run(command, cwd=root)
    if result.returncode:
        failed.append(name + repr(args))
print('FINAL_BACKGROUND_FAILURES', failed, flush=True)
raise SystemExit(bool(failed))
