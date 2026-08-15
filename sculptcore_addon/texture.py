# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Brush textures (brush-mapping Phase 2).

Bakes a Blender ``Texture`` datablock to the engine's grayscale texture and
binds it per stroke. Procedural textures go through ``Texture.evaluate``
sampled over an N x N grid on ``[-1, 1]^2`` (the engine's Global tile spans
the same world square, wrapped beyond it); image textures are read straight
from ``Image.pixels`` — ``evaluate()`` with interpolation on returns the
whole-image average for images, and its intensity channel is a constant —
reduced to linear-light luminance. Bakes are cached by texture name plus a
fingerprint of the texture's settings (brush textures are not part of the
evaluated depsgraph, so no update handler fires when the user edits them —
the fingerprint is compared at stroke start instead). Settings cannot see
pixel edits, and a brush-only image is not in the depsgraph either, so image
bakes additionally re-read the buffer every stroke start and compare a fast
numpy digest — reload, external edit and in-Blender paint all invalidate
without any notifier. (Single-element ``Image.pixels[i]`` access rebuilds
the whole RNA array per access — only ``foreach_get`` is usable here.)
``texture_slot.map_mode`` selects the engine ``TexCoordSpace``; the
screen-pinned modes (Tiled / Stencil) additionally need the stroke operator
to push the region's perspective matrix (``setRenderMatrix``) so the engine
can perspective-project to viewport UV. Tiled parity: Blender tiles at one
texture per ``2 * start_pixel_radius`` screen pixels, expressed engine-side
as ``tex_repeat`` tiles per viewport height.
"""

import bpy

from . import engine

# Bake resolution: 128^2 = 16k RNA evaluate calls, well under stroke-start
# budget; the engine samples bilinearly so moderate resolution suffices.
BAKE_SIZE = 128

# Blender texture_slot.map_mode -> engine TexCoordSpace value (brush.h).
# Blender's View Plane is brush-centered (the texture follows the brush and
# scales with its radius), which matches the engine's normalized Projected
# space, not its screen-pinned ViewPlane — that one matches Stencil. Random
# is View with a per-dab random offset and angle
# (BKE_brush_sample_tex_3d, brush.cc:1013-1020), so it takes the same
# Projected space; the randomization itself is a per-dab push the C++ dab
# batch cannot carry yet (_MAPPING_NOTES).
_COORD_SPACE = {
    '3D': 0,          # Global
    'VIEW_PLANE': 4,  # Projected (brush-centered tangent plane)
    'AREA_PLANE': 4,  # Projected
    'RANDOM': 4,      # Projected (no per-dab randomization; see below)
    'TILED': 2,       # ViewRepeat (screen-pinned, tiled)
    'STENCIL': 1,     # ViewPlane (screen-pinned)
}

# map_mode -> what the engine mapping still gets wrong, surfaced in the N
# panel (ui.py) so no approximation is silent. Every entry needs engine work,
# not addon work: `texture_slot.angle` and Stencil placement have to reach the
# engine as part of the mapping matrix, and Blender's per-dab state
# (tex_mouse, brush_rotation, brush_local_mat, the random offset) has to ride
# the C++ dab-batch record, which today carries 7 floats per dab and no
# matrix. See claudeMemory/design/blender-brush-textures.md §3 and §6.
_MAPPING_NOTES = {
    'VIEW_PLANE': "Texture angle is not mapped yet",
    'AREA_PLANE': "Texture angle and stroke-aligned placement are not mapped yet",
    'RANDOM': "Per-dab randomization is not mapped yet",
    'TILED': "Texture angle is not mapped yet",
    'STENCIL': "Stencil placement and angle are not mapped yet",
}

# Modes whose note stands whatever the slot is set to; the rest only differ
# from Blender once texture_slot.angle is turned off zero.
_ALWAYS_NOTED = {'AREA_PLANE', 'RANDOM', 'STENCIL'}


def mapping_note(bl_brush):
    """A one-line caveat about how faithfully this brush's texture mapping is
    reproduced, or None when nothing is approximated."""
    slot = bl_brush.texture_slot if bl_brush else None
    if bl_brush is None or bl_brush.texture is None or slot is None:
        return None
    mode = slot.map_mode
    if mode not in _COORD_SPACE:
        return "Texture mapping not supported by the engine"
    angled = (abs(slot.angle) > 1.0e-3 or slot.use_rake or slot.use_random)
    if mode in _ALWAYS_NOTED or angled:
        return _MAPPING_NOTES.get(mode)
    return None

# Image bakes keep the image's own resolution up to this cap per axis (the
# engine samples bilinearly from whatever w x h it is handed).
IMAGE_BAKE_MAX = 512

# Texture name -> (settings fingerprint, image pixel digest or None,
# (width, height, np.float32 pixels)).
_cache = {}

# The coefficients IMB_colormanagement_get_luminance uses — the scene linear
# space's Y row, Rec.709 by default. Everything that collapses an RGB texture
# result to the one intensity a brush consumes has to agree on these: the
# bakes below, the ramp LUT, and magic.stex's own inline collapse.
_LUMA = (0.2126729, 0.7151522, 0.0721750)


def invalidate(name=None):
    """Drop the baked pixels for one texture (or all)."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)


