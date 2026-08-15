# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Which brush assets have unsaved changes, where they came from, and what
saving them would do.

`Brush.has_unsaved_changes` is Blender's own flag (`BKE_brush_tag_unsaved_
changes`), set on any user-visible edit to a brush that came from an asset
library and cleared when it is saved back.  Everything else here answers the
question that flag does not: *where would saving it go?*  A brush from the
essentials library cannot be written back — Blender saves a copy into a
writable user library instead, which is why the dialog's save button warns that
builtins get duplicated.
"""

import os

import bpy

# Blender's suffix for the one-datablock blend files the asset system manages
# (`BLENDER_ASSET_FILE_SUFFIX`); part of what makes a file writable-in-place.
ASSET_FILE_SUFFIX = ".asset.blend"

# What saving a brush would do.
SAVE_IN_PLACE = 'IN_PLACE'
SAVE_AS_COPY = 'AS_COPY'

# The paint modes a brush is usable in, in the order the UI lists them.
_MODE_FLAGS = (
    ("use_paint_sculpt", "Sculpt"),
    ("use_paint_vertex", "Vertex Paint"),
    ("use_paint_weight", "Weight Paint"),
    ("use_paint_image", "Texture Paint"),
    ("use_paint_sculpt_curves", "Sculpt Curves"),
    ("use_paint_grease_pencil", "Grease Pencil"),
    ("use_paint_uv_sculpt", "UV Sculpt"),
)


def unsaved_brushes():
    """Brush assets with unsaved changes, by name.

    Only brushes imported from an asset library are ever tagged, so brushes
    that live in the current file (which the file's own save covers) are not
    reported here.
    """
    brushes = [brush for brush in bpy.data.brushes if getattr(brush, "has_unsaved_changes", False)]
    brushes.sort(key=lambda brush: brush.name.lower())
    return brushes


def _norm(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(bpy.path.abspath(path))))


def _user_library_for(filepath):
    """The user asset library (from the preferences) whose directory contains
    `filepath`, if any."""
    target = _norm(filepath)
    if not target:
        return None
    for library in bpy.context.preferences.filepaths.asset_libraries:
        root = _norm(library.path)
        if root and (target == root or target.startswith(root + os.sep)):
            return library
    return None


def describe(brush):
    """Where a brush came from and what saving it would do.

    Mirrors `BKE_asset_edit_id_is_writable`: an asset blend file is writable in
    place when it sits inside a *user* asset library (not the bundled
    essentials), carries the asset-system suffix, and the file system agrees.
    """
    library = brush.library
    filepath = library.filepath if library else ""
    abspath = bpy.path.abspath(filepath) if filepath else ""

    user_library = _user_library_for(abspath)
    writable = bool(
        user_library
        and abspath.endswith(ASSET_FILE_SUFFIX)
        and os.path.isfile(abspath)
        and os.access(abspath, os.W_OK)
    )

    if user_library is not None:
        source = user_library.name
    elif abspath:
        source = "Essentials (read-only)"
    else:
        source = "Unknown"

    asset_data = brush.asset_data
    catalog = ""
    if asset_data is not None:
        catalog = asset_data.catalog_simple_name or ""

    modes = [label for prop, label in _MODE_FLAGS if getattr(brush, prop, False)]

    return {
        "brush": brush,
        "name": brush.name,
        "source": source,
        "filepath": abspath,
        "catalog": catalog,
        "modes": modes,
        "disposition": SAVE_IN_PLACE if writable else SAVE_AS_COPY,
    }


def describe_all(brushes=None):
    if brushes is None:
        brushes = unsaved_brushes()
    return [describe(brush) for brush in brushes]


def copy_target_library():
    """The library a read-only brush would be copied into, mirroring the C
    side's `get_user_library_ref_for_save` fallback: the first enabled on-disk
    user library.  None if the preferences list none, in which case saving a
    copy cannot work at all."""
    for library in bpy.context.preferences.filepaths.asset_libraries:
        if not getattr(library, "enabled", True):
            continue
        if getattr(library, "use_remote_url", False):
            continue
        if not library.path:
            continue
        return library
    return None


def _brush_settings(brush):
    """A compact snapshot of the settings most likely to be what was changed."""
    rows = [
        # `size` is a diameter in Blender 5.x, not a radius.
        ("Size", "{:d} px".format(brush.size)),
        ("Strength", "{:.3f}".format(brush.strength)),
        ("Blend", brush.blend),
    ]
    if brush.use_paint_sculpt:
        rows.append(("Sculpt brush type", brush.sculpt_brush_type))
        rows.append(("Auto-smooth", "{:.3f}".format(brush.auto_smooth_factor)))
        rows.append(("Normal weight", "{:.3f}".format(brush.normal_weight)))
    rows.append(("Spacing", "{:d}%".format(brush.spacing)))
    rows.append(("Texture", brush.texture.name if brush.texture else "None"))
    if brush.texture:
        rows.append(("Texture mapping", brush.texture_slot.map_mode))
    rows.append(("Falloff", brush.curve_distance_falloff_preset))
    return rows


def summary_text(entries=None):
    """The report the "Show me what changed" button drops into a text block."""
    if entries is None:
        entries = describe_all()

    target = copy_target_library()
    lines = []
    lines.append("Brush assets with unsaved changes")
    lines.append("=================================")
    lines.append("")
    lines.append("{:d} brush asset(s) have been edited this session and would be lost on quit."
                 .format(len(entries)))
    lines.append("")
    lines.append("Blender records that a brush changed, not which settings changed, so what")
    lines.append("follows is each brush's current state and where saving it would put it —")
    lines.append("not a diff against the copy on disk.")
    lines.append("")

    num_copies = sum(1 for entry in entries if entry["disposition"] == SAVE_AS_COPY)
    if num_copies:
        lines.append("{:d} of them came from a read-only library (the builtin Essentials brushes)."
                     .format(num_copies))
        if target is not None:
            lines.append('Saving those writes a *copy* into the "{:s}" asset library ({:s});'
                         .format(target.name, bpy.path.abspath(target.path)))
            lines.append("the builtin brush itself is left as it ships.")
        else:
            lines.append("There is no user asset library configured to copy them into, so those")
            lines.append("cannot be saved at all — add one in Preferences > File Paths > Asset")
            lines.append("Libraries first.")
        lines.append("")

    for index, entry in enumerate(entries, 1):
        lines.append("-" * 78)
        lines.append("{:d}. {:s}".format(index, entry["name"]))
        lines.append("-" * 78)
        lines.append("   Library:     {:s}".format(entry["source"]))
        if entry["catalog"]:
            lines.append("   Catalog:     {:s}".format(entry["catalog"]))
        lines.append("   Asset file:  {:s}".format(entry["filepath"] or "<unknown>"))
        lines.append("   Used in:     {:s}".format(", ".join(entry["modes"]) or "<none>"))
        if entry["disposition"] == SAVE_IN_PLACE:
            lines.append("   On save:     updated in place")
        elif target is not None:
            lines.append('   On save:     saved as a new copy in "{:s}"'.format(target.name))
        else:
            lines.append("   On save:     cannot be saved (no writable asset library)")
        lines.append("")
        lines.append("   Current settings")
        for label, value in _brush_settings(entry["brush"]):
            lines.append("     {:<20s} {:s}".format(label + ":", str(value)))
        lines.append("")

    lines.append("-" * 78)
    lines.append("Saving from here: File > Quit and press \"Save All\", or use the brush's own")
    lines.append("Save / Save As entries in the brush asset menu for one brush at a time.")
    lines.append("")
    return "\n".join(lines)
