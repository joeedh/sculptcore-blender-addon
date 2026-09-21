# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Shift-smooth stroke's own settings, and the feature-align brush's rake.

A Shift-stroke smooths with a kernel of its own (``stroke.session.
toggle_kernel_name``), so the active brush's strength and kernel scalars are
the wrong knobs for it: an artist tunes "how hard Shift smooths" once, not
per brush. These definitions therefore default to the *unified* (Scene) value
-- ``storage.unified`` answers True for them until a Scene record says
otherwise -- while staying ordinary generic properties, so a brush can still
opt out of the shared value through the usual inheritance controls.

The rows are drawn by ``ui.SCULPTCORE_PT_shift_smooth`` (their default
location, ``placement.LOCATIONS`` ``SHIFT_SMOOTH``) and consumed by the stroke
operator on a ``mode == 'SMOOTH'`` generic stroke. ``RAKE`` is the
feature-align *brush's* rake (mapping ``TOPOLOGY`` -> ``FEATURE_ALIGN``),
gated to that kernel by ``placement.applicable``.
"""
from .registry import Definition

PREFIX = 'sculptcore.brush.'
STRENGTH = PREFIX + 'shift_smooth_strength'
FEATURE_ALIGN = PREFIX + 'shift_smooth_feature_align'
DYNTOPO = PREFIX + 'shift_smooth_dyntopo'
RAKE_SHIFT = PREFIX + 'shift_smooth_rake'
PROJECTION = PREFIX + 'shift_smooth_projection'
RAKE = PREFIX + 'rake'

# Vanilla's smooth iterates `int(strength * 4)` full-strength relaxation passes
# per dab plus a remainder pass (stroke.dyntopo.smooth_iteration_strengths);
# the 4.0 ceiling is 16 passes, the point past which a dab is a full relax.
STRENGTH_MAX = 4.0

DEFINITIONS = (
    Definition(STRENGTH, "Strength", 'FLOAT32', 0.5, 0.0, STRENGTH_MAX, 0.0, 1.0,
               "How strongly a Shift-stroke smooths: quarter steps add full relaxation passes per dab"),
    Definition(FEATURE_ALIGN, "Feature Align", 'BOOL', False, 0, 1, 0, 1,
               "Shift-smooth with the feature-align smooth (topology rake) instead of the "
               "boundary-aware smooth", dynamic=False),
    Definition(DYNTOPO, "Dyntopo", 'BOOL', False, 0, 1, 0, 1,
               "Remesh under a Shift-smooth stroke when Dynamic Topology is on", dynamic=False),
    Definition(RAKE_SHIFT, "Rake", 'FLOAT32', 0.5, 0.0, 1.0, 0.0, 1.0,
               "How strongly the feature-align Shift-smooth biases edges toward the surface's feature "
               "directions; 0 is a plain smooth", dynamic=False),
    Definition(PROJECTION, "Projection", 'FLOAT32', 0.0, 0.0, 1.0, 0.0, 1.0,
               "Fraction of the Shift-smooth step's normal component removed, so the surface slides "
               "tangentially instead of shrinking", dynamic=False),
    Definition(RAKE, "Rake", 'FLOAT32', 0.5, 0.0, 1.0, 0.0, 1.0,
               "How strongly the feature-align smooth biases edges toward the surface's feature "
               "directions; 0 is a plain smooth", dynamic=False),
)
# The definitions whose effective value is the Scene's unless a Scene record
# opts out (see storage.unified).
UNIFIED_BY_DEFAULT = frozenset((STRENGTH, FEATURE_ALIGN, DYNTOPO, RAKE_SHIFT, PROJECTION))
# The Shift-smooth rows, in panel order; the rake and projection rows only
# matter to the feature-align kernel (projection reaches both).
ORDER = (STRENGTH, DYNTOPO, FEATURE_ALIGN, RAKE_SHIFT, PROJECTION)


def resolve_value(brush, scene, identifier):
    """The effective value of one Shift-smooth setting for ``brush`` under
    ``scene`` -- read directly, for the choices a stroke must make before it
    captures its settings (which kernel to run)."""
    from . import authoring
    from .resolver import resolve_value as _resolve_value
    return _resolve_value(authoring.registry, identifier, authoring.store(brush), authoring.store(scene)).value
