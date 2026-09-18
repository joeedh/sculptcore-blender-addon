# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify and record prepared MASK, finer undo and installed runtime evidence."""
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


native = read('plan6-mask-native-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
for marker in ('mask indexed multichannel capture and finer-only transaction passed',
               'mask shared fold interpolation and owning cleanup passed',
               'mask undo allocation, identity, debt and history cases passed',
               'prepared MASK finer-level undo regression passed'):
    assert marker in prepared['stderr'], marker
launchers = {name: read(name + '.json') for name in (
    'plan6-mask-installed-modal', 'plan6-mask-installed-batches',
    'plan6-mask-installed-preflight', 'plan6-mask-package-smoke',
)}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe')
           for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
batches, preflight = read('plan6-mask-batches.json'), read('plan6-mask-preflight.json')
for result in (batches, preflight):
    assert result['passed'] and Path(result['dll']).resolve() == dll.resolve()
    assert result['sha256'] == digest(dll)
assert len(batches['checks']) == 12 and all(item['max_error'] == 0 for item in batches['checks'])
assert len(preflight['checks']) == 42
samples = read('plan6-mask-modal-samples.json')
assert len(samples) == 8
assert {(item['grid'], item['batch'], item['queued']) for item in samples} == {
    (g, b, q) for g in (False, True) for b in (False, True) for q in (False, True)
}
calls = 0
for item in samples:
    assert item['mask_mode'] and item['mask_max'] > 0 and item['height'] < 1e-6
    assert item['prepared_calls'] and all(result >= 0 for _, result in item['prepared_calls'])
    calls += len(item['prepared_calls'])
result = dict(passed=True, scope='Plan 6 prepared mask capability and finer mask undo; full Plan 6 remains open',
              native=native, launchers=launchers, batch_comparisons=12, preflight_checks=42,
              headed_cases=8, prepared_calls=calls, packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              reviews=['plan6-mask-admission-review.md', 'plan6-mask-storage-review.md',
                       'plan6-mask-undo-lifetime-review.md', 'plan6-mask-undo-footprint-review.md',
                       'plan6-mask-undo-lifetime-implementation.md',
                       'plan6-mask-undo-footprint-implementation.md',
                       'plan6-mask-undo-lifetime-implementationrefined.md',
                       'plan6-mask-undo-footprint-implementationrefined.md'])
(output / 'plan6-mask-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_MASK_GATE_PASS', calls, 'prepared calls, 17 native suites, 12 exact DLL comparisons, 42 preflight checks')
