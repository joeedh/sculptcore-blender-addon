# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Generated engine-only brush properties (brush-mapping M2).

At registration the per-kernel uniform manifest is walked (through a
throwaway engine mesh/tree/brush/executor) and engine-only float, integer and
boolean uniforms become typed properties on ``Brush.sculptcore`` — name, default
and range straight from the manifest. The group serializes with the Brush
datablock (asset-compatible). The mapper copies the active kernel's values
into native fields and typed slots at stroke setup. The N-panel draws them
in an "Engine" section (M3).

Uniforms the Blender mapping already drives (the common scalar props and the
per-type extras) are excluded. Typed extra slots and native fields retain their
storage types; supported dynamic values enter authored storage at stroke start.
"""

import bpy
import math

from . import engine, mapping

# Uniform names the Blender mapping already drives.
_MAPPED = {"strength", "radius", "spacing", "planeoff", "autosmooth", "pinch", "invert",
           # The plane brush's reaches ride Brush.plane_height / plane_depth
           # (per dab, with the inversion mode); the twist angle is stroke
           # state the operator writes per dab.
           "planeHeight", "planeDepth", "rotateAngle"}

_group_cls = None
# Engine kernel name -> tuple of generated prop names in its manifest.
_kernel_props = {}
# Prop name -> Brush.namedFloats slot for store-backed uniforms (extra-kernel
# uniforms with no Brush member; written via setNamedFloat, not setattr).
# Slots are per-build — always taken from the loaded DLL's manifest.
_store_slots = {}
_scalar_types = {}


def props_for_type(sculpt_brush_type):
    """Generated prop names for a Blender sculpt brush type (may be empty)."""
    entry = mapping.KERNEL_BY_TYPE.get(sculpt_brush_type)
    if entry is None:
        return ()
    return _kernel_props.get(entry, ())


def apply(bl_brush, sc_brush):
    """Copy the generated engine props into the engine brush fields for the
    brush's kernel. Called from mapping.apply_brush before writeProps."""
    names = props_for_type(bl_brush.sculpt_brush_type)
    if not names:
        return
    group = getattr(bl_brush, "sculptcore", None)
    if group is None:
        return
    for name in names:
        slot = _store_slots.get(name, -1)
        if slot >= 0:
            suffix = {0: "Float", 4: "Int", 10: "Bool"}[_scalar_types[name]]
            getattr(sc_brush, "setNamed" + suffix)(slot, getattr(group, name))
        else:
            setattr(sc_brush, name, getattr(group, name))


def sync_authored(session, executor, kernel):
    """Seed active dynamic uniforms from the authoritative values just mapped by the host."""
    from sculptcore.brush_properties import UniformProperties, FLOAT32, INT32, BOOL
    access = UniformProperties(engine.manager(), executor, int(kernel))
    for uniform in access.uniforms:
        if not uniform.dynamic or uniform.name in {"strength", "radius", "spacing", "planeoff", "autosmooth", "invert"}:
            continue
        if uniform.scalar_type not in {FLOAT32, INT32, BOOL}:
            continue
        slot = _store_slots.get(uniform.name, -1)
        if slot >= 0:
            suffix = {FLOAT32: "Float", INT32: "Int", BOOL: "Bool"}[uniform.scalar_type]
            value = getattr(session.brush_obj, "getNamed" + suffix)(slot)
        else:
            value = getattr(session.brush_obj, uniform.name)
        if access.read(uniform.index) != value:
            access.write(uniform.index, value)


