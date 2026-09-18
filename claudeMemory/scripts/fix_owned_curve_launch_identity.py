# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

root = Path("C:/dev/blender/main")
header = root / "source/blender/makesrna/RNA_owned_curve.hh"
text = header.read_text(encoding="utf-8")
anchor = "bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path);"
if "RNA_owned_curve_path_equal" not in text:
    text = text.replace(anchor, """/** Compare captured authority without dereferencing possibly removed owner storage. */
bool RNA_owned_curve_path_equal(const rna::OwnedCurvePath &a, const rna::OwnedCurvePath &b);
""" + anchor)
header.write_text(text, encoding="utf-8", newline="\n")
source = root / "source/blender/makesrna/intern/rna_owned_curve.cc"
text = source.read_text(encoding="utf-8")
anchor = "bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path)"
if "bool RNA_owned_curve_path_equal" not in text:
    text = text.replace(anchor, """bool RNA_owned_curve_path_equal(const rna::OwnedCurvePath &a, const rna::OwnedCurvePath &b)
{
  const auto declarations_valid = [](const rna::OwnedCurvePath &path) {
    return std::all_of(path.declarations.begin(), path.declarations.end(),
                       [](const auto &token) { return token->valid; });
  };
  if (!declarations_valid(a) || !declarations_valid(b)) {
    return false;
  }
  if (a.existing.owned_curve || b.existing.owned_curve) {
    return a.existing.owned_curve && b.existing.owned_curve &&
           RNA_owned_curve_equal(a.existing, b.existing);
  }
  return a.owner == b.owner && a.owner_session == b.owner_session && a.root == b.root &&
         a.path == b.path && a.declarations == b.declarations && a.watches == b.watches &&
         std::all_of(a.watches.begin(), a.watches.end(),
                     [](const auto &watch) { return watch->is_valid(); });
}

""" + anchor)
source.write_text(text, encoding="utf-8", newline="\n")

ui = root / "source/blender/editors/interface/templates/interface_template_curve_mapping.cc"
text = ui.read_text(encoding="utf-8")
start = text.index("void template_owned_curve_mapping(")
end = text.index("void template_curve_mapping(", start)
staged = (Path(__file__).parent.parent / "implementation/owned_curve_editor_ui.inc").read_text(encoding="utf-8")
replacement = staged[staged.index("void template_owned_curve_mapping("):]
ui.write_text(text[:start] + replacement + "\n" + text[end:], encoding="utf-8", newline="\n")
