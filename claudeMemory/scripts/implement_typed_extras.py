# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed typed extra compiler changes with guarded replacements."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "engine/source/brush/compiler"


def change(name, edits):
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    for old, new in edits:
        if text.count(old) != 1:
            raise RuntimeError((name, text.count(old), old[:100]))
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")


change("emit_cpp.h", [
    ("// Extra (out-of-repo) kernel: float uniforms that are not member-backed\n  // lower to Brush.namedFloats store slots", "// Extra (out-of-repo) kernel: scalar fields that are not member-backed\n  // lower to typed Brush named store slots"),
    ("/** True when `f` reads through the named-float store in an extra kernel:", "/** True when `f` reads through a typed named store in an extra kernel:"),
    ("validity (float-only)", "validity (float/int/bool)"),
    ("EmitResult emitCpp(const Brush &brush, const CppEmitOptions &opts = {});", "EmitResult emitCpp(const Brush &brush, const CppEmitOptions &opts = {});\n\n/** Shared semantic gate for C++ output and registry collection. */\nVector<string> validateCppFields(const Brush &brush, const CppEmitOptions &opts = {});"),
])
change("emit_cpp.cc", [
    ("namespace {\n\nstruct Emit", '''namespace {

const char *storeSuffix(TypeKind type)
{
  return type == TypeKind::Bool ? "Bool" : type == TypeKind::Int ? "Int" : "Float";
}

const char *scalarCppType(TypeKind type)
{
  return type == TypeKind::Bool ? "bool" : type == TypeKind::Int ? "int" : "float";
}

string integralLiteral(double value)
{
  char text[32];
  std::snprintf(text, sizeof(text), "%.0f", value);
  return string(text);
}

struct Emit'''),
    ("// namedFloats slots instead of erroring", "// typed named slots instead of erroring"),
    ("// their registry-assigned namedFloats slot.", "// their registry-assigned typed slot."),
    ('''          out += inHost ? "brush.namedFloats[kExtraSlot_"
                        : "ctx.brush.namedFloats[kExtraSlot_";''', '''          out += inHost ? "brush.named" : "ctx.brush.named";
          out += storeSuffix(f->type);
          out += "s[kExtraSlot_";'''),
    ('''          out += currentStage && currentStage->kind == StageKind::Host
                     ? "brush.setEvaluatedNamedFloat(kExtraSlot_"
                     : "ctx.brush.setEvaluatedNamedFloat(kExtraSlot_";''', '''          out += currentStage && currentStage->kind == StageKind::Host
                     ? "brush.setEvaluatedNamed"
                     : "ctx.brush.setEvaluatedNamed";
          out += storeSuffix(field->type);
          out += "(kExtraSlot_";'''),
    ('''      case TypeKind::Float:
      case TypeKind::Int:
        break;''', '''      case TypeKind::Float:
      case TypeKind::Int:
      case TypeKind::Bool:
        break;'''),
    ('''        write("  {\\n    float v = brush.getNamedFloat(kExtraSlot_");
        write(f.name);
        write(");\\n");
        if (f.hasRange) {''', '''        write("  {\\n    ");
        write(f.type == TypeKind::Bool ? "uint32_t" : scalarCppType(f.type));
        write(" v = brush.getNamed");
        write(storeSuffix(f.type));
        write("(kExtraSlot_");
        write(f.name);
        write(f.type == TypeKind::Bool ? ") ? 1u : 0u;\\n" : ");\\n");
        if (f.hasRange && f.type != TypeKind::Float) {
          const double lower = std::ceil(std::max(
              f.rangeMin, f.type == TypeKind::Bool ? 0.0 : double(INT32_MIN)));
          const double upper = std::floor(std::min(
              f.rangeMax, f.type == TypeKind::Bool ? 1.0 : double(INT32_MAX)));
          write("    v = v < ");
          write(integralLiteral(lower));
          write(" ? ");
          write(integralLiteral(lower));
          write(" : (v > ");
          write(integralLiteral(upper));
          write(" ? ");
          write(integralLiteral(upper));
          write(" : v);\\n");
        } else if (f.hasRange) {'''),
    ('''        write("    brush.setEvaluatedNamedFloat(kExtraSlot_");
        write(f.name);
        write(", brush.props.lookupValue<float>(\\\"");
        write(f.name);
        write("\\\", ");
        write(floatLit(def));''', '''        write("    brush.setEvaluatedNamed");
        write(storeSuffix(f.type));
        write("(kExtraSlot_");
        write(f.name);
        write(", brush.props.lookupValue<");
        write(scalarCppType(f.type));
        write(">(\\\"");
        write(f.name);
        write("\\\", ");
        write(f.type == TypeKind::Bool ? string(def != 0 ? "true" : "false") :
              f.type == TypeKind::Int ? integralLiteral(def) : floatLit(def));'''),
    ("EmitResult emitCpp(const Brush &brush, const CppEmitOptions &opts)\n{", "Vector<string> validateCppFields(const Brush &brush, const CppEmitOptions &opts)\n{"),
    ('''  // kernels: unlisted scalar floats fall through to the named store; any
  // other unlisted type still needs an engine-side member.
  for (const auto &f : brush.fields) {
    if (f.kind == FieldKind::Uniform) {''', '''  // kernels: unlisted float/int/bool fields use typed named stores.
  Vector<string> names;
  for (const auto &f : brush.fields) {
    for (const auto &name : names) {
      if (name == f.name) {
        em.errors.append(string("duplicate field '") + f.name + "'");
      }
    }
    names.append(f.name);
    if (f.kind == FieldKind::Uniform || (opts.extras && fieldUsesStore(f))) {'''),
    ('''          (f.kind != FieldKind::Uniform || (member && !member->dynamic)))''', '''          (f.kind != FieldKind::Uniform ||
           (f.type != TypeKind::Float && f.type != TypeKind::Int && f.type != TypeKind::Bool) ||
           (member && !member->dynamic)))'''),
    ('''    } else if (f.type != TypeKind::Float) {''', '''    } else if (f.type != TypeKind::Float && f.type != TypeKind::Int &&
               f.type != TypeKind::Bool) {'''),
    ('''"extra kernel uniform '%s': only scalar floats can use the named "''', '''"extra kernel uniform '%s': only float/int/bool scalars can use the named "'''),
    ('''  if (em.errors.size() > 0) {
    EmitResult r;
    r.errors = std::move(em.errors);
    return r;
  }

  for (const auto &st : brush.stages) {''', '''  return std::move(em.errors);
}

EmitResult emitCpp(const Brush &brush, const CppEmitOptions &opts)
{
  Emit em;
  em.brush = &brush;
  em.extrasMode = opts.extras;
  em.errors = validateCppFields(brush, opts);
  if (em.errors.size() > 0) {
    EmitResult r;
    r.errors = std::move(em.errors);
    return r;
  }

  for (const auto &st : brush.stages) {'''),
])
change("sbrushc_main.cc", [
    ('''    RegistryEntry e;
    e.stem = stemOf(p);''', '''    auto fieldErrors = validateCppFields(*brush, CppEmitOptions{true});
    if (fieldErrors.size() > 0) {
      for (const auto &error : fieldErrors) {
        std::fprintf(stderr, "%s: %s\\n", p.c_str(), error.c_str());
      }
      return 1;
    }
    RegistryEntry e;
    e.stem = stemOf(p);'''),
    ('''      // Scalar floats not backed by a Brush member take namedFloats slots;
      // non-float unlisted uniforms are rejected by the per-kernel cpp emit.
      if (f.type == TypeKind::Float && fieldUsesStore(f)) {''', '''      // The shared validator restricts stored fields to float/int/bool.
      if (fieldUsesStore(f)) {'''),
    ('''        su.type = sculptcore::props::Prop::FLOAT32;''', '''        su.type = f.type == TypeKind::Bool ? sculptcore::props::Prop::BOOL :
                  f.type == TypeKind::Int ? sculptcore::props::Prop::INT32 :
                                           sculptcore::props::Prop::FLOAT32;'''),
])
change("emit_wgsl.cc", [
    ('''      } else if (auto *f = findField(nm)) {
        if (f->kind == FieldKind::Uniform) {''', '''      } else if (auto *f = findField(nm)) {
        if (f->type == TypeKind::Bool) {
          out += "(";
        }
        if (f->kind == FieldKind::Uniform) {'''),
    ('''          out += "ctx_u.";
          out += e.name;
        }
      } else {''', '''          out += "ctx_u.";
          out += e.name;
        }
        if (f->type == TypeKind::Bool) {
          out += " != 0u)";
        }
      } else {'''),
    ('''      } else {
        out += wgslType(f.type);
      }
    };''', '''      } else {
        out += f.type == TypeKind::Bool ? "u32" : wgslType(f.type);
      }
    };'''),
])

