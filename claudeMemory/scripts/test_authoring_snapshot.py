# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actual native rollback, bounds, ID links, opaque tokens and curve descriptors."""
import array
import json
from pathlib import Path
import threading
import bpy

checks = []


def check(label, condition):
    assert condition, label
    checks.append(label)


def rejects(label, call):
    try:
        call()
    except (ValueError, TypeError, PermissionError, ReferenceError):
        checks.append(label)
        return
    raise AssertionError(label)


b = bpy.data.brushes.new("Authoring Snapshot", mode='SCULPT')
c = bpy.data.brushes.new("Other Authoring Owner", mode='SCULPT')
b["foreign"] = dict(i=7, f=.5, text="keep", bytes=b'\xff\x00', items=[dict(x=1), dict(x=2)],
                    a=array.array('d', [1.25, 2.5]), ref=c)
b["number"] = 4
b.id_properties_ui("number").update(min=-10, max=20, description="unknown metadata", default=3)
users = c.users
token = b.authoring_edit_begin(undo=False)
check("snapshot does not increase referenced ID users", c.users == users)
b["foreign"]["i"] = 99
b["foreign"]["ref"] = None
b["number"] = 8
b.id_properties_ui("number").update(description="edited")
check("changed rollback reported", b.authoring_edit_cancel(token))
check("unknown nested values and references restored", b["foreign"]["i"] == 7 and b["foreign"]["ref"] == c)
check("reference counts balanced", c.users == users)
check("UI metadata restored", b.id_properties_ui("number").as_dict()['description'] == "unknown metadata")
check("unknown bytes and property arrays preserved", b["foreign"]["bytes"] == b'\xff\x00'
      and b["foreign"]["items"][1]["x"] == 2)
rejects("consumed token", lambda: b.authoring_edit_cancel(token))
token = b.authoring_edit_begin(undo=False)
rejects("cross-owner token", lambda: c.authoring_edit_cancel(token))
rejects("same-owner nested scope", lambda: b.authoring_edit_begin(undo=False))
check("no-op commit returns false", not b.authoring_edit_commit(token))
rejects("exact boolean required", lambda: b.authoring_edit_begin(undo=0))

token = b.authoring_edit_begin(native_settings=True, undo=False)
pair = (b.size, b.unprojected_size, b.use_locked_size)
strength = b.strength
key = b.authoring_native_curve_key('curve_strength')
b.size = b.size * 2
b.unprojected_size = .731
b.use_locked_size = 'SCENE'
b.strength = .75
b.use_pressure_strength = not b.use_pressure_strength
b.curve_strength.curves[0].points[0].location.y = .25
b.use_color_as_displacement = True
b.authoring_edit_cancel(token)
check("exact paired native sizes and mode restored", pair == (b.size, b.unprojected_size, b.use_locked_size))
check("native strength and curve restored",
      b.strength == strength and b.authoring_native_curve_key('curve_strength') == key)
check("excluded native flag preserved", b.use_color_as_displacement)
key = b.authoring_native_curve_key('curve_strength')
b.curve_strength.curves[0].points[0].select = True
check("curve key ignores UI selection", b.authoring_native_curve_key('curve_strength') == key)
b.curve_strength.use_clip = not b.curve_strength.use_clip
check("curve key includes clipping", b.authoring_native_curve_key('curve_strength') != key)
rejects("non-curve path", lambda: b.authoring_native_curve_key('strength'))
rejects("invalid curve path", lambda: b.authoring_native_curve_key('curve_strength\0'))

s = bpy.context.scene
ups = s.tool_settings.sculpt.unified_paint_settings
before = (ups.use_unified_size, ups.use_unified_strength, ups.use_unified_color, ups.use_locked_size)
token = s.authoring_edit_begin(native_settings=True, undo=False)
ups.use_unified_size = not before[0]
ups.use_unified_strength = not before[1]
ups.use_unified_color = not before[2]
ups.use_locked_size = 'SCENE' if before[3] == 'VIEW' else 'VIEW'
s.authoring_edit_cancel(token)
check("Scene legacy unified bits and locked mode restore", before == (
    ups.use_unified_size, ups.use_unified_strength, ups.use_unified_color, ups.use_locked_size))

thread_errors = []
def worker():
    try:
        b.authoring_edit_begin(undo=False)
    except PermissionError:
        thread_errors.append(True)
t = threading.Thread(target=worker)
t.start()
t.join()
check("worker thread rejected before owner access", thread_errors == [True])

token = b.authoring_edit_begin(undo=False)
b["number"] = 12
bpy.data.brushes.remove(c)
c = bpy.data.brushes.new("Other Authoring Owner", mode='SCULPT')
rejects("missing ID reference cannot redirect by name", lambda: b.authoring_edit_cancel(token))
check("failed restore preserves live tree", b["number"] == 12)
del token
b["foreign"]["ref"] = None
token = b.authoring_edit_begin(undo=False)
check("uncommitted token disposal permits a fresh scope", not b.authoring_edit_commit(token))

path = Path(__file__).resolve().parents[1] / 'tests/plan4-authoring-snapshot.checks.json'
path.write_text(json.dumps(checks, indent=2), encoding='utf-8')
print('AUTHORING_SNAPSHOT_OK', len(checks), flush=True)
