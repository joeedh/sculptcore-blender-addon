# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Tiny leaf helpers shared across the ``stroke`` package."""


def _float3(mgr, x, y, z):
    v = mgr.construct("litestl::math::float3")
    v.vec[0] = x
    v.vec[1] = y
    v.vec[2] = z
    return v
