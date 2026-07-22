# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Enable the SculptCore addon and save a portable ``userpref.blend``.

Run headless by ``tools/build-blender-dist.mjs`` with ``BLENDER_USER_CONFIG``
pointed at the dist's ``<version>/config`` directory, so the resulting install
has the addon enabled by default (portable Blender reads that same config when
launched from the install folder).
"""

import sys

import addon_utils
import bpy

MODULE = "sculptcore_addon"

mod = addon_utils.enable(MODULE, default_set=True, persistent=True)
if mod is None:
    # Do not hard-fail: still save the userpref so the state is inspectable,
    # but signal the build script via a non-zero exit.
    sys.stderr.write("enable_addon: FAILED to enable {!r}\n".format(MODULE))
    bpy.ops.wm.save_userpref()
    sys.exit(1)

bpy.ops.wm.save_userpref()
print("enable_addon: {!r} enabled and userpref saved".format(MODULE))
