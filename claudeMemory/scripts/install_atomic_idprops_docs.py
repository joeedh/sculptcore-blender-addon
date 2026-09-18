# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Publish the atomic scalar API manual without rewriting built source files."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
fork = Path('C:/dev/blender/main/doc/python_api')
shutil.copyfile(root / 'implementation/atomic_idprops/info_atomic_id_properties.rst',
                fork / 'rst/info_atomic_id_properties.rst')
path = fork / 'sphinx_doc_gen.py'
text = path.read_text(encoding='utf-8')
entry = '    (Path("info_atomic_id_properties.rst"),\n     "Atomic scalar custom-property authoring and metadata updates."),\n'
if entry not in text:
    marker = '    (Path("info_api_reference.rst"),'
    assert text.count(marker) == 1
    path.write_text(text.replace(marker, entry + marker), encoding='utf-8', newline='\n')
print('ATOMIC_IDPROPS_DOCS_INSTALLED')
