# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the owned-curve RNA layer into the authorized companion fork."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT.parent / "main"
RNA = FORK / "source/blender/makesrna"
PY = FORK / "source/blender/python/intern"


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    assert text.count(old) == 1, (path.name, old, text.count(old))
    path.write_text(text.replace(old, new), newline="\n")


def start(path, function, code):
    text = path.read_text()
    pattern = r"(?m)^[\w :*&]+\b" + function + r"\([^;]*?\)\n\{"
    matches = list(re.finditer(pattern, text))
    assert len(matches) == 1, (path.name, function, len(matches))
    index = matches[0].end()
    body_end = text.find("\n}\n", index)
    if code in text[matches[0].start():body_end]:
        return
    path.write_text(text[:index] + "\n" + code + text[index:], newline="\n")


for source, destination in (
    ("RNA_owned_curve.hh", RNA / "RNA_owned_curve.hh"),
    ("rna_owned_curve.cc", RNA / "intern/rna_owned_curve.cc"),
):
    destination.write_bytes((ROOT / "claudeMemory/implementation" / source).read_bytes())

types = RNA / "RNA_types.hh"
replace(types, "#include <optional>", "#include <memory>\n#include <optional>")
replace(types, "namespace blender {\n\nstruct BlenderRNA;",
        "namespace blender {\n\nnamespace rna { class OwnedCurveHandle; }\n\nstruct BlenderRNA;")
replace(types, "  void *data = nullptr;", "  void *data = nullptr;\n\n"
        "  /** Retains owned-curve views independently of saved IDProperty storage. */\n"
        "  std::shared_ptr<rna::OwnedCurveHandle> owned_curve;")
replace(RNA / "intern/rna_internal_types.hh", "  PROP_INTERN_RNA_DEFINITION = (1 << 7),",
        "  PROP_INTERN_RNA_DEFINITION = (1 << 7),\n  PROP_INTERN_OWNED_CURVE = (1 << 8),")
replace(RNA / "intern/CMakeLists.txt", "  rna_access.cc\n", "  rna_access.cc\n  rna_owned_curve.cc\n")
replace(RNA / "intern/CMakeLists.txt", "  ../RNA_access.hh\n", "  ../RNA_access.hh\n  ../RNA_owned_curve.hh\n")

access = RNA / "intern/rna_access.cc"
replace(access, '#include "RNA_access.hh"', '#include "RNA_access.hh"\n#include "RNA_owned_curve.hh"')
replace(access, "    rna_pointer_refine(r_ptr);", "    rna_pointer_refine(r_ptr);\n    RNA_owned_curve_inherit(parent, r_ptr);")
replace(access, "if (idprop != nullptr && !rna_idproperty_verify_valid(ptr, prop, idprop))",
        "if (idprop != nullptr && !RNA_property_is_owned_curve(prop) &&\n"
        "          !rna_idproperty_verify_valid(ptr, prop, idprop))")
start(access, "property_pointer_get", "  if (!RNA_owned_curve_validate(*ptr)) { return {}; }\n"
      "  if (RNA_property_is_owned_curve(prop)) { return RNA_owned_curve_get(*ptr, *prop); }")
start(access, "RNA_property_pointer_set", "  if (RNA_property_is_owned_curve(prop)) {\n"
      "    OwnedCurveRNAErrorScope::report(OwnedCurveRNAError::Invalid,\n"
      '      "Assign owned curve fields or explicitly initialize/unset the property");\n'
      "    return;\n  }")
start(access, "RNA_property_pointer_add", "  if (RNA_property_is_owned_curve(prop)) {\n"
      "    RNA_owned_curve_initialize(*ptr, prop->identifier.c_str(), \"LINEAR\", nullptr);\n    return;\n  }")
for function in ("RNA_property_pointer_remove", "RNA_property_unset"):
    start(access, function, "  if (RNA_property_is_owned_curve(prop)) {\n"
          "    RNA_owned_curve_unset(*ptr, *prop, nullptr);\n    return;\n  }")
