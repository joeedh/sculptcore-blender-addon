# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""What actually changed on a brush, by comparing it against the copy on disk.

`Brush.has_unsaved_changes` is one bit: *something* was edited.  To name the
settings, the asset's own blend file has to be read back and compared property
by property.

The read goes through ``bpy.data.temp_data()`` — a second, throwaway Main that
is discarded when the block exits.  Appending the original into ``bpy.data``
would work too, but it adds datablocks to the user's file and marks it dirty at
the exact moment the user is being asked whether to quit, which is the one thing
this addon must not do.
"""

import os

import bpy

# How far to follow pointer properties out of the brush (texture slot, the
# per-mode settings structs).  A bound is needed at all because some of those
# structs point back at their owner.
_MAX_DEPTH = 3

# Identity and runtime bookkeeping, not settings.  `has_unsaved_changes` is
# skipped because it is by definition different — it is what got us here.
_SKIP = frozenset({
    "rna_type", "name", "name_full", "original", "users", "use_fake_user",
    "use_extra_user", "library", "library_weak_reference", "override_library",
    "preview", "session_uid", "tag", "id_type", "asset_data", "has_unsaved_changes",
    # Cursor/UI state that Blender writes on its own as the brush is used.
    "active_tag",
    # Derived from the brush type, not set on it.
    "brush_capabilities", "sculpt_capabilities", "image_paint_capabilities",
    "vertex_paint_capabilities", "weight_paint_capabilities",
})

# The asset metadata worth reporting: editing any of these tags the brush too.
_ASSET_FIELDS = (
    ("description", "Description"),
    ("author", "Author"),
    ("license", "License"),
    ("copyright", "Copyright"),
    ("catalog_simple_name", "Catalog"),
)

# Why a brush could not be diffed.  The report prints these verbatim.
NO_FILE = "the asset file it came from is not on disk"
NOT_IN_FILE = "it is no longer in that file under this name (renamed?)"
NO_TEMP_DATA = "this Blender has no bpy.data.temp_data()"


class BrushDiff:
    """Either a list of changed settings, or why there isn't one."""

    def __init__(self, rows=None, reason=None):
        # [(label, old, new)], in the order the properties are declared.
        self.rows = rows or []
        self.reason = reason

    @property
    def available(self):
        return self.reason is None


def _fmt(value):
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, float):
        return "{:.4g}".format(value)
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(_fmt(item) for item in value) + ")"
    return str(value)


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        # Not an epsilon for "close enough": an untouched setting round-trips
        # bit-identically, so this only absorbs the last-bit noise of a value
        # that was written back unchanged.
        return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _read(struct, identifier):
    """A property's value as something comparable, or `_UNREADABLE`."""
    try:
        value = getattr(struct, identifier)
    except Exception:  # noqa: BLE001 - a property that refuses to be read is skipped
        return _UNREADABLE
    if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
        try:
            return tuple(value)
        except Exception:  # noqa: BLE001
            return _UNREADABLE
    return value


_UNREADABLE = object()


def _curve_text(mapping):
    """A curve mapping as a comparable string: its points, per curve."""
    parts = []
    for curve in mapping.curves:
        points = ", ".join("({:.3f}, {:.3f})".format(point.location[0], point.location[1])
                           for point in curve.points)
        parts.append("[" + points + "]")
    return " ".join(parts)


def _ramp_text(ramp):
    """A colour ramp as a comparable string: its stops."""
    stops = ", ".join("{:.3f}:({:.2f}, {:.2f}, {:.2f}, {:.2f})".format(element.position, *element.color)
                      for element in ramp.elements)
    return "{:s} [{:s}]".format(ramp.interpolation, stops)


