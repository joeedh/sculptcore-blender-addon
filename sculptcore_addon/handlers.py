# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Session lifecycle handlers.

Tier-1 undo is memfile-based, so an undo/redo step can move an object out of
the mode without going through the exit callback — e.g. undoing across the
mode-enter boundary drops the object back to Object mode. The engine session
then dangles (its C++ mesh/tree leak, and a later re-enter would overwrite
it). ``undo_post``/``redo_post`` reconcile the session registry against the
objects' actual modes; ``load_post`` drops every session (the engine meshes
were built from the previous file's data, now replaced).

The full custom undo type (undo-integration plan) makes stroke undo exact;
this keeps Tier-1 leak-free and consistent in the meantime.

``depsgraph_update_post`` additionally follows the multires modifier's
``sculpt_levels`` so a change in the modifier UI switches the session's
active engine level (P8 C2), and ``save_pre``/``save_post`` keep the
mode-local multires suppression out of the written file.
"""

import bpy
from bpy.app.handlers import persistent

from . import engine, multires


def _tag_view3d_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# Both level-sync paths re-evaluate the depsgraph, which fires this handler
# again; the nested pass would act on half-updated session bookkeeping.
_syncing_multires = False


def _sync_multires_levels():
    """Follow the multires modifier's levels: its *count* (C5 — the user clicked
    Subdivide or Delete Higher, so the engine stack gains or drops a level) and
    then its sculpt level (C2 — a ``sculpt_levels`` move switches the session's
    active engine level). Cheap when nothing changed (a dict scan and two int
    compares)."""
    from . import convert

    global _syncing_multires
    if _syncing_multires:
        return
    _syncing_multires = True
    try:
        _sync_multires_levels_inner(convert)
    finally:
        _syncing_multires = False


def _sync_multires_levels_inner(convert):
    for name in list(engine.sessions):
        session = engine.sessions[name]
        if not session.multires_ptr:
            continue
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        md = multires.modifier(ob)
        if md is None:
            continue
        if md.total_levels != session.multires_level:
            convert.sync_multires_total_levels(ob)
            _tag_view3d_redraw()
        want = min(max(md.sculpt_levels, 1), session.multires_level)
        if want != session.multires_active_level:
            convert.set_multires_level(ob, want)
            _tag_view3d_redraw()


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    # Deleting an in-mode object (outliner / bpy.data) never runs the exit
    # callback and fires no undo signal until much later, so reconcile here
    # too (cheap: a dict scan) or its engine session leaks.
    _reconcile()
    _sync_multires_levels()
    if depsgraph is not None:
        from . import texture
        texture.invalidate_from_depsgraph(depsgraph)


def _reconcile():
    """Free any session whose object is gone or no longer in the mode."""
    for name in list(engine.sessions):
        ob = bpy.data.objects.get(name)
        in_mode = (
            ob is not None
            and ob.mode == 'CUSTOM'
            and ob.custom_mode == "sculptcore.sculpt"
        )
        if not in_mode:
            engine.sessions.pop(name).free()


def _resync_foreign_states():
    """Rebuild any session whose object came back carrying data the engine no
    longer mirrors.

    Custom-undo modes own their data while active: memfile steps pushed
    in-mode hold a Mesh the engine has already run past (strokes do not write
    back), so an undo that restores one must leave the live state alone —
    which is why ed_undo.cc skips the generic ``refresh`` for this mode. The
    exception is a step written right after an operator edited the data
    underneath the mode (the multires ops, which the fork brackets with
    flush + refresh): there the data *is* the engine's own, and returning to
    that step — a redo past the operator — means rebuilding from it, since no
    engine-side step describes the state. ``Object.custom_mode_state`` is the
    marker that tells the two apart; the session records the value it was
    rebuilt at, and every engine change clears both (undo.engine_diverged)."""
    from . import convert

    for name in list(engine.sessions):
        session = engine.sessions[name]
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        state = ob.custom_mode_state
        if state and state != session.data_state:
            convert.refresh(ob, claim_state=False)
            _tag_view3d_redraw()


@persistent
def _on_undo_redo(scene, depsgraph=None):
    _reconcile()
    _resync_foreign_states()


@persistent
def _on_load(*_args):
    # The previous file's engine meshes are orphaned by the load, and the
    # texture bakes belong to the replaced file's datablocks.
    engine.free_all_sessions()
    from . import texture
    texture.invalidate()


def _multires_modifiers_in_session():
    """The multires modifier of every live multires session, with the
    show_viewport value the session promised to restore on exit."""
    for name in list(engine.sessions):
        session = engine.sessions[name]
        if not session.multires_ptr:
            continue
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        md = multires.modifier(ob)
        if md is not None:
            yield md, session.multires_show_viewport


@persistent
def _on_save_pre(*_args):
    """Un-suppress the multires modifiers before the file is written.

    A multires session hides the modifier for the mode's duration (the engine
    surface is drawn by the external provider, and leaving the modifier on
    would re-subdivide on every depsgraph update); the value is restored on
    exit. Saving mid-mode would otherwise bake `show_viewport = False` into the
    file, and since a custom mode never survives a load — object.cc's
    `blend_read_data` clears #OB_MODE_CUSTOM — the object comes back in Object
    mode with its multires modifier off, i.e. showing the bare base cage. The
    displacement is in the file (the fork flushes the mode through
    ED_editors_flush_edits before writing); only the modifier that shows it was
    switched off.

    Not a concern for the position/attribute state itself, and not needed for
    auto-save, which runs the flush but no save callbacks."""
    for md, show in _multires_modifiers_in_session():
        md.show_viewport = show


@persistent
def _on_save_post(*_args):
    # Back to the mode's suppressed state; the save is over either way, so
    # this is registered on the failure callback too.
    for md, _show in _multires_modifiers_in_session():
        md.show_viewport = False


def register():
    bpy.app.handlers.undo_post.append(_on_undo_redo)
    bpy.app.handlers.redo_post.append(_on_undo_redo)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.save_pre.append(_on_save_pre)
    bpy.app.handlers.save_post.append(_on_save_post)
    bpy.app.handlers.save_post_fail.append(_on_save_post)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    for handler_list, fn in (
        (bpy.app.handlers.undo_post, _on_undo_redo),
        (bpy.app.handlers.redo_post, _on_undo_redo),
        (bpy.app.handlers.load_post, _on_load),
        (bpy.app.handlers.save_pre, _on_save_pre),
        (bpy.app.handlers.save_post, _on_save_post),
        (bpy.app.handlers.save_post_fail, _on_save_post),
        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update),
    ):
        if fn in handler_list:
            handler_list.remove(fn)
