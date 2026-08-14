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
# space, not its screen-pinned ViewPlane — that one matches Stencil. RANDOM
# has no engine analogue yet (parity checklist).
_COORD_SPACE = {
    '3D': 0,          # Global
    'VIEW_PLANE': 4,  # Projected (brush-centered tangent plane)
    'AREA_PLANE': 4,  # Projected
    'TILED': 2,       # ViewRepeat (screen-pinned, tiled)
    'STENCIL': 1,     # ViewPlane (screen-pinned)
}

# Image bakes keep the image's own resolution up to this cap per axis (the
# engine samples bilinearly from whatever w x h it is handed).
IMAGE_BAKE_MAX = 512

# Texture name -> (settings fingerprint, image pixel digest or None,
# (width, height, np.float32 pixels)).
_cache = {}


def invalidate(name=None):
    """Drop the baked pixels for one texture (or all)."""
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)


def invalidate_from_depsgraph(depsgraph):
    """Called from the depsgraph handler: drop bakes of updated Textures.
    An Image edit does not report its user Textures, so any Image update
    drops the whole cache (rebakes are cheap and stroke-start only)."""
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Image):
            _cache.clear()
            return
        if isinstance(update.id, bpy.types.Texture):
            _cache.pop(update.id.name, None)


def _fingerprint(tex):
    """Hashable snapshot of every scalar/enum setting on the texture (plus
    its color ramp and image identity). Brush textures see no depsgraph
    updates, so cache validity is decided by comparing this at stroke
    start — a type switch, slider drag or image swap all change it."""
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
        for el in ramp.elements:
            vals.append((el.position, tuple(el.color)))
    img = getattr(tex, "image", None)
    if img is not None:
        vals.append((img.name_full, tuple(img.size), img.is_float,
                     img.colorspace_settings.name, img.filepath_raw,
                     img.source, img.has_data, img.is_dirty))
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


def _bake_procedural(tex):
    """Evaluate() bake over [-1, 1]^2 (z = 0). For grayscale sources the
    intensity channel (`tin`, evaluate()[3]) matches Blender's own brush
    sampling; color-ramped and inherently-RGB procedurals use linear-light
    luminance of the color instead (tin stays the pre-ramp intensity)."""
    import numpy as np

    n = BAKE_SIZE
    evaluate = tex.evaluate
    use_rgb = getattr(tex, "use_color_ramp", False) or tex.type == 'MAGIC'
    pixels = np.empty(n * n, dtype=np.float32)
    inv = 2.0 / (n - 1)
    idx = 0
    for j in range(n):
        y = j * inv - 1.0
        for i in range(n):
            v = evaluate((i * inv - 1.0, y, 0.0))
            if use_rgb:
                pixels[idx] = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
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
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    if w > IMAGE_BAKE_MAX or h > IMAGE_BAKE_MAX:
        ys = np.linspace(0, h - 1, min(h, IMAGE_BAKE_MAX)).round().astype(int)
        xs = np.linspace(0, w - 1, min(w, IMAGE_BAKE_MAX)).round().astype(int)
        lum = lum[np.ix_(ys, xs)]
        h, w = lum.shape
    return (w, h, np.ascontiguousarray(lum, dtype=np.float32).ravel())


def needs_render_matrix(bl_brush):
    """Whether the brush's texture mapping reads ctx.renderMatrix
    (view-pinned UV)."""
    slot = bl_brush.texture_slot if bl_brush else None
    return (bl_brush is not None and bl_brush.texture is not None
            and slot is not None and slot.map_mode in {'TILED', 'STENCIL'})


def apply_texture(bl_brush, sc_brush, context=None):
    """Bind (or clear) the engine brush texture for a stroke. Unmapped
    map modes (and image textures with no pixels) clear so the kernels'
    sampleBrushTex is a no-op 1.0. ``context`` sizes the Tiled repeat;
    without it Tiled falls back to one tile per viewport height."""
    import sculptcore

    tex = bl_brush.texture if bl_brush else None
    coord_space = None
    if tex is not None and bl_brush.texture_slot is not None:
        coord_space = _COORD_SPACE.get(bl_brush.texture_slot.map_mode)
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
    """Push the region's perspective matrix (world -> NDC) into the executor
    for ViewPlane/ViewRepeat UV. Flat 16 floats, row-major rows appended in
    order — the same element order the mat4 assignment consumes."""
    import sculptcore

    rv3d = context.region_data
    if rv3d is None:
        return
    mat = rv3d.perspective_matrix
    flat = [mat[r][c] for r in range(4) for c in range(4)]
    mgr = engine.manager()
    with sculptcore.construct_from_items(mgr, mgr.get("float"), flat) as vec:
        executor.setRenderMatrix(vec)