def invalidate_from_depsgraph(depsgraph):
    """Called from the depsgraph handler: drop bakes of updated Textures.
    An Image edit does not report its user Textures, so any Image update
    drops the whole cache (rebakes are cheap and stroke-start only).

    Node trees deliberately get no branch here even though a group NodeTree is
    its own ID naming no user: `_node_tree_fingerprint` already sees every
    graph edit, and `_purge_node_execdata` below tags the tree on every bake —
    so clearing on a NodeTree update would invalidate the bake this addon just
    made, and rebake on every stroke forever."""
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Image):
            _cache.clear()
            return
        if isinstance(update.id, bpy.types.Texture):
            _cache.pop(update.id.name, None)


# Node properties that describe where a node sits rather than what it computes.
# Included, they would rebake on a drag across the node editor.
_NODE_COSMETIC = {"location", "location_absolute", "width", "height",
                  "select", "show_options", "show_preview", "show_texture",
                  "hide", "label", "warning_propagation", "bl_label",
                  "bl_description", "bl_icon", "bl_static_type", "bl_width_default",
                  "bl_width_min", "bl_width_max", "bl_height_default",
                  "bl_height_min", "bl_height_max"}


def _ramp_fingerprint(ramp):
    return tuple((el.position, tuple(el.color)) for el in ramp.elements)


def _node_tree_fingerprint(ntree, seen):
    """Hashable snapshot of a texture node graph: per-node type and settings,
    unconnected input defaults, embedded ramps and curves, and the link
    topology. `_fingerprint` alone cannot see any of it — `node_tree` is a
    POINTER, and the RNA walk it does covers scalars only — so a graph edit
    would otherwise leave the bake stale for the rest of the session."""
    key = ntree.as_pointer()
    if key in seen:
        return ('cycle', key)
    seen.add(key)
    nodes = []
    for node in ntree.nodes:
        entry = [node.name, node.bl_idname, node.mute]
        for prop in node.bl_rna.properties:
            if (prop.identifier in _NODE_COSMETIC or prop.is_readonly
                    or prop.type not in {'BOOLEAN', 'INT', 'FLOAT', 'ENUM', 'STRING'}):
                continue
            v = getattr(node, prop.identifier)
            entry.append((prop.identifier,
                          tuple(v) if getattr(prop, "is_array", False) else v))
        for sock in node.inputs:
            # Only unlinked sockets feed a value; a linked one's stale default
            # would churn the fingerprint without changing the result.
            v = None if sock.is_linked else getattr(sock, "default_value", None)
            if v is not None and hasattr(v, "__len__") and not isinstance(v, str):
                v = tuple(v)
            entry.append((sock.identifier, v))
        ramp = getattr(node, "color_ramp", None)
        if ramp is not None:
            entry.append(_ramp_fingerprint(ramp))
        curves = getattr(getattr(node, "mapping", None), "curves", None)
        if curves is not None:
            entry.append(tuple(tuple((pt.location[0], pt.location[1], pt.handle_type)
                                     for pt in curve.points) for curve in curves))
        sub = getattr(node, "node_tree", None)
        if sub is not None:
            entry.append(_node_tree_fingerprint(sub, seen))
        sub_tex = getattr(node, "texture", None)
        if sub_tex is not None:
            entry.append(_fingerprint(sub_tex, seen))
        nodes.append(tuple(entry))
    links = tuple((link.from_node.name, link.from_socket.identifier,
                   link.to_node.name, link.to_socket.identifier, link.is_muted)
                  for link in ntree.links)
    return (tuple(nodes), links)


