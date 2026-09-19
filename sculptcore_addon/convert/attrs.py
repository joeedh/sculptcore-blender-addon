# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender <-> engine attribute bridging: face sets, vertex color, edge
flags, UV, and the generic bridged-attribute (arbitrary custom attribute)
machinery."""

from .. import engine
from .constants import _ATTR_TYPE_MAP, _AT_FLOAT2, _BL_CUSTOM_NORMAL, _BL_FACE_SET, _DEFAULT_COLOR_NAME, _DOMAIN_TO_ENGINE, _DOT_ATTR_EXCEPTIONS, _DOT_ATTR_PREFIXES, _EDGE_FLAG_MAP, _SC_COLOR, _SC_GROUP, _SKIP_ATTR_NAMES, _USE_COLOR, _USE_NONE, _USE_UV



def _default_face_set(mesh):
    """Blender's invisible/default face-set id (Mesh.face_sets_color_default,
    fork RNA; usually 1) — the engine must leave that group untinted in its
    fset overlay stream, where its own "no group" is 0."""
    return int(getattr(mesh, "face_sets_color_default", 1))



def _load_face_sets(mesh, mesh_ptr):
    """Seed the engine `group` face attr from the Blender `.sculpt_face_set`
    attribute (int, face). No-op when the mesh carries no face sets."""
    import numpy as np

    attr = mesh.attributes.get(_BL_FACE_SET)
    if attr is None or attr.domain != 'FACE' or attr.data_type != 'INT':
        return
    values = np.empty(len(mesh.polygons), dtype=np.int32)
    attr.data.foreach_get("value", values)
    engine.capi().lib.Mesh_writeFaceIntAttr(mesh_ptr, _SC_GROUP, values)



def _flush_face_sets(mesh, mesh_ptr):
    """Write the engine `group` face attr back into `.sculpt_face_set`,
    creating it on first use. No-op when the engine has no face groups."""
    import numpy as np

    values = np.empty(len(mesh.polygons), dtype=np.int32)
    if not engine.capi().lib.Mesh_readFaceIntAttr(mesh_ptr, _SC_GROUP, values):
        return
    attr = mesh.attributes.get(_BL_FACE_SET)
    if attr is None:
        attr = mesh.attributes.new(_BL_FACE_SET, 'INT', 'FACE')
    attr.data.foreach_set("value", values)



def _point_float_color(mesh):
    """The active color attribute if it is the POINT/FLOAT_COLOR match the
    engine's `color` float4 vertex attr expects, else None."""
    attr = mesh.color_attributes.active_color
    if attr is not None and attr.domain == 'POINT' and attr.data_type == 'FLOAT_COLOR':
        return attr
    return None



def _load_color(mesh, mesh_ptr, verts_num):
    """Seed the engine `color` attr from the active POINT/FLOAT_COLOR color
    attribute. No-op when there is none of that kind."""
    import numpy as np

    attr = _point_float_color(mesh)
    if attr is None:
        return
    values = np.empty(verts_num * 4, dtype=np.float32)
    attr.data.foreach_get("color", values)
    engine.capi().lib.Mesh_writeVertFloat4Attr(mesh_ptr, _SC_COLOR, values)



def _flush_color(mesh, mesh_ptr, verts_num, color_name=None):
    """Write the engine `color` attr back into the POINT/FLOAT_COLOR color
    attribute it mirrors: the layer recorded at enter (`color_name`), created
    when missing — a rebuild recreating layers may have auto-assigned the
    active designation to an unrelated color layer, so the name wins over the
    active designation. Leaves corner/byte color attributes untouched (logs a
    warning)."""
    import numpy as np

    values = np.empty(verts_num * 4, dtype=np.float32)
    if not engine.capi().lib.Mesh_readVertFloat4Attr(mesh_ptr, _SC_COLOR, values):
        return
    attr = None
    if color_name:
        cand = mesh.color_attributes.get(color_name)
        if cand is None:
            # The rebuild dropped it (or the user deleted it); recreate under
            # its own name. Falling back to the *active* layer here would
            # clobber whichever unrelated color layer attributes.new
            # auto-assigned during the rebuild.
            attr = mesh.color_attributes.new(color_name, 'FLOAT_COLOR', 'POINT')
            if mesh.color_attributes.active_color is None:
                mesh.color_attributes.active_color = attr
        elif cand.domain == 'POINT' and cand.data_type == 'FLOAT_COLOR':
            attr = cand
        else:
            print("SculptCore: color attribute {!r} is no longer "
                  "POINT/FLOAT_COLOR; painted colors not written back".format(color_name))
            return
    if attr is None:
        attr = _point_float_color(mesh)
    if attr is None:
        if mesh.color_attributes.active_color is not None:
            print("SculptCore: active color attribute is not POINT/FLOAT_COLOR; "
                  "painted colors not written back")
            return
        attr = mesh.color_attributes.new(_DEFAULT_COLOR_NAME, 'FLOAT_COLOR', 'POINT')
        mesh.color_attributes.active_color = attr
    attr.data.foreach_set("color", values)



