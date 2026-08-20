# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sculpt layers (LD3): the addon face of the engine's sculpt-layer stack.

A layer is an extra displacement channel the LAYERDRAW kernel writes into;
the composited surface is base + sum(weight_i * layer_i), so a stroke can
be re-weighted or switched off after the fact. On multires the stack lives
in the grid store (one channel per layer, settings rows on the cage); on a
plain mesh it is a "slayer" vertex attribute plus a mesh-side settings row.

This module owns:

- create-on-first-use for the Layer brush (``ensure_stroke_target``) -- the
  grids roster reports LAYERDRAW capable only under a live edit target, so
  the target must exist before the stroke operator's capability queries;
- the multires mutation discipline: every engine layer mutator folds
  pending active-level edits and rematerializes slots, so each call here is
  bracketed snapshot -> mutate -> ``convert._rebind_multires_views``;
- the MR_LAYERS undo payload (layer table + edit target + store blob;
  pushed through ``undo.push_layers``, decoded by ``restore_state``); and
- the layer panel's backing state: a WindowManager collection mirror whose
  weight property reads and writes the engine live, plus the add / remove /
  set-target / toggle-enabled / sync operators.

Weight drags are deliberately not undo steps: store blobs never carry the
settings rows, positions re-derive from weight * channel, and a per-tick
step would flood the stack. Structural ops (add/remove/target/enable) each
push one MR_LAYERS step.
"""

import bpy

from . import convert, engine


def _lib():
    return engine.capi().lib


def layer_count(session):
    if session is None or not session.multires_ptr:
        return 0
    return int(_lib().Multires_layerCount(session.multires_ptr))


def edit_target(session):
    if session is None or not session.multires_ptr:
        return -1
    return int(_lib().Multires_editTarget(session.multires_ptr))


def _active_session(context):
    """The active object's multires session, or None outside the mode /
    off multires (the layer stack UI is multires-only for now)."""
    ob = context.active_object
    if ob is None or ob.mode != 'CUSTOM' or ob.custom_mode != "sculptcore.sculpt":
        return None
    session = engine.sessions.get(ob.name)
    if session is None or not session.multires_ptr:
        return None
    return session


def capture_state(session):
    """One side of an MR_LAYERS undo step: (layer table bytes, edit target,
    store blob). The table is 3 floats per row {weight, enabled, frozen} in
    row (== store channel) order; the blob carries the channels themselves,
    so the pair reproduces the whole stack (the layer-op undo seam
    multires.h layerRemove names). The blob snapshot folds pending slot
    edits and retro-attaches grid-step blobs first (multires_store_blob)."""
    import numpy as np

    lib = _lib()
    mr = session.multires_ptr
    n = lib.Multires_layerTableOut(mr, np.empty(0, dtype=np.float32), 0)
    table = np.zeros(n if n > 0 else 1, dtype=np.float32)
    if n > 0:
        lib.Multires_layerTableOut(mr, table, n)
    return (table[:n].tobytes(), int(lib.Multires_editTarget(mr)),
            convert.multires_store_blob(session))


def restore_state(ob, session, state, level):
    """Decode one side of an MR_LAYERS step. Order matters: the store blob
    first (layerTableRestore sizes the rows from the store's channels), the
    settings-row table second, the edit target last (layerTableRestore
    deliberately clears it). The stale-row window inside the blob restore is
    safe: composition resolves rows to channels by name and skips misses.
    Each engine call rematerializes slots; one final rebind refreshes every
    addon-held view."""
    import numpy as np

    table, target, blob = state
    if not session.multires_ptr or blob is None:
        return
    # The blob restore is a boundary that kills the live grid history; give
    # its blob-less steps their snapshots first so the dead-history fallback
    # stays exact (same rule as undo._decode_grid's own fallback).
    from . import undo
    undo.materialize_grid_blobs(session)
    if not convert.multires_restore_blob(ob, session, blob, level):
        return
    lib = _lib()
    t = np.ascontiguousarray(np.frombuffer(table, dtype=np.float32))
    lib.Multires_layerTableRestore(session.multires_ptr, t, len(t))
    lib.Multires_setEditTarget(session.multires_ptr, target)
    convert._rebind_multires_views(session, session.multires_active_level)
    # Neither the table nor the target lives in the store, so the blob the
    # restore rooted at multires_last_blob still names the current state.
    _sync_mirror(bpy.context, session)


def _add_and_target(lib, mr):
    li = lib.Multires_layerAdd(mr)
    if li >= 0:
        lib.Multires_setEditTarget(mr, li)


def _structural(context, ob, session, message, fn):
    """Run one undoable layer-stack mutation. The pre-snapshot folds pending
    slot mask edits first (the mutator's own writeback folds positions, not
    the mask column -- the set_multires_level discipline), and
    multires_store_blob inside capture_state retro-attaches grid-step blobs
    before the mutation orphans the grid log (GridStroke_sync catches the
    orphaning at the next grid-step decode and falls back to those blobs)."""
    from . import undo

    convert.fold_slot_mask(session)
    before = capture_state(session)
    fn(_lib(), session.multires_ptr)
    convert._rebind_multires_views(session, session.multires_active_level)
    after = capture_state(session)
    if before[2] is not None and after[2] is not None:
        # The mutation's fold changed the store: re-root the next stroke's
        # pre-state at the post-mutation snapshot (the level-switch rule).
        session.multires_last_blob = after[2]
        undo.push_layers(context, ob, session, message, before, after)
    _sync_mirror(context, session)
    undo._tag_view3d_redraw(context)


def ensure_stroke_target(context, ob, session):
    """Create-on-first-use for the Layer brush: give the LAYERDRAW kernel
    somewhere to land before the stroke operator's capability queries. On
    multires that is a live edit target (the grids roster flips on it); with
    no target a fresh layer is created and targeted -- strokes never
    silently re-target an existing layer, whose weight the user may have
    set. On a plain mesh the first "slayer" settings row is enough (the mesh
    executor's LayerEditScope is inert without one, and the row's attr is
    the kernel's by-name binding); a fresh zero layer at weight 1 changes
    nothing, so only the multires target creation pushes an undo step."""
    lib = _lib()
    if session.multires_ptr:
        if lib.Multires_editTarget(session.multires_ptr) < 0:
            _structural(context, ob, session, "Add Sculpt Layer", _add_and_target)
        # Preview strokes take the mesh path through the materialized slot,
        # whose own LayerEditScope also needs a settings row. A lazy slot
        # gets one when convert.ensure_multires_slot materializes it (the
        # edit target is live by now); this covers the slot that was already
        # resident when the target appeared. A zero scratch row at weight 1
        # composites nothing; stroke-end attribution to the store channel
        # follows the mr edit target.
        if session.mesh_ptr and lib.Mesh_sculptLayerCount(session.mesh_ptr) == 0:
            lib.Mesh_sculptLayerAdd(session.mesh_ptr)
    elif session.mesh_ptr and lib.Mesh_sculptLayerCount(session.mesh_ptr) == 0:
        lib.Mesh_sculptLayerAdd(session.mesh_ptr)


def _sync_mirror(context, session):
    """Match the WindowManager mirror's length to the engine stack (draw
    callbacks cannot resize a collection, so every mutation site does)."""
    coll = context.window_manager.sculptcore_layers
    n = layer_count(session)
    while len(coll) > n:
        coll.remove(len(coll) - 1)
    while len(coll) < n:
        coll.add()
    for i, item in enumerate(coll):
        item.index = i


def _weight_get(self):
    session = _active_session(bpy.context)
    if session is None or self.index >= layer_count(session):
        return 0.0
    return float(_lib().Multires_layerWeight(session.multires_ptr, self.index))


def _weight_set(self, value):
    session = _active_session(bpy.context)
    if session is None or self.index >= layer_count(session):
        return
    from . import undo

    # The weight mutator folds pending active-level edits (a store no-op
    # between undo-pushed strokes) and rematerializes: attach grid blobs
    # first, rebind after. Deliberately no undo step per drag tick. Setting
    # the edit target's weight clears the target (engine rule); the panel
    # disables that slider, so this only happens through scripts.
    undo.materialize_grid_blobs(session)
    _lib().Multires_layerSetWeight(session.multires_ptr, self.index, float(value))
    convert._rebind_multires_views(session, session.multires_active_level)
    undo._tag_view3d_redraw(bpy.context)


class SculptCoreLayerMirror(bpy.types.PropertyGroup):
    """One panel row: ``index`` names the engine layer; ``weight`` reads and
    writes the engine live (the engine_props get/set pattern), so the value
    is never stored in the .blend and never goes stale."""
    index: bpy.props.IntProperty()
    weight: bpy.props.FloatProperty(
        name="Weight", description="Composite weight of this sculpt layer",
        min=0.0, soft_max=1.0, max=4.0, get=_weight_get, set=_weight_set)


class _LayerOp:
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _active_session(context) is not None


class SCULPTCORE_OT_layer_add(_LayerOp, bpy.types.Operator):
    """Add a sculpt layer and make it the stroke target"""
    bl_idname = "sculptcore.layer_add"
    bl_label = "Add Layer"

    def execute(self, context):
        session = _active_session(context)
        _structural(context, context.active_object, session,
                    "Add Sculpt Layer", _add_and_target)
        return {'FINISHED'}


class SCULPTCORE_OT_layer_remove(_LayerOp, bpy.types.Operator):
    """Delete this sculpt layer and its displacement"""
    bl_idname = "sculptcore.layer_remove"
    bl_label = "Remove Layer"

    index: bpy.props.IntProperty()

    def execute(self, context):
        session = _active_session(context)
        if self.index >= layer_count(session):
            return {'CANCELLED'}
        li = self.index
        _structural(context, context.active_object, session,
                    "Remove Sculpt Layer",
                    lambda lib, mr: lib.Multires_layerRemove(mr, li))
        return {'FINISHED'}


class SCULPTCORE_OT_layer_set_target(_LayerOp, bpy.types.Operator):
    """Make this layer the stroke target (click again to clear); the
    target sculpts at weight 1"""
    bl_idname = "sculptcore.layer_set_target"
    bl_label = "Set Layer Target"

    index: bpy.props.IntProperty()

    def execute(self, context):
        session = _active_session(context)
        if self.index >= layer_count(session):
            return {'CANCELLED'}
        li = -1 if edit_target(session) == self.index else self.index
        _structural(context, context.active_object, session,
                    "Set Layer Target",
                    lambda lib, mr: lib.Multires_setEditTarget(mr, li))
        return {'FINISHED'}


class SCULPTCORE_OT_layer_toggle_enabled(_LayerOp, bpy.types.Operator):
    """Toggle this layer's contribution to the surface"""
    bl_idname = "sculptcore.layer_toggle_enabled"
    bl_label = "Toggle Layer"

    index: bpy.props.IntProperty()

    def execute(self, context):
        session = _active_session(context)
        if self.index >= layer_count(session):
            return {'CANCELLED'}
        li = self.index
        on = 0 if _lib().Multires_layerEnabled(session.multires_ptr, li) else 1
        _structural(context, context.active_object, session,
                    "Toggle Sculpt Layer",
                    lambda lib, mr: lib.Multires_layerSetEnabled(mr, li, on))
        return {'FINISHED'}


class SCULPTCORE_OT_layer_sync(_LayerOp, bpy.types.Operator):
    """Rebuild the layer list from the engine (a stale list heals here)"""
    bl_idname = "sculptcore.layer_sync"
    bl_label = "Sync Layer List"

    def execute(self, context):
        _sync_mirror(context, _active_session(context))
        return {'FINISHED'}


_classes = (
    SculptCoreLayerMirror,
    SCULPTCORE_OT_layer_add,
    SCULPTCORE_OT_layer_remove,
    SCULPTCORE_OT_layer_set_target,
    SCULPTCORE_OT_layer_toggle_enabled,
    SCULPTCORE_OT_layer_sync,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.sculptcore_layers = bpy.props.CollectionProperty(
        type=SculptCoreLayerMirror, options={'SKIP_SAVE'})


def unregister():
    del bpy.types.WindowManager.sculptcore_layers
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
