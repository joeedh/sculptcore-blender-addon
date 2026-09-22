# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Blender brushes ported in the todos.md batch, host side: Crease / Blob,
Pinch / Magnify along a stroke, the unified Plane brush's reaches and
inversion modes, Twist's dial angle, and Clay Strips' cube tip.

Each case drives the addon's own mapping (``mapping.apply_brush`` on a real
``bpy.types.Brush``) and dab entry points on a flat or bumped grid, then
asserts the geometric signature vanilla's brush leaves:

- Crease (Subtract) trenches and gathers toward the axis; Blob (Add) domes and
  spreads.
- Pinch along a stroke gathers verts onto the stroke *line* (across-stroke
  motion only); Magnify pushes them away at a quarter strength.
- Plane with height 0 / depth 1 (Fill) raises dips and leaves bumps; inverted
  in Swap mode it scrapes bumps and leaves dips; inverted in Invert
  Displacement mode it deepens the dips at half strength.
- Twist rotates the anchored region counter-clockwise about the normal by the
  dial angle (falloff-scaled), and a mirror image the other way.
- Clay Strips' rounded box reaches ``tip_scale_x`` radii along the stroke and
  one radius across.
- The direction table: every BRUSH_DIR_IN item inverts, not only SUBTRACT.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \\
        --python claudeMemory/scripts/test_blender_brushes.py
"""

import math

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, mapping, stroke
from sculptcore_addon.brush_properties.stroke_settings import capture_stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
RADIUS = 0.35
UP = (0.0, 0.0, 1.0)
# `Brush.direction` is a context-dependent enum: its items come from the
# active paint mode, and headless with no object in a paint mode every brush
# reads 'DEFAULT'. A scratch object held in the SculptCore mode, re-activated
# before each brush read, gives it the sculpt item lists.
scratch = None


def activate_scratch():
    bpy.context.view_layer.objects.active = scratch


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def make_grid(name, height=None):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=2)
    ob = bpy.context.object
    ob.name = ob.data.name = name
    if height is not None:
        for v in ob.data.vertices:
            v.co.z = height(v.co.x, v.co.y)
    return ob


def make_brush(name, brush_type, **settings):
    b = bpy.data.brushes.new(name, mode='SCULPT')
    b.sculpt_brush_type = brush_type
    b.strength = 0.5
    b.use_accumulate = True
    activate_scratch()
    for key, value in settings.items():
        setattr(b, key, value)
    return b


def positions(session):
    return convert.mesh_positions(session.mesh_ptr).reshape(-1, 3).copy()


def nearest(before, point):
    return int(np.argmin(np.linalg.norm(before[:, :2] - np.asarray(point, dtype=before.dtype), axis=1)))


class Stroke:
    """One stroke on a fresh grid through the addon's non-modal entry points."""

    def __init__(self, name, brush, height=None, anchored=False, plane_frame=None):
        self.ob = make_grid(name, height)
        self.session = convert.enter(self.ob)
        activate_scratch()
        self.brush = brush
        self.kernel = mapping.kernel_enum(engine.manager(), brush)
        check(self.kernel is not None, "{:s}: kernel for {:s} present in the DLL".format(name, brush.sculpt_brush_type))
        stroke._ensure_brush(self.session)
        stroke._ensure_executor(self.session)
        self.paint = bpy.context.tool_settings.sculpt
        stroke.stroke_begin(self.session, accumulate=True, anchored_grab=anchored,
                            plane_frame=plane_frame or mapping.PLANE_FRAME_DEFAULT)
        self.before = positions(self.session)

    def apply(self, brush, invert=False):
        mapping.apply_brush(brush, self.paint.unified_paint_settings, self.session.brush_obj,
                            world_radius=RADIUS, invert=invert, paint=self.paint)

    def dab(self, xy, invert=False, sign=(1, 1, 1)):
        self.apply(self.brush, invert)
        hit = stroke.raycast(self.session, (xy[0], xy[1], 3.0), (0.0, 0.0, -1.0))
        check(hit is not None, "cursor hits the surface at {!r}".format(xy))
        stroke.set_image_sign(self.session, sign)
        moved = stroke.apply_dab(self.session, self.kernel, hit[0], hit[1], RADIUS)
        check(moved > 0, "dab at {!r} moved geometry ({:d})".format(xy, moved))
        return hit

    def grab(self, anchor, cursor, sign=(1, 1, 1), accum_add=False):
        stroke.set_image_sign(self.session, sign)
        moved = stroke.apply_grab_dab(self.session, self.kernel, anchor, cursor, UP, RADIUS, accum_add=accum_add)
        check(moved > 0, "grab dab at {!r} moved geometry ({:d})".format(anchor, moved))

    def finish(self):
        stroke.stroke_end(self.session)
        after = positions(self.session)
        convert.exit_(self.ob)
        return self.before, after


