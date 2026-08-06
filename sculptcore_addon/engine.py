# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Single load point for the SculptCore engine: imports the ``sculptcore``
ctypes package (``$SCULPTCORE_PYTHON_PATH`` first so a development checkout
overrides the bundle, then the vendored ``lib/`` staged by
``make.mjs bundle``), initializes the binding manager once, and declares
the bulk c-api entry points the conversion layer uses.

The session registry lives here too: one ``session.Session`` per object
currently in the mode, keyed by object name.
"""

import ctypes
import os
import sys

_manager = None
_capi = None

# Object name -> session.Session for every object currently in the mode.
sessions = {}


class EngineError(RuntimeError):
    pass


def _import_sculptcore():
    try:
        import sculptcore
        return sculptcore
    except ImportError:
        pass

    # The dev checkout must win over the vendored bundle, or setting the env
    # var silently stops working once a bundle has been staged.
    candidates = []
    dev_path = os.environ.get("SCULPTCORE_PYTHON_PATH")
    if dev_path:
        candidates.append(dev_path)
    vendored = os.path.join(os.path.dirname(__file__), "lib")
    if os.path.isdir(os.path.join(vendored, "sculptcore")):
        candidates.append(vendored)

    for path in candidates:
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import sculptcore
            return sculptcore
        except ImportError:
            continue

    raise EngineError(
        "SculptCore engine not found: vendor it into {:s} or set "
        "SCULPTCORE_PYTHON_PATH to the package directory".format(vendored))


def manager():
    """The engine binding manager (lazy; loads the native library on first
    use and refuses an ABI-mismatched build)."""
    global _manager
    if _manager is None:
        sculptcore = _import_sculptcore()
        _manager = sculptcore.init()
    return _manager


class _CApi:
    """ctypes declarations for the c-api seams the conversion layer calls
    (the bulk-array entry points are free functions, not reflected)."""

    def __init__(self, lib):
        import numpy as np

        f32p = np.ctypeslib.ndpointer(dtype=np.float32, flags="C_CONTIGUOUS")
        i32p = np.ctypeslib.ndpointer(dtype=np.int32, flags="C_CONTIGUOUS")
        c_int_p = ctypes.POINTER(ctypes.c_int)

        lib.Mesh_fromArrays.argtypes = [
            f32p, ctypes.c_int, i32p, ctypes.c_int, i32p, ctypes.c_int,
        ]
        lib.Mesh_fromArrays.restype = ctypes.c_void_p
        lib.Mesh_arraySizes.argtypes = [ctypes.c_void_p] + [c_int_p] * 4
        lib.Mesh_arraySizes.restype = None
        lib.Mesh_toArrays.argtypes = [ctypes.c_void_p, f32p, i32p, i32p, i32p]
        lib.Mesh_toArrays.restype = ctypes.c_int
        lib.Mesh_topoStamp.argtypes = [ctypes.c_void_p]
        lib.Mesh_topoStamp.restype = ctypes.c_uint64
        lib.Mesh_readVertFloatAttr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, f32p]
        lib.Mesh_readVertFloatAttr.restype = ctypes.c_int
        lib.Mesh_writeVertFloatAttr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, f32p]
        lib.Mesh_writeVertFloatAttr.restype = ctypes.c_int
        lib.Mesh_readFaceIntAttr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, i32p]
        lib.Mesh_readFaceIntAttr.restype = ctypes.c_int
        lib.Mesh_writeFaceIntAttr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, i32p]
        lib.Mesh_writeFaceIntAttr.restype = ctypes.c_int
        lib.Mesh_readVertFloat4Attr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, f32p]
        lib.Mesh_readVertFloat4Attr.restype = ctypes.c_int
        lib.Mesh_writeVertFloat4Attr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, f32p]
        lib.Mesh_writeVertFloat4Attr.restype = ctypes.c_int
        lib.Mesh_writeCornerFloat2Attr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, f32p]
        lib.Mesh_writeCornerFloat2Attr.restype = ctypes.c_int
        # Generic attribute bridge: read/write a named layer of arbitrary type on
        # any domain. The buffer is typed by `type` (an engine AttrType), so it is
        # passed as a raw void pointer (the numpy array carries the real dtype).
        lib.Mesh_readAttr.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        lib.Mesh_readAttr.restype = ctypes.c_int
        lib.Mesh_writeAttr.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p]
        lib.Mesh_writeAttr.restype = ctypes.c_int
        # Vertex-group weights. The generic bridge above refuses
        # AttrType::WEIGHTS — a cell is a refcounted pool index, meaningless
        # outside its mesh — so these move the resolved runs instead, as CSR in
        # bulk: `offsets` has vert_count + 1 entries indexing parallel
        # group/weight arrays, in the same live-vertex order as Mesh_toArrays.
        # Group ids index the name table, which must be written first.
        lib.sc_mesh_weights_element_count.argtypes = [ctypes.c_void_p]
        lib.sc_mesh_weights_element_count.restype = ctypes.c_int
        lib.sc_mesh_weights_get.argtypes = [ctypes.c_void_p, i32p, i32p, f32p]
        lib.sc_mesh_weights_get.restype = ctypes.c_int
        lib.sc_mesh_weights_set.argtypes = [ctypes.c_void_p, i32p, i32p, f32p]
        lib.sc_mesh_weights_set.restype = ctypes.c_int
        lib.sc_mesh_weight_group_count.argtypes = [ctypes.c_void_p]
        lib.sc_mesh_weight_group_count.restype = ctypes.c_int
        lib.sc_mesh_weight_groups_get.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.sc_mesh_weight_groups_get.restype = ctypes.c_int
        lib.sc_mesh_weight_groups_set.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.sc_mesh_weight_groups_set.restype = ctypes.c_int
        # Boundary edge flags (P11): seam/sharp migration keyed by vertex
        # pairs (the engine derives its own edges, so there is no stable edge
        # index correspondence), plus the boundary recompute and the
        # named-target UV unwrap.
        u8p = np.ctypeslib.ndpointer(dtype=np.uint8, flags="C_CONTIGUOUS")
        lib.Mesh_edgeCount.argtypes = [ctypes.c_void_p]
        lib.Mesh_edgeCount.restype = ctypes.c_int
        # Edge identity channel: live edge endpoints in the same live-iteration
        # order the EDGE-domain Mesh_readAttr/Mesh_writeAttr use, so edge
        # columns can be paired with Blender edges by endpoint matching.
        lib.Mesh_edgeVertsOut.argtypes = [ctypes.c_void_p, i32p]
        lib.Mesh_edgeVertsOut.restype = ctypes.c_int
        lib.Mesh_writeEdgeFlagsByVerts.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, i32p, u8p, ctypes.c_int]
        lib.Mesh_writeEdgeFlagsByVerts.restype = ctypes.c_int
        lib.Mesh_readEdgeFlags.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, i32p, ctypes.c_int]
        lib.Mesh_readEdgeFlags.restype = ctypes.c_int
        lib.Mesh_recomputeBoundary.argtypes = [ctypes.c_void_p]
        lib.Mesh_recomputeBoundary.restype = None
        lib.Mesh_generateUVFromSeams.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.Mesh_generateUVFromSeams.restype = ctypes.c_int
        lib.freeMesh.argtypes = [ctypes.c_void_p]
        lib.freeMesh.restype = None
        lib.Mesh_buildSpatialTree.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 3
        lib.Mesh_buildSpatialTree.restype = ctypes.c_void_p
        lib.SpatialTree_free.argtypes = [ctypes.c_void_p]
        lib.SpatialTree_free.restype = None

        # Multires (P8): stack over a cage, per-level materialization, and the
        # position seed/dump that round-trips a level's surface through MDISPS.
        c_int_p4 = [ctypes.POINTER(ctypes.c_int)] * 4
        lib.Mesh_arraySizes.argtypes = [ctypes.c_void_p] + c_int_p4
        lib.Mesh_arraySizes.restype = None
        lib.Mesh_toArrays.argtypes = [ctypes.c_void_p, f32p, i32p, i32p, i32p]
        lib.Mesh_toArrays.restype = ctypes.c_int
        lib.Multires_new.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        lib.Multires_new.restype = ctypes.c_void_p
        lib.Multires_free.argtypes = [ctypes.c_void_p]
        lib.Multires_free.restype = None
        lib.Multires_setActiveLevel.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_setActiveLevel.restype = ctypes.c_int
        lib.Multires_activeMesh.argtypes = [ctypes.c_void_p]
        lib.Multires_activeMesh.restype = ctypes.c_void_p
        lib.Multires_activeTree.argtypes = [ctypes.c_void_p]
        lib.Multires_activeTree.restype = ctypes.c_void_p
        lib.Multires_levelSampleCount.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_levelSampleCount.restype = ctypes.c_int
        lib.Multires_levelPositionsOut.argtypes = [ctypes.c_void_p, ctypes.c_int, f32p]
        lib.Multires_levelPositionsOut.restype = ctypes.c_int
        lib.Multires_fromLevelPositions.argtypes = [
            ctypes.c_void_p, ctypes.c_int, f32p, ctypes.c_int]
        lib.Multires_fromLevelPositions.restype = ctypes.c_int
        lib.Multires_seedLevelPositions.argtypes = [
            ctypes.c_void_p, ctypes.c_int, f32p, ctypes.c_int]
        lib.Multires_seedLevelPositions.restype = ctypes.c_int
        lib.Multires_writeback.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_writeback.restype = ctypes.c_int
        # Level count mutation (P8 C5): follow the modifier's Subdivide /
        # Delete Higher so both stacks keep the same number of levels. Each
        # returns the new maxLevel and leaves the finest level active.
        lib.Multires_maxLevel.argtypes = [ctypes.c_void_p]
        lib.Multires_maxLevel.restype = ctypes.c_int
        lib.Multires_addLevel.argtypes = [ctypes.c_void_p]
        lib.Multires_addLevel.restype = ctypes.c_int
        lib.Multires_removeTopLevel.argtypes = [ctypes.c_void_p]
        lib.Multires_removeTopLevel.restype = ctypes.c_int
        # Store snapshot seam (P8 C4): serialize returns an engine-owned
        # buffer (free with freeMeshBuffer); restore replaces the store and
        # invalidates every derived level (re-activate + re-fetch afterwards).
        lib.Multires_serializeStore.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        lib.Multires_serializeStore.restype = ctypes.POINTER(ctypes.c_uint8)
        lib.Multires_restoreStore.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.Multires_restoreStore.restype = ctypes.c_int
        lib.freeMeshBuffer.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
        lib.freeMeshBuffer.restype = None

        # External draw provider (P5 D6): register a tree under the object's
        # session_uid, refresh its GPU-node CPU buffers, and hand Blender the
        # native provider address.
        lib.sc_external_draw_register.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        lib.sc_external_draw_register.restype = None
        lib.sc_external_draw_register_grids.argtypes = [ctypes.c_uint, ctypes.c_void_p,
                                                        ctypes.c_int]
        lib.sc_external_draw_register_grids.restype = None
        lib.sc_external_draw_unregister.argtypes = [ctypes.c_uint]
        lib.sc_external_draw_unregister.restype = None
        lib.sc_external_draw_update.argtypes = [ctypes.c_uint]
        lib.sc_external_draw_update.restype = None
        lib.sc_external_draw_enable_dynamic.argtypes = [ctypes.c_void_p]
        lib.sc_external_draw_enable_dynamic.restype = None
        # The face `group` id the fset overlay stream leaves untinted, i.e.
        # Blender's Mesh.face_sets_color_default (usually 1) — the engine's own
        # notion of "no group" is 0.
        lib.sc_external_draw_set_default_group.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.sc_external_draw_set_default_group.restype = None
        lib.sc_external_draw_provider.argtypes = []
        lib.sc_external_draw_provider.restype = ctypes.c_void_p

        # Grids-native stroke session (multires W1): the per-level session
        # the stroke path drives instead of filterNodes + execBrush when the
        # tool is grids-capable — no materialized-mesh hot path, block undo.
        lib.GridStroke_new.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.GridStroke_new.restype = ctypes.c_void_p
        lib.GridStroke_free.argtypes = [ctypes.c_void_p]
        lib.GridStroke_free.restype = None
        lib.GridStroke_supported.argtypes = [ctypes.c_int]
        lib.GridStroke_supported.restype = ctypes.c_int
        lib.GridStroke_setMirror.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.GridStroke_setMirror.restype = None
        lib.GridStroke_setNonAccum.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.GridStroke_setNonAccum.restype = None
        lib.GridStroke_setAnchoredGrab.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.GridStroke_setAnchoredGrab.restype = None
        lib.GridStroke_sync.argtypes = [ctypes.c_void_p]
        lib.GridStroke_sync.restype = ctypes.c_int
        lib.GridStroke_syncMask.argtypes = [ctypes.c_void_p]
        lib.GridStroke_syncMask.restype = None
        lib.GridStroke_setDeferNormals.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.GridStroke_setDeferNormals.restype = None
        lib.GridStroke_flushNormals.argtypes = [ctypes.c_void_p]
        lib.GridStroke_flushNormals.restype = None
        lib.GridStroke_begin.argtypes = [ctypes.c_void_p]
        lib.GridStroke_begin.restype = ctypes.c_int
        lib.GridStroke_dab.argtypes = (
            [ctypes.c_void_p, ctypes.c_int] + [ctypes.c_float] * 6 + [ctypes.c_int])
        lib.GridStroke_dab.restype = ctypes.c_int
        lib.GridStroke_end.argtypes = [ctypes.c_void_p]
        lib.GridStroke_end.restype = None
        lib.GridStroke_canUndo.argtypes = [ctypes.c_void_p]
        lib.GridStroke_canUndo.restype = ctypes.c_int
        lib.GridStroke_canRedo.argtypes = [ctypes.c_void_p]
        lib.GridStroke_canRedo.restype = ctypes.c_int
        lib.GridStroke_undo.argtypes = [ctypes.c_void_p]
        lib.GridStroke_undo.restype = ctypes.c_int
        lib.GridStroke_redo.argtypes = [ctypes.c_void_p]
        lib.GridStroke_redo.restype = ctypes.c_int
        lib.GridStroke_dropOldest.argtypes = [ctypes.c_void_p]
        lib.GridStroke_dropOldest.restype = ctypes.c_int
        lib.GridStroke_undoBytes.argtypes = [ctypes.c_void_p]
        lib.GridStroke_undoBytes.restype = ctypes.c_double
        lib.Multires_hasGridDomain.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_hasGridDomain.restype = ctypes.c_int
        lib.Multires_setActiveLevelLazy.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_setActiveLevelLazy.restype = ctypes.c_int
        lib.Multires_levelVertCount.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.Multires_levelVertCount.restype = ctypes.c_int
        lib.Multires_readDomainMask.argtypes = [ctypes.c_void_p, ctypes.c_int, f32p,
                                                ctypes.c_int]
        lib.Multires_readDomainMask.restype = ctypes.c_int
        lib.Multires_writeDomainMask.argtypes = [ctypes.c_void_p, ctypes.c_int, f32p,
                                                 ctypes.c_int]
        lib.Multires_writeDomainMask.restype = ctypes.c_int
        lib.GridTree_castRay.argtypes = (
            [ctypes.c_void_p, ctypes.c_int] + [ctypes.c_float] * 6
            + [f32p, ctypes.POINTER(ctypes.c_int)])
        lib.GridTree_castRay.restype = ctypes.c_int

        self.lib = lib


def capi():
    global _capi
    if _capi is None:
        _capi = _CApi(manager().capi.lib)
    return _capi


def free_all_sessions():
    """Drop every live session (addon unregister; the C side has already
    force-exited the objects and flushed via exit())."""
    for session in list(sessions.values()):
        session.free()
    sessions.clear()
