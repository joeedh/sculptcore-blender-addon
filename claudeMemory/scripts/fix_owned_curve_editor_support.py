# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

root = Path("C:/dev/blender/main")
ui = root / "source/blender/editors/interface/templates/interface_template_curve_mapping.cc"
text = ui.read_text(encoding="utf-8")
text = text.replace('    PointerRNA properties;\n    WM_operator_properties_create(&properties, "UI_OT_owned_curve_edit");',
                    '    PointerRNA properties = WM_operator_properties_create("UI_OT_owned_curve_edit");')
ui.write_text(text, encoding="utf-8", newline="\n")

rna = root / "source/blender/makesrna/intern/rna_owned_curve.cc"
text = rna.read_text(encoding="utf-8")
begin = text.index("std::shared_ptr<rna::OwnedCurvePath> RNA_owned_curve_path_capture")
end = text.index("bool RNA_owned_curve_path_is_set", begin)
part = text[begin:end]
part = part.replace("(parent.owner_id->tag & ID_TAG_COPIED_ON_EVAL))", """((parent.owner_id->tag & ID_TAG_COPIED_ON_EVAL) ||
       ((parent.owner_id->tag & ID_TAG_NO_MAIN) &&
        !(parent.owner_id->flag & ID_FLAG_EMBEDDED_DATA))))""")
text = text[:begin] + part + text[end:]
begin = text.index("bool RNA_owned_curve_path_initialize")
end = text.index("std::shared_ptr<rna::OwnedCurveEdit> RNA_owned_curve_edit_begin", begin)
text = text[:begin] + """bool RNA_owned_curve_path_initialize(rna::OwnedCurvePath &path, Main & /*bmain*/, bContext *C)
{
  if (!main_thread() || path.existing.owned_curve) {
    return fail("Owned curve initialization requires an unset captured path");
  }
  /* The owner watch also covers embedded IDs, which are absent from Main's listbases. */
  if (std::any_of(path.declarations.begin(), path.declarations.end(),
                  [](const auto &token) { return !token->valid; }) ||
      std::any_of(path.watches.begin(), path.watches.end(),
                  [](const auto &watch) { return !watch->is_valid(); }))
  {
    return fail("Owned curve path changed after drawing; redraw before initializing",
                OwnedCurveRNAError::Stale);
  }
  ID *owner = path.owner;
  if (owner->session_uid != path.owner_session || owner->system_properties != path.root) {
    return fail("Owned curve owner storage changed after drawing", OwnedCurveRNAError::Stale);
  }
  PointerRNA root = RNA_id_pointer_create(owner);
  /* No owner, property or path-tree access after the user callback. */
  return bool(RNA_owned_curve_initialize(root, path.path.c_str(), "LINEAR", C).owned_curve);
}

""" + text[end:]
rna.write_text(text, encoding="utf-8", newline="\n")
