# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compare each ported ``.stex`` texture program against Blender's own texture
evaluation.

Run headless against an install that has the addon enabled::

    blender --background --factory-startup --python-exit-code 1 \\
            --python tools/verify_texture_parity.py -- [--samples N] [--seed S]
            [--type CLOUDS] [--verbose]

What is actually comparable
---------------------------
A pointwise diff is only meaningful for a type that shares Blender's noise
basis.  ``clouds.stex`` deliberately does not: it samples the engine's builtin
``vnoise`` because a DSL-inlined transcription of ``BLI_noise`` cost ~9x per
octave under the non-optimizing tcc JIT.  Diffing that against
``RE_texture_evaluate`` point for point measures the substitution and nothing
else -- it fails at any tolerance tight enough to catch a real bug.

So each type declares a **mode**, and the harness runs three checks:

``epilogue``  Every type, tight.  What the drawn ``intensity``/``contrast``/
              ``use_clamp`` do to the raw pattern.  For ``mode='point'`` this is
              simply the two sides diffed at the drawn settings -- the strongest
              possible statement, available because the pattern itself matches.
              For ``mode='field'`` the two raw patterns differ by construction,
              so instead each side is required to satisfy one shared model,
              ``BRICONT``: ``v = raw * contrast + intensity - 0.5``, clamped to
              [0,1] only when ``use_clamp`` is on, with ``raw`` that side's own
              value under neutral settings.  Obeying the same model is what makes
              the two epilogues the same function despite different ``raw``.
              This is the check that catches the bugs Part 0 found (the clamp
              was unconditional, the placement composed in the wrong order).

``placement`` Every type, tight.  The coordinate transform must be
              ``q = (size * (p + ofs) + basis_offset) / scale`` -- offset before
              scale from ``RE_texture_evaluate``, then the ``+1`` and the
              ``1/noisesize`` divide ``BLI_noise_generic_turbulence`` applies to
              the default basis (``noise_c.cc:1244-1258``).  Verified on both
              sides for the texture's own scale, and on the port for the brush
              slot's ``size``/``ofs``, which ``Texture.evaluate()`` does not
              apply at all.  Types whose ``scale_attr`` is ``None`` divide by
              ``noisesize`` *inside* the noise call rather than up front (Wood,
              Marble and Stucci all do; ``wood_int`` hands the waveform the raw
              placed coordinate), so it does not factor out of the pattern and
              this check grades the slot half only.  See ``TRIM_OUTLIERS`` for
              why every worst-case statistic here is a trimmed max rather than
              a bare one.

``field``     The pattern itself.  ``mode='point'`` (basis-free types such as
              Magic and Blend) diffs it sample by sample; ``mode='field'``
              (anything over ``vnoise``) compares the distribution -- mean and
              standard deviation over the sample box -- which is the strongest
              claim a substituted basis supports, and still catches a wrong
              octave weighting, hard-noise fold, or normalization.

**Tolerances are measured, not asserted.**  ``--verbose`` prints every observed
number so tightening a budget is a matter of reading the output, and a
regression shows up as a number moving rather than a pass/fail flip.

A type declares either one spec or a **list** of them (see ``variants``), because
one ``mode`` per type is sometimes too coarse a statement.  Wood is the reason:
two of its four wood types call no noise at all and deserve the pointwise grade,
while Band/Ring Noise can only be graded as a distribution.  The same mechanism
carries the *quiet* variants, which pin ``turbulence`` to its RNA minimum so the
noise contribution is bounded by 1e-4 whatever the basis -- that grades every
part of a noisy arm except the noise amplitude, leaving the amplitude as the one
thing the field case has to carry.

