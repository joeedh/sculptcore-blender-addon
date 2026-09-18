# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run a prefix of the lifecycle harness to isolate shutdown retention."""
from pathlib import Path
import sys

stage = sys.argv[-1]
cleanup = sys.argv[-2] if len(sys.argv) > 2 else "none"
path = Path(__file__).with_name("test_owned_curve_rna.py")
source = path.read_text()
if stage == "save":
    end = source.index('    bpy.data.libraries.write(')
elif stage == "write":
    end = source.index('    with bpy.data.libraries.load(')
elif stage == "link":
    end = source.index('    linked_curve = ')
else:
    marker = '    done("{}")'.format(stage)
    end = source.index(marker) + len(marker)
sys.argv = [sys.argv[0]]
exec(compile(source[:end] + "\n", str(path), "exec"), globals())
if cleanup == "cleanup_manager":
    del target, _
elif cleanup == "cleanup_handles":
    del retained_new, stale_new, iterator
elif cleanup == "cleanup_declarations":
    for cls in (bpy.types.Brush, bpy.types.Scene):
        del cls.owned_test
        del cls.owned_direct
    bpy.utils.unregister_class(OwnedCurveRNARoot)
    bpy.utils.unregister_class(OwnedCurveRNAItem)
import gc
gc.collect()
