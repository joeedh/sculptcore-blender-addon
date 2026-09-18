# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the reviewed independent command-stack boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def edit(path, old, new):
    path = ROOT / path
    text = path.read_text(encoding='utf-8')
    assert text.count(old) == 1, (path, old[:90], text.count(old))
    path.write_text(text.replace(old, new), encoding='utf-8', newline='\n')


header = 'engine/source/brush/brush_configuration.h'
args = '''const util::Vector<int> &devices,
    const util::Vector<int> &modes,
    const util::Vector<float> &factors,
    const util::Vector<int> &enabled,
    const util::Vector<int> &offsets,
    const util::Vector<float> &samples,
    const util::Vector<int> &kinds,
    const util::Vector<double> &parameters'''
edit(header, '#include "litestl/binding/binding.h"',
     '#include "litestl/binding/binding.h"\n#include "props/prop_dynamics.h"')
edit(header, '/** An owned scalar response;', '''/** Decode into a candidate; neither caller buffers nor output change on failure. */
int decodeResponseDynamics(''' + args + ''', props::Dynamics &output);

/** An owned scalar response;''')
path = ROOT / 'engine/source/brush/brush_configuration.cc'
text = path.read_text(encoding='utf-8')
start = text.index('  size_t count = devices.size();', text.index('int Brush::replaceResponseDynamicsChecked'))
end = text.index('\nstatic int legacyType', start)
body = text[start:end].replace('  return commitDynamics(*target, candidate);',
                             '  output = std::move(candidate);\n  return int(PropError::ERROR_NONE);')
text = text[:start] + '''  Dynamics candidate;
  int status = decodeResponseDynamics(devices, modes, factors, enabled, offsets,
                                      samples, kinds, parameters, candidate);
  return status ? status : commitDynamics(*target, candidate);
}

int decodeResponseDynamics(''' + args + ''', props::Dynamics &output)
{
''' + body + text[end:]
path.write_text(text, encoding='utf-8', newline='\n')

header = 'engine/source/brush/brush_program.h'
edit(header, '#include "props/prop_enums.h"', '#include "props/prop_enums.h"\n#include "props/prop_dynamics.h"')
edit(header, '/** Redirects one of a kernel', '''/** Present empty dynamics explicitly disable the inherited brush stack. */
struct BrushDynamicsOverride {
  util::string name;
  props::Prop type = props::Prop::INVALID_TYPE;
  props::Dynamics dynamics;
};

/** Redirects one of a kernel''')
edit(header, '  Vector<BrushScalarOverride> scalarOverrides;',
     '  Vector<BrushScalarOverride> scalarOverrides;\n  Vector<BrushDynamicsOverride> dynamicsOverrides;')
edit(header, '  void setCommandInvert(int idx, bool inv)', '''  /** Candidate replacement; kernel membership is validated before execution. */
  int replaceCommandResponseDynamicsChecked(int idx, util::string name, int scalarType,
      ''' + args.replace('const ', '') + ''');
  /** Remove the local stack so this command inherits the brush again. */
  int removeCommandDynamicsChecked(int idx, util::string name, int scalarType);

  void setCommandInvert(int idx, bool inv)''')
edit(header, '    BIND_STRUCT_METHOD(st, setCommandInvert, MARGS("idx", "inv"));', '''    BIND_STRUCT_METHOD(st, replaceCommandResponseDynamicsChecked,
      MARGS("idx", "name", "scalarType", "devices", "modes", "factors", "enabled",
            "offsets", "samples", "kinds", "parameters"));
    BIND_STRUCT_METHOD(st, removeCommandDynamicsChecked, MARGS("idx", "name", "scalarType"));
    BIND_STRUCT_METHOD(st, setCommandInvert, MARGS("idx", "inv"));''')

source = 'engine/source/brush/brush_program_preparation.cc'
edit(source, '#include "brush_command.h"', '#include "brush_command.h"\n#include "brush_configuration.h"')
edit(source, 'props::ScalarRegistrationResult programError', '''static PropError commandStackTarget(const BrushProgram &program, int idx,
                                    const util::string &name, int scalarType)
{
  if (idx < 0 || size_t(idx) >= program.commands.size() || !name.size() ||
      std::strlen(name.c_str()) != name.size())
    return PropError::ERROR_NOT_EXISTS;
  if (scalarType != int(Prop::FLOAT32) && scalarType != int(Prop::INT32) && scalarType != int(Prop::BOOL))
    return PropError::ERROR_INVALID_TYPE;
  return PropError::ERROR_NONE;
}

int BrushProgram::replaceCommandResponseDynamicsChecked(int idx, util::string name, int scalarType,
    ''' + args.replace('const ', '') + ''')
{
  auto error = commandStackTarget(*this, idx, name, scalarType);
  if (error != PropError::ERROR_NONE)
    return int(error);
  BrushDynamicsOverride candidate{name, Prop(scalarType), {}};
  int status = decodeResponseDynamics(devices, modes, factors, enabled, offsets,
                                     samples, kinds, parameters, candidate.dynamics);
  if (status)
    return status;
  for (auto &item : commands[idx].dynamicsOverrides) {
    if (item.name == name) {
      item = std::move(candidate);
      return 0;
    }
  }
  commands[idx].dynamicsOverrides.append(std::move(candidate));
  return 0;
}

int BrushProgram::removeCommandDynamicsChecked(int idx, util::string name, int scalarType)
{
  auto error = commandStackTarget(*this, idx, name, scalarType);
  if (error != PropError::ERROR_NONE)
    return int(error);
  Vector<BrushDynamicsOverride> candidate;
  for (const auto &item : commands[idx].dynamicsOverrides) {
    if (item.name == name) {
      if (item.type != Prop(scalarType))
        return int(PropError::ERROR_INVALID_TYPE);
    } else {
      candidate.append(item);
    }
  }
  commands[idx].dynamicsOverrides = std::move(candidate);
  return 0;
}

props::ScalarRegistrationResult programError''')
edit(source, '                                      {scope.data(), scope.size()});',
     '''                                      {scope.data(), scope.size()},
                                      ScalarSource::Authored,
                                      {command.dynamicsOverrides.data(), command.dynamicsOverrides.size()});''')

