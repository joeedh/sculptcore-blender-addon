# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the owned-curve guide and add it to Blender's generated API index."""
from pathlib import Path

root = Path("C:/dev/blender/main/doc/python_api")
source = Path(__file__).resolve().parents[1] / "implementation/info_owned_curve_mapping.rst"
(root / "rst/info_owned_curve_mapping.rst").write_text(source.read_text(), encoding="utf-8", newline="\n")
generator = root / "sphinx_doc_gen.py"
text = generator.read_text(encoding="utf-8")
anchor = '    (Path("info_api_reference.rst"),'
entry = ('    (Path("info_owned_curve_mapping.rst"),\n'
         '     "Declaring, editing and caching scalar curves owned by data-blocks."),\n')
if entry not in text:
    assert text.count(anchor) == 1
    generator.write_text(text.replace(anchor, entry + anchor), encoding="utf-8", newline="\n")
