/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

namespace {
struct OwnedCurveNumeric {
  uint64_t generation;
  int point;
  float coordinate[2];
};
struct OwnedCurveDialog {
  std::shared_ptr<rna::OwnedCurvePath> path;
  std::shared_ptr<rna::OwnedCurveEdit> edit;
  std::shared_ptr<OwnedCurveNumeric> numeric;
  uint64_t generation = 0;
  float clip[4] = {0, 0, 1, 1};
  bool use_clip = true;
  bool extrapolate = true;
  bool cancelled = false;
  std::string error;
};
using OwnedCurveDialogPtr = std::shared_ptr<OwnedCurveDialog>;
static std::unordered_map<int, OwnedCurveDialogPtr> owned_curve_tickets;
static int owned_curve_next_ticket = 1;

static OwnedCurveDialogPtr owned_curve_dialog_take(wmOperator *op)
{
  auto *holder = static_cast<OwnedCurveDialogPtr *>(op->customdata);
  if (!holder) {
    return nullptr;
  }
  OwnedCurveDialogPtr result = std::move(*holder);
  MEM_delete(holder);
  op->customdata = nullptr;
  return result;
}

static bool owned_curve_candidate_valid(const CurveMapping &mapping, std::string &error)
{
  IDProperty *encoded = BKE_curvemapping_to_idprop(mapping, "curve", nullptr, error);
  if (!encoded) {
    return false;
  }
  IDP_FreeProperty(encoded);
  return true;
}

static void owned_curve_dialog_changed(OwnedCurveDialog &session)
{
  session.generation++;
  session.error.clear();
  BKE_curvemapping_changed(&RNA_owned_curve_edit_mapping(*session.edit), false);
}

static Button *owned_curve_button(Block *block, const char *label)
{
  Button *button = uiDefBut(block, ButtonType::But, label, 0, 0,
                            4 * UI_UNIT_X, UI_UNIT_Y, nullptr, 0, 0, "");
  button->flag &= ~BUT_UNDO;
  return button;
}

static void owned_curve_dialog_draw(bContext * /*C*/, wmOperator *op)
{
  auto *holder = static_cast<OwnedCurveDialogPtr *>(op->customdata);
  if (!holder || !(*holder)->edit) {
    return;
  }
  const OwnedCurveDialogPtr session = *holder;
  CurveMapping &mapping = RNA_owned_curve_edit_mapping(*session->edit);
  CurveMap &curve = mapping.cm[0];
  Layout *layout = op->layout;
  Block *block = layout->block();

  layout->row(true);
  for (const auto &[label, preset] :
       {std::pair{"Linear", CURVE_PRESET_LINE}, {"Smooth", CURVE_PRESET_SMOOTH},
        {"Sharp", CURVE_PRESET_SHARP}, {"Round", CURVE_PRESET_ROUND}})
  {
    Button *button = owned_curve_button(block, IFACE_(label));
    button_func_set(button, [session, preset](bContext &) {
      CurveMapping &mapping = RNA_owned_curve_edit_mapping(*session->edit);
      BKE_curvemap_reset(&mapping.cm[0], &mapping.clipr, preset, CurveMapSlopeType::Positive);
      owned_curve_dialog_changed(*session);
    });
  }

  layout->row(false);
  auto *graph = static_cast<ButtonCurveMapping *>(uiDefBut(
      block, ButtonType::Curve, IFACE_("Edit Curve"), 0, 0, 16 * UI_UNIT_X,
      10 * UI_UNIT_Y, &mapping, 0, 1, ""));
  graph->flag &= ~BUT_UNDO;
  graph->owned_curve_cancel = [session]() { session->cancelled = true; };
  graph->owned_curve_paste_validate = [session](const CurveMapping &source) {
    if (source.cur != 0 || !std::isfinite(source.curr.xmin) ||
        !std::isfinite(source.curr.xmax) || !std::isfinite(source.curr.ymin) ||
        !std::isfinite(source.curr.ymax) || source.curr.xmin >= source.curr.xmax ||
        source.curr.ymin >= source.curr.ymax)
    {
      session->error = "Clipboard curve has an invalid scalar view";
      return false;
    }
    if (!owned_curve_candidate_valid(source, session->error)) {
      return false;
    }
    session->clip[0] = source.clipr.xmin;
    session->clip[1] = source.clipr.ymin;
    session->clip[2] = source.clipr.xmax;
    session->clip[3] = source.clipr.ymax;
    session->use_clip = source.flag & CUMA_DO_CLIP;
    session->extrapolate = source.flag & CUMA_EXTEND_EXTRAPOLATE;
    return true;
  };
  button_func_set(graph, [session](bContext &) { owned_curve_dialog_changed(*session); });

  int selected = -1;
  for (int i = 0; i < curve.totpoint; i++) {
    if (curve.curve[i].flag & CUMA_SELECT) {
      selected = i;
      if (curve.curve[i].flag & CUMA_ACTIVE) {
        break;
      }
    }
  }
  if (selected >= 0) {
    if (!session->numeric || session->numeric->generation != session->generation ||
        session->numeric->point != selected)
    {
      session->numeric = std::make_shared<OwnedCurveNumeric>(OwnedCurveNumeric{
          session->generation, selected, {curve.curve[selected].x, curve.curve[selected].y}});
    }
    const auto numeric = session->numeric;
    layout->row(true);
    for (int axis = 0; axis < 2; axis++) {
      Button *button = uiDefButV(block, ButtonType::Num, axis == 0 ? "X:" : "Y:",
                                 0, 0, 7 * UI_UNIT_X, UI_UNIT_Y, &numeric->coordinate[axis],
                                 -FLT_MAX, FLT_MAX, "");
      button->flag &= ~BUT_UNDO;
      button_number_precision_set(button, 5);
      button_func_set(button, [session, numeric](bContext &) {
        if (numeric != session->numeric || numeric->generation != session->generation) {
          session->error = "Point selection changed during numeric editing";
          return;
        }
        CurveMapping &mapping = RNA_owned_curve_edit_mapping(*session->edit);
        CurveMapping *candidate = BKE_curvemapping_copy(&mapping);
        auto &point = candidate->cm[0].curve[numeric->point];
        point.x = numeric->coordinate[0];
        point.y = numeric->coordinate[1];
        for (int i = 0; i < candidate->cm[0].totpoint; i++) {
          SET_FLAG_FROM_TEST(candidate->cm[0].curve[i].flag, i == numeric->point, CUMA_ACTIVE);
        }
        BKE_curvemapping_changed(candidate, false);
        if (owned_curve_candidate_valid(*candidate, session->error)) {
          BKE_curvemapping_free_data(&mapping);
          BKE_curvemapping_copy_data(&mapping, candidate);
          owned_curve_dialog_changed(*session);
          numeric->generation = session->generation;
          for (int i = 0; i < mapping.cm[0].totpoint; i++) {
            if (mapping.cm[0].curve[i].flag & CUMA_ACTIVE) {
              numeric->point = i;
              numeric->coordinate[0] = mapping.cm[0].curve[i].x;
              numeric->coordinate[1] = mapping.cm[0].curve[i].y;
              break;
            }
          }
        }
        BKE_curvemapping_free(candidate);
      });
    }
    layout->row(true);
    for (const auto &[label, flags] :
         {std::pair{"Auto", eCurveMapPoint_Flag(0)}, {"Clamped", CUMA_HANDLE_AUTO_ANIM},
          {"Vector", CUMA_HANDLE_VECTOR}})
    {
      Button *button = owned_curve_button(block, IFACE_(label));
      button_func_set(button, [session, numeric, flags](bContext &) {
        if (numeric->generation != session->generation) {
          return;
        }
        auto &point = RNA_owned_curve_edit_mapping(*session->edit).cm[0].curve[numeric->point];
        point.flag = (point.flag & ~(CUMA_HANDLE_AUTO_ANIM | CUMA_HANDLE_VECTOR)) | flags;
        owned_curve_dialog_changed(*session);
      });
    }
    Button *remove = owned_curve_button(block, IFACE_("Remove"));
    if (curve.totpoint <= 2) {
      button_disable(remove, "A curve requires at least two points");
    }
    button_func_set(remove, [session, numeric](bContext &) {
      if (numeric->generation != session->generation) {
        return;
      }
      auto &curve = RNA_owned_curve_edit_mapping(*session->edit).cm[0];
      if (curve.totpoint > 2) {
        BKE_curvemap_remove_point(&curve, &curve.curve[numeric->point]);
        owned_curve_dialog_changed(*session);
      }
    });
  }

  layout->row(true);
  Button *clip = uiDefButV(block, ButtonType::Checkbox, IFACE_("Clip"), 0, 0,
                          7 * UI_UNIT_X, UI_UNIT_Y, &session->use_clip, 0, 1, "");
  clip->flag &= ~BUT_UNDO;
  button_func_set(clip, [session](bContext &) {
    CurveMapping &mapping = RNA_owned_curve_edit_mapping(*session->edit);
    SET_FLAG_FROM_TEST(mapping.flag, session->use_clip, CUMA_DO_CLIP);
    owned_curve_dialog_changed(*session);
  });
  Button *extend = uiDefButV(block, ButtonType::Checkbox, IFACE_("Extrapolate"), 0, 0,
                            7 * UI_UNIT_X, UI_UNIT_Y, &session->extrapolate, 0, 1, "");
  extend->flag &= ~BUT_UNDO;
  button_func_set(extend, [session](bContext &) {
    auto &mapping = RNA_owned_curve_edit_mapping(*session->edit);
    SET_FLAG_FROM_TEST(mapping.flag, session->extrapolate, CUMA_EXTEND_EXTRAPOLATE);
    owned_curve_dialog_changed(*session);
  });

  const char *labels[4] = {"Min X:", "Min Y:", "Max X:", "Max Y:"};
  for (int i = 0; i < 4; i++) {
    if (i % 2 == 0) {
      layout->row(true);
    }
    Button *button = uiDefButV(block, ButtonType::Num, labels[i], 0, 0,
                              7 * UI_UNIT_X, UI_UNIT_Y, &session->clip[i], -100, 100, "");
    button->flag &= ~BUT_UNDO;
    button_func_set(button, [session](bContext &) {
      const float *values = session->clip;
      if (!std::all_of(values, values + 4, [](float value) { return std::isfinite(value); }) ||
          values[0] >= values[2] || values[1] >= values[3])
      {
        session->error = "Clip minimum must be smaller than maximum";
        return;
      }
      auto &mapping = RNA_owned_curve_edit_mapping(*session->edit);
      BLI_rctf_init(&mapping.clipr, values[0], values[2], values[1], values[3]);
      owned_curve_dialog_changed(*session);
    });
  }
  layout->row(true);
  for (int direction = -1; direction <= 1; direction++) {
    const char *label = direction < 0 ? "Zoom Out" : direction > 0 ? "Zoom In" : "Reset View";
    Button *button = owned_curve_button(block, IFACE_(label));
    button_func_set(button, [session, direction](bContext &C) {
      auto &mapping = RNA_owned_curve_edit_mapping(*session->edit);
      if (direction == 0) {
        BKE_curvemapping_reset_view(&mapping);
      }
      else if (direction > 0) {
        curvemap_buttons_zoom_in(&C, &mapping);
      }
      else {
        curvemap_buttons_zoom_out(&C, &mapping);
      }
    });
  }
  if (!session->error.empty()) {
    layout->label(session->error, ICON_ERROR);
  }
}

static wmOperatorStatus owned_curve_dialog_exec(bContext *C, wmOperator *op)
{
  const auto session = owned_curve_dialog_take(op);
  if (!session || session->cancelled) {
    return OPERATOR_CANCELLED;
  }
  OwnedCurveRNAErrorScope errors;
  bool changed = false;
  bool success;
  if (session->edit) {
    const float *clip = session->clip;
    if (!std::all_of(clip, clip + 4, [](float value) { return std::isfinite(value); }) ||
        clip[0] >= clip[2] || clip[1] >= clip[3])
    {
      BKE_report(op->reports, RPT_ERROR, "Clip minimum must be smaller than maximum");
      return OPERATOR_CANCELLED;
    }
    success = RNA_owned_curve_edit_commit(*session->edit, C, changed);
  }
  else {
    success = RNA_owned_curve_path_initialize(*session->path, *CTX_data_main(C), C);
    changed = success;
  }
  if (!success) {
    BKE_report(op->reports, RPT_ERROR, errors.message.empty() ? "Owned curve edit rejected" :
                                                               errors.message.c_str());
  }
  return success && changed ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

static wmOperatorStatus owned_curve_dialog_invoke(bContext *C, wmOperator *op, const wmEvent *)
{
  const int ticket = RNA_int_get(op->ptr, "ticket");
  const auto it = owned_curve_tickets.find(ticket);
  if (it == owned_curve_tickets.end()) {
    return OPERATOR_CANCELLED;
  }
  const auto session = it->second;
  owned_curve_tickets.erase(it);
  op->customdata = MEM_new<OwnedCurveDialogPtr>(__func__, session);
  if (!RNA_owned_curve_path_is_set(*session->path)) {
    return owned_curve_dialog_exec(C, op);
  }
  OwnedCurveRNAErrorScope errors;
  session->edit = RNA_owned_curve_edit_begin(*session->path);
  if (!session->edit) {
    BKE_report(op->reports, RPT_ERROR, errors.message.c_str());
    owned_curve_dialog_take(op);
    return OPERATOR_CANCELLED;
  }
  const auto &mapping = RNA_owned_curve_edit_mapping(*session->edit);
  session->clip[0] = mapping.clipr.xmin;
  session->clip[1] = mapping.clipr.ymin;
  session->clip[2] = mapping.clipr.xmax;
  session->clip[3] = mapping.clipr.ymax;
  session->use_clip = mapping.flag & CUMA_DO_CLIP;
  session->extrapolate = mapping.flag & CUMA_EXTEND_EXTRAPOLATE;
  return WM_operator_props_dialog_popup(C, op, 440, IFACE_("Edit Curve"), IFACE_("Apply"));
}
}  // namespace

void UI_OT_owned_curve_edit(wmOperatorType *ot)
{
  ot->name = "Edit Owned Curve";
  ot->idname = "UI_OT_owned_curve_edit";
  ot->description = "Edit a temporary curve and apply it to its captured owner";
  ot->invoke = owned_curve_dialog_invoke;
  ot->exec = owned_curve_dialog_exec;
  ot->ui = owned_curve_dialog_draw;
  ot->cancel = [](bContext *, wmOperator *op) { owned_curve_dialog_take(op); };
  ot->flag = OPTYPE_UNDO | OPTYPE_INTERNAL;
  PropertyRNA *prop = RNA_def_int(ot->srna, "ticket", 0, 0, INT_MAX, "Ticket", "", 0, INT_MAX);
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
}

void template_owned_curve_mapping(Layout *layout, PointerRNA *ptr, const StringRefNull path)
{
  OwnedCurveRNAErrorScope errors;
  const auto target = RNA_owned_curve_path_capture(*ptr, path.c_str());
  if (!target) {
    layout->label(errors.message, ICON_ERROR);
    return;
  }
  Button *button = owned_curve_button(layout->block(),
      RNA_owned_curve_path_is_set(*target) ? IFACE_("Edit Curve") : IFACE_("Create Custom Curve"));
  if (!ID_IS_EDITABLE(ptr->owner_id) || ID_IS_OVERRIDE_LIBRARY(ptr->owner_id)) {
    button_disable(button, "Owned curve owner is read-only");
  }
  using Target = std::shared_ptr<rna::OwnedCurvePath>;
  button_funcN_set(button, [](bContext *C, void *argument, void *) {
    const auto target = *static_cast<Target *>(argument);
    const auto session = std::make_shared<OwnedCurveDialog>();
    session->path = target;
    while (owned_curve_tickets.contains(owned_curve_next_ticket)) {
      owned_curve_next_ticket = owned_curve_next_ticket == INT_MAX ? 1 : owned_curve_next_ticket + 1;
    }
    const int ticket = owned_curve_next_ticket;
    owned_curve_tickets.emplace(ticket, session);
    PointerRNA properties = WM_operator_properties_create("UI_OT_owned_curve_edit");
    RNA_int_set(&properties, "ticket", ticket);
    WM_operator_name_call(C, "UI_OT_owned_curve_edit", wm::OpCallContext::InvokeDefault,
                          &properties, nullptr);
    WM_operator_properties_free(&properties);
    owned_curve_tickets.erase(ticket);
  }, MEM_new<Target>(__func__, target), nullptr, but_func_argN_free<Target>, but_func_argN_copy<Target>);
  button_func_identity_compare_set(button, [](const Button *a, const Button *b) {
    const auto &left = *static_cast<const Target *>(a->func_argN);
    const auto &right = *static_cast<const Target *>(b->func_argN);
    return RNA_owned_curve_path_equal(*left, *right);
  });
}
