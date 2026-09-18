# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Add independent native command-stack regression cases to existing suites."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'engine/tests/test_brush_prepared_execution.cc'
text = path.read_text(encoding='utf-8')
point = 'static BrushProgram drawSmoothProgram(bool resolved)'
addition = '''static void commandStackConfiguration()
{
  BrushProgram program;
  program.addCommand(int(SculptBrushes::DRAW));
  Vector<int> devices, modes, enabled, offsets, kinds;
  Vector<float> factors, samples;
  Vector<double> parameters;
  offsets.append(0);
  auto replace = [&](int index = 0) {
    return program.replaceCommandResponseDynamicsChecked(index, "radius", int(props::Prop::FLOAT32),
        devices, modes, factors, enabled, offsets, samples, kinds, parameters);
  };
  test_assert(replace() == 0);
  test_assert(program.commands[0].dynamicsOverrides.size() == 1);
  test_assert(program.commands[0].dynamicsOverrides[0].dynamics.devices.size() == 0);
  test_assert(replace(-1) != 0);
  devices.append(0);
  test_assert(replace() != 0);
  test_assert(program.commands[0].dynamicsOverrides[0].dynamics.devices.size() == 0);
  modes.append(1); factors.append(1); enabled.append(1); offsets.append(0); kinds.append(2);
  const double threshold = 0.5000000000000001;
  parameters.append(threshold); parameters.append(0.25); parameters.append(0.75);
  test_assert(replace() == 0);
  test_assert(parameters[0] == threshold && offsets.size() == 2);
  const auto &layer = program.commands[0].dynamicsOverrides[0].dynamics.devices[0];
  test_assert(layer.responseThreshold == threshold && !layer.hasDeviceValue);
  test_assert(program.removeCommandDynamicsChecked(0, "radius", int(props::Prop::INT32)) != 0);
  test_assert(program.commands[0].dynamicsOverrides.size() == 1);
  test_assert(program.removeCommandDynamicsChecked(0, "radius", int(props::Prop::FLOAT32)) == 0);
  test_assert(program.commands[0].dynamicsOverrides.size() == 0);
}

'''
assert point in text
text = text.replace(point, addition + point)
# Existing multi-leaf reference has exact .8/2 radii; independently configured
# command stacks now produce these from .3/1.5 without touching the brush stack.
text = text.replace('  return program;\n}\n\nstatic std::vector<float3> programGeometry', '''  if (resolved) {
    BrushDynamicsOverride main{"radius", props::Prop::FLOAT32, {}};
    main.dynamics.configure(props::DeviceType::PRESSURE, math::BasicMix::ADD, 1);
    program.commands[draw].dynamicsOverrides.append(main);
    BrushDynamicsOverride later{"radius", props::Prop::FLOAT32, {}};
    later.dynamics.configure(props::DeviceType::TILTX, math::BasicMix::ADD, 1);
    program.commands[smooth].dynamicsOverrides.append(later);
    program.commands[smooth].dynamicsOverrides.append({"strength", props::Prop::FLOAT32, {}});
  }
  return program;
}

static std::vector<float3> programGeometry''')
point = '    BrushProgram program = drawSmoothProgram(resolved);'
text = text.replace(point, point + '''
    brush.pushDeviceInput(int(props::DeviceType::TILTX), 0.5f);''')
point = '    program.commands[1].type = SculptBrushes::DRAW;\n    auto *strength'
text = text.replace(point, '''    program.commands[1].type = SculptBrushes::DRAW;
    program.commands[1].dynamicsOverrides.append({"missing", props::Prop::FLOAT32, {}});
    rejects();
    program.commands[1].dynamicsOverrides[0].name = "radius";
    program.commands[1].dynamicsOverrides[0].type = props::Prop::INT32;
    rejects();
    program.commands[1].dynamicsOverrides[0].type = props::Prop::FLOAT32;
    program.commands[1].dynamicsOverrides.append({"radius", props::Prop::FLOAT32, {}});
    rejects();
    program.commands[1].dynamicsOverrides.clear();
    program.commands[0].dynamicsOverrides.append({"strength", props::Prop::FLOAT32, {}});
    program.commands[1].dynamicsOverrides.append({"strength", props::Prop::FLOAT32, {}});
    auto *strength''')
