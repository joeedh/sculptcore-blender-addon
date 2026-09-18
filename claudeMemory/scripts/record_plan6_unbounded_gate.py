# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify recorded unbounded compiler, native, DLL and installed runtime evidence."""
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


native = read('plan6-unbounded-native-results.json')
fixture = read('plan6-unbounded-fixture-results.json')
for results in (native, fixture):
    assert len(results) == 17 and all(item['passed'] for item in results)
for item in native:
    assert item['binary_sha256'] == digest(item['binary']), item['suite']
prepared = next(item for item in native if item['suite'] == 'test_brush_prepared_execution')
for marker in ('Kelvinlet double reference passed 1485 scalar endpoint cases',
               'unbounded extent snapshots, override eligibility and numerical preflight passed',
               'unbounded nonconstant cavity first-contact and strict support passed',
               'DRAW crossing unbounded cavity support uses post-stage first-contact geometry',
               'prepared unbounded mesh/grid independent field oracle, growth, cavity and exact undo passed'):
    assert marker in prepared['stderr'], marker
typed = next(item for item in fixture if item['suite'] == 'test_brush_typed_extras')
assert 'declared then inherited unbounded extent execution and restoration passed' in typed['stderr']
configuration = next(item for item in native if item['suite'] == 'test_brush_configuration')
assert 'checked scalar IEEE and FTZ/DAZ transport, atomicity and preflight passed' in configuration['stderr']
launchers = {name: read(name + '.json') for name in (
    'plan6-unbounded-installed-batches', 'plan6-unbounded-installed-headed',
    'plan6-unbounded-installed-control', 'plan6-unbounded-installed-denormals',
    'plan6-unbounded-package-smoke',
)}
assert all(item['passed'] and item['sha256'] == digest(install / 'blender.exe')
           for item in launchers.values())
dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
assert digest(dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
batches = read('plan6-unbounded-batches.json')
denormals = read('plan6-kelvinlet-denormal-probe.json')
for item in (batches, denormals):
    assert item['passed'] and Path(item['dll']).resolve() == dll.resolve()
    assert item['sha256'] == digest(dll)
assert len(batches['checks']) == 16
assert len(denormals['cases']) == 4
assert sum(case.get('checked_rejection', False) for case in denormals['cases']) == 2
control = read('plan6-automask-modal-samples.json')
assert len(control) == 8
assert all(case['prepared_calls'] and all(status >= 0 for _, status in case['prepared_calls']) for case in control)
bindings = read('plan6-unbounded-bindings/results.json')
assert bindings['passed'] and bindings['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert not (output / 'plan6-unbounded-typescript.log').read_text(encoding='utf-8').strip()
for backend in ('wgsl', 'spirv'):
    result = read('plan6-unbounded-' + backend + '.json')
    assert result['passed']
result = dict(passed=True, scope='Plan 6 nonanchored unbounded execution; generic host adoption remains open',
              native=native, fixture=fixture, launchers=launchers, bindings=bindings,
              batch_comparisons=batches['checks'], denormal_cases=denormals['cases'],
              headed_api_cases=16, headed_modal_control_cases=8,
              packaged_dll_sha256=digest(dll),
              native_dll_sha256=digest(root / 'engine/build/native/sculptcore_capi.dll'),
              reviews=['plan6-unbounded-compiler-review.md', 'plan6-unbounded-execution-review.md',
                       'plan6-unbounded-compiler-implementation-review.md',
                       'plan6-unbounded-execution-implementation-review.md',
                       'plan6-kelvinlet-numerical-review.md', 'plan6-kelvinlet-compatibility-review.md',
                       'plan6-kelvinlet-numerical-implementation-review.md',
                       'plan6-kelvinlet-numerical-implementation-followup-review.md',
                       'plan6-kelvinlet-host-contract-review.md', 'plan6-kelvinlet-host-compatibility-review.md'])
(output / 'plan6-unbounded-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PLAN6_UNBOUNDED_GATE_PASS', '17 native + 17 fixture suites; 16 installed batch comparisons')
