# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual Scene/collection deep-copy and library override policy checks."""
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1] / "tests/owned-curve-copy-policy"
ROOT.mkdir(exist_ok=True)


class OwnedCopyItem(bpy.types.PropertyGroup):
    curve: bpy.props.CurveMappingProperty()


bpy.utils.register_class(OwnedCopyItem)
for cls in (bpy.types.Scene, bpy.types.Brush, bpy.types.Object):
    cls.owned_copy = bpy.props.CollectionProperty(type=OwnedCopyItem)
scene = bpy.context.scene
scene.owned_copy.add()
scene.owned_copy.add()
scene.curve_mapping_initialize("owned_copy[0].curve").curves[0].points[-1].location.y = 0.375
scene.curve_mapping_initialize("owned_copy[1].curve").curves[0].points[-1].location.y = 0.75
source_keys = [item.curve.curve_mapping_cache_key() for item in scene.owned_copy]
copy = scene.copy()
assert all(item.curve.curve_mapping_cache_key()[0] != source_keys[i][0] for i, item in enumerate(copy.owned_copy))
copy.owned_copy.move(0, 1)
copy.owned_copy[1].curve.curves[0].points[-1].location.y = 0.25
assert scene.owned_copy[0].curve.curves[0].points[-1].location.y == 0.375
assert scene.owned_copy[1].curve.curves[0].points[-1].location.y == 0.75
assert [item.curve.curve_mapping_cache_key() for item in scene.owned_copy] == source_keys
print("OWNED_COPY_CHECK Scene.copy nested collection independent", flush=True)

brush = bpy.data.brushes.new("OwnedCopyBrush", mode='SCULPT')
brush.owned_copy.add()
brush.curve_mapping_initialize("owned_copy[0].curve").curves[0].points[-1].location.y = 0.375
copy_brush = brush.copy()
copy_brush.owned_copy[0].curve.curves[0].points[-1].location.y = 0.75
assert brush.owned_copy[0].curve.curves[0].points[-1].location.y == 0.375
print("OWNED_COPY_CHECK Brush.copy nested collection independent", flush=True)

object = bpy.context.object
object.owned_copy.add()
object.curve_mapping_initialize("owned_copy[0].curve").curves[0].points[-1].location.y = 0.375
bpy.data.libraries.write(str(ROOT / "linked.blend"), {object}, fake_user=True)
with bpy.data.libraries.load(str(ROOT / "linked.blend"), link=True) as (_, target):
    target.objects = [object.name]
linked = target.objects[0]
del target, _
scene.collection.objects.link(linked)
print("OVERRIDE_FIXTURE", linked.library.filepath, linked.is_library_indirect, flush=True)
override = linked.override_create(remap_local_usages=False)
assert override.override_library is not None
curve = override.owned_copy[0].curve
before = curve.curve_mapping_cache_key()
for action in (
        lambda: setattr(curve.curves[0].points[-1].location, "y", 0.875),
        lambda: override.curve_mapping_initialize("owned_copy[0].curve"),
        lambda: override.owned_copy[0].property_unset("curve")):
    try:
        action()
    except (PermissionError, AttributeError):
        pass
    else:
        raise AssertionError("Unsupported library override edit succeeded")
assert curve.curves[0].points[-1].location.y == 0.375
assert curve.curve_mapping_cache_key() == before
print("OWNED_COPY_CHECK library override reads and rejected writes preserve definition", flush=True)
print("OWNED_CURVE_COPY_POLICY_PASS 3", flush=True)
