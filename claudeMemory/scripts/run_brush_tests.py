# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run a focused generic-property regression suite; keep generated evidence local."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent

# (case, script, success marker, Blender arguments). None marks a plain Python test.
UNIT = tuple((name, script, None, ()) for name, script in (
    ('ownership', 'test_generic_property_foundation.py'),
    ('responses', 'test_curve_response_cache.py'),
    ('commands', 'test_property_commands.py'),
    ('evaluation', 'test_property_evaluation.py'),
    ('input', 'test_stroke_inputs.py'),
    ('errors', 'test_stroke_registration_errors.py'),
))
AUTHORING = (
    ('snapshot', 'test_authoring_snapshot.py', 'AUTHORING_SNAPSHOT_OK', ()),
    ('native', 'test_native_adapters.py', 'NATIVE_ADAPTERS_OK', ()),
    ('native-fresh', 'test_native_adapters_fresh.py', 'NATIVE_ADAPTERS_FRESH_OK', ()),
    ('inventory', 'test_native_inventory_coverage.py', 'NATIVE_INVENTORY_COVERAGE_OK', ()),
    ('scalars', 'test_atomic_scalar_storage.py', 'ATOMIC_SCALAR_STORAGE_PASS', ()),
    ('scalars-resave', 'test_atomic_scalar_without_authoring.py', 'ATOMIC_WITHOUT_AUTHORING_PASS', ('atomic',)),
    ('scalars-reload', 'test_atomic_scalar_storage.py', 'ATOMIC_SCALAR_STORAGE_PASS', ('verify',)),
    ('stacks', 'test_persistent_stacks.py', 'PERSISTENT_STACKS_PASS', ()),
    ('stacks-resave', 'test_atomic_scalar_without_authoring.py', 'ATOMIC_WITHOUT_AUTHORING_PASS', ('stacks',)),
    ('stacks-reload', 'test_persistent_stacks.py', 'PERSISTENT_STACKS_PASS', ('verify',)),
    ('positions', 'test_persistent_positions.py', 'PERSISTENT_POSITIONS_PASS', ()),
    ('positions-resave', 'test_atomic_scalar_without_authoring.py', 'ATOMIC_WITHOUT_AUTHORING_PASS', ('positions',)),
    ('positions-reload', 'test_persistent_positions.py', 'PERSISTENT_POSITIONS_PASS', ('verify',)),
    ('curves', 'test_custom_curve_storage.py', 'CUSTOM_STORAGE_OK', ()),
    ('curves-resave', 'test_atomic_scalar_without_authoring.py', 'ATOMIC_WITHOUT_AUTHORING_PASS', ('custom',)),
    ('curves-reload', 'test_custom_curve_storage.py', 'CUSTOM_STORAGE_OK', ('verify',)),
    ('frozen', 'test_frozen_authoring.py', 'FROZEN_AUTHORING_OK', ()),
    ('frozen-fresh', 'test_frozen_authoring_fresh.py', 'FROZEN_FRESH_OK', ()),
    ('migration-assets', 'test_brush_migration_assets.py', 'BRUSH_MIGRATION_ASSETS_OK', ()),
    ('migration-disabled', 'test_brush_migration_assets.py', 'BRUSH_MIGRATION_ASSETS_OK', ('disabled',)),
    ('migration-fresh', 'test_brush_migration_assets.py', 'BRUSH_MIGRATION_ASSETS_OK', ('verify',)),
)
RUNTIME = (
    ('settings', 'test_brush_stroke_settings.py', 'PLAN6_STROKE_SETTINGS_PASS', ()),
    ('semantics', 'test_property_native_semantics.py', 'PLAN6_NATIVE_SEMANTICS_PASS', ()),
    ('execution', 'test_brush_runtime.py', 'PLAN6_RUNTIME_HOST_PASS', ()),
    ('automask', 'test_brush_automasking.py', 'PLAN6_GENERIC_AUTOMASK_HOST_PASS', ()),
    ('readiness', 'test_property_execution_readiness.py', 'PLAN6_EXECUTION_READINESS_PASS', ()),
    ('cache', 'test_property_curves.py', 'PLAN5_CURVES_PASSED', ()),
    ('basic-baseline', 'test_brush_frozen_basic.py', 'PLAN6_GENERIC_FROZEN_BASIC_PASS', ()),
)
GESTURES = tuple((name.lower(), 'test_brush_strokes.py', 'PLAN6_GENERIC_MODAL_PASS', (name,))
                 for name in ('DRAW', 'SMOOTH', 'GRAB', 'SNAKE_HOOK', 'MASK', 'PROGRAM', 'VIEW', 'CLAY')) + tuple(
    (name, 'test_brush_routes.py', 'PLAN6_' + name.upper() + '_MODAL_PASS', (name,))
    for name in ('preview', 'dyntopo', 'cage', 'layer', 'attributes')) + (
        ('cache', 'test_brush_curve_cache.py', 'PLAN5_MODAL_CACHE_PASS', ('generic',)),)
