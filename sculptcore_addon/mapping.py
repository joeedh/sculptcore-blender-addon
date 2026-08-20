# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Blender Brush -> SculptCore Brush mapping (declarative table).

M1: the per-dab sculpting brushes. Each entry names the SculptCore kernel
and (optionally) per-type field values applied on stroke start. World-space
radius unprojection is the stroke operator's job; this layer copies
engine-space fields only.

Pose is intentionally *not* supported yet: it needs per-stroke pose-cage
anchor state a bare per-dab ``execBrush`` doesn't set up (and crashes
without it). ``kernel_enum`` returns None for it so the stroke operator
refuses cleanly rather than crashing.
"""

# Engine constants for the device-dynamics seam (brush.h BrushProp ids,
# prop_dynamics.h DeviceType, litestl mix.h BasicMix). The string-keyed
# dynamics API is unreachable from Python (util::string args), so the stroke
# operator configures pressure through these int-keyed ids.
PROP_STRENGTH = 0
PROP_RADIUS = 1
DEVICE_PRESSURE = 0
MIX_MULTIPLY = 1

# Blender sculpt_brush_type -> (SculptCore SculptBrushes name, extra fields).
# `extra` is a dict of SculptCore Brush field -> value/callable(bl_brush).
# Verified per-dab via the parity harness (test_brush_parity).
_MAP = {
    'DRAW': ("DRAW", {}),
    # Vanilla Draw Sharp is a plain normal-offset draw with falloff factors
    # from original coordinates (do_draw_sharp_brush) — no pinch. pinch is
    # reset explicitly because the session Brush is shared across strokes and
    # a prior PINCH stroke would otherwise leak its value into SHARP.
    'DRAW_SHARP': ("SHARP", {"pinch": 0.0}),
    'INFLATE': ("INFLATE", {}),
    # Layer rides the layerdraw kernel: the dab writes a sculpt-layer channel
    # (recomposited by weight) instead of base co, so a stroke can be
    # re-weighted or disabled after the fact. The stroke operator creates the
    # write target on first use (layers.ensure_stroke_target); vanilla's
    # height cap and persistent base are out of scope for now.
    'LAYER': ("LAYERDRAW", {}),
    # Clay + plane family: map the plane offset; the default plane side (+1)
    # produces sensible output at a convex surface (a -1 scrape side finds
    # nothing above the tangent plane on a sphere). Blender's 'PLANE' is the
    # unified flatten/fill brush and 'MULTIPLANE_SCRAPE' the scrape; precise
    # per-mode side/offset semantics is a later refinement.
    'CLAY': ("CLAY", {"planeoff": lambda b: b.plane_offset}),
    'CLAY_STRIPS': ("CLAY", {"planeoff": lambda b: b.plane_offset}),
    'PLANE': ("FILL", {"planeoff": lambda b: b.plane_offset}),
    'MULTIPLANE_SCRAPE': ("SCRAPE", {"planeoff": lambda b: b.plane_offset}),
    # BSMOOTH (boundary-aware smooth): identical to plain SMOOTH on meshes
    # with no marked feature edges. Seam/sharp edge flags transfer to the
    # engine on enter (convert._load_edge_flags), so marked features hold
    # under smoothing (verified: a sharp-marked crest erodes 0% vs 66% of its
    # height unmarked — claudeMemory/tests/bsmooth_boundary_test.py).
    'SMOOTH': ("BSMOOTH", {}),
    'PINCH': ("PINCH", {"pinch": lambda b: b.strength}),
    # Nudge runs an addon-carried extra kernel (brushes/nudge.sbrush), compiled
    # into the DLL at build time; a stale vendored DLL without it makes
    # kernel_enum return None and the stroke cancel cleanly. Its tunable
    # (nudgeProjection) is a namedFloats store uniform written by
    # engine_props.apply, so no per-stroke field reset is needed here.
    'NUDGE': ("NUDGE", {}),
    'MASK': ("MASK", {}),
    # Vertex paint: brushColor synced from the Blender brush color (see
    # apply_brush); writes the `color` float4 vertex attr.
    'PAINT': ("COLOR", {}),
    # Face sets: paint the `group` face attr; the stroke operator assigns a
    # fresh active group id per stroke (see FACE_SET_TYPES).
    'DRAW_FACE_SETS': ("POLYGROUP", {}),
    # Snake hook dabs along the stroke, but its kernel is driven by the grab
    # ctx vectors (`@incremental`, see is_snake_hook); the stroke operator sets
    # them per dab image and advances the dab center with the extruded tip.
    # Blender's pinch
    # control (crease_pinch_factor, labelled "Magnify" for this brush) is 0..1
    # with 0.5 neutral and pinching below it; the kernel takes the engine's
    # 0-means-off convention, so remap here — 2 * (0.5 - factor), positive
    # pinching in, negative inflating. Written on every snake-hook stroke, so
    # the shared `pinch` member cannot leak in from a prior PINCH stroke.
    'SNAKE_HOOK': ("SNAKEHOOK", {"pinch": lambda b: 2.0 * (0.5 - b.crease_pinch_factor)}),
    # Grab dabs at a fixed anchor and reads the cumulative cursor delta
    # (grabTo/grabFrom); the stroke operator drives it via the grab-class path.
    'GRAB': ("GRAB", {}),
    # Elastic deform = a Kelvinlet soft-body grab (same grabFrom/grabTo state,
    # engine mu/nu defaults ~ soft rubber).
    'ELASTIC_DEFORM': ("KELVINLET", {}),
    # Thumb is Grab with the drag flattened into the surface, so it smears
    # sideways instead of pulling out — same kernel, different vector (see
    # TANGENT_DRAG).
    'THUMB': ("GRAB", {}),
}

# Brush types whose cursor drag is projected into the tangent plane of the
# stroke's sculpt normal before the GRAB kernel sees it, and scaled by strength
# — vanilla's do_thumb_brush (`cross(cross(n, delta), n) * bstrength`; Grab
# itself drags by the raw delta and ignores strength). This is not engine
# policy: the kernel is the same anchored from-orig grab either way and only
# the vector the host hands it differs, so it belongs in a host table next to
# _MAP rather than in a kernel annotation.
TANGENT_DRAG = {'THUMB'}


def drag_offset(bl_brush, delta, normal, strength):
    """The object-space drag to hand the GRAB kernel for one grab dab, given the
    raw cursor delta. Identity outside TANGENT_DRAG."""
    if bl_brush.sculpt_brush_type not in TANGENT_DRAG:
        return delta

    import mathutils

    n = mathutils.Vector(normal)
    if n.length_squared == 0.0:
        return delta
    n.normalize()
    d = mathutils.Vector(delta)
    return tuple(n.cross(d).cross(n) * strength)

# Types whose vanilla brush adds its offset EVERY dab regardless of the
# Accumulate toggle (do_draw_sharp_brush has no accumulate branch; its
# "sharp" stability comes from orig-coordinate falloff factors, not from
# capping displacement). The engine's nonAccum instead freezes the stroke at
# single-dab depth — near-invisible for a subtle brush — so the operator
# forces per-dab accumulation for these.
FORCE_ACCUMULATE = {'DRAW_SHARP'}

# Per-type strength compensation folded into every dab. The engine SHARP
# kernel displaces by strength * radius * 0.5; vanilla's draw-sharp offset is
# normal * radius * strength (no 0.5), so double the strength to match.
STRENGTH_SCALE = {'DRAW_SHARP': 2.0}

# Brush types that paint face sets — the operator assigns a fresh `activeGroup`
# id (max existing + 1) at stroke start.
FACE_SET_TYPES = {'DRAW_FACE_SETS'}

# Brush types that paint the `color` vertex attr — on multires, the only ones
# that pay for the cage colour write-back (convert.sync_cage_vert_color).
COLOR_TYPES = {'PAINT'}

# Kernels that exist but need infrastructure not wired yet — kept for
# reference / a future UI "unsupported" hint, never entered.
UNSUPPORTED = {
    'POSE': "needs the pose-cage anchor path",
}


def _policy(bl_brush):
    """The engine-declared policy for the kernel this Blender brush maps to.
    Which brush type maps to which kernel is a host decision (the table above);
    how that kernel wants to be driven is not — it is queried, never listed
    here, so a kernel's annotations can change without a host edit."""
    from . import brush_policy, engine

    if bl_brush is None:
        return brush_policy.for_kernel(None)
    return brush_policy.for_kernel(kernel_enum(engine.manager(), bl_brush))


