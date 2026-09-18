# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed additive analytic response and atomic upload engine changes."""
from pathlib import Path

root = Path(__file__).resolve().parents[2] / 'engine'
updates = {}


def replace(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)


def method(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


path = root / 'source/props/prop_dynamics.h'
text = path.read_text()
assert 'responseKind' not in text
text = replace(text, '  util::Vector<float> curveTable;', '''  util::Vector<float> curveTable;
  // 0 table/identity, 1 constant, 2 two-step. Parameters stay double even for float inputs.
  int responseKind = 0;
  double responseThreshold = 0, responseLow = 0, responseHigh = 0;''')
text = replace(text, '    switch (mixMode) {', '''    if (responseKind < 0 || responseKind > 2 ||
        !std::isfinite(responseThreshold) || !std::isfinite(responseLow) ||
        !std::isfinite(responseHigh) || responseThreshold < 0 || responseThreshold > 1 ||
        (responseKind == 0 && (responseThreshold != 0 || responseLow != 0 || responseHigh != 0)) ||
        (responseKind == 1 && (responseThreshold != 0 || responseHigh != 0)) ||
        (responseKind != 0 && !curveTable.empty())) {
      return false;
    }
    switch (mixMode) {''') if text.count('    switch (mixMode) {') == 1 else text.replace(
    '    switch (mixMode) {', '''    if (responseKind < 0 || responseKind > 2 ||
        !std::isfinite(responseThreshold) || !std::isfinite(responseLow) ||
        !std::isfinite(responseHigh) || responseThreshold < 0 || responseThreshold > 1 ||
        (responseKind == 0 && (responseThreshold != 0 || responseLow != 0 || responseHigh != 0)) ||
        (responseKind == 1 && (responseThreshold != 0 || responseHigh != 0)) ||
        (responseKind != 0 && curveTable.size() != 0)) {
      return false;
    }
    switch (mixMode) {''', 1)
text = replace(text, '    curveTable = samples;', '''    curveTable = samples;
    responseKind = 0;
    responseThreshold = responseLow = responseHigh = 0;''')
text = replace(text, '      curveTable = std::move(pendingSamples_);', '''      curveTable = std::move(pendingSamples_);
      responseKind = 0;
      responseThreshold = responseLow = responseHigh = 0;''')
text = replace(text, '    return type == other.type && name == other.name', '''    return responseKind == other.responseKind && responseThreshold == other.responseThreshold &&
           responseLow == other.responseLow && responseHigh == other.responseHigh &&
           type == other.type && name == other.name''')
text = replace(text, '    int n = int(curveTable.size());', '''    if (responseKind == 1) {
      return Real(responseLow);
    }
    if (responseKind == 2) {
      // Do not round the threshold onto the input before choosing the branch.
      return Real(std::clamp(double(input), 0.0, 1.0) < responseThreshold ? responseLow : responseHigh);
    }
    int n = int(curveTable.size());''')
updates[path] = text

path = root / 'source/brush/brush_configuration.cc'
text = path.read_text()
old = method(text, 'int Brush::replaceDynamicsChecked(')
new = old.replace('Brush::replaceDynamicsChecked(', 'Brush::replaceResponseDynamicsChecked(', 1)
new = replace(new, 'const util::Vector<float> &samples)', '''const util::Vector<float> &samples,
                                  const util::Vector<int> &kinds,
                                  const util::Vector<double> &parameters)''')
new = replace(new, '  if (count > 4 || modes.size() != count',
              '  if (count > 4 || kinds.size() != count || parameters.size() != count * 3 || modes.size() != count')
new = replace(new, '    DynamicDevice layer;', '''    DynamicDevice layer;
    layer.responseKind = kinds[i];
    layer.responseThreshold = parameters[i * 3];
    layer.responseLow = parameters[i * 3 + 1];
    layer.responseHigh = parameters[i * 3 + 2];''')
head = old[:old.index('{')]
delegate = head + '''{
  if (devices.size() > 4) {
    return int(PropError::ERROR_INVALID_DYNAMICS);
  }
  util::Vector<int> kinds;
  util::Vector<double> parameters;
  for (size_t i = 0; i < devices.size(); i++) {
    kinds.append(0);
    parameters.append(0); parameters.append(0); parameters.append(0);
  }
  return replaceResponseDynamicsChecked(name, scalarType, devices, modes, factors, enabled,
                                        offsets, samples, kinds, parameters);
}'''
text = replace(text, old, delegate + '\n\n' + new)
updates[path] = text

path = root / 'source/brush/brush.h'
text = path.read_text()
old = method(text, '  int replaceCommonDynamicsChecked(')
new = old.replace('replaceCommonDynamicsChecked(', 'replaceCommonResponseDynamicsChecked(', 1)
new = replace(new, 'util::Vector<float> &samples)', '''util::Vector<float> &samples,
                                   util::Vector<int> &kinds,
                                   util::Vector<double> &parameters)''')
new = new.replace('return replaceDynamicsChecked(', 'return replaceResponseDynamicsChecked(', 1)
new = replace(new, 'samples);', 'samples, kinds, parameters);')
text = replace(text, old, old + '\n\n' + new)
anchor = '  uint64_t configurationGeneration() const'
declaration = new.replace('  int replaceCommonResponseDynamicsChecked(int propId,',
                          '  int replaceResponseDynamicsChecked(util::string name,', 1)
declaration = declaration[:declaration.index('{')].rstrip() + ';\n'
declaration = declaration.replace('util::Vector<', 'const util::Vector<')
text = replace(text, anchor, declaration + anchor)
anchor = '    BIND_STRUCT_METHOD(st, configurationGeneration, MARGS());'
binding = '''    BIND_STRUCT_METHOD(st, replaceCommonResponseDynamicsChecked,
                       MARGS("propId", "scalarType", "devices", "modes", "factors", "enabled",
                             "offsets", "samples", "kinds", "parameters"));
'''
text = replace(text, anchor, binding + anchor)
updates[path] = text

path = root / 'source/brush/brush_executor.h'
text = path.read_text()
old = method(text, '  int replaceUniformDynamicsChecked(')
new = old.replace('replaceUniformDynamicsChecked(', 'replaceUniformResponseDynamicsChecked(', 1)
new = replace(new, 'util::Vector<float> &samples)', '''util::Vector<float> &samples,
                                    util::Vector<int> &kinds,
                                    util::Vector<double> &parameters)''')
new = new.replace('brush->replaceDynamicsChecked(', 'brush->replaceResponseDynamicsChecked(', 1)
new = replace(new, 'offsets, samples);', 'offsets, samples, kinds, parameters);')
text = replace(text, old, old + '\n\n' + new)
anchor = '    BIND_STRUCT_METHOD(st, queriedUniformEntry, MARGS("idx"));'
text = replace(text, anchor, '''    BIND_STRUCT_METHOD(st, replaceUniformResponseDynamicsChecked,
                       MARGS("token", "uniformIndex", "scalarType", "devices", "modes", "factors",
                             "enabled", "offsets", "samples", "kinds", "parameters"));
''' + anchor)
updates[path] = text

for path, text in updates.items():
    path.write_text(text, encoding='utf-8', newline='\n')
print('ANALYTIC_RESPONSES_INSTALLED', len(updates))
