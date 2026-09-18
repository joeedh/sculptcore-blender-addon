# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Inspect declaration identity without changing user data."""
import bpy
name = 'sc_probe_curve_declaration'
setattr(bpy.types.Brush, name, bpy.props.CurveMappingProperty())
prop = bpy.types.Brush.bl_rna.properties[name]
descriptor = bpy.types.Brush.__dict__.get(name)
print('IDENTITY', prop.as_pointer(), type(descriptor), repr(descriptor), flush=True)
print('CLASS_GET', type(getattr(bpy.types.Brush, name)), getattr(bpy.types.Brush, name) is descriptor, flush=True)
delattr(bpy.types.Brush, name)
setattr(bpy.types.Brush, name, bpy.props.CurveMappingProperty())
current = bpy.types.Brush.bl_rna.properties[name]
print('REPLACED', current.as_pointer(), bpy.types.Brush.__dict__.get(name) is descriptor, flush=True)
try:
    print('OLD', prop.identifier, prop.as_pointer(), flush=True)
except Exception as error:
    print('OLD_REJECTED', type(error).__name__, flush=True)
delattr(bpy.types.Brush, name)
print('DECLARATION_IDENTITY_PASS', flush=True)
