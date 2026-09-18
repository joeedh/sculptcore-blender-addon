# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify prepared dyntopo acceptance evidence against the installed runtime."""
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


native = read('plan6-dyntopo-native-results.json')
assert len(native) == 26 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
assert 'prepared dyntopo split/collapse, cadence, atomic rejection and undo passed' in prepared['stderr']
launchers = {name: read(name + '.json') for name in (
    'plan6-dyntopo-installed-background', 'plan6-dyntopo-installed-headed',
    'plan6-dyntopo-modal-headed', 'plan6-dyntopo-package-smoke')}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe') for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
sources = {}
for name in ('stroke.py', 'convert.py', 'engine.py'):
    source = root / 'sculptcore_addon' / name
    assert digest(source) == digest(install / '5.3/scripts/addons_core/sculptcore_addon' / name), name
    sources[name] = digest(source)
host = read('plan6-dyntopo-host.json')
assert host['passed'] and Path(host['dll']).resolve() == dll.resolve() and host['sha256'] == digest(dll)
assert len(host['checks']) == 8 and len(host['legacy']) == 4
for case in host['checks']:
    a, b, split, skipped, collapse = case['calls']
    assert a < 0 and b < 0 and split > 0 and skipped == 0 and collapse > 0
modal = read('plan6-dyntopo-modal.json')
assert modal['passed'] and modal['sha256'] == digest(dll) and len(modal['cases']) == 4
for case in modal['cases']:
    assert case['calls'] and all(item['count'] >= 0 for item in case['calls'])
    assert case['vertices'][1] > case['vertices'][0]
bindings = read('plan6-dyntopo-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-dyntopo-typescript.log').read_text(encoding='utf-8').strip()
result = dict(passed=True, scope='Plan 6 prepared dyntopo; general attributes and generic adoption remain open',
              native=native, host=host, modal=modal, launchers=launchers, sources=sources, bindings=bindings,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              review_policy='Remaining review requirement waived by user')
(output / 'plan6-dyntopo-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_DYNTOPO_GATE_PASS: 26 native suites, 8 host cases, 4 raw controls and 4 headed gestures')