header = 'engine/source/brush/brush_preparation.h'
edit(header, 'struct BrushScalarOverride;', 'struct BrushScalarOverride;\nstruct BrushDynamicsOverride;')
edit(header, '                      ScalarSource);',
     '                      ScalarSource, std::span<const BrushDynamicsOverride>);')
edit(header, '                    ScalarSource source = ScalarSource::Authored);',
     '''                    ScalarSource source = ScalarSource::Authored,
                    std::span<const BrushDynamicsOverride> dynamicsOverrides = {});''')
source = 'engine/source/brush/brush_preparation.cc'
edit(source, '                       ScalarSource source)',
     '                       ScalarSource source, const BrushDynamicsOverride *stackOverride)')
edit(source, '    T evaluated = base;\n    if (typed && result.dynamic &&\n        !typed->dynamics.evaluateChecked(',
     '''    T evaluated = base;
    const props::Dynamics *dynamics = stackOverride ? &stackOverride->dynamics :
                                                     typed ? &typed->dynamics : nullptr;
    if (dynamics && result.dynamic &&
        !dynamics->evaluateChecked(''')
edit(source, '                    ScalarSource source)',
     '                    ScalarSource source, std::span<const BrushDynamicsOverride> dynamicsOverrides)')
edit(source, '''        auto error =
            prepareValue(brush, value, declaration, common, inputs, override, source);''',
     '''        const BrushDynamicsOverride *stackOverride = nullptr;
        for (const auto &item : dynamicsOverrides) {
          if (item.name == value.name) {
            if (stackOverride)
              return PropError::ERROR_SCHEMA_CONFLICT;
            if (item.type != value.type)
              return PropError::ERROR_INVALID_TYPE;
            if (!value.dynamic || source != ScalarSource::Authored ||
                !props::Dynamics::validStack(item.dynamics.devices))
              return PropError::ERROR_INVALID_DYNAMICS;
            stackOverride = &item;
          }
        }
        auto error = prepareValue(brush, value, declaration, common, inputs,
                                  override, source, stackOverride);''')
edit(source, '  for (auto *property : brush.props.struct_def->properties()) {', '''  for (const auto &item : dynamicsOverrides) {
    bool found = false;
    for (const auto &value : candidate.values_)
      found |= value.name == item.name;
    if (!found)
      return {PropError::ERROR_NOT_EXISTS, item.name};
  }
  for (auto *property : brush.props.struct_def->properties()) {''')
for name in ('brush_executor.cc', 'grid_executor.cc', 'brush_executor.h', 'grid_executor.h'):
    edit('engine/source/brush/' + name, 'if (entry.scalarOverrides.size()',
         'if (entry.dynamicsOverrides.size() || entry.scalarOverrides.size()')

source = ROOT / 'engine/python/sculptcore/brush_properties.py'
text = source.read_text(encoding='utf-8')
start = text.index('        if len(layers) > 4:', text.index('    def replace_stack'))
end = text.index('\n    def set_sample(', start)
body = text[start:end]
validation = body[:body.index('        with ExitStack()')]
validation = '\n'.join(line[4:] if line.startswith('    ') else line for line in validation.splitlines())
helper = '\n\ndef _stack_arrays(layers):\n' + validation + '''
    return (("int32", devices), ("int32", modes), ("float", factors),
            ("int32", enabled), ("int32", offsets), ("float", samples),
            ("int32", kinds), ("double", parameters))


def replace_command_stack(manager, program, command, name, scalar_type, layers):
    """Explicit empty disables inheritance; complete upload preserves state on failure."""
    command = _integer(command)
    if not isinstance(name, str) or not name or '\\x00' in name:
        raise ValueError("Expected a nonempty property name without NUL")
    if _integer(scalar_type) not in (FLOAT32, INT32, BOOL):
        raise ValueError("Unsupported scalar type")
    arrays = _stack_arrays(layers)
    with ExitStack() as stack:
        vectors = [stack.enter_context(_primitive_vector(manager, kind, values)) for kind, values in arrays]
        _check(program.replaceCommandResponseDynamicsChecked(command, name, scalar_type, *vectors))


def inherit_command_stack(program, command, name, scalar_type):
    """Remove an explicit override to inherit the live brush stack."""
    command = _integer(command)
    if not isinstance(name, str) or not name or '\\x00' in name:
        raise ValueError("Expected a nonempty property name without NUL")
    if _integer(scalar_type) not in (FLOAT32, INT32, BOOL):
        raise ValueError("Unsupported scalar type")
    _check(program.removeCommandDynamicsChecked(command, name, scalar_type))
'''
text = text[:start] + '''        arrays = _stack_arrays(layers)
        with ExitStack() as stack:
            vectors = [stack.enter_context(_primitive_vector(self.manager, kind, values))
                       for kind, values in arrays]
            _check(self._call("replace{}ResponseDynamicsChecked", uniform, *vectors))
''' + text[end:]
text = text.replace('\n\nclass _PropertyAccess:', helper + '\n\nclass _PropertyAccess:')
source.write_text(text, encoding='utf-8', newline='\n')
