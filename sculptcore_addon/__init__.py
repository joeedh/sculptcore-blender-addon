# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
SculptCore sculpt mode — a first-class object mode implemented as an addon
on the custom-mode infrastructure (bpy.types.ObjectModeType).

v0 slice: enter/exit with positions-only conversion; the Mesh ID stays
authoritative through the mode's flush callback (memfile undo + save work
unchanged). Stroke operator, draw provider and wrapped undo land on top.
"""

bl_info = {
    "name": "SculptCore Sculpt Mode",
    "author": "Blender Authors",
    "version": (0, 1, 0),
    "blender": (5, 3, 0),
    "location": "3D Viewport > Mode dropdown",
    "description": "Sculpt mode built on the SculptCore engine",
    "category": "Sculpting",
}

import bpy

from . import convert, cursor, engine, engine_props, gestures, handlers, keymap, menus, ops, props, stroke, texture, tools, ui, undo, vanilla_panels


class SculptCoreMode(bpy.types.ObjectModeType):
    bl_idname = "sculptcore.sculpt"
    bl_label = "SculptCore"
    bl_icon = 'SCULPTMODE_HLT'
    bl_object_types = {'MESH'}
    bl_keymap = "SculptCore Mode"
    bl_default_tool = "sculptcore.brush"
    # The brush-asset shelf that polls this mode (ui.py registers it); the
    # header popup selector resolves it via
    # #BrushAssetShelf.get_shelf_name_from_context.
    bl_brush_asset_shelf = "SCULPTCORE_AST_brush_sculpt"
    # Tier-2 delta undo: each stroke pushes a CUSTOM_MODE step wrapping a
    # meshlog step id (see undo.py). The Mesh ID still stays authoritative
    # through flush for save/render; memfile remains the boundary fallback.
    bl_use_custom_undo = True
    # The mode's tools use the shared sculpt brush, so paint-context lookups
    # (brush texture user in the texture properties tab etc.) resolve to it.
    bl_use_sculpt_paint = True

    def enter(self, context, ob):
        _check_draw_provider(self)
        convert.enter(ob)

    def exit(self, context, ob):
        convert.exit_(ob)

    def flush(self, ob):
        convert.flush(ob)

    def refresh(self, context, ob):
        convert.refresh(ob)

    def undo_decode(self, context, ob, state_id, direction, is_final):
        undo.decode(context, ob, state_id, direction, is_final)

    def undo_free(self, state_id):
        undo.free(state_id)

    def draw_cursor(self, context, x, y):
        cursor.draw(context, x, y)


# Decimal address of the provider register() handed the mode, or None when the
# engine was unavailable. Lets enter() detect a silently-rejected registration.
_expected_draw_provider = None
_draw_provider_checked = False


def _check_draw_provider(mode):
    """One-time readback of the registered mode's draw provider (first enter is
    the earliest point a live RNA instance exists to read it through). "0" with
    a provider registered means Blender silently rejected it — the viewport is
    drawing the flush-to-Mesh fallback (for multires: the base cage)."""
    global _draw_provider_checked
    if _draw_provider_checked or _expected_draw_provider is None:
        return
    _draw_provider_checked = True
    if mode.bl_draw_provider == "0":
        print("SculptCore: WARNING: the external draw provider was rejected by this "
              "Blender (bl_draw_provider reads back \"0\") — engine/Blender external-draw "
              "ABI skew? The viewport is showing fallback geometry, not the engine's.")


def register():
    props.register()
    engine_props.register()
    stroke.register()
    ops.register()
    gestures.register()
    # Hand the mode the native external draw provider so custom-mode objects
    # draw their per-node geometry from the engine (P5 D6). Best-effort: if the
    # engine is unavailable the mode still registers and falls back to the
    # flush-to-Mesh draw path.
    try:
        provider = int(engine.capi().lib.sc_external_draw_provider())
        # The provider struct leads with its abi_version; Blender rejects any
        # version other than the one it was built against, *silently* (the RNA
        # string setter cannot report). Compare up front and name both numbers,
        # instead of shipping a viewport that quietly draws fallback geometry.
        import ctypes
        engine_abi = ctypes.cast(ctypes.c_void_p(provider),
                                 ctypes.POINTER(ctypes.c_int)).contents.value
        abi_prop = bpy.types.ObjectModeType.bl_rna.properties.get("bl_draw_provider_abi_version")
        if abi_prop is not None and abi_prop.default != engine_abi:
            print("SculptCore: WARNING: external-draw ABI skew — the engine's provider is "
                  "v{:d} but this Blender expects v{:d}; using the flush-to-Mesh draw path "
                  "(rebuild the older side)".format(engine_abi, abi_prop.default))
        else:
            # An old fork predates the version property; register anyway and let
            # the enter()-time readback catch a rejection.
            SculptCoreMode.bl_draw_provider = str(provider)
            global _expected_draw_provider
            _expected_draw_provider = provider
    except Exception as ex:
        print("SculptCore: external draw provider unavailable ({!r}); "
              "using the flush-to-Mesh draw path".format(ex))
    bpy.utils.register_class(SculptCoreMode)
    keymap.register()
    tools.register()
    # The vanilla brush-panel subclasses first: ui.py parents its engine
    # panel under SCULPTCORE_PT_tools_brush_settings.
    vanilla_panels.register()
    ui.register()
    menus.register()
    handlers.register()


def unregister():
    # Unregistering the mode type force-exits every object still in the
    # mode (exit -> flush -> free) before the class goes away; this only
    # catches sessions those exits left behind.
    handlers.unregister()
    menus.unregister()
    ui.unregister()
    vanilla_panels.unregister()
    tools.unregister()
    keymap.unregister()
    bpy.utils.unregister_class(SculptCoreMode)
    gestures.unregister()
    ops.unregister()
    stroke.unregister()
    engine_props.unregister()
    props.unregister()
    # Python-backed host samplers hold ctypes trampolines the engine calls;
    # drop them before this module (and its keep-alive dict) goes away.
    texture.clear_samplers()
    engine.free_all_sessions()
    undo.reset()
