# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record only current native, installed DLL and actual headed automasking evidence."""
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


native = read('plan6-automask-native-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
for marker in ('prepared cavity authoritative settings and LUT candidates passed',
               'prepared cavity mesh/grid first-contact cache and lifecycle passed',
               'prepared cavity independent strength oracle and exact undo passed'):
    assert marker in prepared['stderr'], marker
launchers = {name: read(name + '.json') for name in (
    'plan6-automask-installed-control', 'plan6-automask-installed-modal',
    'plan6-automask-installed-batches', 'plan6-automask-package-smoke',
)}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe')
           for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
batches = read('plan6-automask-batches.json')
assert batches['passed'] and Path(batches['dll']).resolve() == dll.resolve()
assert batches['sha256'] == digest(dll)
assert len(batches['checks']) == 8 and all(item['max_error'] < 2e-6 for item in batches['checks'])
control = read('plan6-automask-control-samples.json')
samples = read('plan6-automask-modal-samples.json')
assert len(control) == len(samples) == 8
ratios, calls = [], 0
for base, cavity in zip(control, samples):
    assert tuple(base[key] for key in ('grid', 'batch', 'queued')) == tuple(
        cavity[key] for key in ('grid', 'batch', 'queued'))
    assert base['samples'] == cavity['samples']
    assert 0 < cavity['height'] < .8 * base['height']
    assert cavity['prepared_calls'] and all(result >= 0 for _, result in cavity['prepared_calls'])
    calls += len(cavity['prepared_calls'])
    ratios.append(cavity['height'] / base['height'])
bindings = read('plan6-automask-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-automask-typescript.log').read_text(encoding='utf-8').strip()
result = dict(passed=True, scope='Plan 6 command automasking; full generic consumer adoption remains open',
              native=native, launchers=launchers, bindings=bindings, batch_comparisons=batches['checks'],
              headed_cases=8, prepared_calls=calls, cavity_to_control_height_ratios=ratios,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              reviews=['plan6-automask-preparation-review.md', 'plan6-automask-cache-review.md',
                       'plan6-automask-preparation-implementation.md', 'plan6-automask-cache-implementation.md'])
(output / 'plan6-automask-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_AUTOMASK_GATE_PASS', calls, 'prepared calls, 17 native suites, 8 DLL comparisons')
