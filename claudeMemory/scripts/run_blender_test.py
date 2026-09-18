# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dialog-safe Blender script launcher with explicit success markers and durable logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from run_blender_native_tests import suppress_error_dialogs, child_environment, decoded

parser = argparse.ArgumentParser()
parser.add_argument('--script', required=True, type=Path)
parser.add_argument('--blender', type=Path,
                    default=Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe'))
parser.add_argument('--prefix', required=True)
parser.add_argument('--marker', required=True)
parser.add_argument('--headed', action='store_true')
parser.add_argument('--dev-engine', action='store_true')
parser.add_argument('--timeout', type=float, default=120)
parser.add_argument('--args', nargs=argparse.REMAINDER, default=[])
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
binary = args.blender.resolve()
if not args.prefix.replace('-', '').replace('_', '').isalnum():
    parser.error('prefix must be a simple filename component')
(root / 'claudeMemory/tests').mkdir(exist_ok=True)
env = child_environment(binary.parent)
if args.dev_engine:
    env['SCULPTCORE_PYTHON_PATH'] = str(root / 'engine/python')
    env['SCULPTCORE_CAPI_PATH'] = str(root / 'engine/build/native/sculptcore_capi.dll')
command = [str(binary), '--factory-startup', '--python-exit-code', '1']
command += (['--enable-event-simulate', '--no-window-focus', '-p', '0', '0', '1280', '800']
            if args.headed else ['--background'])
command += ['--python', str(args.script.resolve())]
if args.args:
    command += ['--', *args.args]
result = {'command': command, 'passed': False, 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
start = time.monotonic()
try:
    with suppress_error_dialogs():
        process = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=args.timeout,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    output = decoded(process.stdout) + '\n' + decoded(process.stderr)
    result.update(returncode=process.returncode, passed=(process.returncode == 0 and args.marker in output
                                                        and 'Traceback' not in output))
except subprocess.TimeoutExpired as error:
    output = decoded(error.stdout) + '\n' + decoded(error.stderr)
    result['error'] = 'timeout'
result['seconds'] = time.monotonic() - start
target = root / 'claudeMemory/tests' / args.prefix
target.with_suffix('.log').write_text(output, encoding='utf-8')
target.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['passed'] else 1)