path = ROOT / "emit_registry.cc"
text = path.read_text(encoding="utf-8")
text = text.replace('if (su.type != props::Prop::FLOAT32 ||\n          props::validateScalarDeclaration(su)',
                    'if (!isIdentifier(su.name) ||\n          props::validateScalarDeclaration(su)')
text = text.replace('''  if (slots.size() > kNamedUniformSlotLimit) {
    err("extra uniform slot limit exceeded");
  }''', '''  for (auto type : {props::Prop::FLOAT32, props::Prop::INT32, props::Prop::BOOL}) {
    int count = 0;
    for (const auto &slot : slots) {
      count += slot.type == type;
    }
    if (count > kNamedUniformSlotLimit) {
      err("extra uniform slot limit exceeded");
    }
  }''')
start = text.index('  // Named-float store slots')
end = text.index('  h += "} // namespace sculptcore::brush', start)
text = text[:start] + r'''  // Declare typed slots before kernel includes, which reference them directly.
  h += "namespace sculptcore::brush {\n\n";
  struct StoreType {
    props::Prop type;
    const char *suffix;
    const char *cppType;
    const char *propName;
  };
  const StoreType types[] = {
      {props::Prop::FLOAT32, "Float", "float", "FLOAT32"},
      {props::Prop::INT32, "Int", "int32_t", "INT32"},
      {props::Prop::BOOL, "Bool", "bool", "BOOL"},
  };
  for (const auto &type : types) {
    Vector<StoreUniform> typed;
    for (const auto &slot : slots) {
      if (slot.type == type.type) {
        typed.append(slot);
      }
    }
    const string prefix = string("kExtraNamed") + type.suffix;
    h += string("inline constexpr int extraNamed") + type.suffix + "Count = " +
         itoa(int(typed.size())) + ";\n";
    for (int i = 0; i < int(typed.size()); i++) {
      h += string("inline constexpr int kExtraSlot_") + typed[i].name + " = " +
           itoa(i) + ";\n";
    }
    if (typed.size() == 0) {
      continue;
    }
    h += string("inline constexpr ") + type.cppType + " " + prefix + "Defaults[] = {";
    for (int i = 0; i < int(typed.size()); i++) {
      if (i) {
        h += ", ";
      }
      double value = typed[i].hasDefault ? typed[i].defaultValue : 0.0;
      if (type.type == props::Prop::FLOAT32) {
        h += floatLit(value);
      } else if (type.type == props::Prop::BOOL) {
        h += value != 0 ? "true" : "false";
      } else {
        h += itoa(int(value));
      }
    }
    h += "};\n";
    h += string("inline constexpr NamedUniformDescriptor ") + prefix + "Descriptors[] = {\n";
    for (const auto &slot : typed) {
      h += string("  {\"") + slot.name + "\", props::Prop::" + type.propName + ", " +
           (slot.dynamic ? "true" : "false") + "},\n";
    }
    h += "};\n";
  }
  h += "\ninline const NamedUniformDescriptor "
       "*generatedExtraNamedUniformDescriptor(props::Prop type, int slot)\n{\n";
  h += "  (void)type; (void)slot;\n";
  for (const auto &type : types) {
    bool present = false;
    for (const auto &slot : slots) {
      present |= slot.type == type.type;
    }
    if (present) {
      h += string("  if (type == props::Prop::") + type.propName +
           " && slot >= 0 && slot < extraNamed" + type.suffix + "Count) {\n";
      h += string("    return &kExtraNamed") + type.suffix + "Descriptors[slot];\n  }\n";
    }
  }
  h += "  return nullptr;\n}\n\n";
  h += "/** Initialize untouched slots, preserving every existing working value. */\n";
  h += "inline void ensureExtraUniformDefaults(Brush &b)\n{\n  (void)b;\n";
  for (const auto &type : types) {
    bool present = false;
    for (const auto &slot : slots) {
      present |= slot.type == type.type;
    }
    if (present) {
      h += string("  for (int i = 0; i < extraNamed") + type.suffix + "Count; i++) {\n";
      h += string("    b.ensureNamed") + type.suffix + "Default(i, kExtraNamed" +
           type.suffix + "Defaults[i]);\n  }\n";
    }
  }
  h += "}\n\n";
''' + text[end:]
path.write_text(text, encoding="utf-8", newline="\n")
