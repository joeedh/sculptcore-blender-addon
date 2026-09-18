# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Engine-owned authoring defaults, available without loading the engine."""
import math

from .registry import Definition, scalar

AUTOMASK_VIEW_NORMAL = 'sculptcore.brush.automask_view_normal'
VIEW_NORMAL_LIMIT = 'sculptcore.brush.view_normal_limit'
VIEW_NORMAL_FALLOFF = 'sculptcore.brush.view_normal_falloff'
CULL_BACKFACES = 'sculptcore.brush.cull_backfaces'
_PI = scalar('FLOAT32', math.pi)

DEFINITIONS = (
    Definition(AUTOMASK_VIEW_NORMAL, "View Normal", 'BOOL', False, 0, 1, 0, 1,
               "Mask by the angle between the surface normal and the view", dynamic=False),
    Definition(VIEW_NORMAL_LIMIT, "View Normal Limit", 'FLOAT32', 1.5707964, 0, _PI, 0, _PI,
               "Angle at which view-normal masking starts", unit='ROTATION', dynamic=False),
    Definition(VIEW_NORMAL_FALLOFF, "View Normal Falloff", 'FLOAT32', .43633232, 0, _PI, 0, _PI,
               "Angular width of the view-normal mask transition", unit='ROTATION', dynamic=False),
    Definition(CULL_BACKFACES, "Cull Backfaces", 'BOOL', False, 0, 1, 0, 1,
               "Exclude back-facing surfaces from the view-normal mask", dynamic=False),
)
