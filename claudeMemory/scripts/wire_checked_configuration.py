# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Route legacy configuration calls through the reviewed checked native API."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "engine"
p = root / "source/brush/brush.h"
s = p.read_text(encoding="utf-8")
s = s.replace("// Stable small ids for the float props", "// Stable small ids for the common scalar props")
s = s.replace("// Resolve a float property's device-dynamics stack by name, or null. This is\n  // the name-keyed core; any registered float uniform (common or per-kernel) is\n  // reachable, not just the 5 `BrushProp` ids.",
              "// Raw native inspection, including unsupported legacy FLOAT64 stacks.\n  // Configuration uses checked local ownership and eligibility separately.")
needle = "    if (p->type == props::Prop::FLOAT64) {"
assert s.count(needle) == 1
s = s.replace(needle, """    if (p->type == props::Prop::INT32) {
      return &static_cast<props::Int32Prop *>(base)->dynamics;
    }
    if (p->type == props::Prop::BOOL) {
      return &static_cast<props::BoolProp *>(base)->dynamics;
    }
""" + needle)
start = s.index("  // Drop all device layers from a property's dynamics")
end = s.index("  // Int-keyed wrappers", start)
s = s[:start] + """  // Legacy signatures delegate to the checked configuration boundary.
  void clearPropDynamicsByName(util::string name);
  void addPropDynamicByName(util::string name, int deviceType, int mixMode, float mixFactor);
  void setPropDynamicSampleByName(util::string name, int deviceType, int i, int n, float value);

""" + s[end:]
p.write_text(s, encoding="utf-8", newline="\n")
p = root / "source/brush/brush_configuration.cc"
s = p.read_text(encoding="utf-8")
ending = "} // namespace sculptcore::brush\n"
assert s.endswith(ending)
s = s[:-len(ending)] + """
static int legacyType(Brush &brush, const util::string &name)
{
  auto *property = brush.props.struct_def ? brush.props.struct_def->lookup(name) : nullptr;
  return property ? int(property->type) : int(Prop::INVALID_TYPE);
}

static void reportConfiguration(const util::string &name, int error)
{
  if (error) { fprintf(stderr, "brush property '%s': configuration error %d\\n", name.c_str(), error); }
}

void Brush::clearPropDynamicsByName(util::string name)
{
  reportConfiguration(name, clearDynamicsChecked(name, legacyType(*this, name)));
}

void Brush::addPropDynamicByName(util::string name, int device, int mode, float factor)
{
  reportConfiguration(name, configureDynamicChecked(name, legacyType(*this, name), device, mode, factor));
}

void Brush::setPropDynamicSampleByName(util::string name, int device, int index, int count, float value)
{
  reportConfiguration(name, setDynamicSampleChecked(name, legacyType(*this, name), device, index, count, value));
}
""" + ending
p.write_text(s, encoding="utf-8", newline="\n")
p = root / "source/brush/brush_executor.h"
s = p.read_text(encoding="utf-8")
s = s.replace('if (!entry && !isCommonFloatProp(p->name)) {',
              'if (!entry && !isCommonFloatProp(p->name) && p->name != string("invert")) {')
s = s.replace('if (entry && !(entry->isFloat && entry->dynamic)) {',
              '''if (entry && !(entry->dynamic &&
                       (entry->isFloat || entry->scalarType == props::Prop::INT32 ||
                        entry->scalarType == props::Prop::BOOL))) {''')
s = s.replace('uniform is @static / non-float (not ', 'uniform is @static / unsupported (not ')
needle = '        for (const auto &dev : dyn->devices) {'
assert s.count(needle) == 1
s = s.replace(needle, '''        if (!props::Dynamics::validStack(dyn->devices)) {
          res.ok = false;
          res.messages.append(string("uniform '") + p->name + "': invalid or pending device stack");
        }
''' + needle)
p.write_text(s, encoding="utf-8", newline="\n")
p = root / "tests/test_brush_uniform_validate.cc"
s = p.read_text(encoding="utf-8")
s = s.replace('''    // wingAngle is @static so registerProps skips it; register it by hand to
    // construct the bad state (a dynamic on a non-dynamic-capable uniform).''',
'''    // Inject invalid native state after verifying the checked setter rejects it.''')
s = s.replace('''    brush.addPropDynamicByName("wingAngle", PRESSURE, MULTIPLY, 1.0f);''',
'''    brush.addPropDynamicByName("wingAngle", PRESSURE, MULTIPLY, 1.0f);
    test_assert(brush.propDynamics("wingAngle")->devices.size() == 0);
    brush.propDynamics("wingAngle")->devices.append(sculptcore::props::DynamicDevice{});''')
s = s.replace('''    brush.setPropDynamicSampleByName("mu", PRESSURE, 0, 1, 0.5f); // 1-entry table''',
'''    brush.setPropDynamicSampleByName("mu", PRESSURE, 0, 1, 0.5f);
    test_assert(brush.propDynamics("mu")->devices[0].curveTable.size() == 0);
    brush.propDynamics("mu")->devices[0].curveTable.append(0.5f); // Deliberate corruption.''')
p.write_text(s, encoding="utf-8", newline="\n")
