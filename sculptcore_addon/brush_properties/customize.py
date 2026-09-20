# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit preset customization, with dormant data preservation and grouped undo."""
from dataclasses import replace

from .curves import declaration_name
from .edits import authoring_edit
from .registry import PropertyError, ResponseCurve
from .responses import SampleConfig, evaluate, sample


def _seed(mapping, values):
    # Owned point wrappers retire after every write; reacquire each one.
    mapping.use_clip = False
    while len(mapping.curves[0].points) > 2:
        mapping.curves[0].points.remove(mapping.curves[0].points[1])
    mapping.curves[0].points[0].location = (0, values[0])
    mapping.curves[0].points[-1].location = (1, values[-1])
    mapping.curves[0].points[0].handle_type = 'VECTOR'
    mapping.curves[0].points[-1].handle_type = 'VECTOR'
    for index, value in enumerate(values[1:-1], 1):
        point = mapping.curves[0].points.new(index / (len(values) - 1), value)
        point.handle_type = 'VECTOR'
    mapping.update()


def customize(store, definition, device, *, reseed=False, preset=None, undo=False):
    """Select CUSTOM, returning a diagnostic when a step must become editable samples.

    `store` is the already-resolved effective stack owner. Native pressure mappings
    always exist and are preserved unless reseeding was explicitly requested.
    """
    store._write_allowed()
    layers = store.read_stack(definition)
    index = next((i for i, layer in enumerate(layers) if layer.device == device), None)
    if index is None:
        raise PropertyError("Add the device layer before customizing its response")
    if type(reseed) is not bool:
        raise PropertyError("Reseed requires a boolean")
    native = store._has_native_pressure(definition) and device == 'PRESSURE'
    if native:
        reference = store._native.curve_reference(definition.identifier)
        mapping = store._native.curve_mapping(reference)
    else:
        bank = store._curve_bank()
        bank._target(store, definition, device)
        mapping = getattr(store.owner, declaration_name(definition.identifier, device))
    seed = mapping is None or reseed
    source = preset if preset is not None else layers[index].curve
    values = None
    if seed:
        if type(source) is not ResponseCurve:
            raise PropertyError("Reseeding CUSTOM requires an explicit generated preset")
        # Validate the entire float32 payload before any allocation or mutation.
        values = sample(lambda x: evaluate(source, x), SampleConfig())
    with authoring_edit(store, 'Customize Brush Response', undo=undo):
        if mapping is None:
            reference = bank.initialize(store, definition, device)
            mapping = bank.mapping(store, definition, reference)
        if seed:
            _seed(mapping, values)
        reference = (store._native.curve_reference(definition.identifier) if native
                     else bank.reference(store, definition, device))
        updated = list(layers)
        updated[index] = replace(layers[index], curve=reference)
        store.write_stack(definition, tuple(updated))
    return ('Editable TWO_STEP uses a sampled approximation; the generated preset remains exact.'
            if seed and source.preset == 'TWO_STEP' else None)
