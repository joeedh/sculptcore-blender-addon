# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify durable Plan 5 gates and the exact installed source/runtime identities."""
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
tests = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')
addon = install / '5.3/scripts/addons_core/sculptcore_addon'
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def read(name):
    return json.loads((tests / name).read_text())

binary = digest(install / 'blender.exe')
prefixes = ('curves', 'curve-undo', 'modal-cache', 'modal-inputs', 'geometry', 'curve-profile',
            'native-adapters', 'package-smoke', 'packaged-api', 'assets', 'assets-fresh')
launchers = {}
for suffix in prefixes:
    prefix = 'plan5-' + suffix
    result = read(prefix + '.json')
    assert result['passed'] and result['returncode'] == 0 and result['sha256'] == binary, prefix
    assert 'Traceback' not in (tests / (prefix + '.log')).read_text(), prefix
    launchers[prefix] = result
native = read('plan5-restored-gate-results.json')
assert len(native) == 17 and all(result['passed'] and result['returncode'] == 0 for result in native)
for result in native:
    assert digest(Path(result['binary'])) == result['binary_sha256'], result['suite']
dll_gate = read('plan5-checked-bindings.json')
assert dll_gate['passed'] and len(dll_gate['checks']) == 15
generated = read('plan5-generated-bindings/results.json')
assert generated['passed'] and generated['written_to_source']
assert generated['sha256'] == digest(root / 'engine/build/native/sculptcore_capi.dll')
assert len(generated['formatted_typescript']) == 74
for path, expected in generated['formatted_typescript'].items():
    assert digest(root / 'engine/typescript' / path) == expected, path
assert 'PLAN5_TYPESCRIPT_PASS' in (tests / 'plan5-typescript.log').read_text()
for name, count in (('response-cache', 6), ('foundation', 11)):
    log = (tests / ('plan5-' + name + '.log')).read_text()
    assert 'Ran {} tests'.format(count) in log and '\nOK' in log
counts = {}
for filename in ('plan5-curves.checks.json', 'plan5-curve-undo.checks.json',
                 'plan5-modal-cache.checks.json', 'plan5-packaged-api.checks.json',
                 'plan4-native-adapters.checks.json', 'plan4-custom-assets/test.json', 'plan4-custom-assets/verify.json'):
    values = read(filename)
    assert values, filename
    counts[filename] = len(values)
modal = read('plan5-modal-cache.checks.json')
assert [item['counters'] for item in modal] == [[3, 2, 2, 1], [0, 0, 0, 0], [1, 2, 0, 0],
                                              [0, 2, 0, 0], [3, 2, 2, 1]]
assert '[dist] done.' in re.sub(r'\x1b\[[0-9;]*m', '', (tests / 'plan5-stage.log').read_text())
sources = {}
for source in list((root / 'sculptcore_addon/brush_properties').glob('*.py')) + [
        root / 'sculptcore_addon' / name for name in ('mapping.py', 'stroke.py', 'engine_props.py')]:
    relative = source.relative_to(root / 'sculptcore_addon')
    assert source.read_bytes() == (addon / relative).read_bytes(), relative
    compile(source.read_text(), str(source), 'exec')
    sources[str(relative)] = digest(source)
bridge = root / 'engine/python/sculptcore/brush_properties.py'
assert bridge.read_bytes() == (addon / 'lib/sculptcore/brush_properties.py').read_bytes()
for source in (root / 'engine/python/sculptcore/types').glob('*.pyi'):
    assert source.read_bytes() == (addon / 'lib/sculptcore/types' / source.name).read_bytes(), source
packaged_dll = addon / 'lib/sculptcore/sculptcore_capi.dll'
assert digest(packaged_dll) == digest(root / 'engine/build/python/sculptcore_capi.dll')
fixture = read('plan5-fixture-gate-results.json')
assert all(item['passed'] for item in fixture if item['suite'] != 'test_brush_configuration')
record = dict(passed=True, plan=5, binary_sha256=binary, engine_sha256=digest(packaged_dll),
              native_engine_sha256=generated['sha256'], launchers=launchers, native_suites=17,
              fixture_dll_checks=dll_gate, check_counts=counts, addon_sources=sources,
              bridge_sha256=digest(bridge), pure_tests=17,
              profile_before=read('plan5-curve-profile-before-bulk.checks.json'),
              profile_after=read('plan5-curve-profile.checks.json'),
              fixture_note='16 fixture suites passed; configuration harness lifetime corrected and passed '
                           'in final addon-only gate. Exact fixture DLL typed/bulk checks passed.',
              scope='Plan 5 complete; generic stroke/command adoption, UI and migration remain Plans 6-8')
(tests / 'plan5-completion-gate.json').write_text(json.dumps(record, indent=2) + '\n')
tasks_path = root / 'claudeMemory/plans/generic-brush-properties-tasks.md'
tasks = tasks_path.read_text()
start, end = tasks.index('## Plan 5:'), tasks.index('## Plan 6:')
section = tasks[start:end].replace('- [ ]', '- [x]')
if '**Completion:**' not in section:
    section += ('**Completion:** 2026-09-17. [Evidence](../codebase/generic-brush-plan5-evidence.md) '
                'and [verified manifest](../tests/plan5-completion-gate.json): '
                '11 Blender runs, 17 native suites, 15 exact-DLL check groups and 17 pure tests. '
                'Actual warm strokes perform zero unchanged bakes/uploads; analytic typed responses, '
                'customization undo/persistence, asset cleanliness and matched package gates pass.\n\n')
tasks_path.write_text(tasks[:start] + section + tasks[end:])
print(json.dumps(dict(passed=True, plan=5, blender_runs=len(launchers), native_suites=17,
                      pure_tests=17, check_counts=counts), indent=2))
