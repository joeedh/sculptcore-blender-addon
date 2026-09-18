# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Probe existing RNA collection and IDProperty metadata behavior before storage implementation."""
from array import array
import json
import bpy


class SCProbeResponse(bpy.types.PropertyGroup):
    device: bpy.props.StringProperty()
    curve: bpy.props.CurveMappingProperty()


class SCProbeRecord(bpy.types.PropertyGroup):
    identifier: bpy.props.StringProperty()
    responses: bpy.props.CollectionProperty(type=SCProbeResponse)


class SCProbeRoot(bpy.types.PropertyGroup):
    records: bpy.props.CollectionProperty(type=SCProbeRecord)


classes = (SCProbeResponse, SCProbeRecord, SCProbeRoot)
for cls in classes:
    bpy.utils.register_class(cls)
bpy.types.Brush.sc_probe = bpy.props.PointerProperty(type=SCProbeRoot)
brush = bpy.data.brushes.new('Storage probe', mode='SCULPT')
report = {}
report['absent_root'] = tuple(brush.keys())
root = brush.sc_probe
report['pointer_read'] = tuple(brush.keys())
_ = len(root.records)
report['collection_read'] = brush.get('sc_probe').to_dict() if brush.get('sc_probe') is not None else None
root['records'] = [{'identifier': 'one', 'value': 16777217, 'parameters': array('d', [])}]
record = root.records[0]
report['raw_array_binding'] = [record.identifier, type(record['value']).__name__, record['value']]
record['value'] = .625
record.id_properties_ui('value').update(min=0, max=10, soft_min=0, soft_max=1,
                                      default=.5, description='Angle', subtype='ANGLE')
report['metadata'] = record.id_properties_ui('value').as_dict()
record['value'] = True
report['bool'] = [type(record['value']).__name__, record['value']]
response = record.responses.add()
response.device = 'PRESSURE'
curve = response.curve_mapping_initialize('curve')
curve.curves[0].points[-1].location = (1, .375)
before = curve.curve_mapping_cache_key()
record['layers'] = [{'device': 'PRESSURE', 'enabled': True}]
report['curve_preserved'] = [before, curve.curve_mapping_cache_key()]
root.records.add().identifier = 'two'
root.records.move(0, 1)
report['curve_move'] = [curve.curve_mapping_cache_key(), curve.curves[0].points[-1].location.y]
print('GENERIC_STORAGE_PROBE', json.dumps(report), flush=True)
bpy.data.brushes.remove(brush)
del bpy.types.Brush.sc_probe
for cls in reversed(classes):
    bpy.utils.unregister_class(cls)
