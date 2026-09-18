TEST_F(OwnedCurveRuntimeTest, ArraySlotReplacementPreservesUntouchedWatches)
{
  IDProperty *array = IDP_NewIDPArray("slot_test");
  IDP_AddToGroup(owner->properties, array);
  IDP_ResizeIDPArray(array, 2);
  for (int i = 0; i < 2; i++) {
    auto item = idprop::create_group("");
    IDP_AddToGroup(item.get(), idprop::create_group("nested").release());
    IDP_SetIndexArray(array, i, item.get());
    MEM_delete(item.release());
  }
  auto *items = IDP_property_array_get(array);
  auto container = OwnedCurvePathWatch::acquire(*owner, *array);
  auto target = OwnedCurvePathWatch::acquire(*owner, items[0]);
  auto nested = OwnedCurvePathWatch::acquire(*owner, *IDP_GetPropertyFromGroup(&items[0], "nested"));
  auto sibling = OwnedCurvePathWatch::acquire(*owner, items[1]);
  auto sibling_nested = OwnedCurvePathWatch::acquire(*owner, *IDP_GetPropertyFromGroup(&items[1], "nested"));
  IDProperty *identical = IDP_CopyProperty(&items[0]);
  IDP_SetIndexArray(array, 0, identical);
  MEM_delete(identical);
  EXPECT_FALSE(container->is_valid());
  EXPECT_FALSE(target->is_valid());
  EXPECT_FALSE(nested->is_valid());
  EXPECT_TRUE(sibling->is_valid());
  EXPECT_TRUE(sibling_nested->is_valid());
  EXPECT_TRUE(record->is_attached());
}

TEST_F(OwnedCurveRuntimeTest, ArrayResizeInvalidatesOnlyMovedOrRemovedItems)
{
  IDProperty *array = IDP_NewIDPArray("resize_test");
  IDP_AddToGroup(owner->properties, array);
  IDP_ResizeIDPArray(array, 300);
  for (int i = 0; i < array->len; i++) {
    auto item = idprop::create_group("");
    IDP_AddToGroup(item.get(), idprop::create_group("nested").release());
    IDP_SetIndexArray(array, i, item.get());
    MEM_delete(item.release());
  }
  auto *items = IDP_property_array_get(array);
  auto container = OwnedCurvePathWatch::acquire(*owner, *array);
  auto retained = OwnedCurvePathWatch::acquire(*owner, items[0]);
  auto retained_nested = OwnedCurvePathWatch::acquire(*owner, *IDP_GetPropertyFromGroup(&items[0], "nested"));
  auto removed = OwnedCurvePathWatch::acquire(*owner, items[299]);
  auto removed_nested = OwnedCurvePathWatch::acquire(*owner, *IDP_GetPropertyFromGroup(&items[299], "nested"));
  IDP_ResizeIDPArray(array, 299);
  EXPECT_EQ(items, IDP_property_array_get(array));
  EXPECT_FALSE(container->is_valid());
  EXPECT_TRUE(retained->is_valid());
  EXPECT_TRUE(retained_nested->is_valid());
  EXPECT_FALSE(removed->is_valid());
  EXPECT_FALSE(removed_nested->is_valid());
  const int smaller = array->totallen - 200;
  ASSERT_GT(smaller, 0);
  ASSERT_LT(smaller, array->len);
  IDP_ResizeIDPArray(array, smaller);
  EXPECT_FALSE(retained->is_valid());
  EXPECT_FALSE(retained_nested->is_valid());
  items = IDP_property_array_get(array);
  retained = OwnedCurvePathWatch::acquire(*owner, items[0]);
  retained_nested = OwnedCurvePathWatch::acquire(*owner, *IDP_GetPropertyFromGroup(&items[0], "nested"));
  IDP_ResizeIDPArray(array, array->totallen + 1);
  EXPECT_FALSE(retained->is_valid());
  EXPECT_FALSE(retained_nested->is_valid());
  EXPECT_TRUE(record->is_attached());
}

TEST_F(OwnedCurveRuntimeTest, LargeEncodingWithUnrelatedLivePathWatch)
{
  auto watch = OwnedCurvePathWatch::acquire(*owner, *definition);
  for (const int count : {2048, 8192, 32767}) {
    auto &curve = candidate->cm[0];
    MEM_delete(curve.curve);
    curve.curve = MEM_new_array<CurveMapPoint>(count, "large scalar curve");
    curve.totpoint = count;
    for (int i = 0; i < count; i++) {
      curve.curve[i].x = curve.curve[i].y = float(i) / float(count - 1);
      curve.curve[i].flag = CUMA_HANDLE_VECTOR;
    }
    const auto start = std::chrono::steady_clock::now();
    IDProperty *encoded = BKE_curvemapping_to_idprop(*candidate, "large", nullptr, error);
    ASSERT_NE(encoded, nullptr) << error;
    const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start);
    printf("OWNED_CURVE_ENCODE_TIMING %d %.6f seconds\n", count, elapsed.count());
    EXPECT_EQ(IDP_GetPropertyFromGroup(encoded, "points")->len, count);
    EXPECT_TRUE(watch->is_valid());
    IDP_FreeProperty(encoded);
  }
}