The oracle is not ``Texture.evaluate()[0]``
-------------------------------------------
The brush path is ``RE_texture_evaluate`` (``texture_procedural.cc:1061-1098``),
not ``multitex_ext``, and it ends by *overwriting* the per-type intensity with
the luminance of the RGB result whenever ``multitex`` reported ``TEX_RGB``.
``Texture.evaluate()`` performs no such collapse and hands back the pre-collapse
intensity in slot 3, leaving ``trgba`` zero for every intensity-only type.  So
the oracle reads slot 3 for intensity types and luminance(rgb) for the RGB set --
``texture._returns_rgb`` is the same classifier the bake path uses.
"""

import statistics
import random
import sys

import bpy

from sculptcore_addon import engine, texture

# Rec.709 luminance, matching IMB_colormanagement_get_luminance under the
# default (sRGB/Rec.709) working space.
LUMA = (0.2126729, 0.7151522, 0.0721750)

# Sampling box in sculpt space for the pointwise checks. Wide enough that
# several noise cells are crossed at the default noise_scale, without running
# the coordinates so far out that float precision alone explains a divergence.
EXTENT = 3.0

# The field statistic needs a much wider box, because its error floor is set by
# the number of *noise cells* covered, not the number of samples: a lattice
# field is coherent within a cell, so 6 cells per axis leaves the sample mean
# with a ~0.012 standard error of its own -- as large as the difference being
# measured. 32 cells per axis puts that floor near 0.002.
FIELD_EXTENT = 16.0

# Points for the pointwise checks. They are exact identities, so a handful of
# points either shows the defect or does not; the samples budget belongs to the
# statistic.
PROBE_POINTS = 512

# How many of the largest per-point errors each worst-case statistic discards
# before reporting. Not slack. Two of these types put a small input difference
# through a map with no bound on its slope, so a single sample can read O(1)
# while every other one reads 1e-6:
#
#   - Wood's and Marble's saw and triangle waveforms jump by a full unit once
#     per period, and `check_placement` hands the engine a reference coordinate
#     this script rounded to float, which can fall on the far side of a jump;
#   - Marble's Sharper takes `v^(1/4)`, whose derivative is unbounded as
#     v -> 0, so a sample landing on a zero of the waveform amplifies the
#     1e-4 the quiet case allows into a visible number.
#
# Neither can be mistaken for a defect: a wrong placement or a wrong epilogue
# moves the *pattern*, so it misplaces every sample at once, which no amount of
# trimming can hide.
TRIM_OUTLIERS = 4


def trimmed_max(errs):
    """The largest error after discarding `TRIM_OUTLIERS` of them (or the plain
    max, when there are too few samples for that to mean anything)."""
    errs = sorted(errs)
    return errs[-1 - TRIM_OUTLIERS] if len(errs) > 4 * TRIM_OUTLIERS else errs[-1]

# Per-type descriptors. `settings` is what the randomizer draws from -- a tuple
# of two numbers is a closed interval (int if both ends are ints), anything else
# is a choice list; only settings the .stex claims to reproduce belong here
# (Clouds COLOR is absent because `texture._script_supports` deliberately routes
# it to the bake). `neutral` is the epilogue identity: bright 0.5 / contrast 1 /
# no clamp makes BRICONT the identity minus 0.5, exposing the raw pattern.
# `scale_attr` is the type's own coordinate divisor (None for a type that has
# none), and `basis_offset` the constant added before that divide. `budget` is
# measured on this box, printed by --verbose, and tightened by reading that
# output.
TYPES = {
    'CLOUDS': {
        "mode": 'field',
        "settings": {
            "noise_scale": (0.1, 1.5),
            "noise_depth": (0, 5),
            "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
            "cloud_type": ('GRAYSCALE',),
            "intensity": (0.0, 2.0),
            "contrast": (0.2, 2.5),
            "use_clamp": (True, False),
        },
        "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
        "scale_attr": "noise_scale",
        "basis_offset": 1.0,
        # Worst over seeds 1-4 and 20260814: epilogue 8.9e-8, placement 8.7e-6,
        # mean 0.0139, sd 0.0055 -- roughly 2x headroom each. The two pointwise
        # budgets sit far above their float-rounding floor and far below a real
        # defect (a wrong clamp gate or a dropped basis offset both land at
        # O(0.5)), so the gap is not worth narrowing.
        "budget": {"epilogue": 1.0e-6, "placement": 1.0e-4,
                   "mean": 0.03, "sd": 0.012},
    },
    'BLEND': {
        # Zero BLI_noise calls (texture_procedural.cc:55-110): every
        # progression is a closed form of the placed coordinate, so this one
        # is graded pointwise.
        "mode": 'point',
        "settings": {
            "progression": ('LINEAR', 'QUADRATIC', 'EASING', 'DIAGONAL',
                            'SPHERICAL', 'QUADRATIC_SPHERE', 'RADIAL'),
            "use_flip_axis": ('HORIZONTAL', 'VERTICAL'),
            "intensity": (0.0, 2.0),
            "contrast": (0.2, 2.5),
            "use_clamp": (True, False),
        },
        "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
        "scale_attr": None,
        "basis_offset": 0.0,
        # Worst over seeds 1-4 and 20260814: epilogue 0, point 0 -- the port is
        # bit-identical to Blender at every drawn setting. Placement reaches
        # 1.1e-5 only because that check hands the engine a coordinate this
        # script computed in double and rounded to float, rather than one the
        # engine composed itself; the quadratic and radial arms amplify the
        # last-bit difference. Composing the placement wrongly costs O(1).
        "budget": {"epilogue": 1.0e-6, "placement": 3.0e-5, "point": 1.0e-6},
    },
    'MAGIC': {
        # Also noise-free (texture_procedural.cc:290-361) — a fixed sin/cos
        # cascade — so pointwise again, despite being the one ported type that
        # reports TEX_RGB.
        "mode": 'point',
        "settings": {
            "noise_depth": (0, 10),
            "turbulence": (0.0, 10.0),
            "intensity": (0.0, 2.0),
            "contrast": (0.2, 2.5),
            "use_clamp": (True, False),
            # BRICONTRGB's own settings, which only a TEX_RGB type reaches.
            "factor_red": (0.0, 2.0),
            "factor_green": (0.0, 2.0),
            "factor_blue": (0.0, 2.0),
            "saturation": (0.0, 2.0),
        },
        "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False,
                    "factor_red": 1.0, "factor_green": 1.0, "factor_blue": 1.0,
                    "saturation": 1.0},
        "scale_attr": None,
        "basis_offset": 0.0,
        # Worst over seeds 1-4 and 20260814: epilogue 1.4e-6, point 2.6e-7,
        # placement 7.8e-4. The placement budget is deliberately loose and still
        # meaningful. Magic's cascade is chaotic by design: each of up to ten
        # depths multiplies by `turbulence/5` (up to 2 here) and re-enters a
        # cos, so it amplifies its input by as much as ~2^10, and the check
        # feeds the engine a coordinate rounded to float by this script rather
        # than composed by the engine. At |q| ~ 15 that seed error is ~1e-6
        # before a 5x frequency multiplier, which lands exactly where the
        # measurements do. A genuinely wrong placement -- scale before offset,
        # a stray basis offset -- moves the pattern, not its last bits, and
        # shows up at O(1).
        "budget": {"epilogue": 3.0e-6, "placement": 3.0e-3, "point": 1.0e-6},
    },
    # Wood is graded as three cases, because its four wood types are not one
    # code path. Bands and Rings call no noise at all (wood_int, :204-231), so
    # they are pointwise-exact against Blender; Band Noise and Ring Noise add a
    # `vnoise` term and can only be compared as a distribution. The third case
    # pins turbulence at its RNA minimum, which drives the noise term to <= 1e-4
    # and so grades the *noisy* arms pointwise too -- everything about them
    # except the noise amplitude, which is what the field case is left to carry.
    'WOOD': [
        {
            "label": 'bands',
            "mode": 'point',
            "settings": {
                "wood_type": ('BANDS', 'RINGS'),
                "noise_basis_2": ('SIN', 'SAW', 'TRI'),
                # Randomized although these arms ignore them: noise_scale must
                # *not* move the bands (only BLI_noise_generic_noise divides by
                # it, and these arms never call it) and turbulence must not
                # either. Pinning them would leave both facts ungraded.
                "noise_scale": (0.1, 1.5),
                "turbulence": (0.0001, 10.0),
                "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
                "intensity": (0.0, 2.0),
                "contrast": (0.2, 2.5),
                "use_clamp": (True, False),
            },
            "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
            "scale_attr": None,
            "basis_offset": 0.0,
            # Bit-identical, like Blend: no noise call means no substituted
            # basis, and the exact `tex_saw` transcription in wood.stex leaves
            # nothing else to round. Worst over four seeds: epilogue 0,
            # placement 1.5e-5, point 0.
            "budget": {"epilogue": 1.0e-6, "placement": 1.0e-4, "point": 1.0e-6},
        },
        {
            "label": 'quiet-noise',
            "mode": 'point',
            "settings": {
                "wood_type": ('BANDNOISE', 'RINGNOISE'),
                "noise_basis_2": ('SIN', 'SAW', 'TRI'),
                "noise_scale": (0.1, 1.5),
                # The RNA minimum. `turb * t` with t in [0,1] is then bounded by
                # 1e-4 whatever the basis, so the two sides agree pointwise and
                # every part of these arms but the noise amplitude is graded.
                "turbulence": (0.0001, 0.0001),
                "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
                "intensity": (0.0, 2.0),
                "contrast": (0.2, 2.5),
                "use_clamp": (True, False),
            },
            "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
            "scale_attr": None,
            "basis_offset": 0.0,
            # The residual *is* the pinned turbulence, so these two track the
            # 1e-4 bound rather than float error. Worst over four seeds:
            # epilogue 8.0e-5, placement 1.5e-5, point 4.6e-5.
            "budget": {"epilogue": 3.0e-4, "placement": 1.0e-4, "point": 3.0e-4},
        },
        {
            "label": 'noise',
            "mode": 'field',
            "settings": {
                "wood_type": ('BANDNOISE', 'RINGNOISE'),
                "noise_basis_2": ('SIN', 'SAW', 'TRI'),
                "noise_scale": (0.1, 1.5),
                "turbulence": (0.0001, 10.0),
                "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
                "intensity": (0.0, 2.0),
                "contrast": (0.2, 2.5),
                "use_clamp": (True, False),
            },
            "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
            "scale_attr": None,
            "basis_offset": 0.0,
            # Worst over four seeds: epilogue 8.9e-8, placement 2.7e-5,
            # mean 0.0107, sd 0.0039. The two distribution budgets sit at the
            # same ~3x that clouds.stex carries -- they are seed-varying
            # statistics over a *different* noise basis, so headroom there is
            # not slack.
            "budget": {"epilogue": 1.0e-6, "placement": 1.0e-4,
                       "mean": 0.03, "sd": 0.012},
        },
    ],
    # Marble splits the same way, minus a noise-free wood type to lean on:
    # marble_int always adds turbulence, so its pointwise case is the quiet one.
    'MARBLE': [
        {
            "label": 'quiet',
            "mode": 'point',
            "settings": {
                "marble_type": ('SOFT', 'SHARP', 'SHARPER'),
                "noise_basis_2": ('SIN', 'SAW', 'TRI'),
                "noise_scale": (0.1, 1.5),
                "noise_depth": (0, 5),
                "turbulence": (0.0001, 0.0001),
                "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
                "intensity": (0.0, 2.0),
                "contrast": (0.2, 2.5),
                "use_clamp": (True, False),
            },
            "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
            "scale_attr": None,
            "basis_offset": 0.0,
            # Looser than Wood's twin case, and the one budget here that is not
            # a rounded-up measurement: Sharper takes two square roots of the
            # waveform, and d/dv sqrt(sqrt(v)) is unbounded as v -> 0, so the
            # pinned 1e-4 comes back out amplified by however close a drawn
            # sample lands to a zero of the waveform. That is a draw, not a
            # trend -- over four seeds `point` ranged 1.9e-4 to 7.6e-4, a 4x
            # spread with no fix available on the engine side -- so this keeps
            # an order of headroom rather than tracking the observed worst.
            # epilogue observed 1.1e-4, placement 6.8e-6.
            "budget": {"epilogue": 1.0e-3, "placement": 1.0e-4, "point": 1.0e-2},
        },
        {
            "label": 'veined',
            "mode": 'field',
            "settings": {
                "marble_type": ('SOFT', 'SHARP', 'SHARPER'),
                "noise_basis_2": ('SIN', 'SAW', 'TRI'),
                "noise_scale": (0.1, 1.5),
                "noise_depth": (0, 5),
                "turbulence": (0.0001, 10.0),
                "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
                "intensity": (0.0, 2.0),
                "contrast": (0.2, 2.5),
                "use_clamp": (True, False),
            },
            "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
            "scale_attr": None,
            "basis_offset": 0.0,
            # Worst over four seeds: epilogue 8.8e-8, placement 2.3e-5,
            # mean 0.0082, sd 0.0042.
            "budget": {"epilogue": 1.0e-6, "placement": 1.0e-4,
                       "mean": 0.03, "sd": 0.012},
        },
    ],
    'STUCCI': {
        # The one ported type whose value *is* the noise -- no waveform to fall
        # back on -- so it is field-only, and the one that runs no epilogue at
        # all: `stucci()` returns after `max(tin, 0)` with no BRICONT
        # (:393-397). intensity/contrast/use_clamp are still randomized so that
        # the `epilogue: none` model asserts both sides ignore them.
        "mode": 'field',
        "epilogue": 'none',
        "settings": {
            "stucci_type": ('PLASTIC', 'WALL_IN', 'WALL_OUT'),
            "noise_scale": (0.1, 1.5),
            "turbulence": (0.0001, 10.0),
            "noise_type": ('SOFT_NOISE', 'HARD_NOISE'),
            "intensity": (0.0, 2.0),
            "contrast": (0.2, 2.5),
            "use_clamp": (True, False),
        },
        "neutral": {"intensity": 0.5, "contrast": 1.0, "use_clamp": False},
        "scale_attr": None,
        "basis_offset": 0.0,
        # Worst over four seeds: epilogue 0 (exactly -- `none` is the identity
        # on both sides), placement 6.3e-6, mean 0.0121, sd 0.0067. The
        # distribution budgets are the loosest of the three field cases because
        # Stucci's value *is* the substituted noise, with no waveform in front
        # of it to compress the two bases together.
        "budget": {"epilogue": 1.0e-6, "placement": 1.0e-4,
                   "mean": 0.03, "sd": 0.02},
    },
}

CASES = 8


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {"samples": 8000, "seed": 20260814, "types": None, "verbose": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--verbose":
            args["verbose"] = True
        elif a == "--samples":
            i += 1
            args["samples"] = int(argv[i])
        elif a == "--seed":
            i += 1
            args["seed"] = int(argv[i])
        elif a == "--type":
            i += 1
            args["types"] = (args["types"] or []) + [argv[i].upper()]
        else:
            raise SystemExit("verify_texture_parity: unknown argument {!r}".format(a))
        i += 1
    return args


def randomize(tex, spec, rng):
    """Draw one settings combination and write it onto `tex`, returning the
    values actually applied (RNA may clamp or reject)."""
    applied = {}
    for name, choices in spec.items():
        if (len(choices) == 2 and all(isinstance(c, (int, float)) for c in choices)
                and not isinstance(choices[0], bool)):
            lo, hi = choices
            val = rng.randint(lo, hi) if isinstance(lo, int) and isinstance(hi, int) \
                else rng.uniform(lo, hi)
        else:
            val = rng.choice(choices)
        setattr(tex, name, val)
        applied[name] = getattr(tex, name)
    return applied


def points(rng, count, extent=EXTENT):
    return [(rng.uniform(-extent, extent),
             rng.uniform(-extent, extent),
             rng.uniform(-extent, extent)) for _ in range(count)]


def stratified(rng, count, extent):
    """`count` points on a jittered regular grid. Plain uniform sampling leaves
    the sample mean with an O(N^-1/2) error of its own, which at these counts is
    the same size as the field difference being measured; one point per cell
    puts it near O(N^-1) and makes the statistic reproducible."""
    side = max(2, round(count ** (1.0 / 3.0)))
    step = 2.0 * extent / side
    return [(-extent + (i + rng.random()) * step,
             -extent + (j + rng.random()) * step,
             -extent + (k + rng.random()) * step)
            for i in range(side) for j in range(side) for k in range(side)]


def oracle(tex, p):
    """Blender's own intensity for this texture at `p`, following
    RE_texture_evaluate's tail."""
    v = tex.evaluate(p)
    if texture._returns_rgb(tex):
        return LUMA[0] * v[0] + LUMA[1] * v[1] + LUMA[2] * v[2]
    return v[3]