def is_grab_class(bl_brush):
    """Anchored, from-orig grab (`@grabmode`): the dab stays at the stroke's
    anchor and the deform follows the cumulative cursor delta, rather than
    dabbing along the stroke at the moving cursor."""
    return _policy(bl_brush).grab_mode_capable


def is_snake_hook(bl_brush):
    """Path-style grab (`@incremental`): the kernel reads the grab ctx vectors
    — grabFrom is the dab center, grabTo the step since the previous dab, and
    it gathers toward grabFrom + grabTo — but keeps dabbing along the stroke, so
    it takes the normal (spacer / preview) path rather than the anchored one.
    Left unset, both vectors default to the origin and the kernel contracts
    geometry toward the object origin instead of hooking. The spacer path also
    walks the dab center out with the extruded tip rather than raycasting each
    sample — see stroke._snake_hook_advance."""
    return _policy(bl_brush).incremental


def pressure_prop_names(bl_brush):
    """The ``(strength, size)`` pen-pressure toggle property names to draw and
    read for ``bl_brush`` — Blender's own where they mean something there, this
    addon's shadow toggles (props._PRESSURE_PROPS) where they do not.

    Vanilla gates each row on ``sculpt_capabilities.has_*_pressure``, so on a
    brush where that reads False its ``use_pressure_*`` is never drawn and never
    consulted; whatever the shipped asset happens to store is noise (the Snake
    Hook asset stores strength pressure on). This mode drives those brushes with
    pressure all the same, so it substitutes toggles it owns — same rows, same
    response curves, but a default it controls: off, which is what vanilla
    effectively does. Brushes vanilla does support keep their own flags, so
    nothing an artist already set changes.
    """
    caps = bl_brush.sculpt_capabilities
    return (
        "use_pressure_strength" if caps.has_strength_pressure
        else "sculptcore_use_pressure_strength",
        "use_pressure_size" if caps.has_size_pressure
        else "sculptcore_use_pressure_size",
    )


