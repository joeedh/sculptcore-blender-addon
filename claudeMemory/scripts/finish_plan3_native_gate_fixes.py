# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
p=Path('engine/tests/test_brush_prepared_execution.cc');s=p.read_text();s=s.replace('    for (auto kind : {FalloffKind::Gaussian, FalloffKind::Curve}) {','    brush.falloff_curve[0] = 0.1f; // Nonzero edge cannot use a bounded spherical query.\n    for (auto kind : {FalloffKind::Gaussian, FalloffKind::Curve}) {');p.write_text(s)
p=Path('engine/source/brush/cage_smooth.h');s=p.read_text();needle='#include "brush_executor.h"';print('cage include',needle in s)
if needle not in s:
 needle='#include "brush/brush_executor.h"'
assert needle in s
s=s.replace(needle,needle+'\n#include "c-api/dab_inputs.h"');needle='      const float *d = dabs + i * 7;';s=s.replace(needle,needle+'\n      DabInputOverlay overlay(*brush);\n      if (!overlay.valid())\n        return -1;');a=s.index('      DabInputOverlay overlay');b=s.index('    return total;',a);part=s[a:b];idx=part.rfind('    }');part=part[:idx]+'      overlay.commit();\n'+part[idx:];s=s[:a]+part+s[b:];p.write_text(s)
p=Path('engine/source/brush/c-api/mesh_stroke_batch_c_api.cc');s=p.read_text();s=s.replace('return result.error == props::PropError::ERROR_NONE ? exec->lastDabNodeCount : -1;', 'return result.error == props::PropError::ERROR_NONE ? exec->lastDabNodeCount : brush::reportStrokeInputFailure(result);');# single wrappers catch structured errors
s=s.replace('    return -1;\n  return exec->lastDabNodeCount;', '    return exec ? brush::reportStrokeInputFailure(exec->lastRegistration) : -1;\n  return exec->lastDabNodeCount;');p.write_text(s)
p=Path('engine/source/brush/c-api/grid_stroke_c_api.cc');s=p.read_text().replace('  if (result.error != props::PropError::ERROR_NONE)\n    return -1;', '  if (result.error != props::PropError::ERROR_NONE)\n    return brush::reportStrokeInputFailure(result);');p.write_text(s)