start(access, "rna_property_update", "  if (ptr->owned_curve) { RNA_owned_curve_update(C, *ptr); return; }\n"
      "  if (RNA_property_is_owned_curve(prop)) { return; }")

for function, default in (
    ("RNA_property_boolean_get", "false"), ("RNA_property_float_get", "0.0f"),
    ("RNA_property_enum_get", "0"), ("RNA_property_collection_length", "0"),
    ("RNA_property_collection_lookup_int", "false"),
):
    start(access, function, "  if (!RNA_owned_curve_validate(*ptr)) { return " + default + "; }")
start(access, "RNA_property_float_get_array", "  if (!RNA_owned_curve_validate(*ptr)) {\n"
      "    std::fill_n(values, RNA_property_array_length(ptr, prop), 0.0f);\n    return;\n  }")
for function in ("RNA_property_boolean_set", "RNA_property_float_set", "RNA_property_enum_set"):
    start(access, function, "  if (ptr->owned_curve) {\n    const double number = double(value);\n"
          "    RNA_owned_curve_set(*ptr, *prop, &number, 1);\n    return;\n  }")
start(access, "RNA_property_float_set_array", "  if (ptr->owned_curve) {\n"
      "    const int size = RNA_property_array_length(ptr, prop);\n"
      "    Array<double> numbers(size);\n"
      "    for (int i = 0; i < size; i++) { numbers[i] = values[i]; }\n"
      "    RNA_owned_curve_set(*ptr, *prop, numbers.data(), size);\n    return;\n  }")
start(access, "RNA_property_collection_begin", "  if (!RNA_owned_curve_validate(*ptr)) { *iter = {}; return; }\n"
      "  PointerRNA owned_parent;\n"
      "  if (ptr->owned_curve) { owned_parent = *ptr; RNA_owned_curve_pin(owned_parent); ptr = &owned_parent; }")
start(access, "RNA_property_collection_next", "  if (!RNA_owned_curve_validate(iter->parent)) { iter->valid = false; return; }")
replace(access, "if (num > 1 && (iter->idprop || (cprop->flag_internal & PROP_INTERN_RAW_ARRAY)))",
        "if (!iter->parent.owned_curve && num > 1 && (iter->idprop || (cprop->flag_internal & PROP_INTERN_RAW_ARRAY)))")

define = RNA / "intern/rna_define.cc"
replace(define, '#include "RNA_define.hh"', '#include "RNA_define.hh"\n#ifdef RNA_RUNTIME\n#  include "RNA_owned_curve.hh"\n#endif')
start(define, "RNA_def_property_free_pointers", "#ifdef RNA_RUNTIME\n  RNA_owned_curve_declaration_removed(prop);\n#endif")
replace(RNA / "RNA_define.hh", "void RNA_def_property_free_pointers(PropertyRNA *prop);",
        "void RNA_def_property_free_pointers(PropertyRNA *prop);\nvoid RNA_def_property_owned_curve(PropertyRNA *prop);")
replace(define, "void RNA_def_property_free_pointers(PropertyRNA *prop)",
        "void RNA_def_property_owned_curve(PropertyRNA *prop)\n{\n"
        "  prop->flag_internal |= PROP_INTERN_OWNED_CURVE;\n}\n\n"
        "void RNA_def_property_free_pointers(PropertyRNA *prop)")

props = PY / "bpy_props.cc"
replace(props, "static PyObject *pymeth_PointerProperty = nullptr;",
        "static PyObject *pymeth_PointerProperty = nullptr;\nstatic PyObject *pymeth_CurveMappingProperty = nullptr;")