# SculptCore FalloffKind / FalloffShape enum values (brush.h).
_FALLOFF_KIND_CURVE = 3
_FALLOFF_SHAPE_SPHERICAL = 0
_FALLOFF_CURVE_SIZE = 256


# Closed-form preset falloffs, keyed by `curve_distance_falloff_preset`. `t`
# is 1 - normalized distance (1 at center, 0 at edge) — the same value the
# engine feeds falloffEval. Mirrors BKE_brush_curve_strength so brush feel
# matches Blender exactly; CUSTOM samples the editable CurveMapping instead.
_PRESET_FALLOFF = {
    'SHARP': lambda t: t * t,
    'SMOOTH': lambda t: 3.0 * t * t - 2.0 * t * t * t,
    'SMOOTHER': lambda t: t * t * t * (t * (t * 6.0 - 15.0) + 10.0),
    'ROOT': lambda t: t ** 0.5,
    'LIN': lambda t: t,
    'CONSTANT': lambda t: 1.0,
    'SPHERE': lambda t: max(0.0, 2.0 * t - t * t) ** 0.5,
    'POW4': lambda t: t * t * t * t,
    'INVSQUARE': lambda t: t * (2.0 - t),
}


def _upload_lut(cache, key, values, setter):
    """Push a baked 256-entry LUT to the engine, skipping it when the same
    table was uploaded last time.

    Every entry crosses the ctypes marshaller separately (~0.08 ms), so a
    re-upload costs far more than the bake that produced it, and a stroke
    almost never changes the curve. ``cache`` is the session's dict (None
    disables the memo); the baked values themselves are the identity, so an
    actual curve edit still re-uploads.
    """
    values = tuple(values)
    if cache is not None and cache.get(key) == values:
        return
    for i, value in enumerate(values):
        setter(i, value)
    if cache is not None:
        cache[key] = values


