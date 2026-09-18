# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p = Path('engine/source/brush/brush_executor.h')
s = p.read_text()
a = s.index('    auto cmd = createCommand(brushType);', s.index('  void execBrush('))
b = s.index('    // Enter/leave frozen-topology', a)
s = s[:a] + '''    if (!preflightRaw(brushType))
      return;
    auto cmd = createCommand(brushType);

''' + s[b:]
a = s.index('    if (!prog || prog->commands.size() == 0)', s.index('  void execProgram('))
b = s.index('    // Topology freeze/thaw', a)
s = s[:a] + '''    if (!preflightRawProgram(prog))
      return;
    if (!prog->commands.size())
      return;
    if (!prepareProgramDeclarations(prog))
      return;

''' + s[b:]
a = s.index('  int applyDab(BrushProgram *prog,')
b = s.index('  /** Release the stroke-long', a)
chunk = s[a:b].replace('if (!prepareProgramDeclarations(prog))', 'if (!preflightRawProgram(prog) || !prepareProgramDeclarations(prog))')
chunk = chunk.replace('    mesh::Mesh *m = tree->m;', '    if (!preflightRaw(brushType))\n      return -1;\n    mesh::Mesh *m = tree->m;')
chunk = chunk.replace('      execProgram(prog, &nodes, center, normal);', '      execProgram(prog, &nodes, center, normal);\n      if (!lastUniformValidationOk())\n        return -1;')
chunk = chunk.replace('      execBrush(m, brushType, &nodes, center, normal);', '      execBrush(m, brushType, &nodes, center, normal);\n      if (!lastUniformValidationOk())\n        return -1;')
s = s[:a] + chunk + s[b:]
needle = '  /** Internal resolved-property CPU mesh entry.'
a=s.index(needle); b=s.index('  props::ScalarRegistrationResult',a)
s = s[:a] + '''  /** Validate raw source semantics without publishing or mutating geometry. */
  bool preflightRaw(SculptBrushes type);
  bool preflightRawProgram(BrushProgram *program);
  bool supportsResolved(SculptBrushes type);
  bool supportsResolvedProgram(BrushProgram *program);

  /** Checked CPU mesh entry with evaluated spherical node selection. */
''' + s[b:]
needle = '    BIND_STRUCT_METHOD(st, lastUniformValidationOk, MARGS());'
s=s.replace(needle,needle+'''
    BIND_STRUCT_METHOD(st, preflightRaw, MARGS("type"));
    BIND_STRUCT_METHOD(st, preflightRawProgram, MARGS("program"));
    BIND_STRUCT_METHOD(st, supportsResolved, MARGS("type"));
    BIND_STRUCT_METHOD(st, supportsResolvedProgram, MARGS("program"));''')
p.write_text(s)
p=Path('engine/source/brush/grid_executor.h'); s=p.read_text()
a=s.index('  int applyDab(SculptBrushes brushType,')
b=s.index('    auto cmd = createCommand(brushType);',a)
s=s[:b]+'    if (!preflightRaw(brushType, origin, normal))\n      return -1;\n'+s[b:]
a=s.index('    if (!prog || prog->commands.size() == 0)',s.index('  int applyProgram('))
s=s[:a]+'''    if (!preflightRawProgram(prog, origin, normal))
      return -1;
'''+s[a:]
needle='  props::ScalarRegistrationResult lastRegistration;'
s=s.replace(needle,'''  bool preflightRaw(SculptBrushes type, float3 origin, float3 normal);
  bool preflightRawProgram(BrushProgram *program, float3 origin, float3 normal);
  bool supportsResolved(SculptBrushes type);
  bool supportsResolvedProgram(BrushProgram *program);

'''+needle)
p.write_text(s)
p=Path('engine/source/brush/brush_program.h'); s=p.read_text(); needle='    BIND_STRUCT_METHOD(st, setCommandInvert, MARGS("idx", "inv"));'; s=s.replace(needle,needle+'\n    BIND_STRUCT_METHOD(st, setCommandScalarChecked, MARGS("idx", "name", "type", "value"));'); p.write_text(s)
