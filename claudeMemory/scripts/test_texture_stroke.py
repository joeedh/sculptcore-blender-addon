# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""End-to-end check for the ported `.stex` brush textures — plan
claudeMemory/plans/blender-texture-system-port.md §4.3.

`tools/verify_texture_parity.py` grades each script's *values* against
Blender's own texture evaluation, but it does so through `evalTextureAt`: a
direct point query with no stroke, no executor and a null map context. So it
cannot see the half that makes a texture visible — `apply_texture` picking the
script over the bake, the param slab surviving `writeProps`, and the kernels
actually folding `sampleBrushTex` into a dab. That half is what this covers.

Per type, on identical fresh sessions and identical dabs:

1. `apply_texture` routes it — `session.tex_script_type` is the type, which
   also exercises `_SCRIPT_TYPES` and the `slot.map_mode == '3D'` gate that
   the parity harness bypasses by binding scripts directly;
2. the stroke moves verts;
3. the displacement is *modulated*, not merely scaled: the per-vertex ratio
   against an untextured control stroke has real spread. A script that
   compiled but returned a constant would pass 1 and 2 and fail here;
4. no two types produce the same field, which is what catches a stale compile
   cache handing every type the program it compiled first.

Headless is sufficient and not a compromise: 3D mapping is the only map mode
that routes to a script, and a 3D-mapped program reads the sculpt-space point
directly — none of the six `.stex` sources calls `mapPoint()`, so there is no
render matrix to come from a real 3D view. The map-mode paths that *do* need
one still take the bitmap bake.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_texture_stroke.py
"""

import sys

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, stroke, texture

# The depsgraph handler re-enters conversion mid-test; the other headless
# harnesses in this directory unhook it for the same reason.
bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []

RADIUS = 0.45
STRENGTH = 1.0
# A line of dabs across the grid, chosen to stay well inside it so every dab
# lands and the two arms see the same node set.
DAB_XY = [(-0.30, 0.0), (-0.15, 0.0), (0.0, 0.0), (0.15, 0.0), (0.30, 0.0)]

# Every routed type, each configured to a setting with visible structure at
# this stroke's scale. `noise_scale` is the one knob that has to shrink: the
# default 0.25 puts a single noise cell well outside a 0.45-radius dab, so the
# field would be near-constant over the stroke for a reason that is not a bug.
TYPES = {
    'CLOUDS': {"noise_scale": 0.15, "noise_depth": 3},
    'BLEND': {"progression": 'SPHERICAL'},
    'MAGIC': {"noise_depth": 4, "turbulence": 6.0},
    'WOOD': {"wood_type": 'BANDNOISE', "noise_scale": 0.15, "turbulence": 8.0},
    'MARBLE': {"marble_type": 'SHARP', "noise_scale": 0.15, "noise_depth": 3},
    'STUCCI': {"stucci_type": 'WALL_IN', "noise_scale": 0.15, "turbulence": 8.0},
}


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def draw_kernel():
    return int(engine.manager().get(
        "sculptcore::brush::SculptBrushes").items['DRAW'])


def make_grid(name):
    """A dense flat grid: enough verts under one dab that a per-vertex spread
    statistic means something, and flat so the texture is the only thing that
    varies across the footprint."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=96, y_subdivisions=96, size=2)
    ob = bpy.context.object
    ob.name = ob.data.name = name
    return ob


def make_brush(name, tex_type):
    """A sculpt brush with the type bound to its texture slot in 3D mapping —
    the one map mode `apply_texture` routes to a script."""
    bl_brush = bpy.data.brushes.new(name, mode='SCULPT')
    if tex_type is not None:
        tex = bpy.data.textures.new("t_" + name, type=tex_type)
        for attr, val in TYPES[tex_type].items():
            setattr(tex, attr, val)
        bl_brush.texture = tex
    bl_brush.texture_slot.map_mode = '3D'
    return bl_brush


def run_stroke(name, tex_type):
    """One draw stroke over a fresh grid. Returns the per-vertex displacement
    magnitudes, and the session's routed script type."""
    ob = make_grid(name)
    session = convert.enter(ob)
    sc_brush = stroke._ensure_brush(session)
    bl_brush = make_brush(name, tex_type)

    # The real entry point, gate included — not `_apply_script`, which is what
    # the parity harness calls and which would skip `_SCRIPT_TYPES` entirely.
    texture.apply_texture(bl_brush, sc_brush, bpy.context, session=session)

    pre = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    kernel = draw_kernel()
    stroke.stroke_begin(session)
    for x, y in DAB_XY:
        hit = stroke.raycast(session, (x, y, 3.0), (0.0, 0.0, -1.0))
        if hit is None:
            continue
        p, nrm, _face = hit
        # loadProps writes strength*pressure back into the Brush fields, so
        # both have to be re-set before every dab or the stroke fades out
        # after the first one.
        sc_brush.strength = STRENGTH
        sc_brush.radius = RADIUS
        sc_brush.invert = False
        sc_brush.writeProps()
        stroke.apply_dab(session, kernel, tuple(p), tuple(nrm), RADIUS)
    stroke.stroke_end(session)

    post = convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()
    routed = session.tex_script_type
    convert.exit_(ob)
    bpy.data.objects.remove(ob, do_unlink=True)
    return np.linalg.norm(post - pre, axis=1), routed


def modulation(d_tex, d_ctl):
    """Spread of the per-vertex ratio against the untextured control, over the
    verts the control actually moved. A texture that evaluated to a constant
    scales every vertex alike and lands at 0; one that varies across the dab
    footprint does not. Restricting to well-moved verts keeps the ratio away
    from the falloff's own tail, where both sides go to zero and the quotient
    is noise rather than signal."""
    live = d_ctl > 0.25 * d_ctl.max()
    if live.sum() < 32:
        return None
    ratio = d_tex[live] / d_ctl[live]
    return float(ratio.std())


def main():
    control, routed = run_stroke("ctl", None)
    check(routed is None, "untextured stroke routes no script")
    check(control.max() > 1e-4,
          "control stroke moved verts (max {:.4g})".format(control.max()))
    if control.max() <= 1e-4:
        return                       # every check below divides by this

    fields = {}
    for tex_type in TYPES:
        print("{:s}:".format(tex_type))
        moved, routed = run_stroke(tex_type.lower(), tex_type)
        check(routed == tex_type,
              "apply_texture routed the script (got {!r})".format(routed))
        check(moved.max() > 1e-4,
              "textured stroke moved verts (max {:.4g})".format(moved.max()))
        spread = modulation(moved, control)
        check(spread is not None and spread > 0.02,
              "displacement is modulated, not scaled (ratio sd {})".format(
                  "n/a" if spread is None else "{:.4g}".format(spread)))
        fields[tex_type] = moved

    # A stale compile cache — `session.tex_script_type` gating the recompile —
    # would hand a later type the program compiled for an earlier one. Fresh
    # sessions per type make that unlikely rather than impossible, and the
    # cost of ruling it out is one comparison.
    names = sorted(fields)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            same = np.allclose(fields[a], fields[b], atol=1e-6)
            check(not same, "{:s} and {:s} produce different fields".format(a, b))

    print("\n{:d} failure(s)".format(len(failures)))
    for msg in failures:
        print("  FAIL {:s}".format(msg))
    if failures:
        sys.exit(1)
    print("texture stroke routing OK")


main()
