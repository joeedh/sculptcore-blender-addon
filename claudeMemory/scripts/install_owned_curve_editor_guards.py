# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Install the reviewed editor path guards into the companion fork."""

from pathlib import Path

ROOT = Path("C:/dev/blender/main")


def edit(path, before, after):
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if after in source:
        return
    if source.count(before) != 1:
        raise RuntimeError("Expected one patch anchor in {}".format(path))
    target.write_text(source.replace(before, after), encoding="utf-8", newline="\n")


header = "source/blender/blenkernel/BKE_curvemapping_owned.hh"
core = "source/blender/blenkernel/intern/curvemapping_owned.cc"
idprop = "source/blender/blenkernel/intern/idprop.cc"
access = "source/blender/makesrna/intern/rna_access.cc"

edit(header, "/** Lifecycle hooks.", """/** A conservative guard for a UI path before its curve definition exists.
 * Independent from definition records: collection movement expires path guards,
 * but does not detach curves already stored in that collection. Main-thread only. */
class OwnedCurvePathWatch {
 private:
  const ID *owner_;
  bool valid_ = true;
  explicit OwnedCurvePathWatch(const ID &owner) : owner_(&owner) {}
  friend struct OwnedCurveRegistry;

 public:
  static std::shared_ptr<OwnedCurvePathWatch> acquire(const ID &owner,
                                                     const IDProperty &property);
  static std::shared_ptr<OwnedCurvePathWatch> acquire_owner(const ID &owner);
  bool is_valid() const;
};

/** Invalidate only path guards before changing a group's membership or array order. */
void owned_curve_structure_changed(const IDProperty *property);

/** Lifecycle hooks.""")
edit(core,
     "  std::unordered_map<const IDProperty *, std::shared_ptr<OwnedCurveRecord>> records;",
     """  std::unordered_map<const IDProperty *, std::shared_ptr<OwnedCurveRecord>> records;
  std::unordered_map<const IDProperty *, std::weak_ptr<OwnedCurvePathWatch>> watches;
  std::unordered_map<const ID *, std::weak_ptr<OwnedCurvePathWatch>> owner_watches;

  void invalidate_watch_locked(const IDProperty *property)
  {
    auto it = watches.find(property);
    if (it != watches.end()) {
      if (auto watch = it->second.lock()) {
        BLI_assert(BLI_thread_is_main());
        watch->valid_ = false;
      }
      watches.erase(it);
    }
  }

  void invalidate_path_tree_locked(const IDProperty *property)
  {
    if (!property || watches.empty()) {
      return;
    }
    invalidate_watch_locked(property);
    if (property->type == IDP_GROUP) {
      for (const IDProperty &child : property->data.group) {
        invalidate_path_tree_locked(&child);
      }
    }
    else if (property->type == IDP_IDPARRAY) {
      for (int i = 0; i < property->len; i++) {
        invalidate_path_tree_locked(IDP_property_array_get(property) + i);
      }
    }
  }""")
edit(core, "    records.clear();\n  }", """    records.clear();
    for (auto &item : watches) {
      if (auto watch = item.second.lock()) {
        watch->valid_ = false;
      }
    }
    for (auto &item : owner_watches) {
      if (auto watch = item.second.lock()) {
        watch->valid_ = false;
      }
    }
  }""")
edit(core, "    auto it = records.find(property);", """    invalidate_watch_locked(property);
    auto it = records.find(property);""")
edit(core, "      if (records.empty()) {", "      if (records.empty() && watches.empty()) {")
edit(core, "        if (!subtree || records.empty()) {",
     "        if (!subtree || (records.empty() && watches.empty())) {")
edit(core, "      for (auto it = records.begin(); it != records.end();) {", """      for (auto it = owner_watches.begin(); it != owner_watches.end();) {
        auto watch = it->second.lock();
        if (!watch || match(it->first)) {
          if (watch) {
            BLI_assert(BLI_thread_is_main());
            watch->valid_ = false;
          }
          it = owner_watches.erase(it);
        }
        else {
          ++it;
        }
      }
      for (auto it = watches.begin(); it != watches.end();) {
        auto watch = it->second.lock();
        if (!watch || match(watch->owner_)) {
          if (watch) {
            BLI_assert(BLI_thread_is_main());
            watch->valid_ = false;
          }
          it = watches.erase(it);
        }
        else {
          ++it;
        }
      }
      for (auto it = records.begin(); it != records.end();) {""")
edit(core, "        if (match(*it->second->state_)) {",
     "        if (match(it->second->state_->owner)) {")
edit(core, "    value->invalidate([&](const auto &state) { return state.owner == owner; });",
     "    value->invalidate([&](const ID *candidate) { return candidate == owner; });")