factory = r'''
PyDoc_STRVAR(BPy_CurveMappingProperty_doc,
             "CurveMappingProperty(*, name='', description='', update=None)\n"
             "Declare a lazily initialized owner-aware scalar CurveMapping.");
static PyObject *BPy_CurveMappingProperty(PyObject *self, PyObject *args, PyObject *kw)
{
  PyObject *deferred_result;
  StructRNA *srna = bpy_prop_deferred_data_or_srna(
      self, args, kw, pymeth_CurveMappingProperty, &deferred_result);
  if (!srna) { return deferred_result; }
  BPy_PropIDParse id_data{};
  id_data.srna = srna;
  const char *name = nullptr, *description = "";
  PyObject *update_fn = nullptr;
  static const char *keywords[] = {"attr", "name", "description", "update", nullptr};
  static _PyArg_Parser parser = {"O&|$ssO:CurveMappingProperty", keywords, nullptr};
  if (!_PyArg_ParseTupleAndKeywordsFast(args, kw, &parser, bpy_prop_arg_parse_id, &id_data,
                                       &name, &description, &update_fn)) { return nullptr; }
  if (bpy_prop_callback_check(update_fn, "update", 2) == -1) { return nullptr; }
  if (id_data.prop_free_handle) {
    RNA_def_property_free_identifier_deferred_finish(srna, id_data.prop_free_handle);
  }
  PropertyRNA *prop = RNA_def_pointer_runtime(
      srna, id_data.value, RNA_CurveMapping, name ? name : id_data.value, description);
  RNA_def_property_owned_curve(prop);
  RNA_def_property_flag(prop, PROP_EDITABLE);
  RNA_def_property_clear_flag(prop, PROP_ANIMATABLE);
  bpy_prop_callback_assign_update(prop, update_fn);
  RNA_def_property_duplicate_pointers(srna, prop);
  Py_RETURN_NONE;
}

'''
replace(props, "PyObject *BPy_PointerProperty(PyObject *self, PyObject *args, PyObject *kw)",
        factory + "PyObject *BPy_PointerProperty(PyObject *self, PyObject *args, PyObject *kw)")
replace(props, '    {"PointerProperty",', '    {"CurveMappingProperty",\n'
        '     reinterpret_cast<PyCFunction>(BPy_CurveMappingProperty),\n'
        '     METH_VARARGS | METH_KEYWORDS, BPy_CurveMappingProperty_doc},\n    {"PointerProperty",')
replace(props, "  ASSIGN_STATIC(PointerProperty);", "  ASSIGN_STATIC(PointerProperty);\n  ASSIGN_STATIC(CurveMappingProperty);")
replace(props, "  py_func = prop_store->py_data.update_fn;", "  py_func = prop_store->py_data.update_fn;\n  Py_INCREF(py_func);")
replace(props, "  bpy_context_clear(C, &gilstate);\n}\n\n/** \\} */\n\n/* -------------------------------------------------------------------- */\n/** \\name Boolean Property Callbacks",
        "  Py_DECREF(py_func);\n  bpy_context_clear(C, &gilstate);\n}\n\n/** \\} */\n\n/* -------------------------------------------------------------------- */\n/** \\name Boolean Property Callbacks")

bpy = PY / "bpy_rna.cc"
replace(bpy, '#include "RNA_access.hh"', '#include "RNA_access.hh"\n#include "RNA_owned_curve.hh"')
helpers = r'''
static int pyrna_owned_curve_error(const OwnedCurveRNAErrorScope &scope)
{
  if (scope.code == OwnedCurveRNAError::None) { return 0; }
  PyObject *type = scope.code == OwnedCurveRNAError::Stale ? PyExc_ReferenceError :
                   scope.code == OwnedCurveRNAError::ReadOnly ? PyExc_PermissionError : PyExc_ValueError;
  PyErr_SetString(type, scope.message.c_str());
  return -1;
}
int pyrna_pointer_validity_check_only(const PointerRNA *ptr)
{
  OwnedCurveRNAErrorScope scope;
  return ptr->has_type() && RNA_owned_curve_validate(*const_cast<PointerRNA *>(ptr)) ? 0 : -1;
}

'''
replace(bpy, "int pyrna_struct_validity_check_only(const BPy_StructRNA *pysrna)",
        helpers + "int pyrna_struct_validity_check_only(const BPy_StructRNA *pysrna)")
