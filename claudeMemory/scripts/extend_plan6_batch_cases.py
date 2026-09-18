# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise explicit stack rejection and restoration through public batch APIs."""
from pathlib import Path

path = Path(__file__).resolve().parents[2] / 'engine/tests/test_brush_typed_extras.cc'
text = path.read_text(encoding='utf-8')
start, end = text.index('static void publicInputs('), text.index('static void publicInputs(')
end = text.index('\nstatic ', start + 1)
body = text[start:end]
body = body.replace('    meshlog::MeshLog log;', '''    if (programMode) {
      auto &command = program.commands[0];
      command.dynamicsOverrides.append({"typed_count", Prop::INT32, count->dynamics});
      command.dynamicsOverrides.append({"typed_enabled", Prop::BOOL, enabled->dynamics});
      command.dynamicsOverrides.append({"typed_gain", Prop::FLOAT32, gain->dynamics});
      // A different authored stack must not leak into the explicit command.
      gain->dynamics.devices[0].mixFactor = 0.5f;
    }
    meshlog::MeshLog log;''')
body = body.replace('auto runBatch = [&](int n, const float *d, const float *s)',
                    'auto runBatch = [&](int n, const float *d, const float *s, int policy = 1)')
body = body.replace('nullptr, 0, 1)', 'nullptr, 0, policy)')
body = body.replace('                                                            1)\n',
                    '                                                            policy)\n')
body = body.replace('                                                     1);',
                    '                                                     policy);')
point = '    samples[22] = 16;'
body = body.replace(point, '''    if (programMode) {
      // With scalar overrides removed, stack presence alone must force rejection.
      auto saved = program.commands[0];
      program.commands[0].scalarOverrides.clear();
      program.commands[0].dynamicsOverrides.clear();
      program.commands[0].dynamicsOverrides.append({"radius", Prop::FLOAT32, {}});
      const auto working = workingBytes(brush);
      for (int policy : {0, 2}) {
        program.commands[0].type = policy == 2 ? SculptBrushes::KELVINLET : SculptBrushes(tool);
        test_assert(runBatch(0, nullptr, nullptr, policy) == -1);
        test_assert(runBatch(1, dabs, samples, policy) == -1);
        test_assert(workingBytes(brush) == working && brush.strokePathCount == 0);
        unchanged();
      }
      program.commands[0] = saved;
    }
''' + point)
text = text[:start] + body + text[end:]
path.write_text(text, encoding='utf-8', newline='\n')
