# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the documented shader validator dispatcher with inherited dialog suppression."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from run_blender_native_tests import decoded, suppress_error_dialogs

parser = argparse.ArgumentParser()
parser.add_argument('--backend', choices=('wgsl', 'spirv'), required=True)
parser.add_argument('--prefix', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
command = [shutil.which('node'), 'make.mjs', 'sbrush-validate', args.backend, '-j', '8']
start = time.monotonic()
with suppress_error_dialogs():
    process = subprocess.run(command, cwd=root / 'engine', capture_output=True, timeout=600,
                             creationflags=subprocess.CREATE_NO_WINDOW)
log = decoded(process.stdout) + '\n' + decoded(process.stderr)
target = root / 'claudeMemory/tests' / args.prefix
target.with_suffix('.log').write_text(log, encoding='utf-8')
result = dict(passed=process.returncode == 0, command=command, returncode=process.returncode,
              seconds=time.monotonic() - start)
target.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2), flush=True)
raise SystemExit(0 if result['passed'] else 1)