# Both struct validity functions and the property check must refresh before data/owner access.
text = bpy.read_text().replace("if (pysrna->ptr->has_type()) {", "if (pyrna_pointer_validity_check_only(&pysrna->ptr.value()) == 0) {")
text = text.replace("if (self->ptr->has_type()) {\n    return 0;\n  }\n  PyErr_Format(PyExc_ReferenceError,",
                    "if (pyrna_pointer_validity_check_only(&self->ptr.value()) == 0) {\n    return 0;\n  }\n  PyErr_Format(PyExc_ReferenceError,")
bpy.write_text(text, newline="\n")
header = PY / "bpy_rna.hh"
replace(header, "#define PYRNA_STRUCT_IS_VALID(pysrna) (LIKELY(((BPy_StructRNA *)(pysrna))->ptr->has_type()))",
        "#define PYRNA_STRUCT_IS_VALID(pysrna) (pyrna_pointer_validity_check_only(&((BPy_StructRNA *)(pysrna))->ptr.value()) == 0)")
replace(header, "#define PYRNA_PROP_IS_VALID(pysrna) (LIKELY(((BPy_PropertyRNA *)(pysrna))->ptr->has_type()))",
        "#define PYRNA_PROP_IS_VALID(pysrna) (pyrna_pointer_validity_check_only(&((BPy_PropertyRNA *)(pysrna))->ptr.value()) == 0)")
replace(header, "[[nodiscard]] int pyrna_struct_validity_check_only(const BPy_StructRNA *pysrna);",
        "[[nodiscard]] int pyrna_struct_validity_check_only(const BPy_StructRNA *pysrna);\n"
        "[[nodiscard]] int pyrna_pointer_validity_check_only(const PointerRNA *ptr);")
text = bpy.read_text().replace("(a->ptr->data == b->ptr->data)", "RNA_owned_curve_equal(a->ptr.value(), b->ptr.value())")
bpy.write_text(text, newline="\n")
# Hashes stay stable as mapping/channel views refresh.
text = bpy.read_text()
hash_expression = "(self->ptr->owned_curve ? Py_hash_t(RNA_owned_curve_hash(self->ptr.value()) >> 4) : Py_HashPointer(self->ptr->data))"
while hash_expression in text:
    text = text.replace(hash_expression, "Py_HashPointer(self->ptr->data)")
text = text.replace("Py_HashPointer(self->ptr->data)", hash_expression)
bpy.write_text(text, newline="\n")
replace(bpy, "      newptr = RNA_property_pointer_get(ptr, prop);",
        "      OwnedCurveRNAErrorScope owned_scope;\n"
        "      newptr = RNA_property_pointer_get(ptr, prop);\n"
        "      if (pyrna_owned_curve_error(owned_scope) < 0) { return nullptr; }")

for function in ("pyrna_py_to_prop", "pyrna_py_to_prop_array_index", "mathutils_rna_vector_set",
                 "mathutils_rna_vector_set_index", "prop_subscript_ass_array_slice"):
    start(bpy, function, "  OwnedCurveRNAErrorScope owned_scope;")
# Insert before the corresponding update points, within each function body only.
def function_text(path, function, transform):
    text = path.read_text()
    match = re.search(r"(?m)^[\w :*&]+\b" + function + r"\([^;]*?\)\n\{", text)
    assert match, function
    next_function = text.find("\n}\n", match.end()) + 3
    body = text[match.start():next_function]
    changed = transform(body).rstrip() + "\n\n"
    path.write_text(text[:match.start()] + changed + text[next_function:], newline="\n")

for function in ("pyrna_py_to_prop", "pyrna_py_to_prop_array_index", "mathutils_rna_vector_set",
                 "mathutils_rna_vector_set_index", "prop_subscript_ass_array_slice"):
    def add_error(body):
        if "pyrna_owned_curve_error(owned_scope)" in body:
            return body
        index = body.find("  if (RNA_property_update_check(")
        if index < 0 and function == "prop_subscript_ass_array_slice":
            index = body.rfind("  return ")
        assert index >= 0, function
        return body[:index] + "  if (pyrna_owned_curve_error(owned_scope) < 0) { return -1; }\n" + body[index:]
    function_text(bpy, function, add_error)

