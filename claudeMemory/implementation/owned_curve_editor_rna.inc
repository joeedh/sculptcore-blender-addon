/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

namespace rna {
class OwnedCurvePath {
 public:
  ID *owner = nullptr;
  unsigned int owner_session = 0;
  IDProperty *root = nullptr;
  std::string path;
  std::vector<std::shared_ptr<CurveDeclaration>> declarations;
  std::vector<std::shared_ptr<bke::OwnedCurvePathWatch>> watches;
  PointerRNA existing;
};
class OwnedCurveEdit {
 public:
  PointerRNA target;
  CurveMapping *working = nullptr;
  bool finished = false;
  ~OwnedCurveEdit()
  {
    if (working) {
      BKE_curvemapping_free(working);
    }
  }
};
}  // namespace rna

/** Find a current numeric path without obtaining or creating any pointer properties. */
static bool find_group_path(StructRNA *type,
                            IDProperty *group,
                            const PointerRNA &target,
                            std::string &path,
                            const int depth = 0)
{
  if (!group || group->type != IDP_GROUP || depth > 64) {
    return false;
  }
  if (group == target.data && type == target.type) {
    return true;
  }
  for (IDProperty &child : group->data.group) {
    PropertyRNA *prop = RNA_struct_type_find_property(type, child.name);
    if (!prop || !(prop->flag & PROP_IDPROPERTY)) {
      continue;
    }
    const std::string prefix = path + child.name;
    if (prop->type == PROP_POINTER && !RNA_property_is_owned_curve(prop)) {
      StructRNA *child_type = reinterpret_cast<PointerPropertyRNA *>(prop)->pointer_type;
      std::string candidate = prefix + ".";
      if (RNA_struct_is_a(child_type, RNA_PropertyGroup) &&
          find_group_path(child_type, &child, target, candidate, depth + 1))
      {
        path = std::move(candidate);
        return true;
      }
    }
    else if (prop->type == PROP_COLLECTION && child.type == IDP_IDPARRAY) {
      StructRNA *child_type = reinterpret_cast<CollectionPropertyRNA *>(prop)->item_type;
      if (!RNA_struct_is_a(child_type, RNA_PropertyGroup)) {
        continue;
      }
      for (int i = 0; i < child.len; i++) {
        std::string candidate = prefix + "[" + std::to_string(i) + "].";
        if (find_group_path(child_type,
                            IDP_property_array_get(&child) + i,
                            target,
                            candidate,
                            depth + 1))
        {
          path = std::move(candidate);
          return true;
        }
      }
    }
  }
  return false;
}

std::shared_ptr<rna::OwnedCurvePath> RNA_owned_curve_path_capture(PointerRNA &parent,
                                                                const char *path)
{
  if (!main_thread() || !parent.owner_id ||
      (parent.owner_id->tag & ID_TAG_COPIED_ON_EVAL))
  {
    fail("Owned curve editor requires an original ID");
    return nullptr;
  }
  auto result = std::make_shared<rna::OwnedCurvePath>();
  result->owner = parent.owner_id;
  result->owner_session = parent.owner_id->session_uid;
  result->root = parent.owner_id->system_properties;
  result->watches.push_back(bke::OwnedCurvePathWatch::acquire_owner(*result->owner));
  PointerRNA root = RNA_id_pointer_create(parent.owner_id);
  if (parent.data != parent.owner_id || !RNA_struct_is_ID(parent.type)) {
    if (!RNA_struct_is_a(parent.type, RNA_PropertyGroup) ||
        !find_group_path(root.type, result->root, parent, result->path))
    {
      fail("Owned curve editor requires a declared system property path");
      return nullptr;
    }
  }
  result->path += path;
  std::string remaining = result->path;
  StructRNA *type = root.type;
  IDProperty *group = result->root;
  for (int depth = 0; depth <= 64; depth++) {
    if (group) {
      if (group->type != IDP_GROUP) {
        fail("Malformed owned curve path group");
        return nullptr;
      }
      result->watches.push_back(bke::OwnedCurvePathWatch::acquire(*result->owner, *group));
    }
    const size_t end = remaining.find_first_of(".[");
    const std::string name = remaining.substr(0, end);
    PropertyRNA *prop = RNA_struct_type_find_property(type, name.c_str());
    if (!prop || !(prop->flag & PROP_IDPROPERTY)) {
      fail("Owned curve editor path must use declared system properties");
      return nullptr;
    }
    result->declarations.push_back(declaration(prop));
    IDProperty *child = group ? IDP_GetPropertyFromGroup(group, name) : nullptr;
    if (end == std::string::npos) {
      if (!RNA_property_is_owned_curve(prop)) {
        fail("Expected a CurveMappingProperty");
        return nullptr;
      }
      if (child) {
        PointerRNA declaring = depth == 0 ? root : PointerRNA{root.owner_id, type, group};
        result->existing = RNA_owned_curve_get(declaring, *prop);
        if (!result->existing.owned_curve) {
          return nullptr;
        }
      }
      return result;
    }
    if (remaining[end] == '.' && prop->type == PROP_POINTER && !RNA_property_is_owned_curve(prop)) {
      type = reinterpret_cast<PointerPropertyRNA *>(prop)->pointer_type;
      if (!RNA_struct_is_a(type, RNA_PropertyGroup) || (child && child->type != IDP_GROUP)) {
        fail("Owned curve editor path requires PropertyGroup ancestors");
        return nullptr;
      }
      remaining.erase(0, end + 1);
      group = child;
    }
    else if (remaining[end] == '[' && prop->type == PROP_COLLECTION) {
      type = reinterpret_cast<CollectionPropertyRNA *>(prop)->item_type;
      if (!RNA_struct_is_a(type, RNA_PropertyGroup) || !child || child->type != IDP_IDPARRAY) {
        fail("Owned curve editor requires an existing collection item");
        return nullptr;
      }
      result->watches.push_back(bke::OwnedCurvePathWatch::acquire(*result->owner, *child));
      size_t cursor = end + 1;
      const size_t first = cursor;
      int64_t index = 0;
      while (cursor < remaining.size() && remaining[cursor] >= '0' && remaining[cursor] <= '9') {
        if (index > child->len) {
          fail("Owned curve editor collection index out of range");
          return nullptr;
        }
        index = index * 10 + (remaining[cursor++] - '0');
      }
      if (cursor == first || cursor + 2 >= remaining.size() || remaining[cursor] != ']' ||
          remaining[cursor + 1] != '.' || index >= child->len)
      {
        fail("Owned curve editor requires an existing numeric collection index");
        return nullptr;
      }
      group = IDP_property_array_get(child) + index;
      remaining.erase(0, cursor + 2);
    }
    else {
      fail("Unsupported owned curve editor path");
      return nullptr;
    }
  }
  fail("Owned curve editor path exceeds the supported depth");
  return nullptr;
}

bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path)
{
  return bool(path.existing.owned_curve);
}

bool RNA_owned_curve_path_initialize(rna::OwnedCurvePath &path, Main &bmain, bContext *C)
{
  if (!main_thread() || path.existing.owned_curve) {
    return fail("Owned curve initialization requires an unset captured path");
  }
  ID *owner = nullptr;
  ID *id;
  FOREACH_MAIN_ID_BEGIN (&bmain, id) {
    if (id == path.owner && id->session_uid == path.owner_session) {
      owner = id;
    }
  }
  FOREACH_MAIN_ID_END;
  if (!owner || owner->system_properties != path.root ||
      std::any_of(path.declarations.begin(), path.declarations.end(),
                  [](const auto &token) { return !token->valid; }) ||
      std::any_of(path.watches.begin(), path.watches.end(),
                  [](const auto &watch) { return !watch->is_valid(); }))
  {
    return fail("Owned curve path changed after drawing; redraw before initializing",
                OwnedCurveRNAError::Stale);
  }
  PointerRNA root = RNA_id_pointer_create(owner);
  /* No owner, property or path-tree access after the user callback. */
  return bool(RNA_owned_curve_initialize(root, path.path.c_str(), "LINEAR", C).owned_curve);
}

std::shared_ptr<rna::OwnedCurveEdit> RNA_owned_curve_edit_begin(rna::OwnedCurvePath &path)
{
  if (!path.existing.owned_curve || !RNA_owned_curve_validate(path.existing) ||
      !editable(path.existing.owner_id))
  {
    return nullptr;
  }
  auto result = std::make_shared<rna::OwnedCurveEdit>();
  result->target = path.existing;
  RNA_owned_curve_pin(result->target);
  result->working = path.existing.owned_curve->view->snapshot->copy_mapping();
  result->working->cur = 0;
  BKE_curvemapping_reset_view(result->working);
  return result;
}

CurveMapping &RNA_owned_curve_edit_mapping(rna::OwnedCurveEdit &edit)
{
  return *edit.working;
}

bool RNA_owned_curve_edit_commit(rna::OwnedCurveEdit &edit, bContext *C, bool &changed)
{
  changed = false;
  if (edit.finished) {
    return fail("Owned curve edit transaction has already finished");
  }
  edit.finished = true;
  if (!RNA_owned_curve_validate(edit.target)) {
    return false;
  }
  auto binding = edit.target.owned_curve->binding;
  std::string error;
  const auto result = binding->record->commit(
      edit.target.owned_curve->view->revision, *edit.working, error);
  if (result == bke::OwnedCurveResult::Unchanged) {
    return true;
  }
  if (result != bke::OwnedCurveResult::Changed) {
    return fail(error, result == bke::OwnedCurveResult::ReadOnly ? OwnedCurveRNAError::ReadOnly :
                       result == bke::OwnedCurveResult::Stale ? OwnedCurveRNAError::Stale :
                                                              OwnedCurveRNAError::Invalid);
  }
  changed = true;
  notify_owner(binding->owner);
  binding->pending_callback = true;
  RNA_owned_curve_update(C, edit.target);
  return true;
}
