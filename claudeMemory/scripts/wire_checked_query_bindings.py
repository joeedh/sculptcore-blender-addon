# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed query-token and primitive typed binding wrappers."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "engine"


def edit(name, old, new):
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, (name, old[:100], text.count(old))
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


edit("source/props/prop_enums.h", "  ERROR_SCHEMA_CONFLICT = 1 << 6,", "  ERROR_SCHEMA_CONFLICT = 1 << 6,\n  ERROR_STALE_QUERY = 1 << 7,")
edit("source/brush/brush_configuration.h", "#pragma once", '#pragma once\n#include "litestl/binding/binding.h"')
edit("source/brush/brush_configuration.h", "  double value = 0;", '''  double value = 0;
  static litestl::binding::types::Struct<BrushScalarResult> *defineBindings()
  {
    using namespace litestl::binding;
    auto *st = new types::Struct<BrushScalarResult>("sculptcore::brush::BrushScalarResult", sizeof(BrushScalarResult));
    BIND_STRUCT_DEFAULT_CONSTRUCTOR(st);
    BIND_STRUCT_MEMBER(st, status);
    BIND_STRUCT_MEMBER(st, value);
    return st;
  }''')
edit("source/brush/brush_command.h", "  bool hasDefault = true;", "  bool hasDefault = true;\n  int status = 0; // Owned snapshot errors; generated manifests have status zero.")
edit("source/brush/brush_command.h", "    BIND_STRUCT_MEMBER(st, hasDefault);", "    BIND_STRUCT_MEMBER(st, hasDefault);\n    BIND_STRUCT_MEMBER(st, status);")
edit("source/brush/brush_command.h", '''  // Bound read-only so the TS bridge (Wave 5) can enumerate the active brush's
  // manifest by index and read each entry's name/range/dynamic flag. Returned
  // by pointer from CommandExecutor::queriedUniformEntry — never marshalled by
  // value, so a copy constructor is unneeded.''', '''  // Reflected fields are mutable. Legacy queriedUniformEntry returns a borrowed
  // pointer invalidated by requery; uniformSnapshotChecked returns an owned copy.
  // Checked operations use a separate private canonical mapping.''')

wrappers = [
    ("read", "Scalar", "BrushScalarResult", [("bool", "evaluate")], "readScalarChecked"),
    ("write", "Scalar", "int", [("double", "value")], "writeScalarChecked"),
    ("configure", "Dynamic", "int", [("int", "device"), ("int", "mode"), ("float", "factor")], "configureDynamicChecked"),
    ("enable", "Dynamic", "int", [("int", "device"), ("int", "enabled")], "enableDynamicChecked"),
    ("move", "Dynamic", "int", [("int", "device"), ("int", "index")], "moveDynamicChecked"),
    ("clear", "Dynamics", "int", [], "clearDynamicsChecked"),
    ("replace", "DynamicTable", "int", [("int", "device"), ("const Vector<float> &", "samples")], "replaceDynamicTableChecked"),
    ("set", "DynamicSample", "int", [("int", "device"), ("int", "index"), ("int", "count"), ("float", "value")], "setDynamicSampleChecked"),
    ("replace", "Dynamics", "int", [("const Vector<int> &", "devices"), ("const Vector<int> &", "modes"),
                                     ("const Vector<float> &", "factors"), ("const Vector<int> &", "enabled"),
                                     ("const Vector<int> &", "offsets"), ("const Vector<float> &", "samples")], "replaceDynamicsChecked"),
]
for kind, path in (("Common", "source/brush/brush.h"), ("Uniform", "source/brush/brush_executor.h")):
    methods, bindings = [], []
    for verb, subject, result, extra, target in wrappers:
        name = verb + kind + subject + "Checked"
        args = ([("int", "propId")] if kind == "Common" else [("int", "token"), ("int", "uniformIndex")])
        args += [("int", "scalarType")] + extra
        signature = ", ".join(t + " " + n for t, n in args)
        trailing = ", " + ", ".join(n for _, n in extra) if extra else ""
        body = ""
        if kind == "Common":
            body = "    return " + target + "(brushPropName(propId), scalarType" + trailing + ");\n"
        else:
            body = "    string name;\n    int error = checkedUniformName(token, uniformIndex, scalarType, name);\n"
            body += "    if (error) { return " + ("{error, 0}" if result == "BrushScalarResult" else "error") + "; }\n"
            body += "    return brush->" + target + "(name, scalarType" + trailing + ");\n"
        methods.append("  " + result + " " + name + "(" + signature + ")\n  {\n" + body + "  }\n")
        bindings.append("    BIND_STRUCT_METHOD(st, " + name + ", MARGS(" + ", ".join('"' + n + '"' for _, n in args) + "));\n")
    if kind == "Common":
        edit(path, "  BrushScalarResult readScalarChecked", "\n".join(methods) + "\n  BrushScalarResult readScalarChecked")
        edit(path, '    BIND_STRUCT_METHOD(st, clearPropsParent, MARGS());',
             '    BIND_STRUCT_METHOD(st, clearPropsParent, MARGS());\n    BIND_STRUCT_METHOD(st, configurationGeneration, MARGS());\n' + "".join(bindings))
    else:
        edit(path, "  bool registrationSucceeded()", "\n".join(methods) + "\n  bool registrationSucceeded()")
        edit(path, '    BIND_STRUCT_METHOD(st, queryUniformManifest, MARGS("brushType"));',
             '    BIND_STRUCT_METHOD(st, queryUniformManifest, MARGS("brushType"));\n'
             '    BIND_STRUCT_METHOD(st, uniformQueryToken, MARGS());\n'
             '    BIND_STRUCT_METHOD(st, uniformSnapshotChecked, MARGS("token", "uniformIndex"));\n' + "".join(bindings))