replace(bpy, "  FunctionRNA *self_func = self->func;\n\n  ParameterList parms;",
        "  FunctionRNA *self_func = self->func;\n"
        "  OwnedCurveRNAErrorScope owned_scope;\n"
        "  if (!self_ptr->has_type()) { PyErr_SetString(PyExc_ReferenceError, \"RNA function owner was removed\"); return nullptr; }\n"
        "  if (!RNA_owned_curve_validate(*self_ptr)) { pyrna_owned_curve_error(owned_scope); return nullptr; }\n\n"
        "  ParameterList parms;")
replace(bpy, "    err = BPy_reports_to_error(&reports, PyExc_RuntimeError, true);",
        "    err = BPy_reports_to_error(&reports, PyExc_RuntimeError, true);\n"
        "    if (pyrna_owned_curve_error(owned_scope) < 0) { err = -1; }")
start(bpy, "foreach_getset", "  if (self->ptr->owned_curve) {\n"
      '    PyErr_SetString(PyExc_TypeError, "Owned curve collections do not support foreach_get/set");\n'
      "    return nullptr;\n  }")
replace(bpy, "  if (self_property->iter->valid == false) {",
        "  OwnedCurveRNAErrorScope owned_scope;\n"
        "  if (self_property->iter.has_value() && !RNA_owned_curve_validate(self_property->iter->parent)) {\n"
        "    pyrna_owned_curve_error(owned_scope); return nullptr;\n  }\n"
        "  if (!self_property->iter.has_value() || self_property->iter->valid == false) {")

methods = r'''
static PyObject *pyrna_struct_curve_mapping_initialize(BPy_StructRNA *self, PyObject *args, PyObject *kw)
{
  PYRNA_STRUCT_CHECK_OBJ(self);
  const char *path, *preset = "LINEAR";
  static const char *keywords[] = {"property", "preset", nullptr};
  if (!PyArg_ParseTupleAndKeywords(args, kw, "s|$s:curve_mapping_initialize",
                                   const_cast<char **>(keywords), &path, &preset)) { return nullptr; }
  OwnedCurveRNAErrorScope scope;
  PointerRNA result = RNA_owned_curve_initialize(self->ptr.value(), path, preset, BPY_context_get());
  if (pyrna_owned_curve_error(scope) < 0) { return nullptr; }
  if (!RNA_owned_curve_validate(result)) { pyrna_owned_curve_error(scope); return nullptr; }
  return pyrna_struct_CreatePyObject(&result);
}
static PyObject *pyrna_struct_curve_mapping_sync(BPy_StructRNA *self, PyObject *args)
{
  PYRNA_STRUCT_CHECK_OBJ(self);
  const char *path;
  if (!PyArg_ParseTuple(args, "s:curve_mapping_sync", &path)) { return nullptr; }
  OwnedCurveRNAErrorScope scope;
  RNA_owned_curve_sync(self->ptr.value(), path, BPY_context_get());
  if (pyrna_owned_curve_error(scope) < 0) { return nullptr; }
  Py_RETURN_NONE;
}

'''
replace(bpy, "static PyObject *pyrna_struct_property_unset(BPy_StructRNA *self, PyObject *args)",
        methods + "static PyObject *pyrna_struct_property_unset(BPy_StructRNA *self, PyObject *args)")
replace(bpy, "  RNA_property_unset(&self->ptr.value(), prop);",
        "  if (RNA_property_is_owned_curve(prop)) {\n    OwnedCurveRNAErrorScope scope;\n"
        "    RNA_owned_curve_unset(self->ptr.value(), *prop, BPY_context_get());\n"
        "    if (pyrna_owned_curve_error(scope) < 0) { return nullptr; }\n"
        "  } else { RNA_property_unset(&self->ptr.value(), prop); }")
