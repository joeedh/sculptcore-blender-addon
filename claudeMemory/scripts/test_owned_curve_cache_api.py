# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender checks for exact, validated owned-curve cache identities."""
import gc
import json
from pathlib import Path
import threading

import bpy

ROOT = Path(__file__).resolve().parents[1] / "tests" / "owned-curve-cache"
ROOT.mkdir(parents=True, exist_ok=True)
CHECKS = []
CALLS = []


def update(self, context):
    CALLS.append(self.name)


def done(name):
    CHECKS.append(name)
    print("OWNED_CACHE_CHECK " + name, flush=True)


def raises(types, action):
    try:
        action()
    except types:
        return
    raise AssertionError("Expected {}".format(types))


def key(curve):
    result = curve.curve_mapping_cache_key()
    assert type(result) is tuple and len(result) == 2
    assert all(type(value) is int and value > 0 for value in result)
    return result


def current():
    return bpy.data.brushes["CacheAPI"].owned_cache.curve


class OwnedCacheSettings(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty(update=update)


assert bpy.props.owned_curve_mapping_api_version == 1
assert ".. function:: CurveMappingProperty" in bpy.props.CurveMappingProperty.__doc__
bpy.utils.register_class(OwnedCacheSettings)
bpy.types.Brush.owned_cache = bpy.props.PointerProperty(type=OwnedCacheSettings)
brush = bpy.data.brushes.new("CacheAPI", mode='SCULPT')
brush.use_fake_user = True
curve = brush.curve_mapping_initialize("owned_cache.curve")
first = key(curve)
assert len(CALLS) == 1
assert ".. method:: curve_mapping_cache_key" in curve.curve_mapping_cache_key.__doc__
done("capability_docstrings_exact_integer_tuple")

curve.curves[0].points[-1].location = (1, 0.375)
second = key(curve)
assert second[0] == first[0] and second[1] > first[1]
assert key(current()) == second
done("retained_mapping_refreshes_committed_revision")

calls = len(CALLS)
curve.curves[0].points[-1].select = True
curve.curves[0].points[-1].location = (1, 0.375)
curve.update()
brush.curve_mapping_sync("owned_cache.curve")
assert key(curve) == second and len(CALLS) == calls
raises(ValueError, lambda: setattr(curve, "clip_max_x", float('nan')))
assert key(curve) == second and len(CALLS) == calls
done("presentation_noops_sync_and_rejected_writes_preserve_key_and_callbacks")

captured = curve.curve_mapping_cache_key
raw = brush.owned_cache["curve"]
raw["points"][-1]["y"] = 0.75
raises(ReferenceError, lambda: curve.curve_mapping_cache_key())
raises(ReferenceError, captured)
brush.curve_mapping_sync("owned_cache.curve")
third = key(curve)
assert third[0] == first[0] and third[1] > second[1]
assert len(CALLS) == calls + 1
raw["extension"] = "opaque"
brush.curve_mapping_sync("owned_cache.curve")
fourth = key(curve)
assert fourth[0] == first[0] and fourth[1] > third[1]
done("unsynchronized_raw_data_rejects_normal_and_captured_calls_then_sync_advances")

raw["_version"] = 999
raises(ReferenceError, captured)
raises(ValueError, lambda: brush.curve_mapping_sync("owned_cache.curve"))
assert raw["_version"] == 999
raw["_version"] = 1
brush.curve_mapping_sync("owned_cache.curve")
assert key(curve) == fourth
done("unknown_schema_preserved_and_rejected_without_revision_change")

errors = []


def worker():
    for action in (captured, lambda: curve.curve_mapping_cache_key()):
        try:
            action()
        except ReferenceError:
            errors.append(True)


thread = threading.Thread(target=worker)
thread.start()
thread.join()
assert errors == [True, True]
assert key(curve) == fourth
done("normal_and_captured_worker_calls_reject")

raises(ValueError, lambda: brush.curve_mapping_cache_key())
raises(ValueError, lambda: curve.curves[0].curve_mapping_cache_key())
raises(ValueError, lambda: curve.curves[0].points[0].curve_mapping_cache_key())
raises(ValueError, lambda: brush.curve_strength.curve_mapping_cache_key())
done("nonmapping_and_authoritative_native_mapping_rejected")

del captured, curve, raw
gc.collect()
assert key(current()) == fourth
done("wrapper_gc_does_not_replace_record")

curve = current()
captured = curve.curve_mapping_cache_key
bpy.props.RemoveProperty(OwnedCacheSettings, attr="curve")
raises(ReferenceError, captured)
raises(ReferenceError, lambda: curve.curve_mapping_cache_key())
OwnedCacheSettings.curve = bpy.props.CurveMappingProperty(update=update)
assert key(current()) == fourth
raises(ReferenceError, captured)
done("reregistration_reuses_record_but_rejects_old_binding")

copy = brush.copy()
copy_key = key(copy.owned_cache.curve)
assert copy_key[0] != fourth[0]
copy.owned_cache.curve.curves[0].points[-1].location.y = 0.25
assert key(current()) == fourth
assert current().curves[0].points[-1].location.y == 0.75
done("copy_has_independent_identity_and_definition")

curve = copy.owned_cache.curve
captured = curve.curve_mapping_cache_key
cached_key = key(curve)
cache = {cached_key: "immutable samples"}
bpy.data.brushes.remove(copy)
raises(ReferenceError, captured)
raises(ReferenceError, lambda: curve.curve_mapping_cache_key())
assert cache.pop(cached_key) == "immutable samples"
done("deleted_owner_rejects_handles_but_integer_key_remains_usable_for_eviction")

curve = current()
captured = curve.curve_mapping_cache_key
brush.owned_cache.property_unset("curve")
raises(ReferenceError, captured)
replacement = brush.curve_mapping_initialize("owned_cache.curve")
replacement_key = key(replacement)
assert replacement_key[0] not in (first[0], copy_key[0])
replacement.curves[0].points[-1].location.y = 0.625
before_load = key(replacement)
captured = replacement.curve_mapping_cache_key
done("unset_and_reinitialize_never_reuse_record_identity")

bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "cache.blend"))
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "cache.blend"))
raises(ReferenceError, captured)
raises(ReferenceError, lambda: replacement.curve_mapping_cache_key())
after_load = key(current())
assert after_load[0] != before_load[0]
assert current().curves[0].points[-1].location.y == 0.625
done("reload_preserves_definition_and_replaces_runtime_identity")

(ROOT / "test.json").write_text(json.dumps({"checks": CHECKS, "count": len(CHECKS)}, indent=2) + "\n")
print("OWNED_CACHE_PASS {}".format(len(CHECKS)), flush=True)