def _bake_falloff(bl_brush, sc_brush, cache=None):
    """Bake the Blender falloff (preset formula, or the editable curve for
    CUSTOM) into the engine's 256-entry LUT, folding in `hardness`, so brush
    feel matches Blender. `t` = 1 - normalized distance (the value the engine
    feeds falloffEval); hardness remaps the distance before the falloff so the
    inner `hardness` fraction reads full strength."""
    fn = _PRESET_FALLOFF.get(bl_brush.curve_distance_falloff_preset)
    if fn is None:  # CUSTOM: strength(p) = curve(1 - p), matching BKE.
        cumap = bl_brush.curve_distance_falloff
        cumap.update()
        curve = cumap.curves[0]
        def fn(p, _c=cumap, _cv=curve):
            return _c.evaluate(_cv, 1.0 - p)

    hardness = min(1.0, max(0.0, bl_brush.hardness))
    n = _FALLOFF_CURVE_SIZE
    lut = []
    for i in range(n):
        t = i / (n - 1)
        d = 1.0 - t  # normalized distance
        if hardness >= 1.0:
            v = 1.0 if d < 1.0 else 0.0  # hard disc
        elif hardness > 0.0:
            v = 1.0 if d < hardness else fn(1.0 - (d - hardness) / (1.0 - hardness))
        else:
            v = fn(t)
        lut.append(min(1.0, max(0.0, v)))
    _upload_lut(cache, "falloff", lut, sc_brush.setFalloffCurveEntry)
    sc_brush.falloff_kind = _FALLOFF_KIND_CURVE
    # PROJECTED (2D view falloff) has no distinct engine metric yet; both use
    # the spherical distance for now.
    sc_brush.falloff_shape = _FALLOFF_SHAPE_SPHERICAL


# Cavity automasking. The engine mirrors Blender's estimator and remap
# (automask.h, ported from `calc_cavity_factor`), so the mapping is a direct
# field copy plus the optional custom curve baked into the engine's LUT.
_CAVITY_CURVE_SIZE = 256


def cavity_settings(bl_brush, paint):
    """The `MeshAutomaskingSettings` that governs cavity for this stroke, or
    None when cavity automasking is off.

    Mirrors Blender's `automasking_flags_get` precedence: the brush's own
    cavity flags win when it enables either cavity mode, otherwise the
    Paint-level settings apply."""
    for settings in (bl_brush.mesh_automasking_settings if bl_brush else None,
                     paint.mesh_automasking_settings if paint else None):
        if settings is not None and (settings.use_automasking_cavity
                                     or settings.use_automasking_cavity_inverted):
            return settings
    return None


def _apply_cavity(settings, sc_brush, cache=None):
    """Copy the resolved cavity settings onto the engine brush. The executor
    pre-fills a per-vertex factor once per stroke when `automask_cavity` is
    set; every kernel that reads the strength intrinsic is masked by it."""
    if settings is None:
        sc_brush.automask_cavity = False
        return

    sc_brush.automask_cavity = True
    sc_brush.cavity_inverted = bool(settings.use_automasking_cavity_inverted)
    sc_brush.cavity_factor = settings.cavity_factor
    sc_brush.cavity_blur_steps = settings.cavity_blur_steps

    use_curve = bool(settings.use_automasking_custom_cavity_curve)
    sc_brush.cavity_use_curve = use_curve
    if not use_curve:
        return
    # The engine samples the LUT in un-inverted space and inverts afterwards,
    # the same order Blender evaluates the curve in, so bake it as authored.
    cumap = settings.cavity_curve
    cumap.update()
    curve = cumap.curves[0]
    n = _CAVITY_CURVE_SIZE
    lut = [min(1.0, max(0.0, cumap.evaluate(curve, i / (n - 1)))) for i in range(n)]
    _upload_lut(cache, "cavity", lut, sc_brush.setCavityCurveEntry)


