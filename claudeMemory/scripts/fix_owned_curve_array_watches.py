# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the adversarially reviewed array-watch complexity correction."""
from pathlib import Path

ROOT = Path("C:/dev/blender/main")


def edit(path, before, after):
    path = ROOT / path
    text = path.read_text(encoding="utf-8")
    if after in text:
        return
    assert text.count(before) == 1, (path, text.count(before))
    path.write_text(text.replace(before, after), encoding="utf-8", newline="\n")


edit("source/blender/blenkernel/BKE_curvemapping_owned.hh",
     "/** Invalidate only path guards before changing a group's membership or array order. */",
     """/** Invalidate the container watch without traversing unchanged children or detaching records. */
void owned_curve_membership_changed(const IDProperty *property);

/** Invalidate path guards before changing group membership or relocating inline array items. */""")
edit("source/blender/blenkernel/intern/curvemapping_owned.cc",
     "void owned_curve_structure_changed(const IDProperty *property)",
     """void owned_curve_membership_changed(const IDProperty *property)
{
  if (OwnedCurveRegistry *value = live_registry.load()) {
    std::lock_guard lock(value->mutex);
    value->invalidate_watch_locked(property);
  }
}

void owned_curve_structure_changed(const IDProperty *property)""")
edit("source/blender/blenkernel/intern/idprop.cc",
     """  if (item != old) {
    bke::owned_curve_structure_changed(prop);""",
     """  if (item != old) {
    /* Only this slot is replaced; its free hook invalidates its old subtree. */
    bke::owned_curve_membership_changed(prop);""")
edit("source/blender/blenkernel/intern/idprop.cc",
     """  if (newlen != prop->len) {
    bke::owned_curve_structure_changed(prop);
  }""",
     """  if (newlen != prop->len) {
    bke::owned_curve_membership_changed(prop);
  }""")
edit("source/blender/blenkernel/intern/idprop.cc",
     """  /* free trailing items */
  if (newlen < prop->len) {""",
     """  /* Reallocation can move every inline item, including during large shrinks. */
  bke::owned_curve_structure_changed(prop);

  /* free trailing items */
  if (newlen < prop->len) {""")
edit("source/blender/makesrna/intern/rna_access.cc",
     """      if (key + 1 < len) {
        /* move element to be removed to the back */""",
     """      if (key + 1 < len) {
        bke::owned_curve_structure_changed(idprop);
        /* move element to be removed to the back */""")
edit("source/blender/makesrna/intern/rna_access.cc",
     """        if ((array[i].flag & IDP_FLAG_OVERRIDELIBRARY_LOCAL) != 0) {
          memcpy(&tmp, &array[i], sizeof(IDProperty));""",
     """        if ((array[i].flag & IDP_FLAG_OVERRIDELIBRARY_LOCAL) != 0) {
          bke::owned_curve_structure_changed(idprop);
          memcpy(&tmp, &array[i], sizeof(IDProperty));""")
edit("source/blender/blenkernel/intern/curvemapping_owned_test.cc",
     """  IDP_ResizeIDPArray(array, 3);
  EXPECT_FALSE(watch->is_valid());
  EXPECT_FALSE(item_watch->is_valid());""",
     """  IDP_ResizeIDPArray(array, 3);
  EXPECT_FALSE(watch->is_valid());
  EXPECT_TRUE(item_watch->is_valid());""")
