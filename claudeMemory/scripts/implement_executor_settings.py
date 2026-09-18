# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed executor-owned scalar preparation pass."""
from pathlib import Path

p = Path("engine/source/brush/brush_preparation.cc")
s = p.read_text().replace('#include <cstring>', '#include <cstring>\n#include <limits>')
at = s.index("namespace {\nusing props::Prop;")
s = s[:at] + '''std::span<const props::ScalarDeclaration> executorSettingDeclarations()
{
  using props::Prop;
  constexpr double maxFloat = std::numeric_limits<float>::max();
  static const props::ScalarDeclaration settings[] = {
      {"automask_cavity", Prop::BOOL, false, 0, true, 0, 1, false},
      {"cavity_factor", Prop::FLOAT32, false, 0, true, -maxFloat, maxFloat, false},
      {"cavity_blur_steps", Prop::INT32, false, 0, true, 0, INT32_MAX - 1, false},
      {"cavity_inverted", Prop::BOOL, false, 0, true, 0, 1, false},
      {"cavity_use_curve", Prop::BOOL, false, 0, true, 0, 1, false},
      {"automask_view_normal", Prop::BOOL, false, 0, true, 0, 1, false},
      {"cull_backfaces", Prop::BOOL, false, 0, true, 0, 1, false},
      {"view_normal_limit", Prop::FLOAT32, false, 0, true, -maxFloat, maxFloat, false},
      {"view_normal_falloff", Prop::FLOAT32, false, 0, true, -maxFloat, maxFloat, false},
  };
  return settings;
}

bool executorSetting(const util::string &name)
{
  for (const auto &setting : executorSettingDeclarations()) {
    if (setting.name == name)
      return true;
  }
  return false;
}

''' + s[at:]
s = s.replace("  for (const auto &value : values_) {", "  brush.cavity_curve = cavityCurve_;\n  for (const auto &value : values_) {")
s = s.replace("                    std::span<const BrushDynamicsOverride> dynamicsOverrides)\n", "                    std::span<const BrushDynamicsOverride> dynamicsOverrides,\n                    std::span<const float> cavityCurveOverride)\n")
needle = "  candidate.definition_ = brush.props.struct_def;"
assert needle in s
s = s.replace(needle, needle + '''
  static_assert(Brush::kCavityCurveLutSize == 256);
  if (!cavityCurveOverride.empty() && cavityCurveOverride.size() != 256)
    return {PropError::ERROR_INVALID_VALUE, "cavity curve"};
  for (size_t i = 0; i < 256; i++) {
    const float value = cavityCurveOverride.empty() ? brush.cavity_curve[i] : cavityCurveOverride[i];
    if (!std::isfinite(value))
      return {PropError::ERROR_INVALID_VALUE, "cavity curve"};
    candidate.cavityCurve_[i] = value;
  }''')
needle = "    if (scalar(entry.scalarType))\n      candidate.declarations_.append(declarationOf(entry));"
assert needle in s
s = s.replace(needle, '''    if (executorSetting(entry.name)) {
      for (const auto &setting : executorSettingDeclarations()) {
        if (setting.name != entry.name)
          continue;
        if (entry.scalarType != setting.type || entry.dynamic || entry.hasDefault ||
            (entry.hasRange && (entry.rangeMin != setting.rangeMin || entry.rangeMax != setting.rangeMax)))
          return {PropError::ERROR_SCHEMA_CONFLICT, entry.name};
      }
    } else if (scalar(entry.scalarType)) {
      candidate.declarations_.append(declarationOf(entry));
    }''')
needle = "  for (const auto &entry : uniforms) {\n    if (!scalar(entry.scalarType) || commonMember(entry.name) >= 0)"
assert needle in s
s = s.replace(needle, '''  for (const auto &setting : executorSettingDeclarations()) {
    auto error = append({setting.name, setting.type, 0, false, nativeMember(setting.name), -1},
                        &setting, false);
    if (error != PropError::ERROR_NONE)
      return {error, setting.name};
  }
  for (const auto &entry : uniforms) {
    if (!scalar(entry.scalarType) || commonMember(entry.name) >= 0 || executorSetting(entry.name))''')
p.write_text(s)

p = Path("engine/source/brush/brush_program_preparation.cc")
s = p.read_text()
at = s.index("props::ScalarRegistrationResult programError(")
s = s[:at] + '''int BrushProgram::replaceCommandCavityCurveChecked(int idx, Vector<float> &samples)
{
  if (idx < 0 || size_t(idx) >= commands.size())
    return int(PropError::ERROR_NOT_EXISTS);
  if (samples.size() != Brush::kCavityCurveLutSize)
    return int(PropError::ERROR_INVALID_VALUE);
  for (float sample : samples) {
    if (!std::isfinite(sample))
      return int(PropError::ERROR_INVALID_VALUE);
  }
  Vector<float> candidate(samples);
  commands[idx].cavityCurveOverride = std::move(candidate);
  return 0;
}

int BrushProgram::removeCommandCavityCurveChecked(int idx)
{
  if (idx < 0 || size_t(idx) >= commands.size())
    return int(PropError::ERROR_NOT_EXISTS);
  commands[idx].cavityCurveOverride.clear();
  return 0;
}

''' + s[at:]
s = s.replace("if (entry.scalarType == Prop::FLOAT32 || entry.scalarType == Prop::INT32 ||\n          entry.scalarType == Prop::BOOL)", "if (!executorSetting(entry.name) && (entry.scalarType == Prop::FLOAT32 || entry.scalarType == Prop::INT32 ||\n          entry.scalarType == Prop::BOOL))")
needle = "         command.dynamicsOverrides.size()});"
assert needle in s
s = s.replace(needle, "         command.dynamicsOverrides.size()},\n        {command.cavityCurveOverride.size() ? &command.cavityCurveOverride[0] : nullptr,\n         command.cavityCurveOverride.size()});")
s = s.replace("      intSize_(brush.namedInts.size()), boolSize_(brush.namedBools.size())", "      intSize_(brush.namedInts.size()), boolSize_(brush.namedBools.size()), cavityCurve_(brush.cavity_curve)")
# Match the actual initializer wrapping without silently skipping the save.
if 'cavityCurve_(brush.cavity_curve)' not in s:
    s = s.replace("intSize_(brush.namedInts.size()), boolSize_(brush.namedBools.size())", "intSize_(brush.namedInts.size()), boolSize_(brush.namedBools.size()), cavityCurve_(brush.cavity_curve)")
assert 'cavityCurve_(brush.cavity_curve)' in s
s = s.replace("ScopedBrushWorkingValues::~ScopedBrushWorkingValues()\n{", "ScopedBrushWorkingValues::~ScopedBrushWorkingValues()\n{\n  brush_.cavity_curve = cavityCurve_;")
p.write_text(s)
