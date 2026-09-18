# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Remove duplicate SPDX headers introduced when editor fragments were assembled."""
from pathlib import Path

root = Path("C:/dev/blender/main")
header = "/* SPDX-FileCopyrightText: 2026 Blender Authors\n *\n * SPDX-License-Identifier: GPL-2.0-or-later */\n\n"
for relative in (
    "source/blender/makesrna/intern/rna_owned_curve.cc",
    "source/blender/blenkernel/intern/curvemapping_owned_test.cc",
    "source/blender/editors/interface/templates/interface_template_curve_mapping.cc",
):
    path = root / relative
    text = path.read_text()
    index = text.find(header, len(header))
    assert index > 0, relative
    path.write_text(text[:index] + text[index + len(header):])
