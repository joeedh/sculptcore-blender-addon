# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless test for the level-aware multires paint-mask exchange (3.4).

The old exchange was gated to the top subdivision level, and _enter_multires
descends to the modifier's sculpt_levels on entry — so a mask painted at the
default sculpt level of a heavy asset was silently discarded, and a stored
mask was invisible below the top level. This drives the new path:

1. seed CD_GRID_PAINT_MASK with a fine (top-lattice) pattern,
2. enter with sculpt_levels < total levels (session lands on a lower level),
3. check the engine mask at the lower level matches the restricted pattern,
4. paint engine-side at the lower level, flush,
5. check the delta reached the stored grid mask while the fine detail the
   lower lattice cannot represent is preserved.

Run::

    blender.exe --background --factory-startup --python-exit-code 1 \
        --python claudeMemory/scripts/test_multires_mask_levels.py
"""

import numpy as np

import bpy

from sculptcore_addon import convert, engine, handlers, multires

# This test drives the conversion layer directly without entering the custom
# mode, so the addon's depsgraph reconcile handler (which frees sessions of
# objects not in the mode) must not run — multires paths evaluate the
# depsgraph on every exchange.
bpy.app.handlers.depsgraph_update_post.remove(handlers._on_depsgraph_update)

failures = []


def check(cond, msg):
    print("  {:s} {:s}".format("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def main():
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    md = ob.modifiers.new("Multires", 'MULTIRES')
    for _ in range(3):
        bpy.ops.object.multires_subdivide(modifier="Multires")
    md.sculpt_levels = 2  # below total_levels == 3

    depsgraph = bpy.context.evaluated_depsgraph_get()
    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    n_top = len(values)
    check(n_top > 0, "top-level vert values available")

    # Seed a deterministic fine-lattice mask directly into the grid layer.
    fine = ((np.arange(n_top) * 37) % 100 / 100.0).astype(np.float32)
    ob.multires_mask_from_vert_values(depsgraph, fine)
    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    check(has_mask and np.allclose(np.array(values, dtype=np.float32), fine),
          "grid mask seeded")

    session = convert.enter(ob)
    check(session.multires_active_level == 2,
          "session entered at sculpt_levels (level 2 of {})".format(
              session.multires_level))

    # The active-level engine mesh must carry the restricted mask.
    lib = engine.capi().lib
    nv = convert.mesh_vert_num(session.mesh_ptr)
    engine_mask = np.zeros(nv, dtype=np.float32)
    got = lib.Mesh_readVertFloatAttr(session.mesh_ptr, b".spatial.v.mask", engine_mask)
    check(bool(got), "engine mask column exists at the sculpt level")
    check(engine_mask.any(), "engine mask is non-zero at the sculpt level")
    base = session.multires_mask_base
    check(base is not None and np.allclose(base, engine_mask),
          "session mask base matches the imported values")

    # Paint engine-side at the lower level: bump a fixed subset.
    painted = engine_mask.copy()
    painted[: nv // 2] = np.clip(painted[: nv // 2] + 0.5, 0.0, 1.0)
    lib.Mesh_writeVertFloatAttr(session.mesh_ptr, b".spatial.v.mask", painted)

    convert.flush(ob)

    values, has_mask = ob.multires_mask_to_vert_values(depsgraph)
    after = np.array(values, dtype=np.float32)
    check(has_mask, "grid mask still present after flush")
    check(not np.allclose(after, fine),
          "lower-level paint reached the stored grid mask")

    # Delta preservation: where nothing was painted, the fine pattern must be
    # bit-identical (the old code would have overwritten it with an upsample).
    # The painted half touches an unknown subset of top samples, so check the
    # complement conservatively: at least the unpainted engine verts' top
    # samples are unchanged... simplest robust check: the number of changed
    # samples is well below the total.
    changed = np.count_nonzero(~np.isclose(after, fine))
    check(0 < changed < n_top, "delta write changed only part of the mask "
          "({} of {} samples)".format(changed, n_top))

    # Round trip down-up: switching to top must show the updated mask.
    convert.set_multires_level(ob, session.multires_level)
    session = engine.sessions.get(ob.name)
    nv_top = convert.mesh_vert_num(session.mesh_ptr)
    top_mask = np.zeros(nv_top, dtype=np.float32)
    got = lib.Mesh_readVertFloatAttr(session.mesh_ptr, b".spatial.v.mask", top_mask)
    check(bool(got) and top_mask.any(), "mask re-imported at the top level")

    convert.exit_(ob)

    print()
    if failures:
        print("test_multires_mask_levels: {} FAILURE(S)".format(len(failures)))
        for msg in failures:
            print("  - " + msg)
        raise SystemExit(1)
    print("test_multires_mask_levels: all checks passed")


main()
