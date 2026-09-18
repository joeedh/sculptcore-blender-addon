# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Load/resave raw authoring data with all generic authoring imports blocked."""
import importlib.abc
import json
from pathlib import Path
import sys
import addon_utils
import bpy

fixture = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'atomic'
directory, brush_name = {
    'atomic': ('plan4-atomic', 'AtomicSavedBrush'),
    'stacks': ('plan4-stacks', 'PersistentStackBrush'),
    'positions': ('plan4-positions', 'PersistentPositionsBrush'),
    'custom': ('plan4-custom', 'CustomStackBrush'),
}[fixture]
DIRECTORY = Path(__file__).resolve().parents[1] / 'tests' / directory
addon_utils.disable('sculptcore_addon', default_set=False)
prefixes = ('sculptcore_addon.brush_properties', 'generic_property_test_package')
for name in tuple(sys.modules):
    if name.startswith(prefixes):
        del sys.modules[name]


class NoAuthoring(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(prefixes):
            raise ImportError('Authoring modules deliberately unavailable')
        return None


sys.meta_path.insert(0, NoAuthoring())
bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / ('custom.blend' if fixture == 'custom' else 'records.blend')))
brush = bpy.data.brushes[brush_name]
before = brush['sculptcore_properties'].to_dict()
assert not any(name.startswith(prefixes) for name in sys.modules)
bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'without-authoring.blend'))
assert brush['sculptcore_properties'].to_dict() == before
assert not any(name.startswith(prefixes) for name in sys.modules)
(DIRECTORY / 'without-authoring-results.json').write_text(json.dumps(dict(
    passed=True, authoring_imports_blocked=True, addon_disabled=True,
    preserved_records=len(before['records'])), indent=2) + '\n')
print('ATOMIC_WITHOUT_AUTHORING_PASS', flush=True)
