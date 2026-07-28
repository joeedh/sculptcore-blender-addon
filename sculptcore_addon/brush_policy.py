# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Per-kernel policy, queried from the engine instead of hardcoded here.

Everything a dab's shape depends on — grab discipline, whether the field is
unbounded, whether invert is meaningful — is declared by the kernel's
``sbrush`` annotations (``@grabmode`` / ``@incremental`` / ``@unbounded`` /
``@relaxation``) and reflected out through the stateless ``BrushMetadata``
binding. The engine owns that policy; the host asks for it. A host-side
tool-name list drifts the moment a kernel's annotations change, which is what
this module exists to prevent (engine ``documentation/strokeDriverGuide.md``
section 4.0).

The answer is codegen output and fixed for the life of the process, so it is
memoized by SculptBrushes value.

**Extra kernels report nothing.** ``brushDefFlagsFor`` builds the def through
``createCommandSwitch``, which only handles kernels compiled into the engine
proper; an addon-carried kernel from ``brushes/`` (NUDGE) is "unhandled" and
comes back all-false. All-false is indistinguishable from "a plain deforming
draw", which is what NUDGE happens to be — but an addon-carried grab or
unbounded kernel would be silently mis-driven. Keep extra kernels plain until
the engine can report their flags.
"""

from . import engine

# kernel enum value -> Policy
_cache = {}
_metadata_obj = None


def _metadata():
    """The process-wide stateless BrushMetadata handle (built once)."""
    global _metadata_obj
    if _metadata_obj is None:
        _metadata_obj = engine.manager().construct("sculptcore::brush::BrushMetadata")
    return _metadata_obj


class Policy:
    """A kernel's queried ``BrushDefFlags``, plus the two derived questions the
    dab dispatch actually asks."""

    __slots__ = ("grab_mode_capable", "incremental", "unbounded", "relaxes_base",
                 "accumulable", "writes_mask", "writes_color", "face_mode")

    def __init__(self, flags=None):
        get = (lambda name: bool(getattr(flags, name))) if flags is not None else (
            lambda name: False)
        self.grab_mode_capable = get("grabModeCapable")
        self.incremental = get("incremental")
        self.unbounded = get("unbounded")
        self.relaxes_base = get("relaxesBase")
        self.accumulable = get("accumulable")
        self.writes_mask = get("writesMask")
        self.writes_color = get("writesColor")
        self.face_mode = get("faceMode")

    @property
    def is_grab(self):
        """Grab-class: the kernel reads the grab ctx vectors, under either
        discipline (anchored from-orig, or the incremental path style)."""
        return self.grab_mode_capable or self.incremental

    @property
    def latches_filter_radius(self):
        """Whether the node-filter radius must be latched to a per-stroke
        high-water mark. Only from-orig grabs need it: a from-orig dab writes
        only inside the filter, so a shrinking region (drag reversal) strands
        the verts it dropped at their last displaced value. An ``@incremental``
        kernel (Snake Hook) tracks the live surface and also sizes its dyntopo
        dab off this radius, so latching it at the stroke's widest would
        collapse edges well outside the dab."""
        return self.grab_mode_capable and not self.incremental


def for_kernel(kernel):
    """The Policy for a SculptBrushes enum value (memoized). ``None`` kernel —
    an unmapped brush type — reports an all-false policy."""
    if kernel is None:
        return Policy()
    policy = _cache.get(kernel)
    if policy is None:
        policy = Policy(_metadata().queryBrushFlags(int(kernel)))
        _cache[kernel] = policy
    return policy


def field_radius(kernel, radius, sc_brush):
    """The radius at which the kernel's field actually dies out. Equal to the
    falloff radius for an ordinary kernel; for an ``@unbounded`` one (kelvinlet)
    there is no distance falloff at all, only a C1 window closing at
    ``radius * unboundedExtent``, so the field is still live far outside the
    brush radius."""
    if for_kernel(kernel).unbounded:
        return radius * sc_brush.unboundedExtent
    return radius


def filter_radius(kernel, radius, sc_brush, session, drag=0.0):
    """The node-filter radius for one dab — which spatial leaves it may touch.
    This is *not* the falloff radius (that stays ``sc_brush.radius``).

    Widened to the kernel's field radius so an unbounded field can't stay live
    where the node set stops (that tears at leaf boundaries), then by ``drag``
    so a grab's region covers both where verts are and where they move to, and
    finally latched monotonic for from-orig grabs. See the guide's section 4.4
    — this mirrors what ``CommandExecutor::applyDab`` does internally via
    ``filterRadiusFloor``, for the ``execBrush`` / ``execProgram`` paths that
    bypass it."""
    value = field_radius(kernel, radius, sc_brush) + drag
    if for_kernel(kernel).latches_filter_radius:
        value = max(value, session.filter_high_water)
        session.filter_high_water = value
    return value