def bind(tex, bl_brush, sc_brush):
    """Recompile + repush, and fail loudly rather than silently comparing a
    stale program (the settings ride the param slab, so a missed push looks
    like a wrong port)."""
    idx = texture.bind_script(tex, sc_brush, bl_brush)
    assert idx is not None, "bind_script declined: no script, unsupported " \
                            "settings, or a compile failure"
    assert not sc_brush.textureUsesMap(), \
        "script reads mapPoint(); a null map context makes it identity, so it " \
        "must be driven through a stroke instead"
    return idx


def sample_both(tex, bl_brush, sc_brush, pts):
    bind(tex, bl_brush, sc_brush)
    return ([texture.eval_texture_at(sc_brush, p) for p in pts],
            [oracle(tex, p) for p in pts])


def with_settings(tex, values):
    """Apply `values`, returning the previous ones for restoration."""
    saved = {k: getattr(tex, k) for k in values}
    for k, v in values.items():
        setattr(tex, k, v)
    return saved


def variants(specs):
    """A type's descriptor is either one spec or a list of them. Wood is the
    reason: two of its four wood types call no noise at all, so those deserve
    the pointwise grade while Band/Ring Noise can only be graded as a
    distribution, and one `mode` per type cannot say that."""
    return specs if isinstance(specs, list) else [specs]