SUITES = dict(unit=UNIT, authoring=AUTHORING, runtime=RUNTIME, gestures=GESTURES,
              **{'known-falloff': (('frozen-footprint', 'test_brush_frozen_footprint.py',
                                    'PLAN6_GENERIC_BASELINE_PASS', ()),)})
DEPENDENCIES = {'native-fresh': ('native',), 'frozen-fresh': ('frozen',)}
DEPENDENCIES.update({'migration-disabled': ('migration-assets',), 'migration-fresh': ('migration-disabled',)})
for _name in ('scalars', 'stacks', 'positions', 'curves'):
    DEPENDENCIES[_name + '-resave'] = (_name,)
    DEPENDENCIES[_name + '-reload'] = (_name + '-resave',)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=(*SUITES, 'native'), default='unit')
    parser.add_argument('--case', action='append', help='Run selected cases, including required fixture preparation')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--dev-engine', action='store_true',
                        help='Run Blender cases on the engine checkout build (run_blender_test.py --dev-engine)')
    args = parser.parse_args()
    if args.list:
        for suite, cases in SUITES.items():
            print(suite + ': ' + ', '.join(case[0] for case in cases))
        print('native: engine dispatcher regression suites')
        return 0
    if args.suite == 'native':
        if args.case:
            parser.error('Use run_typed_engine_gate.py --suite to select a native binary')
        return subprocess.call([sys.executable, str(SCRIPTS / 'run_typed_engine_gate.py'),
                                '--prefix', 'brush-native', '--extended-registration', '--named-storage',
                                '--compiler-boundaries', '--configuration', '--prepared-execution',
                                '--preview', '--dyntopo', '--attributes', '--semantic'], cwd=ROOT)
    cases = SUITES[args.suite]
    if args.case:
        unknown = set(args.case) - {case[0] for case in cases}
        if unknown:
            parser.error('Unknown cases: ' + ', '.join(sorted(unknown)))
        selected = set(args.case)
        if args.suite == 'authoring':
            while True:
                expanded = selected | {dependency for name in selected for dependency in DEPENDENCIES.get(name, ())}
                if expanded == selected:
                    break
                selected = expanded
        cases = tuple(case for case in cases if case[0] in selected)
    (ROOT / 'claudeMemory/tests').mkdir(exist_ok=True)
    failed = []
    for name, script, marker, extra in cases:
        command = [sys.executable, str(SCRIPTS / script)]
        if marker:
            command = [sys.executable, str(SCRIPTS / 'run_blender_test.py'), '--script',
                       str(SCRIPTS / script), '--prefix', 'brush-' + args.suite + '-' + name,
                       '--marker', marker, '--timeout', '180']
            if args.blender:
                command += ['--blender', str(args.blender)]
            if args.dev_engine:
                command.append('--dev-engine')
            if args.suite == 'gestures':
                command.append('--headed')
            if extra:
                command += ['--args', *extra]
        print('RUN ' + args.suite + '/' + name, flush=True)
        if subprocess.call(command, cwd=ROOT):
            failed.append(name)
    print('FAILED: ' + ', '.join(failed) if failed else 'PASS: ' + args.suite, flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
