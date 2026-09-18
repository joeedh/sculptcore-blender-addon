# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install double-preserving Python event extensions in the Blender fork."""
from pathlib import Path

root = Path('C:/dev/blender/main')
updates = {}


def edit(name, old, new):
    path = root / name
    text = updates.get(path, path.read_text(encoding='utf-8'))
    if text.count(old) != 1:
        raise RuntimeError('{}: unexpected match count for {!r}'.format(name, old[:70]))
    updates[path] = text.replace(old, new)


wm = 'source/blender/python/intern/bpy_rna_wm.cc'
edit(wm, '#include <cstring>', '#include <cstring>\n#include <cmath>\n#include <limits>')
edit(wm, '#include "WM_api.hh"', '#include "WM_api.hh"\n#include "WM_types.hh"\n#include "wm_event_types.hh"')
code = r'''
/* -------------------------------------------------------------------- */
/** \name Event acquisition metadata
 * \{ */

static PyObject *bpy_rna_event_time_get(PyObject *self, void * /*closure*/)
{
  BPy_StructRNA *pyrna = reinterpret_cast<BPy_StructRNA *>(self);
  PYRNA_STRUCT_CHECK_OBJ(pyrna);
  const wmEvent *event = static_cast<const wmEvent *>(pyrna->ptr->data);
  return PyFloat_FromDouble(event->input_time);
}

PyGetSetDef BPY_rna_event_time_getset_def = {
    "time", bpy_rna_event_time_get, nullptr,
    "Monotonic acquisition seconds as a double; check has_time before use", nullptr};

static PyObject *bpy_rna_window_event_simulate_input(PyObject *self,
                                                   PyObject *args,
                                                   PyObject *kwds)
{
  BPy_StructRNA *pyrna = reinterpret_cast<BPy_StructRNA *>(self);
  PYRNA_STRUCT_CHECK_OBJ(pyrna);
  PyObject *legacy = kwds ? PyDict_Copy(kwds) : PyDict_New();
  if (!legacy) {
    return nullptr;
  }
  const char *names[] = {"time", "pressure", "tilt_x", "tilt_y"};
  double values[] = {0.0, 1.0, 0.0, 0.0};
  bool present[] = {false, false, false, false};
  bool tablet = false;
  PyObject *tablet_arg = PyDict_GetItemString(legacy, "tablet");
  if (tablet_arg) {
    if (!PyBool_Check(tablet_arg)) {
      Py_DECREF(legacy);
      PyErr_SetString(PyExc_TypeError, "tablet must be a bool");
      return nullptr;
    }
    tablet = tablet_arg == Py_True;
    PyDict_DelItemString(legacy, "tablet");
  }
  for (int i = 0; i < 4; i++) {
    PyObject *arg = PyDict_GetItemString(legacy, names[i]);
    if (arg && arg != Py_None) {
      if (PyBool_Check(arg) || (!PyFloat_Check(arg) && !PyLong_Check(arg))) {
        Py_DECREF(legacy);
        PyErr_Format(PyExc_TypeError, "%s must be a number or None", names[i]);
        return nullptr;
      }
      values[i] = PyFloat_AsDouble(arg);
      if (PyErr_Occurred()) {
        Py_DECREF(legacy);
        return nullptr;
      }
      const double lo = i < 2 ? 0.0 : -1.0;
      const double hi = i == 0 ? std::numeric_limits<double>::max() : 1.0;
      if (!std::isfinite(values[i]) || values[i] < lo || values[i] > hi) {
        Py_DECREF(legacy);
        PyErr_Format(PyExc_ValueError, "%s is outside its finite input domain", names[i]);
        return nullptr;
      }
      present[i] = true;
    }
    if (arg) {
      PyDict_DelItemString(legacy, names[i]);
    }
  }
  if (!tablet && (present[1] || present[2] || present[3])) {
    Py_DECREF(legacy);
    PyErr_SetString(PyExc_ValueError, "Tablet samples require tablet=True");
    return nullptr;
  }
  /* Validate every extension argument before the existing simulator queues anything. */
  PyObject *method = PyObject_GetAttrString(self, "event_simulate");
  PyObject *result = method ? PyObject_Call(method, args, legacy) : nullptr;
  Py_XDECREF(method);
  Py_DECREF(legacy);
  if (!result) {
    return nullptr;
  }
  if (!BPy_StructRNA_Check(result)) {
    Py_DECREF(result);
    PyErr_SetString(PyExc_RuntimeError, "event_simulate did not return an Event");
    return nullptr;
  }
  auto *event = static_cast<wmEvent *>(reinterpret_cast<BPy_StructRNA *>(result)->ptr->data);
  event->input_time = values[0];
  event->has_input_time = present[0];
  event->tablet.active = tablet ? EVT_TABLET_STYLUS : EVT_TABLET_NONE;
  event->tablet.pressure = float(values[1]);
  event->tablet.tilt = float2(float(values[2]), float(values[3]));
  event->tablet.is_motion_absolute = tablet;
  event->tablet.input_presence = (present[1] ? 1 : 0) | (present[2] ? 2 : 0) |
                                 (present[3] ? 4 : 0);
  if (event->type == MOUSEMOVE) {
    WM_event_retire_mousemove(event->prev);
  }
  return result;
}

PyMethodDef BPY_rna_window_event_simulate_input_method_def = {
    "event_simulate_input",
    reinterpret_cast<PyCFunction>(bpy_rna_window_event_simulate_input),
    METH_VARARGS | METH_KEYWORDS,
    "event_simulate_input(*, time=None, tablet=False, pressure=None, tilt_x=None, "
    "tilt_y=None, **event_arguments)\n\n"
    "Queue an input event with explicit acquisition time and optional tablet channels. "
    "Uses event_simulate arguments and requires --enable-event-simulate. Consecutive "
    "moves follow the native INBETWEEN_MOUSEMOVE queue policy. Omitted channels "
    "are unavailable; zero is a valid sample."};

/** \} */

'''
edit(wm, '}  // namespace blender\n', code + '}  // namespace blender\n')
edit('source/blender/python/intern/bpy_rna_wm.hh',
     'extern PyMethodDef BPY_rna_window_screenshot_method_def;',
     'extern PyMethodDef BPY_rna_window_screenshot_method_def;\nextern PyMethodDef BPY_rna_window_event_simulate_input_method_def;\nextern PyGetSetDef BPY_rna_event_time_getset_def;')
