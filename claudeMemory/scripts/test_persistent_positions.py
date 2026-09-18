# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Saved local placements, defaults, transaction safety and file persistence."""
from array import array
from dataclasses import replace
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generic_property_foundation import load_package
_, native = load_package()
from generic_property_test_package import lifecycle
from generic_property_test_package.registry import Definition, DeviceLayer, Position, PropertyError, Registry
from generic_property_test_package.storage import PersistentOwnerStore, ROOT, record_key

DIRECTORY = Path(__file__).resolve().parents[1] / 'tests/plan4-positions'
DIRECTORY.mkdir(parents=True, exist_ok=True)
DEFAULTS = (Position('HEADER', -3), Position('PANEL', 12))
CUSTOM = (Position('MENU', 7), Position('未知位置', -2147483648))
registry = Registry()
definition = registry.register(Definition('test.positions', 'Positions', 'FLOAT32', .5, 0, 1, 0, 1,
                                          positions=DEFAULTS))
registry.register(native.STRENGTH_DEFINITION)
checks = []
lifecycle.register()


def store(owner, definitions=registry):
    return PersistentOwnerStore(owner, definitions)


def check(name, condition=True):
    assert condition, name
    checks.append(name)


def reject(name, function):
    try:
        function()
    except PropertyError:
        checks.append(name)
    else:
        raise AssertionError('Accepted: ' + name)


def record(owner):
    return owner[ROOT]['records'][record_key(definition.identifier)]


phase = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'test'
if phase == 'verify':
    bpy.ops.wm.open_mainfile(filepath=str(DIRECTORY / 'without-authoring.blend'))
    brush = bpy.data.brushes['PersistentPositionsBrush']
    scene = bpy.data.scenes['PersistentPositionsScene']
    check('fresh Brush placements', store(brush).read_positions(definition) == CUSTOM)
    check('fresh Scene explicit empty', store(scene).read_positions(definition) == ())
    check('fresh opaque position data', record(brush)['positions'][record_key('MENU')]['unknown'] == b'keep')