# Pen-pressure response curves. Blender maps tablet pressure to a strength /
# size factor through the Brush.curve_strength / Brush.curve_size
# CurveMappings (vanilla BKE_curvemapping_evaluateF(curve, 0, pressure)). The
# engine mirrors this with a per-device response table (prop_dynamics.h
# DynamicDevice.curveTable); the smooth brush folds pressure in Python-side, so
# the same table is also sampled directly. Baked once per stroke, never per dab.
_PRESSURE_CURVE_SIZE = 256


def sample_pressure_curve(cumap):
    """Sample a Blender pressure CurveMapping into a list mapping pressure
    (0..1, in ``_PRESSURE_CURVE_SIZE`` steps) to a response factor, matching
    vanilla's ``BKE_curvemapping_evaluateF(curve, 0, pressure)``."""
    cumap.update()
    curve = cumap.curves[0]
    n = _PRESSURE_CURVE_SIZE
    return [cumap.evaluate(curve, i / (n - 1)) for i in range(n)]


def eval_pressure_lut(lut, pressure):
    """Look up a pressure factor in a table from ``sample_pressure_curve``,
    using the same clamped linear interpolation as the engine's ``deviceFactor``
    so the Python-side (smooth) and engine-side paths agree."""
    n = len(lut)
    x = min(1.0, max(0.0, pressure)) * (n - 1)
    i = int(x)
    if i >= n - 1:
        return lut[n - 1]
    t = x - i
    return lut[i] * (1.0 - t) + lut[i + 1] * t


def apply_pressure_dynamics(bl_brush, sc_brush, *, use_strength, use_size, cache=None):
    """Configure the engine's per-stroke pressure dynamics: a MULTIPLY device
    layer per pressure-enabled channel, carrying the baked response curve from
    the matching Brush CurveMapping. Runs once per stroke (the 256-sample bakes
    are far too slow per dab); the stroke operator refills the device sample
    with the event pressure each dab. Passing both flags false — a smooth or
    grab-class stroke — clears both channels, so no stale dynamic survives.

    ``cache`` is the session's curve memo: a stroke asking for the configuration
    the engine already holds reuses it instead of re-marshalling 512 samples
    across the ctypes boundary."""
    # addPropDynamic appends a device with an *identity* curve, so the samples
    # can never be memoized on their own — the memo has to cover the whole
    # clear/add/upload, i.e. skip it only when the engine already holds exactly
    # this configuration.
    want = (tuple(sample_pressure_curve(bl_brush.curve_strength)) if use_strength else None,
            tuple(sample_pressure_curve(bl_brush.curve_size)) if use_size else None)
    if cache is not None and cache.get("pressure") == want:
        return

    sc_brush.clearPropDynamics(PROP_STRENGTH)
    sc_brush.clearPropDynamics(PROP_RADIUS)
    for prop_id, table in ((PROP_STRENGTH, want[0]), (PROP_RADIUS, want[1])):
        if table is None:
            continue
        sc_brush.addPropDynamic(prop_id, DEVICE_PRESSURE, MIX_MULTIPLY, 1.0)
        n = len(table)
        for i, value in enumerate(table):
            sc_brush.setPropDynamicSample(prop_id, DEVICE_PRESSURE, i, n, value)
    if cache is not None:
        cache["pressure"] = want


# For UI / diagnostics: every mapped type (supported or not).
KERNEL_BY_TYPE = {t: v[0] for t, v in _MAP.items()}


def is_supported(bl_brush):
    return bl_brush is not None and bl_brush.sculpt_brush_type in _MAP


