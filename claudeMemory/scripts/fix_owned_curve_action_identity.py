# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Give dialog actions distinct, owned identities across dynamic row redraws."""
from pathlib import Path

path = Path("C:/dev/blender/main/source/blender/editors/interface/templates/interface_template_curve_mapping.cc")
text = path.read_text(encoding="utf-8")
assert "OwnedCurveActionKind" not in text
anchor = "static void owned_curve_dialog_draw(bContext * /*C*/, wmOperator *op)"
addition = """enum class OwnedCurveActionKind { Preset, Handle, Remove, View };
struct OwnedCurveAction {
  OwnedCurveDialogPtr session;
  std::shared_ptr<OwnedCurveNumeric> numeric;
  OwnedCurveActionKind kind;
  int parameter;
  std::function<void(bContext &)> apply;
};

static void owned_curve_action_dispatch(bContext *C, void *argument, void *)
{
  static_cast<OwnedCurveAction *>(argument)->apply(*C);
}

static void owned_curve_action_set(Button *button,
                                   const OwnedCurveDialogPtr &session,
                                   OwnedCurveActionKind kind,
                                   int parameter,
                                   std::function<void(bContext &)> apply,
                                   std::shared_ptr<OwnedCurveNumeric> numeric = nullptr)
{
  button_funcN_set(button,
                   owned_curve_action_dispatch,
                   MEM_new<OwnedCurveAction>(__func__, OwnedCurveAction{
                       session, std::move(numeric), kind, parameter, std::move(apply)}),
                   nullptr,
                   but_func_argN_free<OwnedCurveAction>,
                   but_func_argN_copy<OwnedCurveAction>);
  button_func_identity_compare_set(button, [](const Button *a, const Button *b) {
    const auto &left = *static_cast<const OwnedCurveAction *>(a->func_argN);
    const auto &right = *static_cast<const OwnedCurveAction *>(b->func_argN);
    return left.session == right.session && left.numeric == right.numeric &&
           left.kind == right.kind && left.parameter == right.parameter;
  });
}

"""
assert text.count(anchor) == 1
text = text.replace(anchor, addition + anchor)


def replace(before, after):
    global text
    assert text.count(before) == 1, before
    text = text.replace(before, after)


replace("button_func_set(button, [session, preset](bContext &) {",
        "owned_curve_action_set(button, session, OwnedCurveActionKind::Preset, preset, [session, preset](bContext &) {")
replace("button_func_set(button, [session, numeric, flags](bContext &) {",
        "owned_curve_action_set(button, session, OwnedCurveActionKind::Handle, flags, [session, numeric, flags](bContext &) {")
replace("""        point.flag = (point.flag & ~(CUMA_HANDLE_AUTO_ANIM | CUMA_HANDLE_VECTOR)) | flags;
        owned_curve_dialog_changed(*session);
      });""", """        point.flag = (point.flag & ~(CUMA_HANDLE_AUTO_ANIM | CUMA_HANDLE_VECTOR)) | flags;
        owned_curve_dialog_changed(*session);
      }, numeric);""")
replace("button_func_set(remove, [session, numeric](bContext &) {",
        "owned_curve_action_set(remove, session, OwnedCurveActionKind::Remove, 0, [session, numeric](bContext &) {")
replace("""        BKE_curvemap_remove_point(&curve, &curve.curve[numeric->point]);
        owned_curve_dialog_changed(*session);
      }
    });""", """        BKE_curvemap_remove_point(&curve, &curve.curve[numeric->point]);
        owned_curve_dialog_changed(*session);
      }
    }, numeric);""")
replace("button_func_set(button, [session, direction](bContext &C) {",
        "owned_curve_action_set(button, session, OwnedCurveActionKind::View, direction, [session, direction](bContext &C) {")
assert text.count("if (numeric->generation != session->generation)") == 2
text = text.replace("if (numeric->generation != session->generation)",
                    "if (numeric != session->numeric || numeric->generation != session->generation)")
path.write_text(text, encoding="utf-8", newline="\n")
