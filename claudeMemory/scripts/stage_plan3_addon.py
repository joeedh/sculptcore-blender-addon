# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
import shutil
root = Path(__file__).resolve().parents[2]
source = root / 'sculptcore_addon'
target = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/scripts/addons_core/sculptcore_addon')
assert source.is_dir() and target.is_dir()
shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('lib', '__pycache__', '*.pyc'))
print('Staged addon Python:', target)
