# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded immutable response cache; owner identities are values, never RNA pointers."""
from collections import OrderedDict
import itertools

from .registry import CustomCurveReference, NativeCurveReference, PropertyError, ResponseCurve
from .responses import PreparedResponse, SampleConfig, evaluate, sample


def canonical_mapping(mapping):
    """Evaluation fields only; UI selection and view changes do not invalidate tables."""
    return (
        mapping.use_clip, mapping.clip_min_x, mapping.clip_min_y, mapping.clip_max_x, mapping.clip_max_y,
        mapping.extend, mapping.tone, tuple(mapping.black_level), tuple(mapping.white_level),
        tuple(tuple((tuple(point.location), point.handle_type) for point in curve.points) for curve in mapping.curves),
    )


class ResponseCache:
    def __init__(self, capacity=256):
        if type(capacity) is not int or not 1 <= capacity <= 256:
            raise PropertyError("Response cache capacity must be 1..256")
        self.capacity = capacity
        self.sources = OrderedDict()
        self.contents = OrderedDict()
        self.identities = {}
        self._next = itertools.count(1)
        self.bakes = 0
        self.hits = 0

    def clear(self):
        self.sources.clear()
        self.contents.clear()
        self.identities.clear()

    def get(self, source):
        identity = self.sources.get(source)
        key = self.identities.get(identity)
        if key is None:
            self.sources.pop(source, None)
            return None
        self.sources.move_to_end(source)
        self.contents.move_to_end(key)
        self.hits += 1
        return self.contents[key][1]

    def put(self, source, response, config):
        # Full equality authorizes interning; Python's hash only accelerates lookup.
        key = (config, response)
        present = self.contents.get(key)
        if present is None:
            identity = next(self._next)
            self.contents[key] = identity, response
            self.identities[identity] = key
        else:
            identity, response = present
            self.contents.move_to_end(key)
        self.sources[source] = identity
        self.sources.move_to_end(source)
        while len(self.sources) > self.capacity:
            self.sources.popitem(last=False)
        while len(self.contents) > self.capacity:
            _, (old, _) = self.contents.popitem(last=False)
            del self.identities[old]
        return response

    def generated(self, curve, config=SampleConfig()):
        if type(curve) is not ResponseCurve or type(config) is not SampleConfig:
            raise PropertyError("Expected a generated response")
        curve = ResponseCurve(curve.preset, curve.parameters)
        source = ('GENERATED', curve, config)
        cached = self.get(source)
        if cached is not None:
            return cached
        if curve.preset in ('CONSTANT', 'TWO_STEP'):
            if config.reverse or config.clamp_output or config.hardness:
                raise PropertyError("Analytic device responses require the canonical input domain")
            result = PreparedResponse(curve.preset, parameters=curve.parameters)
        else:
            result = PreparedResponse('TABLE', sample(lambda x: evaluate(curve, x), config))
            self.bakes += 1
        return self.put(source, result, config)

    def mapping(self, source, mapping, config=SampleConfig(), *, native_key=None):
        """Caller must validate the current owner/revision before every invocation."""
        if type(config) is not SampleConfig:
            raise PropertyError("Expected a sampling configuration")
        key = ('MAPPING', source, config)
        cached = self.get(key)
        if cached is not None:
            return cached
        # Native keys include hidden evaluation flags (e.g. wrapping); owned v1
        # forbids those flags and exposes all editable evaluation fields below.
        canonical = (('NATIVE_DEFINITION', native_key, config) if native_key is not None
                     else ('OWNED_DEFINITION', canonical_mapping(mapping), config))
        cached = self.get(canonical)
        if cached is not None:
            return self.put(key, cached, config)
        mapping.update()
        channel = mapping.curves[0]
        values = sample(lambda x: mapping.evaluate(channel, x), config)
        self.bakes += 1
        response = self.put(canonical, PreparedResponse('TABLE', values), config)
        return self.put(key, response, config)


cache = ResponseCache()
epoch = 0
_overlap_cache = OrderedDict()
overlap_bakes = 0


def falloff_response(brush, hardness):
    """Sample native distance falloff once for either settings entry point."""
    from ..mapping import _PRESET_FALLOFF
    preset = brush.curve_distance_falloff_preset
    function = _PRESET_FALLOFF.get(preset)
    config = SampleConfig(reverse=function is None, clamp_output=True, hardness=hardness)
    if function is None:
        return native_response(brush, 'curve_distance_falloff', config)
    key = ('FALLOFF', preset, config)
    response = cache.get(key)
    if response is None:
        response = PreparedResponse('TABLE', sample(function, config))
        cache.bakes += 1
        response = cache.put(key, response, config)
    return response


def overlap_table(brush):
    """Exact native compensation for integer spacing, independent of the LUT."""
    global overlap_bakes
    from ..mapping import _PRESET_FALLOFF
    preset = brush.curve_distance_falloff_preset
    source = brush.authoring_native_curve_key('curve_distance_falloff') if preset == 'CUSTOM' else preset
    key = epoch, source
    if key in _overlap_cache:
        _overlap_cache.move_to_end(key)
        return _overlap_cache[key]
    function = _PRESET_FALLOFF.get(preset)
    if function is None:
        curve = brush.curve_distance_falloff
        channel = curve.curves[0]
        function = lambda t: curve.evaluate(channel, 1.0 - t)
    values = [1.0]
    for spacing in range(1, 100):
        peak = 0.0
        for phase in range(10):
            origin = phase / 10.0 - 1.0
            total = 0.0
            for index in range(int(100 / spacing)):
                distance = abs(origin + index * (spacing / 50.0))
                if distance < 1.0:
                    total += function(1.0 - distance)
            peak = max(peak, abs(total))
        values.append(1.0 / peak if peak > 0.0 else 1.0)
    result = tuple(values)
    overlap_bakes += 1
    _overlap_cache[key] = result
    while len(_overlap_cache) > 256:
        _overlap_cache.popitem(last=False)
    return result


def resolved_response(store, definition, curve, config=SampleConfig()):
    """Validate owner/definition/revision before reusing any native or owned samples."""
    store._checked_definition(definition)
    if type(curve) is ResponseCurve:
        return cache.generated(curve, config)
    if type(curve) is CustomCurveReference:
        if store.curve_bank is None:
            raise PropertyError("Custom curve bank is unavailable")
        mapping = store.curve_bank.mapping(store, definition, curve)
    elif type(curve) is NativeCurveReference:
        mapping = store._native.curve_mapping(curve)
    else:
        raise PropertyError("Invalid response descriptor")
    return cache.mapping(curve, mapping, config,
                         native_key=curve.mapping_key if type(curve) is NativeCurveReference else None)


def native_response(owner, path, config=SampleConfig()):
    """Legacy callers supply the actual ID and exact native path at stroke start."""
    from .lifecycle import _main_thread
    _main_thread()
    try:
        fingerprint = owner.authoring_native_curve_key(path)
        mapping = owner.path_resolve(path)
    except (ValueError, ReferenceError, TypeError) as error:
        raise PropertyError("Native curve owner or path is unavailable") from error
    return cache.mapping(('NATIVE', path, fingerprint), mapping, config, native_key=fingerprint)


def clear():
    global epoch
    epoch += 1
    cache.clear()
    _overlap_cache.clear()