def direction_table():
    b = make_brush("Direction", 'DRAW')
    activate_scratch()
    rows = (('DRAW', 'ADD', False), ('DRAW', 'SUBTRACT', True), ('PINCH', 'PINCH', False),
            ('PINCH', 'MAGNIFY', True), ('INFLATE', 'INFLATE', False), ('INFLATE', 'DEFLATE', True),
            ('CREASE', 'SUBTRACT', True), ('BLOB', 'ADD', False), ('PLANE', 'SUBTRACT', True))
    for brush_type, item, want in rows:
        b.sculpt_brush_type = brush_type
        b.direction = item
        check(b.direction == item and mapping.direction_inverted(b) == want,
              "direction {:s}/{:s} inverted={!r}".format(brush_type, item, want))
        settings = capture_stroke(b, bpy.context.scene)
        check(settings.subtract == want, "capture_stroke {:s}/{:s} subtract={!r}".format(brush_type, item, want))
    b.sculpt_brush_type = 'PLANE'
    b.plane_inversion_mode = 'SWAP_DEPTH_AND_HEIGHT'
    check(mapping.plane_swap_on_invert(b) and capture_stroke(b, bpy.context.scene).plane_swap,
          "plane swap mode captured")
    b.plane_inversion_mode = 'INVERT_DISPLACEMENT'
    check(not mapping.plane_swap_on_invert(b), "plane invert-displacement mode captured")
    b.sculpt_brush_type = 'CLAY_STRIPS'
    b.tip_scale_x, b.tip_roundness = 0.7, 0.15
    settings = capture_stroke(b, bpy.context.scene)
    check(abs(settings.tip_scale_x - 0.7) < 1e-6 and abs(settings.tip_roundness - 0.15) < 1e-6,
          "tip shape captured")
    bpy.data.brushes.remove(b)


def crease_blob():
    for brush_type, direction, sign in (('CREASE', 'SUBTRACT', -1.0), ('BLOB', 'ADD', 1.0)):
        b = make_brush(brush_type.title(), brush_type, direction=direction, crease_pinch_factor=0.8)
        s = Stroke(brush_type.lower(), b)
        s.dab((0.0, 0.0))
        before, after = s.finish()
        delta = after - before
        # A ring of verts at a third of the radius: the offset sign and the
        # toward-axis gather (crease) / spread (blob).
        ring = np.abs(np.linalg.norm(before[:, :2], axis=1) - RADIUS / 3.0) < 0.02
        dz = delta[ring, 2]
        radial_before = np.linalg.norm(before[ring, :2], axis=1)
        radial_after = np.linalg.norm(after[ring, :2], axis=1)
        check(np.all(dz * sign > 1e-4), "{:s}: ring offset has the {:s} sign".format(brush_type, direction))
        check(np.all((radial_after - radial_before) * sign > 1e-5),
              "{:s}: ring {:s} the axis".format(brush_type, "spread from" if sign > 0 else "gathered toward"))
        # The centre vertex only moves along the normal.
        centre = nearest(before, (0.0, 0.0))
        check(np.abs(delta[centre, :2]).max() < 1e-6, "{:s}: centre vertex stays on the axis".format(brush_type))
        bpy.data.brushes.remove(b)
    # Pinch scales with the factor's square: half the factor, a quarter of the gather.
    gathers = []
    for factor in (0.8, 0.4):
        b = make_brush("Crease Factor", 'CREASE', direction='SUBTRACT', crease_pinch_factor=factor)
        s = Stroke("crease_factor_{:.1f}".format(factor), b)
        s.dab((0.0, 0.0))
        before, after = s.finish()
        ring = np.abs(np.linalg.norm(before[:, :2], axis=1) - RADIUS / 3.0) < 0.02
        gathers.append(float((np.linalg.norm(before[ring, :2], axis=1)
                              - np.linalg.norm(after[ring, :2], axis=1)).mean()))
        bpy.data.brushes.remove(b)
    ratio = gathers[0] / gathers[1]
    check(abs(ratio - 4.0) < 0.15, "crease: gather scales with pinch factor squared (ratio {:.3f})".format(ratio))