def _load_edge_flags(mesh, mesh_ptr, recompute=False):
    """Seed the engine boundary edge flags (seam/sharp) from the Blender edge
    bool attributes. Engine vertex indices equal Blender indices at enter
    (Mesh_fromArrays creates verts in order), so edges are keyed by their
    vertex pair. Recomputes the boundary classification when anything was
    seeded — or when the caller passes ``recompute`` (UVs were seeded, which
    marks the whole mesh boundary-dirty) — so BSMOOTH/dyntopo see the seam/
    sharp features *and* the derived UV-chart boundaries from the first
    stroke."""
    import numpy as np

    lib = engine.capi().lib
    edges_num = len(mesh.edges)
    if not edges_num:
        return
    edge_verts = None
    seeded = recompute
    for bl_name, sc_name in _EDGE_FLAG_MAP:
        attr = mesh.attributes.get(bl_name)
        if attr is None or attr.domain != 'EDGE' or attr.data_type != 'BOOLEAN':
            continue
        values = np.empty(edges_num, dtype=np.uint8)
        attr.data.foreach_get("value", values.view(np.bool_))
        if not values.any():
            continue
        if edge_verts is None:
            edge_verts = np.empty(edges_num * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", edge_verts)
        lib.Mesh_writeEdgeFlagsByVerts(mesh_ptr, sc_name, edge_verts, values, edges_num)
        seeded = True
    if seeded:
        lib.Mesh_recomputeBoundary(mesh_ptr)



def _pair_keys(pairs):
    """Sorted vertex pairs packed into int64 keys (order-independent)."""
    import numpy as np

    lo = np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    hi = np.maximum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    return (lo << 32) | hi



def _match_pairs(dst_pairs, src_pairs):
    """For each dst vertex pair, the index of the matching src pair (-1 when
    unmatched). Both arrays are (n, 2); matching is endpoint-order-agnostic."""
    import numpy as np

    if not len(src_pairs) or not len(dst_pairs):
        return np.full(len(dst_pairs), -1, dtype=np.int64)
    src_keys = _pair_keys(src_pairs)
    order = np.argsort(src_keys)
    sorted_keys = src_keys[order]
    dst_keys = _pair_keys(dst_pairs)
    idx = np.searchsorted(sorted_keys, dst_keys)
    idx[idx >= len(sorted_keys)] = len(sorted_keys) - 1
    return np.where(sorted_keys[idx] == dst_keys, order[idx], -1)



def _engine_edge_pairs(mesh_ptr):
    """Every live engine edge's vertex pair, live-iteration order — the order
    the EDGE-domain attribute c-api reads and writes."""
    import numpy as np

    lib = engine.capi().lib
    count = lib.Mesh_edgeCount(mesh_ptr)
    pairs = np.empty(max(count, 1) * 2, dtype=np.int32)
    lib.Mesh_edgeVertsOut(mesh_ptr, pairs)
    return pairs[:count * 2].reshape(-1, 2)



def _flush_edge_flags(session, mesh, vert_map):
    """Recreate the Blender seam/sharp edge attributes from the engine
    boundary flags after a topology rebuild (`calc_edges=True` regenerated the
    edges with all flags dropped). `vert_map` maps engine vertex index ->
    rebuilt Blender index (Mesh_toArrays). Engine edges are matched to Blender
    edges by sorted vertex pair; flags whose edge no longer exists are
    silently dropped (dyntopo may have collapsed it)."""
    import numpy as np

    lib = engine.capi().lib
    edges_num = len(mesh.edges)
    engine_edges = lib.Mesh_edgeCount(session.mesh_ptr)
    if not edges_num or not engine_edges:
        return

    bl_order = bl_keys = None
    buf = np.empty(engine_edges * 2, dtype=np.int32)
    for bl_name, sc_name in _EDGE_FLAG_MAP:
        count = lib.Mesh_readEdgeFlags(session.mesh_ptr, sc_name, buf, engine_edges)
        if count <= 0:
            continue
        if bl_keys is None:
            bl_edge_verts = np.empty(edges_num * 2, dtype=np.int32)
            mesh.edges.foreach_get("vertices", bl_edge_verts)
            keys = _pair_keys(bl_edge_verts.reshape(-1, 2))
            bl_order = np.argsort(keys)
            bl_keys = keys[bl_order]
        pairs = vert_map[buf[:count * 2].reshape(-1, 2)]
        keys = _pair_keys(pairs[np.all(pairs >= 0, axis=1)])
        idx = np.searchsorted(bl_keys, keys)
        idx[idx >= edges_num] = edges_num - 1
        matched = bl_order[idx[bl_keys[idx] == keys]]
        if not len(matched):
            continue
        values = np.zeros(edges_num, dtype=np.bool_)
        values[matched] = True
        attr = mesh.attributes.get(bl_name)
        if attr is None:
            attr = mesh.attributes.new(bl_name, 'BOOLEAN', 'EDGE')
        attr.data.foreach_set("value", values)



def _load_uv(mesh, mesh_ptr):
    """Seed the engine `uv` corner attribute from the active UV map (per-loop
    float2, loop order = the engine's corner order). Returns True when UVs
    were seeded (the engine marks the mesh boundary-dirty so the derived
    UV-chart edge flags can be recomputed). No-op with no UV map."""
    import numpy as np

    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return False
    values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    # A UV map is a CORNER-domain FLOAT2 attribute; reading it through the
    # attribute API is a contiguous memcpy, ~300x faster than the per-element
    # `uv_layers.active.data.uv` accessor (~870 ms -> ~3 ms at 4M corners).
    uv_attr = mesh.attributes.get(uv_layer.name)
    if uv_attr is not None and uv_attr.domain == 'CORNER' and uv_attr.data_type == 'FLOAT2':
        uv_attr.data.foreach_get("vector", values)
    else:
        uv_layer.data.foreach_get("uv", values)
    engine.capi().lib.Mesh_writeCornerFloat2Attr(mesh_ptr, b"uv", values)
    return True



def _flush_uv(mesh, mesh_ptr):
    """Write the engine `uv` corner attr back into the active UV map, creating
    one when the mesh has none. Only called when the engine UVs diverged from
    the Mesh (session.uv_dirty — the UV-project operator / UV reprojection);
    regular strokes never touch UVs, so the default flush skips this."""
    import ctypes

    import numpy as np

    values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    # Engine domain CORNER (4) / AttrType FLOAT2 (2); see _DOMAIN_TO_ENGINE.
    if not engine.capi().lib.Mesh_readAttr(mesh_ptr, 4, b"uv", 2,
                                           values.ctypes.data_as(ctypes.c_void_p)):
        return
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        if uv_layer is None:
            return
    uv_attr = mesh.attributes.get(uv_layer.name)
    if uv_attr is not None and uv_attr.domain == 'CORNER' and uv_attr.data_type == 'FLOAT2':
        uv_attr.data.foreach_set("vector", values)
    else:
        uv_layer.data.foreach_set("uv", values)


# Generic user-attribute bridge
#
# User attribute layers (extra UV maps, color layers, custom vertex/face
# attributes, material indices, ...) are seeded into the engine on enter, so
# dyntopo interpolates them onto new geometry and the meshlog reverts them on
# undo. The topology-rebuild path drops all Blender customdata (clear_geometry),
# so these layers are recreated from the engine afterwards. Positions, topology
# builtins, and the dedicated brush-target layers (mask/face-set/active color)
# have their own paths and are skipped here.



def _attr_is_bridgeable_name(name):
    """False for names the bridge never touches: "position" and dot-prefixed
    internal layers, minus the explicit work-state exceptions."""
    if name in _SKIP_ATTR_NAMES:
        return False
    if not name.startswith("."):
        return True
    return name in _DOT_ATTR_EXCEPTIONS or name.startswith(_DOT_ATTR_PREFIXES)



def _bridge_use(mesh, name, data_type, domain, engine_type):
    """The engine AttrUse tag for a bridged layer, so a re-imported UV map or
    color layer keeps its semantic type. Only a layer `uv_layers` actually
    lists is a UV map — an arbitrary corner float2 (a flow field, a packed
    pair) must not inherit UV semantics (wedge blending, seam handling)."""
    if data_type in {'FLOAT_COLOR', 'BYTE_COLOR'}:
        return _USE_COLOR
    if (engine_type == _AT_FLOAT2 and domain == 'CORNER'
            and mesh.uv_layers.get(name) is not None):
        return _USE_UV
    return _USE_NONE



def _bridge_descriptor(mesh, attr):
    """The bridge descriptor for a Blender attribute layer, or None (logged)
    when its domain or type has no engine mapping. Name-based skips are the
    caller's business (they differ between enter and reconcile)."""
    engine_domain = _DOMAIN_TO_ENGINE.get(attr.domain)
    mapping = _ATTR_TYPE_MAP.get(attr.data_type)
    if engine_domain is None or mapping is None:
        print("SculptCore: attribute {!r} ({:s}/{:s}) is unsupported and "
              "will be dropped on topology change".format(
                  attr.name, attr.domain, attr.data_type))
        return None
    engine_type, ncomp, dtype, prop = mapping
    return {
        "name": attr.name,
        "name_bytes": attr.name.encode("utf-8"),
        "bl_domain": attr.domain,
        "bl_type": attr.data_type,
        "engine_domain": engine_domain,
        "engine_type": engine_type,
        "ncomp": ncomp,
        "dtype": dtype,
        "prop": prop,
        "use": _bridge_use(mesh, attr.name, attr.data_type, attr.domain, engine_type),
    }



def _write_bridged_attr(mesh_ptr, desc, values):
    """Write a bridged layer's values (live-iteration order) into the engine
    under its descriptor's name/type/use."""
    import ctypes

    engine.capi().lib.Mesh_writeAttr(
        mesh_ptr, desc["engine_domain"], desc["name_bytes"], desc["engine_type"],
        desc["use"], values.ctypes.data_as(ctypes.c_void_p))



def _edge_flag_names():
    return {bl_name for bl_name, _ in _EDGE_FLAG_MAP}



def _load_bridged_attrs(mesh, mesh_ptr, session):
    """Seed every user attribute layer into the engine and record a descriptor
    so :func:`_flush_bridged_attrs` can recreate it after a topology rebuild.
    Skips positions/topology builtins, the dedicated mask/face-set/color and
    seam/sharp layers, and unsupported Blender types (logged). EDGE-domain
    values are reordered into engine edge order by endpoint matching (engine
    vertex indices equal Blender's at enter); the engine's edges are derived
    from faces, so a value on a loose Blender edge has no engine edge to land
    on and rides the loose-edge snapshot instead (topology only — see
    _read_loose_edges)."""
    import numpy as np

    color = _point_float_color(mesh)
    if color is not None:
        session.color_attr_name = color.name
    edge_flags = _edge_flag_names()

    session.bridged_attrs = []
    engine_pairs = None
    for attr in mesh.attributes:
        if not _attr_is_bridgeable_name(attr.name):
            continue
        if color is not None and attr.name == color.name:
            continue
        if attr.name in edge_flags:
            continue
        if attr.name == _BL_CUSTOM_NORMAL and attr.data_type == 'INT16_2D':
            continue  # the encoded form has its own decode/re-encode path
        desc = _bridge_descriptor(mesh, attr)
        if desc is None:
            continue
        values = np.empty(len(attr.data) * desc["ncomp"], dtype=desc["dtype"])
        attr.data.foreach_get(desc["prop"], values)
        if desc["bl_domain"] == 'EDGE':
            if engine_pairs is None:
                engine_pairs = _engine_edge_pairs(mesh_ptr)
                bl_pairs = np.empty(len(mesh.edges) * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", bl_pairs)
                match = _match_pairs(engine_pairs, bl_pairs.reshape(-1, 2))
            ncomp = desc["ncomp"]
            engine_values = np.zeros(len(engine_pairs) * ncomp, dtype=desc["dtype"])
            hit = match >= 0
            engine_values.reshape(-1, ncomp)[hit] = \
                values.reshape(-1, ncomp)[match[hit]]
            values = engine_values
        _write_bridged_attr(mesh_ptr, desc, values)
        session.bridged_attrs.append(desc)



def _vert_carry_maps(session, vert_map):
    """(new_bl, old_bl, carry): for every live engine vertex, its rebuilt
    Blender index, its Blender index at the last sync (-1 when it did not
    exist then), and the mask of vertices present on both sides. The carry is
    how host-only per-vertex state crosses a rebuild. An engine index reused
    after a kill can pair a dead vertex's value with an unrelated new one —
    accepted, it is bounded to the brush region."""
    import numpy as np

    prev = session.vert_map_prev
    live_e = np.nonzero(vert_map >= 0)[0]
    new_bl = vert_map[live_e]
    old_bl = np.full(len(live_e), -1, dtype=np.int64)
    if prev is not None:
        in_prev = live_e < len(prev)
        old_bl[in_prev] = prev[live_e[in_prev]]
    return new_bl, old_bl, old_bl >= 0



def _reconcile_bridged_attrs(session, mesh, vert_map, counts):
    """Re-read the Mesh's attribute list immediately before it is destroyed.

    ``session.bridged_attrs`` was built at enter and there is no other read
    point in the session (``refresh`` is disabled for custom-undo modes and
    ``resync_if_diverged`` only compares vertex counts), so without this a
    layer created mid-session is silently dropped by the rebuild and a layer
    deleted mid-session is resurrected from its stale engine copy.

    A deleted layer's descriptor is dropped (its engine column stays, unread).
    A new supported layer is seeded into the engine: POINT-domain values are
    carried over for vertices that survived the topology change, via the
    engine-index maps (``session.vert_map_prev`` pairs engine indices with the
    Blender indices of the last sync, ``vert_map`` with the rebuilt ones); new
    vertices get the type default. An engine index reused after a kill can pair
    a dead vertex's value with an unrelated new one — accepted, it is bounded
    to the brush region. CORNER/FACE domains have no index map across the
    boundary, so their new layers keep their existence but start from defaults
    (logged)."""
    import numpy as np

    live = {}
    edge_flags = _edge_flag_names()
    for attr in mesh.attributes:
        if not _attr_is_bridgeable_name(attr.name) or attr.name in edge_flags:
            continue
        if attr.name == _BL_CUSTOM_NORMAL and attr.data_type == 'INT16_2D':
            continue  # dedicated decode/re-encode path
        # The layer the dedicated engine `color` column mirrors is the one
        # recorded at enter — a mid-session active-color change does not move
        # that column, so any *other* color layer stays generically bridged.
        if session.color_attr_name and attr.name == session.color_attr_name:
            continue
        live[attr.name] = (attr.domain, attr.data_type)

    kept = []
    known = set()
    for desc in session.bridged_attrs:
        state = live.get(desc["name"])
        if state == (desc["bl_domain"], desc["bl_type"]):
            kept.append(desc)
            known.add(desc["name"])
        # else: deleted (or deleted-and-recreated with a new shape, which the
        # created branch below re-seeds under its new descriptor).
    session.bridged_attrs = kept

    created = [name for name, state in live.items() if name not in known]
    if not created:
        return

    new_bl, old_bl, carry = _vert_carry_maps(session, vert_map)

    for name in created:
        attr = mesh.attributes.get(name)
        desc = _bridge_descriptor(mesh, attr)
        if desc is None:
            continue
        count = len(attr.data)
        ncomp = desc["ncomp"]
        if desc["bl_domain"] == 'POINT':
            old_values = np.empty(count * ncomp, dtype=desc["dtype"])
            attr.data.foreach_get(desc["prop"], old_values)
            new_count = counts[0]
            values = np.zeros(new_count * ncomp, dtype=desc["dtype"])
            values.reshape(new_count, ncomp)[new_bl[carry]] = \
                old_values.reshape(count, ncomp)[old_bl[carry]]
        else:
            if desc["bl_domain"] == 'EDGE':
                domain_count = engine.capi().lib.Mesh_edgeCount(session.mesh_ptr)
            else:
                domain_count = counts[{'CORNER': 1, 'FACE': 2}[desc["bl_domain"]]]
            values = np.zeros(domain_count * ncomp, dtype=desc["dtype"])
            print("SculptCore: attribute {!r} was created mid-session on the "
                  "{:s} domain; the layer survives the topology change but "
                  "its values reset (no index map across the rebuild)".format(
                      name, desc["bl_domain"]))
        _write_bridged_attr(session.mesh_ptr, desc, values)
        session.bridged_attrs.append(desc)



def _read_layer_designations(mesh):
    """Snapshot the active/default layer designations that
    ``clear_geometry()`` frees along with the layers (``clear_attribute_names``
    drops all six): the two color names plus the four UV-map designations.
    Read immediately before the rebuild — an enter-time snapshot would revert
    any designation the user changed mid-session. Without the restore, a
    single-UV textured mesh renders untextured after one dyntopo pass (no
    active UV designation means the draw cache skips UV extraction)."""
    uvs = mesh.uv_layers
    active = uvs.active
    clone = mesh.uv_layer_clone
    stencil = mesh.uv_layer_stencil
    return {
        "active_color": mesh.attributes.active_color_name or None,
        "default_color": mesh.attributes.default_color_name or None,
        "uv_active": active.name if active is not None else None,
        "uv_render": next((layer.name for layer in uvs if layer.active_render), None),
        "uv_clone": clone.name if clone is not None else None,
        "uv_stencil": stencil.name if stencil is not None else None,
    }



def _restore_layer_designations(mesh, snap):
    """Write the snapshotted designations back, after every layer exists again
    (``attributes.new`` auto-assigns the active color designation, so restoring
    must come after all layer recreation). The color setters accept dangling
    names without validation, so only names whose layer was actually recreated
    are written."""
    if snap["active_color"] and mesh.attributes.get(snap["active_color"]):
        mesh.attributes.active_color_name = snap["active_color"]
    if snap["default_color"] and mesh.attributes.get(snap["default_color"]):
        mesh.attributes.default_color_name = snap["default_color"]
    uvs = mesh.uv_layers
    layer = uvs.get(snap["uv_active"]) if snap["uv_active"] else None
    if layer is not None:
        uvs.active = layer
    layer = uvs.get(snap["uv_render"]) if snap["uv_render"] else None
    if layer is not None:
        layer.active_render = True
    layer = uvs.get(snap["uv_clone"]) if snap["uv_clone"] else None
    if layer is not None:
        mesh.uv_layer_clone = layer
    layer = uvs.get(snap["uv_stencil"]) if snap["uv_stencil"] else None
    if layer is not None:
        mesh.uv_layer_stencil = layer



def _flush_bridged_attrs(session, mesh, vert_map):
    """Recreate every bridged user attribute layer on the rebuilt Blender mesh
    from the engine's (interpolated / undo-reverted) values. Called on the
    topology-rebuild path only — the fast path leaves Blender customdata intact.
    A layer the engine no longer carries is skipped (leaves no stale data).
    EDGE-domain columns are gathered back by endpoint matching (engine pairs
    mapped through `vert_map`); rebuilt edges with no engine counterpart (the
    re-added loose edges) take the type default."""
    import ctypes

    import numpy as np

    lib = engine.capi().lib
    domain_len = {'POINT': len(mesh.vertices), 'EDGE': len(mesh.edges),
                  'CORNER': len(mesh.loops), 'FACE': len(mesh.polygons)}
    edge_match = None
    for desc in session.bridged_attrs:
        count = domain_len[desc["bl_domain"]]
        ncomp = desc["ncomp"]
        if desc["bl_domain"] == 'EDGE':
            engine_pairs = _engine_edge_pairs(session.mesh_ptr)
            engine_values = np.empty(len(engine_pairs) * ncomp, dtype=desc["dtype"])
            if not lib.Mesh_readAttr(session.mesh_ptr, desc["engine_domain"],
                                     desc["name_bytes"], desc["engine_type"],
                                     engine_values.ctypes.data_as(ctypes.c_void_p)):
                continue
            if edge_match is None:
                mapped = np.where(engine_pairs >= 0, vert_map[engine_pairs], -1)
                mapped[np.any(engine_pairs < 0, axis=1)] = -1
                bl_pairs = np.empty(count * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", bl_pairs)
                edge_match = _match_pairs(bl_pairs.reshape(-1, 2), mapped)
            values = np.zeros(count * ncomp, dtype=desc["dtype"])
            hit = edge_match >= 0
            values.reshape(count, ncomp)[hit] = \
                engine_values.reshape(-1, ncomp)[edge_match[hit]]
        else:
            values = np.empty(count * ncomp, dtype=desc["dtype"])
            if not lib.Mesh_readAttr(session.mesh_ptr, desc["engine_domain"],
                                     desc["name_bytes"], desc["engine_type"],
                                     values.ctypes.data_as(ctypes.c_void_p)):
                continue
        try:
            attr = mesh.attributes.get(desc["name"])
            if attr is None:
                attr = mesh.attributes.new(desc["name"], desc["bl_type"], desc["bl_domain"])
            attr.data.foreach_set(desc["prop"], values)
        except (RuntimeError, TypeError) as error:
            # A reserved/builtin name Blender refuses to recreate, or a
            # domain-size mismatch; skip rather than abort the whole flush.
            print("SculptCore: could not restore attribute {!r}: {:s}".format(
                desc["name"], str(error)))
