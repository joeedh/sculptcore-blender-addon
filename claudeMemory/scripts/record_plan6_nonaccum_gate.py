# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record prepared non-accumulating mesh/grid execution and installed stroke evidence."""
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


native = read('plan6-nonaccum-native-results.json')
assert len(native) == 17 and all(item['passed'] for item in native)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
assert 'prepared nonaccum templates, displacement lifetime, region growth and retry passed' in prepared['stderr']
assert 'prepared BSMOOTH boundary, program, grid and undo gates passed' in prepared['stderr']
launchers = {name: read(name + '.json') for name in (
    'plan6-nonaccum-auto', 'plan6-nonaccum-draw', 'plan6-nonaccum-package-smoke',
)}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe')
           for item in launchers.values())
calls = 0
for mode in ('auto', 'draw'):
    samples = read('plan6-nonaccum-' + mode + '-samples.json')
    assert len(samples) == 8
    assert {(item['grid'], item['batch'], item['queued']) for item in samples} == {
        (grid, batch, queued) for grid in (False, True) for batch in (False, True) for queued in (False, True)
    }
    for item in samples:
        assert item['nonaccum'] and item['autosmooth'] == (mode == 'auto')
        assert item['accumulate_modes'] == [False] and item['prepared_calls']
        assert all(result >= 0 for _, result in item['prepared_calls'])
        calls += len(item['prepared_calls'])
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
result = dict(passed=True, scope='Plan 6 prepared non-accumulating execution; remaining tasks stay open',
              native=native, launchers=launchers, headed_cases=16, prepared_calls=calls,
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              packaged_dll_sha256=digest(dll),
              reviews=['plan6-nonaccum-mesh-review.md', 'plan6-nonaccum-grid-review.md'])
(output / 'plan6-nonaccum-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_NONACCUM_GATE_PASS', calls, 'headed prepared calls; 17 native suites')