def kernel_enum(mgr, bl_brush):
    """The SculptBrushes enum value for a Blender brush, or None when the
    brush type is not supported for sculpting yet — or when the loaded DLL
    lacks the kernel (a stale vendored build without an extra kernel)."""
    entry = _MAP.get(bl_brush.sculpt_brush_type)
    if entry is None:
        return None
    value = mgr.get("sculptcore::brush::SculptBrushes").items.get(entry[0])
    return None if value is None else int(value)


def apply_brush_settings(bl_brush, unified, sc_brush, *, paint=None, cache=None):
    """Configure the stroke-constant part of a SculptCore Brush from a
    Blender Brush: the scalar settings, per-type extras, and the falloff /
    cavity curve bakes. The bakes are 256 engine calls each (~3-5 ms), far
    too slow for the per-dab path, and none of their inputs can change while
    a stroke is running — so this runs once at stroke start and
    ``apply_dab_state`` writes the per-dab values on top.

    ``unified`` is the per-Paint ``UnifiedPaintSettings`` (may be None).
    ``paint`` is the owning ``Paint`` (``tool_settings.sculpt``), consulted
    for automasking settings the brush itself does not override; without it
    only the brush's own settings apply.
    """
    strength = bl_brush.strength
    if unified is not None and unified.use_unified_strength:
        strength = unified.strength

    sc_brush.strength = strength
    sc_brush.spacing = max(bl_brush.spacing, 1) / 100.0  # percent -> fraction

    entry = _MAP.get(bl_brush.sculpt_brush_type)
    if entry is not None:
        for field, value in entry[1].items():
            setattr(sc_brush, field, value(bl_brush) if callable(value) else value)

    if bl_brush.sculpt_brush_type == 'PAINT':
        col = bl_brush.color  # linear RGB
        bc = sc_brush.brushColor.vec
        bc[0], bc[1], bc[2], bc[3] = col[0], col[1], col[2], 1.0

    _bake_falloff(bl_brush, sc_brush, cache)
    _apply_cavity(cavity_settings(bl_brush, paint), sc_brush, cache)

    # Generated engine-only uniforms (Brush.sculptcore, brush-mapping M2) —
    # after the mapping so table-driven fields keep authority.
    from . import engine_props
    engine_props.apply(bl_brush, sc_brush)


def overlap_attenuation(bl_brush):
    """Vanilla's "Adjust Strength for Spacing"
    (#paint_stroke_integrate_overlap): normalize the strength by the
    worst-case sum of overlapping falloff dabs along the stroke line,
    sampled at 10 phase offsets. 1.0 when the flag is off or spacing has no
    overlap (>= 100%).

    Never applied to the drag brushes (is_grab_class / is_snake_hook): vanilla
    reads their strength straight off the brush (`brush_strength`'s
    `root_alpha * feather` for GRAB and SNAKE_HOOK, no `overlap` term), and the
    compensation would be wrong anyway — it cancels the repeated *additive*
    dabs of an offset brush, whereas a drag brush's dabs each carry their own
    step, summing to the cursor's total drag no matter how many there are.
    Attenuating it just leaves the hook short of the cursor by 1/peak (a 5x
    shortfall at the Snake Hook asset's 10% spacing)."""
    if not (bl_brush.use_space_attenuation and bl_brush.spacing < 100):
        return 1.0
    if is_grab_class(bl_brush) or is_snake_hook(bl_brush):
        return 1.0
    fn = _PRESET_FALLOFF.get(bl_brush.curve_distance_falloff_preset)
    if fn is None:  # CUSTOM: strength(p) = curve(1 - p), matching BKE.
        cumap = bl_brush.curve_distance_falloff
        cumap.update()
        curve = cumap.curves[0]

        def fn(t, _c=cumap, _cv=curve):
            return _c.evaluate(_cv, 1.0 - t)

    spacing = max(bl_brush.spacing, 0.1)
    count = int(100 / spacing)
    h = spacing / 50.0
    peak = 0.0
    for i in range(10):
        x0 = i / 10.0 - 1.0
        total = 0.0
        for j in range(count):
            xx = abs(x0 + j * h)
            if xx < 1.0:
                total += fn(1.0 - xx)
        peak = max(peak, abs(total))
    return 1.0 / peak if peak > 0.0 else 1.0


