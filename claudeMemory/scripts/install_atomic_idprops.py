# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed native atomic scalar API without touching unrelated edits."""
from pathlib import Path
import re
import shutil

root = Path(__file__).resolve().parents[1]
fork = Path('C:/dev/blender/main')
intern = fork / 'source/blender/python/intern'
for name in ('bpy_rna_idprops.cc', 'bpy_rna_idprops.hh'):
    shutil.copyfile(root / 'implementation/atomic_idprops' / name, intern / name)


def patch(path, before, after):
    data = path.read_text(encoding='utf-8')
    if after in data:
        return
    assert data.count(before) == 1, (path, before)
    path.write_text(data.replace(before, after), encoding='utf-8', newline='\n')


for extension in ('cc', 'hh'):
    before = '  bpy_rna_id_collection.' + extension + '\n'
    patch(intern / 'CMakeLists.txt', before, before + '  bpy_rna_idprops.' + extension + '\n')
patch(intern / 'bpy_rna_types_capi.cc', '#include "bpy_rna_id_collection.hh"',
      '#include "bpy_rna_id_collection.hh"\n#include "bpy_rna_idprops.hh"')
patch(intern / 'bpy_rna_types_capi.cc', 'static PyMethodDef pyrna_blenddata_methods[] = {',
      'static PyMethodDef pyrna_id_methods[] = {\n'
      '    {nullptr, nullptr, 0, nullptr},\n    {nullptr, nullptr, 0, nullptr},\n};\n\n'
      'static PyMethodDef pyrna_blenddata_methods[] = {')
patch(intern / 'bpy_rna_types_capi.cc', '  /* BlendData */\n',
      '  ARRAY_SET_ITEMS(pyrna_id_methods, BPY_rna_id_properties_update_atomic_method_def);\n'
      '  pyrna_struct_type_extend_capi(RNA_ID, pyrna_id_methods, nullptr);\n\n  /* BlendData */\n')
generic = fork / 'source/blender/python/generic'
patch(generic / 'idprop_py_ui_api.hh', 'void IDPropertyUIData_Init_Types();',
      'PyObject *BPy_IDPropertyUIData_update(IDProperty *property, PyObject *kwargs);\n'
      'PyObject *BPy_IDPropertyUIData_as_dict(IDProperty *property);\n\nvoid IDPropertyUIData_Init_Types();')
helper = '''PyObject *BPy_IDPropertyUIData_update(IDProperty *property, PyObject *kwargs)
{
  BPy_IDPropertyUIManager manager{};
  manager.property = property;
  PyObject *args = PyTuple_New(0);
  if (args == nullptr) { return nullptr; }
  PyObject *result;
  if (IDP_ui_data_type(property) == IDP_UI_DATA_TYPE_INT) {
    IDP_ui_data_ensure(property);
    result = idprop_ui_data_update_int(property, args, kwargs, true) ? Py_NewRef(Py_None) : nullptr;
  }
  else {
    result = BPy_IDPropertyUIManager_update(&manager, args, kwargs);
  }
  Py_DECREF(args);
  return result;
}

PyObject *BPy_IDPropertyUIData_as_dict(IDProperty *property)
{
  if (property->ui_data == nullptr) { Py_RETURN_NONE; }
  const char *identifier = nullptr;
  if (!RNA_enum_identifier(rna_enum_property_subtype_items, property->ui_data->rna_subtype, &identifier)) {
    PyErr_SetString(PyExc_ValueError, "Invalid existing UI subtype; data preserved");
    return nullptr;
  }
  BPy_IDPropertyUIManager manager{};
  manager.property = property;
  return BPy_IDIDPropertyUIManager_as_dict(&manager);
}

'''
path = generic / 'idprop_py_ui_api.cc'
data = path.read_text(encoding='utf-8')
end = data.index('static PyMethodDef BPy_IDPropertyUIManager_methods[] = {')
start = data.find('PyObject *BPy_IDPropertyUIData_update(')
start = end if start < 0 else start
data = data[:start] + helper + data[end:]
data, count = re.subn(
    r'static bool idprop_ui_data_update_int\(IDProperty \*idprop,\s*PyObject \*args,\s*PyObject \*kwargs(?:,\s*bool preserve_enum = false)?\)',
    'static bool idprop_ui_data_update_int(IDProperty *idprop, PyObject *args, PyObject *kwargs, bool preserve_enum = false)', data)
assert count == 1
path.write_text(data, encoding='utf-8', newline='\n')

# Keep ordinary UIManager behavior unchanged while preserving opaque enum
# metadata in the atomic API, which deliberately cannot author enum items.
patch(generic / 'idprop_py_ui_api.cc',
      '  else {\n    ui_data.enum_items = nullptr;\n    ui_data.enum_items_num = 0;\n  }',
      '  else if (!preserve_enum) {\n    ui_data.enum_items = nullptr;\n    ui_data.enum_items_num = 0;\n  }')
print('ATOMIC_IDPROPS_INSTALLED')
