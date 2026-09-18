# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Blender regression checks for the owner-aware CurveMapping RNA layer."""
import json
import math
from pathlib import Path
import sys
import threading

import bpy

ROOT = Path(__file__).resolve().parents[1] / "tests" / "owned-curve-rna"
ROOT.mkdir(parents=True, exist_ok=True)
CHECKS = []
CALLS = []
ACTION = None


def update(self, context):
    CALLS.append((self.id_data.name, self.name))
    if ACTION:
        ACTION(self)


class OwnedCurveRNAItem(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty(update=update)
    other: bpy.props.CurveMappingProperty(update=update)


class OwnedCurveRNARoot(bpy.types.PropertyGroup):
    nested: bpy.props.PointerProperty(type=OwnedCurveRNAItem)
    items: bpy.props.CollectionProperty(type=OwnedCurveRNAItem)


def register():
    bpy.utils.register_class(OwnedCurveRNAItem)
    bpy.utils.register_class(OwnedCurveRNARoot)
    for cls in (bpy.types.Brush, bpy.types.Scene):
        cls.owned_test = bpy.props.PointerProperty(type=OwnedCurveRNARoot)
        cls.owned_direct = bpy.props.CurveMappingProperty()


def done(name):
    CHECKS.append(name)
    print("OWNED_RNA_CHECK " + name, flush=True)


def raises(types, fn):
    try:
        fn()
    except types:
        return
    raise AssertionError("Expected {} from {}".format(types, fn))


def near(a, b):
    assert math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6), (a, b)


def new_brush(name):
    brush = bpy.data.brushes.new(name, mode='SCULPT')
    brush.use_fake_user = True
    return brush


register()
phase = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "test"
if phase == "read":
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "saved.blend"))
    brush = bpy.data.brushes["OwnedCurveRNA"]
    near(brush.owned_test.nested.curve.curves[0].points[-1].location.y, 0.375)
    near(brush.owned_direct.curves[0].points[-1].location.y, 0.75)
    done("fresh_process_readback")
