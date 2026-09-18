# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record only verified final launchers, durable assertions and installed source identities."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
tests = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')
fork = Path('C:/dev/blender/main')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


binary_sha = digest(install / 'blender.exe')
prefixes = ['plan4-final-' + name for name in (
    'authoring_snapshot', 'native_adapters', 'native_adapters_fresh', 'native_inventory_coverage',
    'atomic_scalar_storage', 'atomic_scalar_storage-verify', 'persistent_stacks', 'persistent_stacks-verify',
    'persistent_positions', 'persistent_positions-verify', 'custom_curve_storage', 'frozen_authoring',
    'frozen_authoring_fresh', 'custom-assets', 'custom-assets-fresh', 'owner-safety', 'owner-safety-fresh', 'smoke')]
prefixes += ['plan4-' + name for name in (
    'authoring-undo-headed', 'authoring-collections', 'authoring-custom-undo', 'authoring-undo-limits',
    'authoring-owner-identity', 'curve-widget', 'object-mode-base')]
launchers = {}
for prefix in prefixes:
    result = json.loads((tests / (prefix + '.json')).read_text())
    assert result['passed'] and result['returncode'] == 0 and result['sha256'] == binary_sha, prefix
    assert 'Traceback' not in (tests / (prefix + '.log')).read_text(encoding='utf-8'), prefix
    launchers[prefix] = dict(seconds=result['seconds'], command=result['command'])

check_files = [
    'plan4-authoring-snapshot.checks.json', 'plan4-native-adapters.checks.json',
    'plan4-native-adapters-fresh.checks.json', 'plan4-native-inventory-coverage.checks.json',
    'plan4-atomic/test-results.json', 'plan4-atomic/verify-results.json',
    'plan4-stacks/test-results.json', 'plan4-stacks/verify-results.json',
    'plan4-positions/test-results.json', 'plan4-positions/verify-results.json',
    'plan4-custom/test.json', 'plan4-custom-assets/test.json', 'plan4-custom-assets/verify.json',
    'plan4-frozen/results.json', 'plan4-frozen/fresh.json',
    'plan4-owner-assets/test-results.json', 'plan4-owner-assets/verify-results.json',
    'plan4-authoring-undo-headed.checks.json', 'plan4-authoring-collections.checks.json',
    'plan4-authoring-custom-undo.checks.json', 'plan4-authoring-undo-limits.checks.json',
    'plan4-authoring-owner-identity.checks.json', 'plan4-curve-widget/checks.json',
    'plan4-object-mode-base.checks.json',
]
counts = {}
for name in check_files:
    data = json.loads((tests / name).read_text(encoding='utf-8'))
    checks = data if isinstance(data, list) else data['checks']
    assert checks, name
    counts[name] = len(checks)

sources = {}
for source in (root / 'sculptcore_addon/brush_properties').glob('*.py'):
    relative = source.relative_to(root / 'sculptcore_addon')
    staged = install / '5.3/scripts/addons_core/sculptcore_addon' / relative
    assert source.read_bytes() == staged.read_bytes(), relative
    compile(source.read_text(encoding='utf-8'), str(source), 'exec')
    assert all(len(line) <= 120 for line in source.read_text(encoding='utf-8').splitlines()), relative
    assert 'CLAUDENOTE' not in source.read_text(encoding='utf-8'), relative
    sources[str(relative)] = digest(source)
base = fork / 'scripts/modules/_bpy_types.py'
assert base.read_bytes() == (install / '5.3/scripts/modules/_bpy_types.py').read_bytes()
assert 'class ObjectModeType(_StructRNA, metaclass=_RNAMeta):' in base.read_text(encoding='utf-8')
for name in ('generate_native_authoring.py', 'generate_frozen_authoring.py'):
    subprocess.run([sys.executable, str(root / 'claudeMemory/scripts' / name), '--check'], check=True, cwd=root)
foundation = subprocess.run([sys.executable, str(root / 'claudeMemory/scripts/test_generic_property_foundation.py')],
                            check=True, cwd=root, capture_output=True, text=True)
(tests / 'plan4-final-foundation.log').write_text(foundation.stdout + foundation.stderr, encoding='utf-8')
package_log = (tests / 'plan4-final-package.log').read_text(encoding='utf-8')
assert '[dist] done.' in re.sub(r'\x1b\[[0-9;]*m', '', package_log)

native_paths = (
    'source/blender/editors/undo/authoring_undo.cc',
    'source/blender/editors/include/ED_authoring_undo.hh',
    'source/blender/python/intern/bpy_rna_authoring.cc',
    'source/blender/python/intern/bpy_rna_types_capi.cc',
    'source/blender/editors/interface/templates/interface_template_curve_mapping.cc',
    'source/blender/makesrna/intern/rna_owned_curve.cc',
    'scripts/modules/_bpy_types.py',
    'doc/python_api/rst/info_property_authoring.rst',
)
engine_dll = install / '5.3/scripts/addons_core/sculptcore_addon/lib/sculptcore/sculptcore_capi.dll'
result = dict(passed=True, plan=4, binary_sha256=binary_sha, engine_sha256=digest(engine_dll),
              launchers=launchers, check_counts=counts, addon_sources=sources,
              fork_sources={name: digest(fork / name) for name in native_paths},
              pure_tests=11, scope='Authoring model complete; generic stroke/UI consumers remain Plans 5-8')
(tests / 'plan4-completion-gate.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(passed=True, launchers=len(launchers), checks=counts), indent=2))