def _fingerprint(tex, seen=None):
    """Hashable snapshot of every scalar/enum setting on the texture (plus
    its color ramp, image identity and node graph). Brush textures see no
    depsgraph updates, so cache validity is decided by comparing this at stroke
    start — a type switch, slider drag, image swap or node edit all change it.
    `seen` guards the node-group / Tex-node recursion against a cycle."""
    seen = set() if seen is None else seen
    vals = [tex.type]
    for prop in tex.bl_rna.properties:
        if prop.type not in {'BOOLEAN', 'INT', 'FLOAT', 'ENUM'}:
            continue
        v = getattr(tex, prop.identifier)
        if getattr(prop, "is_array", False):
            v = tuple(v)
        vals.append(v)
    ramp = getattr(tex, "color_ramp", None)
    if getattr(tex, "use_color_ramp", False) and ramp is not None:
        vals.append(_ramp_fingerprint(ramp))
    img = getattr(tex, "image", None)
    if img is not None:
        vals.append((img.name_full, tuple(img.size), img.is_float,
                     img.colorspace_settings.name, img.filepath_raw,
                     img.source, img.has_data, img.is_dirty))
    if getattr(tex, "use_nodes", False) and tex.node_tree is not None:
        vals.append(_node_tree_fingerprint(tex.node_tree, seen))
    return tuple(vals)


def _bake(tex):
    """Grayscale bake of `tex`: ``(width, height, np.float32 pixels)``, or
    None for an image texture with no loadable pixels. Procedurals are
    cached per texture name until the settings fingerprint changes; image
    textures also re-read their pixel buffer and rebake when its digest
    moved (settings can't see a reload or a paint stroke)."""
    fp = _fingerprint(tex)
    entry = _cache.get(tex.name)
    if tex.type == 'IMAGE':
        buf, w, h = _image_pixels(tex)
        if buf is None:
            _cache.pop(tex.name, None)
            return None
        digest = _digest(buf)
        if entry is not None and entry[0] == fp and entry[1] == digest:
            return entry[2]
        baked = _bake_image(tex.image, buf, w, h)
        _cache[tex.name] = (fp, digest, baked)
        return baked
    if entry is not None and entry[0] == fp:
        return entry[2]
    baked = _bake_procedural(tex)
    _cache[tex.name] = (fp, None, baked)
    return baked


def _returns_rgb(tex):
    """Whether ``multitex`` reports TEX_RGB for `tex`, i.e. whether the brush
    path (``RE_texture_evaluate``, texture_procedural.cc:1096-1098) discards
    the per-type ``tin`` and takes ``luminance(trgba)`` instead. Everything
    else writes only ``tin``, which ``Texture.evaluate()`` hands back in slot
    3 while ``trgba`` stays zero — so reading ``[0]`` for these gives a flat
    black bake.

    The RGB set (`multitex`, texture_procedural.cc:700-800): a color band on
    any type; Magic (always, :360); Clouds with ``cloud_type == 'COLOR'``
    (:129-147); Voronoi with any non-Intensity coloring (:507-548); and every
    node-tree texture, since ``ntreeTexExecTree`` ends with an unconditional
    ``retval |= TEX_RGB`` (node_texture_tree.cc:351) — the Output node's own
    ``tin = (r+g+b)/3`` is computed and then thrown away by the luminance
    collapse."""
    if getattr(tex, "use_color_ramp", False):
        return True
    if tex.use_nodes and tex.node_tree is not None:
        return True
    if tex.type == 'MAGIC':
        return True
    if tex.type == 'CLOUDS':
        return tex.cloud_type == 'COLOR'
    if tex.type == 'VORONOI':
        return tex.color_mode != 'INTENSITY'
    return False


def _purge_node_execdata(tex):
    """Force Blender to rebuild a node-tree texture's execution graph.

    `Texture.evaluate()` on a `use_nodes` texture runs `ntreeTexExecTree`,
    which lazily builds `ntree->runtime->execdata` on first use and then
    *keeps it forever* (node_texture_tree.cc:337-345 — "XXX hack: prevent exec
    data from being generated twice"). Link edits, socket defaults and added
    nodes never reach it, so every later evaluate replays the graph as it stood
    the first time it was sampled. The interactive paint paths dodge this by
    bracketing their own `ntreeTexBeginExecTree`/`EndExecTree` per stroke
    (sculpt.cc:5242/6134, paint_cursor.cc:319/338); `evaluate()` has no such
    bracket, and nothing in RNA exposes one.

    Node *removal* does free it (node.cc:5074-5078, "texture node has bad habit
    of keeping exec data around"), which is the only lever Python has: add a
    throwaway node and take it straight back out. The tree ends up structurally
    identical, so the bake's fingerprint is unchanged."""
    ntree = tex.node_tree if getattr(tex, "use_nodes", False) else None
    if ntree is None:
        return
    try:
        ntree.nodes.remove(ntree.nodes.new('TextureNodeCoordinates'))
    except (RuntimeError, TypeError):
        # A node type that no longer exists costs a stale bake, not a failed
        # stroke; the un-purged graph still evaluates.
        pass


