# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record the bounded authoring snapshot gate and installed source identities."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')
installed_addon = install / '5.3/scripts/addons_core/sculptcore_addon'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


blender_hash = digest(install / 'blender.exe')
launchers = {name: read(name + '.json') for name in (
    'plan6-snapshots', 'plan6-snapshots-fresh', 'plan6-snapshots-frozen')}
for name, result in launchers.items():
    assert result['passed'] and result['returncode'] == 0 and result['sha256'] == blender_hash, name
    assert 'Traceback' not in (out / (name + '.log')).read_text(encoding='utf-8'), name
checks = {name: read(name + '.checks.json') for name in ('plan6-snapshots', 'plan6-snapshots-fresh')}
assert all(result['passed'] for result in checks.values())
frozen = (out / 'plan6-snapshots-frozen.log').read_text(encoding='utf-8')
assert 'FROZEN_AUTHORING_OK 77' in frozen
hashes = {}
for name in ('authoring.py', 'engine_catalogue.py', 'snapshots.py'):
    source = root / 'sculptcore_addon/brush_properties' / name
    assert digest(source) == digest(installed_addon / 'brush_properties' / name), name
    assert all(len(line) <= 120 for line in source.read_text(encoding='utf-8').splitlines()), name
    hashes[name] = digest(source)
pure = []
for name in ('test_plan6_commands', 'test_generic_property_foundation', 'test_curve_response_cache'):
    result = subprocess.run([sys.executable, str(root / 'claudeMemory/scripts' / (name + '.py'))],
                            cwd=root, capture_output=True, text=True, timeout=60)
    output = result.stdout + '\n' + result.stderr
    (out / ('plan6-snapshot-' + name + '.log')).write_text(output, encoding='utf-8')
    match = re.search(r'Ran (\d+) tests?', output)
    assert result.returncode == 0 and match and '\nOK' in output, output
    pure.append(dict(suite=name, tests=int(match[1]), passed=True))
result = dict(passed=True, scope='Plan 6B immutable authoring snapshot prerequisite; full Plan 6 remains open',
              launchers=launchers, checks=checks, frozen_checks=77, pure=pure, source_sha256=hashes,
              blender_sha256=blender_hash,
              installed_engine_sha256=digest(installed_addon / 'lib/sculptcore/sculptcore_capi.dll'))
(out / 'plan6-snapshot-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_SNAPSHOT_GATE_PASS', json.dumps(dict(blender_runs=len(launchers),
      new_checks=sum(len(item['checks']) for item in checks.values()), frozen_checks=77,
      pure_tests=sum(item['tests'] for item in pure))))
