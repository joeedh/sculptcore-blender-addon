# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Own a native semantic scalar collection for one immutable stroke snapshot."""
import ctypes
from contextlib import ExitStack

from .adapters import SIZE
from .evaluation import typed_bounds
from .registry import DEVICE_TYPES, PropertyError


def native_layers(stack):
    from sculptcore.brush_properties import DeviceLayer
    operations = {'REPLACE': 0, 'MULTIPLY': 1, 'ADD': 2, 'SUBTRACT': 3, 'DIFFERENCE': 4}
    return tuple(DeviceLayer(DEVICE_TYPES.index(layer.device), operations[layer.operation],
                             layer.factor, layer.enabled, layer.response.samples,
                             layer.response.kind, layer.response.parameters) for layer in stack)


class NativeEvaluation:
    """Upload typed bases/stacks once; evaluate input rows without authoring writes."""

    def __init__(self, settings):
        import numpy as np
        from .. import engine
        from sculptcore.brush_properties import DeviceLayer, _primitive_vector, _stack_arrays

        self.ptr = None
        self.settings = settings
        self.identifiers = tuple(item.definition.identifier for item in settings.properties)
        self.size_index = self.identifiers.index(SIZE)
        self.lib = engine.capi().lib
        self.manager = engine.manager()
        scalar_types = {'FLOAT32': 0, 'INT32': 4, 'BOOL': 10}
        pointer, integer = ctypes.c_void_p, ctypes.c_int
        vector = pointer
        signatures = {
            'SemanticScalars_create': ([], pointer),
            'SemanticScalars_free': ([pointer], None),
            'SemanticScalars_add': ([pointer, integer, ctypes.c_double, ctypes.c_double,
                                     ctypes.c_double, integer], integer),
            'SemanticScalars_replaceDynamics': ([pointer, integer] + [vector] * 8, integer),
            'SemanticScalars_evaluate': ([pointer, integer,
                                         np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS'),
                                         np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS'),
                                         integer,
                                         np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS'),
                                         ctypes.c_size_t], integer),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = arguments, result
        self.ptr = self.lib.SemanticScalars_create()
        if not self.ptr:
            raise PropertyError("Cannot allocate semantic scalar collection")
        try:
            for index, item in enumerate(settings.properties):
                if item.definition.identifier == SIZE:
                    kind, low, high, value = 'FLOAT32', 0.0, 3.4028234663852886e38, 0.0
                else:
                    kind, low, high = typed_bounds(item.value_domain)
                    value = item.value
                result = self.lib.SemanticScalars_add(self.ptr, scalar_types[kind], value, low, high,
                                                       int(item.definition.dynamic))
                if result != index:
                    raise PropertyError("Native scalar declaration rejected: " + item.definition.identifier)
                layers = native_layers(item.stack)
                with ExitStack() as owned:
                    vectors = [owned.enter_context(_primitive_vector(self.manager, kind, values))
                               for kind, values in _stack_arrays(layers)]
                    status = self.lib.SemanticScalars_replaceDynamics(self.ptr, index,
                                                                      *(value.ptr for value in vectors))
                if status:
                    raise PropertyError("Native scalar stack rejected: " + item.definition.identifier)
        except BaseException:
            self.close()
            raise

    def evaluate(self, samples, radii):
        """Return typed semantic values in snapshot order, before unit conversion."""
        import numpy as np
        if self.ptr is None:
            raise PropertyError("Semantic scalar collection is closed")
        inputs = np.ascontiguousarray(samples, dtype=np.float32)
        radii = np.ascontiguousarray(radii, dtype=np.float32)
        if inputs.ndim != 2 or inputs.shape[1] != 5 or radii.shape != (len(inputs),):
            raise PropertyError("Expected Nx5 input rows and one projected radius per row")
        output = np.empty((len(inputs), len(self.identifiers)), dtype=np.float64)
        status = self.lib.SemanticScalars_evaluate(self.ptr, len(inputs), inputs, radii,
                                                  self.size_index, output, output.size)
        if status:
            raise PropertyError("Semantic scalar evaluation rejected ({})".format(status))
        return output

    def close(self):
        if self.ptr is not None:
            self.lib.SemanticScalars_free(self.ptr)
            self.ptr = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