def pinch_magnify():
    for direction, want in (('PINCH', -1.0), ('MAGNIFY', 1.0)):
        b = make_brush("Pinch " + direction, 'PINCH', direction=direction)
        s = Stroke("pinch_" + direction.lower(), b)
        # Two dabs along +X: the first has no tangent (a point pinch), the
        # second pinches toward the stroke line through its centre, so verts
        # beside it move in Y only.
        s.dab((-0.5, 0.0))
        s.dab((0.1, 0.0))
        before, after = s.finish()
        delta = after - before
        beside = (np.abs(before[:, 0] - 0.1) < 0.03) & (np.abs(np.abs(before[:, 1]) - 0.12) < 0.03)
        dx = float(np.abs(delta[beside, 0]).max())
        dy = delta[beside, 1] * np.sign(before[beside, 1])
        check(beside.sum() >= 4 and np.all(dy * want > 1e-5),
              "{:s}: verts beside the line move {:s} it".format(direction, "toward" if want < 0 else "away from"))
        check(dx < 1e-6, "{:s}: no along-stroke motion beside the second dab (max |dx| {:.2e})".format(direction, dx))
        # Under the first (directionless) dab the gather is toward the point.
        first = (np.abs(before[:, 0] + 0.5 - 0.12) < 0.03) & (np.abs(before[:, 1]) < 0.02)
        check(first.any() and np.all(delta[first, 0] * want > 1e-5),
              "{:s}: the first dab pinches toward its point".format(direction))
        bpy.data.brushes.remove(b)


def plane_modes():
    def bumps(x, y):
        return 0.05 * math.sin(8.0 * x) * math.sin(8.0 * y)

    def run(name, invert, mode, height, depth):
        b = make_brush("Plane " + name, 'PLANE', plane_height=height, plane_depth=depth, plane_offset=0.0,
                       plane_inversion_mode=mode, direction='ADD')
        s = Stroke("plane_" + name, b, height=bumps)
        s.dab((0.0, 0.0), invert=invert)
        before, after = s.finish()
        bpy.data.brushes.remove(b)
        delta = after - before
        inside = np.linalg.norm(before[:, :2], axis=1) < RADIUS * 0.6
        up = inside & (before[:, 2] > 0.01)
        down = inside & (before[:, 2] < -0.01)
        return float(delta[up, 2].max()), float(delta[up, 2].min()), float(delta[down, 2].max()), \
            float(delta[down, 2].min())

    # Fill: dips rise, bumps stay.
    up_max, up_min, down_max, down_min = run("fill", False, 'SWAP_DEPTH_AND_HEIGHT', 0.0, 1.0)
    check(abs(up_max) < 1e-7 and abs(up_min) < 1e-7, "plane fill: bumps untouched")
    check(down_min > 1e-4, "plane fill: dips rise ({:.4f}..{:.4f})".format(down_min, down_max))
    fill_rise = down_min
    # Inverted in Swap mode: the reaches trade places -> scrape.
    up_max, up_min, down_max, down_min = run("swap", True, 'SWAP_DEPTH_AND_HEIGHT', 0.0, 1.0)
    check(up_max < -1e-4, "plane swap: bumps scraped down ({:.4f}..{:.4f})".format(up_min, up_max))
    check(abs(down_max) < 1e-7 and abs(down_min) < 1e-7, "plane swap: dips untouched")
    # Inverted in Invert Displacement mode: the dips deepen, at half strength.
    up_max, up_min, down_max, down_min = run("deepen", True, 'INVERT_DISPLACEMENT', 0.0, 1.0)
    check(abs(up_max) < 1e-7 and abs(up_min) < 1e-7, "plane deepen: bumps untouched")
    check(down_max < -1e-4, "plane deepen: dips deepen ({:.4f}..{:.4f})".format(down_min, down_max))
    ratio = -down_max / fill_rise
    check(abs(ratio - 0.5) < 0.05, "plane deepen: half the fill strength (ratio {:.3f})".format(ratio))
    # Flatten: both sides converge on the plane.
    up_max, up_min, down_max, down_min = run("flatten", False, 'INVERT_DISPLACEMENT', 1.0, 1.0)
    check(up_max < -1e-4 and down_min > 1e-4, "plane flatten: both sides move onto the plane")