def bricont(raw, bright, contrast, clamped):
    """texture_common.h:15-25. `raw` is the value under neutral settings, i.e.
    the pattern already shifted by BRICONT's own -0.5."""
    v = raw * contrast + bright - 0.5
    return min(1.0, max(0.0, v)) if clamped else v


def no_epilogue(raw, bright, contrast, clamped):
    """The model for a type that runs *no* epilogue. Stucci is the only one:
    `stucci()` returns straight after `max(tin, 0)` with no BRICONT
    (texture_procedural.cc:393-397) and RE_texture_evaluate adds none, so
    intensity/contrast/use_clamp are inert. Grading it as the identity — with
    those settings still randomized — asserts that inertness on both sides
    rather than declining to check."""
    return raw


EPILOGUES = {'bricont': bricont, 'none': no_epilogue}


def check_epilogue(tex, bl_brush, sc_brush, spec, pts):
    """What the drawn intensity/contrast/clamp do to the raw pattern.

    A `mode='point'` type shares Blender's pattern, so the two sides are simply
    diffed at the drawn settings — no model to be wrong about, and it grades the
    whole per-type epilogue (Magic's BRICONTRGB channel factors, lower-only
    clamp and saturation are not BRICONT and no shared scalar model covers
    them). Only a substituted basis needs the model below."""
    if spec["mode"] == 'point':
        sc_out, bl_out = sample_both(tex, bl_brush, sc_brush, pts)
        return trimmed_max([abs(a - b) / max(1.0, abs(b))
                            for a, b in zip(sc_out, bl_out)])

    saved = with_settings(tex, spec["neutral"])
    sc_raw, bl_raw = sample_both(tex, bl_brush, sc_brush, pts)
    with_settings(tex, saved)
    sc_out, bl_out = sample_both(tex, bl_brush, sc_brush, pts)

    model = EPILOGUES[spec.get("epilogue", 'bricont')]
    bright, contrast, clamped = tex.intensity, tex.contrast, tex.use_clamp
    errs = []
    for raws, outs in ((sc_raw, sc_out), (bl_raw, bl_out)):
        for raw, out in zip(raws, outs):
            want = model(raw, bright, contrast, clamped)
            errs.append(abs(out - want) / max(1.0, abs(want)))
    return trimmed_max(errs)


