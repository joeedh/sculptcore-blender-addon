# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only API exploration after constructing a scratch custom-property record."""
import bpy
scene = bpy.context.scene
scene['atomic_probe'] = {'records': {'key': {'value': .375}}}
for path in ('["atomic_probe"]', '["atomic_probe"]["records"]["key"]',
             '["atomic_probe"]["records"]["key"]["value"]'):
    try:
        value = scene.path_resolve(path, False)
        print('RECORD_PATH', path, type(value), repr(value), hasattr(value, 'id_properties_ui'), flush=True)
    except Exception as error:
        print('RECORD_PATH_ERROR', path, repr(error), flush=True)
print('GENERIC_RECORD_PATH_PROBE_PASS', flush=True)
