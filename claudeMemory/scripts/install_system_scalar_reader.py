# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install reviewed bounded nonmutating system-IDProperty scalar inspection."""
from pathlib import Path
import re

ROOT = Path('C:/dev/blender/main')


def edit(name, before, after):
    path = ROOT / name
    text = path.read_text(encoding='utf-8')
    if re.sub(r'\s+', '', after) in re.sub(r'\s+', '', text):
        return
    assert text.count(before) == 1, name
    path.write_text(text.replace(before, after), encoding='utf-8', newline='\n')


edit('source/blender/python/intern/bpy_rna_idprops.cc',
     'PyObject *update_atomic(BPy_StructRNA *self, PyObject *args)', '''PyObject *system_scalar(BPy_StructRNA *self, PyObject *args)
{
  GCGuard gc;
  if (!BLI_thread_is_main()) {
    PyErr_SetString(PyExc_RuntimeError, "System property inspection requires the main thread");
    return nullptr;
  }
  PyObject *path;
  if (!PyArg_ParseTuple(args, "O:system_property_scalar", &path)) {
    return nullptr;
  }
  if (!PyTuple_CheckExact(path) || PyTuple_GET_SIZE(path) < 1 || PyTuple_GET_SIZE(path) > 32) {
    error("Expected an exact path tuple containing 1..32 keys");
    return nullptr;
  }
  std::vector<std::string> keys;
  for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(path); i++) {
    std::string key;
    if (!key_string(PyTuple_GET_ITEM(path, i), key)) {
      return nullptr;
    }
    keys.push_back(std::move(key));
  }
  if (!self->ptr.has_value()) {
    PyErr_SetString(PyExc_ReferenceError, "ID is no longer available");
    return nullptr;
  }
  PYRNA_STRUCT_CHECK_OBJ(self);
  ID *owner = self->ptr->owner_id;
  if (!G_MAIN || !owner || self->ptr->data != owner || !RNA_struct_is_ID(self->ptr->type) ||
      !BKE_id_is_in_main(G_MAIN, owner) || (owner->tag & ID_TAG_COPIED_ON_EVAL)) {
    error("Expected an original ID in the current Main");
    return nullptr;
  }
  const IDProperty *property = owner->system_properties;
  for (const std::string &key : keys) {
    if (!property || (property->flag & IDP_FLAG_GHOST)) {
      return Py_BuildValue("(OOO)", Py_False, Py_None, Py_None);
    }
    if (property->type != IDP_GROUP) {
      error("System path ancestor is not a group; data preserved");
      return nullptr;
    }
    property = IDP_GetPropertyFromGroup(property, key.c_str());
  }
  if (!property || (property->flag & IDP_FLAG_GHOST)) {
    return Py_BuildValue("(OOO)", Py_False, Py_None, Py_None);
  }
  PyRef value;
  const char *type;
  switch (property->type) {
    case IDP_INT:
      type = "INT";
      value.reset(PyLong_FromLong(IDP_int_get(property)));
      break;
    case IDP_FLOAT:
      type = "FLOAT";
      value.reset(PyFloat_FromDouble(IDP_float_get(property)));
      break;
    case IDP_DOUBLE:
      type = "DOUBLE";
      value.reset(PyFloat_FromDouble(IDP_double_get(property)));
      break;
    case IDP_BOOLEAN:
      type = "BOOLEAN";
      value.reset(PyBool_FromLong(IDP_bool_get(property)));
      break;
    case IDP_STRING: {
      type = "STRING";
      if (property->subtype != IDP_STRING_SUB_UTF8 || property->len < 1 ||
          property->len > 1024 * 1024 + 1 || !IDP_string_get(property) ||
          IDP_string_get(property)[property->len - 1] != 0) {
        error("System string must be bounded UTF-8; data preserved");
        return nullptr;
      }
      value.reset(PyUnicode_DecodeUTF8(IDP_string_get(property), property->len - 1, "strict"));
      break;
    }
    default:
      error("System leaf is not a supported scalar; data preserved");
      return nullptr;
  }
  if (!value) {
    return nullptr;
  }
  return Py_BuildValue("(OsO)", Py_True, type, value.get());
}

PyObject *update_atomic(BPy_StructRNA *self, PyObject *args)''')
edit('source/blender/python/intern/bpy_rna_idprops.cc',
     'PyMethodDef BPY_rna_id_properties_update_atomic_method_def = {', '''PyMethodDef BPY_rna_system_property_scalar_method_def = {
    "system_property_scalar",
    reinterpret_cast<PyCFunction>(system_scalar),
    METH_VARARGS,
    "Inspect an original Main ID's raw system property scalar without allocation or repair. "
    "Exact path tuple, 1..32 keys of 1..63 UTF-8 bytes. Returns (present, type, value); "
    "missing or ghost paths return (False, None, None). Main thread only; read-only IDs allowed."};

PyMethodDef BPY_rna_id_properties_update_atomic_method_def = {''')
edit('source/blender/python/intern/bpy_rna_idprops.hh',
     'extern PyMethodDef BPY_rna_id_properties_update_atomic_method_def;',
     'extern PyMethodDef BPY_rna_id_properties_update_atomic_method_def;\n'
     'extern PyMethodDef BPY_rna_system_property_scalar_method_def;')
edit('source/blender/python/intern/bpy_rna_types_capi.cc',
     '''static PyMethodDef pyrna_id_methods[] = {
    {nullptr, nullptr, 0, nullptr},
    {nullptr, nullptr, 0, nullptr},
};''',
     '''static PyMethodDef pyrna_id_methods[] = {
    {nullptr, nullptr, 0, nullptr},
    {nullptr, nullptr, 0, nullptr},
    {nullptr, nullptr, 0, nullptr},
};
static_assert(ARRAY_SIZE(pyrna_id_methods) == 3);''')
edit('source/blender/python/intern/bpy_rna_types_capi.cc',
     'ARRAY_SET_ITEMS(pyrna_id_methods, BPY_rna_id_properties_update_atomic_method_def);',
     'ARRAY_SET_ITEMS(pyrna_id_methods, BPY_rna_id_properties_update_atomic_method_def, '
     'BPY_rna_system_property_scalar_method_def);')
path = ROOT / 'doc/python_api/rst/info_atomic_id_properties.rst'
text = path.read_text(encoding='utf-8')
if 'Nonmutating system scalar inspection' not in text:
    path.write_text(text + '''
Nonmutating system scalar inspection
-----------------------------------

``ID.system_property_scalar(path_tuple)`` reads raw declared-property backing
storage without RNA validation, repair, declaration access or owner allocation.
It returns a copied ``(present, type_name, value)`` triple. Missing or ghost paths
return ``(False, None, None)``; present malformed ancestors or unsupported leaves
raise without changing data. Supported types are INT, FLOAT, DOUBLE, BOOLEAN and
UTF-8 STRING (at most one MiB). Groups, arrays, byte strings and ID pointers are
not returned. The exact tuple contains 1..32 exact string keys, each 1..63 UTF-8
bytes without NUL. It requires the main thread and an original current-Main ID;
linked/read-only IDs are supported. It never sends update notifications.
''', encoding='utf-8', newline='\n')