else:
    brush = new_brush("OwnedCurveRNA")
    scene = bpy.context.scene
    assert brush.owned_direct is None
    assert not brush.is_property_set("owned_direct")
    assert not brush.is_property_set("owned_test")
    raises(ValueError, lambda: brush.curve_mapping_initialize("owned_test.nested.curve", preset="NO"))
    assert not brush.is_property_set("owned_test")
    raises(ValueError, lambda: brush.curve_mapping_initialize("owned_test.items[0].curve"))
    assert not brush.is_property_set("owned_test")
    done("unset_and_atomic_failed_initialization")

    curve = brush.curve_mapping_initialize("owned_test.nested.curve")
    item = brush.owned_test.nested
    assert isinstance(curve, bpy.types.CurveMapping)
    assert item.is_property_set("curve") and len(curve.curves) == 1
    channel = curve.curves[0]
    assert len(channel.points) == 2
    near(curve.evaluate(channel, 0.375), 0.375)
    assert len(CALLS) == 1 and CALLS[-1][0] == brush.name
    assert item.curve_mapping_initialize("curve") == curve
    assert len(CALLS) == 1
    done("root_path_initialization_native_types_and_callback")

    hashes = (hash(curve), hash(channel))
    lookup = {curve: "mapping", channel: "channel"}
    point = channel.points[-1]
    vector = point.location
    iterator = iter(channel.points)
    next(iterator)
    point.location = (1.0, 0.375)
    assert len(CALLS) == 2
    near(channel.points[-1].location.y, 0.375)
    assert (hash(curve), hash(channel)) == hashes
    assert lookup[item.curve] == "mapping" and lookup[curve.curves[0]] == "channel"
    raises(ReferenceError, lambda: point.location)
    raises(ReferenceError, lambda: vector.y)
    raises(ReferenceError, lambda: next(iterator))
    repr(point)
    str(point)
    done("retained_mapping_channel_point_vector_iterator")

    curve.use_clip = False
    curve.extend = 'HORIZONTAL'
    curve.clip_max_x = 2.0
    near(curve.clip_max_x, 2.0)
    assert not curve.use_clip and curve.extend == 'HORIZONTAL'
    point = channel.points[-1]
    point.handle_type = 'VECTOR'
    assert channel.points[-1].handle_type == 'VECTOR'
    point = channel.points[-1]
    point.location.y = 0.5
    near(channel.points[-1].location.y, 0.5)
    point = channel.points[-1]
    point.location[:] = (1.0, 0.375)
    near(channel.points[-1].location.y, 0.375)
    done("field_array_and_mathutils_transactions")

    calls = len(CALLS)
    for number in (float('nan'), float('inf'), -float('inf'), 1e100):
        raises((ValueError, OverflowError), lambda: setattr(curve, "clip_max_x", number))
        raises((ValueError, OverflowError), lambda: setattr(channel.points[-1], "location", (1, number)))
        raises((ValueError, OverflowError), lambda: channel.points.new(number, 0.5))
        raises((ValueError, OverflowError), lambda: curve.evaluate(channel, number))
    raises(ValueError, lambda: setattr(curve, "clip_max_x", curve.clip_min_x))
    raises(ValueError, lambda: setattr(curve, "tone", 'FILMLIKE'))
    raises(ValueError, lambda: setattr(curve, "black_level", (0.1, 0, 0)))
    assert len(CALLS) == calls
    near(channel.points[-1].location.y, 0.375)
    done("invalid_numbers_and_transactions_preserve_value")

    retained_new = channel.points.new
    inserted = retained_new(0.5, 0.25)
    assert isinstance(inserted, bpy.types.CurveMapPoint)
    near(inserted.location.x, 0.5)
    channel.points.remove(inserted)
    raises(ReferenceError, lambda: inserted.location)
    raises(ValueError, lambda: channel.points.remove(channel.points[0]))
    raises(TypeError, lambda: channel.points.foreach_get("location", [0.0] * 4))
    other = item.curve_mapping_initialize("other")
    other.curves[0].points.new(0.3, 0.6)
    raises(ValueError, lambda: channel.points.remove(other.curves[0].points[1]))
    raises(ValueError, lambda: curve.evaluate(other.curves[0], 0.5))
    done("point_functions_and_membership")

    raw = item["curve"]
    raw["future_extension"] = {"message": "keep"}
    raises(ReferenceError, lambda: curve.curves)
    item.curve_mapping_sync("curve")
    assert item["curve"]["future_extension"]["message"] == "keep"
    raw["points"][-1]["y"] = 0.75
    raises(ReferenceError, lambda: curve.curves)
    item.curve_mapping_sync("curve")
    near(curve.curves[0].points[-1].location.y, 0.75)
    raw["_version"] = 999
    raises((ValueError, ReferenceError), lambda: item.curve)
    assert raw["_version"] == 999
    raises((ValueError, ReferenceError), lambda: item.curve_mapping_initialize("curve"))
    assert raw["_version"] == 999
    raw["_version"] = 1
    item.curve_mapping_sync("curve")
    curve.curves[0].points[-1].location = (1, 0.375)
    assert item["curve"]["future_extension"]["message"] == "keep"
    done("raw_sync_unknown_version_and_extension_preservation")

    del item["other"]
    item["other"] = 7
    curve.clip_max_x = 3
    assert item["other"] == 7
    item.property_unset("other")
    assert item.other is None
    done("malformed_sibling_preserved_and_explicit_unset")

    entries = brush.owned_test.items
    for i in range(30):
        entry = entries.add()
        entry.name = "entry_{}".format(i)
    child_curve = entries[0].curve_mapping_initialize("curve")
    entries.move(0, 29)
    child_curve.clip_max_x = 2
    assert CALLS[-1] == (brush.name, "entry_0")
    entries.remove(29)
    raises(ReferenceError, lambda: child_curve.curves)
    done("collection_growth_move_delete_and_current_callback_parent")

    copy = brush.copy()
    copy.owned_test.nested.curve.curves[0].points[-1].location = (1, 0.875)
    near(curve.curves[0].points[-1].location.y, 0.375)
    old = copy.owned_test.nested.curve
    bpy.data.brushes.remove(copy)
    raises(ReferenceError, lambda: old.curves)
    done("independent_owner_copy_and_deleted_owner")

    thread_results = []
    def background():
        try:
            curve.curves
        except (ValueError, ReferenceError) as error:
            thread_results.append(type(error).__name__)
    thread = threading.Thread(target=background)
    thread.start()
    thread.join()
    assert thread_results
    done("off_main_thread_rejected")

    stale = item.curve
    stale_new = stale.curves[0].points.new
    bpy.props.RemoveProperty(OwnedCurveRNAItem, attr="curve")
    raises(ReferenceError, lambda: stale.curves)
    raises(ReferenceError, lambda: stale_new(0.25, 0.25))
    OwnedCurveRNAItem.curve = bpy.props.CurveMappingProperty(update=update)
    curve = item.curve
    near(curve.curves[0].points[-1].location.y, 0.375)
    raises(ReferenceError, lambda: stale.curves)
    done("declaration_replacement_invalidates_old_wrappers")

    direct = brush.curve_mapping_initialize("owned_direct")
    direct.curves[0].points[-1].location = (1, 0.75)
    scene_curve = scene.curve_mapping_initialize("owned_direct")
    scene_curve.curves[0].points[-1].location = (1, 0.25)
    near(direct.curves[0].points[-1].location.y, 0.75)
    scene.property_unset("owned_direct")
    assert scene.owned_direct is None
    raises(ReferenceError, lambda: scene_curve.curves)
    done("direct_id_storage_and_unset")

    ACTION = lambda owner: setattr(owner.curve, "clip_max_x", 5)
    calls = len(CALLS)
    curve.clip_max_x = 4
    assert len(CALLS) == calls + 1
    near(curve.clip_max_x, 5)
    ACTION = None
    done("same_curve_callback_recursion_guard")

    dying = new_brush("OwnedCurveCallbackDeletion")
    dying_curve = dying.curve_mapping_initialize("owned_test.nested.curve")
    ACTION = lambda owner: bpy.data.brushes.remove(owner.id_data)
    raises(ReferenceError, lambda: dying_curve.curves[0].points.new(0.4, 0.4))
    ACTION = None
    done("point_return_after_callback_owner_deletion")

    ACTION = lambda owner: del_curve_declaration()
    def del_curve_declaration():
        bpy.props.RemoveProperty(OwnedCurveRNAItem, attr="curve")
    curve.clip_max_x = 6
    ACTION = None
    raises(ReferenceError, lambda: curve.curves)
    OwnedCurveRNAItem.curve = bpy.props.CurveMappingProperty(update=update)
    curve = item.curve
    done("callback_unregisters_its_own_declaration")

    for operation in ("scalar", "array", "index", "slice", "function"):
        dying = new_brush("OwnedCurveConversion_" + operation)
        target = dying.curve_mapping_initialize("owned_direct")
        target_point = target.curves[0].points[-1]
        class DeleteOnFloat:
            def __float__(self):
                bpy.data.brushes.remove(dying)
                return 0.5
        value = DeleteOnFloat()
        operations = {
            "scalar": lambda: setattr(target, "clip_max_x", value),
            "array": lambda: setattr(target_point, "location", (1, value)),
            "index": lambda: target_point.location.__setitem__(1, value),
            "slice": lambda: target_point.location.__setitem__(slice(None), (1, value)),
            "function": lambda: target.curves[0].points.new(value, 0.5),
        }
        raises(ReferenceError, operations[operation])
    done("numeric_conversion_owner_deletion")

    dying = new_brush("OwnedCurveBooleanConversion")
    target = dying.curve_mapping_initialize("owned_direct")
    class DeleteOnIndex:
        def __index__(self):
            bpy.data.brushes.remove(dying)
            return 1
    raises(ReferenceError, lambda: setattr(target, "use_clip", DeleteOnIndex()))
    done("boolean_conversion_owner_deletion")

    dying = new_brush("OwnedCurveUnsetCallback")
    dying_item = dying.owned_test.nested
    ACTION = lambda owner: owner.property_unset("curve")
    calls = len(CALLS)
    raises(ReferenceError, lambda: dying_item.curve_mapping_initialize("curve"))
    ACTION = None
    assert len(CALLS) == calls + 1 and dying_item.curve is None
    done("callback_unset_suppresses_same_curve_recursion")

    for removal in ("curve", "item", "ancestor"):
        changing = new_brush("OwnedCurveCallbackRemoval_" + removal)
        entries = changing.owned_test.items
        entries.add().name = "target"
        held = entries[0].curve_mapping_initialize("curve")
        caught = []
        def remove_during_callback(owner):
            # Never reuse the callback's movable item pointer after collection growth.
            for _ in range(20):
                changing.owned_test.items.add()
            if removal == "curve":
                changing.owned_test.items[0].property_unset("curve")
            elif removal == "item":
                changing.owned_test.items.remove(0)
            else:
                changing.property_unset("owned_test")
            try:
                changing.curve_mapping_initialize("owned_test.nested.curve")
            except ValueError:
                caught.append(True)
        ACTION = remove_during_callback
        calls = len(CALLS)
        held.clip_max_x = 2
        ACTION = None
        assert caught and len(CALLS) == calls + 1
        if removal == "ancestor":
            assert not changing.is_property_set("owned_test")
        done("callback_{}_removal_rejects_reinitialization".format(removal))

    raises(ValueError, lambda: setattr(bpy.types.Bone, "owned_bad", bpy.props.CurveMappingProperty()))
    done("unsupported_declaration_rejected")

    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "saved.blend"))
    bpy.data.libraries.write(str(ROOT / "linked.blend"), {brush}, fake_user=True)
    with bpy.data.libraries.load(str(ROOT / "linked.blend"), link=True) as (_, target):
        target.brushes = [brush.name]
    linked = target.brushes[0]
    # Release library context dictionaries before shutdown; they can retain the
    # dynamically registered RNA classes and this harness's wrapper namespace.
    del target, _
    linked_curve = linked.owned_test.nested.curve
    raises((PermissionError, AttributeError), lambda: setattr(linked_curve, "clip_max_x", 7))
    raises((PermissionError, AttributeError), lambda: linked.curve_mapping_initialize("owned_direct"))
    near(linked_curve.clip_max_x, 6)
    raises((PermissionError, AttributeError), lambda: linked_curve.curves[0].points[-1].location.normalize())
    done("read_only_linked_owner")

    retained = brush.owned_direct
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / "saved.blend"))
    raises(ReferenceError, lambda: retained.curves)
    near(bpy.data.brushes["OwnedCurveRNA"].owned_direct.curves[0].points[-1].location.y, 0.75)
    done("save_reload_invalidates_retained_handles")

(ROOT / (phase + ".json")).write_text(json.dumps({
    "checks": CHECKS, "binary": bpy.app.binary_path, "version": bpy.app.version_string,
}, indent=2) + "\n")
print("OWNED_CURVE_RNA_PASS " + phase, flush=True)