def _bake_procedural(tex):
    """Evaluate() bake over [-1, 1]^2 (z = 0). For grayscale sources the
    intensity channel (`tin`, evaluate()[3]) matches Blender's own brush
    sampling; color-ramped and inherently-RGB procedurals use linear-light
    luminance of the color instead (tin stays the pre-ramp intensity)."""
    import numpy as np

    _purge_node_execdata(tex)
    n = BAKE_SIZE
    evaluate = tex.evaluate
    use_rgb = _returns_rgb(tex)
    pixels = np.empty(n * n, dtype=np.float32)
    inv = 2.0 / (n - 1)
    idx = 0
    for j in range(n):
        y = j * inv - 1.0
        for i in range(n):
            v = evaluate((i * inv - 1.0, y, 0.0))
            if use_rgb:
                pixels[idx] = _LUMA[0] * v[0] + _LUMA[1] * v[1] + _LUMA[2] * v[2]
            else:
                pixels[idx] = v[3]
            idx += 1
    return (n, n, pixels)


def _image_pixels(tex):
    """The image's full float RGBA buffer as ``(np.float32 array, w, h)``,
    or ``(None, 0, 0)`` when there are no pixels to read. A file image whose
    load failed (missing file, or a ``//`` path in a not-yet-saved .blend)
    keeps ``has_data`` False and Blender will not retry by itself; there is
    no buffer to lose in that state, so force a reload attempt — the path
    may have become resolvable since (e.g. the file was saved)."""
    import numpy as np

    img = tex.image
    if img is None:
        return None, 0, 0
    if (not img.has_data and img.filepath
            and img.source in {'FILE', 'SEQUENCE', 'MOVIE', 'TILED'}):
        try:
            img.reload()
        except RuntimeError:
            pass
    w, h = img.size
    if w <= 0 or h <= 0 or len(img.pixels) < w * h * 4:
        return None, 0, 0
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf, w, h


def _digest(buf):
    """Order-sensitive sample of the raw pixel buffer (bit view, strided by
    a prime): cheap enough for every stroke start, dense enough that any
    visible edit lands on samples."""
    import numpy as np

    bits = buf.view(np.int32)[::97]
    return (buf.size, int(bits.sum(dtype=np.int64)),
            int(np.bitwise_xor.reduce(bits)) if bits.size else 0)


def _bake_image(img, buf, w, h):
    """Direct-pixel bake of an image texture: linear-light luminance of the
    buffer, downsampled by striding past IMAGE_BAKE_MAX. ``Image.pixels``
    row 0 is the bottom row, matching engine v=0, so no flip. Byte buffers
    arrive display-encoded and are linearized for parity with what
    ``RE_texture_evaluate`` feeds native brushes; float buffers are already
    linear."""
    import numpy as np

    rgb = buf.reshape(h, w, 4)[:, :, :3]
    if not img.is_float and img.colorspace_settings.name == 'sRGB':
        rgb = np.where(rgb <= 0.04045, rgb / 12.92,
                       ((rgb + 0.055) / 1.055) ** 2.4)
    lum = rgb @ np.array(_LUMA, dtype=np.float32)
    if w > IMAGE_BAKE_MAX or h > IMAGE_BAKE_MAX:
        ys = np.linspace(0, h - 1, min(h, IMAGE_BAKE_MAX)).round().astype(int)
        xs = np.linspace(0, w - 1, min(w, IMAGE_BAKE_MAX)).round().astype(int)
        lum = lum[np.ix_(ys, xs)]
        h, w = lum.shape
    return (w, h, np.ascontiguousarray(lum, dtype=np.float32).ravel())


# --------------------------------------------------------------------------
# Script routing: procedural types with a .stex implementation evaluate at
# the true sculpt-space 3D point on the engine (runtime CPU JIT; the source
# is GPU-spliceable too) instead of tiling a 2D [-1, 1]^2 bake. Routed only
# for map_mode '3D' - the screen-pinned/projected modes are 2D by nature,
# where the bake is already exact.

# tex.type -> .stex file under sculptcore_addon/stex/. Every type that *has* a
# script is here, so the parity harness can bind and grade one.
_SCRIPT_FILES = {
    'CLOUDS': "clouds.stex",
    'BLEND': "blend.stex",
    'MAGIC': "magic.stex",
    'WOOD': "wood.stex",
    'MARBLE': "marble.stex",
    'STUCCI': "stucci.stex",
}

