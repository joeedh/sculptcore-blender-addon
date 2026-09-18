/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

TEST_F(OwnedCurveRuntimeTest, PathWatchGroupMutationAndLifetime)
{
  auto root_watch = OwnedCurvePathWatch::acquire(*owner, *owner->properties);
  EXPECT_EQ(root_watch, OwnedCurvePathWatch::acquire(*owner, *owner->properties));
  auto definition_watch = OwnedCurvePathWatch::acquire(*owner, *definition);
  IDProperty *extra = IDP_NewString("extension", "extra");
  IDP_AddToGroup(owner->properties, extra);
  EXPECT_FALSE(root_watch->is_valid());
  EXPECT_TRUE(definition_watch->is_valid());
  EXPECT_TRUE(record->is_attached());
  auto replacement_watch = OwnedCurvePathWatch::acquire(*owner, *owner->properties);
  EXPECT_NE(root_watch, replacement_watch);
  IDP_ReplaceInGroup(owner->properties, IDP_NewString("replacement", "extra"));
  EXPECT_FALSE(replacement_watch->is_valid());
  auto removal_watch = OwnedCurvePathWatch::acquire(*owner, *owner->properties);
  IDP_FreeFromGroup(owner->properties, IDP_GetPropertyFromGroup(owner->properties, "extra"));
  EXPECT_FALSE(removal_watch->is_valid());
  EXPECT_TRUE(definition_watch->is_valid());
  owned_curve_invalidate_owner(owner);
  EXPECT_FALSE(definition_watch->is_valid());
  EXPECT_FALSE(record->is_attached());
}

TEST_F(OwnedCurveRuntimeTest, PathWatchArrayIdentityIsIndependentOfCurveRecords)
{
  IDProperty *array = IDP_NewIDPArray("items");
  IDP_AddToGroup(owner->properties, array);
  IDP_ResizeIDPArray(array, 2);
  for (int i = 0; i < 2; i++) {
    auto item = idprop::create_group("");
    IDP_SetIndexArray(array, i, item.get());
    MEM_delete(item.release());
  }
  auto watch = OwnedCurvePathWatch::acquire(*owner, *array);
  auto item_watch = OwnedCurvePathWatch::acquire(*owner, IDP_property_array_get(array)[0]);
  IDP_ResizeIDPArray(array, 2);
  EXPECT_TRUE(watch->is_valid());
  IDP_ResizeIDPArray(array, 3);
  EXPECT_FALSE(watch->is_valid());
  EXPECT_FALSE(item_watch->is_valid());
  watch = OwnedCurvePathWatch::acquire(*owner, *array);
  auto replacement = idprop::create_group("");
  IDP_SetIndexArray(array, 0, replacement.get());
  MEM_delete(replacement.release());
  EXPECT_FALSE(watch->is_valid());
  watch = OwnedCurvePathWatch::acquire(*owner, *array);
  /* The RNA move route calls this before moving identical inline items. */
  owned_curve_structure_changed(array);
  EXPECT_FALSE(watch->is_valid());
  EXPECT_TRUE(record->is_attached());
  EXPECT_NE(record->snapshot(error), nullptr);
  watch = OwnedCurvePathWatch::acquire(*owner, *array);
  IDP_FreeFromGroup(owner->properties, array);
  EXPECT_FALSE(watch->is_valid());
}

TEST_F(OwnedCurveRuntimeTest, PathWatchContentReplacementAndUnrelatedTemporaryData)
{
  auto watch = OwnedCurvePathWatch::acquire(*owner, *definition);
  IDProperty *copy = IDP_CopyProperty(definition);
  IDP_FreeProperty(copy);
  EXPECT_TRUE(watch->is_valid());
  copy = IDP_CopyProperty(definition);
  IDP_CopyPropertyContent(definition, copy);
  IDP_FreeProperty(copy);
  EXPECT_FALSE(watch->is_valid());
  EXPECT_FALSE(record->is_attached());
  watch = OwnedCurvePathWatch::acquire(*owner, *definition);
  auto owner_watch = OwnedCurvePathWatch::acquire_owner(*owner);
  owned_curve_invalidate_all();
  EXPECT_FALSE(watch->is_valid());
  EXPECT_FALSE(owner_watch->is_valid());
}
