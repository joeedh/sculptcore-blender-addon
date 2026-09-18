# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify and collect durable evidence for the bounded native owner-safety gate."""
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
tests = root / 'claudeMemory/tests'
install = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin')
staged = install / '5.3/scripts/addons_core/sculptcore_addon'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


binary = digest(install / 'blender.exe')
launchers = ('plan4-native', 'plan4-owner-safety', 'plan4-owner-fresh',
             'plan4-owner-headed', 'plan4-native-curve-notifications',
             'plan4-native-curve-fresh', 'plan4-owned-cache', 'plan4-owner-smoke')
for name in launchers:
    result = json.loads((tests / (name + '.json')).read_text())
    assert result['passed'] and result['returncode'] == 0 and result['sha256'] == binary, name
assert 'Ran 11 tests' in (tests / 'plan4-owner-foundation.log').read_text()
assert '\nOK' in (tests / 'plan4-owner-foundation.log').read_text()
package_log = re.sub(r'\x1b\[[0-9;]*m', '', (tests / 'plan4-owner-package.log').read_text())
assert 'done. install ready' in package_log
assert 'enabled by default (no userpref)' in package_log
counts = {}
for name, expected in (('plan4-native-results', 22), ('plan4-owner-assets/test-results', 43),
                       ('plan4-owner-assets/verify-results', 1), ('plan4-owner-headed-results', 3),
                       ('plan4-native-curve-assets/results', 16)):
    result = json.loads((tests / (name + '.json')).read_text())
    counts[name] = len(result['checks'])
    assert counts[name] == expected, name
assert 'OWNED_CACHE_PASS 13' in (tests / 'plan4-owned-cache.log').read_text()
sources = {}
for name in ('__init__.py', 'brush_properties/native.py', 'brush_properties/lifecycle.py'):
    sources[name] = digest(root / 'sculptcore_addon' / name)
    assert sources[name] == digest(staged / name), 'Staged source differs: ' + name
report = dict(
    passed=True,
    scope='Native owner safety only; persistent generic storage remains unimplemented',
    blender_sha256=binary,
    engine_sha256=digest(staged / 'lib/sculptcore/sculptcore_capi.dll'),
    addon_sources=sources,
    fork_source_sha256=digest(Path('C:/dev/blender/main/source/blender/makesrna/intern/rna_sculpt_paint.cc')),
    launchers=launchers, counts=counts, pure_tests=11, owned_cache_checks=13,
    limitations=[
        'Notifier recipient verified by source audit, not direct runtime notifier observation',
        'Undo test covers a Scene custom-property sentinel and lifetime; Brush/native Scene settings retain current values',
        'Import isolation does not unload the engine already loaded by the startup addon',
        'Headless package smoke does not map wgpu_native; no GPU packaging assertion',
    ])
(tests / 'plan4-owner-gate.json').write_text(json.dumps(report, indent=2) + '\n')
print('PLAN4_OWNER_GATE_PASS')