# The subset apply_texture actually routes. A type enters this set only once
# its parity case is green (plans/blender-texture-system-port.md 1.5) - the
# harness grades a script by binding it directly, not through here.
_SCRIPT_TYPES = frozenset({'CLOUDS', 'BLEND', 'MAGIC', 'WOOD', 'MARBLE', 'STUCCI'})

_script_sources = {}
_script_warned = set()


def _script_source(tex_type):
    src = _script_sources.get(tex_type)
    if src is None and tex_type in _SCRIPT_FILES:
        import os
        path = os.path.join(os.path.dirname(__file__), "stex",
                            _SCRIPT_FILES[tex_type])
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        _script_sources[tex_type] = src
    return src


def _script_supports(tex):
    """Whether the type's .stex covers *this* texture's settings. A script
    that silently ignores a setting is worse than the bake, so anything it
    cannot express falls back (the bake evaluates the real thing, just tiled).

    Today: Clouds in Color mode returns RGB from three turbulence fields with
    swizzled coordinates (texture_procedural.cc:129-147) folded through
    BRICONTRGB (rfac/gfac/bfac, a lower-only clamp, an HSV saturation
    round-trip) and then luminance — three inline turbulence loops, since a
    texture block admits exactly one `eval` and no helper functions
    (parser.cc:536-560). Not worth 3x the per-dab cost until it is asked
    for."""
    if tex.type == 'CLOUDS':
        return tex.cloud_type != 'COLOR'
    return True


# Texture.progression -> the DNA stype the .stex switches on
# (DNA_texture_types.h:188-194).
_BLEND_STYPE = {'LINEAR': 0.0, 'QUADRATIC': 1.0, 'EASING': 2.0, 'DIAGONAL': 3.0,
                'SPHERICAL': 4.0, 'QUADRATIC_SPHERE': 5.0, 'RADIAL': 6.0}


def _params_clouds(tex):
    return {
        "scale": _noise_scale(tex),
        "depth": float(tex.noise_depth),
        "hard": 0.0 if tex.noise_type == 'SOFT_NOISE' else 1.0,
    }


def _params_blend(tex):
    return {
        "stype": _BLEND_STYPE[tex.progression],
        "flip": 1.0 if tex.use_flip_axis == 'VERTICAL' else 0.0,
    }


def _params_magic(tex):
    return {
        "depth": float(tex.noise_depth),
        # magic() divides the raw turbulence by 5 up front
        # (texture_procedural.cc:296).
        "turb": tex.turbulence / 5.0,
        # BRICONTRGB's per-channel factors and HSV saturation, which only a
        # TEX_RGB type reaches.
        "rfac": tex.factor_red,
        "gfac": tex.factor_green,
        "bfac": tex.factor_blue,
        "sat": tex.saturation,
    }


# Texture.wood_type / marble_type / stucci_type -> the DNA stype the .stex
# switches on (DNA_texture_types.h:167-170, :181-183, :199-201). The waveform
# enum (noise_basis_2) is shared by Wood and Marble (:160-162).
_WOOD_STYPE = {'BANDS': 0.0, 'RINGS': 1.0, 'BANDNOISE': 2.0, 'RINGNOISE': 3.0}
_MARBLE_STYPE = {'SOFT': 0.0, 'SHARP': 1.0, 'SHARPER': 2.0}
_STUCCI_STYPE = {'PLASTIC': 0.0, 'WALL_IN': 1.0, 'WALL_OUT': 2.0}
_WAVEFORM = {'SIN': 0.0, 'SAW': 1.0, 'TRI': 2.0}


def _noise_scale(tex):
    """`1 / noisesize`, matching BLI_noise_generic_noise's own guard: it skips
    the divide entirely at zero rather than dividing by it
    (noise_c.cc:1198)."""
    ns = tex.noise_scale
    return 1.0 / ns if ns > 1.0e-6 else 1.0


def _params_wood(tex):
    return {
        "stype": _WOOD_STYPE[tex.wood_type],
        "wf": _WAVEFORM[tex.noise_basis_2],
        "scale": _noise_scale(tex),
        "turb": tex.turbulence,
        "hard": 0.0 if tex.noise_type == 'SOFT_NOISE' else 1.0,
    }


def _params_marble(tex):
    return {
        "stype": _MARBLE_STYPE[tex.marble_type],
        "wf": _WAVEFORM[tex.noise_basis_2],
        "scale": _noise_scale(tex),
        "depth": float(tex.noise_depth),
        "turb": tex.turbulence,
        "hard": 0.0 if tex.noise_type == 'SOFT_NOISE' else 1.0,
    }


