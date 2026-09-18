# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Apply the reviewed native runtime slice to the companion checkout, preserving other edits."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT.parent / "main"
BKE = FORK / "source/blender/blenkernel"


def replace(path, old, new):
    text = path.read_text()
    if new in text:
        return
    assert text.count(old) == 1, (path, old)
    path.write_text(text.replace(old, new), newline="\n")


for name in ("BKE_curvemapping_owned.hh", "curvemapping_owned.cc", "curvemapping_owned_test.cc"):
    source = ROOT / "claudeMemory/implementation" / name
    if source.exists():
        shutil.copyfile(source, BKE / (name if name.startswith("BKE_") else "intern/" + name))

for path in (BKE / "intern/idprop.cc", BKE / "intern/lib_id.cc", BKE / "intern/lib_id_delete.cc"):
    replace(path, '#include "BKE_idprop.hh"',
            '#include "BKE_curvemapping_owned.hh"\n#include "BKE_idprop.hh"')

replace(BKE / "intern/idprop.cc",
        "void IDP_RemoveFromGroup(IDProperty *group, IDProperty *prop)\n{",
        "void IDP_RemoveFromGroup(IDProperty *group, IDProperty *prop)\n{\n"
        "  bke::owned_curve_invalidate_tree(prop);")
replace(BKE / "intern/idprop.cc",
        "void IDP_CopyPropertyContent(IDProperty *dst, const IDProperty *src)\n{",
        "void IDP_CopyPropertyContent(IDProperty *dst, const IDProperty *src)\n{\n"
        "  bke::owned_curve_invalidate_tree(dst);")
replace(BKE / "intern/idprop.cc",
        "                                              const int recursion_depth)\n{",
        "                                              const int recursion_depth)\n{\n"
        "  bke::owned_curve_invalidate_property(prop);")
replace(BKE / "intern/lib_id_delete.cc",
        "void BKE_libblock_free_data(ID *id, const bool do_id_user)\n{",
        "void BKE_libblock_free_data(ID *id, const bool do_id_user)\n{\n"
        "  bke::owned_curve_invalidate_owner(id);")
replace(BKE / "intern/lib_id.cc",
        "  BLI_assert(GS(id_a->name) == GS(id_b->name));",
        "  BLI_assert(GS(id_a->name) == GS(id_b->name));\n"
        "  bke::owned_curve_invalidate_owner(id_a);\n"
        "  bke::owned_curve_invalidate_owner(id_b);")

color_path = BKE / "intern/colortools.cc"
color_text = color_path.read_text()
color_text = color_text.replace("  int i = int(fi);\n\n  /* fi is table float index",
                                "\n  /* fi is table float index")
color_path.write_text(color_text, newline="\n")
replace(BKE / "intern/colortools.cc",
        "  if (i < 0) {\n    return cuma->table[0].y;",
        "  /* Convert only after the range check; extrapolation can overflow the float index. */\n"
        "  const int i = int(fi);\n  if (i < 0) {\n    return cuma->table[0].y;")

for old, new in (
    ("  intern/curvemapping_idprop.cc", "  intern/curvemapping_idprop.cc\n  intern/curvemapping_owned.cc"),
    ("  BKE_curvemapping_idprop.hh", "  BKE_curvemapping_idprop.hh\n  BKE_curvemapping_owned.hh"),
    ("    intern/curvemapping_idprop_test.cc",
     "    intern/curvemapping_idprop_test.cc\n    intern/curvemapping_owned_test.cc"),
):
    replace(BKE / "CMakeLists.txt", old, new)
