# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p=Path('sculptcore_addon/stroke.py');s=p.read_text();a=s.index('        # Roll back the previous provisional group only now');b=s.index('        unified = ',a);block=s[a:b];s=s[:a]+s[b:];a=s.index('        # Only the last provisional dab survives');s=s[:a]+block+s[a:];a=s.index('            # Preview and grab-class strokes re-base');b=s.index('            if live:',a);s=s[:a]+s[b:];p.write_text(s)
p=Path('engine/source/brush/c-api/mesh_stroke_batch_c_api.cc');s=p.read_text();a=s.index('  litestl::util::Vector<spatial::SpatialNode *> nodes;',s.index('static int meshDabInputs'));s=s[:a]+'''  if (n == 0) {
    if (!resolved)
      return (program ? exec->preflightRawProgram(program) : exec->preflightRaw(type)) ? 0 : -1;
    auto result = program ? exec->applyResolvedProgram(program, float3(0.0f), float3(0.0f), true) :
                            exec->applyResolvedDab(type, float3(0.0f), float3(0.0f), true);
    return result.error == props::PropError::ERROR_NONE ? 0 : -1;
  }
'''+s[a:];p.write_text(s)
p=Path('engine/source/brush/c-api/grid_stroke_c_api.cc');s=p.read_text();a=s.index('  auto image =',s.index('static int gridDabInputs'));s=s[:a]+'''  if (n == 0) {
    if (!resolved)
      return (program ? s->exec.preflightRawProgram(program, float3(0.0f), float3(0.0f)) :
                         s->exec.preflightRaw(brush::SculptBrushes(tool), float3(0.0f), float3(0.0f))) ? 0 : -1;
    auto result = program ? s->exec.applyResolvedProgram(program, float3(0.0f), float3(0.0f), true) :
                            s->exec.applyResolvedDab(brush::SculptBrushes(tool), float3(0.0f), float3(0.0f), true);
    return result.error == props::PropError::ERROR_NONE ? 0 : -1;
  }
'''+s[a:];p.write_text(s)
p=Path('engine/source/brush/cage_smooth.h');s=p.read_text();a=s.index('  int dabBatch(');b=s.index('  /** Close the executor step',a);part=s[a:b];part=part.replace('int mirrorCount)','int mirrorCount, bool preserveInputs = false)');part=part.replace('    ensureOverrides(tool, cage);','    if (!exec.preflightRaw(SculptBrushes(tool)))\n      return -1;');part=part.replace('        return;','        return true;');part=part.replace('      exec.clearIsFirstOfStep();\n      std::swap(coData->pages, limitCo_.pages);','      std::swap(coData->pages, limitCo_.pages);\n      if (!exec.lastUniformValidationOk())\n        return false;\n      exec.clearIsFirstOfStep();');part=part.replace('        epilogue();\n      }\n    };','        epilogue();\n      }\n      return true;\n    };');part=part.replace('      brush->writeProps();','      brush->writeDabProps();\n      if (!preserveInputs)\n        brush->clearDeviceInputs();');part=part.replace('      oneImage(math::float3(d[0], d[1], d[2]), math::float3(d[3], d[4], d[5]), d[6]);','      if (!exec.preflightRaw(SculptBrushes(tool)))\n        return -1;\n      ensureOverrides(tool, cage);\n      if (!oneImage(math::float3(d[0], d[1], d[2]), math::float3(d[3], d[4], d[5]), d[6]))\n        return -1;');part=part.replace('        oneImage(math::float3','        if (!oneImage(math::float3').replace('                 d[6]);','                 d[6]))\n          return -1;');s=s[:a]+part+s[b:];p.write_text(s)
