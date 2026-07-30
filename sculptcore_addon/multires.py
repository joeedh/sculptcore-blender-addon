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
    return MultiresMap(level, grid_size, engine_sample_to_blender,
                       blender_to_engine_sample, engine_vert_to_blender)


def import_displacement(mr_ptr, mapping, blender_top_positions):
    """Seed the engine stack from Blender's displaced top-level positions
    (subdiv-vertex order). Returns the changed-vert count."""
    import numpy as np

    lib = engine.capi().lib
    # Each engine grid sample takes the displaced position of its paired
    # Blender subdiv vertex (seam replicas resolve to equal values).
    seed = np.ascontiguousarray(
        blender_top_positions[mapping.engine_sample_to_blender], dtype=np.float32)
    return lib.Multires_fromLevelPositions(
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


# Mask exchange (A4). The engine mask lives on the level mesh's
# `.spatial.v.mask` column, Blender's on CD_GRID_PAINT_MASK; both directions
# route through top-level per-subdiv-vertex values via the vert map.
_SC_MASK = b".spatial.v.mask"


def _vert_map(mesh_ptr, mapping):
    """`mapping.engine_vert_to_blender` sized to the engine mesh's live vertex
    count, which is what the per-vertex attribute c-api reads and writes. The
    two agree for a freshly built level mesh (compact, no freelist gaps); a
    disagreement would otherwise run off the end of the exchange buffer."""
    import ctypes

    nv, nc, nf, cap = (ctypes.c_int(0) for _ in range(4))
    engine.capi().lib.Mesh_arraySizes(mesh_ptr, ctypes.byref(nv), ctypes.byref(nc),
                                      ctypes.byref(nf), ctypes.byref(cap))
    vert_map = mapping.engine_vert_to_blender
    if nv.value != len(vert_map):
        raise engine.EngineError(
            "SculptCore: multires level mesh has {} verts, map covers {}".format(
                nv.value, len(vert_map)))
    return vert_map


def import_mask(ob, depsgraph, mesh_ptr, mapping):
    """Seed the engine mask on the (top-level) engine mesh from the object's
    grid paint mask. No-op without a mask layer; returns True when seeded."""
    import numpy as np

    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    if not has_mask:
        return False
    vert_map = _vert_map(mesh_ptr, mapping)
    blender_values = np.array(values, dtype=np.float32)
    engine_values = np.ascontiguousarray(blender_values[vert_map], dtype=np.float32)
    engine.capi().lib.Mesh_writeVertFloatAttr(mesh_ptr, _SC_MASK, engine_values)
    return True


def export_mask(ob, depsgraph, mesh_ptr, mapping):
    """Write the engine mask back into the object's grid paint mask (created
    on first use). No-op when the engine mesh carries no mask."""
    import numpy as np

    vert_map = _vert_map(mesh_ptr, mapping)
    engine_values = np.zeros(len(vert_map), dtype=np.float32)
    if not engine.capi().lib.Mesh_readVertFloatAttr(mesh_ptr, _SC_MASK, engine_values):
        return False
    blender_values = np.zeros(len(mapping.blender_to_engine_sample), dtype=np.float32)
    blender_values[vert_map] = engine_values
    ob.multires_mask_from_vert_values(
        depsgraph, np.ascontiguousarray(blender_values, dtype=np.float32))
    ob.data.update_tag()
    return True