def placed(p, spec, size, ofs, scale):
    """The coordinate the pattern is actually sampled at."""
    off = spec.get("basis_offset", 0.0)
    return tuple(((p[i] + ofs[i]) * size[i] + off) / scale for i in range(3))


def check_placement(tex, bl_brush, sc_brush, spec, pts, rng):
    """Both sides must place the pattern the way RE_texture_evaluate +
    BLI_noise_generic_turbulence do. The reference configuration is the identity
    one -- unit slot, unit scale -- whose own transform is a bare `+
    basis_offset`, so the point fed to it is `placed(p) - basis_offset`."""
    saved = with_settings(tex, spec["neutral"])
    scale_attr = spec["scale_attr"]
    scale = getattr(tex, scale_attr) if scale_attr else 1.0
    off = spec.get("basis_offset", 0.0)
    slot = bl_brush.texture_slot
    size = (rng.uniform(0.3, 3.0), rng.uniform(0.3, 3.0), rng.uniform(0.3, 3.0))
    ofs = (rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0))

    slot.scale, slot.offset = size, ofs
    bind(tex, bl_brush, sc_brush)
    moved = [texture.eval_texture_at(sc_brush, p) for p in pts]
    # Texture.evaluate applies no slot placement, so Blender's half of the
    # identity is the type's own scale only.
    bl_moved = [oracle(tex, p) for p in pts]

    slot.scale, slot.offset = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if scale_attr:
        setattr(tex, scale_attr, 1.0)
    bind(tex, bl_brush, sc_brush)
    errs = []
    for p, want, bl_want in zip(pts, moved, bl_moved):
        q = placed(p, spec, size, ofs, scale)
        errs.append(abs(texture.eval_texture_at(
            sc_brush, tuple(c - off for c in q)) - want))
        bl_q = placed(p, spec, (1.0, 1.0, 1.0), (0.0, 0.0, 0.0), scale)
        errs.append(abs(oracle(tex, tuple(c - off for c in bl_q)) - bl_want))

    if scale_attr:
        setattr(tex, scale_attr, scale)
    with_settings(tex, saved)
    return trimmed_max(errs)


