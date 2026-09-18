# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install documentation for the implemented explicit authoring boundary."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[2]
fork = Path('C:/dev/blender/main')
shutil.copy2(root / 'claudeMemory/implementation/info_property_authoring.rst',
             fork / 'doc/python_api/rst/info_property_authoring.rst')
path = fork / 'doc/python_api/sphinx_doc_gen.py'
text = path.read_text(encoding='utf-8')
anchor = '    (Path("info_atomic_id_properties.rst"),'
addition = ('    (Path("info_property_authoring.rst"),\n'
            '     "Explicit grouped Brush and Scene authoring, rollback and undo."),\n')
if addition not in text:
    assert text.count(anchor) == 1
    path.write_text(text.replace(anchor, addition + anchor), encoding='utf-8', newline='\n')
print('AUTHORING_DOCS_INSTALLED')