def _walk(old, new, prefix, depth, rows):
    for prop in new.bl_rna.properties:
        identifier = prop.identifier
        if identifier in _SKIP or identifier.startswith("is_"):
            continue

        label = prefix + prop.name

        if prop.type == 'POINTER':
            old_value = getattr(old, identifier, None)
            new_value = getattr(new, identifier, None)
            if isinstance(old_value, bpy.types.ID) or isinstance(new_value, bpy.types.ID):
                # A pointer to another datablock (texture, paint curve): the
                # identity is the setting; its contents are their own datablock.
                if _fmt(old_value) != _fmt(new_value):
                    rows.append((label, _fmt(old_value), _fmt(new_value)))
                continue
            if old_value is None or new_value is None:
                if (old_value is None) != (new_value is None):
                    rows.append((label, _fmt(old_value), _fmt(new_value)))
                continue
            if isinstance(new_value, bpy.types.CurveMapping):
                old_text, new_text = _curve_text(old_value), _curve_text(new_value)
                if old_text != new_text:
                    rows.append((label + " (curve)", old_text, new_text))
                continue
            if isinstance(new_value, bpy.types.ColorRamp):
                old_text, new_text = _ramp_text(old_value), _ramp_text(new_value)
                if old_text != new_text:
                    rows.append((label + " (ramp)", old_text, new_text))
                continue
            if depth < _MAX_DEPTH:
                _walk(old_value, new_value, label + " > ", depth + 1, rows)
            continue

        if prop.type == 'COLLECTION':
            continue
        if prop.is_readonly:
            continue

        old_value = _read(old, identifier)
        new_value = _read(new, identifier)
        if old_value is _UNREADABLE or new_value is _UNREADABLE:
            continue
        if prop.type == 'ENUM' and ("" in (old_value, new_value)):
            # Some enums (the texture slot's mapping) build their item list from
            # the paint mode in context, and read back as "" when the stored
            # value is not in that list — which says nothing about whether it
            # changed.  Blender logs its own warning about it; don't add a
            # bogus row on top.
            continue
        if not _same(old_value, new_value):
            rows.append((label, _fmt(old_value), _fmt(new_value)))


def _drop_inactive_size(brush, rows):
    """`size` and `unprojected_size` are two units for one radius, and Blender
    keeps both in step — editing either reports both.  Keep the one the brush is
    actually driven by, which is what its UI shows."""
    inactive = "size" if getattr(brush, "use_locked_size", 'VIEW') == 'SCENE' else "unprojected_size"
    label = brush.bl_rna.properties[inactive].name
    if any(row[0] != label for row in rows):
        return [row for row in rows if row[0] != label]
    return rows


def _asset_rows(old, new):
    """Changes to the asset metadata (description, catalog, tags)."""
    rows = []
    old_data, new_data = old.asset_data, new.asset_data
    if old_data is None or new_data is None:
        return rows
    for identifier, label in _ASSET_FIELDS:
        old_value = getattr(old_data, identifier, None)
        new_value = getattr(new_data, identifier, None)
        if (old_value or "") != (new_value or ""):
            rows.append(("Asset " + label, _fmt(old_value or ""), _fmt(new_value or "")))
    old_tags = ", ".join(sorted(tag.name for tag in old_data.tags))
    new_tags = ", ".join(sorted(tag.name for tag in new_data.tags))
    if old_tags != new_tags:
        rows.append(("Asset Tags", old_tags or "<none>", new_tags or "<none>"))
    return rows


def _diff(old, new):
    rows = []
    _walk(old, new, "", 0, rows)
    rows = _drop_inactive_size(new, rows)
    rows.extend(_asset_rows(old, new))
    return BrushDiff(rows=rows)


def _diff_group(filepath, brushes):
    """Diff every brush that came from one asset file, in one open of it."""
    if not filepath or not os.path.isfile(filepath):
        return {brush.name: BrushDiff(reason=NO_FILE) for brush in brushes}
    if not hasattr(bpy.data, "temp_data"):
        return {brush.name: BrushDiff(reason=NO_TEMP_DATA) for brush in brushes}

    results = {}
    try:
        with bpy.data.temp_data() as temp:
            with temp.libraries.load(filepath, link=False) as (data_from, data_to):
                data_to.brushes = [brush.name for brush in brushes
                                   if brush.name in data_from.brushes]
            originals = {brush.name: brush for brush in temp.brushes}
            for brush in brushes:
                original = originals.get(brush.name)
                if original is None:
                    results[brush.name] = BrushDiff(reason=NOT_IN_FILE)
                else:
                    results[brush.name] = _diff(original, brush)
    except Exception as ex:  # noqa: BLE001 - a report is never worth failing a quit over
        reason = "reading it back failed: {!s}".format(ex)
        for brush in brushes:
            results.setdefault(brush.name, BrushDiff(reason=reason))
    return results


def diff_all(entries):
    """`{brush name: BrushDiff}` for the described brushes.

    Grouped by asset file so a library holding a dozen edited brushes is opened
    once, not a dozen times.
    """
    groups = {}
    for entry in entries:
        groups.setdefault(entry["filepath"], []).append(entry["brush"])

    results = {}
    for filepath, brushes in groups.items():
        results.update(_diff_group(filepath, brushes))
    return results
