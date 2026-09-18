# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record the typed semantic evaluator gate without claiming consumer adoption."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
out = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


native = read('plan6-domains-native.json')
assert native['passed'] and native['comparisons'] == 543 and native['bitwise_float32']
launcher, checks = read('plan6-domains-blender.json'), read('plan6-domains-blender.checks.json')
assert launcher['passed'] and checks['passed'] and len(checks['checks']) == 6
assert launcher['sha256'] == digest(install / 'blender.exe')
source = root / 'sculptcore_addon/brush_properties/evaluation.py'
assert digest(source) == digest(install / '5.3/scripts/addons_core/sculptcore_addon/brush_properties/evaluation.py')
pure = subprocess.run([sys.executable, str(root / 'claudeMemory/scripts/test_plan6_evaluation.py')],
                      capture_output=True, text=True, timeout=60)
output = pure.stdout + '\n' + pure.stderr
(out / 'plan6-domains-pure.log').write_text(output, encoding='utf-8')
assert pure.returncode == 0 and 'Ran 6 tests' in output and '\nOK' in output, output
config = (root / 'engine/build/native/CMakeCache.txt').read_text(encoding='utf-8')
assert 'tests/assets/typed_extras' not in config
for path in (source, root / 'claudeMemory/scripts/test_plan6_evaluation.py',
             root / 'claudeMemory/scripts/test_plan6_evaluation_native.py',
             root / 'claudeMemory/scripts/test_plan6_evaluation_blender.py'):
    too_long = [index for index, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1) if len(line) > 120]
    assert not too_long, (path.name, too_long)
result = dict(passed=True, scope='Plan 6B typed semantic evaluator prerequisite; consumers remain to adopt it',
              native=native, blender=launcher, checks=checks, pure_tests=6, source_sha256=digest(source),
              addon_native_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              installed_python_dll_sha256=digest(install /
                  '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'))
(out / 'plan6-domains-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_DOMAINS_GATE_PASS', native['comparisons'], 'native comparisons; 6 pure tests; 6 Blender groups')
