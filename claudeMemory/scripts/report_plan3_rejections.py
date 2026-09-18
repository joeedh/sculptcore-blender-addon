# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
for filename in ['engine/source/brush/brush_executor.cc', 'engine/source/brush/grid_executor.cc']:
 p=Path(filename);s=p.read_text()
 # Report at the public raw preflight failure boundary.
 if 'brush_executor.cc' in filename:
  s=s.replace('  strokeValidationFailed = !lastValidation.ok;\n  return lastValidation.ok;', '  strokeValidationFailed = !lastValidation.ok;\n  if (!lastValidation.ok)\n    fprintf(stderr, "SculptCore: rejected %s (property status %d)\\n", lastRegistration.name.c_str(), int(lastRegistration.error));\n  return lastValidation.ok;')
 else:
  s=s.replace('  return lastRegistration.error == props::PropError::ERROR_NONE;', '  if (lastRegistration.error != props::PropError::ERROR_NONE)\n    fprintf(stderr, "SculptCore: rejected %s (property status %d)\\n", lastRegistration.name.c_str(), int(lastRegistration.error));\n  return lastRegistration.error == props::PropError::ERROR_NONE;')
 p.write_text(s)
