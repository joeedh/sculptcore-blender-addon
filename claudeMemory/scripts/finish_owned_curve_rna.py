# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply reviewed RNA boundary checks after installing the initial RNA layer."""
import runpy
from pathlib import Path
import re

helpers = runpy.run_path(str(Path(__file__).with_name("owned_curve_patch_helpers.py")))
replace, start, function_text = (helpers[key] for key in ("replace", "start", "function_text"))
bpy, color, access = (helpers[key] for key in ("bpy", "color", "access"))

for function in ("pyrna_owned_curve_error", "pyrna_pointer_validity_check_only"):
    text = bpy.read_text()
    matches = list(re.finditer(r"(?m)^[\w :*&]+\b" + function + r"\([^;]*?\)\n\{", text))
    for match in reversed(matches[1:]):
        end = text.find("\n}\n", match.end()) + 3
        text = text[:match.start()] + text[end:]
    bpy.write_text(text, newline="\n")

for name in ("rna_CurveMap_new_point", "rna_CurveMap_remove_point", "rna_CurveMapping_evaluateF",
             "rna_CurveMapping_update", "rna_CurveMap_initialize", "rna_CurveMapping_reset_view"):
    def signature(body):
        body = body.replace("bContext *C, PointerRNA *ptr", "PointerRNA self, bContext *C")
        body = body.replace("(PointerRNA *ptr", "(PointerRNA self")
        if "PointerRNA *ptr = &self;" not in body:
            body = body.replace("\n{", "\n{\n  PointerRNA *ptr = &self;", 1)
        return body
    function_text(color, name, signature)

replace(bpy, '#include "RNA_owned_curve.hh"', '#include "RNA_owned_curve.hh"\n#include <cmath>')
numeric = r'''
/** Normalize once, before generic RNA conversion can clamp NaN/Inf or overflow. */
static PyObject *pyrna_owned_curve_number(PyObject *value, const bool array)
{
  if (array) {
    PyObject *sequence = PySequence_Fast(value, "Expected a numeric sequence");
    if (!sequence) { return nullptr; }
    const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
    PyObject *result = PyTuple_New(size);
    if (!result) { Py_DECREF(sequence); return nullptr; }
    for (Py_ssize_t i = 0; i < size; i++) {
      PyObject *item = pyrna_owned_curve_number(PySequence_Fast_GET_ITEM(sequence, i), false);
      if (!item) { Py_DECREF(sequence); Py_DECREF(result); return nullptr; }
      PyTuple_SET_ITEM(result, i, item);
    }
    Py_DECREF(sequence);
    return result;
  }
  const double number = PyFloat_AsDouble(value);
  if (PyErr_Occurred()) { return nullptr; }
  if (!std::isfinite(number) || std::abs(number) > FLT_MAX) {
    PyErr_SetString(PyExc_ValueError, "Owned CurveMapping requires finite float32 numbers");
    return nullptr;
  }
  return PyFloat_FromDouble(number);
}
struct OwnedCurvePyNumber {
  PyObject *value = nullptr;
  ~OwnedCurvePyNumber() { Py_XDECREF(value); }
};

'''
replace(bpy, "int pyrna_pointer_validity_check_only(const PointerRNA *ptr)",
        numeric + "int pyrna_pointer_validity_check_only(const PointerRNA *ptr)")
replace(bpy, "  FunctionRNA *self_func = self->func;\n  OwnedCurveRNAErrorScope owned_scope;",
        "  FunctionRNA *self_func = self->func;\n  OwnedCurveRNAErrorScope owned_scope;\n"
        "  owned_scope.require_finite_numbers = bool(self_ptr->owned_curve);")