edit("source/brush/brush_executor.h", "  Vector<BrushUniformManifestEntry> queriedUniforms;", '''  Vector<BrushUniformManifestEntry> queriedUniforms;

private:
  Vector<BrushUniformManifestEntry> canonicalUniforms_;
  int uniformQueryToken_ = 0;
  const CommandExecutor *querySource_ = nullptr;
  Brush *queryBrush_ = nullptr;
  props::StructDef *queryStruct_ = nullptr;
  static int allocateUniformQueryToken();
  int checkedUniformName(int token, int index, int scalarType, string &name) const
  {
    if (token <= 0 || token != uniformQueryToken_ || querySource_ != this ||
        !brush || brush != queryBrush_ || brush->props.struct_def != queryStruct_) {
      return int(props::PropError::ERROR_STALE_QUERY);
    }
    if (index < 0 || index >= int(canonicalUniforms_.size())) {
      return int(props::PropError::ERROR_NOT_EXISTS);
    }
    const auto &entry = canonicalUniforms_[index];
    if (scalarType != int(entry.scalarType)) { return int(props::PropError::ERROR_INVALID_TYPE); }
    name = entry.name;
    return 0;
  }

public:
  int uniformQueryToken() const { return querySource_ == this ? uniformQueryToken_ : 0; }
  BrushUniformManifestEntry uniformSnapshotChecked(int token, int uniformIndex) const
  {
    BrushUniformManifestEntry result;
    string name;
    int type = uniformIndex >= 0 && uniformIndex < int(canonicalUniforms_.size()) ?
                   int(canonicalUniforms_[uniformIndex].scalarType) : int(props::Prop::INVALID_TYPE);
    result.status = checkedUniformName(token, uniformIndex, type, name);
    if (!result.status) { result = canonicalUniforms_[uniformIndex]; }
    return result;
  }''')
edit("source/brush/brush_executor.h", "    queriedUniforms.clear();\n    brush_command cmd;", '''    queriedUniforms.clear();
    canonicalUniforms_.clear();
    querySource_ = this;
    queryBrush_ = nullptr;
    queryStruct_ = nullptr;
    uniformQueryToken_ = allocateUniformQueryToken();
    if (!uniformQueryToken_ || !brush || !brush->props.struct_def) {
      lastRegistration = {props::PropError::ERROR_INVALID_OWNER, "query"};
      return -1;
    }
    brush_command cmd;''')
edit("source/brush/brush_executor.h", '''      queriedUniforms.append(u);
    }
    return int(queriedUniforms.size());''', '''      queriedUniforms.append(u);
      canonicalUniforms_.append(u);
    }
    queryBrush_ = brush;
    queryStruct_ = brush->props.struct_def;
    return int(queriedUniforms.size());''')

path = root / "source/brush/brush_executor.cc"
assert not path.read_text(encoding="utf-8").strip()
path.write_text('''#include "brush/brush_executor.h"
#include <atomic>
#include <limits>

namespace sculptcore::brush {
int CommandExecutor::allocateUniformQueryToken()
{
  static std::atomic<int> next{0};
  int current = next.load(std::memory_order_relaxed);
  while (current < std::numeric_limits<int>::max()) {
    if (next.compare_exchange_weak(current, current + 1, std::memory_order_relaxed)) {
      return current + 1;
    }
  }
  return 0;
}
} // namespace sculptcore::brush
''', encoding="utf-8", newline="\n")
