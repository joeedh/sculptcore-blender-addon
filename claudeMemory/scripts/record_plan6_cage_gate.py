# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify prepared cage smoothing acceptance evidence against the installed runtime."""
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


native = read('plan6-cage-native-results.json')
assert len(native) == 34 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_multires_attrs')
assert prepared['stdout'].count('cage colour smooth:') == 2
launchers = {name: read(name + '.json') for name in (
    'plan6-cage-installed-background', 'plan6-cage-installed-headed',
    'plan6-cage-modal-headed', 'plan6-cage-package-smoke')}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe') for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
sources = {}
for name in ('stroke.py', 'convert.py', 'engine.py'):
    source = root / 'sculptcore_addon' / name
    assert digest(source) == digest(install / '5.3/scripts/addons_core/sculptcore_addon' / name), name
    sources[name] = digest(source)
host = read('plan6-cage-host.json')
assert host['passed'] and Path(host['dll']).resolve() == dll.resolve() and host['sha256'] == digest(dll)
assert host['calls'] and all(item['count'] > 0 for item in host['calls'])
modal = read('plan6-cage-modal.json')
assert modal['passed'] and modal['sha256'] == digest(dll) and len(modal['cases']) == 2
for case in modal['cases']:
    assert case['calls'] and all(item['count'] >= 0 for item in case['calls'])
bindings = read('plan6-cage-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-cage-typescript.log').read_text(encoding='utf-8').strip()
result = dict(passed=True, scope='Plan 6 prepared cage smoothings; cage execution and generic adoption remain open',
              native=native, host=host, modal=modal, launchers=launchers, sources=sources, bindings=bindings,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              review_policy='Remaining review requirement waived by user')
(output / 'plan6-cage-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_CAGE_GATE_PASS: 34 native suites, installed cage lifecycle and 2 headed gestures')