function_text(bpy, "pyrna_py_to_prop", lambda body: body if "OwnedCurvePyNumber normalized;" in body else body.replace(
    "  const int type = RNA_property_type(prop);",
    "  const int type = RNA_property_type(prop);\n  OwnedCurvePyNumber normalized;\n"
    "  if (type == PROP_FLOAT && (ptr->owned_curve || OwnedCurveRNAErrorScope::finite_numbers_required())) {\n"
    "    normalized.value = pyrna_owned_curve_number(value, RNA_property_array_check(prop));\n"
    "    if (!normalized.value) { return -1; }\n    value = normalized.value;\n  }"))
function_text(bpy, "pyrna_py_to_prop_array_index", lambda body: body if "OwnedCurvePyNumber normalized;" in body else body.replace(
    "  PropertyRNA *prop = self->prop;",
    "  PropertyRNA *prop = self->prop;\n  OwnedCurvePyNumber normalized;\n"
    "  if (ptr->owned_curve && RNA_property_type(prop) == PROP_FLOAT) {\n"
    "    normalized.value = pyrna_owned_curve_number(value, false);\n"
    "    if (!normalized.value) { return -1; }\n    value = normalized.value;\n  }"))
def slice_normalization(body):
    first = body.index("\n{") + 2
    last = body.index("  OwnedCurveRNAErrorScope owned_scope;", first)
    code = "\n  const bool owned_target = bool(ptr->owned_curve);\n  OwnedCurvePyNumber normalized;\n"
    code += "  if (value_orig && owned_target && RNA_property_type(prop) == PROP_FLOAT) {\n"
    code += "    normalized.value = pyrna_owned_curve_number(value_orig, true);\n"
    code += "    if (!normalized.value) { return -1; }\n    value_orig = normalized.value;"
    code += "\n    if (owned_target && (!ptr->has_type() || !ptr->owned_curve || pyrna_pointer_validity_check_only(ptr) < 0)) {\n"
    code += '      PyErr_SetString(PyExc_ReferenceError, "Owned curve changed during numeric conversion");\n'
    code += "      return -1;\n    }\n  }\n"
    return body[:first] + code + body[last:]
function_text(bpy, "prop_subscript_ass_array_slice", slice_normalization)
for name in ("mathutils_rna_vector_set", "mathutils_rna_vector_set_index"):
    def finite_vector(body):
        if "Owned curve mathutils values must be finite" in body:
            return body
        return body.replace("  PYRNA_PROP_CHECK_INT(self);", "  PYRNA_PROP_CHECK_INT(self);\n"
                            "  if (self->ptr->owned_curve) {\n"
                            "    const int size = RNA_property_array_length(&self->ptr.value(), self->prop);\n"
                            "    for (int i = 0; i < size; i++) {\n"
                            "      if (!std::isfinite(bmo->data[i])) {\n"
                            '        PyErr_SetString(PyExc_ValueError, "Owned curve mathutils values must be finite");\n'
                            "        return -1;\n      }\n    }\n  }")
    function_text(bpy, name, finite_vector)
start(bpy, "pyprop_array_foreach_getset", "  if (self->ptr->owned_curve) {\n"
      '    PyErr_SetString(PyExc_TypeError, "Owned curve arrays do not support foreach_get/set");\n'
      "    return nullptr;\n  }")
replace(bpy, "        if (*newptr_p) {\n          ret = pyrna_struct_CreatePyObject(newptr_p);",
        "        if (newptr_p->owned_curve) {\n          OwnedCurveRNAErrorScope scope;\n"
        "          if (!RNA_owned_curve_validate(*newptr_p)) { pyrna_owned_curve_error(scope); return nullptr; }\n"
        "        }\n        if (*newptr_p) {\n          ret = pyrna_struct_CreatePyObject(newptr_p);")
for name in ("RNA_property_collection_raw_array", "RNA_property_collection_raw_get", "RNA_property_collection_raw_set"):
    start(access, name, "  if (ptr->owned_curve) {\n"
          "    OwnedCurveRNAErrorScope::report(OwnedCurveRNAError::Invalid, \"Owned curves do not support raw collection access\");\n"
          "    return 0;\n  }")