replace(bpy, '    {"property_unset",',
        '    {"curve_mapping_initialize", reinterpret_cast<PyCFunction>(pyrna_struct_curve_mapping_initialize),\n'
        '     METH_VARARGS | METH_KEYWORDS, "Initialize an owned scalar curve property."},\n'
        '    {"curve_mapping_sync", reinterpret_cast<PyCFunction>(pyrna_struct_curve_mapping_sync),\n'
        '     METH_VARARGS, "Validate raw owned curve edits and notify the owner."},\n'
        '    {"property_unset",')

color = RNA / "intern/rna_color.cc"
color.write_text(color.read_text().replace("}static ", "}\n\nstatic "), newline="\n")
replace(color, '#  include "RNA_access.hh"', '#  include "RNA_access.hh"\n#  include "RNA_owned_curve.hh"')
function_text(color, "rna_CurveMap_new_point", lambda body: r'''static PointerRNA rna_CurveMap_new_point(bContext *C, PointerRNA *ptr, float position, float value)
{
  if (ptr->owned_curve) { return RNA_owned_curve_point_new(*ptr, position, value, C); }
  CurveMapPoint *point = BKE_curvemap_insert(static_cast<CurveMap *>(ptr->data), position, value);
  if (point) { rna_CurveMapping_notify_owner(ptr->owner_id); }
  return RNA_pointer_create_with_parent(*ptr, RNA_CurveMapPoint, point);
}''')
function_text(color, "rna_CurveMap_remove_point", lambda body: r'''static void rna_CurveMap_remove_point(bContext *C, PointerRNA *ptr, ReportList *reports, PointerRNA *point_ptr)
{
  if (ptr->owned_curve) { RNA_owned_curve_point_remove(*ptr, *point_ptr, C); return; }
  if (point_ptr->owned_curve) { BKE_report(reports, RPT_ERROR, "Point is from an owned curve"); return; }
  if (!BKE_curvemap_remove_point(static_cast<CurveMap *>(ptr->data),
                                 static_cast<CurveMapPoint *>(point_ptr->data))) {
    BKE_report(reports, RPT_ERROR, "Unable to remove curve point"); return;
  }
  point_ptr->invalidate();
  rna_CurveMapping_notify_owner(ptr->owner_id);
}''')
function_text(color, "rna_CurveMapping_evaluateF", lambda body: r'''static float rna_CurveMapping_evaluateF(PointerRNA *ptr, ReportList *reports, PointerRNA *curve_ptr, float value)
{
  if (ptr->owned_curve) { return RNA_owned_curve_evaluate(*ptr, *curve_ptr, value); }
  if (curve_ptr->owned_curve) { BKE_report(reports, RPT_ERROR, "Curve belongs to an owned mapping"); return 0; }
  CurveMapping *cumap = static_cast<CurveMapping *>(ptr->data);
  CurveMap *cuma = static_cast<CurveMap *>(curve_ptr->data);
  if (&cumap->cm[0] != cuma && &cumap->cm[1] != cuma && &cumap->cm[2] != cuma && &cumap->cm[3] != cuma) {
    BKE_report(reports, RPT_ERROR, "CurveMapping does not own CurveMap"); return 0;
  }
  if (!cuma->table) { BKE_curvemapping_init(cumap); }
  return BKE_curvemap_evaluateF(cumap, cuma, value);
}''')
function_text(color, "rna_CurveMapping_update", lambda body: r'''static void rna_CurveMapping_update(PointerRNA *ptr)
{
  if (ptr->owned_curve) { RNA_owned_curve_validate(*ptr); return; }
  BKE_curvemapping_changed_all(static_cast<CurveMapping *>(ptr->data));
  rna_CurveMapping_notify_owner(ptr->owner_id);
}''')
function_text(color, "rna_CurveMap_initialize", lambda body: r'''static void rna_CurveMap_initialize(PointerRNA *ptr)
{
  if (ptr->owned_curve) { RNA_owned_curve_validate(*ptr); return; }
  BKE_curvemapping_init(static_cast<CurveMapping *>(ptr->data));
}''')
if "static void rna_CurveMapping_reset_view(" not in color.read_text():
    replace(color, "static void rna_CurveMap_initialize(PointerRNA *ptr)", r'''static void rna_CurveMapping_reset_view(PointerRNA *ptr)
{
  if (ptr->owned_curve) { RNA_owned_curve_reset_view(*ptr); return; }
  BKE_curvemapping_reset_view(static_cast<CurveMapping *>(ptr->data));
}

static void rna_CurveMap_initialize(PointerRNA *ptr)''')
replace(color, '  func = RNA_def_function(srna, "new", "rna_CurveMap_new_point");\n  RNA_def_function_flag(func, FUNC_USE_SELF_ID);',
        '  func = RNA_def_function(srna, "new", "rna_CurveMap_new_point");\n  RNA_def_function_flag(func, FUNC_SELF_AS_RNA | FUNC_USE_CONTEXT);')
