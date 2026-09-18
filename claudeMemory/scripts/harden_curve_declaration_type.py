# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replace the reviewed declaration API with its hardened RNA type extraction."""
import ast
from pathlib import Path

template = Path(__file__).with_name('install_curve_declaration_key.py').read_text(encoding='utf-8')
for node in ast.walk(ast.parse(template)):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'edit'
            and len(node.args) == 3 and isinstance(node.args[2], ast.Constant)
            and 'static PyObject *BPy_curve_mapping_declaration_key' in str(node.args[2].value)):
        replacement = node.args[2].value
        break
else:
    raise AssertionError('Missing hardened template')
path = Path('C:/dev/blender/main/source/blender/python/intern/bpy_props.cc')
source = path.read_text(encoding='utf-8')
start = source.index('PyDoc_STRVAR(\n    BPy_curve_mapping_declaration_key_doc,')
end = source.index('PyDoc_STRVAR(\n    BPy_CurveMappingProperty_doc,', start)
replacement = replacement[:replacement.index('PyDoc_STRVAR(\n    BPy_CurveMappingProperty_doc,')]
path.write_text(source[:start] + replacement + source[end:], encoding='utf-8', newline='\n')
