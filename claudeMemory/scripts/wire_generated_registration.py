# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed generated-registration wiring to its existing emission block."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "engine"
path = root / "source/brush/compiler/emit_cpp.cc"
source = path.read_text(encoding="utf-8")
begin = source.index("    // Declared uniforms — the executor registers")
end = source.index('    write("  def.loadUniformProps', begin)
source = source[:begin] + '''    for (const auto &f : brush->fields) {
      if (f.kind != FieldKind::Uniform) {
        continue;
      }
      write("  def.uniforms.append(sculptcore::brush::BrushUniformManifestEntry{\\\"");
      write(f.name);
      write("\\\", ");
      write(f.type == TypeKind::Float ? "true" : "false");
      write(", ");
      write(fieldDynamicCapable(f) ? "true" : "false");
      write(", ");
      write(doubleLit(f.hasDefault ? f.defaultValue : 0.0));
      write(", ");
      write(f.hasRange ? "true" : "false");
      write(", ");
      write(doubleLit(f.hasRange ? f.rangeMin : 0.0));
      write(", ");
      write(doubleLit(f.hasRange ? f.rangeMax : 0.0));
      write(", ");
      if (extrasMode && fieldUsesStore(f)) {
        write("kExtraSlot_");
        write(f.name);
      } else {
        write("-1");
      }
      write(", sculptcore::props::Prop::");
      write(f.type == TypeKind::Float ? "FLOAT32" :
            f.type == TypeKind::Int ? "INT32" : f.type == TypeKind::Bool ? "BOOL" : "INVALID_TYPE");
      write(", ");
      write(f.hasDefault ? "true" : "false");
      write("});\\n");
    }
''' + source[end:]
old = '''      write(" = brush.props.lookupValue<float>(\\\"");'''
new = '''      write(" = brush.props.lookupValue<");
      write(f.type == TypeKind::Bool ? "bool" : f.type == TypeKind::Int ? "int" : "float");
      write(">(\\\"");'''
assert old in source
source = source.replace(old, new)
path.write_text(source, encoding="utf-8", newline="\n")
