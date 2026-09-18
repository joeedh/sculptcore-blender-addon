# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate native and headed evidence for prepared boundary-aware smoothing."""
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


native = read('plan6-bsmooth-native-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
assert 'prepared BSMOOTH boundary, program, grid and undo gates passed' in prepared['stderr']
launchers = {name: read(name + '.json') for name in (
    'plan6-bsmooth-modal', 'plan6-bsmooth-legacy-modal', 'plan6-bsmooth-package-smoke',
)}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe')
           for item in launchers.values())
samples = read('plan6-bsmooth-modal-samples.json')
assert len(samples) == 8
assert {(item['grid'], item['batch'], item['queued']) for item in samples} == {
    (grid, batch, queued) for grid in (False, True) for batch in (False, True) for queued in (False, True)
}
for item in samples:
    assert item['autosmooth'] and item['prepared_calls']
    assert all(result >= 0 for _, result in item['prepared_calls'])
assert (output / 'plan6-bsmooth-legacy-modal.log').read_text().count('PLAN3_MODAL_CASE_PASS') == 8
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
result = dict(passed=True, scope='Plan 6 prepared BSMOOTH; remaining capabilities and consumers stay open',
              native=native, launchers=launchers, autosmooth_cases=8, legacy_cases=8,
              prepared_calls=sum(len(item['prepared_calls']) for item in samples),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              packaged_dll_sha256=digest(dll),
              reviews=['plan6-bsmooth-mesh-review.md', 'plan6-bsmooth-grid-review.md'])
(output / 'plan6-bsmooth-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_BSMOOTH_GATE_PASS', result['prepared_calls'], 'headed prepared calls; 17 native suites')
