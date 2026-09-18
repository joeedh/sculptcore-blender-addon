# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed persistent Python ObjectModeType base and stage it."""
from pathlib import Path
import shutil

source = Path('C:/dev/blender/main/scripts/modules/_bpy_types.py')
target = Path('C:/dev/blender/build_windows_x64_clang_RelWithDebInfo/bin/5.3/scripts/modules/_bpy_types.py')
text = source.read_text(encoding='utf-8')
anchor = 'class RenderEngine(_StructRNA, metaclass=_RNAMeta):'
addition = 'class ObjectModeType(_StructRNA, metaclass=_RNAMeta):\n    __slots__ = ()\n\n\n'
if addition not in text:
    assert text.count(anchor) == 1
    source.write_text(text.replace(anchor, addition + anchor), encoding='utf-8', newline='\n')
shutil.copy2(source, target)
print('OBJECT_MODE_BASE_STAGED')
