# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Multires import/export (P8).

Convert Blender's `CD_MDISPS` multires displacement into a SculptCore
`Multires` stack on enter and bake it back on flush/exit. The multires modifier
itself is ignored while the mode is active. Both directions round-trip
*absolute top-level positions* (never frames): SculptCore's base is discrete
Catmull-Clark, Blender's is the CC limit surface, but the absolute-position
exchange absorbs the difference (see claudeMemory/research/grid-correspondence.md).

The engine grid samples and Blender's subdivided vertices are two samplings of
the same cage, and they correspond *exactly*: both decompose the cage into one
grid per face corner in (face, loop) order, so grid `g` on one side is grid `g`
on the other, and the two lattices differ only by a fixed transpose within a
grid (see `_lattice_permutation` and claudeMemory/research/grid-correspondence.md).
The map is built combinatorially from that identity plus the fork's
`Object.multires_grid_vert_indices`, and cached per session.
"""

from . import engine


def modifier(ob):
    """The object's multires modifier, or None."""
    for md in ob.modifiers:
        if md.type == 'MULTIRES':
            return md
    return None


def _lattice_permutation(grid_size):
    """Map an engine grid-local sample index to Blender's, within one grid.

    Both sides lay a `w * w` lattice over the same corner patch, but anchor it
    at opposite ends. With `S = w - 1`:

    * engine `(0,0)` is the corner vertex, `+u` runs along the corner's own
      edge, `+v` along the previous corner's edge, so `(S,S)` is the face center;
    * Blender `(0,0)` is the face center and `(S,S)` the corner vertex, with the
      axes swapped relative to the engine (`grid_u = 1 - ptex_v`).

    So engine `(u,v)` is Blender `(S-v, S-u)`, i.e. flat engine `v*w + u` is
    flat Blender `(S-u)*w + (S-v)`. That mapping is its own inverse, so the one
    table serves both directions.
    """
    import numpy as np

    side = grid_size - 1
    v, u = np.divmod(np.arange(grid_size * grid_size), grid_size)
    return (side - u) * grid_size + (side - v)


class MultiresMap:
    """Exact correspondence between engine grid samples and Blender subdivided
    vertices for one object. Built once on enter; every channel (positions,
    paint mask) rides the same tables."""

    def __init__(self, level, grid_size, engine_sample_to_blender,
                 blender_to_engine_sample, engine_vert_to_blender):
        self.level = level
        # Samples per grid side at `level`, i.e. the lattice the tables below
        # were built over; a level change rebuilds the map at the new size.
        self.grid_size = grid_size
        # engine grid-sample index -> Blender subdiv-vertex index (import seed).
        self.engine_sample_to_blender = engine_sample_to_blender
        # Blender subdiv-vertex index -> engine grid-sample index (one
        # representative sample per vertex; boundary replicas all agree).
        self.blender_to_engine_sample = blender_to_engine_sample
        # engine level-mesh vertex -> Blender subdiv-vertex index (per-vertex
        # attribute exchange, e.g. the paint mask). Derived from the grid
        # tables: each grid sample names its engine vertex.
        self.engine_vert_to_blender = engine_vert_to_blender


def build_engine(base_arrays, level):
    """Build an engine Multires stack over the base cage. Returns (mr, cage);
    the caller keeps `cage` alive for the stack's lifetime and frees both."""
    lib = engine.capi().lib
    positions, corner_verts, face_offsets = base_arrays
    cage = lib.Mesh_fromArrays(
        positions, len(positions) // 3,
        corner_verts, len(corner_verts),
        face_offsets, len(face_offsets) - 1,
    )
    if not cage:
        raise engine.EngineError("SculptCore: engine rejected multires cage mesh")
    mr = lib.Multires_new(cage, level, 0, 0, 0)
    if not mr:
        lib.freeMesh(cage)
        raise engine.EngineError("SculptCore: Multires_new failed")
    return mr, cage


