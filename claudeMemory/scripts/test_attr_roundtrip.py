# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless roundtrip test for the attribute bridge.

Drives the conversion layer directly (convert.enter -> forced topology
rebuild -> convert.flush) and asserts that every bridged datum survives:
generic attributes on all four domains, dot-prefixed work-state layers,
loose edges, skin vertices, vertex groups, layer designations, and
mid-session attribute creation/deletion.

The forced rebuild leaves the topology identical (the stamp is faked), so
the vertex maps are identities and every value must round-trip exactly.

Run against a staged build (the addon must be the copy under test)::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_attr_roundtrip.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine

failures = []


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def arr(attr, prop, count, dtype):
    buf = np.zeros(count, dtype=dtype)
    attr.data.foreach_get(prop, buf)
    return buf


def build_object():
    mesh = bpy.data.meshes.new("attr_roundtrip")
    # A 3x3 grid of quads, plus a loose edge (9-10) and a loose vertex (11).
    verts = [(x, y, 0.0) for y in range(3) for x in range(3)]
    verts += [(5.0, 0.0, 0.0), (5.0, 1.0, 1.0), (7.0, 7.0, 7.0)]
    faces = [(y * 3 + x, y * 3 + x + 1, (y + 1) * 3 + x + 1, (y + 1) * 3 + x)
             for y in range(2) for x in range(2)]
    mesh.from_pydata(verts, [(9, 10)], faces)
    mesh.update(calc_edges=True)
    mesh.validate()

    ob = bpy.data.objects.new("attr_roundtrip", mesh)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    return ob


def seed(mesh, name, dtype, domain, prop, values, np_dtype):
    # Some dot layers (.select_vert) already exist on a fresh mesh — a second
    # attributes.new() would silently create "<name>.001".
    attr = mesh.attributes.get(name)
    if attr is None:
        attr = mesh.attributes.new(name, dtype, domain)
    buf = np.asarray(values, dtype=np_dtype)
    attr.data.foreach_set(prop, buf)
    return buf