def pixel_radius(sculpt, bl_brush):
    """The dab radius in screen pixels — the port of #BKE_brush_radius_get.

    ``Brush.size`` is a **diameter**: ``DNA_brush_types.h`` documents
    ``unprojected_size`` as "diameter of the brush in Blender units", both RNA
    properties are ``PROP_DISTANCE_DIAMETER``, and ``versioning_500.cc`` doubles
    the field when reading pre-5.0 files. Native sculpt never reads it raw —
    every consumer (``paint_stroke.cc``'s ``pixel_radius``, the spacing walk,
    ``paint_cursor.cc``) goes through ``BKE_brush_radius_get()``, which halves
    it. Taking ``.size`` for a radius makes every dab twice as wide as vanilla's
    and so covers four times the area.
    """
    size = unified_size(sculpt, bl_brush)
    return size / 2.0


def unified_size(sculpt, bl_brush):
    """The brush's pixel *diameter*, honouring the unified-size override."""
    unified = sculpt.unified_paint_settings
    return unified.size if unified.use_unified_size else bl_brush.size


def unprojected_radius(bl_brush):
    """Object-space fallback radius when a dab centre projects off-screen.
    ``unprojected_size`` is a diameter too (#BKE_brush_unprojected_radius_get)."""
    return bl_brush.unprojected_size / 2.0


def apply_dab_state(bl_brush, unified, sc_brush, *, world_radius, invert,
                    strength_scale=1.0, strength_override=None,
                    allow_invert=True):
    """Write the per-dab brush state: strength, radius and the invert flag
    (a live Ctrl toggles it mid-stroke), folded with the brush direction.
    Assumes ``apply_brush_settings`` ran at stroke start. ``strength_scale``
    folds per-stroke factors in (overlap attenuation). ``allow_invert=False``
    forces the invert flag off regardless of Ctrl/direction — smoothing has no
    inverse (the engine negates kernel strength on invert, and an inverted
    Laplacian moves verts away from their ring average, diverging within a few
    dabs), matching vanilla, where smooth ignores the direction.

    Strength and radius must be rewritten every dab, not only at stroke
    start: the engine's per-dab ``loadProps`` assigns the post-dynamics
    values (e.g. strength x pen pressure) back into the Brush *fields*, so
    the ``writeProps`` below would otherwise persist the decayed field into
    the prop store and a pressure stroke would fade to nothing after the
    first dab. Radius varies per dab anyway (depth-dependent unproject)."""
    if strength_override is not None:
        # Caller-computed strength (multi-pass smooth); scale/unified already
        # folded in.
        strength = strength_override
    else:
        strength = bl_brush.strength
        if unified is not None and unified.use_unified_strength:
            strength = unified.strength
        strength *= strength_scale

    sc_brush.strength = strength
    sc_brush.radius = world_radius
    if allow_invert:
        sc_brush.invert = bool(invert) ^ bool(bl_brush.direction == 'SUBTRACT')
    else:
        sc_brush.invert = False

    # writeProps() bakes the scalar fields into the kernel's uniform block.
    sc_brush.writeProps()


def apply_brush(bl_brush, unified, sc_brush, *, world_radius, invert, paint=None):
    """Configure a SculptCore Brush from a Blender Brush in one call —
    ``apply_brush_settings`` plus ``apply_dab_state``. Single-dab convenience
    for the headless tests; the stroke operator calls the two parts itself so
    the curve bakes run once per stroke, not per dab."""
    apply_brush_settings(bl_brush, unified, sc_brush, paint=paint)
    apply_dab_state(bl_brush, unified, sc_brush,
                    world_radius=world_radius, invert=invert)