def build_map(ob, depsgraph, mr_ptr, level, blender_verts_num):
    """Pair engine grid samples with Blender subdiv vertices, combinatorially.

    The fork's `Object.multires_grid_vert_indices` names, for every top-level
    grid sample in `CD_MDISPS` order, the subdivided vertex it coincides with.
    The engine's grids are the same corner patches enumerated in the same
    order, so `_lattice_permutation` is the whole of the difference — no
    geometric matching is involved, which is what makes this exact at every
    level and on every topology. (It replaced a nearest-neighbour pairing on
    the undisplaced base, which mispaired neighbouring samples wherever the
    engine's discrete-CC base disagreed with Blender's limit surface — visible
    as grid borders pulled toward the base at level >= 3.)

    `mr_ptr` is the engine Multires; only its sample count is read here.
    `blender_verts_num` is the subdivided mesh's vertex count at `level`, which
    the reverse table is sized to."""
    import numpy as np

    lib = engine.capi().lib
    vert_indices, grid_size = ob.multires_grid_vert_indices(depsgraph)
    blender = np.array(vert_indices, dtype=np.int64)
    area = grid_size * grid_size
    if grid_size < 2 or area == 0 or len(blender) % area:
        raise engine.EngineError(
            "SculptCore: multires grid map is malformed ({} samples, grid size {})".format(
                len(blender), grid_size))
    count = lib.Multires_levelSampleCount(mr_ptr, level)
    if count != len(blender):
        raise engine.EngineError(
            "SculptCore: multires grid sample count mismatch "
            "(engine {}, Blender {})".format(count, len(blender)))
    if (blender < 0).any():
        raise engine.EngineError(
            "SculptCore: multires grid sample unpaired by Blender's subdiv walk")

    permutation = _lattice_permutation(grid_size)
    engine_sample_to_blender = blender.reshape(-1, area)[:, permutation].reshape(-1)

    # One representative engine sample per Blender vertex. Boundary vertices are
    # named by several samples; those samples are replicas of a single engine
    # vertex, so which one wins does not matter.
    if int(engine_sample_to_blender.max()) >= blender_verts_num:
        raise engine.EngineError(
            "SculptCore: multires grid map names subdiv vertex {} of {}".format(
                int(engine_sample_to_blender.max()), blender_verts_num))
    blender_to_engine_sample = np.zeros(blender_verts_num, dtype=np.int64)
    blender_to_engine_sample[engine_sample_to_blender] = np.arange(
        len(engine_sample_to_blender))
    # A subdivided vertex no grid sample names is one outside every ptex face —
    # loose edges and wire vertices, which carry no MDISPS/mask element and are
    # not part of the multires domain. Their slot above keeps its zero fill;
    # nothing reads it, because both exchanges are driven by the grid samples.

    # Grid sample -> engine vertex, from the stack's grid tables; combined with
    # the sample map this gives the per-vertex correspondence used for
    # attribute exchange.
    import sculptcore

    mgr = engine.manager()
    mr_obj = mgr.get_bound_pointer(
        mgr.get("sculptcore::subdiv::Multires"), mr_ptr, deref=False)
    with sculptcore.construct_from_items(mgr, mgr.get("int32"), []) as out:
        mr_obj.levelGridVertsOut(level, out)
        grid_verts = out.numpy().copy()
    valid = grid_verts >= 0
    engine_vert_to_blender = np.zeros(int(grid_verts.max()) + 1, dtype=np.int64)
    engine_vert_to_blender[grid_verts[valid]] = engine_sample_to_blender[valid]
    mapping = MultiresMap(level, grid_size, engine_sample_to_blender,
                          blender_to_engine_sample, engine_vert_to_blender)
    return mapping


def import_displacement(mr_ptr, mapping, blender_top_positions):
    """Seed the engine stack from Blender's displaced top-level positions
    (subdiv-vertex order). Uses the chain-only seeding seam — no throwaway
    materializations, down-propagation deferred as debt (settled by the
    first downward level switch) — which is what makes the mode enter fast;
    the caller activates the level afterwards. Returns the sample count."""
    import numpy as np

    lib = engine.capi().lib
    # Each engine grid sample takes the displaced position of its paired
    # Blender subdiv vertex (seam replicas resolve to equal values).
    seed = np.ascontiguousarray(
        blender_top_positions[mapping.engine_sample_to_blender], dtype=np.float32)
    return lib.Multires_seedLevelPositions(
        mr_ptr, mapping.level, seed.reshape(-1), len(seed))


