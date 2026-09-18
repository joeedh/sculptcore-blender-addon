# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed property-authoring boundary in the companion fork."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT.parent / "main"


def replace(path, old, new):
    target = FORK / path
    source = target.read_text(encoding="utf-8")
    if re.sub(r'\s+', '', new) in re.sub(r'\s+', '', source):
        return
    assert source.count(old) == 1, (path, old)
    target.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


for source, target in (
    ("ED_authoring_undo.hh", "source/blender/editors/include/ED_authoring_undo.hh"),
    ("authoring_undo.cc", "source/blender/editors/undo/authoring_undo.cc"),
    ("bpy_rna_authoring.cc", "source/blender/python/intern/bpy_rna_authoring.cc"),
):
    shutil.copyfile(ROOT / "claudeMemory/implementation" / source, FORK / target)

replace("source/blender/editors/undo/CMakeLists.txt", "  custom_mode_undo.cc", "  authoring_undo.cc\n  custom_mode_undo.cc")
replace("source/blender/editors/undo/CMakeLists.txt", "set(INC\n", "set(INC\n  ../../depsgraph\n")
replace("source/blender/python/intern/CMakeLists.txt", "  bpy_rna_idprops.cc", "  bpy_rna_authoring.cc\n  bpy_rna_idprops.cc")
replace("source/blender/editors/undo/undo_system_types.cc", '#include "ED_undo.hh"',
        '#include "ED_undo.hh"\n#include "ED_authoring_undo.hh"')
replace("source/blender/editors/undo/undo_system_types.cc", "  /* Keep global undo last (as a fallback). */",
        "  BKE_undosys_type_append(ed::authoring_undosys_type);\n\n  /* Keep global undo last (as a fallback). */")
names = ("begin", "commit", "cancel", "revision", "curve_key")
replace("source/blender/python/intern/bpy_rna_idprops.hh", "}  // namespace blender",
        "".join("extern PyMethodDef BPY_rna_authoring_{}_method_def;\n".format(name) for name in names)
        + "}  // namespace blender")
target = FORK / "source/blender/python/intern/bpy_rna_types_capi.cc"
source = target.read_text(encoding="utf-8")
source, count = re.subn(
    r"static PyMethodDef pyrna_id_methods\[\] = \{.*?static_assert\(ARRAY_SIZE\(pyrna_id_methods\) == \d+\);",
    "static PyMethodDef pyrna_id_methods[8] = {};\nstatic_assert(ARRAY_SIZE(pyrna_id_methods) == 8);",
    source, flags=re.S)
if count == 0:
    assert "static PyMethodDef pyrna_id_methods[8] = {};" in source
target.write_text(source, encoding="utf-8", newline="\n")
anchor = "pyrna_id_methods[1] = BPY_rna_system_property_scalar_method_def;"
# This tree initializes the method table through ARRAY_SET_ITEMS instead of assignments.
if anchor in source:
    replace(str(target.relative_to(FORK)), anchor, anchor + "\n" + "\n".join(
        "  pyrna_id_methods[{}] = BPY_rna_authoring_{}_method_def;".format(i + 2, name)
        for i, name in enumerate(names)))
else:
    replace(str(target.relative_to(FORK)), "BPY_rna_system_property_scalar_method_def);",
            "BPY_rna_system_property_scalar_method_def,\n" + ",\n".join(
                "                  BPY_rna_authoring_{}_method_def".format(name) for name in names) + ");")
print("authoring undo installed")

replace("source/blender/makesrna/RNA_owned_curve.hh",
        "bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path);",
        "bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path);\n"
        "ID *RNA_owned_curve_path_owner(const rna::OwnedCurvePath &path, Main &bmain);")
replace("source/blender/makesrna/intern/rna_owned_curve.cc", '#include "BKE_library.hh"',
        '#include "BKE_library.hh"\n#include "BKE_lib_id.hh"')
replace("source/blender/makesrna/intern/rna_owned_curve.cc",
        "bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path)",
        """ID *RNA_owned_curve_path_owner(const rna::OwnedCurvePath &path, Main &bmain)
{
  if (!BLI_thread_is_main() ||
      std::any_of(path.watches.begin(), path.watches.end(),
                  [](const auto &watch) { return !watch->is_valid(); }) ||
      !BKE_id_is_in_main(&bmain, path.owner) ||
      path.owner->session_uid != path.owner_session) {
    fail("Owned curve target is stale", OwnedCurveRNAError::Stale);
    return nullptr;
  }
  return path.owner;
}

bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path)""")
template = "source/blender/editors/interface/templates/interface_template_curve_mapping.cc"
target = FORK / template
source = target.read_text(encoding="utf-8")
if "ed::ED_undo_push" in source:
    target.write_text(source.replace("ed::ED_undo_push", "ED_undo_push"), encoding="utf-8", newline="\n")
replace(template, '#include "RNA_owned_curve.hh"',
        '#include "RNA_owned_curve.hh"\n#include "ED_authoring_undo.hh"\n#include "ED_undo.hh"\n'
        '#include "BKE_lib_id.hh"\n#include "BKE_undo_system.hh"')
replace(template, "  bool changed = false;\n  bool success;\n  if (session->edit)", """  bool changed = false;
  bool success;
  ID *owner = RNA_owned_curve_path_owner(*session->path, *CTX_data_main(C));
  if (!owner) { return OPERATOR_CANCELLED; }
  const uint32_t owner_uid = owner->session_uid;
  std::string authoring_error;
  const bool scoped = ELEM(GS(owner->name), ID_BR, ID_SCE);
  auto authoring = scoped ? ed::authoring_edit_begin(C, *owner, false, true, authoring_error) : nullptr;
  if (scoped && !authoring) {
    BKE_report(op->reports, RPT_ERROR, authoring_error.c_str());
    return OPERATOR_CANCELLED;
  }
  if (session->edit)""")
replace(template, "  return success && changed ? OPERATOR_FINISHED : OPERATOR_CANCELLED;", """  if (success && changed) {
    if (authoring) {
      /* The RNA callback can remove the owner. Revalidate without dereferencing it. */
      ID *current = BKE_libblock_find_session_uid(CTX_data_main(C), owner_uid);
      if (!current || !ed::authoring_edit_finish(C, *current, *authoring, true,
                                                "Edit Owned Curve", changed, authoring_error)) {
        BKE_report(op->reports, RPT_ERROR, authoring_error.c_str());
        return OPERATOR_CANCELLED;
      }
    }
    else { ED_undo_push(C, "Edit Owned Curve", UndoEncodeHints::None); }
  }
  return success && changed ? OPERATOR_FINISHED : OPERATOR_CANCELLED;""")
replace(template, "  ot->flag = OPTYPE_UNDO | OPTYPE_INTERNAL;", "  ot->flag = OPTYPE_INTERNAL;")