edit(core, "void owned_curve_invalidate_property(const IDProperty *property)", """std::shared_ptr<OwnedCurvePathWatch> OwnedCurvePathWatch::acquire(const ID &owner,
                                                               const IDProperty &property)
{
  BLI_assert(BLI_thread_is_main());
  OwnedCurveRegistry &value = registry();
  std::lock_guard lock(value.mutex);
  if (value.watches.size() >= 256) {
    std::erase_if(value.watches, [](const auto &entry) { return entry.second.expired(); });
  }
  auto &weak = value.watches[&property];
  auto watch = weak.lock();
  if (watch && watch->owner_ != &owner) {
    watch->valid_ = false;
    watch.reset();
  }
  if (!watch) {
    watch = std::shared_ptr<OwnedCurvePathWatch>(new OwnedCurvePathWatch(owner));
    weak = watch;
  }
  return watch;
}

std::shared_ptr<OwnedCurvePathWatch> OwnedCurvePathWatch::acquire_owner(const ID &owner)
{
  BLI_assert(BLI_thread_is_main());
  OwnedCurveRegistry &value = registry();
  std::lock_guard lock(value.mutex);
  if (value.owner_watches.size() >= 256) {
    std::erase_if(value.owner_watches, [](const auto &entry) { return entry.second.expired(); });
  }
  auto &weak = value.owner_watches[&owner];
  auto watch = weak.lock();
  if (!watch) {
    watch = std::shared_ptr<OwnedCurvePathWatch>(new OwnedCurvePathWatch(owner));
    weak = watch;
  }
  return watch;
}

bool OwnedCurvePathWatch::is_valid() const
{
  BLI_assert(BLI_thread_is_main());
  return valid_;
}

void owned_curve_structure_changed(const IDProperty *property)
{
  if (OwnedCurveRegistry *value = live_registry.load()) {
    std::lock_guard lock(value->mutex);
    if (property && property->type == IDP_IDPARRAY) {
      /* Inline descendants can move even when their contents remain identical. */
      value->invalidate_path_tree_locked(property);
    }
    else {
      value->invalidate_watch_locked(property);
    }
  }
}

void owned_curve_invalidate_property(const IDProperty *property)""")
edit(idprop, "  if (item != old) {\n    idp_free_property_content_recurse", """  if (item != old) {
    bke::owned_curve_structure_changed(prop);
    idp_free_property_content_recurse""")
edit(idprop, "void IDP_ResizeIDPArray(IDProperty *prop, int newlen)\n{\n  BLI_assert(prop->type == IDP_IDPARRAY);",
     """void IDP_ResizeIDPArray(IDProperty *prop, int newlen)
{
  BLI_assert(prop->type == IDP_IDPARRAY);
  if (newlen != prop->len) {
    bke::owned_curve_structure_changed(prop);
  }""")
edit(idprop, "  if (group->data.children_map->children.add(prop)) {\n    group->len++;", """  if (group->data.children_map->children.add(prop)) {
    bke::owned_curve_structure_changed(group);
    group->len++;""")
edit(idprop, "  if (prop_exist != nullptr) {\n    /* Insert the new property", """  if (prop_exist != nullptr) {
    bke::owned_curve_structure_changed(group);
    /* Insert the new property""")
edit(idprop, "void IDP_RemoveFromGroup(IDProperty *group, IDProperty *prop)\n{", """void IDP_RemoveFromGroup(IDProperty *group, IDProperty *prop)
{
  bke::owned_curve_structure_changed(group);""")
edit(access, '#include "RNA_owned_curve.hh"',
     '#include "BKE_curvemapping_owned.hh"\n#include "RNA_owned_curve.hh"')
edit(access, "    if (src_index != dst_index) {\n      IDProperty tmp;", """    if (src_index != dst_index) {
      bke::owned_curve_structure_changed(idprop);
      IDProperty tmp;""")

rna_header = "source/blender/makesrna/RNA_owned_curve.hh"
rna_source = "source/blender/makesrna/intern/rna_owned_curve.cc"
edit(rna_header, "}  // namespace blender", """namespace rna {
class OwnedCurvePath;
class OwnedCurveEdit;
}  // namespace rna

/** Capture an editor target without allocating saved properties, even for missing ancestors. */
std::shared_ptr<rna::OwnedCurvePath> RNA_owned_curve_path_capture(PointerRNA &parent,
                                                                const char *path);
bool RNA_owned_curve_path_is_set(const rna::OwnedCurvePath &path);
/** Reject stale first-initialization targets. Existing definitions use edit transactions instead. */
bool RNA_owned_curve_path_initialize(rna::OwnedCurvePath &path, Main &bmain, bContext *C);
std::shared_ptr<rna::OwnedCurveEdit> RNA_owned_curve_edit_begin(rna::OwnedCurvePath &path);
/** Temporary edit storage; never points into saved owner data. */
CurveMapping &RNA_owned_curve_edit_mapping(rna::OwnedCurveEdit &edit);
/** One-shot commit with the begin-time revision; callbacks may delete owner/declarations. */
bool RNA_owned_curve_edit_commit(rna::OwnedCurveEdit &edit, bContext *C, bool &changed);

}  // namespace blender""")
edit(rna_header, "namespace blender {", "namespace blender {\n\nstruct CurveMapping;\nstruct Main;")
edit(rna_source, '#include "BKE_library.hh"', '#include "BKE_library.hh"\n#include "BKE_main.hh"')
addition = (Path(__file__).parent.parent / "implementation/owned_curve_editor_rna.inc").read_text(encoding="utf-8")
edit(rna_source, "}  // namespace blender", addition + "\n}  // namespace blender")
tests = (Path(__file__).parent.parent / "implementation/owned_curve_path_tests.inc").read_text(encoding="utf-8")
edit("source/blender/blenkernel/intern/curvemapping_owned_test.cc",
     "}  // namespace blender::bke::tests", tests + "\n}  // namespace blender::bke::tests")
