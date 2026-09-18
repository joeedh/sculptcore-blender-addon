# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the delegated RNA result before treating it as an event."""
from pathlib import Path

path = Path('C:/dev/blender/main/source/blender/python/intern/bpy_rna_wm.cc')
text = path.read_text(encoding='utf-8')
text = text.replace('#include "WM_api.hh"', '#include "RNA_access.hh"\n#include "RNA_prototypes.hh"\n\n#include "WM_api.hh"')
old = '  if (!BPy_StructRNA_Check(result)) {'
new = '''  if (!BPy_StructRNA_Check(result) ||
      !reinterpret_cast<BPy_StructRNA *>(result)->ptr.has_value() ||
      !RNA_struct_is_a(reinterpret_cast<BPy_StructRNA *>(result)->ptr->type, RNA_Event) ||
      !reinterpret_cast<BPy_StructRNA *>(result)->ptr->data)
  {'''
assert text.count(old) == 1
path.write_text(text.replace(old, new), encoding='utf-8', newline='\n')
