# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Install the reviewed transactional owned curve dialog and graph hooks."""

from pathlib import Path

ROOT = Path("C:/dev/blender/main")


def edit(path, before, after):
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if after in source:
        return
    if source.count(before) != 1:
        raise RuntimeError("Expected one patch anchor in {}".format(path))
    target.write_text(source.replace(before, after), encoding="utf-8", newline="\n")


template = "source/blender/editors/interface/templates/interface_template_curve_mapping.cc"
header = "source/blender/editors/interface/interface_intern.hh"
handlers = "source/blender/editors/interface/interface_handlers.cc"
api = "source/blender/makesrna/intern/rna_ui_api.cc"
addition = (Path(__file__).parent.parent / "implementation/owned_curve_editor_ui.inc").read_text(encoding="utf-8")
edit(template, '#include "BKE_colortools.hh"', """#include <algorithm>
#include <cfloat>
#include <cmath>
#include <unordered_map>

#include "BKE_curvemapping_idprop.hh"
#include "BKE_idprop.hh"
#include "BKE_report.hh"
#include "RNA_define.hh"
#include "WM_api.hh"
#include "WM_types.hh"

#include "BKE_colortools.hh"
""".rstrip())
edit(template, "void template_curve_mapping(Layout *layout,", addition + "\nvoid template_curve_mapping(Layout *layout,")
edit(template, """  PointerRNA cptr = RNA_property_pointer_get(ptr, prop);
  if (cptr.owned_curve) {
    layout->label(IFACE_("Owned curve editor integration is pending"), ICON_INFO);
    return;
  }""", """  if (RNA_property_is_owned_curve(prop)) {
    if (ELEM(type, 'c', 'h', 'v') || levels || tone || neg_slope) {
      layout->label(IFACE_("Owned curves require scalar controls with positive presets"), ICON_ERROR);
      return;
    }
    template_owned_curve_mapping(layout, ptr, propname);
    return;
  }
  PointerRNA cptr = RNA_property_pointer_get(ptr, prop);""")
edit(header, "  CurveMapping *edit_cumap = nullptr;", """  CurveMapping *edit_cumap = nullptr;
  /** Owned graphs edit temporary storage and can cancel their containing transaction. */
  std::function<void()> owned_curve_cancel;
  std::function<bool(const CurveMapping &)> owned_curve_paste_validate;""")
edit(header, "void UI_OT_eyedropper_bone(wmOperatorType *ot);", """void UI_OT_owned_curve_edit(wmOperatorType *ot);
void UI_OT_eyedropper_bone(wmOperatorType *ot);""")
edit("source/blender/editors/interface/interface_ops.cc", "  WM_operatortype_append(UI_OT_copy_data_path_button);", """  WM_operatortype_append(UI_OT_owned_curve_edit);
  WM_operatortype_append(UI_OT_copy_data_path_button);""")
edit("source/blender/editors/include/UI_interface_c.hh", "void template_curve_mapping(Layout *layout,", """void template_owned_curve_mapping(Layout *layout, PointerRNA *ptr, StringRefNull path);
void template_curve_mapping(Layout *layout,""")
edit(api, '  func = RNA_def_function(srna, "template_curve_mapping", "template_curve_mapping");', """  func = RNA_def_function(srna, "template_owned_curve_mapping", "template_owned_curve_mapping");
  RNA_def_function_ui_description(func, "Draw an owned scalar curve without creating missing property groups");
  parm = RNA_def_pointer(func, "data", "AnyType", "", "ID or declared PropertyGroup owner");
  RNA_def_parameter_flags(parm, PROP_NEVER_NULL, PARM_REQUIRED | PARM_RNAPTR);
  parm = RNA_def_string(func, "path", nullptr, 0, "", "Declared property path with numeric collection indices");
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);

  func = RNA_def_function(srna, "template_curve_mapping", "template_curve_mapping");""")
edit(handlers, """  if (but_copypaste_curve_alive && but->poin != nullptr) {
    button_activate_state(C, but, BUTTON_STATE_NUM_EDITING);""", """  if (but_copypaste_curve_alive && but->poin != nullptr) {
    auto *curve_but = static_cast<ButtonCurveMapping *>(but);
    if (curve_but->owned_curve_paste_validate &&
        !curve_but->owned_curve_paste_validate(but_copypaste_curve))
    {
      ED_region_tag_redraw(CTX_wm_region(C));
      return;
    }
    button_activate_state(C, but, BUTTON_STATE_NUM_EDITING);""")

target = ROOT / handlers
source = target.read_text(encoding="utf-8")
start = source.index("static int do_but_CURVE(")
end = source.index("/* Same as numedit_but_CURVE", start)
part = source[start:end]
if "curve_but->owned_curve_cancel" not in part:
    part = part.replace("  bool changed = false;", """  auto *curve_but = static_cast<ButtonCurveMapping *>(but);
  bool changed = false;""", 1)
    part = part.replace("      if (event->modifier & KM_CTRL) {", """      if ((event->modifier & KM_CTRL) &&
          (!curve_but->owned_curve_cancel || cuma->totpoint < 32767)) {""", 1)
    part = part.replace("      if (sel == -1) {", """      if (sel == -1 && (!curve_but->owned_curve_cancel || cuma->totpoint < 32767)) {""", 1)
    part = part.replace("  else if (data->state == BUTTON_STATE_NUM_EDITING) {", """  else if (data->state == BUTTON_STATE_NUM_EDITING) {
    if (curve_but->owned_curve_cancel && ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE) &&
        event->val == KM_PRESS)
    {
      curve_but->owned_curve_cancel();
      data->cancel = true;
      if (block->handle) {
        block->handle->menuretval = RETURN_CANCEL;
      }
      button_activate_state(C, but, BUTTON_STATE_EXIT);
      return WM_UI_HANDLER_BREAK;
    }""", 1)
    target.write_text(source[:start] + part + source[end:], encoding="utf-8", newline="\n")