point = '    const auto previous = state();\n    test_assert(!(grid ? gridEx.prepareProgramDeclarations'
text = text.replace(point, '''    program.commands[0].scalarOverrides.clear();
    program.commands[0].dynamicsOverrides.append({"radius", props::Prop::FLOAT32, {}});
    const auto previous = state();
    test_assert(!(grid ? gridEx.preflightRawProgram(&program) : meshEx.preflightRawProgram(&program)));
    test_assert((grid ? gridEx.applyProgram(&program, float3(100), normalForTest()) : 0) == 0);
    test_assert(!(grid ? gridEx.prepareProgramDeclarations'''.replace(
        '    test_assert((grid ? gridEx.applyProgram(&program, float3(100), normalForTest()) : 0) == 0);\n',
        '''    test_assert((grid ? gridEx.applyProgram(&program, float3(100), float3(0, 0, 1)) :
                        meshEx.applyDab(&program, float3(100), float3(0, 0, 1), 2, nullptr, 0)) == -1);
'''))
text = text.replace('    programRejection(grid);', '    programRejection(grid);')
text = text.replace('  return test_end();', '  commandStackConfiguration();\n  return test_end();')
path.write_text(text, encoding='utf-8', newline='\n')

path = ROOT / 'engine/tests/test_brush_typed_extras.cc'
text = path.read_text(encoding='utf-8')
point = '    program.commands[1].scalarOverrides.append({"typed_count", Prop::INT32, 16777217.5});'
addition = '''    // Cold command stacks must evaluate without creating authored properties.
    for (int index = 0; index < 2; index++) {
      BrushDynamicsOverride gainStack{"typed_gain", Prop::FLOAT32, {}};
      gainStack.dynamics.configure(props::DeviceType::PRESSURE, math::BasicMix::MULTIPLY, 1);
      gainStack.dynamics.devices[0].responseKind = 1;
      gainStack.dynamics.devices[0].responseLow = 1;
      program.commands[index].dynamicsOverrides.append(gainStack);
      BrushDynamicsOverride countStack{"typed_count", Prop::INT32, {}};
      countStack.dynamics.configure(props::DeviceType::TILTX, math::BasicMix::ADD, 1);
      countStack.dynamics.devices[0].curveTable.append(1);
      countStack.dynamics.devices[0].curveTable.append(0);
      program.commands[index].dynamicsOverrides.append(countStack);
      BrushDynamicsOverride boolStack{"typed_enabled", Prop::BOOL, {}};
      boolStack.dynamics.configure(props::DeviceType::TILTY, math::BasicMix::MULTIPLY, 1);
      boolStack.dynamics.devices[0].responseKind = 2;
      boolStack.dynamics.devices[0].responseThreshold = 0.5;
      boolStack.dynamics.devices[0].responseHigh = 1;
      program.commands[index].dynamicsOverrides.append(boolStack);
    }
    brush.pushDeviceInput(int(props::DeviceType::PRESSURE), 0.1f);
    brush.pushDeviceInput(int(props::DeviceType::TILTX), 1);
    brush.pushDeviceInput(int(props::DeviceType::TILTY), 0.5f);
'''
assert text.count(point) == 1
text = text.replace(point, addition + point)
point = '    test_assert(meshEx.queryUniformManifest(tool) == 8);\n    auto *count'
assert text.count(point) == 1
text = text.replace(point, '''    brush.clearDeviceInputs();
    for (auto &command : program.commands)
      command.dynamicsOverrides.clear();
    test_assert(meshEx.queryUniformManifest(tool) == 8);
    auto *count''')
path.write_text(text, encoding='utf-8', newline='\n')