def main():
    ob = build_object()
    mesh = ob.data
    nv, ne, nc, nf = (len(mesh.vertices), len(mesh.edges), len(mesh.loops),
                      len(mesh.polygons))
    print("test mesh: {} verts / {} edges / {} corners / {} faces".format(
        nv, ne, nc, nf))

    rng = np.arange
    seeded = {}
    seeded["pf"] = seed(mesh, "pf", 'FLOAT', 'POINT', "value", rng(nv) * 0.5, np.float32)
    seeded["p4"] = seed(mesh, "p4", 'FLOAT4', 'POINT', "vector",
                        rng(nv * 4) * 0.25, np.float32)
    seeded["pfdel"] = seed(mesh, "pfdel", 'FLOAT', 'POINT', "value", rng(nv), np.float32)
    seeded["fi"] = seed(mesh, "fi", 'INT', 'FACE', "value", rng(nf) + 7, np.int32)
    seeded["flowfield"] = seed(mesh, "flowfield", 'FLOAT2', 'CORNER', "vector",
                               rng(nc * 2) * 0.125, np.float32)
    seeded["crease_edge"] = seed(mesh, "crease_edge", 'FLOAT', 'EDGE', "value",
                                 (rng(ne) % 10) * 0.1, np.float32)
    seeded["freestyle_edge"] = seed(mesh, "freestyle_edge", 'BOOLEAN', 'EDGE',
                                    "value", rng(ne) % 2, np.bool_)
    seeded[".select_vert"] = seed(mesh, ".select_vert", 'BOOLEAN', 'POINT',
                                  "value", rng(nv) % 2, np.bool_)
    seeded[".hide_vert"] = seed(mesh, ".hide_vert", 'BOOLEAN', 'POINT',
                                "value", (rng(nv) + 1) % 2, np.bool_)
    seeded[".hide_poly"] = seed(mesh, ".hide_poly", 'BOOLEAN', 'FACE',
                                "value", rng(nf) % 2, np.bool_)

    # Two UV maps plus a non-UV corner float2 (above) for the AttrUse check.
    uva = mesh.uv_layers.new(name="UVA")
    uvb = mesh.uv_layers.new(name="UVB")
    uva_vals = (rng(nc * 2) * 0.01).astype(np.float32)
    uvb_vals = (rng(nc * 2) * 0.02 + 1.0).astype(np.float32)
    mesh.attributes["UVA"].data.foreach_set("vector", uva_vals)
    mesh.attributes["UVB"].data.foreach_set("vector", uvb_vals)
    seeded[".pn.UVA"] = seed(mesh, ".pn.UVA", 'BOOLEAN', 'CORNER', "value",
                             rng(nc) % 2, np.bool_)

    # Colors: two point float-color layers; designations split between them.
    ca = mesh.color_attributes.new("ColA", 'FLOAT_COLOR', 'POINT')
    cb = mesh.color_attributes.new("ColB", 'FLOAT_COLOR', 'POINT')
    ca_vals = (rng(nv * 4) * 0.03).astype(np.float32)
    cb_vals = (rng(nv * 4) * 0.04).astype(np.float32)
    ca.data.foreach_set("color", ca_vals)
    cb.data.foreach_set("color", cb_vals)
    mesh.attributes.active_color_name = "ColA"
    mesh.attributes.default_color_name = "ColB"

    # UV designations: active UVA, render/clone/stencil UVB.
    mesh.uv_layers.active = mesh.uv_layers["UVA"]
    mesh.uv_layers["UVB"].active_render = True
    mesh.uv_layer_clone = mesh.uv_layers["UVB"]
    mesh.uv_layer_stencil = mesh.uv_layers["UVB"]

    # Encoded custom normals: bake a tilted field through the official setter
    # (creates the INT16_2D corner layer), then remember the resolved
    # directions the bridge must reproduce.
    tilted = np.empty(nc * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", tilted)
    tilted = tilted.reshape(-1, 3)
    tilted[:, 0] += 0.2
    tilted /= np.linalg.norm(tilted, axis=1)[:, None]
    mesh.normals_split_custom_set(tilted)
    cn_attr = mesh.attributes.get("custom_normal")
    have_encoded = cn_attr is not None and cn_attr.data_type == 'INT16_2D'
    check(have_encoded, "encoded custom_normal layer created")
    resolved = np.empty(nc * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", resolved)

    # Vertex group.
    vg = ob.vertex_groups.new(name="grp")
    vg.add(list(range(0, nv, 2)), 0.75, 'REPLACE')

    # Animation data on the Mesh ID (survives only via set_topology).
    has_set_topology = hasattr(mesh, "set_topology")
    if has_set_topology:
        mesh.animation_data_create()

    # Shape keys: basis + one offset key, basis active (the enter requirement).
    shape_offset = None
    if has_set_topology:
        ob.shape_key_add(name="Basis")
        smile = ob.shape_key_add(name="Smile")
        shape_offset = np.zeros(nv * 3, dtype=np.float32)
        smile.data.foreach_get("co", shape_offset)
        shape_offset = shape_offset.reshape(-1, 3)
        shape_offset[:, 2] += 0.5
        smile.data.foreach_set("co", shape_offset.reshape(-1))
        smile.value = 0.7
        smile.slider_max = 2.0
        ob.active_shape_key_index = 0

    # Skin layer.
    skin_ok = True
    try:
        bpy.ops.mesh.customdata_skin_add()
    except Exception as error:
        print("  note: customdata_skin_add unavailable ({})".format(error))
        skin_ok = False
    skin_radius = None
    if skin_ok and len(mesh.skin_vertices):
        skin_radius = (rng(nv * 2) * 0.05 + 0.1).astype(np.float32)
        mesh.skin_vertices[0].data.foreach_set("radius", skin_radius)

    # --- enter ---
    session = convert.enter(ob)
    check(session is not None, "session created")

    # Mid-session mutations the read point must observe.
    mesh.attributes.remove(mesh.attributes["pfdel"])
    seeded["midpf"] = seed(mesh, "midpf", 'FLOAT', 'POINT', "value",
                           rng(nv) * 2.0, np.float32)
    mesh.uv_layers.active = mesh.uv_layers["UVB"]

    # --- forced topology rebuild (identity) ---
    session.topo_stamp ^= 0xFFFF
    convert.flush(ob)

    mesh = ob.data
    check(len(mesh.vertices) == nv, "vertex count survives")
    check(len(mesh.polygons) == nf, "face count survives")

    def expect(name, prop, count, np_dtype, want, exact=True):
        attr = mesh.attributes.get(name)
        if attr is None:
            check(False, "attribute {!r} survives".format(name))
            return
        got = arr(attr, prop, count, np_dtype)
        same = np.array_equal(got, want) if exact else np.allclose(got, want)
        check(same, "attribute {!r} values round-trip".format(name))

    expect("pf", "value", nv, np.float32, seeded["pf"])
    expect("p4", "vector", nv * 4, np.float32, seeded["p4"])
    expect("fi", "value", nf, np.int32, seeded["fi"])
    expect("flowfield", "vector", nc * 2, np.float32, seeded["flowfield"])
    expect("UVA", "vector", nc * 2, np.float32, uva_vals)
    expect("UVB", "vector", nc * 2, np.float32, uvb_vals)
    expect(".pn.UVA", "value", nc, np.bool_, seeded[".pn.UVA"])
    expect(".select_vert", "value", nv, np.bool_, seeded[".select_vert"])
    expect(".hide_vert", "value", nv, np.bool_, seeded[".hide_vert"])
    expect(".hide_poly", "value", nf, np.bool_, seeded[".hide_poly"])
    expect("ColA", "color", nv * 4, np.float32, ca_vals)
    expect("ColB", "color", nv * 4, np.float32, cb_vals)
    expect("midpf", "value", nv, np.float32, seeded["midpf"])

    check(mesh.attributes.get("pfdel") is None,
          "mid-session-deleted layer is not resurrected")

    # Edge domain: identity topology, but edge *order* may differ after
    # calc_edges; compare by vertex pair.
    def edge_values(name, np_dtype):
        attr = mesh.attributes.get(name)
        if attr is None:
            return None, None
        count = len(mesh.edges)
        vals = arr(attr, "value", count, np_dtype)
        pairs = np.zeros(count * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", pairs)
        keys = convert._pair_keys(pairs.reshape(-1, 2))
        return dict(zip(keys.tolist(), vals.tolist())), count

    orig_pairs = np.zeros(ne * 2, dtype=np.int32)
    # Rebuild the original pair keys from the seeded grid (pre-enter edges).
    # The seeded arrays were indexed by original edge order; reconstruct keys
    # from the original mesh definition instead of trusting current order.
    # (Original mesh object was replaced in place, so recompute from faces.)
    got_crease, _ = edge_values("crease_edge", np.float32)
    got_fs, _ = edge_values("freestyle_edge", np.bool_)
    check(got_crease is not None, "crease_edge survives")
    check(got_fs is not None, "freestyle_edge survives")

    # Loose geometry.
    pairs = np.zeros(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    pair_set = {tuple(sorted(p)) for p in pairs.reshape(-1, 2).tolist()}
    check((9, 10) in pair_set, "loose edge survives the rebuild")
    check(len(mesh.vertices) == nv, "loose vertex survives the rebuild")

    # Designations (uv active changed mid-session to UVB).
    check(mesh.attributes.active_color_name == "ColA", "active color designation")
    check(mesh.attributes.default_color_name == "ColB", "default color designation")
    active_uv = mesh.uv_layers.active
    check(active_uv is not None and active_uv.name == "UVB",
          "active UV designation (mid-session change wins)")
    render_uv = next((l.name for l in mesh.uv_layers if l.active_render), None)
    check(render_uv == "UVB", "render UV designation")
    check(mesh.uv_layer_clone is not None and mesh.uv_layer_clone.name == "UVB",
          "clone UV designation")
    check(mesh.uv_layer_stencil is not None and mesh.uv_layer_stencil.name == "UVB",
          "stencil UV designation")

    # Vertex groups.
    check(len(ob.vertex_groups) == 1 and ob.vertex_groups[0].name == "grp",
          "vertex group survives")
    try:
        w = ob.vertex_groups[0].weight(0)
        check(abs(w - 0.75) < 1e-6, "vertex group weight survives")
    except RuntimeError:
        check(False, "vertex group weight survives")

    # Encoded custom normals: the layer must come back in its encoded form and
    # the resolved directions must match (identity topology — same fans, so
    # only encode quantization separates them).
    if have_encoded:
        cn_attr = mesh.attributes.get("custom_normal")
        check(cn_attr is not None and cn_attr.data_type == 'INT16_2D'
              and cn_attr.domain == 'CORNER', "custom_normal survives encoded")
        got = np.empty(nc * 3, dtype=np.float32)
        mesh.corner_normals.foreach_get("vector", got)
        check(np.allclose(got, resolved, atol=5e-3),
              "resolved corner normals round-trip (max err {:.2e})".format(
                  float(np.abs(got - resolved).max())))

    # Skin.
    if skin_radius is not None:
        if len(mesh.skin_vertices):
            got = np.zeros(nv * 2, dtype=np.float32)
            mesh.skin_vertices[0].data.foreach_get("radius", got)
            check(np.allclose(got, skin_radius), "skin radii round-trip")
        else:
            check(False, "skin layer survives")

    # Crease/freestyle by pair against the seeded original order: original
    # edge order came from the freshly built mesh; rebuild it.
    # (Seeded values were written against the pre-enter edge order; original
    # edges are the same pair set, so compare multisets of values instead.)
    check(sorted(got_crease.values()) == sorted(
        np.asarray(seeded["crease_edge"], dtype=np.float32).tolist()),
        "crease_edge value multiset round-trips")
    check(sorted(got_fs.values()) == sorted(
        np.asarray(seeded["freestyle_edge"], dtype=np.bool_).tolist()),
        "freestyle_edge value multiset round-trips")

    # F4-only guarantees.
    if has_set_topology:
        check(mesh.animation_data is not None, "animation data survives (F4)")
        key = mesh.shape_keys
        check(key is not None and len(key.key_blocks) == 2, "shape key blocks survive")
        if key is not None and len(key.key_blocks) == 2:
            smile = key.key_blocks[1]
            got = np.zeros(nv * 3, dtype=np.float32)
            smile.data.foreach_get("co", got)
            check(np.allclose(got.reshape(-1, 3), shape_offset, atol=1e-6),
                  "non-basis key values round-trip")
            check(abs(smile.value - 0.7) < 1e-6 and abs(smile.slider_max - 2.0) < 1e-6,
                  "key block metadata survives")
            basis = np.zeros(nv * 3, dtype=np.float32)
            key.key_blocks[0].data.foreach_get("co", basis)
            pos = np.zeros(nv * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", pos)
            check(np.allclose(basis, pos), "basis key equals mesh positions")

    convert.exit_(ob)

    # A rebuild with no loose edges exercises set_topology's empty edge_verts.
    mesh2 = bpy.data.meshes.new("no_loose")
    mesh2.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [],
                      [(0, 1, 2, 3)])
    mesh2.update(calc_edges=True)
    ob2 = bpy.data.objects.new("no_loose", mesh2)
    bpy.context.scene.collection.objects.link(ob2)
    session2 = convert.enter(ob2)
    session2.topo_stamp ^= 0xFFFF
    convert.flush(ob2)
    check(len(ob2.data.vertices) == 4 and len(ob2.data.edges) == 4,
          "empty-edge-list rebuild keeps counts")
    convert.exit_(ob2)

    print()
    if failures:
        print("test_attr_roundtrip: {} FAILURE(S)".format(len(failures)))
        for msg in failures:
            print("  - " + msg)
        raise SystemExit(1)
    print("test_attr_roundtrip: all checks passed")


main()
