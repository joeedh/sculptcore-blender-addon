# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify ENHANCE's native, installed host, shader and package evidence."""
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


native = read('plan6-enhance-native-results.json')
latest = read('plan6-enhance-support-results.json')
assert len(latest) == 1 and latest[0]['suite'] == 'test_brush_prepared_execution'
native = [latest[0] if item['suite'] == latest[0]['suite'] else item for item in native]
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
for marker in ('prepared ENHANCE independent temporal oracle, restoration and undo passed',
               'prepared ENHANCE independent support, growth, command order and unbounded union passed'):
    assert marker in latest[0]['stderr'], marker
launchers = {name: read(name + '.json') for name in (
    'plan6-enhance-installed-background', 'plan6-enhance-installed-headed', 'plan6-enhance-package-smoke')}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe') for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
host = read('plan6-enhance-host.json')
assert host['passed'] and Path(host['dll']).resolve() == dll.resolve() and host['sha256'] == digest(dll)
assert len(host['checks']) == 20
assert sum(case['raw_reference'] for case in host['checks']) == 4
for case in host['checks']:
    assert case['max_motion'] > 1e-5
    if not case['raw_reference']:
        assert case['prepared_calls'] and all(status >= 0 for _, status in case['prepared_calls'])
bindings = read('plan6-enhance-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-enhance-typescript.log').read_text(encoding='utf-8').strip()
backends = {name: read('plan6-enhance-' + name + '.json') for name in ('wgsl', 'spirv')}
assert all(item['passed'] for item in backends.values())
result = dict(passed=True, scope='Plan 6 prepared ENHANCE; full generic modal adoption remains open',
              native=native, launchers=launchers, host=host, bindings=bindings, backends=backends,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              review_policy='Remaining review requirement waived by user on 2026-09-18',
              retained_review='plan6-enhance-semantics-review.md')
(output / 'plan6-enhance-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_ENHANCE_GATE_PASS: 17 native suites; 16 prepared host cases and 4 raw controls')
