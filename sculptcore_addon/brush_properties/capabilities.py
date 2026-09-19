# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Capability diagnostics for matching host and typed engine packages."""

ENGINE_EXPORTS = ('SemanticScalars_create', 'SemanticScalars_free', 'SemanticScalars_add',
                  'SemanticScalars_replaceDynamics', 'SemanticScalars_evaluate')


def require_host():
    import bpy
    required = ((bpy.props, ('CurveMappingProperty', 'curve_mapping_declaration_key')),
                (bpy.types.Brush, ('system_property_scalar', 'id_properties_update_atomic',
                                  'curve_mapping_initialize', 'authoring_native_curve_key',
                                  'authoring_edit_begin', 'authoring_edit_commit', 'authoring_edit_cancel')),
                (bpy.types.Scene, ('id_properties_update_atomic', 'curve_mapping_initialize',
                                  'authoring_edit_begin', 'authoring_edit_commit', 'authoring_edit_cancel')))
    missing = [name for owner, names in required for name in names if not callable(getattr(owner, name, None))]
    if missing:
        raise RuntimeError("SculptCore requires its matching Blender 5.3 fork with owned curves and authoring undo; "
                           "missing APIs: " + ', '.join(missing))


def verify_roundtrip():
    """Package gate: real owned storage, migration and native float/int/bool stacks."""
    from dataclasses import replace
    import bpy
    from . import authoring, migration
    from .commands import ExecutionLayer
    from .native_evaluation import NativeEvaluation
    from .registry import Definition, DeviceLayer
    from .responses import PreparedResponse
    from .snapshots import PropertySnapshot
    from .stroke_settings import capture_stroke
    from .. import engine

    require_host()
    missing = [name for name in ENGINE_EXPORTS if not hasattr(engine.capi().lib, name)]
    if missing:
        raise RuntimeError("SculptCore typed engine mismatch; missing exports: " + ', '.join(missing))
    reasons = {item.identifier: authoring.diagnostic(item.identifier) for item in authoring.DEFINITIONS
               if authoring.diagnostic(item.identifier)}
    if reasons:
        raise RuntimeError("SculptCore registered engine contracts are not executable: " + str(reasons))
    brush = bpy.data.brushes.new('Package brush property probe', mode='SCULPT')
    scene = bpy.data.scenes.new('Package brush property probe')
    duplicate = None
    try:
        assert authoring.store(scene).feature_enabled(), "Generic brush release default is disabled"
        store = authoring.store(brush)
        definition = authoring.registry.get('sculptcore.kernel.kelvinlet.nu')
        brush.sculptcore['nu'] = .25
        migration.migrate(store)
        assert store.read_value(definition).value == .25
        authoring.curve_bank.initialize(store, definition, 'SPEED')
        reference = authoring.curve_bank.reference(store, definition, 'SPEED')
        curve = authoring.curve_bank.mapping(store, definition, reference)
        curve.curves[0].points[-1].location.y = .375
        store.write_stack(definition, (DeviceLayer('SPEED', curve=authoring.curve_bank.reference(
            store, definition, 'SPEED')),))
        duplicate = brush.copy()
        copied = authoring.store(duplicate)
        mapping = authoring.curve_bank.mapping(copied, definition, copied.read_stack(definition)[0].curve)
        assert mapping.curves[0].points[-1].location.y == .375
        mapping.curves[0].points[-1].location.y = .625
        assert curve.curves[0].points[-1].location.y == .375
        settings = capture_stroke(brush, scene)
        layer = ExecutionLayer('PRESSURE', PreparedResponse('CONSTANT', parameters=(.5,)))
        for kind, base, low, high in (('FLOAT32', .25, 0, 1), ('INT32', 3, 0, 10), ('BOOL', True, 0, 1)):
            probe = Definition('package.' + kind, kind, kind, base, low, high, low, high)
            settings = replace(settings, properties=settings.properties + (
                PropertySnapshot(probe, probe, base, True, 'PACKAGE', (layer,), True, True, ()),))
        with NativeEvaluation(settings) as native:
            values = native.evaluate(((.5, 0, 0, 0, 1),), (.25,))
            assert tuple(values[0, -3:]) == (.125, 2, 1), values
    finally:
        if duplicate is not None:
            bpy.data.brushes.remove(duplicate)
        bpy.data.brushes.remove(brush)
        bpy.data.scenes.remove(scene)
    return "owned storage/copy, frozen migration and native float/int/bool dynamics"