# Conversion may execute arbitrary Python that deletes the owner or declaration.
for name in ("pyrna_py_to_prop", "pyrna_py_to_prop_array_index", "prop_subscript_ass_array_slice"):
    def validate_normalized(body):
        marker = "    value_orig = normalized.value;" if name == "prop_subscript_ass_array_slice" else "    value = normalized.value;"
        check = ("\n    if (owned_target && (!ptr->has_type() || !ptr->owned_curve || pyrna_pointer_validity_check_only(ptr) < 0)) {\n"
                 '      PyErr_SetString(PyExc_ReferenceError, "Owned curve changed during numeric conversion");\n'
                 "      return -1;\n    }")
        if check in body:
            return body
        body = body.replace("  OwnedCurvePyNumber normalized;", "  const bool owned_target = bool(ptr->owned_curve);\n  OwnedCurvePyNumber normalized;")
        return body.replace(marker, marker + check)
    function_text(bpy, name, validate_normalized)
replace(bpy, "    RNA_function_call(C, &reports, self_ptr, self_func, &parms);",
        "    const bool owned_call = owned_scope.require_finite_numbers;\n"
        "    owned_scope.require_finite_numbers = false;\n"
        "    if (owned_call && (!self_ptr->has_type() || !self_ptr->owned_curve ||\n"
        "                       !RNA_owned_curve_validate(*self_ptr))) {\n"
        "      OwnedCurveRNAErrorScope::report(OwnedCurveRNAError::Stale, \"Owned curve changed during argument conversion\");\n"
        "    }\n    else { RNA_function_call(C, &reports, self_ptr, self_func, &parms); }")
replace(bpy, '      err = pyrna_py_to_prop(&funcptr, parm, iter.data, item, "");',
        '      err = pyrna_py_to_prop(&funcptr, parm, iter.data, item, "");\n'
        "      if (owned_scope.require_finite_numbers && (!self_ptr->has_type() || !self_ptr->owned_curve ||\n"
        "          pyrna_pointer_validity_check_only(self_ptr) < 0)) {\n"
        '        PyErr_SetString(PyExc_ReferenceError, "Owned curve changed during argument conversion");\n'
        "        err = -1;\n        break;\n      }")
props = helpers["props"]
replace(props, '  if (!srna) { return deferred_result; }\n  BPy_PropIDParse id_data{};',
        '  if (!srna) { return deferred_result; }\n'
        '  if (!RNA_struct_is_ID(srna) && !RNA_struct_is_a(srna, RNA_PropertyGroup)) {\n'
        '    PyErr_SetString(PyExc_TypeError, "CurveMappingProperty requires an ID or PropertyGroup declaration");\n'
        '    return nullptr;\n  }\n  BPy_PropIDParse id_data{};')
function_text(bpy, "pyrna_py_to_prop", lambda body: body if "Owned curve changed during boolean conversion" in body else body.replace(
    "        if (param == -1) {",
    "        if (owned_target && (!ptr->has_type() || !ptr->owned_curve || pyrna_pointer_validity_check_only(ptr) < 0)) {\n"
    '          PyErr_SetString(PyExc_ReferenceError, "Owned curve changed during boolean conversion");\n'
    "          return -1;\n        }\n        if (param == -1) {", 1))

for filename in ("mathutils_Vector.cc", "mathutils_Color.cc"):
    path = helpers["FORK"] / "source/blender/python/mathutils" / filename
    text = path.read_text()
    pattern = r"  \(void\)BaseMath_WriteCallback\((\w+)\);[^\n]*"
    for match in reversed(list(re.finditer(pattern, text))):
        tail = text[match.end():text.index("\n}", match.end())]
        result = "-1" if "return 0;" in tail else "nullptr"
        checked = "  if (BaseMath_WriteCallback({}) == -1) {{ return {}; }}".format(match[1], result)
        text = text[:match.start()] + checked + text[match.end():]
    path.write_text(text, newline="\n")
