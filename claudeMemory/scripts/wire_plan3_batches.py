# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p=Path('engine/source/brush/c-api/mesh_stroke_batch_c_api.cc'); s=p.read_text()
s=s.replace('int MeshStroke_dabBatchProgramInputs(brush::CommandExecutor *exec,', 'static int meshDabInputs(brush::CommandExecutor *exec,',1)
s=s.replace('return MeshStroke_dabBatchProgramInputs(exec, tree, mesh, brush, nullptr,', 'return meshDabInputs(exec, tree, mesh, brush, nullptr,',1)
pos=s.index('/** Batch raycast:')
s=s[:pos]+'''int MeshStroke_dabBatchProgramInputs(brush::CommandExecutor *exec, spatial::SpatialTree *tree,
                                     mesh::Mesh *mesh, brush::Brush *brush, brush::BrushProgram *program,
                                     int n, const float *dabs, float strength, const float *inputs,
                                     float filterMul, const float *signs, int mirrors, int policy)
{
  if (!program)
    return -1;
  return meshDabInputs(exec, tree, mesh, brush, program, n, dabs, strength,
                       inputs, filterMul, signs, mirrors, policy, 0);
}

'''+s[pos:]
# Retain original ABI and raw source policy; use the checked shared dab loop.
for fn,prog in [('MeshStroke_dabBatch',False),('MeshStroke_dabBatchProgram',True)]:
    a=s.index('int '+fn+'('); a=s.index('\n{',a); depth=1; b=a+2
    while depth:
        b+=1
        depth += (s[b]=='{')-(s[b]=='}')
    args='prog' if prog else 'nullptr'
    tool='0' if prog else 'tool'
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
  return meshDabInputs(exec, tree, m, b, PROGRAM, n, dabs, strength,
                       samples.data(), filterMul, signs, mirrorCount, 0, TOOL);
}'''.replace('PROGRAM',args).replace('TOOL',tool)
    s=s[:a]+body+s[b+1:]
p.write_text(s)
