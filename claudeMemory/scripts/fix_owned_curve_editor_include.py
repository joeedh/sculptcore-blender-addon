# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

target = Path("C:/dev/blender/main/source/blender/editors/interface/templates/interface_template_curve_mapping.cc")
source = target.read_text(encoding="utf-8")
source = source.replace('#include "BKE_colortools.hh\n', '#include "BKE_colortools.hh"\n')
target.write_text(source, encoding="utf-8", newline="\n")