def twist():
    def run(name, sign):
        b = make_brush("Twist", 'ROTATE', strength=1.0)
        s = Stroke("twist_" + name, b, anchored=True)
        s.apply(b)
        s.session.brush_obj.rotateAngle = 0.5 * mapping.dial_angle_flip(sign)
        anchor = (0.0, 0.0, 0.0)
        s.grab(anchor, anchor, sign=sign)
        before, after = s.finish()
        bpy.data.brushes.remove(b)
        return before, after

    before, after = run("primary", (1, 1, 1))
    delta = after - before
    check(np.abs(delta[:, 2]).max() < 1e-6, "twist: rotation stays in the tangent plane")
    # Rotation angle of each moved vertex about +Z, positive = counter-clockwise.
    moved = np.linalg.norm(delta[:, :2], axis=1) > 1e-6
    a, c = before[moved, :2], after[moved, :2]
    angles = np.arctan2(a[:, 0] * c[:, 1] - a[:, 1] * c[:, 0], (a * c).sum(axis=1))
    check(moved.sum() > 20 and np.all(angles > 0.0) and angles.max() <= 0.5 + 1e-4,
          "twist: {:d} verts turned counter-clockwise by up to {:.3f} rad".format(int(moved.sum()), float(angles.max())))
    radial = np.abs(np.linalg.norm(c, axis=1) - np.linalg.norm(a, axis=1)).max()
    check(radial < 1e-5, "twist: verts keep their distance from the anchor (max drift {:.2e})".format(radial))
    inner = np.linalg.norm(a, axis=1) < 0.05
    outer = np.linalg.norm(a, axis=1) > RADIUS * 0.8
    check(inner.any() and outer.any() and angles[inner].min() > angles[outer].max(),
          "twist: the angle fades with the falloff")
    # A mirror image (X reflected) turns the other way.
    before, after = run("mirror", (-1, 1, 1))
    delta = after - before
    moved = np.linalg.norm(delta[:, :2], axis=1) > 1e-6
    a, c = before[moved, :2], after[moved, :2]
    angles = np.arctan2(a[:, 0] * c[:, 1] - a[:, 1] * c[:, 0], (a * c).sum(axis=1))
    check(moved.sum() > 20 and np.all(angles < 0.0), "twist: the X-mirror image turns clockwise")
    # The dial itself: the port of BLI_dial_angle.
    from sculptcore_addon.stroke.dial import Dial
    dial = Dial((100.0, 100.0), 5.0)
    check(dial.angle((102.0, 100.0)) == 0.0, "dial: inside the threshold, no angle")
    check(dial.angle((120.0, 100.0)) == 0.0, "dial: the first direction past the threshold is the reference")
    check(abs(dial.angle((100.0, 120.0)) - math.pi / 2.0) < 1e-6, "dial: a quarter turn counter-clockwise")
    check(abs(dial.angle((80.0, 100.0)) - math.pi) < 1e-6, "dial: a half turn")
    check(abs(dial.angle((100.0, 80.0)) - 1.5 * math.pi) < 1e-6, "dial: past pi keeps winding")
    check(abs(dial.angle((120.0, 100.0)) - 2.0 * math.pi) < 1e-6, "dial: a full turn")


def clay_strips_tip():
    def run(name, tip_scale_x):
        b = make_brush("Clay Strips", 'CLAY_STRIPS', tip_scale_x=tip_scale_x, tip_roundness=0.15,
                       plane_offset=0.4, sculpt_plane='AREA')
        s = Stroke("strips_" + name, b)
        # Two dabs along +X: the second dab's box is oriented by the stroke.
        s.dab((-0.9, 0.0))
        s.dab((0.0, 0.0))
        sc = s.session.brush_obj
        check(int(sc.falloff_shape) == mapping._FALLOFF_SHAPE_ROUNDED_BOX
              and abs(sc.falloff_extent.vec[0] - tip_scale_x) < 1e-6 and abs(sc.falloff_roundness - 0.15) < 1e-6,
              "clay strips: rounded box installed (extent {:.2f}, roundness {:.2f})".format(
                  sc.falloff_extent.vec[0], sc.falloff_roundness))
        before, after = s.finish()
        bpy.data.brushes.remove(b)
        return before, after - before

    before, delta = run("scaled", 0.7)
    along = nearest(before, (0.85 * RADIUS, 0.0))
    across = nearest(before, (0.0, 0.85 * RADIUS))
    check(abs(delta[along, 2]) < 1e-7, "clay strips: 0.85 r along the stroke is outside the 0.7 r box")
    check(delta[across, 2] > 1e-4, "clay strips: 0.85 r across the stroke is inside the box")
    before, delta = run("square", 1.0)
    along = nearest(before, (0.85 * RADIUS, 0.0))
    check(delta[along, 2] > 1e-4, "clay strips: tip_scale_x 1 reaches 0.85 r along the stroke")
    # Roundness 0.15: the corner region outside the rounded rectangle is dead.
    corner = nearest(before, (0.97 * RADIUS, 0.97 * RADIUS))
    edge = nearest(before, (0.97 * RADIUS, 0.0))
    check(abs(delta[corner, 2]) < 1e-7 and delta[edge, 2] > 1e-5, "clay strips: corners are rounded off")


def main():
    global scratch
    scratch = make_grid("scratch")
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    check(scratch.mode == 'CUSTOM', "scratch object holds the SculptCore mode")
    direction_table()
    crease_blob()
    pinch_magnify()
    plane_modes()
    twist()
    clay_strips_tip()
    activate_scratch()
    bpy.ops.object.custom_mode_toggle(mode_id='sculptcore.sculpt')
    if failures:
        raise SystemExit("test_blender_brushes: {:d} failure(s)".format(len(failures)))
    print("BLENDER_BRUSHES_OK")


main()
