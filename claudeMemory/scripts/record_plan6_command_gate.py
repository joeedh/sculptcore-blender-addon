# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record the bounded command gate; never claim full Plan 6 completion."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
output = root / 'claudeMemory/tests'


def read(name):
    return json.loads((output / name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


fixture = {item['suite']: item for item in read('plan6-command-fixture-results.json')}
fixture.update({item['suite']: item for item in read('plan6-command-fixture-final-results.json')})
assert len(fixture) == 17 and all(item['passed'] for item in fixture.values())
native = read('plan6-command-addon-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
launchers = {name: read(name + '.json') for name in (
    'plan6-stack-owners', 'plan6-command-modal', 'plan6-packaged-api', 'plan6-command-package-smoke')}
assert all(result['passed'] for result in launchers.values())
blender = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/blender.exe')
assert all(result['sha256'] == digest(blender) for result in launchers.values())
bindings = read('plan6-command-bindings.json')
owners = read('plan6-stack-owners.checks.json')
package = read('plan6-packaged-api.checks.json')
assert bindings['passed'] and owners['passed'] and package['passed']
assert package['sha256'] == digest(package['dll'])
assert package['sha256'] == digest(root / 'engine/build/python/sculptcore_capi.dll')
pure = []
for name in ('test_plan6_commands', 'test_generic_property_foundation', 'test_curve_response_cache'):
    result = subprocess.run([sys.executable, str(root / 'claudeMemory/scripts' / (name + '.py'))],
                            cwd=root, capture_output=True, text=True, timeout=60)
    text = result.stdout + '\n' + result.stderr
    (output / ('plan6-' + name + '.log')).write_text(text, encoding='utf-8')
    match = re.search(r'Ran (\d+) tests?', text)
    assert result.returncode == 0 and match and '\nOK' in text, text
    pure.append(dict(suite=name, tests=int(match[1]), passed=True))
modal_log = (output / 'plan6-command-modal.log').read_text(encoding='utf-8')
assert modal_log.count('PLAN3_MODAL_CASE_PASS') == 8
ts = subprocess.run([str(root / 'engine/typescript/node_modules/.bin/tsgo.cmd'), '--noEmit'],
                    cwd=root / 'engine/typescript', capture_output=True, text=True, timeout=60)
(output / 'plan6-command-typescript.log').write_text(ts.stdout + ts.stderr, encoding='utf-8')
assert ts.returncode == 0, ts.stdout + ts.stderr
result = dict(passed=True, scope='Plan 6A bounded command integration; full Plan 6 remains open',
              native_suites=native, fixture_suites=list(fixture.values()), launchers=launchers,
              command_bindings=bindings, owner_snapshots=owners, package=package,
              pure=pure, headed_modal_cases=8, typescript_passed=True,
              blender_sha256=digest(blender),
              native_engine_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'))
(output / 'plan6-command-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_COMMAND_GATE_PASS', json.dumps(dict(native=len(native), fixture=len(fixture),
      pure=sum(item['tests'] for item in pure), blender_runs=len(launchers), headed_modal_cases=8)))