def _params_stucci(tex):
    return {
        "stype": _STUCCI_STYPE[tex.stucci_type],
        "scale": _noise_scale(tex),
        "turb": tex.turbulence,
        "hard": 0.0 if tex.noise_type == 'SOFT_NOISE' else 1.0,
    }


# tex.type -> the params only that type's .stex declares.
_TYPE_PARAMS = {
    'CLOUDS': _params_clouds,
    'BLEND': _params_blend,
    'MAGIC': _params_magic,
    'WOOD': _params_wood,
    'MARBLE': _params_marble,
    'STUCCI': _params_stucci,
}


def _script_params(tex, bl_brush):
    """The .stex param values for `tex` (names must match the script's
    `param` decls). Scalar params update through the live slab - no
    recompile on a slider drag.

    `bl_brush` may be None, which means identity placement: the slot's
    scale/offset live on the brush, not the texture, so a caller sampling a
    texture outside any brush has none to apply."""
    slot = bl_brush.texture_slot if bl_brush is not None else None
    params = {
        "bright": tex.intensity,
        "contrast": tex.contrast,
        # BRICONT clamps only when TEX_NO_CLAMP is clear; use_clamp is that
        # flag negated (rna_texture.cc:1513-1514), and the flag is set by
        # default, so this is 1.0 on a fresh texture.
        "no_clamp": 0.0 if tex.use_clamp else 1.0,
        "use_ramp": 1.0 if tex.use_color_ramp else 0.0,
        "sx": slot.scale[0] if slot else 1.0,
        "sy": slot.scale[1] if slot else 1.0,
        "sz": slot.scale[2] if slot else 1.0,
        "ox": slot.offset[0] if slot else 0.0,
        "oy": slot.offset[1] if slot else 0.0,
        "oz": slot.offset[2] if slot else 0.0,
    }
    params.update(_TYPE_PARAMS[tex.type](tex))
    return params


def _ramp_lut(tex):
    """The color ramp as 256 linear-light luminance samples (the engine ramp
    param is scalar; brush sampling only consumes intensity)."""
    import numpy as np

    evaluate = tex.color_ramp.evaluate
    lut = np.empty(256, dtype=np.float32)
    for i in range(256):
        c = evaluate(i / 255.0)
        lut[i] = _LUMA[0] * c[0] + _LUMA[1] * c[1] + _LUMA[2] * c[2]
    return lut


def _compile_script(tex_type, src, sc_brush):
    """Compile `src` onto `sc_brush` and return its param-name -> index map,
    or None on failure (reported to the console once per type)."""
    import sculptcore
    from sculptcore import _descriptors

    mgr = engine.manager()
    data = src.encode("utf-8")
    # setTextureScript takes Vector<char>; plain char registers as "int8"
    # in the reflection registry (source is ASCII, so sign is moot).
    with sculptcore.construct_from_items(mgr, mgr.get("int8"), data) as vec:
        ok = sc_brush.setTextureScript(vec)
    if not ok:
        if tex_type not in _script_warned:
            _script_warned.add(tex_type)
            err = _descriptors.read_litestl_string(sc_brush.texture_script_error.ptr)
            print("sculptcore: texture script for {:s} failed: {:s}".format(tex_type, err))
        return None
    idx = {}
    for i in range(sc_brush.textureParamCount()):
        # `name` marshals as a bound util::string view, not a Python str.
        entry = sc_brush.queriedTextureParamEntry(i)
        idx[_descriptors.read_litestl_string(entry.name.ptr)] = i
    return idx


def _push_script_params(tex, bl_brush, sc_brush, idx):
    """Write this texture's settings into the live param slab. Cheap enough
    to repeat per stroke — no recompile, just float writes."""
    import sculptcore

    params = _script_params(tex, bl_brush)
    # Driven from what the *script* declares, not from what the dict holds: a
    # type whose epilogue Blender does not run (Stucci has no BRICONT) simply
    # omits those params, and the extras go unused. The lookup still raises on
    # a param the script declares and nothing supplies — that one would keep
    # its .stex default and read as a setting the port silently ignores.
    for name, i in idx.items():
        if name == "shape":
            continue  # the ramp, uploaded below rather than as a float
        sc_brush.setTextureParamAt(i, float(params[name]))
    if tex.use_color_ramp and tex.color_ramp is not None:
        lut = _ramp_lut(tex)
        mgr = engine.manager()
        with sculptcore.construct_from_items(mgr, mgr.get("float"), ()) as vec:
            vec.resize(lut.size)
            vec.numpy()[:] = lut
            sc_brush.setTextureRampAt(idx["shape"], vec)


