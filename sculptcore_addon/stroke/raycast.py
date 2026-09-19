# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""View-ray unprojection and casting against the engine tree/grid domain."""

from .. import engine, mapping
from ._util import _float3


def raycast(session, origin, direction):
    """Cast a ray (object space) against the engine tree; returns a
    (position, normal, face_index) tuple on hit, else None. Grids sessions
    with a live domain use the GridTree — its bounds refresh per dab
    engine-side, where the mesh tree's would be stale between grids dabs."""
    lib = engine.capi().lib
    if (session.multires_ptr
            # While the grids provider is displaying, the domain is the
            # authoritative surface (a mesh-path stroke flips the provider to
            # 'SLOT' first, and a level rebind re-registers at the new
            # level), and with the lazy slot there may be NO mesh tree yet.
            and session.draw_provider_kind == 'GRIDS'
            and lib.Multires_hasGridDomain(
                session.multires_ptr, session.multires_active_level)):
        import ctypes

        import numpy as np

        out = np.zeros(10, dtype=np.float32)
        nearest = ctypes.c_int(-1)
        hit = lib.GridTree_castRay(
            session.multires_ptr, session.multires_active_level,
            origin[0], origin[1], origin[2],
            direction[0], direction[1], direction[2],
            out, ctypes.byref(nearest))
        if not hit:
            return None
        # Level-mesh face id from the hit cell (buildLevelTopo's grid-major
        # cell order) so callers keep their face-index semantics.
        side = 1 << (session.multires_active_level - 1)
        face = int(out[7]) * side * side + int(out[9]) * side + int(out[8])
        return ((float(out[0]), float(out[1]), float(out[2])),
                (float(out[3]), float(out[4]), float(out[5])), face)

    mgr = engine.manager()
    tree = session.tree()
    orig_v = _float3(mgr, *origin)
    dir_v = _float3(mgr, *direction)
    hit = mgr.construct("sculptcore::spatial::CastRayIsect")
    try:
        if not tree.castRay(orig_v, dir_v, hit):
            return None
        p = tuple(hit.p.vec)
        n = tuple(hit.normal.vec)
        return (p, n, hit.faceIndex)
    finally:
        for obj in (orig_v, dir_v, hit):
            obj.dispose()


def _ray_origin_dir(context, coord):
    """Object-space ``(origin, direction)`` of the view ray through a 2D region
    coordinate (both 3-tuples). Split out so symmetry can reflect the ray and
    re-cast it."""
    from bpy_extras import view3d_utils

    region = context.region
    rv3d = context.region_data
    ob = context.active_object

    origin_world = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction_world = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    matrix_inv = ob.matrix_world.inverted()
    origin = matrix_inv @ origin_world
    direction = (matrix_inv.to_3x3() @ direction_world).normalized()
    return tuple(origin), tuple(direction)


def _ray_from_coord(context, coord, session):
    """Unproject a 2D region coordinate to an object-space ray and cast it
    against the engine tree."""
    origin, direction = _ray_origin_dir(context, coord)
    return raycast(session, origin, direction)


def _ray_from_event(context, event, session):
    """Unproject the mouse event to an object-space ray and cast it against
    the engine tree."""
    return _ray_from_coord(
        context, (event.mouse_region_x, event.mouse_region_y), session)


def _cursor_on_anchor_plane(context, event, anchor_obj):
    """Object-space point where the mouse ray meets the view-facing plane
    through the anchor — grab's drag target."""
    return _coord_on_plane(context, (event.mouse_region_x, event.mouse_region_y),
                           anchor_obj)


def _coord_on_plane(context, coord, anchor_obj):
    """Object-space point where the ray through a 2D region coordinate meets the
    view-facing plane through ``anchor_obj``. Measuring drag on a plane at a
    fixed depth (rather than against the surface) is what lets a stroke keep
    dragging after the geometry has moved out from under the cursor."""
    import mathutils
    from bpy_extras import view3d_utils

    region = context.region
    rv3d = context.region_data
    ob = context.active_object

    anchor_world = ob.matrix_world @ mathutils.Vector(anchor_obj)
    loc_world = view3d_utils.region_2d_to_location_3d(region, rv3d, coord, anchor_world)
    return tuple(ob.matrix_world.inverted() @ loc_world)


def _pixel_to_world_length(context, position, pixel_len):
    """Object-space length spanning ``pixel_len`` screen pixels at
    ``position``'s depth (vanilla paint_calc_object_space_radius semantics).
    Returns None when the point projects off-screen."""
    import mathutils
    from bpy_extras import view3d_utils

    region = context.region
    rv3d = context.region_data
    ob = context.active_object

    center_world = ob.matrix_world @ mathutils.Vector(position)
    offset_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, center_world)
    if offset_2d is None:
        return None
    offset_2d = offset_2d.copy()
    offset_2d.x += pixel_len
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, offset_2d)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, offset_2d)
    # Object-space distance from the point to the unprojected offset at its depth.
    edge_world = ray_origin + ray_dir * (center_world - ray_origin).length
    matrix_inv = ob.matrix_world.inverted()
    return (matrix_inv @ edge_world - matrix_inv @ center_world).length


def _world_radius(context, brush, position):
    """Object-space dab radius from the brush's pixel radius at the dab
    location."""
    sculpt = context.tool_settings.sculpt
    length = _pixel_to_world_length(context, position, mapping.pixel_radius(sculpt, brush))
    return length or (mapping.unprojected_radius(brush) or 1.0)
