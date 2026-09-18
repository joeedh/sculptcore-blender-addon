# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Share validation between manifest and fixed common-property Python adapters."""
from pathlib import Path
import re

path = Path(__file__).resolve().parents[2] / "engine/python/sculptcore/brush_properties.py"
source = path.read_text(encoding="utf-8")
start = source.index("class UniformProperties:")
methods = source.index("    def read(self, index,", start)
header = source[start:methods].replace("class UniformProperties:", "class UniformProperties(_PropertyAccess):")
body = source[methods:]
body = re.sub(r"self.executor\.(\w+)Uniform(\w+)\(\s*self.token, uniform.index, uniform.scalar_type,?\s*",
              lambda match: 'self._call("' + match[1] + '{}' + match[2] + '", uniform, ', body)
body = body.replace('uniform, ))', 'uniform))')
assert "self.executor." not in body
header += '''    def _call(self, method, uniform, *args):
        return getattr(self.executor, method.format("Uniform"))(
            self.token, uniform.index, uniform.scalar_type, *args)


'''
common = '''@dataclass(frozen=True)
class _ScalarTarget:
    index: int
    scalar_type: int


class CommonProperties(_PropertyAccess):
    """Validated access to fixed BrushProp IDs: 0 strength, 1 radius, 2 autosmooth,
    3 plane offset, 4 spacing, 5 invert. Keep the native Brush alive.

    Native declaration eligibility remains authoritative after kernel queries.
    """

    def __init__(self, manager, brush):
        self.manager = manager
        self.brush = brush

    def _uniform(self, index):
        index = _integer(index)
        if index not in range(6):
            raise IndexError(index)
        return _ScalarTarget(index, BOOL if index == 5 else FLOAT32)

    def _call(self, method, uniform, *args):
        return getattr(self.brush, method.format("Common"))(uniform.index, uniform.scalar_type, *args)
'''
path.write_text(source[:start] + "class _PropertyAccess:\n" + body + "\n\n" + header + common,
                encoding="utf-8", newline="\n")
