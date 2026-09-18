# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Propagate registration failure through the program batch aggregators."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "engine/source/brush/c-api"
path = root / "mesh_stroke_batch_c_api.cc"
source = path.read_text(encoding="utf-8")
begin = source.index("int MeshStroke_dabBatchProgram(")
prefix, body = source[:begin], source[begin:]
body = body.replace("    total += oneImage(center, normal, d[6]);", """    int result = oneImage(center, normal, d[6]);
    if (result < 0) {
      return -1;
    }
    total += result;""")
body = body.replace("      total += oneImage(float3(", "      result = oneImage(float3(")
body = body.replace("                        d[6]);", """                        d[6]);
      if (result < 0) {
        return -1;
      }
      total += result;""")
path.write_text(prefix + body, encoding="utf-8", newline="\n")

path = root / "grid_stroke_c_api.cc"
source = path.read_text(encoding="utf-8")
begin = source.index("int GridStroke_dabBatchProgram(")
end = source.index("\nvoid GridStroke_end", begin)
body = source[begin:end]
body = body.replace("  brush::Brush *b = s->exec.brush;", """  if (!s->exec.prepareProgramDeclarations(prog)) {
    return -1;
  }
  brush::Brush *b = s->exec.brush;""")
body = body.replace("    moved += GridStroke_dabProgram(s, prog, d[0], d[1], d[2], d[3], d[4], d[5]);", """    int result = GridStroke_dabProgram(s, prog, d[0], d[1], d[2], d[3], d[4], d[5]);
    if (result < 0) {
      return -1;
    }
    moved += result;""")
body = body.replace("      moved += GridStroke_dabProgram(s,", "      result = GridStroke_dabProgram(s,")
body = body.replace("                                     d[5] * sg[2]);", """                                     d[5] * sg[2]);
      if (result < 0) {
        return -1;
      }
      moved += result;""")
source = source[:begin] + body + source[end:]
path.write_text(source, encoding="utf-8", newline="\n")
