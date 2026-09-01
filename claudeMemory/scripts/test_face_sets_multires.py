# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless test for the face-set (POLYGROUP) brush on a multires session.

Face sets are a Derived grid attribute, so the engine roster refuses the
grids-native path and the stroke runs mesh-path on the slot's derived `group`
column. The slot is lazy, and the operator's per-stroke group setup reads it
before stroke_begin would have materialized it -- binding a null Mesh* and
faulting inside the engine (fixed by convert.ensure_multires_slot here).

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_face_sets_multires.py
"""

import numpy as np
import bpy
from sculptcore_addon import convert, engine, handlers, stroke

bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []
def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg), flush=True)
    if not cond:
        failures.append(msg)

mgr = engine.manager()
brushes = mgr.get("sculptcore::brush::SculptBrushes").items
kernel = int(brushes['POLYGROUP'])

bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
ob.modifiers.new("Multires", 'MULTIRES')
for _ in range(3):
    bpy.ops.object.multires_subdivide(modifier="Multires")

session = convert.enter(ob)
check(session.multires_ptr is not None, "multires session entered")
check(session.mesh_ptr == 0, "slot is lazy at enter")
check(not stroke.grids_capable(session, kernel), "POLYGROUP is not grids-capable")

sc_brush = stroke._ensure_brush(session)
sc_brush.radius = 0.6
sc_brush.strength = 1.0
sc_brush.writeProps()

# What the modal operator's invoke does for a face-set brush.
convert.ensure_multires_slot(session)
check(session.mesh_ptr != 0, "slot materialized for the face-set brush")
mesh_obj = session.mesh()
mesh_obj.ensureFaceGroups()
gid = int(mesh_obj.newFaceGroupId())
check(gid != convert._default_face_set(ob.data), "new group id is not the default set")
sc_brush.activeGroup = gid
sc_brush.writeProps()

faces_num = convert.mesh_face_num(session.mesh_ptr)
before = np.zeros(faces_num, dtype=np.int32)
engine.capi().lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, before)

stroke.stroke_begin(session, grids_kernel=kernel)
check(not session.last_stroke_grids, "dispatched mesh-path, not grids")
stroke.apply_dab(session, kernel, (0.0, -0.4, 1.0), (0.0, 0.0, 1.0), 0.6)
stroke.stroke_end(session)

after = np.zeros(faces_num, dtype=np.int32)
engine.capi().lib.Mesh_readFaceIntAttr(session.mesh_ptr, convert._SC_GROUP, after)
painted = int((after == gid).sum())
check(painted > 0, "dab painted {:d} faces with the new group".format(painted))
check(painted < faces_num, "dab did not paint the whole mesh")

convert.flush(ob)
attr = ob.data.attributes.get(".sculpt_face_set")
check(attr is not None, "flush wrote .sculpt_face_set")

# A second face-set stroke on a session whose slot is already resident.
mesh_obj = session.mesh()
mesh_obj.ensureFaceGroups()
gid2 = int(mesh_obj.newFaceGroupId())
check(gid2 != gid, "second stroke got a fresh group id")

# session.mesh() on a slot-less multires session now raises instead of faulting.
saved, session.mesh_ptr, session.mesh_obj = session.mesh_ptr, 0, None
try:
    session.mesh()
    check(False, "slot-less session.mesh() raised")
except RuntimeError:
    check(True, "slot-less session.mesh() raised")
session.mesh_ptr = saved

convert.exit_(ob)
print("FAILURES: {:d}".format(len(failures)))
if failures:
    raise SystemExit(1)
print("test_face_sets_multires: all checks passed")
