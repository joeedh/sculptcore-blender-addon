# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify native and installed prepared anchored-grab evidence."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
output = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')


def read(name):
    return json.loads((output / name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


native = read('plan6-grab-native-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
assert 'prepared anchored grab independent mesh/grid oracle, radius growth, symmetry and undo passed' in prepared['stderr']
launchers = {name: read(name + '.json') for name in (
    'plan6-grab-installed-background', 'plan6-grab-installed-headed', 'plan6-grab-package-smoke',
    'plan6-grab-kelvinlet-background', 'plan6-grab-kelvinlet-headed')}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe') for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
host = read('plan6-grab-host.json')
assert host['passed'] and Path(host['dll']).resolve() == dll.resolve() and host['sha256'] == digest(dll)
assert len(host['checks']) == 24
for case in host['checks']:
    assert case['prepared_calls'] and all(status >= 0 for _, status in case['prepared_calls'])
kelvinlet = read('plan6-grab-kelvinlet-host.json')
assert kelvinlet['passed'] and kelvinlet['kelvinlet'] and len(kelvinlet['checks']) == 24
assert Path(kelvinlet['dll']).resolve() == dll.resolve() and kelvinlet['sha256'] == digest(dll)
for case in kelvinlet['checks']:
    assert case['prepared_calls'] and all(status >= 0 for _, status in case['prepared_calls'])
bindings = read('plan6-grab-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-grab-typescript.log').read_text(encoding='utf-8').strip()
result = dict(passed=True, scope='Plan 6 prepared anchored grab; preview, dyntopo and generic consumer adoption remain open',
              native=native, launchers=launchers, host=host, kelvinlet=kelvinlet, bindings=bindings,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              review_policy='Remaining review requirement waived by user',
              region_cost='Positive-radius anchored stages select all nonempty leaves')
(output / 'plan6-grab-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_GRAB_GATE_PASS: 17 native suites and 48 installed host cases')