replace(color, '  parm = RNA_def_pointer(func, "point", "CurveMapPoint", "", "New point");\n  RNA_def_parameter_flags(parm, PROP_NEVER_NULL, ParameterFlag(0));',
        '  parm = RNA_def_pointer(func, "point", "CurveMapPoint", "", "New point");\n  RNA_def_parameter_flags(parm, PROP_THICK_WRAP, PARM_RNAPTR);')
replace(color, "  RNA_def_function_flag(func, FUNC_USE_SELF_ID | FUNC_USE_REPORTS);",
        "  RNA_def_function_flag(func, FUNC_SELF_AS_RNA | FUNC_USE_CONTEXT | FUNC_USE_REPORTS);")
replace(color, '  func = RNA_def_function(srna, "update", "rna_CurveMapping_update");\n  RNA_def_function_flag(func, FUNC_USE_SELF_ID);',
        '  func = RNA_def_function(srna, "update", "rna_CurveMapping_update");\n  RNA_def_function_flag(func, FUNC_SELF_AS_RNA);')
replace(color, '  func = RNA_def_function(srna, "reset_view", "BKE_curvemapping_reset_view");',
        '  func = RNA_def_function(srna, "reset_view", "rna_CurveMapping_reset_view");\n  RNA_def_function_flag(func, FUNC_SELF_AS_RNA);')
replace(color, '  func = RNA_def_function(srna, "initialize", "rna_CurveMap_initialize");',
        '  func = RNA_def_function(srna, "initialize", "rna_CurveMap_initialize");\n  RNA_def_function_flag(func, FUNC_SELF_AS_RNA);')
replace(color, '  func = RNA_def_function(srna, "evaluate", "rna_CurveMapping_evaluateF");\n  RNA_def_function_flag(func, FUNC_USE_REPORTS);',
        '  func = RNA_def_function(srna, "evaluate", "rna_CurveMapping_evaluateF");\n  RNA_def_function_flag(func, FUNC_SELF_AS_RNA | FUNC_USE_REPORTS);')
replace(color, '  parm = RNA_def_pointer(func, "curve", "CurveMap", "curve", "Curve to evaluate");\n  RNA_def_parameter_flags(parm, PROP_NEVER_NULL, PARM_REQUIRED);',
        '  parm = RNA_def_pointer(func, "curve", "CurveMap", "curve", "Curve to evaluate");\n  RNA_def_parameter_flags(parm, PROP_NEVER_NULL, PARM_REQUIRED | PARM_RNAPTR);\n  RNA_def_parameter_clear_flags(parm, PROP_THICK_WRAP, ParameterFlag(0));')

ui = FORK / "source/blender/editors/interface/templates/interface_template_curve_mapping.cc"
replace(ui, '#include "RNA_access.hh"', '#include "RNA_access.hh"\n#include "RNA_owned_curve.hh"')
replace(ui, "  if (!cptr || !RNA_struct_is_a(cptr.type, RNA_CurveMapping)) {",
        "  if (cptr.owned_curve) {\n    layout->label(IFACE_(\"Owned curve editor integration is pending\"), ICON_INFO);\n    return;\n  }\n"
        "  if (!cptr || !RNA_struct_is_a(cptr.type, RNA_CurveMapping)) {")
