# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Install the reviewed exact owned-curve cache identity and API metadata."""

from pathlib import Path

root = Path("C:/dev/blender/main")


def edit(path, before, after):
    target = root / path
    source = target.read_text(encoding="utf-8")
    if after in source:
        return
    if source.count(before) != 1:
        raise RuntimeError("Expected one patch anchor in {}".format(path))
    target.write_text(source.replace(before, after), encoding="utf-8", newline="\n")


header = "source/blender/blenkernel/BKE_curvemapping_owned.hh"
native = "source/blender/blenkernel/intern/curvemapping_owned.cc"
rna_header = "source/blender/makesrna/RNA_owned_curve.hh"
rna = "source/blender/makesrna/intern/rna_owned_curve.cc"
python = "source/blender/python/intern/bpy_rna.cc"
props = "source/blender/python/intern/bpy_props.cc"

edit(header, "  uint64_t revision() const;", """  /** Process-local identity, independent of wrapper addresses and declaration generations. */
  uint64_t identity() const;
  uint64_t revision() const;""")
edit(native, "struct OwnedCurveRecord::State {", """/* Records are created only on the main thread. Never reset this on load or undo. */
static uint64_t next_record_identity = 1;

struct OwnedCurveRecord::State {
  const uint64_t identity = next_record_identity++;""")
edit(native, "uint64_t OwnedCurveRecord::revision() const", """uint64_t OwnedCurveRecord::identity() const
{
  BLI_assert(BLI_thread_is_main());
  BLI_assert(state_->identity != 0);
  return state_->identity;
}

uint64_t OwnedCurveRecord::revision() const""")
edit(rna_header, "bool RNA_owned_curve_validate(PointerRNA &ptr);", """bool RNA_owned_curve_validate(PointerRNA &ptr);
/** Validate and return immutable cache identity for a current owned mapping. */
bool RNA_owned_curve_cache_key(PointerRNA &ptr, uint64_t &identity, uint64_t &revision);""")
edit(rna, "void RNA_owned_curve_inherit(const PointerRNA &parent, PointerRNA &child)", """bool RNA_owned_curve_cache_key(PointerRNA &ptr, uint64_t &identity, uint64_t &revision)
{
  if (!main_thread()) {
    return false;
  }
  if (!ptr.has_type()) {
    return fail("Owned CurveMapping wrapper was removed", OwnedCurveRNAError::Stale);
  }
  if (!ptr.owned_curve || ptr.type != RNA_CurveMapping ||
      ptr.owned_curve->kind != CurveKind::Mapping)
  {
    return fail("Cache keys require an owned CurveMapping");
  }
  if (!RNA_owned_curve_validate(ptr)) {
    return false;
  }
  /* Validation may replace an unpinned handle with the current snapshot. */
  const auto &handle = *ptr.owned_curve;
  identity = handle.binding->record->identity();
  revision = handle.view->revision;
  return true;
}

void RNA_owned_curve_inherit(const PointerRNA &parent, PointerRNA &child)""")
edit(rna, "  auto result = record->sync(error);\n  if (!ELEM", """  auto result = record->sync(error);
  if (result == bke::OwnedCurveResult::Unchanged) {
    return;
  }
  if (!ELEM""")
edit(rna, '"Owned curve point or iterator belongs to an older revision"',
     '"Owned curve handle belongs to an older revision"')

