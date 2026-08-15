# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Verify that an assembled install comes up with this repo's addons enabled.

Run headless by the staging tools once the ``.always_enable`` marker has been
written next to the addon (see ``build-blender-dist.mjs`` / ``fetch-blender-
dist.mjs``)::

    blender --background --factory-startup --python tools/verify_addon.py

``--factory-startup`` is deliberate: the marker is read by ``addon_utils`` at
startup and owes nothing to the user preferences, so a factory-startup launch
proves the addon is on with *no* ``userpref.blend`` involved at all.  The
preferences check below is the other half of that contract — the addon must be
enabled without ever appearing in (and therefore without ever being saved into)
the user's preferences.
"""

import sys

import addon_utils
import bpy

MODULE = "sculptcore_addon"
# The other add-ons an install ships; enabled the same way, by the same marker.
MODULES = (MODULE, "brush_save_reminder")

failures = []

for module in MODULES:
    if not addon_utils.check(module)[1]:
        failures.append("{!r} is not enabled".format(module))

# Only meaningful against the factory preferences: a developer's own global
# config may legitimately still list the addon from a manual enable long ago
# (harmless — `_initialize_once` skips a prefs entry that is always-enabled).
if bpy.app.factory_startup:
    listed = {addon.module for addon in bpy.context.preferences.addons}
    for module in MODULES:
        if module in listed:
            failures.append("{!r} leaked into the user preferences".format(module))

# Registration actually ran (not just the module import): the stroke operator is
# the addon's most load-bearing class. `bpy.ops` cannot be probed for this —
# `bpy.ops.<anything>.<anything>` resolves lazily without checking — but an
# unregistered class is genuinely absent from `bpy.types`.
if not hasattr(bpy.types, "SCULPTCORE_OT_brush_stroke"):
    failures.append("sculptcore.brush_stroke operator is not registered")
if not hasattr(bpy.types, "BRUSHSAVE_OT_quit_dialog"):
    failures.append("brush_save_reminder.quit_dialog operator is not registered")

if failures:
    for msg in failures:
        sys.stderr.write("verify_addon: FAILED: {:s}\n".format(msg))
    sys.exit(1)

print("verify_addon: {:s} enabled by default (no userpref)"
      .format(", ".join(repr(module) for module in MODULES)))