def bind_script(tex, sc_brush, bl_brush=None):
    """Compile `tex`'s .stex onto `sc_brush` and push its settings, with no
    stroke or session involved — the entry the parity harness uses. Returns
    the param-name -> index map, or None when the type has no script, the
    script cannot express these settings, or compilation failed."""
    if not _script_supports(tex):
        return None
    src = _script_source(tex.type)
    if src is None:
        return None
    idx = _compile_script(tex.type, src, sc_brush)
    if idx is None:
        return None
    _push_script_params(tex, bl_brush, sc_brush, idx)
    return idx


def eval_texture_at(sc_brush, p, n=(0.0, 0.0, 1.0)):
    """Sample the brush's bound texture program at one point. Returns 0.0 with
    nothing bound. The map context is null, so a program reading mapPoint()
    (sc_brush.textureUsesMap()) sees identity — such a program has to be
    driven through a stroke, which is where the real render matrix arrives."""
    return sc_brush.evalTextureAt(p[0], p[1], p[2], n[0], n[1], n[2])


def _apply_script(bl_brush, tex, sc_brush, session):
    """Bind `tex` as a runtime texture program on the session's brush.
    Compiles once per session per texture type (the source is static;
    settings ride the param slab), then pushes params + ramp per stroke.
    Returns False - caller falls back to the bake - when the type is not
    routed yet, its script cannot express these settings, or the engine can't
    compile (no CPU JIT)."""
    if tex.type not in _SCRIPT_TYPES or not _script_supports(tex):
        return False
    src = _script_source(tex.type)
    if src is None or session is None:
        return False
    if session.tex_script_type != tex.type:
        idx = _compile_script(tex.type, src, sc_brush)
        if idx is None:
            session.tex_script_type = None
            return False
        session.tex_script_type = tex.type
        session.tex_script_param_index = idx
    _push_script_params(tex, bl_brush, sc_brush, session.tex_script_param_index)
    # A bound program takes precedence over the bitmap; drop the stale bake.
    sc_brush.clearTexture()
    return True


def _scripts_enabled(context):
    """The texture-script kill switch. A ported .stex that compiles and is
    wrong has no other backstop - `_apply_script` falls back to the bake only
    on a *compile* failure - so one scene toggle routes every type back through
    it. Absent a context (or the property, pre-register) scripts stay on."""
    scene = getattr(context, "scene", None) if context is not None else None
    return getattr(scene, "sculptcore_texture_scripts", True)


def _clear_script(sc_brush, session):
    if session is not None and session.tex_script_type is not None:
        sc_brush.clearTextureScript()
        session.tex_script_type = None


def needs_render_matrix(bl_brush):
    """Whether the brush's texture mapping reads ctx.renderMatrix
    (view-pinned UV)."""
    slot = bl_brush.texture_slot if bl_brush else None
    return (bl_brush is not None and bl_brush.texture is not None
            and slot is not None and slot.map_mode in {'TILED', 'STENCIL'})


def apply_texture(bl_brush, sc_brush, context=None, session=None):
    """Bind (or clear) the engine brush texture for a stroke. Procedurals
    with a .stex implementation route as texture programs when 3D-mapped
    (infinite extent; needs ``session`` for the compile cache); everything
    else takes the bitmap bake. Unmapped map modes (and image textures with
    no pixels) clear so the kernels' sampleBrushTex is a no-op 1.0.
    ``context`` sizes the Tiled repeat; without it Tiled falls back to one
    tile per viewport height."""
    import sculptcore

    tex = bl_brush.texture if bl_brush else None
    slot = bl_brush.texture_slot if bl_brush else None
    coord_space = None
    if tex is not None and slot is not None:
        coord_space = _COORD_SPACE.get(slot.map_mode)
        if (slot.map_mode == '3D' and _scripts_enabled(context)
                and _apply_script(bl_brush, tex, sc_brush, session)):
            return
    _clear_script(sc_brush, session)
    baked = _bake(tex) if tex is not None and coord_space is not None else None
    if baked is None:
        sc_brush.clearTexture()
        return

    width, height, pixels = baked
    mgr = engine.manager()
    # Bulk fill through the vector's zero-copy numpy view: per-item
    # construct_from_items marshalling is ~1.4 s for a 512^2 bake.
    with sculptcore.construct_from_items(mgr, mgr.get("float"), ()) as vec:
        vec.resize(pixels.size)
        vec.numpy()[:] = pixels
        sc_brush.setTexture(width, height, vec)
    sc_brush.coord_space = coord_space
    sc_brush.tex_repeat = _tile_repeat(bl_brush, context)


