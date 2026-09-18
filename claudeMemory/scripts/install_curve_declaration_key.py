# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed non-reused owned CurveMapping declaration identity."""
from pathlib import Path

ROOT = Path('C:/dev/blender/main')


def edit(path, before, after):
    target = ROOT / path
    source = target.read_text(encoding='utf-8')
    if after in source:
        return
    assert source.count(before) == 1, path
    target.write_text(source.replace(before, after), encoding='utf-8', newline='\n')


HEADER = 'source/blender/makesrna/RNA_owned_curve.hh'
RNA = 'source/blender/makesrna/intern/rna_owned_curve.cc'
PROPS = 'source/blender/python/intern/bpy_props.cc'
edit(HEADER, 'void RNA_owned_curve_declaration_removed(PropertyRNA *prop);', '''void RNA_owned_curve_declaration_removed(PropertyRNA *prop);
/** Process-local declaration lifetime identity; does not access or allocate owner data. */
bool RNA_owned_curve_declaration_key(PropertyRNA *prop, uint64_t &key);''')
edit(RNA, 'struct CurveDeclaration {\n  PropertyRNA *property;', '''struct CurveDeclaration {
  PropertyRNA *property;
  uint64_t identity = 0;''')
edit(RNA, 'void RNA_owned_curve_declaration_removed(PropertyRNA *prop)\n{', '''bool RNA_owned_curve_declaration_key(PropertyRNA *prop, uint64_t &key)
{
  if (!main_thread() || !RNA_property_is_owned_curve(prop)) {
    return fail("Expected a directly declared owned CurveMapping property");
  }
  /* Never reset across unregister, load or undo; zero permanently marks exhaustion. */
  static uint64_t next_identity = 1;
  auto token = declaration(prop);
  if (token->identity == 0) {
    if (next_identity == 0) {
      return fail("Owned CurveMapping declaration identity exhausted");
    }
    token->identity = next_identity++;
  }
  key = token->identity;
  return true;
}

void RNA_owned_curve_declaration_removed(PropertyRNA *prop)
{''')
edit(PROPS, '#include "BLI_listbase.hh"', '#include "BLI_listbase.hh"\n#include "BLI_threads.hh"')
edit(PROPS, '#include "RNA_enum_types.hh"', '#include "RNA_enum_types.hh"\n#include "RNA_owned_curve.hh"')
edit(PROPS, 'PyDoc_STRVAR(\n    BPy_CurveMappingProperty_doc,', '''PyDoc_STRVAR(
    BPy_curve_mapping_declaration_key_doc,
    ".. function:: curve_mapping_declaration_key(type, identifier)\\n"
    "\\n"
    "   Return a positive process-local lifetime key for a directly declared owned curve.\\n"
    "   Main thread only. Missing, inherited-only and non-owned properties raise ValueError.\\n"
    "   Re-registration always creates a new key; no owner storage is allocated.\\n"
    "   Keys are runtime-only and must not be serialized.\\n");
static PyObject *BPy_curve_mapping_declaration_key(PyObject * /*self*/, PyObject *args)
{
  if (!BLI_thread_is_main()) {
    PyErr_SetString(PyExc_RuntimeError, "Curve declaration access requires the main thread");
    return nullptr;
  }
  PyObject *type, *identifier;
  if (!PyArg_ParseTuple(args, "OO:curve_mapping_declaration_key", &type, &identifier)) {
    return nullptr;
  }
  if (!PyType_Check(type) ||
      !PyType_IsSubtype(reinterpret_cast<PyTypeObject *>(type), &pyrna_struct_Type) ||
      reinterpret_cast<PyTypeObject *>(type)->tp_dict == nullptr || !PyUnicode_CheckExact(identifier)) {
    PyErr_SetString(PyExc_TypeError, "Expected an RNA type and an exact string identifier");
    return nullptr;
  }
  Py_ssize_t length;
  const char *name = PyUnicode_AsUTF8AndSize(identifier, &length);
  if (!name) {
    return nullptr;
  }
  if (length == 0 || memchr(name, 0, size_t(length))) {
    PyErr_SetString(PyExc_ValueError, "Identifier must be nonempty without NUL");
    return nullptr;
  }
  PyObject *value = PyDict_GetItemString(reinterpret_cast<PyTypeObject *>(type)->tp_dict, "bl_rna");
  if (!value || !BPy_StructRNA_Check(value)) {
    PyErr_SetString(PyExc_TypeError, "Expected a registered RNA type");
    return nullptr;
  }
  auto *wrapper = reinterpret_cast<BPy_StructRNA *>(value);
  if (!wrapper->ptr.has_value()) {
    PyErr_SetString(PyExc_ReferenceError, "RNA type is no longer available");
    return nullptr;
  }
  if (pyrna_struct_validity_check(wrapper) == -1) {
    return nullptr;
  }
  if (wrapper->ptr->type != RNA_Struct || !wrapper->ptr->data) {
    PyErr_SetString(PyExc_TypeError, "Expected valid RNA type metadata");
    return nullptr;
  }
  StructRNA *srna = static_cast<StructRNA *>(wrapper->ptr->data);
  if (RNA_struct_py_type_get(srna) != type) {
    PyErr_SetString(PyExc_TypeError, "RNA metadata does not belong to this type");
    return nullptr;
  }
  PropertyRNA *prop = RNA_struct_type_find_property_no_base(srna, UString(name));
  OwnedCurveRNAErrorScope error;
  uint64_t key;
  if (!RNA_owned_curve_declaration_key(prop, key)) {
    PyErr_SetString(PyExc_ValueError, error.message.c_str());
    return nullptr;
  }
  return PyLong_FromUnsignedLongLong(key);
}

PyDoc_STRVAR(
    BPy_CurveMappingProperty_doc,''')
edit(PROPS, '    {"CurveMappingProperty",', '''    {"curve_mapping_declaration_key",
     BPy_curve_mapping_declaration_key,
     METH_VARARGS,
     BPy_curve_mapping_declaration_key_doc},
    {"CurveMappingProperty",''')
doc = ROOT / 'doc/python_api/rst/info_owned_curve_mapping.rst'
text = doc.read_text(encoding='utf-8')
if 'Declaration lifetime identity' not in text:
    doc.write_text(text + '''
Declaration lifetime identity
-----------------------------

``bpy.props.curve_mapping_declaration_key(type, identifier)`` returns a positive,
process-local integer for a directly declared owned CurveMapping property. Test
for this function explicitly: initial API version 1 builds predate it. The call
requires the main thread, an RNA Python type and an exact nonempty string without
NUL. Missing, inherited-only and non-owned properties raise ``ValueError``.
Runtime bookkeeping may be allocated, but no owner data is read or allocated.

The key remains stable while the declaration exists, including across owner
copy/load/undo. Removing and re-registering even the identical deferred property
produces a new key. It cannot be replaced by a PropertyRNA address or the mapping
cache key, both of which can survive or be reused across declaration changes.
Never serialize this key; combine it with owner and mapping lifetime checks.
''', encoding='utf-8', newline='\n')