def _walk_manifests():
    """Per-kernel engine-only float uniforms via a throwaway executor:
    {kernel_name: [(name, default, has_range, min, max, slot, scalar_type)]}."""
    import numpy as np

    lib = engine.capi().lib
    mgr = engine.manager()

    positions = np.array([0, 0, 0, 1, 0, 0, 0, 1, 0], dtype=np.float32)
    corner_verts = np.array([0, 1, 2], dtype=np.int32)
    face_offsets = np.array([0, 3], dtype=np.int32)
    mesh_ptr = lib.Mesh_fromArrays(positions, 3, corner_verts, 3, face_offsets, 1)
    tree_ptr = lib.Mesh_buildSpatialTree(mesh_ptr, 0, 0, 0)

    tree = mgr.get_bound_pointer(
        mgr.get("sculptcore::spatial::SpatialTree"), tree_ptr, deref=False)
    brush = mgr.construct("sculptcore::brush::Brush")
    ctor = mgr.get_struct("sculptcore::brush::CommandExecutor").find_constructor("main")
    executor = mgr.construct_with(ctor, tree, brush)

    # The reflected `name` member is a litestl string wrapper; read its
    # contents through the runtime's string reader.
    from sculptcore._descriptors import read_litestl_string
    from .brush_properties import authoring
    from .brush_properties.legacy import ASSOCIATIONS

    manifests = {}
    contracts = []
    try:
        items = mgr.get("sculptcore::brush::SculptBrushes").items
        # Every kernel a Blender type maps to, plus every kernel the frozen
        # legacy rows declare a contract for: a row outlives the mapping that
        # first exposed it (FILL's planeSide, once the PLANE type moved to the
        # plane kernel), and its readiness is still graded against the DLL.
        kernel_names = set(mapping.KERNEL_BY_TYPE.values())
        kernel_names.update(association[0] for association in ASSOCIATIONS.values())
        for kernel_name in sorted(kernel_names):
            enum_value = items.get(kernel_name)
            if enum_value is None:
                # A stale DLL without this kernel (e.g. an extra kernel not
                # compiled in) must not take down every generated prop.
                print("SculptCore: kernel {!r} missing from engine enum; "
                      "skipping its props".format(kernel_name))
                continue
            count = executor.queryUniformManifest(int(enum_value))
            if count < 0:
                raise RuntimeError("Uniform declaration registration failed for kernel {!r}".format(kernel_name))
            entries = []
            for i in range(count):
                entry = executor.queriedUniformEntry(i)
                if entry is None or int(entry.scalarType) not in {0, 4, 10}:
                    continue
                name = read_litestl_string(entry.name.ptr)
                for identifier, association in ASSOCIATIONS.items():
                    if association == (kernel_name, name):
                        contracts.append((identifier, {0: 'FLOAT32', 4: 'INT32', 10: 'BOOL'}[int(entry.scalarType)],
                                          bool(entry.dynamic)))
                # storeSlot >= 0: an extra-kernel uniform living in the
                # Brush.namedFloats store (no member). getattr(entry, ...)
                # tolerates a pre-wave-2 DLL without the field.
                slot = int(getattr(entry, "storeSlot", -1))
                if name in _MAPPED or (slot < 0 and not hasattr(brush, name)):
                    continue
                # Default from the live engine BRUSH, not the DSL `def`: the
                # plain dab path reads fields, and their authored defaults are
                # the current behavior (e.g. planeSide is +1 as a field but 0
                # in the DSL — a generated 0 would break the plane family).
                # Store slots were just default-seeded by the manifest query's
                # command creation, so the same read works for them.
                scalar_type = int(entry.scalarType)
                suffix = {0: "Float", 4: "Int", 10: "Bool"}[scalar_type]
                default = (getattr(brush, "getNamed" + suffix)(slot) if slot >= 0
                           else getattr(brush, name))
                entries.append((name, default,
                                bool(entry.hasRange),
                                float(entry.rangeMin), float(entry.rangeMax), slot, scalar_type))
            if entries:
                manifests[kernel_name] = entries
    finally:
        executor.dispose()
        brush.dispose()
        lib.SpatialTree_free(tree_ptr)
        lib.freeMesh(mesh_ptr)
    from .brush_properties.capabilities import ENGINE_EXPORTS
    required = ENGINE_EXPORTS
    authoring.refresh_manifest(contracts, execution_ready=all(hasattr(lib, name) for name in required))
    return manifests


def register():
    """Keep frozen aliases available without a DLL; execution fails explicitly."""
    global _group_cls, _kernel_props
    try:
        manifests = _walk_manifests()
    except Exception as ex:
        print("SculptCore: engine prop generation unavailable ({!r})".format(ex))
        manifests = {}

    annotations = {}
    # name -> True once a *ranged* declaration registered it: a shared name can
    # appear in several kernels' manifests (projection: bsmooth, nudge...), and
    # a rangeless first sighting must not lock out a later @range declaration.
    union = {}
    for kernel_name, entries in sorted(manifests.items()):
        names = []
        for name, default, has_range, range_min, range_max, store_slot, scalar_type in entries:
            names.append(name)
            if name in _scalar_types and _scalar_types[name] != scalar_type:
                raise RuntimeError("Conflicting scalar types for " + name)
            _scalar_types[name] = scalar_type
            if store_slot >= 0:
                _store_slots[name] = store_slot
            if name in union and (union[name] or not has_range):
                continue
            union[name] = has_range
            kwargs = {"name": name, "default": default}
            if scalar_type == 10:
                annotations[name] = bpy.props.BoolProperty(**kwargs)
            else:
                if has_range:
                    kwargs["min"] = math.ceil(range_min) if scalar_type == 4 else range_min
                    kwargs["max"] = math.floor(range_max) if scalar_type == 4 else range_max
                factory = bpy.props.IntProperty if scalar_type == 4 else bpy.props.FloatProperty
                annotations[name] = factory(**kwargs)
        _kernel_props[kernel_name] = tuple(names)

    # Public v0 paths remain available even without the engine. Their declaration
    # contract comes from the frozen inventory, never a replacement DLL default.
    from .brush_properties import migration, compatibility
    for name, definitions in migration.BY_NAME.items():
        definition = definitions[0]
        annotations[name] = bpy.props.FloatProperty(
            name=name, default=definition.default, min=definition.minimum, max=definition.maximum,
            soft_min=definition.soft_minimum, soft_max=definition.soft_maximum,
            **compatibility.callbacks(name))
    _group_cls = type("SculptCoreBrushSettings", (bpy.types.PropertyGroup,),
                      {"__annotations__": annotations})
    bpy.utils.register_class(_group_cls)
    bpy.types.Brush.sculptcore = bpy.props.PointerProperty(
        type=_group_cls, name="SculptCore",
        description="Engine-only brush settings (generated from the kernel manifests)")


def unregister():
    global _group_cls
    from .brush_properties import authoring
    authoring.refresh_manifest(())
    _kernel_props.clear()
    _store_slots.clear()
    _scalar_types.clear()
    if _group_cls is None:
        return
    if hasattr(bpy.types.Brush, "sculptcore"):
        del bpy.types.Brush.sculptcore
    bpy.utils.unregister_class(_group_cls)
    _group_cls = None