else:
    brush = bpy.data.brushes.new('PersistentPositionsBrush', mode='SCULPT')
    brush.use_fake_user = True
    scene = bpy.data.scenes.new('PersistentPositionsScene')
    local, parent = store(brush), store(scene)
    check('absent returns definition defaults', local.read_positions(definition) == DEFAULTS)
    local.reset_positions(definition)
    check('untouched read/reset allocate nothing', ROOT not in brush)
    local.write_positions(definition, ())
    check('explicit empty overrides nonempty defaults', local.read_positions(definition) == () and ROOT in brush)
    local.reset_positions(definition)
    check('reset returns defaults', local.read_positions(definition) == DEFAULTS)
    local.write_positions(definition, DEFAULTS)
    changed = Registry()
    updated = changed.register(replace(definition, positions=CUSTOM))
    revised = store(brush, changed)
    check('explicit equal-default override survives new defaults', revised.read_positions(updated) == DEFAULTS)
    revised.reset_positions(updated)
    check('reset adopts revised defaults', revised.read_positions(updated) == CUSTOM)
    local.write_positions(definition, CUSTOM)
    parent.write_positions(definition, DEFAULTS)
    for mode in ('UNIFIED', 'ALWAYS', 'NEVER'):
        for unified in (True, False):
            for inherit in (True, False):
                local.write_mode(definition.identifier, mode)
                local.write_stack_inheritance(definition.identifier, inherit)
                parent.write_unified(definition.identifier, unified)
                local.write_positions(definition, CUSTOM)
                assert local.read_positions(definition) == CUSTOM and parent.read_positions(definition) == DEFAULTS
    check('all twelve inheritance combinations leave placement local')
    for owner in (brush, scene):
        store(owner).write_positions(native.STRENGTH_DEFINITION, CUSTOM)
        check(owner.bl_rna.identifier + ' native placement without native stack capability',
              store(owner).read_positions(native.STRENGTH_DEFINITION) == CUSTOM)
    check('fresh Scene native settings stayed unavailable', scene.tool_settings.sculpt is None)
    record(brush)['positions'][record_key('MENU')]['unknown'] = b'keep'
    record(brush)['positions'][record_key('MENU')]['unknown_array'] = array('f', [.25, .5])
    local.write_positions(definition, tuple(reversed(CUSTOM)))
    check('reorder retains location-associated extensions',
          record(brush)['positions'][record_key('MENU')]['unknown'] == b'keep')
    local.write_positions(definition, ())
    local.write_positions(definition, CUSTOM)
    check('clear and readd retain unknown native array type',
          record(brush)['positions'][record_key('MENU')]['unknown_array'].typecode == 'f')
    for owner in (brush, scene):
        original = store(owner).read_positions(definition)
        copied = owner.copy()
        store(copied).write_positions(definition, (Position('COPY_ONLY'),))
        check(owner.bl_rna.identifier + ' independent placement copy',
              store(owner).read_positions(definition) == original)
    for location, index in (('', 0), ('NUL\0', 0), ('\ud800', 0), ('界' * 342, 0),
                            ('HEADER', True), ('HEADER', 2147483648), ('HEADER', -2147483649)):
        reject('invalid Position ' + repr((location, index)), lambda: Position(location, index))
    reject('same location differing indexes', lambda: local.write_positions(definition,
           (Position('MENU', 0), Position('MENU', 1))))
    reject('overlong position count', lambda: local.write_positions(definition,
           tuple(Position('LOCATION_' + str(i)) for i in range(129))))
    forged = Position('FORGED')
    object.__setattr__(forged, 'location', [])
    reject('forged position rejected cleanly', lambda: local.write_positions(definition, (forged,)))
    largest = tuple(Position('LOCATION_' + str(i), i) for i in range(127)) + (Position('界' * 341 + 'x', 2147483647),)
    local.write_positions(definition, largest)
    check('128 positions and 1024-byte Unicode location', local.read_positions(definition) == largest)
    local.write_positions(definition, CUSTOM)
    for order in ('[', '{}', '[1]', '[]' * 9000, '[' * 2000 + ']' * 2000,
                  json.dumps([record_key('MENU')] * 2), json.dumps(['invalid'])):
        record(brush)['positions_order'] = order
        reject('bad encoded order ' + order[:25], lambda: local.read_positions(definition))
        local.write_positions(definition, CUSTOM)
    for header in ('positions_order', 'positions_version'):
        del record(brush)[header]
        reject('partial header ' + header, lambda: local.read_positions(definition))
        local.write_positions(definition, CUSTOM)
    for version in (True, 2):
        record(brush)['positions_version'] = version
        before = brush[ROOT].to_dict()
        reject('future/mistyped read ' + repr(version), lambda: local.read_positions(definition))
        reject('future/mistyped write ' + repr(version), lambda: local.write_positions(definition, CUSTOM))
        reject('future/mistyped reset ' + repr(version), lambda: local.reset_positions(definition))
        assert before == brush[ROOT].to_dict()
        local.write_value(definition, .375)
        local.write_stack(definition, (DeviceLayer('PRESSURE'),))
        local.write_mode(definition.identifier, 'NEVER')
        check('other authoring preserves placement version ' + repr(version),
              record(brush)['positions_version'] == version)
        record(brush)['positions_version'] = 1
    key = record_key('MENU')
    for field, bad in (('location', 'WRONG_HASH'), ('sort_index', True), ('sort_index', 1.5)):
        entry = record(brush)['positions'][key]
        good = entry[field]
        entry[field] = bad
        before = brush[ROOT].to_dict()
        reject('active malformed read ' + field + repr(bad), lambda: local.read_positions(definition))
        assert brush[ROOT].to_dict() == before
        record(brush)['positions'][key][field] = good
    for missing in (False, True):
        saved_entry = record(brush)['positions'][key].to_dict()
        if missing:
            del record(brush)['positions'][key]
        else:
            record(brush)['positions'][key] = 7
        reject('missing/non-group active entry ' + repr(missing), lambda: local.read_positions(definition))
        if not missing:
            del record(brush)['positions'][key]
        record(brush)['positions'][key] = saved_entry
    for identity in ('OTHER_LOCATION', 7, None):
        entry = record(brush)['positions'][key]
        if identity is None:
            del entry['location']
        else:
            entry['location'] = identity
        local.write_positions(definition, ())
        before = brush[ROOT].to_dict()
        reject('dormant collision or missing identity ' + repr(identity),
               lambda: local.write_positions(definition, CUSTOM))
        assert before == brush[ROOT].to_dict()
        record(brush)['positions'][key]['location'] = 'MENU'
    local.write_positions(definition, CUSTOM)
    record(brush)['positions'][record_key(CUSTOM[-1].location)]['sort_index'] = {'broken': True}
    before = brush[ROOT].to_dict()
    reject('late field failure rolls back all positions', lambda: local.write_positions(definition,
           (Position('MENU', 999), CUSTOM[-1])))
    check('late failure preserves root', before == brush[ROOT].to_dict())
    local.reset_positions(definition)
    check('reset retains malformed dormant entries but reads defaults', local.read_positions(definition) == DEFAULTS)
    del record(brush)['positions'][record_key(CUSTOM[-1].location)]['sort_index']
    local.write_positions(definition, CUSTOM)
    record(brush)['positions_order'] = 7
    local.reset_positions(definition)
    check('reset repairs scalar order', local.read_positions(definition) == DEFAULTS)
    local.write_positions(definition, CUSTOM)
    for bad in ({'broken': True}, array('i', [1, 2])):
        record(brush)['positions_order'] = bad
        before = brush[ROOT].to_dict()
        reject('non-scalar order reset ' + type(bad).__name__, lambda: local.reset_positions(definition))
        check('failed reset preserves root ' + type(bad).__name__, brush[ROOT].to_dict() == before)
        del record(brush)['positions_order']
        local.write_positions(definition, CUSTOM)
    saved = record(brush)['positions'].to_dict()
    record(brush)['positions'] = 7
    reject('malformed top group read', lambda: local.read_positions(definition))
    reject('malformed top group reset', lambda: local.reset_positions(definition))
    del record(brush)['positions']
    record(brush)['positions'] = saved
    parent.write_positions(definition, ())
    linked_file = DIRECTORY / 'linked.blend'
    bpy.data.libraries.write(str(linked_file), {brush}, fake_user=True)
    with bpy.data.libraries.load(str(linked_file), link=True) as (_, target):
        target.brushes = [brush.name]
    linked = store(target.brushes[0])
    check('linked placement read', linked.read_positions(definition) == CUSTOM)
    reject('linked placement same write rejects', lambda: linked.write_positions(definition, CUSTOM))
    reject('linked placement reset rejects', lambda: linked.reset_positions(definition))
    bpy.ops.wm.save_as_mainfile(filepath=str(DIRECTORY / 'records.blend'))
    check('saved placement fixture')

(DIRECTORY / (phase + '-results.json')).write_text(json.dumps(dict(passed=True, checks=checks), indent=2) + '\n')
lifecycle.unregister()
print('PERSISTENT_POSITIONS_PASS', phase, len(checks), flush=True)