capi = 'source/blender/python/intern/bpy_rna_types_capi.cc'
edit(capi, '''static PyMethodDef pyrna_window_methods[] = {
    {nullptr, nullptr, 0, nullptr}, /* #BPY_rna_window_screenshot_method_def */''', '''static PyGetSetDef pyrna_event_getset[] = {
    {nullptr, nullptr, nullptr, nullptr, nullptr}, /* #BPY_rna_event_time_getset_def */
    {nullptr, nullptr, nullptr, nullptr, nullptr},
};

static PyMethodDef pyrna_window_methods[] = {
    {nullptr, nullptr, 0, nullptr}, /* #BPY_rna_window_event_simulate_input_method_def */
    {nullptr, nullptr, 0, nullptr}, /* #BPY_rna_window_screenshot_method_def */''')
edit(capi, '''  ARRAY_SET_ITEMS(pyrna_window_methods, BPY_rna_window_screenshot_method_def);
  BLI_STATIC_ASSERT(ARRAY_SIZE(pyrna_window_methods) == 2, "Unexpected number of methods")''', '''  ARRAY_SET_ITEMS(pyrna_window_methods,
                  BPY_rna_window_screenshot_method_def,
                  BPY_rna_window_event_simulate_input_method_def);
  BLI_STATIC_ASSERT(ARRAY_SIZE(pyrna_window_methods) == 3, "Unexpected number of methods")
  ARRAY_SET_ITEMS(pyrna_event_getset, BPY_rna_event_time_getset_def);
  pyrna_struct_type_extend_capi(RNA_Event, nullptr, pyrna_event_getset);''')
for path, text in updates.items():
    path.write_text(text, encoding='utf-8', newline='\n')
print('Updated {} Python event API files'.format(len(updates)))