def check_field(tex, bl_brush, sc_brush, spec, rng, samples):
    """The pattern itself: pointwise for a shared basis, distribution for a
    substituted one.

    The box is widened by the type's own scale so that it always spans the same
    number of noise cells: a distribution measured over a fixed sculpt-space box
    has a sample mean whose variance grows with noise_scale, which reads as a
    budget failure at large scales and hides a real shift at small ones."""
    scale_attr = spec["scale_attr"]
    extent = FIELD_EXTENT * (getattr(tex, scale_attr) if scale_attr else 1.0)
    pts = stratified(rng, samples, extent)
    saved = with_settings(tex, spec["neutral"])
    sc_raw, bl_raw = sample_both(tex, bl_brush, sc_brush, pts)
    with_settings(tex, saved)
    if spec["mode"] == 'point':
        return {"point": trimmed_max([abs(a - b) / max(1.0, abs(b))
                                      for a, b in zip(sc_raw, bl_raw)])}
    return {"mean": abs(statistics.fmean(sc_raw) - statistics.fmean(bl_raw)),
            "sd": abs(statistics.pstdev(sc_raw) - statistics.pstdev(bl_raw))}


def main():
    args = parse_args()
    # Everything with a .stex, not just the subset apply_texture routes today:
    # a type has to pass here *before* it is added to _SCRIPT_TYPES.
    types = args["types"] or sorted(texture._SCRIPT_FILES)
    unknown = [t for t in types if t not in texture._SCRIPT_FILES]
    if unknown:
        raise SystemExit("verify_texture_parity: no .stex for: {}".format(unknown))

    mgr = engine.manager()  # loads the native library, or raises
    bl_brush = bpy.data.brushes.new("sc_parity", mode='SCULPT')

    failures = []
    graded = 0
    for tex_type in types:
        specs = TYPES.get(tex_type)
        if specs is None:
            failures.append("{:s}: has a .stex but no TYPES entry -- a ported "
                            "type must ship its harness case".format(tex_type))
            continue
        for spec in variants(specs):
            graded += 1
            name = "{:s}/{:s}".format(tex_type, spec["label"]) \
                if "label" in spec else tex_type
            budget = spec["budget"]
            rng = random.Random(args["seed"])
            tex = bpy.data.textures.new("sc_parity_" + name, type=tex_type)
            bl_brush.texture = tex
            worst = {}
            for case in range(CASES):
                bl_brush.texture_slot.scale = (1.0, 1.0, 1.0)
                bl_brush.texture_slot.offset = (0.0, 0.0, 0.0)
                applied = randomize(tex, spec["settings"], rng)
                sc_brush = mgr.construct('sculptcore::brush::Brush')
                pts = points(rng, PROBE_POINTS)
                observed = {
                    "epilogue": check_epilogue(tex, bl_brush, sc_brush, spec, pts),
                    "placement": check_placement(tex, bl_brush, sc_brush, spec, pts, rng),
                }
                observed.update(check_field(tex, bl_brush, sc_brush, spec, rng,
                                            args["samples"]))
                if args["verbose"]:
                    print("  {:s} case {:d}: {:s}\n      {!r}".format(
                        name, case,
                        "  ".join("{:s}={:.6g}".format(k, v)
                                  for k, v in observed.items()),
                        applied))
                for key, value in observed.items():
                    worst[key] = max(worst.get(key, 0.0), value)
                    if value > budget[key]:
                        failures.append(
                            "{:s} case {:d}: {:s} {:.6g} over budget {:g}\n    {!r}".format(
                                name, case, key, value, budget[key], applied))
            print("verify_texture_parity: {:s} ({:s}) {:s}".format(
                name, spec["mode"],
                "  ".join("{:s}={:.6g}/{:g}".format(k, v, budget[k])
                          for k, v in worst.items())))

    if failures:
        for msg in failures:
            sys.stderr.write("verify_texture_parity: FAILED: {:s}\n".format(msg))
        sys.exit(1)

    print("verify_texture_parity: {:d} case(s) over {:d} type(s) within "
          "budget".format(graded, len(types)))


main()
