# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Headless parity check: the addon's Python stroke spacer vs the engine's
BrushStrokeDriver, on the same synthetic mouse paths.

No ``bpy`` — ``sculptcore_addon.stroke_driver`` and ``.stroke_math`` are loaded
under a synthetic parent package so the addon's ``bpy``-importing
``__init__.py`` never runs. ``push_view`` *is* exercised (through a mathutils
stand-in with ``transposed`` / ``inverted`` / ``translation``), because a
silently transposed matrix or an unset ``viewSize`` is exactly what this is
meant to catch.

Run it against a dev engine checkout:

    $env:SCULPTCORE_PYTHON_PATH = "<repo>\\engine\\python"
    $env:PATH = "<repo>\\engine\\build\\python;$env:PATH"
    python claudeMemory/scripts/stroke_sampler_parity.py

What it does *not* cover: the surface projection of each emitted point (the
driver is used as a pure spacer; every point is re-raycast host-side), and
anything view-dependent beyond the matrices it feeds in. The in-viewport A/B
checklist in the plan is still the sign-off gate.
"""

import importlib
import math
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(REPO, "sculptcore_addon")
PKG = "_sc_addon_headless"

REGION_W = 1200
REGION_H = 800

# Interior dabs must agree to a small fraction of a pixel: the samplers run the
# same algorithm in double, and the driver only narrows to float32 when it
# writes DabSample.screenP. Observed worst case is 3e-5 px on smooth paths;
# the headroom to 0.05 covers the constant sub-pixel offset a clamped segment
# (below) leaves in the walk carry for every dab after it.
POS_TOL = 0.05

# Dabs on a segment with a coincident outer control point — the first segment
# of a stroke, the right-clamped trailing one, and either side of a repeated
# pointer position — get a looser bound, as a fraction of the dab interval.
# The two samplers pick a different tangent there *by design*:
# `crToBezier` takes a one-sided tangent when a neighbor coincides, while
# `stroke_math.cr_to_bezier` floors the knot interval at 1e-9 and so leaves the
# end with (near) zero velocity. The engine's is the better rule — a clamped
# end should continue the segment's own direction, not stall — so this is an
# accepted behavior change, bounded here rather than asserted away.
CLAMPED_TOL_FRACTION = 0.05


# --------------------------------------------------------------------------
# Minimal mathutils stand-in (only what stroke_driver.push_view touches).

class Mat4:
    """Row-major 4x4 with Blender's mathutils surface: ``m[r]`` is row r,
    matrices are column-vector (``M @ v``), and ``translation`` is the last
    column."""

    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def __getitem__(self, r):
        return self.rows[r]

    def __matmul__(self, other):
        return Mat4([[sum(self.rows[i][k] * other.rows[k][j] for k in range(4))
                      for j in range(4)] for i in range(4)])

    def transposed(self):
        return Mat4([[self.rows[r][c] for r in range(4)] for c in range(4)])

    @property
    def translation(self):
        return (self.rows[0][3], self.rows[1][3], self.rows[2][3])

    def inverted(self):
        # Gauss-Jordan on [M | I].
        a = [self.rows[r][:] + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
        for col in range(4):
            pivot = max(range(col, 4), key=lambda r: abs(a[r][col]))
            if abs(a[pivot][col]) < 1e-12:
                raise ValueError("singular matrix")
            a[col], a[pivot] = a[pivot], a[col]
            scale = 1.0 / a[col][col]
            a[col] = [v * scale for v in a[col]]
            for r in range(4):
                if r == col:
                    continue
                f = a[r][col]
                if f:
                    a[r] = [v - f * w for v, w in zip(a[r], a[col])]
        return Mat4([row[4:] for row in a])

    @staticmethod
    def identity():
        return Mat4([[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)])


def _view_matrix(eye_z):
    """World -> camera for an eye at (0, 0, eye_z) looking down -Z."""
    m = Mat4.identity()
    m.rows[2][3] = -eye_z
    return m


def _projection_matrix(fov_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fov_deg) * 0.5)
    return Mat4([
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far + near) / (near - far), 2.0 * far * near / (near - far)],
        [0.0, 0.0, -1.0, 0.0],
    ])


class FakeContext:
    """Just enough of a Blender context for stroke_driver.push_view."""

    def __init__(self):
        view = _view_matrix(5.0)
        proj = _projection_matrix(45.0, REGION_W / REGION_H, 0.1, 100.0)

        self.region = types.SimpleNamespace(width=REGION_W, height=REGION_H)
        self.region_data = types.SimpleNamespace(
            view_matrix=view, perspective_matrix=proj @ view)
        # A non-identity object matrix, so a dropped or transposed obmat push
        # cannot pass by looking like the identity.
        obmat = Mat4.identity()
        obmat.rows[0][3] = 0.3
        obmat.rows[1][3] = -0.2
        obmat.rows[2][1] = 0.15
        self.active_object = types.SimpleNamespace(matrix_world=obmat)
        self.space_data = types.SimpleNamespace(clip_start=0.1)


# --------------------------------------------------------------------------
# Addon module loading.

def load_addon_modules():
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [ADDON_DIR]
    sys.modules[PKG] = pkg
    return (importlib.import_module(PKG + ".stroke_math"),
            importlib.import_module(PKG + ".stroke_driver"))


# --------------------------------------------------------------------------
# The Python sampler, mirroring stroke.StrokeSpacer (which lives in the
# bpy-importing stroke.py and so cannot be imported here). Keep in sync.

class PySpacer:
    """Emits ``(point, clamped)`` pairs; ``clamped`` marks a dab whose segment
    had a coincident outer control point (see CLAMPED_TOL_FRACTION)."""

    def __init__(self, stroke_math):
        self.sm = stroke_math
        self.points = []
        self.walk_carry = 0.0

    def add(self, p, spacing):
        p = (float(p[0]), float(p[1]))
        self.points.append(p)
        n = len(self.points)
        if n == 1 or spacing <= 0.0:
            return [(p, False)]
        if n < 3:
            return []
        return self._walk_segment(n - 3, right_clamp=False, spacing=spacing)

    def flush(self, spacing):
        n = len(self.points)
        if n < 2 or spacing <= 0.0:
            return []
        return self._walk_segment(n - 2, right_clamp=True, spacing=spacing)

    def _walk_segment(self, i, right_clamp, spacing):
        pts = self.points
        p1, p2 = pts[i], pts[i + 1]
        p0 = pts[i - 1] if i >= 1 else p1
        p3 = p2 if right_clamp else pts[i + 2]
        bez = self.sm.cr_to_bezier(p0, p1, p2, p3)
        emitted, self.walk_carry = self.sm.arc_length_walk(bez, spacing, self.walk_carry)
        clamped = p0 == p1 or p3 == p2
        return [(p, clamped) for p in emitted]


# --------------------------------------------------------------------------
# Synthetic paths: (name, [(x, y, pressure), ...]).

def paths():
    out = []

    pts = [(200.0 + i * 12.0, 400.0, 1.0) for i in range(40)]
    out.append(("straight", pts))

    pts = []
    for i in range(60):
        t = i / 59.0
        pts.append((200.0 + 700.0 * t, 400.0 + 180.0 * math.sin(t * math.pi * 2.0),
                    0.2 + 0.8 * t))
    out.append(("sine, ramping pressure", pts))

    # Fast flick: large gaps between events, the case where a spline sampler
    # earns its keep over a per-event dab.
    pts = [(100.0 + i * 160.0, 200.0 + i * 90.0, 1.0) for i in range(7)]
    out.append(("fast flick", pts))

    # Jitter around a line, plus two coincident points (the cr_to_bezier /
    # crToBezier degenerate-tangent branch, whose epsilons differ: 1e-9
    # Python, 1e-7 engine).
    pts = []
    for i in range(50):
        x = 150.0 + i * 15.0
        y = 500.0 + (7.0 if i % 3 == 0 else -5.0 if i % 3 == 1 else 0.0)
        pts.append((x, y, 1.0))
    pts.insert(20, pts[19])
    out.append(("jitter + coincident point", pts))

    # A tight loop, so the walk carry has to survive high curvature.
    pts = []
    for i in range(80):
        a = i / 79.0 * math.pi * 2.0
        pts.append((600.0 + 120.0 * math.cos(a), 400.0 + 120.0 * math.sin(a), 1.0))
    out.append(("loop", pts))

    return out


# --------------------------------------------------------------------------

def run_python(stroke_math, pts, step):
    spacer = PySpacer(stroke_math)
    emitted = []
    for x, y, _pressure in pts:
        emitted.extend(spacer.add((x, y), step))
    emitted.extend(spacer.flush(step))
    return emitted


def run_driver(sd, ctx, pts, pixel_radius, spacing_pct):
    driver = sd.make_driver()
    try:
        emitted = []
        for x, y, pressure in pts:
            sd.push_view(driver, ctx)
            sd.push_event(driver, (x, y), REGION_H, pressure=pressure,
                          invert=False, radius=pixel_radius,
                          spacing=spacing_pct / 100.0)
            emitted.extend(sd.poll_dabs(driver, REGION_H))
        emitted.extend(sd.flush_dabs(driver, REGION_H))
        return emitted
    finally:
        driver.dispose()


def compare(name, step, py, drv):
    ok = True
    print("  {:s}".format(name))
    if len(py) != len(drv):
        print("    FAIL dab count: python {:d}, driver {:d}".format(len(py), len(drv)))
        ok = False

    worst = {False: (0.0, -1), True: (0.0, -1)}
    counts = {False: 0, True: 0}
    for i, ((p, clamped), d) in enumerate(zip(py, drv)):
        counts[clamped] += 1
        dist = math.hypot(p[0] - d.screen[0], p[1] - d.screen[1])
        if dist > worst[clamped][0]:
            worst[clamped] = (dist, i)

    clamped_tol = CLAMPED_TOL_FRACTION * step
    for clamped, tol, label in ((False, POS_TOL, "interior"),
                                (True, clamped_tol, "clamped ")):
        if not counts[clamped]:
            continue
        dist, i = worst[clamped]
        print("    {:s} {:4d} dabs, max offset {:.6f} px (dab {:d}, tol {:g})".format(
            label, counts[clamped], dist, i, tol))
        if dist > tol:
            print("    FAIL: {:s} offset exceeds {:g} px".format(label.strip(), tol))
            ok = False
    return ok


def check_pressure_interpolation(pts, drv):
    """The driver interpolates pressure along each segment; the Python path
    reuses the arriving event's. Not a parity failure — a documented win — so
    it is reported, not asserted."""
    lo = min(p[2] for p in pts)
    hi = max(p[2] for p in pts)
    if hi - lo < 1e-6:
        return
    values = sorted({round(d.pressure, 6) for d in drv})
    print("    pressure: input {:d} distinct over [{:.3f}, {:.3f}] -> "
          "driver {:d} distinct".format(
              len({round(p[2], 6) for p in pts}), lo, hi, len(values)))


def main():
    stroke_math, sd = load_addon_modules()
    ctx = FakeContext()

    failures = 0
    for spacing_pct, pixel_radius in ((10, 50.0), (25, 50.0), (50, 35.0), (100, 20.0)):
        # Vanilla: interval = pixel radius * spacing / 50. The driver reaches
        # the same number as spacing/100 * 2 * radius (SCREEN mode).
        step = spacing_pct / 50.0 * pixel_radius
        print("spacing {:d}%, radius {:g}px -> interval {:g}px".format(
            spacing_pct, pixel_radius, step))
        for name, pts in paths():
            py = run_python(stroke_math, pts, step)
            drv = run_driver(sd, ctx, pts, pixel_radius, spacing_pct)
            if not compare(name, step, py, drv):
                failures += 1
            check_pressure_interpolation(pts, drv)
        print("")

    if failures:
        print("{:d} case(s) FAILED".format(failures))
        return 1
    print("all cases match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