def export_bake(ob, depsgraph, mr_ptr, mapping):
    """Bake the engine stack's top-level surface into the object's CD_MDISPS
    via the dedup subdiv-vertex reshape seam."""
    import numpy as np

    lib = engine.capi().lib
    count = lib.Multires_levelSampleCount(mr_ptr, mapping.level)
    engine_top = np.empty(count * 3, dtype=np.float32)
    lib.Multires_levelPositionsOut(mr_ptr, mapping.level, engine_top)
    engine_top = engine_top.reshape(-1, 3)

    vertcos = np.ascontiguousarray(
        engine_top[mapping.blender_to_engine_sample].reshape(-1), dtype=np.float32)
    ob.multires_reshape_from_vert_positions(depsgraph, vertcos)
    ob.data.update_tag()


# Mask exchange (MK4). The engine's mask truth is the STORE's "mask" channel
# (every level; Authored rule), and its top-level sample layout is exactly the
# engine grid-sample order the map pairs with Blender's subdiv vertices — so
# both directions of the exchange are exact top-level copies, and a no-edit
# round trip is bit-identical. Importing also seeds every coarser level by
# injection (each coarse sample coincides with a top sample); exporting reads
# the top level alone, since the engine's own edit propagation keeps it
# current. Slot-mesh mask columns and domain mirrors are caches, refreshed
# from the store by generation (convert.sync_slot_mask / the engine's write
# hooks) — nothing here touches them.
_SC_MASK = b".spatial.v.mask"

# Engine enum values for the mask channel declaration: mesh::AttrType::FLOAT,
# GridElemDomain::Vertex, GridLevelRule::Authored.
_MASK_CHANNEL_ARGS = (b"mask", 1, 0, 1, 1, 1)


def _stored_top_engine_values(ob, depsgraph, mapping):
    """The stored grid paint mask in top-level engine-sample order, or None
    when the object has no mask layer."""
    import numpy as np

    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    if not has_mask:
        return None
    blender_values = np.array(values, dtype=np.float32)
    return blender_values[mapping.engine_sample_to_blender]



def import_mask(ob, depsgraph, mapping, mr_ptr):
    """Seed the store's mask channel from the object's grid paint mask: the
    top level takes the stored lattice verbatim, every coarser level is
    seeded by injection. Raw channel writes are propagation-free SEEDs (the
    engine re-mirrors alive domains and marks draw itself). No-op when the
    object has no mask layer — the channel is not created for maskless
    objects."""
    import numpy as np

    top_values = _stored_top_engine_values(ob, depsgraph, mapping)
    if top_values is None:
        return
    lib = engine.capi().lib
    ch = lib.Multires_gridChannelEnsure(mr_ptr, *_MASK_CHANNEL_ARGS)
    if ch < 0:
        raise engine.EngineError("SculptCore: engine refused the mask grid channel")
    top = mapping.level
    top_w = mapping.grid_size
    grids = top_values.reshape(-1, top_w, top_w)
    for level in range(top, 0, -1):
        f = 1 << (top - level)
        values = np.ascontiguousarray(grids[:, ::f, ::f].reshape(-1), dtype=np.float32)
        if lib.Multires_gridChannelWrite(mr_ptr, level, ch, 0, len(grids),
                                         values, len(values)) != len(values):
            raise engine.EngineError(
                "SculptCore: mask channel write failed at level {}".format(level))


def export_mask(ob, depsgraph, mapping, mr_ptr):
    """Write the store's top-level mask back into the object's grid paint
    mask (created on first use), clipped to 0..1. The store top is the mask
    truth — edits at any level reached it through the engine's upward
    prolongation — so the copy is exact and a no-edit round trip is
    bit-identical. No-op while the engine holds no mask content (never
    creates a zero CD layer)."""
    import numpy as np

    lib = engine.capi().lib
    ch = lib.Multires_gridChannelFind(mr_ptr, b"mask")
    top = mapping.level
    if ch < 0 or not lib.Multires_gridChannelLevelAllocated(mr_ptr, top, ch):
        return
    n = len(mapping.engine_sample_to_blender)
    top_w = mapping.grid_size
    top_values = np.empty(n, dtype=np.float32)
    if lib.Multires_gridChannelRead(mr_ptr, top, ch, 0, n // (top_w * top_w),
                                    top_values, n) != n:
        return
    blender_values = np.zeros(len(mapping.blender_to_engine_sample), dtype=np.float32)
    blender_values[mapping.engine_sample_to_blender] = np.clip(top_values, 0.0, 1.0)
    ob.multires_mask_from_vert_values(
        depsgraph, np.ascontiguousarray(blender_values, dtype=np.float32))
    ob.data.update_tag()