def _tile_repeat(bl_brush, context):
    """Engine ``tex_repeat`` (tiles per viewport height) for the stroke.
    Blender's Tiled mode samples screen pixels divided by the stroke-start
    pixel radius, with the texture spanning [-1, 1] — one tile per
    ``2 * pixel_radius`` pixels — so repeat = region_height / (2 * radius).
    Non-Tiled modes (and headless/unknown regions) use 1.0."""
    if bl_brush.texture_slot.map_mode != 'TILED' or context is None:
        return 1.0
    region = context.region
    if region is None or region.height <= 0:
        return 1.0
    from . import mapping
    radius = mapping.pixel_radius(context.tool_settings.sculpt, bl_brush)
    if radius <= 0.0:
        return 1.0
    return region.height / (2.0 * radius)


# --------------------------------------------------------------------------
# Host samplers (texture scripts): Python-backed procedural fields callable
# from .stex sources as `sampler float <name>(float3 p[, float3 n]);`.

# name -> (fn thunk, grad thunk or None). The engine stores the raw function
# pointers, so the ctypes CFUNCTYPE objects must stay referenced until the
# sampler is unregistered — dropping them frees the trampolines and the next
# stroke calls freed memory.
_live_samplers = {}


def register_sampler(name, fn, grad=None, wgsl="", fd_step=1.0e-3):
    """Register (or update in place) an engine host sampler backed by Python
    callables. ``fn((px, py, pz), (nx, ny, nz)) -> float`` is required.
    ``grad(p, n) -> (value, gx, gy, gz)`` is optional; without it the engine
    synthesizes central differences with step ``fd_step`` (six extra ``fn``
    taps per gradient). ``wgsl`` optionally supplies the GPU body (it must
    define ``fn hs_<name>(p: vec3f, n: vec3f) -> f32``); left empty the
    sampler is CPU-only and every texture calling it loses its GPU path.

    Updating an existing name swaps what bound programs call without a
    recompile. The callbacks run per evaluated vertex under the GIL — keep
    them trivial; the 128x128 bake (apply_texture) remains the fast path for
    anything expressible as a Blender Texture. Returns True on success."""
    capi = engine.capi()

    fn_thunk = capi.SAMPLER_FN(
        lambda user, p, n: fn((p[0], p[1], p[2]), (n[0], n[1], n[2])))
    grad_thunk = capi.SAMPLER_GRAD_FN(0)
    if grad is not None:
        def _grad(user, p, n, out):
            out[0], out[1], out[2], out[3] = grad(
                (p[0], p[1], p[2]), (n[0], n[1], n[2]))
        grad_thunk = capi.SAMPLER_GRAD_FN(_grad)

    ok = capi.lib.sc_host_sampler_register(
        name.encode("utf-8"), fn_thunk, grad_thunk, None,
        wgsl.encode("utf-8"), fd_step)
    if ok:
        _live_samplers[name] = (fn_thunk, grad_thunk)
    return bool(ok)


def unregister_sampler(name):
    """Clear the named sampler's callbacks engine-side (bound programs read
    0.0 from then on; later compiles against it fail), then release the
    keep-alive thunks. Returns True if the sampler existed."""
    ok = engine.capi().lib.sc_host_sampler_unregister(name.encode("utf-8"))
    _live_samplers.pop(name, None)
    return bool(ok)


def clear_samplers():
    """Addon-unregister teardown: unregister every Python-backed sampler so
    the engine never holds pointers into a module about to be freed."""
    for name in list(_live_samplers):
        unregister_sampler(name)


def apply_render_matrix(context, executor):
    """Push the object -> clip matrix into the executor for
    ViewPlane/ViewRepeat UV. Flat 16 floats, row-major rows appended in
    order — the same element order the mat4 assignment consumes.

    Engine coordinates are *object* space (stroke.py converts world -> object
    on the way in), so this is ``rv3d.perspective_matrix @ ob.matrix_world``,
    the same composition gestures.py:38 uses to project verts. Pushing the
    bare perspective matrix mis-projected every screen-pinned texture on a
    transformed object."""
    import sculptcore

    rv3d = context.region_data
    ob = context.active_object
    if rv3d is None or ob is None:
        return
    mat = rv3d.perspective_matrix @ ob.matrix_world
    flat = [mat[r][c] for r in range(4) for c in range(4)]
    mgr = engine.manager()
    with sculptcore.construct_from_items(mgr, mgr.get("float"), flat) as vec:
        executor.setRenderMatrix(vec)
