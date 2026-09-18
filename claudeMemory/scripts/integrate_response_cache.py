# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the reviewed Plan 5 legacy curve consumer integration once."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / 'sculptcore_addon/mapping.py'
text = path.read_text()
start = text.index('def _upload_lut(')
end = text.index('\n\n# Cavity automasking.', start)
text = text[:start] + '''def _upload_lut(cache, key, values, setter, sc_brush):
    """Keep immutable table installation scoped to a live target and lifecycle epoch."""
    from .brush_properties import sampling
    values = tuple(values)
    previous = cache.get(key) if cache is not None else None
    if (previous is not None and previous[0] is sc_brush
            and previous[1:] == (sampling.epoch, values)):
        return
    if len(values) != 256:
        raise ValueError("Legacy falloff and cavity tables require exactly 256 entries")
    for i, value in enumerate(values):
        setter(i, value)
    if cache is not None:
        cache[key] = (sc_brush, sampling.epoch, values)
        cache['table_uploads'] = cache.get('table_uploads', 0) + 1


def _bake_falloff(bl_brush, sc_brush, cache=None):
    from .brush_properties import sampling
    from .brush_properties.responses import PreparedResponse, SampleConfig, sample
    preset = bl_brush.curve_distance_falloff_preset
    fn = _PRESET_FALLOFF.get(preset)
    config = SampleConfig(reverse=fn is None, clamp_output=True,
                          hardness=min(1.0, max(0.0, bl_brush.hardness)))
    if fn is None:
        response = sampling.native_response(bl_brush, 'curve_distance_falloff', config)
    else:
        key = ('LEGACY_FALLOFF', preset, config)
        response = sampling.cache.get(key)
        if response is None:
            response = PreparedResponse('TABLE', sample(fn, config))
            sampling.cache.bakes += 1
            sampling.cache.put(key, response, config)
    _upload_lut(cache, 'falloff', response.samples, sc_brush.setFalloffCurveEntry, sc_brush)
    sc_brush.falloff_kind = _FALLOFF_KIND_CURVE
    sc_brush.falloff_shape = _FALLOFF_SHAPE_SPHERICAL
''' + text[end:]
start = text.index('    cumap = settings.cavity_curve')
end = text.index('\n\n\n# Pen-pressure', start)
text = text[:start] + '''    from .brush_properties import sampling
    from .brush_properties.responses import SampleConfig
    owner = settings.id_data
    path = ('mesh_automasking_settings.cavity_curve' if owner.bl_rna.identifier == 'Brush'
            else 'tool_settings.sculpt.mesh_automasking_settings.cavity_curve')
    response = sampling.native_response(owner, path, SampleConfig(clamp_output=True))
    _upload_lut(cache, 'cavity', response.samples, sc_brush.setCavityCurveEntry, sc_brush)
''' + text[end:]
start = text.index('def sample_pressure_curve(')
end = text.index('\n\ndef eval_pressure_lut', start)
text = text[:start] + '''def sample_pressure_curve(owner, path):
    """Resolve native authority once at stroke start; unchanged definitions reuse samples."""
    from .brush_properties.sampling import native_response
    return native_response(owner, path).samples
''' + text[end:]
start = text.index('    # addPropDynamic appends', text.index('def apply_pressure_dynamics('))
end = text.index('\n\n\n# For UI', start)
text = text[:start] + '''    from . import engine
    from .brush_properties.uploads import StackUploads
    from sculptcore.brush_properties import CommonProperties, DeviceLayer
    want = (sample_pressure_curve(bl_brush, 'curve_strength') if use_strength else None,
            sample_pressure_curve(bl_brush, 'curve_size') if use_size else None)
    memo = cache.setdefault('pressure_uploads', StackUploads()) if cache is not None else StackUploads()
    stacks = tuple((prop, () if table is None else (DeviceLayer(DEVICE_PRESSURE, samples=table),))
                   for prop, table in ((PROP_STRENGTH, want[0]), (PROP_RADIUS, want[1])))
    memo.install(sc_brush, CommonProperties(engine.manager(), sc_brush), stacks, command='legacy-pressure')
''' + text[end:]
text = text.replace('def overlap_attenuation(bl_brush):', 'def overlap_attenuation(bl_brush, cache=None):')
start = text.index('    fn = _PRESET_FALLOFF.get', text.index('def overlap_attenuation'))
text = text[:start] + '''    from .brush_properties import sampling
    preset = bl_brush.curve_distance_falloff_preset
    source = (bl_brush.authoring_native_curve_key('curve_distance_falloff') if preset == 'CUSTOM' else preset)
    key = (sampling.epoch, source, bl_brush.spacing)
    previous = cache.get('overlap') if cache is not None else None
    if previous is not None and previous[0] == key:
        return previous[1]
''' + text[start:]
text = text.replace('    return 1.0 / peak if peak > 0.0 else 1.0', '''    result = 1.0 / peak if peak > 0.0 else 1.0
    if cache is not None:
        cache['overlap'] = (key, result)
        cache['overlap_bakes'] = cache.get('overlap_bakes', 0) + 1
    return result''')
path.write_text(text)
path = root / 'sculptcore_addon/stroke.py'
text = path.read_text().replace('mapping.sample_pressure_curve(self.brush.curve_strength)',
                                "mapping.sample_pressure_curve(self.brush, 'curve_strength')")
text = text.replace('mapping.sample_pressure_curve(self.brush.curve_size)',
                    "mapping.sample_pressure_curve(self.brush, 'curve_size')")
text = text.replace('mapping.overlap_attenuation(self.brush)',
                    'mapping.overlap_attenuation(self.brush, cache=sess.curve_cache)')
# Existing stroke local is `session`, verify rather than inventing a target.
text = text.replace('cache=sess.curve_cache)', 'cache=self.session.curve_cache)')
path.write_text(text)
print('PLAN5_LEGACY_CACHE_INTEGRATED')
