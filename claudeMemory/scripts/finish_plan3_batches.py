# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p=Path('engine/source/brush/c-api/grid_stroke_c_api.cc'); s=p.read_text()
for fn,prog in [('GridStroke_dabBatch',False),('GridStroke_dabBatchProgram',True)]:
    a=s.index('int '+fn+'('); a=s.index('\n{',a); depth=1; b=a+2
    while depth:
        b+=1; depth += (s[b]=='{')-(s[b]=='}')
    body='''
{
  if (n < 0 || n > INT_MAX / 7)
    return -1;
  litestl::util::Vector<float> samples;
  samples.resize(size_t(n) * 6);
  for (int i = 0; i < n; i++) {
    float *row = samples.data() + i * 6;
    row[0] = usePressure ? pressure : 0;
    row[1] = row[2] = row[3] = 0;
    row[4] = usePressure ? 1 : 0;
    row[5] = invert != 0;
  }
  return gridDabInputs(s, TOOL, PROGRAM, n, dabs, strength,
                       samples.data(), signs, mirrorCount, 0);
}'''.replace('PROGRAM','prog' if prog else 'nullptr').replace('TOOL','0' if prog else 'tool')
    s=s[:a]+body+s[b+1:]
a=s.index('int GridStroke_dab('); b=s.index('/** One logical dab',a)
chunk=s[a:b].replace('    return 0;', '    return -1;').replace('  s->exec.setGrabAccumAdd', '''  if (!s->exec.preflightRaw(brush::SculptBrushes(tool), float3(ox, oy, oz), float3(nx, ny, nz)))
    return -1;
  s->exec.setGrabAccumAdd''')
s=s[:a]+chunk+s[b:]
p.write_text(s)
# Empty resolved programs validate stray stacks too, before advancing a step.
for file in ['engine/source/brush/brush_executor.cc','engine/source/brush/grid_executor.cc']:
    p=Path(file); s=p.read_text(); needle='  if (!program->commands.size()) {\n'
    s=s.replace(needle,needle+'''    PreparedBrushScalars empty;
    lastRegistration = prepareBrushScalars(*brush, {}, brush->deviceInputCtx, empty);
    if (lastRegistration.error != PropError::ERROR_NONE)
      return lastRegistration;
''',1)
    p.write_text(s)