docstrings = r'''PyDoc_STRVAR(pyrna_struct_curve_mapping_initialize_doc,
             ".. method:: curve_mapping_initialize(property, *, preset='LINEAR')\n"
             "\n"
             "   Initialize an owned scalar curve, staging absent pointer ancestors atomically.\n"
             "   Existing definitions are returned unchanged. Reading an unset property returns None.\n"
             "\n"
             "   :param property: Declared property path; collections require existing numeric indices.\n"
             "   :type property: str\n"
             "   :param preset: Initial preset; currently LINEAR only.\n"
             "   :type preset: str\n"
             "   :return: The owned curve.\n"
             "   :rtype: :class:`CurveMapping`\n");
PyDoc_STRVAR(pyrna_struct_curve_mapping_sync_doc,
             ".. method:: curve_mapping_sync(property, /)\n"
             "\n"
             "   Validate and publish raw owned-definition edits. Invalid data remains untouched.\n"
             "   Changed definitions notify their owner and callback; unchanged sync does neither.\n"
             "\n"
             "   :param property: Declared owned-curve path with existing numeric collection indices.\n"
             "   :type property: str\n");
PyDoc_STRVAR(pyrna_struct_curve_mapping_cache_key_doc,
             ".. method:: curve_mapping_cache_key()\n"
             "\n"
             "   Return a validated, immutable (runtime record identity, definition revision) key.\n"
             "   Only owned CurveMapping instances support this method. Call it before cache reuse.\n"
             "   Presentation/no-op edits preserve the key; committed definition edits advance it.\n"
             "   Keys are process-local and must not be saved or used after an access error.\n"
             "   New records after copy/load/unset have new identities; re-registration may reuse a record.\n"
             "\n"
             "   :return: Two exact unsigned integer values.\n"
             "   :rtype: tuple[int, int]\n");

static PyObject *pyrna_struct_curve_mapping_cache_key(BPy_StructRNA *self, PyObject * /*args*/)
{
  PYRNA_STRUCT_CHECK_OBJ(self);
  OwnedCurveRNAErrorScope scope;
  uint64_t identity, revision;
  if (!RNA_owned_curve_cache_key(self->ptr.value(), identity, revision)) {
    pyrna_owned_curve_error(scope);
    return nullptr;
  }
  PyObject *identity_object = PyLong_FromUnsignedLongLong(identity);
  if (!identity_object) {
    return nullptr;
  }
  PyObject *revision_object = PyLong_FromUnsignedLongLong(revision);
  if (!revision_object) {
    Py_DECREF(identity_object);
    return nullptr;
  }
  PyObject *result = PyTuple_Pack(2, identity_object, revision_object);
  Py_DECREF(identity_object);
  Py_DECREF(revision_object);
  return result;
}

'''
edit(python, "static PyObject *pyrna_struct_curve_mapping_initialize(BPy_StructRNA *self,",
     docstrings + "static PyObject *pyrna_struct_curve_mapping_initialize(BPy_StructRNA *self,")
edit(python, '     "Initialize an owned scalar curve property."},',
     "     pyrna_struct_curve_mapping_initialize_doc},")
edit(python, '     "Validate raw owned curve edits and notify the owner."},', """     pyrna_struct_curve_mapping_sync_doc},
    {"curve_mapping_cache_key",
     reinterpret_cast<PyCFunction>(pyrna_struct_curve_mapping_cache_key),
     METH_NOARGS,
     pyrna_struct_curve_mapping_cache_key_doc},""")
edit(props, '  submodule = PyModule_Create(&props_module);', """  submodule = PyModule_Create(&props_module);
  if (!submodule) {
    return nullptr;
  }
  if (PyModule_AddIntConstant(submodule, "owned_curve_mapping_api_version", 1) < 0) {
    Py_DECREF(submodule);
    return nullptr;
  }""")
target = root / props
text = target.read_text(encoding="utf-8")
start = text.index("PyDoc_STRVAR(BPy_CurveMappingProperty_doc,")
end = text.index("static PyObject *BPy_CurveMappingProperty(", start)
text = text[:start] + r'''PyDoc_STRVAR(BPy_CurveMappingProperty_doc,
             ".. function:: CurveMappingProperty(*, name='', description='', update=None)\n"
             "\n"
             "   Declare a lazily initialized, ID-owned scalar CurveMapping on an ID or PropertyGroup.\n"
             "   Values persist inside their owner, support deep copying and external brush assets,\n"
             "   and remain None until explicitly initialized. No node tree backs this property.\n"
             "   See the Owned Curve Mappings guide for lifecycle, caching and UI behavior.\n"
             "   Availability is reported by bpy.props.owned_curve_mapping_api_version.\n"
             "\n"
             "   :param name: Human-readable property name.\n"
             "   :type name: str\n"
             "   :param description: Tooltip text.\n"
             "   :type description: str\n"
             "   :param update: Optional callback (declaring_parent, context), after owner notification.\n"
             "   :type update: Callable | None\n"
             "   :return: Deferred property declaration for registration.\n"
             "   :rtype: _PropertyDeferred\n");
''' + text[end:]
target.write_text(text, encoding="utf-8", newline="\n")
